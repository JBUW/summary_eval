"""Ticket 05d — end-to-end generate integration through a real,
trivially cheap fixture model server (serve mode): plan/done line
formats, the exit classes (0 success, 1 failure, 2 contract error),
the resulting store rows, and a resume after a mid-run failure with
no re-call on committed items.

Each server run gets its own port: a stopped server leaves TIME_WAIT
sockets on its port, and the port pre-scan probe must never see them.
"""
import json
import os
import socket

import harness  # noqa: F401  (puts the repo root on sys.path)

from evalapp.store import Store

FIXTURE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures",
    "fake_model_server.py",
)
PLAN_LINE = "plan(generate): 1 summarizer, 3 items, 1 server cycle"
BUILD_NOTE = 'note: model server build: {"model": "model.bin", "status": "running"}'
ARGV = ["generate", "--select", "named", "#0-2", "--summarizer", "s"]


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


def _counts(workspace):
    store = Store(str(workspace / "store.db"))
    try:
        return dict(store.table_counts())
    finally:
        store.close()


def test_success_exit_0_store_rows_and_completion_log(tmp_path):
    workspace = _workspace(tmp_path, 18090)
    result = _run(workspace)
    result.assert_exit(0)
    assert result.lines == [
        PLAN_LINE,
        BUILD_NOTE,
        "done(generate): 3 committed, 0 skipped, 0 failed",
    ]
    log = (workspace / "completions.log").read_text(encoding="utf-8").splitlines()
    assert log == [f"completion {n}: usrtranscript {n - 1}" for n in (1, 2, 3)]
    counts = _counts(workspace)
    assert counts["generations"] == 3
    assert counts["transcripts"] == 3
    assert counts["models"] == 1
    assert counts["prompt_templates"] == 1


def test_failure_exit_1_tail_and_resume_note(tmp_path):
    workspace = _workspace(tmp_path, 18091, fail_after=1)
    result = _run(workspace)
    result.assert_exit(1)
    lines = result.lines
    assert len(lines) == 7
    assert lines[0] == PLAN_LINE
    assert lines[1] == BUILD_NOTE
    assert (
        lines[2]
        == "error: item named#1 (summarizer 's'): HTTP 500 from model server"
    )
    assert lines[3].startswith("fake-model-server launched with: --serve")
    assert lines[4] == "fake-model-server: loading model"
    assert lines[5] == "env FAKE_VAR=(unset)"
    assert lines[6] == "note: re-run to resume; 1 item already committed"
    assert _user_contents(workspace) == ["usrtranscript 0", "usrtranscript 1"]
    assert _counts(workspace)["generations"] == 1


def test_resume_skips_committed_without_recall(tmp_path):
    workspace = _workspace(tmp_path, 18092, fail_after=1)
    _run(workspace).assert_exit(1)
    _server_section(workspace, 18093)
    result = _run(workspace)
    result.assert_exit(0)
    assert result.lines == [
        PLAN_LINE,
        BUILD_NOTE,
        "done(generate): 2 committed, 1 skipped, 0 failed",
    ]
    assert _user_contents(workspace) == [
        "usrtranscript 0",
        "usrtranscript 1",
        "usrtranscript 1",
        "usrtranscript 2",
    ]
    assert _counts(workspace)["generations"] == 3


def test_busy_port_exit_2_with_orphan_hint(tmp_path):
    workspace = _workspace(tmp_path, 18094)
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 18094))
        result = _run(workspace)
    finally:
        probe.close()
    result.assert_exit(2)
    assert result.lines == [
        PLAN_LINE,
        "error: port 18094 already bound "
        "(a previous model server may still be running)",
    ]
