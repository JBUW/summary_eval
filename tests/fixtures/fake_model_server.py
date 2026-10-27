#!/usr/bin/env python3
"""Fake model server for the 05b lifecycle tests.

Prints its launch line plus a couple of log lines, then loops forever.
Special flags: --trap-term ignores SIGTERM; --die N exits with code N
after a short sleep. No sockets are opened.
"""
import os
import signal
import sys
import time

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

while True:
    time.sleep(1)
