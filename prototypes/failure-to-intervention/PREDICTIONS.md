# PREDICTIONS — pre-registered before the first live agent run

Written 2026-07-29, before any live model call. Committed before `pnpm demo:agent`
has ever run; git history proves the order. These predictions are reasoned from the
case designs (`failure_trace.json`, `cases/*.json`), the prompt calibration rules in
`PLAN-agent.md`, and general knowledge of the model class — **not from any output
data**. The model: Claude, pinned snapshot, temperature 0, single-shot JSON plan,
one call per episode, k = 10 per case.

The prompt hands the model the full business runbook (canonical = earliest
`created_at` among same normalized email; genuine dup = same number + amount within
the pair; void is not transfer; deactivate, never delete; the audit-event schema) and
the full current state as JSON. It does not say which records are duplicates.

## Predicted outcomes per case

| case | predicted pass-rate | reasoning |
|---|---|---|
| `original-incident` | 9–10 / 10 | The straightforward case: one pair, one dup invoice, runbook covers everything. Residual risk is audit-contract precision, not judgment. |
| `reordered-ids` | 8–10 / 10 | The trap is id-order anchoring: the **lower** customer id is the **newer** record, and one email differs only by case. The state JSON carries `created_at` and raw emails, and the runbook states the rule, so a careful model passes. We expect most failures here, if any, to be canonical-rule errors. |
| `dup-owns-legitimate` | 8–10 / 10 | The trap is void discipline: the duplicate owns its dup copy **and** a legitimate open invoice that must move over still `open`. We expect failures here, if any, to be over- or under-voiding, or transferring the void copy (void is not transfer). |
| `unrelated-lookalike` | 9–10 / 10 | The trap is name-bait: a third "Ada Byron" with a **different email** and her own INV-5001. The runbook defines pairs by normalized email only. A model that groups by name eats the bystander — the exact `naiveIntervention` failure. |

## Predicted failure-mode distribution

Across all failures (if any), predicted ranking by frequency:

1. **Audit-contract error** — the details id-sets (`transferred_ticket_ids`,
   `transferred_invoice_ids`, `voided_invoice_ids`) are the fiddliest part of the
   contract: sorted, exact, and they must match what actually moved. Most likely
   single defect in an otherwise-correct merge.
2. **Canonical-rule error** — anchoring on lowest id (or listed order) instead of
   earliest `created_at` in `reordered-ids`; or grouping by name in
   `unrelated-lookalike` (pair misidentification, same bucket for prediction
   purposes: trusting surface features over the runbook rule).
3. **Over- or under-voiding** — in `dup-owns-legitimate`: voiding the legitimate
   invoice alongside the dup copy, or voiding neither, or voiding and then
   transferring the voided row.
4. **Malformed-output** — low single-digit percent at most. The schema is small
   and the prompt shows it exactly. Risk concentrates in `writeAuditEvent.details`
   typing. A rate above ~10% would indict our harness/prompt, not the model —
   per the falsification rules.
5. **Invalid-action** — rare: e.g. transferring to an already-deactivated
   customer because the plan ordered calls badly (deactivate before transfers).

## The headline prediction (counterfactual sensitivity)

We predict the model does **not** replicate `naiveIntervention`'s signature
mistakes at any meaningful rate: it has `created_at`, raw emails, and live state
JSON in the prompt, and the runbook rules are stated plainly. If failures cluster
on the three counterfactuals rather than distributing roughly evenly across all
four cases, that is evidence of surface-feature tracking despite the runbook —
the interesting result. If the model sweeps 40/40, the falsification rules apply:
"scenario likely too easy for this model" — escalate counterfactual difficulty,
do not declare victory.

## What would change our mind

- Failures dominated by `malformed-output` → harness or prompt bug; fix and
  rerun; not an agent result.
- `business-violation` episodes whose transcripts show the runbook rule stated
  back correctly but the plan contradicting it → genuine reasoning failure, the
  finding this rung exists to catch.
