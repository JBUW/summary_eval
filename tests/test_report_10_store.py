"""Ticket 10 — the five new read-only Store methods: latest-wins name
lookups, generation lookup by the four identity columns, pooled metric
values across references, and judge quality values with NULLs excluded."""
import time

import harness  # noqa: F401  (puts the repo root on sys.path)

from evalapp.identities import canonical_json, hash_components, judge_id, sha256_hex
from evalapp.judge_parser import QUALITIES
from evalapp.store import Store


def _store(tmp_path):
    return Store(str(tmp_path / "store.db"))


def _seeded_store(tmp_path):
    store = Store(str(tmp_path / "store.db"))
    model_sha = store.upsert_model(b"model-bytes", "m", "model.bin")
    template_sha = store.upsert_template("sys", "usr", "t")
    generation_shas, transcript_shas = [], []
    for index in range(2):
        transcript_sha = store.upsert_transcript(
            f"transcript {index}", "named", f"id-{index:02d}", index
        )
        generation_shas.append(
            store.upsert_generation(
                transcript_sha, model_sha, {}, template_sha, {},
                f"gen {index}",
            )
        )
        transcript_shas.append(transcript_sha)
    return store, model_sha, template_sha, transcript_shas, generation_shas


def test_model_sha_by_name(tmp_path):
    store = _store(tmp_path)
    try:
        assert store.model_sha_by_name("m") is None
        sha = store.upsert_model(b"model-bytes", "m", "model.bin")
        assert store.model_sha_by_name("m") == sha == sha256_hex(b"model-bytes")
    finally:
        store.close()


def test_model_sha_by_name_latest_wins(tmp_path):
    store = _store(tmp_path)
    try:
        store.upsert_model(b"old-bytes", "m", "model.bin")
        time.sleep(1.05)
        store.upsert_model(b"new-bytes", "m", "model.bin")
        assert store.model_sha_by_name("m") == sha256_hex(b"new-bytes")
    finally:
        store.close()


def test_template_sha_by_name(tmp_path):
    store = _store(tmp_path)
    try:
        assert store.template_sha_by_name("t") is None
        sha = store.upsert_template("sys", "usr", "t")
        assert sha == hash_components(["sys", "usr"])
        assert store.template_sha_by_name("t") == sha
    finally:
        store.close()


def test_template_sha_by_name_latest_wins(tmp_path):
    store = _store(tmp_path)
    try:
        store.upsert_template("sys", "usr", "t")
        time.sleep(1.05)
        store.upsert_template("sys2", "usr2", "t")
        assert store.template_sha_by_name("t") == hash_components(
            ["sys2", "usr2"]
        )
    finally:
        store.close()


def test_generations_for(tmp_path):
    store, model_sha, template_sha, transcript_shas, generation_shas = (
        _seeded_store(tmp_path)
    )
    try:
        empty = canonical_json({})
        found = store.generations_for(model_sha, empty, template_sha, empty)
        assert set(found) == set(zip(generation_shas, transcript_shas))
        assert store.generations_for(None, empty, template_sha, empty) == []
        assert store.generations_for(model_sha, empty, None, empty) == []
        args = canonical_json({"temperature": 0.5})
        assert store.generations_for(model_sha, args, template_sha, empty) == []
        other = store.upsert_generation(
            transcript_shas[0], model_sha, {"temperature": 0.5},
            template_sha, {}, "other",
        )
        assert store.generations_for(
            model_sha, args, template_sha, empty
        ) == [(other, transcript_shas[0])]
    finally:
        store.close()


def test_metric_values(tmp_path):
    store, _, _, transcript_shas, generation_shas = _seeded_store(tmp_path)
    try:
        first, second = generation_shas
        store.upsert_metric_evaluation("faithfulness", first, None, 0.25)
        store.upsert_metric_evaluation("faithfulness", second, None, 0.75)
        reference = store.upsert_reference_summary(
            "ref", transcript_shas[0], "named", "id-00", 0
        )
        store.upsert_metric_evaluation("faithfulness", first, reference, 0.5)
        store.upsert_metric_evaluation("other_metric", first, None, 1.0)
        assert store.metric_values("faithfulness", []) == []
        assert store.metric_values("unknown", [first]) == []
        assert sorted(store.metric_values("faithfulness", [first, second])) == [
            0.25, 0.5, 0.75,
        ]
        assert store.metric_values("other_metric", [first, second]) == [1.0]
    finally:
        store.close()


def test_judge_quality_values(tmp_path):
    store, _, _, _, generation_shas = _seeded_store(tmp_path)
    try:
        first, second = generation_shas
        judge_a = judge_id(
            "pin", {}, "", "Judge {transcript} against {summary}", False
        )
        judge_b = judge_id(
            "other", {}, "", "Judge {transcript} against {summary}", False
        )
        store.upsert_judge(
            "pin", {}, "", "Judge {transcript} against {summary}", False,
            "a", "http://127.0.0.1:1", None,
        )
        store.upsert_judge(
            "other", {}, "", "Judge {transcript} against {summary}", False,
            "b", "http://127.0.0.1:1", None,
        )
        store.upsert_judge_evaluation(judge_a, first, None, 1.0, None, 0.5)
        store.upsert_judge_evaluation(judge_a, second, None, None, 0.75, None)
        store.upsert_judge_evaluation(judge_b, first, None, 0.25, 0.25, 0.25)
        shas = [first, second]
        assert store.judge_quality_values(judge_a, QUALITIES[0], []) == []
        assert store.judge_quality_values(judge_a, QUALITIES[0], shas) == [1.0]
        assert store.judge_quality_values(judge_a, QUALITIES[1], shas) == [0.75]
        assert store.judge_quality_values(judge_a, QUALITIES[2], shas) == [0.5]
        assert store.judge_quality_values(judge_b, QUALITIES[0], shas) == [0.25]
    finally:
        store.close()
