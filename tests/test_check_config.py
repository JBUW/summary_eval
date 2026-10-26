import harness


def test_unknown_metric_lists_registered(tmp_path):
    harness.write_config(
        str(tmp_path / "config.json"),
        {},
        store="store.db",
        extra_top_level={"default_metrics": ["rougeX"]},
    )
    result = harness.run_cli(["check"], cwd=tmp_path)
    result.assert_exit(2)
    expected = (
        f"unknown metric 'rougeX' (registered: {', '.join(harness.ALL_METRICS)})"
    )
    assert result.lines == harness.discovery_lines([], harness.ALL_METRICS, [], []) + [
        f"error: {expected}",
    ]
    assert not result.with_prefix("plan(check):")


def test_unknown_judge_lists_configured_none(tmp_path):
    harness.write_config(
        str(tmp_path / "config.json"),
        {},
        store="store.db",
        extra_top_level={"default_judges": ["ghost"]},
    )
    result = harness.run_cli(["check"], cwd=tmp_path)
    result.assert_exit(2)
    assert result.lines == harness.discovery_lines(harness.ALL_METRICS, [], [], []) + [
        "error: unknown judge 'ghost' (configured: (none))",
    ]
    assert not result.with_prefix("plan(check):")


def test_metric_and_judge_errors_together_metric_first(tmp_path):
    harness.write_config(
        str(tmp_path / "config.json"),
        {},
        store="store.db",
        extra_top_level={
            "default_metrics": ["rougeX"],
            "default_judges": ["ghost"],
        },
    )
    result = harness.run_cli(["check"], cwd=tmp_path)
    result.assert_exit(2)
    expected = (
        f"error: unknown metric 'rougeX' "
        f"(registered: {', '.join(harness.ALL_METRICS)})",
        "error: unknown judge 'ghost' (configured: (none))",
    )
    assert result.lines == (
        harness.discovery_lines([], harness.ALL_METRICS, [], []) + list(expected)
    )
    assert not result.with_prefix("plan(check):")


def test_duplicate_name_in_models(tmp_path):
    harness.write_text(
        str(tmp_path / "config.json"),
        '{"models": {"m": {"path": "a"}, "m": {"path": "b"}}}\n',
    )
    result = harness.run_cli(["check"], cwd=tmp_path)
    result.assert_exit(2)
    assert result.lines == harness.STANDARD_DISCOVERY + [
        "error: duplicate name 'm' in models",
    ]
