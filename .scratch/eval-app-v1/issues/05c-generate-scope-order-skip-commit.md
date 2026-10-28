# 05c: `generate` — scope, order, skip, commit

**What to build:** `generate` becomes a real command for its happy path: selection → deterministic item order → pre-scan skip → per-item atomic commit. No selection flags ⇒ full scope (all configured summarizers × all configured datasets × all entries); component selections form a Cartesian product with named summarizers added as extra single combinations; an already-committed item is skipped with no model call; each item commits as one complete-or-absent unit, and a fully committed scope exits 0 without ever starting a server. Fail-fast and resume behavior are the next ticket (05d).

**Blocked by:** 1 (Scaffold: executable, console contract, selection grammar), 2 (Configuration + datasets; `check` static phase), 4 (Store, identities, and `clear`), 05a (Endpoint client), 05b (Model server lifecycle)

**Status:** ready-for-agent

Series note (05a–05d): ticket 05 (Endpoint client, model server lifecycle, `generate`) is split into these four parts; implement them in sequence, each self-contained and committing on its own.

- [x] No selection flags ⇒ full scope (all configured summarizers × all configured datasets × all entries); `--summarizer`, `--model`, `--prompt-template` are repeatable and take `*`; component selections form a Cartesian product, and named summarizers are added as extra single combinations.
- [x] Item order is deterministic — summarizer → dataset → entry, in configuration/file order; the loaded model may only affect attempt scheduling, never the identity of what runs.
- [x] Pre-scan before any call: committed generations are looked up by identity; an already-committed item is skipped with no model call and counted; whole scope committed ⇒ exit 0 without spawning the server, with `note: all N items already committed; server not started`.
- [x] Commit unit = one item (entry × summarizer): upserts of `transcripts`, `reference_summaries` (when the dataset declares `reference_field`), `models`, `prompt_templates`, plus the `generations` INSERT, all in one transaction — complete-or-absent, a crash loses at most one unit; committed generations are terminal, never re-rolled.
- [x] `generate` never invokes judges or metrics and never reads reference summaries for scoring (it does upsert reference summaries when the dataset declares a reference field, so scoring can commit in its own transactions).
- [x] The dataset R1 load-time contract (fail-fast, exit 2, file + line) governs generate inputs; a failure aborts before any call.
- [x] Line formats match the docs exactly: `plan(generate): 1 summarizer, 3 items, 1 server cycle`; `done(generate): 3 committed, 0 skipped, 0 failed` (and `done(generate): 0 committed, 3 skipped, 0 failed` on the all-committed path).
- [x] Unit tests run through the fake endpoint client (05a): scope expansion, deterministic order, pre-scan skip, and per-item commits are asserted as external behavior — no real server, no network.

## Comments
- 2026-10-27 — split from ticket 05 (Endpoint client, model server lifecycle, `generate`) into 05a–05d.
- 2026-10-28 — implemented: generate CLI wiring — selection expansion (full scope / Cartesian / named summarizers), deterministic order, pre-scan skip with all-committed short-circuit (exit 0, server not started), per-item complete-or-absent commit; lazy per-cycle prevalidation at first spawn; plan-line contract; 478 tests green via bin/check
