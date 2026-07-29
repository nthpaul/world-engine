# Agent log: ramanujan

**Role:** independent read-only reviewer of the integrated failure-to-intervention diff
**Completion status:** done

## Assignment

Review the integrated diff `bd5da40..HEAD` for the prototype at
`prototypes/failure-to-intervention/`, against PLAN.md's contract. I wrote none
of this code. Check, in priority order: (A) scope compliance, (B) correctness of
the core overfit-vs-robust claim, (C) determinism, (D) domain-API confinement,
(E) docs accuracy, (F) test quality. Run the test/demo/typecheck commands. Write
only this log; change nothing else.

## Decisions

- Reviewed by reading every source file, case file, test file, and doc in full,
  then re-running the three acceptance commands myself rather than trusting the
  agent logs.
- Traced the verifier's pair/dup-invoice derivation by hand against all four
  seeds, and traced naive and robust line by line on each case, instead of
  sampling.
- Treated the review brief's scope boundary ("nothing outside `prototypes/` and
  `coordination/agents/`") as a literal claim to verify, then checked the
  exceptions against SWARM.md ownership rules before calling them problems.

## Evidence

Commands I ran myself (all in `prototypes/failure-to-intervention`):

- `pnpm test` — exit 0, `Test Files 4 passed (4)`, `Tests 60 passed (60)`.
- `pnpm demo` — exit 0. Matrix matches README's quoted block exactly
  (row order: original-incident, dup-owns-legitimate, reordered-ids,
  unrelated-lookalike). Violation lines match hypatia's pinned exact sets.
- `pnpm typecheck` — exit 0, no output.

Per-area findings:

**A. Scope.** Grepped `src/` for web/UI/MCP/auth/deploy/container/model-call/RL
surfaces — zero hits. Dependencies are better-sqlite3 + zod only; dev deps are
tsx/typescript/vitest/@types. `pnpm.onlyBuiltDependencies` set per PLAN.
Commits in range do NOT touch `docs/DESIGN.md` or root `README.md` (both are
modified only in the uncommitted working tree — pre-existing planning-phase
changes, acknowledged in orchestrator's log and D-0003). One boundary note:
the range `bd5da40..HEAD` also creates three files outside the stated boundary
— root `.gitignore` (47630c5, hygiene), `coordination/CHANGELOG.md` and
`coordination/DECISIONS.md` (28dc22c, 729 lines of planning-phase synthesis
committed alongside PLAN.md). All three are steward/orchestrator-owned per
SWARM.md rule 3, so this is a reporting nuance, not scope creep. No forbidden
item anywhere.

**B. Core claim — holds.**
- Verifier derives everything from the initial snapshot: `derivePairs(initial)`
  (verifier.ts:20-66) groups active customers by trim+lowercase email, picks
  canonical by `created_at` then lowest id, computes non-surviving dup copies
  from initial invoices. No fixture ids anywhere in verifier.ts.
- Naive's pass on original-incident is legitimate: on that seed its three
  shortcuts (name grouping, lowest id, "INV-5001") all happen to be correct, so
  it performs the state-correct merge. The checks are not vacuous —
  `verify(initial, initial)` fails all four cases (verifier.test.ts:162-171),
  and every individual defect trips its named invariant (verifier.test.ts:77-144).
- Robust (robust.ts) contains no fixture constants — only the audit action
  string and reason text, both contract vocabulary from PLAN.md, plus
  state-derived logic.
- Demo matrix equals PLAN's pinned matrix; naive's three counterfactual
  failures fire for the pinned right reasons (redteam.test.ts:670-700).

**C. Determinism — holds.** No `Date.now`/`new Date`/`Math.random`/timers/env
anywhere in src or tests. `checked_at` = `task.issued_at` (report.ts:40).
Digest is sha256 over canonical JSON with sorted keys (db.ts:92-107); snapshots
are `ORDER BY id`; inserts are sorted by id; case order is filename-sorted.
Byte-identical reports across repeated runs are pinned by redteam meta tests.
One theoretical nit: `localeCompare` on ISO timestamps (verifier.ts:34,54;
robust.ts:22,41) is locale-dependent in principle; code-unit compare would be
bulletproof. Risk is near-zero for same-format ISO-8601 UTC strings.

**D. Confinement — holds.** The evaluated db is a local in `runEvaluation`
(report.ts:11); it flows only into `createDomainApi` closures and `snapshot`.
No module exports the instance. API-returned rows are plain objects, not live
handles. An intervention importing `reconstruct` could only build its own
unrelated in-memory db. Red-team confirms all API-reachable cheats are caught;
the only surviving gaps (created_at backdating, homoglyph seeds) are
raw-SQL-only or seed-side and are documented in code and tests.

**E. Docs.** README's quoted demo output is byte-accurate; case table,
intervention descriptions, and limits section all match the code. WALKTHROUGH
is accurate per file with one stale line: the `tests/` section says "The
directory is not present yet at the time of writing, so `pnpm test` finds no
test files until that work lands" (WALKTHROUGH.md:129-131) — false since
605f3b1; 60 tests exist. That violates PLAN acceptance criterion 5 (docs match
code).

**F. Tests.** 60 tests (reconstruct 5, verifier 10, interventions 9, redteam
36). Assertions pin exact sorted invariant-id sets, not loose matchers; all
tests are synchronous (no missing-await risk); the `[]`-asserting tests
(11d, 17a-ii, 18d) sit alongside non-empty pins on the same seeds, so the
suite is not tautological. The matrix test compares against PLAN's pinned
matrix, an external expectation.

## Files changed

### Created

- `coordination/agents/ramanujan.md` (this file)

### Modified

- none

## Unresolved questions

- For orchestrator/tesla: swap the four `localeCompare` timestamp comparisons
  for code-unit comparison? (Determinism hygiene, not a live bug.)
- For orchestrator: `runEvaluation` calls `fn(api, task)` synchronously and the
  `Intervention` type (`(api, task) => void`) silently accepts an async
  function. Post-await work would go unjudged (fails the run, so no false
  pass) and would likely crash the process with an unhandled rejection after
  `db.close()`. Worth one line in PLAN or an `await Promise.resolve(fn(...))`
  hardening — or leave as out-of-contract.
- The three out-of-boundary files in the commit range (see Evidence A) — fine
  under SWARM.md, but the orchestrator should know the review brief's literal
  boundary claim does not hold.

## Completion status

done
