# 11: `check` live phase + `--probe-judges`

**What to build:** The opt-in live phase of `check`, which runs only if the static phase is clean: local server probes (readiness, trivial completion, context adequacy) and opt-in judge rubric probes that cost almost nothing and flag context-window and rubric problems before a long run. Reuses ticket 05b's server lifecycle module and shared launch-line composition over ticket 05a's endpoint client, and ticket 07's parser.

**Blocked by:** 2 (Configuration + datasets; `check` static phase), 05a (Endpoint client), 05b (Model server lifecycle), 7 (Judge response parser + golden fixtures)

**Status:** ready-for-agent

- [x] The live phase runs only if the static phase is clean; a static failure exits 2 and the live phase is skipped.
- [x] Local only, fail-fast: exit 1 with the failing target, the error, and the last ~20 server-log lines.
- [x] Per distinct (model, model_args) in configuration order: spawn → wait for readiness (bounded by the startup timeout) → print `/props` informationally → one probe completion per distinct resolved summarizer (deduplicated; a fixed short probe transcript constant in the code, never dataset content — no dataset content leaves the machine) → context-adequacy probe for the longest in-scope transcript per dataset (`POST /tokenize`, chars/3 fallback; over ⇒ `warn:` only) → stop; the port is reused between cycles.
- [x] `--probe-judges` is opt-in (default off; no external or paid call is made by default): one trivial completion per judge, the rubric rendered with placeholder example values only, the response run through the real parser; nothing usable or a transport failure ⇒ exit 1.
- [x] A judge whose `api_key_env` variable is unset/empty ⇒ static failure (exit 2).
- [x] Exit 0 = static clean and all live probes OK (warnings allowed).
- [x] The server lifecycle and launch-line composition come from ticket 05b — no second implementation.

## Comments

- 2026-10-29 — implemented: live phase (per-pair model cycles: spawn → readiness → /props build note + trivial preflight → deduped summarizer probes → first-pair context-adequacy per dataset) + opt-in --probe-judges (placeholder rubric through the real parser); fail-fast exit 1 with target error line + raw 20-line server-log tail; done(check) summary line; docs/commands.md §check updated; integration in tests/test_check_11_integration.py (605 tests green via bin/check)
