"""Ticket 06b — score_plan (resume pre-scan), the judges phase (faked
judge_call seam), and the score orchestrator, docs/commands.md §score."""
import json

import pytest

from evalapp import scoring
from evalapp.datasets import Dataset
from evalapp.errors import RuntimeFailure, SpecError
from evalapp.identities import judge_evaluation_id, judge_id, summary_id
from evalapp.metrics import registered_names
from evalapp.scoring import (
    Flag,
    JudgePhaseResult,
    MetricsPhaseResult,
    ResolvedScorers,
    ScorePlan,
    run_judges_phase,
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


def _judge_entry(
    requires_reference=False, model_name="pin", user_template="tpl {transcript}"
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
    model_sha = store.upsert_model(b"model-bytes", "m", "model.bin")
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
    def __init__(self, scores):
        self.scores = scores
        self.calls = []

    def __call__(self, client, name, entry, transcript, generation, reference):
        self.calls.append((client, name, transcript, generation, reference))
        return self.scores


def _run_phase(
    store, resolved, judges, dataset, fake, console, infeasible=(),
    client="client-obj",
):
    return run_judges_phase(
        store,
        resolved,
        ResolvedScorers((), tuple(judges), ()),
        set(infeasible),
        {"ds": dataset},
        {"ds": [0]},
        select_summarizers(resolved),
        client,
        fake,
        console,
    )


def _reference_dataset(tmp_path, ref_value):
    """A dataset whose file holds the reference column (decl['path'] is the
    dataset file; _read_reference re-reads it by index)."""
    dataset_path = tmp_path / "data.jsonl"
    dataset_path.write_text(json.dumps({"t": "t0", "ref": ref_value}) + "\n")
    return Dataset(
        name="ds",
        decl={
            "path": str(dataset_path),
            "transcript_field": "t",
            "reference_field": "ref",
        },
        entries=[{"transcript": "t0"}],
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
        plan = score_plan(
            store,
            resolved,
            ResolvedScorers(
                ("faithfulness", "key_claim_completeness"), ("j",), ()
            ),
            infeasible,
            {"ds": dataset},
            {"ds": [0, 1, 2]},
            select_summarizers(resolved),
        )
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
            "pin", {}, "sys", "tpl {transcript}", False
        )
        store.upsert_judge_evaluation(
            judge_sha, generation_sha, None, 1.0, 1.0, 1.0
        )
        plan = score_plan(
            store,
            resolved,
            ResolvedScorers(("faithfulness",), ("j",), ()),
            set(),
            {"ds": dataset},
            {"ds": [0, 1, 2]},
            select_summarizers(resolved),
        )
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
            "pin", {}, "sys", "tpl {transcript}", True
        )
        store.upsert_judge_evaluation(
            judge_sha, generation_sha, reference_sha, 1.0, 1.0, 1.0
        )
        plan = score_plan(
            store,
            resolved,
            ResolvedScorers((), ("j",), ()),
            set(),
            {"ds": dataset},
            {"ds": [0, 1, 2]},
            select_summarizers(resolved),
        )
    finally:
        store.close()
    # the row exists with a non-NULL reference and the dataset has no
    # reference_field at all — any reference parsing would have failed
    assert plan == ScorePlan(
        metrics=0, judges=1, items=3, to_run=2, already_scored=1,
        infeasible_pairs=0,
    )


def test_happy_path_commits_unit_and_passes_client(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path, judges={"j": _judge_entry()})
    store = Store(tmp_path / "store.db")
    try:
        generation_sha, _ = _commit_generation(store, "t0", 0)
        _seed_judge(store, _judge_entry())
        fake = _JudgeFake(
            {"factual_correctness": 0.9, "completeness": 0.8, "conciseness": None}
        )
        result = _run_phase(
            store, resolved, ("j",), _dataset(), fake, _RecordingConsole()
        )
        judge_sha = judge_id("pin", {}, "sys", "tpl {transcript}", False)
        unit_sha = judge_evaluation_id(judge_sha, generation_sha, None)
        row = store.get_judge_evaluation(unit_sha)
    finally:
        store.close()
    assert result == JudgePhaseResult(
        items=1, missing_generation=0, committed=1, skipped=0, dropped=0,
        failed=0,
    )
    assert fake.calls == [("client-obj", "j", "t0", "gen:t0", None)]
    assert row == (0.9, 0.8, None)


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
        fake = _JudgeFake({"factual_correctness": 1.0})
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
    judges_flag=Flag(), generate=None,
):
    return scoring.score(
        resolved,
        store_path,
        metrics_flag,
        judges_flag,
        datasets,
        selected,
        (None, None, None),
        console,
        "client-obj",
        _JudgeFake({}),
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


def test_orchestrator_order_warn_plan_generate_metrics_judges(
    tmp_path, monkeypatch
):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(
        model_path,
        template_path,
        judges={"j": _judge_entry(requires_reference=True)},
    )
    events = []
    store_seen = []
    console = _RecordingConsole()

    def fake_plan(store, r, scorers, infeasible, datasets, selected, summarizers):
        events.append(("plan", len(console.warnings)))
        store_seen.append(store)
        return ScorePlan(5, 1, 3, 9, 0, 2)

    def fake_generate(store, c):
        events.append("generate")
        store_seen.append(store)

    def fake_metrics(store, r, scorers, infeasible, datasets, selected, summarizers, c):
        events.append("metrics")
        store_seen.append(store)
        return MetricsPhaseResult(3, 0, 9, 0, 0, 0)

    def fake_judges(store, r, scorers, infeasible, datasets, selected, summarizers, client, judge_call, c):
        events.append("judges")
        store_seen.append(store)
        return JudgePhaseResult(3, 0, 3, 0, 0, 0)

    monkeypatch.setattr("evalapp.scoring.score_plan", fake_plan)
    monkeypatch.setattr("evalapp.scoring.run_metrics_phase", fake_metrics)
    monkeypatch.setattr("evalapp.scoring.run_judges_phase", fake_judges)

    scorers, plan, metrics_result, judges_result = _score(
        resolved,
        tmp_path / "store.db",
        console,
        {"ds": _dataset()},
        {"ds": [0, 1, 2]},
        judges_flag=Flag(value=["j"]),
        generate=fake_generate,
    )
    assert events == [("plan", 2), "generate", "metrics", "judges"]
    assert len(store_seen) == 4
    assert all(store is store_seen[0] for store in store_seen)
    assert scorers == ResolvedScorers(
        metrics=registered_names(), judges=("j",), notes=()
    )
    assert plan == ScorePlan(5, 1, 3, 9, 0, 2)
    assert metrics_result == MetricsPhaseResult(3, 0, 9, 0, 0, 0)
    assert judges_result == JudgePhaseResult(3, 0, 3, 0, 0, 0)


def test_generate_failure_propagates_before_any_scoring(tmp_path, monkeypatch):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path)
    events = []

    def fake_plan(store, r, scorers, infeasible, datasets, selected, summarizers):
        events.append("plan")
        return ScorePlan(5, 0, 3, 15, 0, 1)

    def fake_metrics(store, r, scorers, infeasible, datasets, selected, summarizers, c):
        events.append("metrics")
        return MetricsPhaseResult(0, 0, 0, 0, 0, 0)

    def fake_judges(store, r, scorers, infeasible, datasets, selected, summarizers, client, judge_call, c):
        events.append("judges")
        return JudgePhaseResult(0, 0, 0, 0, 0, 0)

    def boom(store, c):
        raise RuntimeFailure("generate stage 1 failed")

    monkeypatch.setattr("evalapp.scoring.score_plan", fake_plan)
    monkeypatch.setattr("evalapp.scoring.run_metrics_phase", fake_metrics)
    monkeypatch.setattr("evalapp.scoring.run_judges_phase", fake_judges)

    with pytest.raises(RuntimeFailure, match="generate stage 1 failed"):
        _score(
            resolved,
            tmp_path / "store.db",
            _RecordingConsole(),
            {"ds": _dataset()},
            {"ds": [0, 1, 2]},
            generate=boom,
        )
    assert events == ["plan"]


