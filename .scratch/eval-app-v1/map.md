# Map: eval-app-v1

## Notes

- Effort: build `evalapp` per `spec.md`; tickets in `issues/`. Done: 01–16, 06a–06c, 07.
- Ticket 06 was split into 06a–06c on 2026-10-27 (a single session looped on the combined scope); the split parts carry the original ticket's `Blocked by` edges.
- The `Status:` lines on tickets stay as written; done = every box checked + an "implemented" comment under `## Comments` (see 05a, 05b, 07).
- Closed tickets' settled designs were pruned from this map on 2026-10-30; recover them via `git log --follow .scratch/eval-app-v1/map.md` (the per-ticket `design settled` commits), the code, and `docs/`.

## Decisions-so-far

- Judge rendering: a placeholder is substituted only when its value is available for the call; unrecognized or non-applicable placeholders pass through as literal text (docs/config.md, Rendering).
- `resolved["prompt_templates"][name]` stores the template's `path` string, not the content.
- The `score` commit unit is one (item, scorer): the `reference_summaries` upsert (when applicable) and the evaluation INSERT in the same transaction; a crash loses at most one unit (docs/commands.md, §score Store footprint).
- The normative `score` console strings live in docs/commands.md §score.
- Ticket 12 (architecture review, 2026-10-31): the dataset loader is the only reader of a dataset file. Each entry carries `reference` (text, or `None` iff no `reference_field`); `Dataset.has_references` replaces callers' `decl["reference_field"]` checks; R1 makes empty-reference handling at use sites dead, so none exists; references are a load-time snapshot held in memory like transcripts. `scoring._read_reference` is deleted, together with the per-entry "has no reference … (pair skipped)" warn-and-drop path (unreachable under R1) and its three hand-built-Dataset tests; `done(score)` keeps its `dropped` slot unchanged (now always 0); `docs/design.md` R2 is reworded to the per-(scorer, dataset) form of `docs/config.md` (issues/12-dataset-owns-reference.md).
- Ticket 13 (architecture review, 2026-10-31): `evalapp/summarizers.py` owns the generation-identity inputs of a summarizer. `Summarizer.key` is the only four-part key (model, `model_args`, template, `gen_params`); `SummarizerInputs` = (model hash, prompt template, template hash); no "surface" names. A cache object in the module caches the model hash by model and the template by template (not by the four-part key), so summarizers sharing a model hash its file once; callers build no keys. The model file is hashed in chunks, never held whole in memory; `store.upsert_model` takes the model hash, not bytes. `_run_score` creates one cache per command for plan, generate, metrics and judges (`score`, `sweep`); the `generate` command creates its own. `check_live` uses `Summarizer.key` and gets templates from the cache without reading model files; template errors name the template. No doc changes: the model identity stays the sha256 of the file bytes (issues/13-summarizer-inputs.md).
- Ticket 14 (architecture review, 2026-11-01): `evalapp/prepare.py` owns command preparation that needs the configuration; `cli.py` keeps only command-line-only checks. Three entry points: `load_scope(args, console, scope=None)` (config → datasets → scope via an optional scope function, default `resolve_selection(args.select, …)`; `sweep` = all entries, `report` = selection then blind sample → empty-scope note → validation; returns one object with config, datasets, scope, resolved), `server_overrides(args)`, `server_spec(args, config)` and `server_cycles(spec, resolved, client, console)` (split so `check_live` keeps the spec for the context-adequacy warn; caller creates the client; `check_live` tests patch `prepare.ServerCycles`), `scorer_flags(args)`. Early stop is `errors.CommandStop(code)`, raised after printing, mapped by `main`. `check_static`/`check_live` use `prepare` and import nothing private from `cli.py` (`port_is_free` from `model_server`). No glossary entry, no doc changes. `main(argv)` tests stay; direct tests only for moved rules without a test today (issues/14-prepare-module.md).
- Ticket 15 (architecture review, 2026-11-01): `scoring.py` passes one frozen `ScoringRun` (store, resolved, scorers, infeasible, datasets, selected, summarizers, inputs, console) to `score_plan(run)`, `run_metrics_phase(run)`, `run_judges_phase(run, client)`. The endpoint client is the only seam: no `judge_call` parameter. `score`/`sweep` take `prepare.Loaded` (8 and 7 parameters). The generate hook is `generate(run)`; `generate_hook(client, cycles)`, no `print_plan`. `score_metrics` is deleted. Tests: replace the three phase-patching 06b tests with real `score()` runs; keep direct phase tests with the new signatures. No doc changes; `dropped` stays in Fog.
- Ticket 16 (architecture review, 2026-11-01): `report` finds candidates by content identity: it hashes model and template via one `SummarizerInputsCache` and calculates `generation_id` per in-scope transcript and candidate (as `score_plan`), then reads `metric_values`/`judge_quality_values`. Delete `generations_for`, `model_sha_by_name`, `template_sha_by_name` and their 5 store tests. Missing/unreadable file: `RuntimeFailure` exit 1 after `plan(report)`, before any output; no CSV. Tests: alias, swapped file, missing file. `docs/commands.md` §report: one identity line + exit 1.
- Ticket 17 (architecture follow-up, 2026-11-01): remove `dropped` (always 0 since ticket 12): `done(score): N committed, M failed`; `MetricsPhaseResult`/`JudgePhaseResult` lose the field; `docs/commands.md` §score/§sweep examples change; test expectations change text only, no new tests. R2 infeasible pairs stay reported by `warn:` and `plan(score)`.

## Fog

- (none)

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
- 12: dataset owns the reference summary — closed 2026-10-31.
- 13: summarizers module owns the summarizer inputs — closed 2026-10-31.
- 14: prepare module owns command preparation — closed 2026-10-31.
- 15: one scoring run shrinks the scoring interface — closed 2026-11-01.
- 16: report finds candidates by identity, not by name — closed 2026-11-01.
