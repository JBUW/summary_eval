# 13: The summarizers module owns the summarizer inputs

**What to build:** One module, `evalapp/summarizers.py`, answers "what are the generation-identity inputs of this summarizer": the model hash, the loaded prompt template, and the template hash. Today `generate._load_surface` and `scoring._item_surface` are copies of the same code, and the four-part key (model, `model_args`, template, `gen_params`) is written out five times across `generate`, `scoring` and `check_live`. The copies are deleted; `generate`, `score`, `sweep` and `check` use the module.

**Blocked by:** none

**Status:** ready-for-agent

- [ ] `Summarizer.key` is the only builder of the four-part key; the copies in `generate`, `scoring` (three inline) and `check_live` are deleted.
- [ ] `SummarizerInputs` holds (model hash, prompt template, template hash); `_load_surface` and `_item_surface` are deleted. No "surface" names remain.
- [ ] A cache object in `summarizers.py` returns the `SummarizerInputs` of a summarizer. It caches the model hash by model and the template (with its hash) by template, so summarizers that share a model hash its file once. Callers build no keys.
- [ ] The model file is hashed in chunks and never held whole in memory; the model hash value is unchanged (sha256 of the file bytes, docs/store-schema.md).
- [ ] `store.upsert_model` takes the model hash instead of the model bytes; its callers and tests pass a hash.
- [ ] `_run_score` creates one cache per command and passes it to the plan, generate, metrics and judges steps (`score` and `sweep`); the `generate` command creates its own. Each model file is read at most once per command.
- [ ] `check_live` uses `Summarizer.key` for probe deduplication and loads templates through the cache without reading model files; a template read error names the template, not the summarizer.
- [ ] Tests: the model-file read error test (`tests/test_metrics_phase.py`, "file not found") moves to a test of the module; one test asserts that summarizers sharing a model read its file once per command.

## Comments
