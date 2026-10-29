import os

from . import check_live
from . import metrics
from .cli import _parse_json_object, port_is_free
from .config import (
    DEFAULT_CONFIG_NAME,
    effective_store_path,
    load_config,
    validate_config,
)
from .datasets import _load
from .errors import SpecError
from .store import Store


def run_check(args, console):
    if args.server_args is not None:
        _parse_json_object(args.server_args, "--server-args")
    if args.server_env is not None:
        _parse_json_object(args.server_env, "--server-env")
    collector = []
    config = load_config(
        args.config if args.config is not None else DEFAULT_CONFIG_NAME,
        args.config is not None,
        console,
        errors=collector,
    )
    errors, resolved = validate_config(config, console)
    for line in _discovery_lines(config):
        print(line)
    if collector or errors:
        for message in list(collector) + list(errors):
            console.error(message)
        return 2
    console.plan("check", f"{len(config.get('datasets', {}))} datasets")
    file_errors = _file_checks(args, config, resolved)
    if file_errors:
        for message in file_errors:
            console.error(message)
        return 2
    _handle_store(args, config, console)
    check_live.run_live(args, config, resolved, console)
    return 0


def _discovery_lines(config):
    def family(default_key, universe):
        raw = config.get(default_key)
        if raw is None or not isinstance(raw, list):
            return list(universe), []
        named, seen = [], set()
        for item in raw:
            if not isinstance(item, str) or item in seen:
                continue
            seen.add(item)
            if item in universe:
                named.append(item)
        return named, [name for name in universe if name not in seen]

    metric_universe = list(metrics.registered_names())
    judge_universe = (
        list(config["judges"]) if isinstance(config.get("judges"), dict) else []
    )
    named_metrics, other_metrics = family("default_metrics", metric_universe)
    named_judges, other_judges = family("default_judges", judge_universe)

    def value(label, names):
        return f"  {label}:".ljust(33) + (", ".join(names) if names else "(none)")

    return [
        f"metrics (registered: {len(metric_universe)}):",
        value("default_metrics", named_metrics),
        value("registered, not named there", other_metrics),
        f"judges (configured: {len(judge_universe)}):",
        value("default_judges", named_judges),
        value("configured, not named there", other_judges),
    ]


def _file_checks(args, config, resolved):
    errors = _dataset_checks(config)
    server = config.get("server")
    has_section = isinstance(server, dict)
    if not has_section and args.server_command is None:
        errors.append("no server section in config (no fallback launch)")
    command = args.server_command
    if command is None and has_section:
        candidate = server.get("command")
        if isinstance(candidate, str):
            command = candidate
    if command is not None and not os.path.exists(command):
        errors.append(f"server: command not found: {command}")
    for name, entry in resolved["models"].items():
        path = entry["path"]
        if isinstance(path, str) and not os.path.exists(path):
            errors.append(f"model '{name}': file not found: {path}")
    for name, path in resolved["prompt_templates"].items():
        if isinstance(path, str) and not os.path.exists(path):
            errors.append(f"prompt template '{name}': file not found: {path}")
    port = args.server_port
    if port is None and has_section:
        raw = server.get("port")
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            port = raw
    if port is not None:
        try:
            port_is_free(port)
        except SpecError as exc:
            errors.append(str(exc))
    if args.probe_judges:
        for name, entry in resolved["judges"].items():
            variable = entry.get("api_key_env")
            if isinstance(variable, str) and os.environ.get(variable) in (None, ""):
                errors.append(
                    f"judge '{name}': environment variable '{variable}' "
                    "is unset or empty"
                )
    return errors


def _dataset_checks(config):
    errors = []
    for name, entry in config.get("datasets", {}).items():
        path = entry["path"]
        try:
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
        except FileNotFoundError:
            errors.append(f"dataset '{name}': file not found: {path}")
            continue
        except (OSError, UnicodeDecodeError) as exc:
            detail = getattr(exc, "strerror", None) or exc
            errors.append(f"dataset '{name}': cannot read {path}: {detail}")
            continue
        extension = path.rsplit(".", 1)[1].lower() if "." in path else ""
        if extension not in ("csv", "jsonl", "json"):
            errors.append(
                f"dataset '{name}': unsupported file extension '{extension}' "
                "(supported: .csv, .jsonl, .json)"
            )
            continue
        _, _, load_errors = _load(name, path, text, entry)
        errors.extend(load_errors)
    return errors


def _handle_store(args, config, console):
    store_path = effective_store_path(config, args.store)
    if args.create_store:
        store = Store(store_path)
        created = store.created
        store.close()
        if created:
            console.note(f"created empty store at {store_path}")
    else:
        store = Store.open_readonly(store_path)
        if store is None:
            console.note(f"no store at {store_path}")
        else:
            store.close()
