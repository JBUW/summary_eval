# 02c: Check plumbing (read-only store, port pre-scan, server flags)

**What to build:** Part C of ticket 02 (its box 5, plus the independently testable halves of boxes 12–13): the plumbing `check` and the spawn commands need — `Store.open_readonly` (absent ⇒ None, never bootstraps; present ⇒ schema-verified, zero tables OK), a port pre-scan helper (socket-creation failure ⇒ port free; bind failure ⇒ bound error), the wholesale `--server-*` CLI overrides on generate/score/sweep/check (never written back; `default_metrics` / `default_judges` are NOT wholesale-replaceable), and the score gate (`--server-* flags require --generate`, before `--server-args` JSON parse and config load).

**Blocked by:** 1 (Scaffold: executable, console contract, selection grammar)

**Status:** ready-for-agent

- [x] Wholesale CLI overrides apply for the store path and the five server launch values on every command that spawns or could spawn; overrides are never written back; `default_metrics` / `default_judges` are NOT wholesale-replaceable.

## Settled design (implement as written; do not re-derive from the docs)

1. **Flags/gates:** `--server-command/--server-args/--server-env/--server-port/--server-startup-timeout` on generate/score/sweep/check (docs verified: sweep section lists them too); `--probe-judges`, `--create-store` on check. **Score gate: ANY `--server-*` ⇒ exit 2 `error: --server-* flags require --generate`, at TOP of score handler, BEFORE JSON parse and config load** (score has no `--generate` yet — that's the 05a–05d series). Sweep/generate/check just ACCEPT the flags in ticket 02 (no spawn behavior yet); on `check` `--server-command` changes the binary-existence check and `--server-port` changes the pre-scan target.
2. **check store handling:** default read-only: absent ⇒ `note: no store at <p>` (never created); present ⇒ open read-only `sqlite3.connect(f"file:{path}?mode=ro", uri=True)`, schema check runs (≥1 table); mismatch ⇒ `_MISMATCH` error exit 2; unopenable ⇒ `cannot open store at {path}: {exc}`; empty file (0 tables) present ⇒ OK, no bootstrap. `--create-store` ⇒ normal `Store(path)` shared path (bootstrap note `created empty store at <p>` if created); probe results discarded; never commits. **Implementation (mine):** add `Store.open_readonly(path)` classmethod (or module fn) → `None` if file absent, else Store with `readonly=True`: skip makedirs, connect via URI, zero-tables ⇒ NO bootstrap (treat as valid empty), ≥1 ⇒ `_verify_schema`. Reuse the static `_columns_of`/`_foreign_keys_of`.
3. **Port pre-scan:** `socket.socket(AF_INET, SOCK_STREAM)`; `except OSError` at creation (sandbox PermissionError) ⇒ treat FREE; `bind(("127.0.0.1", port))` fails ⇒ `port <N> already bound (a previous model server may still be running)`.
- Sweep handler in ticket 02: unchanged stub + accepts new flags (no server behavior).

## Current state (re-verified; rely on it)

- **`evalapp/store.py` (502L):** single shared open path; absent/zero-tables ⇒ bootstrap (dir+file+8 tables), `created=True`; ≥1 table ⇒ `_verify_schema` (exact table set + `_columns_of` + `_foreign_keys_of` — **all static, take a `db` handle, designed for reuse**), else `SpecError(_MISMATCH.format(path=path))` where `_MISMATCH = "store at {path} does not match the expected schema (move or delete the file to start a fresh store)"`; connect failure ⇒ `SpecError(f"cannot open store at {path}: {exc}")`. `table_counts()`, `clear()`, `close()`. **No read-only mode — must add.**
- **`evalapp/cli.py` (153L):** Parser: `--config`, `--store` (all), `--select` (generate/score/report), `--yes` (clear).
- Sandbox: `socket.socket()` ⇒ `PermissionError` (treat port as FREE)

## Exact strings (CLI gate, port pre-scan, store) — keep EXACT

- CLI: `--server-* flags require --generate` (SCORE only, gating BEFORE `--server-args` JSON parse); `invalid JSON for --server-args: <detail>` (same shape `--server-env`); `--server-args must be a JSON object`.
- Port pre-scan: `port <N> already bound (a previous model server may still be running)`.
- store: `note: no store at <p>`; `--create-store` bootstrap ⇒ `note: created empty store at <p>`; schema mismatch ⇒ exact `_MISMATCH`; cannot open ⇒ `cannot open store at {path}: {exc}`.

## Implementation

1. **`evalapp/store.py`:** read-only open support.
2. **`evalapp/cli.py`:** new flags in `build_parser` (per the flag list above); the score gate; the port pre-scan helper.

## Tests to add

- `Store.open_readonly`: absent file ⇒ `None` (never bootstraps); zero tables ⇒ valid empty; ≥1 table ⇒ schema-verified (mismatch ⇒ the exact `_MISMATCH` error); unopenable ⇒ `cannot open store at {path}: {exc}`.
- Port pre-scan: bind a socket in-test on a random port ⇒ the bound error; a free port passes; sandbox socket-creation failure ⇒ treated free.
- Score `--server-*` gate (before config load: missing config + `--server-port` ⇒ the gate error, not the config error).

## Definition of done

- `/usr/local/py-utils/bin/pytest tests/ -q` stays green (baseline **146 passed**); stdlib only. (NOT `/usr/local/python/current/bin/python3` — 3.14.8, no pytest installed.)
- Tick all boxes in this ticket and append a `## Comments` line (date + what was implemented).
- One commit including this ticket file: `git -c user.name="Codex" -c user.email="codex@local" commit -m "feat: ticket 02c — check plumbing"`.

## Comments
2026-10-26 — Added Store.open_readonly (absent file yields None and never bootstraps; a zero-table file is a valid empty store; one or more tables get the same exact schema check); check store handling: default read-only open (absent => note, mismatch => exact _MISMATCH) and --create-store bootstrap note; --server-* flags accepted on generate/score/sweep/check plus --probe-judges/--create-store on check (never written back; default_metrics/default_judges untouched); score gate before JSON parse and config load (--server-* flags require --generate); check-only --server-args/--server-env JSON object validation; port_is_free pre-scan helper (socket-creation failure => free; bind failure => bound error); added tests/test_check_plumbing.py (23 tests) and extended tests/test_store.py (5 tests).
