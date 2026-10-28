"""Ticket 05c — the generate command happy path: scope expansion,
deterministic item order, pre-scan skip, and per-item atomic commit,
through the fake endpoint client (05a). No real server, no network."""
import json

import harness  # noqa: F401  (puts the repo root on sys.path)

from evalapp.console import Console
from evalapp.datasets import Dataset
from evalapp.endpoint_client import EndpointClient
from evalapp.errors import RuntimeFailure
from evalapp.generate import generate_hook, run_generate
from evalapp.identities import generation_id, model_id, template_id, transcript_id
from evalapp.store import Store
from evalapp.summarizers import select_summarizers


def _workspace(tmp_path):
    model_path = tmp_path / "model.bin"
    model_path.write_bytes(b"model-bytes")
    template_path = tmp_path / "template.json"
    template_path.write_text(
        json.dumps({"system_content": "sys", "user_template": "usr"})
    )
    return model_path, template_path


def _resolved(model_path, template_path):
    return {
        "models": {
            "m": {"path": str(model_path), "model_args": {}, "gen_params": {}}
        },
        "prompt_templates": {"t": str(template_path)},
        "summarizers": {
            "s": {
                "model": "m",
                "model_args": {},
                "prompt_template": "t",
                "gen_params": {},
            }
        },
        "judges": {},
        "defaults": {"metrics": None, "judges": None},
    }


def _dataset():
    return Dataset(
        name="ds",
        decl={
            "path": "x.jsonl",
            "transcript_field": "t",
            "reference_field": None,
        },
        entries=[{"transcript": f"t{i}"} for i in range(3)],
    )


def _workspace_two(tmp_path):
    model_paths = {}
    for name in ("m1", "m2"):
        path = tmp_path / f"{name}.bin"
        path.write_bytes(f"model-bytes-{name}".encode("utf-8"))
        model_paths[name] = path
    template_paths = {}
    for name in ("t1", "t2"):
        path = tmp_path / f"{name}.json"
        path.write_text(
            json.dumps({"system_content": f"sys-{name}", "user_template": f"usr-{name}"})
        )
        template_paths[name] = path
    return model_paths, template_paths


def _resolved_two(model_paths, template_paths):
    return {
        "models": {
            name: {"path": str(path), "model_args": {}, "gen_params": {}}
            for name, path in model_paths.items()
        },
        "prompt_templates": {name: str(path) for name, path in template_paths.items()},
        "summarizers": {
            "s1": {"model": "m1", "model_args": {}, "prompt_template": "t1", "gen_params": {}},
            "s2": {"model": "m2", "model_args": {}, "prompt_template": "t2", "gen_params": {}},
        },
        "judges": {},
        "defaults": {"metrics": None, "judges": None},
    }


def _commit_generation(store, transcript, index):
    """Seed the FK chain (transcript/model/template/generation) and return
    the generation sha for (transcript, the single summarizer)."""
    transcript_sha = store.upsert_transcript(transcript, "ds", None, index)
    model_sha = store.upsert_model(b"model-bytes", "m", "model.bin")
    template_sha = store.upsert_template("sys", "usr", "t")
    return (
        store.upsert_generation(
            transcript_sha, model_sha, {}, template_sha, {},
            f"gen:{transcript}",
        ),
        transcript_sha,
    )


class _CapturingConsole(Console):
    def __init__(self):
        super().__init__()
        self.lines = []

    def _emit(self, line, stage):
        self.lines.append(line)
        super()._emit(line, stage)


class _FakeServer:
    root = "http://fake"


class _FakeCycles:
    def __init__(self):
        self.ensured = []
        self.stops = 0

    def ensure(self, model, model_args):
        self.ensured.append((model, model_args))
        return _FakeServer()

    def stop(self):
        self.stops += 1


