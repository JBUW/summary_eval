import pytest

import hashlib

import harness


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def test_default_config_name(tmp_path):
    harness.standard_workspace(tmp_path)
    result = harness.run_cli(["check"], cwd=tmp_path)
    result.assert_exit(2)
    assert "plan(check): 2 datasets" in result.lines


def test_explicit_config_flag(tmp_path):
    harness.standard_workspace(tmp_path, config_name="other.json")
    result = harness.run_cli(["check", "--config", "other.json"], cwd=tmp_path)
    result.assert_exit(2)
    assert "plan(check): 2 datasets" in result.lines


def test_missing_default_config(tmp_path):
    result = harness.run_cli(["check"], cwd=tmp_path)
    result.assert_exit(2)
    assert result.lines == [
        "error: config file not found: config.json (pass --config PATH to use another)"
    ]


def test_missing_explicit_config(tmp_path):
    result = harness.run_cli(["check", "--config", "nope.json"], cwd=tmp_path)
    result.assert_exit(2)
    assert result.lines == ["error: config file not found: nope.json"]


def test_invalid_json_config(tmp_path):
    harness.write_text(str(tmp_path / "config.json"), "{not json")
    result = harness.run_cli(["check"], cwd=tmp_path)
    result.assert_exit(2)
    assert len(result.with_prefix("error:")) == 1


def test_store_override(tmp_path):
    harness.standard_workspace(tmp_path)
    harness.add_server_section(str(tmp_path / "config.json"))
    result = harness.run_cli(
        ["check", "--store", "elsewhere/store.db"], cwd=tmp_path
    )
    result.assert_exit(0)
    assert "note: no store at elsewhere/store.db" in result.lines


@pytest.mark.parametrize(
    ("command", "expected"),
    [("check", 2), ("generate", 0), ("clear", 0)],
)
def test_config_file_never_written(tmp_path, command, expected):
    harness.standard_workspace(tmp_path)
    config_path = str(tmp_path / "config.json")
    before = sha256(config_path)
    result = harness.run_cli([command, "--store", "elsewhere/store.db"], cwd=tmp_path)
    result.assert_exit(expected)
    assert sha256(config_path) == before
