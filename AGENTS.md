# Repository guidance

World Engine is a local workflow environment, evaluation, and trace-curation platform. Read `docs/OPERATIONS.md` and `coordination/BUILD.md` for current delivery status. Dated reports and receipts describe their pinned collection revisions, not every later implementation. The failure-to-intervention prototype and older coordination proposals are historical references.

## Work and ownership

- Read the relevant implementation and callers before changing a contract. Keep changes scoped to the requested behavior.
- Use the standard library and existing dependencies before adding a framework or abstraction. Add a boundary only when it owns a rule or a real external integration.
- Keep environment transitions, grading, rollout execution, persistence, and HTTP parsing owned by their existing modules.
- Keep each PR atomic and passing CI. For this rebuild, the user explicitly requested Git and GitHub delivery, overriding the general preference for Graphite. Check current task instructions before changing the Git workflow.
- Keep market research, external-company comparisons and private strategy documents outside the public repository, including reports, PDFs, PR descriptions and commit messages. Public guides describe implemented contracts and measured evidence. Preserve required licenses, source attribution and functional integration identities.
- Before publication, run `scripts/check_publication.py` with an operator-owned term list outside Git. Stage intended public files first; the check inspects tracked names, text, gzip records and PDF text/links, not untracked files, image/video pixels or Git/PR history. Review media separately and never commit the private term list.
- Do not revert changes made by another worker. Use `coordination/BUILD.md` to understand active ownership. Its designated owner updates the board.

## Environment correctness

- Every episode owns its mutable state. Eliminate cross-episode sharing before introducing locks.
- Validate inputs at HTTP, configuration, provider-response, and tool boundaries. Internal code uses parsed types with explicit state transitions.
- Production validation must use explicit guards, never `assert`: Python `-O` removes assertions. The AST regression scans production modules; tests/examples may use assertions, but validation must not depend on them.
- A seed is not proof of deterministic replay. Control or record random choices, time, IDs, external responses, and action ordering.
- Keep terminal completion, budget truncation, cancellation, provider failure, and environment failure distinct in persisted evidence.
- New worlds use binary business-outcome reward by default. Preserve diagnostic checks separately; unchanged safety constraints and `finish` alone must not earn positive outcome reward. Existing shaped-reward contracts require an explicit versioned change, not silent reinterpretation of historical receipts.
- Respect provider ownership: the manager owns one provider per batch, direct rollout owns an internally created provider, and a supplied rollout provider belongs to its caller. Cleanup failures must preserve finalized evidence, terminal outcome coherence, admission release, and redacted errors. Cooperative deadlines do not prove actual resource closure.
- Preserve task, environment, grader, policy, and export schema revisions when the format supports them. Investigate replay mismatches rather than silently replacing values.
- Check fingerprint inputs before changing a shared module. Keep adapter-only configuration separate from domain and grader schemas; adding a provider must not silently invalidate historical world evidence. Test representative pinned receipts alongside the new entry point.
- Validate imported episode outcome labels and lineage against replayed trusted state. Module/class fingerprints do not recursively attest external helpers; retain dependency and source manifests.
- Regrading creates a new recorded decision. Keep the original grade and evidence.

## Grader and data boundaries

- Grade trusted state and committed effects. Never accept the agent's final answer as proof a transaction occurred.
- Anchor the whole operational state, immutable metadata, role/target permissions, prior history, generated identities, and exact change certificates to trusted initial facts. Checking selected fields or operation names is insufficient. Audit missing/extra/duplicate/misordered events must not retain full credit.
- Graders must not call operational `apply`, replay, or a scripted provider to determine authorization. Independently validate legal contract states/certificates. Preserve legitimate partial progress, all allowed operation orders, optional approvals, and idempotent retries; only actual changes produce audit certificates.
- Test preservation of unrelated records, permissions, idempotency, and known reward exploits alongside positive reference executions.
- Do not expose private expected values, protected grading code, sealed evaluation fixtures, credentials, or operator-only snapshots in agent observations or training exports.
- Hidden tests inside an agent-readable filesystem are not hidden. For untrusted code, isolate the evaluator outside the agent's writable environment.
- The in-process Python environments are trusted simulations, not arbitrary-code security sandboxes. State this limit in provider and security documentation.
- Retain failed and rejected traces with their reasons. Curation must not erase selection-bias evidence.
- DPO candidates share the same task and comparable initial conditions. Raw grouped rollout JSON is not trainable GRPO data without exact sampled tokens, behavior probabilities, context, masks, and policy identity.
- Respect benchmark canaries and evaluation-only terms. Keep protected benchmark tasks and held-out fixtures out of training exports.
- Record source rights, permitted use, attribution, redaction, and deletion requirements before ingesting external data. Publicly readable and open source do not mean public domain.

## Verification and claims

- For real-application browser work, read `docs/gitlab-browser.md`, `docs/gitlab-runtime.md`, and `docs/gitlab-browser-protocol.md`. Do not combine browser attempts with synthetic episode metrics or export them as training data.
- Browser actions use the current observed node IDs. Do not give the policy reset APIs, controller credentials, Docker access, arbitrary JavaScript, or sealed grading inputs.
- Close the browser and finalize its video before stopping ingress and application writers, sealing authoritative state, and invoking the separate verifier. Uncertain closure or cleanup must block further admission.
- Keep browser JSONL journals authoritative and SQLite indexes rebuildable. Persist exact inference requests and raw replies before accepting actions; preserve rejected replies and partial failures.
- Restart the API at the pinned revision before a fixed collection. File hashes taken at submission do not prove which Python objects an already-running server loaded.
- Keep the local GitLab pilot at one active attempt per controller. Its host-browser/Docker boundaries, cooperative quotas and selected-table grader are not a multi-tenant service or full GitLab fidelity certificate.

- Verify actual runtime artifacts. Run focused checks, inspect API values and exports, and exercise the console on desktop and mobile after user-facing changes.
- Keep a reproducible command and evidence for every benchmark claim. Record machine, revision, workload, policy, seed, budget, errors, and sample count.
- Collect into an explicit fresh directory and refuse existing files, directories, or symlinks before performing work. Never prune or replace another run's raw evidence, screenshots, videos, or failure receipts. Preserve stopped and unattempted outcomes alongside successful attempts.
- Commit and review runtime, collector, and fixed experiment protocol before model collection. Pin the exact revision, model identity, task sample, budgets, attempt order, retry policy, and analysis. Keep the pinned source unchanged until collection finishes; tuning or retries require a separate protocol and receipt.
- Do not generalize a tiny local model experiment into overall capability. Do not claim production transfer, 100% fidelity, security certification, or competitor superiority without corresponding evidence.
- Separate measured facts, documented external claims, and proposed designs in docs. Cite primary sources for technical comparisons.
- Do not make paid model calls, provision paid cloud resources, download large models, create accounts, or send external messages without explicit user authorization. Existing local resources can support bounded experiments.
- Keep credentials and private data out of code, logs, exports, screenshots, and commits. Bind the development API to loopback by default.
