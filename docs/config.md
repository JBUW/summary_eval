# Configuration file

Authoritative, current specification of the configuration file (v1). This file is the
"what it is now" reference; `.scratch/grill-with-docs/DECISIONS.md` is the decision log
(the "why and when").

House rule: any decision that changes the configuration updates this file in the same
round as the log entry. If the two ever disagree, this file states what the config looks
like today and the log explains the change.

## Conventions

- **Location:** the default config file is `config.json` in the working directory;
  `--config PATH` points to another (the flag is shared by all subcommands, see
  `docs/commands.md`). A missing file is a pre-effect failure (exit 2):
  `error: config file not found: config.json (pass --config PATH to use another)`.
  An explicitly given file that is missing or not valid JSON is also exit 2.
- **JSON, strict:** the file is parsed with a duplicate-key check — standard JSON
  parsing silently lets the last duplicate win, which is exactly the inconsistency the
  check exists to catch: `error: duplicate name '<x>' in <section>` (exit 2). The check
  runs in the same shared loading pass as the unrecognized-field scan below.
- **Unrecognized fields warn, they do not fail:** a key at a schema-fixed level that is
  not in the recognized set for that level is ignored but reported, one line per field,
  exit code unaffected: `warn: unrecognized field '<name>' in <location>`. The CONTENTS
  of the open maps `server.args`, `model_args`, `gen_params`, and `env` are exempt —
  their keys belong to the model server binary or the request layer, not to this
  application's schema, and they are passed through untouched.
- **No computable hashes:** the config never carries identity hashes. Every store
  identity is computed at commit time from the stored values (see `docs/store-schema.md`);
  a hash typed into the config could be edited into inconsistency, so it is not a
  configuration input.
- **Names are handles, never identities:** the keys inside `models`, `prompt_templates`,
  `summarizers`, `datasets`, and `judges` are names — CLI selection tokens and store
  courtesy columns, never part of any store identity hash. A name must match a
  conservative identifier pattern (no whitespace): `invalid name '<key>' in <section>`
  (exit 2). `*` is reserved for the CLI's "all" token: `error: name '*' is reserved`
  (exit 2).
- **Key order is convention, not contract:** the top-level key order shown in the
  normative example below is the house order; it is not validated and not part of any
  error.
- **Normative example:** the `config.json` at the repo root is the normative example
  configuration. The data/prompt/model paths it references are illustrative and absent
  from the repo; `check` reporting them as contract failures is expected until they
  exist.

## Sections

### `store`

| Field | Type | Required | Meaning |
|---|---|---|---|
| `store` | string | no (default `store.db`) | path of the single SQLite file that is the results store |

The `--store PATH` flag overrides this value. See `docs/store-schema.md` for what the
file holds.

### `server`

Launch configuration for the model server the application spawns. The section is
launch-only: nothing in it is ever stored in the results store (directly or indirectly),
and none of it is part of any identity. An absent `server` section makes `generate` a
hard error (exit 2); there is no fallback launch.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `command` | string | yes | path of the server executable |
| `args` | object | no (absent ≡ `{}`) | launch arguments of the server SOFTWARE. Keys are the binary's flag names; see the renderer below. Absent or empty renders nothing |
| `env` | object | no (default `{}`) | environment variables for the spawned process, passed through untouched |
| `port` | number | yes | port the server listens on; the single value for the pre-scan (bound ⇒ exit 2), the launch `--port`, readiness polling, and the exit-2 message |
| `startup_timeout_s` | number | yes | seconds to wait for the server to become ready |

**The argument renderer.** `server.args` and `model_args` are associative arrays
rendered by one shared rule: key ⇒ `--key`; scalar ⇒ `--key value`; `true` ⇒ bare
`--key`; `false` ⇒ omitted. The effective launch command is:

    server.command + rendered server.args + rendered resolved model_args + --port <port> + --model <model path>

On any startup failure the fully rendered command is printed, so nothing is lost by
keeping the config in map form.

**`server.args` vs `model_args` (deliberate asymmetry).** `server.args` is flat,
single-sourced, and never layers into anything: it configures the server software
(context window, batch size, …) and must not contain anything that affects model output.
`model_args` varies between candidates, so it is layered (model entry ← summarizer
override, below) and is the only args column ever stored. It is the user's
responsibility to keep output-affecting settings out of `server.args`; the
configuration does not police it.

### `models`

Name-keyed object: model name → entry. A model entry fixes the file and its
behavior-affecting launch arguments; a model is identified in the store by the sha256 of
the file's bytes (computed, never in the config).

