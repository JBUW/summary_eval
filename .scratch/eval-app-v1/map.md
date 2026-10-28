# Map: eval-app-v1

## Notes

- Effort: build `evalapp` per `spec.md`; tickets in `issues/`. Done: 01–09, 06a–06c, 07. Open: 10, 11.
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
### Ticket 06a (settled 2026-10-27)

Scope: `score` rules only — metrics-phase feasibility + execution; no sweep scorer-set rules, no generate lifecycle.

**Template file format** (open item resolved): the template file is a JSON object; string keys `system_content` (absent ≡ `""`) and `user_template` (absent ≡ `""`); the loader maps `user_template` → the `user_prefix` column; unknown keys ignored; any read/parse failure at commit time ⇒ `RuntimeFailure` (exit 1). `prompt_text` (the instruction surface passed to metrics) = `system_content + user_prefix`.

**Three new modules:**

- `evalapp/templates.py` — `@dataclass(frozen=True) Template(system_content, user_prefix)`; `load_template(name, path) -> Template`. FileNotFoundError ⇒ `RuntimeFailure(f"template '{name}': file not found: {path}")`; OSError/UnicodeDecodeError ⇒ `RuntimeFailure(f"template '{name}': cannot read {path}: {detail}")` (detail = strerror-or-exc, same pattern as datasets.py); JSONDecodeError ⇒ `RuntimeFailure(f"template '{name}': not valid JSON: {exc}")`; non-dict ⇒ `RuntimeFailure(f"template '{name}': must be a JSON object with string fields 'system_content' and 'user_template'")`; non-string value ⇒ `RuntimeFailure(f"template '{name}': 'system_content' and 'user_template' must be strings")`.

