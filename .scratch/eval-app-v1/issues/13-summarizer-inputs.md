# 13: The summarizers module owns the summarizer inputs

**What to build:** One module, `evalapp/summarizers.py`, answers "what are the generation-identity inputs of this summarizer": the model hash, the loaded prompt template, and the template hash. Today `generate._load_surface` and `scoring._item_surface` are copies of the same code, and the four-part key (model, `model_args`, template, `gen_params`) is written out five times across `generate`, `scoring` and `check_live`. The copies are deleted; `generate`, `score`, `sweep` and `check` use the module.

**Blocked by:** none

**Status:** ready-for-agent

- [x] `Summarizer.key` is the only builder of the four-part key; the copies in `generate`, `scoring` (three inline) and `check_live` are deleted.
- [x] `SummarizerInputs` holds (model hash, prompt template, template hash); `_load_surface` and `_item_surface` are deleted. No "surface" names remain.
- [x] A cache object in `summarizers.py` returns the `SummarizerInputs` of a summarizer. It caches the model hash by model and the template (with its hash) by template, so summarizers that share a model hash its file once. Callers build no keys.
- [x] The model file is hashed in chunks and never held whole in memory; the model hash value is unchanged (sha256 of the file bytes, docs/store-schema.md).
- [x] `store.upsert_model` takes the model hash instead of the model bytes; its callers and tests pass a hash.
- [x] `_run_score` creates one cache per command and passes it to the plan, generate, metrics and judges steps (`score` and `sweep`); the `generate` command creates its own. Each model file is read at most once per command.
- [x] `check_live` uses `Summarizer.key` for probe deduplication and loads templates through the cache without reading model files; a template read error names the template, not the summarizer.
- [x] Tests: the model-file read error test (`tests/test_metrics_phase.py`, "file not found") moves to a test of the module; one test asserts that summarizers sharing a model read its file once per command.

## Comments

- 2026-10-31 — implemented (b37a889): `Summarizer.key` (also replaces a sixth copy in `select_summarizers`), `SummarizerInputs`, `SummarizerInputsCache` (model hash per model, chunked; template per template) in `evalapp/summarizers.py`; `_load_surface`/`_item_surface` deleted; `_run_score` shares one cache across plan, generate hook, metrics and judges (phases and `run_generate` take `inputs=None` → own cache); `store.upsert_model(sha, …)`; `check_live` uses `named_summarizer` (was `_named`) + `Summarizer.key` + `cache.template()`. Tests: model-file error and template-name error moved to tests/test_summarizers.py, chunked-hash value test, read-once-per-command test (tests/test_score_08_generate.py; fails with 2 reads if a phase builds its own cache). 565 non-sockets tests green (one pre-existing proxy 403 failure); the sockets suite in an LF worktree shows the same 16 environmental failures as the baseline