| Field | Type | Required | Meaning |
|---|---|---|---|
| `path` | string | yes | path of the model file |
| `model_args` | object | no (absent ≡ `{}`) | model-behavior launch arguments; the baseline for summarizer overrides |
| `gen_params` | object | no (absent ≡ `{}`) | request-time sampling parameters; the baseline for summarizer overrides |

`{"path": …}` alone is a legal entry. Absent ≡ empty applies to the parameter maps at
config/resolution/wire level only; the CLI's `[]`-versus-omitted distinction is a
different matter and untouched. A resolved empty `gen_params` sends no sampling fields
and the server's defaults apply — there is no "must be non-empty" rule.

### `prompt_templates`

Name-keyed object: template name → entry.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `path` | string | yes | path of the template file |

The config entry is the file reference only. The template file's own format, how a
template turns a transcript into the exact messages sent (system content + user prefix,
where the sent user content is exactly `user_prefix + transcript`), and the store's
`prompt_templates` row are specified by `docs/store-schema.md` §4. Terminology: a prompt
template is a recipe; it is NOT the prompt that is sent (the sent prompt is the template
instantiated with a specific transcript).

### `summarizers`

Name-keyed object: summarizer name → entry. A **Summarizer** is a candidate: the four
components model + `model_args` + prompt template + `gen_params`. Every summarizer
resolves to exactly one of these 4-tuples, statically, as a pure function of the config:

| Field | Type | Required | Meaning |
|---|---|---|---|
| `base` | string | no | name of an EARLIER summarizer entry to build on (see below) |
| `model` | string | see below | name of a model entry |
| `prompt_template` | string | see below | name of a prompt-template entry |
| `model_args` | object | no | per-key overrides of the model entry's `model_args` |
| `gen_params` | object | no | per-key overrides of the model entry's `gen_params` |

- **`base` semantics.** The child starts from the base's RESOLVED spec: references
  (`model`, `prompt_template`) are overridden outright when the child sets them; objects
  (`model_args`, `gen_params`) merge per key, so `{"flash-attn": false}` cancels a
  base's `{"flash-attn": true}`. `base` must appear earlier in the file:
  `summarizer 'no-fa': base 'std' must appear earlier in the file`. The name is never
  copied.
- **Resolution is two-stage.** Stage 1: each model entry's `model_args`/`gen_params`
  stand as-is (absent ≡ `{}`). Stage 2: each summarizer applies its own `model_args` /
  `gen_params` per-key over the stage-1 baseline of its model. `server.args` never
  layers in. A missing component is hard-filled from the config — it is NEVER
  "the currently loaded model plus its startup parameters".
- **The model path is not overridable.** A summarizer may reference a model entry but
  never set a path: `summarizer 'X': field 'path' is not allowed — the model path is
  fixed by the model entry`. Overriding the path would misrepresent the candidate.
- **Failure messages (exit 2):** an unresolvable component: `summarizer 'X': component
  'prompt_template' not resolvable (set it directly or via a base chain)`.
- **Consequences.** Two summarizers resolving to the same 4-tuple are the same
  candidate (a pure `base` copy produces a duplicate that is skipped, not re-run).
  Because resolution is static, a model or its `model_args` may change mid-run and the
  server cycles per distinct resolved `(model, model_args)`; the currently loaded model
  may affect only the ORDER of work (scheduling), never its identity. The store keeps
  the resolved values, never the config references.

### `datasets`

Name-keyed object: dataset name → entry.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `path` | string | yes | path of the dataset file |
| `transcript_field` | string | yes | column (CSV) or object key (JSONL) holding the transcript |
| `reference_field` | string | no | column/key holding the reference summary |
| `entry_id_field` | string | no | column/key holding the entry's identifier |

There is no `format` field and no reference-usage flag: references exist for a dataset
iff `reference_field` is present, and the dataset is named iff `entry_id_field` is
present (both auto-detected from the declaration; entry contents are never read past
the declared fields).

**File format is the file extension:** `.csv` — fields are column names, RFC-4180,
UTF-8; `.jsonl` and `.json` — one JSON object per line, fields are object keys. Any
other extension is a load failure (exit 2).

**Contract R1 (load-time, fail-fast, exit 2):** the file is unreadable or missing; the
extension is not one of the two supported; a declared field is absent from the file; a
row is malformed; the file has zero entries; a transcript is empty; a declared
`entry_id_field` yields any empty id, or ids repeat within the dataset (uniqueness is
enforced within a dataset only — across datasets neither enforced nor assumed); a
declared `reference_field` yields any empty reference.

