# Matched adapter study: observed results

Collected October 10, 2026, 06:48:30 to 07:15:20 UTC. Root independently validated the finalized evidence without new inference. This evidence release includes the original journal/report and independent-validation sidecar. The [locked protocol](workflow-model-study.md) remains immutable source history. The [foundation report](report/world-engine-report.md) and historical six-case native receipts are unchanged.

## Source and execution

Collection source: `622c5b18ee38d0e581d04832e555801febc37dc3`. Protocol `workflow-matched-adapters-v1`, SHA256 `6abb1350ea008d962624bc2561bb486b461ffd426a01cbd1bfcd51c33ff391bc`. World versions were CRM 1.1.1, refund 1.1.2 and incident 1.0.1. Access provisioning was not a study task.

The already-installed `qwen3:8b` catalog digest was `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`. Both adapters used temperature zero, thinking disabled, 512 output tokens and an 8192-token context setting. Each of 32 fixed new-seed tasks received one native and one recorded-JSON attempt plus two scripted controls. Adapter-first order was balanced 16/16. No tuning, retry, fallback, model download or paid call occurred.

Limits were twenty decisions and 35 seconds per episode, 45 minutes overall, concurrency one and 64 MiB. All 128 planned slots finalized; no stop reason, inconclusive episode or cleanup error was reported. Elapsed collection was 1600.268 seconds, approximately 26.67 minutes. The raw journal has 128 full finalized records, including failures. These are 32 tasks, not 128 independent tasks.

Relevant source scope was clean and all recorded file hashes matched. Overall checkout dirtiness was true and explicitly retained. Machine metadata records Apple M4 Max, arm64, 16 logical CPUs, 64 GiB memory, Python 3.13.5, httpx 0.28.1, Pydantic 2.14.0 and reported Ollama 0.22.0. A catalog digest and reported daemon metadata do not authenticate model execution or frozen weights. Background load and thermal/cache state were not controlled laboratory variables.

## Business outcomes and clean execution

| World | Tasks per adapter | Native business passes | JSON business passes | Native / JSON clean passes |
| --- | ---: | ---: | ---: | ---: |
| CRM | 8 | 0 | 0 | 0 / 0 |
| Refund | 16 | 16 | 7 | 6 / 0 |
| Incident | 8 | 8 | 0 | 0 / 0 |
| Total | 32 | 24 | 7 | 6 / 0 |

The scripted reference passed all 32 tasks; the intentionally incomplete baseline passed none. Those controls establish tested implementation behavior, not learned competence. The model's native business rate was 24/32, 75.0%, but clean success was only 6/32, 18.75%. Recorded JSON passed 7/32, 21.875%, with no clean success. A business pass after denied actions is not a clean curated demonstration.

Descriptive 95% Wilson intervals for business micro-rates are native 57.9%--86.7% and JSON 11.0%--38.8%. CRM's 0/8 interval still extends to 32.4%; zero observed passes does not prove impossible success. Fixed synthetic tasks and deterministic fixture families are not independent population sampling. These intervals do not establish production representativeness or unseen-rule generalization.

Micro-average gives each task equal weight, so refunds comprise half the sample. Equal-world macro-average gives the three worlds equal weight: native 66.67%, JSON 14.58%. Neither weighting is a measured production workload distribution.

## Matched comparison

| Pair outcome | Tasks |
| --- | ---: |
| Both adapters passed | 7 |
| Native only passed | 17 |
| JSON only passed | 0 |
| Neither passed | 8 |

All 32 pairs were complete. The observed native-minus-JSON business micro-difference is 17/32, 53.125 percentage points. The predeclared world-stratified whole-pair bootstrap used 2000 resamples and seed 20261010. Its descriptive 95% interval is 40.625--65.625 points. The equal-world macro-difference is 52.083 points with interval 43.75--60.417 points.

This compares complete frozen adapter contracts, including different prompts, schemas and parsing. It does not isolate one formatting variable, show a trained model improvement, estimate repeated-attempt reliability or establish superiority outside these tasks and bounds. Balanced first order reduces one ordering imbalance but does not remove host/cache effects.

## Read failures before choosing a remedy

Five native CRM attempts stopped after inspection because the response contained multiple tool calls, violating the locked one-call contract. No prefix was executed. One CRM native attempt timed out; two finished with an incorrect task state. These are different failure mechanisms. Relaxing the contract retrospectively would change the experiment, not repair its recorded score.

Recorded JSON had 23 timeout terminations, two maximum-step terminations and seven task passes. Calling all failures malformed JSON would be false. Native recorded 85 invalid environment actions; JSON recorded 280. Denials preserve state but consume decisions and time. A timeout alone does not prove a provider bug or business-reasoning error; inspect its saved exchanges and action history.

There were 775 recorded transport attempts: native 259 and JSON 516. Known reported usage sums to 979,980 input and 18,638 output tokens, but aggregate completeness is false. These are partial known sums, not complete totals, billed costs or attested model executions. Do not infer efficiency per solved task from incomplete token accounting.

## Independent proof and immutable bytes

The [independent-validation sidecar](../artifacts/workflow-model-study/20261010-matched-v1/independent-validation.json) records root's verification of all 128 episodes by replay at the collected source, exact report/raw identity and grading correspondence, source hashes, and all 128 ATIF conversions against actual pinned Harbor `Trajectory` 0.24.0. The schema SHA256 was `892a423ee9c710e8067740b36dd15c9de2f0157d05b6c1ea30acc25ff1c4da6c`. Root also verified 384 exclusions across SFT, DPO and grouped formats, 128 per format, before candidate pools were queried. These are evaluation-only operator records, never trainer batches. Validation made no model calls and completed before subsequent runtime source changes.

The original raw/report pair contains exactly 17,729,163 bytes, below the 64 MiB collection limit. Later independent-validation sidecars are additional publication bytes, not silently included in that original accounting. Original files remain unchanged:

- [Report](../artifacts/workflow-model-study/20261010-matched-v1/report.json): SHA256 `a9d8cb7d7a267afb40358a4bcd8c035db5761f0f21a31547358ccf2c21263bda`.
- [Raw finalized journal](../artifacts/workflow-model-study/20261010-matched-v1/evaluation-episodes.jsonl): SHA256 `ae70f57de632a135d2856c6a46d3befe9cc1bb6e1f3ae7b64847a310f4032e16`.

Replay checks internal consistency, not signed host authenticity, reported timing or stochastic output regeneration. Saved finalized episodes are fsynced before the next attempt; an in-flight request is not a crash-durable journal entry.

## Replay without inference

From the evidence repository, use an unused checkout path and the exact collected source. Subsequent provider/world revisions can intentionally invalidate current-source replay:

```sh
EVIDENCE_ROOT="$(pwd)"
git worktree add --detach /tmp/world-engine-matched-replay \
  622c5b18ee38d0e581d04832e555801febc37dc3
cd /tmp/world-engine-matched-replay
uv run python -m world_engine replay --file \
  "$EVIDENCE_ROOT/artifacts/workflow-model-study/20261010-matched-v1/evaluation-episodes.jsonl"
```

This makes no provider calls. Do not rerun collection to validate the receipt, relabel failed attempts, or overwrite it after a fix. Exact sampled token IDs, masks, behavior log-probabilities and a verified training checkpoint remain absent. The [trainer feasibility audit](trainer-preprocessing-feasibility.md) remains a separate blocked gate.
