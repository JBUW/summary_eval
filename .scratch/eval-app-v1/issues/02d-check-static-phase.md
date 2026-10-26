# 02d: check static phase (collect-all, discovery, file checks)

**What to build:** Part D of ticket 02 (its boxes 9, 10, 11, 14): the `check` static phase end-to-end — `load_config` collect mode → `validate_config` → the six-line scorer discovery (byte-exact, printed whenever the config parses) → ALL failures printed in one pass, exit 2, live phase skipped → otherwise `plan(check): N datasets` → static file checks (datasets, `server.command`, model files, prompt templates, port pre-scan, judge env vars under `--probe-judges`) → store handling (read-only by default; `--create-store` opt-in) → exit 0. Includes the existing-test flips (serverless workspaces now exit 2) and the stale `docs/commands.md` example fixes, in the same round.

**Blocked by:** 02a (Configuration strict contract), 02b (Dataset load contract), 02c (Check plumbing)

**Status:** ready-for-agent

- [x] The `check` static phase collects and prints ALL failures in one pass, then exits 2; the live phase is skipped (deliberate contrast to the fail-fast run commands).
- [x] `check` errors carry the valid sets (e.g. an unknown metric lists the registered metrics; an unknown judge lists the configured judges).
- [x] Scorer discovery is printed regardless of store presence, in two disjoint groups per family (named in the relevant default vs. registered/configured but not named there); every registered metric and configured judge appears in exactly one group.
- [x] Against the normative example configuration at the repo root (whose data, prompt, and model paths are illustrative and absent), `check` reports those missing-file contract failures and exits 2 — the expected first end-to-end demo until the files exist.

## Settled design (implement as written; do not re-derive from the docs)

1. **Discovery groups:** group1 = config FILE order (dedupe keep-first, unknowns filtered, non-str skipped) for both families; `default_X` absent (or not a list) ⇒ group1 = ALL universe (metrics registry sorted / judges config-order keys), group2 `(none)`; present (even `[]`) ⇒ group1 = that list, group2 = remainder in universe order. Doc's literal `(absent ⇒ all configured)` annotation is **NOT rendered**.
2. **Discovery display, byte-exact, 6 lines:** headers `metrics (registered: N):` (N=5) / `judges (configured: M):` (M = keys in judges section, 0 if absent/invalid); value lines = `f"  {label}:".ljust(33) + value` (trailing spaces: `default_metrics:`→15, `registered, not named there:`→3, `default_judges:`→16, `configured, not named there:`→3; ljust(33) uniform); empty ⇒ `(none)` else `", ".join`. Printed whenever config PARSES (even with errors), AFTER all warns, BEFORE all error lines, plain `print` (no console prefix).
3. **check flow (order matters):** `load_config(errors=collector)` [file/JSON errors ⇒ SpecError as today, no discovery] → `validate_config` [warns via console, errors collected] → print discovery 6 lines → if errors: print all `error:` lines, exit 2 (NO plan line, NO store handling). Else: `plan(check): N datasets` (N = len of datasets section, 0 if absent) → static file checks in this order: **datasets (all errors per file, config order) → server.command existence → model files → prompt template files → port pre-scan → judge env (only if `--probe-judges`)** → print any errors, exit 2 if any → else store handling → exit 0. Effective server: `command = --server-command or config command (if str)`; `port = --server-port or config port (if number)`; `no server section in config (no fallback launch)` fires iff config has no server section AND no `--server-command`; command check iff command not None; port pre-scan iff port not None. `--server-args`/`--server-env` JSON-parsed in check (and generate/sweep/score handlers where accepted? — for ticket 02 only check actually uses them; parse+validate in check with the two error strings + must-be-object; other commands just accept the flags unused) — DECIDE: parse in a shared helper called from check; keeping it check-only is simplest and no other command uses them yet.
4. **check store handling:** default read-only: absent ⇒ `note: no store at <p>` (never created); present ⇒ open read-only `sqlite3.connect(f"file:{path}?mode=ro", uri=True)`, schema check runs (≥1 table); mismatch ⇒ `_MISMATCH` error exit 2; unopenable ⇒ `cannot open store at {path}: {exc}`; empty file (0 tables) present ⇒ OK, no bootstrap. `--create-store` ⇒ normal `Store(path)` shared path (bootstrap note `created empty store at <p>` if created); probe results discarded; never commits. **Implementation (mine):** add `Store.open_readonly(path)` classmethod (or module fn) → `None` if file absent, else Store with `readonly=True`: skip makedirs, connect via URI, zero-tables ⇒ NO bootstrap (treat as valid empty), ≥1 ⇒ `_verify_schema`. Reuse the static `_columns_of`/`_foreign_keys_of`.
5. **File-existence checks:** `os.path.exists` for server.command / model files / prompt template paths.
- `plan(check): N datasets` emitted only when config-shape is clean (after discovery, before file checks); NOT on the error exit-2 path.
- Judge env check uses `os.environ.get(var)` — unset OR `""` ⇒ error; only for judges whose api_key_env is a str (shape errors already reported otherwise).
- `default_metrics`/`default_judges` discovery uses the raw list values (non-str skipped, unknowns filtered, dedupe keep-first).
- **Stale-handoff guard (resolved contradiction — final design wins):** the 2026-10-25 session handoffs 07 (15:00) and 08 (15:09) claimed "absent server must not fail / check exits 0 on the standard workspace" and "remove the `plan(check)` line" — both **wrong**; an absent server **is** a check error (`no server section in config (no fallback launch)`), firing in the static stage **after** the `plan(check): N datasets` line, which is **kept** (146 existing tests + docs depend on it).

## Current state (re-verified; rely on it)

