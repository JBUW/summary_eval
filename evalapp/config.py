import json

from . import metrics
from .errors import SpecError

DEFAULT_CONFIG_NAME = "config.json"
DEFAULT_STORE_NAME = "store.db"

KNOWN_TOP_LEVEL_FIELDS = (
    "store",
    "server",
    "models",
    "prompt_templates",
    "summarizers",
    "datasets",
    "judges",
    "default_judges",
    "default_metrics",
)

KNOWN_SERVER_FIELDS = ("command", "args", "env", "port", "startup_timeout_s")

# Entry fields recognized per section. The summarizer's `path` key is
# deliberately absent here: it has its own dedicated error and is exempt
# from the warn scan.
KNOWN_ENTRY_FIELDS = {
    "models": ("path", "model_args", "gen_params"),
    "prompt_templates": ("path",),
    "summarizers": ("base", "model", "prompt_template", "model_args", "gen_params"),
    "datasets": ("path", "transcript_field", "reference_field", "entry_id_field"),
    "judges": (
        "endpoint",
        "model_name",
        "api_key_env",
        "requires_reference",
        "user_template",
        "gen_params",
        "system_content",
    ),
}


class _Pairs:
    """Marker wrapping the raw (key, value) pairs of one JSON object.

    A distinct type (not a bare list) so an object's pair list can never be
    confused with a JSON array while the tree is still being walked.
    """

    def __init__(self, pairs):
        self.pairs = pairs


def _object_pairs_hook(pairs):
    return _Pairs(pairs)


