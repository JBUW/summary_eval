# 16: report finds candidates by identity, not by name

**What to build:** `report` matches each candidate to stored results by content identity, the same way as `score`. Today `report._collect_rows` resolves the model and template shas through `store.model_sha_by_name` / `store.template_sha_by_name` (the row with the latest `updated_at`), then lists generations with `store.generations_for`. This breaks `docs/store-schema.md` §1 (courtesy columns are never resolved against config; `updated_at` is never read by app logic) and gives wrong rows: two config models that use the same file (aliases) — only the last-written name finds its rows; a swapped model file — the report shows the rows of the old file; and ties at 1-second resolution.

**Blocked by:** none

**Status:** ready-for-agent

- [x] `report` hashes the model file and template through one `SummarizerInputsCache`, as `score` does; it does not read the `name`/`model_path` courtesy columns or `updated_at`.
- [x] For each in-scope transcript and candidate, `report` calculates `generation_id(transcript_sha, model_sha, model_args, template_sha, gen_params)` (as `score_plan` does) and reads `metric_values` / `judge_quality_values` for those shas; an uncommitted generation matches no rows.
- [x] `store.generations_for`, `store.model_sha_by_name` and `store.template_sha_by_name` are deleted, with their 5 tests in `tests/test_report_10_store.py`.
- [x] A missing or unreadable model or template file gives the same `RuntimeFailure` (exit 1) and message as `score`. It occurs after the `plan(report)` lines and before any table, JSON or CSV output; no CSV file is created.
- [x] Tests (existing report test files): alias — two config models with the same file both show the same rows; swapped file — the model file changes after scoring, the report shows `n=0`; missing model file — exit 1, message shown, no CSV. Each fails before the change.
- [x] `docs/commands.md` §report: one line saying candidates match stored results by content identity (model file and template are hashed, as in `score`, so they must be readable), and exit 1 in its exit codes. `docs/store-schema.md` and GLOSSARY.md do not change.

## Comments

- 2026-11-01 — implemented (f5fdd5e): `report._collect_rows` hashes model and template via one `SummarizerInputsCache` and calculates `generation_id` per in-scope transcript and candidate. `Store.model_sha_by_name`, `template_sha_by_name` and `generations_for` deleted with their 5 tests. The core report tests' `_run` now changes into the workspace (config paths are relative). `test_latest_wins_name_lookup` replaced by `test_alias_models_share_rows`, `test_swapped_model_file_matches_no_rows` and `test_missing_model_file_cli`; all three fail on the old code. `docs/commands.md` §report: identity line and exit 1. Non-sockets suite: 560 passed, 1 known environmental failure (proxy 403); sockets suite: same 16 baseline environmental failures.
