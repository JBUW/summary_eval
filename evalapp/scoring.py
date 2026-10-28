"""Scorer resolution, the metrics and judges phases, and the full score
run (docs/commands.md, §score).

The CLI hands this module raw flag state (Flag); resolution owns the
precedence rules, the ``[]`` no-op token, and the exit-2 SpecError wording.
score() emits everything itself: pre-effect warns/notes, the plan(score)
line, mid-run phase warns (legal after plan lines), the generation and
no-scorers notes, and done(score).
"""
import csv
import json
import os
from dataclasses import dataclass

from . import metrics
from .errors import RuntimeFailure, SpecError
from .identities import (
    canonical_json,
    judge_evaluation_id,
    judge_id,
    generation_id,
    metric_evaluation_id,
    model_id,
    summary_id,
    template_id,
    transcript_id,
)
from .metrics import MetricInput
from .templates import load_template
from .store import Store
from .summarizers import select_summarizers

_EMPTY_BRACKET = "[]"


@dataclass(frozen=True)
class Flag:
    """Raw state of one --metrics/--judges flag family.

    value: None = flag omitted; ``"bare"`` = ``--judges`` with no tokens
    (judges axis only); otherwise the token list exactly as given, the
    ``[]`` token included.
    no: True when the matching --no-X shorthand is present.
    """

    value: str | list[str] | None = None
    no: bool = False


@dataclass(frozen=True)
class ResolvedScorers:
    metrics: tuple
    judges: tuple
    notes: tuple


@dataclass(frozen=True)
class MetricsPhaseResult:
    items: int
    missing_generation: int
    committed: int
    skipped: int
    excluded: int
    dropped: int


@dataclass(frozen=True)
class ScorePlan:
    metrics: int
    judges: int
    items: int
    to_run: int
    already_scored: int
    infeasible_pairs: int


@dataclass(frozen=True)
class JudgePhaseResult:
    items: int
    missing_generation: int
    committed: int
    skipped: int
    dropped: int
    failed: int


def resolve_scorers(resolved, metrics_flag, judges_flag):
    if metrics_flag.no and metrics_flag.value is not None:
        raise SpecError("--no-metrics is mutually exclusive with --metrics")
    if judges_flag.no and judges_flag.value is not None:
        raise SpecError("--no-judges is mutually exclusive with --judges")

    tokens = _metric_tokens(resolved, metrics_flag)
    metric_names = tuple(spec.name for spec in metrics.resolve(tokens))
    judges, notes = _judge_names(resolved, judges_flag)
    return ResolvedScorers(metrics=metric_names, judges=judges, notes=tuple(notes))


def resolve_sweep_scorers(resolved, all_metrics, all_judges):
    if all_metrics:
        metric_tokens = ["*"]
    else:
        default = resolved["defaults"]["metrics"]
        metric_tokens = (
            ["*"] if default is None else _without_empty_bracket(list(default))
        )
    metric_names = tuple(spec.name for spec in metrics.resolve(metric_tokens))
    if all_judges:
        judge_tokens = ["*"]
    else:
        default = resolved["defaults"]["judges"]
        judge_tokens = (
            ["*"] if default is None else _without_empty_bracket(list(default))
        )
    judges = _select_judge_tokens(judge_tokens, resolved)
    return ResolvedScorers(metrics=metric_names, judges=judges, notes=())


def _credential_preflight(resolved, judges_flag):
    if judges_flag.value is None or judges_flag.value == "bare":
        return
    for token in judges_flag.value:
        if token in ("*", "[]"):
            continue
        variable = resolved["judges"][token]["api_key_env"]
        if isinstance(variable, str) and os.environ.get(variable) in (None, ""):
            raise SpecError(
                f"judge '{token}': environment variable "
                f"'{variable}' is unset or empty"
            )


def _sweep_credential_preflight(resolved, console, judges):
    kept = []
    for name in judges:
        variable = resolved["judges"][name]["api_key_env"]
        if isinstance(variable, str) and os.environ.get(variable) in (None, ""):
            console.warn(
                f"judge '{name}': environment variable '{variable}' "
                "is unset or empty (judge skipped)"
            )
            continue
        kept.append(name)
    return tuple(kept)


def _without_empty_bracket(tokens):
    return [token for token in tokens if token != _EMPTY_BRACKET]


