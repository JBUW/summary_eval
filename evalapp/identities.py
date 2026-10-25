"""sha256 identities for store rows (docs/store-schema.md, Conventions).

An identity is the hex sha256 of the entity's inputs, computed, never typed:
texts are hashed as UTF-8 bytes, model files as raw bytes, and everything
else as canonical JSON of the listed components (keys sorted, no
insignificant whitespace; an absent value is JSON null). Endpoint URL,
display name, and credential variable are never identity components.
"""
import hashlib
import json


def canonical_json(value):
    """Canonical JSON: keys sorted, no insignificant whitespace."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def sha256_text(text):
    return sha256_hex(text.encode("utf-8"))


def hash_components(components):
    """sha256 of the canonical JSON of the component list."""
    return sha256_hex(canonical_json(list(components)).encode("utf-8"))


def transcript_id(text):
    return sha256_text(text)


def summary_id(text):
    return sha256_text(text)


def model_id(model_bytes):
    return sha256_hex(model_bytes)


def template_id(system_content, user_prefix):
    return hash_components([system_content, user_prefix])


def judge_id(model_name, gen_params, system_content, user_template, requires_reference):
    return hash_components(
        [model_name, gen_params, system_content, user_template, bool(requires_reference)]
    )


def generation_id(transcript_sha, model_sha, model_args, template_sha, gen_params):
    return hash_components(
        [transcript_sha, model_sha, model_args, template_sha, gen_params]
    )


def judge_evaluation_id(judge_sha, generation_sha, reference_sha):
    return hash_components([judge_sha, generation_sha, reference_sha])


def metric_evaluation_id(metric_name, generation_sha, reference_sha):
    return hash_components([metric_name, generation_sha, reference_sha])
