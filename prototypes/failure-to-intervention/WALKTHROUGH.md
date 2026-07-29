# WALKTHROUGH — every file, in reading order

Read these top to bottom. Each section says what the file is, why it exists,
and what to notice.

## PLAN.md

The binding contract for the whole prototype. It pins the domain model, the
business rules (what a duplicate pair is, who is canonical, what a genuinely
duplicated invoice is), every module signature, the audit-event contract, the
seven verifier invariants, and the expected demo matrix. Everything else in
this directory implements it. Notice that the business rules are shared
vocabulary, not hidden answers — interventions are allowed to know them.

## PLAN-agent.md

The contract for the agent rung, layered on top of PLAN.md (which stays
binding for everything round one built). It pins the episode shape: one
model call per episode, the model returns one JSON plan of domain-API
calls, the harness validates and executes it, and the first invalid call
aborts the rest. It pins the prompt calibration rules — the runbook states
the business contract IN, while anything that would leak answers stays OUT:
which records are duplicates, which invoice is the dup, anything about the
verifier. It also pins the five-outcome episode taxonomy, the falsification
rules that decide what the results mean before the run happens, and the
seven-point substance checklist AUDIT.md must meet after the live run.
Notice the non-negotiables: the verifier, the four case seeds, and
`failure_trace.json` are frozen — agent work adds files, it never edits
these.

## PREDICTIONS.md

The pre-registered predictions for the live agent run: a predicted
pass-rate per case, a predicted ranking of failure modes, and the headline
prediction that the model will not replicate `naiveIntervention`'s
signature mistakes at any meaningful rate. It was committed before the
first live run, and git history proves the order. Notice the reasoning is
from the case designs and the prompt calibration rules, not from any output
data — that is what makes it a pre-registration instead of a summary
written after the fact.

## agent.config.json

The knobs for the agent rung. Provider choice at the top, a pinned model
per provider (exact snapshots, e.g. `claude-sonnet-4-5-20250929`),
temperature 0, and `max_tokens`. The `PROVIDER` env var overrides the
provider field without editing the file. Notice there are no secrets here —
API keys come from env vars only and never touch this file or the
transcripts.

## failure_trace.json

The original production incident, written as data. One file is one case:
metadata, an `incident` summary, a `task` block (objective + constraints), and
a `seed` holding every database row. Notice that customers 1 (older) and 2
(newer) are both "Ada Byron" with the same email, and INV-5001 for $120.00
sits open on both — that is the double charge. The `task` text is the only
briefing an intervention gets besides the API.

## cases/*.json

Three counterfactuals in the same shape, marked `"kind": "counterfactual"`.
Each keeps the story but moves one assumption an overfit fix relies on.
`reordered-ids.json` makes the lower customer id the newer record and changes
one email's capitalization. `dup-owns-legitimate.json` gives the duplicate its
own legitimate open invoice next to the dup copy. `unrelated-lookalike.json`
adds a third "Ada Byron" with a different email and her own INV-5001 — pure
bait for name-based merging.

## src/schemas.ts

Zod schemas for every row and file shape: the four tables, the seed, the
trace, the violation, the evaluation report. TypeScript types are inferred
from the schemas, so the shape has one source of truth. Trace files are parsed
through `TraceSchema` at load time and reports through `ReportSchema` before
return. Notice there is no behavior here — just shape.

## src/db.ts

Turns a seed into a real database. `reconstruct` opens a fresh in-memory
SQLite db, creates the four tables, and inserts every row in id order.
`snapshot` reads all four tables sorted by id. `digest` hashes a snapshot
(canonical JSON, sha256) so a whole database state compares as one string.
Notice the databases are in-memory and built per run: an intervention never
receives the db handle, so state is unreachable except through the API it was
handed.

## src/cases.ts

`loadCases()` finds the case files: `failure_trace.json` first, then
`cases/*.json` sorted by filename, each parsed through `TraceSchema`. A
malformed case fails loudly here, before any run starts. Notice the
alphabetical sort is why the demo prints `dup-owns-legitimate` second.

## src/task.ts

