# Store schema

Authoritative, current shape of the results store (v1). This file is the "what it is now"
reference; `.scratch/grill-with-docs/DECISIONS.md` is the decision log (the "why and when").

House rule: any decision that changes the store updates this file in the same round as the
log entry. If the two ever disagree, this file states what the store looks like today and
the log explains the change.

## Conventions

- **Medium:** one SQLite file (`store` section of the config names it; default `store.db`).
- **Identity = primary key.** Every table's primary key is a `*_sha256` column: the hex
  sha256 of the object the row stands for. Identities are computed, never typed by hand,
  and no two rows in the same table share one. Inserting a row with an existing identity
  is an upsert under the stamp rule below.
- **Canonical JSON:** identity hashes are taken over `canonical_json` of the listed
  components — keys sorted, no insignificant whitespace. "or null" means JSON `null`
  when the value is absent.
- **Identity vs. courtesy.** Identity columns participate in the primary key. Courtesy
  columns are human-readable copies of names/addresses that the config or dataset file
  gave an entity at commit time. They are never resolved against config or datasets,
  never validated, and never key anything: a row stays readable if the config later
  renames or removes the entity.
- **`updated_at` on every table** (TEXT NOT NULL, ISO-8601 UTC seconds, e.g.
  `2026-10-15T09:30:00Z`). Out of every identity hash, never read by app logic. Purpose:
  an aid to external cleanup — it shows when a row's non-identity values were last seen
  in a different form. Stamp rule: a commit to an *existing* identity stamps the row iff
  at least one non-identity value differs from what is stored; a pure re-insert (no
  change) leaves the row untouched; a fresh insert sets it once.
- **Exclusions (never stored):** credentials (only the environment-variable *name* is
  stored), model files (their content hash is the identity), metric implementations
  (only the code-registry name is stored).
- **No migration, no version number.** A store that does not match this schema is a
  pre-effect failure (exit 2); `clear` is the only sanctioned reset.
- **Summarizer = 4 components:** model + `model_args` + prompt template + `gen_params`.
  A row that records a summarizer stores exactly these four (two as foreign keys, two as
  written-out values).

## 1. transcripts

Literal input texts, verbatim. Content-addressed: the same text used from any dataset
is one row. No provenance and no revision history — an edited dataset entry is a new
text, hence a new row; the old row and its results remain.

| Column | Type | Note |
|---|---|---|
| `transcript_sha256` | TEXT PK | sha256 of the text bytes |
| `transcript_text` | TEXT NOT NULL | the literal transcript, verbatim |
| `dataset_name` | TEXT NOT NULL | courtesy: dataset name at last load |
| `entry_id` | TEXT NULL | courtesy: entry id at last load; NULL iff the dataset has no `entry_id_field` |
| `entry_index` | INTEGER NOT NULL | courtesy: 0-based file position at last load |
| `updated_at` | TEXT NOT NULL | stamp rule above |

Example:

| transcript_sha256 | transcript_text | dataset_name | entry_id | entry_index | updated_at |
|---|---|---|---|---|---|
| `9f1c…e2` | `00:01 Alice: The release slipped…` | `meetbank` | `m218` | `41` | `2026-10-15T09:30:00Z` |

## 2. reference_summaries

Verbatim golden summaries. Absence of a row = the entry has no reference (there is no
flag column and no null-text row). The transcript foreign key is **non-unique**: a
transcript may carry several references; each evaluation picks exactly one.
Evaluation-side only — generation never reads this table.

| Column | Type | Note |
|---|---|---|
| `summary_sha256` | TEXT PK | sha256 of the summary text |
| `summary_text` | TEXT NOT NULL | the literal reference summary, verbatim |
| `transcript_sha256` | TEXT FK → transcripts | non-unique |
| `dataset_name` | TEXT NOT NULL | courtesy triple, same rules as in `transcripts` |
| `entry_id` | TEXT NULL | |
| `entry_index` | INTEGER NOT NULL | |
| `updated_at` | TEXT NOT NULL | |

Example:

| summary_sha256 | summary_text | transcript_sha256 | dataset_name | entry_id | entry_index | updated_at |
|---|---|---|---|---|---|---|
| `77aa…01` | `Alice proposes slipping the release to…` | `9f1c…e2` | `meetbank` | `m218` | `41` | `2026-10-15T09:30:00Z` |

## 3. models

Model files under test (and, if ever allowed, local judge models). Identity is the
**content** of the model file: a file swapped at the same path is a new identity — a new
row; the old row and its generations remain. `name`/`model_path` are courtesy: the file
at that path may have been renamed or moved since, and nothing re-checks it.

