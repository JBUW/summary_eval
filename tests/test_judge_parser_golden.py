"""Golden fixtures at the judge-response parsing seam (ticket 07).

These are golden *fixtures*: recorded raw judge responses paired with the
structured outcome the parser must produce. They are deliberately distinct
from the glossary's *golden set* (a curated, documented subset of a
dataset) — see the naming-discipline note in evalapp/judge_parser.py.
"""
import json
from pathlib import Path

import pytest

import harness  # noqa: F401  (puts the repo root on sys.path)
from evalapp.judge_parser import parse_judge_response

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "judge_parser_golden.json").read_text("utf-8")
)


@pytest.mark.parametrize("case", FIXTURES, ids=[case["id"] for case in FIXTURES])
def test_golden_fixture(case):
    result = parse_judge_response(case["raw"])
    assert result.rejected is case["expected"]["rejected"]
    assert result.values == case["expected"]["values"]
    assert result.warnings == tuple(case["expected"]["warnings"])