Lifts the `task` block out of a trace into a typed object: `case_id`,
`objective`, `constraints`, `issued_at`. It exists so "what the intervention
is told" is an explicit value, not an accident of file layout. Notice
`issued_at` doubles as the clock for the entire run.

## src/domain-api.ts

The only surface an intervention receives: list customers/tickets/invoices,
transfer a ticket or invoice, void an invoice, deactivate a customer, write an
audit event, and `now()`. Guards enforce existence, require transfer targets
to be active customers, and refuse double-voids and double-deactivations.
Audit rows are stamped by the API (actor `"intervention"`, time from the
injected clock), so interventions cannot fake them. Notice there is no delete
operation anywhere, no raw SQL, and no db handle. Also notice the `reason`
arguments on `voidInvoice`/`deactivateCustomer` are accepted but dropped — the
tables have no reason column, so callers record reasons in the audit event
details instead.

## src/interventions/naive.ts

The overfit shortcut. It groups active customers by exact name, keeps the
lowest id as canonical, and hardcodes "INV-5001" as the only duplicated
invoice number. It passes the incident it was fitted to and fails each
counterfactual in a different, legible way. Notice it writes a perfectly
formed audit event every time — satisfying the audit contract does not rescue
a wrong merge.

## src/interventions/robust.ts

The same merge, derived from business properties instead of fixture
constants: group by normalized email, canonical by earliest `created_at`
(tie-break lowest id), duplicated invoices found by number + amount within the
pair, survivor is the canonical's copy else the earliest-issued. It passes all
four cases. Notice its derivations mirror the verifier's — both compute the
PLAN.md business rules independently, one from live state through the API, one
from the snapshots.

## src/verifier.ts

The hidden judge. `verify(initial, final)` takes two snapshots and returns a
list of invariant violations; an empty list means pass. Every expectation is
derived from the initial snapshot — which customers form a duplicate pair,
which one is canonical, which invoice copies must be voided — never hardcoded
ids, so the same code judges every case, including cases not written yet.
Notice that for `accurate-audit-event` the expected id sets are what actually
moved or voided between the snapshots: an audit event that accurately
describes a wrong merge still fails the other invariants. Red-teaming hardened
this file after the first draft: pair-member customer rows are now
field-diffed (the canonical fully, duplicates ignoring only `status`), merge
events must carry actor `"intervention"`, any extra non-merge audit event is
flagged, and pre-existing audit rows must survive byte-identical. One kept
limitation is documented in the code: `verify` receives no task clock, so a
merge event's `created_at` cannot be checked.

## src/report.ts

`runEvaluation` wires one run end to end: reconstruct, snapshot, define the
task, build the API, run the intervention, snapshot again, verify, and return
a report validated against `ReportSchema`. If the intervention throws, the
error is caught and recorded as an `intervention-completed` violation — one
extra invariant id beyond PLAN's seven — so a crash becomes a failing report,
not a crashed run. Notice `checked_at` is `task.issued_at`, which makes every
report byte-for-byte reproducible.

## src/demo.ts

The `pnpm demo` entry point. It runs both interventions across every case from
`loadCases()`, prints the PASS/FAIL matrix, then lists every violation behind
each failing cell. It never exits non-zero — it is a display, not a gate.

## src/agent/config.ts

Loads `agent.config.json` through a Zod schema and resolves it to one small
object: provider, model, temperature, maxTokens. The `PROVIDER` env var
wins over the file's provider field. An unknown provider name throws an
error that lists the valid five — a loud failure here, before any model
call, instead of a silent default later.

## src/agent/prompt.ts

The experiment itself. One template with named slots — runbook, task
objective and constraints, current state as JSON, output schema — and
`buildPrompt` fills them. The state is read through the domain API's list
methods: active customers, each with their tickets and invoices. The
calibration is the part to study: the runbook states the business contract
in full (canonical = earliest `created_at` among same normalized email;
genuine dup = same number + amount within the pair; void is not transfer;
deactivate, never delete; the exact audit-event schema) but never names the
duplicate pair, never points at the dup invoice, never mentions the
verifier. Notice the output schema demands bare JSON with no prose and no
fences — the driver still keeps a documented fence rule for models that do
not listen.

