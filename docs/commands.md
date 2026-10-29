# Commands

Authoritative, current reference for the application's command-line interface. This file is
the "what it is now" reference for every subcommand; `.scratch/grill-with-docs/DECISIONS.md`
is the decision log (the "why and when"), and `docs/store-schema.md` is the authoritative
shape of the results store that these commands write.

House rule: this file shows usage the way the application itself prints it (usage lines,
flag sections, example console output), so it doubles as the agent reference for building
and explaining the CLI. The executable name is fixed at implementation time; usage lines
below write it as `<app>`.

## Conventions

- **One executable, six subcommands:** `check | generate | score | sweep | report | clear`.
  There is no `serve` — the model server's lifecycle is internal to the run commands.
  Search/meta-strategy commands (e.g. `tune`) are parked: the design allows them to be
  added later as thin orchestration over `generate`/`score`, but they do not exist.
- **Shared flags on every subcommand:** `--config PATH` (omittable; default `config.json`)
  and `--store PATH` (overrides the config's `store` value).
- **Wholesale CLI overrides** cover non-definition config values only: `store`,
  `server.command`, `server.args`, `server.env`, `server.port`, `server.startup_timeout_s`
  (as `--store`, `--server-command`, `--server-args`, `--server-env`, `--server-port`,
  `--server-startup-timeout`). Overrides are never written back to the config file.
  `default_metrics` / `default_judges` are NOT part of this mechanism — they interact with
  the `--metrics` / `--judges` flags as documented per command.
- **Exit codes:**
  - `0` — success, including no-ops and dry runs. A no-op is reported with `note:`,
    never `error:`.
  - `1` — runtime failure (model call, metric algorithm, judge transport, server
    spawn/readiness). Fail-fast: the run aborts at the first failure. Server failures
    print the failing item, the error, and the last ~20 lines of the server log.
  - `2` — pre-effect specification error: nothing was executed (no model/judge calls,
    no store writes). Covers unknown names, malformed flags/specs/JSON, out-of-range
    indexes, config-shape failures, schema mismatch, busy port, and flag misuse.
- **Output vocabulary** (stdout prefixes are the machine interface; scripts may key on
  them):
  - `error:` — a specification or runtime failure (exit 1 or 2).
  - `warn:` — something was dropped or skipped; the run proceeds (exit 0).
  - `plan:` — what the command will do / did do, before or after the work.
  - `note:` — informational, including absences; a level below `warn:`.
  - Message order within a run: `warn:` lines first, then `plan:` lines, then `note:` lines.
- **Terminology (strict):**
  - `metric` — a code-registered algorithmic scorer; produces one scalar value.
  - `judge` — a configuration-defined LLM scorer; produces one value per quality.
  - `quality` — one axis a judge scores (e.g. `factual_correctness`).
  - `scorer` — umbrella for metric or judge. Never used in user-facing counts: the
    console says `4 metrics, 1 judge`, not `5 scorers`.
  - `store` — the results database. Never called "database" in user-facing text.
  - `endpoint` — a judge's URL. Never "server" in user-facing text; the spawned local
    process is called the "model server".
  - `summary` — a generated text artifact only. Performance roll-ups are produced by
    `report` and are not called summaries.
  - `Summarizer` — a candidate: the four components model + model_args + prompt
    template + gen_params.
  - `prompt template` — a recipe describing how to turn a transcript into the exact
    messages (with their roles) sent to the model. It is NOT the prompt that is sent.
- **Config role:** the configuration is the universe of definitions (models, prompt
  templates, summarizers, datasets, judges, defaults). The command line selects and
  steers. The store holds results and is independent of both: courtesy name columns in
  the store originate from the config but are never resolved against it.
- **Store opening:** every command opens the store through one shared path: absent file
  or zero tables ⇒ create directory, file, and all 8 tables; an existing file with ≥ 1
  table ⇒ exact schema check. Schema mismatch is a hard error, never auto-migration,
  e.g. `error: store evalstore.sqlite3 schema mismatch: table 'generations' missing column
  'model_args'` plus a hint to move or delete the file. The only exception is `check`,
  which by default only reads (see below).
- **Concurrent instances:** at most one active instance per store. There is no app-level
  locking; SQLite's own file locking keeps the store from corrupting. Races cost
  (duplicated calls), they don't corrupt.

## Selection grammar

Dataset scoping on the run commands uses one repeatable flag:

    --select <dataset> <spec> [<spec> ...]   (repeatable)

- First token of each occurrence = dataset name; the rest = specs. A `--select`
  occurrence with zero specs is an error — never a silent full run:
  `--select qmsum-dev` ⇒ exit 2. `*` already expresses "everything" in one token.
- No `--select` at all ⇒ full scope (all configured datasets, all entries).
- Selections across occurrences are unioned; duplicates dropped.
- Spec forms (three disjoint namespaces, one marker each):
  - `#(<N>|<A>-<B>)(,(<N>|<A>-<B>))*` — one or more comma-separated elements, each a
    single 0-based file-order position or an inclusive range, in any order (a range may
    lead, e.g. `#3-7,0`). Strict digits only. Out-of-range, inverted, or malformed ⇒
    exit 2. Valid in named AND unnamed datasets.
  - `@<name>` — literal entry id, any string (`@@x` names an entry literally called
    `@x`). Resolves only in named datasets (one with `entry_id_field`); in an unnamed
    dataset ⇒ exit 2.
  - `*` — all entries of the dataset. As the entire `--select` argument (`--select *`)
    it means all datasets × all entries.
- Dataset and entry names may contain any characters; the markers are what make
  addressing unambiguous. Entry names are dataset-scoped — always give
  `<dataset> <spec>` pairs, never a bare entry name.

Examples:

    --select meetbank @doc-123
    --select qmsum-dev #3-7
    --select qmsum-dev #0,5,10-12
    --select meetbank *
    --select meetbank @doc-123 @doc-124 --select qmsum-dev #0-2

## check

Pre-flight diagnostic over the whole configuration. No selection flags, no scorer flags.

    <app> check [--config PATH] [--store PATH]
                [--server-command PATH] [--server-args JSON] [--server-env JSON]
                [--server-port N] [--server-startup-timeout S]
                [--probe-judges] [--create-store]

**Static phase (linter).** Collects and prints ALL static failures, then exits 2; the
live phase is skipped (deliberate contrast to the run commands, which fail fast).
Coverage:

- Config shape: duplicate names in a definition section
  (`error: duplicate name '<x>' in <section>`), `*` used as a name (reserved),
  `base` appearing after the summarizer it names, full four-component resolution of
  every summarizer, a stray `path` in a summarizer, unknown names in
  `default_metrics` / `default_judges` (errors carry the valid sets, e.g.
  `error: unknown metric 'rougeX' (registered: bertscore, bleu, rouge_l)` and
  `error: unknown judge 'gpt-4o' (configured: openrouter-llama-3-70b)`).
  Unrecognized fields anywhere else are a `warn:` only
  (`warn: unrecognized field '<name>' in <location>`); the open maps (`server.args`,
  `model_args`, `gen_params`, `env`) are exempt.
- Judge contract: every judge entry carries a REQUIRED boolean `requires_reference`
  (absent or non-boolean ⇒ exit 2). `{transcript}` and `{summary}` must appear in
  `system_content` + `user_template` combined (missing ⇒
  `error: judge 'X': missing placeholder '<p>'`); `{reference}` is required iff the flag
  is on (`error: judge 'X': requires_reference is true but placeholder '{reference}' is
  missing`); a superfluous `{reference}` with the flag off is legal. Unknown `{...}`
  tokens are NOT an error — they are not substituted and pass through unchanged into
  the sent prompt.
- Dataset contract: file missing/unreadable; extension not `.csv`, `.jsonl`, or `.json`;
  declared purpose field absent (CSV: column name, JSONL/JSON: object key); malformed
  rows (CSV column-count mismatch, duplicate header names; JSONL non-JSON line) with
  line numbers; zero entries; empty `transcript_field` value; `entry_id_field` declared
  but any entry has an empty id (ids are all-or-nothing). No transcript-length checks
  of any kind.
- The `server.command` binary and every model file exist.
- Port pre-scan: the configured port already bound ⇒ failure plus a hint that an
  orphaned server may be holding it.

**Store:** by default `check` opens read-only. Absent store ⇒ `note: no store at
<path>` — reported at a level below warning, never created. With `--create-store`, the
normal shared open path applies (bootstrap when absent: `note: created empty store at
<path>`). With ≥ 1 table the exact schema check runs either way. Probe results are
discarded; `check` never commits anything.

**Live phase (only if static is clean).** Local only, fail-fast. Per distinct
`(model, model_args)` pair in configuration order: spawn the model server → wait for
readiness (bounded by `startup_timeout_s`) → print the `/props` payload informationally
(`note: model server build: <json>`) and make one trivial preflight completion (the
preflight prompt is never counted in the fixture server's `--completion-log`) → run one
probe completion per distinct resolved summarizer of the pair (deduplicated by template
and gen_params; a fixed short probe transcript constant in the code, never dataset
content — no dataset content leaves the machine) → after the FIRST pair's probes only, a
context-adequacy probe per dataset in configuration order (empty datasets are skipped;
the longest transcript by char length; a `POST /tokenize` call only when the effective
`server.args` `ctx-size` is a positive int — bool excluded, so an absent `ctx-size`
means no tokenize call at all; any tokenize failure falls back to `len(text) // 3` and
never fails the run) → stop; the port is reused between cycles. Over ⇒ `warn:` only:
`warn: dataset '<name>': longest transcript (<N> tokens) exceeds context size (<ctx>)`,
or on the chars/3 fallback,
`warn: dataset '<name>': longest transcript (~<N> tokens estimated from chars/3)
exceeds context size (<ctx>)`.

A failure anywhere in a cycle fails fast with exit 1: one error line naming the failing
target — `error: model '<name>': <detail>` for a readiness or preflight failure,
`error: summarizer '<name>': <detail>` for a probe failure (a transport error renders
as e.g. `HTTP 500 from model server`) — followed by the last 20 lines of the server
log, raw, no prefix.

`--probe-judges` is opt-in, default off (no external/paid call by default). With it,
after the model cycles: one trivial completion per judge in configuration order, the
rubric rendered with placeholder example values only ("Example transcript for the
check judge probe.", "Example summary for the check judge probe.", and — only when the
judge's `requires_reference` is true — "Example reference for the check judge probe."),
the response run through the real parser; nothing usable ⇒
`error: judge '<name>': no usable values in probe response`, exit 1; a transport
failure ⇒ `error: judge '<name>': <detail>`, exit 1. Judge failures get no server-log
tail (no local server is involved). A judge whose `api_key_env` variable is unset/empty
⇒ static failure (exit 2).

Exit 0 = static clean and all live probes OK (warnings allowed). When the live phase
runs at all (at least one model pair, or `--probe-judges`), the last line is
`done(check): <n> server cycle(s), <m> summarizer probe(s), <k> judge probe(s)`
(pluralized per count, e.g. `done(check): 3 server cycles, 3 summarizer probes, 0
judge probes`); with no pairs and no `--probe-judges` there is no done line.

Scorer discovery (static; printed regardless of store presence, disjoint groups):

Example output (hypothetical configuration; default_metrics = [rouge_l],
default_judges absent):

    metrics (registered: 3):
      default_metrics:               rouge_l
      registered, not named there:   bertscore, bleu
    judges (configured: 1):
      default_judges:                openrouter-llama-3-70b
      configured, not named there:   (none)

In that illustration the judges lines show the absent-case shape: with
`default_judges` absent, group 1 is all configured and group 2 is (none).

Every registered metric and configured judge appears in exactly one group. A non-empty
"not named there" group means "these exist but will not run by default".

Against the repo's config.json (assuming the files it references exist):

    $ <app> check
    metrics (registered: 5):
      default_metrics:               faithfulness, key_claim_completeness, conciseness_length_proxy, structural_instruction_check
      registered, not named there:   internal_consistency
    judges (configured: 1):
      default_judges:                openrouter-llama-3-70b
      configured, not named there:   (none)
    plan(check): 2 datasets
    note: no store at evalstore.sqlite3
    note: model server build: {...}
    note: model server build: {...}
    note: model server build: {...}
    done(check): 3 server cycles, 3 summarizer probes, 0 judge probes
    exit 0

## generate

Stage 1: produce summaries from transcripts with the selected summarizers. Never
invokes judges or metrics, never reads reference summaries.

    <app> generate [--config PATH] [--store PATH]
                   [--select <dataset> <spec> ... ...]
                   [--summarizer NAME ...] [--model NAME ...] [--prompt-template NAME ...]
                   [--server-command PATH] [--server-args JSON] [--server-env JSON]
                   [--server-port N] [--server-startup-timeout S]

- No selection flags ⇒ full scope: all configured summarizers × all configured
  datasets × all entries.
- `--summarizer`, `--model`, `--prompt-template` are repeatable and take `*`. Named
  summarizers are NOT dissected into components: the component selections form a
  Cartesian product, which is a set of summarizers; specifically named summarizers are
  then ADDED as extra single combinations.
- No fallback server arguments: if the config has no `server` section, generation is a
  hard error. `server.args` may be `{}`; nothing is invented.
- `model_args` resolution is a two-layer merge: the model entry's `model_args` (absent
  ≡ empty) with the summarizer's `model_args` overriding per key. `server.args` is
  separate — it never layers into `model_args`. The resolved values are always taken
  from the configuration; a missing component is never "whatever is currently loaded".
- Item order is deterministic: summarizer → dataset → entry (config/file order). The
  currently loaded model may only affect the order attempts are made in (scheduling),
  never the identity of what runs.

**Server lifecycle.** One model-server cycle per distinct resolved
`(model, model_args)` pair, spawned on demand mid-run; the port is reused between
cycles; a busy port ⇒ exit 2 (never adopted; re-running after a crash hints at the
orphaned server). The launch line is the shared composition: `server.command` +
rendered `server.args` + rendered resolved `model_args` + `--port` + `--model <path>`.
Map rendering is shared: key ⇒ `--key`; scalar ⇒ `--key value`; `true` ⇒ bare
`--key`; `false` ⇒ omitted. `gen_params` are not launch arguments — they ride with each
completion request. For the example config:

    # summarizer 'std' (gemma, model_args {"flash-attn": true})
    /home/vscode/llama.cpp/build-rocm/bin/llama-server --ctx-size 32768 --batch-size 512 --flash-attn --port 8080 --model /home/vscode/models/gemma-3-27b-it.Q4_K_M.gguf

    # summarizer 'no-fa' (same model, model_args {"flash-attn": false} → omitted)
    /home/vscode/llama.cpp/build-rocm/bin/llama-server --ctx-size 32768 --batch-size 512 --port 8080 --model /home/vscode/models/gemma-3-27b-it.Q4_K_M.gguf

**Skip logic.** Before any call, committed generations are pre-scanned by identity
(transcript + summarizer): an item already committed ⇒ skipped, no model call, counted.
Identical transcript text across datasets with the same summarizer ⇒ one store row.
If the whole scope is already committed ⇒ exit 0 WITHOUT spawning the server.

**Store footprint.** Upserts `transcripts` and `reference_summaries` (when the dataset
declares `reference_field`) plus `models` and `prompt_templates` (same transaction),
then one `generations` row per committed item.

**Fail-fast.** First failure (HTTP error, empty completion, server death, readiness
timeout) ⇒ abort, exit 1, failing item + error + last ~20 server-log lines + a resume
hint (committed items persist; re-run to continue).

    $ <app> generate --select qmsum-dev #0-2 --summarizer std
    plan(generate): 1 summarizer, 3 items, 1 server cycle
    done(generate): 3 committed, 0 skipped, 0 failed
    exit 0

    $ <app> generate --select qmsum-dev #0-2 --summarizer std
    plan(generate): 1 summarizer, 3 items, 1 server cycle
    note: all 3 items already committed; server not started
    done(generate): 0 committed, 3 skipped, 0 failed
    exit 0

    $ <app> generate --summarizer std --summarizer no-fa
    error: port 8080 already bound (a previous model server may still be running)
    exit 2

    $ <app> generate --select qmsum-dev #0-2 --summarizer std
    error: item qmsum-dev#1 (summarizer 'std'): HTTP 500 from model server
    <last ~20 lines of server log>
    note: re-run to resume; 1 item already committed
    exit 1

## score

Stage 2: score committed generations with the effective metric set and/or judge set.
Never generates summaries and never spawns the model server UNLESS `--generate`.

    <app> score [--config PATH] [--store PATH]
                [--select <dataset> <spec> ... ...]
                [--summarizer NAME ...] [--model NAME ...] [--prompt-template NAME ...]
                [--metrics NAME ...] [--judges NAME ...]
                [--no-metrics] [--no-judges]
                [--generate]
                [--server-command PATH] [--server-args JSON] [--server-env JSON]
                [--server-port N] [--server-startup-timeout S]

**Metrics resolution (precedence):**

1. `--metrics <name> ...` ⇒ exactly that list (the `[]` token ⇒ zero metrics, legal).
2. `--metrics` omitted ⇒ `default_metrics` (present-but-`[]` ⇒ zero metrics).
3. `default_metrics` key absent from the config ⇒ ALL code-registered metrics.

Any registered metric is invocable by name or `*` whether or not it appears in the
config. `*` may co-occur with names (union = the whole set).

**Judges resolution (precedence):**

1. `--judges <name> ...` ⇒ exactly that list.
2. `--judges *` ⇒ all configured judges.
3. `--judges` bare ⇒ `default_judges` if present (present-but-`[]` ⇒ zero +
   `note: --judges given but default_judges is empty; no judges run`); if the key is
   ABSENT ⇒ all configured judges (the explicit flag shows enough intent).
4. `--judges` omitted ⇒ ZERO judges — the deliberate safe default, no error; the plan
   line shows `0 judges`. Judges are never invoked implicitly.

**The `[]` token and shorthands.** `--no-metrics` ≡ `--metrics '[]'`; `--no-judges` ≡
`--judges '[]'`. `[]` is a token, not a flag value you type bare: quote it in the shell
(`--metrics '[]'`). `--no-X` is mutually exclusive with `--X` in any form ⇒ exit 2.

**Server flags.** The config `server` section is always legal (it is schema) and is
exercised only with `--generate` — inert without it, never an error. CLI `--server-*`
without `--generate` ⇒ exit 2: `error: --server-* flags require --generate`.

**Execution order.** (1) Pre-effect validation (unknown names, malformed specs/JSON,
out-of-range, config-shape failures) ⇒ exit 2 before store or network. (2) Resolve the
effective scorer set. (3) Infeasible (scorer, dataset) pairs — a reference-requiring
scorer over a dataset without `reference_field` — are dropped with one `warn:` each;
they are never committed. (4) With `--generate`: the full `generate` lifecycle runs
first (stage-1 fail-fast aborts before any scoring). (5) Metrics phase over all items,
THEN judges phase — no judge tokens spent before the free metrics finish; a metric
algorithm failure ⇒ exit 1 before any judge call. Each (item, scorer) unit is one
transaction.

**Judge failures.** A judge call yielding no extractable quality ⇒ `warn:` + no row +
continue (dataset averages are the point; the unit can be retried later). Transport or
HTTP failure, or an empty completion ⇒ fail-fast exit 1, naming the item and the judge.

**Notes (all exit 0).** No committed generations in scope (no `--generate`) ⇒
`note: no committed generations in scope; run 'generate' first`. Some but not all
selected items lack committed generations ⇒ `note: N selected items have no committed
generation; run 'generate' first`. Zero feasible pairs ⇒ warnings + `note: no scorable
pairs in scope; nothing scored`. Both flag families empty ⇒ `note: no metrics or
judges selected; nothing scored` (with `--generate` the generation stage still runs
first, then the note).

**Plan line.** Always printed, always with the effective scorer set. Unit semantics:
"infeasible" counts (scorer, dataset) pairs (= the `warn:` line count); "to run" /
"already scored" count (item, scorer) units (units belonging to infeasible pairs
are excluded from "to run").

    $ <app> score --select meetbank * --summarizer std
    plan(score): 4 metrics, 1 judge | 50 items | 250 to run, 0 already scored | 0 infeasible
    done(score): 250 committed, 0 dropped, 0 failed
    exit 0

    $ <app> score --no-judges --select qmsum-dev #3-7
    plan(score): 4 metrics, 0 judges | 5 items | 20 to run, 0 already scored | 0 infeasible
    exit 0

    $ <app> score --generate --select meetbank @doc-123 --summarizer std --judges openrouter-llama-3-70b
    plan(generate): 1 summarizer, 1 item, 1 server cycle
    plan(score): 4 metrics, 1 judge | 1 item | 5 to run, 0 already scored | 0 infeasible
    done(generate): 1 committed, 0 skipped, 0 failed
    done(score): 5 committed, 0 dropped, 0 failed
    exit 0

    $ <app> score --server-port 8081
    error: --server-* flags require --generate
    exit 2

**Store footprint.** Commits `metric_evaluations` (scalar value) and
`judge_evaluations` (one nullable column per quality); upserts `reference_summaries`
when the dataset declares `reference_field`; with `--generate`, the `generate`
footprint as well.

## sweep

Exhaustive wide net: exact `score` semantics, including implied generation, over ALL
configured summarizers × ALL configured datasets × the resolved scorer set. It never
depends on prior state — missing summaries are produced first. Infeasible (scorer,
dataset) pairs warn+drop as in `score`.

    <app> sweep [--config PATH] [--store PATH]
                [--server-command PATH] [--server-args JSON] [--server-env JSON]
                [--server-port N] [--server-startup-timeout S]
                [--all-metrics] [--all-judges] [--all]

- **No selection or scorer flags.** Any of `--select` / `--summarizer` / `--model` /
  `--prompt-template` / `--metrics` / `--judges` / `--generate` ⇒ exit 2:
  `error: 'sweep' takes no selection or scorer flags (it is exhaustive); use 'score --generate' to narrow`
- **Scorer set** (the default-vs-all distinction): `default_metrics` present ⇒ exactly
  that list (incl. `[]` ⇒ zero metrics); absent ⇒ all code-registered. `default_judges`
  present ⇒ exactly that list; absent ⇒ all configured judges. Present-but-empty ≠
  absent — there is no fallback to all.
- **Widen-only overrides:** `--all-metrics`, `--all-judges` (independent, default off),
  and the combined `--all` (= both). Composable with the individuals, idempotent,
  set-based. No narrowing flags exist.
- The summarizer axis is the configured summarizers ONLY (no model×template Cartesian
  product). Wider probing: `generate --model * --prompt-template *`, or define the
  combinations as summarizers in the config.
- Message order: `warn:` → `plan(generate):` → `plan(score):` → `done(generate):` →
  `done(score):`. Whole scope committed ⇒ no server spawn. Credential preflight: a
  judge whose `api_key_env` is unset/empty ⇒ `warn:` + drop, exit 0 (contrast: an
  explicit `score --judges X` with an unset key is exit 2).
- Per-item and per-(item, scorer) commits; exit classes 0/1/2 inherited from `score`.

    $ <app> sweep --select meetbank *
    error: 'sweep' takes no selection or scorer flags (it is exhaustive); use 'score --generate' to narrow
    exit 2

    $ <app> sweep
    warn: judge 'openrouter-llama-3-70b' requires reference summaries; dataset 'qmsum-dev' has none (pair skipped)
    plan(generate): 4 summarizers, 292 items, 3 server cycles
    plan(score): 4 metrics, 1 judge | 292 items | 1368 to run, 0 already scored | 1 infeasible
    done(generate): 292 committed, 0 skipped, 0 failed
    done(score): 1368 committed, 0 dropped, 0 failed
    exit 0

    $ <app> sweep --all
    plan(generate): 4 summarizers, 292 items, 3 server cycles
    plan(score): 4 metrics, 1 judge | 292 items | 1368 to run, 0 already scored | 1 infeasible
    exit 0
    # (with the example config, --all changes nothing: default_metrics already lists
    #  all 4 registered metrics and default_judges lists the only configured judge;
    #  the flag matters when the config names fewer.)

## report

Computes and prints summaries of candidate performance from the store. The only
command that reads evaluations; produces nothing but a display. Strictly read-only:
no commits, no upserts (not even courtesy-column refreshes), no server, no model or
judge calls. Exit 0 (zero rows ⇒ `note: no scored results in scope; run 'score' (or
'score --generate') first`) / 2 (pre-effect, including `--server-*` given — report has
no generate stage).

    <app> report [--config PATH] [--store PATH]
                 [--select <dataset> <spec> ... ...]
                 [--summarizer NAME ...] [--model NAME ...] [--prompt-template NAME ...]
                 [--metrics NAME ...] [--judges NAME ...]
                 [--no-metrics] [--no-judges]
                 [--json] [--by dataset] [--blind-sample N] [--csv PATH]

- Selection and scorer resolution = `score` without `--generate` (including `*`).
- Default output: a human table, one row per (candidate, scorer) with
  `n, mean, min, max`; judges get one row per candidate × quality; `n=0` rows are
  shown with dashes, not omitted.
- `--json` — same data, stable key order.
- `--by dataset` — the only grouping axis (default: aggregated across in-scope
  datasets).
- `--blind-sample N` — the last N entries of each in-scope dataset in file order,
  applied after `--select`. A reporting/holdout convention only; nothing is enforced.
- `--csv PATH` — flattened rows, header `candidate[,dataset],scorer,n,mean,min,max`;
  the table is suppressed (scope lines still on stdout); the parent directory must
  exist (else exit 2); the file is created only after pre-effect validation; mutually
  exclusive with `--json` (exit 2); minimal CSV dialect.

    $ <app> report --by dataset
    candidate,dataset,scorer,n,mean,min,max
    std,meetbank,faithfulness,50,0.83,0.61,0.97
    std,meetbank,key_claim_completeness,50,0.71,0.40,0.93
    std,meetbank,factual_correctness (judge),50,0.88,0.70,1.00
    std,meetbank,completeness (judge),50,0.81,0.55,0.95
    std,meetbank,conciseness (judge),50,0.64,0.30,0.90
    no-fa,qmsum-dev,faithfulness,23,0.79,0.58,0.94
    exit 0

    $ <app> report --metrics '[]' --no-judges --blind-sample 10 --csv out/meetbank.csv
    note: wrote 4 rows to out/meetbank.csv
    exit 0

This command was accepted SHALLOWLY: the shape stands, details are re-openable by name.

## clear

Wipes the store: all 8 tables, single transaction, all-or-nothing, no subsetting.
The config is loaded only to resolve the default store path. Role: the human-initiated
clean slate after, e.g., a hardware change — the application does not detect hardware
changes; that is the human's job.

    <app> clear [--config PATH] [--store PATH] [--yes]

Dry-run by default (a dry run is a successful invocation, not an error):

    $ <app> clear
    plan(clear): store evalstore.sqlite3 | transcripts 210 | reference_summaries 150 | models 2 | prompt_templates 3 | generations 840 | judges 1 | judge_evaluations 300 | metric_evaluations 600
    note: re-run with --yes to delete all rows (this cannot be undone)
    exit 0

With `--yes` (the flag is the confirmation; there is no interactive prompt):

    $ <app> clear --yes
    done(clear): 2105 rows deleted across 8 tables
    exit 0

Scripts verifying that the wipe actually happened key on the `done(clear):` line — the
stdout prefixes are the machine interface (a lightweight PoC convention, not a real
API). No store ⇒ `note: no store at evalstore.sqlite3; nothing to clear`, exit 0. Missing
config ⇒ exit 2 (the default store path is unresolvable).

## Notes

- **Local model as judge endpoint (zero-change path).** A manually started local
  `llama-server` can serve as a judge: set the judge's `endpoint` to
  `http://127.0.0.1:<port>/v1`. `api_key_env` must still name a set variable (a dummy
  works) because `check --probe-judges` fails statically on an unset/empty env. Judge
  endpoints get no readiness check — a dead endpoint is a transport failure (exit 1).
  The same judge model reached locally or remotely is the same identity: its rows
  dedupe.
- **Self-judging is misconfiguration.** A judge whose model is also the model under
  test is a setup error, not a supported mode; the application does not police it.
- **Retired command names.** The old `metrics`/`judge`/`score` triad is gone;
  `metrics X...` re-expresses as `score --metrics X...` (no `--judges`), and
  `judge Y...` as `score --metrics '[]' --judges Y...`.
- **`config.json` at the repo root** is the normative example configuration. The
  data/prompt/model paths it references are illustrative and absent from the repo;
  `check` reporting them as contract failures is expected until they exist.
- **`tune` / meta-strategies** are parked, not dropped: the architecture (atomic
  per-item and per-(item, scorer) commits, the store as single source of truth,
  input-addressed identities, deterministic selection, config summarizer roster)
  allows them to be added later as thin orchestration subcommands.
