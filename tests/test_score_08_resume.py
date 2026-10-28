import harness  # noqa: F401  (puts the repo root on sys.path)
import contextlib
import io
import json

from evalapp.console import Console
from evalapp.datasets import Dataset
from evalapp.endpoint_client import EndpointClient
from evalapp.judge_call import judge_call
from evalapp.scoring import Flag, score
from evalapp.store import Store


def _workspace(tmp_path):
    model_path = tmp_path / "model.bin"
    model_path.write_bytes(b"model-bytes")
    template_path = tmp_path / "template.json"
    template_path.write_text(
        json.dumps({"system_content": "sys", "user_template": "usr"})
    )
    return model_path, template_path


def _resolved(model_path, template_path, judges=None):
    return {
        "models": {"m": {"path": str(model_path)}},
        "prompt_templates": {"t": str(template_path)},
        "summarizers": {
            "s": {
                "model": "m",
                "model_args": {},
                "prompt_template": "t",
                "gen_params": {},
            }
        },
        "judges": judges or {},
        "defaults": {"metrics": None, "judges": None},
    }


def _dataset(name="ds", reference_field=None, entries=None, path="x.jsonl"):
    if entries is None:
        entries = [{"transcript": f"t{i}"} for i in range(3)]
    return Dataset(
        name=name,
        decl={
            "path": path,
            "transcript_field": "t",
            "reference_field": reference_field,
        },
        entries=entries,
    )


def _judge_entry(
    requires_reference=False,
    model_name="pin",
    system_content="sys",
    user_template="Transcript:\n{transcript}\n\n"
    "Summary under evaluation:\n{summary}",
    gen_params=None,
):
    return {
        "endpoint": "https://e/v1",
        "model_name": model_name,
        "api_key_env": None,
        "requires_reference": requires_reference,
        "gen_params": gen_params or {},
        "system_content": system_content,
        "user_template": user_template,
    }


def _commit_generation(store, transcript, index, dataset_name="ds"):
    """Seed the FK chain (transcript/model/template/generation) and return
    the generation sha for (transcript, the single summarizer)."""
    transcript_sha = store.upsert_transcript(transcript, dataset_name, None, index)
    model_sha = store.upsert_model(b"model-bytes", "m", "model.bin")
    template_sha = store.upsert_template("sys", "usr", "t")
    return (
        store.upsert_generation(
            transcript_sha, model_sha, {}, template_sha, {},
            f"gen:{transcript}",
        ),
        transcript_sha,
    )


def _seed_judge(store, entry, name="j"):
    return store.upsert_judge(
        entry["model_name"], entry["gen_params"], entry["system_content"],
        entry["user_template"], entry["requires_reference"], name,
        entry["endpoint"], entry["api_key_env"],
    )


class _FakeTransport:
    """Records every request; replays queued outcomes in order."""

    def __init__(self):
        self.requests = []
        self._outcomes = []

    def enqueue(self, *outcomes):
        self._outcomes.extend(outcomes)

    def request(self, method, url, headers, body, timeout):
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers or {}),
                "body": body,
                "timeout": timeout,
            }
        )
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _completion(text):
    return json.dumps({"choices": [{"message": {"content": text}}]})


def _good_judge_outcome():
    return (
        200,
        _completion("factual_correctness: 1.0\ncompleteness: 0.5\n"
                    "conciseness: 0.25"),
    )


def _reject_judge_outcome():
    return 200, _completion("fake: no qualities here")


def _score(resolved, tmp_path, metrics_flag, judges_flag, datasets, selected,
           seed=None, fake=None):
    """Run score() end-to-end with a real Console on captured stdout."""
    store_path = str(tmp_path / "store.db")
    store = Store(store_path)
    if seed is not None:
        seed(store)
    store.close()
    fake = fake or _FakeTransport()
    console = Console()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = score(
            resolved, store_path, metrics_flag, judges_flag, datasets,
            selected, (None, None, None), console,
            EndpointClient(transport=fake), judge_call,
        )
    lines = [line for line in buffer.getvalue().splitlines() if line]
    return lines, *result, fake


def _seeded_generations(store):
    for index in range(3):
        _commit_generation(store, f"t{index}", index)
    _seed_judge(store, _judge_entry())


def test_metrics_resume_second_run_all_already_scored(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path)

    def seed(store):
        _seeded_generations(store)

    first_fake = _FakeTransport()
    lines, _scorers, plan, _metrics_result, _judges_result, _fake = _score(
        resolved, tmp_path, Flag(value=["faithfulness"]), Flag(no=True),
        {"ds": _dataset()}, {"ds": [0, 1, 2]}, seed=seed, fake=first_fake,
    )
    assert lines == [
        "plan(score): 1 metric, 0 judges | 3 items | "
        "3 to run, 0 already scored | 0 infeasible",
        "done(score): 3 committed, 0 dropped, 0 failed",
    ]
    assert plan.to_run == 3
    assert plan.already_scored == 0

    # Second run, same store: everything already scored, nothing to do,
    # no client traffic at all.
    second_fake = _FakeTransport()
    lines, _scorers, plan, metrics_result, _judges_result, _fake = _score(
        resolved, tmp_path, Flag(value=["faithfulness"]), Flag(no=True),
        {"ds": _dataset()}, {"ds": [0, 1, 2]}, fake=second_fake,
    )
    assert lines == [
        "plan(score): 1 metric, 0 judges | 3 items | "
        "0 to run, 3 already scored | 0 infeasible",
        "done(score): 0 committed, 0 dropped, 0 failed",
    ]
    assert plan.to_run == 0
    assert plan.already_scored == 3
    assert metrics_result.committed == 0
    assert metrics_result.skipped == 3
    assert len(second_fake.requests) == 0


