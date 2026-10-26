# 02a: Configuration strict contract (collect mode)

**What to build:** Part A of ticket 02 (its boxes 1–4): the configuration is loaded under the full strict contract. `load_config` gains a collect mode (duplicate-name errors can be appended instead of raised; file/JSON failures still raise), and a new `validate_config(config, console) -> (errors, resolved)` checks section shapes, name rules, per-section field contracts, unrecognized-field warnings, summarizer base-chain resolution to a four-tuple, and the judge placeholder contract. Only `check` (ticket 02d) calls the collect mode; the fail-fast paths of the run commands stay byte-identical.

**Blocked by:** 1 (Scaffold: executable, console contract, selection grammar)

**Status:** ready-for-agent

**Series note (02a–02d):** implement the four parts sequentially in a single context — no subagent orchestration; each part is self-contained and commits on its own.

- [x] Strict JSON configuration: duplicate keys in a definition section ⇒ `error: duplicate name '<x>' in <section>`; `*` used as a name ⇒ error; unrecognized fields ⇒ `warn: unrecognized field '<name>' in <location>` only; the open maps (`server.args`, `model_args`, `gen_params`, `env`) are exempt from recognition.
- [x] Every summarizer resolves at load time to a full four-tuple (model + model_args + prompt template + gen_params); `base` copy-then-override names an earlier summarizer (later ⇒ static error); a stray `path` in a summarizer ⇒ error.
- [x] model_args resolution is a two-layer merge (model entry, then summarizer override per key); the model path is never overridable from a summarizer; `server.args` never layers into model_args.
- [x] Judge contract: `requires_reference` is a REQUIRED boolean (absent or non-boolean ⇒ exit 2); `{transcript}` and `{summary}` must appear in the system + user template combined (missing ⇒ error naming the placeholder); `{reference}` is required iff the flag is on; a superfluous `{reference}` with the flag off is legal; unknown `{...}` tokens are NOT errors (they pass through unsubstituted).

## Settled design (implement as written; do not re-derive from the docs)

1. **`validate_config(config, console) -> (errors, resolved)`** — ONLY `check` calls it; run commands stay fail-fast. **Refinements (mine):**
   - `load_config` gains optional `errors=None` param: dups in `_convert` append to `errors` when given else raise (file-missing/JSON errors ALWAYS raise, even for check ⇒ no discovery then). Top-level unrecognized warns MOVE out of `_convert` into `load_config` after convert (console.warn, file order — identical output to today).
   - `validate_config` pass 1 = per-section shape/name/field errors in top-level FILE order (iterate `config` dict keys in order; `store` check included): `config.server` + all 5 section entry-level unrecognized warns emitted here (only when section/entry is a dict; `path` key in summarizer has its own error and is exempt from warn scan). Pass 2 = summarizer resolution (file order), then defaults type/unknown checks.
   - **Summarizer resolution:** child starts from base's RESOLVED spec iff base name is an EARLIER entry; else error `base 'Y' must appear earlier in the file` AND start from empty spec (decision 9: component errors still fire if components missing). Child: model/prompt_template override outright; model_args/gen_params merge per key over model-entry baseline (absent ≡ `{}`); `server.args` never layers; path never overridable. Component "resolvable" = name EXISTS in the section (entry validity reported separately). Resolved dict: `{"model": name, "model_args": {...}, "prompt_template": name, "gen_params": {...}}`.
   - **resolved dict:** `store` (str or None if absent/invalid), `server` (validated dict or None), `models` {name:{path,model_args,gen_params}} valid entries only, `prompt_templates` {name:path}, `summarizers` {name:4-tuple}, `datasets` {name:decl}, `judges` {name:entry}, `defaults` {metrics: raw list or None, judges: raw list or None}.

## Current state (re-verified; rely on it)

- **`evalapp/config.py` (127L):** `load_config(path, explicit, console)` fail-fast (FileNotFound→2 msgs, OSError→`cannot read config file: {p}: {detail}`, JSONDecodeError→`invalid JSON in {p}: {exc}`, not-dict→`invalid JSON in {p}: top-level value must be an object`). Dups + top-level unrecognized warns live in `_convert` (via `_Pairs`/`_object_pairs_hook`); `KNOWN_TOP_LEVEL_FIELDS` = 9. `validate_datasets(config)` fail-fast (declared dict: path, transcript_field, reference_field, entry_id_field=None). `effective_store_path(config, override)`: override → config `store` (non-empty str else `config 'store' must be a non-empty string`) → `store.db`.
- **`evalapp/errors.py`:** `SpecError` (2), `RuntimeFailure` (1). — `main` in `evalapp/cli.py` (153L) maps them: SpecError→2, RuntimeFailure→1 (run commands stay fail-fast).
- **`evalapp/metrics/__init__.py`:** `registered_names()` sorted (5: `conciseness_length_proxy, faithfulness, internal_consistency, key_claim_completeness, structural_instruction_check`); `_unknown_metric(name)` (line 66) = `unknown metric '{name}' (registered: {', '.join(registered_names())})`.

