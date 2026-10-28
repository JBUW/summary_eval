"""Ticket 06c — the real judge-call handler: rubric rendering, one
completion call per (item, judge) unit through the fake endpoint client
(05a), and the raw response through the ticket-07 parse seam; plus the
judges-phase failure wrap naming the item and the judge.
No real server, no network."""
import json

import harness  # noqa: F401  (puts the repo root on sys.path)
import pytest

from evalapp.datasets import Dataset
from evalapp.endpoint_client import (
    EndpointClient,
    EndpointError,
    EmptyCompletionError,
    HttpError,
    RequestTimeout,
)
from evalapp.errors import RuntimeFailure
from evalapp.identities import generation_id, judge_evaluation_id
from evalapp.judge_call import judge_call, render_judge_messages
from evalapp.scoring import JudgePhaseResult, ResolvedScorers, run_judges_phase
from evalapp.store import Store
from evalapp.summarizers import select_summarizers


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


def _dataset():
    return Dataset(
        name="ds",
        decl={
            "path": "x.jsonl",
            "transcript_field": "t",
            "reference_field": None,
        },
        entries=[{"transcript": f"t{i}"} for i in range(3)],
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


def _commit_generation(store, transcript, index):
    """Seed the FK chain (transcript/model/template/generation) and return
    the generation sha for (transcript, the single summarizer)."""
    transcript_sha = store.upsert_transcript(transcript, "ds", None, index)
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


class _RecordingConsole:
    def __init__(self):
        self.warnings = []

    def warn(self, message):
        self.warnings.append(message)


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


def _client(fake):
    return EndpointClient(transport=fake)


def _run_phase(store, resolved, judges, dataset, client, console,
               infeasible=()):
    return run_judges_phase(
        store,
        resolved,
        ResolvedScorers((), tuple(judges), ()),
        set(infeasible),
        {"ds": dataset},
        {"ds": [0]},
        select_summarizers(resolved),
        client,
        judge_call,
        console,
    )


def test_render_substitutes_transcript_and_summary():
    entry = _judge_entry(
        system_content="Grade {transcript} vs {summary}",
        user_template="Transcript:\n{transcript}\n\nSummary under evaluation:\n{summary}",
    )

    messages = render_judge_messages(entry, "T-0", "G-0", None)

    assert messages == [
        {"role": "system", "content": "Grade T-0 vs G-0"},
        {
            "role": "user",
            "content": "Transcript:\nT-0\n\nSummary under evaluation:\nG-0",
        },
    ]


def test_render_reference_substituted_when_available():
    entry = _judge_entry(
        requires_reference=True,
        user_template="{transcript} / {summary} / {reference}",
    )

    messages = render_judge_messages(entry, "T-0", "G-0", "R-0")

    assert messages == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "T-0 / G-0 / R-0"},
    ]


def test_render_reference_passes_through_when_none():
    entry = _judge_entry(
        requires_reference=False,
        user_template="{transcript} {summary} {reference}",
    )

    messages = render_judge_messages(entry, "T-0", "G-0", None)

    assert messages[1]["content"] == "T-0 G-0 {reference}"


def test_render_unrecognized_tokens_pass_through():
    entry = _judge_entry(user_template="{transcript} {foo} {bar baz}")

    messages = render_judge_messages(entry, "T-0", "G-0", None)

    assert messages[1]["content"] == "T-0 {foo} {bar baz}"


def test_render_empty_system_omitted():
    entry = _judge_entry(system_content="", user_template="{transcript}")

    messages = render_judge_messages(entry, "T-0", "G-0", None)

    assert messages == [{"role": "user", "content": "T-0"}]


def test_render_substituted_values_are_not_rescanned():
    entry = _judge_entry(user_template="T: {transcript}")

    messages = render_judge_messages(entry, "see {summary} now", "G-0", None)

    assert messages[1]["content"] == "T: see {summary} now"


