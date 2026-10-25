# 02b: Dataset load contract (R1 fail-fast set)

**What to build:** Part B of ticket 02 (its boxes 6–7): datasets load by extension and the R1 load-time contract — duplicate CSV column names, empty transcript, empty or duplicate entry ids, empty reference values — is checked in one pass, naming file and line. `datasets.py` gains an internal collect mode; the public `load_dataset` keeps fail-first-error semantics byte-identical. Box 8 (R2: a missing reference summary is a per-pair warning and drop, never an error) is runtime behavior of a later ticket and out of scope here — design decision 4: "R2 is runtime, later ticket — ticket 02 does NOTHING for it".

**Blocked by:** 1 (Scaffold: executable, console contract, selection grammar)

**Status:** ready-for-agent

- [ ] Datasets load by extension: CSV (RFC 4180, UTF-8), JSONL, JSON (one object per line); any other extension is a load-time contract failure.
- [ ] R1 fail-fast set (exit 2, naming file and line): missing/unreadable file, bad extension, declared purpose field absent, malformed rows (CSV column-count mismatch, duplicate header names; JSONL non-JSON line), zero entries, empty transcript value, entry-id field declared but any id empty. No transcript-length checks of any kind.

## Comments
