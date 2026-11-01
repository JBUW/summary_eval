"""The report command: a strictly read-only roll-up of stored evaluations.

Nothing here mutates the store (no commits, no upserts), spawns a server, or
calls a model or judge; it reads rows and prints a display.
"""
import csv
import json
import os

from .errors import SpecError
from .identities import generation_id, transcript_id
from .judge_parser import QUALITIES
from .scoring import judge_sha
from .store import Store
from .summarizers import SummarizerInputsCache

_ZERO_ROWS_NOTE = (
    "no scored results in scope; run 'score' (or 'score --generate') first"
)


def apply_blind_sample(scope, n):
    """The last n entries of each dataset; n == 0 is an explicit empty scope."""
    if n is None:
        return scope
    if n == 0:
        return {name: [] for name in scope}
    return {name: indices[-n:] for name, indices in scope.items()}


def candidate_label(summarizer):
    if summarizer.name is not None:
        return summarizer.name
    return f"{summarizer.model}+{summarizer.template}"


def _stats(values):
    if not values:
        return (0, None, None, None)
    return (len(values), sum(values) / len(values), min(values), max(values))


def _row(candidate, dataset, scorer, values):
    n, mean, low, high = _stats(values)
    row = {"candidate": candidate}
    if dataset is not None:
        row["dataset"] = dataset
    row["scorer"] = scorer
    row["n"] = n
    row["mean"] = mean
    row["min"] = low
    row["max"] = high
    return row


def _cells(row):
    def formatted(value):
        return "-" if value is None else f"{value:.2f}"

    cells = [str(row[key]) for key in ("candidate", "dataset", "scorer", "n")
             if key in row]
    cells.extend(formatted(row[key]) for key in ("mean", "min", "max"))
    return cells


def _header(by_dataset):
    return (
        ["candidate", "dataset", "scorer", "n", "mean", "min", "max"]
        if by_dataset
        else ["candidate", "scorer", "n", "mean", "min", "max"]
    )


def _group_scope(dataset, indices):
    return {transcript_id(dataset.entries[i]["transcript"]) for i in indices}


def _collect_rows(store, resolved, summarizers, scorers, groups):
    """Candidates match stored rows by content identity, as in score: the
    model file and template are hashed, never looked up by name."""
    inputs = SummarizerInputsCache(resolved)
    rows = []
    for group_label, group_scope in groups:
        for candidate in summarizers:
            candidate_inputs = inputs.inputs(candidate)
            generation_shas = [
                generation_id(
                    transcript_sha, candidate_inputs.model_sha,
                    candidate.model_args, candidate_inputs.template_sha,
                    candidate.gen_params,
                )
                for transcript_sha in sorted(group_scope)
            ]
            label = candidate_label(candidate)
            for metric in scorers.metrics:
                rows.append(_row(
                    label, group_label, metric,
                    store.metric_values(metric, generation_shas),
                ))
            for judge in scorers.judges:
                sha = judge_sha(resolved, judge)
                for quality in QUALITIES:
                    rows.append(_row(
                        label, group_label, f"{quality} (judge)",
                        store.judge_quality_values(sha, quality, generation_shas),
                    ))
    return rows


def report(resolved, store_path, datasets, scope, summarizers, scorers, console,
           by_dataset=False, json_out=False, csv_path=None):
    if csv_path is not None:
        parent = os.path.dirname(csv_path)
        if parent and not os.path.isdir(parent):
            raise SpecError(
                f"csv path '{csv_path}': parent directory does not exist"
            )
    store = Store(store_path)
    try:
        if by_dataset:
            groups = [
                (name, _group_scope(datasets[name], indices))
                for name, indices in scope.items()
            ]
        else:
            union = set()
            for name, indices in scope.items():
                union |= _group_scope(datasets[name], indices)
            groups = [(None, union)]
        rows = _collect_rows(store, resolved, summarizers, scorers, groups)
    finally:
        store.close()
    if sum(row["n"] for row in rows) == 0:
        console.note(_ZERO_ROWS_NOTE)
        return 0
    if json_out:
        console.log(json.dumps(rows, indent=2))
        return 0
    if csv_path is not None:
        with open(csv_path, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(_header(by_dataset))
            writer.writerows(_cells(row) for row in rows)
        console.note(f"wrote {len(rows)} rows to {csv_path}")
        return 0
    console.log(",".join(_header(by_dataset)))
    for row in rows:
        console.log(",".join(_cells(row)))
    return 0