def test_judges_resume_no_client_calls_on_committed(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path, judges={"j": _judge_entry()})

    def seed(store):
        _seeded_generations(store)

    first_fake = _FakeTransport()
    first_fake.enqueue(_good_judge_outcome(), _good_judge_outcome(),
                       _good_judge_outcome())
    lines, _scorers, plan, _metrics_result, judges_result, _fake = _score(
        resolved, tmp_path, Flag(no=True), Flag(value=["j"]),
        {"ds": _dataset()}, {"ds": [0, 1, 2]}, seed=seed, fake=first_fake,
    )
    assert plan.to_run == 3
    assert plan.already_scored == 0
    assert judges_result.committed == 3
    assert len(first_fake.requests) == 3

    # Second run with an EMPTY outcome queue: any client call on an
    # already-scored unit would raise IndexError from the fake.
    second_fake = _FakeTransport()
    lines, _scorers, plan, _metrics_result, judges_result, _fake = _score(
        resolved, tmp_path, Flag(no=True), Flag(value=["j"]),
        {"ds": _dataset()}, {"ds": [0, 1, 2]}, fake=second_fake,
    )
    assert lines == [
        "plan(score): 0 metrics, 1 judge | 3 items | "
        "0 to run, 3 already scored | 0 infeasible",
        "done(score): 0 committed, 0 dropped, 0 failed",
    ]
    assert plan.to_run == 0
    assert plan.already_scored == 3
    assert judges_result.committed == 0
    assert judges_result.skipped == 3
    assert len(second_fake.requests) == 0


def test_resume_retries_only_failed_judge_units(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path, judges={"j": _judge_entry()})

    def seed(store):
        _seeded_generations(store)

    # First run: t0 and t2 score, t1's reply parses to no qualities ⇒
    # warned, not committed, counted failed.
    first_fake = _FakeTransport()
    first_fake.enqueue(_good_judge_outcome(), _reject_judge_outcome(),
                       _good_judge_outcome())
    lines, _scorers, plan, _metrics_result, judges_result, _fake = _score(
        resolved, tmp_path, Flag(no=True), Flag(value=["j"]),
        {"ds": _dataset()}, {"ds": [0, 1, 2]}, seed=seed, fake=first_fake,
    )
    assert plan.to_run == 3
    assert judges_result.committed == 2
    assert judges_result.failed == 1
    assert lines[-1] == "done(score): 2 committed, 0 dropped, 1 failed"

    # Resume: only the failed unit is retried — exactly one request, and
    # it names the failed transcript.
    second_fake = _FakeTransport()
    second_fake.enqueue(_good_judge_outcome())
    lines, _scorers, plan, _metrics_result, judges_result, _fake = _score(
        resolved, tmp_path, Flag(no=True), Flag(value=["j"]),
        {"ds": _dataset()}, {"ds": [0, 1, 2]}, fake=second_fake,
    )
    assert lines == [
        "plan(score): 0 metrics, 1 judge | 3 items | "
        "1 to run, 2 already scored | 0 infeasible",
        "done(score): 1 committed, 0 dropped, 0 failed",
    ]
    assert plan.to_run == 1
    assert plan.already_scored == 2
    assert judges_result.committed == 1
    assert judges_result.skipped == 2
    assert len(second_fake.requests) == 1
    assert r"Transcript:\nt1" in second_fake.requests[0]["body"]


def test_combined_metrics_and_judges_resume_counts(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path, judges={"j": _judge_entry()})

    def seed(store):
        _commit_generation(store, "t0", 0)
        _commit_generation(store, "t1", 1)
        _seed_judge(store, _judge_entry())

    first_fake = _FakeTransport()
    first_fake.enqueue(_good_judge_outcome(), _good_judge_outcome())
    lines, _scorers, plan, metrics_result, judges_result, _fake = _score(
        resolved, tmp_path,
        Flag(value=["faithfulness"]), Flag(value=["j"]),
        {"ds": _dataset(entries=[{"transcript": "t0"},
                                 {"transcript": "t1"}])},
        {"ds": [0, 1]}, seed=seed, fake=first_fake,
    )
    assert lines == [
        "plan(score): 1 metric, 1 judge | 2 items | "
        "4 to run, 0 already scored | 0 infeasible",
        "done(score): 4 committed, 0 dropped, 0 failed",
    ]
    assert plan.to_run == 4
    assert plan.already_scored == 0
    assert metrics_result.committed == 2
    assert judges_result.committed == 2
    # Only the judge units touch the client.
    assert len(first_fake.requests) == 2

    second_fake = _FakeTransport()
    lines, _scorers, plan, metrics_result, judges_result, _fake = _score(
        resolved, tmp_path,
        Flag(value=["faithfulness"]), Flag(value=["j"]),
        {"ds": _dataset(entries=[{"transcript": "t0"},
                                 {"transcript": "t1"}])},
        {"ds": [0, 1]}, fake=second_fake,
    )
    assert lines == [
        "plan(score): 1 metric, 1 judge | 2 items | "
        "0 to run, 4 already scored | 0 infeasible",
        "done(score): 0 committed, 0 dropped, 0 failed",
    ]
    assert plan.to_run == 0
    assert plan.already_scored == 4
    assert metrics_result.skipped == 2
    assert judges_result.skipped == 2
    assert len(second_fake.requests) == 0