## Exact strings (config contract) — keep EXACT

- **Load (fail-fast, UNCHANGED):** `config file not found: <p>` / `config file not found: config.json (pass --config PATH to use another)` / `cannot read config file: <p>: <detail>` / `invalid JSON in <p>: <exc>` / `duplicate name '<k>' in <location>` — location: top-level children use own key; deeper uses top-level section key (dup inside model entry ⇒ `... in models`; dup inside server ⇒ `... in server`).
- `store`: `config 'store' must be a non-empty string`.
- Names: `name '*' is reserved` (NO section in message); `invalid name '<key>' in <section>` (invalid = empty or any whitespace char).
- Sections: `<section> must be an object mapping names to entries` (models, prompt_templates, summarizers, datasets, judges).
- Server: `config 'server' must be an object`; fixed order: `server: field 'command' must be a string` → `server: field 'args' must be an object` → `server: field 'env' must be an object` → `server: field 'port' is required and must be a number` → `server: field 'startup_timeout_s' is required and must be a number` (number = int/float, bool excluded).
- Model: `model '<n>': entry must be an object` → `field 'path' must be a string` → `field 'model_args' must be an object` → `field 'gen_params' must be an object`.
- Template: `prompt template '<n>': entry must be an object` → `field 'path' must be a string`.
- Summarizer: `summarizer '<n>': entry must be an object` → `summarizer '<n>': field 'path' is not allowed — the model path is fixed by the model entry` (EM DASH) → `field '<f>' must be a string` (base, model, prompt_template order) → `field '<f>' must be an object` (model_args, gen_params) → `summarizer 'X': base 'Y' must appear earlier in the file` (same string for unknown/later/self) → `summarizer 'X': component 'model' not resolvable (set it directly or via a base chain)` then same for `'prompt_template'` (model FIRST).
- Judge (per-entry order): `judge '<n>': entry must be an object` → `field '<f>' must be a string` (endpoint, model_name, api_key_env, user_template) → `judge '<n>': requires_reference is required and must be a boolean` → `field 'gen_params' must be an object` → `field 'system_content' must be a string` → placeholders (scan over system+user combined; runs iff user_template is str AND requires_reference is bool; system defaults `""` if absent or non-str): `judge 'X': missing placeholder '{transcript}'` → `judge 'X': missing placeholder '{summary}'` → iff flag true: `judge 'X': requires_reference is true but placeholder '{reference}' is missing`. Superfluous `{reference}` legal; unknown `{...}` legal.
- Defaults: `default_metrics must be a list of strings` / `default_judges must be a list of strings`; any non-str element ⇒ ONE error `default_metrics: entries must be strings` (same shape for judges); unknowns ONE error each AFTER type errors, deduped first-occurrence order: reuse `metrics._unknown_metric(name)`; `unknown judge '<x>' (configured: <config-order names>)` (empty roster ⇒ `(none)`).
- Warns: `warn: unrecognized field '<name>' in <location>` — locations: `config`, `config.server`, `models.<n>`, `prompt_templates.<n>`, `summarizers.<n>`, `datasets.<n>`, `judges.<n>`.

## Implementation

1. **`evalapp/config.py`:** `load_config(errors=None)` + move top-level warns out of `_convert`; add `validate_config` (+ `_warn_unrecognized(config, console, sections_only)` helper: `sections_only=True` covers `config.server` + 5 section entry levels; `False` = top-level only). Keep `load_config`/`validate_datasets`/`effective_store_path` fail-fast byte-identical for run commands.

## Tests to add

- Config contract (sections, names, reserved, warns incl. `config.server`/entry locations, defaults); summarizer resolution (base chains, per-key merge, unresolvable base ⇒ base error + component errors); judge contract/placeholders.

## Definition of done

- `/usr/local/py-utils/bin/pytest tests/ -q` stays green (baseline **146 passed**); stdlib only. (NOT `/usr/local/python/current/bin/python3` — 3.14.8, no pytest installed.)
- Tick all boxes in this ticket and append a `## Comments` line (date + what was implemented).
- One commit including this ticket file: `git -c user.name="Codex" -c user.email="codex@local" commit -m "feat: ticket 02a — config strict contract"`.

## Comments
2026-10-26 — Implemented load_config collect mode (errors param) and validate_config strict contract (sections/names/fields, warns, summarizer base-chain resolution, judge placeholder contract, defaults); added tests/test_config_contract.py (85 tests).
