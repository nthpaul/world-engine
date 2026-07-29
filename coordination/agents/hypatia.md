# Agent log: hypatia

**Role:** adversarial red team for the hidden state-based verifier,
`prototypes/failure-to-intervention/tests/redteam.test.ts`
**Completion status:** done

## Assignment

Try to make the verifier PASS a final state that violates the business intent,
or otherwise prove the evaluation can be gamed. Own exactly
`tests/redteam.test.ts` (no src/, other tests, cases, or docs). At least 8
distinct cheats, each asserted REJECTED with named invariant ids; genuine holes
pinned with `test.fails` + "VERIFIER HOLE" comments so the suite stays green.
Also verify determinism under repetition and that naive's counterfactual
failures fire for the right reasons. `pnpm test` and `pnpm typecheck` must
exit 0. Document holes here with severity + fix direction; do not patch them.

## Decisions

- **Every cheat runs through `createDomainApi` + optional raw SQL, then
  `verify(initial, final)`**, asserting exact sorted invariant-id sets (shannon's
  convention). Raw SQL is test-only power; where a hole needs it, the finding
  says whether a real DomainApi intervention could reach it.
- **18 cheat families, 30 cheat tests** (plus 2 determinism + 3
  naive-failure-reason tests = 35 in the file). 11 families fully rejected;
  2 hole classes confirmed (7 `test.fails` pins); 1 informational blind spot.
- **Holes were double-confirmed out-of-band**: each `test.fails` construction
  was re-run in a throwaway tsx probe asserting `verify()` returns exactly `[]`,
  so the `test.fails` pins fail for the right reason (the hole), not a test bug.
- **Cheat 15 attribution nuance**: rows stolen FROM a pair member and dropped on
  an unrelated customer are caught by the pair invariants
  (`tickets-preserved-attached` / `invoices-preserved-only-dup-voided`), not by
  `unrelated-records-unchanged`, because that check partitions rows by INITIAL
  owner. Still rejected — comment left at the test.

### Verifier holes found (severity + fix direction)

**H1 — Pair-member CUSTOMER row content is never checked.**
`single-active-canonical` and `duplicate-deactivated-not-deleted` check only
`status`; `unrelated-records-unchanged` skips pair members. So a merge that is
otherwise perfect can rename the canonical customer (10a), rename the
deactivated duplicate (10b), rewrite the duplicate's email to hide that
duplication ever existed (10c), or backdate the canonical's `created_at` (10d)
— all score a clean pass. Pair tickets and invoices ARE fully field-diffed, so
this is an asymmetric guard, not a design stance.
*Severity:* **Medium as shipped** — the DomainApi has no update-customer method,
so no compliant intervention can reach it; but it is the largest verifier gap,
and becomes **High** the moment the API grows any customer-edit capability or
the verifier is reused against a wider surface. A merge that corrupts the
surviving customer's identity is exactly what "merge, don't rewrite history"
forbids.
*Fix direction:* field-diff pair-member customers the way invoices are diffed:
`changedFields(initial, final, ["status"])` for duplicates and a full diff for
the canonical (a correct merge touches the canonical's customer row not at all).

**H2 — Audit-trail integrity is only checked for merge-event
action/entity/details.**
- H2a (17a): after a correct API merge, rewriting the merge event's `actor` to
  "operator-admin" and backdating `created_at` via raw SQL passes clean. The
  API stamps both fields, so no compliant intervention can reach this.
  *Severity:* **Low** — but note the original incident WAS an audit-trail
  failure; if "accurate audit event" is meant to cover who/when, the check is
  under-scoped. *Fix:* assert `actor` is the API-stamped value and `created_at`
  equals the task clock (or at least >= the latest initial event).
- H2b (17b): an extra audit event with any non-`customer.dedup.merge` action
  and arbitrary false details (e.g. "INV-4000 refunded in full") is added
  unexamined — `accurate-audit-event` filters on the exact action string and
  `no-rows-deleted` allows audit growth. **Reachable through the DomainApi**
  (`action` is a free string). A bad merge still fails the merge invariants,
  so no false pass for overfit merges, but a passing intervention can fabricate
  side-history undetected. *Severity:* **Low-Medium.** *Fix:* policy for new
  non-merge events — schema-validate known actions or forbid unknown ones.
- H2c (17c): pre-existing audit events are never content-diffed
  (`no-rows-deleted` checks id presence only), so historical audit rows can be
  rewritten. No shipped seed has audit events, so latent. *Severity:* **Low
  (latent).** *Fix:* deep-equality check on initial audit events, same as
  unrelated customers get.

**Informational blind spot (not a scored hole):** normalization is
trim+lowercase only. A seed with a Cyrillic homoglyph email (`аda@example.com`,
U+0430) derives NO duplicate pair, so `verify()` is vacuously clean on the
untouched state (18d). An intervention can't weaponize this (it can't edit
emails, and any merge-like action between the homoglyph records trips
`unrelated-records-unchanged`, 18e), but it's a seed-integrity caveat for the
eval's counterfactual claims. *Fix (optional):* NFKC/confusable-skeleton
normalization in `derivePairs`, or a seed linter.

### What held up (strong properties worth keeping)

- The verifier recomputes expected audit id sets from ACTUAL initial->final
  state changes, so do-nothing/partial-merge cheats with perfectly forged
  `details` (01-03, 07) are caught — the strongest anti-overfit property.
- Audit count, duplicate events per dup, unexpected events, and near-miss
  action strings (04-06) all caught.
- Void semantics airtight: void-is-not-transfer (12), over-voiding (13),
  survivor status flip with a fully accurate audit event (14) — proving
  accurate claims cannot rescue a bad state.
