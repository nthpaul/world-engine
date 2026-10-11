# Locked real-model admission study

Status: collector implemented, not authorized for collection, October 10, 2026.
Only offline mocked tests have run. No model execution or result is claimed.
Root must review the collector, tests and exact protocol digest, commit CI-green
source, and separately authorize collection. This document does not authorize
inference.

## Question and scope

Does allowing two overlapping workflow episodes, rather than one, improve
observed verified business passes per batch wall second on the same local
model and task sample? This collector measures SDK caller-wave admission, not
RunManager or HTTP API throughput. Each batch shares one prepared provider and
admits fixed ascending waves of one or two episodes. The native provider has no
shared conversation state; episode recording uses context-local ownership. Existing
scripted and simulated-I/O controls establish scheduler behavior, but not useful
throughput under a real daemon's queue and inference latency.

This experiment addresses that narrow missing measurement. Client admission
concurrency is not GPU parallelism, server batch size or a controlled inference
count. A higher episode rate with more failed or timed-out tasks is not an
improvement in the primary metric. Zero passes makes useful-throughput zero,
even if decision throughput increases.

## Fixed plan

| Field | Locked value |
| --- | --- |
| World | `refund-ops`, version `1.1.2`, evaluation-only |
| Task seeds | Exactly `53000, 53001, 53002, 53003, 53004, 53005, 53006, 53007` |
| Batches | Four, in order: concurrency `1, 2, 2, 1` |
| Slot order | Seeds ascending within every batch; eight slots per batch |
| Model | Existing public `qwen3:8b` |
| Catalog digest | `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41` |
| Protocol | Unchanged `ollama-tools-v1`, exact system prompt, tools and contract |
| Serving request | Temperature `0`, `think=false`, `stream=false`, `num_predict=512`, `num_ctx=8192`, `keep_alive=5m` |
| Episode limits | Twenty decisions, 35 seconds after episode admission |
| Maximum work | 32 model episode slots; at most 640 recorded chat attempts |
| Overall limit | 1,200 seconds, including preparation, journaling and cleanup |
| Original artifact limit | 64 MiB for all collector-produced files, including temporary files |
| Protocol digest | `46b07934df72ff4d88c020fe9f937018ef94e603e405c0a615b0ddaf7abf2b68` |

The plan must verify that these seeds do not occur in earlier published
collections, and report any overlap before authorization. New seeds in the same
eight synthetic refund cases are not family-heldout generalization. Record the
deterministic case metadata without private grader answers. The eight tasks
repeat four times; there are eight unique task identities, not 32 independent
tasks. Two attempts per task at each admission level are repeats, not retries.

All batches retain the same initial public observations, task/scenario/split,
world/grader fingerprints, policy contract, catalog digest and decision/time
budgets. Admission is the only deliberate client configuration difference.
Concurrent response completion order is observed, not forced deterministic.
There is no fallback, retry, seed replacement, prompt tuning, model pull,
training, paid call or cloud endpoint. Run no other model experiment alongside
the collection. Record known background contention; do not silently discard it.

## Ownership and measurement

Use the existing rollout lifecycle, not a new agent engine. Each batch owns one
prepared native provider and fixed bounded waves. The caller prepares before
admission and closes in `finally`; supplied rollout
providers remain caller-owned. Do not use a long-lived shared history or share
mutable world state. Mock tests must verify peak in-flight admitted episodes
never exceeds one or two as configured, including errors and cancellation.

Measure each batch with a monotonic clock, starting before first admission and
ending after the final wave's full raw records are flushed/fsynced and its
semantic validation finishes. The clock runs continuously across waves. It
includes client scheduling, request waiting, world transitions, raw persistence,
interwave source checks and semantic validation. Record validation phase time
without subtracting it from batch wall time. Record preparation and cleanup
separately, plus total collector elapsed time. Do not substitute
the sum of overlapping episode times, database timestamps, daemon counters or
episode duration for batch wall time. Do not sum segmented admission clocks or
adjust the clock definition after observing results.

