# GitLab browser pilot collection protocol

This protocol qualifies the first local real-application browser workflow. It is
not a model-training experiment, a production-fidelity certification, or a
throughput comparison with another provider.

## Fixed collection

Collection `20261010-v3` uses task `1.0.2`, grader `gitlab-state-v3`, and the
`ollama-browser-tools-v2` policy protocol. Collection
`20261010-v1`, pinned at `248facd`, remains unchanged: its positive browser control
posted the requested ordinary comment and closed the target, but the v2 grader
incorrectly expected a closure system note and rejected GitLab's legitimate
`updated_by_id` change. The model was never attempted. A fresh collection must
qualify both controls again; the old outcome is not rewritten or reused.

Collection `20261010-v2`, pinned at `878667`, qualified both controls. Its local
model attempt failed before any browser action: the complete first HTTP 200
reply had empty assistant content and no tool call. Keep that reply and outcome
unchanged. Ollama 0.22.0's tool-parameter type drops the root `oneOf` and
`discriminator` fields used by the previous adapter. This is a wire-format
compatibility defect, not proof that it alone caused the empty reply.
The new protocol exposes seven separately named browser tools with ordinary
object parameter schemas. The controller derives action kind from the validated
tool name, checks strict argument types and bounds, and accepts exactly one call.
It does not accept JSON text as a fallback. See the
[pinned Ollama API types](https://github.com/ollama/ollama/blob/v0.22.0/api/types.go)
and [official tool examples](https://docs.ollama.com/capabilities/tool-calling).

This is a new integration qualification, not a retry within v2 or a comparable
model-capability experiment. No task, grader, model weights, context budget,
generation settings, action budget, or timeout changes accompany this repair.

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
For GitLab 19.4, authorized closure is certified by its persisted state event,
ordinary actor and updater, not a nonexistent closure system note. Require exactly
one new ordinary comment, preserve prior notes, and verify that comment predates
the target closure and state event. Reject extra comments, system notes, events,
wrong actors, internal notes and unrelated changes.

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
