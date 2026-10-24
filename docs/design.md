# Phase 0 Design

The Phase 0 design: how the settled decisions fit into an implementable system.

This is not a decision record: decisions live in `.scratch/grill-with-docs/DECISIONS.md`. Normative shape lives in four places, and this document only cross-references them — `docs/store-schema.md` (the results store), `docs/config.md` (the configuration file), `docs/commands.md` (the subcommands), and `docs/adr/0001-app-owned-model-server.md` (server ownership). It introduces no new CLI strings and no new schema; where this document and one of them disagree, those four documents govern.

House rule: any decision that changes the design updates this file in the same round as the log entry.

## 1. Purpose & scope

The application is a working proof-of-concept answering one question: which **summarizer** — the four-tuple of model, `model_args`, `gen_params`, and prompt template — summarizes texts best, while staying mindful of the cost (in time and LLM calls, judges included) of producing and scoring summaries.

It is a single executable with six subcommands — `check`, `generate`, `score`, `sweep`, `report`, `clear` — whose full contracts (selection grammar, flags, message prefixes, exit codes) are in `docs/commands.md`. In v1 terms:

- **generate** produces summaries for selected transcripts × selected summarizers, committing each unit as it completes, so an interrupted run resumes by skipping committed work.
- **score** scores committed generations with registered metrics and configured judges; it can imply the missing generations.
- **sweep** is the exhaustive wide net: all configured summarizers × all configured datasets × the resolved scorer set, never dependent on prior state.
- **report** rolls store rows up into performance summaries (strictly descriptive in v1).
- **check** is the cheap sanity pass before spending calls (its live phase spawns only the local server — no external/paid calls by default); **clear** is the only sanctioned reset of the store.

The v1 boundary is deliberately narrow: one active instance per store at a time (section 5), no dataset conversion (section 6), corpus choice out of scope (sections 6, 10), and hardware assumed, not detected (section 2).

**Implementation language.** Python 3 (3.14 or later), venv. The v1 interface is a CLI built on stdlib `argparse`; no application or CLI framework is used. No constraint on third-party libraries; the only recorded dependency constraint is Q16a6's metric-path revisit trigger.

## 2. Hardware & launch

### 2.1 Working hardware

The starting machine has an AMD Radeon 8060S with 32 GB of unified memory, and v1 must run 4-bit quantizations of ~27B models on it (Gemma 3 27B class; the 2026-10-21 smoke test picked `google/gemma-3-27b-it-qat-q4_0-gguf` — full GPU offload with no additional model arguments, readiness 8–10 s — and an 8B model is kept for development). Later targets, in order: a MacBook Pro with 48 GB of unified memory, then a local GPU server with more.

### 2.2 Framebuffer allocation (a human step)

On a unified-memory machine, the graphics memory a model can use is a carve-out that the operator must size (and make persist). Allocating the framebuffer large enough for the chosen model + parameters is a **human step performed outside the application**, before it is used. The application neither detects nor manages the carve-out: if it is too small, the server fails to come up and `generate` fails fast (exit 1) with the server's last output lines.

### 2.3 Hardware-agnostic stance

v1 is not hardware-aware: no device detection, no per-device code paths, no device metadata in the store. Unsuitable model + parameter combinations surface as clear failures, and after a hardware change it is a **human responsibility** to start from a clean slate: `clear` the store and update the launch profile in the configuration. The revisit trigger for hardware-awareness is the first run on another device (ADR 0001).

### 2.4 Custom build; binary identity is informational

The working llama.cpp build is custom-compiled (ROCm/HIP), so the application does not assume an official release. The build it talks to is observed via `/props` at spawn time and treated as **informational**: printed for the operator, never stored, never part of any identity.

### 2.5 `model_args` vs `server.args`

Two kinds of server arguments exist, and they are asymmetric by design:

- **`model_args`** describe the model and affect its output. They are part of the summarizer's identity, stored with every generation record, and resolve in two stages (summarizer definition overrides model definition; absent in both ≡ `{}`).
- **`server.args`** describe the launch (threads, device flags, …). They are launch plumbing: never stored, never layered into `model_args`, never part of any identity. Keeping output-affecting arguments out of `server.args` is the operator's discipline; the application does not police it (field contracts in `docs/config.md`).

## 3. Model server lifecycle

The application owns the model server — rationale and boundary in ADR 0001; this section fixes the runtime flow.

### 3.1 Launch profile

A **launch profile** is the fully resolved spawn specification of one server cycle: `server.command` + `server.args`, the model file path, the resolved `model_args`, port, environment, and startup timeout. It is determined entirely by configuration and command line — never read from the store — and an absent `server` section makes `generate` fail (exit 2): there is no fallback.

### 3.2 One server at a time; one cycle per distinct `(model, model_args)`

`generate` groups its planned work by distinct resolved `(model, model_args)` pairs and runs **one server cycle per pair**, sequentially; at any moment exactly one server is alive. Each cycle:

