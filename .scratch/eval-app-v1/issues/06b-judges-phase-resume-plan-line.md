# 06b: Scoring — judges phase, resume, plan line

**What to build:** The second stage of the scoring module: the judges phase that runs after the metrics phase, resume by pre-scanning already-scored units, and the always-printed plan line reporting the effective scorer set. The per-(item, judge) call itself — rubric rendering, one call per generation, the parse-seam handoff — is ticket 06c; this ticket drives that call and proves the phase with it faked.

**Blocked by:** 1 (Scaffold: executable, console contract, selection grammar), 4 (Store, identities, and `clear`), 05a (Endpoint client), 06a (Scoring: scorer resolution, feasibility, metrics phase)

**Status:** ready-for-agent

Series note (06a–06c): ticket 06 (Scoring pipeline) is split into these three parts; implement them in sequence, each self-contained and committing on its own.

- [x] Execution order (this part): (4) with `--generate`, the full generate lifecycle runs first and a stage-1 abort prevents any scoring; (5) metrics phase over all items, THEN judges phase — no judge tokens spent before the free metrics finish; a metric algorithm failure ⇒ exit 1 before any judge call.
- [x] Resume: already-scored (item, scorer) units are pre-scanned and skipped — no calls on them, only the remainder committed.
- [x] The plan line is always printed and always shows the effective scorer set; "infeasible" counts (scorer, dataset) pairs, "to run" / "already scored" count (item, scorer) units excluding infeasible pairs.
- [x] Unit tests run through the fake endpoint client (ticket 05a) with no real server and no network.

## Comments
- 2026-10-27 — split from ticket 06 (Scoring pipeline: scorer resolution, feasibility, metrics + judges phases) into 06a–06c.
- 2026-10-27 — implemented per the settled map design (slices `29e5b8a`→`a22c3f6`): store judge reads, score_plan, run_judges_phase (faked judge_call seam), score orchestrator; full suite green.
