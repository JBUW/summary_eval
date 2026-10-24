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
