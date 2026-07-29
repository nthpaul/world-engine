# Agent log: tesla

**Role:** implementation — entire prototype core at `prototypes/failure-to-intervention/`
**Completion status:** done (initial build + verifier-hardening follow-up)

## Assignment

Implement the whole prototype core per `PLAN.md`: `package.json`, `tsconfig.json`,
`.gitignore`, the four case files (`failure_trace.json` + `cases/*.json`), and all of
`src/` (schemas, db, cases, task, domain-api, verifier, report, naive + robust
interventions, demo). Typecheck clean, `pnpm demo` matrix matching PLAN, no tests,
no README/WALKTHROUGH, no commits.

## Decisions

- **`runEvaluation` catches intervention throws.** PLAN does not say what happens
  when an intervention throws. I catch the error and record it as a violation with
  invariant id `intervention-completed` (one extra id beyond the seven), then still
  snapshot and run `verify`. Result: a cheating or broken intervention produces a
  failing report instead of crashing the run. This should make hypatia's red-team
  tests easier to write. `passed` is still `violations.length === 0`.
- **`checked_at` = `task.issued_at`.** Keeps reports fully deterministic: same seed
  + same intervention => identical report, byte for byte. Digests verified stable
  across repeated runs (see Evidence).
- **"Active" invoice means `status !== "void"`** (open or paid), for both the
  genuine-dup detection and the "transfer remaining active invoices" rule. All
  four seeds only exercise open copies, so this reading is safe; noted in case
  shannon wants to pin it differently.
- **Domain API guards beyond PLAN's minimum:** `deactivateCustomer` throws on an
  already-deactivated customer; transfers and deactivation validate existence;
  transfer targets must be active; `voidInvoice` refuses already-void rows (pinned).
  No delete, no raw SQL, no db handle anywhere in the API. `voidInvoice`/`deactivateCustomer`
  accept a `reason` param but the tables have no reason column — callers record it
  in the audit event details (one comment in the code says this).
- **Audit event rows are stamped by the API** (`actor: "intervention"`,
  `created_at` from the injected clock), so interventions cannot fake them; the
  verifier therefore checks only `action`, `entity_type`, `entity_id`, and
  `details` contents, which is where an intervention can actually go wrong.
