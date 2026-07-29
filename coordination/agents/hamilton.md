# Agent log: hamilton

**Role:** stage 1 builder for the agent rung (`PLAN-agent.md`) — the whole `src/agent/` source layer
**Completion status:** done

## Assignment

Implement the agent rung's source layer end to end in `prototypes/failure-to-intervention`:
`src/agent/` (config, prompt, plan-schema, five ProviderDrivers + lazy index, driver, classify,
runner, audit-report, demo-agent), `agent.config.json`, the async `runAsyncEvaluation` entry in
`report.ts` (sync path byte-identical), `package.json` script + deps, `.gitignore` episodes entry.
No tests (backus owns those), no docs (sagan owns those), no commit.

## Decisions

- **OpenAI default model is `gpt-4.1`, not the GPT-5.6 flagship.** The rig pins `temperature: 0`
  and the brief pins the openai driver on `chat.completions.create`. The GPT-5.6 reasoning family
  rejects any non-default temperature on chat completions (400 error; confirmed in OpenAI's July
  2026 docs and developer-community reports). A default that 400s on every call is not a sane
  default, so I pinned the newest temperature-compatible chat model. Flagged here so the
  orchestrator can revisit (e.g. switch the driver to the Responses API) if openai becomes the
  acceptance provider.
- **Cursor driver returns `usage: undefined`** per the pinned contract, with a code comment. Note:
  the installed `@cursor/sdk` 1.0.26 does declare an optional `usage` field on `RunResult`. I
  followed the brief; if the orchestrator wants cursor token accounting, the field is there to map.
- **Ollama driver maps `prompt_eval_count`/`eval_count` to usage** when present. The brief pinned
  only `message.content`; usage fields are optional in `CompletionUsage` and this makes audit token
  sums work for ollama. Noted as a small add, not a contradiction.
- **OpenRouter shares one implementation with OpenAI** (`createOpenAiCompatibleDriver` in
  `openai.ts`, baseURL + env key parameterized) instead of duplicating the driver.
- **Injected seams**: each factory takes `injected?` — `{ client?: Anthropic }`,
  `{ client?: OpenAI }`, `{ fetch?: typeof fetch }`, `{ prompt?: CursorPromptFn }`. When a fake is
  injected, no env key is required; without one, the factory throws naming the exact env var.
- **Error mapping** (both official SDKs share one taxonomy): connection timeout → `timeout`,
  connection failure → `network`, HTTP 429 → `rate-limit`, 401/403 → `auth`, anything else →
  `unknown`. Cursor maps its `AuthenticationError`/`RateLimitError`/`NetworkError` classes the same
  way; non-`finished` run status → `ProviderCallError("unknown")`.
- **JSON extraction rule** (documented in `driver.ts`): bare `JSON.parse` of the trimmed response,
  else exactly one fenced ```` ```json ````/```` ``` ```` block parsed; zero/multiple fences or an
  unparseable body → `malformed-output`.
- **Infrastructure retry**: runner retries the episode once; if still infrastructure it counts as
  `excluded` and leaves the pass-rate denominator. One transcript per episode index (final attempt).
- **`runAgentEpisode` never rethrows inside the evaluation closure** — provider errors and aborted
  plans still produce a normal `EvaluationReport` (untouched or partial state) for traceability,
  and `classifyEpisode` assigns the outcome by pinned precedence.
- **Transcript schema** lives in `runner.ts` (`TranscriptSchema`, zod) and `audit-report.ts` parses
  with it, so `audit-data.json` regenerates purely from `episodes/`.

## Evidence

Baseline before changes: `pnpm test` 60/60, `pnpm typecheck` clean, `pnpm demo` pinned matrix.

After implementation (exact outputs):

- `pnpm test` → `Test Files 4 passed (4)`, `Tests 60 passed (60)`.
- `pnpm typecheck` → clean, exit 0.
- `pnpm demo` → matrix unchanged (naive PASS only original-incident; robust PASS all four).
- `pnpm demo:agent` with no keys in env → stderr `demo:agent: anthropic provider requires
  ANTHROPIC_API_KEY in the environment`, exit 1, no stack spray. Same clean error for
  `PROVIDER=openai|openrouter|cursor` (each names its env var); `PROVIDER=bogus` →
  `unknown provider "bogus"; valid providers: anthropic, openai, openrouter, ollama, cursor`.
