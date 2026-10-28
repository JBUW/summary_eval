"""Ticket 08 slice 3 -- the --generate two-stage plan interleaving:
score() prints plan(generate) (via the store-free generate_plan_text
helper) before plan(score), the hook (built with print_plan=False) runs
after both plan lines and before any scoring phase, a stage-1 failure
propagates with both plan lines printed and no scoring, and the
print_plan kwarg default preserves 05c/05d run_generate behavior."""
import harness  # noqa: F401  (puts the repo root on sys.path)
import contextlib
import io
import json

import pytest

from evalapp.console import Console
from evalapp.datasets import Dataset
from evalapp.endpoint_client import EndpointClient
from evalapp.errors import FailFastAbort
from evalapp.generate import generate_hook, generate_plan_text, run_generate
from evalapp.judge_call import judge_call
from evalapp.scoring import Flag, score
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


def _workspace_one_model_two_templates(tmp_path):
    model_path = tmp_path / "model.bin"
    model_path.write_bytes(b"model-bytes")
    template_paths = {}
    for name in ("t1", "t2"):
        path = tmp_path / f"{name}.json"
        path.write_text(
            json.dumps({"system_content": f"sys-{name}", "user_template": f"usr-{name}"})
        )
        template_paths[name] = path
    return model_path, template_paths


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


