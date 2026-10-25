import dataclasses

import pytest

from evalapp.errors import SpecError
from evalapp.metrics import (
    MetricSpec,
    get,
    registered_names,
    resolve,
    validate,
)

EXPECTED_NAMES = (
    "conciseness_length_proxy",
    "faithfulness",
    "internal_consistency",
    "key_claim_completeness",
    "structural_instruction_check",
)


def test_discovery_registers_exactly_the_five_v1_metrics():
    assert registered_names() == EXPECTED_NAMES


def test_requires_reference_flags():
    assert get("key_claim_completeness").requires_reference is True
    for name in (
        "faithfulness",
        "conciseness_length_proxy",
        "structural_instruction_check",
        "internal_consistency",
    ):
        assert get(name).requires_reference is False


def test_spec_is_frozen():
    spec = get("faithfulness")
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.requires_reference = True


def test_root_config_default_metrics_are_all_registered():
    for name in (
        "faithfulness",
        "key_claim_completeness",
        "conciseness_length_proxy",
        "structural_instruction_check",
    ):
        assert get(name) is not None


def test_resolve_by_name():
    specs = resolve(["faithfulness"])
    assert [spec.name for spec in specs] == ["faithfulness"]


def test_resolve_star_selects_all_registered_sorted():
    assert [spec.name for spec in resolve(["*"])] == list(EXPECTED_NAMES)


def test_resolve_star_unions_with_names_without_duplicates():
    names = [spec.name for spec in resolve(["faithfulness", "*"])]
    assert names == [
        "faithfulness"
    ] + [name for name in EXPECTED_NAMES if name != "faithfulness"]


def test_resolve_empty_is_empty():
    assert resolve([]) == []


def test_resolve_unknown_metric_lists_the_registered_set():
    with pytest.raises(SpecError) as excinfo:
        resolve(["rougeX"])
    expected = (
        "unknown metric 'rougeX' (registered: "
        + ", ".join(EXPECTED_NAMES)
        + ")"
    )
    assert str(excinfo.value) == expected


def _spec(name, requires_reference=False, compute=None):
    def _compute(input):
        return 0.5

    return MetricSpec(
        name=name,
        requires_reference=requires_reference,
        compute=_compute if compute is None else compute,
    )


def test_validation_pass_rejects_names_with_whitespace():
    with pytest.raises(SpecError):
        validate([_spec("bad name")])


def test_validation_pass_rejects_uppercase_names():
    with pytest.raises(SpecError):
        validate([_spec("Faithfulness")])


def test_validation_pass_rejects_non_boolean_reference_flag():
    with pytest.raises(SpecError):
        validate([_spec("faithfulness", requires_reference="yes")])


def test_validation_pass_rejects_non_callable_compute():
    with pytest.raises(SpecError):
        validate([_spec("faithfulness", compute="not callable")])


def test_validation_pass_rejects_duplicate_names():
    with pytest.raises(SpecError):
        validate([_spec("faithfulness"), _spec("faithfulness")])


def test_validation_pass_accepts_a_clean_set():
    registry = validate([_spec("faithfulness"), _spec("other", requires_reference=True)])
    assert sorted(registry) == ["faithfulness", "other"]
