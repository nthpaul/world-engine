# Agent log: archimedes

**Role:** build orchestrator for the agent rung (`PLAN-agent.md`) of the failure-to-intervention prototype
**Completion status:** in_progress

## Assignment

User-directed build (2026-07-29): implement `prototypes/failure-to-intervention/PLAN-agent.md`
end to end — `src/agent/` (config, prompt, plan-schema, five ProviderDrivers, driver,
classify, runner, audit-report, demo-agent), `agent.config.json`, `tests/agent.test.ts`,
`PREDICTIONS.md`, README/WALKTHROUGH updates, `pnpm demo:agent`. Coordinate subagents
(Auto model only, one bounded assignment each); personally verify, commit incrementally
by explicit path, and push. Live run + AUDIT.md only if `ANTHROPIC_API_KEY` is present.

## Decisions

- Roster (fresh names; tesla/shannon/lamarr/hypatia/ramanujan/steward/einstein taken):
  - `hamilton` — stage 1: all of `src/agent/`, `agent.config.json`, the async entry in
    `report.ts`, `package.json` script + deps, `.gitignore` episodes entry
  - `backus` — stage 2a: `tests/agent.test.ts`
  - `sagan` — stage 2b: README agent-rung section + WALKTHROUGH new files
  - `godel` — stage 3: red-team plan-schema parsing / classification / provider-selection edges
  - `poincare` — stage 4: independent read-only review of the integrated diff
- I write `PREDICTIONS.md` myself (pre-registration is a plan-level artifact, like PLAN.md
  was in round one) and commit it before anything else, so git history proves it precedes
  any live run.
- Environment check (2026-07-29 ~02:05 local): no `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
  `OPENROUTER_API_KEY`, `CURSOR_API_KEY`, or `PROVIDER` in the orchestrator shell. Unless a
  key appears, this build delivers everything up to the live-run gate plus exact run
  instructions. No AUDIT.md without data.
- SDK availability verified on npm: `@anthropic-ai/sdk` 0.115.0, `openai` 7.1.0,
  `@cursor/sdk` 1.0.26 all installable. Ollama = plain fetch, OpenRouter = OpenAI-compatible
  endpoint; no extra deps. Expectation: all five drivers fully implemented, none isolated —
  unless a driver proves unverifiable, in which case it is isolated behind the interface and
  flagged per PLAN-agent.
- Design pins for stage 1 (so tests and docs converge):
  - `ProviderDriver.complete(req) -> Promise<{text, usage?}>`; each driver constructor takes
    an optional injected client/transport so tests fake it without network or SDKs.
  - `createProvider(config)` is async and lazy-imports the selected driver module only;
    unknown provider name or missing env key = clear thrown error, never silent fallthrough.
  - Plan JSON shape: `{ "calls": [...] }`, Zod discriminated union on `method`, max 50 calls.
  - JSON extraction: full-text parse, then single fenced-block parse; anything else is
    `malformed-output`. Documented, deterministic, testable.
  - Classification precedence: infrastructure (retry once, excluded) < malformed-output <
    invalid-action (abort rest, partial recorded) < business-violation < pass.
  - Cursor driver uses `Agent.prompt` one-shot (`local: { cwd: <empty temp dir> }`) so the
    agentic runtime has nothing to act on; usage may be absent; caveat flagged in docs.
- Frozen-adjacent: `report.ts` gains an async entry but the sync `runEvaluation` path and
  its thenable guard stay byte-stable.

## Evidence

- Read PLAN-agent.md, PLAN.md, SWARM.md, orchestrator.md (round-one log), all of src/,
  one test file, README, WALKTHROUGH, failure_trace.json, .gitignore.
- Baseline before any delegation: `pnpm test` 60/60 green, `pnpm typecheck` clean,
  `pnpm demo` prints the pinned matrix (naive PASS only original-incident; robust PASS all).
- Branch `master`, remote `origin` = github.com/nthpaul/world-engine.git.
- node v22.23.1, pnpm 10.33.0.
- Untracked pre-existing items that must never be staged: docs/DESIGN.md deletion;
  ARCHITECTURE.md, RESEARCH.md, ROADMAP.md, SWARM.md; coordination/agents/{bohr,curie,
  darwin,einstein,faraday,feynman,galileo,hopper,lovelace,maxwell,noether,pasteur,steward,
  turing}.md; coordination/proposals/; experiments/.

## Files changed

### Created

- `coordination/agents/archimedes.md` (this file)

## Unresolved questions

- None.

## Stage log

### Stage 0 — pre-registration (commit ff3250c)

Wrote `PREDICTIONS.md` (per-case predicted outcomes + failure-mode ranking, reasoned
from case designs) and committed it with this log BEFORE any build, so git history
proves it predates the first live run.

### Stage 1 — `hamilton` implements `src/agent/` (verified, committed)

Hamilton delivered all 16 files + surgical edits (`report.ts` async entry, package.json
script+deps, `.gitignore` episodes/). Its log: coordination/agents/hamilton.md.
Deviations it flagged, all accepted: openai default `gpt-4.1` (GPT-5.x reasoning models
reject temperature 0); cursor usage stays undefined though @cursor/sdk 1.0.26 declares
optional RunResult.usage; ollama maps prompt_eval/eval counts to usage; openrouter
reuses the openai factory with baseURL override.

Orchestrator verification (not trusting claims): `pnpm test` 60/60, `pnpm typecheck`
clean, `pnpm demo` matrix unchanged; `git diff` shows ZERO changes to verifier.ts /
failure_trace.json / cases/ / tests/; `runEvaluation` body byte-identical in the diff.
Read all 15 new source files + agent.config.json myself. Personally spot-checked abort
semantics with a scripted fake provider (no network): invalid call at index 1 aborts
the rest (`invalid-action`, executedCalls=1), a correct full-merge plan passes with
zero violations. Deleted hamilton's smoke-run `audit-data.json` and `episodes/` —
fake data must never be committed.
