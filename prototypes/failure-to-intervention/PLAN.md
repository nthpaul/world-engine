# PLAN — failure-to-intervention prototype

One small executable proof: a production-shaped agent failure, reconstructed as a
stateful environment, evaluated by business invariants, varied counterfactually,
used to distinguish an overfit intervention from a robust one.

Data flow:

```
failure_trace.json
  -> reconstruct deterministic SQLite state
  -> task definition
  -> intervention operating through a domain API
  -> hidden state-based verifier
  -> structured evaluation report
```

Stack: TypeScript, Node.js, pnpm, SQLite (better-sqlite3, in-memory), Zod, Vitest.
No web UI, MCP, auth, deployment, containers, model calls, RL, plugin
architecture, or extra business domains.

## File tree and single-writer ownership

```
prototypes/failure-to-intervention/
  PLAN.md                     (orchestrator)
  README.md                   (lamarr)  — experiment + exact commands
  WALKTHROUGH.md              (lamarr)  — every file in reading order
  package.json                (tesla)
  tsconfig.json               (tesla)
  .gitignore                  (tesla)   — node_modules/
  failure_trace.json          (tesla)   — case 1, the original incident
  cases/
    reordered-ids.json        (tesla)   — case 2
    dup-owns-legitimate.json  (tesla)   — case 3
    unrelated-lookalike.json  (tesla)   — case 4
  src/
    schemas.ts                (tesla)   — Zod schemas + inferred types
    db.ts                     (tesla)   — DDL, reconstruct, snapshot, digest
    cases.ts                  (tesla)   — load + validate all case files
    task.ts                   (tesla)   — trace -> task definition
    domain-api.ts             (tesla)   — constrained API given to interventions
    verifier.ts               (tesla)   — hidden state-based invariant checks
    report.ts                 (tesla)   — runEvaluation -> EvaluationReport
    interventions/naive.ts    (tesla)
    interventions/robust.ts   (tesla)
    demo.ts                   (tesla)   — `pnpm demo` result matrix
  tests/
    reconstruct.test.ts       (shannon)
    verifier.test.ts          (shannon) — known-pass + known-fail
    interventions.test.ts     (shannon) — naive vs robust across cases
    redteam.test.ts           (hypatia) — cheat attempts must be caught
```

## Domain model (SQLite)

- `customers(id INTEGER PK, name TEXT, email TEXT, created_at TEXT, status TEXT)` — status `active` | `deactivated`
- `tickets(id INTEGER PK, customer_id INTEGER, subject TEXT, status TEXT, created_at TEXT)` — status `open` | `closed`
- `invoices(id INTEGER PK, customer_id INTEGER, number TEXT, amount_cents INTEGER, issued_at TEXT, status TEXT)` — status `open` | `paid` | `void`
- `audit_events(id INTEGER PK, actor TEXT, action TEXT, entity_type TEXT, entity_id INTEGER, details TEXT, created_at TEXT)` — details is a JSON string

ISO-8601 UTC strings for all timestamps. All rows come from the trace seed; the
only rows added at runtime are audit events.

## Trace file schema (Zod, `schemas.ts`)

```json
{
  "case_id": "original-incident",
  "kind": "incident" | "counterfactual",
  "description": "…",
  "incident": { "summary": "…", "observed_at": "2026-07-01T00:00:00Z" },
  "task": { "issued_at": "2026-07-02T00:00:00Z", "objective": "…", "constraints": ["…"] },
  "seed": {
    "customers": [ … ], "tickets": [ … ], "invoices": [ … ], "audit_events": []
  }
}
```

## Business rules (shared vocabulary, not hidden answers)

- Two active customers are a **duplicate pair** when their normalized emails
  (trim + lowercase) match.
- The **canonical** customer is the one with the earliest `created_at`;
  tie-break: lowest `id`.
- An invoice is **genuinely duplicated** when the pair holds two active copies
  with the same `number` and `amount_cents`. The copy on the canonical customer
  survives; if the canonical has no copy, the earliest-issued copy survives.
- History is preserved: legitimate tickets/invoices move to the canonical
  customer; the duplicate is **deactivated, never deleted**; the voided copy
  stays where it was (void is not transfer).
- Every merge writes one audit event (contract below).
- Unrelated customers — different normalized email, even if the name matches —
  are out of scope and must stay byte-identical.

## The four cases

| case_id | file | wrinkle |
|---|---|---|
| `original-incident` | `failure_trace.json` | Ada Byron pair (ids 1 older / 2 newer); INV-5001 $120.00 exists on both; Grace Lee unrelated |
| `reordered-ids` | `cases/reordered-ids.json` | same story, new ids/numbers; the **lower** customer id is the **newer** record |
| `dup-owns-legitimate` | `cases/dup-owns-legitimate.json` | duplicate owns the dup copy **and** a unique legitimate invoice that must move over still `open` |
| `unrelated-lookalike` | `cases/unrelated-lookalike.json` | third "Ada Byron" with a **different email** and her own INV-5001; must stay untouched |

## Pinned module contracts