- `evalapp/summarizers.py` — `@dataclass(frozen=True) Summarizer(name: str|None, model, model_args: dict, template, gen_params: dict)`. `select_summarizers(resolved, summarizer_names=None, model_names=None, template_names=None)`: each arg `None` (flag omitted) or token tuple (`*` ok). All three None ⇒ all configured summarizers in config order, each resolved to `Summarizer(name, entry["model"], dict(entry["model_args"]), entry["prompt_template"], dict(entry["gen_params"]))`; none configured ⇒ `()`. Else: the Cartesian product is computed **only if at least one of model_names/template_names is not None** — `model_list = list(models) if model_names is None else _select_tokens(model_names, models, "model")`, same for templates (`"prompt template"`); product = models outer × templates inner of `Summarizer(None, model, dict(entry["model_args"]), template, dict(entry["gen_params"]))` (the model entry's own args — no summarizer override). Settle: `--summarizer std` alone (no component axis) ⇒ product ∅, result = just the named summarizer. Named summarizers (given order; `*` ⇒ config order) are ADDED after the product and never dissected. Dedupe by `(model, canonical_json(model_args), template, canonical_json(gen_params))`, first occurrence wins; return a tuple. `_select_tokens(tokens, configured, kind)`: given order, dedupe first-occurrence, `*` ⇒ all configured, unknown ⇒ `SpecError(f"unknown {kind} '{token}' ({roster})")`; roster = `", ".join(configured)` or `"none configured"`. `canonical_json` comes from `evalapp/identities`.

- `evalapp/scoring.py` —
  - `@dataclass(frozen=True) Flag`: `value: str | list[str] | None` (None=omitted | `"bare"` (judges axis only) | token list), `no: bool = False`.
  - `@dataclass(frozen=True) ResolvedScorers`: `metrics: tuple[str, ...]`, `judges: tuple[str, ...]`, `notes: tuple[str, ...]` (note BODIES; the caller emits `console.note(body)` AFTER its own `plan:` line).
  - `@dataclass(frozen=True) MetricsPhaseResult`: `items, missing_generation, committed, skipped, excluded, dropped: int`.
  - `resolve_scorers(resolved, metrics_flag, judges_flag)`: guards first — `metrics_flag.no and metrics_flag.value is not None` ⇒ `SpecError("--no-metrics is mutually exclusive with --metrics")`; judges mirror. Metrics tokens: `no` ⇒ `[]`; omitted ⇒ `defaults["metrics"]` if not None else `["*"]`; list ⇒ as given; then `metrics.resolve(tokens)` ⇒ names tuple (SpecError with roster on unknown). Judges: `no` or omitted ⇒ `()`; bare ⇒ `defaults["judges"]` if not None (present-but-`[]` ⇒ `()` + note body `--judges given but default_judges is empty; no judges run`), else all configured; explicit list ⇒ `*` ⇒ all configured, given order deduped, unknown ⇒ `SpecError(f"unknown judge '{token}' ({roster})")`.
  - `infeasible_pairs(resolved, scorers, datasets)` ⇒ ordered list of `(kind, scorer_name, dataset_name)` triples: metrics (resolved order) × datasets (config order) where `metrics.get(name).requires_reference` and `dataset.decl["reference_field"] is None`; then judges (resolved order) × datasets where `resolved["judges"][name]["requires_reference"]`.
  - `run_metrics_phase(store, resolved, scorers, infeasible, datasets, selected, summarizers, console)`: `specs = metrics.resolve(list(scorers.metrics))`. Iterate dataset (config order) → `for index in selected[dataset.name]` → summarizer (set order); `items += 1` per triple. Per item: `entry = dataset.entries[index]`; `transcript_sha = transcript_id(entry["transcript"])`; per-summarizer cache keyed by Summarizer: model bytes from `resolved["models"][sum.model]["path"]` → `model_id(...)`; `template = load_template(sum.template, resolved["prompt_templates"][sum.template])` → `template_id(...)`. `generation_sha = generation_id(transcript_sha, model_sha, sum.model_args, template_sha, sum.gen_params)`; `store.get_generation(generation_sha)` None ⇒ `missing_generation += 1; continue`. Per spec: `(spec.name, dataset.name) in infeasible` ⇒ skip; if `spec.requires_reference`: lazily read the reference ONCE per item (first ref-metric triggers; cached for the item's other metrics); None ⇒ `console.warn(f"metric '{spec.name}' has no reference for entry #{index} in dataset '{dataset.name}' (pair skipped)")` + `dropped += 1; continue`; else `reference_sha = summary_id(ref)`. `unit_sha = metric_evaluation_id(spec.name, generation_sha, reference_sha)`; `store.get_metric_evaluation(unit_sha)` not None ⇒ `skipped += 1; continue` (skip-on-rerun). `MetricInput(transcript_text=entry["transcript"], generation_text=gen_text, reference_summary_text=ref if requires else None, prompt_text=template.system_content + template.user_prefix)`; compute inside `try/except Exception` ⇒ `raise RuntimeFailure(f"metric '{spec.name}' failed for entry #{index} in dataset '{dataset.name}': {exc}") from exc` (any algorithm failure ⇒ exit 1; the metrics phase runs entirely before any judge call). value None ⇒ `excluded += 1` (no row); else ONE `with store.transaction():` — if requires: `upsert_reference_summary(ref, transcript_sha, dataset.name, entry.get("entry_id"), index)` — plus `upsert_metric_evaluation(spec.name, generation_sha, reference_sha, value)`; `committed += 1`. Return `MetricsPhaseResult(...)`.
  - `_read_reference(decl, index)`: re-reads `decl["path"]` (FileNotFoundError/OSError/UnicodeDecodeError ⇒ RuntimeFailure, same detail pattern); csv ⇒ `csv.reader(text.splitlines())`, record = `dict(zip(rows[0], rows[index+1]))`; jsonl/json ⇒ `json.loads` per non-empty line, must be dict, i-th record; out-of-range/parse failure ⇒ RuntimeFailure; `value = record.get(decl["reference_field"])`; None or `""` ⇒ None (R2).
  - **Settled wordings (2026-10-27, run_metrics_phase slice):** model-file read in the phase — FileNotFoundError ⇒ `RuntimeFailure(f"model '{name}': file not found: {path}")`; OSError/UnicodeDecodeError ⇒ `RuntimeFailure(f"model '{name}': cannot read {path}: {detail}")` (detail = strerror-or-exc, same pattern as datasets.py). `_read_reference` — file not found ⇒ `reference: file not found: {path}`; cannot read ⇒ `reference: cannot read {path}: {detail}`; JSONDecodeError ⇒ `reference: malformed {path}: not valid JSON: {exc}`; non-dict JSONL record ⇒ `reference: malformed {path}: expected a JSON object`; out-of-range (csv or jsonl) ⇒ `reference: {path} has no entry #{index}`. CSV: `rows = list(csv.reader(text.splitlines()))`, out-of-range when `len(rows) <= index + 1`, `record = dict(zip(rows[0], rows[index+1]))` (short row ⇒ key absent ⇒ lenient R2 drop). JSONL/JSON: `json.loads` per non-empty line, must be dict, i-th record.
  - `score_metrics(resolved, store_path, metrics_flag, judges_flag, datasets, selected, summarizer_selection, console)`: `scorers = resolve_scorers(...)`; `summarizers = select_summarizers(resolved, *summarizer_selection)` (selection = triple of None/token-tuples); `pairs = infeasible_pairs(...)`; emit in order `console.warn(f"{kind} '{name}' requires reference summaries; dataset '{ds}' has none (pair skipped)")`; `infeasible = {(name, ds) for _, name, ds in pairs}`; `store = Store(store_path)`; try: phase / finally: `store.close()`; return `(scorers, result)`.

**R2 composition (fog bullet 2 resolved):** dataset-level infeasible pairs (no `reference_field`) are warned once up front and excluded from all units; per-entry missing reference (R2) is a per-pair warn + drop at commit time, via the lazy read above — the lazy read happens per item at commit time (not at load), so the resume pre-scan needs no template/reference parsing beyond what the pre-scan already does for generation identity.

**Store additions** (`evalapp/store.py`): `get_generation(sha)` → `SELECT generation_text FROM generations WHERE generation_sha256 = ?` row-or-None; `get_metric_evaluation(sha)` → `SELECT value FROM metric_evaluations WHERE metric_evaluation_sha256 = ?` row-or-None (both via `_execute(...).fetchone()`); `transaction()` contextmanager (`import contextlib`; `self._unit_depth = 0` in `__init__`): depth += 1; yield; `self._db.commit()`; on Exception: `self._db.rollback()`, re-raise; finally depth -= 1. While `_unit_depth > 0`, `_execute` runs bare `self._db.execute` instead of `with self._db:` (still wrapping sqlite3.Error ⇒ RuntimeFailure).
### Ticket 06b (settled 2026-10-27)

Scope: judges phase + resume pre-scan + plan data. The per-(item, judge) call itself (rubric rendering, endpoint call, parse) is 06c behind the `judge_call` seam; the plan/done line printing is 08 (the scoring module has no CLI surface — 06b computes and returns, 08 prints).

**Judge-call seam (dependency injection, no raising stub):** `run_judges_phase` takes a `judge_call` parameter. Contract: `judge_call(client, judge_name, judge_entry, transcript_text, generation_text, reference) -> dict[str, float | None] | None`; `judge_entry` = `resolved["judges"][judge_name]`; the dict keys are the three v1 qualities `factual_correctness`, `completeness`, `conciseness` (a value may be None; the phase reads each with `dict.get`, missing ≡ None); `None` = nothing extractable ⇒ phase warns + no row + `failed += 1`. `RuntimeFailure` (transport/HTTP/empty completion) naming the item+judge is 06c's responsibility and propagates as exit 1. 06b proves the phase with an injected fake (no server, no network); 06c implements the real handler; 08 passes it.

**Store additions** (`evalapp/store.py`; `upsert_judge`/`upsert_judge_evaluation` already exist from ticket 04 — unchanged):
- `get_judge_evaluation(sha)` → `SELECT factual_correctness, completeness, conciseness FROM judge_evaluations WHERE judge_evaluation_sha256 = ?` → 3-tuple or None (row-or-None, like `get_metric_evaluation`).
- `has_metric_evaluation(metric_name, generation_sha) -> bool` and `has_judge_evaluation(judge_sha, generation_sha) -> bool` → `SELECT 1 ... LIMIT 1` row-existence. Row existence (with any reference, or none) is the resume criterion: already-scored ⇔ an evaluation row exists for (scorer, generation); no reference parsing in the pre-scan (consistent with the 06a R2 decision).

**Plan pre-scan:** `score_plan(store, resolved, scorers, infeasible, datasets, selected, summarizers) -> ScorePlan`; `@dataclass(frozen=True) ScorePlan(metrics, judges, items, to_run, already_scored, infeasible_pairs)` (all int). Same triple iteration as the phases (datasets in config order → selected indices → summarizers; generation identity via `_item_surface` with the per-summarizer cache; NO `get_generation` check — a unit counts "to run" even when its generation is not committed yet, so a `--generate` run reports the full remainder before generate commits). Per (triple, scorer) unit, scorers in effective order (metrics resolved order, then judges resolved order), infeasible (scorer, dataset) pairs skipped: `has_*` true ⇒ `already_scored += 1`, else `to_run += 1`. `metrics = len(scorers.metrics)`, `judges = len(scorers.judges)`, `infeasible_pairs = len(infeasible)`.

**Judges phase:** `run_judges_phase(store, resolved, scorers, infeasible, datasets, selected, summarizers, client, judge_call, console) -> JudgePhaseResult`; `@dataclass(frozen=True) JudgePhaseResult(items, missing_generation, committed, skipped, dropped, failed)` (all int). Same iteration as `run_metrics_phase`: `items += 1` per triple; per-summarizer surface cache; missing generation ⇒ `missing_generation += 1; continue`. Per judge in resolved order: infeasible pair ⇒ silent skip (no reference read, no warn); `judge_entry["requires_reference"]` ⇒ lazy `_read_reference` once per item, shared across the item's judges (the `reference`/`reference_loaded` pattern of the metrics phase); reference None ⇒ `console.warn(f"judge '{name}' has no reference for entry #{index} in dataset '{dataset.name}' (pair skipped)")` + `dropped += 1; continue` (that pair only, before any resume check). `judge_sha = judge_id(model_name, gen_params, system_content, user_template, requires_reference)` from the entry (cached per name). `unit_sha = judge_evaluation_id(judge_sha, generation_sha, reference_sha)` (reference None ⇒ NULL). `store.get_judge_evaluation(unit_sha)` not None ⇒ `skipped += 1; continue` (resume: no call, no tokens). Else call `judge_call(client, name, judge_entry, entry["transcript"], generation_text, reference)`; `None` ⇒ `console.warn(f"judge '{name}' returned no extractable qualities for entry #{index} in dataset '{dataset.name}' (unit not committed)")` + `failed += 1`; else ONE `with store.transaction():` — when requires: `upsert_reference_summary(reference, transcript_sha, dataset.name, entry.get("entry_id"), index)` — plus `upsert_judge_evaluation(judge_sha, generation_sha, reference_sha, scores.get("factual_correctness"), scores.get("completeness"), scores.get("conciseness"))` ⇒ `committed += 1`. Empty `scorers.judges` ⇒ the phase is a no-op (no judge tokens spent).

**Orchestrator:** `score(resolved, store_path, metrics_flag, judges_flag, datasets, selected, summarizer_selection, console, client, judge_call, generate=None) -> (scorers, plan, metrics_result, judges_result)`. Order: (1) `resolve_scorers` (SpecError ⇒ exit 2, before the store); (2) `select_summarizers` (SpecError, before the store); (3) `infeasible_pairs` warns in order + `infeasible` set; (4) `Store(store_path)`; (5) `plan = score_plan(...)` — BEFORE generate (docs message order: warn → plan(generate) → plan(score) → done(generate) → done(score)); (6) if `generate is not None`: `generate(store, console)` — a callable taking (store, console); a stage-1 RuntimeFailure from it propagates before any scoring; (7) `run_metrics_phase(...)` — a metric RuntimeFailure propagates before any judge call; (8) `run_judges_phase(...)`; (9) `store.close()` in a finally. `score_metrics` (06a) stays as-is; the plan/done line text is printed by 08 from the returned data.

**Slices (TDD, red first, commit each green):** (1) store reads (`tests/test_store.py`); (2) `score_plan` (new `tests/test_scoring_06b.py`); (3) `run_judges_phase` with faked `judge_call` (same file); (4) `score` orchestrator with a fake generate hook — proves abort-before-scoring, pre-scan-before-generate, metrics-before-judges (same file); (5) 06b close.
### Ticket 06c (settled 2026-10-28)

Scope: the real judge-call handler that 06b's judges phase drives — rubric rendering, one completion call per (item, judge) unit, parse through the 07 seam, commit or warn — plus the phase-side wrap that names the item and the judge on failure (delegated by the 06b scope section).

**New module `evalapp/judge_call.py`:**
- `render_judge_messages(judge_entry, transcript_text, generation_text, reference) -> list[dict]`: single-pass `re.sub(r"\{(\w+)\}", …)` over `system_content` and `user_template`; mapping `{transcript}` → transcript, `{summary}` → the generation text, `{reference}` → the reference **only when not None** — all other tokens pass through literal (`{reference}` when None; `{bar baz}` never matches `\w+`). Single-pass ⇒ substituted values are never re-scanned. Messages: the rendered `system_content` as the `system` message **only if non-empty**, then the rendered `user_template` as the `user` message.
- `judge_call(client, judge_name, judge_entry, transcript_text, generation_text, reference) -> dict[str, float | None] | None` (06b seam, unchanged): `client.complete(entry["endpoint"], entry["model_name"], messages, gen_params=entry["gen_params"], api_key_env=entry["api_key_env"])`; `EndpointError` (ANY subclass) ⇒ `RuntimeFailure(str(exc))` — detail only, `__cause__` chained; `parse_judge_response(raw).rejected` ⇒ `None`; else `{q: values.get(q) for q in QUALITIES}` (all three keys, nullable, no composite).

**Phase change** (`evalapp/scoring.py` `run_judges_phase` — the 06b file; the 06b scope section delegates item+judge naming to 06c, and the handler signature carries no dataset/index): wrap the `judge_call(...)` call in `try/except RuntimeFailure` ⇒ re-raise `RuntimeFailure(f"judge '{name}' failed for entry #{index} in dataset '{dataset.name}': {exc}") from exc` (mirrors the metrics-phase wording; final example: `judge 'j' failed for entry #0 in dataset 'ds': HTTP 500`). Update 06b's `test_judge_call_failure_propagates` (tests/test_scoring_06b.py): its fake should raise the detail-only `RuntimeFailure("HTTP 500")` (like the real handler) and the test asserts the full wrapped message.

**Tests:** new self-contained `tests/test_scoring_06c.py`. No cross-test imports (zero in the repo — not a pattern). Copy the minimal 06b fixtures verbatim from tests/test_scoring_06b.py (`_workspace`, `_resolved`, `_dataset`, `_commit_generation`, `_seed_judge`, `_RecordingConsole`) plus a 06c `_judge_entry` variant (default `user_template="Transcript:\n{transcript}\n\nSummary under evaluation:\n{summary}"`), plus a local recording `_FakeTransport` (pattern from tests/test_endpoint_client.py: `enqueue(*outcomes)`, `request()` records `{method,url,headers,body,timeout}` then pops the outcome — raise if it is an Exception) and `_completion(text)`. Every test uses the **real** `EndpointClient(transport=fake)` (the 05a seam) and the **real** 07 parser; store-row assertions happen BEFORE `store.close()`.

**Slices (TDD, red first, commit each green):** (1) `render_judge_messages` (substitution, `{reference}` pass-through, unrecognized pass-through, empty-system omission, no re-scan); (2) `judge_call` clean parse ⇒ full 3-key dict + recorded request (url `https://e/v1/chat/completions`, model, messages, gen_params ride, no Bearer when `api_key_env=None`) and rejected parse ⇒ `None`; (3) `judge_call` failure family (parametrize: `HttpError(500, …)` → `"HTTP 500"`, `EmptyCompletionError()` → `"empty completion"`, `RequestTimeout(300.0)` → `"timeout after 300.0s"`, `EndpointError("connection failed: refused")` → same string) ⇒ detail-only `RuntimeFailure` with `__cause__` chained; (4) phase wrap + 06b test update; (5) phase integration with the REAL handler + fake client: commit ⇒ `result.committed == 1` and `store.get_judge_evaluation(judge_evaluation_id(judge_sha, gen_sha, None))` returns the 3-tuple of scores, rejected ⇒ warn text `judge 'j' returned no extractable qualities for entry #0 in dataset 'ds' (unit not committed)` + no row + `failed == 1`, transport failure ⇒ wrapped exit-1 message; (6) 06c close.

No doc changes needed for 06c (the judge-failure wording is already in docs/commands.md §score "Judge failures"; the rendering note is already in docs/config.md); no store changes.
### Ticket 05c (settled 2026-10-28)

Scope: `generate` happy path — scope expansion, deterministic item order, pre-scan skip, per-item atomic commit. Fail-fast/resume wording is 05d; CLI wiring for `score` is 08.

**New module `evalapp/generate.py`:**
- `run_generate(store, console, resolved, datasets, selected, summarizers, client, cycles)` — `datasets` is the full `{name: Dataset}` map from the CLI, `selected` is `resolve_selection`'s `{name: sorted dataset-indices}`, `summarizers` the selected tuple. Also `generate_hook(resolved, datasets, selected, summarizers, client, cycles)` returning a 2-arg closure `(store, console)` wrapping `run_generate` (06b's `score()` calls `generate(store, console)` with an already-open store, scoring.py:488-489; ticket 08 passes the hook as `generate=`).
- **Items**: `for summarizer in summarizers: for dataset in datasets.values(): for index in selected[dataset.name]` ⇒ summarizer → dataset → entry, config/file order.
- **Pre-scan before any call**: per item, surface-cache keyed `(summarizer.model, canonical_json(summarizer.model_args), summarizer.template, canonical_json(summarizer.gen_params))`; `generation_id(transcript_id(entry["transcript"]), model_sha, summarizer.model_args, template_sha, summarizer.gen_params)`; `store.get_generation(sha) is None` ⇒ pending, else skipped+1.
- **Surface**: local `_load_surface(resolved, summarizer)` → `(model_bytes, model_sha, template, template_sha)` — like `scoring._item_surface` (scoring.py:503-527) but keeps model bytes (`upsert_model` needs them). Same FileNotFoundError/OSError wording as scoring.
- **Messages**: system message only if `template.system_content` non-empty; user content = `template.user_prefix + transcript` exactly.
- **Server cycles planned** C = distinct `(model, canonical_json(model_args))` among the selected summarizers, first-appearance order — scope-based, NOT pending-based. Do NOT use `distinct_model_pairs(resolved)` (it walks config summarizers, model_server.py:83).
- **Console lines** (byte-exact, docs/commands.md:255-262): `plan(generate): {S} summarizer(s), {I} item(s), {C} server cycle(s)` — each count pluralized, `n==1` singular else plural incl. 0 (`1 summarizer, 3 items, 1 server cycle` / `0 summarizers, 0 items, 0 server cycles`). All-committed (`not pending`): plan → `note: all {I} items already committed; server not started` **only when I≥1** (0 items ⇒ plan + done only, no note) → `done(generate): 0 committed, {skipped} skipped, 0 failed`; no spawn. Success/failure end: `done(generate): {committed} committed, {skipped} skipped, 0 failed` (failed always 0 in 05c).
- **Execution** (pending non-empty): wrap in `try/finally: cycles.stop()` (idempotent). Per item: `server = cycles.ensure(summarizer.model, summarizer.model_args)`; `text = client.complete(server.root, summarizer.model, messages, gen_params=summarizer.gen_params)`; any `EndpointError` ⇒ `RuntimeFailure(str(exc)) from exc` (detail-only, judge_call.py:85-86 pattern; 05d adds item naming/log tail/resume note). Read reference **just before the transaction** when `dataset.decl["reference_field"] is not None` via `from .scoring import _read_reference` (cross-module private import has precedent: check_static imports `cli._parse_json_object`); value None ⇒ no upsert. Then ONE `store.transaction()`: `upsert_transcript(entry["transcript"], dataset.name, entry.get("entry_id"), index)` → `upsert_reference_summary(reference, transcript_sha, dataset.name, entry.get("entry_id"), index)` if reference not None → `upsert_model(model_bytes, summarizer.model, model_path)` → `upsert_template(template.system_content, template.user_prefix, summarizer.template)` → `upsert_generation(transcript_sha, model_sha, summarizer.model_args, template_sha, summarizer.gen_params, text)`.
- `model_path` = `resolved["models"][summarizer.model]["path"]`. `Summarizer.model_args` is already the final two-layer merge (config.py:406) — use as-is.

**CLI (`evalapp/cli.py`), generate subparser only:**
- `--summarizer`, `--model`, `--prompt-template`, each `nargs="+"`, `action="append"`, `default=None`; `_tokens(value)` → `None` or `tuple(tok for group in value for tok in group)`; `select_summarizers(resolved, _tokens(args.summarizer), _tokens(args.model), _tokens(args.prompt_template))` (summarizers.py:50 — None = axis omitted; product only when a component axis given; named added after product; dedupe first-occurrence).
- New `_generate` flow: `_load` → `validate_datasets` → `load_dataset` for all (R1 exit 2, before anything) → `resolve_selection` → keep `no entries in scope; nothing to do` note short-circuit (before config validation; pinned by test_console_contract.py:10-15) → `validate_config` (errors ⇒ exit 2) → `select_summarizers` → `effective_server_spec(config, command=args.server_command, args_map=…, env_map=…, port=…, startup_timeout_s=…)` (absent section ⇒ `SpecError("no server section in config (no fallback launch)")`, model_server.py:68, exit 2 **before store open**; keep `_parse_json_object` handling for `--server-args`/`--server-env`) → `client = create_client()` → `cycles = ServerCycles(spec, {name: m["path"] for name, m in resolved["models"].items()}, client, console)` (constructor spawns nothing) → `store = Store(effective_store_path(config, args.store))` → `run_generate(...)` with `store.close()` in finally → return 0.
- **Remove** from `_generate` the stub's `prevalidate_launch(spec, distinct_model_pairs(resolved), …)` call — `ServerCycles._make_server` prevalidates per cycle at first `ensure` (model_server.py:234-236). Settled consequence: all-committed + busy port ⇒ exit 0, never validated.
- Imports: drop `prevalidate_launch` and `distinct_model_pairs` from cli.py; **keep** `port_is_free` re-export (check_static.py:4 does `from .cli import _parse_json_object, port_is_free`; tests use `cli.port_is_free`). No `created empty store` note in `_generate`. Leave `_score`/`_run_command`/`_check`/`_sweep` untouched (their per-dataset plan lines are ticket 08's concern).

**Existing tests that break (plan-line format change) and the fix:** `harness.plan_count(result, command, dataset)` parsed the OLD per-dataset line `plan(generate): <name> N entries`; new format is one line with total items; all 15 call sites use "generate". Replace `plan_count` with `plan_items(result)` parsing the item count from the single `plan(generate):` line (regex on `\d+ items?`). Add `harness.add_summarizer_section(path)` (style of `add_server_section`, harness.py:127): writes `model.bin` (`b"model-bytes"`) + `template.json` (`{"system_content":"sys","user_template":"usr"}`) next to the config and adds `models: {"m": {"path": "model.bin"}}`, `prompt_templates: {"t": "template.json"}`, `summarizers: {"s": {"model": "m", "prompt_template": "t"}}` — needed because with 0 configured summarizers the plan line is always `0 summarizers, 0 items, 0 server cycles` and selection counts are unobservable. Update call sites (1 summarizer, item count == entry count): test_selection_hash.py `test_hash_specs_select_counts` (per-case `== expected`), `test_hash_specs_valid_in_unnamed_datasets` (`== 4`); test_selection_star.py named-star `== 12` (drop the `unnamed is None` line), bare-star `== 24`, bare-star+`--select named #0` `== 24`; test_selection_union.py unioned 3, duplicates dropped 4, no-flag full scope 24, cross-dataset 2; test_selection_at.py three success tests `== 1` each; test_dataset_loader.py `test_json_extension_is_one_object_per_line` `== 2` (plain `generate`, add summarizer section there too). Unaffected: test_subcommands.py (generate case already adds a server section, no summarizers ⇒ `0 summarizers, 0 items, 0 server cycles`, asserts exit 0 + no `error:`; `--metrics x` is argparse-level), test_console_contract.py (empty-scope note; `#99` ⇒ exit 2, no plan line).

**Tests:** new self-contained `tests/test_generate_05c.py`. Copy fixtures verbatim from tests/test_scoring_06c.py lines 1-147 (`_workspace`, `_resolved`, `_dataset`, `_commit_generation`, `_FakeTransport` (`enqueue(*outcomes)`, `request()` records `{method,url,headers,body,timeout}` then pops outcome — raises if Exception), `_completion`, `_client` = REAL `EndpointClient(transport=fake)`). Add: `_CapturingConsole(Console)` recording lines in `_emit`; `_FakeCycles` recording `ensure(model, model_args)` order, returning a fake server with `.root = "http://fake"`, own `.stop()`; variants: 2 models/templates + 2 named summarizers (Cartesian/order); `_dataset` with `reference_field` declared + reference JSONL on disk. No cross-test imports; store-row assertions before `store.close()`.

**Slices (TDD, red first, commit each green):** (1) scope + order — 2 summarizers × 1 dataset × 3 entries ⇒ 6 completions summarizer→dataset→entry (assert request bodies: model name, `user == "usr"+transcript`, system "sys"); Cartesian + named-added selection; empty-system template ⇒ no system message; gen_params ride; no Bearer; (2) pre-scan skip + all-committed — 1 pre-seeded ⇒ `2 committed, 1 skipped, 0 failed`, all 3 ⇒ `_FakeCycles.ensure` never called + plan/note/done byte-exact, 0 items ⇒ no note; (3) per-item commit unit — rows in all 5 tables with sha cross-checks, reference upsert present when declared + value / absent when None, complete-or-absent (transport raises `HttpError(500, …)` on 2nd request ⇒ detail-only `RuntimeFailure("HTTP 500")` propagates, item 1 committed, item 2 absent from every table, `cycles.stop()` after failure); (4) CLI wiring — parser flags repeatable + `*`, all-committed through `harness.run_cli` (server section + summarizer section + pre-seeded store.db, `--select` + `--summarizer s`) ⇒ exit 0 + 3 byte-exact lines (exit 0 proves no spawn — the harness `/bin/true` server would fail readiness), absent server section ⇒ exit 2 `error: no server section in config (no fallback launch)`; apply the harness + 5-file test updates in this slice; (5) close — boxes + implemented comment + map Notes.

No doc changes expected (behavior already matches docs/commands.md §generate; fail-fast wording is 05d).
### Ticket 05d (settled 2026-10-28)

Scope: the failure and recovery half of `generate` — fail-fast block on first failure, resume on re-run (via the 05c pre-scan, no separate path), and the end-to-end integration tests through a real, cheap server.

**Failure block** — emitted by `run_generate` in the pending loop; one new `except (EndpointError, RuntimeFailure)` wraps BOTH `cycles.ensure(...)` and `client.complete(...)` (the `server = cycles.ensure(...)` moves inside the try). In order:
1. `console.error(f"item {dataset.name}#{index} (summarizer '{name}'): {detail}")` — `<index>` is the 0-based dataset index; `name` = `summarizer.name or "unnamed"` (Cartesian-selected summarizers carry no name); `detail` = `f"{exc} from model server"` for the EndpointError family but `str(exc)` as-is for ensure-derived RuntimeFailures (already self-describing).
2. Each line of `cycles.log_tail(20)` via a new `Console.log(line)` — raw, no prefix, stage-unconstrained (`self._emit(line, None)`).
3. `console.note(f"re-run to resume; {N} {_plural(N, 'item', 'items')} already committed")` — N = pre-scan skipped + committed-this-run; always emitted (even N=0).
No `done(generate)` on failure. `cycles.stop()` stays in the `finally`. A SpecError from ensure prevalidation (busy port) is NOT caught: it propagates to exit 2 after the plan line (settled 05b).

**New exception** `FailFastAbort` in `evalapp/errors.py` — NOT a RuntimeFailure subclass (the block is already printed; main must not re-print). `cli.main` gains `except FailFastAbort: return 1` (no output) alongside the existing SpecError → 2 / RuntimeFailure → 1. It propagates through scoring's `generate(store, console)` hook unwrapped ⇒ the stage-1 abort before scoring comes for free.

**Exact edits:** generate.py — the errors import gains `FailFastAbort`; the module docstring drops "Fail-fast wording and the resume note are ticket 05d;" (keep "the score CLI wiring is ticket 08"); the pending loop gets the try/except as above. console.py — `def log(self, line): self._emit(line, None)`. errors.py — `class FailFastAbort(Exception)` with docstring. cli.py — import `FailFastAbort`; main maps it to 1.

**Tests:** update `tests/test_generate_05c.py` — import swap (RuntimeFailure is used only in the failure test), `_FakeCycles.log_tail(n=20) → []`, `test_failure_is_complete_or_absent` now expects `pytest.raises(FailFastAbort)` and the 3 lines (plan / `error: item ds#1 (summarizer 's'): HTTP 500 from model server` / `note: re-run to resume; 1 item already committed`); keep the store-counts and `cycles.stops == 1` assertions. New self-contained `tests/test_generate_05d.py` (fixtures copied verbatim from 05c): parametrized failure classes (`(500, …)` ⇒ "HTTP 500…", `(200, "{}")` ⇒ "empty completion…", `RequestTimeout(300.0)` ⇒ "timeout after 300.0s…", `EndpointError("connection failed: refused")` ⇒ "connection failed: refused from model server") each ⇒ the exact 3 lines and `cycles.stops == 1`; an ensure-derived RuntimeFailure verbatim (no "from model server" suffix); an unnamed summarizer (Cartesian select ⇒ `(summarizer 'unnamed')`); resume-note counts (seeded skip ⇒ "2 items already committed", immediate first failure ⇒ "1 item already committed" singular); raw tail lines between error and note (no prefix); SpecError passthrough (raises SpecError, not FailFastAbort, console.lines == [plan], `cycles.stop()` once, 0 generations); complete-or-absent through the real failure path.

**Fixture serve mode** (`tests/fixtures/fake_model_server.py`, default path byte-unchanged): flags `--serve` (bare), `--port`, `--model`, `--fail-after N`, `--completion-log PATH` (same `args.index(flag) + 1` parsing). When serving: a `ThreadingHTTPServer` on 127.0.0.1:port; `log_message` no-op so the server log stays exactly the 3 launch lines; `GET /props` ⇒ `{"model": <--model value>, "status": "running"}`; `POST /chat/completions` ⇒ the preflight prompt (`"Reply with the single word: ok"`, mirror of model_server's PREFLIGHT_MESSAGES) answers `ok` and is never counted/logged; every other completion increments a per-process counter, appends `completion {n}: {user}\n` to the completion log when given, then answers 500 `{"error": "injected failure"}` when the counter exceeds `--fail-after`, else `{"choices": [{"message": {"content": "fake: " + user}}]}`. Default SIGTERM ⇒ `ModelServer.stop()` works as-is.

**Integration tests** (`tests/test_generate_05d_integration.py`, harness CLI + real fixture, port 18090 — 05b owns 18081/9090/7070/8081; no `harness.add_server_section`): a helper writes `standard_workspace` + `add_summarizer_section` + its own server section (command FIXTURE, args `{"serve": True, "completion-log": <path>, ["fail-after": N]}`, port 18090, startup_timeout_s 10).
- Success: exit 0, 3 byte-exact lines (plan / `note: model server build: {"model": "model.bin", "status": "running"}` / done 3-0-0), completion log = `completion {n}: usrtranscript {n-1}` for n 1..3, store 3 generations / 3 transcripts / 1 model / 1 prompt_template.
- Failure (`--fail-after 1`): exit 1, 7 lines: plan, build note, `error: item named#1 (summarizer 's'): HTTP 500 from model server`, the 3 raw tail lines (launch line / `fake-model-server: loading model` / `env FAKE_VAR=(unset)`), `note: re-run to resume; 1 item already committed`; completion log has items 0 and 1 only; store 1 generation.
- Resume (config args rewritten without fail-after, same store): exit 0, `done(generate): 2 committed, 1 skipped, 0 failed`; completion-log user contents = [usrtranscript 0 ×1, usrtranscript 1 ×2 (500 attempt + resume), usrtranscript 2 ×1] — no re-call on the committed item; 3 generations.
- Busy port (bind 127.0.0.1:18090 in-test): exit 2, lines == [plan, `error: port 18090 already bound (a previous model server may still be running)`].

**Slices (TDD, red first, commit each green):** (1) FailFastAbort + Console.log + failure block + cli mapping + 05c test update + `tests/test_generate_05d.py`; (2) fixture serve mode + `tests/test_generate_05d_integration.py` (4 tests); (3) close — boxes + implemented comment + map Notes.

No doc changes (docs/commands.md §generate "Fail-fast" already specifies the block verbatim, including the `qmsum-dev#1` example).

### Ticket 08 (settled 2026-10-28)

**Scope:** the `score` CLI (`cli.py` `_score` stub at line 189) wires the settled scoring module (06a–06c) to the console and store; plan/done/note lines, credential preflight, `--generate` two-stage, resume, fail-fast. No scoring-module behavior changes beyond what 08 requires of `scoring.py` (print responsibility) and `generate.py` (plan-text helper).

1. **Console guard relaxation (required).** `run_metrics_phase` / `run_judges_phase` warn mid-run, AFTER the always-printed plan lines ⇒ a real `Console` would AssertionError (warn=0 < plan=1). Drop the hard assert in `_emit` (keep stage bookkeeping or simplify). Update the `console.py` top-of-file comment: warn→plan→note is the pre-effect order; mid-run warns after the plan lines are legal (score phases). `tests/test_console_contract.py` expectations unchanged (check-flow order unchanged); add one warn-after-plan-doesn't-raise test.
2. **Plan-line interleaving — `score()` prints BOTH plan lines** (not the CLI). Order inside `score()`: resolve_scorers → select_summarizers → credential preflight → infeasible warns → [no-scorable-pairs note] → `Store` → `score_plan` → [plan(generate) when `generate is not None`] → plan(score) → generate hook → metrics phase → judges phase → close (finally) → [generation notes | no-scorers note] → done(score) → return.
   - `plan(score): {m} metric(s), {j} judge(s) | {i} item(s) | {t} to run, {a} already scored | {f} infeasible` (pluralize metric/judge/item via a local `_plural`; "infeasible" left unpluralized).
   - `plan(generate)` text is store-free ⇒ new pure helper in generate.py **`generate_plan_text(datasets, selected, summarizers)`**, used by both `run_generate` (refactor its plan line to use it) and `score()` (**lazy function-local import — generate.py line 11 imports from scoring.py ⇒ circular**). `run_generate` and `generate_hook` gain a `print_plan=True` kwarg (default preserves 05c/05d behavior); the CLI `--generate` hook passes `print_plan=False`.
   - scoring.py needs its own one-line `_plural` (cannot import from generate).
3. **`done(score): {c} committed, {d} dropped, {f} failed`**, printed by `score()`: committed = metrics.committed + judges.committed; dropped = metrics.dropped + judges.dropped; failed = judges.failed. Always printed (empty scorer set ⇒ `0 committed, 0 dropped, 0 failed`).
4. **Notes (all exit 0, printed by `score()`):**
   - `note: no committed generations in scope; run 'generate' first` — no `--generate`, scorer set non-empty, `plan.items > 0`, ALL triples missing generation (N from `metrics_result.missing_generation`, total from `metrics_result.items`).
   - `note: N selected items have no committed generation; run 'generate' first` — 0 < N < total (same preconditions).
   - `note: no scorable pairs in scope; nothing scored` — zero feasible **(selection-scoped)** (scorer, dataset-with-selected-entries) pairs, i.e. for every scorer every in-scope dataset is in the infeasible set; scorer set non-empty; printed right after the infeasible warns, BEFORE the plan lines, in all contexts; with `--generate` the generation stage still runs afterward. (Contrast: `infeasible_pairs()` itself is NOT selection-scoped — this check is a new scoped computation.)
   - `note: no metrics or judges selected; nothing scored` — both flag families empty; printed AFTER the plan line(s); with `--generate` the generation stage runs first, then the note. The two "nothing scored" notes are mutually exclusive (empty vs non-empty scorer set); generation notes are suppressed when the scorer set is empty.
5. **Credential preflight:** only judges selected by **explicit name** (non-`*`/non-`[]` tokens from the `--judges` flag value; NOT bare/default/`*`/omitted); `api_key_env` unset or empty ⇒ SpecError `judge '{name}': environment variable '{variable}' is unset or empty` (static, exit 2, pre-store; check `isinstance(variable, str) and os.environ.get(variable) in (None, "")` — same wording as `check_static.py`). Placement: in `score()` pre-effect AFTER resolve_scorers + select_summarizers, BEFORE the infeasible warns (failed preflight exits 2 without warns).
6. **Bare `--metrics` (no tokens):** parser-level error, exit 2 — argparse `nargs="+"` ⇒ `error: argument --metrics: expected at least one argument` (via `_Parser.error`). `--judges` uses `nargs="*"` (bare legal ⇒ `Flag(value="bare")`).
7. **CLI Flag construction:** metrics omitted ⇒ `Flag(no=<--no-metrics present>)`; else `Flag(value=_tokens(args.metrics), no=<--no-metrics present>)` (both present ⇒ resolve_scorers raises the mutual-exclusion SpecError). Judges omitted ⇒ `Flag(no=<--no-judges present>)`; `args.judges == []` or all groups empty ⇒ `Flag(value="bare")`; else the flattened token tuple; `no=True` similarly. `--metrics`/`--judges` repeatable via `action="append"`.
8. **Empty scope:** keep the existing pattern — `note: no entries in scope; nothing to do`, exit 0, before any plan line (mirror `_generate`'s position: after resolve_selection, before validate_config).
9. **CLI `_score` pre-effect order (exit 2 before store/network):** parse (bare `--metrics` ⇒ 2) → `--server-*` without `--generate` ⇒ 2 (keep existing guard, now conditioned on `not args.generate`) → load config → validate_datasets/load_dataset → resolve_selection → empty-scope note+0 → validate_config errors ⇒ 2 → (if `--generate`: select_summarizers [SpecError], args/env JSON, `effective_server_spec`, `EndpointClient`, `ServerCycles`, `generate_hook(..., print_plan=False)`) → build Flags → `score(...)` → return 0. `EndpointClient` + `judge_call` (imported from `.judge_call`) always constructed (judges need them); `ServerCycles` ONLY with `--generate`.
10. **Judge-failure exit 1 path:** already in 06b/06c — just wire the real `judge_call` from `evalapp/judge_call.py` into the CLI call.
11. **Integration test judge path (FINALIZED):** the fixture `--serve` replies `"fake: <user>"` ⇒ zero quality labels ⇒ all 3 qualities missing ⇒ `JudgeParse(rejected=True)` ⇒ judge unit warns + `failed` count (assert fail path + exit 0 + `done(score): … N failed` in integration). Judge SUCCESS stays covered by 06c-style unit tests (real `EndpointClient(transport=fake)` + real parser). **Do NOT extend the fixture** (05d byte-unchanged constraint).

**Doc examples to assert verbatim (docs/commands.md §score):**
```
score --select meetbank * --summarizer std
  plan(score): 4 metrics, 1 judge | 50 items | 250 to run, 0 already scored | 0 infeasible
  done(score): 250 committed, 0 dropped, 0 failed        exit 0
score --no-judges --select qmsum-dev #3-7
  plan(score): 4 metrics, 0 judges | 5 items | 20 to run, 0 already scored | 0 infeasible
score --generate --select meetbank @doc-123 --summarizer std --judges openrouter-llama-3-70b
  plan(generate): 1 summarizer, 1 item, 1 server cycle
  plan(score): 4 metrics, 1 judge | 1 item | 5 to run, 0 already scored | 0 infeasible
  done(generate): 1 committed, 0 skipped, 0 failed
  done(score): 5 committed, 0 dropped, 0 failed          exit 0
score --server-port 8081
  error: --server-* flags require --generate             exit 2
```

**Slices (TDD, red first, commit each green; files `tests/test_score_08*.py`, ASCII-only, `import harness  # noqa: F401` first line where used, fixtures copied verbatim per 06b/06c — zero cross-test imports):**
1. Console guard relaxation (+ warn-after-plan test in `tests/test_console_contract.py`) + parser (nargs/append/new flags; widen `--summarizer/--model/--prompt-template` to `if command in ("generate", "score")`) + `_score` pre-effect exit-2s: bare `--metrics` ⇒ 2, `--server-*` without `--generate` ⇒ 2 (and with `--generate` passes the guard), no+value mutual exclusion ⇒ 2 (exact SpecError text), credential preflight ⇒ 2 (explicit name fails; `*`/bare/omitted pass).
2. Plan/notes/done lines via `score()` unit tests with fake client / real scoring functions / real `Store` / **real `Console`** (proves no assert crash on mid-run warn): metrics-only (docs format), judges-only, bare judges, zero scorers (`--no-metrics --no-judges` ⇒ plan 0/0 + no-scorers note + done 0-0-0), all-missing generations note, partial note (N), no-scorable-pairs note (reference-requiring scorer over reference-less dataset, selection-scoped), mid-run reference warns interleaved after plan.
3. `--generate` two-stage: plan interleaving (plan(generate) before plan(score), hook in between), `generate_plan_text` helper + `print_plan=False` hook (plan(generate) appears exactly once), stage-1 FailFastAbort ⇒ no scoring (assert phases didn't run), 05c/05d behavior preserved (default `print_plan=True`).
4. Resume: re-run skips committed (item, scorer) units, fake client sees no calls on them, remainder only; `to_run`/`already scored` counts correct.
5. Integration via fixture `--serve` (ports ≥18090, one port per server run; 05b owns 18081/9090/7070/8081, 05d used 18090 — pick fresh, e.g. 18100+; TIME_WAIT ⇒ distinct ports per test): score smoke through the real endpoint (plan/done lines byte-exact, exit 0, store rows: metric_evaluations/judge_evaluations/reference_summaries), `score --generate` two-stage end-to-end, judge-reject (failed count, exit 0), judge-500 fail-fast exit 1 naming item+judge (use `--fail-after`), resume-after-partial-failure (re-run on a different port, no calls on committed units).
6. Close 08: all **12** boxes in `issues/08-score.md` + `- 2026-10-28 — implemented: …` under `## Comments` (mention final test count); map Notes → `Done: 01–09, 06a–06c, 07. Open: 10, 11.`; commit `docs(scratch): ticket 08 — close`.

### Ticket 09 (settled 2026-10-28)

Scope: `sweep` — exact `score` semantics including implied generation, over ALL
configured summarizers x all datasets x the resolved scorer set; no selection or
scorer flags (any of the seven families => exit 2 with the byte-exact docs error);
widen-only `--all-metrics/--all-judges/--all`; exit classes 0/1/2 inherited from `score`.

**`evalapp/scoring.py`:**

- New `resolve_sweep_scorers(resolved, all_metrics, all_judges) -> ResolvedScorers(notes=())`:
  metrics: `all_metrics` => `["*"]`; else `defaults["metrics"]` None => `["*"]` (all
  code-registered), present => `_without_empty_bracket(default)` (`[]` => zero, no
  fallback); then `metrics.resolve(tokens)`. Judges: `all_judges` => `["*"]`; else
  default_judges None => `["*"]` (all configured), present =>
  `_without_empty_bracket(default)` (`[]` => zero); then `_select_judge_tokens`
  (unknown name still SpecError). Widen flags force the full set independently =>
  composable/idempotent for free.
- New `_sweep_credential_preflight(resolved, console, judges)`: per name,
  `variable = resolved["judges"][name]["api_key_env"]`; if `isinstance(variable, str)
  and os.environ.get(variable) in (None, "")` => `warn: judge '<name>': environment
  variable '<var>' is unset or empty (judge skipped)` + drop; else keep; returns the
  kept tuple. Runs BEFORE the infeasible warns (score's preflight position); the plan
  counts only kept judges. (Contrast score: explicit `--judges X` unset key => exit 2.)
- Refactor `score()` tail into shared privates (score regression-covered by the
  existing suite, behavior byte-identical):
  - `_pre_effect(resolved, scorers, datasets, selected, console) -> infeasible set`:
    the infeasible pair warns, then the `no scorable pairs in scope; nothing scored`
    note (order as in score today).
  - `_run_score(store_path, resolved, scorers, infeasible, datasets, selected,
    summarizers, console, client, judge_call, generate) -> (plan, metrics_result,
    judges_result)`: Store open, `score_plan`, `plan(generate)` when hook,
    `plan(score)`, the hook, `run_metrics_phase`, `run_judges_phase`, close in
    finally, the `no metrics or judges selected; nothing scored` note when zero
    scorers, the missing-generation notes only when `generate is None`,
    `done(score)`.
- New `sweep(resolved, store_path, all_metrics, all_judges, datasets, selected,
  console, client, judge_call, generate)`: `resolve_sweep_scorers` =>
  `_sweep_credential_preflight` (warn+drop) => `select_summarizers(resolved)`
  (all-None => all configured, config order) => `_pre_effect` => `_run_score`. The
  hook is ALWAYS present (generation implied).

**`evalapp/cli.py`:**

- `_sweep` (replaces the stub): guard FIRST, pre-config: forbidden attrs
  `("select", "summarizer", "model", "prompt_template", "metrics", "judges",
  "generate")`; `if any(getattr(args, n) for n in ...)` => `SpecError("'sweep' takes
  no selection or scorer flags (it is exhaustive); use 'score --generate' to
  narrow")` => `error: ...` exit 2 (byte-exact; bare `--judges` => `args.judges =
  [[]]` truthy => caught). Body mirrors `_score` minus selection: `_load` =>
  `validate_datasets` => `load_dataset` each => `selected = {name:
  list(range(len(ds.entries)))}` => empty-scope => `note: no entries in scope;
  nothing to do` + 0 (before validate_config, as in `_score`) => `validate_config`
  errors => 2 => `EndpointClient` => `select_summarizers(resolved)` => parse
  `--server-args/--server-env` => `effective_server_spec` => `ServerCycles` =>
  `generate_hook(..., print_plan=False)` => `sweep(..., all_metrics=args.all_metrics
  or args.all, all_judges=args.all_judges or args.all, ...)` => 0. Server flags
  already legal (SERVER_COMMANDS has "sweep").
- `build_parser`: sweep subparser gets the seven forbidden flags FOR DETECTION ONLY
  (so every form parses and the guard emits the canonical error): `--select`,
  `--summarizer`, `--model`, `--prompt-template`, `--metrics`, `--judges`
  (all nargs="*" append — bare forms must hit the guard, not argparse),
  `--generate` (store_true); plus the NEW allowed `--all-metrics/--all-judges/--all`
  (store_true). NO `--no-metrics/--no-judges` (argparse generic exit 2; no
  narrowing flags exist).

**Behavior notes:** whole scope committed => `run_generate` pre-scan prints
`note: all N items already committed; server not started` +
`done(generate): 0 committed, N skipped, 0 failed`; the hook never calls
`cycles.ensure` (no spawn). Zero scorers (`default_metrics: []` +
`default_judges: []`) => generate still runs first, then score's note
`no metrics or judges selected; nothing scored` and plan
`0 metric(s), 0 judge(s) | ...`. Message order: warn => plan(generate) =>
plan(score) => done(generate) => done(score). Exit classes: FailFastAbort
(stage-1 generate failure; judge transport/HTTP/empty response) => 1; judge
parse-reject => warn + `failed` count, exit 0.

**TDD slices (red first, commit each green; files `tests/test_sweep_09*.py`;
ASCII-only; `import harness  # noqa: F401` first line; no conftest/cross-test
imports; helpers copied verbatim from the 08 files):**
1. Parser: every forbidden flag form => exact error + exit 2; the three widen flags
   accepted; `--no-metrics` => argparse exit 2.
2. Scorer-set units: `resolve_sweep_scorers` (default present-exact / `[]`-zero /
   absent-all / widen / idempotent) + credential warn+drop via in-process CLI.
3. Orchestration units (helpers from `test_score_08_lines.py`): message order,
   no-spawn note when all committed, infeasible warns, zero-scorers note,
   plan(resume) counts.
4. Integration (fixture `--serve`, ports >=18112, one port per server run): sweep
   smoke (24 items; verify byte-exact counts via a throwaway smoke run FIRST, then
   assert observed), re-sweep no-spawn, judge parse-reject failed count, store row
   counts via `Store.table_counts()`.
5. Close 09: 8 boxes + `- 2026-10-28 — implemented: ...` (final test count) in
   `issues/09-sweep.md`; map Notes => `Done: 01–09, 06a–06c, 07. Open: 10, 11.`;
   commit `docs(scratch): ticket 09 — close`.
