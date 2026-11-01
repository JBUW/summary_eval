# 15: One scoring run shrinks the scoring interface

**What to build:** `evalapp/scoring.py` passes one frozen `ScoringRun` to its phases in place of 7–11 repeated parameters, and the injected endpoint client is the only test seam. Today `score_plan`, `run_metrics_phase` and `run_judges_phase` each receive store, resolved, scorers, infeasible, datasets, selected, summarizers, console and inputs; `score` (11 parameters) and `sweep` (10) add `judge_call` and the generate hook; three 06b tests replace all three phases with fakes; `score_metrics` is called only by its own test; `cli._score`/`cli._sweep` select the summarizers a second time to build the generate hook.

**Blocked by:** none

**Status:** ready-for-agent

- [x] `ScoringRun` (frozen dataclass, `scoring.py`) holds store, resolved, scorers, infeasible, datasets, selected, summarizers, inputs (`SummarizerInputsCache`) and console; `_run_score` builds it after it opens the store. No GLOSSARY.md entry (code type).
- [x] Phases: `score_plan(run)`, `run_metrics_phase(run)`, `run_judges_phase(run, client)`.
- [x] The `judge_call` parameter is removed from `score`, `sweep`, `_run_score` and `run_judges_phase`; the judges phase calls `judge_call` directly. Tests fake only the endpoint client (as 06c does).
- [x] `score(loaded, store_path, metrics_flag, judges_flag, summarizer_selection, console, client, generate=None)` and `sweep(loaded, store_path, all_metrics, all_judges, console, client, generate)` read `resolved`, `datasets` and `scope` from the `prepare.Loaded` fields; `scoring` does not import `prepare`.
- [x] The generate hook is `generate(run)` and reads store, console, inputs, resolved, datasets, selected and summarizers from the run; `generate_hook(client, cycles)` binds only those two and has no `print_plan` (`run_generate` keeps its own). `cli` no longer selects summarizers for the hook; `generate.py` does not import `scoring`.
- [x] `score_metrics` and `tests/test_score_metrics.py` are deleted; any assertion with no other coverage moves to a `score()` test.
- [x] Tests: the three 06b tests that patch `score_plan`/`run_metrics_phase`/`run_judges_phase` are replaced by tests that run the real `score()` with a fake endpoint client and check the store and the console lines. The direct phase tests (`test_metrics_phase.py`, 06b, 06c) stay with the new signatures via a small run-building helper. The `FakeJudge` tests move to a fake client. The 05c test of the hook's default `print_plan=True` changes to match.
- [x] No doc changes (the docs do not name `judge_call`, the hook or the phases); only docstrings change. The `dropped` question stays in the map Fog; `dropped` is unchanged.

## Comments

- 2026-11-01 — implemented (71ecaec): `ScoringRun` in `scoring.py`; phases `score_plan(run)`, `run_metrics_phase(run)`, `run_judges_phase(run, client)`; `score`/`sweep` take `prepare.Loaded`; `generate_hook(client, cycles)` returns `generate(run)`. Test helper `harness.scoring_run`. The 06b judge tests use a fake endpoint transport; since the parser rejects partial answers by default, the happy-path row now has three values (was `(0.9, 0.8, None)`). The metric-failure test swaps one `metrics._REGISTRY` entry instead of patching a phase. `test_score_metrics.py` deleted: its two checks are covered by `test_spec_error_raises_before_store_created` and the new orchestrator-order test. Non-sockets suite: 563 passed, 1 known environmental failure (proxy 403); sockets suite: same 16 baseline environmental failures.
