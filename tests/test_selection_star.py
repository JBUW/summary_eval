import harness


def run_select(workspace, *argv):
    return harness.run_cli(["generate", *argv], cwd=workspace)


def test_named_star_selects_all_of_that_dataset(tmp_path):
    workspace = harness.standard_workspace(tmp_path)
    harness.add_server_section(str(workspace / "config.json"))
    harness.add_summarizer_section(str(workspace / "config.json"))
    result = run_select(workspace, "--select", "named", "*")
    result.assert_exit(1)
    assert harness.plan_items(result) == 12


def test_bare_star_selects_all_datasets_and_entries(tmp_path):
    workspace = harness.standard_workspace(tmp_path)
    harness.add_server_section(str(workspace / "config.json"))
    harness.add_summarizer_section(str(workspace / "config.json"))
    result = run_select(workspace, "--select", "*")
    result.assert_exit(1)
    assert harness.plan_items(result) == 24


def test_star_must_be_the_sole_token(tmp_path):
    workspace = harness.standard_workspace(tmp_path)
    result = run_select(workspace, "--select", "*", "named")
    result.assert_exit(2)
    assert result.with_prefix("error:")


def test_star_prefix_is_not_a_dataset_name(tmp_path):
    workspace = harness.standard_workspace(tmp_path)
    result = run_select(workspace, "--select", "*x")
    result.assert_exit(2)
    assert result.with_prefix("error:")


def test_bare_star_unions_with_explicit_occurrence(tmp_path):
    workspace = harness.standard_workspace(tmp_path)
    harness.add_server_section(str(workspace / "config.json"))
    harness.add_summarizer_section(str(workspace / "config.json"))
    result = run_select(workspace, "--select", "*", "--select", "named", "#0")
    result.assert_exit(1)
    assert harness.plan_items(result) == 24