**Contract R2 (runtime, warn-and-drop, exit 0):** a reference-requiring scorer (a judge
with `requires_reference: true`) selected over a dataset without references is
infeasible: one `warn:` per infeasible pair, the pair is dropped, and the run
proceeds. Zero feasible pairs ⇒ the warnings plus
`note: no scorable pairs in scope; nothing scored`, exit 0.

**No length checks, no length configuration keys in v1.** Whether a transcript fits a
model's context is a runtime question: `check`'s context-adequacy probe reports it
warn-only, and `generate` fails fast (exit 1) on a transcript the model cannot take.

### `judges`

Name-keyed object: judge name → entry. A judge is an endpoint-resident LLM: the
application calls it but never spawns, monitors, or stops it.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `endpoint` | string | yes | URL of the judge's OpenAI-compatible endpoint. An access address: refreshable, and deliberately OUT of the store identity (the same judge model at another URL is the same judge) |
| `model_name` | string | yes | the pin: provider-qualified stable identifier of the judge model |
| `api_key_env` | string | yes | NAME of the environment variable holding the credential. Credentials never live in the config |
| `requires_reference` | boolean | yes (no default) | whether the judge needs a reference summary. Absent or non-boolean ⇒ exit 2 |
| `gen_params` | object | no (absent ≡ `{}`) | request-time sampling parameters for the judge calls |
| `system_content` | string | no (absent ≡ `""`) | the judge prompt's system message |
| `user_template` | string | yes | the judge prompt's user message as a placeholder template |

**Placeholder validation (pre-effect, exit 2).** The required placeholders are scanned
over `system_content` + `user_template` combined: `{transcript}` and `{summary}` are
always required — missing ⇒ `judge 'X': missing placeholder '<p>'`; with
`requires_reference: true`, `{reference}` is additionally required — missing ⇒
`judge 'X': requires_reference is true but placeholder '{reference}' is missing`. A
`{reference}` placeholder while the flag is off is legal (superfluous). Unrecognized
`{…}` tokens pass through untouched.

**Rendering.** A placeholder is substituted only when its value is available for the
call; unrecognized or non-applicable placeholders pass through as literal text. There is
no substituted-in stand-in for a missing reference — code prevents a
reference-requiring judge from ever being called without one (R2 drops the pair
earlier).

**Store identity.** See `docs/store-schema.md` §5: the identity is the hash of
`[model_name, gen_params, system_content, user_template, requires_reference]` — the
name key, `endpoint`, and `api_key_env` are out.

### `default_judges` / `default_metrics`

Both optional lists of names. `default_judges`: names of judges from the `judges`
object. `default_metrics`: names of code-registered metrics. Neither list is a registry:
the metric universe is the code (any registered metric is invocable by name or `*`
whether or not it appears in the config); the judge universe is the `judges` object. An
unknown name in either list is exit 2 with the roster, e.g.
`error: unknown metric 'rougeX' (registered: …)` /
`error: unknown judge 'gpt-4o' (configured: …)`.

**Present-but-`[]` ≠ absent.** For `score`: with the flag omitted, `default_metrics`
present-but-`[]` selects zero metrics, while an ABSENT key selects all code-registered
metrics. Same for `default_judges` under the bare `--judges` case (below). The
command-line `[]`-versus-omitted distinction for the flags themselves is documented
per command in `docs/commands.md`.

## Config ↔ command line

The division of labor: the configuration is the universe of definitions (models, prompt
templates, summarizers, datasets, judges, defaults); the command line selects and
steers; the store holds results and is independent of both.

- **Wholesale overrides** (replace the config value for the run; fail-fast exit 2;
  never written back to the file) cover exactly the non-definition values: `store`,
  `server.command`, `server.args`, `server.env`, `server.port`,
  `server.startup_timeout_s` — as `--store`, `--server-command`, `--server-args <json>`,
  `--server-env <json>`, `--server-port`, `--server-startup-timeout` — available on every
  server-spawning command (`generate`, `score` only together with `--generate`, `sweep`,
  `check`); `--server-*` without `--generate` ⇒ exit 2
  `error: --server-* flags require --generate`; invalid JSON ⇒
  `invalid JSON for --server-args: <detail>`. After override, the port is a single
  effective value used everywhere (pre-scan, launch, readiness, error message).
  `default_metrics` / `default_judges` are NOT wholesale-replaceable — they interact
  with the `--metrics` / `--judges` flags by the precedence documented per command in
  `docs/commands.md` (including the shorthands `--no-metrics` ≡ `--metrics []` and
  `--no-judges` ≡ `--judges []`, each mutually exclusive with its `--X` in any form).
