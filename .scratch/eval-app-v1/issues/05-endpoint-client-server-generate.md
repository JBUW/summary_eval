# 05: Endpoint client, model server lifecycle, `generate`

**What to build:** The injected endpoint client — the program's single door to the network, serving both the model server and judge endpoints — becomes the seam unit tests inject a fake client into. The server lifecycle module owns the full ADR-0001 lifecycle: pre-spawn validation, spawn from the shared launch-line composition, bounded readiness polling, preflight completion, clean stop — one cycle per distinct resolved (model, model_args) pair, port reused between cycles. On top of both, `generate` becomes a real command: selection → deterministic item order → pre-scan skip → per-item atomic commit → fail-fast with a resume hint.

**Blocked by:** 1 (Scaffold: executable, console contract, selection grammar), 2 (Configuration + datasets; `check` static phase), 4 (Store, identities, and `clear`)

**Status:** ready-for-agent

- [ ] The endpoint client is the single injected transport for all HTTP to model server and judge endpoints; unit tests inject a fake client and assert on the requests it received and on the store/stdout results that followed.
- [ ] Pre-spawn validation: the `server.command` binary exists, the model file exists, and the port is free; a busy port ⇒ exit 2 with `error: port <N> already bound (a previous model server may still be running)` — refused, never adopted.
- [ ] Launch line = `server.command` + rendered `server.args` + rendered resolved `model_args` + `--port` + `--model <path>`; shared map rendering: key ⇒ `--key`, scalar ⇒ `--key value`, `true` ⇒ bare `--key`, `false` ⇒ omitted; `gen_params` are not launch arguments — they ride with each completion request.
- [ ] Readiness = polling `GET /props` until the server reports running, bounded by the configured startup timeout; preflight = one trivial completion; `/props` build info is printed informationally and never stored.
- [ ] One server cycle per distinct resolved (model, model_args) pair in configuration order, spawned on demand mid-run; the port is reused between cycles; clean stop is SIGTERM, wait, SIGKILL.
- [ ] Absent `server` section in the configuration ⇒ hard error, exit 2; nothing is invented, no fallback arguments (`server.args` may be `{}`).
- [ ] No selection flags ⇒ full scope (all configured summarizers × all configured datasets × all entries); `--summarizer`, `--model`, `--prompt-template` are repeatable and take `*`; component selections form a Cartesian product, and named summarizers are added as extra single combinations.
- [ ] Item order is deterministic — summarizer → dataset → entry, in configuration/file order; the loaded model may only affect attempt scheduling, never the identity of what runs.
- [ ] Pre-scan before any call: committed generations are looked up by identity; an already-committed item is skipped with no model call and counted; whole scope committed ⇒ exit 0 without spawning the server, with `note: all N items already committed; server not started`.
- [ ] Commit unit = one item (entry × summarizer): upserts of `transcripts`, `reference_summaries` (when the dataset declares `reference_field`), `models`, `prompt_templates`, plus the `generations` INSERT, all in one transaction — complete-or-absent, a crash loses at most one unit; committed generations are terminal, never re-rolled.
- [ ] `generate` never invokes judges or metrics and never reads reference summaries for scoring (it does upsert reference summaries when the dataset declares a reference field, so scoring can commit in its own transactions).
- [ ] Fail-fast: first HTTP error, empty completion, server death, or readiness timeout ⇒ exit 1 with the failing item, the error, the last ~20 lines of server output, and a resume hint (docs example: `note: re-run to resume; 1 item already committed`).
- [ ] The dataset R1 load-time contract (fail-fast, exit 2, file + line) governs generate inputs; a failure aborts before any call.
- [ ] Line formats match the docs exactly: `plan(generate): 1 summarizer, 3 items, 1 server cycle`; `done(generate): 3 committed, 0 skipped, 0 failed`.
- [ ] Integration tests (inheriting the P0b smoke criteria): spawn → readiness (bounded by the startup timeout) → preflight completion → clean stop; busy port refused with the orphan-server hint; absent `server` section ⇒ exit 2.

## Comments
