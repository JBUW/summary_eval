"""Conciseness length proxy: a measurable stand-in for conciseness.

Short is measurable, concise is not — so this metric measures length only,
never content. Redundancy is the fraction of repeated tokens in the
generation (1 - distinct/total, over ALL tokens, stopwords included: length
is length); the length factor is min(1, transcript tokens / generation
tokens), so a generation longer than the transcript scales down. The value
is (1 - redundancy) * length_factor. A generation with no tokens is an
exclusion (None).
"""

from ._spec import MetricInput, MetricSpec, register
from ._text import tokens


def compute(m_input: MetricInput) -> float | None:
    generation = tokens(m_input.generation_text)
    if not generation:
        return None
    redundancy = 1.0 - len(set(generation)) / len(generation)
    length_factor = min(1.0, len(tokens(m_input.transcript_text)) / len(generation))
    return (1.0 - redundancy) * length_factor


register(
    MetricSpec(
        name="conciseness_length_proxy",
        requires_reference=False,
        compute=compute,
    )
)
