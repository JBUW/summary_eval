"""Tests for the injected endpoint client (ticket 05a).

The client is the program's single door to the network, serving both the
model server and the bare judge endpoint profiles. These tests run at the
client seam: a fake transport is injected, and the tests assert on the
requests the client was asked to make and on the outcome or error class
that followed. No real server, no network.
"""
import json

import harness  # noqa: F401  (puts the repo root on sys.path)
import pytest

from evalapp import endpoint_client
from evalapp.endpoint_client import (
    EndpointClient,
    EndpointError,
    EmptyCompletionError,
    HttpError,
    RequestTimeout,
)

JUDGE_ENDPOINT = "https://openrouter.test/api/v1"
SERVER_ROOT = "http://127.0.0.1:8081"


def completion_body(text="the summary"):
    return json.dumps({"choices": [{"message": {"content": text}}]})


class FakeTransport:
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


def client_with(fake):
    return EndpointClient(transport=fake)


def test_complete_posts_chat_completions_and_returns_text():
    fake = FakeTransport()
    fake.enqueue((200, completion_body("hello there")))
    client = client_with(fake)

    text = client.complete(
        JUDGE_ENDPOINT, "small-model", [{"role": "user", "content": "hi"}]
    )

    assert text == "hello there"
    request = fake.requests[0]
    assert request["method"] == "POST"
    assert request["url"] == JUDGE_ENDPOINT + "/chat/completions"
    payload = json.loads(request["body"])
    assert payload["model"] == "small-model"
    assert payload["messages"] == [{"role": "user", "content": "hi"}]


def test_complete_strips_trailing_slash_from_endpoint():
    fake = FakeTransport()
    fake.enqueue((200, completion_body()))
    client = client_with(fake)

    client.complete(JUDGE_ENDPOINT + "/", "small-model", [])

    assert fake.requests[0]["url"] == JUDGE_ENDPOINT + "/chat/completions"


def test_complete_rides_gen_params_with_the_request():
    fake = FakeTransport()
    fake.enqueue((200, completion_body()))
    client = client_with(fake)

    client.complete(
        JUDGE_ENDPOINT,
        "small-model",
        [{"role": "user", "content": "hi"}],
        gen_params={"temperature": 0.2, "max_tokens": 96},
    )

    payload = json.loads(fake.requests[0]["body"])
    assert payload["temperature"] == 0.2
    assert payload["max_tokens"] == 96


def test_complete_sends_no_sampling_fields_when_gen_params_resolve_empty():
    fake = FakeTransport()
    fake.enqueue((200, completion_body()), (200, completion_body()))
    client = client_with(fake)

    client.complete(JUDGE_ENDPOINT, "small-model", [], gen_params=None)
    client.complete(JUDGE_ENDPOINT, "small-model", [], gen_params={})

    for request in fake.requests:
        assert set(json.loads(request["body"])) == {"model", "messages"}


def test_complete_sends_bearer_header_when_credential_env_is_set(monkeypatch):
    monkeypatch.setenv("EVAL_TEST_JUDGE_KEY", "sekret")
    fake = FakeTransport()
    fake.enqueue((200, completion_body()))
    client = client_with(fake)

    client.complete(
        JUDGE_ENDPOINT, "small-model", [], api_key_env="EVAL_TEST_JUDGE_KEY"
    )

    assert fake.requests[0]["headers"]["Authorization"] == "Bearer sekret"


def test_complete_omits_authorization_when_credential_env_unset(monkeypatch):
    monkeypatch.delenv("EVAL_TEST_MISSING_KEY", raising=False)
    fake = FakeTransport()
    fake.enqueue((200, completion_body()))
    client = client_with(fake)

    client.complete(
        JUDGE_ENDPOINT, "small-model", [], api_key_env="EVAL_TEST_MISSING_KEY"
    )

    assert "Authorization" not in fake.requests[0]["headers"]


def test_complete_omits_authorization_when_credential_env_empty(monkeypatch):
    monkeypatch.setenv("EVAL_TEST_EMPTY_KEY", "")
    fake = FakeTransport()
    fake.enqueue((200, completion_body()))
    client = client_with(fake)

    client.complete(
        JUDGE_ENDPOINT, "small-model", [], api_key_env="EVAL_TEST_EMPTY_KEY"
    )

    assert "Authorization" not in fake.requests[0]["headers"]


def test_complete_raises_http_error_with_status_and_body():
    fake = FakeTransport()
    fake.enqueue((500, "boom"))
    client = client_with(fake)

    with pytest.raises(HttpError) as excinfo:
        client.complete(JUDGE_ENDPOINT, "small-model", [])

    error = excinfo.value
    assert error.status == 500
    assert error.body == "boom"
    assert str(error) == "HTTP 500"
    assert isinstance(error, EndpointError)


