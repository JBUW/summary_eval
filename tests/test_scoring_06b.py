"""Ticket 06b — score_plan (resume pre-scan), the judges phase (through
the fake endpoint transport, the only seam), and the score orchestrator,
docs/commands.md §score."""
import json

import harness
import pytest

from evalapp import metrics
from evalapp.datasets import Dataset
from evalapp.endpoint_client import EndpointClient
from evalapp.errors import RuntimeFailure, SpecError
from evalapp.identities import judge_evaluation_id, judge_id, summary_id, model_id
from evalapp.metrics import MetricSpec, registered_names
from evalapp.prepare import Loaded
from evalapp.scoring import (
    Flag,
    JudgePhaseResult,
    ResolvedScorers,
    ScorePlan,
    run_judges_phase,
    score,
    score_plan,
)
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


_TEMPLATE = "tpl {transcript} | {summary} | {reference}"


def _judge_entry(
    requires_reference=False, model_name="pin", user_template=_TEMPLATE
):
    return {
        "endpoint": "https://e/v1",
        "model_name": model_name,
        "api_key_env": None,
        "requires_reference": requires_reference,
        "gen_params": {},
        "system_content": "sys",
        "user_template": user_template,
    }


def _commit_generation(store, transcript, index):
    """Seed the FK chain (transcript/model/template/generation) and return
    the generation sha for (transcript, the single summarizer)."""
    transcript_sha = store.upsert_transcript(transcript, "ds", None, index)
    model_sha = store.upsert_model(model_id(b"model-bytes"), "m", "model.bin")
    template_sha = store.upsert_template("sys", "usr", "t")
    from evalapp.identities import generation_id

    return store.upsert_generation(
        transcript_sha, model_sha, {}, template_sha, {}, f"gen:{transcript}"
    ), transcript_sha


def _seed_judge(store, entry, name="j"):
    return store.upsert_judge(
        entry["model_name"], entry["gen_params"], entry["system_content"],
        entry["user_template"], entry["requires_reference"], name,
        entry["endpoint"], entry["api_key_env"],
    )


class _RecordingConsole:
    def __init__(self):
        self.warnings = []
        self.plans = []
        self.notes = []
        self.dones = []

    def warn(self, message):
        self.warnings.append(message)

    def plan(self, command, message):
        self.plans.append((command, message))

    def note(self, message):
        self.notes.append(message)

    def done(self, command, message):
        self.dones.append((command, message))


class _JudgeFake:
    """Fake endpoint transport for judge completions. Answers every
    request with the given qualities (None: an answer with no qualities;
    status >= 400: an HTTP failure) and records each rendered user
    message in ``calls``."""

    def __init__(self, scores, status=200, on_request=None):
        self.scores = scores
        self.status = status
        self.on_request = on_request
        self.calls = []

    def request(self, method, url, headers, body, timeout):
        self.calls.append(json.loads(body)["messages"][-1]["content"])
        if self.on_request is not None:
            self.on_request()
        if self.scores is None:
            text = "I cannot evaluate these qualities."
        else:
            text = "\n".join(f"{k}: {v}" for k, v in self.scores.items())
        return self.status, json.dumps(
            {"choices": [{"message": {"content": text}}]}
        )


_ALL_SCORES = {
    "factual_correctness": 1.0, "completeness": 1.0, "conciseness": 1.0,
}


def _run_phase(store, resolved, judges, dataset, fake, console, infeasible=()):
    return run_judges_phase(
        harness.scoring_run(
            store, resolved, ResolvedScorers((), tuple(judges), ()),
            {"ds": dataset}, {"ds": [0]}, select_summarizers(resolved),
            infeasible, console,
        ),
        EndpointClient(transport=fake),
    )


def _reference_dataset(ref_value):
    return Dataset(
        name="ds",
        decl={
            "path": "data.jsonl",
            "transcript_field": "t",
            "reference_field": "ref",
        },
        entries=[{"transcript": "t0", "reference": ref_value}],
    )


