# 02b: Dataset load contract (R1 fail-fast set)

**What to build:** Part B of ticket 02 (its boxes 6–7): datasets load by extension and the R1 load-time contract — duplicate CSV column names, empty transcript, empty or duplicate entry ids, empty reference values — is checked in one pass, naming file and line. `datasets.py` gains an internal collect mode; the public `load_dataset` keeps fail-first-error semantics byte-identical. Box 8 (R2: a missing reference summary is a per-pair warning and drop, never an error) is runtime behavior of a later ticket and out of scope here — design decision 4: "R2 is runtime, later ticket — ticket 02 does NOTHING for it".

**Blocked by:** 1 (Scaffold: executable, console contract, selection grammar)

**Status:** ready-for-agent

- [x] Datasets load by extension: CSV (RFC 4180, UTF-8), JSONL, JSON (one object per line); any other extension is a load-time contract failure.
- [x] R1 fail-fast set (exit 2, naming file and line): missing/unreadable file, bad extension, declared purpose field absent, malformed rows (CSV column-count mismatch, duplicate header names; JSONL non-JSON line), zero entries, empty transcript value, entry-id field declared but any id empty. No transcript-length checks of any kind.

## Settled design (implement as written; do not re-derive from the docs)

1. **R1/R2 boundary:** R1 = load-time (incl. empty transcript, empty/repeated entry ids per-dataset, **empty reference value**). R2 (runtime, later ticket) — ticket 02 does NOTHING for it; reference key absent from a JSONL row is already the existing `field '<k>' not found` error.
2. **datasets.py collect mode:** internal `_load(name, path, text, decl) -> (entries, id_map, errors)`. Error order: CSV = [dup-header (once per name) → field-absence → per-row malformed (row order) → per-row value checks (row order: empty transcript, empty id, dup id, empty reference)] + `no entries in <path>` appended if entries==0. JSONL = [per-row malformed + per-row field-absence (row order) → per-row value checks (row order)] + `no entries` if 0. Value checks run only for rows/objects that parsed; a declared field absent ⇒ skip checks for that field only. Malformed rows are skipped for value checks but scanning continues. Public `load_dataset` = collect, then raise `errors[0]` if any — fail-fast first-error semantics stay byte-identical (146 tests depend on it).

## Current state (re-verified; rely on it)

- **`evalapp/datasets.py` (113L):** `Dataset(name, decl, entries, id_map)`; `load_dataset(name, decl)` fail-fast; entries `{"index","transcript"[,"entry_id"]}` — reference_field never read at load; CSV lines numbered from 2, JSONL from 1; all errors prefixed `dataset '<n>': `.

## Exact strings (dataset load) — keep EXACT

- Datasets (existing UNCHANGED, all `dataset '<n>': ` prefix): `datasets must be an object mapping names to entries`, `entry must be an object`, `field '<f>' must be a string` (path, transcript_field, reference_field, entry_id_field order), `file not found: <path>`, `cannot read <path>: <detail>`, `unsupported file extension '<e>' (supported: .csv, .jsonl, .json)`, `no entries in <path>`, `malformed line N in <path>: expected X columns, got Y` / `: empty row` / `: empty line` / `: not a JSON object: <exc>` / `: expected a JSON object`, `field '<k>' not found in <path> (line N)` (JSONL) / `(columns: ...)` (CSV file-level).
- **NEW R1:** `dataset '<n>': duplicate column name 'x' in <path>` (CSV header, once per name, BEFORE field-absence); `dataset '<n>': empty transcript in <path> (line N)` (`== ""` or None, NO strip); `... empty entry id in <path> (line N)`; `... duplicate entry id 'x' in <path> (line N)` (N = 2nd occurrence); `... empty reference in <path> (line N)`.

## Implementation

1. **`evalapp/datasets.py`:** collect mode + 5 new R1 checks.

## Tests to add

- R1 dataset checks in BOTH fail-fast and collect modes.

## Definition of done

- `/usr/local/py-utils/bin/pytest tests/ -q` stays green (baseline **146 passed**); stdlib only. (NOT `/usr/local/python/current/bin/python3` — 3.14.8, no pytest installed.)
- Tick all boxes in this ticket and append a `## Comments` line (date + what was implemented).
- One commit including this ticket file: `git -c user.name="Codex" -c user.email="codex@local" commit -m "feat: ticket 02b — dataset load contract"`.

## Comments
2026-10-26 — Added collect mode (_load -> entries, id_map, errors) with R1 checks (duplicate CSV column names, empty transcript, empty/duplicate entry ids, empty reference, value checks only for parsed rows); load_dataset raises errors[0], fail-fast strings byte-identical; added tests/test_dataset_contract.py (21 tests).
