"""Ticket 08 — score pre-effect: parser flags, --server-* guard, judge credential preflight."""
import harness  # noqa: F401  (puts the repo root on sys.path)

import json
import os


def test_bare_metrics_flag_rejected_by_parser(tmp_path):
    harness.standard_workspace(tmp_path)
    result = harness.run_cli(["score", "--metrics"], cwd=tmp_path)
    result.assert_exit(2)
    assert result.with_prefix("error:") == [
        "error: argument --metrics: expected at least one argument"
    ]


def test_server_flag_without_generate_rejected(tmp_path):
    result = harness.run_cli(["score", "--server-port", "8081"], cwd=tmp_path)
    result.assert_exit(2)
    assert result.lines == ["error: --server-* flags require --generate"]


def test_generate_passes_guard_and_fails_at_preflight(tmp_path):
    harness.standard_workspace(tmp_path)
    harness.add_summarizer_section(str(tmp_path / "config.json"))
    harness.add_server_section(str(tmp_path / "config.json"), port=18101)
    result = harness.run_cli(
        ["score", "--generate", "--server-port", "18101"], cwd=tmp_path
    )
    result.assert_exit(1)
    assert result.with_prefix("plan(generate):")
    assert not any(
        "--server-* flags require --generate" in line for line in result.lines
    )


def test_scorer_flags_mutually_exclusive(tmp_path):
    harness.standard_workspace(tmp_path)
    result = harness.run_cli(
        ["score", "--no-metrics", "--metrics", "factual_correctness"],
        cwd=tmp_path,
    )
    result.assert_exit(2)
    assert result.lines == [
        "error: --no-metrics is mutually exclusive with --metrics"
    ]
    result = harness.run_cli(["score", "--no-judges", "--judges"], cwd=tmp_path)
    result.assert_exit(2)
    assert result.lines == [
        "error: --no-judges is mutually exclusive with --judges"
    ]


def test_judge_credential_preflight(tmp_path):
    harness.standard_workspace(tmp_path)
    harness.add_summarizer_section(str(tmp_path / "config.json"))
    path = str(tmp_path / "config.json")
    with open(path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    config["judges"] = {
        "j": {
            "endpoint": "http://127.0.0.1:1",
            "model_name": "judge-model",
            "api_key_env": "EVALAPP_TEST_UNSET_JUDGE_VAR",
            "user_template": "transcript: {transcript} summary: {summary}",
            "requires_reference": False,
        }
    }
    harness.write_text(path, json.dumps(config, indent=2) + "\n")
    os.environ.pop("EVALAPP_TEST_UNSET_JUDGE_VAR", None)
    result = harness.run_cli(["score", "--judges", "j"], cwd=tmp_path)
    result.assert_exit(2)
    assert result.lines == [
        "error: judge 'j': environment variable "
        "'EVALAPP_TEST_UNSET_JUDGE_VAR' is unset or empty"
    ]
    os.environ["EVALAPP_TEST_UNSET_JUDGE_VAR"] = "key"
    try:
        for argv in (["score", "--no-judges"], ["score"]):
            result = harness.run_cli(argv, cwd=tmp_path)
            result.assert_exit(0)
            assert not result.with_prefix("error:")
    finally:
        os.environ.pop("EVALAPP_TEST_UNSET_JUDGE_VAR", None)