Reserve at most 30 seconds for each batch's preparation, three cooperative seconds
for each of four batch-provider cleanups, and 60 seconds for final reporting.
Recheck metadata for each prepared provider without generating warmup replies.
Catalog mismatch, source drift, failed preparation or cleanup stops further
admission. A new admitted episode needs its full 35-second reservation before
the overall deadline; a two-slot wave needs time for both to finish within that
deadline, not two serial 35-second reservations. Cancellation stops admission,
cancels owned workers once, preserves finalized returns and closes the provider.
Cooperative cancellation/close does not attest server resource release.

At the worst episode timeout, batch bounds are approximately 280 seconds at
concurrency one and 140 at two: total 840 seconds. Four preparation reservations
add 120 seconds, cleanup adds 12, and finalization reserves 60, totaling 1,032
seconds before validation/persistence overhead. This arithmetic is a ceiling for cooperative
calls, not a measurement or guarantee for blocking/malicious extensions.

## Raw-first evidence and caps

Default and `--plan` must perform no provider construction, daemon contact,
Store creation, credential inspection or inference. Only explicit `--collect`
with a reviewed full source SHA and fresh `--output` may collect. Planning is
runnable without daemon contact:

```sh
uv run python examples/model_concurrency_study.py --plan
```

After separate authorization, the collection command is:

```sh
uv run python examples/model_concurrency_study.py --collect \
  --source-revision FULL_REVIEWED_40_CHARACTER_SHA \
  --output artifacts/model-concurrency-study/FRESH_RUN
```

Replace both placeholders with the reviewed source and an unused path. Default
execution is the same pure plan. Collection refuses abbreviated revisions.

Refuse existing files, directories and live/dangling symlinks before contacting
a provider. Require clean committed runtime, dependencies, collector, tests and
this protocol, with pre/post gates and individual source hashes. Record machine,
Python, CPU/architecture and relevant installed library versions, reported
daemon version, exact contracts/options, plan digest, batch/slot order and
prepared catalog identity. Missing metadata remains unknown. Report the full
checkout dirty flag separately from clean captured source.

Keep one bounded append-only raw operator journal and one derived report; no
SQLite/ATIF/training duplicate is needed. Save each finalized attempted envelope
before semantic replay or aggregation and before any next wave is admitted.
The caller waits for the whole wave, journals/fsyncs every returned value, then
validates it. Journal writes have one owner and cannot interleave. Preserve exact
JSON values and recorded wire-body hashes/completeness, not reconstructed
responses. Full returned failures, timeouts and malformed serializable
envelopes remain evidence. An invalid envelope is inconclusive, never dropped
or replaced; an unserializable return gets a bounded redacted marker explicitly
stating that exact evidence was not preserved.

Before admission, reserve a conservative full episode serialization budget,
one MiB for report/terminal-stop capacity, and capacity for **every in-flight
episode**. The 24 MiB conservative episode reservation requires
48 MiB at concurrency two, in addition to prior raw bytes. Reuse it only with
its derivation/near-limit tests rechecked for this fixed world and all recorded
fields. The local derivation budgets 8 MiB of serialized provider events,
twenty trace entries each allowing 132 KiB context, 384 KiB observation,
64 KiB action, 64 KiB result and 4 KiB metadata, plus 1 MiB for snapshots and
envelope metadata. An escape-heavy near-limit serialization test checks that
this sum and its wrapper fit 24 MiB. These are conservative fixed-refund
bounds, not protection against arbitrary trusted extensions. A 64 MiB cap can
stop the experiment before 32 slots in a worst case;
do not promise full completion. Never start work relying on later compression,
deletion or truncation to regain capacity. Include temporary serialized artifacts
in accounting; prefer bounded streaming/hash accounting over duplicate files.