- Smoke harness (throwaway `/tmp` script, scripted fake provider, no network): k=10 × 4 cases wrote
  40 transcripts to the gitignored `episodes/`. Exercised every outcome: pass (correct merge plan),
  `malformed-output` (prose reply; schema-invalid method; >50 calls; wrong entityType literal; two
  fenced blocks), `invalid-action` (transfer to nonexistent customer aborts at call 0, partial log
  kept), `infrastructure` (scripted 429 → retried once → excluded, `passRate` computed over the
  remaining 9). Infrastructure transcript has `rawResponse: null` and untouched-state violations
  for traceability; pass transcript has 4/4 ok calls and zero violations.
- `tsx src/agent/audit-report.ts` → `wrote .../audit-data.json (40 episodes across 4 cases)` with
  per-case k/counts/passRate/excluded, token sums, and cost from the price table.
- `grep` over `episodes/` for `api_key|API_KEY|sk-|cursor_` → no matches.
- `git status`/`git diff`: zero changes to `src/verifier.ts`, `failure_trace.json`, `cases/`,
  `tests/`. `report.ts` diff is import additions + the appended async entry; `runEvaluation` body
  byte-identical.
- SDK surfaces verified against installed packages: `@anthropic-ai/sdk` 0.115.0 (`input_tokens` is
  `number | null` → mapped with `?? undefined`), `openai` 7.1.0 (`max_completion_tokens` current,
  `max_tokens` deprecated), `@cursor/sdk` 1.0.26 (`Agent.prompt(message, AgentOptions)` →
  `RunResult{status, result, error}`; error classes exported from package root).

## Files changed

### Created

- `prototypes/failure-to-intervention/src/agent/config.ts`
- `prototypes/failure-to-intervention/src/agent/prompt.ts`
- `prototypes/failure-to-intervention/src/agent/plan-schema.ts`
- `prototypes/failure-to-intervention/src/agent/providers/types.ts`
- `prototypes/failure-to-intervention/src/agent/providers/anthropic.ts`
- `prototypes/failure-to-intervention/src/agent/providers/openai.ts`
- `prototypes/failure-to-intervention/src/agent/providers/openrouter.ts`
- `prototypes/failure-to-intervention/src/agent/providers/ollama.ts`
- `prototypes/failure-to-intervention/src/agent/providers/cursor.ts`
- `prototypes/failure-to-intervention/src/agent/providers/index.ts`
- `prototypes/failure-to-intervention/src/agent/driver.ts`
- `prototypes/failure-to-intervention/src/agent/classify.ts`
- `prototypes/failure-to-intervention/src/agent/runner.ts`
- `prototypes/failure-to-intervention/src/agent/audit-report.ts`
- `prototypes/failure-to-intervention/src/agent/demo-agent.ts`
- `prototypes/failure-to-intervention/agent.config.json`

### Modified

- `prototypes/failure-to-intervention/src/report.ts` — added `AsyncIntervention` type +
  `runAsyncEvaluation`; `runEvaluation` byte-identical
- `prototypes/failure-to-intervention/package.json` — `"demo:agent"` script; deps via
  `pnpm add @anthropic-ai/sdk openai @cursor/sdk` (0.115.0 / 7.1.0 / 1.0.26)
- `prototypes/failure-to-intervention/pnpm-lock.yaml` — via pnpm add only
- `prototypes/failure-to-intervention/.gitignore` — added `episodes/`

### Left on disk, untracked, not mine to commit

- `prototypes/failure-to-intervention/episodes/` — sample smoke transcripts (gitignored)
- `prototypes/failure-to-intervention/audit-data.json` — generated from those sample episodes.
  **Not gitignored** (the brief pinned only the `episodes/` entry); orchestrator decides whether to
  ignore or commit it.

## Unresolved questions

- `audit-data.json` gitignore decision (above).
- Cursor `RunResult.usage` exists in 1.0.26 but is unmapped per the pinned contract — relax or keep?
- ~~Re-running `demo:agent` overwrites `episode-<index>.json` deterministically but does not clear
  stale higher-index files~~ — resolved by the follow-up (below): the runner now clears
  `episode-*.json` in the case dir before each run.
- OpenAI temperature restriction (decision 1) — the openai driver works end to end with `gpt-4.1`;
  GPT-5.6 models need the Responses API or no custom temperature.

