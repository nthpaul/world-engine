# failure-to-intervention

A small executable proof of one World Engine idea: a production-shaped agent
failure, turned into a replayable task with a real pass/fail signal.

## What this proves

An automated merge caused a production incident: two "Ada Byron" customer
records shared one email, the customer was double-charged, and the fix voided
the wrong invoice and left no audit trail. This prototype rebuilds that failure
as deterministic SQLite state. It scores any proposed fix against business
invariants, not against the incident's exact rows. Then it replays the same
story under three counterfactual variations. That spread is what separates an
overfit fix from a robust one: the overfit fix passes the original incident and
fails every variation, while the robust fix passes all four.

This is the repo mission in miniature: production failure in, counterfactual
tasks out, an intervention validated before anyone calls it safe.

## Data flow

```
failure_trace.json (plus cases/*.json)
  -> reconstruct deterministic SQLite state
  -> task definition
  -> intervention operating through a domain API
  -> hidden state-based verifier
  -> structured evaluation report
```

## The four cases

| case_id | file | wrinkle |
|---|---|---|
| `original-incident` | `failure_trace.json` | The incident itself: two Ada Byron records share `ada@example.com`; INV-5001 ($120.00) sits open on both; Grace Lee is a bystander |
| `reordered-ids` | `cases/reordered-ids.json` | Same story, new ids and invoice numbers; the **lower** customer id is the **newer** record, and one email differs only by case |
| `dup-owns-legitimate` | `cases/dup-owns-legitimate.json` | The duplicate owns its copy of the duplicated invoice **and** a legitimate open invoice that must move over still `open` |
| `unrelated-lookalike` | `cases/unrelated-lookalike.json` | A third "Ada Byron" with a **different email** and her own INV-5001; she must stay byte-identical |

## The two interventions

- **naive** — the overfit shortcut. Groups active customers by exact name,
  keeps the lowest id as canonical, and hardcodes invoice number "INV-5001" as
  the only duplicated invoice. It was fitted to the one incident it saw.
- **robust** — derives everything from business properties: groups by
  normalized email, picks the canonical customer by earliest `created_at`,
  finds genuinely duplicated invoices by number + amount within the pair,
  voids only the non-surviving copies, moves the rest, deactivates, audits.
  No fixture constants.

## The agent rung

The same rig now seats a real model in the intervention slot. One model
call per episode returns a single-shot JSON plan: an ordered list of
domain-API calls. The harness Zod-validates the plan, executes it through
the same constrained API the hand-written interventions use, and the same
frozen verifier judges the result.

Every episode is classified exactly one way: `pass`, `business-violation`,
`invalid-action`, `malformed-output`, or `infrastructure`. Infrastructure
episodes (network, rate limit, timeout) are retried once, then excluded
from the pass rate. Each case runs k = 10 episodes at temperature 0 with a
pinned model snapshot. Transcripts land in `episodes/` (gitignored).

Five providers sit behind one interface: anthropic (the default), openai,
openrouter, ollama, and cursor. Provider choice and model live in
`agent.config.json`, overridable with the `PROVIDER` env var. API keys come
from env vars only and never touch transcripts.

## Run it

```bash
cd prototypes/failure-to-intervention
pnpm install
pnpm demo       # prints the result matrix
pnpm test       # vitest suite
pnpm typecheck  # tsc --noEmit, strict
pnpm demo:agent # live model run; needs the provider's API key in the environment
```

`pnpm demo:agent` needs the provider's API key in the environment
(`ANTHROPIC_API_KEY` by default). It runs k = 10 episodes on each of the
four cases against the live model; expected spend is under $1. It prints
the pass-rate matrix with an agent column next to naive and robust, the
per-case classification counts, token and cost totals, and the
falsification rules that were decided before the run. Afterwards,
`tsx src/agent/audit-report.ts` regenerates `audit-data.json` from
`episodes/`.

## Expected demo output

```
case                    naive   robust
original-incident       PASS    PASS
dup-owns-legitimate     FAIL    PASS
reordered-ids           FAIL    PASS
unrelated-lookalike     FAIL    PASS
```

Below the matrix, `pnpm demo` also prints the violations behind each FAIL
cell. They name the exact invariant and the exact row ids, so each failure is
legible: naive picks the wrong canonical in `reordered-ids`, never voids the
dup copy in `dup-owns-legitimate`, and merges the unrelated customer in
`unrelated-lookalike`.

Rows print in `loadCases()` order: the incident first, then counterfactuals
sorted by filename.

## Limits

This is a synthetic, single-domain fixture: four hand-written seeds against
one imaginary SaaS schema. Round one's interventions are deterministic
TypeScript functions with no model in the loop — they test intervention
logic, not model behavior. The agent rung does put a model in the loop,
judged by the same frozen verifier, but it is single-shot only (no
multi-turn repair), it runs on this one small domain, and the prompt is the
experiment: the results say as much about the prompt as about the model.
The verifier is hidden from interventions (they never receive it) but lives
in the same repo, so "hidden" is a code boundary, not a security boundary.
Passing here shows the evaluation machinery works end to end; it is not
evidence that any real agent improved.

## More

- [PLAN.md](PLAN.md) — the binding contract this was built against
- [PLAN-agent.md](PLAN-agent.md) — the agent-rung contract: episode shape,
  prompt calibration, outcome taxonomy, falsification rules
- [PREDICTIONS.md](PREDICTIONS.md) — per-case predictions, pre-registered
  before the first live run
- [WALKTHROUGH.md](WALKTHROUGH.md) — every file, in reading order
- AUDIT.md — the behavioral audit, authored from `audit-data.json` after
  the live run; it does not exist until then
