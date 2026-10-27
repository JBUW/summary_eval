"""Ticket 06a — scorer resolution (resolve_scorers, docs/commands.md §score)."""
import pytest

from evalapp import metrics
from evalapp.errors import SpecError
from evalapp.scoring import Flag, ResolvedScorers, resolve_scorers

ALL = metrics.registered_names()
JUDGES = ("alpha", "beta")


def _resolved(default_metrics=None, default_judges=None, judges=JUDGES):
    return {
        "models": {},
        "prompt_templates": {},
        "summarizers": {},
        "judges": {name: {"requires_reference": False} for name in judges},
        "defaults": {"metrics": default_metrics, "judges": default_judges},
    }


# --- metrics axis ---------------------------------------------------------


def test_metrics_explicit_list_exact_given_order_deduped():
    result = resolve_scorers(_resolved(), Flag(value=[ALL[1], ALL[0], ALL[1]]), Flag())
    assert result.metrics == (ALL[1], ALL[0])
    assert isinstance(result, ResolvedScorers)
    assert all(isinstance(name, str) for name in result.metrics)


def test_metrics_empty_bracket_token_selects_zero():
    result = resolve_scorers(_resolved(), Flag(value=["[]"]), Flag())
    assert result.metrics == ()


def test_metrics_empty_bracket_token_unions_with_names():
    result = resolve_scorers(_resolved(), Flag(value=[ALL[0], "[]"]), Flag())
    assert result.metrics == (ALL[0],)


def test_metrics_star_selects_all_registered():
    result = resolve_scorers(_resolved(), Flag(value=["*"]), Flag())
    assert result.metrics == ALL


def test_metrics_star_unions_with_names():
    tokens = [ALL[2], "*"]
    result = resolve_scorers(_resolved(), Flag(value=tokens), Flag())
    assert result.metrics == (ALL[2],) + tuple(
        name for name in ALL if name != ALL[2]
    )


def test_metrics_omitted_uses_default_metrics_in_order():
    result = resolve_scorers(
        _resolved(default_metrics=[ALL[1], ALL[0]]), Flag(), Flag()
    )
    assert result.metrics == (ALL[1], ALL[0])


def test_metrics_omitted_default_present_but_empty_selects_zero():
    result = resolve_scorers(_resolved(default_metrics=[]), Flag(), Flag())
    assert result.metrics == ()


def test_metrics_omitted_default_absent_selects_all_registered():
    result = resolve_scorers(_resolved(), Flag(), Flag())
    assert result.metrics == ALL


def test_metrics_unknown_raises_with_registered_roster():
    with pytest.raises(SpecError) as excinfo:
        resolve_scorers(_resolved(), Flag(value=["nope"]), Flag())
    assert str(excinfo.value) == (
        "unknown metric 'nope' (registered: " + ", ".join(ALL) + ")"
    )


# --- judges axis ----------------------------------------------------------


def test_judges_explicit_list_exact_given_order():
    result = resolve_scorers(_resolved(), Flag(), Flag(value=["beta", "alpha"]))
    assert result.judges == ("beta", "alpha")


def test_judges_star_selects_all_configured_in_config_order():
    result = resolve_scorers(_resolved(), Flag(), Flag(value=["*"]))
    assert result.judges == JUDGES


def test_judges_star_unions_with_names():
    result = resolve_scorers(_resolved(), Flag(), Flag(value=["beta", "*"]))
    assert result.judges == ("beta", "alpha")


def test_judges_empty_bracket_token_selects_zero():
    result = resolve_scorers(_resolved(), Flag(), Flag(value=["[]"]))
    assert result.judges == ()


def test_judges_unknown_raises_with_configured_roster():
    with pytest.raises(SpecError) as excinfo:
        resolve_scorers(_resolved(), Flag(), Flag(value=["gamma"]))
    assert str(excinfo.value) == "unknown judge 'gamma' (alpha, beta)"


def test_judges_unknown_with_none_configured():
    with pytest.raises(SpecError) as excinfo:
        resolve_scorers(_resolved(judges=()), Flag(), Flag(value=["gamma"]))
    assert str(excinfo.value) == "unknown judge 'gamma' (none configured)"


def test_judges_no_flag_selects_zero():
    result = resolve_scorers(_resolved(), Flag(), Flag(no=True))
    assert result.judges == ()


def test_judges_omitted_selects_zero_even_with_default():
    result = resolve_scorers(_resolved(default_judges=["alpha"]), Flag(), Flag())
    assert result.judges == ()


def test_judges_bare_uses_default_judges_in_order():
    result = resolve_scorers(
        _resolved(default_judges=["beta", "alpha"]), Flag(), Flag(value="bare")
    )
    assert result.judges == ("beta", "alpha")
    assert result.notes == ()


def test_judges_bare_default_present_but_empty_zero_plus_note():
    result = resolve_scorers(
        _resolved(default_judges=[]), Flag(), Flag(value="bare")
    )
    assert result.judges == ()
    assert result.notes == (
        "--judges given but default_judges is empty; no judges run",
    )


def test_judges_bare_default_absent_selects_all_configured():
    result = resolve_scorers(_resolved(), Flag(), Flag(value="bare"))
    assert result.judges == JUDGES
    assert result.notes == ()


# --- --no-X guards --------------------------------------------------------


def test_no_metrics_with_metrics_raises():
    with pytest.raises(SpecError) as excinfo:
        resolve_scorers(_resolved(), Flag(no=True, value=[ALL[0]]), Flag())
    assert str(excinfo.value) == (
        "--no-metrics is mutually exclusive with --metrics"
    )


def test_no_judges_with_judges_raises():
    with pytest.raises(SpecError) as excinfo:
        resolve_scorers(_resolved(), Flag(), Flag(no=True, value=["alpha"]))
    assert str(excinfo.value) == (
        "--no-judges is mutually exclusive with --judges"
    )


def test_no_judges_with_bare_raises():
    with pytest.raises(SpecError) as excinfo:
        resolve_scorers(_resolved(), Flag(), Flag(no=True, value="bare"))
    assert str(excinfo.value) == (
        "--no-judges is mutually exclusive with --judges"
    )


def test_guards_run_before_unknown_name_errors():
    with pytest.raises(SpecError) as excinfo:
        resolve_scorers(_resolved(), Flag(no=True, value=["definitely-unknown"]), Flag())
    assert str(excinfo.value) == (
        "--no-metrics is mutually exclusive with --metrics"
    )
    with pytest.raises(SpecError) as excinfo:
        resolve_scorers(_resolved(), Flag(), Flag(no=True, value=["gamma"]))
    assert str(excinfo.value) == (
        "--no-judges is mutually exclusive with --judges"
    )
