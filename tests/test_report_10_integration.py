"""Ticket 10 — end-to-end report integration through the fixture server
(generate -> score, then the report variants): the default table is
read-only (store counts unchanged), --json shape, --by dataset shape,
--blind-sample, and the zero-rows note.

The report never starts a server itself; the server section exists only
so generate can run. Each server run gets its own port (a stopped server
leaves TIME_WAIT sockets, and the port pre-scan probe must never see
them).
"""
import json
import os
import pytest

import harness  # noqa: F401  (puts the repo root on sys.path)

from evalapp.store import Store

pytestmark = pytest.mark.sockets

FIXTURE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures",
    "fake_model_server.py",
)
GENERATE_ARGV = ["generate", "--select", "named", "#0-2", "--summarizer", "s"]
SCORE_ARGV = [
    "score", "--no-judges", "--metrics", "faithfulness",
    "--select", "named", "#0-2",
]
ZERO_ROWS = (
    "note: no scored results in scope; run 'score' (or 'score --generate') first"
)


def _server_section(workspace, port, fail_after=None):
    """Rewrite the config's server section: the fixture in serve mode."""
    path = os.path.join(str(workspace), "config.json")
    with open(path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    args = {
        "serve": True,
        "completion-log": str(workspace / "completions.log"),
    }
    if fail_after is not None:
        args["fail-after"] = fail_after
    config["server"] = {
        "command": FIXTURE,
        "args": args,
        "env": {},
        "port": port,
        "startup_timeout_s": 10,
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2)
        handle.write("\n")


def _workspace(tmp_path, port, fail_after=None):
    workspace = harness.standard_workspace(tmp_path)
    harness.add_summarizer_section(os.path.join(str(workspace), "config.json"))
    _server_section(workspace, port, fail_after)
    return workspace


def _counts(workspace):
    store = Store(str(workspace / "store.db"))
    try:
        return dict(store.table_counts())
    finally:
        store.close()


def _generate_and_score(workspace):
    result = harness.run_cli(GENERATE_ARGV, cwd=str(workspace))
    result.assert_exit(0)
    result = harness.run_cli(SCORE_ARGV, cwd=str(workspace))
    result.assert_exit(0)


def test_report_table_read_only(tmp_path):
    workspace = _workspace(tmp_path, 18200)
    _generate_and_score(workspace)
    before = _counts(workspace)
    result = harness.run_cli(
        ["report", "--select", "named", "#0-2"], cwd=str(workspace)
    )
    result.assert_exit(0)
    lines = result.lines
    assert lines[0] == "plan(report): named 3 entries"
    assert lines[1] == "candidate,scorer,n,mean,min,max"
    data = lines[2:]
    assert len(data) == len(harness.ALL_METRICS)
    faithfulness = [line for line in data
                    if line.startswith("s,faithfulness,")]
    assert len(faithfulness) == 1
    assert faithfulness[0].split(",")[:3] == ["s", "faithfulness", "3"]
    for line in data:
        for field in line.split(",")[3:]:
            if field != "-":
                float(field)
    assert _counts(workspace) == before


def test_report_json(tmp_path):
    workspace = _workspace(tmp_path, 18201)
    _generate_and_score(workspace)
    result = harness.run_cli(
        ["report", "--json", "--select", "named", "#0-2"], cwd=str(workspace)
    )
    result.assert_exit(0)
    lines = result.lines
    assert lines[0] == "plan(report): named 3 entries"
    rows = json.loads("\n".join(lines[1:]))
    assert list(rows[0]) == ["candidate", "scorer", "n", "mean", "min", "max"]
    faithfulness = [row for row in rows if row["scorer"] == "faithfulness"]
    assert len(faithfulness) == 1
    assert faithfulness[0]["candidate"] == "s"
    assert faithfulness[0]["n"] == 3


def test_report_by_dataset(tmp_path):
    workspace = _workspace(tmp_path, 18202)
    _generate_and_score(workspace)
    result = harness.run_cli(
        ["report", "--by", "dataset", "--select", "named", "#0-2"],
        cwd=str(workspace),
    )
    result.assert_exit(0)
    lines = result.lines
    assert lines[0] == "plan(report): named 3 entries"
    assert lines[1] == "candidate,dataset,scorer,n,mean,min,max"
    data = lines[2:]
    named_rows = [line for line in data
                  if line.startswith("s,named,faithfulness,")]
    assert len(named_rows) == 1
    assert named_rows[0].startswith("s,named,faithfulness,3,")
    assert "s,unnamed,faithfulness,0,-,-,-" in data


def test_report_blind_sample(tmp_path):
    workspace = _workspace(tmp_path, 18203)
    _generate_and_score(workspace)
    result = harness.run_cli(
        ["report", "--select", "named", "#0-2", "--blind-sample", "2"],
        cwd=str(workspace),
    )
    result.assert_exit(0)
    lines = result.lines
    assert lines[0] == "plan(report): named 2 entries"
    assert lines[1] == "candidate,scorer,n,mean,min,max"
    faithfulness = [line for line in lines[2:]
                    if line.startswith("s,faithfulness,")]
    assert len(faithfulness) == 1
    assert faithfulness[0].startswith("s,faithfulness,2,")


def test_report_zero_rows(tmp_path):
    workspace = _workspace(tmp_path, 18204)
    result = harness.run_cli(
        ["report", "--select", "unnamed", "*"], cwd=str(workspace)
    )
    result.assert_exit(0)
    assert result.lines == [
        "plan(report): unnamed 12 entries",
        ZERO_ROWS,
    ]
