"""Ticket 06a — run_metrics_phase (end-to-end over a real Store)."""
import json
import sqlite3

import pytest

from evalapp.datasets import Dataset, load_dataset
from evalapp.errors import RuntimeFailure
from evalapp.identities import (
    metric_evaluation_id,
    model_id,
    summary_id,
    transcript_id,
)
from evalapp.metrics import MetricInput, MetricSpec, get as get_spec
from evalapp.scoring import (
    MetricsPhaseResult,
    ResolvedScorers,
    run_metrics_phase,
)
from evalapp.store import Store
from evalapp.summarizers import Summarizer

MODEL_BYTES = b"model-bytes-v1"
GEN = "alpha beta gamma delta"


class RecordingConsole:
    def __init__(self):
        self.lines = []

    def warn(self, message):
        self.lines.append(("warn", message))

    def note(self, message):
        self.lines.append(("note", message))

    def plan(self, command, message):
        self.lines.append(("plan", command, message))

    def done(self, command, message):
        self.lines.append(("done", command, message))


def _build(tmp_path, template=None):
    template = (
        {"system_content": "SYS", "user_template": "USR"}
        if template is None
        else template
    )
    model_path = tmp_path / "model.bin"
    model_path.write_bytes(MODEL_BYTES)
    template_path = tmp_path / "template.json"
    template_path.write_text(json.dumps(template), encoding="utf-8")
    dataset_path = tmp_path / "data.jsonl"
    records = [
        {"text": "transcript one", "id": "id-0", "ref": "the reference claim here"},
        {"text": "transcript two", "id": "id-1", "ref": "second reference line"},
    ]
    dataset_path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )
    decl = {
        "path": str(dataset_path),
        "transcript_field": "text",
        "reference_field": "ref",
        "entry_id_field": "id",
    }
    dataset = load_dataset("ds", decl)
    resolved = {
        "models": {
            "m": {"path": str(model_path), "model_args": {}, "gen_params": {}},
        },
        "prompt_templates": {"t": str(template_path)},
        "summarizers": {},
        "judges": {},
        "defaults": {"metrics": None, "judges": None},
    }
    return dataset, resolved, Summarizer("s", "m", {}, "t", {}), template


def _seed(store, dataset, template, generation_text=GEN):
    entry = dataset.entries[0]
    transcript_sha = store.upsert_transcript(
        entry["transcript"], "ds", entry.get("entry_id"), 0
    )
    model_sha = store.upsert_model(MODEL_BYTES, "m", "model.bin")
    template_sha = store.upsert_template(
        template["system_content"], template["user_template"], "t"
    )
    return store.upsert_generation(
        transcript_sha, model_sha, {}, template_sha, {}, generation_text
    )


def _phase(store, resolved, summarizer, metric_names, dataset, selected=None,
           infeasible=frozenset(), console=None):
    selected = selected if selected is not None else {"ds": [0]}
    console = console if console is not None else RecordingConsole()
    scorers = ResolvedScorers(metrics=tuple(metric_names), judges=(), notes=())
    return run_metrics_phase(
        store, resolved, scorers, infeasible, {"ds": dataset}, selected,
        (summarizer,), console,
    ), console


def test_commits_non_reference_metric(tmp_path):
    dataset, resolved, summarizer, template = _build(tmp_path)
    store = Store(str(tmp_path / "store.db"))
    generation_sha = _seed(store, dataset, template)
    result, _ = _phase(
        store, resolved, summarizer, ["conciseness_length_proxy"], dataset
    )
    assert result == MetricsPhaseResult(
        items=1, missing_generation=0, committed=1, skipped=0, excluded=0, dropped=0
    )
    expected = get_spec("conciseness_length_proxy").compute(
        MetricInput(
            transcript_text="transcript one",
            generation_text=GEN,
            reference_summary_text=None,
            prompt_text="SYSUSR",
        )
    )
    assert store.get_metric_evaluation(
        metric_evaluation_id("conciseness_length_proxy", generation_sha, None)
    ) == expected
    store.close()


def test_reference_metric_commits_evaluation_and_reference_summary(tmp_path):
    dataset, resolved, summarizer, template = _build(tmp_path)
    store = Store(str(tmp_path / "store.db"))
    generation_sha = _seed(store, dataset, template)
    result, _ = _phase(
        store, resolved, summarizer, ["key_claim_completeness"], dataset
    )
    assert result == MetricsPhaseResult(
        items=1, missing_generation=0, committed=1, skipped=0, excluded=0, dropped=0
    )
    reference = "the reference claim here"
    expected = get_spec("key_claim_completeness").compute(
        MetricInput(
            transcript_text="transcript one",
            generation_text=GEN,
            reference_summary_text=reference,
            prompt_text="SYSUSR",
        )
    )
    assert expected is not None
    assert store.get_metric_evaluation(
        metric_evaluation_id("key_claim_completeness", generation_sha, summary_id(reference))
    ) == expected
    connection = sqlite3.connect(str(store.path))
    try:
        rows = connection.execute(
            "SELECT transcript_sha256, dataset_name, entry_id, entry_index "
            "FROM reference_summaries"
        ).fetchall()
    finally:
        connection.close()
    assert rows == [(transcript_id("transcript one"), "ds", "id-0", 0)]
    store.close()