1. **Pre-spawn validation** — binary present, model file present, port free (a busy port is refused, exit 2; a foreign server is never adopted).
2. **Spawn** the cycle's launch profile.
3. **Readiness poll** on `GET /props`, bounded by the startup timeout.
4. **Preflight** — one trivial completion proving the loop works end to end.
5. **Run** the cycle's planned generations, committing each unit to the store as it completes (section 7).
6. **Clean stop** before the next cycle starts; the port is reused across cycles.

Ordering is deterministic (summarizer → dataset → entry, each in configuration/file order); the model already loaded in the server may be used to schedule work for time efficiency, but it never changes what is computed. Work committed in the store is pre-scanned by identity and skipped before any expensive call; if the whole scope is already committed, the command exits 0 without spawning anything.

### 3.3 Failures; no persisted server log in v1

Failures are fail-fast (exit 1): a server that does not come up, a failed preflight, or a model that rejects its parameters aborts the run, and the last ~20 lines of the server's output are printed to the console. That console output is the record: **no server log is persisted in v1**. Persisting one (e.g. beside the store file) is a re-openable decision, not a v1 commitment.

## 4. Judge separation

Judges are a different kind of thing from the model under test, and the architecture keeps them apart:

- A judge is a **bare endpoint profile** (URL, `model_name` pin, credential by environment-variable name, optional `gen_params`, rubric texts with placeholders). The application never spawns, monitors, or stops a judge; a judge endpoint must exist when the app runs.
- A judge's identity is the hash of its scoring-relevant fields — model name, `gen_params`, rubric texts, `requires_reference` — **not** the endpoint, name, or credentials: the same judge model at another URL is the same judge.
- Judges get the same preflight discipline as the tested model, adapted: a **rubric-parse probe** (one trivial completion of a placeholder-example rubric, parsed with the real parser) before any judging work is planned.
- **Self-judging** — pointing a judge at the application's own spawned server — is a misconfiguration, not a supported mode. The application does not reserve the port or otherwise make it impossible; nothing in the architecture depends on it being impossible. (A legitimate *local* judge is a different matter — see the zero-change path below.)
- A local judge on the same machine is a **zero-change path**: run `llama-server` manually, point the judge endpoint at it, set a dummy credential variable (see Notes in `docs/commands.md`).

The parked extension is a first-class judge lifecycle: judges with their own launch profiles and their own lifecycle unit, managed independently of the tested-model server and never sharing its mechanism (section 11).

## 5. Concurrency

v1 assumes at most one active instance per store — no lock or pid files, only SQLite's own file locking — so concurrent instances can double-spend work but never corrupt the store (first committed result wins; a differing re-sighting only stamps `updated_at`).

## 6. Data layer

The application is **corpus-agnostic** (which corpora it is pointed at is a curation-side fact, section 10) and a **validator, not a converter**: datasets arrive already in canonical form (CSV or JSONL, with the relevant fields named in the configuration — `docs/config.md`), and no evaluation run ever performs a conversion. Conversion tools may or may not live in this project; if they do, they are separate from these commands.

Two standing rules cover everything the loader does:

- **R1 — load-time contract failures are final** (exit 1): configured fields missing, entries structurally malformed, or a dataset mixing named and unnamed entries. Text-length limits are *not* checked at load time in v1; fit is instead surfaced by `check`'s context-adequacy probe (warning) and by `generate` failing fast (exit 1) if a model rejects a prompt.
- **R2 — per-entry reference absence is not an error.** Scoring drops the pairs that cannot be scored (warning); a scope with zero scorable pairs prints the note "no scorable pairs in scope; nothing scored" and exits 0.

Datasets do not exist in the store by name: the store holds the texts themselves (plus courtesy `dataset_name`/`entry_id`/`entry_index` columns), so it stays valid if the datasets on disk change or disappear (`docs/store-schema.md`).

## 7. Store & commit

The normative shape — one SQLite file, eight tables, hash-identity primary keys, courtesy columns, the `updated_at` stamping rule — is `docs/store-schema.md`. The design commitments that doc does not narrate:

- **Reconstruction-first.** The store holds as much as reasonably possible of everything a generation or its evaluations used, with as little external dependency (config, dataset) as possible. Reasonableness is lost by object size, availability, or security — credentials stay as environment-variable names, model files as content hashes, metric implementations as registry names — and each such exclusion is mitigated by a purely decorative name column.
- **Complete or absent; write-once.** A store either exists with the full schema or does not. Any command that may write opens or bootstraps it through the shared path (`check` is read-only unless told to create it); a schema mismatch is a pre-effect failure (exit 2) — never migrated. `clear` is the only sanctioned reset.
- **Commit.** One transaction per unit — a generation unit or a scoring unit — at the end of the unit, after the LLM call(s) and validation. Its three jobs: atomicity (complete-or-absent to any reader), timing (a crash earlier means the unit never happened; at most one unit is lost), and terminality (write-once, never re-rolled). Re-running any command is therefore **recovery, not repetition**: committed units are found by lookup and skipped before any expensive call.
- **The store is the index.** There is no separate index object, no manifest file, no run directories: the skip-on-rerun pre-scan over the store's own rows is the entire recovery logic.
- **Filename.** The canonical default store filename is `store.db`; it governs when the configuration is silent (documented in `docs/store-schema.md` Conventions and the `store` section of `docs/config.md`). Every documentation example uses the store named by the normative example configuration (`evalstore.sqlite3`), so sample outputs match what running the shipped `config.json` actually prints.

