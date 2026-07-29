# Agent log: shannon

**Role:** test suite — `tests/reconstruct.test.ts`, `tests/verifier.test.ts`,
`tests/interventions.test.ts` for the failure-to-intervention prototype
**Completion status:** done

## Assignment

Write the Vitest suite per `PLAN.md` and the orchestrator's pinned coverage:
determinism/digest tests for `reconstruct`, known-pass + known-fail verifier
tests (one per broken behavior, asserting specific invariant ids), a
property-based spot check that `verify(initial, initial)` is not clean, and
naive-vs-robust intervention tests including the full 4x2 matrix, report-schema
validation, and intervention-independent `initial_digest`. Only write under
`tests/` plus this log. No commits.

## Decisions

- **Known-fail states are built from a hand-written correct merge, not from
  `robustIntervention`.** `buildMergedFinal()` in `verifier.test.ts` replays the
  correct moves for the original incident (void invoice 2, transfer ticket 1 to
  customer 1, deactivate customer 2) through `createDomainApi(db, () =>
  task.issued_at)`, minus the audit event. Each known-fail test then adds
  exactly one defect (raw SQL or one extra API call). A dedicated test
  ("the hand-built merge ... is itself clean under verify()") pins the helper as
  a second known-pass, so the known-fail tests don't silently depend on robust
  staying correct. Known-pass via `robustIntervention` is still covered
  separately through `runEvaluation` (test name says so).
- **Exact invariant-id sets, sorted, not just `.toContain`.** Every known-fail
  construction was traced through `verifier.ts` by hand to isolate the named
  invariant(s); asserting the exact set pins verifier behavior against both
  misses and surprise extra violations. Two intentional exceptions to
  single-id sets, both documented in comments at the assertion site:
  - (a) delete-the-duplicate asserts both `no-rows-deleted` and
    `duplicate-deactivated-not-deleted` (the assignment pairs them).
  - (e) wrong-canonical-kept asserts `single-active-canonical` AND
    `duplicate-deactivated-not-deleted`, because a still-active duplicate
    necessarily trips both. The construction deactivates canonical customer 1
    via the API and reactivates duplicate 2 via raw SQL after the correct
    moves, so the audit event stays accurate and no other invariant fires.
- **`db.pragma("foreign_keys = OFF")` is required to build the deleted-row
  state.** better-sqlite3 enforces FK constraints by default; the first test
  run failed with `SqliteError: FOREIGN KEY constraint failed` because voided
  invoice 2 still references customer 2. The environment physically blocks the
  naive delete — a nice property for the red team. The test lifts the pragma
  (tests may touch the db directly) and comments why.
- **Digest format pinned as `/^[0-9a-f]{64}$/`** wherever a digest is asserted.
- **`loadCases()` order pinned** (original-incident first, then alphabetical:
  dup-owns-legitimate, reordered-ids, unrelated-lookalike) since the matrix
  test and demo depend on it.
- `checked_at === task.issued_at` asserted for all 8 reports as an extra
  determinism check beyond the required schema/digest assertions.

## Evidence

- Read `PLAN.md`, `coordination/agents/orchestrator.md`,
  `coordination/agents/tesla.md`, `SWARM.md`, all of `src/`, and all four case
  JSON files before writing any test.
- `pnpm test` — exit 0. Exact summary:

```
 Test Files  3 passed (3)
      Tests  24 passed (24)
```

  (One intermediate failure during development: test (a) hit
  `SqliteError: FOREIGN KEY constraint failed` before the pragma fix above —
  a test bug, not a src bug.)
- `pnpm typecheck` — exit 0, no output beyond the script header (`tsc
  --noEmit`, strict).
- All known-fail exact-set assertions were verified against `src/verifier.ts`
  logic by hand before running; the suite confirmed every trace on the first
  green run.

## Files changed

### Created

- `prototypes/failure-to-intervention/tests/reconstruct.test.ts` (5 tests)
- `prototypes/failure-to-intervention/tests/verifier.test.ts` (10 tests)
- `prototypes/failure-to-intervention/tests/interventions.test.ts` (9 tests)
- `coordination/agents/shannon.md` (this file)

### Modified

- none

## Notes for hypatia (red team)

- My known-fail states all start from `buildMergedFinal()` (correct merge
  moves, no audit) plus one defect; red-team cheats will need different
  constructions (e.g. extra/unexpected audit events, id-set lies in `details`,
  do-nothing interventions, edits to pair-member rows) to avoid duplicating
  this approach.
- FK enforcement is ON in the reconstructed db; any delete-cheat needs
  `PRAGMA foreign_keys = OFF` first. The verifier itself doesn't need the
  pragma — it works on snapshots.
- `runEvaluation` never throws for intervention errors; it records invariant id
  `intervention-completed` instead. Assert on `report.passed`/`violations`.
- `verify(initial, initial)` is already proven non-clean for all four cases
  (each flags at least `single-active-canonical` + `accurate-audit-event`).

## Unresolved questions

- None. No suspected src bugs; every traced expectation matched the verifier's
  actual behavior.

## Completion status

done
