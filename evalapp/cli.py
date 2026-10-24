import argparse
import os
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

SUBCOMMANDS = ("check", "generate", "score", "sweep", "report", "clear")
SELECT_COMMANDS = ("generate", "score", "report")


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
        sub.set_defaults(handler=_HANDLERS[command])
    return parser


def _load(args, console):
    return load_config(
        args.config if args.config is not None else DEFAULT_CONFIG_NAME,
        args.config is not None,
        console,
    )


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
    config = _load(args, console)
    declared = validate_datasets(config)
    console.plan("check", f"{len(declared)} datasets")
    store_path = effective_store_path(config, args.store)
    if not os.path.exists(store_path):
        console.note(f"no store at {store_path}")
    return 0


def _clear(args, console):
    config = _load(args, console)
    store_path = effective_store_path(config, args.store)
    if not os.path.exists(store_path):
        console.note(f"no store at {store_path}; nothing to clear")
        return 0
    console.plan("clear", f"store {store_path}")
    return 0


def _sweep(args, console):
    config = _load(args, console)
    declared = validate_datasets(config)
    console.plan("sweep", f"{len(declared)} datasets")
    return 0


_HANDLERS = {
    "check": _check,
    "generate": lambda args, console: _run_command("generate", args, console),
    "score": lambda args, console: _run_command("score", args, console),
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
