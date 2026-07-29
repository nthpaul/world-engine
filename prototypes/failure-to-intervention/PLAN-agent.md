# PLAN-agent — putting a real agent in the intervention slot

Extends `PLAN.md` (which stays the binding contract for everything already built).
Goal: replace the hand-written intervention with a real model acting through the
same constrained domain API, and learn whether the rig judges it fairly.

Decisions locked with the user (2026-07-29):

- **Model:** Claude API, exact snapshot pinned in config. `ANTHROPIC_API_KEY`
  from the environment; never logged, never committed.
- **Interaction:** single-shot plan. One model call per episode. Multi-turn is a
  later rung, not this one.
- **Gate:** this plan is signed off before any build.

Non-negotiables carried from round one: the verifier, the four case seeds, and
`failure_trace.json` are **frozen** — agent work adds files, it does not edit
these. The goalposts do not move. No MCP, no UI, no deployment, no RL.

## The episode shape (single-shot)

One episode = one model call:

1. Build the prompt: task text + the current state (customers, tickets,
   invoices as JSON, read through the domain API's list methods) + the business
   runbook + the output schema.
2. The model returns one JSON **plan**: an ordered array of API calls.
3. The harness Zod-validates every call, then executes them in order through
   the real domain API. First invalid call aborts the rest (partial execution
   is recorded).
4. Snapshot, verify, classify, write the transcript.

Read methods (`listCustomers` etc.) are never plan actions — their data is
already in the prompt. Plan actions are exactly: `transferTicket`,
`transferInvoice`, `voidInvoice`, `deactivateCustomer`, `writeAuditEvent`.
Max 50 calls per plan.

## The prompt is the experiment (calibration rules)

The prompt must state the *contract* without leaking *answers*:

- IN: business runbook — canonical = earliest `created_at` among same normalized
  email; genuinely duplicated invoice = same number + amount within the pair;
  void is not transfer; deactivate, never delete; the exact audit-event schema
  (action, entity, details keys).
- IN: current state JSON and the plan output schema.
- OUT: which records are duplicates, which invoice is the dup, any ids as
  "expected", anything about the verifier or its invariants.

Draft prompt skeleton is part of sign-off; it lives in `src/agent/prompt.ts`
as a template with named slots.

## Files (new only)

```
src/agent/
  config.ts        — loads agent.config.json (model snapshot, temperature 0, max_tokens)
  prompt.ts        — runbook + state + schema template, and its renderer
  plan-schema.ts   — Zod schema for the plan JSON (method union + per-method args)
  driver.ts        — AgentDriver: builds prompt, calls Claude, parses plan, executes via API
  classify.ts      — episode outcome taxonomy (below)
  runner.ts        — runAgentEvaluation(caseFile, k): fresh reconstruct per episode,
                     k episodes, aggregates pass-rate
  demo-agent.ts    — `pnpm demo:agent`: pass-rate matrix + classification counts
agent.config.json  — pinned model snapshot + settings (no secrets)
episodes/          — transcripts (gitignored; local evidence, per repo sovereignty principle)
tests/agent.test.ts — plan-schema, execution-abort, classification, runner with a
                     scripted fake driver (no network in tests, ever)
```

`report.ts` gains an async agent entry point; the sync function path and its
guard are unchanged.

## Outcome taxonomy (every episode classified exactly one way)

- `pass` — verifier returns zero violations.
- `business-violation` — executed cleanly, verifier failed it. The interesting case.
- `invalid-action` — the domain API rejected a call (e.g. transfer to a
  deactivated customer). Agent reasoning error, aborts remaining calls.
- `malformed-output` — plan JSON unparseable or schema-invalid. Agent output error.
- `infrastructure` — network/rate-limit/timeout. Not counted; episode is retried
  once, then excluded and noted.

## Statistics and evidence

- k = 10 episodes per case, temperature 0, pinned model snapshot. Temp 0 reduces
  variance; it does not guarantee identical outputs — k still matters.
- Transcript per episode: full prompt, raw model response, parsed plan,
  execution log, verifier violations, model id, token counts, wall time.
  Transcripts are the evidence chain and raw material for future failure traces.
- `pnpm demo:agent` prints: case × pass-rate matrix (functions as today, agent
  as a new column), classification counts, total cost estimate.

## Falsification rules (decided before the run, printed with results)

- 10/10 on all four cases → "scenario likely too easy for this model" — escalate
  counterfactual difficulty; do not declare victory.
- Failures dominated by `malformed-output`/schema friction → harness or prompt
  bug; fix and rerun; not an agent result.
- `business-violation` failures → genuine agent finding; the transcript becomes
  a candidate failure trace for the next counterfactual family.

## Acceptance criteria

1. `pnpm test` and `pnpm typecheck` stay green; new tests cover plan-schema,
   abort-on-invalid, classification, and the runner via a fake driver. Tests
   never touch the network.
2. `git diff` shows zero changes to `src/verifier.ts`, `failure_trace.json`,
   `cases/`, existing tests.
3. `pnpm demo:agent` produces the pass-rate matrix + classifications + episodes
   on disk. **This step needs the user's API key and a small spend (< $1); the
   user runs it or hands over the key at that point.**
4. Transcripts contain no API key material.
5. README gains a short "agent rung" section; WALKTHROUGH gains the new files.

## Explicitly not this rung

Multi-turn tool loops, a second model, local/Ollama drivers, difficulty
escalation, prompt-injection red-teaming of the agent path, any training.
Each is a separate gated plan if this one lands.

## Build ownership (after sign-off)

Same swarm pattern: orchestrator owns this plan; `tesla` implements `src/agent/`
and the `report.ts` entry; `shannon` owns `tests/agent.test.ts`; `lamarr` owns
doc updates; `hypatia` red-teams the classification/parsing edges; `ramanujan`
reviews. Coordination via `coordination/agents/<name>.md` as before.
