"""Dataset load contract: R1 fail-fast set in fail-fast and collect mode (ticket 02b)."""
import pytest

import harness  # noqa: F401  (puts the repo root on sys.path)
from evalapp.datasets import _load, load_dataset
from evalapp.errors import SpecError


def decl(path, **overrides):
    base = {
        "path": path,
        "transcript_field": "text",
        "reference_field": "ref",
        "entry_id_field": "id",
    }
    base.update(overrides)
    return base


def text_of(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def collect(path, d):
    return _load("ds", path, text_of(path), d)


def fail_first(path, d):
    with pytest.raises(SpecError) as excinfo:
        load_dataset("ds", d)
    return str(excinfo.value)


# --- CSV: duplicate column names ---


def test_csv_duplicate_column_reported_once_per_name(tmp_path):
    path = harness.write_text(str(tmp_path / "ds.csv"), "a,a,a\nx,y,z\n")
    d = decl(path, transcript_field="a", reference_field=None, entry_id_field=None)
    entries, id_map, errors = collect(path, d)
    assert errors == [f"dataset 'ds': duplicate column name 'a' in {path}"]
    assert entries == [{"index": 0, "transcript": "z"}]
    assert id_map == {}


def test_csv_duplicate_column_is_first_error_before_field_absence(tmp_path):
    path = harness.write_csv(
        str(tmp_path / "ds.csv"), ["text", "text", "id"], [["a", "b", "1"]]
    )
    d = decl(path)
    entries, id_map, errors = collect(path, d)
    assert errors == [
        f"dataset 'ds': duplicate column name 'text' in {path}",
        f"dataset 'ds': field 'ref' not found in {path} (columns: text, text, id)",
    ]
    assert entries == [{"index": 0, "transcript": "b", "entry_id": "1"}]
    assert id_map == {"1": 0}
    assert fail_first(path, d) == (
        f"dataset 'ds': duplicate column name 'text' in {path}"
    )


# --- CSV: R1 value checks ---


def test_csv_empty_transcript(tmp_path):
    path = harness.write_csv(
        str(tmp_path / "ds.csv"), ["text", "ref", "id"], [["", "r2", "b"]]
    )
    d = decl(path)
    entries, id_map, errors = collect(path, d)
    assert errors == [f"dataset 'ds': empty transcript in {path} (line 2)"]
    assert entries == [{"index": 0, "transcript": "", "entry_id": "b"}]
    assert id_map == {"b": 0}
    assert fail_first(path, d) == f"dataset 'ds': empty transcript in {path} (line 2)"


def test_csv_empty_entry_id(tmp_path):
    path = harness.write_csv(
        str(tmp_path / "ds.csv"), ["text", "ref", "id"], [["ok", "r1", ""]]
    )
    d = decl(path)
    entries, id_map, errors = collect(path, d)
    assert errors == [f"dataset 'ds': empty entry id in {path} (line 2)"]
    assert entries == [{"index": 0, "transcript": "ok", "entry_id": ""}]
    assert id_map == {"": 0}
    assert fail_first(path, d) == f"dataset 'ds': empty entry id in {path} (line 2)"


def test_csv_duplicate_entry_id_names_later_occurrence(tmp_path):
    path = harness.write_csv(
        str(tmp_path / "ds.csv"),
        ["text", "ref", "id"],
        [["ok", "r1", "a"], ["ok2", "r2", "a"]],
    )
    d = decl(path)
    entries, id_map, errors = collect(path, d)
    assert errors == [f"dataset 'ds': duplicate entry id 'a' in {path} (line 3)"]
    assert entries == [
        {"index": 0, "transcript": "ok", "entry_id": "a"},
        {"index": 1, "transcript": "ok2", "entry_id": "a"},
    ]
    assert id_map == {"a": 1}
    assert fail_first(path, d) == (
        f"dataset 'ds': duplicate entry id 'a' in {path} (line 3)"
    )


def test_csv_empty_reference(tmp_path):
    path = harness.write_csv(
        str(tmp_path / "ds.csv"), ["text", "ref", "id"], [["ok", "", "a"]]
    )
    d = decl(path)
    entries, id_map, errors = collect(path, d)
    assert errors == [f"dataset 'ds': empty reference in {path} (line 2)"]
    assert entries == [{"index": 0, "transcript": "ok", "entry_id": "a"}]
    assert id_map == {"a": 0}
    assert fail_first(path, d) == f"dataset 'ds': empty reference in {path} (line 2)"


def test_csv_malformed_rows_precede_value_checks(tmp_path):
    path = harness.write_csv(
        str(tmp_path / "ds.csv"),
        ["text", "ref", "id"],
        [["", "r2", "b"], ["only-two"]],
    )
    d = decl(path)
    entries, id_map, errors = collect(path, d)
    assert errors == [
        f"dataset 'ds': malformed line 3 in {path}: expected 3 columns, got 1",
        f"dataset 'ds': empty transcript in {path} (line 2)",
    ]
    assert entries == [{"index": 0, "transcript": "", "entry_id": "b"}]
    assert fail_first(path, d) == (
        f"dataset 'ds': malformed line 3 in {path}: expected 3 columns, got 1"
    )


# --- CSV: collect error order and no-entries ---


def test_csv_collect_full_error_order(tmp_path):
    path = harness.write_text(
        str(tmp_path / "ds.csv"),
        "text,ref,id\nok,r1,a\n,r2,b\nok,,\nx,r5,a\nonly-two\na,b,c,d\n",
    )
    d = decl(path)
    entries, id_map, errors = collect(path, d)
    assert errors == [
        f"dataset 'ds': malformed line 6 in {path}: expected 3 columns, got 1",
        f"dataset 'ds': malformed line 7 in {path}: expected 3 columns, got 4",
        f"dataset 'ds': empty transcript in {path} (line 3)",
        f"dataset 'ds': empty entry id in {path} (line 4)",
        f"dataset 'ds': empty reference in {path} (line 4)",
        f"dataset 'ds': duplicate entry id 'a' in {path} (line 5)",
    ]
    assert len(entries) == 4
    assert id_map == {"a": 3, "b": 1, "": 2}


def test_csv_all_malformed_appends_no_entries(tmp_path):
    path = harness.write_csv(
        str(tmp_path / "ds.csv"), ["text", "ref", "id"], [["only-two"]]
    )
    d = decl(path)
    entries, id_map, errors = collect(path, d)
    assert entries == []
    assert id_map == {}
    assert errors == [
        f"dataset 'ds': malformed line 2 in {path}: expected 3 columns, got 1",
        f"dataset 'ds': no entries in {path}",
    ]


def test_csv_empty_file_is_no_entries_only(tmp_path):
    path = harness.write_text(str(tmp_path / "ds.csv"), "")
    d = decl(path)
    entries, id_map, errors = collect(path, d)
    assert (entries, id_map) == ([], {})
    assert errors == [f"dataset 'ds': no entries in {path}"]
    assert fail_first(path, d) == f"dataset 'ds': no entries in {path}"


# --- JSONL: collect mode ---


def test_jsonl_collect_full_error_order(tmp_path):
    path = harness.write_text(
        str(tmp_path / "ds.jsonl"),
        '{"text": "ok", "ref": "r", "id": "a"}\n'
        "not json\n"
        '{"ref": "r", "id": "b"}\n'
        '{"text": "", "ref": "r", "id": "a"}\n'
        '{"text": "ok", "ref": "", "id": "c"}\n',
    )
    d = decl(path)
    entries, id_map, errors = collect(path, d)
    assert len(errors) == 5
    assert errors[0].startswith(
        f"dataset 'ds': malformed line 2 in {path}: not a JSON object"
    )
    assert errors[1:] == [
        f"dataset 'ds': field 'text' not found in {path} (line 3)",
        f"dataset 'ds': empty transcript in {path} (line 4)",
        f"dataset 'ds': duplicate entry id 'a' in {path} (line 4)",
        f"dataset 'ds': empty reference in {path} (line 5)",
    ]
    assert entries == [
        {"index": 0, "transcript": "ok", "entry_id": "a"},
        {"index": 1, "entry_id": "b"},
        {"index": 2, "transcript": "", "entry_id": "a"},
        {"index": 3, "transcript": "ok", "entry_id": "c"},
    ]
    assert id_map == {"a": 2, "b": 1, "c": 3}


def test_jsonl_null_transcript(tmp_path):
    path = harness.write_jsonl(
        str(tmp_path / "ds.jsonl"), [{"text": None, "ref": "r", "id": "a"}]
    )
    d = decl(path)
    entries, id_map, errors = collect(path, d)
    assert errors == [f"dataset 'ds': empty transcript in {path} (line 1)"]
    assert fail_first(path, d) == f"dataset 'ds': empty transcript in {path} (line 1)"


def test_jsonl_empty_entry_id(tmp_path):
    path = harness.write_jsonl(
        str(tmp_path / "ds.jsonl"), [{"text": "ok", "ref": "r", "id": ""}]
    )
    d = decl(path)
    assert fail_first(path, d) == f"dataset 'ds': empty entry id in {path} (line 1)"


def test_jsonl_duplicate_entry_id(tmp_path):
    path = harness.write_jsonl(
        str(tmp_path / "ds.jsonl"),
        [
            {"text": "ok", "ref": "r", "id": "a"},
            {"text": "ok2", "ref": "r2", "id": "a"},
        ],
    )
    d = decl(path)
    assert fail_first(path, d) == (
        f"dataset 'ds': duplicate entry id 'a' in {path} (line 2)"
    )


def test_jsonl_null_reference(tmp_path):
    path = harness.write_jsonl(
        str(tmp_path / "ds.jsonl"), [{"text": "ok", "ref": None, "id": "a"}]
    )
    d = decl(path)
    assert fail_first(path, d) == f"dataset 'ds': empty reference in {path} (line 1)"


def test_jsonl_absent_field_skips_only_its_value_check(tmp_path):
    path = harness.write_text(
        str(tmp_path / "ds.jsonl"),
        '{"text": "ok", "id": "a"}\n'
        '{"id": "b"}\n',
    )
    d = decl(path)
    entries, id_map, errors = collect(path, d)
    assert errors == [
        f"dataset 'ds': field 'ref' not found in {path} (line 1)",
        f"dataset 'ds': field 'text' not found in {path} (line 2)",
        f"dataset 'ds': field 'ref' not found in {path} (line 2)",
    ]
    assert entries == [
        {"index": 0, "transcript": "ok", "entry_id": "a"},
        {"index": 1, "entry_id": "b"},
    ]
    assert id_map == {"a": 0, "b": 1}


# --- negative pins ---


def test_single_space_transcript_is_not_empty(tmp_path):
    path = harness.write_text(str(tmp_path / "ds.csv"), "text,ref\n ,r\n")
    d = {"path": path, "transcript_field": "text", "reference_field": "ref"}
    entries, id_map, errors = collect(path, d)
    assert errors == []
    assert entries == [{"index": 0, "transcript": " "}]
    assert id_map == {}


def test_no_entry_id_errors_without_entry_id_field(tmp_path):
    path = harness.write_csv(
        str(tmp_path / "ds.csv"),
        ["text", "ref"],
        [["ok", ""], ["ok2", ""]],
    )
    d = {"path": path, "transcript_field": "text", "reference_field": "ref"}
    entries, id_map, errors = collect(path, d)
    assert errors == [
        f"dataset 'ds': empty reference in {path} (line 2)",
        f"dataset 'ds': empty reference in {path} (line 3)",
    ]
    assert entries == [
        {"index": 0, "transcript": "ok"},
        {"index": 1, "transcript": "ok2"},
    ]
    assert id_map == {}


def test_two_empty_ids_give_two_errors_without_duplicate(tmp_path):
    path = harness.write_csv(
        str(tmp_path / "ds.csv"),
        ["text", "ref", "id"],
        [["ok", "r1", ""], ["ok2", "r2", ""]],
    )
    d = decl(path)
    entries, id_map, errors = collect(path, d)
    assert errors == [
        f"dataset 'ds': empty entry id in {path} (line 2)",
        f"dataset 'ds': empty entry id in {path} (line 3)",
    ]
    assert len(entries) == 2


def test_clean_load_shapes_entries_and_id_map(tmp_path):
    path = harness.write_csv(
        str(tmp_path / "ds.csv"),
        ["text", "ref", "id"],
        [["t1", "r1", "a"], ["t2", "r2", "b"]],
    )
    dataset = load_dataset("ds", decl(path))
    assert dataset.entries == [
        {"index": 0, "transcript": "t1", "entry_id": "a"},
        {"index": 1, "transcript": "t2", "entry_id": "b"},
    ]
    assert dataset.id_map == {"a": 0, "b": 1}

    jsonl_path = harness.write_jsonl(
        str(tmp_path / "ds2.jsonl"),
        [
            {"text": "t1", "ref": "r1", "id": "a"},
            {"text": "t2", "ref": "r2", "id": "b"},
        ],
    )
    dataset = load_dataset("ds", decl(jsonl_path))
    assert dataset.entries == [
        {"index": 0, "transcript": "t1", "entry_id": "a"},
        {"index": 1, "transcript": "t2", "entry_id": "b"},
    ]
    assert dataset.id_map == {"a": 0, "b": 1}


# --- CLI end-to-end ---


def test_cli_empty_transcript_is_exit_2_naming_file_and_line(tmp_path):
    path = str(tmp_path / "ds.csv")
    harness.write_csv(path, ["text", "ref", "id"], [["", "r1", "b"]])
    harness.write_config(
        str(tmp_path / "config.json"),
        {
            "ds": {
                "path": path,
                "transcript_field": "text",
                "reference_field": "ref",
                "entry_id_field": "id",
            }
        },
        store="store.db",
    )
    result = harness.run_cli(["generate"], cwd=tmp_path)
    result.assert_exit(2)
    assert result.with_prefix("error:") == [
        f"error: dataset 'ds': empty transcript in {path} (line 2)"
    ]
