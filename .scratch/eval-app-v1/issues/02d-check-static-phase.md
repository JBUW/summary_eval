# 02d: check static phase (collect-all, discovery, file checks)

**What to build:** Part D of ticket 02 (its boxes 9, 10, 11, 14): the `check` static phase end-to-end — `load_config` collect mode → `validate_config` → the six-line scorer discovery (byte-exact, printed whenever the config parses) → ALL failures printed in one pass, exit 2, live phase skipped → otherwise `plan(check): N datasets` → static file checks (datasets, `server.command`, model files, prompt templates, port pre-scan, judge env vars under `--probe-judges`) → store handling (read-only by default; `--create-store` opt-in) → exit 0. Includes the existing-test flips (serverless workspaces now exit 2) and the stale `docs/commands.md` example fixes, in the same round.

**Blocked by:** 02a (Configuration strict contract), 02b (Dataset load contract), 02c (Check plumbing)

**Status:** ready-for-agent

- [ ] The `check` static phase collects and prints ALL failures in one pass, then exits 2; the live phase is skipped (deliberate contrast to the fail-fast run commands).
- [ ] `check` errors carry the valid sets (e.g. an unknown metric lists the registered metrics; an unknown judge lists the configured judges).
- [ ] Scorer discovery is printed regardless of store presence, in two disjoint groups per family (named in the relevant default vs. registered/configured but not named there); every registered metric and configured judge appears in exactly one group.
- [ ] Against the normative example configuration at the repo root (whose data, prompt, and model paths are illustrative and absent), `check` reports those missing-file contract failures and exits 2 — the expected first end-to-end demo until the files exist.

## Comments
