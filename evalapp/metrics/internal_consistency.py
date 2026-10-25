"""Internal consistency: do the generation's own claims contradict each other?

Claims are the generation's content sentences. A claim is negated when any
of its raw tokens (stopwords included, so bare "not", "no", "cannot" and
contractions like "isn't" all count) is a negation word. A pair of claims
contradicts when they share at least one content token and exactly one of
the two is negated. The value is 1 - contradictions/total_pairs over all
claim pairs. Fewer than two claims is an exclusion (None). This is a cheap
heuristic with low yield — the first metric to cut if it stays vacuous.
"""

from ._spec import MetricInput, MetricSpec, register
from ._text import NEGATION_WORDS, content_sentences, content_tokens, tokens


def compute(m_input: MetricInput) -> float | None:
    claims = content_sentences(m_input.generation_text)
    if len(claims) < 2:
        return None
    claim_tokens = [content_tokens(claim) for claim in claims]
    negated = [bool(set(tokens(claim)) & NEGATION_WORDS) for claim in claims]
    total_pairs = 0
    contradictions = 0
    for i in range(len(claims)):
        for j in range(i + 1, len(claims)):
            total_pairs += 1
            if claim_tokens[i] & claim_tokens[j] and negated[i] != negated[j]:
                contradictions += 1
    return 1.0 - contradictions / total_pairs


register(
    MetricSpec(
        name="internal_consistency",
        requires_reference=False,
        compute=compute,
    )
)
