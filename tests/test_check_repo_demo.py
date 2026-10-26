import os

import pytest

import harness
from evalapp import cli
from evalapp.errors import SpecError

EXPECTED_ERRORS = [
    "error: dataset 'meetbank': file not found: data/meetbank_50.csv",
    "error: dataset 'qmsum-dev': file not found: data/qmsum_dev.jsonl",
    "error: server: command not found: "
    "/home/vscode/llama.cpp/build-rocm/bin/llama-server",
    "error: model 'gemma-3-27b-it-q4_k_m': file not found: "
    "/home/vscode/models/gemma-3-27b-it.Q4_K_M.gguf",
    "error: model 'qwen3-32b-it-q4_k_m': file not found: "
    "/home/vscode/models/qwen3-32b-it.Q4_K_M.gguf",
    "error: prompt template 'decision-minutes': file not found: "
    "prompts/decision-minutes.json",
    "error: prompt template 'detailed-report': file not found: "
    "prompts/detailed-report.json",
    "error: prompt template 'brief-summary': file not found: "
    "prompts/brief-summary.json",
]


def test_repo_config_demo_reports_missing_files():
    try:
        cli.port_is_free(8080)
    except SpecError:
        pytest.skip("port 8080 already bound")
    result = harness.run_cli(["check"], cwd=harness.REPO_ROOT)
    result.assert_exit(2)
    assert result.lines == (
        harness.REPO_DISCOVERY + ["plan(check): 2 datasets"] + EXPECTED_ERRORS
    )
    assert not os.path.exists(
        os.path.join(harness.REPO_ROOT, "evalstore.sqlite3")
    )
