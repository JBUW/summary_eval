# Spec: v1 evaluation app — transcript → summary evaluation

Status: ready-for-agent
Feature slug: eval-app-v1
Date: 2026-10-22

Synthesized from the full decision log (DECISIONS.md) and a same-day cross-check of all
relevant documentation: GLOSSARY.md, assignment.txt, docs/design.md, docs/config.md,
docs/store-schema.md, docs/commands.md, docs/adr/0001-app-owned-model-server.md, and the
normative example configuration at the repo root. The repo is greenfield: docs, config
example, and glossary exist; no code exists yet.

## Problem Statement

I evaluate local LLMs on summarizing meeting transcripts. I have several candidate
summarizers — combinations of model, model arguments, prompt template, and generation
parameters — and curated datasets of transcripts, some with reference summaries. Today the
comparison loop is manual: I start the model server by hand, produce summaries one at a
time, score them with a few metrics and an LLM judge I prompt by hand, and keep track of
results in my head and scratch files.

The pain is concrete:

- Re-runs are expensive (model loads and LLM calls) and I keep paying for work already done.
- Results are not reproducible: I cannot say which exact inputs produced a stored row.
- There is no single source of truth: partial runs, crashes, and repeated experiments
  leave no recoverable state.
- Configuration drift (which judges, which metrics, which datasets) lives in my head, not
  in a reviewable artifact.
- I have no cheap way to verify that my setup — config, datasets, judge rubrics, hardware
  context window — is sound before spending a long generation run.

I need a single, resumable, reproducible tool that owns the generate → score → report
loop end to end.

## Solution

A single Python executable with six subcommands — `check`, `generate`, `score`, `sweep`,
`report`, `clear` — driven by one configuration file. The configuration is the universe of
definitions (models, prompt templates, summarizers, datasets, judges, defaults); the
command line only selects and steers; the results store holds results and is independent
of both.

Core properties, from the user's perspective:

- **Everything is resumable.** Every stored row is addressed by the identity of its
  inputs. A re-run pre-scans the store, skips committed work without spending a single
  model call, and commits only the rest. A crash loses at most one item or one
  (item, scorer) unit; re-running is the recovery mechanism. Committed work is terminal —
  never re-rolled.
- **The app owns the local model server.** Spawn, readiness wait, trivial preflight
  completion, per-item work, clean stop — no manual `llama-server` juggling. One server
  cycle per distinct resolved (model, model_args) pair; the port is reused between
  cycles; a busy port is refused (never adopted).
- **Judges are endpoints, not processes.** A judge is a bare endpoint profile — any
  OpenAI-compatible URL, hosted or a locally started server. The app never spawns,
  monitors, or stops a judge.
- **The console is the machine interface.** Stable exit classes (0 success incl. no-ops,
  1 runtime fail-fast, 2 pre-effect specification error) and stable stdout prefixes
  (`error:`, `warn:`, `plan:`, `note:`), with the plan line always showing the effective
  scorer set (e.g. `4 metrics, 1 judge`).
- **`check` de-risks before you spend.** A static lint that prints ALL configuration and
  contract failures in one pass, plus an opt-in live phase (local server probes, optional
  judge rubric probes) that costs almost nothing and flags context-window and rubric
  problems before a long run.
- **`report` is a descriptive roll-up**, strictly read-only: per (candidate, scorer)
  n/mean/min/max, judges per candidate × quality, every figure indicating its source.
- **`clear` is the human's clean slate** — dry-run by default, `--yes` to wipe — used,
  for example, after a hardware change. The app is hardware-agnostic and does not detect
  hardware changes; that is the human's job.

## User Stories

