# GitLab browser pilot collection protocol

This protocol qualifies the first local real-application browser workflow. It is
not a model-training experiment, a production-fidelity certification, or a
throughput comparison with another provider.

## Fixed collection

Run these attempts in the stated order, with no automatic retry. Every attempt
gets a fresh GitLab instance, database, accounts, network, and browser context.

| Attempt | Provider | Seed | Maximum actions | Interaction deadline |
| --- | --- | --- | --- | --- |
| Incomplete control | `browser-baseline` | 42 | 1 | 30 seconds |
| Public-AX reference control | `browser-reference` | 42 | 30 | 180 seconds |
| Local model | `local-browser`, `qwen3:8b` | 42 | 30 | 600 seconds |

The controls test feasibility and grading, not model capability. The model
attempt is one sampled task. Report it whether it succeeds, fails, is cancelled,
or encounters an infrastructure error. Changes to the policy, task, application,
grader, or budgets require a new protocol and a separate collection directory.
If either control fails its required outcome or cleanup, stop collection and
retain all later attempts as unattempted. Correct infrastructure in a separate
revision and collection; never silently replace the failed qualification.

Commit the runtime, policy, collector, and protocol before model collection. Pin
the Git revision and source hashes, application image digest, grader image and
source hashes, local model digest, BrowserGym/Playwright/browser versions, seed,
budgets, timestamps, and all terminal/cleanup outcomes. Existing unrelated
untracked evidence may remain but must be listed, not silently treated as clean
source. Untracked runtime or collector code prevents collection.

## Required evidence

Record each command intent durably before its browser effect, and each observed
result before the next decision. Keep exact model request bodies and raw replies,
including rejected replies. Distinguish the AX text actually sent to the text
model from screenshots retained for operator review.

Capture the post-login browser video and every observation screenshot. Never
record login credentials, authentication cookies, reset tokens, admin API
headers, or private expected-state inputs in public traces. Keep finalization
evidence and failed attempts; do not replace files in an existing directory.

After closing the browser, stop ingress and application writers before exporting
authoritative state. Grade that sealed export in a separate read-only,
network-disabled, nonroot verifier container with no app mounts, host socket,
model credentials, or admin credentials. Record the seal hash and verifier checks.
Validate the positive control, rejection of the incomplete control, unchanged
unrelated records and permissions, and cleanup of owned containers/volumes/networks.

## Operator QA

Check the actual console at desktop, 390px, and 360px widths. Inspect task
selection, admission, lifecycle transitions, captured browser state, exact
model observation, timeline selection, outcome, errors/cancellation, and video
playback. Check the decoded video has changing, nonblank frames corresponding
to the real screenshots. Save both screenshots and recordings with a QA receipt.

No paid resources, cloud accounts, model downloads, or remote provider calls are
part of this protocol. Local Docker plus a host browser is a trusted-operator
development configuration, not an untrusted multi-tenant isolation guarantee.
Media is checked against a 96 MiB cooperative budget at observation and closure;
the 128 MiB episode budget reserves space for the journal and terminal evidence.
Neither checkpoint is a hard filesystem quota while recording is in progress.
Browser actions and closure use a synchronous Playwright worker thread. A stuck
native call cannot be forcibly terminated by an asyncio deadline; grading and
admission fail closed on uncertain closure. A killable browser worker is required
before advertising strict cleanup bounds or accepting untrusted tenants.
