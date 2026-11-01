import argparse
import os
import sys

from . import prepare
from .config import effective_store_path
from .console import Console
from .errors import CommandStop, FailFastAbort, RuntimeFailure, SpecError
from .endpoint_client import EndpointClient
from .generate import generate_hook, run_generate
from .report import apply_blind_sample, report
from .scoring import resolve_scorers, score, sweep
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
        if command in ("generate", "score", "report"):
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
        if command == "report":
            sub.add_argument("--metrics", nargs="+", action="append", default=None)
            sub.add_argument("--judges", nargs="*", action="append", default=None)
            sub.add_argument("--no-metrics", action="store_true", default=False)
            sub.add_argument("--no-judges", action="store_true", default=False)
            sub.add_argument("--json", action="store_true", default=False)
            sub.add_argument("--by", choices=("dataset",), default=None)
            sub.add_argument("--blind-sample", type=int, default=None)
            sub.add_argument("--csv", default=None)
        if command == "sweep":
            for flag in (
                "--select",
                "--summarizer",
                "--model",
                "--prompt-template",
                "--metrics",
                "--judges",
            ):
                sub.add_argument(flag, nargs="*", action="append", default=None)
            sub.add_argument("--generate", action="store_true", default=False)
            sub.add_argument("--all-metrics", action="store_true", default=False)
            sub.add_argument("--all-judges", action="store_true", default=False)
            sub.add_argument("--all", action="store_true", default=False)
        sub.set_defaults(handler=_HANDLERS[command])
    return parser


def _generate(args, console):
    loaded = prepare.load_scope(args, console)
    summarizers = select_summarizers(
        loaded.resolved,
        prepare.tokens(args.summarizer),
        prepare.tokens(args.model),
        prepare.tokens(args.prompt_template),
    )
    spec = prepare.server_spec(args, loaded.config)
    client = EndpointClient()
    cycles = prepare.server_cycles(spec, loaded.resolved, client, console)
    store = Store(effective_store_path(loaded.config, args.store))
    try:
        run_generate(
            store, console, loaded.resolved, loaded.datasets, loaded.scope,
            summarizers, client, cycles,
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
    loaded = prepare.load_scope(args, console)
    resolved = loaded.resolved
    selection = (
        prepare.tokens(args.summarizer),
        prepare.tokens(args.model),
        prepare.tokens(args.prompt_template),
    )
    client = EndpointClient()
    hook = None
    if args.generate:
        spec = prepare.server_spec(args, loaded.config)
        cycles = prepare.server_cycles(spec, resolved, client, console)
        hook = generate_hook(client, cycles)
    metrics_flag, judges_flag = prepare.scorer_flags(args)
    score(loaded, effective_store_path(loaded.config, args.store),
          metrics_flag, judges_flag, selection, console, client,
          generate=hook)
    return 0


def _report(args, console):
    if args.csv is not None and args.json:
        raise SpecError("--csv and --json are mutually exclusive")
    if args.blind_sample is not None and args.blind_sample < 0:
        raise SpecError(
            f"invalid --blind-sample {args.blind_sample} (must be >= 0)"
        )
    loaded = prepare.load_scope(
        args, console,
        scope=lambda datasets: apply_blind_sample(
            resolve_selection(args.select, datasets), args.blind_sample
        ),
    )
    resolved = loaded.resolved
    metrics_flag, judges_flag = prepare.scorer_flags(args)
    scorers = resolve_scorers(resolved, metrics_flag, judges_flag)
    summarizers = select_summarizers(
        resolved, prepare.tokens(args.summarizer), prepare.tokens(args.model),
        prepare.tokens(args.prompt_template),
    )
    for name, indices in loaded.scope.items():
        if indices:
            console.plan("report", f"{name} {len(indices)} entries")
    report(
        resolved, effective_store_path(loaded.config, args.store),
        loaded.datasets, loaded.scope, summarizers, scorers, console,
        by_dataset=args.by == "dataset", json_out=args.json,
        csv_path=args.csv,
    )
    return 0


def _clear(args, console):
    config = prepare.command_config(args, console)
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


_SWEEP_FORBIDDEN_ATTRS = (
    "select",
    "summarizer",
    "model",
    "prompt_template",
    "metrics",
    "judges",
    "generate",
)


def _sweep(args, console):
    if any(getattr(args, name) for name in _SWEEP_FORBIDDEN_ATTRS):
        raise SpecError(
            "'sweep' takes no selection or scorer flags (it is exhaustive); "
            "use 'score --generate' to narrow"
        )
    loaded = prepare.load_scope(
        args, console,
        scope=lambda datasets: {
            name: list(range(len(dataset.entries)))
            for name, dataset in datasets.items()
        },
    )
    resolved = loaded.resolved
    client = EndpointClient()
    spec = prepare.server_spec(args, loaded.config)
    cycles = prepare.server_cycles(spec, resolved, client, console)
    hook = generate_hook(client, cycles)
    sweep(loaded, effective_store_path(loaded.config, args.store),
          args.all_metrics or args.all, args.all_judges or args.all,
          console, client, generate=hook)
    return 0


_HANDLERS = {
    "check": _check,
    "generate": _generate,
    "score": _score,
    "sweep": _sweep,
    "report": _report,
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
    except CommandStop as exc:
        return exc.code
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