1. As a researcher, I want to define models, prompt templates, summarizers, datasets, judges, and defaults in one configuration file, so that the whole evaluation universe is reviewable in one place.
2. As a researcher, I want the configuration to be strict JSON with duplicate-key detection, so that an ambiguous configuration fails loudly before any effect.
3. As a researcher, I want unrecognized configuration fields to produce warnings rather than errors, so that forward-compatible additions do not break existing runs.
4. As a researcher, I want summarizers to be copy-then-override from a `base` summarizer, so that I can vary one component at a time without restating the full four components.
5. As a researcher, I want every summarizer to be exactly a four-tuple (model + model_args + prompt template + gen_params) fully resolved at load time, so that a summarizer name always means one precise candidate.
6. As a researcher, I want names to be plain handles with `*` reserved, so that I can reference definitions unambiguously from the command line.
7. As a researcher, I want to override the store path and all model-server launch values (command, args, env, port, startup timeout) from the command line without editing the configuration, so that I can experiment per run.
8. As a researcher, I want such overrides to never be written back to the configuration file, so that the file stays the reviewed source of truth.
9. As a researcher, I want to curate datasets as CSV or JSONL/JSON with the format determined by extension, so that I can use existing corpus formats without conversion.
10. As a researcher, I want a dataset to become named when it declares an entry-id field, so that I can address individual entries by stable id.
11. As a researcher, I want ids to be all-or-nothing (every entry has an id or none do), so that named addressing is never half-broken.
12. As a researcher, I want load-time contract failures (missing file, bad extension, declared field absent, malformed rows, zero entries, empty transcript, empty or repeated ids, empty declared reference) to be fail-fast exit-2 errors naming the file and line, so that curation mistakes are caught before any model call.
13. As a researcher, I want no transcript-length checks of any kind, so that dataset acceptance depends only on well-formedness, not on arbitrary length policy.
14. As a researcher, I want a missing reference summary to be a per-pair warning and drop rather than an error, so that datasets without references still score with scorers that do not require them.
15. As a researcher, I want a selection grammar supporting 0-based positions and ranges, entry ids, and `*`, unioned across repeatable flags, so that I can re-run any subset without editing the configuration.
16. As a researcher, I want a `--select` occurrence with no specs to be an error rather than a silent full run, so that a typo cannot burn model calls.
17. As a researcher, I want `generate` to produce summaries for the selected summarizers × datasets × entries, so that I obtain candidate artifacts to score.
18. As a researcher, I want the app to own the local model server lifecycle (spawn, readiness wait, preflight, clean stop), so that a run is self-contained and needs no manual server management.
19. As a researcher, I want exactly one server cycle per distinct resolved (model, model_args) pair with the port reused between cycles, so that model loads are amortized over all items.
20. As a researcher, I want a busy port to be refused with a hint that an orphaned server may be holding it, so that a stale process can never silently serve a run.
21. As a researcher, I want items already committed in the store to be skipped before any call and counted in the plan and done lines, so that re-runs never pay for work already done.
22. As a researcher, I want a fully committed scope to exit 0 without spawning the server at all, so that checking "is this done?" is free.
23. As a researcher, I want identical transcript text across datasets to deduplicate to one store row, so that the store does not bloat with duplicates.
24. As a researcher, I want deterministic item order (summarizer → dataset → entry, in configuration/file order), so that runs are reproducible.
25. As a researcher, I want fail-fast on the first generation failure with the failing item, the error, the last ~20 lines of the server log, and a resume hint, so that I can diagnose and continue where I left off.
26. As a researcher, I want committed generations to be terminal — never re-rolled — so that stored results stay stable across re-runs.
27. As a researcher, I want metrics to be code-registered and invocable by name whether or not they appear in the configuration, so that the codebase, not the config, is the metric catalog.
28. As a researcher, I want each metric to produce exactly one scalar value with a frozen spec (name, reference requirement, value contract), so that metric behavior is stable and testable.
29. As a researcher, I want a metric that cannot produce a value to be an exclusion rather than a stored row, so that the store holds only real values.
30. As a researcher, I want judges to be bare endpoint profiles with no lifecycle, so that I can point a judge at any OpenAI-compatible endpoint, hosted or local.
31. As a researcher, I want one judge call to score several qualities (one nullable value per quality, never cross-averaged, no composite), so that a single completion yields multiple interpretable axes.
32. As a researcher, I want the judge rubric's `{transcript}` and `{summary}` placeholders to be mandatory and `{reference}` required exactly when the judge declares `requires_reference`, so that a rubric cannot be silently wrong about its inputs.
33. As a researcher, I want a `requires_reference` judge to be never called without a reference, guaranteed by code, so that an invalid score can never be committed.
34. As a researcher, I want scorer selection precedence (explicit list, then `*`, then bare flag to defaults, then omitted to zero for judges) with the plan line always printing the effective set, so that I always see exactly which scorers will run.
35. As a researcher, I want `--no-metrics` and `--no-judges` shorthands equivalent to the `[]` token, so that I can cheaply run a single scorer family.
36. As a researcher, I want infeasible (scorer, dataset) pairs — a reference-requiring scorer over a dataset without references — to be warned and dropped, so that a mixed scope proceeds on its feasible part.
37. As a researcher, I want the metrics phase to run before the judges phase, so that no judge tokens are spent before the free metrics finish.
38. As a researcher, I want a judge response yielding no extractable quality to be a warning, no row, and continue, so that one bad response does not kill a scoring run.
39. As a researcher, I want judge transport, HTTP, or empty-completion failures to fail fast naming the item and the judge, so that I can fix the endpoint and retry just the failed units.
40. As a researcher, I want already-scored (item, scorer) units to be skipped on re-run, so that scoring is resumable exactly like generation.
41. As a researcher, I want `score --generate` to run the full generation stage first in the same invocation, so that a fresh dataset can be generated and scored with one command.
42. As a researcher, I want a local model to serve as a judge with zero code or config changes (manually started local server as the endpoint plus a dummy credential variable), so that judging with a local model is always an option.
43. As a researcher, I want `sweep` to be exhaustive — all configured summarizers × all datasets × the resolved scorer set, with generation implied — so that a full wide net is a single command.
44. As a researcher, I want `sweep` to accept no selection or scorer flags, so that "exhaustive" cannot be accidentally narrowed.
45. As a researcher, I want widen-only `--all-metrics`, `--all-judges`, and `--all` on `sweep`, so that I can broaden a sweep beyond the configured defaults with no narrowing options to misuse.
46. As a researcher, I want `report` to show n/mean/min/max per (candidate, scorer), one row per candidate × quality for judges, and n=0 rows with dashes, so that candidate comparison is a glance.
47. As a researcher, I want every reported figure to indicate its source (n, and judge where applicable), so that I can trust each roll-up.
48. As a researcher, I want `--by dataset`, `--json`, `--blind-sample N`, and `--csv` output options on `report`, so that I can slice and export results without leaving the tool.
49. As a researcher, I want `report` to be strictly read-only — no commits, no upserts, not even courtesy-name refreshes — so that inspecting results can never mutate the store.
50. As a researcher, I want `check` to lint the entire configuration statically and print ALL failures in one pass before exiting, so that I can fix everything in a single edit cycle.
51. As a researcher, I want `check` errors to carry the valid sets (e.g. unknown metric names listing the registered metrics), so that I can fix name mistakes immediately.
52. As a researcher, I want `check` to discover scorers in two disjoint groups (named in defaults vs. registered/configured but not named there), so that I always see what exists but will not run by default.
53. As a researcher, I want a live `check` phase that probes the local server — readiness, trivial completion, context adequacy against the longest in-scope transcript per dataset — so that I know the hardware can handle the corpus before a long run.
54. As a researcher, I want judge rubric probes to be opt-in via `--probe-judges`, so that no external or paid call is ever made by default.
55. As a researcher, I want `check` to open the store read-only by default with explicit opt-in to create it, so that diagnostics never create state.
56. As a researcher, I want `clear` to be dry-run by default and destructive only with `--yes`, so that a destructive wipe can never be accidental.
57. As a researcher, I want `clear` to be the human-initiated clean slate after, e.g., a hardware change, so that the application can stay hardware-agnostic.
58. As a researcher, I want stable exit classes (0 success including no-ops, 1 runtime failure with fail-fast, 2 pre-effect specification error with nothing executed), so that scripts can classify what happened.
59. As a researcher, I want a no-op to be reported with `note:` and exit 0, never `error:`, so that "nothing to do" is never confused with failure.
60. As a researcher, I want stable stdout prefixes with a fixed message order (warn → plan → note) as the machine interface, so that scripts can key on the console output.
61. As a researcher, I want every stored row to be addressed by the identity of its inputs, so that results are reproducible and duplicate work deduplicates automatically.
62. As a researcher, I want courtesy name columns in the store to be last-seen-wins and never resolved against the configuration, so that renaming definitions does not rewrite history.
63. As a researcher, I want the store itself to be the index — no manifests, no run directories — so that there is exactly one source of truth to clear.

