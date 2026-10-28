import harness


def make_workspace(tmp_path, decl):
    harness.write_config(
        str(tmp_path / "config.json"),
        {"ds": decl},
        store="store.db",
    )
    return tmp_path


def generate(workspace):
    return harness.run_cli(["generate"], cwd=workspace)


def test_missing_file(tmp_path):
    workspace = make_workspace(tmp_path, {"path": "missing.jsonl", "transcript_field": "text"})
    result = generate(workspace)
    result.assert_exit(2)
    errors = result.with_prefix("error:")
    assert len(errors) == 1
    assert "file not found" in errors[0]


def test_unsupported_extension(tmp_path):
    harness.write_text(str(tmp_path / "ds.txt"), "hello\n")
    workspace = make_workspace(tmp_path, {"path": "ds.txt", "transcript_field": "text"})
    result = generate(workspace)
    result.assert_exit(2)
    errors = result.with_prefix("error:")
    assert len(errors) == 1
    assert "unsupported file extension" in errors[0]


def test_header_only_csv_has_no_entries(tmp_path):
    harness.write_csv(str(tmp_path / "ds.csv"), ["text"], [])
    workspace = make_workspace(tmp_path, {"path": "ds.csv", "transcript_field": "text"})
    result = generate(workspace)
    result.assert_exit(2)
    errors = result.with_prefix("error:")
    assert len(errors) == 1
    assert "no entries" in errors[0]


def test_empty_jsonl_file_has_no_entries(tmp_path):
    harness.write_text(str(tmp_path / "ds.jsonl"), "")
    workspace = make_workspace(tmp_path, {"path": "ds.jsonl", "transcript_field": "text"})
    result = generate(workspace)
    result.assert_exit(2)
    errors = result.with_prefix("error:")
    assert len(errors) == 1
    assert "no entries" in errors[0]


def test_non_json_line_in_jsonl(tmp_path):
    harness.write_text(str(tmp_path / "ds.jsonl"), "not json\n")
    workspace = make_workspace(tmp_path, {"path": "ds.jsonl", "transcript_field": "text"})
    result = generate(workspace)
    result.assert_exit(2)
    errors = result.with_prefix("error:")
    assert len(errors) == 1
    assert "malformed line 1" in errors[0]


def test_declared_csv_column_absent(tmp_path):
    harness.write_csv(str(tmp_path / "ds.csv"), ["body"], [["x"]])
    workspace = make_workspace(tmp_path, {"path": "ds.csv", "transcript_field": "text"})
    result = generate(workspace)
    result.assert_exit(2)
    errors = result.with_prefix("error:")
    assert len(errors) == 1
    assert "not found" in errors[0]


def test_declared_jsonl_key_absent(tmp_path):
    harness.write_jsonl(str(tmp_path / "ds.jsonl"), [{"body": "x"}])
    workspace = make_workspace(tmp_path, {"path": "ds.jsonl", "transcript_field": "text"})
    result = generate(workspace)
    result.assert_exit(2)
    errors = result.with_prefix("error:")
    assert len(errors) == 1
    assert "not found" in errors[0]


def test_csv_row_with_extra_column(tmp_path):
    harness.write_csv(str(tmp_path / "ds.csv"), ["text", "id"], [["a", "b", "c"]])
    workspace = make_workspace(
        tmp_path,
        {"path": "ds.csv", "transcript_field": "text", "entry_id_field": "id"},
    )
    result = generate(workspace)
    result.assert_exit(2)
    errors = result.with_prefix("error:")
    assert len(errors) == 1
    assert "malformed line 2" in errors[0]


def test_json_extension_is_one_object_per_line(tmp_path):
    harness.write_jsonl(str(tmp_path / "ds.json"), [{"text": "a"}, {"text": "b"}])
    workspace = make_workspace(tmp_path, {"path": "ds.json", "transcript_field": "text"})
    harness.add_server_section(str(tmp_path / "config.json"))
    harness.add_summarizer_section(str(tmp_path / "config.json"))
    result = generate(workspace)
    result.assert_exit(1)
    assert harness.plan_items(result) == 2