## Stage log

Stage 1 complete 2026-07-29 ~02:35 local: all 16 new files + 4 modified files delivered;
60/60 tests, clean typecheck, unchanged demo matrix, both smoke checks pass. Nothing committed.

---

## Follow-up (2026-07-29 ~03:25 local): godel's three findings fixed

**Completion status:** done

### Assignment

Fix the three minor findings in `tests/agent-redteam.test.ts` (see `coordination/agents/godel.md`),
exactly to the orchestrator's pinned shape. Own only `src/agent/`; godel updates its own FINDING
tests; no commit.

### What changed

- **FIX 1 (retried infra attempts recorded)** — `runner.ts`: `AgentRunSummary` gains
  `infraRetries: number` = episodes whose first attempt was infrastructure but whose final outcome
  was not. `counts` stays final-outcome-only (sums to k); `excluded` stays = final infrastructure
  outcomes. `TranscriptSchema` gains `attempts: z.number().int().positive()` (1 or 2).
- **FIX 2 (infra error detail on disk)** — `driver.ts`: `EpisodeResult` gains
  `providerError: { kind: string; message: string } | null` (populated from the ProviderCallError;
  null unless outcome is infrastructure). `runner.ts`: transcript gains
  `infraErrors: [{ attempt, kind, message }]` — one entry per infrastructure ATTEMPT: double-failure
  records attempts 1 and 2; a recovered retry records attempt 1; empty array when no infra happened.
- **FIX 3 (stale transcripts)** — `runner.ts` `runAgentEvaluation`: when `episodesDir` is set,
  before the episode loop it mkdirs `<episodesDir>/<case_id>/` and deletes every file matching
  `/^episode-\d+\.json$/`. Same-k overwrites unchanged; smaller-k reruns no longer leak.
