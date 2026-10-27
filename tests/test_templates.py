"""Ticket 06a — template loading (evalapp/templates.py, docs/config.md prompt_templates)."""
import json

import pytest

from evalapp.errors import RuntimeFailure
from evalapp.templates import Template, load_template


def _write(tmp_path, text, name="t.json"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_load_template_maps_user_template_to_user_prefix(tmp_path):
    path = _write(
        tmp_path,
        json.dumps({"system_content": "sys", "user_template": "usr", "extra": 1}),
    )
    template = load_template("t", path)
    assert isinstance(template, Template)
    assert template.system_content == "sys"
    assert template.user_prefix == "usr"


def test_load_template_absent_keys_are_empty_strings(tmp_path):
    path = _write(tmp_path, json.dumps({"other": 1}))
    template = load_template("t", path)
    assert template == Template(system_content="", user_prefix="")


def test_load_template_missing_file(tmp_path):
    with pytest.raises(RuntimeFailure, match=r"template 't': file not found: "):
        load_template("t", str(tmp_path / "nope.json"))


def test_load_template_is_a_directory(tmp_path):
    with pytest.raises(RuntimeFailure, match="template 't': cannot read"):
        load_template("t", str(tmp_path))


def test_load_template_invalid_utf8(tmp_path):
    path = tmp_path / "bad.json"
    path.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(RuntimeFailure, match="template 't': cannot read"):
        load_template("t", str(path))


def test_load_template_not_valid_json(tmp_path):
    path = _write(tmp_path, "{not json")
    with pytest.raises(RuntimeFailure, match=r"template 't': not valid JSON: "):
        load_template("t", path)


def test_load_template_non_dict(tmp_path):
    path = _write(tmp_path, json.dumps(["system_content"]))
    with pytest.raises(
        RuntimeFailure,
        match=r"must be a JSON object with string fields 'system_content' and 'user_template'",
    ):
        load_template("t", path)


def test_load_template_non_string_value(tmp_path):
    path = _write(
        tmp_path,
        json.dumps({"system_content": 42, "user_template": "x"}),
    )
    with pytest.raises(
        RuntimeFailure,
        match=r"'system_content' and 'user_template' must be strings",
    ):
        load_template("t", path)
