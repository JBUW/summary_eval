import pytest

from evalapp.errors import SpecError
from evalapp.summarizers import Summarizer, select_summarizers


def _resolved():
    return {
        "models": {
            "a": {"path": "/m/a", "model_args": {}, "gen_params": {}},
            "b": {"path": "/m/b", "model_args": {}, "gen_params": {}},
        },
        "prompt_templates": {"t1": "/t/t1", "t2": "/t/t2"},
        "summarizers": {
            "std": {
                "model": "a",
                "model_args": {},
                "prompt_template": "t1",
                "gen_params": {"max_tokens": 10},
            },
            "fast": {
                "model": "b",
                "model_args": {},
                "prompt_template": "t2",
                "gen_params": {},
            },
        },
    }


def test_no_flags_selects_all_configured_in_order():
    result = select_summarizers(_resolved())
    assert result == (
        Summarizer("std", "a", {}, "t1", {"max_tokens": 10}),
        Summarizer("fast", "b", {}, "t2", {}),
    )


def test_no_flags_none_configured_selects_nothing():
    result = select_summarizers(
        {"models": {}, "prompt_templates": {}, "summarizers": {}}
    )
    assert result == ()


def test_named_only_selects_named_in_given_order():
    result = select_summarizers(_resolved(), summarizer_names=("fast", "std"))
    assert [s.name for s in result] == ["fast", "std"]
    assert result[0] == Summarizer("fast", "b", {}, "t2", {})


def test_named_star_selects_all_in_config_order():
    result = select_summarizers(_resolved(), summarizer_names=("*",))
    assert [s.name for s in result] == ["std", "fast"]


def test_named_unknown_raises_with_roster():
    with pytest.raises(SpecError) as excinfo:
        select_summarizers(_resolved(), summarizer_names=("nope",))
    assert str(excinfo.value) == "unknown summarizer 'nope' (std, fast)"


def test_named_alone_does_not_compute_product():
    # --summarizer std with no component axis: the product is empty,
    # the result is just the named summarizer.
    result = select_summarizers(_resolved(), summarizer_names=("std",))
    assert result == (Summarizer("std", "a", {}, "t1", {"max_tokens": 10}),)


def test_model_axis_only_products_with_all_templates():
    result = select_summarizers(_resolved(), model_names=("b",))
    assert result == (
        Summarizer(None, "b", {}, "t1", {}),
        Summarizer(None, "b", {}, "t2", {}),
    )


def test_both_axes_product_models_outer_templates_inner():
    result = select_summarizers(
        _resolved(), model_names=("b", "a"), template_names=("t2", "t1")
    )
    assert [(s.model, s.template) for s in result] == [
        ("b", "t2"),
        ("b", "t1"),
        ("a", "t2"),
        ("a", "t1"),
    ]


def test_omitted_axis_means_all_configured_on_that_axis():
    result = select_summarizers(_resolved(), template_names=("t2",))
    assert result == (
        Summarizer(None, "a", {}, "t2", {}),
        Summarizer(None, "b", {}, "t2", {}),
    )


def test_star_axis_selects_all_configured():
    result = select_summarizers(_resolved(), model_names=("*",), template_names=("t1",))
    assert [(s.model, s.template) for s in result] == [("a", "t1"), ("b", "t1")]


def test_product_uses_model_entry_own_args_and_params():
    resolved = _resolved()
    resolved["models"]["a"]["model_args"] = {"n_ctx": 4096}
    resolved["models"]["a"]["gen_params"] = {"temperature": 0.2}
    result = select_summarizers(resolved, model_names=("a",), template_names=("t1",))
    assert result == (Summarizer(None, "a", {"n_ctx": 4096}, "t1", {"temperature": 0.2}),)


def test_named_added_after_product():
    result = select_summarizers(
        _resolved(), summarizer_names=("std",), model_names=("a",), template_names=("t1",)
    )
    assert [s.name for s in result] == [None, "std"]


def test_dedupe_by_components_first_occurrence_wins():
    resolved = _resolved()
    resolved["summarizers"]["std"]["gen_params"] = {}  # std == the a x t1 product combo
    result = select_summarizers(
        resolved, summarizer_names=("std",), model_names=("a",), template_names=("t1",)
    )
    assert result == (Summarizer(None, "a", {}, "t1", {}),)


def test_duplicate_tokens_deduped_first_occurrence():
    result = select_summarizers(_resolved(), model_names=("b", "b"))
    assert result == (
        Summarizer(None, "b", {}, "t1", {}),
        Summarizer(None, "b", {}, "t2", {}),
    )
    named = select_summarizers(_resolved(), summarizer_names=("std", "std"))
    assert [s.name for s in named] == ["std"]


def test_unknown_model_raises_with_roster():
    with pytest.raises(SpecError) as excinfo:
        select_summarizers(_resolved(), model_names=("zzz",))
    assert str(excinfo.value) == "unknown model 'zzz' (a, b)"


def test_unknown_template_raises_with_roster():
    with pytest.raises(SpecError) as excinfo:
        select_summarizers(_resolved(), template_names=("zzz",))
    assert str(excinfo.value) == "unknown prompt template 'zzz' (t1, t2)"


def test_unknown_token_roster_none_configured():
    with pytest.raises(SpecError) as excinfo:
        select_summarizers(_resolved(), model_names=("*",), template_names=("zzz",))
    # templates are configured, so the roster lists them
    assert str(excinfo.value) == "unknown prompt template 'zzz' (t1, t2)"
    with pytest.raises(SpecError) as excinfo:
        select_summarizers(
            {"models": {}, "prompt_templates": {}, "summarizers": {}},
            model_names=("zzz",),
        )
    assert str(excinfo.value) == "unknown model 'zzz' (none configured)"
