# Map: eval-app-v1

## Notes

- Effort: build `evalapp` per `spec.md`; tickets in `issues/`. Done: 01–05b, 07. Open: 05c, 05d, 06a–06c, 08, 09, 10, 11.
- Planned implementation order: 06a → 06b → 06c → 05c → 05d → 08 → 09 → 10 → 11 (satisfies every `Blocked by` edge).
- Ticket 06 was split into 06a–06c on 2026-10-27 (a single session looped on the combined scope); the split parts carry the original ticket's `Blocked by` edges.
- The scoring module (06a–06c) has no CLI surface of its own: behavior is proven by unit tests through the fake endpoint client (05a); ticket 08 does the CLI wiring, and 06 exposes the hook interface in the `cli.py` `_score` stub.
- While implementing 06, update in the same round: docs/commands.md §score, docs/config.md (prompt_templates / judges), docs/store-schema.md (prompt_templates).
- Ticket `Status:` lines stay as written; done = every box checked + an "implemented" comment under `## Comments` (see 05a, 05b, 07).

## Decisions-so-far

- Judge rendering: a placeholder is substituted only when its value is available for the call; unrecognized or non-applicable placeholders pass through as literal text (docs/config.md, Rendering; settled 2026-10-27 while working 06).
- `resolved["prompt_templates"][name]` stores the template's `path` string, not the content (settled 2026-10-27 while working 06).
- The `score` commit unit is one (item, scorer): the `reference_summaries` upsert (when applicable) and the evaluation INSERT in the same transaction; a crash loses at most one unit (docs/commands.md, §score Store footprint).
- The normative `score` console strings live in docs/commands.md §score; the judge-parser contract (07), endpoint-client behavior (05a), and credential-error wording were checked against the docs in the 2026-10-27 session.

## Fog

- Where the scorer reads reference text at commit time: dataset entries carry no reference value at load (`reference_field` is never read at load — 02b), yet both `generate` and `score` upsert `reference_summaries` when the dataset declares `reference_field` (docs/commands.md). Decide the lazy-read mechanism, including its interplay with the resume pre-scan (which needed template-file parsing).
- How 02b box 8 (R2: a missing reference summary is a per-pair warn + drop, runtime) composes with 06a's dataset-level infeasible-pair warn + drop (dataset without `reference_field`).
