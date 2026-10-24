# 03: Metrics registry + v1 metrics

**What to build:** The codebase itself becomes the metric catalog: metrics are registered by automatic discovery (importing a metric module registers it; no decorator list, no central registry file to maintain) and any registered metric is invocable by name whether or not it appears in the configuration. Each metric is a frozen spec — name, reference requirement, single-scalar value contract — validated in one assembly-time pass, and each v1 metric is proven by hand on small, manually calculated examples, including its exclusion path.

**Blocked by:** 1 (Scaffold: executable, console contract, selection grammar)

**Status:** ready-for-agent

- [ ] Registration by import discovery; no decorator list, no central registry file; one assembly-time validation pass validates every registered metric's spec.
- [ ] Each metric produces exactly one scalar value; its spec (name, requires-reference flag, value contract) is frozen.
- [ ] A metric that cannot produce a value for an input is an exclusion, not a stored row.
- [ ] All five v1 metrics exist: faithfulness (no reference), key_claim_completeness (reference required), conciseness_length_proxy (no reference), structural_instruction_check (no reference, always runnable), and the internal-consistency metric (optional, low yield, first to cut).
- [ ] Every metric has unit tests on small, manually calculated examples — inputs and expected scalar outputs verified by hand, no model and no store involved — including the exclusion path (an input for which the metric cannot produce a value).
- [ ] A registered metric is invocable by name (or `*`) whether or not it appears in the configuration.

## Comments
