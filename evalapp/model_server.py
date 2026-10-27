"""The model server lifecycle (ADR-0001).

The single owner of everything around the spawned model server process:
pre-spawn validation (binary exists, model file exists, port free — a busy
port is refused, never adopted), the shared launch-line composition,
bounded readiness polling through the endpoint client, one trivial
preflight completion, and a clean stop (SIGTERM, grace wait, SIGKILL).

Later commands drive :class:`ServerCycles`; nothing else in the program
spawns, monitors, or stops a model server.
"""
import json
import os
import socket
import subprocess
import tempfile
import time

from .endpoint_client import EndpointError
from .errors import RuntimeFailure, SpecError

PREFLIGHT_MESSAGES = [{"role": "user", "content": "Reply with the single word: ok"}]

READY_POLL_INTERVAL_S = 0.2
READY_POLL_TIMEOUT_S = 5.0
STOP_GRACE_S = 5.0


def render_launch_args(mapping):
    """Shared map rendering for launch arguments, in insertion order.

    key ⇒ ``--key``; scalar ⇒ ``--key value``; true ⇒ bare ``--key``;
    false/None ⇒ omitted. ``gen_params`` never ride here — they ride with
    each completion request.
    """
    rendered = []
    for key, value in mapping.items():
        if value is False or value is None:
            continue
        flag = f"--{key}"
        if value is True:
            rendered.append(flag)
        else:
            rendered.extend([flag, str(value)])
    return rendered


def build_launch_line(command, server_args, model_args, port, model_path):
    """The full launch line: command + server args + model args + --port + --model."""
    return [
        command,
        *render_launch_args(server_args),
        *render_launch_args(model_args),
        "--port", str(port),
        "--model", model_path,
    ]


def effective_server_spec(config, command=None, args_map=None, env_map=None,
                          port=None, startup_timeout_s=None):
    """Merge config server section with command-line overrides.

    A flag beats the config for each field; a map flag is a whole
    replacement of the config map; args/env default to ``{}``. An absent
    ``server`` section is a hard error even when a ``--server-command``
    flag is given — nothing is invented, no fallback launch.
    """
    server = config.get("server")
    if not isinstance(server, dict):
        raise SpecError("no server section in config (no fallback launch)")
    return {
        "command": command if command is not None else server.get("command"),
        "args": args_map if args_map is not None else (server.get("args") or {}),
        "env": env_map if env_map is not None else (server.get("env") or {}),
        "port": port if port is not None else server.get("port"),
        "startup_timeout_s": (
            startup_timeout_s if startup_timeout_s is not None
            else server.get("startup_timeout_s")
        ),
    }


def distinct_model_pairs(resolved):
    """One entry per distinct resolved (model, model_args) pair.

    Walks the resolved summarizers in configuration order; the dedup key
    is the model name plus the model_args map (argument order ignored).
    Returns ``[(model, model_args), ...]`` in first-appearance order.
    """
    pairs = []
    seen = set()
    for entry in resolved["summarizers"].values():
        key = (entry["model"], json.dumps(entry["model_args"], sort_keys=True))
        if key not in seen:
            seen.add(key)
            pairs.append((entry["model"], entry["model_args"]))
    return pairs


def port_is_free(port):
    """Port pre-scan: socket-creation failure (e.g. sandboxed) counts as
    free; a bind failure raises SpecError with the bound-port error."""
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return True
    try:
        probe.bind(("127.0.0.1", port))
    except OSError:
        raise SpecError(
            f"port {port} already bound "
            "(a previous model server may still be running)"
        ) from None
    finally:
        probe.close()
    return True


def prevalidate_launch(spec, pairs, models):
    """Pre-spawn checks, in order: command exists, model files exist, port free.

    A busy port is refused with the orphan-server hint — never adopted.
    """
    command = spec["command"]
    if not os.path.exists(command):
        raise SpecError(f"server: command not found: {command}")
    for model, _model_args in pairs:
        path = models[model]["path"]
        if not os.path.isfile(path):
            raise SpecError(f"model '{model}': file not found: {path}")
    port_is_free(spec["port"])