| Column | Type | Note |
|---|---|---|
| `model_sha256` | TEXT PK | sha256 of the model file bytes |
| `name` | TEXT NOT NULL | courtesy: config identifier at last load |
| `model_path` | TEXT NOT NULL | courtesy: file location at last load |
| `updated_at` | TEXT NOT NULL | |

No behavioral parameters here — `model_args` and `gen_params` live in `generations`.

Example:

| model_sha256 | name | model_path | updated_at |
|---|---|---|---|
| `c3d9…4b` | `gemma-3-27b-it-q4_k_m` | `/home/vscode/models/gemma-3-27b-it-q4_k_m.gguf` | `2026-10-15T09:30:00Z` |

## 4. prompt_templates

Summarizer prompt templates only (judge prompts live in `judges`). `user_prefix` is a
pure **prefix**: the sent user content is exactly `user_prefix + transcript`. No
separator is injected by code, no placeholders exist in this column, ever. An empty
prefix (`""`) means the user content is exactly the transcript (the instruction lives in
`system_content`). Both text columns are NOT NULL; `""` = "no such message".

| Column | Type | Note |
|---|---|---|
| `template_sha256` | TEXT PK | sha256(canonical_json([system_content, user_prefix])) |
| `name` | TEXT NOT NULL | courtesy: config name, out of identity |
| `system_content` | TEXT NOT NULL | |
| `user_prefix` | TEXT NOT NULL | `""` legal |
| `updated_at` | TEXT NOT NULL | |

Example:

| template_sha256 | name | system_content | user_prefix | updated_at |
|---|---|---|---|---|
| `a1e0…9c` | `decision-minutes` | `Summarize the meeting as decision minutes…` | `Meeting transcript:` | `2026-10-15T09:30:00Z` |

## 5. judges

Endpoint-resident LLM judges; mirrors the config judge entry except credentials. A bare
endpoint profile — the app does not spawn, monitor, or stop the judge. `model_name` is
the **pin**: the provider-qualified stable identifier of the judge model (e.g.
`openrouter/llama-3-70b`). `endpoint` is deliberately out of the identity hash: it is an
access address, refreshable like a courtesy column — the same judge model at another
URL is the same judge. `api_key_env` holds only the environment-variable name.

Placeholders in `user_template`: `{transcript}` and `{summary}` are mandatory;
`{reference}` is meaningful iff `requires_reference` is on. Rendering substitutes a
placeholder only when its value is available; unrecognized or non-applicable
placeholders pass through as literal text. Static presence/absence validation is done
by `check`.

`requires_reference` is **in** the identity: two prompts identical apart from the flag
are different judges.

| Column | Type | Note |
|---|---|---|
| `judge_sha256` | TEXT PK | sha256(canonical_json([model_name, gen_params, system_content, user_template, requires_reference])) |
| `name` | TEXT NOT NULL | courtesy, out of identity |
| `endpoint` | TEXT NOT NULL | URL; out of identity, refreshable |
| `model_name` | TEXT NOT NULL | the pin |
| `gen_params` | TEXT NOT NULL | canonical JSON |
| `system_content` | TEXT NOT NULL | `""` legal |
| `user_template` | TEXT NOT NULL | placeholder template |
| `requires_reference` | INTEGER NOT NULL | 1/0; in identity |
| `api_key_env` | TEXT | environment-variable name only (decorative) |
| `updated_at` | TEXT NOT NULL | |

Example:

| judge_sha256 | name | endpoint | model_name | gen_params | system_content | user_template | requires_reference | api_key_env | updated_at |
|---|---|---|---|---|---|---|---|---|---|
| `5b7e…1f` | `openrouter-llama-3-70b` | `https://openrouter.ai/api/v1` | `openrouter/llama-3-70b` | `{"temperature": 0}` | `You score summaries on…` | `Transcript: {transcript}\nSummary: {summary}\nReference: {reference}\nReturn JSON…` | `1` | `OPENROUTER_API_KEY` | `2026-10-15T09:30:00Z` |

## 6. generations

One row per (transcript × summarizer). The primary key is **input-addressed**: derived
from what went in, so a candidate can be looked up before the model is called (that
lookup is the deduplication that makes repeated runs free). The summarizer's four
components appear exactly once each: model and template as foreign keys, `model_args`
and `gen_params` written out. `model_args` covers model behavior only — server-software
launch settings (`server.args`) are never stored.

| Column | Type | Note |
|---|---|---|
| `generation_sha256` | TEXT PK | sha256(canonical_json([transcript_sha256, model_sha256, model_args, template_sha256, gen_params])) |
| `generation_text` | TEXT NOT NULL | the generated summary, verbatim |
| `transcript_sha256` | TEXT FK → transcripts | |
| `model_sha256` | TEXT FK → models | |
| `model_args` | TEXT NOT NULL | canonical JSON; model behavior only |
| `template_sha256` | TEXT FK → prompt_templates | |
| `gen_params` | TEXT NOT NULL | canonical JSON; request-time generation params |
| `updated_at` | TEXT NOT NULL | creation-frozen in practice (all non-key values are fixed once generated) |

