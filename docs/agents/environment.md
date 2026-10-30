# Environment

Quirks of this dev container, read before interpreting test failures or choosing where to run a command.

## Socket tests

- `bin/check` (the commit gate) excludes tests marked `sockets`; they bind real local model servers on ports 18000-18300 and are only meaningful out-of-sandbox.
- Run the full suite with `bin/check --with-sockets` (out-of-sandbox) when a change touches the model-server lifecycle, the endpoint client, or any `*_integration.py` test, or whenever you need the full-suite green before closing an effort.
- A stopped server leaves TIME_WAIT sockets on its port for ~60s. A `port already bound` failure right after a `--with-sockets` run is residue, not a code bug: wait it out and re-run.

## Observability

- `ps` is broken (fatal library error). List processes by scanning `/proc/*/cmdline`; inspect socket states with `ss -tan`.

## Remote git

- The container has no GitHub credentials. Push and remote-branch operations happen from a machine that has credentials; commit locally and leave the branch for the user to push.
