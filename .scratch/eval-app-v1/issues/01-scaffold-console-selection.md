# 01: Scaffold: executable, console contract, selection grammar

**What to build:** A single Python executable exposing all six subcommands (`check`, `generate`, `score`, `sweep`, `report`, `clear`) behind a stable machine interface. Every subcommand accepts `--config` (default: the example configuration name) and `--store`. The console is the contract: exit classes 0 (success, including no-ops and dry runs), 1 (runtime fail-fast), 2 (pre-effect specification error — nothing was executed), and the four stdout prefixes `error:`, `warn:`, `plan:`, `note:` in fixed order within a run (warn → plan → note). A no-op is reported with `note:` and exit 0, never `error:`. The run commands share one repeatable `--select <dataset> <spec>...` flag implementing the selection grammar: `#` for 0-based positions and inclusive ranges (strict digits, comma-separated, any order), `@` for literal entry ids (`@@x` names an entry literally called `@x`), `*` for all entries (a bare `--select *` = all datasets × all entries), unioned across occurrences with duplicates dropped; a `--select` occurrence with zero specs is an error, never a silent full run; no flag ⇒ full scope. A reusable test harness that invokes the executable in-process and captures stdout and exit codes is established here and used by this ticket's grammar tests.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [x] One executable exposes all six subcommands; unknown subcommand or flag ⇒ exit 2 with an `error:` line.
- [x] `--config` defaults to `config.json`; `--store` overrides the configuration's store value; overrides are never written back to the configuration file.
- [x] Exit classes are stable and classified correctly: 0 = success including no-ops and dry runs; 1 = runtime failure, fail-fast; 2 = pre-effect specification error with nothing executed (no model or judge calls, no store writes).
- [x] No-ops are printed with `note:` and exit 0; `error:` is never used for "nothing to do".
- [x] Message order within a run: `warn:` lines first, then `plan:` lines, then `note:` lines.
- [x] `#` specs: single 0-based positions and inclusive ranges, comma-separated in any order (a range may lead); strict digits only; out-of-range, inverted, or malformed ⇒ exit 2; valid in named AND unnamed datasets.
- [x] `@` specs: literal entry ids; `@@x` names an entry literally called `@x`; resolves only in named datasets ⇒ unnamed is exit 2.
- [x] `*`: all entries of the dataset; as the entire `--select` argument it means all datasets × all entries.
- [x] Occurrences are unioned, duplicates dropped; a `--select` occurrence with zero specs ⇒ exit 2; no `--select` ⇒ full scope.
- [x] Tests assert only external behavior (stdout lines, exit codes) and survive behavior-preserving refactors; the test harness is reusable by later tickets.

## Comments
- 2026-10-24 — implemented: bin/evalapp scaffold (six subcommands, --config/--store), console contract (exit classes 0/1/2, stdout prefixes error:/warn:/plan:/note: in fixed order, no-ops as note: with exit 0), selection grammar (#/@/* with union and dedup), in-process test harness; 8 test files, 53 tests green via /usr/local/py-utils/bin/pytest.
