"""Structural instruction check: does the generation follow the prompt's structure?

Requirements are extracted from the prompt text:
- every prompt line mentioning "section" (case-insensitive) contributes one
  requirement per quoted phrase ('...' or "...") on that line — the quoted
  title must appear, case-insensitively, as a substring of the generation;
- if the prompt mentions "action item" (case-insensitive), one requirement
  is contributed — the generation must contain at least one bullet line
  (matching ^\\s*[-*]\\s+\\S).

With zero requirements the check is vacuously satisfied (1.0), so this metric
is never an exclusion. The value is the fraction of satisfied requirements.
"""

import re

from ._spec import MetricInput, MetricSpec, register

_QUOTED_PATTERN = re.compile(r"'([^']+)'|\"([^\"]+)\"")
_BULLET_PATTERN = re.compile(r"^\s*[-*]\s+\S")


def _requirements(prompt_text: str) -> list[str | None]:
    """Required section titles (strings); None stands for the bullet rule."""
    requirements: list[str | None] = []
    for line in prompt_text.splitlines():
        if "section" in line.lower():
            for single, double in _QUOTED_PATTERN.findall(line):
                requirements.append((single or double).lower())
    if "action item" in prompt_text.lower():
        requirements.append(None)
    return requirements


def compute(m_input: MetricInput) -> float | None:
    requirements = _requirements(m_input.prompt_text)
    if not requirements:
        return 1.0
    lowered_generation = m_input.generation_text.lower()
    has_bullet = any(
        _BULLET_PATTERN.match(line)
        for line in m_input.generation_text.splitlines()
    )
    satisfied = 0
    for title in requirements:
        if title is None:
            if has_bullet:
                satisfied += 1
        elif title in lowered_generation:
            satisfied += 1
    return satisfied / len(requirements)


register(
    MetricSpec(
        name="structural_instruction_check",
        requires_reference=False,
        compute=compute,
    )
)
