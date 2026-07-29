# Agent log: sagan

**Role:** stage 2b docs owner for the agent rung (`PLAN-agent.md`) — README + WALKTHROUGH only
**Completion status:** done

## Assignment

Update the two docs for the agent rung in `prototypes/failure-to-intervention`:
README.md (new "The agent rung" section, `Run it` additions for `pnpm demo:agent`,
Limits rephrase, More list additions) and WALKTHROUGH.md (PLAN-agent.md, PREDICTIONS.md,
agent.config.json, all of `src/agent/` in reading order, episodes/ + audit-data.json note,
tests/ and package.json section updates). Own only those two files. No commits.

## Decisions

- Placement of new WALKTHROUGH sections: `PLAN-agent.md`, `PREDICTIONS.md`, and
  `agent.config.json` go right after the `PLAN.md` section (contracts and knobs up top,
  matching the assignment's listed order). The `src/agent/` code sections go after
  `src/demo.ts`, because they build on concepts the round-one sections introduce
  (`runAsyncEvaluation`, the domain API, the verifier). The episodes/ + audit-data.json
  note closes that block, before tests/.
- The five provider drivers got one combined section, headed
  `src/agent/providers/{anthropic,openai,openrouter,ollama,cursor}.ts`, per the brief.
- Did not touch the `src/report.ts` section; `runAsyncEvaluation` is described inside the
  `src/agent/driver.ts` section instead (the brief's section list did not include a
  report.ts edit).
- tests/ intro rephrased count-free ("Green under `pnpm test`; nothing in the suite
  touches the network.") and the `agent.test.ts` (backus) bullet describes the coverage
  from the assignment brief. The file was not on disk at write time (backus is stage 2a,
  concurrent), so that bullet is the one claim I could not verify against the real file.
  The count-free phrasing means nothing in the section breaks when it lands.
- AUDIT.md is mentioned in README's More list as plain text, not a link, with "it does
  not exist until then" — it is the post-live-run deliverable, not a current file.
- Said nothing about audit-data.json's gitignore status (hamilton flagged it as an open
  orchestrator decision). Only claimed episodes/ is gitignored, which is true.
- Fixed the stale `.gitignore` parenthetical in the package.json section
  ("just node_modules/" → "`node_modules/` and `episodes/`") since that line became
  false when the episodes entry landed.

## Evidence

Read before writing: PLAN-agent.md, SWARM.md, coordination/agents/archimedes.md,
coordination/agents/hamilton.md, README.md and WALKTHROUGH.md in full, all 15 files
under `src/agent/` (including providers/), `agent.config.json`, `PREDICTIONS.md`,
`package.json`, `.gitignore`, and `src/report.ts`.

Verified against the repo:

- `pnpm test` → 4 files, 60/60 green; `pnpm typecheck` → clean (exit 0), run at
  2026-07-29 ~02:47 local after the docs edits were planned.
- `demo:agent` script exists (`tsx src/agent/demo-agent.ts`); K = 10; matrix header
  prints naive/robust/agent columns; classification counts, token + cost totals, and
  the three falsification rules print with results; the closing line points at
  `tsx src/agent/audit-report.ts`.
- `agent.config.json`: provider `anthropic`, per-provider model pins, temperature 0,
  max_tokens 8192; `PROVIDER` env override is in `config.ts`.
- Env-key names checked in each driver: ANTHROPIC_API_KEY, OPENAI_API_KEY,
  OPENROUTER_API_KEY, CURSOR_API_KEY; ollama needs none (OLLAMA_HOST optional).
- `.gitignore` contains `episodes/`; `episodes/` and `audit-data.json` are not on disk
  (orchestrator deleted the smoke-run fakes).
- "Under $1" spend expectation comes from PLAN-agent.md acceptance criteria.

Could not verify: `tests/agent.test.ts` contents (not yet on disk); the `pnpm demo:agent`
live output (no API keys in the environment, per archimedes's environment check).

## Files changed

### Modified

- `prototypes/failure-to-intervention/README.md`
- `prototypes/failure-to-intervention/WALKTHROUGH.md`

### Created

- `coordination/agents/sagan.md` (this file)

## Unresolved questions

- None blocking. The `agent.test.ts` bullet should be re-checked against backus's real
  file once it lands; the wording tracks the assignment brief, not the file.

## Follow-up (2026-07-29 ~03:55 local)

**Assignment:** fix poincare's minor finding 1 — add the missing `tests/agent-redteam.test.ts`
(godel) bullet to WALKTHROUGH.md's tests/ section; verify the rest of the section against
reality. Own only WALKTHROUGH.md; no commit.

**Done:**

- Read `coordination/agents/poincare.md` and `tests/agent-redteam.test.ts` in full, then
  added the bullet after `agent.test.ts`, matching the existing bullets' style and
  count-free phrasing. Every clause checked against the real file: extraction strictness
  (fence variants, nested fences, BOM, duplicate keys), schema-vs-domain layering,
  classification edges (abort at call 0, wrong-action audit event, plain-Error provider
  throw), runner edges (`infraRetries`/`attempts`/`infraErrors`, stale-transcript cleanup),
  provider-selection errors, audit-report aggregation (flattened infra errors with file
  paths, cost math).
- Verified the rest of the section: six test files on disk (reconstruct, verifier,
  interventions, redteam, agent, agent-redteam). The `agent.test.ts` bullet was also
  independently confirmed accurate by poincare. Intro stays count-free.
- The audit-side rename (poincare finding 2, `infraRetries` → `retriedEpisodes` in
  `src/agent/audit-report.ts`) does not touch any WALKTHROUGH wording: my runner and
  audit-report sections name no audit-side field, and the new bullet's runner clause
  uses runner-side names, which are unchanged.

**Heads-up for the orchestrator (not mine to fix):** `pnpm test` is currently
**178/179** — `tests/agent-redteam.test.ts:662` still asserts `data.totals.infraRetries`
(and `:667` per-case) after the audit-side rename to `retriedEpisodes` landed in
`src/agent/audit-report.ts`. Presumably mid-fix; I left src/ and tests/ untouched per my
bounds. The "Green under `pnpm test`" intro line stands as the acceptance statement and
will be true again once the stale assertion is updated.

**Files changed:** `prototypes/failure-to-intervention/WALKTHROUGH.md` (one bullet added);
this log.

**Status:** done.
