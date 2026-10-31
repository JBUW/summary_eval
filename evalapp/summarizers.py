"""Summarizers: selection for score/generate (docs/commands.md, §score)
and the generation-identity inputs of a summarizer.

Named summarizers are NOT dissected into components: the component
selections form a Cartesian product, which is a set of summarizers;
specifically named summarizers are then added as extra single
combinations.

SummarizerInputsCache reads each model file and each prompt template at
most once per cache; a command creates one cache and shares it across its
steps. Model files are hashed in chunks, never held whole in memory.
"""
import hashlib
from dataclasses import dataclass

from .errors import RuntimeFailure, SpecError
from .identities import canonical_json, template_id
from .templates import Template, load_template

_MODEL_CHUNK = 1 << 20


@dataclass(frozen=True)
class Summarizer:
    name: str | None
    model: str
    model_args: dict
    template: str
    gen_params: dict

    @property
    def key(self):
        """The four components that make two summarizers the same."""
        return (
            self.model,
            canonical_json(self.model_args),
            self.template,
            canonical_json(self.gen_params),
        )


@dataclass(frozen=True)
class SummarizerInputs:
    model_sha: str
    template: Template
    template_sha: str


class SummarizerInputsCache:
    """The generation-identity inputs of summarizers: the model hash is
    cached per model, the template (with its hash) per template."""

    def __init__(self, resolved):
        self._resolved = resolved
        self._model_shas = {}
        self._templates = {}

    def inputs(self, summarizer):
        model_sha = self._model_shas.get(summarizer.model)
        if model_sha is None:
            model_sha = self._hash_model(summarizer.model)
            self._model_shas[summarizer.model] = model_sha
        template, template_sha = self._template(summarizer.template)
        return SummarizerInputs(model_sha, template, template_sha)

    def template(self, name):
        return self._template(name)[0]

    def _template(self, name):
        cached = self._templates.get(name)
        if cached is None:
            template = load_template(
                name, self._resolved["prompt_templates"][name]
            )
            cached = (
                template,
                template_id(template.system_content, template.user_prefix),
            )
            self._templates[name] = cached
        return cached

    def _hash_model(self, model):
        path = self._resolved["models"][model]["path"]
        digest = hashlib.sha256()
        try:
            with open(path, "rb") as handle:
                while chunk := handle.read(_MODEL_CHUNK):
                    digest.update(chunk)
        except FileNotFoundError:
            raise RuntimeFailure(
                f"model '{model}': file not found: {path}"
            ) from None
        except OSError as exc:
            detail = getattr(exc, "strerror", None) or exc
            raise RuntimeFailure(
                f"model '{model}': cannot read {path}: {detail}"
            ) from None
        return digest.hexdigest()


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


def named_summarizer(resolved, name):
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
        result = [named_summarizer(resolved, name) for name in summarizers]
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
                result.append(named_summarizer(resolved, name))

    seen = {}
    for summarizer in result:
        seen.setdefault(summarizer.key, summarizer)
    return tuple(seen.values())
