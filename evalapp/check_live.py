"""The live phase of check (ticket 11): one server cycle per distinct
(model, model_args) pair, one probe completion per distinct summarizer
surface of the pair, a once-per-dataset context-adequacy warn after the
first pair's probes, and remote judge probes behind --probe-judges. No
store footprint. The endpoint client and the server cycles are referenced
through module attributes at call time (unit tests monkeypatch them on
this module).
"""
import json

from .cli import _parse_json_object
from .datasets import load_dataset
from .endpoint_client import EndpointError, create_client
from .errors import FailFastAbort, RuntimeFailure
from .identities import canonical_json
from .judge_call import judge_call
from .model_server import (
    ServerCycles,
    distinct_model_pairs,
    effective_server_spec,
)
from .templates import load_template

PROBE_TRANSCRIPT = "Probe transcript for the check command."
JUDGE_EXAMPLE_TRANSCRIPT = "Example transcript for the check judge probe."
JUDGE_EXAMPLE_SUMMARY = "Example summary for the check judge probe."
JUDGE_EXAMPLE_REFERENCE = "Example reference for the check judge probe."


def _plural(count, singular, plural):
    return singular if count == 1 else plural


def _fail_local(console, cycles, target, exc):
    """The local fail-fast shape: error line, log tail, FailFastAbort."""
    detail = (
        f"{exc} from model server"
        if isinstance(exc, EndpointError)
        else str(exc)
    )
    console.error(f"{target}: {detail}")
    for line in cycles.log_tail(20):
        console.log(line)
    raise FailFastAbort()


def _surface_key(entry):
    return (
        entry["model"],
        canonical_json(entry["model_args"]),
        entry["prompt_template"],
        canonical_json(entry["gen_params"]),
    )


def _probe_messages(template):
    messages = []
    if template.system_content:
        messages.append({"role": "system", "content": template.system_content})
    messages.append(
        {"role": "user", "content": template.user_prefix + PROBE_TRANSCRIPT}
    )
    return messages


def _context_adequacy(config, client, server, spec, console):
    """Once per dataset on the longest transcript; warn-only, never fails."""
    ctx = spec["args"].get("ctx-size")
    if not (isinstance(ctx, int) and not isinstance(ctx, bool) and ctx > 0):
        return
    for name, decl in config.get("datasets", {}).items():
        dataset = load_dataset(name, decl)
        if not dataset.entries:
            continue
        longest = max(
            (entry["transcript"] for entry in dataset.entries), key=len
        )
        estimated = False
        try:
            tokens = client.tokenize(server.root, longest)
        except EndpointError:
            tokens = len(longest) // 3
            estimated = True
        if tokens > ctx:
            count = (
                f"~{tokens} tokens estimated from chars/3"
                if estimated
                else f"{tokens} tokens"
            )
            console.warn(
                f"dataset '{name}': longest transcript "
                f"({count}) exceeds context size ({ctx})"
            )


def run_live(args, config, resolved, console):
    """The check live phase: model cycles, context adequacy, judge probes."""
    pairs = distinct_model_pairs(resolved)
    if not (pairs or args.probe_judges):
        return
    client = create_client()
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
    spec = None
    cycles = None
    if pairs:
        spec = effective_server_spec(
            config,
            command=args.server_command,
            args_map=args_map,
            env_map=env_map,
            port=args.server_port,
            startup_timeout_s=args.server_startup_timeout,
        )
        cycles = ServerCycles(
            spec,
            {name: model["path"] for name, model in resolved["models"].items()},
            client,
            console,
        )
    probe_count = 0
    judge_count = 0
    try:
        for index, (model, model_args) in enumerate(pairs):
            try:
                server = cycles.ensure(model, model_args)
            except (EndpointError, RuntimeFailure) as exc:
                _fail_local(console, cycles, f"model '{model}'", exc)
            seen = set()
            for name, entry in resolved["summarizers"].items():
                if (
                    entry["model"] != model
                    or json.dumps(entry["model_args"], sort_keys=True)
                    != json.dumps(model_args, sort_keys=True)
                ):
                    continue
                key = _surface_key(entry)
                if key in seen:
                    continue
                seen.add(key)
                template = load_template(
                    name, resolved["prompt_templates"][entry["prompt_template"]]
                )
                try:
                    client.complete(
                        server.root,
                        model,
                        _probe_messages(template),
                        gen_params=entry["gen_params"],
                    )
                except (EndpointError, RuntimeFailure) as exc:
                    _fail_local(console, cycles, f"summarizer '{name}'", exc)
                probe_count += 1
            if index == 0:
                _context_adequacy(config, client, server, spec, console)
        if args.probe_judges:
            for name, entry in resolved["judges"].items():
                normalized = {
                    **entry,
                    "gen_params": entry.get("gen_params") or {},
                }
                reference = (
                    JUDGE_EXAMPLE_REFERENCE
                    if entry["requires_reference"]
                    else None
                )
                try:
                    result = judge_call(
                        client,
                        name,
                        normalized,
                        JUDGE_EXAMPLE_TRANSCRIPT,
                        JUDGE_EXAMPLE_SUMMARY,
                        reference,
                    )
                except RuntimeFailure as exc:
                    console.error(f"judge '{name}': {exc}")
                    raise FailFastAbort()
                if result is None:
                    console.error(
                        f"judge '{name}': no usable values in probe response"
                    )
                    raise FailFastAbort()
                judge_count += 1
    finally:
        if cycles is not None:
            cycles.stop()
    console.done(
        "check",
        f"{len(pairs)} "
        f"{_plural(len(pairs), 'server cycle', 'server cycles')}, "
        f"{probe_count} "
        f"{_plural(probe_count, 'summarizer probe', 'summarizer probes')}, "
        f"{judge_count} "
        f"{_plural(judge_count, 'judge probe', 'judge probes')}",
    )