- **`evalapp/cli.py` (153L):** `_check` today: load → validate_datasets → `plan(check): N datasets` → `note: no store at {p}` if absent → 0.
- **`evalapp/console.py`:** stage assert warn(0)→plan(1)→note(2); error/done unconstrained.
- **`evalapp/metrics/__init__.py`:** `registered_names()` sorted (5: `conciseness_length_proxy, faithfulness, internal_consistency, key_claim_completeness, structural_instruction_check`); `_unknown_metric(name)` (line 66) = `unknown metric '{name}' (registered: {', '.join(registered_names())})`.
- **`tests/harness.py`:** `run_cli(argv, cwd)`, `RunResult.lines/with_prefix/assert_exit`, `write_text/write_csv/write_jsonl`, `write_config(path, datasets, store=None, extra_top_level=None)`, `standard_workspace` (2× 12-entry JSONL: `named` ids id-00..id-11, `unnamed`; config store=`store.db`), `plan_count`.
- **Repo `config.json`:** normative example — server cmd + 2 model paths + 3 prompt paths all ABSENT, 4 summarizers (std / no-fa / qwen-warm / second-look w/ base chains), datasets meetbank (CSV, 3 fields) + qmsum-dev (JSONL, transcript only), 1 judge `openrouter-llama-3-70b` (requires_reference true, api_key_env `OPENROUTER_API_KEY`, port 8080), `default_judges`=[that judge], `default_metrics`=[faithfulness, key_claim_completeness, conciseness_length_proxy, structural_instruction_check] (`internal_consistency` NOT named).
- **Test constraints:** `tests/test_config_flags.py` + `tests/test_subcommands.py` require `plan(check): 2 datasets` on clean check runs (docs' check example omits it — tests win, keep the line).

## Exact strings (check static phase) — keep EXACT

- **check-specific:** `no server section in config (no fallback launch)` (check-only — absent server legal for run commands now); `server: command not found: <path>`; `model '<n>': file not found: <path>`; `prompt template '<n>': file not found: <path>`; `port <N> already bound (a previous model server may still be running)`; `judge '<n>': environment variable '<var>' is unset or empty` (--probe-judges only); store: `note: no store at <p>`; `--create-store` bootstrap ⇒ `note: created empty store at <p>`; schema mismatch ⇒ exact `_MISMATCH`; cannot open ⇒ `cannot open store at {path}: {exc}`.

## Implementation

1. **`evalapp/cli.py`:** rewrite `_check` (per the check flow above); the judge env helper.
2. **`docs/commands.md` stale examples (fix in same commit):** (a) "Against the repo's config.json" block: `metrics (registered: 4):` → `metrics (registered: 5):` and `registered, not named there:   (none)` → `registered, not named there:   internal_consistency`; (b) hypothetical block: line `default_judges:                (absent ⇒ all configured)` is not rendered — replace with `default_judges:                openrouter-llama-3-70b` and `configured, not named there:   (none)`, and fix the following paragraph accordingly (absent ⇒ group 1 = all configured, group 2 = (none)).

## Tests to add

New files (one per check area, under `tests/`): `test_check_config.py`, `test_check_summarizers.py`, `test_check_judges.py`, `test_check_datasets.py`, `test_check_discovery.py`, `test_check_overrides.py`, `test_check_port_store.py` (monkeypatch `check_static.port_is_free` where needed), `test_check_repo_demo.py`.

- Check static end-to-end (all-error collection + exit 2; discovery byte-exact incl. `ljust(33)` + `(none)`; store absent note; `--create-store`; read-only schema mismatch; port-bound — bind a socket in-test on a random port; `--probe-judges` env).
- Repo-`config.json` demo (box 14): `run_cli(["check"], cwd=REPO_ROOT)` ⇒ exit 2 with the missing-file errors; assert **no** `evalstore.sqlite3` is created (read-only default — the repo config store is `evalstore.sqlite3`); guard the port-8080 case.
- Existing-test flips (serverless workspaces now exit 2 — the `plan(check)` line still prints on a clean config; store handling only runs after all static checks pass, so a serverless workspace now exits 2 before `note: no store`):
  - `tests/test_config_flags.py::test_default_config_name` + `test_explicit_config_flag`: keep `plan(check): 2 datasets`, flip `assert_exit(0)` → `assert_exit(2)`.
  - `tests/test_config_flags.py::test_store_override`: exit 0→2; give the config a `server` section to still reach store handling and exercise the override.
  - `tests/test_config_flags.py::test_config_file_never_written` (params check/generate/clear, all currently expect exit 0): parametrize the expected code (check=2, generate=0, clear=0).
  - `tests/test_subcommands.py::test_all_six_subcommands_run` (all six expect exit 0): special-case `check` (now exit 2, no-server error).
  - `tests/test_console_contract.py::test_message_order_warn_plan_note`: new order warn → 6-line discovery → (needs a server section) `note: no store at store.db`.
  - `tests/test_dataset_loader.py` stays green untouched (fail-fast semantics byte-identical).

## Definition of done

- `/usr/local/py-utils/bin/pytest tests/ -q` stays green (baseline **146 passed**); stdlib only. (NOT `/usr/local/python/current/bin/python3` — 3.14.8, no pytest installed.)
- Manual `check` against the repo `config.json` (exit 2 on the missing files is the expected first demo); iterate ≤3× on failures.
- Tick all boxes in this ticket and append a `## Comments` line (date + what was implemented).
- One commit including this ticket file: `git -c user.name="Codex" -c user.email="codex@local" commit -m "feat: ticket 02d — check static phase"`.

## Comments
2026-10-26 — implemented the check static phase end-to-end (collect-all with exit 2, byte-exact 6-line scorer discovery, static file checks, read-only store handling with --create-store opt-in); suite green at 309 passed, 1 skipped, with the serverless-test flips and the docs/commands.md example fixes in the same round.