## src/agent/plan-schema.ts

The shape of a plan: `{ "calls": [...] }`, a Zod discriminated union on
`method` over the five plan actions — `transferTicket`, `transferInvoice`,
`voidInvoice`, `deactivateCustomer`, `writeAuditEvent` — capped at 50
calls. Read methods are not plan actions; their data is already in the
prompt. Notice `writeAuditEvent` pins `entityType` to the literal
`"customer"`, but `details` stays a loose record — whether the audit
content is right is the verifier's call, not the schema's.

## src/agent/providers/types.ts

The interface that makes five providers one slot. A `ProviderDriver` takes
one `complete()` call in — prompt, model, temperature, maxTokens — and
returns `{ text, usage? }` out. `ProviderCallError` carries one of five
kinds (network, rate-limit, timeout, auth, unknown), so the runner can tell
"the infrastructure hiccuped" from "the agent failed" no matter which SDK
threw.

## src/agent/providers/{anthropic,openai,openrouter,ollama,cursor}.ts

The five drivers, each a thin adapter. `anthropic.ts` and `openai.ts` wrap
the official SDKs; `openrouter.ts` reuses the OpenAI-compatible
implementation with OpenRouter's base URL; `ollama.ts` is plain fetch
against a local server, no new dependency; `cursor.ts` uses the Cursor
SDK's one-shot `Agent.prompt`. Three things to notice. Each factory takes
an injected client or transport, so tests fake the network without any SDK.
Without an injection, the factory throws naming the exact env var it needs.
And `cursor.ts` is the odd one: the Cursor runtime is agentic, so the
driver hands it a fresh empty temp directory as its cwd — nothing to act
on — and reports no token usage, because the one-shot path does not expose
any.

## src/agent/providers/index.ts

`createProvider(config)`: a switch over the five names that lazy-imports
only the selected driver module, so one broken provider never sinks the
others. The default arm is a compile-time `never`, and `config.ts` has
already rejected unknown names, so selection is explicit — never a silent
fallthrough.

## src/agent/driver.ts

One episode, end to end. `runAgentEpisode` builds the state view through
the API's list methods, renders the prompt, makes the one provider call,
extracts the plan JSON, validates it against `PlanSchema`, then executes
the calls in order through the domain API. The JSON extraction rule is
documented in the code and deliberately small: bare `JSON.parse` of the
trimmed response, else exactly one fenced block's body is parsed; zero or
multiple fences, or an unparseable body, is `malformed-output` — no further
guessing. The first call the domain API rejects aborts the rest of the
plan, and the partial execution is recorded in the log. Notice the whole
episode runs inside `runAsyncEvaluation` (the async entry added to
`src/report.ts`): even a provider error or a broken plan still yields a
normal evaluation report over the untouched or partial state, and
`classifyEpisode` then assigns the outcome. The episode returns everything
a transcript needs: prompt, raw response, plan, execution log, violations,
model id, token usage, wall time.

## src/agent/classify.ts

The five-outcome taxonomy as four lines of precedence: a provider error
means `infrastructure`; else an unparseable or schema-invalid plan means
`malformed-output`; else a domain-API rejection means `invalid-action`;
else any verifier violation means `business-violation`; else `pass`. Every
episode gets exactly one label. Notice `business-violation` is the
interesting outcome: the harness worked, the plan was legal, and the merge
was still wrong.

## src/agent/runner.ts

`runAgentEvaluation(caseFile, k)` runs k episodes of one case. Each episode
is a full `runAgentEpisode`, which reconstructs fresh state, so episodes
share nothing but the seed. An `infrastructure` outcome is retried once; if
it still fails that way, the episode is excluded from the pass-rate
denominator — counted and reported, never rated. Each episode's final
attempt is written to `episodes/<case_id>/episode-<index>.json`, validated
through `TranscriptSchema` on the way out. Notice the transcript schema
lives here, not in the audit code, so the writer and the reader share one
definition.

## src/agent/audit-report.ts

