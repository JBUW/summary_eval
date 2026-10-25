"""Key-claim completeness: how much of the reference summary the generation covers.

The reference summary is treated as the annotated key-claim set: its content
sentences are the key claims, and only those claims count. A key claim is
covered when at least half of its distinct content tokens appear among the
generation's distinct content tokens (integer math: 2 * shared >= total). The
value is the fraction of covered key claims. A missing (or empty) reference,
or one without content sentences, is an exclusion (None).
"""

from ._spec import MetricInput, MetricSpec, register
from ._text import content_sentences, content_tokens


def compute(m_input: MetricInput) -> float | None:
    reference = m_input.reference_summary_text
    if not reference:
        return None
    claims = content_sentences(reference)
    if not claims:
        return None
    generation = content_tokens(m_input.generation_text)
    covered = 0
    for claim in claims:
        claim_tokens = content_tokens(claim)
        if len(claim_tokens & generation) * 2 >= len(claim_tokens):
            covered += 1
    return covered / len(claims)


register(
    MetricSpec(
        name="key_claim_completeness",
        requires_reference=True,
        compute=compute,
    )
)
