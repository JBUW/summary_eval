"""Parse raw judge responses into structured quality values.

This module is the program's single trust boundary for judge output: raw,
untrusted text goes in and a structured, policy-checked outcome comes out.
It is pure — no I/O, no configuration, no store, no network.

Forgiveness contract. Judge responses are LLM text, so the parser forgives
surrounding prose, markdown fences, unknown labels, and any other unknown
content: only a quality label followed (within a few characters of
whitespace or punctuation) by a number counts as a value. Identical
duplicate values are accepted — an integer and its decimal form, ``1`` and
``1.0``, are the same value. What the parser does not forgive: a quality
whose label is misspelled is treated as *missing* (there is no fuzzy label
matching), a quality with conflicting values is ambiguous and is excluded
with a warning rather than guessed at, and out-of-scale values are
recorded as out-of-range warnings with the raw value — never clamped.

Parse policy. When any quality is missing, conflicting, or out of range,
the outcome carries one warning per affected quality, emitted in
:data:`QUALITIES` order. Whether such an outcome is *rejected* (no values
at all) or *partially accepted* (only the clean qualities) is governed by
the module constant :data:`ACCEPT_PARTIAL_RESULTS`, which defaults to off:
partial results are rejected wholesale, and the caller is expected to warn,
record the exclusion, and commit no judge row.

Naming discipline: the recorded raw responses paired with expected
outcomes are golden *fixtures* (input at this seam); they stay distinct
from the glossary's *golden set* (the curated, documented subset of a
dataset).
"""
import re
from dataclasses import dataclass

# Exactly the quality column names of judge_evaluations (docs/store-schema.md).
QUALITIES = ("factual_correctness", "completeness", "conciseness")

# Quality values are fractions; the documented rows and report examples
# (docs/store-schema.md, docs/commands.md) all use 0.0-1.0.
QUALITY_SCALE = (0.0, 1.0)

# Read at call time; tests monkeypatch it to exercise partial acceptance.
ACCEPT_PARTIAL_RESULTS = False

# Between a label and its number: up to eight whitespace or punctuation
# characters only — no letters, digits, or minus signs.
_GAP = r"[\s:;,\"'()\[\]{}*#=]{0,8}"
_NUMBER = r"-?(?:\d+(?:\.\d+)?|\.\d+)"


def _label_pattern(quality: str) -> re.Pattern[str]:
    words = [re.escape(word) for word in quality.split("_")]
    return re.compile(
        r"(?<![\w-])" + r"[_\- ]".join(words) + r"(?![\w-])" + _GAP + r"(" + _NUMBER + r")",
        re.IGNORECASE,
    )


_LABEL_PATTERNS = {quality: _label_pattern(quality) for quality in QUALITIES}


@dataclass(frozen=True)
class JudgeParse:
    values: dict[str, float]
    rejected: bool
    warnings: tuple[str, ...]


def parse_judge_response(raw_text: str) -> JudgeParse:
    values: dict[str, float] = {}
    warnings: list[str] = []
    for quality in QUALITIES:
        numbers = [
            float(match.group(1))
            for match in _LABEL_PATTERNS[quality].finditer(raw_text)
        ]
        if not numbers:
            warnings.append(f"quality '{quality}' missing from judge response")
        elif len(set(numbers)) > 1:
            warnings.append(
                f"quality '{quality}' conflicting values in judge response: "
                + ", ".join(repr(number) for number in numbers)
            )
        elif not QUALITY_SCALE[0] <= numbers[0] <= QUALITY_SCALE[1]:
            warnings.append(
                f"quality '{quality}' out of range in judge response: "
                f"{numbers[0]!r} (scale {QUALITY_SCALE[0]}-{QUALITY_SCALE[1]})"
            )
        else:
            values[quality] = numbers[0]
    if warnings and not ACCEPT_PARTIAL_RESULTS:
        return JudgeParse(values={}, rejected=True, warnings=tuple(warnings))
    return JudgeParse(values=values, rejected=False, warnings=tuple(warnings))
