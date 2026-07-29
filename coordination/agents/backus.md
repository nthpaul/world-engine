# Agent log: backus

**Role:** stage 2a test author for the agent rung (`PLAN-agent.md`) — `tests/agent.test.ts`
**Completion status:** done

## Assignment

Write `prototypes/failure-to-intervention/tests/agent.test.ts`, the full test suite for the
agent rung: plan-schema, extractPlanJson, abort-on-invalid, classification matrix, the runner
via a fake driver (retry, exclusion, fresh reconstruction, transcripts, no-key-leak), provider
selection and all five driver factories behind mocked transports, `runAsyncEvaluation`, and the
prompt contract/leakage check. Own only that file. No network in tests, ever — every provider
test uses hamilton's injected seams (`{ client }` / `{ fetch }` / `{ prompt }`). Do not commit.
Frozen: `src/verifier.ts`, `failure_trace.json`, `cases/`, the four existing test files.

## Decisions

- Env-var hygiene via `vi.stubEnv(name, undefined)` (deletes) + one file-level
  `afterEach(() => vi.unstubAllEnvs())` — verified against the installed vitest 4.1.10 that
  `stubEnv(name, undefined)` deletes and restores. Missing-key factory tests are therefore
  environment-independent.
- SDK-style errors are constructed from the real classes (`new APIError(429, undefined, msg,
  undefined)` from `@anthropic-ai/sdk` / `openai`), because both drivers dispatch on
  `instanceof APIError` + `err.status`. Constructor shapes checked against the installed
  `core/error.d.ts` and `core/error.js` of both SDKs; both tolerate undefined error/headers.
- Fake clients are double-cast (`as unknown as Anthropic` / `as unknown as OpenAI`,
  `as unknown as typeof fetch`); cursor fakes are typed against the exported `CursorPromptFn`
  with literal `RunResult` objects (`{ id, status: "finished", result }`).
- The `createProvider(...)` per-name test stubs dummy keys for all four keyed providers so the
  SDK-constructing factories build real client objects — construction makes no network call;
  `complete()` is never invoked there. Ollama needs nothing (only reads `OLLAMA_HOST`).
- Fresh-reconstruction check compares `initial_digest`/`final_digest` across two episodes of
  the same scripted correct plan, on top of both outcomes being `pass`.
- Transcript key-leak check stubs all four key env vars with distinct dummies and greps every
  written transcript file for each value (the pin named ANTHROPIC_API_KEY; the other three cost
  one loop iteration).
- Abort test additionally asserts `single-active-canonical` in the episode violations — state-
  level proof that the post-abort `deactivateCustomer` never ran, not just log-level proof.
- Kept the leakage check to exactly the pinned words ("verifier", "invariant") rather than
  adding "expected", per the orchestrator's keep-it-simple pin.

## Evidence

- Read PLAN-agent.md, SWARM.md (repo root), coordination/agents/{archimedes,hamilton}.md, all
  15 `src/agent/` files + providers/, `src/report.ts`, `agent.config.json`, all four existing
  tests, `failure_trace.json`, domain-api/schemas/cases/task/robust for fixtures and style.
- Baseline before writing: `pnpm test` → `Test Files 4 passed (4)`, `Tests 60 passed (60)`;
  `pnpm typecheck` exit 0.
- After writing `tests/agent.test.ts` (58 new tests, first run green):
  - `pnpm test` → `Test Files 5 passed (5)`, `Tests 118 passed (118)`.
  - `pnpm typecheck` → exit 0, no output.
- Mutation sanity check on my own suite: changed the classifyEpisode "clean + zero violations"
  expectation from `"pass"` to `"infrastructure"` → `Tests 1 failed | 117 passed (118)`
  (`Test Files 1 failed | 4 passed (5)`). Reverted → `Tests 118 passed (118)`. Suite detects a
  one-string mutation.
- Frozen check: `git diff --stat` over `src/verifier.ts`, `failure_trace.json`, `cases/`, and
  the four existing test files → empty. `git status --porcelain -- tests/ src/` shows only
  `?? prototypes/failure-to-intervention/tests/agent.test.ts`. Nothing committed.
- No network: every provider factory test injects hamilton's seams; SDK packages are imported
  (for `APIError`) but never called; the ollama default-`fetch` path is never exercised
  (injected fake everywhere `complete()` runs).

## Files changed

### Created

- `prototypes/failure-to-intervention/tests/agent.test.ts` (58 tests across 10 describes)
- `coordination/agents/backus.md` (this file)

## Unresolved questions

- None.

## Coverage map (assignment pins → tests)

1. plan-schema — valid 5-method plan parses; 9 wrong/missing-arg cases via it.each; unknown
   method; non-"customer" entityType; >50 rejected / 50 accepted; non-integer ids.
2. extractPlanJson — bare JSON; ```json fence; bare fence; prose-only throws; two fences throw;
   non-plan JSON fails PlanSchema.
3. abort-on-invalid — mid-plan transfer to customer 999 → `invalid-action`, executedCalls 1,
   failed call logged, index-2 call absent, dup still active in violations.
4. classifyEpisode — 5-way matrix + 2 precedence checks.
5. runner — k=3 pass-rate 1; retry-once (flaky → counted as pass, complete() called 2×);
   always-down (excluded === k, passRate null, 2 calls per episode); digest-level fresh
   reconstruction; transcripts written/schema-valid/fields asserted/no key material.
6. providers — text+usage mapping for anthropic/openai/openrouter/ollama/cursor; 429→rate-limit
   for both SDK drivers; ollama TypeError→network and HTTP 500→ProviderCallError; cursor
   error-status→ProviderCallError; missing-key errors naming the exact env var (all four);
   createProvider resolves all five names with matching `.name`; unknown provider via
   loadAgentConfig lists the five valid names.
7. runAsyncEvaluation — correct async merge passes clean; mid-way throw →
   intervention-completed violation + passed false.
8. prompt check — runbook ("normalized email", "created_at") + state JSON present; "verifier"
   and "invariant" absent.
