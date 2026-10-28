"""Ticket 05d — the failure and recovery half of generate: the fail-fast
block (error line + raw server-log tail + resume note), the FailFastAbort
abort, SpecError passthrough, and complete-or-absent through the real
failure path. No real server (that is the integration slice)."""
import json

import pytest

import harness  # noqa: F401  (puts the repo root on sys.path)

from evalapp.console import Console
from evalapp.datasets import Dataset
from evalapp.endpoint_client import EndpointClient, EndpointError, RequestTimeout
from evalapp.errors import FailFastAbort, RuntimeFailure, SpecError
from evalapp.generate import run_generate
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
    def __init__(self, tail=(), ensure_raises=None):
        self.ensured = []
        self.stops = 0
        self._tail = list(tail)
        self._ensure_raises = ensure_raises

    def ensure(self, model, model_args):
        self.ensured.append((model, model_args))
        if self._ensure_raises is not None:
            raise self._ensure_raises
        return _FakeServer()

    def log_tail(self, n=20):
        return self._tail[-n:]

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


FAILURE_CASES = [
    ([(500, "boom")], "HTTP 500 from model server"),
    ([(200, "{}")], "empty completion from model server"),
    ([RequestTimeout(300.0)], "timeout after 300.0s from model server"),
    (
        [EndpointError("connection failed: refused")],
        "connection failed: refused from model server",
    ),
]


@pytest.mark.parametrize("outcomes, detail", FAILURE_CASES)
def test_failure_block_lines_and_stop(tmp_path, outcomes, detail):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path)
    datasets = {"ds": _dataset()}
    selected = {"ds": [0]}
    fake = _FakeTransport()
    fake.enqueue(*outcomes)
    console = _CapturingConsole()
    cycles = _FakeCycles()
    store = Store(str(tmp_path / "store.db"))
    with pytest.raises(FailFastAbort):
        run_generate(
            store, console, resolved, datasets, selected,
            select_summarizers(resolved), _client(fake), cycles,
        )
    assert console.lines == [
        "plan(generate): 1 summarizer, 1 item, 1 server cycle",
        f"error: item ds#0 (summarizer 's'): {detail}",
        "note: re-run to resume; 0 items already committed",
    ]
    assert cycles.stops == 1
    assert dict(store.table_counts())["generations"] == 0
    store.close()


def test_ensure_runtime_failure_verbatim(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path)
    datasets = {"ds": _dataset()}
    selected = {"ds": [0]}
    fake = _FakeTransport()
    console = _CapturingConsole()
    cycles = _FakeCycles(
        ensure_raises=RuntimeFailure(
            "model server exited during startup (exit code 3)"
        )
    )
    store = Store(str(tmp_path / "store.db"))
    with pytest.raises(FailFastAbort):
        run_generate(
            store, console, resolved, datasets, selected,
            select_summarizers(resolved), _client(fake), cycles,
        )
    assert console.lines == [
        "plan(generate): 1 summarizer, 1 item, 1 server cycle",
        "error: item ds#0 (summarizer 's'): "
        "model server exited during startup (exit code 3)",
        "note: re-run to resume; 0 items already committed",
    ]
    assert cycles.stops == 1
    store.close()


def test_unnamed_cartesian_summarizer(tmp_path):
    model_paths, template_paths = _workspace_two(tmp_path)
    resolved = _resolved_two(model_paths, template_paths)
    datasets = {"ds": _dataset()}
    selected = {"ds": [0]}
    summarizers = select_summarizers(resolved, None, ("m1",), ("t1",))
    assert summarizers[0].name is None
    fake = _FakeTransport()
    fake.enqueue((500, "boom"))
    console = _CapturingConsole()
    cycles = _FakeCycles()
    store = Store(str(tmp_path / "store.db"))
    with pytest.raises(FailFastAbort):
        run_generate(
            store, console, resolved, datasets, selected,
            summarizers, _client(fake), cycles,
        )
    assert console.lines == [
        "plan(generate): 1 summarizer, 1 item, 1 server cycle",
        "error: item ds#0 (summarizer 'unnamed'): HTTP 500 from model server",
        "note: re-run to resume; 0 items already committed",
    ]
    assert cycles.stops == 1
    store.close()


