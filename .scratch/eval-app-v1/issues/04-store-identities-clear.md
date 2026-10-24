# 04: Store, identities, and `clear`

**What to build:** The store becomes the single source of truth AND the index: one SQLite file with exactly 8 tables, every row addressed by the identity of its inputs, so re-runs dedupe automatically and committed work is terminal. A user gets a store that bootstraps itself on first use, fails loudly (exit 2, with a hint) on a schema mismatch — never migration — and `clear`, the human's clean slate after e.g. a hardware change: dry-run by default, destructive only with `--yes`, all-or-nothing.

**Blocked by:** 1 (Scaffold: executable, console contract, selection grammar)

**Status:** ready-for-agent

- [ ] One shared open path: absent file or zero tables ⇒ create directory, file, and all 8 tables (noted); an existing file with ≥ 1 table ⇒ exact schema check; mismatch ⇒ exit 2 with a hint to move or delete the file, never auto-migration.
- [ ] Exactly 8 tables: transcripts, reference_summaries, models, prompt_templates, judges, generations, judge_evaluations, metric_evaluations.
- [ ] Identities are sha256 over canonical JSON of the entity's inputs: model = hash of the model file bytes (path irrelevant; same bytes = same model); generation = hash of (transcript, model, model_args, prompt template, gen_params); judge = hash of (model name, gen_params, system content, user template, requires_reference) — endpoint URL, display name, and credential variable are NOT part of the identity; evaluation = hash of (scorer identity, generation, reference-or-null).
- [ ] Transcripts and reference summaries are content-addressed: identical transcript text across datasets is one store row.
- [ ] `updated_at` is stamped only when an existing identity is upserted with differing non-key values.
- [ ] Courtesy name columns are last-seen-wins and are never resolved against the configuration.
- [ ] Metric evaluation rows carry a single NOT NULL scalar; judge evaluation rows carry one nullable column per quality; no composite score and no cross-quality averaging exist.
- [ ] `clear` wipes all 8 tables in a single transaction, all-or-nothing, no subsetting; the configuration is loaded only to resolve the default store path.
- [ ] `clear` is dry-run by default (a successful invocation): prints per-table row counts and a note, exit 0; `--yes` is the confirmation — no interactive prompt; the wipe prints a `done(clear):` line that scripts key on.
- [ ] `clear` with no store ⇒ `note:`, exit 0; missing configuration ⇒ exit 2.
- [ ] No manifests, no run directories: the store is the index and the only thing `clear` wipes.

## Comments
