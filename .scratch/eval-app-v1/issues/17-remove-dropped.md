# 17: remove the always-zero `dropped` count from `done(score)`

**What to build:** `done(score)` prints `N committed, M failed`, without `dropped`. Before ticket 12 the score phases added 1 to `dropped` when an entry had no reference summary at scoring time (one `warn:` per skipped pair). Ticket 12 moved reference loading into the dataset, where a malformed entry is an R1 load-time failure, so that skip cannot occur and `dropped` is always 0. Infeasible (scorer, dataset) pairs (R2) are already reported by one `warn:` each and by `plan(score)`'s `N infeasible`.

**Blocked by:** none

**Status:** ready-for-agent

- [ ] `MetricsPhaseResult` and `JudgePhaseResult` (`evalapp/scoring.py`) lose the `dropped` field; the phases stop counting it.
- [ ] `done(score)` (used by `score` and `sweep`) is `done(score): N committed, M failed`.
- [ ] `docs/commands.md`: the 3 `done(score)` examples drop `0 dropped`. No GLOSSARY.md or `docs/design.md` change (neither names it).
- [ ] Tests: expected `done(score)` lines and phase-result constructions drop `dropped` (text-only changes; no new tests).

## Comments
