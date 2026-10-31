"""The generate command (docs/commands.md, §generate): selection →
deterministic item order → pre-scan skip → per-item atomic commit.

Committed generations are terminal; a re-run pre-scans the store and
skips committed items without any model call. The score CLI wiring is
ticket 08.
"""
from .endpoint_client import EndpointError
from .errors import FailFastAbort, RuntimeFailure
from .identities import canonical_json, generation_id, transcript_id
from .summarizers import SummarizerInputsCache




def _messages(template, transcript_text):
    messages = []
    if template.system_content:
        messages.append({"role": "system", "content": template.system_content})
    messages.append({"role": "user", "content": template.user_prefix + transcript_text})
    return messages


def _plural(count, singular, plural):
    return singular if count == 1 else plural


def generate_plan_text(datasets, selected, summarizers):
    """The plan(generate) line text, store-free: summarizer, item, and
    server-cycle counts. Used by run_generate and by score() (which
    imports it lazily to avoid the generate<->scoring cycle)."""
    item_count = len(summarizers) * sum(
        len(indices) for indices in selected.values()
    )
    cycle_count = len(
        {
            (summarizer.model, canonical_json(summarizer.model_args))
            for summarizer in summarizers
        }
    )
    return (
        f"{len(summarizers)} "
        f"{_plural(len(summarizers), 'summarizer', 'summarizers')}, "
        f"{item_count} {_plural(item_count, 'item', 'items')}, "
        f"{cycle_count} "
        f"{_plural(cycle_count, 'server cycle', 'server cycles')}"
    )


def run_generate(
    store, console, resolved, datasets, selected, summarizers, client,
    cycles, print_plan=True, inputs=None,
):
    """One generate run: the plan line, the pre-scan skip, and the
    per-item atomic commits (one complete-or-absent unit per item).
    print_plan defaults to True (standalone CLI); score() prints the
    plan(generate) line itself and passes print_plan=False. inputs is the
    command's SummarizerInputsCache (a new one when None)."""
    inputs = inputs if inputs is not None else SummarizerInputsCache(resolved)
    items = [
        (summarizer, dataset, index)
        for summarizer in summarizers
        for dataset in datasets.values()
        for index in selected[dataset.name]
    ]
    item_count = len(items)
    if print_plan:
        console.plan(
            "generate", generate_plan_text(datasets, selected, summarizers)
        )

    pending = []
    skipped = 0
    for summarizer, dataset, index in items:
        entry = dataset.entries[index]
        summarizer_inputs = inputs.inputs(summarizer)
        generation_sha = generation_id(
            transcript_id(entry["transcript"]),
            summarizer_inputs.model_sha,
            summarizer.model_args,
            summarizer_inputs.template_sha,
            summarizer.gen_params,
        )
        if store.get_generation(generation_sha) is None:
            pending.append(
                (summarizer, dataset, index, entry, summarizer_inputs, generation_sha)
            )
        else:
            skipped += 1

    if not pending:
        if item_count:
            console.note(
                f"all {item_count} items already committed; server not started"
            )
        console.done("generate", f"0 committed, {skipped} skipped, 0 failed")
        return

    committed = 0
    try:
        for summarizer, dataset, index, entry, summarizer_inputs, generation_sha in pending:
            template = summarizer_inputs.template
            try:
                server = cycles.ensure(summarizer.model, summarizer.model_args)
                text = client.complete(
                    server.root,
                    summarizer.model,
                    _messages(template, entry["transcript"]),
                    gen_params=summarizer.gen_params,
                )
            except (EndpointError, RuntimeFailure) as exc:
                detail = (
                    f"{exc} from model server"
                    if isinstance(exc, EndpointError)
                    else str(exc)
                )
                console.error(
                    f"item {dataset.name}#{index} "
                    f"(summarizer '{summarizer.name or 'unnamed'}'): {detail}"
                )
                for line in cycles.log_tail(20):
                    console.log(line)
                total = skipped + committed
                console.note(
                    f"re-run to resume; {total} "
                    f"{_plural(total, 'item', 'items')} already committed"
                )
                raise FailFastAbort()
            reference = entry["reference"] if dataset.has_references else None
            with store.transaction():
                transcript_sha = store.upsert_transcript(
                    entry["transcript"], dataset.name, entry.get("entry_id"), index
                )
                if reference is not None:
                    store.upsert_reference_summary(
                        reference, transcript_sha, dataset.name,
                        entry.get("entry_id"), index,
                    )
                store.upsert_model(
                    summarizer_inputs.model_sha, summarizer.model,
                    resolved["models"][summarizer.model]["path"],
                )
                store.upsert_template(
                    template.system_content, template.user_prefix, summarizer.template
                )
                store.upsert_generation(
                    transcript_sha, summarizer_inputs.model_sha,
                    summarizer.model_args, summarizer_inputs.template_sha,
                    summarizer.gen_params, text,
                )
            committed += 1
    finally:
        cycles.stop()
    console.done(
        "generate", f"{committed} committed, {skipped} skipped, 0 failed"
    )


def generate_hook(
    resolved, datasets, selected, summarizers, client, cycles,
    print_plan=True,
):
    """The generate(store, console, inputs) hook for score: scoring.py
    calls it with an already-open store and the command's
    SummarizerInputsCache; ticket 08 passes it as `generate=` with
    print_plan=False because score() prints the plan(generate) line
    itself (before the plan(score) line, before the hook runs)."""

    def generate(store, console, inputs=None):
        run_generate(
            store, console, resolved, datasets, selected, summarizers, client,
            cycles, print_plan=print_plan, inputs=inputs,
        )

    return generate
