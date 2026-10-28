"""Ticket 05b: model server lifecycle (pre-spawn validation, spawn, readiness,
preflight, stop, cycle switching)."""
import json
import os
import time

import pytest

import harness
from evalapp import model_server
from evalapp.cli import main
from evalapp.endpoint_client import EndpointError, HttpError
from evalapp.errors import RuntimeFailure, SpecError

FIXTURE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "fake_model_server.py"
)


class FakeClient:
    """Records calls; mirrors EndpointClient.props/complete signatures."""

    def __init__(self, props_result=None, complete_result="ok", complete_error=None):
        if props_result is None:
            props_result = {"backend": "unit", "version": "fake"}
        self.props_result = props_result
        self.complete_result = complete_result
        self.complete_error = complete_error
        self.props_calls = []
        self.complete_calls = []

    def props(self, server_root, timeout=None):
        self.props_calls.append((server_root, timeout))
        if isinstance(self.props_result, Exception):
            raise self.props_result
        return self.props_result

    def complete(self, endpoint, model_name, messages, gen_params=None,
                 api_key_env=None, timeout=None):
        self.complete_calls.append(
            (endpoint, model_name, list(messages), gen_params, api_key_env, timeout)
        )
        if self.complete_error is not None:
            raise self.complete_error
        return self.complete_result


class RecordingConsole:
    def __init__(self):
        self.calls = []

    def note(self, message):
        self.calls.append(("note", message))

    def plan(self, command, message):
        self.calls.append(("plan", command, message))

    def warn(self, message):
        self.calls.append(("warn", message))

    def error(self, message):
        self.calls.append(("error", message))

    def done(self, command, message):
        self.calls.append(("done", command, message))


def make_spec(**overrides):
    spec = {
        "command": FIXTURE,
        "args": {},
        "env": {},
        "port": 18081,
        "startup_timeout_s": 10,
    }
    spec.update(overrides)
    return spec


def wait_for_log_line(server, needle, timeout=5.0):
    """Wait until the child printed ``needle``.

    The fake client reports readiness before the child's interpreter has
    started, so a freshly ensured server's log is not complete yet.
    """
    deadline = time.monotonic() + timeout
    while not any(needle in line for line in server.log_tail(50)):
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"log never contained {needle!r}: {server.log_tail(50)}"
            )
        time.sleep(0.05)


def summarizer_entry(model, model_args, template="p"):
    return {
        "model": model,
        "model_args": model_args,
        "prompt_template": template,
        "gen_params": {},
    }


def write_model_file(tmp_path, name="model.bin"):
    return harness.write_text(str(tmp_path / name), "fake model bytes")