def test_missing_reference_drops_pair_with_warn(tmp_path):
    dataset, resolved, summarizer, template = _build(tmp_path)
    no_ref_path = tmp_path / "noref.jsonl"
    no_ref_path.write_text(
        json.dumps({"text": "transcript one", "id": "id-0"}) + "\n",
        encoding="utf-8",
    )
    broken = Dataset(
        name="ds",
        decl={
            "path": str(no_ref_path),
            "transcript_field": "text",
            "reference_field": "ref",
            "entry_id_field": "id",
        },
        entries=[{"index": 0, "transcript": "transcript one", "entry_id": "id-0"}],
    )
    store = Store(str(tmp_path / "store.db"))
    _seed(store, broken, template)
    console = RecordingConsole()
    result, console = _phase(
        store, resolved, summarizer, ["key_claim_completeness"], broken,
        console=console,
    )
    assert result == MetricsPhaseResult(
        items=1, missing_generation=0, committed=0, skipped=0, excluded=0, dropped=1
    )
    assert console.lines == [
        (
            "warn",
            "metric 'key_claim_completeness' has no reference for entry #0 "
            "in dataset 'ds' (pair skipped)",
        )
    ]
    store.close()


def test_skip_on_rerun(tmp_path):
    dataset, resolved, summarizer, template = _build(tmp_path)
    store = Store(str(tmp_path / "store.db"))
    _seed(store, dataset, template)
    first, _ = _phase(
        store, resolved, summarizer, ["conciseness_length_proxy"], dataset
    )
    second, _ = _phase(
        store, resolved, summarizer, ["conciseness_length_proxy"], dataset
    )
    assert (first.committed, first.skipped) == (1, 0)
    assert (second.committed, second.skipped) == (0, 1)
    store.close()


def test_missing_generation_not_committed(tmp_path):
    dataset, resolved, summarizer, template = _build(tmp_path)
    store = Store(str(tmp_path / "store.db"))
    result, _ = _phase(
        store, resolved, summarizer, ["conciseness_length_proxy"], dataset
    )
    assert result == MetricsPhaseResult(
        items=1, missing_generation=1, committed=0, skipped=0, excluded=0, dropped=0
    )
    store.close()


def test_none_value_excluded_no_row(tmp_path):
    dataset, resolved, summarizer, template = _build(tmp_path)
    store = Store(str(tmp_path / "store.db"))
    generation_sha = _seed(store, dataset, template, generation_text="!!!")
    result, _ = _phase(
        store, resolved, summarizer, ["conciseness_length_proxy"], dataset
    )
    assert result == MetricsPhaseResult(
        items=1, missing_generation=0, committed=0, skipped=0, excluded=1, dropped=0
    )
    assert store.get_metric_evaluation(
        metric_evaluation_id("conciseness_length_proxy", generation_sha, None)
    ) is None
    store.close()


def test_infeasible_pair_skipped_silently(tmp_path):
    dataset, resolved, summarizer, template = _build(tmp_path)
    store = Store(str(tmp_path / "store.db"))
    _seed(store, dataset, template)
    console = RecordingConsole()
    result, console = _phase(
        store, resolved, summarizer, ["key_claim_completeness"], dataset,
        infeasible={("key_claim_completeness", "ds")}, console=console,
    )
    assert result == MetricsPhaseResult(
        items=1, missing_generation=0, committed=0, skipped=0, excluded=0, dropped=0
    )
    assert console.lines == []
    store.close()


def test_metric_failure_is_runtime_failure(tmp_path, monkeypatch):
    from evalapp import metrics as metrics_module

    def _boom(_input):
        raise ValueError("kaboom")

    monkeypatch.setattr(
        metrics_module,
        "resolve",
        lambda tokens: [MetricSpec("boom", False, _boom)],
    )
    dataset, resolved, summarizer, template = _build(tmp_path)
    store = Store(str(tmp_path / "store.db"))
    _seed(store, dataset, template)
    with pytest.raises(
        RuntimeFailure,
        match=r"metric 'boom' failed for entry #0 in dataset 'ds': kaboom",
    ):
        _phase(store, resolved, summarizer, ["boom"], dataset)
    store.close()


def test_prompt_text_is_template_composition(tmp_path):
    template = {
        "system_content": "",
        "user_template": "Write a section called 'Alpha'.",
    }
    dataset, resolved, summarizer, _ = _build(tmp_path, template)
    store = Store(str(tmp_path / "store.db"))
    generation_sha = _seed(
        store, dataset, template, generation_text="beta gamma delta epsilon"
    )
    result, _ = _phase(
        store, resolved, summarizer, ["structural_instruction_check"], dataset
    )
    assert result.committed == 1
    assert store.get_metric_evaluation(
        metric_evaluation_id("structural_instruction_check", generation_sha, None)
    ) == 0.0
    store.close()


def test_missing_model_file_is_runtime_failure(tmp_path):
    dataset, resolved, summarizer, template = _build(tmp_path)
    resolved["models"]["m"]["path"] = str(tmp_path / "gone.bin")
    store = Store(str(tmp_path / "store.db"))
    with pytest.raises(RuntimeFailure, match=r"model 'm': file not found: "):
        _phase(store, resolved, summarizer, ["conciseness_length_proxy"], dataset)
    store.close()
