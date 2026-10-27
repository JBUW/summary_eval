"""Summarizer selection for score/generate (docs/commands.md, §score).

Named summarizers are NOT dissected into components: the component
selections form a Cartesian product, which is a set of summarizers;
specifically named summarizers are then added as extra single
combinations.
"""
from dataclasses import dataclass

from .errors import SpecError
from .identities import canonical_json


@dataclass(frozen=True)
class Summarizer:
    name: str | None
    model: str
    model_args: dict
    template: str
    gen_params: dict


def _select_tokens(tokens, configured, kind):
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
            raise SpecError(f"unknown {kind} '{token}' ({roster})")
    return selected


def _named(resolved, name):
    spec = resolved["summarizers"][name]
    return Summarizer(
        name,
        spec["model"],
        dict(spec["model_args"]),
        spec["prompt_template"],
        dict(spec["gen_params"]),
    )


def select_summarizers(resolved, summarizer_names=None, model_names=None, template_names=None):
    models = resolved.get("models") or {}
    templates = resolved.get("prompt_templates") or {}
    summarizers = resolved.get("summarizers") or {}

    if summarizer_names is None and model_names is None and template_names is None:
        result = [_named(resolved, name) for name in summarizers]
    else:
        result = []
        if model_names is not None or template_names is not None:
            model_list = _select_tokens(model_names, list(models), "model") if model_names is not None else list(models)
            template_list = (
                _select_tokens(template_names, list(templates), "prompt template")
                if template_names is not None
                else list(templates)
            )
            for model in model_list:
                entry = models[model]
                for template in template_list:
                    result.append(
                        Summarizer(
                            None,
                            model,
                            dict(entry["model_args"]),
                            template,
                            dict(entry["gen_params"]),
                        )
                    )
        if summarizer_names is not None:
            for name in _select_tokens(summarizer_names, list(summarizers), "summarizer"):
                result.append(_named(resolved, name))

    seen = {}
    for summarizer in result:
        key = (
            summarizer.model,
            canonical_json(summarizer.model_args),
            summarizer.template,
            canonical_json(summarizer.gen_params),
        )
        if key not in seen:
            seen[key] = summarizer
    return tuple(seen.values())
