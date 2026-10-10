# Roadmap and evidence gates

Updated 2026-10-10. Each milestone requires evidence before the repository describes it as complete.

## Local platform

The rebuild provides workflow worlds, a Python SDK, bounded rollout jobs, grades, persisted traces, replay, candidate training exports, and an operator console. Consult [operations](OPERATIONS.md) for exact commands and limits. The [build board](../coordination/BUILD.md) records verification status.

Completion requires reference and failing policies, permission-boundary tests, independent episode state, consistent replay, truthful export labels, a frontend build, and browser QA. A bounded local language-model experiment adds actual policy evidence. Report its sample count and costs.

## Real application parity

Select one task family and a pinned application revision. Compare transitions, permissions, observations, timing, and outcomes against the real application. Have a domain expert independently review feasibility and grading.

Completion requires differential tests, a disagreement ledger, repaired mismatches, and a fidelity statement scoped to the validated task distribution. A simulated UI does not complete this gate.

## Public benchmark integration

Run a licensed public task with pinned source, image digest, bounded local compute, and evaluator separation. Respect no-training canaries. Disclose protocol adaptations, including preinstalled verifier dependencies and resource changes.

Completion requires a run receipt, saved model actions, original revision, grader outcome, cleanup evidence, and a reproducible command. An oracle pass proves feasibility. A model pass is one observed attempt.

The rebuild delivers one separate, adapted Terminal-Bench task runner with pinned source, recorded images, separate verification, a passing reference, and a failing negative control. Its bounded local-model attempt produced no executable command because JSON responses were truncated. [The protocol and evidence](public-benchmark.md) satisfy a local integration check, not broad benchmark coverage or the official leaderboard protocol. Wider task coverage and native Harbor job integration remain future work.

## Trainer integration

Choose an established trainer and a small open model whose license permits the experiment. Establish SFT formatting and masks first. Add DPO after validating pair provenance. Add PPO or GRPO when exact behavior tokens, probabilities, masks, group identity, and policy version are available.

Completion requires an actual checkpoint, pinned configuration, logs, data manifest, held-out comparison at equal budgets, confidence intervals, and regression analysis. Candidate JSONL exports do not complete this gate.

## Cloud sandbox execution

Integrate one provider at the create-execute-snapshot-cleanup boundary. Keep the grader and secrets outside the agent workspace. Set network, resource, lifetime, queue, and spending limits before a run.

Completion requires permission and egress tests, cancellation cleanup, retries, measured cold and warm startup, concurrent throughput, and cost per accepted episode. Provider documentation does not complete this gate.

## Multi-tenant operations

Add authentication, per-tenant authorization, separate storage, quotas, audit logs, retention, deletion, recovery, and secret handling when a deployment calls for them. The development console is a local operator tool.

Completion requires tenant-boundary tests, recovery drills, data-rights records, deployment review, and incident procedures. Tenant IDs in a shared database do not establish isolation.

## Dataset release

Review accepted traces independently. Publish a manifest describing distribution, rights, redaction, selection, rejected samples, split construction, and limitations. Keep held-out and public evaluation material out of training corpora.

Completion requires record-level rights, reproducible selection, replay checks, cross-split deduplication, and an actual deletion process. Trace volume does not replace these checks.
