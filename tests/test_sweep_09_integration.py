"""Ticket 09 — end-to-end sweep integration through a real, trivially
cheap fixture model server: the full 24-item smoke (implied generation,
all five registered metrics, unique transcript texts so every item keeps
its own generation), a re-sweep that commits nothing and never spawns a
server, and the judges phase against the fixture as a bare endpoint
(parse-reject warns, exit 0).

The fixture is used two ways: the config's server section (sweep's
implied generation spawns it) and, for the judge, the test starts it
itself (a judge is a bare endpoint with no lifecycle). Each server run
gets its own port (a stopped server leaves TIME_WAIT sockets, and the
port pre-scan probe must never see them).
"""
import json
import os
import socket
import subprocess
import sys
import time

import harness  # noqa: F401  (puts the repo root on sys.path)

from evalapp.store import Store

FIXTURE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures",
    "fake_model_server.py",
)
BUILD_NOTE = 'note: model server build: {"model": "model.bin", "status": "running"}'
KEY_CLAIM = ("warn: metric 'key_claim_completeness' requires reference "
             "summaries; dataset '%s' has none (pair skipped)")


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


def _judge_section(workspace, port):
    """Add a judge 'j': the fixture as a bare endpoint (no /v1, no
    lifecycle), with the dummy credential variable the preflight names."""
    path = os.path.join(str(workspace), "config.json")
    with open(path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    config["judges"] = {
        "j": {
            "endpoint": "http://127.0.0.1:%d" % port,
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


def _unique_text_workspace(tmp_path, port):
    """standard_workspace with each entry's text made unique per
    dataset: the stock texts collide across datasets, and content-
    addressed identities would merge named[i] with unnamed[i]."""
    workspace = harness.standard_workspace(tmp_path)
    for name in ("named", "unnamed"):
        path = os.path.join(str(workspace), name + ".jsonl")
        with open(path, "r", encoding="utf-8") as handle:
            entries = [json.loads(line) for line in handle if line]
        for index, entry in enumerate(entries):
            entry["text"] = "%s transcript %d" % (name, index)
        harness.write_jsonl(path, entries)
    harness.add_summarizer_section(os.path.join(str(workspace), "config.json"))
    _server_section(workspace, port)
    return workspace


def _counts(workspace):
    store = Store(str(workspace / "store.db"))
    try:
        return dict(store.table_counts())
    finally:
        store.close()


class _JudgeServer:
    """The fixture in serve mode, started by the test (a judge has no
    lifecycle of its own)."""

    def __init__(self, port, log_path, fail_after=None):
        args = [
            sys.executable, FIXTURE, "--serve", "--port", str(port),
            "--model", "pin", "--completion-log", str(log_path),
        ]
        if fail_after is not None:
            args += ["--fail-after", str(fail_after)]
        self._proc = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        self._wait_ready(port)

    def _wait_ready(self, port):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                raise AssertionError("fixture server exited before ready")
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2)
                return
            except OSError:
                time.sleep(0.05)
        raise AssertionError("fixture server did not become ready")

    def stop(self):
        if self._proc.poll() is None:
            self._proc.terminate()
            self._proc.wait(timeout=5)


def test_sweep_smoke_and_resweep_no_spawn(tmp_path):
    workspace = _unique_text_workspace(tmp_path, 18112)
    result = harness.run_cli(["sweep"], cwd=str(workspace))
    result.assert_exit(0)
    assert result.lines == [
        KEY_CLAIM % "named",
        KEY_CLAIM % "unnamed",
        "plan(generate): 1 summarizer, 24 items, 1 server cycle",
        "plan(score): 5 metrics, 0 judges | 24 items | 96 to run, "
        "0 already scored | 2 infeasible",
        BUILD_NOTE,
        "done(generate): 24 committed, 0 skipped, 0 failed",
        "done(score): 72 committed, 0 dropped, 0 failed",
    ]
    counts = _counts(workspace)
    assert counts["transcripts"] == 24
    assert counts["generations"] == 24
    assert counts["metric_evaluations"] == 72
    assert counts["judge_evaluations"] == 0

    result = harness.run_cli(["sweep"], cwd=str(workspace))
    result.assert_exit(0)
    assert result.lines == [
        KEY_CLAIM % "named",
        KEY_CLAIM % "unnamed",
        "plan(generate): 1 summarizer, 24 items, 1 server cycle",
        "plan(score): 5 metrics, 0 judges | 24 items | 24 to run, "
        "72 already scored | 2 infeasible",
        "note: all 24 items already committed; server not started",
        "done(generate): 0 committed, 24 skipped, 0 failed",
        "done(score): 0 committed, 0 dropped, 0 failed",
    ]
    counts = _counts(workspace)
    assert counts["generations"] == 24
    assert counts["metric_evaluations"] == 72


def test_sweep_judge_parse_reject_warns_exit_0(tmp_path, monkeypatch):
    monkeypatch.setenv("EVALAPP_TEST_JUDGE_KEY", "test-key")
    workspace = _unique_text_workspace(tmp_path, 18113)
    _judge_section(workspace, 18114)
    log = workspace / "judge.log"
    judge = _JudgeServer(18114, log)
    try:
        result = harness.run_cli(["sweep"], cwd=str(workspace))
    finally:
        judge.stop()
    result.assert_exit(0)
    expected = [
        KEY_CLAIM % "named",
        KEY_CLAIM % "unnamed",
        "plan(generate): 1 summarizer, 24 items, 1 server cycle",
        "plan(score): 5 metrics, 1 judge | 24 items | 120 to run, "
        "0 already scored | 2 infeasible",
        BUILD_NOTE,
        "done(generate): 24 committed, 0 skipped, 0 failed",
    ]
    for name in ("named", "unnamed"):
        for index in range(12):
            expected.append(
                "warn: judge 'j' returned no extractable qualities for "
                "entry #%d in dataset '%s' (unit not committed)"
                % (index, name)
            )
    expected.append("done(score): 72 committed, 0 dropped, 24 failed")
    assert result.lines == expected
    log_lines = log.read_text(encoding="utf-8").splitlines()
    assert len(log_lines) == 24
    assert log_lines[0] == (
        "completion 1: Judge named transcript 0 against "
        "fake: usrnamed transcript 0"
    )
    assert log_lines[11] == (
        "completion 12: Judge named transcript 11 against "
        "fake: usrnamed transcript 11"
    )
    assert log_lines[12] == (
        "completion 13: Judge unnamed transcript 0 against "
        "fake: usrunnamed transcript 0"
    )
    assert log_lines[23] == (
        "completion 24: Judge unnamed transcript 11 against "
        "fake: usrunnamed transcript 11"
    )
    counts = _counts(workspace)
    assert counts["generations"] == 24
    assert counts["metric_evaluations"] == 72
    assert counts["judge_evaluations"] == 0
