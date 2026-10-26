import harness
from evalapp import check_static
from evalapp.errors import SpecError


def test_no_server_section_no_fallback(tmp_path):
    harness.standard_workspace(tmp_path)
    result = harness.run_cli(["check"], cwd=tmp_path)
    result.assert_exit(2)
    assert result.lines == harness.STANDARD_DISCOVERY + [
        "plan(check): 2 datasets",
        "error: no server section in config (no fallback launch)",
    ]


def test_server_command_missing(tmp_path):
    harness.standard_workspace(tmp_path)
    result = harness.run_cli(["check", "--server-command", "/nope"], cwd=tmp_path)
    result.assert_exit(2)
    assert result.lines == harness.STANDARD_DISCOVERY + [
        "plan(check): 2 datasets",
        "error: server: command not found: /nope",
    ]


def test_server_command_override_succeeds(tmp_path):
    harness.standard_workspace(tmp_path)
    result = harness.run_cli(["check", "--server-command", "/bin/true"], cwd=tmp_path)
    result.assert_exit(0)
    assert result.lines == harness.STANDARD_DISCOVERY + [
        "plan(check): 2 datasets",
        "note: no store at store.db",
    ]


def test_server_port_override_wins_over_config(tmp_path, monkeypatch):
    harness.standard_workspace(tmp_path)
    harness.add_server_section(str(tmp_path / "config.json"), port=8080)
    seen = []

    def fake_port_is_free(port):
        seen.append(port)
        raise SpecError(
            "port 8081 already bound "
            "(a previous model server may still be running)"
        )

    monkeypatch.setattr(check_static, "port_is_free", fake_port_is_free)
    result = harness.run_cli(["check", "--server-port", "8081"], cwd=tmp_path)
    result.assert_exit(2)
    assert seen == [8081]
    assert result.lines == harness.STANDARD_DISCOVERY + [
        "plan(check): 2 datasets",
        "error: port 8081 already bound "
        "(a previous model server may still be running)",
    ]


def test_store_override_path(tmp_path):
    harness.standard_workspace(tmp_path)
    harness.add_server_section(str(tmp_path / "config.json"))
    result = harness.run_cli(["check", "--store", "elsewhere/store.db"], cwd=tmp_path)
    result.assert_exit(0)
    assert "note: no store at elsewhere/store.db" in result.lines
    assert not (tmp_path / "store.db").exists()
