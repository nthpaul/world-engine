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

## tests/

Four files, 60 tests, green under `pnpm test`.

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

## package.json + tsconfig.json

Three scripts: `demo` (tsx), `test` (vitest run), `typecheck` (tsc --noEmit).
Runtime dependencies are just better-sqlite3 and zod;
`pnpm.onlyBuiltDependencies` permits the better-sqlite3 native build. The
tsconfig is strict, ES2022, bundler module resolution, and its `include`
lists `tests`, so the test files typecheck with the rest. Also in
this directory: `.gitignore` (just `node_modules/`) and `pnpm-lock.yaml`
(pinned installs).

## README.md

The front door: the story, the exact commands, the expected demo matrix, and
the limits of what this proves. Read it first, then come back here when you
want the files.