def _metric_tokens(resolved, flag):
    if flag.no:
        return []
    if flag.value is None:
        default = resolved["defaults"]["metrics"]
        if default is None:
            return ["*"]
        return _without_empty_bracket(list(default))
    return _without_empty_bracket(list(flag.value))


def _judge_names(resolved, flag):
    notes = []
    if flag.no or flag.value is None:
        return (), notes
    if flag.value == "bare":
        default = resolved["defaults"]["judges"]
        if default is None:
            tokens = list(resolved["judges"])
        elif default:
            tokens = _without_empty_bracket(list(default))
        else:
            notes.append(
                "--judges given but default_judges is empty; no judges run"
            )
            return (), notes
    else:
        tokens = _without_empty_bracket(list(flag.value))
    return _select_judge_tokens(tokens, resolved), notes


def _select_judge_tokens(tokens, resolved):
    configured = list(resolved["judges"])
    roster = ", ".join(configured) if configured else "none configured"
    selected = []
    for token in tokens:
        if token == "*":
            for name in configured:
                if name not in selected:
                    selected.append(name)
        elif token in configured:
            if token not in selected:
                selected.append(token)
        else:
            raise SpecError(f"unknown judge '{token}' ({roster})")
    return tuple(selected)


def infeasible_pairs(resolved, scorers, datasets):
    """Ordered (kind, scorer_name, dataset_name) triples for the pairs a
    reference-requiring scorer cannot run on (dataset has no
    ``reference_field``): metrics first (resolved order), then judges
    (resolved order), datasets in config order."""
    pairs = []
    for name in scorers.metrics:
        if not metrics.get(name).requires_reference:
            continue
        for dataset in datasets.values():
            if dataset.decl["reference_field"] is None:
                pairs.append(("metric", name, dataset.name))
    for name in scorers.judges:
        if not resolved["judges"][name]["requires_reference"]:
            continue
        for dataset in datasets.values():
            if dataset.decl["reference_field"] is None:
                pairs.append(("judge", name, dataset.name))
    return pairs


def run_metrics_phase(
    store, resolved, scorers, infeasible, datasets, selected, summarizers,
    console,
):
    """Metrics phase over every item (dataset × selected index × summarizer),
    one atomic (item, scorer) unit at a time; a metric algorithm failure is a
    RuntimeFailure (exit 1) before any judge call."""
    specs = metrics.resolve(list(scorers.metrics))
    surfaces = {}
    items = missing_generation = committed = skipped = excluded = dropped = 0
    for dataset in datasets.values():
        for index in selected[dataset.name]:
            entry = dataset.entries[index]
            transcript_sha = transcript_id(entry["transcript"])
            reference = None
            reference_loaded = False
            for summarizer in summarizers:
                items += 1
                surface_key = (
                    summarizer.model,
                    canonical_json(summarizer.model_args),
                    summarizer.template,
                    canonical_json(summarizer.gen_params),
                )
                surface = surfaces.get(surface_key)
                if surface is None:
                    surface = _item_surface(resolved, summarizer)
                    surfaces[surface_key] = surface
                model_sha, template, template_sha = surface
                generation_sha = generation_id(
                    transcript_sha, model_sha, summarizer.model_args,
                    template_sha, summarizer.gen_params,
                )
                generation_text = store.get_generation(generation_sha)
                if generation_text is None:
                    missing_generation += 1
                    continue
                for spec in specs:
                    if (spec.name, dataset.name) in infeasible:
                        continue
                    if spec.requires_reference:
                        if not reference_loaded:
                            reference = _read_reference(dataset.decl, index)
                            reference_loaded = True
                        if reference is None:
                            console.warn(
                                f"metric '{spec.name}' has no reference "
                                f"for entry #{index} in dataset "
                                f"'{dataset.name}' (pair skipped)"
                            )
                            dropped += 1
                            continue
                    reference_sha = (
                        summary_id(reference)
                        if spec.requires_reference
                        else None
                    )
                    unit_sha = metric_evaluation_id(
                        spec.name, generation_sha, reference_sha
                    )
                    if store.get_metric_evaluation(unit_sha) is not None:
                        skipped += 1
                        continue
                    value = _compute_metric(
                        spec, entry, generation_text, reference, template,
                        index, dataset.name,
                    )
                    if value is None:
                        excluded += 1
                        continue
                    with store.transaction():
                        if spec.requires_reference:
                            store.upsert_reference_summary(
                                reference, transcript_sha, dataset.name,
                                entry.get("entry_id"), index,
                            )
                        store.upsert_metric_evaluation(
                            spec.name, generation_sha, reference_sha, value
                        )
                    committed += 1
    return MetricsPhaseResult(
        items=items,
        missing_generation=missing_generation,
        committed=committed,
        skipped=skipped,
        excluded=excluded,
        dropped=dropped,
    )


