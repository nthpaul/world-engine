# Bounded Local Model Study Proposal

Status: proposed protocol, not yet approved, locked, or executed. There are no results for this study. Root must select the verified adapter, commit the exact protocol and collector, freeze all runtime source, and explicitly authorize collection before any model requests. No new weights, paid providers, cloud compute, or trainer calls are permitted.

## Question

How reliably can the existing local Qwen3 8B model complete the CRM, refund, and incident rules within a fixed action budget, and do native tool calls versus structured-JSON actions change end-to-end success on identical fixtures? This study tests the delivered synthetic fixtures and two adapters. It does not measure application parity, learning gains, unseen workflow-family transfer, or a leaderboard score.

Use the verified native-tool and structured-JSON adapters, with one attempt per adapter on each task. Do not silently switch protocols for a failed call. Both must enforce one authorized action per decision and record their exact wire inputs. Their required formatting instructions and tool-schema encoding differ; this is an adapter-protocol comparison, not an isolated experiment on model reasoning. The older foundation sample is historical context, not a matched comparator because prompts, source, and tasks have changed.

## Proposed Fixed Sample

| Field | Proposed value |
|---|---|
| Worlds | `crm-merge` 1.1.0; `refund-ops` 1.1.1; `incident-control` 1.0.1 |
| Seeds | Exact new evaluation-seed lists below; no previously collected low seeds |
| Unique tasks | 32 family/seed fixtures: 8 CRM, 16 refund, 8 incident |
| Coverage | Four CRM cases with two seeds each; eight refund cases with two seeds each; four SEV1 and four SEV2 incidents |
| Model attempts | One native and one JSON attempt per exact task, 64 maximum |
| Controls | One scripted reference and one incomplete baseline per exact task, 64 control attempts |
| Total attempts | 128 maximum, including controls |
| Episode budget | 20 tool decisions and 35 seconds for every policy |
| Model/runtime | Already-installed `qwen3:8b`, digest verified against local catalog before collection |
| Inference settings | Temperature 0, thinking disabled, 512 output tokens and 8,192 context tokens, if supported by the tested adapter |
| Concurrency | 1; no simultaneous UI or benchmark inference |
| Model decision cap | 1,280 maximum, including invalid decisions and retries |
| Aggregate wall cap | 45 minutes, including both adapter attempts and controls |
| Data purpose | Evaluation-only; excluded from SFT/DPO/grouped training exports |

Exact fixed lists:

- CRM: `1000000, 1000001, 1000002, 1000003, 1000004, 1000005, 1000006, 1000007`.
- Refund: `1000104, 1000105, 1000106, 1000107, 1000108, 1000109, 1000110, 1000111, 1000112, 1000113, 1000114, 1000115, 1000116, 1000117, 1000118, 1000119`.
- Incident: `1000200, 1000201, 1000202, 1000203, 1000204, 1000206, 1000208, 1000210`.

CRM and refund are balanced by the fixed modulo case map. Incident seeds are the first four SEV1 and first four SEV2 fixtures in the predefined candidate range `1000200..1000215`, selected solely from generated severity metadata without model inference or inspection of attempted outcomes. All cases remain the existing authorized-recovery incident path; severity balance does not add a new incident rule. These are new inference-evaluation seeds, not unseen rules or guaranteed training-uncontaminated data.

The existing model digest is `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`. A changed digest is a new experiment, not an implicit substitute. Catalog lookup is not permission to download a missing model. Record actual installed runtime versions and adapter settings rather than assuming API capability from model name.

Build the task order deterministically: for refund index `i=0..15`, schedule that refund task followed by CRM index `i//2` when `i` is even or incident index `i//2` when `i` is odd. This spreads all three worlds through the collection rather than placing one at the end. Within each task, native is first for CRM indices 0..3 and refund indices 0..7; JSON is first for their remaining indices. Native is first for incident seeds `1000200, 1000201, 1000202, 1000206`; JSON is first for the other four. Each case or severity therefore gets one or two tasks with each first adapter, totaling 16 native-first and 16 JSON-first pairs. Collect both scripted controls with the same bounds.

