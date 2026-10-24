Status: accepted

# The application owns the model server; all model traffic goes through an endpoint

The program talks to a model only through an HTTP endpoint (the OpenAI-compatible
chat interface, plus the server's `/props` for readiness and build information);
every detail of how a model is served — the llama.cpp build, possibly a custom
local build, and its launch command — lives in the `server` section of the config
and nowhere else. The application spawns and stops exactly one server per run:
pre-spawn validation (binary, model file, port free), a readiness poll, a trivial
preflight completion, then a clean stop; a busy port is refused, never adopted.
Portability lives in the code — the endpoint is the only model-facing interface;
accountability lives in the store — model identity is the content hash of the
model file, and generation identity carries the resolved `model_args` and
`gen_params`. Because custom builds are in scope, the app does not assume an
official release: the build it talks to is observed via `/props` at spawn time
(informational, not stored).

## Considered Options

- **Ollama as a wrapper over the existing custom build** — rejected: the serving
  state (what is loaded, with which arguments) would live outside the
  application's spawn/validate/record path.
- **Externally started servers only, with spawning as a later extension** —
  rejected: the application could not verify the state of a process it did not
  start. Painless to add later as an `--adopt` flag if a concrete workflow
  demands it.

## Consequences

- A judge is a bare endpoint profile with no lifecycle — the application does
  not spawn, monitor, or stop a judge; self-judging (pointing a judge at the
  app's own server) is a misconfiguration, not a supported mode.
- `server.args` is never stored in the store; only output-relevant values
  (`model_args`, `gen_params`) enter the generation identity.
- v1 records no device metadata; after a hardware change the human resets the
  store. Revisit trigger: first run on another device.
