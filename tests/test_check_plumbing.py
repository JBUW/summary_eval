import socket
import sqlite3

import pytest

import harness
from evalapp import cli
from evalapp import store
from evalapp.errors import SpecError


def _tables(path):
    db = sqlite3.connect(path)
    try:
        return {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master"
                " WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
    finally:
        db.close()


class _BoundSocket:
    def bind(self, address):
        raise OSError("address already in use")

    def close(self):
        pass


def test_port_is_free_bound_raises(monkeypatch):
    monkeypatch.setattr(socket, "socket", lambda *a, **k: _BoundSocket())
    with pytest.raises(SpecError) as excinfo:
        cli.port_is_free(8081)
    assert str(excinfo.value) == (
        "port 8081 already bound "
        "(a previous model server may still be running)"
    )


def test_port_is_free_free_port_passes():
    assert cli.port_is_free(18081) is True


def test_port_is_free_creation_failure_is_free(monkeypatch):
    def boom(*args, **kwargs):
        raise PermissionError("sandboxed")

    monkeypatch.setattr(socket, "socket", boom)
    assert cli.port_is_free(8081) is True


@pytest.mark.parametrize(
    "argv",
    [
        ["score", "--server-command", "/nope"],
        ["score", "--server-args", "{}"],
        ["score", "--server-env", "{}"],
        ["score", "--server-port", "8081"],
        ["score", "--server-startup-timeout", "1.5"],
    ],
)
def test_score_server_flags_require_generate_before_config_load(tmp_path, argv):
    result = harness.run_cli(argv, cwd=tmp_path)  # no config in cwd
    result.assert_exit(2)
    assert result.lines == ["error: --server-* flags require --generate"]


def test_score_gate_before_json_parse(tmp_path):
    harness.standard_workspace(tmp_path)
    result = harness.run_cli(["score", "--server-args", "{bad"], cwd=tmp_path)
    result.assert_exit(2)
    assert result.lines == ["error: --server-* flags require --generate"]


def test_check_absent_store_not_created(tmp_path):
    harness.standard_workspace(tmp_path)
    harness.add_server_section(str(tmp_path / "config.json"))
    result = harness.run_cli(["check"], cwd=tmp_path)
    result.assert_exit(0)
    assert "note: no store at store.db" in result.lines
    assert not (tmp_path / "store.db").exists()


def test_check_zero_table_store_is_valid_empty(tmp_path):
    harness.standard_workspace(tmp_path)
    db = sqlite3.connect(str(tmp_path / "store.db"))
    db.close()
    harness.add_server_section(str(tmp_path / "config.json"))
    result = harness.run_cli(["check"], cwd=tmp_path)
    result.assert_exit(0)
    assert not result.with_prefix("note: created empty store")
    assert _tables(str(tmp_path / "store.db")) == set()


def test_check_valid_store_passes(tmp_path):
    harness.standard_workspace(tmp_path)
    opened = store.Store(str(tmp_path / "store.db"))
    opened.close()
    harness.add_server_section(str(tmp_path / "config.json"))
    result = harness.run_cli(["check"], cwd=tmp_path)
    result.assert_exit(0)
    assert not result.with_prefix("error:")


def test_check_mismatch_store_errors(tmp_path):
    harness.standard_workspace(tmp_path)
    db = sqlite3.connect(str(tmp_path / "store.db"))
    db.execute("CREATE TABLE wrong_table (x TEXT)")
    db.commit()
    db.close()
    harness.add_server_section(str(tmp_path / "config.json"))
    result = harness.run_cli(["check"], cwd=tmp_path)
    result.assert_exit(2)
    expected = store._MISMATCH.format(path="store.db")
    assert result.lines == harness.STANDARD_DISCOVERY + [
        "plan(check): 2 datasets",
        f"error: {expected}",
    ]


def test_check_create_store_bootstraps(tmp_path):
    harness.standard_workspace(tmp_path)
    harness.add_server_section(str(tmp_path / "config.json"))
    result = harness.run_cli(["check", "--create-store"], cwd=tmp_path)
    result.assert_exit(0)
    assert "note: created empty store at store.db" in result.lines
    assert _tables(str(tmp_path / "store.db")) == set(store.TABLES)


def test_check_accepts_all_plumbing_flags(tmp_path):
    harness.standard_workspace(tmp_path)
    result = harness.run_cli(
        [
            "check",
            "--server-command", "/bin/true",
            "--server-args", "{}",
            "--server-env", "{}",
            "--server-port", "8081",
            "--server-startup-timeout", "1.5",
            "--probe-judges",
        ],
        cwd=tmp_path,
    )
    result.assert_exit(0)
    assert not (tmp_path / "store.db").exists()


@pytest.mark.parametrize("command", ["generate", "sweep"])
def test_generate_and_sweep_accept_server_flags(tmp_path, command):
    harness.standard_workspace(tmp_path)
    harness.add_server_section(str(tmp_path / "config.json"))
    result = harness.run_cli(
        [command, "--server-port", "8081", "--server-command", "/bin/true"],
        cwd=tmp_path,
    )
    result.assert_exit(0)


@pytest.mark.parametrize("command", ["report", "clear"])
def test_report_and_clear_reject_server_flags(tmp_path, command):
    harness.standard_workspace(tmp_path)
    result = harness.run_cli([command, "--server-port", "8081"], cwd=tmp_path)
    result.assert_exit(2)
    assert len(result.with_prefix("error:")) == 1


@pytest.mark.parametrize("flag", ["--server-args", "--server-env"])
def test_check_invalid_json(tmp_path, flag):
    harness.standard_workspace(tmp_path)
    result = harness.run_cli(["check", flag, "{bad"], cwd=tmp_path)
    result.assert_exit(2)
    expected = (
        f"error: invalid JSON for {flag}: "
        "Expecting property name enclosed in double quotes: "
        "line 1 column 2 (char 1)"
    )
    assert result.lines == [expected]


@pytest.mark.parametrize("flag", ["--server-args", "--server-env"])
def test_check_json_must_be_object(tmp_path, flag):
    harness.standard_workspace(tmp_path)
    result = harness.run_cli(["check", flag, "[]"], cwd=tmp_path)
    result.assert_exit(2)
    assert result.lines == [f"error: {flag} must be a JSON object"]
