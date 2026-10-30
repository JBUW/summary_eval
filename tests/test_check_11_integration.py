"""Ticket 11 — check's live phase end-to-end through the real,
trivially cheap fixture model server (serve mode): the success line
sequence with exactly one counted completion (the preflight prompt
never reaches the completion log), the local fail-fast on a failing
probe completion (error line plus the raw server-log tail, no done
line), and the static-fail skip (exit 2, the server section never
launched, no live output).

Each server run gets its own port: a stopped server leaves TIME_WAIT
sockets on its port, and the port pre-scan probe must never see them.
"""
import json
import os
import pytest

import harness  # noqa: F401  (puts the repo root on sys.path)

from evalapp.check_live import PROBE_TRANSCRIPT

pytestmark = pytest.mark.sockets

FIXTURE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures",
    "fake_model_server.py",
)
PLAN_LINE = "plan(check): 2 datasets"
BUILD_NOTE = 'note: model server build: {"model": "model.bin", "status": "running"}'
PROBE_USER = "usr" + PROBE_TRANSCRIPT
ARGV = ["check"]


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


def _run(workspace):
    return harness.run_cli(ARGV, cwd=str(workspace))


def _user_contents(workspace):
    log = (workspace / "completions.log").read_text(encoding="utf-8")
    return [line.split(": ", 1)[1] for line in log.splitlines()]


def test_success_exit_0_and_one_probe_completion(tmp_path):
    workspace = _workspace(tmp_path, 18211)
    result = _run(workspace)
    result.assert_exit(0)
    assert result.lines == [
        *harness.STANDARD_DISCOVERY,
        PLAN_LINE,
        "note: no store at store.db",
        BUILD_NOTE,
        "done(check): 1 server cycle, 1 summarizer probe, 0 judge probes",
    ]
    assert _user_contents(workspace) == [PROBE_USER]


def test_failure_exit_1_error_and_raw_tail_no_done(tmp_path):
    workspace = _workspace(tmp_path, 18212, fail_after=0)
    result = _run(workspace)
    result.assert_exit(1)
    lines = result.lines
    assert lines[:10] == [
        *harness.STANDARD_DISCOVERY,
        PLAN_LINE,
        "note: no store at store.db",
        BUILD_NOTE,
        "error: summarizer 's': HTTP 500 from model server",
    ]
    assert lines[10].startswith("fake-model-server launched with: --serve")
    assert lines[11] == "fake-model-server: loading model"
    assert lines[12] == "env FAKE_VAR=(unset)"
    assert len(lines) == 13
    assert _user_contents(workspace) == [PROBE_USER]


def test_static_fail_exit_2_live_skipped(tmp_path):
    workspace = harness.standard_workspace(tmp_path)
    config_path = os.path.join(str(workspace), "config.json")
    harness.add_summarizer_section(config_path)
    harness.add_server_section(config_path, port=18213)
    os.remove(str(workspace / "named.jsonl"))
    result = _run(workspace)
    result.assert_exit(2)
    assert result.lines == [
        *harness.STANDARD_DISCOVERY,
        PLAN_LINE,
        "error: dataset 'named': file not found: named.jsonl",
    ]
    assert not (workspace / "completions.log").exists()