```ts
// schemas.ts — Zod schemas: CustomerSchema, TicketSchema, InvoiceSchema,
// AuditEventSchema, SeedSchema, TraceSchema, ViolationSchema, ReportSchema
// + inferred types Customer, Ticket, Invoice, AuditEvent, Seed, Trace,
//   Violation, EvaluationReport

// db.ts
export function reconstruct(seed: Seed): Database          // fresh :memory:, DDL + inserts in id order
export interface Snapshot { customers: Customer[]; tickets: Ticket[]; invoices: Invoice[]; audit_events: AuditEvent[] } // sorted by id
export function snapshot(db: Database): Snapshot
export function digest(snap: Snapshot): string             // sha256 hex of canonical JSON

// cases.ts
export interface CaseFile { trace: Trace; path: string }
export function loadCases(root?: string): CaseFile[]       // failure_trace.json first, then cases/*.json sorted

// task.ts
export interface Task { case_id: string; objective: string; constraints: string[]; issued_at: string }
export function defineTask(trace: Trace): Task

// domain-api.ts — the ONLY surface an intervention receives
export interface DomainApi {
  listCustomers(filter?: { status?: "active" | "deactivated" }): Customer[];
  listTickets(customerId: number): Ticket[];
  listInvoices(customerId: number): Invoice[];
  transferTicket(ticketId: number, toCustomerId: number): void;
  transferInvoice(invoiceId: number, toCustomerId: number): void;
  voidInvoice(invoiceId: number, reason: string): void;
  deactivateCustomer(customerId: number, reason: string): void;
  writeAuditEvent(e: { action: string; entityType: "customer"; entityId: number; details: Record<string, unknown> }): void;
  now(): string;                                            // task.issued_at — deterministic
}
export function createDomainApi(db: Database, clock: () => string): DomainApi
// No raw SQL. No db handle. No delete capability anywhere in the API.

// interventions/types (lives in report.ts or domain-api.ts)
export type Intervention = (api: DomainApi, task: Task) => void;

// verifier.ts
export interface InvariantViolation { invariant: string; message: string; details?: unknown }
export function verify(initial: Snapshot, final: Snapshot): InvariantViolation[]

// report.ts
export function runEvaluation(cf: CaseFile, name: string, fn: Intervention): EvaluationReport
// EvaluationReport: { case_id, intervention, passed, violations: Violation[],
//   initial_digest, final_digest, checked_at }
```

### Audit event contract (what a correct merge writes)

- `action` = `"customer.dedup.merge"`, `entityType` = `"customer"`,
  `entityId` = the deactivated duplicate's id.
- `details` keys: `canonical_customer_id`, `deactivated_customer_id`,
  `transferred_ticket_ids` (sorted), `transferred_invoice_ids` (sorted),
  `voided_invoice_ids` (sorted), `reason` (string).
- One event per deactivated duplicate; `actor`/`created_at` stamped by the API.

## Verifier invariants (property-based; expectations derived from initial state)

| id | check |
|---|---|
| `single-active-canonical` | per duplicate pair in initial state: exactly one member stays active, and it is the earliest-created one |
| `tickets-preserved-attached` | every initial ticket still exists, unedited; pair members' tickets are attached to the canonical customer |
| `invoices-preserved-only-dup-voided` | every initial invoice still exists; only the non-surviving genuine-dup copies are `void`; the survivor and all legitimate invoices keep their status and sit on the canonical customer |
| `duplicate-deactivated-not-deleted` | non-canonical pair members exist with status `deactivated` |
| `accurate-audit-event` | one `customer.dedup.merge` event per deactivated duplicate; `canonical_customer_id` correct; id sets in details match what actually moved/voided |
| `unrelated-records-unchanged` | customers outside every duplicate pair, plus their tickets/invoices, are deep-equal to initial |
| `no-rows-deleted` | every (table, id) present initially is present finally; row counts only grow (audit_events) |

## Interventions

- `naiveIntervention` — the overfit shortcut. Groups active customers by **name**,
  keeps the **lowest id** as canonical, voids invoice number **"INV-5001"** on the
  losers, moves the losers' remaining tickets/invoices, deactivates, writes the
  audit event. Passes `original-incident`; fails `reordered-ids` (wrong
  canonical, unknown invoice number), `dup-owns-legitimate` (dup never voided),
  and `unrelated-lookalike` (eats the unrelated customer).
- `robustIntervention` — implements the business rules above from live state:
  group by normalized email, canonical by earliest `created_at`, detect
  duplicated invoices by number+amount within the pair, void only non-surviving
  copies, transfer the rest, deactivate, audit. Passes all four cases. No
  fixture constants.

## Expected demo matrix

```
case                    naive   robust
original-incident       PASS    PASS
reordered-ids           FAIL    PASS
dup-owns-legitimate     FAIL    PASS
unrelated-lookalike     FAIL    PASS
```

## Acceptance criteria

1. `pnpm install` works offline-of-extra-config (better-sqlite3 prebuilds;
   `package.json` sets `pnpm.onlyBuiltDependencies: ["better-sqlite3"]`).
2. `pnpm demo` prints the matrix above and exits 0.
3. `pnpm test` green: determinism/digest tests, known-pass + known-fail
   verifier tests, naive-passes-original/fails-counterfactuals test,
   robust-passes-all test, red-team cheat-rejection tests.
4. `pnpm typecheck` clean (`tsc --noEmit`, strict).
5. README (commands + story) and WALKTHROUGH (files in reading order) match the
   code.