def test_fresh_store_counts_every_unit_to_run(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(
        model_path, template_path, judges={"j": _judge_entry()}
    )
    dataset = _dataset()
    infeasible = {("key_claim_completeness", "ds"), ("j", "ds")}
    store = Store(tmp_path / "store.db")
    try:
        plan = score_plan(harness.scoring_run(
            store, resolved, ResolvedScorers(("faithfulness", "key_claim_completeness"), ("j",), ()),
            {"ds": dataset}, {"ds": [0, 1, 2]},
            select_summarizers(resolved), infeasible,
        ))
    finally:
        store.close()
    assert plan == ScorePlan(
        metrics=2, judges=1, items=3, to_run=3, already_scored=0,
        infeasible_pairs=2,
    )


def test_resume_counts_committed_units_already_scored(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(
        model_path, template_path, judges={"j": _judge_entry()}
    )
    dataset = _dataset()
    store = Store(tmp_path / "store.db")
    try:
        generation_sha, _ = _commit_generation(store, "t0", 0)
        _seed_judge(store, _judge_entry())
        store.upsert_metric_evaluation("faithfulness", generation_sha, None, 0.5)
        judge_sha = judge_id(
            "pin", {}, "sys", _TEMPLATE, False
        )
        store.upsert_judge_evaluation(
            judge_sha, generation_sha, None, 1.0, 1.0, 1.0
        )
        plan = score_plan(harness.scoring_run(
            store, resolved, ResolvedScorers(("faithfulness",), ("j",), ()),
            {"ds": dataset}, {"ds": [0, 1, 2]},
            select_summarizers(resolved), set(),
        ))
    finally:
        store.close()
    # item 0: both units already scored; items 1-2: uncommitted
    # generations still count "to run" (no get_generation check)
    assert plan == ScorePlan(
        metrics=1, judges=1, items=3, to_run=4, already_scored=2,
        infeasible_pairs=0,
    )


def test_pre_scan_never_parses_references(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    judge = _judge_entry(requires_reference=True)
    resolved = _resolved(model_path, template_path, judges={"j": judge})
    dataset = _dataset()
    store = Store(tmp_path / "store.db")
    try:
        generation_sha, transcript_sha = _commit_generation(store, "t0", 0)
        _seed_judge(store, _judge_entry(requires_reference=True))
        reference_sha = store.upsert_reference_summary(
            "ref-0", transcript_sha, "ds", None, 0
        )
        judge_sha = judge_id(
            "pin", {}, "sys", _TEMPLATE, True
        )
        store.upsert_judge_evaluation(
            judge_sha, generation_sha, reference_sha, 1.0, 1.0, 1.0
        )
        plan = score_plan(harness.scoring_run(
            store, resolved, ResolvedScorers((), ("j",), ()),
            {"ds": dataset}, {"ds": [0, 1, 2]},
            select_summarizers(resolved), set(),
        ))
    finally:
        store.close()
    # the row exists with a non-NULL reference and the dataset has no
    # reference_field at all — any reference parsing would have failed
    assert plan == ScorePlan(
        metrics=0, judges=1, items=3, to_run=2, already_scored=1,
        infeasible_pairs=0,
    )


def test_happy_path_commits_unit_through_client(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path, judges={"j": _judge_entry()})
    store = Store(tmp_path / "store.db")
    try:
        generation_sha, _ = _commit_generation(store, "t0", 0)
        _seed_judge(store, _judge_entry())
        fake = _JudgeFake(
            {"factual_correctness": 0.9, "completeness": 0.8, "conciseness": 0.7}
        )
        result = _run_phase(
            store, resolved, ("j",), _dataset(), fake, _RecordingConsole()
        )
        judge_sha = judge_id("pin", {}, "sys", _TEMPLATE, False)
        unit_sha = judge_evaluation_id(judge_sha, generation_sha, None)
        row = store.get_judge_evaluation(unit_sha)
    finally:
        store.close()
    assert result == JudgePhaseResult(
        items=1, missing_generation=0, committed=1, skipped=0, dropped=0,
        failed=0,
    )
    assert fake.calls == ["tpl t0 | gen:t0 | {reference}"]
    assert row == (0.9, 0.8, 0.7)


def test_resume_skips_existing_unit_without_call(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path, judges={"j": _judge_entry()})
    store = Store(tmp_path / "store.db")
    try:
        generation_sha, _ = _commit_generation(store, "t0", 0)
        entry = _judge_entry()
        _seed_judge(store, entry)
        judge_sha = _seed_judge(store, entry)
        store.upsert_judge_evaluation(
            judge_sha, generation_sha, None, 0.5, 0.5, 0.5
        )
        fake = _JudgeFake(_ALL_SCORES)
        result = _run_phase(
            store, resolved, ("j",), _dataset(), fake, _RecordingConsole()
        )
    finally:
        store.close()
    assert result == JudgePhaseResult(
        items=1, missing_generation=0, committed=0, skipped=1, dropped=0,
        failed=0,
    )
    assert fake.calls == []


def _score(
    resolved, store_path, console, datasets, selected, metrics_flag=Flag(),
    judges_flag=Flag(), generate=None, fake=None,
):
    return score(
        Loaded(config=None, datasets=datasets, scope=selected,
               resolved=resolved),
        store_path,
        metrics_flag,
        judges_flag,
        (None, None, None),
        console,
        EndpointClient(transport=fake or _JudgeFake(_ALL_SCORES)),
        generate,
    )


def test_spec_error_raises_before_store_created(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path)
    store_path = tmp_path / "store.db"
    with pytest.raises(SpecError):
        _score(
            resolved,
            store_path,
            _RecordingConsole(),
            {"ds": _dataset()},
            {"ds": [0]},
            metrics_flag=Flag(value=["*"], no=True),
        )
    assert not store_path.exists()


class _EventConsole(_RecordingConsole):
    """Records every line, in order, into a shared event list."""

    def __init__(self, events):
        super().__init__()
        self.events = events

    def warn(self, message):
        super().warn(message)
        self.events.append("warn")

    def plan(self, command, message):
        super().plan(command, message)
        self.events.append(f"plan({command})")

    def done(self, command, message):
        super().done(command, message)
        self.events.append(f"done({command})")


def _committing_hook(events, stores, error=None):
    """A generate hook that commits the t0 generation (and seeds the
    judge row) into the run's store; raises ``error`` afterwards."""

    def generate(run):
        events.append("generate")
        stores.append(run.store)
        _commit_generation(run.store, "t0", 0)
        _seed_judge(run.store, _judge_entry())
        if error is not None:
            raise error

    return generate


def _metric_rows(store):
    return dict(store.table_counts())["metric_evaluations"]


def test_orchestrator_order_warn_plan_generate_metrics_judges(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(
        model_path, template_path, judges={"j": _judge_entry()}
    )
    events, stores = [], []
    console = _EventConsole(events)
    fake = _JudgeFake(
        _ALL_SCORES,
        on_request=lambda: events.append(("judge", _metric_rows(stores[0]))),
    )
    scorers, plan, metrics_result, judges_result = _score(
        resolved,
        tmp_path / "store.db",
        console,
        {"ds": _dataset()},
        {"ds": [0]},
        judges_flag=Flag(value=["j"]),
        generate=_committing_hook(events, stores),
        fake=fake,
    )
    # the metrics phase commits every metric row before the first judge call
    assert metrics_result.committed > 0
    assert events == [
        "warn", "plan(generate)", "plan(score)", "generate",
        ("judge", metrics_result.committed), "done(score)",
    ]
    assert scorers == ResolvedScorers(
        metrics=registered_names(), judges=("j",), notes=()
    )
    assert plan == ScorePlan(
        metrics=5, judges=1, items=1, to_run=5, already_scored=0,
        infeasible_pairs=1,
    )
    assert judges_result == JudgePhaseResult(
        items=1, missing_generation=0, committed=1, skipped=0, dropped=0,
        failed=0,
    )


def test_generate_failure_propagates_before_any_scoring(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(
        model_path, template_path, judges={"j": _judge_entry()}
    )
    events, stores = [], []
    fake = _JudgeFake(_ALL_SCORES)
    store_path = tmp_path / "store.db"
    with pytest.raises(RuntimeFailure, match="generate stage 1 failed"):
        _score(
            resolved,
            store_path,
            _EventConsole(events),
            {"ds": _dataset()},
            {"ds": [0]},
            judges_flag=Flag(value=["j"]),
            generate=_committing_hook(
                events, stores, RuntimeFailure("generate stage 1 failed")
            ),
            fake=fake,
        )
    store = Store(store_path)
    try:
        assert _metric_rows(store) == 0
    finally:
        store.close()
    assert fake.calls == []
    assert events == ["warn", "plan(generate)", "plan(score)", "generate"]


def test_metrics_failure_prevents_judges_phase(tmp_path, monkeypatch):
    def _boom(_input):
        raise ValueError("metric exploded")

    monkeypatch.setitem(
        metrics._REGISTRY,
        "faithfulness",
        MetricSpec("faithfulness", False, _boom),
    )
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(
        model_path, template_path, judges={"j": _judge_entry()}
    )
    store = Store(tmp_path / "store.db")
    _commit_generation(store, "t0", 0)
    _seed_judge(store, _judge_entry())
    store.close()
    fake = _JudgeFake(_ALL_SCORES)
    with pytest.raises(RuntimeFailure, match="metric exploded"):
        _score(
            resolved,
            tmp_path / "store.db",
            _RecordingConsole(),
            {"ds": _dataset()},
            {"ds": [0]},
            metrics_flag=Flag(value=["faithfulness"]),
            judges_flag=Flag(value=["j"]),
            fake=fake,
        )
    assert fake.calls == []


def test_score_without_generate_hook_runs_real_phases(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path)
    dataset = _dataset()
    store = Store(tmp_path / "store.db")
    _commit_generation(store, "t0", 0)
    store.close()
    console = _RecordingConsole()
    scorers, plan, metrics_result, judges_result = _score(
        resolved,
        tmp_path / "store.db",
        console,
        {"ds": dataset},
        {"ds": [0]},
    )
    assert scorers == ResolvedScorers(
        metrics=registered_names(), judges=(), notes=()
    )
    assert plan == ScorePlan(
        metrics=5, judges=0, items=1, to_run=4, already_scored=0,
        infeasible_pairs=1,
    )
    assert metrics_result.missing_generation == 0
    assert metrics_result.committed + metrics_result.excluded == 4
    assert judges_result == JudgePhaseResult(0, 0, 0, 0, 0, 0)
    assert console.warnings == [
        "metric 'key_claim_completeness' requires reference summaries; "
        "dataset 'ds' has none (pair skipped)"
    ]


def test_missing_generation_counts_and_makes_no_call(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path, judges={"j": _judge_entry()})
    store = Store(tmp_path / "store.db")
    try:
        _seed_judge(store, _judge_entry())
        fake = _JudgeFake(_ALL_SCORES)
        result = _run_phase(
            store, resolved, ("j",), _dataset(), fake, _RecordingConsole()
        )
    finally:
        store.close()
    assert result == JudgePhaseResult(
        items=1, missing_generation=1, committed=0, skipped=0, dropped=0,
        failed=0,
    )
    assert fake.calls == []


def test_unextractable_result_warns_and_counts_failed(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path, judges={"j": _judge_entry()})
    store = Store(tmp_path / "store.db")
    try:
        generation_sha, _ = _commit_generation(store, "t0", 0)
        entry = _judge_entry()
        _seed_judge(store, entry)
        fake = _JudgeFake(None)
        console = _RecordingConsole()
        result = _run_phase(
            store, resolved, ("j",), _dataset(), fake, console
        )
        judge_sha = judge_id("pin", {}, "sys", _TEMPLATE, False)
        assert not store.has_judge_evaluation(judge_sha, generation_sha)
    finally:
        store.close()
    assert result == JudgePhaseResult(
        items=1, missing_generation=0, committed=0, skipped=0, dropped=0,
        failed=1,
    )
    assert console.warnings == [
        "judge 'j' returned no extractable qualities for entry #0 "
        "in dataset 'ds' (unit not committed)"
    ]


def test_reference_judge_commits_reference_and_scores(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(
        model_path, template_path,
        judges={"j": _judge_entry(requires_reference=True)},
    )
    dataset = _reference_dataset("ref-0")
    store = Store(tmp_path / "store.db")
    try:
        generation_sha, _ = _commit_generation(store, "t0", 0)
        entry = _judge_entry(requires_reference=True)
        _seed_judge(store, entry)
        fake = _JudgeFake(
            {"factual_correctness": 1.0, "completeness": 0.7,
             "conciseness": 0.6}
        )
        result = _run_phase(
            store, resolved, ("j",), dataset, fake, _RecordingConsole()
        )
        counts = dict(store.table_counts())
        judge_sha = judge_id("pin", {}, "sys", _TEMPLATE, True)
        reference_sha = summary_id("ref-0")
        unit_sha = judge_evaluation_id(
            judge_sha, generation_sha, reference_sha
        )
        row = store.get_judge_evaluation(unit_sha)
    finally:
        store.close()
    assert result == JudgePhaseResult(
        items=1, missing_generation=0, committed=1, skipped=0, dropped=0,
        failed=0,
    )
    assert fake.calls == ["tpl t0 | gen:t0 | ref-0"]
    assert row == (1.0, 0.7, 0.6)
    assert counts["reference_summaries"] == 1


def test_infeasible_pair_is_silent(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(
        model_path, template_path,
        judges={"j": _judge_entry(requires_reference=True)},
    )
    store = Store(tmp_path / "store.db")
    try:
        _commit_generation(store, "t0", 0)
        _seed_judge(store, _judge_entry(requires_reference=True))
        fake = _JudgeFake(_ALL_SCORES)
        console = _RecordingConsole()
        result = _run_phase(
            store, resolved, ("j",), _dataset(), fake, console,
            infeasible={("j", "ds")},
        )
    finally:
        store.close()
    assert result == JudgePhaseResult(
        items=1, missing_generation=0, committed=0, skipped=0, dropped=0,
        failed=0,
    )
    assert fake.calls == []
    assert console.warnings == []


def test_judge_call_failure_propagates(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path, judges={"j": _judge_entry()})
    store = Store(tmp_path / "store.db")
    try:
        _commit_generation(store, "t0", 0)
        _seed_judge(store, _judge_entry())

        failing = _JudgeFake(_ALL_SCORES, status=500)

        with pytest.raises(
            RuntimeFailure,
            match="judge 'j' failed for entry #0 in dataset 'ds': HTTP 500",
        ):
            _run_phase(
                store, resolved, ("j",), _dataset(), failing,
                _RecordingConsole(),
            )
    finally:
        store.close()


def test_reference_shared_across_judges(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    judges = {
        "j1": _judge_entry(requires_reference=True),
        "j2": _judge_entry(
            requires_reference=True, model_name="pin2"
        ),
    }
    resolved = _resolved(model_path, template_path, judges=judges)
    dataset = _reference_dataset("ref-0")
    store = Store(tmp_path / "store.db")
    try:
        _commit_generation(store, "t0", 0)
        _seed_judge(store, judges["j1"], name="j1")
        _seed_judge(store, judges["j2"], name="j2")
        fake = _JudgeFake(_ALL_SCORES)
        result = _run_phase(
            store, resolved, ("j1", "j2"), dataset, fake, _RecordingConsole()
        )
    finally:
        store.close()
    assert result == JudgePhaseResult(
        items=1, missing_generation=0, committed=2, skipped=0, dropped=0,
        failed=0,
    )
    assert [call.split(" | ")[-1] for call in fake.calls] == [
        "ref-0", "ref-0",
    ]


def test_no_judges_is_all_zero_noop(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path)
    store = Store(tmp_path / "store.db")
    try:
        _commit_generation(store, "t0", 0)
        fake = _JudgeFake(_ALL_SCORES)
        result = _run_phase(
            store, resolved, (), _dataset(), fake, _RecordingConsole()
        )
    finally:
        store.close()
    assert result == JudgePhaseResult(
        items=0, missing_generation=0, committed=0, skipped=0, dropped=0,
        failed=0,
    )
    assert fake.calls == []
