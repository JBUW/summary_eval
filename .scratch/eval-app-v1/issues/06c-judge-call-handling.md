# 06c: Scoring — judge call handling

**What to build:** The judge-call handler that ticket 06b's judges phase drives: one call per generation scores several qualities, the rubric is rendered with its placeholders, and the raw response passes through the parse seam (ticket 07). Nothing extractable ⇒ `warn:` + no row + continue; transport/HTTP failure or empty completion ⇒ fail-fast exit 1 naming the item and the judge.

**Blocked by:** 1 (Scaffold: executable, console contract, selection grammar), 05a (Endpoint client), 7 (Judge response parser + golden fixtures), 06b (Scoring: judges phase, resume, plan line)

**Status:** ready-for-agent

Series note (06a–06c): ticket 06 (Scoring pipeline) is split into these three parts; implement them in sequence, each self-contained and committing on its own.

- [ ] One call per generation scores several qualities (one nullable value per quality, never cross-averaged, no composite).
- [ ] The rubric is rendered with its placeholders and the raw response passes through the parse seam (ticket 07).
- [ ] Nothing extractable ⇒ `warn:` + no row + continue.
- [ ] Transport/HTTP failure or empty completion ⇒ fail-fast exit 1 naming the item and the judge.
- [ ] Unit tests run through the fake endpoint client (ticket 05a) and stop at the parse seam: rendering, transport handling, and commits are asserted with no real server and no network.

## Comments
- 2026-10-27 — split from ticket 06 (Scoring pipeline: scorer resolution, feasibility, metrics + judges phases) into 06a–06c.
