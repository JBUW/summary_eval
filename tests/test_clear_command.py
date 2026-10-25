import sqlite3

import harness
from evalapp import store


def _seed_counts(tmp_path):
    """Seed 10 rows: 3 transcripts, one each in the other seven tables."""
    path = str(tmp_path / "store.db")
    opened = store.Store(path)
    try:
        transcript_shas = [
            opened.upsert_transcript(f"text {index}", "named", f"id-{index:02d}", index)
            for index in range(3)
        ]
        opened.upsert_reference_summary(
            "ref 0", transcript_shas[0], "named", "id-00", 0
        )
        model_sha = opened.upsert_model(b"model bytes", "m", "/models/m.gguf")
        template_sha = opened.upsert_template("sys", "prefix", "t")
        generation_sha = opened.upsert_generation(
            transcript_shas[0], model_sha, {}, template_sha, {"max_tokens": 1}, "gen text"
        )
        judge_sha = opened.upsert_judge(
            "pin", {"temperature": 0}, "sys", "tpl", True, "j", "https://e/v1", None
        )
        opened.upsert_judge_evaluation(judge_sha, generation_sha, None, 0.9, 0.8, 0.75)
        opened.upsert_metric_evaluation("rouge_l", generation_sha, None, 0.42)
    finally:
        opened.close()
    return path


def _table_counts(path):
    db = sqlite3.connect(path)
    try:
        tables = [
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master"
                " WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {
            table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in tables
        }
    finally:
        db.close()


def _plan_line(counts):
    return (
        "plan(clear): store store.db | "
        + " | ".join(f"{table} {count}" for table, count in counts)
    )


def test_clear_no_store_is_a_note(tmp_path):
    harness.standard_workspace(tmp_path)
    result = harness.run_cli(["clear"], cwd=tmp_path)
    result.assert_exit(0)
    assert result.lines == ["note: no store at store.db; nothing to clear"]
    assert not (tmp_path / "store.db").exists()


def test_clear_yes_no_store_is_a_note(tmp_path):
    harness.standard_workspace(tmp_path)
    result = harness.run_cli(["clear", "--yes"], cwd=tmp_path)
    result.assert_exit(0)
    assert result.lines == ["note: no store at store.db; nothing to clear"]
    assert not (tmp_path / "store.db").exists()


def test_clear_missing_config_fails(tmp_path):
    result = harness.run_cli(["clear"], cwd=tmp_path)
    result.assert_exit(2)
    assert len(result.with_prefix("error:")) == 1


def test_clear_dry_run_prints_counts_and_keeps_rows(tmp_path):
    harness.standard_workspace(tmp_path)
    _seed_counts(tmp_path)
    result = harness.run_cli(["clear"], cwd=tmp_path)
    result.assert_exit(0)
    assert result.lines == [
        _plan_line(
            [
                ("transcripts", 3),
                ("reference_summaries", 1),
                ("models", 1),
                ("prompt_templates", 1),
                ("generations", 1),
                ("judges", 1),
                ("judge_evaluations", 1),
                ("metric_evaluations", 1),
            ]
        ),
        "note: re-run with --yes to delete all rows (this cannot be undone)",
    ]
    counts = _table_counts(str(tmp_path / "store.db"))
    assert counts["transcripts"] == 3
    assert sum(counts.values()) == 10


def test_clear_yes_deletes_every_row(tmp_path):
    harness.standard_workspace(tmp_path)
    _seed_counts(tmp_path)
    result = harness.run_cli(["clear", "--yes"], cwd=tmp_path)
    result.assert_exit(0)
    assert result.lines == ["done(clear): 10 rows deleted across 8 tables"]
    counts = _table_counts(str(tmp_path / "store.db"))
    assert set(counts) == set(store.TABLES)
    assert all(count == 0 for count in counts.values())


def test_clear_zero_table_file_bootstraps_first(tmp_path):
    harness.standard_workspace(tmp_path)
    with sqlite3.connect(str(tmp_path / "store.db")):
        pass
    result = harness.run_cli(["clear"], cwd=tmp_path)
    result.assert_exit(0)
    assert result.lines == [
        _plan_line([(table, 0) for table in store.TABLES]),
        "note: created empty store at store.db",
        "note: re-run with --yes to delete all rows (this cannot be undone)",
    ]
    counts = _table_counts(str(tmp_path / "store.db"))
    assert set(counts) == set(store.TABLES)
    assert all(count == 0 for count in counts.values())