Reserve twenty remaining chat attempts per admitted episode, up to forty for
two active episodes. Count started requests including rejected and cancelled
calls, not only successful decisions. A cooperative shared request hook prevents
race-driven admission above the 640 limit. If an unexpected oversized return
fits remaining unreserved capacity, preserve it completely and stop
inconclusive; otherwise preserve a generic marker and disclose loss. Quotas,
timeout, interrupt, source drift and cleanup failure leave an explicit terminal
report, attempted/returned/exact-raw/verified/inconclusive counts and unattempted
slots. Redacted diagnostic markers are not exact raw envelopes. A failed raw
write is counted separately from a persisted marker; already returned peers in
that admitted wave remain accounted for even if persistence fails. Source validity
is checked again before the terminal report, including stopped prefixes.
No implicit retry or new inference is allowed during verification.

Records are evaluation-only and training-ineligible. Independently replay all
returned valid episodes at pinned source; validate actual pinned Harbor schema
and all three training export exclusions after collection, without inference.
Record full raw/report byte totals and hashes; later validation sidecars are
additional publication data. Finalized journals are not mid-episode
process-crash durability.

## Predeclared analysis

The primary per-batch metric is `verified business passes / batch wall seconds`.
Report its observed value, denominator and all unverified/unattempted slots.
Also report clean successes, attempted/finalized/verified counts, authoritative
business failures, status/termination counts, invalid actions, provider/harness
failures and cleanup. A stopped study remains a descriptive prefix, not a
completed admission comparison. Show all four batches before any pooled result.

Report per-batch finalized episodes/second and executed decisions/second using
the same wall clock. Report admitted peak overlap and recorded chat attempts,
accepted replies, cancellations, request/response bytes, observed transport
latency, known input/output token totals and daemon counters with known-request
denominators and completeness flags. Missing cancelled-call work is unknown,
not zero. More admitted tasks can produce more or fewer requests because tool
errors and early termination change trajectories. These are not equal-number-
of-inferences workloads, and request timestamps alone are not GPU scheduling.

Within-task pairs are fixed in advance: batch zero versus batch one, then batch
three versus batch two (concurrency one versus two). For business and clean
outcomes, report both-pass, concurrency-one-only, concurrency-two-only and
neither cells for each round, with exact comparable/eligible denominators.
Do not pool sixteen pairs as independent samples. Also report each unique
seed's zero/one/two pass count at each admission level and the eight task-level
differences. Any interval must resample whole tasks with all four attempts kept
together, and remain descriptive for eight fixed synthetic tasks. Server-load
or order effects are not removed by balanced `1,2,2,1` scheduling.

## Interpretation and acceptance gates

`keep_alive=5m` requests residency, not a verified warm-load or prefix-cache
state. Metadata preflight does not warm the model. Batch one can include model
load; later batches can benefit from warm weights, cached prompts or changed
background load. The symmetric order limits a simple direction-of-time bias but
does not isolate those factors. A server may serialize concurrent requests,
queue them, batch prefill/decode or contend for KV capacity. Episode deadlines
include that daemon wait. Full wire capture does not attest rendered tokenizer
input, actual executed weights, KV occupancy or cache hits.

Before collection approval, confirm the question remains useful, fixed
seeds/protocol/quotas are practical, and no other locked experiment competes
for the daemon. Require offline tests for one/two admission,
shared request reservations, raw-first ordering, malformed first/later returns,
partial stop/cancellation, concurrent quota pressure, source/model drift,
cleanup failure, exact repeated-task pairing and wall-time accounting. The
collector's request hook uses an injected `httpx` client; native provider class,
contract and protocol remain unchanged. Only loopback port 11434 tags/show/version
metadata and locked native chat requests are admitted; model pulls, arbitrary
paths, alternate models and changed generation options are rejected before
transport. Preparation is metadata-only, not model warmup. Source
and protocol must be committed and reviewed before collecting evidence.

Completion requires all 32 planned slots accounted for, reproducible source and
raw/report hashes, independent replay/interchange/exclusion checks, and an
honest useful-throughput comparison. All-zero outcomes are a valid negative
result, not permission to change seeds or budgets. Neither a positive nor a
negative result establishes cloud scaling, representative application fidelity,
causal GPU parallelism or trained-model improvement.
