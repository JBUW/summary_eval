import harness  # noqa: F401  (puts the repo root on sys.path)
import contextlib
import io
import json

from evalapp.console import Console
from evalapp.datasets import Dataset
from evalapp.endpoint_client import EndpointClient
from evalapp.judge_call import judge_call
from evalapp.scoring import Flag, score
from evalapp.store import Store


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


def _score(resolved, tmp_path, metrics_flag, judges_flag, datasets, selected,
           seed=None, fake=None):
    """Run score() end-to-end with a real Console on captured stdout."""
    store_path = str(tmp_path / "store.db")
    store = Store(store_path)
    if seed is not None:
        seed(store)
    store.close()
    fake = fake or _FakeTransport()
    console = Console()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = score(
            resolved, store_path, metrics_flag, judges_flag, datasets,
            selected, (None, None, None), console,
            EndpointClient(transport=fake), judge_call,
        )
    lines = [line for line in buffer.getvalue().splitlines() if line]
    return lines, *result, fake


def test_metrics_only_docs_format(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path)
    seeded = {}

    def seed(store):
        for index in range(3):
            seeded[index] = _commit_generation(store, f"t{index}", index)

    lines, _scorers, plan, _metrics_result, _judges_result, _fake = _score(
        resolved, tmp_path,
        Flag(value=["faithfulness", "conciseness_length_proxy",
                    "structural_instruction_check"]),
        Flag(),
        {"ds": _dataset()}, {"ds": [0, 1, 2]}, seed=seed,
    )

    assert lines == [
        "plan(score): 3 metrics, 0 judges | 3 items | "
        "9 to run, 0 already scored | 0 infeasible",
        "done(score): 9 committed, 0 dropped, 0 failed",
    ]
    assert plan.items == 3
    assert plan.to_run == 9
    store = Store(str(tmp_path / "store.db"))
    try:
        for index in range(3):
            generation_sha, _transcript_sha = seeded[index]
            for name in ("faithfulness", "conciseness_length_proxy",
                         "structural_instruction_check"):
                assert store.has_metric_evaluation(name, generation_sha)
    finally:
        store.close()


def test_judges_only(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path,
                         judges={"j": _judge_entry()})

    def seed(store):
        for index in range(3):
            _commit_generation(store, f"t{index}", index)
        _seed_judge(store, _judge_entry())

    fake = _FakeTransport()
    outcome = (
        200,
        _completion("factual_correctness: 1.0\ncompleteness: 0.5\n"
                    "conciseness: 0.25"),
    )
    fake.enqueue(outcome, outcome, outcome)

    lines, _scorers, _plan, _metrics_result, _judges_result, fake = _score(
        resolved, tmp_path, Flag(no=True), Flag(value=["j"]),
        {"ds": _dataset()}, {"ds": [0, 1, 2]}, seed=seed, fake=fake,
    )

    assert lines == [
        "plan(score): 0 metrics, 1 judge | 3 items | "
        "3 to run, 0 already scored | 0 infeasible",
        "done(score): 3 committed, 0 dropped, 0 failed",
    ]
    assert len(fake.requests) == 3