## 8. Metrics & judges

**Mechanism.** Metrics are discovered automatically: importing the metric package at startup registers them — no decorator, no hand-maintained list. Each metric is a frozen `MetricSpec` (name, reference requirement, value contract); all validation happens in a single assembly-time pass, so metric classes carry no validation logic of their own. Instances are built once per run with their dependencies (store access, judge endpoints) injected.

Metric values are vectors of computed scalars; how those vectors are interpreted or presented is out of scope (section 12). Per-item value validation is deliberately **relaxed**: an improper value is logged (`warn:`), recorded as an exclusion, and kept out of the vector and any aggregation — it never aborts the run. Assembly- and configuration-level validation, by contrast, is hard fail-fast. There is **no repair-and-retry** for bad LLM output: stochasticity is treated as variance of the judge, and a repair pass would inject bias. The parsing seam is maximally forgiving per quality label — prose, code fences, unknown content, identical duplicates, and int-vs-decimal are forgiven; conflicting duplicates are ambiguous, out-of-scale values are recorded as `out_of_range` and never clamped, and a misspelled label counts as missing. Whether partial results are accepted at all is one code constant, `ACCEPT_PARTIAL_RESULTS` (default off). Rubric prompts must use placeholder examples only. A configuration with zero judges degrades cleanly, and judges are never silently cross-averaged.

**The v1 metric set and its applicability:**

| Name | Kind | Needs reference summary | Note |
|---|---|---|---|
| judge-rubric | judge | per `requires_reference` | one rubric call returns factual correctness, completeness, conciseness |
| faithfulness | metric | no | |
| key_claim_completeness | metric | yes | |
| conciseness_length_proxy | metric | no | honest weakness: "short" is measurable, "concise" is not |
| structural_instruction_check | metric | no | always runnable |
| internal consistency | metric (optional) | no | low expected yield; first to cut if the set must shrink |

A judge with `requires_reference` on is never called for an entry that lacks a reference summary — the code guarantees it; a judge with the flag off may be called regardless.

## 9. Judge-agnostic configuration

The configuration carries no hosted-LLM credentials and the application assumes none. Three consequences follow:

1. Judge-based scoring is simply inapplicable until the user configures a judge endpoint (a manually run local judge endpoint is a legitimate one).
2. Any second comparison model (e.g. for curation) must be a **local** model — there is no hosted access to fall back on.
3. The preferred provenance for reference reports — a strong **hosted** model writing them — is unavailable until a key exists; curation then falls back to QMSum's gold summaries or hand-written ones (section 10).

## 10. Open facts with consequences

Curation-side facts, not architecture — recorded here because they constrain what v1 will actually be pointed at:

- **Corpus:** MeetingBank first, QMSum as fallback.
- **Golden set:** working plan of 50 items, stratified by transcript length; the selection criteria live in the curation record, not here.
- **Reference-report provenance:** the lean is that a strong hosted model writes the reference reports (writer ≠ judge); the fallbacks are QMSum gold summaries or hand-written ones. Which of these is actually used depends on section 9.

## 11. Deferred & parked

Each parked item keeps a seam in the architecture and has a revisit trigger:

- **Tune / meta-strategies.** The commands are already composable (selection grammar + store dedup), so a future `tune` command is a thin loop over `generate`/`score` with a candidate-selection heuristic (which may account for model load time). *Trigger:* the first need to automate multi-round candidate selection beyond `sweep`'s one-shot exhaustive net.
- **Judge lifecycle.** Judges stay bare endpoints in v1; the extension is their own launch profile and lifecycle unit, never sharing the tested-model server's mechanism. *Trigger:* the first time an operator wants the app to start and stop a judge server.
- **Re-sampling.** A generation's identity is (transcript, summarizer); a second sample of the same pair would need an extra identity component. *Trigger:* the first need to compare multiple samples of one summarizer.
- **Metric versioning.** A metric's identity is its registry name; mixing results from different versions of one metric is an accepted PoC limitation (separation is the human `clear` discipline, and `report` prints the support `n` per candidate and scorer). *Trigger:* the first request to distinguish metric code versions in a comparison view.
- **Attention dilution.** The v1 metric set is deliberately small; metric yield is first measured by the Phase 1 smoke test, and low-yield entries (internal consistency first) are cut there.

Terminology duty: the old decision-log phrase "dynamic metrics" was a conflation — the correct term is **judge**. New writing must not reintroduce the old phrase.

## 12. Explicitly out of scope

- Multi-axis interpretability and presentation of metric vectors (in v1 a metric is a vector of computed values, full stop).
- Device metadata and any hardware-aware behavior.
- Parallelism and multi-instance concurrency (section 5).
- Text-length configuration keys and load-time length checks (section 6).
- Dataset conversion tools as part of an evaluation run (section 6).
- Manifest files, run directories, persisted server logs, and the other retired concepts — the store is the only record (section 7).