## Implementation Decisions

### Runtime and packaging

- Python 3.14+, run in a virtualenv, `argparse` from the standard library for the CLI, no application framework. Third-party libraries are unconstrained; the only recorded dependency constraint is the revisit trigger on metric implementations (decision Q16a6).
- One executable, six subcommands: `check | generate | score | sweep | report | clear`. There is no `serve` — the model server's lifecycle is internal to the run commands. `tune` and other meta-strategy commands are parked and do not exist.
- The executable name is fixed at implementation time; all documentation writes it as a placeholder.

### Modules (responsibility map)

- **CLI layer** — flag parsing per subcommand, selection-grammar parsing, exit-class dispatch, stdout formatting (the four prefixes and their ordering), plan/done line construction.
- **Configuration module** — strict JSON loading with duplicate-key detection; recognition of known sections/fields (unrecognized fields warn-only; the open maps `server.args`, `model_args`, `gen_params`, `env` are exempt); `base` chain resolution; full four-component summarizer resolution; wholesale CLI override application.
- **Dataset module** — load by extension (CSV per RFC 4180 UTF-8; JSONL/JSON one object per line); R1 load-time contract checks (fail-fast, file + line); R2 reference-absence handling; entry ordering.
- **Identity module** — canonical JSON serialization and sha256 identity computation for every stored entity.
- **Store module** — the single shared open path (bootstrap when absent: directory, file, all 8 tables; exact schema check when present; mismatch is a hard error, never migration); upserts; transaction boundaries; `clear`.
- **Server lifecycle module** — pre-spawn validation, spawn, readiness polling, preflight completion, clean stop; launch-line composition and map rendering (shared with the check live phase).
- **Generation module** — pre-scan skip logic, deterministic item ordering, per-item commit units, fail-fast with resume hint.
- **Scoring module** — scorer resolution (metrics and judges), infeasible-pair computation, metrics phase, judges phase, per-(item, scorer) commit units.
- **Endpoint client** — the single injected transport for all HTTP to model server and judge endpoints (this is a test seam; see Testing Decisions).
- **Judge response parser** — the pure function at the trust boundary: raw judge text → structured quality values (this is a test seam; see Testing Decisions).
- **Report module** — strictly read-only aggregation over the store; table/JSON/CSV rendering.
- **Check module** — static lint phase (collect-all-then-exit-2) and live probe phase (local-only, fail-fast, exit 1), scorer discovery display.

