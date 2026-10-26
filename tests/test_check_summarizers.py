import harness


def _write(tmp_path, extra):
    return harness.write_config(
        str(tmp_path / "config.json"),
        {},
        store="store.db",
        extra_top_level=extra,
    )


def test_summarizer_unresolvable_model(tmp_path):
    _write(
        tmp_path,
        {
            "summarizers": {"s": {"model": "nope", "prompt_template": "t"}},
            "prompt_templates": {"t": {"path": "x.json"}},
        },
    )
    result = harness.run_cli(["check"], cwd=tmp_path)
    result.assert_exit(2)
    assert result.lines == harness.STANDARD_DISCOVERY + [
        "error: summarizer 's': component 'model' not resolvable "
        "(set it directly or via a base chain)",
    ]


def test_summarizer_stray_path_rejected(tmp_path):
    _write(
        tmp_path,
        {
            "models": {"m": {"path": "m.gguf"}},
            "prompt_templates": {"t": {"path": "x.json"}},
            "summarizers": {
                "s": {"model": "m", "prompt_template": "t", "path": "nope.gguf"},
            },
        },
    )
    result = harness.run_cli(["check"], cwd=tmp_path)
    result.assert_exit(2)
    assert result.lines == harness.STANDARD_DISCOVERY + [
        "error: summarizer 's': field 'path' is not allowed — "
        "the model path is fixed by the model entry",
    ]


def test_summarizer_base_must_appear_earlier(tmp_path):
    _write(
        tmp_path,
        {
            "models": {"m": {"path": "m.gguf"}},
            "prompt_templates": {"t": {"path": "x.json"}},
            "summarizers": {
                "child": {"model": "m", "prompt_template": "t", "base": "parent"},
                "parent": {"model": "m", "prompt_template": "t"},
            },
        },
    )
    result = harness.run_cli(["check"], cwd=tmp_path)
    result.assert_exit(2)
    assert result.lines == harness.STANDARD_DISCOVERY + [
        "error: summarizer 'child': base 'parent' must appear earlier in the file",
    ]
