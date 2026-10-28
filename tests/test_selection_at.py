import harness


def workspace_with_ids(tmp_path, ids):
    harness.write_jsonl(
        str(tmp_path / "named.jsonl"),
        [{"text": f"t{i}", "id": entry_id} for i, entry_id in enumerate(ids)],
    )
    harness.write_config(
        str(tmp_path / "config.json"),
        {"named": {"path": "named.jsonl", "transcript_field": "text", "entry_id_field": "id"}},
        store="store.db",
    )
    harness.add_server_section(str(tmp_path / "config.json"))
    harness.add_summarizer_section(str(tmp_path / "config.json"))
    return tmp_path


def test_at_spec_selects_one_entry(tmp_path):
    workspace = harness.standard_workspace(tmp_path)
    harness.add_server_section(str(workspace / "config.json"))
    harness.add_summarizer_section(str(workspace / "config.json"))
    result = harness.run_cli(
        ["generate", "--select", "named", "@id-03"], cwd=workspace
    )
    result.assert_exit(1)
    assert harness.plan_items(result) == 1


def test_double_at_names_literal_at_id(tmp_path):
    workspace = workspace_with_ids(tmp_path, ["@x", "y"])
    result = harness.run_cli(
        ["generate", "--select", "named", "@@x"], cwd=workspace
    )
    result.assert_exit(1)
    assert harness.plan_items(result) == 1


def test_at_spec_rejected_in_unnamed_dataset(tmp_path):
    workspace = harness.standard_workspace(tmp_path)
    result = harness.run_cli(
        ["generate", "--select", "unnamed", "@anything"], cwd=workspace
    )
    result.assert_exit(2)
    assert result.with_prefix("error:")


def test_at_spec_unknown_id(tmp_path):
    workspace = harness.standard_workspace(tmp_path)
    result = harness.run_cli(
        ["generate", "--select", "named", "@nope"], cwd=workspace
    )
    result.assert_exit(2)
    errors = result.with_prefix("error:")
    assert len(errors) == 1
    assert "nope" in errors[0]


def test_at_spec_id_may_contain_comma(tmp_path):
    workspace = workspace_with_ids(tmp_path, ["a,b", "a", "b"])
    result = harness.run_cli(
        ["generate", "--select", "named", "@a,b"], cwd=workspace
    )
    result.assert_exit(1)
    assert harness.plan_items(result) == 1