- Wrong-target merge (15), swap-style new active row via INSERT (16), edits to
  pair tickets/invoices (08-09) all caught.
- Deactivate-first ordering is (correctly) irrelevant: pairs derive from the
  initial snapshot and only final state is judged (11d, clean pass).
- A pre-deactivated same-email record in the seed is treated as out of scope
  and creates no cheat surface (11a); the API physically blocks transfers to
  deactivated customers (11b); SQL reactivation is caught (11c).
- Case/whitespace email variants are treated as duplicates both ways (18a-c).
- Determinism: `runEvaluation(robust)` x2 on all four cases yields
  byte-identical reports (digests included).
- Naive fails for the right reasons, exact sets pinned: reordered-ids →
  {accurate-audit-event, duplicate-deactivated-not-deleted,
  invoices-preserved-only-dup-voided, single-active-canonical,
  tickets-preserved-attached}; dup-owns-legitimate →
  {invoices-preserved-only-dup-voided}; unrelated-lookalike →
  {accurate-audit-event, unrelated-records-unchanged}.

## Evidence

- Read `PLAN.md`, all of `src/`, all four case JSONs, shannon's and tesla's
  logs, `SWARM.md` before writing anything.
- `pnpm test` — exit 0:
```
 Test Files  4 passed (4)
      Tests  52 passed | 7 expected fail (59)
```
- `pnpm typecheck` — exit 0, no output beyond the script header.
- Out-of-band tsx probe (deleted after use): all 7 `test.fails` constructions
  (10a-d, 17a-c) confirmed to return EXACTLY zero violations from `verify()`.
- One intermediate red run during development: cheat 15 initially expected
  `unrelated-records-unchanged` to fire; actual behavior attributes stolen
  pair-member rows to the pair invariants (see Decisions). Test bug, not src
  bug; fixed by tracing `verifier.ts` lines 129-135 vs 331-345.

## Files changed

### Created

- `prototypes/failure-to-intervention/tests/redteam.test.ts` (35 tests)
- `coordination/agents/hypatia.md` (this file)

### Modified

- none

## Unresolved questions

- **H1 (Medium; High if the API grows customer editing):** pair-member customer
  name/email/created_at unchecked — fix by field-diffing pair-member customers
  (ignore `status` for dups, full diff for canonical). Owner: tesla/orchestrator.
- **H2a/H2b/H2c (Low to Low-Medium):** merge-event actor/created_at unchecked;
  non-merge audit events unexamined; initial audit events not content-diffed.
  Needs a policy decision on what "accurate audit event" covers beyond
  action/entity/details.
- **Homoglyph normalization blind spot (informational):** worth a one-line note
  in README/WALKTHROUGH if the eval's counterfactual claims rely on
  trim+lowercase being sufficient.

## Completion status

done

## Follow-up: hole closure (2026-07-29, after tesla's verifier patch)

### Decisions

- Tesla patched `src/verifier.ts` with all four fixes. I read the patch and
  verified each closure EMPIRICALLY (throwaway tsx probe, deleted after use)
  before converting, per the orchestrator's instruction not to assume:
  - H1: `single-active-canonical` fully field-diffs the canonical;
    `duplicate-deactivated-not-deleted` field-diffs dups ignoring only `status`.
    10a/10d -> 1 violation each (`single-active-canonical`); 10b/10c -> 1 each
    (`duplicate-deactivated-not-deleted`).
  - H2a: merge events must have `actor === "intervention"`. 17a -> 1 violation
    (`accurate-audit-event`). **`created_at` stays unchecked** — tesla's code
    comment: `verify()` receives no task clock, so no expected value is
    derivable from state. Honest split: 17a asserts the actor rewrite is
    caught; new informational test 17a-ii documents that created_at-only
    backdating via raw SQL still passes (reachable only via raw SQL; the API
    stamps created_at, so no compliant intervention can exploit it).
  - H2b: any new non-`customer.dedup.merge` event is flagged. 17b -> 1
    violation (`accurate-audit-event`).
  - H2c: pre-existing audit events are deep-equal diffed. 17c -> 1 violation
    (`accurate-audit-event`).
- All 7 `test.fails` pins converted to normal `it()` tests with exact
  invariant-id sets + message substring assertions (same style as the rest of
  the file); "VERIFIER HOLE" comments replaced with one-line "Closed by ..."
  notes. The unused `test` import was dropped (strict typecheck).
- No remaining holes found: every converted cheat is now rejected, and the
  baseline run before converting showed the other 52 tests (shannon's
  included) unaffected by the patch.

### Evidence

- Baseline `pnpm test` post-patch, pre-conversion: 7 failed (all "Expect test
  to fail" on my pins — i.e. every cheat now caught), 52 passed.
- Probe output (exact violations per construction) matched the assertions
  written; e.g. `17a -> [accurate-audit-event] audit event 1: actor should be
  "intervention" but is "operator-admin"`, `17a created_at ONLY -> 0 violations`.
- Final `pnpm test` — exit 0:
```
 Test Files  4 passed (4)
      Tests  60 passed (60)
```
  Zero failed, zero expected-fail.
- Final `pnpm typecheck` — exit 0, no output beyond the script header.

### Files changed

- Modified `prototypes/failure-to-intervention/tests/redteam.test.ts`
  (7 conversions + 1 new informational test, 17a-ii; 36 tests in file now)
- Modified `coordination/agents/hypatia.md` (this section)

### Unresolved questions

- Only the documented `created_at` limitation remains (17a-ii): merge-event
  timestamps are unchecked because `verify()` gets no task clock. If the eval
  ever wants timestamp honesty, the fix is passing `task.issued_at` (or a
  clock bound) into `verify()` and asserting `created_at` against it. Low
  severity: raw-SQL-only reachability.

### Completion status

done
