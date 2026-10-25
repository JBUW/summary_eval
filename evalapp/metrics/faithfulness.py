"""Faithfulness: how much of what the generation claims is in the transcript.

The generation's content sentences (sentences with at least one non-stopword
token) are its claims. A claim is faithful when at least half of its distinct
content tokens also appear among the transcript's distinct content tokens
(integer math: 2 * shared >= total). The value is the fraction of faithful
claims. A generation with no content sentences is an exclusion (None), never
a score.
"""

from ._spec import MetricInput, MetricSpec, register
from ._text import content_sentences, content_tokens


def compute(m_input: MetricInput) -> float | None:
    claims = content_sentences(m_input.generation_text)
    if not claims:
        return None
    transcript = content_tokens(m_input.transcript_text)
    faithful = 0
    for claim in claims:
        claim_tokens = content_tokens(claim)
        if len(claim_tokens & transcript) * 2 >= len(claim_tokens):
            faithful += 1
    return faithful / len(claims)


register(MetricSpec(name="faithfulness", requires_reference=False, compute=compute))
