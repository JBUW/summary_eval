# 12: The dataset module owns the reference summary

**What to build:** The dataset loader keeps each entry's reference summary, as it already keeps the transcript. `generate` and the scoring phases read the reference summary from the loaded entry. `scoring._read_reference` (a second parser of the same file, re-reading the whole file once per entry and per phase, imported privately by `generate`) is deleted.

**Blocked by:** none

**Status:** ready-for-agent

- [x] Every loaded entry carries `reference`: the text, or `None` iff the dataset declares no `reference_field`.
- [x] `Dataset.has_references` answers "does this dataset carry reference summaries"; callers stop reading `decl["reference_field"]`.
- [x] No empty-means-no-reference logic outside the loader: R1 already rejects an empty reference at load (exit 2).
- [x] References are read once at load and stay in memory for the command, as transcripts do (load-time snapshot).
- [x] `scoring._read_reference` and its private import in `generate` are deleted.
- [x] The per-entry "has no reference … (pair skipped)" warn-and-drop path in both scoring phases is deleted (unreachable under R1); `done(score)` keeps its `dropped` slot unchanged.
- [x] `docs/design.md` R2 is reworded to the per-(scorer, dataset) form of `docs/config.md`.
- [x] Tests: the three per-entry-drop tests are deleted; the monkeypatch read-counting test and `_reference_dataset` are replaced by in-memory `Dataset` entries; one loader test per format (CSV, JSONL) asserts `reference` is carried.

## Comments

- 2026-10-31 — implemented (693d135): entries carry `reference`; `Dataset.has_references`; `scoring._read_reference`, its import in `generate`, and the per-entry warn-and-drop path deleted; `dropped` slot kept (always 0, open in map Fog); docs/design.md R2 reworded; three dead-path tests deleted, reference tests now use in-memory entries; loader tests pin `reference` for CSV and JSONL (562 non-sockets tests green; the one failure, test_endpoint_client default-client, is a pre-existing proxy 403)