def test_bare_judges_singular_item(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(
        model_path, template_path,
        judges={
            "j1": _judge_entry(model_name="pin-1"),
            "j2": _judge_entry(model_name="pin-2"),
        },
    )

    def seed(store):
        _commit_generation(store, "t0", 0)
        _seed_judge(store, _judge_entry(model_name="pin-1"), name="j1")
        _seed_judge(store, _judge_entry(model_name="pin-2"), name="j2")

    fake = _FakeTransport()
    outcome = (
        200,
        _completion("factual_correctness: 1.0\ncompleteness: 0.5\n"
                    "conciseness: 0.25"),
    )
    fake.enqueue(outcome, outcome)

    lines, _scorers, _plan, _metrics_result, _judges_result, fake = _score(
        resolved, tmp_path, Flag(no=True), Flag(value="bare"),
        {"ds": _dataset()}, {"ds": [0]}, seed=seed, fake=fake,
    )

    assert lines == [
        "plan(score): 0 metrics, 2 judges | 1 item | "
        "2 to run, 0 already scored | 0 infeasible",
        "done(score): 2 committed, 0 dropped, 0 failed",
    ]
    assert len(fake.requests) == 2


def test_zero_scorers(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path)

    def seed(store):
        for index in range(3):
            _commit_generation(store, f"t{index}", index)

    lines, _scorers, _plan, _metrics_result, _judges_result, _fake = _score(
        resolved, tmp_path, Flag(no=True), Flag(no=True),
        {"ds": _dataset()}, {"ds": [0, 1, 2]}, seed=seed,
    )

    assert lines == [
        "plan(score): 0 metric(s), 0 judge(s) | 3 items | "
        "0 to run, 0 already scored | 0 infeasible",
        "note: no metrics or judges selected; nothing scored",
        "done(score): 0 committed, 0 dropped, 0 failed",
    ]


def test_all_missing_generations_note(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path)

    lines, _scorers, _plan, _metrics_result, _judges_result, _fake = _score(
        resolved, tmp_path, Flag(value=["faithfulness"]), Flag(no=True),
        {"ds": _dataset()}, {"ds": [0, 1, 2]},
    )

    assert lines == [
        "plan(score): 1 metric, 0 judges | 3 items | "
        "3 to run, 0 already scored | 0 infeasible",
        "note: no committed generations in scope; run 'generate' first",
        "done(score): 0 committed, 0 dropped, 0 failed",
    ]


def test_partial_missing_generations_note(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path)

    def seed(store):
        _commit_generation(store, "t0", 0)

    lines, _scorers, _plan, _metrics_result, _judges_result, _fake = _score(
        resolved, tmp_path, Flag(value=["faithfulness"]), Flag(no=True),
        {"ds": _dataset()}, {"ds": [0, 1, 2]}, seed=seed,
    )

    assert lines == [
        "plan(score): 1 metric, 0 judges | 3 items | "
        "3 to run, 0 already scored | 0 infeasible",
        "note: 2 selected items have no committed generation; "
        "run 'generate' first",
        "done(score): 1 committed, 0 dropped, 0 failed",
    ]


def test_no_scorable_pairs_selection_scoped(tmp_path):
    ref_path = tmp_path / "ds_ref.jsonl"
    ref_path.write_text(
        json.dumps({"transcript": "r0", "r": "ref-0"}) + "\n"
        + json.dumps({"transcript": "r1", "r": "ref-1"}) + "\n"
    )
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path)
    ds_plain = _dataset(
        name="ds_plain",
        entries=[{"transcript": f"t{i}"} for i in range(2)],
    )
    ds_ref = _dataset(
        name="ds_ref", reference_field="r",
        entries=[
            {"transcript": "r0", "r": "ref-0"},
            {"transcript": "r1", "r": "ref-1"},
        ],
        path=str(ref_path),
    )

    def seed(store):
        _commit_generation(store, "t0", 0, dataset_name="ds_plain")
        _commit_generation(store, "t1", 1, dataset_name="ds_plain")

    lines, _scorers, _plan, _metrics_result, _judges_result, _fake = _score(
        resolved, tmp_path,
        Flag(value=["key_claim_completeness"]), Flag(no=True),
        {"ds_plain": ds_plain, "ds_ref": ds_ref},
        {"ds_plain": [0, 1], "ds_ref": []},
        seed=seed,
    )

    assert lines == [
        "warn: metric 'key_claim_completeness' requires reference "
        "summaries; dataset 'ds_plain' has none (pair skipped)",
        "note: no scorable pairs in scope; nothing scored",
        "plan(score): 1 metric, 0 judges | 2 items | "
        "0 to run, 0 already scored | 1 infeasible",
        "done(score): 0 committed, 0 dropped, 0 failed",
    ]


def test_mid_run_reference_warn_after_plan(tmp_path):
    ref_path = tmp_path / "ref.jsonl"
    ref_path.write_text(json.dumps({"transcript": "t0", "r": ""}) + "\n")
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path)
    dataset = _dataset(
        reference_field="r", entries=[{"transcript": "t0"}], path=str(ref_path),
    )

    def seed(store):
        _commit_generation(store, "t0", 0)

    lines, _scorers, _plan, _metrics_result, _judges_result, _fake = _score(
        resolved, tmp_path,
        Flag(value=["key_claim_completeness"]), Flag(no=True),
        {"ds": dataset}, {"ds": [0]}, seed=seed,
    )

    assert lines == [
        "plan(score): 1 metric, 0 judges | 1 item | "
        "1 to run, 0 already scored | 0 infeasible",
        "warn: metric 'key_claim_completeness' has no reference for "
        "entry #0 in dataset 'ds' (pair skipped)",
        "done(score): 0 committed, 1 dropped, 0 failed",
    ]


def test_cli_metrics_only_fresh_store(tmp_path):
    workspace = harness.standard_workspace(tmp_path)
    harness.add_summarizer_section(str(workspace / "config.json"))

    result = harness.run_cli(
        ["score", "--metrics", "faithfulness", "--select", "named", "#0-1"],
        cwd=tmp_path,
    )

    result.assert_exit(0)
    assert result.lines == [
        "plan(score): 1 metric, 0 judges | 2 items | "
        "2 to run, 0 already scored | 0 infeasible",
        "note: no committed generations in scope; run 'generate' first",
        "done(score): 0 committed, 0 dropped, 0 failed",
    ]


def test_cli_zero_scorers(tmp_path):
    workspace = harness.standard_workspace(tmp_path)
    harness.add_summarizer_section(str(workspace / "config.json"))

    result = harness.run_cli(
        ["score", "--no-metrics", "--no-judges", "--select", "named", "#0-1"],
        cwd=tmp_path,
    )

    result.assert_exit(0)
    assert result.lines == [
        "plan(score): 0 metric(s), 0 judge(s) | 2 items | "
        "0 to run, 0 already scored | 0 infeasible",
        "note: no metrics or judges selected; nothing scored",
        "done(score): 0 committed, 0 dropped, 0 failed",
    ]
