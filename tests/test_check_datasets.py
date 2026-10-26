import harness


def _write(tmp_path, datasets, extra=None):
    harness.write_config(
        str(tmp_path / "config.json"),
        datasets,
        store="store.db",
        extra_top_level=extra,
    )
    harness.add_server_section(str(tmp_path / "config.json"))


def test_missing_dataset_file(tmp_path):
    _write(tmp_path, {"d": {"path": "missing.jsonl", "transcript_field": "text"}})
    result = harness.run_cli(["check"], cwd=tmp_path)
    result.assert_exit(2)
    assert result.lines == harness.STANDARD_DISCOVERY + [
        "plan(check): 1 datasets",
        "error: dataset 'd': file not found: missing.jsonl",
    ]


def test_unsupported_extension(tmp_path):
    harness.write_text(str(tmp_path / "d.txt"), "transcript")
    _write(tmp_path, {"d": {"path": "d.txt", "transcript_field": "text"}})
    result = harness.run_cli(["check"], cwd=tmp_path)
    result.assert_exit(2)
    assert result.lines == harness.STANDARD_DISCOVERY + [
        "plan(check): 1 datasets",
        "error: dataset 'd': unsupported file extension 'txt' "
        "(supported: .csv, .jsonl, .json)",
    ]


def test_malformed_jsonl_reports_every_bad_line(tmp_path):
    harness.write_text(str(tmp_path / "d.jsonl"), "{bad json\n[1, 2]\n")
    _write(tmp_path, {"d": {"path": "d.jsonl", "transcript_field": "text"}})
    result = harness.run_cli(["check"], cwd=tmp_path)
    result.assert_exit(2)
    assert result.lines == harness.STANDARD_DISCOVERY + [
        "plan(check): 1 datasets",
        "error: dataset 'd': malformed line 1 in d.jsonl: not a JSON object: "
        "Expecting property name enclosed in double quotes: line 1 column 2 (char 1)",
        "error: dataset 'd': malformed line 2 in d.jsonl: expected a JSON object",
        "error: dataset 'd': no entries in d.jsonl",
    ]
