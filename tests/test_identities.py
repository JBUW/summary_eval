import hashlib
import json

from evalapp import identities


def _cj(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sha_hex(data):
    return hashlib.sha256(data).hexdigest()


def _components_hash(components):
    return _sha_hex(_cj(list(components)).encode("utf-8"))


def test_canonical_json_exact_form():
    assert identities.canonical_json({"b": 1, "a": [1, {"y": 2, "x": None}]}) == (
        '{"a":[1,{"x":null,"y":2}],"b":1}'
    )


def test_canonical_json_key_order_independent():
    assert identities.canonical_json({"a": {"x": 1, "y": [2, 3]}, "b": "s"}) == (
        identities.canonical_json({"b": "s", "a": {"y": [2, 3], "x": 1}})
    )


def test_transcript_and_summary_ids_hash_utf8_bytes():
    for function in (identities.transcript_id, identities.summary_id):
        assert function("hello") == _sha_hex("hello".encode("utf-8"))
        # non-ASCII: the UTF-8 bytes are hashed, not the Python string
        assert function("résumé") == _sha_hex("résumé".encode("utf-8"))
        assert function("") == _sha_hex(b"")


def test_model_id_hashes_raw_file_bytes():
    payload = b"\x00\x01ggu\xff"
    assert identities.model_id(payload) == _sha_hex(payload)
    assert identities.model_id(b"\x00\x01ggu\xfe") != identities.model_id(payload)


def test_template_id_is_canonical_component_hash():
    assert identities.template_id("sys", "prefix") == _components_hash(["sys", "prefix"])
    # the components are ordered: swapped content is a different template
    assert identities.template_id("prefix", "sys") != identities.template_id("sys", "prefix")
    # empty strings are legal content
    assert identities.template_id("", "") == _components_hash(["", ""])


def test_judge_id_excludes_endpoint_name_and_credential():
    expected = _components_hash(
        ["openrouter/llama-3-70b", {"temperature": 0}, "You score…", "T: {transcript}", True]
    )
    assert (
        identities.judge_id(
            "openrouter/llama-3-70b", {"temperature": 0}, "You score…", "T: {transcript}", True
        )
        == expected
    )
    # gen_params key order is irrelevant
    assert identities.judge_id("m", {"temperature": 0, "top_p": 1}, "s", "t", True) == (
        identities.judge_id("m", {"top_p": 1, "temperature": 0}, "s", "t", True)
    )
    # flipping requires_reference changes the identity
    assert identities.judge_id("m", {}, "s", "t", True) != identities.judge_id("m", {}, "s", "t", False)


def test_generation_id_embeds_args_and_params_as_json():
    transcript_sha, model_sha, template_sha = "t" * 64, "m" * 64, "p" * 64
    args = {"flash-attn": True}
    params = {"max_tokens": 2048, "temperature": 0.3}
    expected = _components_hash([transcript_sha, model_sha, args, template_sha, params])
    assert (
        identities.generation_id(transcript_sha, model_sha, args, template_sha, params)
        == expected
    )
    # key order inside either dict is irrelevant
    assert identities.generation_id(
        transcript_sha, model_sha, {"flash-attn": True}, template_sha, {"temperature": 0.3, "max_tokens": 2048}
    ) == expected


def test_evaluation_ids_use_null_for_missing_reference():
    judge_sha, generation_sha, reference_sha = "j" * 64, "g" * 64, "r" * 64
    assert identities.judge_evaluation_id(judge_sha, generation_sha, None) == (
        _components_hash([judge_sha, generation_sha, None])
    )
    assert identities.judge_evaluation_id(judge_sha, generation_sha, None) != (
        identities.judge_evaluation_id(judge_sha, generation_sha, reference_sha)
    )
    assert identities.metric_evaluation_id("rouge_l", generation_sha, None) == (
        _components_hash(["rouge_l", generation_sha, None])
    )
    assert identities.metric_evaluation_id("rouge_l", generation_sha, None) != (
        identities.metric_evaluation_id("rouge_l", generation_sha, reference_sha)
    )
