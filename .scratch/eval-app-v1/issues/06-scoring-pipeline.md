# 06: Scoring pipeline: scorer resolution, feasibility, metrics + judges phases

**What to build:** The scoring module — the mechanism behind `score`, `sweep`, and `report`: scorer resolution with the exact precedence rules, infeasible-pair computation, the metrics-then-judges phase order, per-(item, scorer) atomic commits, resume/skip, and judge call handling that stops at the parse seam. No CLI surface yet — this ticket's behavior is proven by unit tests through the fake endpoint client and by ticket 08's `score` command.

**Blocked by:** 1 (Scaffold: executable, console contract, selection grammar), 3 (Metrics registry + v1 metrics), 4 (Store, identities, and `clear`), 05a (Endpoint client), 7 (Judge response parser + golden fixtures)

**Status:** ready-for-agent

- [ ] Metrics precedence: explicit `--metrics` (including the `[]` token) ⇒ exactly that list; flag omitted ⇒ `default_metrics` (present-but-`[]` ⇒ zero metrics); key absent from the configuration ⇒ ALL code-registered metrics; any registered metric is invocable by name or `*` whether or not it appears in the configuration; `*` unions with names.
- [ ] Judges precedence: explicit `--judges` list ⇒ exactly that list; `--judges *` ⇒ all configured; bare `--judges` ⇒ `default_judges` if present (present-but-`[]` ⇒ zero + `note: --judges given but default_judges is empty; no judges run`), else all configured (the explicit flag shows enough intent); flag omitted ⇒ ZERO judges — the deliberate safe default, no error, plan line shows `0 judges`. Judges are never invoked implicitly.
- [ ] `--no-metrics` ≡ `--metrics '[]'`; `--no-judges` ≡ `--judges '[]'`; each `--no-X` combined with `--X` in any form ⇒ exit 2.
- [ ] Execution order: (1) pre-effect validation ⇒ exit 2 before store or network; (2) resolve the effective scorer set; (3) infeasible (scorer, dataset) pairs — a reference-requiring scorer over a dataset without `reference_field` — are dropped with one `warn:` each and are never committed; (4) with `--generate`, the full generate lifecycle runs first and a stage-1 abort prevents any scoring; (5) metrics phase over all items, then judges phase — a metric algorithm failure ⇒ exit 1 before any judge call.
- [ ] Commit unit = one (item, scorer): the `reference_summaries` upsert (when applicable) and the evaluation INSERT in the same transaction; a crash loses at most one unit.
- [ ] Resume: already-scored (item, scorer) units are pre-scanned and skipped — no calls on them, only the remainder committed.
- [ ] Judge call: one call per generation scores several qualities (one nullable value per quality, never cross-averaged, no composite); the rubric is rendered with its placeholders and the raw response passes through the parse seam (ticket 07); nothing extractable ⇒ `warn:` + no row + continue; transport/HTTP failure or empty completion ⇒ fail-fast exit 1 naming the item and the judge.
- [ ] The plan line is always printed and always shows the effective scorer set; "infeasible" counts (scorer, dataset) pairs, "to run" / "already scored" count (item, scorer) units excluding infeasible pairs.
- [ ] Unit tests run through the fake endpoint client (ticket 05a) and stop at the parse seam: resolution, rendering, transport handling, and commits are asserted with no real server and no network.

## Comments