### Roles and data flow

- Configuration = universe of definitions. Command line = selection and steering. Store = results only. Courtesy name columns in the store originate from the configuration but are never resolved against it.
- `generate` never invokes judges or metrics and never reads reference summaries for scoring (it does upsert reference summaries when the dataset declares a reference field, so scoring can commit in its own transactions).
- `score` never generates and never spawns the model server unless `--generate` is given; with `--generate`, the full generate lifecycle runs first and a stage-1 abort prevents any scoring.
- The scoring commands read committed store rows; they never require a live server.

### Identities (input-addressed)

- All primary keys are sha256 over canonical JSON of the entity's inputs:
  - Model identity = hash of the model file bytes (path is irrelevant; same bytes = same model).
  - Generation identity = hash(transcript, model, model_args, prompt template, gen_params). Input-addressing makes lookup-before-call deduplication trivial: committed ⇒ skipped.
  - Judge identity = hash([model name, gen_params, system content, user template, requires_reference]). Endpoint URL, display name, and credential variable are NOT part of the identity: the same judge model reached locally or remotely dedupes to the same rows.
  - Evaluation identity = hash(scorer identity, generation, reference-or-null).
- Transcripts and reference summaries are content-addressed; identical transcript text across datasets is one store row.
- `updated_at` is stamped only when an existing identity is upserted with differing non-key values.
- No migration: schema mismatch is exit 2 with a hint to move or delete the file. `clear` is the only destructive path.
- Terminality: committed generations and evaluations are never recomputed or re-rolled; re-sampling is out of scope. The store is the index — no manifests, no run directories.

### Store schema

One SQLite file (default filename from the configuration; the normative example uses `evalstore.sqlite3`), exactly 8 tables: `transcripts`, `reference_summaries`, `models`, `prompt_templates`, `judges`, `generations`, `judge_evaluations`, `metric_evaluations`.

- Every command opens the store through the one shared path; the only exception is `check`, which is read-only by default and creates only with an explicit opt-in flag.
- At most one active instance per store is a usage discipline; there is no app-level locking. SQLite file locking prevents corruption; races cost duplicated calls, not integrity.
- Metric evaluation rows carry a single NOT NULL scalar value. Judge evaluation rows carry one nullable REAL column per quality (`factual_correctness`, `completeness`, `conciseness`), one call per generation scores several, values are never cross-averaged, and no composite score exists.

### Configuration contracts

- Strict JSON; duplicate keys in a definition section are errors (`error: duplicate name '<x>' in <section>`); `*` is a reserved name; unrecognized fields are warnings with location; open maps are exempt from recognition.
- Summarizer: four components; `base` names an earlier summarizer in the file (later = static error); copy-then-override semantics; a stray `path` in a summarizer is an error; model_args resolution is a two-layer merge (model entry, then summarizer override per key); the model path is never overridable from a summarizer; `server.args` never layers into `model_args`.
- Judge: `requires_reference` is a REQUIRED boolean (absent or non-boolean ⇒ exit 2); placeholder contract as in User Stories 32–33; unknown `{...}` tokens are not errors — they pass through unsubstituted into the sent prompt; `api_key_env` must name a set, non-empty variable.
- No computable hashes ever appear in the configuration. Key order is convention-only (checked nowhere).
- Wholesale CLI overrides: `store` and the five `server.*` values, available on every command that spawns or could spawn; `--server-*` without `--generate` on a command that has a generate stage ⇒ exit 2. `default_metrics` / `default_judges` are NOT wholesale-replaceable.

### Dataset contracts

