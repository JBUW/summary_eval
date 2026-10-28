import pytest

import harness


def run_select(workspace, *tokens):
    return harness.run_cli(["generate", "--select", *tokens], cwd=workspace)


def test_hash_specs_select_counts(tmp_path):
    workspace = harness.standard_workspace(tmp_path)
    harness.add_server_section(str(workspace / "config.json"))
    harness.add_summarizer_section(str(workspace / "config.json"))
    cases = {
        ("#0",): 1,
        ("#3-7",): 5,
        ("#0,5,10-11",): 4,
        ("#3-7,0",): 6,
        ("#5,1,3",): 3,
        ("#00,01",): 2,
    }
    for tokens, expected in cases.items():
        result = run_select(workspace, "named", *tokens)
        result.assert_exit(1)
        assert harness.plan_items(result) == expected, tokens


def test_hash_specs_reject_invalid(tmp_path):
    workspace = harness.standard_workspace(tmp_path)
    for spec in ("#12", "#7-3", "#a", "#", "#1-", "#-1", "#1-2-3", "#0,@x"):
        result = run_select(workspace, "named", spec)
        result.assert_exit(2)
        assert result.with_prefix("error:"), spec


def test_hash_specs_valid_in_unnamed_datasets(tmp_path):
    workspace = harness.standard_workspace(tmp_path)
    harness.add_server_section(str(workspace / "config.json"))
    harness.add_summarizer_section(str(workspace / "config.json"))
    result = run_select(workspace, "unnamed", "#1-4")
    result.assert_exit(1)
    assert harness.plan_items(result) == 4