The 35-second limit permits at most 2,240 seconds of model episode time for all 64 attempts, leaving 460 seconds inside the 45-minute aggregate cap for preflight, controls, replay, and artifact work. It is a feasibility bound, not a completion guarantee: cancellation, cleanup, or hardware failures can still stop the collection. This shorter limit differs from the foundation's 120-second sample and must be disclosed. Counterbalancing reduces some order effects but does not eliminate cache, thermal, or background-load confounds. Exact temperature-zero reproducibility is not assumed.

If the aggregate cap, transcript capacity, or user interruption stops collection, preserve every attempted outcome and explicitly mark the remaining predetermined slots `not_attempted`. Do not count unattempted slots as policy failures, replace hard cases, retry the worse protocol, or continue under a larger undeclared budget. A partial receipt is valid bounded evidence, not completion of the protocol. An incomplete pair is excluded from the paired difference but remains in the attempted-slot report.

## Freeze and Receipt Requirements

Before collection, root must commit the canonical protocol, ordered slot list, collector, environment/grader/provider source, and tests. The collector must reject dirty implementation or a changed protocol and must record the exact Git revision, source and grader fingerprints, collector hash, model digest, task identity, lineage, split, prompt hash, actual serialized model requests/responses, finish reasons, tool calls, tool outcomes, usage, timing, termination, final authoritative grade, and invalid actions.

Native request/response transcripts are operator evidence, not automatically trainer-ready messages. Preserve exact wire contents for loopback calls while excluding secrets and hidden grader material. Put a bounded total transcript/artifact cap in the final collector, proposed at 64 MiB. Stop and mark the attempt inconclusive rather than silently dropping raw responses and retaining a success label. Do not invent token IDs, sampled log probabilities, or a loss mask from text.

Replay every recorded environment action under the collected source; this verifies environment consistency, not a second inference run or authenticity of model identity. Keep historical receipts immutable. Later full-module or provider changes require the pinned collected checkout for replay. Do not compare tasks merely by displayed names when source fingerprints differ.

## Analysis Without Inflating the Sample

Report each attempted task's grade, policy actions, invalid-action count, termination, and failure category. Separate model protocol/parse failures, tool-permission errors, valid but incorrect policy decisions, action exhaustion, provider/harness failures, and successful completion. Operational end-to-end success includes integration failures; a conditional policy-only rate must state its denominator and exclusions separately.

Each adapter has 32 unique task attempts, with per-world denominators 8 CRM, 16 refund, and 8 incident if collection completes. Report the per-adapter success proportions and Wilson intervals, then matched both-pass, native-only, JSON-only, and neither-pass counts. The paired success difference uses only complete task pairs; any bootstrap interval must resample whole task pairs, stratified by world, not treat the 64 attempts as independent tasks. Show the micro-average over the prespecified task mixture and the equal-world macro-average separately, because refund contributes half the tasks. Per-case results have only two seeds and are descriptive, not well-powered comparative estimates. Do not infer learning gains from a protocol difference or oracle successes.

The fixture rules were used during implementation and are visible. New seeds reduce reuse of earlier inference samples but do not establish new-rule generalization. Hash-based seed splits preserve dataset lineage; they do not prove withheld-case or family generalization. Any future generalization study must lock a genuinely excluded variant family or task distribution before development. Group both protocols and counterfactual descendants by original family/seed lineage for curation.

## Stop and Review

Stop on a changed model digest or source, paid/remote endpoint, uncontrolled concurrent inference, secret disclosure, missing raw-transcript retention, artifact cap, aggregate duration cap, or user interruption. Preserve an explicit stopped receipt with completed and unattempted slots. Root reviews the record before public delivery. No tuning or follow-up retry is part of this protocol; any later intervention gets its own committed source and protocol.
