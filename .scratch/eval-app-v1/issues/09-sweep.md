# 09: `sweep` command

**What to build:** The exhaustive wide net: exact `score` semantics, including implied generation, over ALL configured summarizers × ALL configured datasets × the resolved scorer set. It never depends on prior state — missing summaries are produced first. No selection or scorer flags exist to misuse; widening is possible, narrowing is not.

**Blocked by:** 8 (`score` command)

**Status:** ready-for-agent

- [ ] Exhaustive: all configured summarizers × all configured datasets × the resolved scorer set, with generation implied; the summarizer axis is the configured summarizers only (no model × template Cartesian product).
- [ ] Any of `--select` / `--summarizer` / `--model` / `--prompt-template` / `--metrics` / `--judges` / `--generate` ⇒ exit 2 with `error: 'sweep' takes no selection or scorer flags (it is exhaustive); use 'score --generate' to narrow`.
- [ ] Scorer set: `default_metrics` present ⇒ exactly that list (incl. `[]` ⇒ zero metrics), absent ⇒ all code-registered; `default_judges` present ⇒ exactly that list, absent ⇒ all configured judges. Present-but-empty ≠ absent — no fallback to all.
- [ ] Widen-only overrides: `--all-metrics` and `--all-judges` (independent, default off) and `--all` (= both); composable with the individuals, idempotent, set-based; no narrowing flags exist.
- [ ] Message order: `warn:` → `plan(generate):` → `plan(score):` → `done(generate):` → `done(score):`; whole scope committed ⇒ no server spawn.
- [ ] Infeasible (scorer, dataset) pairs warn+drop exactly as in `score` (docs shape: `warn: judge 'X' requires reference summaries; dataset 'Y' has none (pair skipped)`).
- [ ] Credential preflight: a judge whose `api_key_env` is unset/empty ⇒ `warn:` + drop, exit 0 (contrast: an explicit `score --judges X` with an unset key is exit 2).
- [ ] Per-item and per-(item, scorer) commits; exit classes 0/1/2 inherited from `score`.

## Comments