def _resolved(model_path, template_path):
    return {
        "models": {"m": {"path": str(model_path)}},
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


def _resolved_shared_model(model_path, template_paths):
    """Two summarizers over the SAME model+args with different templates:
    they survive select_summarizers' surface dedup, and their server
    cycle count collapses to one."""
    return {
        "models": {"m": {"path": str(model_path)}},
        "prompt_templates": {
            name: str(path) for name, path in template_paths.items()
        },
        "summarizers": {
            "s1": {
                "model": "m",
                "model_args": {},
                "prompt_template": "t1",
                "gen_params": {},
            },
            "s2": {
                "model": "m",
                "model_args": {},
                "prompt_template": "t2",
                "gen_params": {},
            },
        },
        "judges": {},
        "defaults": {"metrics": None, "judges": None},
    }


def _resolved_two(model_paths, template_paths):
    return {
        "models": {
            name: {"path": str(path)} for name, path in model_paths.items()
        },
        "prompt_templates": {name: str(path) for name, path in template_paths.items()},
        "summarizers": {
            "s1": {"model": "m1", "model_args": {}, "prompt_template": "t1", "gen_params": {}},
            "s2": {"model": "m2", "model_args": {}, "prompt_template": "t2", "gen_params": {}},
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

    def log_tail(self, n=20):
        return []

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


def _run_score(resolved, tmp_path, metrics_flag, judges_flag, datasets, selected,
               generate=None):
    """Run score() end-to-end with a real Console on captured stdout."""
    store_path = str(tmp_path / "store.db")
    console = Console()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = score(
            resolved, store_path, metrics_flag, judges_flag, datasets,
            selected, (None, None, None), console,
            EndpointClient(transport=_FakeTransport()), judge_call,
            generate=generate,
        )
    lines = [line for line in buffer.getvalue().splitlines() if line]
    return lines, store_path, *result


def test_generate_plan_text_helper(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path)
    datasets = {"ds": _dataset()}
    summarizers = select_summarizers(resolved)
    assert generate_plan_text(datasets, {"ds": [0]}, summarizers) == (
        "1 summarizer, 1 item, 1 server cycle"
    )
    assert generate_plan_text(datasets, {"ds": [0, 1, 2]}, summarizers) == (
        "1 summarizer, 3 items, 1 server cycle"
    )

    model_path2, template_paths = _workspace_one_model_two_templates(tmp_path)
    shared = _resolved_shared_model(model_path2, template_paths)
    shared_summarizers = select_summarizers(shared)
    assert generate_plan_text(datasets, {"ds": [0, 1, 2]}, shared_summarizers) == (
        "2 summarizers, 6 items, 1 server cycle"
    )

    model_paths, template_paths = _workspace_two(tmp_path)
    two = _resolved_two(model_paths, template_paths)
    two_summarizers = select_summarizers(two)
    assert generate_plan_text(datasets, {"ds": [0, 1, 2]}, two_summarizers) == (
        "2 summarizers, 6 items, 2 server cycles"
    )


def test_plan_interleaving_hook_in_between(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path)
    datasets = {"ds": _dataset()}
    selected = {"ds": [0, 1, 2]}
    fake = _FakeTransport()
    fake.enqueue(*[(200, _completion(f"g{i}")) for i in range(3)])
    hook = generate_hook(
        resolved, datasets, selected, select_summarizers(resolved),
        _client(fake), _FakeCycles(), print_plan=False,
    )

    lines, store_path, _scorers, plan, _metrics_result, _judges_result = _run_score(
        resolved, tmp_path, Flag(value=["faithfulness"]), Flag(no=True),
        datasets, selected, generate=hook,
    )

    assert lines == [
        "plan(generate): 1 summarizer, 3 items, 1 server cycle",
        "plan(score): 1 metric, 0 judges | 3 items | "
        "3 to run, 0 already scored | 0 infeasible",
        "done(generate): 3 committed, 0 skipped, 0 failed",
        "done(score): 3 committed, 0 dropped, 0 failed",
    ]
    assert sum(line.startswith("plan(generate)") for line in lines) == 1
    assert plan.items == 3
    assert len(fake.requests) == 3
    store = Store(store_path)
    try:
        counts = dict(store.table_counts())
    finally:
        store.close()
    assert counts["generations"] == 3
    assert counts["metric_evaluations"] == 3


def test_stage1_fail_fast_prints_plans_no_scoring(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path)
    datasets = {"ds": _dataset()}
    selected = {"ds": [0, 1, 2]}

    def boom(_store, _console):
        raise FailFastAbort()

    store_path = str(tmp_path / "store.db")
    console = Console()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        with pytest.raises(FailFastAbort):
            score(
                resolved, store_path, Flag(value=["faithfulness"]),
                Flag(no=True), datasets, selected, (None, None, None), console,
                EndpointClient(transport=_FakeTransport()), judge_call,
                generate=boom,
            )
    lines = [line for line in buffer.getvalue().splitlines() if line]
    assert lines == [
        "plan(generate): 1 summarizer, 3 items, 1 server cycle",
        "plan(score): 1 metric, 0 judges | 3 items | "
        "3 to run, 0 already scored | 0 infeasible",
    ]
    store = Store(store_path)
    try:
        counts = dict(store.table_counts())
    finally:
        store.close()
    assert counts["generations"] == 0
    assert counts["metric_evaluations"] == 0


def test_print_plan_kwarg_preserves_default(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path)
    datasets = {"ds": _dataset()}
    selected = {"ds": [0, 1, 2]}
    summarizers = select_summarizers(resolved)

    for tag, kwargs in (("default", {}), ("true", {"print_plan": True})):
        fake = _FakeTransport()
        fake.enqueue(*[(200, _completion(f"g{i}")) for i in range(3)])
        store = Store(str(tmp_path / f"store-{tag}.db"))
        console = _CapturingConsole()
        run_generate(
            store, console, resolved, datasets, selected, summarizers,
            _client(fake), _FakeCycles(), **kwargs,
        )
        store.close()
        assert console.lines == [
            "plan(generate): 1 summarizer, 3 items, 1 server cycle",
            "done(generate): 3 committed, 0 skipped, 0 failed",
        ]

    fake = _FakeTransport()
    fake.enqueue(*[(200, _completion(f"g{i}")) for i in range(3)])
    store = Store(str(tmp_path / "store-false.db"))
    console = _CapturingConsole()
    run_generate(
        store, console, resolved, datasets, selected, summarizers,
        _client(fake), _FakeCycles(), print_plan=False,
    )
    store.close()
    assert console.lines == ["done(generate): 3 committed, 0 skipped, 0 failed"]
