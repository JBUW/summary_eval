import json

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


class _Pairs:
    """Marker wrapping the raw (key, value) pairs of one JSON object.

    A distinct type (not a bare list) so an object's pair list can never be
    confused with a JSON array while the tree is still being walked.
    """

    def __init__(self, pairs):
        self.pairs = pairs


def _object_pairs_hook(pairs):
    return _Pairs(pairs)


def load_config(path, explicit, console):
    """Load the configuration file, returning the parsed object.

    ``path`` is the configured name; ``explicit`` says whether the user
    passed --config. All failures are SpecError (exit 2).
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
    config = _convert(parsed, "config", console, top_level=True)
    if not isinstance(config, dict):
        raise SpecError(f"invalid JSON in {path}: top-level value must be an object")
    return config


def _convert(node, location, console, top_level=False):
    if isinstance(node, _Pairs):
        seen = set()
        converted = {}
        for key, value in node.pairs:
            if key in seen:
                raise SpecError(f"duplicate name '{key}' in {location}")
            seen.add(key)
            converted[key] = _convert(
                value, key if top_level else location, console
            )
        if top_level:
            for key, _ in node.pairs:
                if key not in KNOWN_TOP_LEVEL_FIELDS:
                    console.warn(f"unrecognized field '{key}' in config")
        return converted
    if isinstance(node, list):
        return [_convert(item, location, console) for item in node]
    return node


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
