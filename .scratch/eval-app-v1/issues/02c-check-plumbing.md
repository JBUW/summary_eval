# 02c: Check plumbing (read-only store, port pre-scan, server flags)

**What to build:** Part C of ticket 02 (its box 5, plus the independently testable halves of boxes 12–13): the plumbing `check` and the spawn commands need — `Store.open_readonly` (absent ⇒ None, never bootstraps; present ⇒ schema-verified, zero tables OK), a port pre-scan helper (socket-creation failure ⇒ port free; bind failure ⇒ bound error), the wholesale `--server-*` CLI overrides on generate/score/sweep/check (never written back; `default_metrics` / `default_judges` are NOT wholesale-replaceable), and the score gate (`--server-* flags require --generate`, before `--server-args` JSON parse and config load).

**Blocked by:** 1 (Scaffold: executable, console contract, selection grammar)

**Status:** ready-for-agent

- [ ] Wholesale CLI overrides apply for the store path and the five server launch values on every command that spawns or could spawn; overrides are never written back; `default_metrics` / `default_judges` are NOT wholesale-replaceable.

## Comments
