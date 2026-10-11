# Bounded Matched Local Model Study

Status: collector implemented and mock-tested; collection is **not authorized or executed**. There are no study results. Root must review and commit the collector, tests and protocol, freeze the complete runtime, then authorize its exact source revision before any model requests. No new weights, paid providers, cloud compute, or trainer calls are permitted.

The implementation is [the collector](../examples/workflow_model_study.py), with [focused tests](../tests/test_workflow_model_study.py). Its fixed protocol SHA-256 is `6abb1350ea008d962624bc2561bb486b461ffd426a01cbd1bfcd51c33ff391bc`. The default command and `--plan` never instantiate or contact a provider:

```sh
uv run python examples/workflow_model_study.py --plan
uv run pytest tests/test_workflow_model_study.py -q
```

Verification on 2026-10-10: 48 focused tests passed and affected Ruff checks passed. All collector tests use fake transports/episodes or local serialization; no model requests or actual study collection occurred.

`--collect` requires both `--source-revision` with a reviewed full commit SHA and `--output` naming a nonexistent directory. Supplying those arguments without `--collect` still only prints the plan. A flag is an execution gate, not evidence that an operator obtained approval. Do not collect until the runtime and protocol commit has been reviewed and explicitly authorized.

## Question

How reliably can the existing local Qwen3 8B model complete the CRM, refund, and incident rules within a fixed action budget, and do native tool calls versus structured-JSON actions change end-to-end success on identical fixtures? This study tests the delivered synthetic fixtures and two adapters. It does not measure application parity, learning gains, unseen workflow-family transfer, or a leaderboard score.

Use the verified native-tool and structured-JSON adapters, with one attempt per adapter on each task. Do not silently switch protocols for a failed call. Both must enforce one authorized action per decision and record their exact wire inputs. Their required formatting instructions and tool-schema encoding differ; this is an adapter-protocol comparison, not an isolated experiment on model reasoning. The older foundation sample is historical context, not a matched comparator because prompts, source, and tasks have changed.

## Locked Sample

| Field | Fixed value |
|---|---|
| Worlds | `crm-merge` 1.1.1; `refund-ops` 1.1.2; `incident-control` 1.0.1 |
| Seeds | Exact new evaluation-seed lists below; no previously collected low seeds |
| Unique tasks | 32 family/seed fixtures: 8 CRM, 16 refund, 8 incident |
| Coverage | Four CRM cases with two seeds each; eight refund cases with two seeds each; four SEV1 and four SEV2 incidents |
| Model attempts | One native and one JSON attempt per exact task, 64 maximum |
| Controls | One scripted reference and one incomplete baseline per exact task, 64 control attempts |
| Total attempts | 128 maximum, including controls |
| Episode budget | 20 tool decisions and 35 seconds for every policy |
| Model/runtime | Already-installed `qwen3:8b`, digest verified against local catalog before collection |
| Inference settings | Temperature 0, thinking disabled, 512 output tokens and 8,192 context tokens; reject different adapter contracts |
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

The task order is deterministic: for refund index `i=0..15`, schedule that refund task followed by CRM index `i//2` when `i` is even or incident index `i//2` when `i` is odd. This spreads all three worlds through the collection rather than placing one at the end. Within each task, native is first for CRM indices 0..3 and refund indices 0..7; JSON is first for their remaining indices. Native is first for incident seeds `1000200, 1000201, 1000202, 1000206`; JSON is first for the other four. Each case or severity therefore gets one or two tasks with each first adapter, totaling 16 native-first and 16 JSON-first pairs. Every task's slot order is scripted reference, incomplete baseline, then its specified adapter pair. Controls use the same episode bounds.

The 35-second limit permits at most 2,240 seconds of model episode time for all 64 attempts, leaving 460 seconds inside the 45-minute aggregate cap for preflight, controls, replay, and artifact work. The collector reserves ten seconds for cleanup and refuses a new episode without its full remaining 35-second budget. This is a feasibility bound, not a completion guarantee: cancellation, cleanup, or hardware failures can stop collection. Cooperative timeouts are not a process-kill guarantee; a late finalization is reported as stopped, not a compliant completion. This shorter limit differs from the foundation's 120-second sample and must be disclosed. Counterbalancing reduces some order effects but does not eliminate cache, thermal, or background-load confounds. Exact temperature-zero reproducibility is not assumed.

If the aggregate cap, transcript capacity, or user interruption stops collection, preserve every attempted outcome and explicitly mark the remaining predetermined slots `not_attempted`. Do not count unattempted slots as policy failures, replace hard cases, retry the worse protocol, or continue under a larger undeclared budget. A partial receipt is valid bounded evidence, not completion of the protocol. An incomplete pair is excluded from the paired difference but remains in the attempted-slot report.

## Freeze and Receipt Requirements

Before collection, root must commit the canonical protocol, ordered slot list, collector, environment/grader/provider source, and tests. The collector rejects a dirty complete `src/world_engine` tree, dependencies, collector, study tests or this protocol document, including untracked files in those paths. It records their SHA-256 values and the full reviewed Git revision; it checks the source again before each slot and at finalization. Other checkout dirtiness is separately reported. Fixtures must match locked versions, state/environment/grader fingerprints and task order. Each raw episode retains lineage, split, prompt hash, actual application request/response bytes, finish reasons, calls, outcomes, usage, timing, termination, authoritative grade, and invalid actions.

