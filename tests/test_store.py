import contextlib
import sqlite3

import pytest

from evalapp import store
from evalapp.errors import RuntimeFailure, SpecError
from evalapp.identities import (
    generation_id,
    judge_evaluation_id,
    judge_id,
    metric_evaluation_id,
    transcript_id,
)


class _Clock:
    def __init__(self, value):
        self.value = value


def _freeze_clock(monkeypatch, initial="2026-01-01T00:00:00Z"):
    clock = _Clock(initial)
    monkeypatch.setattr(store, "_now", lambda: clock.value)
    return clock


@contextlib.contextmanager
def _raw(path):
    db = sqlite3.connect(path)
    try:
        yield db
    finally:
        db.close()


def _row(path, sql, *params):
    with _raw(path) as db:
        return db.execute(sql, params).fetchone()


def _table_names(path):
    with _raw(path) as db:
        return {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )}


def _seed_chain(opened, reference=True):
    """One row each in transcripts, models, prompt_templates, generations
    (and reference_summaries when reference=True), FK-linked."""
    transcript_sha = opened.upsert_transcript("text", "d", None, 0)
    model_sha = opened.upsert_model(b"bytes", "m", "/m.gguf")
    template_sha = opened.upsert_template("sys", "pre", "t")
    generation_sha = opened.upsert_generation(
        transcript_sha, model_sha, {}, template_sha, {"max_tokens": 1}, "gen text"
    )
    reference_sha = None
    if reference:
        reference_sha = opened.upsert_reference_summary("ref text", transcript_sha, "d", None, 0)
    return transcript_sha, model_sha, template_sha, generation_sha, reference_sha


def test_bootstrap_creates_directory_and_eight_tables(tmp_path):
    path = str(tmp_path / "nested" / "deeper" / "store.db")
    opened = store.Store(path)
    try:
        assert opened.created is True
        assert _table_names(path) == set(store.TABLES)
        assert [table for table, _ in opened.table_counts()] == list(store.TABLES)
        assert all(count == 0 for _, count in opened.table_counts())
    finally:
        opened.close()


def test_zero_table_file_is_bootstrapped(tmp_path):
    path = str(tmp_path / "store.db")
    with _raw(path):
        pass  # empty sqlite file, zero tables
    opened = store.Store(path)
    try:
        assert opened.created is True
        assert _table_names(path) == set(store.TABLES)
    finally:
        opened.close()


def test_existing_valid_store_is_not_created(tmp_path):
    path = str(tmp_path / "store.db")
    first = store.Store(path)
    first.close()
    second = store.Store(path)
    try:
        assert second.created is False
    finally:
        second.close()


def test_mismatch_missing_table_fails_with_hint(tmp_path):
    path = str(tmp_path / "store.db")
    first = store.Store(path)
    first.close()
    with _raw(path) as db:
        db.execute("DROP TABLE judges")
    with pytest.raises(SpecError, match="move or delete"):
        store.Store(path)


def test_mismatch_extra_table_fails_with_hint(tmp_path):
    path = str(tmp_path / "store.db")
    first = store.Store(path)
    first.close()
    with _raw(path) as db:
        db.execute("CREATE TABLE bogus (x TEXT)")
    with pytest.raises(SpecError, match="move or delete"):
        store.Store(path)


def test_mismatch_missing_column_fails_with_hint(tmp_path):
    path = str(tmp_path / "store.db")
    first = store.Store(path)
    first.close()
    with _raw(path) as db:
        db.execute("ALTER TABLE transcripts DROP COLUMN entry_index")
    with pytest.raises(SpecError, match="move or delete"):
        store.Store(path)


def test_garbage_file_fails_with_hint(tmp_path):
    path = str(tmp_path / "store.db")
    with open(path, "wb") as handle:
        handle.write(b"definitely not a sqlite database")
    with pytest.raises(SpecError, match="move or delete"):
        store.Store(path)


