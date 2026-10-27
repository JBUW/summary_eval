"""Ticket 06a — score_metrics pre-effect (resolve, infeasible warns, phase
wiring, docs/commands.md §score)."""
import pytest

from evalapp import metrics
from evalapp.datasets import Dataset
from evalapp.errors import SpecError
from evalapp.scoring import (
    Flag,
    MetricsPhaseResult,
    score_metrics,
)

ALL = metrics.registered_names()


def _resolved(default_metrics=None, default_judges=None, judges=()):
    return {
        "models": {},
        "prompt_templates": {},
        "summarizers": {},
        "judges": {name: {"requires_reference": False} for name in judges},
        "defaults": {"metrics": default_metrics, "judges": default_judges},
    }


class _RecordingConsole:
    def __init__(self):
        self.warnings = []

    def warn(self, message):
        self.warnings.append(message)


def test_unknown_metric_is_spec_error_before_any_store(tmp_path):
    store_path = tmp_path / "does-not-exist" / "store.db"
    with pytest.raises(SpecError) as excinfo:
        score_metrics(
            _resolved(),
            store_path,
            Flag(value=["bogus"]),
            Flag(),
            {},
            {},
            (None, None, None),
            _RecordingConsole(),
        )
    assert str(excinfo.value) == (
        f"unknown metric 'bogus' (registered: {', '.join(ALL)})"
    )
    assert not store_path.exists()
    assert not store_path.parent.exists()


def test_infeasible_warns_emit_before_phase_runs(tmp_path, monkeypatch):
    dataset = Dataset(
        name="ds",
        decl={
            "path": "x.jsonl",
            "transcript_field": "t",
            "reference_field": None,
        },
        entries=[{"transcript": "t"}],
    )
    console = _RecordingConsole()

    def fake_phase(*args):
        console.warn("phase-marker")
        return MetricsPhaseResult(0, 0, 0, 0, 0, 0)

    monkeypatch.setattr("evalapp.scoring.run_metrics_phase", fake_phase)
    scorers, result = score_metrics(
        _resolved(),
        tmp_path / "store.db",
        Flag(value=["key_claim_completeness"]),
        Flag(),
        {"ds": dataset},
        {"ds": [0]},
        (None, None, None),
        console,
    )
    assert scorers.metrics == ("key_claim_completeness",)
    assert result == MetricsPhaseResult(0, 0, 0, 0, 0, 0)
    assert console.warnings == [
        "metric 'key_claim_completeness' requires reference summaries; "
        "dataset 'ds' has none (pair skipped)",
        "phase-marker",
    ]
