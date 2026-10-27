"""Scorer resolution for score (docs/commands.md, §score).

The CLI hands this module raw flag state (Flag); resolution owns the
precedence rules, the ``[]`` no-op token, and the exit-2 SpecError wording.
Note bodies are returned for the caller to emit as ``console.note`` AFTER its
own ``plan:`` line (console stages are monotonic).
"""
from dataclasses import dataclass

from . import metrics
from .errors import SpecError

_EMPTY_BRACKET = "[]"


@dataclass(frozen=True)
class Flag:
    """Raw state of one --metrics/--judges flag family.

    value: None = flag omitted; ``"bare"`` = ``--judges`` with no tokens
    (judges axis only); otherwise the token list exactly as given, the
    ``[]`` token included.
    no: True when the matching --no-X shorthand is present.
    """

    value: str | list[str] | None = None
    no: bool = False


@dataclass(frozen=True)
class ResolvedScorers:
    metrics: tuple
    judges: tuple
    notes: tuple


def resolve_scorers(resolved, metrics_flag, judges_flag):
    if metrics_flag.no and metrics_flag.value is not None:
        raise SpecError("--no-metrics is mutually exclusive with --metrics")
    if judges_flag.no and judges_flag.value is not None:
        raise SpecError("--no-judges is mutually exclusive with --judges")

    tokens = _metric_tokens(resolved, metrics_flag)
    metric_names = tuple(spec.name for spec in metrics.resolve(tokens))
    judges, notes = _judge_names(resolved, judges_flag)
    return ResolvedScorers(metrics=metric_names, judges=judges, notes=tuple(notes))


def _without_empty_bracket(tokens):
    return [token for token in tokens if token != _EMPTY_BRACKET]


def _metric_tokens(resolved, flag):
    if flag.no:
        return []
    if flag.value is None:
        default = resolved["defaults"]["metrics"]
        if default is None:
            return ["*"]
        return _without_empty_bracket(list(default))
    return _without_empty_bracket(list(flag.value))


def _judge_names(resolved, flag):
    notes = []
    if flag.no or flag.value is None:
        return (), notes
    if flag.value == "bare":
        default = resolved["defaults"]["judges"]
        if default is None:
            tokens = list(resolved["judges"])
        elif default:
            tokens = _without_empty_bracket(list(default))
        else:
            notes.append(
                "--judges given but default_judges is empty; no judges run"
            )
            return (), notes
    else:
        tokens = _without_empty_bracket(list(flag.value))
    return _select_judge_tokens(tokens, resolved), notes


def _select_judge_tokens(tokens, resolved):
    configured = list(resolved["judges"])
    roster = ", ".join(configured) if configured else "none configured"
    selected = []
    for token in tokens:
        if token == "*":
            for name in configured:
                if name not in selected:
                    selected.append(name)
        elif token in configured:
            if token not in selected:
                selected.append(token)
        else:
            raise SpecError(f"unknown judge '{token}' ({roster})")
    return tuple(selected)