class _FakeTransport:
    """Records every request; replays queued outcomes in order."""

    def __init__(self):
        self.requests = []
        self._outcomes = []

    def enqueue(self, *outcomes):
        self._outcomes.extend(outcomes)

    def request(self, method, url, headers, body, timeout):
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers or {}),
                "body": body,
                "timeout": timeout,
            }
        )
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _completion(text):
    return json.dumps({"choices": [{"message": {"content": text}}]})


def _client(fake):
    return EndpointClient(transport=fake)


def test_full_scope_deterministic_order(tmp_path):
    model_paths, template_paths = _workspace_two(tmp_path)
    resolved = _resolved_two(model_paths, template_paths)
    datasets = {"ds": _dataset()}
    selected = {"ds": [0, 1, 2]}
    summarizers = select_summarizers(resolved)
    fake = _FakeTransport()
    fake.enqueue(*[(200, _completion(f"g{i}")) for i in range(6)])
    console = _CapturingConsole()
    cycles = _FakeCycles()
    store = Store(str(tmp_path / "store.db"))
    run_generate(store, console, resolved, datasets, selected, summarizers, _client(fake), cycles)

    assert [req["url"] for req in fake.requests] == ["http://fake/chat/completions"] * 6
    bodies = [json.loads(req["body"]) for req in fake.requests]
    expected = (
        [("m1", "t1", i) for i in range(3)] + [("m2", "t2", i) for i in range(3)]
    )
    for body, (model, template, index) in zip(bodies, expected):
        assert body["model"] == model
        assert body["messages"] == [
            {"role": "system", "content": f"sys-{template}"},
            {"role": "user", "content": f"usr-{template}t{index}"},
        ]
    assert all(
        req["headers"] == {"Content-Type": "application/json"} for req in fake.requests
    )
    assert cycles.ensured == [("m1", {})] * 3 + [("m2", {})] * 3
    assert cycles.stops == 1
    assert console.lines == [
        "plan(generate): 2 summarizers, 6 items, 2 server cycles",
        "done(generate): 6 committed, 0 skipped, 0 failed",
    ]


def test_cartesian_product_plus_named_add(tmp_path):
    model_paths, template_paths = _workspace_two(tmp_path)
    resolved = _resolved_two(model_paths, template_paths)
    resolved["models"]["m1"]["model_args"] = {"a": 1}
    resolved["models"]["m2"]["gen_params"] = {"temperature": 0.5}
    datasets = {"ds": Dataset(
        name="ds",
        decl={"path": "x.jsonl", "transcript_field": "t", "reference_field": None},
        entries=[{"transcript": f"t{i}"} for i in range(2)],
    )}
    selected = {"ds": [0, 1]}
    summarizers = select_summarizers(
        resolved,
        summarizer_names=("s1",),
        model_names=("m1", "m2"),
        template_names=("t1",),
    )
    assert [s.model for s in summarizers] == ["m1", "m2", "m1"]
    assert [s.name for s in summarizers] == [None, None, "s1"]

    fake = _FakeTransport()
    fake.enqueue(*[(200, _completion(f"g{i}")) for i in range(6)])
    console = _CapturingConsole()
    cycles = _FakeCycles()
    store = Store(str(tmp_path / "store.db"))
    run_generate(store, console, resolved, datasets, selected, summarizers, _client(fake), cycles)

    bodies = [json.loads(req["body"]) for req in fake.requests]
    expected = (
        [("m1", i) for i in range(2)]
        + [("m2", i) for i in range(2)]
        + [("m1", i) for i in range(2)]
    )
    for body, (model, index) in zip(bodies, expected):
        assert body["model"] == model
        assert body["messages"][-1] == {
            "role": "user",
            "content": f"usr-t1t{index}",
        }
    assert "temperature" not in bodies[0]
    assert bodies[2]["temperature"] == 0.5
    assert console.lines == [
        "plan(generate): 3 summarizers, 6 items, 3 server cycles",
        "done(generate): 6 committed, 0 skipped, 0 failed",
    ]


