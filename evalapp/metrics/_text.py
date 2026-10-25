"""Shared text primitives for the v1 metrics.

Tokenization is deliberately coarse: words are runs of lowercase letters,
digits, and apostrophes, so contractions ("isn't") survive as single tokens.
Stopword removal is only used where a metric measures *meaning* (claims);
metrics that measure *length* count every token.
"""

import re

TOKEN_PATTERN = re.compile(r"[a-z0-9']+")
SENTENCE_PATTERN = re.compile(r"[^.!?]*[.!?]+|[^.!?]+$")

STOPWORDS = frozenset((
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "but",
    "by", "can", "cannot", "did", "does", "do", "had", "has", "have",
    "he", "her", "his", "i", "if", "in", "into", "is", "it", "its",
    "just", "me", "more", "most", "no", "nor", "not", "of", "off", "on",
    "once", "only", "or", "other", "our", "out", "over", "own", "she",
    "so", "some", "such", "than", "that", "the", "their", "them", "then",
    "there", "these", "they", "this", "to", "too", "under", "until", "up",
    "very", "was", "we", "were", "what", "when", "which", "who", "whom",
    "why", "will", "with", "within", "you", "your",
))

NEGATION_WORDS = frozenset((
    "cannot", "can't", "didn't", "doesn't", "don't", "isn't", "aren't",
    "wasn't", "weren't", "won't", "no", "not", "never", "none", "neither",
    "nor",
))


def tokens(text: str) -> list[str]:
    """All raw lowercase word tokens, in order (apostrophes kept)."""
    return TOKEN_PATTERN.findall(text.lower())


def content_tokens(text: str) -> set[str]:
    """The distinct non-stopword tokens of text."""
    return set(tokens(text)) - STOPWORDS


def sentences(text: str) -> list[str]:
    """Text split on sentence-final punctuation; empty pieces dropped."""
    return [piece.strip() for piece in SENTENCE_PATTERN.findall(text) if piece.strip()]


def content_sentences(text: str) -> list[str]:
    """The sentences of text that contain at least one content token."""
    return [sentence for sentence in sentences(text) if content_tokens(sentence)]
