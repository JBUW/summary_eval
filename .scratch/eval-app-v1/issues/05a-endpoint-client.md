# 05a: Endpoint client (injected transport + fake)

**What to build:** The injected endpoint client — the program's single door to the network, serving both the model server and judge endpoints — becomes the seam unit tests inject a fake client into. Tests assert on the requests it received and on the store/stdout results that followed, with no real server and no network. The client carries the shared error model the later fail-fast paths key on: HTTP error, empty completion, and timeout are distinct, nameable failures — not one generic exception.

**Blocked by:** 1 (Scaffold: executable, console contract, selection grammar), 2 (Configuration + datasets; `check` static phase)

**Status:** ready-for-agent

Series note (05a–05d): ticket 05 (Endpoint client, model server lifecycle, `generate`) is split into these four parts; implement them in sequence, each self-contained and committing on its own.

- [x] One client is the single transport for all HTTP to model server and judge endpoints; no other module issues network calls.
- [x] The client is injected at the seam: unit tests (this and later tickets) pass a fake client and assert on the requests it received and on the store/stdout results that followed.
- [x] Completion requests carry the per-request `gen_params` — they ride with each completion request, never as launch arguments.
- [x] The model-server surface exposes `GET /props` (readiness and build info) and `POST /tokenize` (the later context-adequacy probe, ticket 11) alongside completions.
- [x] Judge calls address a bare endpoint profile — URL, `model_name` pin, optional credential by environment-variable name — with no lifecycle, no spawn, no monitoring.
- [x] The error model distinguishes the three failure classes the fail-fast paths key on: HTTP error (status + body), empty completion, timeout.

## Comments
- 2026-10-27 — split from ticket 05 (Endpoint client, model server lifecycle, `generate`) into 05a–05d.
- 2026-10-27 — implemented: single endpoint client with injected transport seam (fake in tests), 3-class error model (HttpError/EmptyCompletionError/RequestTimeout), gen_params ride-along, /props + /tokenize surface, bare judge endpoint profile; 336 tests green via /usr/local/py-utils/bin/pytest