def test_judge_call_clean_parse_returns_all_qualities():
    fake = _FakeTransport()
    fake.enqueue(
        (200, _completion(
            "factual_correctness: 1.0\ncompleteness: 0.5\nconciseness: 0.25"
        ))
    )
    entry = _judge_entry(gen_params={"temperature": 0.2})

    scores = judge_call(_client(fake), "j", entry, "T-0", "G-0", None)

    assert scores == {
        "factual_correctness": 1.0,
        "completeness": 0.5,
        "conciseness": 0.25,
    }
    request = fake.requests[0]
    assert request["method"] == "POST"
    assert request["url"] == "https://e/v1/chat/completions"
    assert "Authorization" not in request["headers"]
    payload = json.loads(request["body"])
    assert payload["model"] == "pin"
    assert payload["messages"] == [
        {"role": "system", "content": "sys"},
        {
            "role": "user",
            "content": "Transcript:\nT-0\n\nSummary under evaluation:\nG-0",
        },
    ]
    assert payload["temperature"] == 0.2


def test_judge_call_rejected_parse_returns_none():
    fake = _FakeTransport()
    fake.enqueue((200, _completion("I cannot evaluate these qualities.")))

    scores = judge_call(
        _client(fake), "j", _judge_entry(), "T-0", "G-0", None
    )

    assert scores is None


@pytest.mark.parametrize(
    ("outcome", "detail"),
    [
        (HttpError(500, "boom"), "HTTP 500"),
        (EmptyCompletionError(), "empty completion"),
        (RequestTimeout(300.0), "timeout after 300.0s"),
        (EndpointError("connection failed: refused"),
         "connection failed: refused"),
    ],
)
def test_judge_call_failure_raises_detail_only_runtime_failure(
    outcome, detail
):
    fake = _FakeTransport()
    fake.enqueue(outcome)

    with pytest.raises(RuntimeFailure) as excinfo:
        judge_call(_client(fake), "j", _judge_entry(), "T-0", "G-0", None)

    assert str(excinfo.value) == detail
    assert excinfo.value.__cause__ is outcome


def test_phase_commits_scores_through_real_handler(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path, judges={"j": _judge_entry()})
    store = Store(tmp_path / "store.db")
    try:
        gen_sha, _transcript_sha = _commit_generation(store, "t0", 0)
        judge_sha = _seed_judge(store, _judge_entry())
        fake = _FakeTransport()
        fake.enqueue(
            (200, _completion(
                "factual_correctness: 1.0\ncompleteness: 0.5\nconciseness: 0.25"
            ))
        )
        console = _RecordingConsole()
        result = _run_phase(
            store, resolved, ("j",), _dataset(), _client(fake), console
        )
        assert result == JudgePhaseResult(
            items=1, missing_generation=0, committed=1, skipped=0,
            dropped=0, failed=0,
        )
        assert store.get_judge_evaluation(
            judge_evaluation_id(judge_sha, gen_sha, None)
        ) == (1.0, 0.5, 0.25)
    finally:
        store.close()


def test_phase_rejected_parse_warns_and_counts_failed(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path, judges={"j": _judge_entry()})
    store = Store(tmp_path / "store.db")
    try:
        gen_sha, _transcript_sha = _commit_generation(store, "t0", 0)
        judge_sha = _seed_judge(store, _judge_entry())
        fake = _FakeTransport()
        fake.enqueue((200, _completion("I cannot evaluate these qualities.")))
        console = _RecordingConsole()
        result = _run_phase(
            store, resolved, ("j",), _dataset(), _client(fake), console
        )
        assert result == JudgePhaseResult(
            items=1, missing_generation=0, committed=0, skipped=0,
            dropped=0, failed=1,
        )
        assert console.warnings == [
            "judge 'j' returned no extractable qualities "
            "for entry #0 in dataset 'ds' (unit not committed)"
        ]
        assert store.get_judge_evaluation(
            judge_evaluation_id(judge_sha, gen_sha, None)
        ) is None
    finally:
        store.close()


def test_phase_transport_failure_exits_with_wrapped_message(tmp_path):
    model_path, template_path = _workspace(tmp_path)
    resolved = _resolved(model_path, template_path, judges={"j": _judge_entry()})
    store = Store(tmp_path / "store.db")
    try:
        _commit_generation(store, "t0", 0)
        _seed_judge(store, _judge_entry())
        fake = _FakeTransport()
        fake.enqueue(HttpError(500, "boom"))
        with pytest.raises(
            RuntimeFailure,
            match="judge 'j' failed for entry #0 in dataset 'ds': HTTP 500",
        ):
            _run_phase(
                store, resolved, ("j",), _dataset(), _client(fake),
                _RecordingConsole(),
            )
    finally:
        store.close()
