# Roadmap and evidence gates

Updated 2026-10-10. Each milestone requires evidence before the repository describes it as complete.

## Local platform

The rebuild provides workflow worlds, a Python SDK, bounded rollout jobs, grades, persisted traces, replay, candidate training exports, and an operator console. Consult [operations](OPERATIONS.md) for exact commands and limits. The [build board](../coordination/BUILD.md) records verification status.

Completion requires reference and failing policies, permission-boundary tests, independent episode state, consistent replay, truthful export labels, a frontend build, and browser QA. A bounded local language-model experiment adds actual policy evidence. Report its sample count and costs.

Scoped follow-ups now include deterministic CRM/refund boundary variants, incident grader integrity, pinned Harbor ATIF interchange, native API/console/CLI/SDK entrypoints, and a constrained local Docker SDK. The historical native six-episode receipt records four business passes and two clean successes across 48 transport requests; it is separate from later matched studies. Docker lifecycle measurements use four repeated synthetic inputs, not real-model or cloud workloads. The [build board](../coordination/BUILD.md) distinguishes source and artifact delivery status.

The latest [CRM/refund certificate correction](workflow-grader-integrity.md) strengthens whole-state/history grading and accepts legitimate transfer-before-void ownership. Protocol-v3 coverage at `ee26d7b9` now includes 128 scripted episodes over 64 matched tasks, with independent raw/statistical/replay/Harbor/exclusion checks. Previously collected outcomes stay pinned historical evidence, not proof that the new corruption cases were rejected then.

[Access provisioning](access-provisioning.md) adds partial observation, bounded discovery, corroborated identity, least-privilege policy, service-owned reviews and grant/denial outcomes. Binary reward avoids credit for preservation or early finish alone. Controls passed 32/32 reference and 0/32 baseline episodes. [Eight native attempts](access-native-results.md) all timed out at 35 seconds, with zero settlement/finish and zero passes; navigation errors and the deadline remain distinct diagnostic factors. No proposed longer-deadline follow-up has run. Access UI v2 passed 31 checks; the failed serialization attempt v1 is retained. These gates establish bounded local behavior, not directory parity or compliance.

