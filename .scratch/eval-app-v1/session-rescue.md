# Ticket 02 — session rescue / progress log (2026-10-25)

Purpose: persist the in-log progress from the failed ticket-02 implementation
sessions so a fresh session can continue with minimal rework. The settled
design itself is authoritative and lives in
`.scratch/eval-app-v1/ticket-02-design.md` — this file adds only what exists
solely in session logs (timeline, environment facts, conclusions, test
planning). Do not re-derive the design; read that file first.

## Session timeline (log dir `/workspaces/devcontainer/.codex/sessions/2026/10/25/`)

| File (rollout-2026-10-25T…jsonl) | Lines | What it is |
|---|---|---|
| `10-17-43-…` | 15 | Early routing chatter, no ticket-02 content. |
| `10-48-29-…` | 13 | Short `$ask-matt` routing session; no code. |
| `10-52-01-01a172b0-…` | 4352 | **Main implement-spec session** (~10:52→18:54 UTC, ~28 compactions). All ticket-02 investigation (every source file, test, harness, doc read) + 12 intermediate handoffs, dumped to `/tmp/handoffs/01-1103-checkpoint.txt` … `12-1633-handoff.txt`. **Zero code written.** Ends with the final settled design (final handoff at line 4196 of that log), extracted to `ticket-02-design.md`. |
| `10-53-02-…` | 59 | Short `$ask-matt` routing session; no code. |
| `18-54-27-…` | 682 | Diagnostic session after the main session died: confirmed nothing was lost on disk (no stray worktrees with ticket-02 code), committed the rescued design doc as `839278c`. |
| `21-03-54-…` | 543 | Prior rescue attempt: extracted the 12 handoffs to `/tmp/handoffs/`, then died on `NameError: re`. This file is the completed version of that rescue. |

Frontier identified by the routing sessions: tickets 02 and 07 (07 since done).

## Repo-vs-in-log split (what is committed vs. log-only)

Committed (branch `integrate/eval-app-v1`, HEAD `839278c`, clean tree, no
stashes, `git fsck --unreachable` empty):
- 01 `0393337`, 03 `1aa785e`, 04 `d9e9b72`, 07 `3cb4077`
- `839278c` = rescued settled design doc

In-log only (not in the repo):
- The 12 intermediate handoffs (extracted copies were in `/tmp/handoffs/`,
  removed 2026-10-26 during /tmp cleanup; originals remain inside the
  4352-line log above).
- Environment corrections (see below).
- The resolved contradiction between stale handoffs 07/08 and the final design.
- Shadow-worktree conclusions: `/tmp/eval-app-shadow` (real git repo, master
  `e86df35 baseline: pre-ticket-01`, clean, no ticket-02 code) and
  `/tmp/shadow-test` (real git repo, master with zero commits) are both dead
  ends — **no ticket-02 code exists anywhere; implement from scratch.**

## Ticket graph / remaining after 02

- 05 (needs 02), 06 (needs 07 ✓), 08 (needs 05+06), 09+10 (need 08),
  11 (needs 02+05+07).
- Suggested order: `07✓ & 02 → 05 & 06 → 08 → {09, 10, 11}`.

## Environment facts (verified, do not re-probe)

- pytest: `/usr/local/py-utils/bin/pytest` (venv
  `/usr/local/py-utils/venvs/pytest/bin/python`). NOT
  `/usr/local/python/current/bin/python3` (3.14.8, no pytest installed).
- Baseline: `146 passed in 1.40s` — must stay green.
- Sandbox: `socket.socket()` ⇒ `PermissionError` ⇒ treat any port as FREE;
  bind test on `127.0.0.1` for the "already bound" error path.
- Network restricted; writable paths = project + `/tmp` only.
- `/home/vscode/llama.cpp/build-rocm/bin/llama-server` absent from this
  machine ⇒ repo `config.json` check must fail on the missing command (exit 2).

## Test plan for ticket 02 (from handoff 12, not yet written)

New files: `test_check_config.py`, `test_check_summarizers.py`,
`test_check_judges.py`, `test_check_datasets.py`, `test_check_discovery.py`,
`test_check_overrides.py`, `test_check_port_store.py` (monkeypatch
`check_static.port_is_free` where needed), `test_check_repo_demo.py`
(`cwd=REPO_ROOT` ⇒ exit 2; assert **no** `evalstore.sqlite3` created).

Existing tests that must change (order change: `plan(check)` line still prints
on clean config; store handling only after all static checks pass, so a
serverless workspace now exits 2 before `note: no store`):
- `tests/test_config_flags.py::test_default_config_name` + `test_explicit_config_flag`:
  keep `plan(check): 2 datasets`, flip `assert_exit(0)` → `assert_exit(2)`.
- `tests/test_config_flags.py::test_store_override`: exit 0→2; give the config
  a `server` section to still reach store handling and exercise the override.
- `tests/test_config_flags.py::test_config_file_never_written` (params
  check/generate/clear, all currently expect exit 0): parametrize the expected
  code (check=2, generate=0, clear=0).
- `tests/test_subcommands.py::test_all_six_subcommands_run` (all six expect
  exit 0): special-case `check` (now exit 2, no-server error).
- `tests/test_console_contract.py::test_message_order_warn_plan_note`: new
  order warn → 6-line discovery → (needs a server section)
  `note: no store at store.db`.
- `tests/test_dataset_loader.py` stays green untouched (fail-fast semantics
  byte-identical).

## Resolved contradiction (design doc wins)

Stale handoffs 07 (15:00) and 08 (15:09) claimed: (a) "absent server must not
fail / check exits 0 on the standard workspace" and (b) "remove the
`plan(check)` line". Both are **wrong**. Final 18:34 design: an absent server
**is** a check error — `no server section in config (no fallback launch)` —
firing in the static stage, **after** the `plan(check): N datasets` line; the
`plan(check)` line is **kept** (146 existing tests + docs depend on it).

## Lessons

- Single-context implementation; no subagent orchestration for this ticket.
- Update tests in the same round as behavior changes.
- One commit per ticket; explicit `-c` identity; tick all boxes + append a
  `## Comments` line when closing.