- **Selection flags** (`--select`, `--summarizer`, `--model`, `--prompt-template`,
  `--metrics`, `--judges`, …) select from the config's universe; unknown names are
  exit 2. The `--select` grammar itself is specified in `docs/commands.md`.
- **The store is not a config input.** Courtesy name columns in the store originate
  from the config but are never resolved against it; the config never reads the store
  for behavior (deduplication aside, which is an artifact of the current command set,
  not a hard rule).

## Normative example

`config.json` (repo root), verbatim:

```json
{
  "store": "evalstore.sqlite3",
  "server": {
    "command": "/home/vscode/llama.cpp/build-rocm/bin/llama-server",
    "args": {
      "ctx-size": 32768,
      "batch-size": 512
    },
    "env": {},
    "port": 8080,
    "startup_timeout_s": 120
  },
  "models": {
    "gemma-3-27b-it-q4_k_m": {
      "path": "/home/vscode/models/gemma-3-27b-it.Q4_K_M.gguf",
      "model_args": {
        "flash-attn": true
      },
      "gen_params": {
        "temperature": 0.3,
        "max_tokens": 2048
      }
    },
    "qwen3-32b-it-q4_k_m": {
      "path": "/home/vscode/models/qwen3-32b-it.Q4_K_M.gguf",
      "model_args": {
        "flash-attn": true
      },
      "gen_params": {
        "temperature": 0.5,
        "max_tokens": 1024
      }
    }
  },
  "prompt_templates": {
    "decision-minutes": {
      "path": "prompts/decision-minutes.json"
    },
    "detailed-report": {
      "path": "prompts/detailed-report.json"
    },
    "brief-summary": {
      "path": "prompts/brief-summary.json"
    }
  },
  "summarizers": {
    "std": {
      "model": "gemma-3-27b-it-q4_k_m",
      "prompt_template": "decision-minutes"
    },
    "no-fa": {
      "base": "std",
      "model_args": {
        "flash-attn": false
      }
    },
    "qwen-warm": {
      "base": "std",
      "model": "qwen3-32b-it-q4_k_m",
      "prompt_template": "brief-summary",
      "gen_params": {
        "temperature": 0.7
      }
    },
    "second-look": {
      "base": "std"
    }
  },
  "datasets": {
    "meetbank": {
      "path": "data/meetbank_50.csv",
      "transcript_field": "transcript",
      "reference_field": "golden_summary",
      "entry_id_field": "doc_id"
    },
    "qmsum-dev": {
      "path": "data/qmsum_dev.jsonl",
      "transcript_field": "dialogue"
    }
  },
  "judges": {
    "openrouter-llama-3-70b": {
      "endpoint": "https://openrouter.ai/api/v1",
      "model_name": "openrouter/llama-3-70b",
      "api_key_env": "OPENROUTER_API_KEY",
      "requires_reference": true,
      "gen_params": {
        "temperature": 0.0,
        "max_tokens": 512
      },
      "system_content": "You are an impartial judge of summarization quality. Score each requested quality as a number on the declared scale; answer only the rubric.",
      "user_template": "Transcript:\n{transcript}\n\nSummary under evaluation:\n{summary}\n\nReference summary:\n{reference}\n\nScore: factual_correctness, completeness, conciseness."
    }
  },
  "default_judges": [
    "openrouter-llama-3-70b"
  ],
  "default_metrics": [
    "faithfulness",
    "key_claim_completeness",
    "conciseness_length_proxy",
    "structural_instruction_check"
  ]
}
```

## Not in the config

- **The metric registry** — code; names only are referenced (`default_metrics`, `--metrics`).
- **Any hash** — every identity is computed at commit time.
- **Credentials** — only the environment-variable NAME (`api_key_env`).
- **Length bounds** — no maximum-length field anywhere; the fit question is a runtime
  probe / fail-fast (see `datasets` above).
- **`server.args` in the store** — launch-time software setting; never stored.
- **`ACCEPT_PARTIAL_RESULTS`** — a code constant in v1, not configurable.
- **Dataset entry contents** — the config declares fields; the file holds the data.
- **Store contents** — results live in the store file, not the config.
