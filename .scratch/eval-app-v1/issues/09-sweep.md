# 09: `sweep` command

**What to build:** The exhaustive wide net: exact `score` semantics, including implied generation, over ALL configured summarizers × ALL configured datasets × the resolved scorer set. It never depends on prior state — missing summaries are produced first. No selection or scorer flags exist to misuse; widening is possible, narrowing is not.

**Blocked by:** 8 (`score` command)

**Status:** ready-for-agent

- [x] Exhaustive: all configured summarizers × all configured datasets × the resolved scorer set, with generation implied; the summarizer axis is the configured summarizers only (no model × template Cartesian product).
- [x] Any of `--select` / `--summarizer` / `--model` / `--prompt-template` / `--metrics` / `--judges` / `--generate` ⇒ exit 2 with `error: 'sweep' takes no selection or scorer flags (it is exhaustive); use 'score --generate' to narrow`.
- [x] Scorer set: `default_metrics` present ⇒ exactly that list (incl. `[]` ⇒ zero metrics), absent ⇒ all code-registered; `default_judges` present ⇒ exactly that list, absent ⇒ all configured judges. Present-but-empty ≠ absent — no fallback to all.
- [x] Widen-only overrides: `--all-metrics` and `--all-judges` (independent, default off) and `--all` (= both); composable with the individuals, idempotent, set-based; no narrowing flags exist.
- [x] Message order: `warn:` → `plan(generate):` → `plan(score):` → `done(generate):` → `done(score):`; whole scope committed ⇒ no server spawn.
- [x] Infeasible (scorer, dataset) pairs warn+drop exactly as in `score` (docs shape: `warn: judge 'X' requires reference summaries; dataset 'Y' has none (pair skipped)`).
- [x] Credential preflight: a judge whose `api_key_env` is unset/empty ⇒ `warn:` + drop, exit 0 (contrast: an explicit `score --judges X` with an unset key is exit 2).
- [x] Per-item and per-(item, scorer) commits; exit classes 0/1/2 inherited from `score`.

## Comments
- 2026-10-28 — implemented: exhaustive sweep command (guard that rejects any of the seven forbidden flag families pre-config with the byte-exact error, scorer-set resolution from defaults and the widen flags, credential preflight warn+drop, generation implied with the no-spawn note when the whole scope is already committed, exact score message order, infeasible pair warns, exit classes inherited from score) + 3 end-to-end integration tests through the fixture server (24-item smoke with unique texts, re-sweep no-spawn, judge parse-reject exit 0); 554 tests green via bin/check
