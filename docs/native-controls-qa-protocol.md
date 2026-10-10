# Native Controls QA Protocol

This collector inspects configuration controls, not model execution. It creates no
rollouts, imports, downloads or cancellations and never presses Start. Historical
native receipt inspection and measured model studies remain separate evidence.

## Locked Checks

Protocol `native-controls-read-only-v1` has SHA-256
`d05f475561417eafb642317e84a1297e001c70eddbf4da6e62bfa1f46753ec77`,
computed from the collector's ordered JSON protocol object. At 1440x960,
390x844 and 360x844, it checks:

- Initial legacy concurrency is 4 and evaluation-only is editable.
- Selecting either native alias sets concurrency to 1, selects public
  `qwen3:8b`, locks evaluation-only true and exposes no paid consent control.
- Explicit concurrency 2 survives a switch between native aliases.
- Legacy local concurrency and evaluation-only remain editable.
- Every dialog closes with Cancel, without submitting a run.

One worker is a conservative native default, not a hard cap or a claim that it is
optimal for every model. Twelve screenshots show closed model dropdowns. No other
installed model or weights are inspected.

## Run

Default execution is a pure plan with no output, source commands, browser or API
contact:

```sh
node scripts/qa-native-controls.mjs --plan
```

Actual collection requires separate operator authorization after source review,
commit, CI and an operator-owned API restart. Use a new output root:

```sh
node scripts/qa-native-controls.mjs --collect \
  --source-revision REVIEWED_FULL_40_CHARACTER_SHA \
  --api-startup-revision OPERATOR_ATTESTED_FULL_40_CHARACTER_SHA \
  --output artifacts/native-controls-qa/NEW_RUN
```

`WORLD_ENGINE_UI_URL` defaults to `http://127.0.0.1:5173`. Only a loopback origin
without credentials or URL parameters is accepted. Existing files, directories,
live symlinks and dangling symlinks at the output path are rejected before source
commands or browser activity. No historical evidence is overwritten or pruned.

## Safety And Evidence

The browser gate accepts only same-origin GETs. API paths are limited to health,
providers, environments and the run list. Every request is fetched with redirect
following disabled; redirect responses are aborted before browser fulfillment.
POST, PUT, PATCH, DELETE, other methods, nonlocal requests and redirected requests
are blocked. Service workers and WebSocket connections are disabled. A forbidden request fails the receipt;
the report distinguishes blocked attempts from zero forwarded mutations.

The public catalog is read mechanically for UI readiness. The receipt persists
only the two native alias IDs, local kind, configured/opt-in flags and a boolean
confirming the exact public model is available. It does not save catalog bodies,
other installed model names, remote configured flags, keys, headers or daemon
metadata. GET accounting retains whitelisted API paths and a generic UI-asset
label, not arbitrary URLs. Errors omit supplied values and underlying details.

Health must report package version `0.1.0`, idle execution and paid calls disabled.
That package version does **not** prove an API source revision. The optional
startup revision is an operator declaration, separately supplied after restart,
not cryptographic remote attestation. The collector records and rechecks its own
reviewed HEAD and hashes of runtime, frontend, dependencies and collector scope
before browser startup and after finalization. Full-checkout dirtiness is reported
separately; unrelated new files outside the declared scope are not source-gate
failures and are never silently described as a clean whole checkout.

Published screenshots, video and report are limited to 64 MiB, with 1 MiB reserved
for the report. Files are created exclusively. Playwright records video in a
private temporary directory; its size is checked after context close before
publication. This is **not** a hard transient recording disk quota. An oversized
video causes a stopped result rather than valid video evidence. Temporary files
are removed during cooperative finalization.

The 120-second cooperative overall budget reserves 15 seconds for finalization;
work stops after 105 seconds. Browser operations have short timeouts. These bounds
do not guarantee hard preemption of a hung or malicious browser extension. A
finalization failure is reported honestly, retaining already published artifacts.
Source/fresh-output preflight failures can stop before any report is produced.

Offline tests exercise no-activity planning, output preservation, redaction,
metadata projection, redirect/mutation gates, artifact bounds and fake modal
transitions. Actual connected browser evidence is collected only after separate
authorization; passing these tests alone is not a connected UI result.