def score_plan(store, resolved, scorers, infeasible, datasets, selected, summarizers):
    """Resume pre-scan: every (item, scorer) unit counts "to run" or
    "already scored" by evaluation-row existence alone — no generation
    fetch, no reference parsing, so an uncommitted generation (a
    --generate run) still reports the full remainder before generate."""
    surfaces = {}
    judge_shas = {}
    items = to_run = already_scored = 0
    for dataset in datasets.values():
        for index in selected[dataset.name]:
            entry = dataset.entries[index]
            transcript_sha = transcript_id(entry["transcript"])
            for summarizer in summarizers:
                items += 1
                surface_key = (
                    summarizer.model,
                    canonical_json(summarizer.model_args),
                    summarizer.template,
                    canonical_json(summarizer.gen_params),
                )
                surface = surfaces.get(surface_key)
                if surface is None:
                    surface = _item_surface(resolved, summarizer)
                    surfaces[surface_key] = surface
                model_sha, _template, template_sha = surface
                generation_sha = generation_id(
                    transcript_sha, model_sha, summarizer.model_args,
                    template_sha, summarizer.gen_params,
                )
                for name in scorers.metrics:
                    if (name, dataset.name) in infeasible:
                        continue
                    if store.has_metric_evaluation(name, generation_sha):
                        already_scored += 1
                    else:
                        to_run += 1
                for name in scorers.judges:
                    if (name, dataset.name) in infeasible:
                        continue
                    judge_sha = judge_shas.get(name)
                    if judge_sha is None:
                        judge_sha = _judge_sha(resolved, name)
                        judge_shas[name] = judge_sha
                    if store.has_judge_evaluation(judge_sha, generation_sha):
                        already_scored += 1
                    else:
                        to_run += 1
    return ScorePlan(
        metrics=len(scorers.metrics),
        judges=len(scorers.judges),
        items=items,
        to_run=to_run,
        already_scored=already_scored,
        infeasible_pairs=len(infeasible),
    )


def _judge_sha(resolved, name):
    entry = resolved["judges"][name]
    return judge_id(
        entry["model_name"], entry["gen_params"], entry["system_content"],
        entry["user_template"], entry["requires_reference"],
    )


def score_metrics(
    resolved, store_path, metrics_flag, judges_flag, datasets, selected,
    summarizer_selection, console,
):
    """Pre-effect (resolve scorers + summarizers, drop infeasible reference
    pairs with warns) runs BEFORE the store is opened; then the metrics
    phase, store closed in a finally. Returns (scorers, phase result)."""
    scorers = resolve_scorers(resolved, metrics_flag, judges_flag)
    summarizers = select_summarizers(resolved, *summarizer_selection)
    pairs = infeasible_pairs(resolved, scorers, datasets)
    for kind, name, dataset_name in pairs:
        console.warn(
            f"{kind} '{name}' requires reference summaries; "
            f"dataset '{dataset_name}' has none (pair skipped)"
        )
    infeasible = {(name, dataset_name) for _, name, dataset_name in pairs}
    store = Store(store_path)
    try:
        result = run_metrics_phase(
            store, resolved, scorers, infeasible, datasets, selected,
            summarizers, console,
        )
    finally:
        store.close()
    return scorers, result


