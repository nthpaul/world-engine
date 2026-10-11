# Real GitLab browser results

Collected locally on 2026-10-10. Phases 1--3 now have a real application runtime,
isolated persisted-state grading, durable browser traces, an operator console,
and a Python SDK. This is a single-workflow local pilot, not full GitLab parity,
a hosted sandbox fleet, or a trained model.

Start with the [architecture and SDK guide](gitlab-browser.md), then inspect the
[successful reference](http://127.0.0.1:5173/#attempts/65290263-20e0-4895-97eb-19ac5c2a418b)
and the [failed model attempt](http://127.0.0.1:5173/#attempts/bddafe06-9cc8-4289-9e68-f3714b051e5c).
Those local history links require this collection's operator database. The files
linked below remain usable without that database.

## What actually ran

GitLab CE 19.4.1 runs with its real PostgreSQL, Redis and ordinary browser UI.
Each attempt gets fresh volumes, accounts, networks and browser context. The
original fixture has a private Release Operations project, three identically
titled issues with distinct deployment markers, and existing comments. The task
requires discovery of marker `REL-2026-1042`, one exact ordinary comment, and
closure of that issue without changing unrelated records or access.

The model receives the public task and a bounded accessibility tree, not a
synthetic state description. Its tools act on current observed browser node IDs.
The model does not receive screenshot pixels in this adapter; screenshots and
video are operator evidence. Navigation, page rendering, editor behavior, HTTP
requests and committed GitLab effects are real. Background jobs, integrations,
credential management, runners and broader settings workflows are outside this
task's fidelity.

The final fixed cohort used committed source
`222c9d22b89f92bea43fc7ad7404f750854e8111`. The API was restarted at that revision
before collection. Source stayed unchanged through collection and terminal
console QA. File hashes and operator startup attestations are consistency
evidence, not cryptographic proof of loaded code or host authenticity.

| Pin | Value |
| --- | --- |
| Task / grader | `gitlab-issue-close` `1.0.2` / `gitlab-state-v3` |
| Fixture SHA-256 | `2c22491ac0393855fe2588934129d90f6711a409a45f7586b08bde564560dcbd` |
| GitLab image | `sha256:7fff8748a25202c1d38885797510afe055f555856f3f50c2b17466a853be5d24` |
| Browser stack | BrowserGym 0.14.3, Playwright 1.44, cached Chromium 156.0.8078.4 |
| Local model | Already-installed `qwen3:8b`, Ollama 0.22.0 |
| Model digest | `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41` |
| Policy protocol | `ollama-browser-tools-v2` |
| Model settings | temperature 0, 512 predicted tokens, 16,384 context, thinking off |
| Sampling / admission | Seed 42, one active attempt, no automatic retries |

The [committed collection protocol](gitlab-browser-protocol.md) fixes attempt
order and budgets. Incomplete control gets one action / 30 seconds; reference
gets 30 / 180 seconds; model gets 30 / 600 seconds. These interaction deadlines
exclude startup and finalization. No paid calls, cloud resources, external accounts,
new model weights or training runs were used.

## Outcomes, including original failures

Each row is one attempt, not an independent task sample. Do not pool these
versioned qualifications into a model capability score. A reference is a
scripted public-AX feasibility control, not a learned policy.

| Cohort / source | Incomplete control | Reference | Local model |
| --- | --- | --- | --- |
| [v1 receipt](../artifacts/gitlab-browser/20261010-v1/receipt.json) / `248facd` | 1 action, reward 0 | 15 actions, original reward 0; grader false negative | Unattempted after qualification stopped |
| [v2 receipt](../artifacts/gitlab-browser/20261010-v2/receipt.json) / `878667` | 1 action, reward 0 | 15 actions, all seven checks pass, reward 1 | Provider error before any action, reward 0 |
| [v3 receipt](../artifacts/gitlab-browser/20261010-v3/receipt.json) / `222c9d22` | 1 action, reward 0 | 14 actions, all seven checks pass, reward 1 | 30 valid actions, `max_steps`, reward 0 |

All admitted attempts completed ownership-certified cleanup. V1 correctly
submitted the comment and closed the issue, but its grader prohibited the
ordinary actor's legitimate `updated_by_id` change and expected a closure system
note that GitLab's Work items action does not create. The versioned v3 grader
instead checks the actual persisted closure event. Diagnostic regrading passes
the old seal; the original grade and bytes remain unchanged.

V2 retained a complete HTTP 200 reply with empty assistant content and no tool
call. The previous adapter sent a discriminated-union root schema that Ollama
0.22.0's tool-parameter type does not preserve. That is a definite compatibility
defect, not proof that it alone caused the empty reply. The repair exposes seven
ordinary object-schema tools, validates exactly one call, and keeps strict
controller bounds. It adds no JSON-text fallback or retry. V3 is a fresh
integration qualification, not a replacement for the rejected v2 attempt.

In v3 the model chose the observed "New project" link, then clicked the New
project breadcrumb 29 more times. All 30 calls were valid browser actions. It
never discovered the assigned project or issue and made no covered task-state change.
The three preservation checks passed; the four business checks failed. The
completed lifecycle means evidence was finalized, not that the task succeeded.
This sample demonstrates a navigation/repetition failure, not learning or a
general model capability estimate. No further tuning or model attempts followed.

All 30 exact requests and complete raw replies were retained. Independent
review reconstructed each request from the preceding public AX observation,
the bounded 12-action history, fixed tool definitions and settings. The bodies
match recorded request hashes and contain no hidden grading context. Reported
usage is complete for these replies: 78,421 input tokens and 660 output tokens.
These are daemon usage counts, not sampled token IDs or behavior logprobs.

## Timing and storage

These are single local measurements on an ARM macOS host with 64 GiB memory and
a Docker Desktop VM reporting 16 CPUs and about 7.65 GiB memory. The GitLab
container has a 4 GiB / four-CPU limit. Images were cached, but each database and
application instance was fresh. No browser concurrency benchmark was run.

| V3 phase, seconds | Incomplete | Reference | Model |
| --- | ---: | ---: | ---: |
| Startup | 161.474 | 152.917 | 157.264 |
| Browser rollout | 0.517 | 12.024 | 73.225 |
| Browser/video closure | 0.343 | 0.152 | 0.654 |
| State sealing | 28.467 | 27.131 | 29.010 |
| Detached grading | 0.202 | 0.195 | 0.195 |
| Cleanup | 0.854 | 0.880 | 0.885 |
| End to end | 191.870 | 193.316 | 261.488 |

End-to-end time includes additional lifecycle work, so the rows need not sum
exactly. Ollama's summed reported `total_duration` is 56.474 seconds across the
30 model replies; that is different from browser rollout wall time.
Startup and sealing dominate the successful control. Snapshot/fork or warm
instance work needs reset-isolation proof before it can claim useful speedups.

The v3 collector produced 737 original files / 21,772,903 bytes, including
342 hash-chained journal records, 334 API responses and 51 registered media
artifacts / 10,712,903 bytes. The model has 229 journal records, 31 observation
screenshots and one video. Independent audits checked journal chains, exact
request/reply hashes and all registered media sizes/digests. Console QA and
decoded-video QA are separate additional evidence, not part of those totals.

## Grading and isolation

Browser closure and video flushing precede sealing. The controller stops ingress
and application writers, exports a read-only repeatable-read state projection,
then stops the app. A separate nonroot, read-only, network-disabled verifier
receives the private seal over stdin. It has no app mounts, Docker socket or
administrator credentials. Seals remain private and are not published here.

The verifier requires the ordinary actor's exact comment and authorized closure,
an exact actor/issue/namespace closure certificate, ordered timestamps, preserved
prior notes, and unchanged unrelated issues and access. It grades persisted
effects, never the policy's success claim. The reference seal hash is
`aba6c9d669c058be5b3a2cce0a54e34d0d7b9867064b77861d90a8a59fc3e0a4`;
the unchanged model seal hash is
`8968c67781afaac4acf52bcab36932e663f319dae2897da836c80dd999cc3039`.

The covered-table projection is not a full database/repository certificate.
Docker and the host browser assume a trusted local operator. HTTP routing is
not an OS-level or all-transport boundary, and this Docker daemon's raw-iptables
warning prevents network-security certification. There is no tenant-safe hosted
execution, killable native browser worker, daemon TTL after host crash, or hard
media disk quota. Uncertain closure or cleanup blocks further admission.

After v3, independent owner-label checks found no owned containers, volumes or
networks. Unrelated Docker services were preserved. The legacy database stayed
at 15 runs / 81 episodes / 43 events with integrity `ok`, no active runs, and
exactly unchanged logical row hashes across this browser collection.

## Screenshots and video QA

The successful reference's [final screenshot](../artifacts/gitlab-browser/20261010-v3/reference/screenshots/0014.png)
shows the exact posted comment and Closed issue. Its
[14.48-second browser recording](../artifacts/gitlab-browser/20261010-v3/reference/video/9be7abeafee18ecd123cd092692adf52.webm)
captures the real GitLab workflow. The model's
[final screenshot](../artifacts/gitlab-browser/20261010-v3/model/screenshots/0030.png)
and [74.04-second browser recording](../artifacts/gitlab-browser/20261010-v3/model/video/d1cc615dd4d28208deb36c7f6c9e4597.webm)
show its actual New project loop.

| Terminal console QA | Checks | HTTP GETs | Screenshots | New attempts / inference |
| --- | ---: | ---: | ---: | --- |
| [Reference report](../artifacts/browser-console/qa/20261010-gitlab-v3-reference/report.json) | 41 passed | 58 | 11 | 0 / 0 |
| [Model report](../artifacts/browser-console/qa/20261010-gitlab-v3-model/report.json) | 57 passed | 74 | 11 | 0 / 0 |

Both runs inspected Browser, Timeline and Outcome at desktop, 390px and 360px,
plus desktop catalog/history. All 48 registered reference/model media digests
matched. There were no browser errors, blocked requests or mutations; each QA
used one explicitly scoped local Vite HMR socket. Source and startup pins were
checked before and after. Recorded-video playback advanced from zero to about
0.248 seconds and from zero to ten decoded frames on desktop. Mobile playback
advancement was not separately verified. Both rollout and console videos fully
decode, and reviewers inspected all screenshots and sampled decoded frames.

The [reference console recording](../artifacts/browser-console/qa/20261010-gitlab-v3-reference/video/page@93e2c8ac0f5215cdba51cb46ec204878.webm)
and [model console recording](../artifacts/browser-console/qa/20261010-gitlab-v3-model/video/page@62f7d323a678e06d443c90db146f86b9.webm)
are QA recordings, not substitute rollout videos.

Separate timestamped frame checks passed for the
[reference](../artifacts/gitlab-video-qa/20261010-v3-reference/receipt.json)
and [model](../artifacts/gitlab-video-qa/20261010-v3-model/receipt.json).
The [incomplete-control pixel QA](../artifacts/gitlab-video-qa/20261010-v3-incomplete/receipt.json)
failed: its 1.2-second recording has a nearly blank context-startup frame at
0.12 seconds, while its 0.6- and 1.08-second frames show GitLab. The video decodes;
the original failed QA receipt is retained without weakening the threshold or
recollecting. Do not describe every recording QA as passing.

## Verification and remaining gates

At runtime source `222c9d22`, the local suite passed 2,079 tests with six optional
skips. Ruff and the TypeScript/Vite build passed. The built wheel contains the
exact repaired browser policy and six canonical packaged GitLab assets. GitHub
delivery is dependent atomic PRs [57](https://github.com/nthpaul/world-engine/pull/57),
[58](https://github.com/nthpaul/world-engine/pull/58), and
[59](https://github.com/nthpaul/world-engine/pull/59), followed by this results
publication. No merge was requested. Earlier test/report counts remain historical.

Next work should address a killable isolated browser worker and host-crash
reconciliation, then varied original tasks, a second real application and
expanded grading coverage. Only then measure useful concurrency and warm-reset
throughput. Browser trajectories remain evaluation-only; SFT/DPO/GRPO export and
training require separate rights, token/logprob, formatting and held-out
evaluation contracts. No competitor superiority or production transfer is
established by these controls.