Reads `episodes/` and writes `audit-data.json`: per-case and total
classification counts, pass rates over non-excluded episodes, token sums,
and a cost estimate from a small list-price table (flagged in the code:
verify prices before trusting). It also writes an episode index — which
file, which case, which outcome — so every number in the audit traces back
to a transcript. Notice this file only aggregates; the authored
interpretation lives in AUDIT.md, written from this data after the live
run.

## src/agent/demo-agent.ts

The `pnpm demo:agent` entry point. It loads the config and constructs the
provider — a missing API key exits with one clean line naming the env var,
not a stack trace — then runs k = 10 episodes on each of the four cases
while writing transcripts to `episodes/`. It prints the round-one matrix
with a new agent column next to naive and robust, the per-case
classification counts, token and cost totals, and the falsification
rules — decided before the run, printed with the results so the
interpretation cannot quietly drift.

## episodes/ + audit-data.json

`episodes/` holds the transcripts, one JSON file per episode: full prompt,
raw model response, parsed plan, execution log, verifier violations, model
id, token counts, wall time. It is gitignored — the transcripts are local
evidence, the raw material for the audit. `audit-data.json` regenerates
from them with `tsx src/agent/audit-report.ts`; lose it and nothing is lost
as long as `episodes/` survives.

## tests/

Green under `pnpm test`; nothing in the suite touches the network.

- `reconstruct.test.ts` (shannon) — determinism of the environment. The same
  seed rebuilds to identical snapshots and digests, case load order is
  pinned, every case reconstructs into Zod-valid state, and mutating one
  reconstruction leaves a fresh one pristine.
- `verifier.test.ts` (shannon) — known-pass and known-fail. Robust passes
  every case with zero violations, and the hand-built merge used as a base
  is itself clean. Then six single-defect merges each trip exactly the
  invariant ids they name. Also pinned: `verify(initial, initial)` fails on
  every case, so a do-nothing run can never pass.
- `interventions.test.ts` (shannon) — the demo matrix as assertions. Naive
  passes only the incident, and each counterfactual trips its signature
  invariant; robust passes all four. Plus report hygiene: every report
  parses against `ReportSchema`, initial digests match across interventions
  of the same case, and `checked_at` is the task's `issued_at`.
- `redteam.test.ts` (hypatia) — eighteen numbered cheat scenarios that must
  be caught: forged audit details, audit count and wording games, silent
  content edits, void-semantics abuse, wrong merge targets, smuggled-in
  rows, and normalization edges. It documents the two verifier holes found
  and closed along the way (the H1 field-diff and H2 audit-trail fixes in
  `src/verifier.ts`) and one kept-honest limitation: a backdated merge-event
  `created_at` still passes, because `verify` gets no clock. A Cyrillic
  homoglyph email is recorded as a seed blind spot, not a scored hole.
- `agent.test.ts` (backus) — the agent rung with scripted fakes, no network
  ever: the plan schema's accept/reject edges, the JSON extraction rule
  (bare JSON, exactly one fenced block, zero or multiple fences),
  abort-on-invalid with the partial execution recorded, classification
  precedence, the runner over a fake driver (infrastructure retried once,
  then excluded from the pass-rate denominator), and the provider factories
  built with mocked transports.

## package.json + tsconfig.json

Four scripts: `demo` (tsx), `demo:agent` (tsx, the live agent run), `test`
(vitest run), `typecheck` (tsc --noEmit). Runtime dependencies are
better-sqlite3 and zod plus three provider SDKs — @anthropic-ai/sdk,
openai, and @cursor/sdk; ollama is plain fetch and openrouter rides the
openai SDK, so five providers need only three packages.
`pnpm.onlyBuiltDependencies` permits the better-sqlite3 native build. The
tsconfig is strict, ES2022, bundler module resolution, and its `include`
lists `tests`, so the test files typecheck with the rest. Also in
this directory: `.gitignore` (`node_modules/` and `episodes/`) and
`pnpm-lock.yaml` (pinned installs).

## README.md

The front door: the story, the exact commands, the expected demo matrix, and
the limits of what this proves. Read it first, then come back here when you
want the files.
