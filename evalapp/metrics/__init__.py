"""The v1 metrics registry.

Discovery: at import time every module in this package that does not start
with an underscore is imported, and each metric module registers its
MetricSpec at import. The registered specs then go through one assembly-time
validation pass (validate); any violation raises SpecError and the import
fails. Excluding a metric from a run is not storing anything special — a
metric that is not selected simply never runs.
"""

import importlib
import pkgutil
import re

from ..errors import SpecError
from ._spec import MetricInput, MetricSpec, all_specs, register

__all__ = [
    "MetricInput",
    "MetricSpec",
    "all_specs",
    "get",
    "register",
    "registered_names",
    "resolve",
    "validate",
]

_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def validate(specs: list[MetricSpec]) -> dict[str, MetricSpec]:
    """The single assembly-time validation pass.

    Pure: takes a list of specs and returns a name -> spec registry sorted
    by name, or raises SpecError on the first violation.
    """
    registry: dict[str, MetricSpec] = {}
    for spec in specs:
        if not _NAME_PATTERN.match(spec.name):
            raise SpecError(
                f"metric spec: invalid name {spec.name!r} "
                "(must match '^[a-z][a-z0-9_]*$')"
            )
        if not isinstance(spec.requires_reference, bool):
            raise SpecError(
                f"metric '{spec.name}': requires_reference must be a bool, "
                f"got {spec.requires_reference!r}"
            )
        if not callable(spec.compute):
            raise SpecError(f"metric '{spec.name}': compute must be callable")
        if spec.name in registry:
            raise SpecError(f"metric '{spec.name}' is registered more than once")
        registry[spec.name] = spec
    return dict(sorted(registry.items()))


def _discover() -> None:
    """Import every public module in this package so it can register."""
    for module_info in pkgutil.iter_modules(__path__):
        if module_info.name.startswith("_"):
            continue
        importlib.import_module(f"{__name__}.{module_info.name}")


def _unknown_metric(name: str) -> str:
    return f"unknown metric '{name}' (registered: {', '.join(registered_names())})"


_discover()
_REGISTRY = validate(all_specs())


def registered_names() -> tuple[str, ...]:
    """Every registered metric name, sorted."""
    return tuple(_REGISTRY)


def get(name: str) -> MetricSpec:
    """The spec registered under name; SpecError if there is none."""
    if name in _REGISTRY:
        return _REGISTRY[name]
    raise SpecError(_unknown_metric(name))


def resolve(tokens: list[str]) -> list[MetricSpec]:
    """Resolve a selection list to specs.

    ``*`` expands to every registered metric, sorted; names keep their given
    order; duplicates collapse to the first occurrence; an unknown name
    raises SpecError listing the registered set.
    """
    resolved: list[MetricSpec] = []
    seen: set[str] = set()
    for token in tokens:
        names = registered_names() if token == "*" else (token,)
        for name in names:
            if name in seen:
                continue
            spec = get(name)
            seen.add(name)
            resolved.append(spec)
    return resolved