def test_transcript_upsert_stamp_rule(tmp_path, monkeypatch):
    clock = _freeze_clock(monkeypatch)
    t1 = "2026-01-02T00:00:00Z"
    path = str(tmp_path / "store.db")
    opened = store.Store(path)
    try:
        sha = opened.upsert_transcript("hello world", "meetbank", "m1", 3)
        assert sha == transcript_id("hello world")
        assert _row(path, "SELECT entry_id, entry_index, updated_at FROM transcripts") == ("m1", 3, "2026-01-01T00:00:00Z")
        clock.value = t1
        opened.upsert_transcript("hello world", "meetbank", "m1", 3)  # pure re-insert
        assert _row(path, "SELECT updated_at FROM transcripts") == ("2026-01-01T00:00:00Z",)
        opened.upsert_transcript("hello world", "meetbank", "m2", 4)  # courtesy change
        assert _row(path, "SELECT entry_id, entry_index, updated_at FROM transcripts") == ("m2", 4, t1)
    finally:
        opened.close()


def test_transcript_entry_id_null_round_trip(tmp_path, monkeypatch):
    clock = _freeze_clock(monkeypatch)
    t1 = "2026-02-01T00:00:00Z"
    path = str(tmp_path / "store.db")
    opened = store.Store(path)
    try:
        opened.upsert_transcript("no ids here", "unnamed", None, 7)
        assert _row(path, "SELECT entry_id IS NULL, entry_index FROM transcripts") == (1, 7)
        clock.value = t1
        opened.upsert_transcript("no ids here", "unnamed", None, 7)  # identical, NULL stays
        assert _row(path, "SELECT updated_at FROM transcripts") == ("2026-01-01T00:00:00Z",)
        opened.upsert_transcript("no ids here", "other", None, 7)  # dataset_name change
        assert _row(path, "SELECT dataset_name, updated_at FROM transcripts") == ("other", t1)
    finally:
        opened.close()


def test_content_addressed_transcript_last_seen_wins(tmp_path):
    path = str(tmp_path / "store.db")
    opened = store.Store(path)
    try:
        first = opened.upsert_transcript("same text", "dataset-a", "a1", 0)
        second = opened.upsert_transcript("same text", "dataset-b", "b9", 11)
        assert first == second
        assert _row(path, "SELECT COUNT(*) FROM transcripts") == (1,)
        assert _row(path, "SELECT dataset_name, entry_id, entry_index FROM transcripts") == ("dataset-b", "b9", 11)
    finally:
        opened.close()


def test_generation_is_input_addressed(tmp_path, monkeypatch):
    clock = _freeze_clock(monkeypatch)
    t1 = "2026-03-01T00:00:00Z"
    path = str(tmp_path / "store.db")
    opened = store.Store(path)
    try:
        transcript_sha, model_sha, template_sha, _, _ = _seed_chain(opened, reference=False)
        args = {"flash-attn": True}
        params = {"temperature": 0.3}
        expected = generation_id(transcript_sha, model_sha, args, template_sha, params)
        sha = opened.upsert_generation(transcript_sha, model_sha, args, template_sha, params, "summary one")
        assert sha == expected
        assert _row(
            path,
            "SELECT generation_text, model_args, gen_params FROM generations WHERE generation_sha256 = ?",
            sha,
        ) == (
            "summary one",
            '{"flash-attn":true}',
            '{"temperature":0.3}',
        )
        clock.value = t1
        opened.upsert_generation(transcript_sha, model_sha, args, template_sha, params, "summary one")
        assert _row(
            path,
            "SELECT COUNT(*), updated_at FROM generations WHERE generation_sha256 = ?",
            sha,
        ) == (1, "2026-01-01T00:00:00Z")
        # same inputs, different text: deduped to one row, stamped
        opened.upsert_generation(transcript_sha, model_sha, args, template_sha, params, "summary two")
        assert _row(
            path,
            "SELECT COUNT(*), generation_text, updated_at FROM generations WHERE generation_sha256 = ?",
            sha,
        ) == (1, "summary two", t1)
    finally:
        opened.close()


