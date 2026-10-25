# 02: Configuration + datasets; `check` static phase

**What to build:** The configuration is loaded as the universe of definitions under the full strict contract, datasets are loaded by extension, and `check` becomes the app's first end-to-end demo: a static lint that collects and prints ALL configuration and dataset contract failures in one pass, then exits 2 (the live phase is skipped). A user fixing typos sees everything that is wrong in one edit cycle, with the valid sets attached to name errors, and the scorer discovery display shows — in two disjoint groups per family — what exists and what will run by default. `check` opens the store read-only by default (never created unless explicitly opted in) and never commits.

**Blocked by:** 1 (Scaffold: executable, console contract, selection grammar)

**Status:** ready-for-agent

- [ ] Strict JSON configuration: duplicate keys in a definition section ⇒ `error: duplicate name '<x>' in <section>`; `*` used as a name ⇒ error; unrecognized fields ⇒ `warn: unrecognized field '<name>' in <location>` only; the open maps (`server.args`, `model_args`, `gen_params`, `env`) are exempt from recognition.
- [ ] Every summarizer resolves at load time to a full four-tuple (model + model_args + prompt template + gen_params); `base` copy-then-override names an earlier summarizer (later ⇒ static error); a stray `path` in a summarizer ⇒ error.
- [ ] model_args resolution is a two-layer merge (model entry, then summarizer override per key); the model path is never overridable from a summarizer; `server.args` never layers into model_args.
- [ ] Judge contract: `requires_reference` is a REQUIRED boolean (absent or non-boolean ⇒ exit 2); `{transcript}` and `{summary}` must appear in the system + user template combined (missing ⇒ error naming the placeholder); `{reference}` is required iff the flag is on; a superfluous `{reference}` with the flag off is legal; unknown `{...}` tokens are NOT errors (they pass through unsubstituted).
- [ ] Wholesale CLI overrides apply for the store path and the five server launch values on every command that spawns or could spawn; overrides are never written back; `default_metrics` / `default_judges` are NOT wholesale-replaceable.
- [ ] Datasets load by extension: CSV (RFC 4180, UTF-8), JSONL, JSON (one object per line); any other extension is a load-time contract failure.
- [ ] R1 fail-fast set (exit 2, naming file and line): missing/unreadable file, bad extension, declared purpose field absent, malformed rows (CSV column-count mismatch, duplicate header names; JSONL non-JSON line), zero entries, empty transcript value, entry-id field declared but any id empty. No transcript-length checks of any kind.
- [ ] R2: a missing reference summary is a per-pair warning and drop, never an error.
- [ ] The `check` static phase collects and prints ALL failures in one pass, then exits 2; the live phase is skipped (deliberate contrast to the fail-fast run commands).
- [ ] `check` errors carry the valid sets (e.g. an unknown metric lists the registered metrics; an unknown judge lists the configured judges).
- [ ] Scorer discovery is printed regardless of store presence, in two disjoint groups per family (named in the relevant default vs. registered/configured but not named there); every registered metric and configured judge appears in exactly one group.
- [ ] The `server.command` binary and every model file must exist; the configured port already bound ⇒ failure plus a hint that an orphaned server may be holding it.
- [ ] Store: `check` opens read-only by default (absent store ⇒ `note:`, never created); the explicit opt-in flag applies the normal shared open path; probe results are discarded; `check` never commits.
- [ ] Against the normative example configuration at the repo root (whose data, prompt, and model paths are illustrative and absent), `check` reports those missing-file contract failures and exits 2 — the expected first end-to-end demo until the files exist.

## Comments
- 2026-10-25 — split into 02a (boxes 1–4), 02b (boxes 6–7; box 8/R2 out of scope per design decision 4), 02c (box 5 + Store.open_readonly/port pre-scan/--server-* flags + score gate), 02d (boxes 9, 10, 11, 14 + _check rewrite + existing-test and docs/commands.md updates). A/B/C independent; D after A+B+C. Close the parts, not this file.