def load_config(path, explicit, console, errors=None):
    """Load the configuration file, returning the parsed object.

    ``path`` is the configured name; ``explicit`` says whether the user
    passed --config. All failures are SpecError (exit 2). When ``errors``
    (a list) is given, duplicate-name errors are appended to it instead of
    raised — the collect mode used by check; file and JSON failures always
    raise.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except FileNotFoundError:
        if explicit:
            raise SpecError(f"config file not found: {path}") from None
        raise SpecError(
            f"config file not found: {DEFAULT_CONFIG_NAME} "
            "(pass --config PATH to use another)"
        ) from None
    except OSError as exc:
        raise SpecError(f"cannot read config file: {path}: {exc.strerror or exc}") from None
    try:
        parsed = json.loads(text, object_pairs_hook=_object_pairs_hook)
    except json.JSONDecodeError as exc:
        raise SpecError(f"invalid JSON in {path}: {exc}") from None
    config = _convert(parsed, "config", errors, top_level=True)
    if not isinstance(config, dict):
        raise SpecError(f"invalid JSON in {path}: top-level value must be an object")
    _warn_unrecognized(config, console, sections_only=False)
    return config


def _convert(node, location, errors=None, top_level=False):
    if isinstance(node, _Pairs):
        seen = set()
        converted = {}
        for key, value in node.pairs:
            if key in seen:
                message = f"duplicate name '{key}' in {location}"
                if errors is not None:
                    errors.append(message)
                else:
                    raise SpecError(message)
            seen.add(key)
            converted[key] = _convert(value, key if top_level else location, errors)
        return converted
    if isinstance(node, list):
        return [_convert(item, location, errors) for item in node]
    return node


def _warn_unrecognized(config, console, sections_only):
    """Emit unrecognized-field warns per the strict contract.

    ``sections_only=False`` scans the top level only; ``True`` scans
    config.server plus the five section entry levels, walking the config in
    file order. Open maps (server.args, model_args, gen_params, env values)
    are exempt.
    """
    if not isinstance(config, dict):
        return
    if not sections_only:
        for key in config:
            if key not in KNOWN_TOP_LEVEL_FIELDS:
                console.warn(f"unrecognized field '{key}' in config")
        return
    for key, value in config.items():
        if key == "server":
            if not isinstance(value, dict):
                continue
            for field in value:
                if field not in KNOWN_SERVER_FIELDS:
                    console.warn(f"unrecognized field '{field}' in config.server")
        elif key in KNOWN_ENTRY_FIELDS:
            if not isinstance(value, dict):
                continue
            for name, entry in value.items():
                if not isinstance(entry, dict):
                    continue
                for field in entry:
                    if key == "summarizers" and field == "path":
                        continue
                    if field not in KNOWN_ENTRY_FIELDS[key]:
                        console.warn(f"unrecognized field '{field}' in {key}.{name}")


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_valid_name(name):
    return name != "" and not any(char.isspace() for char in name)


def _has_type(value, kind):
    return isinstance(value, str) if kind == "string" else isinstance(value, dict)


def validate_config(config, console):
    """Check the full strict contract of the configuration.

    Returns (errors, resolved): ``errors`` is a list of bare error messages
    (no ``error:`` prefix); ``resolved`` holds the resolved shape of the
    parts that passed. check and generate call this; errors are collected
    and returned, never raised.
    """
    errors = []
    resolved = {
        "store": None,
        "server": None,
        "models": {},
        "prompt_templates": {},
        "summarizers": {},
        "datasets": {},
        "judges": {},
        "defaults": {"metrics": None, "judges": None},
    }
    _warn_unrecognized(config, console, sections_only=True)
    _check_top_level(config, errors, resolved)
    _resolve_summarizers(config, errors, resolved)
    _check_defaults(config, errors, resolved)
    return errors, resolved


def _check_top_level(config, errors, resolved):
    for key, value in config.items():
        if key == "store":
            if isinstance(value, str) and value:
                resolved["store"] = value
            else:
                errors.append("config 'store' must be a non-empty string")
        elif key == "server":
            _check_server(value, errors, resolved)
        elif key in KNOWN_ENTRY_FIELDS:
            _check_section(key, value, errors, resolved)


def _check_server(server, errors, resolved):
    if not isinstance(server, dict):
        errors.append("config 'server' must be an object")
        return
    resolved["server"] = server
    for field in ("command", "args", "env"):
        kind = "string" if field == "command" else "object"
        if field in server and not _has_type(server[field], kind):
            errors.append(f"server: field '{field}' must be {'an' if kind == 'object' else 'a'} {kind}")
    for field in ("port", "startup_timeout_s"):
        if not _is_number(server.get(field)):
            errors.append(f"server: field '{field}' is required and must be a number")


def _check_section(section, entries, errors, resolved):
    if not isinstance(entries, dict):
        errors.append(f"{section} must be an object mapping names to entries")
        return
    for name, entry in entries.items():
        if name == "*":
            errors.append("name '*' is reserved")
            continue
        if not _is_valid_name(name):
            errors.append(f"invalid name '{name}' in {section}")
            continue
        if section == "models":
            _check_model_entry(name, entry, errors, resolved)
        elif section == "prompt_templates":
            _check_template_entry(name, entry, errors, resolved)
        elif section == "summarizers":
            _check_summarizer_entry(name, entry, errors)
        elif section == "datasets":
            _check_dataset_entry(name, entry, errors, resolved)
        else:
            _check_judge_entry(name, entry, errors, resolved)


def _check_model_entry(name, entry, errors, resolved):
    if not isinstance(entry, dict):
        errors.append(f"model '{name}': entry must be an object")
        return
    valid = True
    for field in ("path", "model_args", "gen_params"):
        kind = "string" if field == "path" else "object"
        if field in entry and not _has_type(entry[field], kind):
            errors.append(f"model '{name}': field '{field}' must be {'an' if kind == 'object' else 'a'} {kind}")
            valid = False
    if valid:
        resolved["models"][name] = {
            "path": entry.get("path"),
            "model_args": entry.get("model_args") or {},
            "gen_params": entry.get("gen_params") or {},
        }


def _check_template_entry(name, entry, errors, resolved):
    if not isinstance(entry, dict):
        errors.append(f"prompt template '{name}': entry must be an object")
        return
    if "path" in entry and not isinstance(entry["path"], str):
        errors.append(f"prompt template '{name}': field 'path' must be a string")
        return
    resolved["prompt_templates"][name] = entry.get("path")


def _check_summarizer_entry(name, entry, errors):
    if not isinstance(entry, dict):
        errors.append(f"summarizer '{name}': entry must be an object")
        return
    if "path" in entry:
        errors.append(
            f"summarizer '{name}': field 'path' is not allowed — "
            "the model path is fixed by the model entry"
        )
    for field in ("base", "model", "prompt_template"):
        if field in entry and not isinstance(entry[field], str):
            errors.append(f"summarizer '{name}': field '{field}' must be a string")
    for field in ("model_args", "gen_params"):
        if field in entry and not isinstance(entry[field], dict):
            errors.append(f"summarizer '{name}': field '{field}' must be an object")


def _check_dataset_entry(name, entry, errors, resolved):
    if not isinstance(entry, dict):
        errors.append(f"dataset '{name}': entry must be an object")
        return
    valid = True
    for field in ("path", "transcript_field"):
        if not isinstance(entry.get(field), str):
            errors.append(f"dataset '{name}': field '{field}' must be a string")
            valid = False
    for field in ("reference_field", "entry_id_field"):
        if field in entry and not isinstance(entry[field], str):
            errors.append(f"dataset '{name}': field '{field}' must be a string")
            valid = False
    if not valid:
        return
    declaration = {
        "path": entry["path"],
        "transcript_field": entry["transcript_field"],
        "reference_field": None,
        "entry_id_field": None,
    }
    for field in ("reference_field", "entry_id_field"):
        if field in entry:
            declaration[field] = entry[field]
    resolved["datasets"][name] = declaration


def _check_judge_entry(name, entry, errors, resolved):
    if not isinstance(entry, dict):
        errors.append(f"judge '{name}': entry must be an object")
        return
    for field in ("endpoint", "model_name", "api_key_env", "user_template"):
        if field in entry and not isinstance(entry[field], str):
            errors.append(f"judge '{name}': field '{field}' must be a string")
    if not isinstance(entry.get("requires_reference"), bool):
        errors.append(
            f"judge '{name}': requires_reference is required and must be a boolean"
        )
    if "gen_params" in entry and not isinstance(entry["gen_params"], dict):
        errors.append(f"judge '{name}': field 'gen_params' must be an object")
    if "system_content" in entry and not isinstance(entry["system_content"], str):
        errors.append(f"judge '{name}': field 'system_content' must be a string")
    _check_judge_placeholders(name, entry, errors)
    resolved["judges"][name] = entry


def _check_judge_placeholders(name, entry, errors):
    user = entry.get("user_template")
    flag = entry.get("requires_reference")
    if not isinstance(user, str) or not isinstance(flag, bool):
        return
    system = entry.get("system_content")
    combined = (system if isinstance(system, str) else "") + user
    if "{transcript}" not in combined:
        errors.append(f"judge '{name}': missing placeholder '{{transcript}}'")
    if "{summary}" not in combined:
        errors.append(f"judge '{name}': missing placeholder '{{summary}}'")
    if flag and "{reference}" not in combined:
        errors.append(
            f"judge '{name}': requires_reference is true but "
            "placeholder '{reference}' is missing"
        )


def _resolve_summarizers(config, errors, resolved):
    section = config.get("summarizers")
    if not isinstance(section, dict):
        return
    names = list(section)
    models = config.get("models")
    if not isinstance(models, dict):
        models = {}
    templates = config.get("prompt_templates")
    if not isinstance(templates, dict):
        templates = {}
    resolved_specs = {}
    for name, entry in section.items():
        if not isinstance(entry, dict):
            continue
        model = None
        template = None
        args_baseline = {}
        params_baseline = {}
        if "base" in entry:
            base = entry.get("base")
            earlier = (
                isinstance(base, str)
                and base in names
                and names.index(base) < names.index(name)
            )
            if not earlier:
                errors.append(
                    f"summarizer '{name}': base '{base}' must appear earlier in the file"
                )
            else:
                spec = resolved_specs.get(base)
                if spec is not None:
                    model = spec["model"]
                    template = spec["prompt_template"]
                    args_baseline = spec["model_args"]
                    params_baseline = spec["gen_params"]
        if "model" in entry:
            model = entry["model"]
            args_baseline = _model_entry_baseline(models, model, "model_args")
            params_baseline = _model_entry_baseline(models, model, "gen_params")
        if "prompt_template" in entry:
            template = entry["prompt_template"]
        child_args = entry.get("model_args")
        if not isinstance(child_args, dict):
            child_args = {}
        child_params = entry.get("gen_params")
        if not isinstance(child_params, dict):
            child_params = {}
        failed = False
        if not _is_resolvable(model, models):
            errors.append(
                f"summarizer '{name}': component 'model' not resolvable "
                "(set it directly or via a base chain)"
            )
            failed = True
        if not _is_resolvable(template, templates):
            errors.append(
                f"summarizer '{name}': component 'prompt_template' not resolvable "
                "(set it directly or via a base chain)"
            )
            failed = True
        if not failed:
            spec = {
                "model": model,
                "model_args": {**args_baseline, **child_args},
                "prompt_template": template,
                "gen_params": {**params_baseline, **child_params},
            }
            resolved["summarizers"][name] = spec
            resolved_specs[name] = spec


def _is_resolvable(name, section):
    return isinstance(name, str) and name in section


def _model_entry_baseline(models, model, field):
    entry = models.get(model) if isinstance(model, str) else None
    if not isinstance(entry, dict):
        return {}
    value = entry.get(field)
    return value if isinstance(value, dict) else {}


def _check_defaults(config, errors, resolved):
    resolved["defaults"] = {
        "metrics": config.get("default_metrics"),
        "judges": config.get("default_judges"),
    }
    judges = config.get("judges")
    judge_names = list(judges) if isinstance(judges, dict) else []
    _check_default_list(
        config,
        "default_metrics",
        errors,
        metrics.registered_names(),
        metrics._unknown_metric,
    )
    _check_default_list(
        config,
        "default_judges",
        errors,
        judge_names,
        lambda name: (
            f"unknown judge '{name}' "
            f"(configured: {', '.join(judge_names) or '(none)'})"
        ),
    )


def _check_default_list(config, key, errors, universe, unknown):
    if key not in config:
        return
    value = config[key]
    if not isinstance(value, list):
        errors.append(f"{key} must be a list of strings")
        return
    if any(not isinstance(item, str) for item in value):
        errors.append(f"{key}: entries must be strings")
    seen = set()
    for item in value:
        if not isinstance(item, str) or item in seen:
            continue
        seen.add(item)
        if item not in universe:
            errors.append(unknown(item))


# --- fail-fast helpers for the run commands (unchanged behavior) ---


def validate_datasets(config):
    """Return the declared datasets as an ordered name -> declaration dict."""
    datasets = config.get("datasets", {})
    if not isinstance(datasets, dict):
        raise SpecError("datasets must be an object mapping names to entries")
    validated = {}
    for name, entry in datasets.items():
        if not isinstance(entry, dict):
            raise SpecError(f"dataset '{name}': entry must be an object")
        for required in ("path", "transcript_field"):
            value = entry.get(required)
            if not isinstance(value, str):
                raise SpecError(
                    f"dataset '{name}': field '{required}' must be a string"
                )
        declaration = {
            "path": entry["path"],
            "transcript_field": entry["transcript_field"],
            "reference_field": None,
            "entry_id_field": None,
        }
        for optional in ("reference_field", "entry_id_field"):
            if optional in entry:
                value = entry[optional]
                if not isinstance(value, str):
                    raise SpecError(
                        f"dataset '{name}': field '{optional}' must be a string"
                    )
                declaration[optional] = value
        validated[name] = declaration
    return validated


def effective_store_path(config, override):
    """Resolve the store path: --store wins, then config, then store.db."""
    if override is not None:
        return override
    store = config.get("store")
    if store is None:
        return DEFAULT_STORE_NAME
    if not isinstance(store, str) or not store:
        raise SpecError("config 'store' must be a non-empty string")
    return store
