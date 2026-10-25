"""Parser constants and parse policy at the judge-response seam (ticket 07)."""
import dataclasses
import json
import sqlite3
from pathlib import Path

import pytest

import harness  # noqa: F401  (puts the repo root on sys.path)
import evalapp.judge_parser as judge_parser
from evalapp import store
from evalapp.judge_parser import (
    ACCEPT_PARTIAL_RESULTS,
    QUALITIES,
    QUALITY_SCALE,
    parse_judge_response,
)

_FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "judge_parser_golden.json").read_text("utf-8")
)


def _raw(case_id):
    return next(case["raw"] for case in _FIXTURES if case["id"] == case_id)


def test_partial_acceptance_is_off_by_default():
    assert ACCEPT_PARTIAL_RESULTS is False


def test_qualities_are_the_judge_evaluation_columns(tmp_path):
    store.Store(tmp_path / "store.db")
    db = sqlite3.connect(tmp_path / "store.db")
    try:
        columns = tuple(
            row[1]
            for row in db.execute("PRAGMA table_info(judge_evaluations)")
            if row[2] == "REAL"
        )
    finally:
        db.close()
    assert QUALITIES == columns


def test_scale_is_zero_to_one():
    assert QUALITY_SCALE == (0.0, 1.0)


def test_result_is_a_frozen_dataclass():
    result = parse_judge_response(_raw("clean"))
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.rejected = True


def _accepting(monkeypatch):
    monkeypatch.setattr(judge_parser, "ACCEPT_PARTIAL_RESULTS", True)


def test_partial_missing_is_accepted_when_constant_on(monkeypatch):
    _accepting(monkeypatch)
    result = parse_judge_response(_raw("partial_missing_quality"))
    assert result.rejected is False
    assert result.values == {"factual_correctness": 0.9, "completeness": 0.8}
    assert result.warnings == (
        "quality 'conciseness' missing from judge response",
    )


def test_conflict_keeps_clean_qualities_when_constant_on(monkeypatch):
    _accepting(monkeypatch)
    result = parse_judge_response(_raw("conflicting_duplicates"))
    assert result.rejected is False
    assert result.values == {"completeness": 0.8, "conciseness": 0.7}
    assert result.warnings == (
        "quality 'factual_correctness' conflicting values in judge response: 0.9, 0.6",
    )


def test_out_of_scale_keeps_clean_qualities_when_constant_on(monkeypatch):
    _accepting(monkeypatch)
    result = parse_judge_response(_raw("out_of_scale"))
    assert result.rejected is False
    assert result.values == {"completeness": 0.8, "conciseness": 0.7}
    assert result.warnings == (
        "quality 'factual_correctness' out of range in judge response: "
        "1.7 (scale 0.0-1.0)",
    )


def test_garbage_is_accepted_empty_when_constant_on(monkeypatch):
    _accepting(monkeypatch)
    result = parse_judge_response("no qualities here at all")
    assert result.rejected is False
    assert result.values == {}
    assert result.warnings == (
        "quality 'factual_correctness' missing from judge response",
        "quality 'completeness' missing from judge response",
        "quality 'conciseness' missing from judge response",
    )


def test_clean_parse_unchanged_when_constant_on(monkeypatch):
    _accepting(monkeypatch)
    result = parse_judge_response(_raw("clean"))
    assert result.rejected is False
    assert result.values == {
        "factual_correctness": 0.9,
        "completeness": 0.8,
        "conciseness": 0.75,
    }
    assert result.warnings == ()


def test_negative_value_is_out_of_range():
    result = parse_judge_response(
        "factual_correctness: 0.9\ncompleteness: -0.2\nconciseness: 0.7"
    )
    assert result.rejected is True
    assert result.values == {}
    assert result.warnings == (
        "quality 'completeness' out of range in judge response: "
        "-0.2 (scale 0.0-1.0)",
    )


def test_integer_and_decimal_forms_are_identical_duplicates():
    result = parse_judge_response(
        "factual_correctness: 1\ncompleteness: 0.8\nconciseness: 0.7\n"
        "To reiterate: factual_correctness: 1.0"
    )
    assert result.rejected is False
    assert result.values == {
        "factual_correctness": 1.0,
        "completeness": 0.8,
        "conciseness": 0.7,
    }
    assert result.warnings == ()


def test_separator_and_case_variants_of_labels_are_accepted():
    result = parse_judge_response(
        "Factual-Correctness: 0.9\nCompleteness: 0.8\nConciseness: 0.7"
    )
    assert result.rejected is False
    assert result.values == {
        "factual_correctness": 0.9,
        "completeness": 0.8,
        "conciseness": 0.7,
    }
    assert result.warnings == ()


def test_unknown_labels_are_ignored():
    result = parse_judge_response(
        "fluency: 0.9\nbias: 0.1\n"
        "factual_correctness: 0.5\ncompleteness: 0.6\nconciseness: 0.7"
    )
    assert result.rejected is False
    assert result.values == {
        "factual_correctness": 0.5,
        "completeness": 0.6,
        "conciseness": 0.7,
    }
    assert result.warnings == ()


def test_extended_label_does_not_match():
    result = parse_judge_response(
        "factual_correctness: 0.9\ncompleteness_score: 0.8\nconciseness: 0.7"
    )
    assert result.rejected is True
    assert result.values == {}
    assert result.warnings == (
        "quality 'completeness' missing from judge response",
    )