@pytest.mark.parametrize(
    "body",
    [
        json.dumps({"choices": [{"message": {"content": ""}}]}),
        json.dumps({"choices": [{"message": {}}]}),
        json.dumps({"choices": [{"message": {"content": None}}]}),
        json.dumps({"choices": []}),
        json.dumps({"choices": [{}]}),
        json.dumps({"no_choices": True}),
        "not json at all",
    ],
)
def test_complete_raises_empty_completion_on_unusable_payload(body):
    fake = FakeTransport()
    fake.enqueue((200, body))
    client = client_with(fake)

    with pytest.raises(EmptyCompletionError) as excinfo:
        client.complete(JUDGE_ENDPOINT, "small-model", [])

    assert str(excinfo.value) == "empty completion"
    assert isinstance(excinfo.value, EndpointError)


def test_complete_propagates_request_timeout():
    fake = FakeTransport()
    fake.enqueue(RequestTimeout(300.0))
    client = client_with(fake)

    with pytest.raises(RequestTimeout) as excinfo:
        client.complete(JUDGE_ENDPOINT, "small-model", [])

    assert str(excinfo.value) == "timeout after 300.0s"
    assert isinstance(excinfo.value, EndpointError)


def test_complete_passes_effective_timeout_to_transport():
    fake = FakeTransport()
    fake.enqueue((200, completion_body()), (200, completion_body()))
    client = EndpointClient(transport=fake)

    client.complete(JUDGE_ENDPOINT, "small-model", [])

    assert fake.requests[0]["timeout"] == 300.0

    fake.enqueue((200, completion_body()))
    client.complete(JUDGE_ENDPOINT, "small-model", [], timeout=2.0)

    assert fake.requests[-1]["timeout"] == 2.0


def test_props_gets_server_root_and_returns_build_info():
    fake = FakeTransport()
    fake.enqueue((200, json.dumps({"model": "x", "context": 8192})))
    client = client_with(fake)

    info = client.props(SERVER_ROOT)

    assert info == {"model": "x", "context": 8192}
    request = fake.requests[0]
    assert request["method"] == "GET"
    assert request["url"] == SERVER_ROOT + "/props"
    assert request["body"] is None


def test_props_raises_http_error_on_bad_status():
    fake = FakeTransport()
    fake.enqueue((503, "down"))
    client = client_with(fake)

    with pytest.raises(HttpError) as excinfo:
        client.props(SERVER_ROOT)

    assert excinfo.value.status == 503
    assert excinfo.value.body == "down"


@pytest.mark.parametrize("body", ["[1, 2]", "garbage"])
def test_props_raises_endpoint_error_on_malformed_payload(body):
    fake = FakeTransport()
    fake.enqueue((200, body))
    client = client_with(fake)

    with pytest.raises(EndpointError) as excinfo:
        client.props(SERVER_ROOT)

    assert not isinstance(excinfo.value, HttpError)


def test_tokenize_posts_content_and_returns_count():
    fake = FakeTransport()
    fake.enqueue((200, json.dumps({"tokens": 42})))
    client = client_with(fake)

    count = client.tokenize(SERVER_ROOT, "hello world")

    assert count == 42
    request = fake.requests[0]
    assert request["method"] == "POST"
    assert request["url"] == SERVER_ROOT + "/tokenize"
    assert json.loads(request["body"]) == {"content": "hello world"}


def test_tokenize_raises_http_error_on_bad_status():
    fake = FakeTransport()
    fake.enqueue((500, "nope"))
    client = client_with(fake)

    with pytest.raises(HttpError) as excinfo:
        client.tokenize(SERVER_ROOT, "hello world")

    assert excinfo.value.status == 500


@pytest.mark.parametrize(
    "body", ["garbage", json.dumps({"no_tokens": True}), json.dumps({"tokens": "many"})]
)
def test_tokenize_raises_endpoint_error_on_malformed_payload(body):
    fake = FakeTransport()
    fake.enqueue((200, body))
    client = client_with(fake)

    with pytest.raises(EndpointError) as excinfo:
        client.tokenize(SERVER_ROOT, "hello world")

    assert not isinstance(excinfo.value, HttpError)


def test_create_client_builds_default_client_with_urllib_transport():
    client = endpoint_client.create_client(timeout=2.0)

    with pytest.raises(EndpointError) as excinfo:
        client.props("http://127.0.0.1:1")

    assert not isinstance(excinfo.value, HttpError)
    assert not isinstance(excinfo.value, RequestTimeout)
