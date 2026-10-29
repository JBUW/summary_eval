"""Ticket 11 — check's live phase (units): the model server cycles, the
per-pair summarizer probes (pair order, surface dedup, message shape,
gen_params passthrough), the once-per-dataset context adequacy check
(tokenize gating, warn wordings, chars/3 estimate fallback), and the
static-fail-skip structure, the local fail-fast shape (error line plus
the last twenty log lines, stop, exit 1), and the remote judge probes
behind --probe-judges (message shape, parseable and rejected outcomes,
transport failure, requires_reference gating). The endpoint client and
the server cycles are faked at the evalapp.check_live module attributes;
everything else runs through the real CLI entry point.
"""
import json
import os

import harness  # noqa: F401  (puts the repo root on sys.path)

import evalapp.check_live as check_live
from evalapp.endpoint_client import EndpointError
from evalapp.errors import RuntimeFailure

PORT = 18111
ROOT = f"http://127.0.0.1:{PORT}"


class FakeServer:
    root = ROOT

    def log_tail(self, n=20):
        return []


class FakeCycles:
    def __init__(self):
        self.ensured = []
        self.stopped = False
        self.ensure_error = None

    def ensure(self, model, model_args):
        if self.ensure_error is not None:
            raise self.ensure_error
        self.ensured.append((model, model_args))
        return FakeServer()

    def stop(self):
        self.stopped = True

    def log_tail(self, n=20):
        return ["tail line 1", "tail line 2", "tail line 3"]


class FakeClient:
    def __init__(self):
        self.completions = []
        self.tokenize_calls = []
        self.tokenize_result = 0
        self.tokenize_error = None
        self.complete_result = "ok"
        self.complete_error = None

    def complete(self, endpoint, model_name, messages, gen_params=None,
                 api_key_env=None, timeout=None):
        if self.complete_error is not None:
            raise self.complete_error
        self.completions.append(
            (endpoint, model_name, list(messages), gen_params, api_key_env)
        )
        return self.complete_result

    def tokenize(self, server_root, text, timeout=None):
        self.tokenize_calls.append((server_root, text))
        if self.tokenize_error is not None:
            raise self.tokenize_error
        return self.tokenize_result


def _install(monkeypatch, client, cycles):
    """Patch create_client / ServerCycles on evalapp.check_live; return a call log."""
    log = {"clients": 0, "cycles": 0}

    def fake_create_client(timeout=None):
        log["clients"] += 1
        return client

    def fake_cycles(spec, model_paths, client_arg, console=None):
        log["cycles"] += 1
        return cycles

    monkeypatch.setattr(check_live, "create_client", fake_create_client)
    monkeypatch.setattr(check_live, "ServerCycles", fake_cycles)
    return log


def _workspace(tmp_path, server_args=None):
    workspace = harness.standard_workspace(tmp_path)
    config_path = os.path.join(str(workspace), "config.json")
    harness.add_server_section(config_path, port=PORT)
    if server_args is not None:
        with open(config_path, "r", encoding="utf-8") as handle:
            config = json.load(handle)
        config["server"]["args"] = server_args
        harness.write_text(config_path, json.dumps(config, indent=2) + "\n")
    return workspace


