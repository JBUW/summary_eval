"""The injected endpoint client: the program's single door to the network.

One client serves both sides of the app's HTTP: the spawned model server
(completions, plus the server-root ``GET /props`` readiness/build-info
surface and the ``POST /tokenize`` context-adequacy surface) and the bare
judge endpoint profiles (URL, model name pin, optional credential by
environment-variable name — no lifecycle, no spawn, no monitoring). No
other module issues network calls.

The transport is injected at the seam: unit tests pass a fake and assert on
the requests received and on the outcome or error class that followed. The
default transport is :class:`UrllibTransport`; the default client is built
by :func:`create_client`, which later orchestration calls through the
module attribute at call time.

Error model — the three failure classes the fail-fast paths key on, over a
base that also catches everything else endpoint-shaped:

- :class:`HttpError` — the endpoint answered with a status >= 400; carries
  ``status`` and ``body``.
- :class:`EmptyCompletionError` — a 2xx completion payload with no usable
  content (non-JSON, missing choices, empty content).
- :class:`RequestTimeout` — the request exceeded its timeout.
- :class:`EndpointError` — base; also the fallback for a dead endpoint
  (connection failure) and for malformed non-completion responses.
"""
import json
import os
import socket
import urllib.error
import urllib.request

DEFAULT_TIMEOUT_S = 300.0


class EndpointError(Exception):
    """Base of every endpoint failure (the exit-1 family)."""


class HttpError(EndpointError):
    """The endpoint answered with a status >= 400."""

    def __init__(self, status, body):
        super().__init__(f"HTTP {status}")
        self.status = status
        self.body = body

    def __str__(self):
        return f"HTTP {self.status}"


class EmptyCompletionError(EndpointError):
    """A 2xx completion payload with no usable content."""

    def __str__(self):
        return "empty completion"


class RequestTimeout(EndpointError):
    """The request exceeded its timeout."""

    def __init__(self, timeout):
        super().__init__(f"timeout after {timeout}s")
        self.timeout = timeout

    def __str__(self):
        return f"timeout after {self.timeout}s"


class UrllibTransport:
    """Default transport: stdlib urllib against a single request.

    Returns ``(status, body_text)`` for any HTTP response (>= 400 included).
    Raises :class:`RequestTimeout` on timeout and the base
    :class:`EndpointError` on connection failure.
    """

    def request(self, method, url, headers, body, timeout):
        data = body.encode("utf-8") if isinstance(body, str) else body
        request = urllib.request.Request(
            url, data=data, headers=dict(headers or {}), method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                return response.status, raw.decode("utf-8", "replace")
        except (TimeoutError, socket.timeout):
            raise RequestTimeout(timeout) from None
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            return exc.code, raw.decode("utf-8", "replace")
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise RequestTimeout(timeout) from None
            raise EndpointError(f"connection failed: {reason}") from None
        except OSError as exc:
            raise EndpointError(f"connection failed: {exc}") from None


def _parse_json_object(text):
    try:
        payload = json.loads(text)
    except ValueError:
        raise EndpointError("malformed JSON in endpoint response") from None
    if not isinstance(payload, dict):
        raise EndpointError("malformed JSON in endpoint response")
    return payload


def _completion_text(text):
    try:
        payload = json.loads(text)
    except ValueError:
        raise EmptyCompletionError() from None
    if not isinstance(payload, dict):
        raise EmptyCompletionError() from None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise EmptyCompletionError() from None
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise EmptyCompletionError() from None
    content = message.get("content")
    if not isinstance(content, str) or content == "":
        raise EmptyCompletionError() from None
    return content


class EndpointClient:
    """One client for all HTTP to the model server and judge endpoints."""

    def __init__(self, transport=None, timeout=DEFAULT_TIMEOUT_S):
        self._transport = transport if transport is not None else UrllibTransport()
        self._timeout = timeout

    def _effective_timeout(self, timeout):
        return self._timeout if timeout is None else timeout

    def complete(
        self,
        endpoint,
        model_name,
        messages,
        gen_params=None,
        api_key_env=None,
        timeout=None,
    ):
        """One completion call; returns the content string of the first choice.

        ``gen_params`` ride with this request only (never as launch
        arguments); a resolved-empty map sends no sampling fields. When
        ``api_key_env`` names a set, non-empty variable a
        ``Authorization: Bearer`` header is added; otherwise no header is
        sent and any 401 surfaces as :class:`HttpError`.
        """
        headers = {"Content-Type": "application/json"}
        if api_key_env:
            key = os.environ.get(api_key_env, "")
            if key:
                headers["Authorization"] = f"Bearer {key}"
        payload = {"model": model_name, "messages": list(messages)}
        if gen_params:
            payload.update(gen_params)
        url = endpoint.rstrip("/") + "/chat/completions"
        status, body = self._transport.request(
            "POST", url, headers, json.dumps(payload), self._effective_timeout(timeout)
        )
        if status >= 400:
            raise HttpError(status, body)
        return _completion_text(body)

    def props(self, server_root, timeout=None):
        """GET the model server's build info (readiness surface)."""
        url = server_root.rstrip("/") + "/props"
        status, body = self._transport.request(
            "GET", url, {}, None, self._effective_timeout(timeout)
        )
        if status >= 400:
            raise HttpError(status, body)
        return _parse_json_object(body)

    def tokenize(self, server_root, text, timeout=None):
        """POST a transcript to the model server; returns its token count."""
        url = server_root.rstrip("/") + "/tokenize"
        headers = {"Content-Type": "application/json"}
        status, body = self._transport.request(
            "POST",
            url,
            headers,
            json.dumps({"content": text}),
            self._effective_timeout(timeout),
        )
        if status >= 400:
            raise HttpError(status, body)
        payload = _parse_json_object(body)
        tokens = payload.get("tokens")
        if not isinstance(tokens, int) or isinstance(tokens, bool):
            raise EndpointError("malformed /tokenize response")
        return tokens


def create_client(timeout=DEFAULT_TIMEOUT_S):
    """Factory for the default client; called at call time by orchestration."""
    return EndpointClient(timeout=timeout)