The latest four-world CPU receipt contains 2,160 episodes in 72 batches with 120 unique world/seed tasks repeated nine times. All per-trial and aggregate statistics reconcile with raw records. This completes scripted local measurement, not inference scheduling, CPU parallelism or a competitor speed comparison. Public-boundary hardening was delivered in [PR #28](https://github.com/nthpaul/world-engine/pull/28) at `451c1cf9`, with 26 focused tests. The separate [advanced workbook](report/advanced-environment-labs.pdf), twelve pages with nine labs and 27 primary sources, was published in [PR #29](https://github.com/nthpaul/world-engine/pull/29).

The [matched model study](workflow-model-study-results.md) completed at source `622c5b18ee38d0e581d04832e555801febc37dc3`: all 128 planned model/control slots finalized, with native 24/32 business passes and six clean successes versus recorded JSON 7/32 and zero clean. Root independently verified replay, pinned schema, source hashes and training exclusion. Evidence and its validation sidecar were published at `c5d7caba` in [PR #21](https://github.com/nthpaul/world-engine/pull/21). This completes one bounded synthetic adapter comparison, not representative production evaluation, repeated-attempt reliability, new-rule generalization or model training.

The [five-phase current console proof](../artifacts/qa/20261010-current-final-validation-v1/independent-validation.json) at `b4501029` passed 129 checks with 56 screenshots and five videos. Its 34 new scripted episodes and two historical native imports passed 36 replay/Harbor checks; 26 downloads reproduced byte-for-byte. Imported model evidence is not newly executed native API evaluation. The [CPU profile](../artifacts/profiling/20261010-v2/independent-validation.json) saved all 192 scripted episodes/1,456 decisions and verified 728 redundant reads removed in profiled trials without changed logical outcomes. Unprofiled read counts and the historical unsaved 96 episodes remain unproven, not reconstructed.

The [locked SDK admission study](model-concurrency-study-results.md) at `1d9f2315` completes one real-model concurrency measurement: 32 attempts/eight repeated tasks, 16/16 admission-one passes versus 13/16 admission-two, twelve clean successes overall and three retained timeouts. Observed useful rates were 0.07266 versus 0.05926 passes/second of summed continuous batch wall. Replay/actual Harbor/training-exclusion proofs passed. This negative fixed-workload result does not establish an optimal admission rule, causal GPU parallelism, cache behavior or API throughput. Root verified 1,499 tests/six optional skips, Ruff and frontend build at that collection source. Native CLI/default integration was later committed at `ef63eda9`, with 1,547 tests/six optional skips and preserved historical native compatibility: omitted native concurrency one, explicit one through eight, unchanged legacy four. Corrected zero-inference control QA and actual API-receipt inspection now pass at source51; neither source verification nor imported history is a new model evaluation.

## Real application parity

The separate [native API smoke](native-api-smoke-results.md) at `8b82c7aa` completes actual API/RunManager/factory admission on one refund task: two ordered native attempts, both clean passes, no retries. Corrected [controls QA](native-controls-qa-results.md) and both readonly episode inspection phases at `6bdec4f0` passed 65 checks/34 screenshots/three videos without new episodes, imports or model calls. The original controls v1 automated pass/360px visual failure is preserved. UI source51 passed all 1,657 tests/no skips, including actual Harbor/approved-existing-image Docker probes, with all CI green. These local integration gates do not complete broader task capability, training, cloud or production-parity milestones below.

Select one task family and a pinned application revision. Compare transitions, permissions, observations, timing, and outcomes against the real application. Have a domain expert independently review feasibility and grading.

Completion requires differential tests, a disagreement ledger, repaired mismatches, and a fidelity statement scoped to the validated task distribution. A simulated UI does not complete this gate.

## Public benchmark integration

Run a licensed public task with pinned source, image digest, bounded local compute, and evaluator separation. Respect no-training canaries. Disclose protocol adaptations, including preinstalled verifier dependencies and resource changes.

Completion requires a run receipt, saved model actions, original revision, grader outcome, cleanup evidence, and a reproducible command. An oracle pass proves feasibility. A model pass is one observed attempt.

The rebuild delivers one separate, adapted Terminal-Bench task runner with pinned source, recorded images, separate verification, a passing reference, and a failing negative control. Its final bounded native-tool local-model attempt executed eight shell commands but failed to produce the required CSV. Earlier JSON-v1 attempts produced no executable commands because responses were truncated; those historical protocol failures remain separate. [The protocol and evidence](public-benchmark.md) satisfy a local integration check, not broad benchmark coverage or the official leaderboard protocol. Wider task coverage and native Harbor job integration remain future work. ATIF schema interchange does not complete the native Harbor execution gate.

## Trainer integration

Choose an established trainer and a small open model whose license permits the experiment. Establish SFT formatting and masks first. Add DPO after validating pair provenance. Add PPO or GRPO when exact behavior tokens, probabilities, masks, group identity, and policy version are available.

Completion requires an actual checkpoint, pinned configuration, logs, data manifest, held-out comparison at equal budgets, confidence intervals, and regression analysis. Candidate JSONL exports do not complete this gate.

The [local feasibility audit](trainer-preprocessing-feasibility.md) found no installed exact tokenizer/template executor or trainer framework in the inspected runtimes. Public installed model metadata supplies vocabulary and template details, but that is not an executable preprocessing adapter or training checkpoint. This gate remains blocked without separately authorized, verified prerequisites.

## Cloud sandbox execution

Integrate one provider at the create-execute-snapshot-cleanup boundary. Keep the grader and secrets outside the agent workspace. Set network, resource, lifetime, queue, and spending limits before a run.

Completion requires permission and egress tests, cancellation cleanup, retries, measured cold and warm startup, concurrent throughput, and cost per accepted episode. Provider documentation does not complete this gate.

## Multi-tenant operations

Add authentication, per-tenant authorization, separate storage, quotas, audit logs, retention, deletion, recovery, and secret handling when a deployment calls for them. The development console is a local operator tool.

Completion requires tenant-boundary tests, recovery drills, data-rights records, deployment review, and incident procedures. Tenant IDs in a shared database do not establish isolation.

## Dataset release

Review accepted traces independently. Publish a manifest describing distribution, rights, redaction, selection, rejected samples, split construction, and limitations. Keep held-out and public evaluation material out of training corpora.

Completion requires record-level rights, reproducible selection, replay checks, cross-split deduplication, and an actual deletion process. Trace volume does not replace these checks.

The [scripted candidate corpus results](scripted-candidate-results.md) record 128 verified episodes on 64 tasks at `5e5eb0d9`: 64 clean reference passes, baseline zero business passes, 620 decisions and no retries/inconclusive/unattempted slots. Measured task splits are 51/6/7 train/validation/test; exports contain 397 train SFT decisions, 51 strict DPO pairs and 51 mixed-policy nontrainable groups. Thirteen heldout reference cases are excluded per export. Independent replay, actual Harbor validation and exact export reconstruction establish data consistency, not trained-model improvement or family generalization. No model/tokenizer/training/cloud calls occurred.

The pure native-ledger builder's 76 tests precede SDK integration at `d71a05d`: explicit v2 opt-in, unchanged default v1, trusted-reset request regeneration and protocol/module/eligibility guards. Root verified 1,196 tests, six optional skips, Ruff and frontend build at that source. The [later sixteen-attempt comparison](../artifacts/access-ledger-study/20261010-v1/report.json) at `cc2d4956` completes one locked eight-pair access measurement: both protocols passed zero tasks, with eight paired neither outcomes. V1 timed out eight times; v2 finished three times and reached max steps five times without settlement. All sixteen replay/Harbor and 48 training exclusions were checked. A cache/causal speed claim, full-token-context guarantee or successful discovery policy remains unestablished.
