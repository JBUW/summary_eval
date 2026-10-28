"""Ticket 09 — sweep scorer-set resolution and judge credential preflight."""
import contextlib
import harness  # noqa: F401  (puts the repo root on sys.path)
import io
import os

import pytest

from evalapp.console import Console
from evalapp.errors import SpecError
from evalapp.metrics import registered_names
from evalapp.scoring import ResolvedScorers, _sweep_credential_preflight, resolve_sweep_scorers


def _resolved(default_metrics, default_judges, judge_names=()):
    judges = {
        name: {
            "endpoint": "https://e/v1",
            "model_name": "pin",
            "api_key_env": None,
            "requires_reference": False,
            "gen_params": {},
            "system_content": "sys",
            "user_template": "x",
        }
        for name in judge_names
    }
    return {
        "models": {},
        "prompt_templates": {},
        "summarizers": {},
        "judges": judges,
        "defaults": {"metrics": default_metrics, "judges": default_judges},
    }


def test_defaults_present_are_exact():
    resolved = _resolved(
        ["faithfulness", "conciseness_length_proxy"],
        ["j2", "j1"],
        judge_names=("j1", "j2"),
    )
    scorers = resolve_sweep_scorers(resolved, False, False)
    assert scorers.metrics == ("faithfulness", "conciseness_length_proxy")
    assert scorers.judges == ("j2", "j1")
    assert scorers.notes == ()


def test_defaults_empty_lists_are_zero():
    resolved = _resolved([], [], judge_names=("j1",))
    scorers = resolve_sweep_scorers(resolved, False, False)
    assert scorers.metrics == ()
    assert scorers.judges == ()


def test_defaults_empty_bracket_token_are_zero():
    resolved = _resolved(["[]"], ["[]"], judge_names=("j1",))
    scorers = resolve_sweep_scorers(resolved, False, False)
    assert scorers.metrics == ()
    assert scorers.judges == ()


def test_defaults_absent_select_all():
    resolved = _resolved(None, None, judge_names=("j2", "j1"))
    scorers = resolve_sweep_scorers(resolved, False, False)
    assert scorers.metrics == registered_names()
    assert scorers.judges == ("j2", "j1")


def test_widen_flags_force_full_set():
    resolved = _resolved(["faithfulness"], ["j1"], judge_names=("j1", "j2"))
    assert resolve_sweep_scorers(resolved, True, False).metrics == registered_names()
    assert resolve_sweep_scorers(resolved, True, False).judges == ("j1",)
    assert resolve_sweep_scorers(resolved, False, True).metrics == ("faithfulness",)
    assert resolve_sweep_scorers(resolved, False, True).judges == ("j1", "j2")
    both = resolve_sweep_scorers(resolved, True, True)
    assert both == ResolvedScorers(registered_names(), ("j1", "j2"), ())


def test_widen_flags_are_idempotent():
    resolved = _resolved(None, None, judge_names=("j1",))
    plain = resolve_sweep_scorers(resolved, False, False)
    all_metrics = resolve_sweep_scorers(resolved, True, False)
    all_judges = resolve_sweep_scorers(resolved, False, True)
    all = resolve_sweep_scorers(resolved, True, True)
    assert all_metrics.metrics == all.metrics == plain.metrics
    assert all_judges.judges == all.judges == plain.judges


def test_unknown_default_judge_is_spec_error():
    resolved = _resolved(None, ["nope"], judge_names=("j1",))
    with pytest.raises(SpecError):
        resolve_sweep_scorers(resolved, False, False)


def test_credential_preflight_warns_and_drops():
    os.environ.pop("EVALAPP_TEST_SWEEP_UNSET", None)
    resolved = _resolved(None, None, judge_names=("ok", "bad"))
    resolved["judges"]["bad"]["api_key_env"] = "EVALAPP_TEST_SWEEP_UNSET"
    console = Console()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        kept = _sweep_credential_preflight(resolved, console, ("ok", "bad"))
    assert kept == ("ok",)
    assert buffer.getvalue().splitlines() == [
        "warn: judge 'bad': environment variable 'EVALAPP_TEST_SWEEP_UNSET' "
        "is unset or empty (judge skipped)"
    ]


def test_credential_preflight_drops_empty_variable():
    os.environ["EVALAPP_TEST_SWEEP_EMPTY"] = ""
    try:
        resolved = _resolved(None, None, judge_names=("ok", "empty"))
        resolved["judges"]["empty"]["api_key_env"] = "EVALAPP_TEST_SWEEP_EMPTY"
        console = Console()
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            kept = _sweep_credential_preflight(resolved, console, ("ok", "empty"))
        assert kept == ("ok",)
        assert buffer.getvalue().splitlines() == [
            "warn: judge 'empty': environment variable 'EVALAPP_TEST_SWEEP_EMPTY' "
            "is unset or empty (judge skipped)"
        ]
    finally:
        del os.environ["EVALAPP_TEST_SWEEP_EMPTY"]