- Format by extension: `.csv` (RFC 4180, UTF-8), `.jsonl`, `.json` (one object per line). Any other extension is a load-time contract failure.
- R1 (fail-fast, exit 2, file + line): missing/unreadable file, bad extension, declared purpose field absent, malformed rows (CSV column-count mismatch or duplicate header names; JSONL non-JSON line), zero entries, empty transcript value, entry-id field declared but any id empty. No length checks.
- R2 (not an error): a dataset without a reference field simply makes reference-requiring scorers infeasible for it — warn + drop per pair.

### Selection grammar

- One repeatable flag on the run commands: dataset name followed by specs; occurrences union; duplicates dropped; no flag ⇒ full scope.
- Three disjoint spec namespaces, one marker each: `#` for 0-based positions and inclusive ranges (comma-separated, any order, strict digits; out-of-range/inverted/malformed ⇒ exit 2; valid in named and unnamed datasets), `@` for literal entry ids (named datasets only; `@@x` names an entry literally called `@x`), `*` for all entries of the dataset (and `--select *` alone = all datasets × all entries).
- A `--select` occurrence with zero specs ⇒ exit 2, never a silent full run.

### Model server lifecycle (per ADR 0001)

- The application owns exactly one spawned model server per run. One cycle per distinct resolved (model, model_args) pair, sequential, spawned on demand mid-run, port reused between cycles.
- Pre-spawn validation: the `server.command` binary exists, the model file exists, the port is free. A busy port is refused with a hint about a possibly orphaned server; it is never adopted.
- Readiness = poll `GET /props` until the server reports running, bounded by the configured startup timeout. Preflight = one trivial completion. `/props` build info is printed informationally and never stored.
- Launch line = `server.command` + rendered `server.args` + rendered resolved `model_args` + `--port` + `--model <path>`. Map rendering is shared: key ⇒ `--key`, scalar ⇒ `--key value`, boolean true ⇒ bare `--key`, boolean false ⇒ omitted. `gen_params` are not launch arguments; they ride with each completion request.
- Clean stop: SIGTERM, wait, SIGKILL. Failures exit 1 with the failing item, the error, the last ~20 lines of server output, and (for runs) a resume hint.
- Absent `server` section in the configuration ⇒ `generate` is a hard error (exit 2); nothing is invented, no fallback arguments.

### Generation

- Item order is deterministic: summarizer → dataset → entry, in configuration/file order. The loaded model may only affect attempt scheduling, never the identity of what runs.
- Pre-scan before any call: committed generations are looked up by identity; an already-committed item is skipped with no model call and counted. Whole scope committed ⇒ exit 0 without spawning the server.
- Commit unit = one item (entry × summarizer): upserts of `transcripts`, `reference_summaries` (when the dataset declares a reference field), `models`, `prompt_templates`, plus the `generations` INSERT, all in one transaction. Complete-or-absent; a crash loses at most one unit.
- Fail-fast: first HTTP error, empty completion, server death, or readiness timeout aborts the run (exit 1) with failing item, error, last ~20 server log lines, and a resume hint.

### Scoring

- Metrics resolution precedence: explicit `--metrics` list (including the `[]` token) ⇒ exactly that list; flag omitted ⇒ `default_metrics` (present-but-empty ⇒ zero metrics); key absent ⇒ ALL code-registered metrics. Any registered metric is invocable by name or `*` whether or not it appears in the configuration; `*` unions with names.
- Judges resolution precedence: explicit `--judges` list ⇒ exactly that list; `--judges *` ⇒ all configured; bare `--judges` ⇒ `default_judges` if present (present-but-empty ⇒ zero, with a note) else all configured (the explicit flag shows enough intent); flag omitted ⇒ ZERO judges — the deliberate safe default, no error, plan line shows `0 judges`. Judges are never invoked implicitly.
- `--no-metrics` ≡ `--metrics '[]'`; `--no-judges` ≡ `--judges '[]'`; each `--no-X` is mutually exclusive with `--X` in any form ⇒ exit 2.
- Execution order: (1) pre-effect validation ⇒ exit 2 before store or network; (2) resolve the effective scorer set; (3) infeasible (scorer, dataset) pairs are dropped with one `warn:` each and are never committed; (4) with `--generate`, the full generate lifecycle first; (5) metrics phase over all items, then judges phase.
- Commit unit = one (item, scorer): the `reference_summaries` upsert (when applicable) and the evaluation INSERT in the same transaction.
- Judge failures: no extractable quality ⇒ `warn:` + no row + continue; transport/HTTP failure or empty completion ⇒ fail-fast exit 1 naming item and judge.
- The plan line is always printed and always shows the effective scorer set; "infeasible" counts (scorer, dataset) pairs, while "to run" / "already scored" count (item, scorer) units excluding infeasible pairs.
- Note lines (all exit 0) cover: no committed generations in scope, some selected items lacking committed generations, zero feasible pairs, and both flag families empty (with `--generate` the generation stage still runs first).

