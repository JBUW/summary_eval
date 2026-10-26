import json

import harness
from evalapp import check_static

KEY = "EVALAPP_TEST_JUDGE_KEY"


def _workspace_with_judge(tmp_path):
    harness.standard_workspace(tmp_path)
    path = str(tmp_path / "config.json")
    with open(path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    config["judges"] = {"j": {"requires_reference": False, "api_key_env": KEY}}
    harness.write_text(path, json.dumps(config, indent=2) + "\n")
    harness.add_server_section(path)


def _discovery():
    return harness.discovery_lines(harness.ALL_METRICS, [], ["j"], [])


def test_judge_requires_reference_required(tmp_path):
    harness.write_config(
        str(tmp_path / "config.json"),
        {},
        store="store.db",
        extra_top_level={"judges": {"j": {}}},
    )
    result = harness.run_cli(["check"], cwd=tmp_path)
    result.assert_exit(2)
    assert result.lines == harness.discovery_lines(harness.ALL_METRICS, [], ["j"], []) + [
        "error: judge 'j': requires_reference is required and must be a boolean",
    ]


def test_judge_reference_placeholder_missing(tmp_path):
    harness.write_config(
        str(tmp_path / "config.json"),
        {},
        store="store.db",
        extra_top_level={
            "judges": {
                "j": {
                    "requires_reference": True,
                    "user_template": "{transcript} {summary}",
                }
            }
        },
    )
    result = harness.run_cli(["check"], cwd=tmp_path)
    result.assert_exit(2)
    assert result.lines == _discovery() + [
        "error: judge 'j': requires_reference is true but "
        "placeholder '{reference}' is missing",
    ]


def test_probe_judges_unset_env(tmp_path, monkeypatch):
    _workspace_with_judge(tmp_path)
    monkeypatch.delenv(KEY, raising=False)
    monkeypatch.setattr(check_static, "port_is_free", lambda port: True)
    result = harness.run_cli(["check", "--probe-judges"], cwd=tmp_path)
    result.assert_exit(2)
    assert result.lines == _discovery() + [
        "plan(check): 2 datasets",
        f"error: judge 'j': environment variable '{KEY}' is unset or empty",
    ]


def test_probe_judges_empty_env(tmp_path, monkeypatch):
    _workspace_with_judge(tmp_path)
    monkeypatch.setenv(KEY, "")
    monkeypatch.setattr(check_static, "port_is_free", lambda port: True)
    result = harness.run_cli(["check", "--probe-judges"], cwd=tmp_path)
    result.assert_exit(2)
    assert result.lines == _discovery() + [
        "plan(check): 2 datasets",
        f"error: judge 'j': environment variable '{KEY}' is unset or empty",
    ]


def test_judge_env_not_checked_without_probe(tmp_path, monkeypatch):
    _workspace_with_judge(tmp_path)
    monkeypatch.delenv(KEY, raising=False)
    monkeypatch.setattr(check_static, "port_is_free", lambda port: True)
    result = harness.run_cli(["check"], cwd=tmp_path)
    result.assert_exit(0)
    assert result.lines == _discovery() + [
        "plan(check): 2 datasets",
        "note: no store at store.db",
    ]