def run_judges_phase(
    store, resolved, scorers, infeasible, datasets, selected, summarizers,
    client, judge_call, console,
):
    """Judges phase over every item (dataset × selected index ×
    summarizer), one atomic (item, judge) unit at a time; resume skips a
    unit whose evaluation row already exists (no call, no tokens)."""
    if not scorers.judges:
        return JudgePhaseResult(0, 0, 0, 0, 0, 0)
    surfaces = {}
    judge_shas = {}
    items = missing_generation = committed = skipped = dropped = failed = 0
    for dataset in datasets.values():
        for index in selected[dataset.name]:
            entry = dataset.entries[index]
            transcript_sha = transcript_id(entry["transcript"])
            reference = None
            reference_loaded = False
            for summarizer in summarizers:
                items += 1
                surface_key = (
                    summarizer.model,
                    canonical_json(summarizer.model_args),
                    summarizer.template,
                    canonical_json(summarizer.gen_params),
                )
                surface = surfaces.get(surface_key)
                if surface is None:
                    surface = _item_surface(resolved, summarizer)
                    surfaces[surface_key] = surface
                model_sha, _template, template_sha = surface
                generation_sha = generation_id(
                    transcript_sha, model_sha, summarizer.model_args,
                    template_sha, summarizer.gen_params,
                )
                generation_text = store.get_generation(generation_sha)
                if generation_text is None:
                    missing_generation += 1
                    continue
                for name in scorers.judges:
                    if (name, dataset.name) in infeasible:
                        continue
                    judge_entry = resolved["judges"][name]
                    if judge_entry["requires_reference"]:
                        if not reference_loaded:
                            reference = _read_reference(dataset.decl, index)
                            reference_loaded = True
                        if reference is None:
                            console.warn(
                                f"judge '{name}' has no reference "
                                f"for entry #{index} in dataset "
                                f"'{dataset.name}' (pair skipped)"
                            )
                            dropped += 1
                            continue
                    reference_sha = (
                        summary_id(reference)
                        if judge_entry["requires_reference"]
                        else None
                    )
                    judge_sha = judge_shas.get(name)
                    if judge_sha is None:
                        judge_sha = _judge_sha(resolved, name)
                        judge_shas[name] = judge_sha
                    unit_sha = judge_evaluation_id(
                        judge_sha, generation_sha, reference_sha
                    )
                    if store.get_judge_evaluation(unit_sha) is not None:
                        skipped += 1
                        continue
                    try:
                        scores = judge_call(
                            client, name, judge_entry, entry["transcript"],
                            generation_text, reference,
                        )
                    except RuntimeFailure as exc:
                        raise RuntimeFailure(
                            f"judge '{name}' failed for entry #{index} "
                            f"in dataset '{dataset.name}': {exc}"
                        ) from exc
                    if scores is None:
                        console.warn(
                            f"judge '{name}' returned no extractable "
                            f"qualities for entry #{index} in dataset "
                            f"'{dataset.name}' (unit not committed)"
                        )
                        failed += 1
                        continue
                    with store.transaction():
                        if judge_entry["requires_reference"]:
                            store.upsert_reference_summary(
                                reference, transcript_sha, dataset.name,
                                entry.get("entry_id"), index,
                            )
                        store.upsert_judge_evaluation(
                            judge_sha, generation_sha, reference_sha,
                            scores.get("factual_correctness"),
                            scores.get("completeness"),
                            scores.get("conciseness"),
                        )
                    committed += 1
    return JudgePhaseResult(
        items=items,
        missing_generation=missing_generation,
        committed=committed,
        skipped=skipped,
        dropped=dropped,
        failed=failed,
    )


def _plural(count, word):
    return f"{count} {word}{'s' if count != 1 else ''}"


def _has_scorable_pair(scorers, infeasible, selected):
    """Whether any (scorer, in-scope dataset) pair is feasible; in-scope
    means at least one selected entry (selection-scoped)."""
    in_scope = [name for name, indices in selected.items() if indices]
    return any(
        (name, dataset_name) not in infeasible
        for name in (*scorers.metrics, *scorers.judges)
        for dataset_name in in_scope
    )


