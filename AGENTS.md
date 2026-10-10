# Repository guidance

World Engine is a local workflow environment, evaluation, and trace-curation platform. Treat `docs/report/world-engine-report.md`, `docs/OPERATIONS.md`, and `coordination/BUILD.md` as current guidance. The failure-to-intervention prototype and older coordination proposals are historical references.

## Work and ownership

- Read the relevant implementation and callers before changing a contract. Keep changes scoped to the requested behavior.
- Use the standard library and existing dependencies before adding a framework or abstraction. Add a boundary only when it owns a rule or a real external integration.
- Keep environment transitions, grading, rollout execution, persistence, and HTTP parsing owned by their existing modules.
- Keep each PR atomic and passing CI. For this rebuild, the user explicitly requested Git and GitHub delivery, overriding the general preference for Graphite. Check current task instructions before changing the Git workflow.
- Do not revert changes made by another worker. Use `coordination/BUILD.md` to understand active ownership. Its designated owner updates the board.

## Environment correctness

- Every episode owns its mutable state. Eliminate cross-episode sharing before introducing locks.
- Validate inputs at HTTP, configuration, provider-response, and tool boundaries. Internal code uses parsed types with explicit state transitions.
- A seed is not proof of deterministic replay. Control or record random choices, time, IDs, external responses, and action ordering.
- Keep terminal completion, budget truncation, cancellation, provider failure, and environment failure distinct in persisted evidence.
- Preserve task, environment, grader, policy, and export schema revisions when the format supports them. Investigate replay mismatches rather than silently replacing values.
- Validate imported episode outcome labels and lineage against replayed trusted state. Module/class fingerprints do not recursively attest external helpers; retain dependency and source manifests.
- Regrading creates a new recorded decision. Keep the original grade and evidence.

## Grader and data boundaries

- Grade trusted state and committed effects. Never accept the agent's final answer as proof a transaction occurred.
- Test preservation of unrelated records, permissions, idempotency, and known reward exploits alongside positive reference executions.
- Do not expose private expected values, protected grading code, sealed evaluation fixtures, credentials, or operator-only snapshots in agent observations or training exports.
- Hidden tests inside an agent-readable filesystem are not hidden. For untrusted code, isolate the evaluator outside the agent's writable environment.
- The in-process Python environments are trusted simulations, not arbitrary-code security sandboxes. State this limit in provider and security documentation.
- Retain failed and rejected traces with their reasons. Curation must not erase selection-bias evidence.
- DPO candidates share the same task and comparable initial conditions. Raw grouped rollout JSON is not trainable GRPO data without exact sampled tokens, behavior probabilities, context, masks, and policy identity.
- Respect benchmark canaries and evaluation-only terms. Keep protected benchmark tasks and held-out fixtures out of training exports.
- Record source rights, permitted use, attribution, redaction, and deletion requirements before ingesting external data. Publicly readable and open source do not mean public domain.

## Verification and claims

- Verify actual runtime artifacts. Run focused checks, inspect API values and exports, and exercise the console on desktop and mobile after user-facing changes.
- Keep a reproducible command and evidence for every benchmark claim. Record machine, revision, workload, policy, seed, budget, errors, and sample count.
- Do not generalize a tiny local model experiment into overall capability. Do not claim production transfer, 100% fidelity, security certification, or competitor superiority without corresponding evidence.
- Separate measured facts, documented external claims, and proposed designs in docs. Cite primary sources for technical comparisons.
- Do not make paid model calls, provision paid cloud resources, download large models, create accounts, or send external messages without explicit user authorization. Existing local resources can support bounded experiments.
- Keep credentials and private data out of code, logs, exports, screenshots, and commits. Bind the development API to loopback by default.
