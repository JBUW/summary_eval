# 12: The dataset module owns the reference summary

**What to build:** The dataset loader keeps each entry's reference summary, as it already keeps the transcript. `generate` and the scoring phases read the reference summary from the loaded entry. `scoring._read_reference` (a second parser of the same file, re-reading the whole file once per entry and per phase, imported privately by `generate`) is deleted.

**Blocked by:** none

**Status:** ready-for-agent

- [ ] Every loaded entry carries `reference`: the text, or `None` iff the dataset declares no `reference_field`.
- [ ] `Dataset.has_references` answers "does this dataset carry reference summaries"; callers stop reading `decl["reference_field"]`.
- [ ] No empty-means-no-reference logic outside the loader: R1 already rejects an empty reference at load (exit 2).
- [ ] References are read once at load and stay in memory for the command, as transcripts do (load-time snapshot).
- [ ] `scoring._read_reference` and its private import in `generate` are deleted.
- [ ] Tests: the monkeypatch read-counting test and `_reference_dataset` are replaced by in-memory `Dataset` entries; one loader test per format (CSV, JSONL) asserts `reference` is carried.

## Comments
