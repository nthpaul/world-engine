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
- Re-running `demo:agent` overwrites `episode-<index>.json` deterministically but does not clear
  stale higher-index files from an older, larger-k run; `audit-report` counts everything in
  `episodes/`. Operator clears the dir between runs, or the runner gains a clean step later.
- OpenAI temperature restriction (decision 1) — the openai driver works end to end with `gpt-4.1`;
  GPT-5.6 models need the Responses API or no custom temperature.

## Stage log

Stage 1 complete 2026-07-29 ~02:35 local: all 16 new files + 4 modified files delivered;
60/60 tests, clean typecheck, unchanged demo matrix, both smoke checks pass. Nothing committed.