def _add_surfaces(workspace, models, templates, summarizers):
    config_path = os.path.join(str(workspace), "config.json")
    with open(config_path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    for name in models:
        harness.write_text(
            os.path.join(str(workspace), models[name]["path"]),
            f"model-bytes-{name}",
        )
    for name in templates:
        harness.write_text(
            os.path.join(str(workspace), f"{name}.json"),
            json.dumps(templates[name]) + "\n",
        )
    config["models"] = models
    config["prompt_templates"] = {
        name: {"path": f"{name}.json"} for name in templates
    }
    config["summarizers"] = summarizers
    harness.write_text(config_path, json.dumps(config, indent=2) + "\n")


def _write_dataset(workspace, name, transcripts):
    objects = [
        {"text": text, "id": f"id-{index:02d}"} if name == "named"
        else {"text": text}
        for index, text in enumerate(transcripts)
    ]
    harness.write_jsonl(os.path.join(str(workspace), f"{name}.jsonl"), objects)


def _probe_workspace(tmp_path, server_args):
    """Standard workspace + one model/template/summarizer + server args."""
    workspace = _workspace(tmp_path, server_args)
    harness.add_summarizer_section(os.path.join(str(workspace), "config.json"))
    return workspace


JUDGE_ENDPOINT = "https://judges.example.com/v1"
PARSEABLE_JUDGE = (
    "factual_correctness: 1.0\n"
    "completeness: 0.5\n"
    "conciseness: 1.0"
)
JUDGE_DISCOVERY = harness.discovery_lines(harness.ALL_METRICS, [], ["j"], [])


def _judge_workspace(tmp_path, user_template, requires_reference=False):
    """Standard workspace + server section + one judge 'j' (no gen_params)."""
    workspace = _workspace(tmp_path)
    config_path = os.path.join(str(workspace), "config.json")
    with open(config_path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    config["judges"] = {
        "j": {
            "endpoint": JUDGE_ENDPOINT,
            "model_name": "judge-model",
            "api_key_env": "JUDGE_KEY",
            "requires_reference": requires_reference,
            "user_template": user_template,
        }
    }
    harness.write_text(config_path, json.dumps(config, indent=2) + "\n")
    return workspace


def test_no_models_exit_0_identical_to_today(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    client, cycles = FakeClient(), FakeCycles()
    log = _install(monkeypatch, client, cycles)
    result = harness.run_cli(["check"], cwd=str(workspace))
    result.assert_exit(0)
    assert result.lines == harness.STANDARD_DISCOVERY + [
        "plan(check): 2 datasets",
        "note: no store at store.db",
    ]
    assert log == {"clients": 0, "cycles": 0}
    assert client.completions == []
    assert client.tokenize_calls == []
    assert cycles.ensured == []
    assert cycles.stopped is False


def test_pair_order_summarizer_dedup_and_message_shape(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    _add_surfaces(
        workspace,
        {
            "m1": {"path": "m1.bin"},
            "m2": {"path": "m2.bin", "model_args": {"foo": "bar"}},
        },
        {
            "t1": {"system_content": "sys-a", "user_template": "usr-a"},
            "t2": {"system_content": "", "user_template": "usr-b"},
            "t3": {"system_content": "sys-c", "user_template": "usr-c"},
        },
        {
            "s1": {"model": "m1", "prompt_template": "t1"},
            "s2": {"model": "m1", "prompt_template": "t2", "gen_params": {"temp": 0.2}},
            "s3": {"model": "m1", "prompt_template": "t1"},
            "s4": {"model": "m2", "prompt_template": "t3"},
        },
    )
    client, cycles = FakeClient(), FakeCycles()
    _install(monkeypatch, client, cycles)
    result = harness.run_cli(["check"], cwd=str(workspace))
    result.assert_exit(0)
    assert result.lines == harness.STANDARD_DISCOVERY + [
        "plan(check): 2 datasets",
        "note: no store at store.db",
        "done(check): 2 server cycles, 3 summarizer probes, 0 judge probes",
    ]
    assert cycles.ensured == [("m1", {}), ("m2", {"foo": "bar"})]
    assert cycles.stopped is True
    probe = check_live.PROBE_TRANSCRIPT
    assert client.completions == [
        (
            ROOT, "m1",
            [
                {"role": "system", "content": "sys-a"},
                {"role": "user", "content": "usr-a" + probe},
            ],
            {},
            None,
        ),
        (
            ROOT, "m1",
            [{"role": "user", "content": "usr-b" + probe}],
            {"temp": 0.2},
            None,
        ),
        (
            ROOT, "m2",
            [
                {"role": "system", "content": "sys-c"},
                {"role": "user", "content": "usr-c" + probe},
            ],
            {},
            None,
        ),
    ]
    assert client.tokenize_calls == []


def test_context_adequacy_tokenizes_longest_once_per_dataset(tmp_path, monkeypatch):
    workspace = _probe_workspace(tmp_path, {"ctx-size": 100})
    _write_dataset(workspace, "named", ["a", "bb", "ccc"])
    _write_dataset(workspace, "unnamed", ["x", "yy"])
    client, cycles = FakeClient(), FakeCycles()
    client.tokenize_result = 5
    _install(monkeypatch, client, cycles)
    result = harness.run_cli(["check"], cwd=str(workspace))
    result.assert_exit(0)
    assert result.lines == harness.STANDARD_DISCOVERY + [
        "plan(check): 2 datasets",
        "note: no store at store.db",
        "done(check): 1 server cycle, 1 summarizer probe, 0 judge probes",
    ]
    assert client.tokenize_calls == [(ROOT, "ccc"), (ROOT, "yy")]


def test_context_adequacy_warns_when_longest_exceeds_ctx(tmp_path, monkeypatch):
    workspace = _probe_workspace(tmp_path, {"ctx-size": 4})
    _write_dataset(workspace, "named", ["a", "bb", "ccc"])
    _write_dataset(workspace, "unnamed", ["x", "yy"])
    client, cycles = FakeClient(), FakeCycles()
    client.tokenize_result = 5
    _install(monkeypatch, client, cycles)
    result = harness.run_cli(["check"], cwd=str(workspace))
    result.assert_exit(0)
    assert result.lines == harness.STANDARD_DISCOVERY + [
        "plan(check): 2 datasets",
        "note: no store at store.db",
        "warn: dataset 'named': longest transcript (5 tokens) "
        "exceeds context size (4)",
        "warn: dataset 'unnamed': longest transcript (5 tokens) "
        "exceeds context size (4)",
        "done(check): 1 server cycle, 1 summarizer probe, 0 judge probes",
    ]


def test_context_adequacy_no_call_without_ctx_size(tmp_path, monkeypatch):
    workspace = _probe_workspace(tmp_path, {})
    client, cycles = FakeClient(), FakeCycles()
    _install(monkeypatch, client, cycles)
    result = harness.run_cli(["check"], cwd=str(workspace))
    result.assert_exit(0)
    assert client.tokenize_calls == []
    assert result.with_prefix("warn:") == []


def test_context_adequacy_no_call_for_non_int_or_bool_ctx_size(tmp_path, monkeypatch):
    for label, ctx_size in (("str", "100"), ("bool", True)):
        workspace = _probe_workspace(tmp_path / label, {"ctx-size": ctx_size})
        client, cycles = FakeClient(), FakeCycles()
        _install(monkeypatch, client, cycles)
        result = harness.run_cli(["check"], cwd=str(workspace))
        result.assert_exit(0)
        assert client.tokenize_calls == []


def test_context_adequacy_estimate_fallback_on_endpoint_error(tmp_path, monkeypatch):
    workspace = _probe_workspace(tmp_path, {"ctx-size": 1})
    _write_dataset(workspace, "named", ["a", "cccccc"])
    _write_dataset(workspace, "unnamed", ["x"])
    client, cycles = FakeClient(), FakeCycles()
    client.tokenize_error = EndpointError("connection failed: refused")
    _install(monkeypatch, client, cycles)
    result = harness.run_cli(["check"], cwd=str(workspace))
    result.assert_exit(0)
    assert client.tokenize_calls == [(ROOT, "cccccc"), (ROOT, "x")]
    assert result.lines == harness.STANDARD_DISCOVERY + [
        "plan(check): 2 datasets",
        "note: no store at store.db",
        "warn: dataset 'named': longest transcript "
        "(~2 tokens estimated from chars/3) exceeds context size (1)",
        "done(check): 1 server cycle, 1 summarizer probe, 0 judge probes",
    ]


def test_static_failure_skips_live(tmp_path, monkeypatch):
    workspace = _probe_workspace(tmp_path, {})
    os.remove(os.path.join(str(workspace), "named.jsonl"))
    client, cycles = FakeClient(), FakeCycles()
    log = _install(monkeypatch, client, cycles)
    result = harness.run_cli(["check"], cwd=str(workspace))
    result.assert_exit(2)
    assert result.lines == harness.STANDARD_DISCOVERY + [
        "plan(check): 2 datasets",
        "error: dataset 'named': file not found: named.jsonl",
    ]
    assert log == {"clients": 0, "cycles": 0}
    assert client.completions == []
    assert cycles.ensured == []


def test_ensure_runtime_failure_fails_fast_with_tail_and_stop(
    tmp_path, monkeypatch
):
    workspace = _probe_workspace(tmp_path, {})
    client, cycles = FakeClient(), FakeCycles()
    cycles.ensure_error = RuntimeFailure("readiness probe failed")
    _install(monkeypatch, client, cycles)
    result = harness.run_cli(["check"], cwd=str(workspace))
    result.assert_exit(1)
    assert result.lines == harness.STANDARD_DISCOVERY + [
        "plan(check): 2 datasets",
        "note: no store at store.db",
        "error: model 'm': readiness probe failed",
        "tail line 1",
        "tail line 2",
        "tail line 3",
    ]
    assert cycles.stopped is True
    assert client.completions == []


def test_probe_endpoint_error_fails_fast_with_tail(tmp_path, monkeypatch):
    workspace = _probe_workspace(tmp_path, {})
    client, cycles = FakeClient(), FakeCycles()
    client.complete_error = EndpointError("HTTP 500")
    _install(monkeypatch, client, cycles)
    result = harness.run_cli(["check"], cwd=str(workspace))
    result.assert_exit(1)
    assert result.lines == harness.STANDARD_DISCOVERY + [
        "plan(check): 2 datasets",
        "note: no store at store.db",
        "error: summarizer 's': HTTP 500 from model server",
        "tail line 1",
        "tail line 2",
        "tail line 3",
    ]
    assert cycles.stopped is True


def test_judge_probe_parseable_counts_and_exit_0(tmp_path, monkeypatch):
    workspace = _judge_workspace(
        tmp_path, "transcript: {transcript}\nsummary: {summary}"
    )
    monkeypatch.setenv("JUDGE_KEY", "test-key")
    client, cycles = FakeClient(), FakeCycles()
    client.complete_result = PARSEABLE_JUDGE
    log = _install(monkeypatch, client, cycles)
    result = harness.run_cli(["check", "--probe-judges"], cwd=str(workspace))
    result.assert_exit(0)
    assert result.lines == JUDGE_DISCOVERY + [
        "plan(check): 2 datasets",
        "note: no store at store.db",
        "done(check): 0 server cycles, 0 summarizer probes, 1 judge probe",
    ]
    assert log == {"clients": 1, "cycles": 0}
    assert client.completions == [
        (
            JUDGE_ENDPOINT,
            "judge-model",
            [
                {
                    "role": "user",
                    "content": "transcript: "
                    + check_live.JUDGE_EXAMPLE_TRANSCRIPT
                    + "\nsummary: "
                    + check_live.JUDGE_EXAMPLE_SUMMARY,
                }
            ],
            {},
            "JUDGE_KEY",
        )
    ]


def test_judge_probe_rejected_response_exit_1(tmp_path, monkeypatch):
    workspace = _judge_workspace(tmp_path, "t: {transcript} s: {summary}")
    monkeypatch.setenv("JUDGE_KEY", "test-key")
    client, cycles = FakeClient(), FakeCycles()
    client.complete_result = "I cannot evaluate this response."
    _install(monkeypatch, client, cycles)
    result = harness.run_cli(["check", "--probe-judges"], cwd=str(workspace))
    result.assert_exit(1)
    assert result.lines == JUDGE_DISCOVERY + [
        "plan(check): 2 datasets",
        "note: no store at store.db",
        "error: judge 'j': no usable values in probe response",
    ]


def test_judge_probe_transport_failure_exit_1_without_tail(
    tmp_path, monkeypatch
):
    workspace = _judge_workspace(tmp_path, "t: {transcript} s: {summary}")
    monkeypatch.setenv("JUDGE_KEY", "test-key")
    client, cycles = FakeClient(), FakeCycles()
    client.complete_error = EndpointError("connection timed out")
    _install(monkeypatch, client, cycles)
    result = harness.run_cli(["check", "--probe-judges"], cwd=str(workspace))
    result.assert_exit(1)
    assert result.lines == JUDGE_DISCOVERY + [
        "plan(check): 2 datasets",
        "note: no store at store.db",
        "error: judge 'j': connection timed out",
    ]


def test_probe_judges_off_makes_no_judge_calls(tmp_path, monkeypatch):
    workspace = _judge_workspace(tmp_path, "t: {transcript} s: {summary}")
    monkeypatch.delenv("JUDGE_KEY", raising=False)
    client, cycles = FakeClient(), FakeCycles()
    log = _install(monkeypatch, client, cycles)
    result = harness.run_cli(["check"], cwd=str(workspace))
    result.assert_exit(0)
    assert result.lines == JUDGE_DISCOVERY + [
        "plan(check): 2 datasets",
        "note: no store at store.db",
    ]
    assert log == {"clients": 0, "cycles": 0}
    assert client.completions == []


def test_judge_requires_reference_false_leaves_placeholder_literal(
    tmp_path, monkeypatch
):
    workspace = _judge_workspace(
        tmp_path,
        "t: {transcript} s: {summary} r: {reference}",
        requires_reference=False,
    )
    monkeypatch.setenv("JUDGE_KEY", "test-key")
    client, cycles = FakeClient(), FakeCycles()
    client.complete_result = PARSEABLE_JUDGE
    _install(monkeypatch, client, cycles)
    result = harness.run_cli(["check", "--probe-judges"], cwd=str(workspace))
    result.assert_exit(0)
    assert client.completions[0][2] == [
        {
            "role": "user",
            "content": "t: "
            + check_live.JUDGE_EXAMPLE_TRANSCRIPT
            + " s: "
            + check_live.JUDGE_EXAMPLE_SUMMARY
            + " r: {reference}",
        }
    ]


def test_judge_without_gen_params_no_keyerror(tmp_path, monkeypatch):
    workspace = _judge_workspace(tmp_path, "t: {transcript} s: {summary}")
    monkeypatch.setenv("JUDGE_KEY", "test-key")
    client, cycles = FakeClient(), FakeCycles()
    client.complete_result = PARSEABLE_JUDGE
    _install(monkeypatch, client, cycles)
    result = harness.run_cli(["check", "--probe-judges"], cwd=str(workspace))
    result.assert_exit(0)
    assert client.completions[0][3] == {}
