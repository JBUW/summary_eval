import pytest

from evalapp.metrics import MetricInput, get

TRANSCRIPT = "One two three four five six seven eight nine ten."  # 10 words


def evaluate(generation, transcript=TRANSCRIPT):
    spec = get("conciseness_length_proxy")
    return spec.compute(
        MetricInput(transcript_text=transcript, generation_text=generation)
    )


def test_same_length_no_redundancy_scores_one():
    assert evaluate(TRANSCRIPT) == 1.0


def test_repeated_words_are_redundancy():
    generation = "One two three four five. One two three four five."
    assert evaluate(generation) == 0.5


def test_longer_than_the_transcript_scales_down():
    generation = (
        "One two three four five six seven eight nine ten "
        "eleven twelve thirteen fourteen fifteen."
    )
    assert evaluate(generation) == 10 / 15


def test_stopwords_count_towards_length():
    generation = "the the the the the the the the the the"
    assert evaluate(generation) == pytest.approx(0.1)


def test_generation_without_words_is_an_exclusion():
    assert evaluate("") is None
