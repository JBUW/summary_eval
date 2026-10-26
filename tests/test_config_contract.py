"""Strict configuration contract: validate_config collect mode (ticket 02a)."""
import pytest

import harness  # noqa: F401  (puts the repo root on sys.path)
from evalapp import config as config_mod
from evalapp import metrics
from evalapp.console import Console
from evalapp.errors import SpecError


def full_config():
    return {
        "store": "s.db",
        "server": {
            "command": "uvicorn",
            "args": {"--port": "8080"},
            "env": {},
            "port": 8080,
            "startup_timeout_s": 30,
        },
        "models": {
            "m1": {
                "path": "/models/m1",
                "model_args": {"flash-attn": True},
                "gen_params": {"temperature": 0.3, "max_tokens": 2048},
            }
        },
        "prompt_templates": {"t1": {"path": "/prompts/t1.txt"}},
        "summarizers": {"s1": {"model": "m1", "prompt_template": "t1"}},
        "datasets": {"d1": {"path": "d.jsonl", "transcript_field": "text"}},
        "judges": {
            "j1": {
                "endpoint": "https://api.example.com/v1",
                "model_name": "model-x",
                "api_key_env": "API_KEY",
                "requires_reference": True,
                "user_template": "T: {transcript} S: {summary} R: {reference}",
            }
        },
        "default_metrics": ["faithfulness"],
        "default_judges": ["j1"],
    }


def check(config, capsys=None):
    errors, resolved = config_mod.validate_config(config, Console())
    out = capsys.readouterr().out if capsys is not None else None
    return errors, resolved, out


def summarizer_config(models=None, templates=None, summarizers=None):
    return {
        "models": models
        if models is not None
        else {"m1": {"path": "/p", "model_args": {"a": 1}, "gen_params": {"g": 1}}},
        "prompt_templates": templates
        if templates is not None
        else {"t1": {"path": "/p"}},
        "summarizers": summarizers or {},
    }


def judge_config(user, flag=True, system=None):
    entry = {"user_template": user, "requires_reference": flag}
    if system is not None:
        entry["system_content"] = system
    return {"judges": {"j1": entry}}


def write_json(path, text):
    harness.write_text(path, text)
    return path


# --- full config and resolved shape ---


def test_full_config_is_valid(capsys):
    errors, resolved, out = check(full_config(), capsys)
    assert errors == []
    assert out == ""
    assert resolved["store"] == "s.db"
    assert resolved["server"] == full_config()["server"]
    assert resolved["models"]["m1"] == {
        "path": "/models/m1",
        "model_args": {"flash-attn": True},
        "gen_params": {"temperature": 0.3, "max_tokens": 2048},
    }
    assert resolved["prompt_templates"]["t1"] == "/prompts/t1.txt"
    assert resolved["summarizers"]["s1"] == {
        "model": "m1",
        "model_args": {"flash-attn": True},
        "prompt_template": "t1",
        "gen_params": {"temperature": 0.3, "max_tokens": 2048},
    }
    assert resolved["datasets"]["d1"] == {
        "path": "d.jsonl",
        "transcript_field": "text",
        "reference_field": None,
        "entry_id_field": None,
    }
    assert resolved["judges"]["j1"] == full_config()["judges"]["j1"]
    assert resolved["defaults"] == {"metrics": ["faithfulness"], "judges": ["j1"]}


# --- store ---


def test_store_absent_is_none():
    errors, resolved, _ = check({})
    assert errors == []
    assert resolved["store"] is None


@pytest.mark.parametrize("value", ["", 5, None, []])
def test_store_invalid(value):
    errors, resolved, _ = check({"store": value})
    assert errors == ["config 'store' must be a non-empty string"]
    assert resolved["store"] is None


def test_store_valid():
    errors, resolved, _ = check({"store": "s.db"})
    assert errors == []
    assert resolved["store"] == "s.db"


# --- server ---


def test_server_non_dict():
    errors, resolved, _ = check({"server": 5})
    assert errors == ["config 'server' must be an object"]
    assert resolved["server"] is None


def test_server_empty_requires_port_and_timeout():
    errors, resolved, _ = check({"server": {}})
    assert errors == [
        "server: field 'port' is required and must be a number",
        "server: field 'startup_timeout_s' is required and must be a number",
    ]
    assert resolved["server"] == {}


