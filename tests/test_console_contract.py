import harness


def test_clear_noop_uses_note_not_error(tmp_path):
    harness.standard_workspace(tmp_path)
    result = harness.run_cli(["clear"], cwd=tmp_path)
    result.assert_exit(0)
    assert result.lines == ["note: no store at store.db; nothing to clear"]
    assert not result.with_prefix("error:")


def test_generate_empty_scope_uses_note_not_error(tmp_path):
    harness.write_config(str(tmp_path / "config.json"), {}, store="store.db")
    result = harness.run_cli(["generate"], cwd=tmp_path)
    result.assert_exit(0)
    assert result.lines == ["note: no entries in scope; nothing to do"]
    assert not result.with_prefix("error:")


def test_message_order_warn_plan_note(tmp_path):
    harness.write_jsonl(
        str(tmp_path / "only.jsonl"),
        [{"text": "transcript", "id": "a"}],
    )
    harness.write_config(
        str(tmp_path / "config.json"),
        {"only": {"path": "only.jsonl", "transcript_field": "text", "entry_id_field": "id"}},
        store="store.db",
        extra_top_level={"bogus_key": 1},
    )
    harness.add_server_section(str(tmp_path / "config.json"))
    result = harness.run_cli(["check"], cwd=tmp_path)
    result.assert_exit(0)
    assert result.lines == [
        "warn: unrecognized field 'bogus_key' in config"
    ] + harness.STANDARD_DISCOVERY + [
        "plan(check): 1 datasets",
        "note: no store at store.db",
    ]


def test_spec_error_uses_error_and_exit_class_2(tmp_path):
    harness.standard_workspace(tmp_path)
    result = harness.run_cli(["generate", "--select", "named", "#99"], cwd=tmp_path)
    result.assert_exit(2)
    errors = result.with_prefix("error:")
    assert len(errors) == 1
    assert "out of range" in errors[0]
    assert not result.with_prefix("plan(generate):")
