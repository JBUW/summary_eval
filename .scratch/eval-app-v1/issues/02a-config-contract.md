# 02a: Configuration strict contract (collect mode)

**What to build:** Part A of ticket 02 (its boxes 1–4): the configuration is loaded under the full strict contract. `load_config` gains a collect mode (duplicate-name errors can be appended instead of raised; file/JSON failures still raise), and a new `validate_config(config, console) -> (errors, resolved)` checks section shapes, name rules, per-section field contracts, unrecognized-field warnings, summarizer base-chain resolution to a four-tuple, and the judge placeholder contract. Only `check` (ticket 02d) calls the collect mode; the fail-fast paths of the run commands stay byte-identical.

**Blocked by:** 1 (Scaffold: executable, console contract, selection grammar)

**Status:** ready-for-agent

- [ ] Strict JSON configuration: duplicate keys in a definition section ⇒ `error: duplicate name '<x>' in <section>`; `*` used as a name ⇒ error; unrecognized fields ⇒ `warn: unrecognized field '<name>' in <location>` only; the open maps (`server.args`, `model_args`, `gen_params`, `env`) are exempt from recognition.
- [ ] Every summarizer resolves at load time to a full four-tuple (model + model_args + prompt template + gen_params); `base` copy-then-override names an earlier summarizer (later ⇒ static error); a stray `path` in a summarizer ⇒ error.
- [ ] model_args resolution is a two-layer merge (model entry, then summarizer override per key); the model path is never overridable from a summarizer; `server.args` never layers into model_args.
- [ ] Judge contract: `requires_reference` is a REQUIRED boolean (absent or non-boolean ⇒ exit 2); `{transcript}` and `{summary}` must appear in the system + user template combined (missing ⇒ error naming the placeholder); `{reference}` is required iff the flag is on; a superfluous `{reference}` with the flag off is legal; unknown `{...}` tokens are NOT errors (they pass through unsubstituted).

## Comments