def test_metrics_failure_prevents_judges_phase(tmp_path, monkeypatch):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(
        model_path, template_path, judges={"j": _judge_entry()}
    )
    events = []

    def fake_plan(store, r, scorers, infeasible, datasets, selected, summarizers):
        events.append("plan")
        return ScorePlan(5, 1, 1, 6, 0, 0)

    def fake_metrics(store, r, scorers, infeasible, datasets, selected, summarizers, c):
        events.append("metrics")
        raise RuntimeFailure("metric exploded")

    def fake_judges(store, r, scorers, infeasible, datasets, selected, summarizers, client, judge_call, c):
        events.append("judges")
        return JudgePhaseResult(0, 0, 0, 0, 0, 0)

    monkeypatch.setattr("evalapp.scoring.score_plan", fake_plan)
    monkeypatch.setattr("evalapp.scoring.run_metrics_phase", fake_metrics)
    monkeypatch.setattr("evalapp.scoring.run_judges_phase", fake_judges)

    with pytest.raises(RuntimeFailure, match="metric exploded"):
        _score(
            resolved,
            tmp_path / "store.db",
            _RecordingConsole(),
            {"ds": _dataset()},
            {"ds": [0]},
            judges_flag=Flag(value=["j"]),
        )
    assert events == ["plan", "metrics"]


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
        fake = _JudgeFake({"factual_correctness": 1.0})
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
        judge_sha = judge_id("pin", {}, "sys", "tpl {transcript}", False)
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
    dataset = _reference_dataset(tmp_path, "ref-0")
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
        judge_sha = judge_id("pin", {}, "sys", "tpl {transcript}", True)
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
    assert fake.calls == [("client-obj", "j", "t0", "gen:t0", "ref-0")]
    assert row == (1.0, 0.7, 0.6)
    assert counts["reference_summaries"] == 1


