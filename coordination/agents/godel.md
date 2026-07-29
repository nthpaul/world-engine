# Agent log: godel

**Role:** stage 3 red-team for the agent rung (`PLAN-agent.md`) — parsing / classification / provider-selection edges
**Completion status:** done

## Assignment

Red-team the agent rung's plan-schema parsing, classification, and provider-selection edges;
pin findings as tests in a NEW file `prototypes/failure-to-intervention/tests/agent-redteam.test.ts`.
Own only that file plus this log; no src changes; no commits; no network (scripted fakes via the
injected seams only). Frozen: `src/verifier.ts`, `failure_trace.json`, `cases/`, all existing
test files. Probe families: (1) JSON extraction edges, (2) plan-schema edges, (3) classification
edges, (4) runner edges, (5) provider-selection edges, (6) audit-report edges, plus own additions.
Correct behavior → passing pin; wrong behavior → failing test marked FINDING with severity.

## Decisions

- **Verified predictions empirically before pinning.** Ran a throwaway tsx script (deleted after)
  through `extractPlanJson` and `PlanSchema` for every regex/Zod trace I intended to pin:
  uppercase ` ```JSON ` → 0-blocks error; trailing spaces / indented closing fence / CRLF / BOM →
  tolerated; duplicate keys → last-wins; nested fences → SyntaxError (one block, unparseable body);
  newline-``` inside a string → SyntaxError (body truncated); trailing comma → 0-blocks error;
  Zod v4 strips unknown keys at call AND plan level. No pin rests on a guess.
- **No overlap with backus.** His suite covers the happy paths, the unit-level classify matrix,
  retry/exclude counts, and factory-level missing-key errors. Mine adds: every extraction edge
  above, schema-vs-domain layer pins, end-to-end classification precedence with non-empty
  violations, transcript-on-disk behavior for infrastructure episodes, rerun/overwrite semantics,
  `PROVIDER` env override per name, `createProvider`-level no-fallthrough, `OLLAMA_HOST`
  normalization, and all `aggregateEpisodes` edges.
- **Three findings, all severity minor** (no blockers, no majors):
  1. **Retried infrastructure attempts vanish.** `runAgentEvaluation` reassigns `episode` on
     retry and keeps only the final attempt. A flaky-once episode records the 429 nowhere: not in
     `counts`, not in `episodes`, not in the transcript; attempt-1 token usage also vanishes from
     cost accounting. PLAN-agent says infrastructure is "retried once, then excluded and noted"
     and the AUDIT substance rules require infrastructure episodes "counted and described".
     "Noted" is honored only for the double-failure path. The failing test asserts
     `counts.infrastructure === 1` with `excluded === 0`, which also forces decoupling
     "infra attempts" from "excluded episodes" (today `excluded === counts.infrastructure`).
  2. **Excluded infrastructure episodes drop the error detail.** The transcript records
     `outcome: "infrastructure"` and `rawResponse: null` but the `ProviderCallError`'s kind and
     message appear in no transcript or `EpisodeResult` field. The audit cannot describe its
     excluded episodes (429 vs timeout vs driver bug) from on-disk evidence. Failing test asserts
     the transcript carries the provider error in some field.
  3. **Smaller-k reruns leave stale transcripts that audit-report counts.** The runner overwrites
     `episode-<index>.json` for the current k but never clears the case dir. k=2 then k=1 leaves
     a stale `episode-1.json`; `aggregateEpisodes` reports `totals.k === 2`. Mixed-k reruns
     silently corrupt the audit distributions AUDIT.md is authored from (hamilton flagged this as
     an unresolved question; I pin it as a defect). Failing test asserts `totals.k === 1` after
     the rerun. Severity minor rather than major only because a documented workaround exists
     (clear the dir manually); it becomes silent data corruption the moment anyone mixes k in one
     dir. Recommended fix: runner cleans stale `episode-*.json` in the case dir before writing.
- **Judged-correct behaviors pinned, not flagged:** extraction strictness for uppercase/non-json
  fence tags and trailing commas (the prompt forbids fences; the fence path is best-effort
  recovery, and the documented rule is "full-text parse, then exactly one fenced block");
  last-wins duplicate keys (standard `JSON.parse` semantics); schema accepting id 0 / negatives /
  empty reasons with the domain API and verifier as the rejecting layers (matches PLAN-agent's
  "Zod-validates shape, domain API enforces semantics" split); Zod stripping unknown keys;
  self-transfer executing cleanly with the verifier as backstop; plain-`Error` throws classified
  infrastructure via kind `"unknown"` (noted in-test that this can mask driver bugs); audit-report
  failing LOUD on a malformed transcript (a skip would corrupt distributions); `costUsd` null for
  unpriced models vs defined 0 for priced models with missing usage; deterministic transcript
  overwrite on same-k reruns; malformed `agent.config.json` throwing a raw `SyntaxError` (noted:
  no file-path context, could be friendlier).

