# 10: `report` command

**What to build:** The descriptive roll-up: per (candidate, scorer) n/mean/min/max, judges per candidate × quality, every figure indicating its source — strictly read-only, the only command that reads evaluations, producing nothing but a display.

**Blocked by:** 8 (`score` command)

**Status:** ready-for-agent

- [x] Strictly read-only: no commits, no upserts (not even courtesy-column refreshes), no server, no model or judge calls.
- [x] Selection and scorer resolution = `score` without `--generate` (including `*`).
- [x] Any `--server-*` flag ⇒ exit 2 (report has no generate stage).
- [x] Default output: a human table, one row per (candidate, scorer) with `n, mean, min, max`; judges get one row per candidate × quality; `n=0` rows are shown with dashes, not omitted; every figure indicates its source (n, and `(judge)` where applicable).
- [x] `--json` — same data, stable key order.
- [x] `--by dataset` — the only grouping axis (default: aggregated across in-scope datasets).
- [x] `--blind-sample N` — the last N entries of each in-scope dataset in file order, applied after `--select`; a reporting/holdout convention only, nothing enforced.
- [x] `--csv PATH` — flattened rows, header `candidate[,dataset],scorer,n,mean,min,max`; the table is suppressed (scope lines still on stdout); the parent directory must exist (else exit 2); the file is created only after pre-effect validation; mutually exclusive with `--json` (exit 2); minimal CSV dialect; `note: wrote N rows to <path>`.
- [x] Zero rows ⇒ `note: no scored results in scope; run 'score' (or 'score --generate') first`, exit 0.
- [x] Extend the end-to-end smoke test: a tiny dataset with a fake or trivially cheap endpoint through `generate` → `score` → `report`, asserting the plan/done lines, exit classes, and the resulting store rows.

## Comments
- 2026-10-29 — implemented: report command (strictly read-only: no commits, no upserts, no server, no model/judge calls; selection and scorer resolution = score without --generate; --server-* ⇒ exit 2; default table with n, mean, min, max per (candidate, scorer), judges one row per candidate × quality, n=0 rows shown with dashes, every figure source-indicated; --json stable key order; --by dataset the only grouping axis; --blind-sample N applied after --select; --csv PATH with pre-effect validation, minimal dialect, mutex with --json; zero rows ⇒ note + exit 0) + 33 ticket tests (13 core unit, 7 store unit, 8 parser, 5 end-to-end integration through the fixture server); bin/check green apart from socket-bound tests the sandbox cannot run. Note: the docs/commands.md --csv example (--metrics '[]' --no-judges ⇒ "note: wrote 4 rows") is impossible — zero scorers ⇒ zero-rows note; left as written, accepted SHALLOWLY per the ticket.
