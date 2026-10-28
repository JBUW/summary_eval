import harness  # noqa: F401  (puts the repo root on sys.path)
import contextlib
import io
import json
from types import SimpleNamespace

from evalapp.console import Console
from evalapp.datasets import Dataset
from evalapp.endpoint_client import EndpointClient
from evalapp.generate import generate_hook
from evalapp.judge_call import judge_call
from evalapp.scoring import sweep
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


def _resolved(model_path, template_path, judges=None):
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
        "judges": judges or {},
        "defaults": {"metrics": None, "judges": None},
    }


def _dataset(name="ds", reference_field=None, entries=None, path="x.jsonl"):
    if entries is None:
        entries = [{"transcript": f"t{i}"} for i in range(3)]
    return Dataset(
        name=name,
        decl={
            "path": path,
            "transcript_field": "t",
            "reference_field": reference_field,
        },
        entries=entries,
    )


def _judge_entry(
    requires_reference=False,
    model_name="pin",
    system_content="sys",
    user_template="Transcript:\n{transcript}\n\n"
    "Summary under evaluation:\n{summary}",
    gen_params=None,
):
    return {
        "endpoint": "https://e/v1",
        "model_name": model_name,
        "api_key_env": None,
        "requires_reference": requires_reference,
        "gen_params": gen_params or {},
        "system_content": system_content,
        "user_template": user_template,
    }


def _commit_generation(store, transcript, index, dataset_name="ds"):
    """Seed the FK chain (transcript/model/template/generation) and return
    the generation sha for (transcript, the single summarizer)."""
    transcript_sha = store.upsert_transcript(transcript, dataset_name, None, index)
    model_sha = store.upsert_model(b"model-bytes", "m", "model.bin")
    template_sha = store.upsert_template("sys", "usr", "t")
    return (
        store.upsert_generation(
            transcript_sha, model_sha, {}, template_sha, {},
            f"gen:{transcript}",
        ),
        transcript_sha,
    )


def _seed_judge(store, entry, name="j"):
    return store.upsert_judge(
        entry["model_name"], entry["gen_params"], entry["system_content"],
        entry["user_template"], entry["requires_reference"], name,
        entry["endpoint"], entry["api_key_env"],
    )


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


class _FakeCycles:
    """Stands in for ServerCycles: no process, one fixed endpoint root."""

    def ensure(self, model, model_args):
        return SimpleNamespace(root="http://fake")

    def stop(self):
        pass

    def log_tail(self, count):
        return []


def _sweep_run(resolved, tmp_path, all_metrics, all_judges, datasets, selected,
               seed=None, fake=None):
    """Run sweep() end-to-end with a real Console on captured stdout."""
    store_path = str(tmp_path / "store.db")
    store = Store(store_path)
    if seed is not None:
        seed(store)
    store.close()
    fake = fake or _FakeTransport()
    client = EndpointClient(transport=fake)
    cycles = _FakeCycles()
    hook = generate_hook(
        resolved, datasets, selected, select_summarizers(resolved),
        client, cycles, print_plan=False,
    )
    console = Console()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = sweep(
            resolved, store_path, all_metrics, all_judges, datasets,
            selected, console, client, judge_call, generate=hook,
        )
    lines = [line for line in buffer.getvalue().splitlines() if line]
    return lines, *result, fake


def test_message_order(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path)
    resolved["defaults"]["metrics"] = [
        "faithfulness", "key_claim_completeness"
    ]
    fake = _FakeTransport()
    fake.enqueue(
        (200, _completion("fake text")),
        (200, _completion("fake text")),
        (200, _completion("fake text")),
    )
    lines, _scorers, _plan, _metrics_result, _judges_result, _fake = _sweep_run(
        resolved, tmp_path, None, None, {"ds": _dataset()},
        {"ds": [0, 1, 2]}, fake=fake,
    )
    assert lines == [
        "warn: metric 'key_claim_completeness' requires reference summaries; "
        "dataset 'ds' has none (pair skipped)",
        "plan(generate): 1 summarizer, 3 items, 1 server cycle",
        "plan(score): 2 metrics, 0 judges | 3 items | 3 to run, "
        "0 already scored | 1 infeasible",
        "done(generate): 3 committed, 0 skipped, 0 failed",
        "done(score): 3 committed, 0 dropped, 0 failed",
    ]


def test_cli_no_spawn_all_committed(tmp_path):
    harness.standard_workspace(tmp_path)
    harness.add_summarizer_section(str(tmp_path / "config.json"))
    harness.add_server_section(str(tmp_path / "config.json"))
    store = Store(str(tmp_path / "store.db"))
    model_sha = store.upsert_model(b"model-bytes", "m", "model.bin")
    template_sha = store.upsert_template("sys", "usr", "t")
    for name in ("named", "unnamed"):
        with open(tmp_path / f"{name}.jsonl", encoding="utf-8") as handle:
            entries = [json.loads(line) for line in handle if line]
        for index, entry in enumerate(entries):
            transcript_sha = store.upsert_transcript(
                entry["text"], name, entry.get("id"), index
            )
            store.upsert_generation(
                transcript_sha, model_sha, {}, template_sha, {},
                f"gen:{name}{index}",
            )
    store.close()
    result = harness.run_cli(["sweep"], cwd=tmp_path)
    result.assert_exit(0)
    assert result.lines == [
        "warn: metric 'key_claim_completeness' requires reference summaries; "
        "dataset 'named' has none (pair skipped)",
        "warn: metric 'key_claim_completeness' requires reference summaries; "
        "dataset 'unnamed' has none (pair skipped)",
        "plan(generate): 1 summarizer, 24 items, 1 server cycle",
        "plan(score): 5 metrics, 0 judges | 24 items | 96 to run, "
        "0 already scored | 2 infeasible",
        "note: all 24 items already committed; server not started",
        "done(generate): 0 committed, 24 skipped, 0 failed",
        "done(score): 36 committed, 0 dropped, 0 failed",
    ]


