import pytest

import harness


@pytest.mark.parametrize(
    "command", ["check", "generate", "score", "sweep", "report", "clear"]
)
def test_all_six_subcommands_run(tmp_path, command):
    harness.standard_workspace(tmp_path)
    result = harness.run_cli([command], cwd=tmp_path)
    result.assert_exit(0)
    assert not result.with_prefix("error:")


def test_unknown_subcommand(tmp_path):
    harness.standard_workspace(tmp_path)
    result = harness.run_cli(["nosuch"], cwd=tmp_path)
    result.assert_exit(2)
    assert len(result.with_prefix("error:")) == 1


def test_no_subcommand(tmp_path):
    harness.standard_workspace(tmp_path)
    result = harness.run_cli([], cwd=tmp_path)
    result.assert_exit(2)
    assert result.with_prefix("error:")


@pytest.mark.parametrize(
    "argv",
    [
        ["check", "--bogus"],
        ["generate", "--metrics", "x"],
        ["sweep", "--select", "named", "*"],
        ["clear", "--yes"],
        ["report", "--json"],
    ],
)
def test_unknown_flags(tmp_path, argv):
    harness.standard_workspace(tmp_path)
    result = harness.run_cli(argv, cwd=tmp_path)
    result.assert_exit(2)
    assert len(result.with_prefix("error:")) == 1
