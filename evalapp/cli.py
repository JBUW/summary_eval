import argparse
import json
import os
import sys

from .config import (
    DEFAULT_CONFIG_NAME,
    validate_config,
    effective_store_path,
    load_config,
    validate_datasets,
)
from .console import Console
from .datasets import load_dataset
from .errors import FailFastAbort, RuntimeFailure, SpecError
from .endpoint_client import EndpointClient
from .generate import generate_hook, run_generate
from .judge_call import judge_call
from .model_server import (
    effective_server_spec,
    ServerCycles,
    port_is_free,  # re-exported for check_static
)
from .scoring import Flag, score
from .selection import resolve_selection
from .summarizers import select_summarizers
from .store import Store

SUBCOMMANDS = ("check", "generate", "score", "sweep", "report", "clear")
SELECT_COMMANDS = ("generate", "score", "report")
SERVER_COMMANDS = ("generate", "score", "sweep", "check")
_SERVER_FLAG_ATTRS = (
    "server_command",
    "server_args",
    "server_env",
    "server_port",
    "server_startup_timeout",
)


class _CliExit(Exception):
    """Raised from the argument parser's error() to carry the exit code."""

    def __init__(self, code):
        self.code = code


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        print(f"error: {message}")
        raise _CliExit(2)


def build_parser():
    parser = _Parser(prog="evalapp", description="evalapp")
    subparsers = parser.add_subparsers(
        dest="command", required=True, parser_class=_Parser
    )
    for command in SUBCOMMANDS:
        sub = subparsers.add_parser(command)
        sub.add_argument("--config", default=None)
        sub.add_argument("--store", default=None)
        if command in SELECT_COMMANDS:
            sub.add_argument(
                "--select",
                nargs="+",
                action="append",
                default=None,
                metavar="<dataset> <spec>...",
            )
        if command in SERVER_COMMANDS:
            sub.add_argument("--server-command", default=None)
            sub.add_argument("--server-args", default=None)
            sub.add_argument("--server-env", default=None)
            sub.add_argument("--server-port", type=int, default=None)
            sub.add_argument("--server-startup-timeout", type=float, default=None)
        if command == "clear":
            sub.add_argument("--yes", action="store_true", default=False)
        if command == "check":
            sub.add_argument("--probe-judges", action="store_true", default=False)
            sub.add_argument("--create-store", action="store_true", default=False)
        if command in ("generate", "score"):
            sub.add_argument("--summarizer", nargs="+", action="append", default=None)
            sub.add_argument("--model", nargs="+", action="append", default=None)
            sub.add_argument(
                "--prompt-template", nargs="+", action="append", default=None
            )
        if command == "score":
            sub.add_argument("--metrics", nargs="+", action="append", default=None)
            sub.add_argument("--judges", nargs="*", action="append", default=None)
            sub.add_argument("--no-metrics", action="store_true", default=False)
            sub.add_argument("--no-judges", action="store_true", default=False)
            sub.add_argument("--generate", action="store_true", default=False)
        sub.set_defaults(handler=_HANDLERS[command])
    return parser


def _load(args, console):
    return load_config(
        args.config if args.config is not None else DEFAULT_CONFIG_NAME,
        args.config is not None,
        console,
    )