## Evidence

- Read: PLAN-agent.md, SWARM.md, coordination/agents/{archimedes,hamilton,backus}.md, all 8
  `src/agent/` files + 7 `src/agent/providers/` files, `src/report.ts`, `src/domain-api.ts`,
  `src/verifier.ts`, `agent.config.json`, `tests/agent.test.ts`, `failure_trace.json`,
  `src/schemas.ts`, `src/cases.ts`.
- Baseline before writing: `pnpm test` → 118/118, `pnpm typecheck` clean.
- Empirical trace script (created, run, deleted — never in the repo): output quoted in Decisions.
- Final: `pnpm test` → **176 passed / 3 failed (179 total)**; the 3 failures are exactly the
  three FINDING tests, each failing for the pinned reason (`counts.infrastructure` 0 vs 1;
  `transcript.providerError` undefined; `totals.k` 2 vs 1). `pnpm typecheck` → clean, exit 0.
- Frozen check: `git status --porcelain` over the prototype shows only
  `?? tests/agent-redteam.test.ts`; `git diff --stat` over `src/verifier.ts`,
  `failure_trace.json`, `cases/`, `tests/agent.test.ts` is empty. Nothing committed. The
  scratch script was removed; no other files touched.
- No network: every episode ran through hand-rolled `ProviderDriver` objects; provider-selection
  tests stub env vars (`vi.stubEnv`) and never call `complete()` on real SDK paths; the ollama
  URL pin used an injected fake `fetch`.

## Files changed

### Created

- `prototypes/failure-to-intervention/tests/agent-redteam.test.ts` (61 tests across 6 describes:
  58 passing pins + 3 failing findings)
- `coordination/agents/godel.md` (this file)

## Unresolved questions

- ~~Finding 1 forces a design decision for whoever fixes it~~ — resolved by the follow-up
  (below): counts stay final-outcome-only; attempts surface via `infraRetries` and the
  transcript's `attempts`/`infraErrors`.
- ~~Finding 3's fix interacts with operators accumulating episodes in one dir~~ — resolved by the
  follow-up: the runner cleans `episode-*.json` in the case dir before each run; flagged for the
  README/AUDIT author.

## Probe-family coverage map (for the orchestrator's report)

