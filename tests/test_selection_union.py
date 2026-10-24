import harness


def run_select(workspace, *argv):
    return harness.run_cli(["generate", *argv], cwd=workspace)


def test_occurrences_are_unioned(tmp_path):
    workspace = harness.standard_workspace(tmp_path)
    result = run_select(
        workspace, "--select", "named", "#0,1", "--select", "named", "#1,2"
    )
    result.assert_exit(0)
    assert harness.plan_count(result, "generate", "named") == 3


def test_duplicates_are_dropped(tmp_path):
    workspace = harness.standard_workspace(tmp_path)
    result = run_select(
        workspace,
        "--select", "named", "#0",
        "--select", "named", "#0",
        "--select", "named", "#2-4",
    )
    result.assert_exit(0)
    assert harness.plan_count(result, "generate", "named") == 4


def test_occurrence_with_zero_specs_is_an_error(tmp_path):
    workspace = harness.standard_workspace(tmp_path)
    result = run_select(workspace, "--select", "named")
    result.assert_exit(2)
    assert result.with_prefix("error:")


def test_no_flag_means_full_scope(tmp_path):
    workspace = harness.standard_workspace(tmp_path)
    result = harness.run_cli(["generate"], cwd=workspace)
    result.assert_exit(0)
    assert harness.plan_count(result, "generate", "named") == 12
    assert harness.plan_count(result, "generate", "unnamed") == 12


def test_union_across_datasets(tmp_path):
    workspace = harness.standard_workspace(tmp_path)
    result = run_select(
        workspace, "--select", "named", "#0", "--select", "unnamed", "#1"
    )
    result.assert_exit(0)
    assert harness.plan_count(result, "generate", "named") == 1
    assert harness.plan_count(result, "generate", "unnamed") == 1
