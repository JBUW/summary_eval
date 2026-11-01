# 14: The prepare module owns command preparation

**What to build:** One module, `evalapp/prepare.py`, holds the command preparation that needs the configuration: load, scope and validate; the server overrides and server cycles; the scorer flags. Today `_generate`, `_score`, `_sweep` and `_report` in `cli.py` repeat the load–scope–validate steps, the server-cycle setup is written out in four places (plus a fifth parse in `check_static`), and the scorer-flag setup in two. `check_static` and `check_live` import private names from `cli.py`, which imports them back. After this ticket `cli.py` only reads the command line, runs the command-line-only checks, and calls the commands.

**Blocked by:** none

**Status:** ready-for-agent

- [x] `cli.py` keeps only the command-line-only checks (`--server-*` requires `--generate`, the flags `sweep` forbids, `--csv`/`--json` exclusive, `--blind-sample >= 0`); everything that needs the configuration moves to `evalapp/prepare.py`.
- [x] `prepare.load_scope(args, console, scope=None)` loads the configuration and the datasets, computes the scope (default `resolve_selection(args.select, datasets)`; `sweep` passes all entries, `report` passes selection then blind sample), prints the empty-scope note, validates the configuration, and returns one object (config, datasets, scope, resolved). The note-before-validation order exists only here.
- [x] `prepare.server_overrides(args)` parses `--server-args`/`--server-env`; `prepare.server_spec(args, config)` builds the effective server spec; `prepare.server_cycles(spec, resolved, client, console)` builds the `ServerCycles`. `generate`, `score` and `sweep` call both; `check_live` keeps the spec for the context-adequacy warn. The caller creates the endpoint client; the `check_live` tests patch `prepare.ServerCycles`.
- [x] `prepare.scorer_flags(args)` builds the `--metrics`/`--judges` `Flag` pair; `_score` and `_report` use it.
- [x] `errors.CommandStop(code)`: raised after its message is printed (empty scope → 0, configuration errors → 2); `main` returns its code.
- [x] `check_static` and `check_live` use `prepare` for the server overrides and cycles and import nothing private from `cli.py`; `port_is_free` comes from `model_server`.
- [x] No GLOSSARY.md entry; no doc changes (the docs do not describe the module layout).
- [x] Tests: the `main(argv)` tests stay unchanged (console contract, same behavior); direct tests are added only for a moved rule that has no test today.

## Comments

- 2026-10-31 — implemented (83078c4): `evalapp/prepare.py` holds `load_scope`, `scorer_flags`, `server_overrides`/`server_spec`/`server_cycles`; `CommandStop` added to `errors.py`. Two small public additions beyond the plan: `prepare.tokens` (shared by `cli`) and `prepare.command_config` (used by `clear`). `check_live` still calls `server_overrides(args)` before the pair checks, to keep its JSON-validation behavior. Every moved rule already had a test, so no direct tests were added. Non-sockets suite: 565 passed, 1 known environmental failure (proxy 403); sockets suite: same 16 baseline environmental failures.
