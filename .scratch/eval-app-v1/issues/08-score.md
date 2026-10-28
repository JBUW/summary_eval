# 08: `score` command

**What to build:** The complete `score` command: stage 2 of the loop — score committed generations with the effective metric set and/or judge set. The full flag set, the always-printed plan line with the effective scorer set, the exit-0 note lines, `--generate` two-stage invocations, credential preflight, and resume. `score` never generates and never spawns the model server unless `--generate` is given.

**Blocked by:** 05a (Endpoint client), 05b (Model server lifecycle), 05c (`generate`: scope, order, skip, commit), 05d (`generate`: fail-fast, resume, integration), 06a (Scoring: scorer resolution, feasibility, metrics phase), 06b (Scoring: judges phase, resume, plan line), 06c (Scoring: judge call handling)

**Status:** ready-for-agent

- [x] Full flag set: `--select`, `--summarizer/--model/--prompt-template`, `--metrics/--judges` (repeatable, with `*` and the `[]` token), `--no-metrics/--no-judges`, `--generate`, and the five `--server-*` flags.
- [x] `--server-*` without `--generate` ⇒ exit 2 with `error: --server-* flags require --generate`; the config's `server` section is inert without `--generate`, never an error.
- [x] With `--generate`: the full generate lifecycle runs first in the same invocation, in the docs' message order (`plan(generate):` → `plan(score):` → `done(generate):` → `done(score):`), and a stage-1 abort prevents any scoring.
- [x] The plan line is always printed with the effective scorer set, in the docs' format: `plan(score): 4 metrics, 1 judge | 50 items | 250 to run, 0 already scored | 0 infeasible` ("infeasible" = (scorer, dataset) pairs; "to run" / "already scored" = (item, scorer) units excluding infeasible).
- [x] Note lines (all exit 0): `note: no committed generations in scope; run 'generate' first`; `note: N selected items have no committed generation; run 'generate' first`; `note: no scorable pairs in scope; nothing scored` (after the infeasible `warn:` lines); `note: no metrics or judges selected; nothing scored` (with `--generate` the generation stage still runs first, then the note).
- [x] Credential: an explicitly named judge whose `api_key_env` variable is unset/empty ⇒ static failure, exit 2.
- [x] Resume: a re-run skips already-scored (item, scorer) units, spends no calls on them, and commits only the remainder.
- [x] `score` never spawns the server without `--generate`; judges are bare endpoints with no lifecycle; a local model as judge works with zero code or config changes (a manually started local server as the endpoint plus a dummy credential variable).
- [x] Judge transport/HTTP failure or empty completion ⇒ fail-fast exit 1 naming the item and the judge.
- [x] Store footprint: `metric_evaluations` (a single scalar) and `judge_evaluations` (one nullable column per quality); `reference_summaries` upserted when the dataset declares `reference_field`; with `--generate`, the generate footprint as well.
- [x] Done line matches the docs: `done(score): 250 committed, 0 dropped, 0 failed`.
- [x] Integration tests: re-run after a simulated partial failure skips committed units (no calls on them, only the remainder committed); a score-level smoke through a fake or trivially cheap endpoint asserts the plan/done lines, exit classes, and the resulting store rows.

## Comments
- 2026-10-28 — implemented: full score command (complete flag set, `--server-*` without `--generate` ⇒ exit 2, infeasible reference warns, always-printed plan line, the note lines, judge credential preflight, `--generate` two-stage interleaving, resume that skips committed (item, scorer) units with no re-calls, judges as bare endpoints with no lifecycle) + 5 end-to-end integration tests through the fixture server (score smoke, two-stage, judge parse-reject, judge HTTP 500 exit 1, judge resume after repointing the endpoint); 522 tests green via bin/check