class ModelServer:
    """One spawned model server process: start, monitor, tail, stop."""

    def __init__(self, launch_line, port, env_map=None):
        self.root = f"http://127.0.0.1:{port}"
        self._log = tempfile.TemporaryFile(mode="w+b")
        self._exit_code = None
        self._log_text = None
        env = {**os.environ, **{k: str(v) for k, v in (env_map or {}).items()}}
        try:
            self._proc = subprocess.Popen(
                launch_line,
                stdin=subprocess.DEVNULL,
                stdout=self._log,
                stderr=subprocess.STDOUT,
                env=env,
            )
        except OSError as exc:
            self._log.close()
            raise RuntimeFailure(f"failed to start model server: {exc}") from exc

    def alive(self):
        return self._proc is not None and self._proc.poll() is None

    def exit_code(self):
        if self._proc is None:
            return self._exit_code
        code = self._proc.poll()
        if code is not None and self._exit_code is None:
            self._exit_code = code
        return code

    def stop(self):
        """Idempotent: SIGTERM, wait out the grace window, then SIGKILL."""
        if self._proc is None:
            return
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=STOP_GRACE_S)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
        self._exit_code = self._proc.wait()
        self._proc = None
        self._log.seek(0)
        self._log_text = self._log.read().decode("utf-8", "replace")
        self._log.close()

    def log_tail(self, n=20):
        """Last n log lines; after stop, from the kept text ([] if no text)."""
        if self._log_text is not None:
            lines = self._log_text.splitlines()
        else:
            self._log.seek(0)
            text = self._log.read().decode("utf-8", "replace")
            self._log.seek(0, os.SEEK_END)
            lines = text.splitlines()
        return lines[-n:]


class ServerCycles:
    """One server cycle per distinct (model, model_args) pair, on demand.

    The port is reused between cycles; the current server is stopped
    before its successor spawns. Any failure between spawn and readiness
    leaves the server stoppable (it is ``last_server``).
    """

    def __init__(self, spec, model_paths, client, console=None):
        self._spec = spec
        self._model_paths = model_paths
        self._client = client
        self._console = console
        self._server = None
        self._last_server = None
        self._current_key = None

    @property
    def last_server(self):
        return self._last_server

    def ensure(self, model, model_args):
        """A live, ready server for (model, model_args) — reused or respawned.

        The new server is registered before readiness, so any failure
        between spawn and preflight still leaves it stoppable via
        :meth:`stop` and readable via :meth:`log_tail` as ``last_server``.
        """
        key = (model, json.dumps(model_args, sort_keys=True))
        if key == self._current_key and self._server is not None and self._server.alive():
            return self._server
        self.stop()
        server = self._make_server(model, model_args)
        self._server = server
        self._last_server = server
        self._readiness(server, model)
        self._current_key = key
        return server

    def _make_server(self, model, model_args):
        """Pre-spawn validation and Popen; raises before any server exists."""
        path = self._model_paths[model]
        prevalidate_launch(self._spec, [(model, model_args)], {model: {"path": path}})
        launch_line = build_launch_line(
            self._spec["command"],
            self._spec["args"],
            model_args,
            self._spec["port"],
            path,
        )
        return ModelServer(launch_line, self._spec["port"], self._spec["env"])

    def _readiness(self, server, model):
        """Bounded /props polling, the build note, and the preflight completion."""
        props = self._wait_ready(server)
        if self._console is not None:
            self._console.note("model server build: " + json.dumps(props, sort_keys=True))
        try:
            self._client.complete(server.root, model, list(PREFLIGHT_MESSAGES))
        except EndpointError as exc:
            raise RuntimeFailure(f"model server preflight failed: {exc}") from exc

    def _wait_ready(self, server):
        """Poll GET /props until the server reports running, bounded."""
        deadline = time.monotonic() + self._spec["startup_timeout_s"]
        while True:
            code = server.exit_code()
            if code is not None:
                raise RuntimeFailure(
                    f"model server exited during startup (exit code {code})"
                )
            try:
                return self._client.props(server.root, timeout=READY_POLL_TIMEOUT_S)
            except EndpointError:
                pass
            if time.monotonic() >= deadline:
                raise RuntimeFailure(
                    f"model server not ready after {self._spec['startup_timeout_s']:g}s"
                )
            time.sleep(READY_POLL_INTERVAL_S)

    def stop(self):
        if self._server is not None:
            self._server.stop()
        self._server = None
        self._current_key = None

    def log_tail(self, n=20):
        if self._last_server is None:
            return []
        return self._last_server.log_tail(n)