def test_server_bool_port_is_not_a_number():
    errors, _, _ = check({"server": {"port": True, "startup_timeout_s": 30}})
    assert errors == ["server: field 'port' is required and must be a number"]


def test_server_field_errors_in_fixed_order():
    errors, _, _ = check(
        {
            "server": {
                "command": 5,
                "args": [1],
                "env": "nope",
                "port": "8080",
            }
        }
    )
    assert errors == [
        "server: field 'command' must be a string",
        "server: field 'args' must be an object",
        "server: field 'env' must be an object",
        "server: field 'port' is required and must be a number",
        "server: field 'startup_timeout_s' is required and must be a number",
    ]


# --- section shapes and names ---


@pytest.mark.parametrize(
    "section",
    ["models", "prompt_templates", "summarizers", "datasets", "judges"],
)
def test_section_must_be_object(section, capsys):
    errors, _, out = check({section: 5}, capsys)
    assert errors == [f"{section} must be an object mapping names to entries"]
    assert out == ""


@pytest.mark.parametrize(
    "section",
    ["models", "prompt_templates", "summarizers", "datasets", "judges"],
)
def test_star_name_reserved_without_entry_errors(section):
    errors, _, _ = check({section: {"*": 5}})
    assert errors == ["name '*' is reserved"]


@pytest.mark.parametrize("name", ["", "a b", "a\tb", "a\nb"])
def test_invalid_names(name):
    errors, _, _ = check({"models": {name: {}}})
    assert errors == [f"invalid name '{name}' in models"]


# --- model entries ---


def test_model_entry_non_dict():
    errors, resolved, _ = check({"models": {"m1": 5}})
    assert errors == ["model 'm1': entry must be an object"]
    assert resolved["models"] == {}


def test_model_entry_field_order():
    errors, _, _ = check(
        {"models": {"m1": {"path": 5, "model_args": [1], "gen_params": "x"}}}
    )
    assert errors == [
        "model 'm1': field 'path' must be a string",
        "model 'm1': field 'model_args' must be an object",
        "model 'm1': field 'gen_params' must be an object",
    ]


def test_model_entry_empty_is_valid():
    errors, resolved, _ = check({"models": {"m1": {}}})
    assert errors == []
    assert resolved["models"]["m1"] == {"path": None, "model_args": {}, "gen_params": {}}


# --- prompt template entries ---


def test_template_entry_non_dict():
    errors, _, _ = check({"prompt_templates": {"t1": 5}})
    assert errors == ["prompt template 't1': entry must be an object"]


def test_template_path_must_be_string():
    errors, _, _ = check({"prompt_templates": {"t1": {"path": 5}}})
    assert errors == ["prompt template 't1': field 'path' must be a string"]


def test_template_empty_entry_resolves_to_none_path():
    errors, resolved, _ = check({"prompt_templates": {"t1": {}}})
    assert errors == []
    assert resolved["prompt_templates"]["t1"] is None


# --- summarizer entries ---


def test_summarizer_entry_non_dict():
    errors, resolved, _ = check({"summarizers": {"s1": 5}})
    assert errors == ["summarizer 's1': entry must be an object"]
    assert resolved["summarizers"] == {}


def test_summarizer_stray_path_errors_without_warn(capsys):
    config = full_config()
    config["summarizers"]["s1"]["path"] = "/models/m1"
    errors, resolved, out = check(config, capsys)
    assert errors == [
        "summarizer 's1': field 'path' is not allowed — the model path is fixed by the model entry"
    ]
    assert "warn:" not in out
    assert "s1" in resolved["summarizers"]


def test_summarizer_string_fields_in_order_plus_resolution_errors():
    config = summarizer_config(
        summarizers={"s1": {"base": 1, "model": 2, "prompt_template": 3}}
    )
    errors, _, _ = check(config)
    assert errors == [
        "summarizer 's1': field 'base' must be a string",
        "summarizer 's1': field 'model' must be a string",
        "summarizer 's1': field 'prompt_template' must be a string",
        "summarizer 's1': base '1' must appear earlier in the file",
        "summarizer 's1': component 'model' not resolvable "
        "(set it directly or via a base chain)",
        "summarizer 's1': component 'prompt_template' not resolvable "
        "(set it directly or via a base chain)",
    ]


