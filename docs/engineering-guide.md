# Environment engineering guide

This guide describes World Engine's contracts and the reasoning behind them.
Use the [operations guide](OPERATIONS.md) for commands, the
[architecture guide](architecture.md) for the Python workflow engine, and the
[browser guide](gitlab-browser.md) for real-application execution. Dated
experiment protocols and receipts retain their original sources and outcomes.

## Start with a workflow

An environment must model the decisions a worker actually makes: discover the
right record, inspect policy and dependencies, perform authorized changes,
handle failures, and verify the result. Visual resemblance alone does not prove
behavioral fidelity. A text observation can describe a real application; a
beautiful imitation can still have incorrect permissions or transaction rules.

Declare the covered behavior before collecting data. Specify roles, records,
dependencies, legal operation orders, retries, expected side effects, and what
must not change. A complete application image does not make every task realistic
or every effect visible to a selected-table grader.

World Engine has two distinct paths. The Python worlds are trusted in-process
simulations. The browser pilot runs real GitLab CE, using an ordinary account and
actual pages. Its first task covers issue discovery, one exact comment, and
authorized closure. Background jobs, integrations and broader application
workflows are outside that pilot's fidelity.

## Separate lifecycle ownership

A task pack identifies its application image, fixture, task version, seed,
observation mode, grader and permitted use. Runtime owns allocation, reset,
sealing, grading and cleanup. Driver owns observations, browser actions and
media. Policy owns inference. Storage owns durable evidence. Avoid giving one
component access merely because another component already has it.

Every episode owns mutable resources. Fresh volumes, accounts and browser
contexts reduce accidental cross-episode dependence. Warm reset or snapshot
forking needs evidence that it restores every relevant state, including caches,
background effects and permissions. A seed alone is not deterministic replay.

## Grade effects, not claims

Define the intended business outcome independently of the agent's final answer.
Check authorization and committed effects against trusted initial facts. An
agent saying "done" or preserving safety constraints without completing the task
must not receive positive business reward.

Preserve prior history, unrelated records, resource ownership and permissions.
Exact change certificates should constrain actors, targets, order, duplicates
and unexpected effects. Tests should cover valid completion and incomplete work,
wrong records, wrong actors, forged events, extra comments, duplicate operations,
missing history and attempts to alter evaluation evidence.

Reward hacking includes exploiting a weak score and tampering with the evaluator
or its inputs. Keep the evaluator outside the agent's writable environment. For
the browser pilot, close the browser and video first, stop ingress and writers,
seal authoritative state, then grade in a separate readonly, network-disabled,
nonroot container. The covered projection is not a certificate over every table,
repository or external effect.

## Keep the evidence before the effect

Persist command intent before executing it, and result before the next decision.
Record task, image, grader, policy and source identities. Retain exact model
requests and complete raw replies, including rejected responses and partial
failures. Hash chains and registered media digests establish local consistency,
not signed host authenticity.

Keep completion, action-budget truncation, cancellation, provider failure,
environment failure and cleanup failure distinct. Lifecycle completion is not
task success. Reference policies establish feasibility and grader behavior;
they do not demonstrate a learned model's capability.

Screenshots and recordings are separate from model observations. The current
text-model browser adapter receives bounded AX text and public action history,
not image pixels. Login credentials, cookies, private expected values and seals
must stay out of public observations and artifacts.

## Measure useful throughput

Report startup, reset, inference, interaction, state sealing, grading and cleanup
separately, then report end-to-end time. Count successful useful tasks, not just
started instances. Retain every failure and its cost.

Concurrency is an admission setting, not proof of CPU or GPU parallelism. Model
servers can queue overlapping client requests. Resource saturation can increase
latency, timeouts and failure rates. Pin workload, policy, budgets and sample
order before a comparison; distinguish repeated attempts from independent tasks.

The current browser pilot admits one active attempt. Its measured successful
reference used about 153 seconds of startup and 12 seconds of browser interaction.
Those observations motivate lifecycle work, not a claim of distributed throughput.
See the [browser results](gitlab-browser-results.md) for exact denominators.

## Separate evaluation data from training data

Record source rights, allowed use, attribution, deletion requirements and
redaction decisions. Public visibility is not permission to train or redistribute.
Keep held-out tasks, canaries, reference solutions and task-specific evaluation
feedback out of training candidates.

SFT needs exact consumed context, assistant targets and loss masks. DPO needs
comparable alternatives for the same prompt and initial conditions, with verified
preference labels. Policy-gradient training needs exact sampled token IDs,
behavior probabilities, context, masks, rewards, grouping and checkpoint
identity. Grouped JSON traces alone are not a trainable GRPO batch.

Keep one declared policy identity throughout each rollout. A version change or
stale sample needs an explicit treatment rule. A training claim needs an actual
checkpoint and controlled held-out evaluation; a trace export is not learning.
Browser episodes remain evaluation-only in this implementation.

## Treat local isolation honestly

The operator and Docker daemon are trusted. HTTP allowlists do not replace an
OS-level boundary or cover every browser transport. Cooperative deadlines do
not forcibly terminate a stuck native browser call. Uncertain closure, journal
finalization or cleanup must block admission.

A hosted service requires additional isolation, authentication, resource quotas,
crash reconciliation, expiring leases, secret management and tenant-aware storage.
The local pilot does not provide those guarantees. New applications and broader
tasks need expanded state coverage, adversarial grading tests and fixed
qualification protocols before collecting model evidence.
