import json

import harness


def _rewrite(tmp_path, mutate):
    path = str(tmp_path / "config.json")
    with open(path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    mutate(config)
    harness.write_text(path, json.dumps(config, indent=2) + "\n")


def test_gold_discovery_and_store_note(tmp_path):
    harness.standard_workspace(tmp_path)
    harness.add_server_section(str(tmp_path / "config.json"))
    result = harness.run_cli(["check"], cwd=tmp_path)
    result.assert_exit(0)
    assert result.lines == harness.STANDARD_DISCOVERY + [
        "plan(check): 2 datasets",
        "note: no store at store.db",
    ]


def test_empty_default_metrics_lists_all_registered(tmp_path):
    harness.standard_workspace(tmp_path)
    harness.add_server_section(str(tmp_path / "config.json"))
    _rewrite(tmp_path, lambda config: config.update({"default_metrics": []}))
    result = harness.run_cli(["check"], cwd=tmp_path)
    result.assert_exit(0)
    assert result.lines == (
        harness.discovery_lines([], harness.ALL_METRICS, [], [])
        + ["plan(check): 2 datasets", "note: no store at store.db"]
    )


def test_default_metrics_dedupe_skip_nonstr_and_unknown(tmp_path):
    harness.standard_workspace(tmp_path)
    harness.add_server_section(str(tmp_path / "config.json"))
    _rewrite(
        tmp_path,
        lambda config: config.update(
            {"default_metrics": ["faithfulness", "faithfulness", "rougeX", 42]}
        ),
    )
    result = harness.run_cli(["check"], cwd=tmp_path)
    result.assert_exit(2)
    discovery = harness.discovery_lines(
        ["faithfulness"],
        [
            "conciseness_length_proxy",
            "internal_consistency",
            "key_claim_completeness",
            "structural_instruction_check",
        ],
        [],
        [],
    )
    assert result.lines == discovery + [
        "error: default_metrics: entries must be strings",
        f"error: unknown metric 'rougeX' (registered: {', '.join(harness.ALL_METRICS)})",
    ]
    assert not result.with_prefix("plan(check):")


def test_configured_judges_grouped_when_defaults_absent(tmp_path):
    harness.standard_workspace(tmp_path)
    harness.add_server_section(str(tmp_path / "config.json"))
    _rewrite(
        tmp_path,
        lambda config: config.update(
            {
                "judges": {
                    "j1": {"requires_reference": False},
                    "j2": {"requires_reference": False},
                }
            }
        ),
    )
    result = harness.run_cli(["check"], cwd=tmp_path)
    result.assert_exit(0)
    assert result.lines == (
        harness.discovery_lines(harness.ALL_METRICS, [], ["j1", "j2"], [])
        + ["plan(check): 2 datasets", "note: no store at store.db"]
    )
