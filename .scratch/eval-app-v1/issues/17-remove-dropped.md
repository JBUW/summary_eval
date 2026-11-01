# 17: remove the always-zero `dropped` count from `done(score)`

**What to build:** `done(score)` prints `N committed, M failed`, without `dropped`. Before ticket 12 the score phases added 1 to `dropped` when an entry had no reference summary at scoring time (one `warn:` per skipped pair). Ticket 12 moved reference loading into the dataset, where a malformed entry is an R1 load-time failure, so that skip cannot occur and `dropped` is always 0. Infeasible (scorer, dataset) pairs (R2) are already reported by one `warn:` each and by `plan(score)`'s `N infeasible`.

**Blocked by:** none

**Status:** ready-for-agent

- [x] `MetricsPhaseResult` and `JudgePhaseResult` (`evalapp/scoring.py`) lose the `dropped` field; the phases stop counting it.
- [x] `done(score)` (used by `score` and `sweep`) is `done(score): N committed, M failed`.
- [x] `docs/commands.md`: the 3 `done(score)` examples drop `0 dropped`. No GLOSSARY.md or `docs/design.md` change (neither names it).
- [x] Tests: expected `done(score)` lines and phase-result constructions drop `dropped` (text-only changes; no new tests).

## Comments

- 2026-11-01 — implemented (2565a92): `dropped` removed from `MetricsPhaseResult`, `JudgePhaseResult` and `done(score)`; the empty `JudgePhaseResult(0, 0, 0, 0, 0)` and one 06b assertion lost a positional zero. `docs/commands.md`: 3 examples. Tests: text-only changes in 9 files. Non-sockets suite: 560 passed, 1 known environmental failure (proxy 403); sockets suite: same 16 baseline environmental failures.