### Metrics registry

- Metrics are code-registered by automatic discovery (importing a metric module registers it; no decorator list, no central registry file to maintain). The codebase is the catalog.
- Each metric is a frozen spec: name, `requires_reference`, and a value contract (single scalar). Validation happens in one assembly-time pass.
- v1 metric set: `faithfulness` (no reference), `key_claim_completeness` (reference required), `conciseness_length_proxy` (no reference — "short is measurable, concise is not"), `structural_instruction_check` (no reference, always runnable), and an internal-consistency metric (optional, low yield, first to cut).
- A metric that cannot produce a value for an input is an exclusion, not a stored row.

### Judge transport and the trust boundary

- Judges are bare endpoint profiles: URL, model name, generation parameters, system content, user template, `requires_reference`, `api_key_env`. No lifecycle: the app never spawns, monitors, or stops a judge. A dead endpoint is a transport failure (exit 1), not something to recover.
- Self-judging (a judge whose model is the model under test) is a user misconfiguration; the application does not police it.
- Credential handling: `api_key_env` unset/empty ⇒ static failure (exit 2) in `check` and for an explicitly named judge in `score`; in `sweep` it is a `warn:` + drop (exit 0).
- The judge's raw response text is the program's single trust boundary: transcripts, summaries, configuration, and prompt templates are curated or app-generated, so runtime validation belongs only here. The parse policy is deliberately relaxed — warning + recorded exclusion, or partial acceptance governed by the code constant `ACCEPT_PARTIAL_RESULTS` (default off) — because this input is genuinely untrusted. Out-of-scale values are marked out-of-range and never clamped; a misspelled quality label is treated as missing, not as a value.

### Report

- Shallow, strictly descriptive per (candidate, scorer): n/mean/min/max, plus coverage (n scored, n excluded by reason). Judges: one row per candidate × quality. n=0 rows are shown with dashes.
- No mechanical pooling gate: metric identity is the registry name only. Mixing changed metric code across the store's lifetime is an accepted PoC limitation; `clear` is the human separation discipline.
- Every figure indicates its source (n, and judge where applicable). Output options: human table (default), `--json` (stable key order), `--by dataset` (the only grouping axis), `--blind-sample N` (last N entries per in-scope dataset in file order, applied after selection; a reporting/holdout convention, nothing enforced), `--csv PATH` (flattened rows; table suppressed; mutually exclusive with `--json`; parent directory must exist; file created only after pre-effect validation; minimal CSV dialect).
- Strictly read-only: no commits, no upserts (not even courtesy-column refreshes), no server, no model or judge calls.

### Check

- Static phase (linter): collects and prints ALL static failures, then exits 2; the live phase is skipped. Deliberate contrast to the run commands, which fail fast. Coverage: duplicate names; `*` as a name; `base` ordering; full four-component resolution; stray `path`; unknown names in `default_metrics` / `default_judges` (errors carry the valid sets); judge contract (required boolean, placeholder rules); dataset contract (the R1 set); `server.command` binary and model files exist; port pre-scan (bound ⇒ failure with orphan-server hint). Unrecognized fields warn-only; open maps exempt.
- Store: read-only by default (absent store ⇒ `note:`, never created); explicit opt-in flag applies the normal shared open path; probe results are discarded; `check` never commits.
- Live phase (only if static is clean): local only, fail-fast (exit 1, failing target + error + last ~20 server log lines). Per distinct (model, model_args) in configuration order: spawn → readiness (bounded) → `/props` printed informationally → one probe completion per distinct resolved summarizer (deduplicated; a fixed short probe transcript constant in code, never dataset content — no dataset content leaves the machine) → context-adequacy probe for the longest in-scope transcript per dataset (tokenize call with a chars/3 fallback; over ⇒ `warn:` only) → stop; port reused between cycles.
- `--probe-judges` is opt-in (default off; no external/paid call by default): one trivial completion per judge with the rubric rendered using placeholder example values only, run through the real parser; nothing usable or a transport failure ⇒ exit 1.
- Exit 0 = static clean and all live probes OK (warnings allowed).
- Scorer discovery (static, printed regardless of store presence, two disjoint groups per family): named in the relevant default vs. registered/configured but not named there. Every registered metric and configured judge appears in exactly one group.

### Clear

- Wipes all 8 tables in a single transaction, all-or-nothing, no subsetting. The configuration is loaded only to resolve the default store path.
- Dry-run by default (a dry run is a successful invocation): prints per-table row counts and a note. `--yes` is the confirmation; there is no interactive prompt. No store ⇒ `note:`, exit 0. Missing configuration ⇒ exit 2.
- Scripts verifying the wipe key on the `done(clear):` line.