Both adapters finish metadata-only preflight and match the exact installed model name/digest before **any** episode or chat. Actual Ollama version and adapter contracts are retained. The receipt records platform, Python, architecture, logical CPU count, installed HTTPX/Pydantic versions, and bounded public macOS CPU/memory metadata when available. Unknown optional values are omitted. No environment-variable inventory or secrets are recorded. Catalog metadata does not prove immutable server execution or weight identity during each request; temperature zero and a digest do not attest determinism.

Native and recorded-JSON transcripts are operator evidence, not automatically trainer-ready messages. `evaluation-episodes.jsonl` is the single authoritative append-only journal; `report.json` is a bounded derived summary. There is no duplicate SQLite database or automatic ATIF export. Finalized raw episodes are flushed and fsynced before validation or another attempt. This is not mid-episode crash durability. An unexpected harness exception without a finalized episode produces an explicit `episode: null` attempt-error row, not a fabricated grade. Replay such a mixed journal by selecting non-null episodes, and retain its error rows as provenance.

The 64 MiB disk cap includes every file under the output directory, including unexpected temporary files. Before an episode the collector reserves 24 MiB for its raw envelope and 1 MiB for the final report. The fixed-world capacity derivation accounts for up to 8 MiB of recorder events, twenty 132 KiB policy contexts, conservative 384 KiB normalized actions after escaping, 64 KiB observations/results, per-step overhead, and 1 MiB of snapshots/metadata. Initial observations are limited to 32 KiB; these three pinned worlds grow state through bounded primitive audit entries, not arbitrary documents. A synthetic serialization test fills these conservative allowances beyond 20 MiB. This is a scoped calculation and stress test, not a universal envelope bound for future worlds or a hostile host.

If an unexpectedly oversized episode still fits the total cap, its full raw envelope is preserved and collection stops as inconclusive. It is not retained as a verified success. If a broken runtime exceeds even the remaining total space, the report explicitly marks the unavailable/inconclusive attempt; it cannot claim complete raw retention for that attempt. No further request or enlarged budget is permitted. Do not invent token IDs, sampled log probabilities, or a loss mask from text.

Replay every recorded environment action under the collected source; this verifies environment consistency, not a second inference run or authenticity of model identity. Keep historical receipts immutable. Later full-module or provider changes require the pinned collected checkout for replay. Do not compare tasks merely by displayed names when source fingerprints differ.

## Analysis Without Inflating the Sample

Report each attempted task's grade, policy actions, invalid-action count, termination, and failure category. Separate protocol/parse failures, tool-permission or argument errors, valid but incorrect decisions, action exhaustion, provider/harness failures, and successful completion. Successful episodes with invalid actions are business passes but not clean successes. The primary metric is `passed`, not mean shaped reward: legacy preservation/finish checks can earn partial credit without business progress. They are diagnostic values, not a validated trainer objective. Operational end-to-end success includes integration failures; a conditional policy-only rate must state its denominator and exclusions separately.

Each adapter has 32 unique task attempts, with per-world denominators 8 CRM, 16 refund, and 8 incident if collection completes. The implementation reports per-world and micro success rates with Wilson 95% intervals, clean micro success, and equal-world macro success. Duplicate task-policy rows are rejected. Unattempted slots never enter denominators. Attempted harness failures with no usable episode are explicit operational failures, not silently dropped successes; they do not form complete paired outcomes. Saved but unverified envelopes are quarantined, their raw labels remain unchanged, and report counters distinguish finalized, verified and inconclusive episodes.

Paired analysis reports both-pass, native-only, JSON-only and neither-pass counts using only complete verified task pairs. The bootstrap resamples whole pairs within each world, with 2,000 samples and seed `20261010`, never the 64 attempts as independent observations. It reports micro and equal-world macro paired differences separately. An equal-world macro is unavailable if any world has no usable samples. Wilson and percentile bootstrap intervals are descriptive under this fixed public sample, not guaranteed population coverage. Per-case results have only two seeds and are descriptive, not well-powered comparative estimates. Do not infer learning gains from a protocol difference or oracle successes.

The fixture rules were used during implementation and are visible. New seeds reduce reuse of earlier inference samples but do not establish new-rule generalization. Hash-based seed splits preserve dataset lineage; they do not prove withheld-case or family generalization. Any future generalization study must lock a genuinely excluded variant family or task distribution before development. Group both protocols and counterfactual descendants by original family/seed lineage for curation.

## Stop and Review

Stop on a changed model digest or source, paid/remote endpoint, uncontrolled concurrent inference, secret disclosure, missing raw-transcript retention, artifact cap, aggregate duration cap, or user interruption. Preserve an explicit stopped receipt with completed and unattempted slots. Root reviews the record before public delivery. No tuning or follow-up retry is part of this protocol; any later intervention gets its own committed source and protocol.

Concurrency one applies to this collector, not all clients of an Ollama daemon. The operator must exclude simultaneous UI/benchmark inference; the daemon does not provide the collector a global exclusivity guarantee. Cleanup is attempted for both model adapters even after preparation or collection failure; a cleanup failure preserves existing rows and writes a stopped report. No fallback, missing-model download, new training code or follow-up inference is authorized by this implementation.