def test_judge_evaluation_nullables_and_re_evaluation_stamp(tmp_path, monkeypatch):
    clock = _freeze_clock(monkeypatch)
    t1 = "2026-04-01T00:00:00Z"
    path = str(tmp_path / "store.db")
    opened = store.Store(path)
    try:
        _, _, _, generation_sha, reference_sha = _seed_chain(opened)
        judge_sha = opened.upsert_judge(
            "pin", {"temperature": 0}, "sys", "tpl", True, "j", "https://e/v1", None
        )
        assert judge_sha == judge_id("pin", {"temperature": 0}, "sys", "tpl", True)
        sha = opened.upsert_judge_evaluation(judge_sha, generation_sha, reference_sha, 0.9, None, 0.75)
        assert sha == judge_evaluation_id(judge_sha, generation_sha, reference_sha)
        assert _row(path, "SELECT factual_correctness, completeness, conciseness FROM judge_evaluations") == (
            0.9, None, 0.75
        )
        clock.value = t1
        opened.upsert_judge_evaluation(judge_sha, generation_sha, reference_sha, 0.9, None, 0.75)
        assert _row(path, "SELECT updated_at FROM judge_evaluations") == ("2026-01-01T00:00:00Z",)
        opened.upsert_judge_evaluation(judge_sha, generation_sha, reference_sha, 0.9, 0.8, 0.75)
        assert _row(path, "SELECT completeness, updated_at FROM judge_evaluations") == (0.8, t1)
        # a NULL reference is a different identity (JSON null) and needs no reference row
        sha_none = opened.upsert_judge_evaluation(judge_sha, generation_sha, None, None, None, None)
        assert sha_none == judge_evaluation_id(judge_sha, generation_sha, None)
        assert _row(path, "SELECT COUNT(*) FROM judge_evaluations") == (2,)
        assert _row(
            path,
            "SELECT reference_summary_sha256 IS NULL FROM judge_evaluations WHERE judge_evaluation_sha256 = ?",
            sha_none,
        ) == (1,)
    finally:
        opened.close()


def test_metric_evaluation_rows(tmp_path, monkeypatch):
    clock = _freeze_clock(monkeypatch)
    t1 = "2026-05-01T00:00:00Z"
    path = str(tmp_path / "store.db")
    opened = store.Store(path)
    try:
        _, _, _, generation_sha, reference_sha = _seed_chain(opened)
        sha = opened.upsert_metric_evaluation("rouge_l", generation_sha, reference_sha, 0.42)
        assert sha == metric_evaluation_id("rouge_l", generation_sha, reference_sha)
        assert _row(path, "SELECT value, updated_at FROM metric_evaluations") == (0.42, "2026-01-01T00:00:00Z")
        clock.value = t1
        # same (metric, generation) with no reference is a different row
        opened.upsert_metric_evaluation("rouge_l", generation_sha, None, 0.42)
        assert _row(path, "SELECT COUNT(*) FROM metric_evaluations") == (2,)
        opened.upsert_metric_evaluation("rouge_l", generation_sha, reference_sha, 0.42)
        assert _row(path, "SELECT COUNT(*) FROM metric_evaluations") == (2,)
        assert _row(
            path,
            "SELECT updated_at FROM metric_evaluations WHERE metric_evaluation_sha256 = ?",
            sha,
        ) == ("2026-01-01T00:00:00Z",)
    finally:
        opened.close()


def test_metric_evaluation_value_not_null(tmp_path):
    path = str(tmp_path / "store.db")
    opened = store.Store(path)
    try:
        _, _, _, generation_sha, reference_sha = _seed_chain(opened)
        with pytest.raises(RuntimeFailure):
            opened.upsert_metric_evaluation("rouge_l", generation_sha, reference_sha, None)
    finally:
        opened.close()


def test_clear_deletes_all_eight_tables(tmp_path):
    path = str(tmp_path / "store.db")
    opened = store.Store(path)
    try:
        _, _, _, generation_sha, reference_sha = _seed_chain(opened)
        judge_sha = opened.upsert_judge("pin", {}, "s", "t", False, "j", "https://e/v1", "K")
        opened.upsert_judge_evaluation(judge_sha, generation_sha, reference_sha, 1.0, 1.0, 1.0)
        opened.upsert_metric_evaluation("rouge_l", generation_sha, reference_sha, 0.5)
        assert [count for _, count in opened.table_counts()] == [1] * 8
        assert opened.clear() == 8
        assert [count for _, count in opened.table_counts()] == [0] * 8
    finally:
        opened.close()
