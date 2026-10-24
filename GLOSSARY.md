# LLM Summary Evaluation

Domain language for the evaluation program that measures the quality of LLM-generated summaries produced from conversation transcripts under written prompt templates. The word "report" belongs to the `report` command (the performance roll-up), not to the artifact.

## Language

**Local model**:
A model served on the project's own hardware (the starting machine with the AMD Radeon 8060S, the MacBook, or a future GPU server), as opposed to a third-party API.
_Avoid_: on-device model, edge model, small model

**Hosted model**:
A model accessed through a third-party API, used as the strong comparison baseline.
_Avoid_: cloud model, API model, big model

**Endpoint**:
The HTTP service through which the program talks to a single model. It is the only interface the program uses for generation and judging; the config (the `server` section for the model under test, the endpoint fields for judges) is the only place where serving details (engine, backend, launch command) are allowed to exist.
_Avoid_: server, backend, model

**Scorer**:
The umbrella term for the two kinds of scorer: a **metric** (code-registered, algorithmic) and a **judge** (config-defined, LLM-based). It names the shared role — "something that produces evaluation rows for committed generations" — and never appears in user-facing counts: a plan line says `4 metrics, 1 judge`, never `5 scorers`.
_Avoid_: evaluator, referee

**Judge**:
A config-defined LLM scorer, addressed as a bare endpoint profile: endpoint URL, the `model_name` pin, optional credential by environment-variable name. The app does not spawn, monitor, or stop a judge. Identity = the hash of its config definition (model name, `gen_params`, rubric texts, `requires_reference`); the endpoint is out of the identity — an access address, refreshable: the same judge model at another URL is the same judge. One call scores several qualities at once. A judge with `requires_reference` on is never called without a reference summary — the code guarantees it. Self-judging (pointing a judge at the app's own spawned server) is a misconfiguration, not a supported mode: there is exactly one app-owned server, and it serves the model under test.
_Avoid_: evaluator, referee, second model

**Rubric**:
The judge's scoring instrument, written out verbatim in the `judges` table at commit time: `system_content` + `user_template` binding the qualities to be scored (v1 set: factual correctness, completeness, conciseness) to the transcript and the summary under judgment. The rubric is part of the judge's identity — not a versioned prompt file. Placeholders: `{transcript}` and `{summary}` are mandatory; `{reference}` is meaningful iff `requires_reference` is on; rendering substitutes a placeholder only when its value is available, and unrecognized or non-applicable placeholders pass through as literal text. `check` validates placeholder presence statically.
_Avoid_: scorecard, criteria list, judge model, prompt file

**Metric**:
An algorithmic scorer only — a judge is not a metric (terminology rule, 2026-10-16). Defined in code and registered by automatic discovery: metric modules are imported and registered at startup (no decorator, no list maintenance); code defines, config selects. `default_metrics` is optional in the config; absent ⇒ all registered metrics, an explicit `[]` ⇒ deliberately zero. A metric produces, per (generation × chosen reference-or-null), a single scalar, stored in `metric_evaluations` under its bare registry name. Identity is the registry name: no per-metric version, no commit pinning. `requires_reference` is declared at registration.
_Avoid_: scoring method, measure, judge, scorer

**Quality**:
A stable quality dimension a judge is asked to score — v1 set: factual correctness, completeness, conciseness (the `judge_evaluations` column names). A quality is what a judge value's label refers to; it is never itself a scorer, and scores are never collapsed into a composite in v1. Interpretability and presentation of the multi-value judge result are out of scope (2026-10-08b cut); the deferred unit is where a summary makes or withholds quality claims.
_Avoid_: dimension, criterion, metric, score, axis

**Score**:
One number in an evaluation row: a metric's `value` (NOT NULL — a metric that cannot produce a proper value is an exclusion, not a row) or one nullable judge quality (a partially parsed judge response lands with the values that came through; a response with no usable value is a recorded exclusion, never a row). Identity and provenance live on the evaluation row, not on the score.
_Avoid_: metric, result, rating

**Preflight**:
The verification pass executed before a command commits to items. `generate`: poll `GET /props` until the server reports running, then one trivial completion against the model under test. Scoring commands: a rubric-parse probe per judge in scope (one trivial completion, the rubric rendered with placeholder example values only, the real parser under the `ACCEPT_PARTIAL_RESULTS` policy). `check`: the static phase, plus the opt-in `--probe-judges` (the only preflight action with external cost). The probe guards the systematic (a judge cannot answer the rubric at all); the per-item recorded exclusion guards the incidental (a judge fails on one item). Any preflight failure aborts before items are processed, with context, no retries.
_Avoid_: dry run, sanity check, warmup

**Trust boundary**:
The point where untrusted input enters the program's otherwise deterministic processing. In v1 there is exactly one: the judge's raw response text (transcripts, summaries, config, and prompt templates are curated or app-generated). Consequence: runtime validation is proper only here — the relaxed parse policy (warning + recorded exclusion, or partial acceptance per the `ACCEPT_PARTIAL_RESULTS` switch) exists because this input is genuinely untrusted; the same validation firing on internally-originated data is a missing test to fix in development, not a runtime condition.
_Avoid_: input validation, schema check, guard

**Seam**:
A deliberately narrow, replaceable boundary between two parts of the program where one side can be faked or substituted without editing the other. Placement rule: seams go where trust changes (the pure parse function between raw judge text and structured values) or where a dependency is external or expensive (the injected endpoint client between the program and the network). This is what makes metrics unit-testable without a model: tests exercise everything up to the seams; a judge's judgment itself is never unit-tested.
_Avoid_: interface, API, abstraction layer

**Golden set**:
The curated, documented subset of a dataset — transcripts with, where the dataset provides them, reference summaries — on which all candidates are evaluated and compared. Which dataset, how many items, and the stratification criteria are curation-time data decisions (Q3), not architecture.
_Avoid_: test set, benchmark set, sample

**Summarization**:
The task under evaluation: the model under test producing a summary from a transcript under a prompt template. In the control flow it is the `generate` stage: spawn → readiness → preflight → per-item committed generation → clean stop. It is the only stage that requires the model server to be alive; the scoring commands read committed store rows, never the live server. Distinct from Performance (what is optimized) and from the `report` command's roll-up.
_Avoid_: inference, completion, pipeline step, summary (the artifact), report (the roll-up command)

**Pooling**:
Combining evaluation rows across summarizers and commands into one comparison — in v1, what the `report` command does: it queries the store and aligns generations and scores across candidates. There is no mechanical gate: mixing rows produced under different metric code is an accepted PoC limitation (metric identity = registry name only; no version or commit is stored). The `clear` command is the human separation discipline (a hardware or code change ⇒ a clean slate, Q10), and the `updated_at` columns are the external-fix instrument. Revisit trigger: the first request to distinguish code versions in stored results.
_Avoid_: merging, aggregation, run

**Summarizer**:
A configured candidate: exactly four components — model + `model_args` + prompt template + `gen_params`. A summarizer may inherit components from another via `base` (copy-then-override; the model file may not be overridden). The prompt template describes how an input transcript becomes the exact message (system + user content) sent to the model — it is not the literal sent prompt. The unit the search explores; generation records are keyed by (transcript × summarizer). The server binds per distinct (model, `model_args`), not per summarizer — several summarizers may share one server. "Candidate" remains the search-status word, not the identity.
_Avoid_: combination, config, variant, setup, candidate (that is a summarizer's search status, not its identity)

**Meta-strategy**:
An orchestration policy that automates the search: decides which (transcript × summarizer) work to request next under a time budget, reading the continuously updated store. **PARKED (2026-10-17):** no such command ships in v1; `tune` is addable later as a thin subcommand — the store design already supports it (per-unit commits, skip-on-rerun, intermediate results readable).
_Avoid_: scheduler, workflow, pipeline

**Generation record**:
The store row committed by `generate`, one per (transcript × summarizer): the summary text verbatim + its **generation identity** (the input-addressed primary key: the hash of what went in — so the row can be looked up before the model is called). No cost or provenance-snapshot columns; the row stands alone — scoring works after the model server is gone (Q17b). Renamed from "report record" (2026-10-12, Q17c0); the artifact word later drifted to "summary" (see Summary).
_Avoid_: report record, output row

**Generation identity**:
The primary key of a generation record: the sha256 of the canonical JSON of (transcript identity, model identity, `model_args`, template identity, `gen_params`) — input-addressed, so the same (transcript × summarizer) is one row, found by lookup before any model call. Referenced as a foreign key by every evaluation row scoring that generation.
_Avoid_: report identity, key, fingerprint

**Summary**:
The produced artifact: the text a model under test generates from a transcript under a prompt template; the unit that is scored. The dataset's reference artifact is a **reference summary** — the corpus's word "summary" is origin metadata, not project vocabulary. The performance roll-up is not a summary: it belongs to the `report` command. Reserved for the artifact sense: the store row is a **generation record**, the task is **Summarization**.
_Avoid_: report (that is the roll-up command), summarization, output, record

**Performance**:
The measured quality of a candidate summarizer: its scores per metric and quality, aggregated across transcripts. What the search optimizes. The roll-up itself — coverage (n scored / n excluded by reason), means with their n, comparison views aligning transcripts across candidates — is produced by the `report` command from store rows, never from a live endpoint; strictly descriptive in v1.
_Avoid_: summarization, score (one value for one item), quality (a property a judge scores), throughput

**Provenance**:
The self-describing metadata a store row carries, so that a row is readable with no external context. Reconstruction-first philosophy: the store holds as much as reasonably possible that could be used to reconstruct a generation or its evaluations, with as little external dependency (config, dataset) as possible; reasonableness is lost by object size, availability, or security — in which case the exclusion is mitigated by a purely decorative name column. The standing exclusions: credentials → the environment-variable name; model files → the content hash; metric implementations → the code-registry name; prompt templates and judge definitions → written out verbatim in their own tables. There is no app git commit and no dataset hash in any row — dataset origin lives in the courtesy `dataset_name`/`entry_id`/`entry_index` columns, and server launch arguments are never stored.
_Avoid_: metadata, lineage, manifest (retired)

**Store**:
The logical set of committed work-request outcomes under committed identities. v1 realization: one SQLite file with the eight tables of `docs/store-schema.md`. The store is both the source of truth and the index — there is no separate index object; the skip-on-rerun pre-scan (a lookup by identity before any expensive call) is the entire recovery logic. Contract: append-only, complete-or-absent, write-once (reuse by lookup); storage of outcomes is authoritative, not a cache. A schema mismatch is a pre-effect failure (exit 2) — no migration; `clear` is the only sanctioned reset. At most one active app instance per store (Q17g). Courtesy columns are last-seen-wins and are never resolved; the `updated_at` stamp rule records when a row's non-identity values were last seen in a different form — an external-cleanup aid, not a last-use timestamp.
_Avoid_: database (that is the medium), cache, ledger

**Commit**:
The single atomic point where one unit's outcome becomes a durable visible fact. One transaction per unit: a `generate` unit = the upserts of its `transcripts`/`models`/`prompt_templates` rows + the `generations` INSERT; a scoring unit = the upsert of its `reference_summaries` row (where one is used) + the evaluation INSERTs. Three jobs: (1) atomicity — complete-or-absent to any reader; (2) timing — end of the unit, after the LLM call(s) and validation; a crash earlier means it never happened (≤1 unit lost); (3) terminality — write-once, never re-rolled; a re-run finds committed units by lookup and skips them. The `updated_at` stamp is the sole post-commit trace.
_Avoid_: git commit, checkpoint, flush
