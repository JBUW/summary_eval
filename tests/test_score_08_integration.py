"""Ticket 08 — end-to-end score integration through a real, trivially
cheap fixture model server: the score-level smoke (metrics phase with
infeasible reference pairs), the --generate two-stage invocation, and
the judges phase against the fixture as a bare endpoint (parse-reject
warns and a simulated HTTP failure), including a resume that retries
only the failed judge units.

Judges are bare endpoints with no lifecycle, so the test starts the
fixture itself; each server run gets its own port (a stopped server
leaves TIME_WAIT sockets, and the port pre-scan probe must never see
them).
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
GEN_PLAN = "plan(generate): 1 summarizer, 3 items, 1 server cycle"
BUILD_NOTE = 'note: model server build: {"model": "model.bin", "status": "running"}'
GEN_DONE = "done(generate): 3 committed, 0 skipped, 0 failed"
GENERATE_ARGV = ["generate", "--select", "named", "#0-2", "--summarizer", "s"]


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


def _repoint_judge(workspace, port):
    """Point judge 'j' at a different port (a dead endpoint left in the
    config is a connection failure, not a resume)."""
    path = os.path.join(str(workspace), "config.json")
    with open(path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    config["judges"]["j"]["endpoint"] = "http://127.0.0.1:%d" % port
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


def test_score_smoke_metrics_phase(tmp_path):
    workspace = _workspace(tmp_path, 18102)
    result = harness.run_cli(GENERATE_ARGV, cwd=str(workspace))
    result.assert_exit(0)
    assert result.lines == [GEN_PLAN, BUILD_NOTE, GEN_DONE]
    result = harness.run_cli(
        ["score", "--no-judges", "--select", "named", "#0-2"],
        cwd=str(workspace),
    )
    result.assert_exit(0)
    assert result.lines == [
        "warn: metric 'key_claim_completeness' requires reference "
        "summaries; dataset 'named' has none (pair skipped)",
        "warn: metric 'key_claim_completeness' requires reference "
        "summaries; dataset 'unnamed' has none (pair skipped)",
        "plan(score): 5 metrics, 0 judges | 3 items | 12 to run, "
        "0 already scored | 2 infeasible",
        "done(score): 9 committed, 0 dropped, 0 failed",
    ]
    counts = _counts(workspace)
    assert counts["generations"] == 3
    assert counts["metric_evaluations"] == 9
    assert counts["judge_evaluations"] == 0
    assert counts["reference_summaries"] == 0


def test_score_generate_two_stage(tmp_path):
    workspace = _workspace(tmp_path, 18103)
    result = harness.run_cli(
        ["score", "--generate", "--no-judges", "--metrics", "faithfulness",
         "--select", "named", "#0-2", "--summarizer", "s"],
        cwd=str(workspace),
    )
    result.assert_exit(0)
    assert result.lines == [
        GEN_PLAN,
        "plan(score): 1 metric, 0 judges | 3 items | 3 to run, "
        "0 already scored | 0 infeasible",
        BUILD_NOTE,
        GEN_DONE,
        "done(score): 3 committed, 0 dropped, 0 failed",
    ]
    counts = _counts(workspace)
    assert counts["generations"] == 3
    assert counts["metric_evaluations"] == 3


def test_judge_parse_reject_warns_and_continues(tmp_path, monkeypatch):
    monkeypatch.setenv("EVALAPP_TEST_JUDGE_KEY", "test-key")
    workspace = _workspace(tmp_path, 18105)
    _judge_section(workspace, 18106)
    harness.run_cli(
        ["generate", "--select", "named", "#0-1", "--summarizer", "s"],
        cwd=str(workspace),
    ).assert_exit(0)
    log = workspace / "judge.log"
    judge = _JudgeServer(18106, log)
    try:
        result = harness.run_cli(
            ["score", "--metrics", "faithfulness", "--judges", "j",
             "--select", "named", "#0-1"],
            cwd=str(workspace),
        )
    finally:
        judge.stop()
    result.assert_exit(0)
    assert result.lines == [
        "plan(score): 1 metric, 1 judge | 2 items | 4 to run, "
        "0 already scored | 0 infeasible",
        "warn: judge 'j' returned no extractable qualities for entry #0 "
        "in dataset 'named' (unit not committed)",
        "warn: judge 'j' returned no extractable qualities for entry #1 "
        "in dataset 'named' (unit not committed)",
        "done(score): 2 committed, 0 dropped, 2 failed",
    ]
    assert log.read_text(encoding="utf-8").splitlines() == [
        "completion 1: Judge transcript 0 against fake: usrtranscript 0",
        "completion 2: Judge transcript 1 against fake: usrtranscript 1",
    ]
    counts = _counts(workspace)
    assert counts["generations"] == 2
    assert counts["metric_evaluations"] == 2
    assert counts["judge_evaluations"] == 0


def test_judge_http_failure_exit_1(tmp_path, monkeypatch):
    monkeypatch.setenv("EVALAPP_TEST_JUDGE_KEY", "test-key")
    workspace = _workspace(tmp_path, 18107)
    _judge_section(workspace, 18108)
    harness.run_cli(
        ["generate", "--select", "named", "#0-1", "--summarizer", "s"],
        cwd=str(workspace),
    ).assert_exit(0)
    log = workspace / "judge.log"
    judge = _JudgeServer(18108, log, fail_after=0)
    try:
        result = harness.run_cli(
            ["score", "--no-metrics", "--judges", "j", "--select", "named",
             "#0-1"],
            cwd=str(workspace),
        )
    finally:
        judge.stop()
    result.assert_exit(1)
    assert result.lines == [
        "plan(score): 0 metrics, 1 judge | 2 items | 2 to run, "
        "0 already scored | 0 infeasible",
        "error: judge 'j' failed for entry #0 in dataset 'named': HTTP 500",
    ]
    assert log.read_text(encoding="utf-8").splitlines() == [
        "completion 1: Judge transcript 0 against fake: usrtranscript 0",
    ]


def test_judge_resume_retries_only_failed_units(tmp_path, monkeypatch):
    monkeypatch.setenv("EVALAPP_TEST_JUDGE_KEY", "test-key")
    workspace = _workspace(tmp_path, 18109)
    _judge_section(workspace, 18110)
    harness.run_cli(GENERATE_ARGV, cwd=str(workspace)).assert_exit(0)
    score_argv = [
        "score", "--metrics", "faithfulness", "--judges", "j",
        "--select", "named", "#0-2",
    ]
    judge_a = _JudgeServer(18110, workspace / "judge_a.log")
    try:
        result = harness.run_cli(score_argv, cwd=str(workspace))
    finally:
        judge_a.stop()
    result.assert_exit(0)
    assert result.lines == [
        "plan(score): 1 metric, 1 judge | 3 items | 6 to run, "
        "0 already scored | 0 infeasible",
        "warn: judge 'j' returned no extractable qualities for entry #0 "
        "in dataset 'named' (unit not committed)",
        "warn: judge 'j' returned no extractable qualities for entry #1 "
        "in dataset 'named' (unit not committed)",
        "warn: judge 'j' returned no extractable qualities for entry #2 "
        "in dataset 'named' (unit not committed)",
        "done(score): 3 committed, 0 dropped, 3 failed",
    ]
    assert (workspace / "judge_a.log").read_text(encoding="utf-8").splitlines() == [
        "completion 1: Judge transcript 0 against fake: usrtranscript 0",
        "completion 2: Judge transcript 1 against fake: usrtranscript 1",
        "completion 3: Judge transcript 2 against fake: usrtranscript 2",
    ]
    _repoint_judge(workspace, 18111)
    judge_b = _JudgeServer(18111, workspace / "judge_b.log")
    try:
        result = harness.run_cli(score_argv, cwd=str(workspace))
    finally:
        judge_b.stop()
    result.assert_exit(0)
    assert result.lines == [
        "plan(score): 1 metric, 1 judge | 3 items | 3 to run, "
        "3 already scored | 0 infeasible",
        "warn: judge 'j' returned no extractable qualities for entry #0 "
        "in dataset 'named' (unit not committed)",
        "warn: judge 'j' returned no extractable qualities for entry #1 "
        "in dataset 'named' (unit not committed)",
        "warn: judge 'j' returned no extractable qualities for entry #2 "
        "in dataset 'named' (unit not committed)",
        "done(score): 0 committed, 0 dropped, 3 failed",
    ]
    assert (workspace / "judge_b.log").read_text(encoding="utf-8").splitlines() == [
        "completion 1: Judge transcript 0 against fake: usrtranscript 0",
        "completion 2: Judge transcript 1 against fake: usrtranscript 1",
        "completion 3: Judge transcript 2 against fake: usrtranscript 2",
    ]
    counts = _counts(workspace)
    assert counts["generations"] == 3
    assert counts["metric_evaluations"] == 3
    assert counts["judge_evaluations"] == 0
