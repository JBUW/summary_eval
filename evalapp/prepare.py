"""Command preparation that needs the configuration (ticket 14): load,
scope and validate; the server overrides, spec and cycles; the scorer
flags. cli.py keeps only the command-line-only checks and calls these.

An early stop prints its message first, then raises CommandStop with the
exit code (empty scope -> 0, configuration errors -> 2).
"""
import json
from dataclasses import dataclass

from .config import (
    DEFAULT_CONFIG_NAME,
    load_config,
    validate_config,
    validate_datasets,
)
from .datasets import load_dataset
from .errors import CommandStop, SpecError
from .model_server import ServerCycles, effective_server_spec
from .scoring import Flag
from .selection import resolve_selection


@dataclass(frozen=True)
class Loaded:
    config: dict
    datasets: dict
    scope: dict
    resolved: dict


def command_config(args, console):
    return load_config(
        args.config if args.config is not None else DEFAULT_CONFIG_NAME,
        args.config is not None,
        console,
    )


def load_scope(args, console, scope=None):
    """Config -> datasets -> scope -> empty-scope note -> validation.
    scope maps the loaded datasets to {name: [index, ...]}; the default
    is the --select selection."""
    config = command_config(args, console)
    declared = validate_datasets(config)
    datasets = {name: load_dataset(name, decl) for name, decl in declared.items()}
    selected = (
        scope(datasets)
        if scope is not None
        else resolve_selection(args.select, datasets)
    )
    if not any(selected.values()):
        console.note("no entries in scope; nothing to do")
        raise CommandStop(0)
    errors, resolved = validate_config(config, console)
    if errors:
        for message in errors:
            console.error(message)
        raise CommandStop(2)
    return Loaded(config, datasets, selected, resolved)


def tokens(value):
    if value is None:
        return None
    return tuple(token for group in value for token in group)


def scorer_flags(args):
    """The (metrics, judges) Flag pair: a bare --judges is "bare"."""
    metrics_flag = (
        Flag(no=args.no_metrics)
        if args.metrics is None
        else Flag(value=tokens(args.metrics), no=args.no_metrics)
    )
    if args.judges is None:
        judges_flag = Flag(no=args.no_judges)
    else:
        judge_tokens = tokens(args.judges)
        judges_flag = (
            Flag(value="bare", no=args.no_judges)
            if not judge_tokens
            else Flag(value=judge_tokens, no=args.no_judges)
        )
    return metrics_flag, judges_flag


def _json_object(value, flag):
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SpecError(f"invalid JSON for {flag}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SpecError(f"{flag} must be a JSON object")
    return parsed


def server_overrides(args):
    """(args_map, env_map) from --server-args / --server-env (None if absent)."""
    args_map = (
        _json_object(args.server_args, "--server-args")
        if args.server_args is not None
        else None
    )
    env_map = (
        _json_object(args.server_env, "--server-env")
        if args.server_env is not None
        else None
    )
    return args_map, env_map


def server_spec(args, config):
    args_map, env_map = server_overrides(args)
    return effective_server_spec(
        config,
        command=args.server_command,
        args_map=args_map,
        env_map=env_map,
        port=args.server_port,
        startup_timeout_s=args.server_startup_timeout,
    )


def server_cycles(spec, resolved, client, console):
    return ServerCycles(
        spec,
        {name: model["path"] for name, model in resolved["models"].items()},
        client,
        console,
    )