def test_missing_reference_drops_pair_before_resume_check(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(
        model_path, template_path,
        judges={"j": _judge_entry(requires_reference=True)},
    )
    dataset = _reference_dataset(tmp_path, "")
    store = Store(tmp_path / "store.db")
    try:
        generation_sha, transcript_sha = _commit_generation(store, "t0", 0)
        entry = _judge_entry(requires_reference=True)
        _seed_judge(store, entry)
        # an evaluation row already exists — the drop must still win
        reference_sha = store.upsert_reference_summary(
            "old-ref", transcript_sha, "ds", None, 0
        )
        judge_sha = judge_id("pin", {}, "sys", "tpl {transcript}", True)
        store.upsert_judge_evaluation(
            judge_sha, generation_sha, reference_sha, 0.5, 0.5, 0.5
        )
        fake = _JudgeFake({"factual_correctness": 1.0})
        console = _RecordingConsole()
        result = _run_phase(
            store, resolved, ("j",), dataset, fake, console
        )
    finally:
        store.close()
    assert result == JudgePhaseResult(
        items=1, missing_generation=0, committed=0, skipped=0, dropped=1,
        failed=0,
    )
    assert fake.calls == []
    assert console.warnings == [
        "judge 'j' has no reference for entry #0 in dataset 'ds' "
        "(pair skipped)"
    ]


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
        fake = _JudgeFake({"factual_correctness": 1.0})
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

        def failing(*args):
            raise RuntimeFailure("HTTP 500")

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


def test_reference_read_once_shared_across_judges(tmp_path, monkeypatch):
    model_path, template_path = _workspace(tmp_path)
    judges = {
        "j1": _judge_entry(requires_reference=True),
        "j2": _judge_entry(
            requires_reference=True, model_name="pin2"
        ),
    }
    resolved = _resolved(model_path, template_path, judges=judges)
    dataset = _reference_dataset(tmp_path, "ref-0")
    store = Store(tmp_path / "store.db")
    try:
        _commit_generation(store, "t0", 0)
        _seed_judge(store, judges["j1"], name="j1")
        _seed_judge(store, judges["j2"], name="j2")
        reads = []
        real_read = scoring._read_reference

        def counting_read(decl, index):
            reads.append(index)
            return real_read(decl, index)

        monkeypatch.setattr("evalapp.scoring._read_reference", counting_read)
        fake = _JudgeFake({"factual_correctness": 1.0})
        result = _run_phase(
            store, resolved, ("j1", "j2"), dataset, fake, _RecordingConsole()
        )
    finally:
        store.close()
    assert result == JudgePhaseResult(
        items=1, missing_generation=0, committed=2, skipped=0, dropped=0,
        failed=0,
    )
    assert reads == [0]


def test_no_judges_is_all_zero_noop(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path)
    store = Store(tmp_path / "store.db")
    try:
        _commit_generation(store, "t0", 0)
        fake = _JudgeFake({"factual_correctness": 1.0})
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
