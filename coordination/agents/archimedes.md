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

### Stage 2 — `backus` tests ∥ `sagan` docs (verified, committed)

Backus wrote `tests/agent.test.ts`: 58 tests, 10 describes, all pinned areas covered
(plan-schema, extractPlanJson, abort-on-invalid, classify matrix + precedence, runner
with fake driver incl. retry-once/exclude/fresh-reconstruct/transcript-hygiene, all five
provider factories with mocked transports incl. error mapping, missing-key errors naming
env vars, createProvider, runAsyncEvaluation, prompt leakage). Sagan updated README
(agent-rung section, demo:agent, limits rescoped, More list) and WALKTHROUGH (all new
files in reading order, count-free tests phrasing).

Orchestrator verification: `pnpm test` 118/118 (60 + 58), `pnpm typecheck` clean,
`pnpm demo` unchanged; frozen files untouched (existing tests unmodified — only the new
file added). Independent mutation check: swapped classify precedence (malformed vs
invalid-action) → exactly 1 test failed (the precedence pin); reverted → 58/58 green.
Read the README diff in full and the test-file structure; WALKTHROUGH section list
checked against the real tree.

### Stage 3 — `godel` red-teams agent edges; fixes by `hamilton` (verified, committed)

Godel probed six assigned families plus its own additions (BOM, trailing commas, nested
fences, duplicate keys, OLLAMA_HOST slashes, cost math): 61 tests in
`tests/agent-redteam.test.ts`, 58 passing pins + 3 failing findings, all minor, no
blockers/majors. Orchestrator confirmed the three failures match their pinned reasons
before dispatching fixes. Findings and fixes (hamilton, pinned shape):
1. Retried infrastructure attempts vanished — runner gains `infraRetries` (recovered
   episodes), transcripts gain `attempts` and per-attempt `infraErrors`; counts stay
   final-outcome-only.
2. Excluded infra episodes dropped error detail — transcripts now carry kind+message per
   attempt; `EpisodeResult.providerError`; audit-report flattens `infraErrors` with file
   paths (satisfies AUDIT substance rule 5: counted AND described).
3. Smaller-k reruns left stale transcripts — runner cleans `episode-*.json` in the case
   dir before writing.
Godel then converted all three findings to permanent passing assertions and pinned the
runner-vs-audit `infraRetries` naming difference (recovered-only vs all retried
transcripts) in a comment for the AUDIT author.

Orchestrator verification: `pnpm test` 179/179, `pnpm typecheck` clean, `pnpm demo`
matrix unchanged, diff confined to the four src/agent fix files + the new red-team file;
frozen files zero-diff.

### Stage 4 — `poincare` independent read-only review (verified, committed)

Poincare reviewed the integrated delta (d210be9..HEAD): no blockers, no majors, verdict
"ready for the live run". Per-criterion verdicts: 1 met, 2 met, 3 ready (all non-live
paths exercised), 4 met, 5 mostly met, 6 on track, 7 met in spirit. Two minors fixed
forward:
1. WALKTHROUGH tests/ section predated the red-team suite — `sagan` added the
   `agent-redteam.test.ts` bullet.
2. `infraRetries` name collision (runner = recovered episodes; audit = all retried
   transcripts) — `hamilton` renamed the audit side to `retriedEpisodes` before AUDIT.md
   could inherit the confusion; `godel` updated its pins.
Poincare's notes, dispositioned: runbook omits the lowest-id canonical tie-break (no seed
has tied created_at — accepted, noted); prompt template sequential .replace would collide
with literal {{...}} in a future case (frozen seeds clean — accepted); acceptance 7's
"createProvider instantiates each with a mocked transport" is split between factory-level
mocks and construction-only dummy keys (accepted — spirit met; only openrouter's baseURL
construction path is untested, noted); retried infra attempts lose no OBSERVABLE usage
since a failed complete() throws (correction to godel's framing, accepted); PLAN-agent's
stale "local/Ollama drivers" line under "not this rung" — fixed by me as plan owner.
audit-data.json gitignore question settled: NOT gitignored; it is a deliverable committed
after the live run, regenerable from episodes/.

Orchestrator verification (final gate): `pnpm test` 179/179, `pnpm typecheck` clean,
`pnpm demo` matrix unchanged, `pnpm demo:agent` with no key exits 1 with the clear
provider error; frozen files zero-diff across the entire build (d210be9..HEAD).
