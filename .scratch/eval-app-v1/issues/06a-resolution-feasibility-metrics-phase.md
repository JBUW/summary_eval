# 06a: Scoring — scorer resolution, feasibility, metrics phase

**What to build:** The scoring module's foundation — the mechanism behind `score`, `sweep`, and `report`: resolving the effective scorer set with the exact precedence rules, computing the infeasible (scorer, dataset) pairs, and the metrics phase over all items with per-(item, scorer) atomic commits. No CLI surface yet — behavior is proven by unit tests through the fake endpoint client, later exercised by ticket 08's `score` command.

**Blocked by:** 1 (Scaffold: executable, console contract, selection grammar), 3 (Metrics registry + v1 metrics), 4 (Store, identities, and `clear`), 05a (Endpoint client)

**Status:** ready-for-agent

Series note (06a–06c): ticket 06 (Scoring pipeline) is split into these three parts; implement them in sequence, each self-contained and committing on its own.

- [x] Metrics precedence: explicit `--metrics` (including the `[]` token) ⇒ exactly that list; flag omitted ⇒ `default_metrics` (present-but-`[]` ⇒ zero metrics); key absent from the configuration ⇒ ALL code-registered metrics; any registered metric is invocable by name or `*` whether or not it appears in the configuration; `*` unions with names.
- [x] Judges precedence: explicit `--judges` list ⇒ exactly that list; `--judges *` ⇒ all configured; bare `--judges` ⇒ `default_judges` if present (present-but-`[]` ⇒ zero + `note: --judges given but default_judges is empty; no judges run`), else all configured (the explicit flag shows enough intent); flag omitted ⇒ ZERO judges — the deliberate safe default, no error, plan line shows `0 judges`. Judges are never invoked implicitly.
- [x] `--no-metrics` ≡ `--metrics '[]'`; `--no-judges` ≡ `--judges '[]'`; each `--no-X` combined with `--X` in any form ⇒ exit 2.
- [x] Execution order (this part): (1) pre-effect validation ⇒ exit 2 before store or network; (2) resolve the effective scorer set; (3) infeasible (scorer, dataset) pairs — a reference-requiring scorer over a dataset without `reference_field` — are dropped with one `warn:` each and are never committed.
- [x] Metrics phase over all items; a metric algorithm failure ⇒ exit 1 before any judge call.
- [x] Commit unit = one (item, scorer): the `reference_summaries` upsert (when applicable) and the evaluation INSERT in the same transaction; a crash loses at most one unit.
- [x] Unit tests run through the fake endpoint client (ticket 05a) with no real server and no network.

## Comments
- 2026-10-27 — split from ticket 06 (Scoring pipeline: scorer resolution, feasibility, metrics + judges phases) into 06a–06c.
- 2026-10-27 — implemented per the settled map design (slices `49d21bb`→`1f4d0bb`): templates/summarizers/store-getters modules, resolve_scorers, infeasible_pairs, run_metrics_phase, score_metrics; full suite green.
