"""Shared metric data types and the passive registration list.

A MetricSpec is a frozen triple: a lowercase name, whether the metric
requires a reference summary, and the pure function that computes its
value (a number in [0, 1], or None to exclude the item). Metric modules
call register() at import time; nothing in the package enumerates which
metrics exist — discovery simply imports the modules and whatever they
registered is the set.
"""

from dataclasses import dataclass
from typing import Callable

__all__ = ["MetricInput", "MetricSpec", "all_specs", "register"]


@dataclass(frozen=True)
class MetricInput:
    """The texts handed to every metric's compute function."""

    transcript_text: str
    generation_text: str
    reference_summary_text: str | None = None
    prompt_text: str = ""


@dataclass(frozen=True)
class MetricSpec:
    """A registered metric: name, reference requirement, value contract."""

    name: str
    requires_reference: bool
    compute: Callable[[MetricInput], float | None]


_SPECS: list[MetricSpec] = []


def register(spec: MetricSpec) -> None:
    """Append a spec to the passive registration list (import-time hook)."""
    _SPECS.append(spec)


def all_specs() -> list[MetricSpec]:
    """A copy of everything registered so far."""
    return list(_SPECS)