def test_resume_note_counts_skipped_plus_committed(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path)
    datasets = {"ds": _dataset()}
    selected = {"ds": [0, 1, 2]}
    store = Store(str(tmp_path / "store.db"))
    _commit_generation(store, "t0", 0)
    fake = _FakeTransport()
    fake.enqueue((200, _completion("g1")), (500, "boom"))
    console = _CapturingConsole()
    cycles = _FakeCycles()
    with pytest.raises(FailFastAbort):
        run_generate(
            store, console, resolved, datasets, selected,
            select_summarizers(resolved), _client(fake), cycles,
        )
    assert console.lines[-1] == "note: re-run to resume; 2 items already committed"
    assert cycles.stops == 1
    store.close()


def test_resume_note_singular_immediate_failure(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path)
    datasets = {"ds": _dataset()}
    selected = {"ds": [0, 1]}
    store = Store(str(tmp_path / "store.db"))
    _commit_generation(store, "t0", 0)
    fake = _FakeTransport()
    fake.enqueue((500, "boom"))
    console = _CapturingConsole()
    cycles = _FakeCycles()
    with pytest.raises(FailFastAbort):
        run_generate(
            store, console, resolved, datasets, selected,
            select_summarizers(resolved), _client(fake), cycles,
        )
    assert console.lines[-1] == "note: re-run to resume; 1 item already committed"
    assert cycles.stops == 1
    store.close()


def test_raw_log_tail_between_error_and_note(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path)
    datasets = {"ds": _dataset()}
    selected = {"ds": [0]}
    fake = _FakeTransport()
    fake.enqueue((500, "boom"))
    console = _CapturingConsole()
    cycles = _FakeCycles(tail=("line one", "line two"))
    store = Store(str(tmp_path / "store.db"))
    with pytest.raises(FailFastAbort):
        run_generate(
            store, console, resolved, datasets, selected,
            select_summarizers(resolved), _client(fake), cycles,
        )
    assert console.lines == [
        "plan(generate): 1 summarizer, 1 item, 1 server cycle",
        "error: item ds#0 (summarizer 's'): HTTP 500 from model server",
        "line one",
        "line two",
        "note: re-run to resume; 0 items already committed",
    ]
    assert cycles.stops == 1
    store.close()


def test_spec_error_passthrough(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path)
    datasets = {"ds": _dataset()}
    selected = {"ds": [0]}
    fake = _FakeTransport()
    console = _CapturingConsole()
    cycles = _FakeCycles(
        ensure_raises=SpecError(
            "port 1234 already bound "
            "(a previous model server may still be running)"
        )
    )
    store = Store(str(tmp_path / "store.db"))
    with pytest.raises(SpecError):
        run_generate(
            store, console, resolved, datasets, selected,
            select_summarizers(resolved), _client(fake), cycles,
        )
    assert console.lines == ["plan(generate): 1 summarizer, 1 item, 1 server cycle"]
    assert cycles.stops == 1
    assert dict(store.table_counts())["generations"] == 0
    store.close()


def test_failure_path_complete_or_absent(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path)
    datasets = {"ds": _dataset()}
    selected = {"ds": [0, 1]}
    fake = _FakeTransport()
    fake.enqueue((200, _completion("g0")), (500, "boom"))
    console = _CapturingConsole()
    cycles = _FakeCycles()
    store = Store(str(tmp_path / "store.db"))
    with pytest.raises(FailFastAbort):
        run_generate(
            store, console, resolved, datasets, selected,
            select_summarizers(resolved), _client(fake), cycles,
        )
    model_sha = model_id(b"model-bytes")
    template_sha = template_id("sys", "usr")
    committed_sha = generation_id(
        transcript_id("t0"), model_sha, {}, template_sha, {}
    )
    failed_sha = generation_id(
        transcript_id("t1"), model_sha, {}, template_sha, {}
    )
    assert store.get_generation(committed_sha) == "g0"
    assert store.get_generation(failed_sha) is None
    assert dict(store.table_counts()) == {
        "transcripts": 1,
        "reference_summaries": 0,
        "models": 1,
        "prompt_templates": 1,
        "generations": 1,
        "judges": 0,
        "judge_evaluations": 0,
        "metric_evaluations": 0,
    }
    assert cycles.stops == 1
    store.close()
