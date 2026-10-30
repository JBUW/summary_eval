## Agent skills

### Issue tracker

Issues live as markdown files under `.scratch/<feature-slug>/` in this repo. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-label vocabulary: needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`. `docs/store-schema.md` is the authoritative current shape of the results store; any decision that changes the store updates it in the same round as the log entry.
`docs/config.md` is the authoritative current specification of the configuration file; any decision that changes the config updates it in the same round as the log entry.
`docs/commands.md` is the how-to and agent reference for all subcommands; any decision that changes CLI behavior updates it in the same round as the log entry.
`docs/design.md` is the Phase 0 design document — how the settled decisions fit into an implementable system; any decision that changes the design updates it in the same round as the log entry.

## Ticket progress

Per-effort decisions live in the effort map `.scratch/<feature>/map.md` (Notes / Decisions-so-far / Fog; per `docs/agents/issue-tracker.md`).

- Write a ticket's settled design decisions into the map's Decisions-so-far before writing its code; a handoff points at the map instead of restating the decisions.
- A ticket is done when it is committed. Resume a ticket with no new commit by writing the smallest code slice first, then re-reading only what a failing test names.
- `bin/check` (the pytest suite) green + commit = ticket done.

### Loop self-awareness

Progress must survive compaction and a stall must be visible, so a restart never loses work or repeats a dead end:

- Commit each green slice the moment it is green; a slice that is not committed is not done.
- Re-read the file's exact bytes before re-applying a failed patch.
- The same test failing the same way twice is a loop: stop iterating, re-read the ticket and the map, check the assumption the code was built on, and re-plan the smallest slice.

## Environment

Container quirks (broken `ps`, sandboxed sockets, no GitHub credentials) and when to run the full `--with-sockets` suite: `docs/agents/environment.md`.

## Git

### Commit identity

Agent commits must always pass the identity explicitly: `git -c user.name="Codex" -c user.email="codex@local" ...`. The agent must not use the identity set in the repository config (`.git/config`).

### Pre-commit hook

Commits are gated by `hooks/pre-commit`, which runs `bin/check`; a red suite aborts the commit. The default gate excludes `sockets`-marked tests (real local server sockets); run the full suite with `bin/check --with-sockets`. A fresh clone must activate it first: `git config core.hooksPath hooks`. Bypass only when deliberately committing red: `git commit --no-verify`.