1. JSON extraction: uppercase/non-json tags, fence-line trailing spaces, indented closing fence,
   CRLF, BOM, prose before+after one fence, empty/whitespace, JSON primitives, duplicate keys,
   ``` inside string values (mid-line and newline variants), nested fences, trailing comma.
2. Plan schema: id 0/negative layer pin (schema accepts, domain API rejects), empty-string
   reasons, nested/unicode details, extra-key stripping, empty calls array → business-violation,
   self-transfer and double-void absurd plans.
3. Classification: abort at index 0, wrong-action audit event (business-violation not
   invalid-action), plain-Error provider throw → infrastructure, schema-invalid + verifier
   violations → malformed-output precedence end to end.
4. Runner: k=1, retry-trace pin + FINDING 1, double-infra counts/excluded/transcript + FINDING 2,
   same-k overwrite pin, smaller-k stale-tail FINDING 3.
5. Provider selection: `PROVIDER` override ×5 with model resolution, case-sensitivity and empty
   string, missing `providers` entry error, malformed JSON config, `createProvider` missing-key
   no-fallthrough ×4, `OLLAMA_HOST` trailing-slash normalization + default URL.
6. audit-report: missing usage (unpriced → null cost; priced → defined 0), exact cost math,
   malformed transcript fails loud, non-episode files and root-level strays ignored.

---

## Follow-up (2026-07-29 ~03:35 local): FINDING tests converted after hamilton's fixes

**Completion status:** done

### Assignment

Hamilton fixed all three findings in `src/agent/` to the orchestrator's pinned shape (see its
log follow-up). Convert my two remaining FINDING tests from failing findings into permanent
passing assertions of the fixed behavior (drop the FINDING marker, keep the intent), pin the new
audit fields, and pin the runner-vs-audit `infraRetries` naming difference. Own only
`tests/agent-redteam.test.ts`; no src; no commit. Suite must be 100% green.

### What changed in my test file

- **FINDING 1 → renamed passing test** ("infrastructure-then-success: the retry is recorded via
  infraRetries and transcript attempts/infraErrors; counts stay final"). Absorbed the now-stale
  "leaves no trace" pin (its final-only assertions folded in). Asserts `infraRetries === 1`,
  `counts.infrastructure === 0`, `excluded === 0`, `passRate === 1`, episodes array final-only,
  `episodes[0].providerError === null`, and the transcript's `attempts: 2` +
  `infraErrors: [{attempt: 1, kind: "rate-limit", message: "HTTP 429"}]`. The WHY comment
  (PLAN-agent "noted" + audit substance rule 5) now describes what the code does. The pinned fix
  deliberately differs from my original failing assertion (`counts.infrastructure === 1`): counts
  stay final-outcome-only and the attempt is surfaced via `infraRetries` — a better design, since
  it leaves the pass-rate denominator math untouched.
- **FINDING 2 → renamed passing test** ("an excluded infrastructure episode records both
  attempts' kind and message (transcript and audit)"). Double-failure with DISTINCT errors per
  attempt proves both are recorded: transcript `infraErrors` carries attempt 1 (`network`) and
  attempt 2 (`timeout`); `episodes[0].providerError` carries the final attempt's `{kind,
  message}` at driver level; `aggregateEpisodes` flattens both with file paths into
  totals/cases. Also pins `infraRetries === 0` for a double-failure (excluded, not recovered).
- **FINDING 3 → renamed, assertion unchanged** ("a smaller-k rerun leaves no stale
  transcripts..."). Hamilton's runner-side clean step makes the original `totals.k === 1`
  assertion pass; I dropped the stale FINDING marker/defect comment and added a dir-listing
  assertion (`["episode-0.json"]` survives).
- **New audit test**: scripted mix (recovered 429→pass + double-failure timeouts + clean pass)
  pins `infraRetries` and `infraErrors` on `CaseAudit`/totals — runner `infraRetries === 1`
  (recovered only) vs audit `infraRetries === 2` (all transcripts with `attempts > 1`, including
  the double-failure), `infraErrors` flattened to 3 entries with per-file paths. The naming
  difference is pinned in a comment so the AUDIT author is not surprised by two different
  numbers for the same run.
- File header comment updated: no FINDING markers remain; the three converted tests are
  permanent assertions of the fixed behavior.

### Evidence

- `pnpm test` → `Test Files 6 passed (6)`, `Tests 179 passed (179)`. 100% green.
- `pnpm typecheck` → clean, exit 0.
- Count reconciliation: my file holds 61 tests (118 + 61 = 179): the new audit-mix test (+1)
  offsets merging the stale "leaves no trace" pin into the renamed retry test (−1).
- `git status --porcelain` over the prototype: `src/agent/` modifications are hamilton's; my
  only artifact is `tests/agent-redteam.test.ts` (untracked). `git diff --stat` over
  `src/verifier.ts`, `failure_trace.json`, `cases/`, `tests/agent.test.ts` is empty. Nothing
  committed.

### Deviations

- Finding 3's rename was not in the brief's itemized list (the brief said it "already passes as
  written"), but leaving a passing test named "FINDING(minor)" asserting the opposite of its
  title would mislead every future reader; renamed with the assertion kept identical.

### Unresolved questions

- None.

---

## Follow-up 2 (2026-07-29 ~03:55 local): audit-side field renamed `infraRetries` → `retriedEpisodes`

**Completion status:** done

### Assignment

Per poincare's minor 2, hamilton renamed the AUDIT-side field in `audit-report.ts`
(semantics unchanged: count of transcripts with `attempts > 1`); the runner-side `infraRetries`
(recovered episodes) keeps its name. Update my test file: audit-side assertions use
`retriedEpisodes`, runner-side stays `infraRetries`, and the naming-difference comment is
rewritten for the resolved naming. Own only the test file + log; no commit.

### What changed in my test file

- `data.totals.infraRetries` → `data.totals.retriedEpisodes` (asserts 2).
- `data.cases[0]` matchObject `{ infraRetries: 2 }` → `{ retriedEpisodes: 2 }`.
- Mixed-run test retitled ("infraRetries, retriedEpisodes, and infraErrors aggregate for a
  mixed run...") and its comment rewritten: no longer "same field name, two definitions" but
  distinct names for distinct definitions — runner `infraRetries` = recovered episodes only;
  audit `retriedEpisodes` = every transcript with `attempts > 1` (includes double-failures).
  Same run, two numbers: 1 vs 2.
- Runner-side assertions (`summary.infraRetries` at the retry, double-failure, and mixed-run
  tests) untouched by design.

### Evidence

- `pnpm test` → `Test Files 6 passed (6)`, `Tests 179 passed (179)`. Fully green.
- `pnpm typecheck` → clean, exit 0.
- `git status --porcelain` over the prototype: my modification is `tests/agent-redteam.test.ts`
  only (the file itself was committed by the orchestrator in 7211a72; these edits are
  uncommitted per the no-commit rule). `src/agent/audit-report.ts` is hamilton's rename;
  `WALKTHROUGH.md` is sagan's. `git diff --stat` over the frozen paths is empty.

### Deviations

- None.

### Unresolved questions

- None.