def test_empty_system_template_omits_system_message(tmp_path):
    model_path = tmp_path / "model.bin"
    model_path.write_bytes(b"model-bytes")
    template_path = tmp_path / "template.json"
    template_path.write_text(json.dumps({"user_template": "usr"}))
    resolved = _resolved(model_path, template_path)
    datasets = {"ds": _dataset()}
    selected = {"ds": [0]}
    fake = _FakeTransport()
    fake.enqueue((200, _completion("g0")))
    console = _CapturingConsole()
    cycles = _FakeCycles()
    store = Store(str(tmp_path / "store.db"))
    run_generate(
        store, console, resolved, datasets, selected,
        select_summarizers(resolved), _client(fake), cycles,
    )
    body = json.loads(fake.requests[0]["body"])
    assert body["messages"] == [{"role": "user", "content": "usrt0"}]


def test_generate_hook_wraps_run_generate(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path)
    datasets = {"ds": _dataset()}
    selected = {"ds": [0, 1, 2]}
    fake = _FakeTransport()
    fake.enqueue(*[(200, _completion(f"g{i}")) for i in range(3)])
    hook = generate_hook(
        resolved, datasets, selected, select_summarizers(resolved), _client(fake),
        _FakeCycles(),
    )
    console = _CapturingConsole()
    store = Store(str(tmp_path / "store.db"))
    hook(store, console)
    assert len(fake.requests) == 3
    assert console.lines == [
        "plan(generate): 1 summarizer, 3 items, 1 server cycle",
        "done(generate): 3 committed, 0 skipped, 0 failed",
    ]


def test_prescan_skips_committed_item(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path)
    datasets = {"ds": _dataset()}
    selected = {"ds": [0, 1, 2]}
    store = Store(str(tmp_path / "store.db"))
    _commit_generation(store, "t0", 0)
    fake = _FakeTransport()
    fake.enqueue((200, _completion("g1")), (200, _completion("g2")))
    console = _CapturingConsole()
    cycles = _FakeCycles()
    run_generate(
        store, console, resolved, datasets, selected,
        select_summarizers(resolved), _client(fake), cycles,
    )
    assert [
        json.loads(req["body"])["messages"][-1]["content"] for req in fake.requests
    ] == ["usrt1", "usrt2"]
    assert cycles.ensured == [("m", {})] * 2
    assert cycles.stops == 1
    assert console.lines == [
        "plan(generate): 1 summarizer, 3 items, 1 server cycle",
        "done(generate): 2 committed, 1 skipped, 0 failed",
    ]
    store.close()


def test_all_committed_never_starts_server(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path)
    datasets = {"ds": _dataset()}
    selected = {"ds": [0, 1, 2]}
    store = Store(str(tmp_path / "store.db"))
    for index in range(3):
        _commit_generation(store, f"t{index}", index)
    fake = _FakeTransport()
    console = _CapturingConsole()
    cycles = _FakeCycles()
    run_generate(
        store, console, resolved, datasets, selected,
        select_summarizers(resolved), _client(fake), cycles,
    )
    assert fake.requests == []
    assert cycles.ensured == []
    assert cycles.stops == 0
    assert console.lines == [
        "plan(generate): 1 summarizer, 3 items, 1 server cycle",
        "note: all 3 items already committed; server not started",
        "done(generate): 0 committed, 3 skipped, 0 failed",
    ]
    store.close()


def test_zero_items_plan_and_done_only(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path)
    datasets = {"ds": _dataset()}
    selected = {"ds": []}
    fake = _FakeTransport()
    console = _CapturingConsole()
    cycles = _FakeCycles()
    store = Store(str(tmp_path / "store.db"))
    run_generate(
        store, console, resolved, datasets, selected,
        select_summarizers(resolved), _client(fake), cycles,
    )
    assert fake.requests == []
    assert cycles.ensured == []
    assert cycles.stops == 0
    assert console.lines == [
        "plan(generate): 1 summarizer, 0 items, 1 server cycle",
        "done(generate): 0 committed, 0 skipped, 0 failed",
    ]
    store.close()
