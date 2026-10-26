import socket
import sqlite3

import pytest

import harness
from evalapp import store


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


def test_bound_config_port_detected(tmp_path):
    harness.standard_workspace(tmp_path)
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        pytest.skip("socket creation not permitted in this environment")
    try:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        harness.add_server_section(str(tmp_path / "config.json"), port=port)
        result = harness.run_cli(["check"], cwd=tmp_path)
    finally:
        probe.close()
    result.assert_exit(2)
    assert result.lines == harness.STANDARD_DISCOVERY + [
        "plan(check): 2 datasets",
        f"error: port {port} already bound "
        "(a previous model server may still be running)",
    ]


def test_free_config_port_passes(tmp_path):
    harness.standard_workspace(tmp_path)
    harness.add_server_section(str(tmp_path / "config.json"), port=18081)
    result = harness.run_cli(["check"], cwd=tmp_path)
    result.assert_exit(0)
    assert result.lines == harness.STANDARD_DISCOVERY + [
        "plan(check): 2 datasets",
        "note: no store at store.db",
    ]


def test_zero_table_store_emits_no_notes(tmp_path):
    harness.standard_workspace(tmp_path)
    db = sqlite3.connect(str(tmp_path / "store.db"))
    db.close()
    harness.add_server_section(str(tmp_path / "config.json"))
    result = harness.run_cli(["check"], cwd=tmp_path)
    result.assert_exit(0)
    assert result.lines == harness.STANDARD_DISCOVERY + ["plan(check): 2 datasets"]


def test_mismatch_store_schema_error(tmp_path):
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


def test_create_store_bootstraps_schema(tmp_path):
    harness.standard_workspace(tmp_path)
    harness.add_server_section(str(tmp_path / "config.json"))
    result = harness.run_cli(["check", "--create-store"], cwd=tmp_path)
    result.assert_exit(0)
    assert "note: created empty store at store.db" in result.lines
    assert _tables(str(tmp_path / "store.db")) == set(store.TABLES)