- **Propagation** — `audit-report.ts`: `CaseAudit` and `totals` gain `infraRetries` (sum of
  transcripts with attempts > 1 — note this counts ALL retried episodes including double-failures,
  per the pinned definition, so it can exceed the runner's recovered-only `infraRetries`) and
  `infraErrors: { file, kind, message }[]` flattened from transcripts. `demo-agent.ts`:
  classifications lines gain `, retried N` when `summary.infraRetries > 0`.
  *(Superseded 2026-07-29 ~03:55: the audit-side field is now named `retriedEpisodes` — see the
  second follow-up below.)*

### Decisions

- **TS narrowing workaround in `driver.ts`:** the provider error is assigned inside the
  `runAsyncEvaluation` closure; at the return statement TS narrows the `let` to `null` (closure
  assignments aren't tracked), so the error is held in a boxed `{ current }` with a code comment.
  No behavior change.
- **`writeTranscript` signature** gains an `EpisodeAttempts` param (`{ attempts, infraErrors }`)
  rather than stuffing retry data onto `EpisodeResult` — attempts are a runner-level concept the
  driver knows nothing about. Only `EpisodeResult.providerError` crosses the driver boundary, as
  pinned.

### Evidence

- `pnpm typecheck` → clean, exit 0.
- `pnpm test` → `Test Files 1 failed | 5 passed (6)`, `Tests 2 failed | 177 passed (179)`.
  The 2 failures are godel FINDING tests 1 and 2, which still assert the pre-fix shape
  (`counts.infrastructure === 1` after a recovered retry; a `providerError` field on the
  transcript). The pinned fix deliberately differs: counts stay final-only with the retry surfaced
  via `infraRetries`, and the transcript field is named `infraErrors`. Godel updates both tests.
  FINDING 3's existing assertion (`totals.k === 1` after a smaller-k rerun) already matches the fix
  and now PASSES — hence 177 passing, one more than the brief's expected 176.
- Manual smoke (throwaway `/tmp` script, scripted fake provider, tmp episodesDir, no network —
  deleted after):
  - 3-episode mix (flaky-once 429→pass, always-down timeout, clean pass): summary
    `{k:3, counts:{pass:2, infrastructure:1}, passRate:1, excluded:1, infraRetries:1}`.
  - Transcripts: episode-0 `outcome=pass attempts=2 infraErrors=[{attempt:1, rate-limit, 429}]`;
    episode-1 `outcome=infrastructure attempts=2 infraErrors=[attempt 1 + attempt 2 timeouts]`;
    episode-2 `attempts=1 infraErrors=[]`.
  - k=1 rerun into the same dir: only `episode-0.json` survives; `aggregateEpisodes().totals.k === 1`.
  - `aggregateEpisodes` on the 3-episode mix: `infraRetries: 2`, `infraErrors` flattened with file
    paths (3 entries across 2 files).
- Ownership check: `git status --porcelain` over the prototype shows modifications only under
  `src/agent/` plus the pre-existing untracked `tests/agent-redteam.test.ts` (godel's). Frozen
  files untouched; nothing committed.

### Files changed (follow-up)

- `src/agent/driver.ts` — `EpisodeResult.providerError`; boxed error for TS narrowing
- `src/agent/runner.ts` — `AgentRunSummary.infraRetries`, `EpisodeAttempts`, transcript
  `attempts`/`infraErrors`, stale-file cleanup, retry bookkeeping
- `src/agent/audit-report.ts` — `InfraErrorRecord`, bucket/CaseAudit/totals `infraRetries` +
  `infraErrors`
- `src/agent/demo-agent.ts` — `, retried N` in classifications

### Deviations

None from the pinned shape. One note for godel: its FINDING 1 test asserts
`counts.infrastructure === 1` for a recovered retry, which the pinned fix contradicts (counts stay
final-outcome-only); the recovered attempt is visible via `summary.infraRetries === 1` and the
transcript's `attempts: 2` + `infraErrors[0]`. FINDING 2's assertion should target
`transcript.infraErrors` (and `episode.providerError` at the driver level) rather than a
`transcript.providerError` field.

---

## Second follow-up (2026-07-29 ~03:55 local): audit-side field rename

**Completion status:** done, with one cross-file typecheck caveat (godel's update resolves it)

### Assignment

Poincare minor 2 (`coordination/agents/poincare.md`): the name `infraRetries` meant two different
numbers — runner-side (recovered episodes only) vs audit-side (all transcripts with
`attempts > 1`). Rename the AUDIT side only to `retriedEpisodes`, semantics unchanged. Do not
touch runner.ts, driver.ts, demo-agent.ts, or any test file.

### What changed

`src/agent/audit-report.ts` only, 6 lines: `infraRetries` → `retriedEpisodes` in `CaseAudit`,
`AuditData.totals`, the internal `Bucket` type, `emptyBucket`, the aggregation loop
(`if (t.attempts > 1) b.retriedEpisodes++`), and `summarize`. Value semantics identical;
`audit-data.json` now carries the field under the new name. Runner-side `infraRetries`
(`runner.ts`, read by `demo-agent.ts`) untouched by design.

### Evidence

- `git diff --stat`: `src/agent/audit-report.ts | 12 ++++++------ 1 file changed, 6 insertions(+),
  6 deletions(-)`. Nothing else in the prototype modified.
- `grep infraRetries src/` → only `runner.ts` (definition) and `demo-agent.ts` (read of the runner
  summary). Rename contained.
- `pnpm test` → `Test Files 1 failed | 5 passed (6)`, `Tests 1 failed | 178 passed (179)`. The one
  failure is exactly godel's audit-side pin
  (`agent-redteam.test.ts > audit-report (red-team edges) > "infraRetries and infraErrors
  aggregate for a mixed run..."`, first tripped at line 662 `expect(data.totals.infraRetries)`,
  also line 667 `toMatchObject({ infraRetries: 2 })`). Godel's runner-side assertions (lines 349,
  408, 656) all pass — the runner name is untouched.
- **Caveat — `pnpm typecheck` exits 1** with exactly one error, in godel's file:
  `tests/agent-redteam.test.ts(662,26): Property 'infraRetries' does not exist on type ...`.
  All `src/` code typechecks clean. The assignment pinned both "typecheck must pass" and "do not
  touch test files"; godel's stale typed property access makes both impossible at once until godel
  renames that access (662) and the `toMatchObject` key (667) to `retriedEpisodes`. Reported
  rather than worked around: any alias keeping the old name compiling would re-introduce the
  confusing field into `audit-data.json`, defeating the rename.

### Deviations / blockers

- Blocker (hand-off, not code): full-project typecheck stays red until godel updates its two
  audit-side assertions. Everything in my ownership is green.
