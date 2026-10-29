"""Ticket 10 — report core units: blind sampling, candidate labels, stats,
and report() in-process against a real resolved config (validate_config on a
harness-written workspace, never hand-crafted): exact table lines, the
zero-rows note, csv rows + note, csv missing-parent (in-process and via the
CLI), exact --json text, --by dataset shape, multiple-reference pooling,
latest-wins name lookup, and NULL quality skip."""
import contextlib
import csv
import io
import json
import os
import time

import harness  # noqa: F401  (puts the repo root on sys.path)

import pytest

from evalapp.config import validate_config, validate_datasets
from evalapp.console import Console
from evalapp.datasets import load_dataset
from evalapp.errors import SpecError
from evalapp.report import apply_blind_sample, candidate_label, _stats, report
from evalapp.scoring import Flag, judge_sha, resolve_scorers
from evalapp.selection import resolve_selection
from evalapp.store import Store
from evalapp.summarizers import Summarizer, select_summarizers

ZERO_ROWS = "note: no scored results in scope; run 'score' (or 'score --generate') first"


def _workspace(tmp_path):
    workspace = harness.standard_workspace(tmp_path)
    harness.add_summarizer_section(os.path.join(str(workspace), "config.json"))
    return workspace


def _add_judge(workspace):
    path = os.path.join(str(workspace), "config.json")
    with open(path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    config["judges"] = {
        "j": {
            "endpoint": "http://127.0.0.1:1",
            "model_name": "pin",
            "api_key_env": "EVALAPP_TEST_JUDGE_KEY",
            "requires_reference": False,
            "gen_params": {},
            "system_content": "",
            "user_template": "Judge {transcript} against {summary}",
        }
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2)
        handle.write("\n")


def _seed(store):
    model_sha = store.upsert_model(b"model-bytes", "m", "model.bin")
    template_sha = store.upsert_template("sys", "usr", "t")
    generation_shas, transcript_shas = [], []
    for index in range(3):
        transcript_sha = store.upsert_transcript(
            f"transcript {index}", "named", f"id-{index:02d}", index
        )
        generation_shas.append(
            store.upsert_generation(
                transcript_sha, model_sha, {}, template_sha, {},
                f"gen {index}",
            )
        )
        transcript_shas.append(transcript_sha)
    return model_sha, template_sha, generation_shas, transcript_shas


def _context(workspace, with_judge=False):
    if with_judge:
        _add_judge(workspace)
    previous = os.getcwd()
    os.chdir(str(workspace))
    try:
        with open("config.json", "r", encoding="utf-8") as handle:
            config = json.load(handle)
        errors, resolved = validate_config(config, Console())
        assert errors == []
        declared = validate_datasets(config)
        datasets = {name: load_dataset(name, decl)
                    for name, decl in declared.items()}
        scope = resolve_selection(None, datasets)
        summarizers = select_summarizers(resolved)
    finally:
        os.chdir(previous)
    return {
        "workspace": workspace,
        "resolved": resolved,
        "datasets": datasets,
        "scope": scope,
        "summarizers": summarizers,
    }


def _seed_evaluations(context, store, generation_shas):
    entry = context["resolved"]["judges"]["j"]
    store.upsert_judge(
        entry["model_name"], entry["gen_params"], entry["system_content"],
        entry["user_template"], entry["requires_reference"], "j",
        entry["endpoint"], entry["api_key_env"],
    )
    store.upsert_metric_evaluation("faithfulness", generation_shas[0], None, 0.25)
    store.upsert_metric_evaluation("faithfulness", generation_shas[1], None, 0.75)
    sha = judge_sha(context["resolved"], "j")
    store.upsert_judge_evaluation(sha, generation_shas[0], None, 1.0, None, 0.5)
    store.upsert_judge_evaluation(sha, generation_shas[1], None, None, 0.75, None)


def _run(context, scorers, by_dataset=False, json_out=False, csv_path=None):
    console = Console()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = report(
            context["resolved"],
            str(context["workspace"] / "store.db"),
            context["datasets"],
            context["scope"],
            context["summarizers"],
            scorers,
            console,
            by_dataset=by_dataset,
            json_out=json_out,
            csv_path=csv_path,
        )
    raw = buffer.getvalue()
    return code, [line for line in raw.splitlines() if line], raw


def _seeded_context(tmp_path):
    context = _context(_workspace(tmp_path), with_judge=True)
    store = Store(str(context["workspace"] / "store.db"))
    try:
        _, _, generation_shas, _ = _seed(store)
        _seed_evaluations(context, store, generation_shas)
    finally:
        store.close()
    return context


def test_apply_blind_sample():
    scope = {"a": [0, 1, 2, 3, 4], "b": [5, 6]}
    assert apply_blind_sample(scope, None) is scope
    assert apply_blind_sample(scope, 0) == {"a": [], "b": []}
    assert apply_blind_sample(scope, 2) == {"a": [3, 4], "b": [5, 6]}
    assert apply_blind_sample(scope, 9) == scope


def test_candidate_label():
    assert candidate_label(Summarizer("s", "m", {}, "t", {})) == "s"
    assert candidate_label(Summarizer(None, "m", {}, "t", {})) == "m+t"


def test_stats():
    assert _stats([]) == (0, None, None, None)
    assert _stats([0.25, 0.5, 0.75]) == (3, 0.5, 0.25, 0.75)
    assert _stats([0.25]) == (1, 0.25, 0.25, 0.25)


def test_default_table_exact(tmp_path):
    context = _seeded_context(tmp_path)
    scorers = resolve_scorers(
        context["resolved"], Flag(value=["faithfulness"]), Flag(value=["j"])
    )
    code, lines, _ = _run(context, scorers)
    assert code == 0
    assert lines == [
        "candidate,scorer,n,mean,min,max",
        "s,faithfulness,2,0.50,0.25,0.75",
        "s,factual_correctness (judge),1,1.00,1.00,1.00",
        "s,completeness (judge),1,0.75,0.75,0.75",
        "s,conciseness (judge),1,0.50,0.50,0.50",
    ]


def test_zero_rows_note(tmp_path):
    context = _context(_workspace(tmp_path))
    store = Store(str(context["workspace"] / "store.db"))
    store.close()
    scorers = resolve_scorers(context["resolved"], Flag(no=False), Flag(no=False))
    code, lines, _ = _run(context, scorers)
    assert code == 0
    assert lines == [ZERO_ROWS]


def test_csv_rows_and_note(tmp_path):
    context = _seeded_context(tmp_path)
    out_dir = context["workspace"] / "out"
    out_dir.mkdir()
    csv_path = str(out_dir / "rows.csv")
    scorers = resolve_scorers(
        context["resolved"], Flag(value=["faithfulness"]), Flag(value=["j"])
    )
    code, _, raw = _run(context, scorers, csv_path=csv_path)
    assert code == 0
    assert raw == f"note: wrote 4 rows to {csv_path}\n"
    with open(csv_path, newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows == [
        ["candidate", "scorer", "n", "mean", "min", "max"],
        ["s", "faithfulness", "2", "0.50", "0.25", "0.75"],
        ["s", "factual_correctness (judge)", "1", "1.00", "1.00", "1.00"],
        ["s", "completeness (judge)", "1", "0.75", "0.75", "0.75"],
        ["s", "conciseness (judge)", "1", "0.50", "0.50", "0.50"],
    ]


def test_csv_not_written_on_zero_rows(tmp_path):
    context = _context(_workspace(tmp_path))
    out_dir = context["workspace"] / "out"
    out_dir.mkdir()
    csv_path = str(out_dir / "rows.csv")
    store = Store(str(context["workspace"] / "store.db"))
    store.close()
    scorers = resolve_scorers(context["resolved"], Flag(no=False), Flag(no=False))
    code, lines, _ = _run(context, scorers, csv_path=csv_path)
    assert code == 0
    assert lines == [ZERO_ROWS]
    assert not os.path.exists(csv_path)


def test_csv_missing_parent_in_process(tmp_path):
    context = _context(_workspace(tmp_path))
    scorers = resolve_scorers(context["resolved"], Flag(no=False), Flag(no=False))
    with pytest.raises(SpecError) as excinfo:
        _run(context, scorers, csv_path="nope/rows.csv")
    assert str(excinfo.value) == (
        "csv path 'nope/rows.csv': parent directory does not exist"
    )


def test_csv_missing_parent_cli(tmp_path):
    harness.standard_workspace(tmp_path)
    result = harness.run_cli(["report", "--csv", "nope/rows.csv"], cwd=tmp_path)
    result.assert_exit(2)
    assert result.lines == [
        "plan(report): named 12 entries",
        "plan(report): unnamed 12 entries",
        "error: csv path 'nope/rows.csv': parent directory does not exist",
    ]


def test_json_exact(tmp_path):
    context = _seeded_context(tmp_path)
    scorers = resolve_scorers(
        context["resolved"], Flag(value=["faithfulness"]), Flag(value=["j"])
    )
    code, _, raw = _run(context, scorers, json_out=True)
    assert code == 0
    expected = [
        {"candidate": "s", "scorer": "faithfulness", "n": 2,
         "mean": 0.5, "min": 0.25, "max": 0.75},
        {"candidate": "s", "scorer": "factual_correctness (judge)", "n": 1,
         "mean": 1.0, "min": 1.0, "max": 1.0},
        {"candidate": "s", "scorer": "completeness (judge)", "n": 1,
         "mean": 0.75, "min": 0.75, "max": 0.75},
        {"candidate": "s", "scorer": "conciseness (judge)", "n": 1,
         "mean": 0.5, "min": 0.5, "max": 0.5},
    ]
    assert raw == json.dumps(expected, indent=2) + "\n"
    assert json.loads(raw) == expected


def test_by_dataset_shape(tmp_path):
    context = _context(_workspace(tmp_path))
    store = Store(str(context["workspace"] / "store.db"))
    try:
        _, _, generation_shas, _ = _seed(store)
        store.upsert_metric_evaluation("faithfulness", generation_shas[0], None, 0.25)
        store.upsert_metric_evaluation("faithfulness", generation_shas[1], None, 0.75)
    finally:
        store.close()
    scorers = resolve_scorers(
        context["resolved"], Flag(value=["faithfulness"]), Flag(no=True)
    )
    code, lines, _ = _run(context, scorers, by_dataset=True)
    assert code == 0
    assert lines == [
        "candidate,dataset,scorer,n,mean,min,max",
        "s,named,faithfulness,2,0.50,0.25,0.75",
        "s,unnamed,faithfulness,2,0.50,0.25,0.75",
    ]


def test_multiple_reference_pooling(tmp_path):
    context = _context(_workspace(tmp_path))
    store = Store(str(context["workspace"] / "store.db"))
    try:
        _, _, generation_shas, transcript_shas = _seed(store)
        first = generation_shas[0]
        ref_one = store.upsert_reference_summary(
            "ref one", transcript_shas[0], "named", "id-00", 0
        )
        ref_two = store.upsert_reference_summary(
            "ref two", transcript_shas[0], "named", "id-00", 0
        )
        store.upsert_metric_evaluation("faithfulness", first, ref_one, 0.25)
        store.upsert_metric_evaluation("faithfulness", first, ref_two, 0.75)
    finally:
        store.close()
    scorers = resolve_scorers(
        context["resolved"], Flag(value=["faithfulness"]), Flag(no=True)
    )
    code, lines, _ = _run(context, scorers)
    assert code == 0
    assert lines == [
        "candidate,scorer,n,mean,min,max",
        "s,faithfulness,2,0.50,0.25,0.75",
    ]


def test_latest_wins_name_lookup(tmp_path):
    context = _context(_workspace(tmp_path))
    store = Store(str(context["workspace"] / "store.db"))
    try:
        old_sha = store.upsert_model(b"old-bytes", "m", "model.bin")
        time.sleep(1.05)
        new_sha = store.upsert_model(b"model-bytes", "m", "model.bin")
        template_sha = store.upsert_template("sys", "usr", "t")
        transcript_sha = store.upsert_transcript(
            "transcript 0", "named", "id-00", 0
        )
        store.upsert_generation(
            transcript_sha, old_sha, {}, template_sha, {}, "old gen"
        )
        new_generation = store.upsert_generation(
            transcript_sha, new_sha, {}, template_sha, {}, "new gen"
        )
        store.upsert_metric_evaluation("faithfulness", new_generation, None, 0.75)
    finally:
        store.close()
    scorers = resolve_scorers(
        context["resolved"], Flag(value=["faithfulness"]), Flag(no=True)
    )
    code, lines, _ = _run(context, scorers)
    assert code == 0
    assert lines == [
        "candidate,scorer,n,mean,min,max",
        "s,faithfulness,1,0.75,0.75,0.75",
    ]
