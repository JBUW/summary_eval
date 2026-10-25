# 03: Metrics registry + v1 metrics

**What to build:** The codebase itself becomes the metric catalog: metrics are registered by automatic discovery (importing a metric module registers it; no decorator list, no central registry file to maintain) and any registered metric is invocable by name whether or not it appears in the configuration. Each metric is a frozen spec — name, reference requirement, single-scalar value contract — validated in one assembly-time pass, and each v1 metric is proven by hand on small, manually calculated examples, including its exclusion path.

**Blocked by:** 1 (Scaffold: executable, console contract, selection grammar)

**Status:** ready-for-agent

- [x] Registration by import discovery; no decorator list, no central registry file; one assembly-time validation pass validates every registered metric's spec.
- [x] Each metric produces exactly one scalar value; its spec (name, requires-reference flag, value contract) is frozen.
- [x] A metric that cannot produce a value for an input is an exclusion, not a stored row.
- [x] All five v1 metrics exist: faithfulness (no reference), key_claim_completeness (reference required), conciseness_length_proxy (no reference), structural_instruction_check (no reference, always runnable), and the internal-consistency metric (optional, low yield, first to cut).
- [x] Every metric has unit tests on small, manually calculated examples — inputs and expected scalar outputs verified by hand, no model and no store involved — including the exclusion path (an input for which the metric cannot produce a value).
- [x] A registered metric is invocable by name (or `*`) whether or not it appears in the configuration.

## Comments
- 2026-10-25 — implemented: evalapp/metrics registry (pkgutil import discovery, passive registration list, single assembly-time validation pass, resolve by name/`*` with first-occurrence dedupe) plus the five v1 metrics (faithfulness, key_claim_completeness, conciseness_length_proxy, structural_instruction_check, internal_consistency), each a frozen spec with a pure compute, exclusion = None, and its algorithm documented in the module docstring; 6 new test files, 94 tests green via /usr/local/py-utils/bin/pytest.
