#!/usr/bin/env python3
"""Fake model server for the generate lifecycle and integration tests.

Prints its launch line plus a couple of log lines, then loops forever.
Special flags: --trap-term ignores SIGTERM; --die N exits with code N
after a short sleep. With --serve it opens a real HTTP server on --port:
GET /props answers the build info; POST /chat/completions answers
"fake: <user content>", except the preflight prompt which answers "ok";
--fail-after N makes every completion after the first N answer HTTP 500;
--completion-log PATH appends one "completion N: <user content>" line
per counted completion.
"""
import json
import os
import signal
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

args = sys.argv[1:]

if "--trap-term" in args:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)

die_code = None
if "--die" in args:
    die_code = int(args[args.index("--die") + 1])

print("fake-model-server launched with: " + " ".join(args), flush=True)
print("fake-model-server: loading model", flush=True)
print(f"env FAKE_VAR={os.environ.get('FAKE_VAR', '(unset)')}", flush=True)

if die_code is not None:
    time.sleep(0.1)
    sys.exit(die_code)

if "--serve" in args:
    PREFLIGHT_PROMPT = "Reply with the single word: ok"
    port = int(args[args.index("--port") + 1])
    model = args[args.index("--model") + 1]
    fail_after = None
    if "--fail-after" in args:
        fail_after = int(args[args.index("--fail-after") + 1])
    completion_log = None
    if "--completion-log" in args:
        completion_log = args[args.index("--completion-log") + 1]
    state = {"count": 0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, status, obj):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/props":
                self._send(200, {"model": model, "status": "running"})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/chat/completions":
                self._send(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
            user = payload["messages"][-1]["content"]
            if user == PREFLIGHT_PROMPT:
                self._send(200, {"choices": [{"message": {"content": "ok"}}]})
                return
            state["count"] += 1
            if completion_log is not None:
                with open(completion_log, "a", encoding="utf-8") as handle:
                    handle.write(f"completion {state['count']}: {user}\n")
            if fail_after is not None and state["count"] > fail_after:
                self._send(500, {"error": "injected failure"})
            else:
                self._send(
                    200, {"choices": [{"message": {"content": "fake: " + user}}]}
                )

    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
    sys.exit(0)

while True:
    time.sleep(1)