- **Verifier derives everything from the initial snapshot only:** duplicate pairs
  (normalized email, active customers), canonical (earliest `created_at`, tie ->
  lowest id), genuine-dup copies (same number+amount_cents, 2+ active copies in the
  pair; survivor = canonical's copy else earliest-issued). For `accurate-audit-event`,
  the expected id sets are what actually moved/voided between initial and final, so
  an event that accurately describes a wrong merge still fails the other invariants.
  Initially-void invoices must stay byte-identical in place (not in any seed, but
  the property is enforced).
- **Case seeds:** case 2 gives the newer record (id 11) email `Ada@example.com`
  vs the canonical's `ada@example.com`, so robust's normalization is actually
  exercised; names stay exactly equal so naive still attempts the merge (and picks
  the wrong canonical). Case 4 has exactly three customers (the pair + the
  lookalike, no Grace) per the assignment's "the Ada pair as in case 1, PLUS a
  third customer also named Ada Byron"; her INV-5001 is the same 12000 cents as
  the pair's, maximum bait.
- **Dependencies:** installed via `pnpm add` so versions are real: better-sqlite3
  13.0.2 (node-gyp compiled from source, Xcode CLT present — no prebuilt
  download, but install worked; node:sqlite fallback NOT needed), zod 4.4.3,
  typescript 7.0.2, tsx 4.23.1, vitest 4.1.10, @types/node 26.1.2,
  @types/better-sqlite3 7.6.13. Corepack added a `packageManager: pnpm@10.33.0`
  field to package.json on first install; left in place, it matches the pinned
  toolchain.

## Evidence

- `pnpm install` — clean; better-sqlite3 native build ran under the
  `onlyBuiltDependencies` allowance (gyp compiled against node 22.23.1 headers).
- `pnpm typecheck` — clean, exit 0, no output beyond the script header.
- `pnpm demo` — exit 0. Exact output:

```
case                    naive   robust
original-incident       PASS    PASS
dup-owns-legitimate     FAIL    PASS
reordered-ids           FAIL    PASS
unrelated-lookalike     FAIL    PASS

violations:
- dup-owns-legitimate x naive | invoices-preserved-only-dup-voided: invoice 2 (INV-8100) is a duplicated copy and should be void but is open
- dup-owns-legitimate x naive | invoices-preserved-only-dup-voided: invoice 2 (INV-8100) is a duplicated copy and must stay on customer 2 (void is not transfer) but is on customer 1
- reordered-ids x naive | single-active-canonical: pair ada@example.com: canonical customer 27 is not active (status: deactivated)
- reordered-ids x naive | single-active-canonical: pair ada@example.com: duplicate customer 11 is still active
- reordered-ids x naive | tickets-preserved-attached: ticket 5 should be attached to canonical customer 27 but is on customer 11
- reordered-ids x naive | invoices-preserved-only-dup-voided: invoice 10 (INV-9001) should sit on canonical customer 27 but is on customer 11
- reordered-ids x naive | invoices-preserved-only-dup-voided: invoice 12 (INV-9001) is a duplicated copy and should be void but is open
- reordered-ids x naive | invoices-preserved-only-dup-voided: invoice 13 (INV-8700) should sit on canonical customer 27 but is on customer 11
- reordered-ids x naive | duplicate-deactivated-not-deleted: duplicate customer 11 should be deactivated but is active
- reordered-ids x naive | accurate-audit-event: no customer.dedup.merge audit event for deactivated customer 11
- reordered-ids x naive | accurate-audit-event: unexpected customer.dedup.merge audit event 1 for customer 27
- unrelated-lookalike x naive | accurate-audit-event: expected 1 customer.dedup.merge audit event(s) but found 2
- unrelated-lookalike x naive | accurate-audit-event: unexpected customer.dedup.merge audit event 2 for customer 3
- unrelated-lookalike x naive | unrelated-records-unchanged: unrelated customer 3 changed (status: "active" -> "deactivated")
- unrelated-lookalike x naive | unrelated-records-unchanged: unrelated ticket 2 changed (customer_id: 3 -> 1)
- unrelated-lookalike x naive | unrelated-records-unchanged: unrelated invoice 4 changed (status: "open" -> "void")

legend: naive is the overfit shortcut — expected to PASS original-incident and FAIL every counterfactual; robust is expected to PASS all four.
```

- Determinism smoke check (two `runEvaluation` calls on the same case): digests
  identical across runs. Case 1 initial digest
  `b45318a778378fadeffb94b7cc09267e43c892ac78e8119ce1215b26c68d5e5a`,
  final digest after robust
  `ee8beb91badcf93c7b3cf31a7cfb81118f02a163393d8b35ae7864d09b76b342`.
- Throwing-intervention smoke check: report `passed: false`, violations start with
  `intervention-completed`, followed by the untouched-state invariant violations.

## Files changed

### Created (all under `prototypes/failure-to-intervention/` unless noted)

- `package.json`, `tsconfig.json`, `.gitignore`
- `failure_trace.json`
- `cases/reordered-ids.json`, `cases/dup-owns-legitimate.json`, `cases/unrelated-lookalike.json`
- `src/schemas.ts`, `src/db.ts`, `src/cases.ts`, `src/task.ts`, `src/domain-api.ts`,
  `src/verifier.ts`, `src/report.ts`, `src/interventions/naive.ts`,
  `src/interventions/robust.ts`, `src/demo.ts`
- `coordination/agents/tesla.md` (this file)

### Modified

- none (package.json `dependencies`/`devDependencies`/`packageManager` fields were
  filled by `pnpm add`/corepack in place)

## Notes for shannon (tests) and hypatia (red team)

- Violation shape: `{ invariant, message, details? }`. Messages are plain sentences
  with concrete ids (see demo output above for live examples). `details` is only
  set for audit-event id-set mismatches: `{ expected: number[], actual: unknown }`.
- The seven invariant ids fire exactly as pinned. One extra id exists:
  `intervention-completed`, only when the intervention throws inside `runEvaluation`.
- Known-fail construction is easy through the public surface: build a `Snapshot`
  by running `reconstruct(seed)` + `snapshot(db)`, mutate rows in plain JS (or run
  a bad intervention through `createDomainApi(db, () => task.issued_at)`), then call
  `verify(initial, final)`. For a known-pass, run `robustIntervention` on any case.
- `runEvaluation(cf, name, fn)` never throws for intervention errors; assert on
  `report.passed` / `report.violations` instead of expecting exceptions.
- Report is validated with `ReportSchema.parse` before return; `checked_at` is
  deterministic (`task.issued_at`), so full-report equality assertions are stable.
- `loadCases()` order: `failure_trace.json` first, then `cases/*.json` sorted by
  filename: `dup-owns-legitimate`, `reordered-ids`, `unrelated-lookalike`. This is
  the order the demo prints in (see Unresolved questions).
- `Intervention` type is exported from `src/domain-api.ts` and re-exported from
  `src/report.ts`.

## Unresolved questions

- **Demo row order vs PLAN's printed matrix.** PLAN's `loadCases` contract says
  "failure_trace.json first, then cases/*.json sorted" (alphabetical), and my
  assignment says the demo iterates `loadCases()`. PLAN's printed matrix lists
  rows in story order (reordered-ids before dup-owns-legitimate), which is not
  alphabetical. I followed the pinned `loadCases` contract, so the demo prints
  `dup-owns-legitimate` second. Every PASS/FAIL cell matches PLAN exactly. If the
  orchestrator wants the literal printed order from PLAN's matrix block, the fix
  is one line (sort key in `loadCases` or a display-order in `demo.ts`) — flagging
  rather than guessing, since the file names are pinned.

## Completion status

done

---

## Follow-up: verifier hardening (2026-07-29)

### Assignment

Orchestrator follow-up: hypatia's red team confirmed 11 cheat families caught but
found 4 holes (H1, H2a, H2b, H2c). Patch ONLY `src/verifier.ts`; hypatia converts
her 7 `test.fails` hole tests afterward.

### Decisions

- **H1 — pair-member customer rows now content-checked.** Canonical customer: no
  field may change at all; violations land under `single-active-canonical` with
  messages like `canonical customer 1 was edited (name: "Ada" -> "Eve")`. Each
  duplicate: only `status` may change (`changedFields` ignore list `["status"]`);
  violations land under `duplicate-deactivated-not-deleted`. Missing rows skip the
  diff (already flagged by the existing missing-row violation). Blocks rename /
  email-rewrite / created_at-backdating cheats.
- **H2a — merge-event `actor` must be `"intervention"`** (the fixed value the
  domain API stamps; a system property, not a fixture constant). Violation under
  `accurate-audit-event`: `audit event N: actor should be "intervention" but is "..."`.
  `created_at` stays unchecked, documented in a code comment: `verify()` receives
  no task clock, so the expected value cannot be derived from state — known
  limitation.
- **H2b — new audit events with any action other than `customer.dedup.merge` are
  flagged** under `accurate-audit-event`: `unexpected audit event N with action "..."`.
  Same pass that already flags unexpected merge events.
- **H2c — pre-existing audit events are diffed.** Every initial event must exist in
  final, deep-equal via `changedFields`. Violations under `accurate-audit-event`:
  `pre-existing audit event N changed (...)` or `pre-existing audit event N is
  missing in final state` (the missing case overlaps `no-rows-deleted`
  deliberately, consistent with existing overlap style).
- Placement verified against shannon's exact-`invariantIds` assertions before
  patching: her length-1 and exact-set tests all construct states where the new
  checks stay silent, so nothing green flipped.

### Evidence

- `pnpm typecheck` — clean, exit 0.
- `pnpm test` — exit 1 with exactly the 7 expected flips failing and everything
  else green. Summary line: `Test Files  1 failed | 3 passed (4)` /
  `Tests  7 failed | 52 passed (59)`. The 7 failures are precisely hypatia's hole
  tests (10a, 10b, 10c, 10d, 17a, 17b, 17c), each failing with `Error: Expect test
  to fail` — i.e. the cheats are now caught, so the `test.fails` expectation
  inverted. All 52 other tests pass, including shannon's 24.
- `pnpm demo` — matrix unchanged: original-incident naive PASS, all other naive
  cells FAIL, all robust cells PASS.

### Files changed

- Modified `prototypes/failure-to-intervention/src/verifier.ts` (only)
- Modified `coordination/agents/tesla.md` (this note)

### Unresolved questions

- Same as before (demo row order vs PLAN's printed matrix), unchanged.
- Known limitation now explicit in code: merge-event `created_at` is not verified
  (no clock available to `verify()`). If the orchestrator wants it checked,
  `verify` would need the task or an expected timestamp passed in — a signature
  change, so flagged rather than done.

### Completion status

done
