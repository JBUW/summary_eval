# 11: `check` live phase + `--probe-judges`

**What to build:** The opt-in live phase of `check`, which runs only if the static phase is clean: local server probes (readiness, trivial completion, context adequacy) and opt-in judge rubric probes that cost almost nothing and flag context-window and rubric problems before a long run. Reuses ticket 05's server lifecycle module and shared launch-line composition, and ticket 07's parser.

**Blocked by:** 2 (Configuration + datasets; `check` static phase), 5 (Endpoint client, model server lifecycle, `generate`), 7 (Judge response parser + golden fixtures)

**Status:** ready-for-agent

- [ ] The live phase runs only if the static phase is clean; a static failure exits 2 and the live phase is skipped.
- [ ] Local only, fail-fast: exit 1 with the failing target, the error, and the last ~20 server-log lines.
- [ ] Per distinct (model, model_args) in configuration order: spawn → wait for readiness (bounded by the startup timeout) → print `/props` informationally → one probe completion per distinct resolved summarizer (deduplicated; a fixed short probe transcript constant in the code, never dataset content — no dataset content leaves the machine) → context-adequacy probe for the longest in-scope transcript per dataset (`POST /tokenize`, chars/3 fallback; over ⇒ `warn:` only) → stop; the port is reused between cycles.
- [ ] `--probe-judges` is opt-in (default off; no external or paid call is made by default): one trivial completion per judge, the rubric rendered with placeholder example values only, the response run through the real parser; nothing usable or a transport failure ⇒ exit 1.
- [ ] A judge whose `api_key_env` variable is unset/empty ⇒ static failure (exit 2).
- [ ] Exit 0 = static clean and all live probes OK (warnings allowed).
- [ ] The server lifecycle and launch-line composition come from ticket 05 — no second implementation.

## Comments
