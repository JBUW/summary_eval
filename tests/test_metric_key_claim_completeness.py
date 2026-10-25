from evalapp.metrics import MetricInput, get

REFERENCE = "The team chose the red design. Budget is two hundred dollars."


def evaluate(generation, reference):
    spec = get("key_claim_completeness")
    return spec.compute(
        MetricInput(
            transcript_text="transcript",
            generation_text=generation,
            reference_summary_text=reference,
        )
    )


def test_every_key_claim_is_covered():
    generation = "The team chose the red design and the budget is two hundred dollars."
    assert evaluate(generation, REFERENCE) == 1.0


def test_half_the_key_claims_are_covered():
    generation = "The team chose the red design."
    assert evaluate(generation, REFERENCE) == 0.5


def test_no_key_claim_is_covered():
    generation = "Nothing was decided."
    assert evaluate(generation, REFERENCE) == 0.0


def test_missing_reference_is_an_exclusion():
    assert evaluate("The team chose the red design.", None) is None


def test_reference_without_key_claims_is_an_exclusion():
    assert evaluate("The team chose the red design.", "The. The.") is None