def test_summarizer_object_fields():
    config = full_config()
    config["summarizers"]["s1"].update({"model_args": [1], "gen_params": "x"})
    errors, resolved, _ = check(config)
    assert errors == [
        "summarizer 's1': field 'model_args' must be an object",
        "summarizer 's1': field 'gen_params' must be an object",
    ]
    assert resolved["summarizers"]["s1"]["model_args"] == {"flash-attn": True}
    assert resolved["summarizers"]["s1"]["gen_params"] == {"temperature": 0.3, "max_tokens": 2048}


# --- summarizer resolution ---


def test_summarizer_baseline_from_model_entry():
    errors, resolved, _ = check(
        summarizer_config(summarizers={"s1": {"model": "m1", "prompt_template": "t1"}})
    )
    assert errors == []
    assert resolved["summarizers"]["s1"] == {
        "model": "m1",
        "model_args": {"a": 1},
        "prompt_template": "t1",
        "gen_params": {"g": 1},
    }


def test_summarizer_per_key_model_args_merge():
    errors, resolved, _ = check(
        summarizer_config(
            summarizers={
                "s1": {
                    "model": "m1",
                    "prompt_template": "t1",
                    "model_args": {"top_p": 0.9},
                }
            }
        )
    )
    assert errors == []
    assert resolved["summarizers"]["s1"]["model_args"] == {"a": 1, "top_p": 0.9}


def test_summarizer_base_inherits_resolved_spec():
    errors, resolved, _ = check(
        summarizer_config(
            summarizers={
                "s1": {"model": "m1", "prompt_template": "t1", "model_args": {"b": 2}},
                "s2": {"base": "s1", "gen_params": {"h": 2}},
            }
        )
    )
    assert errors == []
    assert resolved["summarizers"]["s2"] == {
        "model": "m1",
        "model_args": {"a": 1, "b": 2},
        "prompt_template": "t1",
        "gen_params": {"g": 1, "h": 2},
    }


def test_child_model_override_resets_baseline():
    models = {
        "m1": {"path": "/p", "model_args": {"a": 1}, "gen_params": {"g": 1}},
        "m2": {"path": "/q", "model_args": {"c": 2}},
    }
    errors, resolved, _ = check(
        summarizer_config(
            models=models,
            summarizers={
                "s1": {"model": "m1", "prompt_template": "t1"},
                "s2": {"base": "s1", "model": "m2"},
            },
        )
    )
    assert errors == []
    assert resolved["summarizers"]["s2"] == {
        "model": "m2",
        "model_args": {"c": 2},
        "prompt_template": "t1",
        "gen_params": {},
    }


def test_unknown_base_with_own_components_resolves():
    errors, resolved, _ = check(
        summarizer_config(
            summarizers={"s1": {"base": "nope", "model": "m1", "prompt_template": "t1"}}
        )
    )
    assert errors == ["summarizer 's1': base 'nope' must appear earlier in the file"]
    assert resolved["summarizers"]["s1"] == {
        "model": "m1",
        "model_args": {"a": 1},
        "prompt_template": "t1",
        "gen_params": {"g": 1},
    }


def test_unknown_base_without_components():
    errors, resolved, _ = check(summarizer_config(summarizers={"s1": {"base": "nope"}}))
    assert errors == [
        "summarizer 's1': base 'nope' must appear earlier in the file",
        "summarizer 's1': component 'model' not resolvable "
        "(set it directly or via a base chain)",
        "summarizer 's1': component 'prompt_template' not resolvable "
        "(set it directly or via a base chain)",
    ]
    assert resolved["summarizers"] == {}


def test_later_base_errors_but_own_components_resolve():
    errors, resolved, _ = check(
        summarizer_config(
            summarizers={
                "s1": {"base": "s2", "model": "m1", "prompt_template": "t1"},
                "s2": {"model": "m1", "prompt_template": "t1"},
            }
        )
    )
    assert errors == ["summarizer 's1': base 's2' must appear earlier in the file"]
    assert "s1" in resolved["summarizers"]
    assert "s2" in resolved["summarizers"]


