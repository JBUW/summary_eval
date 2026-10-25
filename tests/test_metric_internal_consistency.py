import pytest

from evalapp.metrics import MetricInput, get


def evaluate(generation):
    spec = get("internal_consistency")
    return spec.compute(
        MetricInput(transcript_text="transcript", generation_text=generation)
    )


def test_pairwise_contradiction_scores_zero():
    generation = (
        "The budget is two hundred dollars. "
        "The budget is not two hundred dollars."
    )
    assert evaluate(generation) == 0.0


def test_non_contradictory_claims_score_one():
    generation = "The budget is two hundred dollars. Alice sends the report."
    assert evaluate(generation) == 1.0


def test_one_of_three_pairs_contradicts():
    generation = "The plan is done. The plan is not done. Alice left early."
    assert evaluate(generation) == pytest.approx(2 / 3)


def test_negation_by_contraction_counts():
    generation = "The plan is done. The plan isn't done."
    assert evaluate(generation) == 0.0


def test_fewer_than_two_claims_is_an_exclusion():
    assert evaluate("The budget is two hundred dollars.") is None
    assert evaluate("") is None