def score(
    resolved, store_path, metrics_flag, judges_flag, datasets, selected,
    summarizer_selection, console, client, judge_call, generate=None,
):
    """Full score run; prints everything itself. Pre-effect (scorers,
    summarizers, judge credential preflight, infeasible warns, the
    no-scorable-pairs note) before the store, then the plan (resume
    pre-scan), the plan(generate) line when a generate hook is given,
    and the plan(score) line -- all BEFORE the hook (a stage-1 failure
    propagates before any scoring), then the metrics phase (a failure
    propagates before any judge call), then the judges phase; the store
    closes in a finally; the generation and no-scorers notes and
    done(score) print after close. Returns (scorers, plan,
    metrics_result, judges_result)."""
    scorers = resolve_scorers(resolved, metrics_flag, judges_flag)
    summarizers = select_summarizers(resolved, *summarizer_selection)
    _credential_preflight(resolved, judges_flag)
    pairs = infeasible_pairs(resolved, scorers, datasets)
    for kind, name, dataset_name in pairs:
        console.warn(
            f"{kind} '{name}' requires reference summaries; "
            f"dataset '{dataset_name}' has none (pair skipped)"
        )
    infeasible = {(name, dataset_name) for _, name, dataset_name in pairs}
    if (scorers.metrics or scorers.judges) and not _has_scorable_pair(
        scorers, infeasible, selected,
    ):
        console.note("no scorable pairs in scope; nothing scored")
    store = Store(store_path)
    try:
        plan = score_plan(
            store, resolved, scorers, infeasible, datasets, selected,
            summarizers,
        )
        if generate is not None:
            from .generate import generate_plan_text
            console.plan(
                "generate", generate_plan_text(datasets, selected, summarizers)
            )
        scorer_text = (
            "0 metric(s), 0 judge(s)"
            if plan.metrics == 0 and plan.judges == 0
            else f"{_plural(plan.metrics, 'metric')}, "
            f"{_plural(plan.judges, 'judge')}"
        )
        console.plan(
            "score",
            f"{scorer_text} | {_plural(plan.items, 'item')} | "
            f"{plan.to_run} to run, {plan.already_scored} already scored | "
            f"{plan.infeasible_pairs} infeasible",
        )
        if generate is not None:
            generate(store, console)
        metrics_result = run_metrics_phase(
            store, resolved, scorers, infeasible, datasets, selected,
            summarizers, console,
        )
        judges_result = run_judges_phase(
            store, resolved, scorers, infeasible, datasets, selected,
            summarizers, client, judge_call, console,
        )
    finally:
        store.close()
    if not (scorers.metrics or scorers.judges):
        console.note("no metrics or judges selected; nothing scored")
    elif generate is None and plan.items > 0:
        missing = metrics_result.missing_generation
        total = metrics_result.items
        if missing == total:
            console.note(
                "no committed generations in scope; run 'generate' first"
            )
        elif missing > 0:
            console.note(
                f"{missing} selected items have no committed generation; "
                f"run 'generate' first"
            )
    console.done(
        "score",
        f"{metrics_result.committed + judges_result.committed} committed, "
        f"{metrics_result.dropped + judges_result.dropped} dropped, "
        f"{judges_result.failed} failed",
    )
    return scorers, plan, metrics_result, judges_result


def _item_surface(resolved, summarizer):
    """(model_sha, template, template_sha) for one summarizer; the model
    file and the template file are each read at most once per phase."""
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
    return model_sha, template, template_sha


def _compute_metric(
    spec, entry, generation_text, reference, template, index, dataset_name,
):
    prompt_text = template.system_content + template.user_prefix
    metric_input = MetricInput(
        transcript_text=entry["transcript"],
        generation_text=generation_text,
        reference_summary_text=reference if spec.requires_reference else None,
        prompt_text=prompt_text,
    )
    try:
        return spec.compute(metric_input)
    except Exception as exc:
        raise RuntimeFailure(
            f"metric '{spec.name}' failed for entry #{index} "
            f"in dataset '{dataset_name}': {exc}"
        ) from exc


def _read_reference(decl, index):
    """The reference text for one entry, or None (R2 drop) when the field is
    absent or empty; any read/parse failure is a RuntimeFailure (exit 1)."""
    path = decl["path"]
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except FileNotFoundError:
        raise RuntimeFailure(f"reference: file not found: {path}") from None
    except (OSError, UnicodeDecodeError) as exc:
        detail = getattr(exc, "strerror", None) or exc
        raise RuntimeFailure(
            f"reference: cannot read {path}: {detail}"
        ) from None
    extension = path.rsplit(".", 1)[1].lower() if "." in path else ""
    if extension == "csv":
        rows = list(csv.reader(text.splitlines()))
        if len(rows) <= index + 1:
            raise RuntimeFailure(f"reference: {path} has no entry #{index}")
        record = dict(zip(rows[0], rows[index + 1]))
    else:
        records = []
        for line in text.splitlines():
            if not line:
                continue
            try:
                line_record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeFailure(
                    f"reference: malformed {path}: not valid JSON: {exc}"
                ) from exc
            if not isinstance(line_record, dict):
                raise RuntimeFailure(
                    f"reference: malformed {path}: expected a JSON object"
                )
            records.append(line_record)
        if index >= len(records):
            raise RuntimeFailure(f"reference: {path} has no entry #{index}")
        record = records[index]
    value = record.get(decl["reference_field"])
    if value in (None, ""):
        return None
    return value
