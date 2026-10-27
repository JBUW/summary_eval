# 05b: Model server lifecycle (ADR-0001)

**What to build:** The server lifecycle module that owns the full ADR-0001 lifecycle of the model server: pre-spawn validation, spawn from the shared launch-line composition, bounded readiness polling, a trivial preflight completion, and a clean stop. One cycle per distinct resolved (model, model_args) pair in configuration order, spawned on demand mid-run, the port reused between cycles. Later commands (`generate`, `check`'s live phase, `score --generate`) drive this module; nothing else in the program spawns, monitors, or stops a model server.

**Blocked by:** 1 (Scaffold: executable, console contract, selection grammar), 2 (Configuration + datasets; `check` static phase), 05a (Endpoint client)

**Status:** ready-for-agent

Series note (05a–05d): ticket 05 (Endpoint client, model server lifecycle, `generate`) is split into these four parts; implement them in sequence, each self-contained and committing on its own.

- [ ] Pre-spawn validation: the `server.command` binary exists, the model file exists, and the port is free; a busy port ⇒ exit 2 with `error: port <N> already bound (a previous model server may still be running)` — refused, never adopted.
- [ ] Launch line = `server.command` + rendered `server.args` + rendered resolved `model_args` + `--port` + `--model <path>`; shared map rendering: key ⇒ `--key`, scalar ⇒ `--key value`, `true` ⇒ bare `--key`, `false` ⇒ omitted; `gen_params` are not launch arguments — they ride with each completion request.
- [ ] Readiness = polling `GET /props` through the endpoint client (05a) until the server reports running, bounded by the configured startup timeout; preflight = one trivial completion; `/props` build info is printed informationally and never stored.
- [ ] One server cycle per distinct resolved (model, model_args) pair in configuration order, spawned on demand mid-run; the port is reused between cycles; clean stop is SIGTERM, wait, SIGKILL.
- [ ] Absent `server` section in the configuration ⇒ hard error, exit 2; nothing is invented, no fallback arguments (`server.args` may be `{}`).
- [ ] Integration tests (inheriting the P0b smoke criteria): spawn → readiness (bounded by the startup timeout) → preflight completion → clean stop; busy port refused with the orphan-server hint; absent `server` section ⇒ exit 2.

## Comments
- 2026-10-27 — split from ticket 05 (Endpoint client, model server lifecycle, `generate`) into 05a–05d.
