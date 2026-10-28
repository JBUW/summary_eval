"""Ticket 09 — sweep pre-effect: forbidden flags rejected pre-config, widen flags accepted."""
import harness  # noqa: F401  (puts the repo root on sys.path)

FORBIDDEN = (
    "error: 'sweep' takes no selection or scorer flags (it is exhaustive); "
    "use 'score --generate' to narrow"
)


def _assert_forbidden(tmp_path, *argv):
    result = harness.run_cli(["sweep", *argv], cwd=tmp_path)
    result.assert_exit(2)
    assert result.lines == [FORBIDDEN]


def test_select_bare_rejected(tmp_path):
    _assert_forbidden(tmp_path, "--select")


def test_select_with_tokens_rejected(tmp_path):
    _assert_forbidden(tmp_path, "--select", "named", "*")


def test_summarizer_bare_rejected(tmp_path):
    _assert_forbidden(tmp_path, "--summarizer")


def test_summarizer_with_tokens_rejected(tmp_path):
    _assert_forbidden(tmp_path, "--summarizer", "s")


def test_model_bare_rejected(tmp_path):
    _assert_forbidden(tmp_path, "--model")


def test_model_with_tokens_rejected(tmp_path):
    _assert_forbidden(tmp_path, "--model", "m")


def test_prompt_template_bare_rejected(tmp_path):
    _assert_forbidden(tmp_path, "--prompt-template")


def test_prompt_template_with_tokens_rejected(tmp_path):
    _assert_forbidden(tmp_path, "--prompt-template", "t")


def test_metrics_bare_rejected(tmp_path):
    _assert_forbidden(tmp_path, "--metrics")


def test_metrics_with_tokens_rejected(tmp_path):
    _assert_forbidden(tmp_path, "--metrics", "faithfulness")


def test_judges_bare_rejected(tmp_path):
    _assert_forbidden(tmp_path, "--judges")


def test_judges_with_tokens_rejected(tmp_path):
    _assert_forbidden(tmp_path, "--judges", "j")


def test_generate_rejected(tmp_path):
    _assert_forbidden(tmp_path, "--generate")


def test_widen_flags_accepted(tmp_path):
    harness.standard_workspace(tmp_path)
    harness.add_server_section(str(tmp_path / "config.json"))
    for argv in (
        ["sweep", "--all-metrics"],
        ["sweep", "--all-judges"],
        ["sweep", "--all"],
        ["sweep", "--all", "--all-metrics", "--all-judges"],
    ):
        result = harness.run_cli(argv, cwd=tmp_path)
        assert not any(FORBIDDEN in line for line in result.lines), (argv, result.stdout)
        assert result.exit_code != 2, (argv, result.stdout)


def test_narrowing_flags_rejected_by_parser(tmp_path):
    for flag in ("--no-metrics", "--no-judges"):
        result = harness.run_cli(["sweep", flag], cwd=tmp_path)
        result.assert_exit(2)
        assert not any(FORBIDDEN in line for line in result.lines), result.stdout