Example:

| generation_sha256 | generation_text | transcript_sha256 | model_sha256 | model_args | template_sha256 | gen_params | updated_at |
|---|---|---|---|---|---|---|---|
| `e842…d7` | `Decisions: release slipped to Q1…` | `9f1c…e2` | `c3d9…4b` | `{"flash-attn": true}` | `a1e0…9c` | `{"temperature": 0.3, "max_tokens": 2048}` | `2026-10-15T09:31:12Z` |

## 7. judge_evaluations

One row per (judge × generation × chosen reference). The reference foreign key is
nullable; "missing reference" is JSON `null` inside the identity hash. The hash primary
key is deliberate: a composite key would force NOT NULL or a sentinel, and a UNIQUE
index does not deduplicate NULLs, so the hash keeps the convention uniform. The three
 quality scores are nullable REALs: a judge response that parses only partially lands
 here with the values that came through; a response with no usable value is an exclusion
 (a console warning, never a store row) and never lands here. There is no raw-response
 column. Code (not the schema)
guarantees that a `requires_reference = 1` judge never produces a NULL-reference row.

| Column | Type | Note |
|---|---|---|
| `judge_evaluation_sha256` | TEXT PK | sha256(canonical_json([judge_sha256, generation_sha256, reference_summary_sha256 or null])) |
| `judge_sha256` | TEXT FK → judges | |
| `generation_sha256` | TEXT FK → generations | |
| `reference_summary_sha256` | TEXT NULL FK → reference_summaries | |
| `factual_correctness` | REAL NULL | |
| `completeness` | REAL NULL | |
| `conciseness` | REAL NULL | |
| `updated_at` | TEXT NOT NULL | moves only if a re-evaluation actually changes a value |

Example:

| judge_evaluation_sha256 | judge_sha256 | generation_sha256 | reference_summary_sha256 | factual_correctness | completeness | conciseness | updated_at |
|---|---|---|---|---|---|---|---|
| `b3a1…88` | `5b7e…1f` | `e842…d7` | `77aa…01` | `0.9` | `0.8` | `0.75` | `2026-10-15T09:40:03Z` |

## 8. metric_evaluations

One row per (metric × generation × chosen reference). `metric_name` is the bare
code-registry name of an implemented algorithmic metric: no foreign key, no metrics
table, no version or commit column. A new metric added to the code later simply writes
new rows under a new name; existing rows are untouched. `value` is a single scalar and
NOT NULL — a metric that cannot produce a proper value is an exclusion, not a row
(deliberate contrast with the judge nullables).

| Column | Type | Note |
|---|---|---|
| `metric_evaluation_sha256` | TEXT PK | sha256(canonical_json([metric_name, generation_sha256, reference_summary_sha256 or null])) |
| `metric_name` | TEXT NOT NULL | code-registry name |
| `generation_sha256` | TEXT FK → generations | |
| `reference_summary_sha256` | TEXT NULL FK → reference_summaries | |
| `value` | REAL NOT NULL | single scalar |
| `updated_at` | TEXT NOT NULL | creation-frozen (metrics are deterministic) |

Example:

| metric_evaluation_sha256 | metric_name | generation_sha256 | reference_summary_sha256 | value | updated_at |
|---|---|---|---|---|---|
| `0d55…c3` | `rouge_l` | `e842…d7` | `77aa…01` | `0.42` | `2026-10-15T09:41:00Z` |

## Relationships

 Every foreign key, listed explicitly as edges (source table.column → target table):

 | From | To | Note |
 |---|---|---|
 | `reference_summaries.transcript_sha256` | `transcripts` | non-unique: one transcript may carry several references |
 | `generations.transcript_sha256` | `transcripts` | |
 | `generations.model_sha256` | `models` | |
 | `generations.template_sha256` | `prompt_templates` | |
 | `judge_evaluations.judge_sha256` | `judges` | |
 | `judge_evaluations.generation_sha256` | `generations` | |
 | `judge_evaluations.reference_summary_sha256` | `reference_summaries` | nullable |
 | `metric_evaluations.generation_sha256` | `generations` | |
 | `metric_evaluations.reference_summary_sha256` | `reference_summaries` | nullable |

Every foreign key resolves to a row that is never deleted except by `clear`; a
generation's referenced transcript, model, template, and every evaluation's referenced
judge and reference are always present in the same store.