### CLI contracts

- Shared flags on every subcommand: `--config` (default `config.json`) and `--store` (overrides the configuration's store value).
- Exit classes: 0 = success including no-ops and dry runs (no-ops reported with `note:`, never `error:`); 1 = runtime failure, fail-fast (model call, metric algorithm, judge transport, server spawn/readiness); 2 = pre-effect specification error — nothing executed, no model/judge calls, no store writes (unknown names, malformed flags/specs/JSON, out-of-range indexes, config-shape failures, schema mismatch, busy port, flag misuse).
- Output vocabulary (stdout prefixes are the machine interface): `error:`, `warn:` (dropped or skipped; the run proceeds, exit 0), `plan:` (what the command will do / did do), `note:` (informational, including absences; a level below `warn:`). Message order within a run: `warn:` first, then `plan:`, then `note:`.
- Terminology is strict in all user-facing text: `metric` (code-registered, one scalar), `judge` (configuration-defined LLM scorer, one value per quality), `quality` (one axis a judge scores), `scorer` (umbrella — never in user-facing counts; the console says `4 metrics, 1 judge`), `store` (never "database"), `endpoint` (a judge's URL, never "server"; the spawned local process is the "model server"), `summary` (generated text artifact only), `Summarizer` (the four-component candidate), `prompt template` (the recipe, not the prompt that is sent).

## Testing Decisions

### What makes a good test

A good test asserts only external behavior: rows committed to the store, stdout prefixes and lines, exit codes, or the requests an injected endpoint client was asked to make. A test never inspects internal state, asserts on call order inside a module, or reaches into unexported helpers. A test that breaks on a behavior-preserving refactor is a bad test. The judge's judgment itself — what a live model thinks of a summary — is never a test target.

### Seams

A seam is the outside of something that can be treated as a black box: a deliberately narrow, replaceable boundary between two parts of the program where one side can be faked or substituted without editing the other. Placement rule: seams go where trust changes, or where a dependency is external or expensive. Existing seams are preferred to new ones; the highest usable seam wins; the fewer seams in the codebase, the better.

This application is designed to have exactly two seams, both at the highest useful point, and both were validated with the user:

1. **The pure judge-response parse function** — the program's single trust boundary. Raw judge text goes in; structured quality values come out. Tests exercise everything up to this seam (resolution, rendering, transport handling, commit) and stop at it.
2. **The injected endpoint client** — the program's single door to the network, serving both the model server and judge endpoints. Unit tests inject a fake client and assert on the requests it received and on the store/stdout results that followed.

No seams below these two are needed: configuration, datasets, identities, store, selection, and scoring orchestration are all plain code reachable from above the seams.

### Why these seams (the rationale, stated precisely)

The unit seams were chosen **because integration tests are slow** — a model server must be spawned, reach readiness, and real LLM calls must complete — **not** to minimize the total number of tests. The goal is maximum coverage of fast, deterministic behavior without paying for the slow parts: with only two slow dependencies in the system and both behind the seams, essentially all logic is unit-testable without a server or a network. If integration tests were cheap, this seam placement would not change — only the test counts would.

### Golden fixtures at the parse seam

Recorded raw judge responses, paired with their expected structured outcome, forming the golden fixture set for the parse seam. Required coverage:

- Clean, directly parseable values.
- Prose-wrapped values and markdown-fenced values.
- Duplicate quality values: identical duplicates (accepted) versus conflicting duplicates (excluded per the parse policy).
- Integer versus decimal value forms.
- Out-of-scale value ⇒ marked out-of-range, **never clamped**.
- Misspelled quality label ⇒ treated as missing, not as a value.
- Partial-acceptance behavior per the code constant `ACCEPT_PARTIAL_RESULTS` (default off): with it off, a partially parseable response yields the warning-plus-exclusion path.

Naming discipline: these are golden *fixtures* of input at a seam. They must not be conflated with the glossary's *golden set* — the curated, documented subset of a dataset on which all candidates are evaluated. Different concepts; keep the terms distinct in code, comments, and documentation.

### Metrics (assignment hard requirement)

Every custom metric has unit tests on small, manually calculated examples — inputs and expected scalar outputs verified by hand, no model and no store involved. This covers `faithfulness`, `key_claim_completeness`, `conciseness_length_proxy`, `structural_instruction_check`, and the internal-consistency metric, including the exclusion path (input for which the metric cannot produce a value).

### Integration tests (slow, few, high-leverage)

Because each of these is expensive (server spawn and/or LLM calls), the suite keeps them few:

- Server lifecycle: spawn → readiness (bounded by the startup timeout) → preflight completion → clean stop; busy port refused with the orphan-server hint (never adopted); absent `server` section ⇒ exit 2.
- End-to-end smoke: a tiny dataset with a fake or trivially cheap endpoint through `generate` → `score` → `report`, asserting the plan/done lines, exit classes, and the resulting store rows.
- Pre-effect contract failures: configuration shape errors, dataset R1 failures (with file + line in the message), selection-grammar violations, flag misuse — each asserting exit 2 and that nothing was executed (no store writes, no network).
- Store behavior: bootstrap of an absent store (directory, file, all 8 tables), exact schema check, schema mismatch ⇒ exit 2, `clear` dry-run vs. `--yes`.
- Resume/skip: re-run after a simulated partial failure skips committed units, spends no calls on them, and commits only the remainder.

### Prior art

The repository is greenfield — there is no existing test suite to imitate. The closest prior art is the P0b smoke-test criteria (server readiness within the configured bound, a trivial generation succeeding, and the failure path exiting 1 with the last ~20 server log lines), which the integration smoke tests inherit and extend.

## Out of Scope

- `tune` and meta-strategies — parked, not dropped; the architecture (atomic per-item and per-(item, scorer) commits, store as single source of truth, input-addressed identities, deterministic selection, the configuration's summarizer roster) allows them to be added later as thin orchestration subcommands.
- First-class judge lifecycle (spawning, monitoring, stopping judges) — judges remain bare endpoint profiles.
- Re-sampling of committed work — committed generations and evaluations are terminal; no re-rolls.
- Metric versioning — metric identity is the registry name; mixing changed metric code across the store's lifetime is an accepted PoC limitation; `clear` is the human separation discipline.
- Attention-dilution cuts (rubric/prompt trimming strategies) — parked with their trigger conditions in the decision log.
- `--adopt` or any adoption of externally started model servers — a busy port is refused, never adopted.
- Content-hash configuration pinning.
- Device/hardware metadata and hardware-change detection — the app is hardware-agnostic; after a hardware change the human clears the store and updates the launch profile.
- Persisted server logs — only the last ~20 lines are shown on failure; nothing is saved in v1.
- Per-item tokenize preflight — context adequacy is probed once per dataset against its longest in-scope transcript, warn-only.
- Report analysis beyond the accepted shallow shape (descriptive n/mean/min/max, coverage, source indication) — the shape stands, details are re-openable by name.
- Transcript length checks of any kind and any length configuration keys.
- App-level locking or multi-instance coordination — at most one active instance per store is a usage discipline; SQLite file locking is the only machinery.
- Interactive prompts — `clear` confirms via the `--yes` flag; nothing else prompts.
- Composite scores, cross-quality averaging, and any interpretability layer — judges score per quality; that is the end of the pipeline.
- Implementation itself — P0d formal approval is a human responsibility; implementation starts only after sign-off plus an explicit ask.

## Further Notes

- **Vocabulary.** Use the glossary's terms and avoid its listed synonyms throughout the implementation (e.g., `endpoint` not "server" for a judge URL; `scorer` never in user-facing counts; `store` not "database"; `summary` for the generated artifact only; `Summarizer` not "variant" or "setup"; "manifest" is retired — the store is the index).
- **Normative hierarchy.** If this spec and any document disagree, the four normative documents govern (store schema, configuration, commands, design) per the design document's own rule; the decision log records the why and when.
- **Cross-check.** All relevant documentation was re-read and cross-checked on 2026-10-22 while writing this spec (decision log in full, glossary, assignment, all four normative documents, the ADR, and the example configuration). No drift was found; earlier filename-role and hardware-naming discrepancies had already been resolved in the log.
- **Hardware context.** The starting machine is an AMD Radeon 8060S with 32 GB unified memory. The P0b smoke test passed on 2026-10-21 with the 27B QAT Q4_0 model (readiness 8–10 s, full GPU offload, no extra model arguments); 8B models are development-only.
- **Open curation facts** (data decisions, not architecture): corpus is MeetingBank first with QMSum as fallback; the golden set is ~50 items stratified by length; reference provenance is lean (hosted writer, never the judge; fallbacks are QMSum gold summaries or hand-written references).
- **Example configuration.** The `config.json` at the repo root is the normative example configuration; the data/prompt/model paths it references are illustrative and absent from the repo, so `check` reporting them as contract failures is expected until they exist.
- **Known flag, user decision, not spec-relevant.** The example configuration's models use Q4_K_M with `flash-attn: true` while the smoke test used the QAT Q4_0 variant; the configuration was deliberately left unchanged pending a user decision.
- **Tracker.** This spec is the feature's issue. Labeled ready-for-agent; no decision-log entry or normative-document updates are owed — the spec changes no store, configuration, CLI, or design decision.