def test_self_base_errors():
    errors, _, _ = check(
        summarizer_config(
            summarizers={"s1": {"base": "s1", "model": "m1", "prompt_template": "t1"}}
        )
    )
    assert errors == ["summarizer 's1': base 's1' must appear earlier in the file"]


def test_earlier_unresolved_base_produces_no_base_error():
    errors, resolved, _ = check(
        summarizer_config(
            summarizers={
                "s1": {"model": 5, "prompt_template": 5},
                "s2": {"base": "s1"},
            }
        )
    )
    assert errors == [
        "summarizer 's1': field 'model' must be a string",
        "summarizer 's1': field 'prompt_template' must be a string",
        "summarizer 's1': component 'model' not resolvable "
        "(set it directly or via a base chain)",
        "summarizer 's1': component 'prompt_template' not resolvable "
        "(set it directly or via a base chain)",
        "summarizer 's2': component 'model' not resolvable "
        "(set it directly or via a base chain)",
        "summarizer 's2': component 'prompt_template' not resolvable "
        "(set it directly or via a base chain)",
    ]
    assert "earlier" not in "".join(errors)
    assert resolved["summarizers"] == {}


def test_invalid_component_entry_still_resolves_with_empty_baseline():
    errors, resolved, _ = check(
        summarizer_config(
            models={"bad": 5},
            summarizers={"s1": {"model": "bad", "prompt_template": "t1"}},
        )
    )
    assert errors == ["model 'bad': entry must be an object"]
    assert resolved["summarizers"]["s1"] == {
        "model": "bad",
        "model_args": {},
        "prompt_template": "t1",
        "gen_params": {},
    }


def test_non_string_model_gives_field_and_component_errors():
    errors, resolved, _ = check(
        summarizer_config(summarizers={"s1": {"model": 5, "prompt_template": "t1"}})
    )
    assert errors == [
        "summarizer 's1': field 'model' must be a string",
        "summarizer 's1': component 'model' not resolvable "
        "(set it directly or via a base chain)",
    ]
    assert resolved["summarizers"] == {}


# --- judge entries ---


def test_judge_entry_non_dict():
    errors, resolved, _ = check({"judges": {"j1": 5}})
    assert errors == ["judge 'j1': entry must be an object"]
    assert resolved["judges"] == {}


def test_judge_string_fields_in_order():
    errors, _, _ = check(
        {
            "judges": {
                "j1": {
                    "endpoint": 5,
                    "model_name": [1],
                    "api_key_env": {},
                    "user_template": 3,
                    "requires_reference": True,
                }
            }
        }
    )
    assert errors == [
        "judge 'j1': field 'endpoint' must be a string",
        "judge 'j1': field 'model_name' must be a string",
        "judge 'j1': field 'api_key_env' must be a string",
        "judge 'j1': field 'user_template' must be a string",
    ]


def test_judge_full_error_order_and_dict_lands_in_resolved():
    entry = {
        "endpoint": 5,
        "requires_reference": "yes",
        "user_template": "x",
        "gen_params": [1],
        "system_content": 5,
    }
    errors, resolved, _ = check({"judges": {"j1": entry}})
    assert errors == [
        "judge 'j1': field 'endpoint' must be a string",
        "judge 'j1': requires_reference is required and must be a boolean",
        "judge 'j1': field 'gen_params' must be an object",
        "judge 'j1': field 'system_content' must be a string",
    ]
    assert resolved["judges"]["j1"] == entry


@pytest.mark.parametrize("flag", [None, "yes", 1])
def test_judge_requires_reference_must_be_boolean(flag):
    entry = {"user_template": "T: {transcript} S: {summary}"}
    if flag is not None:
        entry["requires_reference"] = flag
    errors, _, _ = check({"judges": {"j1": entry}})
    assert errors == ["judge 'j1': requires_reference is required and must be a boolean"]


# --- judge placeholders ---


def test_placeholders_split_between_system_and_user():
    errors, _, _ = check(
        judge_config("S: {summary} R: {reference}", system="T: {transcript}")
    )
    assert errors == []


def test_superfluous_reference_is_legal_with_flag_off():
    errors, _, _ = check(
        judge_config("T: {transcript} S: {summary} R: {reference}", flag=False)
    )
    assert errors == []