def set_config_server_section(workspace, command, port=8081):
    config_path = str(workspace / "config.json")
    with open(config_path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    config["server"] = {
        "command": command,
        "args": {},
        "env": {},
        "port": port,
        "startup_timeout_s": 10,
    }
    harness.write_text(config_path, json.dumps(config, indent=2) + "\n")
    return config_path


def raise_busy_port(port):
    raise SpecError(
        f"port {port} already bound "
        "(a previous model server may still be running)"
    )


# --- shared map rendering -------------------------------------------------


def test_render_launch_args_forms_and_order():
    assert model_server.render_launch_args({}) == []
    rendered = model_server.render_launch_args(
        {"flag": True, "count": 3, "rate": 0.5, "name": "x", "off": False, "nil": None}
    )
    assert rendered == ["--flag", "--count", "3", "--rate", "0.5", "--name", "x"]


def test_build_launch_line_exact():
    line = model_server.build_launch_line(
        "/bin/server",
        {"ctx": 4096, "flash-attn": True},
        {"temp": 0.7, "n": 1},
        8081,
        "/models/m.bin",
    )
    assert line == [
        "/bin/server",
        "--ctx", "4096",
        "--flash-attn",
        "--temp", "0.7",
        "--n", "1",
        "--port", "8081",
        "--model", "/models/m.bin",
    ]


# --- effective server spec ------------------------------------------------


def test_effective_server_spec_absent_section_even_with_command_flag():
    for kwargs in ({}, {"command": "/bin/whatever"}):
        with pytest.raises(SpecError) as excinfo:
            model_server.effective_server_spec({}, **kwargs)
        assert str(excinfo.value) == "no server section in config (no fallback launch)"


def test_effective_server_spec_config_only_with_map_defaults():
    config = {
        "server": {
            "command": "/bin/server",
            "args": {"a": 1},
            "port": 9090,
            "startup_timeout_s": 42,
        }
    }
    assert model_server.effective_server_spec(config) == {
        "command": "/bin/server",
        "args": {"a": 1},
        "env": {},
        "port": 9090,
        "startup_timeout_s": 42,
    }


def test_effective_server_spec_flags_beat_config_whole_replacement():
    config = {
        "server": {
            "command": "/bin/server",
            "args": {"a": 1},
            "env": {"E": "v"},
            "port": 9090,
            "startup_timeout_s": 42,
        }
    }
    spec = model_server.effective_server_spec(
        config,
        command="/bin/other",
        args_map={"b": True},
        env_map={},
        port=7070,
        startup_timeout_s=5.0,
    )
    assert spec == {
        "command": "/bin/other",
        "args": {"b": True},
        "env": {},
        "port": 7070,
        "startup_timeout_s": 5.0,
    }


# --- distinct (model, model_args) pairs -----------------------------------


def test_distinct_model_pairs_dedup_and_configuration_order():
    resolved = {
        "summarizers": {
            "a": summarizer_entry("m1", {"t": 0.5}),
            "b": summarizer_entry("m2", {"x": 2, "y": 1}),
            "c": summarizer_entry("m1", {"t": 0.5}, template="q"),
            "d": summarizer_entry("m1", {"t": 0.9}),
            "e": summarizer_entry("m2", {"y": 1, "x": 2}),
        }
    }
    assert model_server.distinct_model_pairs(resolved) == [
        ("m1", {"t": 0.5}),
        ("m2", {"x": 2, "y": 1}),
        ("m1", {"t": 0.9}),
    ]


# --- pre-spawn validation -------------------------------------------------


def test_prevalidate_launch_missing_command():
    spec = make_spec(command="/nonexistent/nope")
    with pytest.raises(SpecError) as excinfo:
        model_server.prevalidate_launch(spec, [("m", {})], {"m": {"path": FIXTURE}})
    assert str(excinfo.value) == "server: command not found: /nonexistent/nope"


def test_prevalidate_launch_missing_model_file():
    spec = make_spec()
    with pytest.raises(SpecError) as excinfo:
        model_server.prevalidate_launch(
            spec, [("m", {})], {"m": {"path": "/nonexistent/model.bin"}}
        )
    assert str(excinfo.value) == "model 'm': file not found: /nonexistent/model.bin"


def test_prevalidate_launch_busy_port(monkeypatch):
    spec = make_spec()
    monkeypatch.setattr(model_server, "port_is_free", raise_busy_port)
    with pytest.raises(SpecError) as excinfo:
        model_server.prevalidate_launch(spec, [("m", {})], {"m": {"path": FIXTURE}})
    assert str(excinfo.value) == (
        "port 18081 already bound "
        "(a previous model server may still be running)"
    )


# --- lifecycle: real processes --------------------------------------------


def test_spawn_readiness_preflight_stop(tmp_path):
    model_file = write_model_file(tmp_path)
    spec = make_spec(env={"FAKE_VAR": "42"})
    client = FakeClient()
    console = RecordingConsole()
    cycles = model_server.ServerCycles(spec, {"m": model_file}, client, console)
    try:
        server = cycles.ensure("m", {})
        wait_for_log_line(server, "fake-model-server launched with:")
        assert server.alive()
        assert server.root == "http://127.0.0.1:18081"
        assert (
            "note",
            'model server build: {"backend": "unit", "version": "fake"}',
        ) in console.calls
        assert client.props_calls
        assert all(root == "http://127.0.0.1:18081" for root, _ in client.props_calls)
        assert all(
            timeout == model_server.READY_POLL_TIMEOUT_S
            for _, timeout in client.props_calls
        )
        assert len(client.complete_calls) == 1
        endpoint, model_name, messages, *_ = client.complete_calls[0]
        assert endpoint == "http://127.0.0.1:18081"
        assert model_name == "m"
        assert messages == model_server.PREFLIGHT_MESSAGES
        cycles.stop()
        tail = server.log_tail(20)
        assert any("fake-model-server launched with: --port 18081 --model " in line
                   for line in tail)
        assert "env FAKE_VAR=42" in tail
        assert server.exit_code() is not None
    finally:
        cycles.stop()


def test_readiness_timeout_stops_and_keeps_log(tmp_path):
    model_file = write_model_file(tmp_path)
    spec = make_spec(startup_timeout_s=0.3)
    client = FakeClient(props_result=EndpointError("connection failed: refused"))
    cycles = model_server.ServerCycles(spec, {"m": model_file}, client)
    try:
        with pytest.raises(RuntimeFailure) as excinfo:
            cycles.ensure("m", {})
        assert str(excinfo.value) == "model server not ready after 0.3s"
        wait_for_log_line(cycles.last_server, "fake-model-server launched with:")
        assert "fake-model-server launched with:" in " ".join(cycles.log_tail(20))
    finally:
        cycles.stop()
    assert cycles.last_server is not None
    assert cycles.last_server.exit_code() is not None


def test_server_death_during_startup(tmp_path):
    model_file = write_model_file(tmp_path)
    spec = make_spec(args={"die": 3})
    client = FakeClient(props_result=EndpointError("connection failed: refused"))
    cycles = model_server.ServerCycles(spec, {"m": model_file}, client)
    try:
        with pytest.raises(RuntimeFailure) as excinfo:
            cycles.ensure("m", {})
        assert str(excinfo.value) == "model server exited during startup (exit code 3)"
        assert "--die 3" in " ".join(cycles.log_tail(20))
        assert cycles.last_server.exit_code() == 3
    finally:
        cycles.stop()


def test_preflight_failure(tmp_path):
    model_file = write_model_file(tmp_path)
    spec = make_spec()
    client = FakeClient(complete_error=HttpError(500, "boom"))
    cycles = model_server.ServerCycles(spec, {"m": model_file}, client)
    try:
        with pytest.raises(RuntimeFailure) as excinfo:
            cycles.ensure("m", {})
        assert str(excinfo.value) == "model server preflight failed: HTTP 500"
        wait_for_log_line(cycles.last_server, "fake-model-server launched with:")
        assert "fake-model-server launched with:" in " ".join(cycles.log_tail(20))
    finally:
        cycles.stop()


def test_cycle_switching_and_reuse(tmp_path):
    model_one = write_model_file(tmp_path, "m1.bin")
    model_two = write_model_file(tmp_path, "m2.bin")
    spec = make_spec()
    client = FakeClient()
    cycles = model_server.ServerCycles(
        spec, {"m1": model_one, "m2": model_two}, client
    )
    try:
        server_one = cycles.ensure("m1", {})
        server_two = cycles.ensure("m2", {})
        assert not server_one.alive()
        assert server_two.alive()
        assert server_two.root == server_one.root
        props_calls_before = len(client.props_calls)
        assert cycles.ensure("m2", {}) is server_two
        assert len(client.props_calls) == props_calls_before
        server_three = cycles.ensure("m2", {"t": 0.9})
        assert server_three is not server_two
        assert not server_two.alive()
        assert server_three.alive()
    finally:
        cycles.stop()


def test_ensure_busy_port_refuses_without_spawn(tmp_path, monkeypatch):
    model_file = write_model_file(tmp_path)
    spec = make_spec()
    monkeypatch.setattr(model_server, "port_is_free", raise_busy_port)
    client = FakeClient()
    cycles = model_server.ServerCycles(spec, {"m": model_file}, client)
    with pytest.raises(SpecError) as excinfo:
        cycles.ensure("m", {})
    assert str(excinfo.value) == (
        "port 18081 already bound "
        "(a previous model server may still be running)"
    )
    assert cycles.log_tail() == []
    assert cycles.last_server is None
    assert client.props_calls == []
    assert client.complete_calls == []


def test_stop_escalates_to_sigkill_after_grace(tmp_path, monkeypatch):
    model_file = write_model_file(tmp_path)
    spec = make_spec(args={"trap-term": True})
    client = FakeClient()
    cycles = model_server.ServerCycles(spec, {"m": model_file}, client)
    try:
        server = cycles.ensure("m", {})
        wait_for_log_line(server, "fake-model-server launched with: --trap-term")
        monkeypatch.setattr(model_server, "STOP_GRACE_S", 0.2)
        server.stop()
        assert not server.alive()
        assert server.exit_code() == -9
        assert "--trap-term" in " ".join(server.log_tail(20))
    finally:
        cycles.stop()


# --- CLI wiring (generate preflight, no spawn yet) ------------------------


def test_generate_without_server_section_exits_2(tmp_path):
    workspace = harness.standard_workspace(tmp_path)
    result = harness.run_cli(["generate", "--config", "config.json"], cwd=workspace)
    result.assert_exit(2)
    assert result.lines == ["error: no server section in config (no fallback launch)"]


def test_generate_command_not_found_exits_2(tmp_path):
    workspace = harness.standard_workspace(tmp_path)
    set_config_server_section(workspace, "/nonexistent/llama-server")
    harness.add_summarizer_section(str(workspace / "config.json"))
    result = harness.run_cli(["generate", "--config", "config.json"], cwd=workspace)
    result.assert_exit(2)
    assert result.lines == [
        "plan(generate): 1 summarizer, 24 items, 1 server cycle",
        "error: server: command not found: /nonexistent/llama-server",
    ]


def test_generate_valid_section_prints_plan_lines(tmp_path):
    workspace = harness.standard_workspace(tmp_path)
    set_config_server_section(workspace, FIXTURE)
    result = harness.run_cli(["generate", "--config", "config.json"], cwd=workspace)
    result.assert_exit(0)
    assert result.lines == [
        "plan(generate): 0 summarizers, 0 items, 0 server cycles",
        "done(generate): 0 committed, 0 skipped, 0 failed",
    ]


def test_generate_busy_port_exits_2(tmp_path, monkeypatch):
    workspace = harness.standard_workspace(tmp_path)
    set_config_server_section(workspace, FIXTURE, port=8081)
    harness.add_summarizer_section(str(workspace / "config.json"))
    monkeypatch.setattr(model_server, "port_is_free", raise_busy_port)
    result = harness.run_cli(["generate", "--config", "config.json"], cwd=workspace)
    result.assert_exit(2)
    assert result.lines == [
        "plan(generate): 1 summarizer, 24 items, 1 server cycle",
        "error: port 8081 already bound "
        "(a previous model server may still be running)",
    ]
