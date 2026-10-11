# Provider cleanup

The scheduler owns one provider per batch. Direct `rollout(config, index)` owns
its internally created provider; `rollout(config, index, provider)` borrows the
caller-owned provider and does not prepare or close it.

Provider cleanup uses a two-second cooperative timeout. Ordinary exceptions,
timeouts, and cancellation produce redacted cleanup outcomes rather than
discarding finalized episode evidence. This does not hard-preempt a malicious
extension that blocks the event loop or suppresses cancellation. A timeout does
not prove that an external connection, process, or resource was closed.

## Batch Outcomes

Completed episodes remain append-only and unchanged when shared-provider cleanup
fails. A normally completed batch becomes `failed`, with a safe cleanup error.
Explicit cancellation and shutdown remain `cancelled` and `interrupted`, including
requests arriving during cleanup. A primary preparation or execution error is
not replaced by a secondary cleanup error; the batch error retains the primary
reason and appends a fixed redacted cleanup reason. Terminal persistence is attempted
before admission is released; admission release still occurs if persistence
raises. Closing the manager releases its database owner lease. Resource cleanup
and scheduler admission/lease release are distinct outcomes.

Queued cancellation starts the ownership finalizer without preparing the provider
or beginning an episode. Repeated cancellation waits for the same finalizer;
it does not repeatedly cancel resource cleanup.

## Direct Episode Outcomes

An owned provider with a close method adds `provider_cleanup`, containing schema
`world-engine.provider-cleanup.v1`, status (`completed`, `failed`, `timeout`, or
`cancelled`), and a fixed redacted error or null. Failed or timed-out cleanup makes
an otherwise completed episode `failed`; cancellation during cleanup makes it
`cancelled`. The original execution termination and diagnostic grader remain
recorded. Authoritative reward is zero and passed is false when cleanup fails.
Preparation failure produces no fabricated episode and preserves its primary
safe error after attempting cleanup.

Replay checks cleanup metadata and outcome-label coherence. It does not attest
that cleanup actually occurred or that resources were closed. Missing cleanup
metadata remains compatible with older episodes. Failed, timed-out, and cancelled
cleanup evidence is operator-only: all SFT, DPO, and grouped rollout exports and
their alternative candidate pools exclude it, even with `quality=all`. Raw trace
exports retain the cleanup outcome and mark these records training-ineligible.

## Verification

```sh
uv run pytest tests/test_provider_lifecycle.py tests/test_runs.py
uv run ruff check src/world_engine/rollout.py src/world_engine/exports.py tests/test_provider_lifecycle.py
```

Tests use local scripted and mock providers only; no model calls are needed.
