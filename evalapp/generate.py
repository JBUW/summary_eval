"""The generate command (docs/commands.md, §generate): selection →
deterministic item order → pre-scan skip → per-item atomic commit.

Committed generations are terminal; a re-run pre-scans the store and
skips committed items without any model call. Fail-fast wording and the
resume note are ticket 05d; the score CLI wiring is ticket 08.
"""
from .endpoint_client import EndpointError
from .errors import RuntimeFailure
from .identities import canonical_json, generation_id, model_id, template_id, transcript_id
from .scoring import _read_reference
from .templates import load_template


def _surface_key(summarizer):
    return (
        summarizer.model,
        canonical_json(summarizer.model_args),
        summarizer.template,
        canonical_json(summarizer.gen_params),
    )


def _load_surface(resolved, summarizer):
    """(model_bytes, model_sha, template, template_sha) for one summarizer;
    the model file and the template file are each read at most once per
    run (caller caches by summarizer identity)."""
    path = resolved["models"][summarizer.model]["path"]
    try:
        with open(path, "rb") as handle:
            model_bytes = handle.read()
    except FileNotFoundError:
        raise RuntimeFailure(
            f"model '{summarizer.model}': file not found: {path}"
        ) from None
    except (OSError, UnicodeDecodeError) as exc:
        detail = getattr(exc, "strerror", None) or exc
        raise RuntimeFailure(
            f"model '{summarizer.model}': cannot read {path}: {detail}"
        ) from None
    model_sha = model_id(model_bytes)
    template = load_template(
        summarizer.template, resolved["prompt_templates"][summarizer.template]
    )
    template_sha = template_id(template.system_content, template.user_prefix)
    return model_bytes, model_sha, template, template_sha


def _messages(template, transcript_text):
    messages = []
    if template.system_content:
        messages.append({"role": "system", "content": template.system_content})
    messages.append({"role": "user", "content": template.user_prefix + transcript_text})
    return messages


def _plural(count, singular, plural):
    return singular if count == 1 else plural


def run_generate(store, console, resolved, datasets, selected, summarizers, client, cycles):
    """One generate run: the plan line, the pre-scan skip, and the
    per-item atomic commits (one complete-or-absent unit per item)."""
    items = [
        (summarizer, dataset, index)
        for summarizer in summarizers
        for dataset in datasets.values()
        for index in selected[dataset.name]
    ]
    item_count = len(items)
    cycle_count = len(
        {
            (summarizer.model, canonical_json(summarizer.model_args))
            for summarizer in summarizers
        }
    )
    console.plan(
        "generate",
        f"{len(summarizers)} "
        f"{_plural(len(summarizers), 'summarizer', 'summarizers')}, "
        f"{item_count} {_plural(item_count, 'item', 'items')}, "
        f"{cycle_count} "
        f"{_plural(cycle_count, 'server cycle', 'server cycles')}",
    )

    surfaces = {}
    pending = []
    skipped = 0
    for summarizer, dataset, index in items:
        entry = dataset.entries[index]
        surface = surfaces.setdefault(
            _surface_key(summarizer), _load_surface(resolved, summarizer)
        )
        model_bytes, model_sha, template, template_sha = surface
        generation_sha = generation_id(
            transcript_id(entry["transcript"]),
            model_sha,
            summarizer.model_args,
            template_sha,
            summarizer.gen_params,
        )
        if store.get_generation(generation_sha) is None:
            pending.append((summarizer, dataset, index, entry, surface, generation_sha))
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
        for summarizer, dataset, index, entry, surface, generation_sha in pending:
            model_bytes, model_sha, template, template_sha = surface
            server = cycles.ensure(summarizer.model, summarizer.model_args)
            try:
                text = client.complete(
                    server.root,
                    summarizer.model,
                    _messages(template, entry["transcript"]),
                    gen_params=summarizer.gen_params,
                )
            except EndpointError as exc:
                raise RuntimeFailure(str(exc)) from exc
            reference = None
            if dataset.decl["reference_field"] is not None:
                reference = _read_reference(dataset.decl, index)
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
                    model_bytes, summarizer.model,
                    resolved["models"][summarizer.model]["path"],
                )
                store.upsert_template(
                    template.system_content, template.user_prefix, summarizer.template
                )
                store.upsert_generation(
                    transcript_sha, model_sha, summarizer.model_args,
                    template_sha, summarizer.gen_params, text,
                )
            committed += 1
    finally:
        cycles.stop()
    console.done(
        "generate", f"{committed} committed, {skipped} skipped, 0 failed"
    )


def generate_hook(resolved, datasets, selected, summarizers, client, cycles):
    """The generate(store, console) hook for score: scoring.py calls it
    with an already-open store; ticket 08 passes it as `generate=`."""

    def generate(store, console):
        run_generate(
            store, console, resolved, datasets, selected, summarizers, client,
            cycles,
        )

    return generate
