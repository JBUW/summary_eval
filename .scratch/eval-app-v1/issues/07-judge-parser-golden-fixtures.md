# 07: Judge response parser + golden fixtures

**What to build:** The pure function at the program's single trust boundary: raw judge text goes in, structured quality values come out. The parse policy is deliberately relaxed because this input is genuinely untrusted — warning plus recorded exclusion, or partial acceptance governed by the code constant `ACCEPT_PARTIAL_RESULTS` (default off). A golden fixture set — recorded raw judge responses paired with their expected structured outcome — pins the parser's behavior at this seam.

**Blocked by:** 1 (Scaffold: executable, console contract, selection grammar)

**Status:** ready-for-agent

- [ ] A pure function maps raw judge text to structured quality values: no I/O, no configuration, no store, no network.
- [ ] Out-of-scale values are marked out-of-range and never clamped.
- [ ] A misspelled quality label is treated as missing, not as a value.
- [ ] Parse policy: warning + recorded exclusion, or partial acceptance governed by the code constant `ACCEPT_PARTIAL_RESULTS` (default off).
- [ ] Golden fixtures (recorded raw response + expected outcome) cover at least: clean, directly parseable values; prose-wrapped and markdown-fenced values; duplicate quality values (identical duplicates accepted, conflicting duplicates excluded per the parse policy); integer versus decimal value forms; out-of-scale ⇒ out-of-range; misspelled label ⇒ missing; the partial-acceptance path per the constant (off ⇒ warning + exclusion).
- [ ] Naming discipline: these are golden *fixtures* (input at a seam) and stay distinct from the glossary's *golden set* (the curated, documented subset of a dataset) in code, comments, and documentation.

## Comments
