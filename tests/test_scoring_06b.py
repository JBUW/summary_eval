"""Ticket 06b — score_plan (resume pre-scan) and the judges phase
(faked judge_call seam), docs/commands.md §score."""
import json

from evalapp.datasets import Dataset
from evalapp.identities import judge_id, summary_id
from evalapp.scoring import ResolvedScorers, ScorePlan, score_plan
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


def _judge_entry(requires_reference=False):
    return {
        "endpoint": "https://e/v1",
        "model_name": "pin",
        "api_key_env": None,
        "requires_reference": requires_reference,
        "gen_params": {},
        "system_content": "sys",
        "user_template": "tpl {transcript}",
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


def _seed_judge(store, name="j", requires_reference=False):
    entry = _judge_entry(requires_reference)
    return store.upsert_judge(
        entry["model_name"], entry["gen_params"], entry["system_content"],
        entry["user_template"], entry["requires_reference"], name,
        entry["endpoint"], entry["api_key_env"],
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
        _seed_judge(store)
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
        _seed_judge(store, requires_reference=True)
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
