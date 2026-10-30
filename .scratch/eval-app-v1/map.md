# Map: eval-app-v1

## Notes

- Effort: build `evalapp` per `spec.md`; tickets in `issues/`. Done: 01–11, 06a–06c, 07.
- Ticket 06 was split into 06a–06c on 2026-10-27 (a single session looped on the combined scope); the split parts carry the original ticket's `Blocked by` edges.
- The `Status:` lines on tickets stay as written; done = every box checked + an "implemented" comment under `## Comments` (see 05a, 05b, 07).
- Closed tickets' settled designs were pruned from this map on 2026-10-30; recover them via `git log --follow .scratch/eval-app-v1/map.md` (the per-ticket `design settled` commits), the code, and `docs/`.

## Decisions-so-far

- Judge rendering: a placeholder is substituted only when its value is available for the call; unrecognized or non-applicable placeholders pass through as literal text (docs/config.md, Rendering).
- `resolved["prompt_templates"][name]` stores the template's `path` string, not the content.
- The `score` commit unit is one (item, scorer): the `reference_summaries` upsert (when applicable) and the evaluation INSERT in the same transaction; a crash loses at most one unit (docs/commands.md, §score Store footprint).
- The normative `score` console strings live in docs/commands.md §score.

## Closed tickets

- 01–04, 07: scaffold / console / selection / config + dataset contracts / check static / store / metrics registry / judge parser — closed 2026-10-24…26.
- 05a/05b: endpoint client, model server lifecycle — closed 2026-10-27.
- 05c/05d: generate scope, order, skip, commit; fail-fast, resume, integration — closed 2026-10-28.
- 06a/06b: resolution, feasibility, metrics phase; judges phase, resume, plan line — closed 2026-10-27.
- 06c: judge call handling — closed 2026-10-28.
- 08: score CLI — closed 2026-10-28.
- 09: sweep — closed 2026-10-28.
- 10: report — closed 2026-10-29.
- 11: check live phase — closed 2026-10-29.
