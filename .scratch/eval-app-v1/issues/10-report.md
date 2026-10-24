# 10: `report` command

**What to build:** The descriptive roll-up: per (candidate, scorer) n/mean/min/max, judges per candidate × quality, every figure indicating its source — strictly read-only, the only command that reads evaluations, producing nothing but a display.

**Blocked by:** 8 (`score` command)

**Status:** ready-for-agent

- [ ] Strictly read-only: no commits, no upserts (not even courtesy-column refreshes), no server, no model or judge calls.
- [ ] Selection and scorer resolution = `score` without `--generate` (including `*`).
- [ ] Any `--server-*` flag ⇒ exit 2 (report has no generate stage).
- [ ] Default output: a human table, one row per (candidate, scorer) with `n, mean, min, max`; judges get one row per candidate × quality; `n=0` rows are shown with dashes, not omitted; every figure indicates its source (n, and `(judge)` where applicable).
- [ ] `--json` — same data, stable key order.
- [ ] `--by dataset` — the only grouping axis (default: aggregated across in-scope datasets).
- [ ] `--blind-sample N` — the last N entries of each in-scope dataset in file order, applied after `--select`; a reporting/holdout convention only, nothing enforced.
- [ ] `--csv PATH` — flattened rows, header `candidate[,dataset],scorer,n,mean,min,max`; the table is suppressed (scope lines still on stdout); the parent directory must exist (else exit 2); the file is created only after pre-effect validation; mutually exclusive with `--json` (exit 2); minimal CSV dialect; `note: wrote N rows to <path>`.
- [ ] Zero rows ⇒ `note: no scored results in scope; run 'score' (or 'score --generate') first`, exit 0.
- [ ] Extend the end-to-end smoke test: a tiny dataset with a fake or trivially cheap endpoint through `generate` → `score` → `report`, asserting the plan/done lines, exit classes, and the resulting store rows.

## Comments