def _parse_json_object(value, flag):
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SpecError(f"invalid JSON for {flag}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SpecError(f"{flag} must be a JSON object")
    return parsed


def _tokens(value):
    if value is None:
        return None
    return tuple(token for group in value for token in group)


def _run_command(command, args, console):
    config = _load(args, console)
    declared = validate_datasets(config)
    datasets = {name: load_dataset(name, decl) for name, decl in declared.items()}
    scope = resolve_selection(args.select, datasets)
    if not any(scope.values()):
        console.note("no entries in scope; nothing to do")
        return 0
    for name, decl in declared.items():
        indices = scope[name]
        if indices:
            console.plan(command, f"{name} {len(indices)} entries")
    return 0


def _generate(args, console):
    config = _load(args, console)
    declared = validate_datasets(config)
    datasets = {name: load_dataset(name, decl) for name, decl in declared.items()}
    scope = resolve_selection(args.select, datasets)
    if not any(scope.values()):
        console.note("no entries in scope; nothing to do")
        return 0
    errors, resolved = validate_config(config, console)
    if errors:
        for message in errors:
            console.error(message)
        return 2
    summarizers = select_summarizers(
        resolved,
        _tokens(args.summarizer),
        _tokens(args.model),
        _tokens(args.prompt_template),
    )
    args_map = (
        _parse_json_object(args.server_args, "--server-args")
        if args.server_args is not None
        else None
    )
    env_map = (
        _parse_json_object(args.server_env, "--server-env")
        if args.server_env is not None
        else None
    )
    spec = effective_server_spec(
        config,
        command=args.server_command,
        args_map=args_map,
        env_map=env_map,
        port=args.server_port,
        startup_timeout_s=args.server_startup_timeout,
    )
    client = EndpointClient()
    cycles = ServerCycles(
        spec,
        {name: model["path"] for name, model in resolved["models"].items()},
        client,
        console,
    )
    store = Store(effective_store_path(config, args.store))
    try:
        run_generate(
            store, console, resolved, datasets, scope, summarizers, client, cycles
        )
    finally:
        store.close()
    return 0


def _check(args, console):
    from . import check_static

    return check_static.run_check(args, console)


def _score(args, console):
    if any(getattr(args, name) is not None for name in _SERVER_FLAG_ATTRS):
        if not args.generate:
            raise SpecError("--server-* flags require --generate")
    config = _load(args, console)
    declared = validate_datasets(config)
    datasets = {name: load_dataset(name, decl) for name, decl in declared.items()}
    scope = resolve_selection(args.select, datasets)
    if not any(scope.values()):
        console.note("no entries in scope; nothing to do")
        return 0
    errors, resolved = validate_config(config, console)
    if errors:
        for message in errors:
            console.error(message)
        return 2
    client = EndpointClient()
    hook = None
    if args.generate:
        summarizers = select_summarizers(
            resolved, _tokens(args.summarizer), _tokens(args.model),
            _tokens(args.prompt_template)
        )
        args_map = (_parse_json_object(args.server_args, "--server-args")
                   if args.server_args is not None else None)
        env_map = (_parse_json_object(args.server_env, "--server-env")
                   if args.server_env is not None else None)
        spec = effective_server_spec(config, command=args.server_command,
                                     args_map=args_map, env_map=env_map,
                                     port=args.server_port,
                                     startup_timeout_s=args.server_startup_timeout)
        cycles = ServerCycles(
            spec, {name: model["path"] for name, model in resolved["models"].items()},
            client, console
        )
        hook = generate_hook(resolved, datasets, scope, summarizers, client, cycles, print_plan=False)
    metrics_flag = (Flag(no=args.no_metrics) if args.metrics is None
                    else Flag(value=_tokens(args.metrics), no=args.no_metrics))
    if args.judges is None:
        judges_flag = Flag(no=args.no_judges)
    else:
        tokens = _tokens(args.judges)
        judges_flag = (Flag(value="bare", no=args.no_judges) if not tokens
                       else Flag(value=tokens, no=args.no_judges))
    score(resolved, effective_store_path(config, args.store), metrics_flag,
          judges_flag, datasets, scope,
          (_tokens(args.summarizer), _tokens(args.model),
           _tokens(args.prompt_template)), console, client, judge_call,
          generate=hook)
    return 0


def _clear(args, console):
    config = _load(args, console)
    store_path = effective_store_path(config, args.store)
    if not os.path.exists(store_path):
        console.note(f"no store at {store_path}; nothing to clear")
        return 0
    store = Store(store_path)
    try:
        counts = store.table_counts()
        if args.yes:
            deleted = store.clear()
            console.done("clear", f"{deleted} rows deleted across {len(counts)} tables")
        else:
            console.plan(
                "clear",
                f"store {store_path} | " + " | ".join(f"{t} {c}" for t, c in counts),
            )
    finally:
        store.close()
    if store.created:
        console.note(f"created empty store at {store_path}")
    if not args.yes:
        console.note("re-run with --yes to delete all rows (this cannot be undone)")
    return 0


def _sweep(args, console):
    config = _load(args, console)
    declared = validate_datasets(config)
    console.plan("sweep", f"{len(declared)} datasets")
    return 0


_HANDLERS = {
    "check": _check,
    "generate": _generate,
    "score": _score,
    "sweep": _sweep,
    "report": lambda args, console: _run_command("report", args, console),
    "clear": _clear,
}


def main(argv):
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except _CliExit as exc:
        return exc.code
    except SystemExit as exc:
        return int(exc.code)
    console = Console()
    try:
        return args.handler(args, console)
    except FailFastAbort:
        return 1
    except SpecError as exc:
        console.error(str(exc))
        return 2
    except RuntimeFailure as exc:
        console.error(str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