def test_unknown_tokens_pass_through():
    errors, _, _ = check(judge_config("{foo} T: {transcript} S: {summary}", flag=False))
    assert errors == []


def test_reference_required_iff_flag_on():
    errors, _, _ = check(judge_config("T: {transcript} S: {summary}"))
    assert errors == [
        "judge 'j1': requires_reference is true but placeholder '{reference}' is missing"
    ]


def test_missing_transcript_and_summary():
    errors, _, _ = check(judge_config("hello", flag=False))
    assert errors == [
        "judge 'j1': missing placeholder '{transcript}'",
        "judge 'j1': missing placeholder '{summary}'",
    ]


def test_all_three_missing_with_flag_on():
    errors, _, _ = check(judge_config("hello"))
    assert errors == [
        "judge 'j1': missing placeholder '{transcript}'",
        "judge 'j1': missing placeholder '{summary}'",
        "judge 'j1': requires_reference is true but placeholder '{reference}' is missing",
    ]


def test_non_string_system_counts_as_empty():
    entry = {
        "user_template": "T: {transcript} S: {summary}",
        "requires_reference": False,
        "system_content": 5,
    }
    errors, _, _ = check({"judges": {"j1": entry}})
    assert errors == ["judge 'j1': field 'system_content' must be a string"]


# --- defaults ---


def test_defaults_absent():
    errors, resolved, _ = check({})
    assert errors == []
    assert resolved["defaults"] == {"metrics": None, "judges": None}


def test_defaults_empty_lists():
    errors, resolved, _ = check({"default_metrics": [], "default_judges": []})
    assert errors == []
    assert resolved["defaults"] == {"metrics": [], "judges": []}


@pytest.mark.parametrize("key", ["default_metrics", "default_judges"])
def test_defaults_non_list(key):
    errors, _, _ = check({key: "nope"})
    assert errors == [f"{key} must be a list of strings"]


@pytest.mark.parametrize("key", ["default_metrics", "default_judges"])
def test_defaults_entries_must_be_strings(key):
    errors, _, _ = check({key: [1]})
    assert errors == [f"{key}: entries must be strings"]


def test_unknown_metric_deduped_first_occurrence():
    errors, _, _ = check({"default_metrics": ["nope", 1, "nope", "nope2"]})
    assert errors == [
        "default_metrics: entries must be strings",
        metrics._unknown_metric("nope"),
        metrics._unknown_metric("nope2"),
    ]


def test_unknown_judge_uses_config_order():
    entry = {"requires_reference": False, "user_template": "T: {transcript} S: {summary}"}
    errors, _, _ = check({"judges": {"b": entry, "a": entry}, "default_judges": ["x"]})
    assert errors == ["unknown judge 'x' (configured: b, a)"]


def test_unknown_judge_with_empty_roster():
    errors, _, _ = check({"default_judges": ["x"]})
    assert errors == ["unknown judge 'x' (configured: (none))"]


# --- unrecognized field warns ---


@pytest.mark.parametrize(
    ("section", "entry"),
    [
        ("models", {"path": "/p", "extra": 1}),
        ("prompt_templates", {"path": "/p", "extra": 1}),
        ("summarizers", {"model": "m1", "extra": 1}),
        ("datasets", {"path": "d.jsonl", "transcript_field": "text", "extra": 1}),
        (
            "judges",
            {
                "user_template": "T: {transcript} S: {summary}",
                "requires_reference": False,
                "extra": 1,
            },
        ),
    ],
)
def test_entry_warns_name_their_entry(section, entry, capsys):
    _, _, out = check({section: {"n1": entry}}, capsys)
    assert out.splitlines() == [f"warn: unrecognized field 'extra' in {section}.n1"]


def test_server_warn_location(capsys):
    _, _, out = check(
        {
            "server": {
                "command": "c",
                "args": {},
                "env": {},
                "port": 1,
                "startup_timeout_s": 1,
                "weird": 2,
            }
        },
        capsys,
    )
    assert out.splitlines() == ["warn: unrecognized field 'weird' in config.server"]


