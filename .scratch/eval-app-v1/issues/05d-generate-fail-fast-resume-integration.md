# 05d: `generate` — fail-fast, resume, integration

**What to build:** The failure and recovery half of `generate`: on the first failure — HTTP error, empty completion, server death, or readiness timeout — the run aborts with exit 1, naming the failing item and the error, showing the last ~20 lines of the server log, and pointing at resume. A re-run after a partial failure skips the already-committed items with no model call and commits the remainder. Closes the series with the end-to-end integration tests for the whole `generate` flow.

**Blocked by:** 05c (`generate`: scope, order, skip, commit)

**Status:** ready-for-agent

Series note (05a–05d): ticket 05 (Endpoint client, model server lifecycle, `generate`) is split into these four parts; implement them in sequence, each self-contained and committing on its own.

- [ ] Fail-fast: first HTTP error, empty completion, server death, or readiness timeout ⇒ exit 1 with the failing item, the error, the last ~20 lines of the server log, and a resume hint (docs example: `note: re-run to resume; 1 item already committed`).
- [ ] Failure line format matches the docs exactly: `error: item <dataset>#<n> (summarizer '<s>'): <error>` followed by the log tail and the resume note (docs example: `error: item qmsum-dev#1 (summarizer 'std'): HTTP 500 from model server`).
- [ ] Resume: a re-run after a partial failure skips the already-committed items via the pre-scan (05c) with no model call on them and commits the remainder — no separate resume path, no re-rolling of committed generations.
- [ ] Integration tests (inheriting the P0b smoke criteria) through a real, trivially cheap server: the plan/done line formats, the exit classes (0 success, 1 failure, 2 contract error), and the resulting store rows; a partial failure mid-run resumes correctly with no re-calls on committed items.

## Comments
- 2026-10-27 — split from ticket 05 (Endpoint client, model server lifecycle, `generate`) into 05a–05d.
