"""Ticket 10 — report parser: the docs' flag set is accepted (report has no
generate stage, so no --server-*), and the pre-config guards (--csv/--json
mutex, negative --blind-sample) fire before the config is loaded."""
import harness  # noqa: F401  (puts the repo root on sys.path)


def test_full_flag_set_accepted(tmp_path):
    harness.standard_workspace(tmp_path)
    result = harness.run_cli(
        [
            "report",
            "--select", "named", "#0-2",
            "--summarizer", "s",
            "--model", "m",
            "--prompt-template", "t",
            "--metrics", "faithfulness",
            "--judges", "j",
            "--by", "dataset",
            "--blind-sample", "2",
            "--csv", "out.csv",
        ],
        cwd=tmp_path,
    )
    result.assert_exit(2)
    # Got past argparse (no 'unrecognized arguments'): the failure is a
    # later-stage scorer resolution against an empty config.
    assert result.lines == ["error: unknown judge 'j' (none configured)"]


def test_server_flags_rejected(tmp_path):
    harness.standard_workspace(tmp_path)
    result = harness.run_cli(["report", "--server-port", "1"], cwd=tmp_path)
    result.assert_exit(2)
    errors = result.with_prefix("error:")
    assert len(errors) == 1
    assert "unrecognized arguments" in errors[0]
    assert result.with_prefix("plan(") == []


def test_json_and_csv_mutually_exclusive(tmp_path):
    # Pre-config: no workspace needed at all.
    result = harness.run_cli(["report", "--json", "--csv", "out.csv"])
    result.assert_exit(2)
    assert result.lines == ["error: --csv and --json are mutually exclusive"]


def test_negative_blind_sample_rejected(tmp_path):
    result = harness.run_cli(["report", "--blind-sample", "-1"])
    result.assert_exit(2)
    assert result.lines == [
        "error: invalid --blind-sample -1 (must be >= 0)"
    ]


def test_blind_sample_requires_int(tmp_path):
    result = harness.run_cli(["report", "--blind-sample", "abc"])
    result.assert_exit(2)
    assert len(result.with_prefix("error:")) == 1


def test_by_only_dataset(tmp_path):
    result = harness.run_cli(["report", "--by", "foo"])
    result.assert_exit(2)
    assert len(result.with_prefix("error:")) == 1


def test_metrics_with_no_metrics_rejected(tmp_path):
    harness.standard_workspace(tmp_path)
    result = harness.run_cli(
        ["report", "--metrics", "faithfulness", "--no-metrics"], cwd=tmp_path
    )
    result.assert_exit(2)
    assert result.lines == ["error: --no-metrics is mutually exclusive with --metrics"]


def test_bare_judges_with_no_judges_rejected(tmp_path):
    harness.standard_workspace(tmp_path)
    result = harness.run_cli(["report", "--judges", "--no-judges"], cwd=tmp_path)
    result.assert_exit(2)
    assert result.lines == ["error: --no-judges is mutually exclusive with --judges"]