def test_warns_walk_file_order_across_sections(capsys):
    config = {
        "models": {"m1": {"path": "/p", "x": 1}},
        "server": {"command": "c", "port": 1, "startup_timeout_s": 1, "y": 2},
        "judges": {
            "j1": {
                "user_template": "T: {transcript} S: {summary}",
                "requires_reference": False,
                "z": 3,
            }
        },
    }
    _, _, out = check(config, capsys)
    assert out.splitlines() == [
        "warn: unrecognized field 'x' in models.m1",
        "warn: unrecognized field 'y' in config.server",
        "warn: unrecognized field 'z' in judges.j1",
    ]


def test_open_maps_are_exempt_from_recognition(capsys):
    config = {
        "server": {
            "command": "c",
            "args": {"--anything": "v", "nested": {"deep": 1}},
            "env": {"ANYTHING": "1"},
            "port": 1,
            "startup_timeout_s": 1,
        },
        "models": {
            "m1": {"path": "/p", "model_args": {"k": 1}, "gen_params": {"k2": 2}}
        },
    }
    _, _, out = check(config, capsys)
    assert out == ""


# --- load_config collect mode ---


def test_load_config_collect_mode_top_level_dup(tmp_path):
    path = write_json(str(tmp_path / "c.json"), '{"models": {"m1": {}}, "models": {}}')
    errors = []
    config = config_mod.load_config(path, True, Console(), errors=errors)
    assert errors == ["duplicate name 'models' in config"]
    assert config == {"models": {}}


def test_load_config_collect_mode_dup_inside_section(tmp_path):
    path = write_json(
        str(tmp_path / "c.json"), '{"models": {"m1": {"path": "/p", "path": "/q"}}}'
    )
    errors = []
    config = config_mod.load_config(path, True, Console(), errors=errors)
    assert errors == ["duplicate name 'path' in models"]
    assert config["models"]["m1"] == {"path": "/q"}


def test_load_config_collect_mode_dup_inside_server(tmp_path):
    path = write_json(
        str(tmp_path / "c.json"),
        '{"server": {"port": 1, "port": 2, "startup_timeout_s": 5}}',
    )
    errors = []
    config = config_mod.load_config(path, True, Console(), errors=errors)
    assert errors == ["duplicate name 'port' in server"]
    assert config["server"]["port"] == 2


def test_load_config_fail_fast_dup_still_raises(tmp_path):
    path = write_json(str(tmp_path / "c.json"), '{"models": {}, "models": {}}')
    with pytest.raises(SpecError, match="duplicate name 'models' in config"):
        config_mod.load_config(path, True, Console())


def test_load_config_collect_mode_missing_file_still_raises(tmp_path):
    errors = []
    with pytest.raises(SpecError, match=r"config file not found: .*/c\.json$"):
        config_mod.load_config(str(tmp_path / "c.json"), True, Console(), errors=errors)
    assert errors == []


def test_load_config_collect_mode_invalid_json_still_raises(tmp_path):
    path = write_json(str(tmp_path / "c.json"), "{not json")
    errors = []
    with pytest.raises(SpecError, match=r"invalid JSON in .*/c\.json"):
        config_mod.load_config(path, True, Console(), errors=errors)
    assert errors == []


def test_load_config_collect_mode_still_warns(tmp_path, capsys):
    path = write_json(str(tmp_path / "c.json"), '{"bogus": 1, "models": {}}')
    errors = []
    config = config_mod.load_config(path, True, Console(), errors=errors)
    assert errors == []
    assert config == {"bogus": 1, "models": {}}
    assert capsys.readouterr().out.splitlines() == ["warn: unrecognized field 'bogus' in config"]


def test_top_level_warns_in_file_order(tmp_path, capsys):
    path = write_json(str(tmp_path / "c.json"), '{"zz": 1, "aa": 2}')
    config_mod.load_config(path, True, Console())
    assert capsys.readouterr().out.splitlines() == [
        "warn: unrecognized field 'zz' in config",
        "warn: unrecognized field 'aa' in config",
    ]


def test_load_config_three_positional_args_still_works(tmp_path, capsys):
    path = write_json(str(tmp_path / "c.json"), '{"store": "s.db"}')
    config = config_mod.load_config(path, False, Console())
    assert config == {"store": "s.db"}
    assert capsys.readouterr().out == ""
