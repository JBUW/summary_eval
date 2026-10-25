from evalapp.metrics import MetricInput, get

TRANSCRIPT = "Alice will send the report by Friday. Bob handles the budget."


def evaluate(generation, transcript=TRANSCRIPT):
    spec = get("faithfulness")
    return spec.compute(
        MetricInput(transcript_text=transcript, generation_text=generation)
    )


def test_half_the_claims_are_faithful():
    generation = "Alice will send the report by Friday. The team is happy."
    assert evaluate(generation) == 0.5


def test_every_claim_is_faithful():
    generation = "Bob will handle the budget. Bob owns the budget now."
    assert evaluate(generation) == 1.0


def test_no_claim_is_faithful():
    generation = "The meeting went well. Everyone left early."
    assert evaluate(generation) == 0.0


def test_generation_without_claims_is_an_exclusion():
    assert evaluate("...") is None
    assert evaluate("") is None


def test_generation_full_of_stopwords_is_an_exclusion():
    assert evaluate("The. The. The.") is None