def test_infeasible_warn_and_note_before_plans(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path)
    resolved["defaults"]["metrics"] = ["key_claim_completeness"]
    fake = _FakeTransport()
    fake.enqueue(
        (200, _completion("fake text")),
        (200, _completion("fake text")),
        (200, _completion("fake text")),
    )
    lines, _scorers, _plan, _metrics_result, _judges_result, _fake = _sweep_run(
        resolved, tmp_path, None, None, {"ds": _dataset()},
        {"ds": [0, 1, 2]}, fake=fake,
    )
    assert lines == [
        "warn: metric 'key_claim_completeness' requires reference summaries; "
        "dataset 'ds' has none (pair skipped)",
        "note: no scorable pairs in scope; nothing scored",
        "plan(generate): 1 summarizer, 3 items, 1 server cycle",
        "plan(score): 1 metric, 0 judges | 3 items | 0 to run, "
        "0 already scored | 1 infeasible",
        "done(generate): 3 committed, 0 skipped, 0 failed",
        "done(score): 0 committed, 0 dropped, 0 failed",
    ]


def test_zero_scorers_generates_first(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path)
    resolved["defaults"]["metrics"] = []
    fake = _FakeTransport()
    fake.enqueue(
        (200, _completion("fake text")),
        (200, _completion("fake text")),
        (200, _completion("fake text")),
    )
    lines, _scorers, _plan, _metrics_result, _judges_result, _fake = _sweep_run(
        resolved, tmp_path, None, None, {"ds": _dataset()},
        {"ds": [0, 1, 2]}, fake=fake,
    )
    assert lines == [
        "plan(generate): 1 summarizer, 3 items, 1 server cycle",
        "plan(score): 0 metric(s), 0 judge(s) | 3 items | 0 to run, "
        "0 already scored | 0 infeasible",
        "done(generate): 3 committed, 0 skipped, 0 failed",
        "note: no metrics or judges selected; nothing scored",
        "done(score): 0 committed, 0 dropped, 0 failed",
    ]


def test_resume_counts(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path)
    resolved["defaults"]["metrics"] = ["faithfulness"]

    def seed(store):
        for index in range(3):
            generation_sha, _transcript_sha = _commit_generation(
                store, f"t{index}", index
            )
            store.upsert_metric_evaluation(
                "faithfulness", generation_sha, None, 0.0
            )

    lines, _scorers, _plan, _metrics_result, _judges_result, _fake = _sweep_run(
        resolved, tmp_path, None, None, {"ds": _dataset()},
        {"ds": [0, 1, 2]}, seed=seed,
    )
    assert lines == [
        "plan(generate): 1 summarizer, 3 items, 1 server cycle",
        "plan(score): 1 metric, 0 judges | 3 items | 0 to run, "
        "3 already scored | 0 infeasible",
        "note: all 3 items already committed; server not started",
        "done(generate): 0 committed, 3 skipped, 0 failed",
        "done(score): 0 committed, 0 dropped, 0 failed",
    ]


def test_credential_drop_preflight(tmp_path, monkeypatch):
    unset_var = "EVALAPP_SWEEP_TEST_UNSET_JUDGE_KEY"
    monkeypatch.delenv(unset_var, raising=False)
    model_path, template_path = _workspace(tmp_path)
    entry = _judge_entry()
    entry["api_key_env"] = unset_var
    resolved = _resolved(model_path, template_path, judges={"j": entry})
    resolved["defaults"]["metrics"] = ["faithfulness"]
    resolved["defaults"]["judges"] = ["j"]
    fake = _FakeTransport()
    fake.enqueue(
        (200, _completion("fake text")),
        (200, _completion("fake text")),
        (200, _completion("fake text")),
    )
    lines, scorers, _plan, _metrics_result, _judges_result, _fake = _sweep_run(
        resolved, tmp_path, None, None, {"ds": _dataset()},
        {"ds": [0, 1, 2]}, fake=fake,
    )
    assert scorers.judges == ()
    assert lines == [
        "warn: judge 'j': environment variable "
        "'EVALAPP_SWEEP_TEST_UNSET_JUDGE_KEY' is unset or empty (judge skipped)",
        "plan(generate): 1 summarizer, 3 items, 1 server cycle",
        "plan(score): 1 metric, 0 judges | 3 items | 3 to run, "
        "0 already scored | 0 infeasible",
        "done(generate): 3 committed, 0 skipped, 0 failed",
        "done(score): 3 committed, 0 dropped, 0 failed",
    ]
