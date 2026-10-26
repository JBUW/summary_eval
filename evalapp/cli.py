import argparse
import json
import os
import socket
import sys

from .config import (
    DEFAULT_CONFIG_NAME,
    effective_store_path,
    load_config,
    validate_datasets,
)
from .console import Console
from .datasets import load_dataset
from .errors import RuntimeFailure, SpecError
from .selection import resolve_selection
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
        sub.set_defaults(handler=_HANDLERS[command])
    return parser


def _load(args, console):
    return load_config(
        args.config if args.config is not None else DEFAULT_CONFIG_NAME,
        args.config is not None,
        console,
    )


def port_is_free(port):
    """Port pre-scan: socket-creation failure (e.g. sandboxed) counts as
    free; a bind failure raises SpecError with the bound-port error."""
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return True
    try:
        probe.bind(("127.0.0.1", port))
    except OSError:
        raise SpecError(
            f"port {port} already bound "
            "(a previous model server may still be running)"
        ) from None
    finally:
        probe.close()
    return True


def _parse_json_object(value, flag):
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SpecError(f"invalid JSON for {flag}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SpecError(f"{flag} must be a JSON object")
    return parsed


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


def _check(args, console):
    if args.server_args is not None:
        _parse_json_object(args.server_args, "--server-args")
    if args.server_env is not None:
        _parse_json_object(args.server_env, "--server-env")
    config = _load(args, console)
    declared = validate_datasets(config)
    console.plan("check", f"{len(declared)} datasets")
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
    return 0


def _score(args, console):
    if any(getattr(args, name) is not None for name in _SERVER_FLAG_ATTRS):
        raise SpecError("--server-* flags require --generate")
    return _run_command("score", args, console)


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
    "generate": lambda args, console: _run_command("generate", args, console),
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
    except SpecError as exc:
        console.error(str(exc))
        return 2
    except RuntimeFailure as exc:
        console.error(str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
