# Local model admission study results

October 10, 2026. One authorized collection completed at source
`1d9f2315348cbea192f7ae5c4f1cf0343ba6618a`, with no retries, changed settings,
fallback, downloads, paid calls or training. The original [report](../artifacts/model-concurrency-study/20261010-v1/report.json)
and [operator journal](../artifacts/model-concurrency-study/20261010-v1/evaluation-episodes.jsonl)
remain unchanged; [independent validation](../artifacts/model-concurrency-study/20261010-v1/independent-validation.json)
is additional publication data.

## Question and locked workload

Does admitting two overlapping episodes improve verified business passes per
batch wall second, compared with admitting one? This measures **SDK caller-wave
admission**, not RunManager/API throughput or GPU parallelism. The
[predeclared protocol](model-concurrency-study.md), SHA256
`46b07934df72ff4d88c020fe9f937018ef94e603e405c0a615b0ddaf7abf2b68`, fixes
refund-ops `1.1.2`, seeds 53000 through 53007, and four ascending-seed batches
with admission levels **1, 2, 2, 1**. These are eight unique synthetic tasks
repeated four times, not 32 independent tasks or sixteen independent pairs.

The existing public `qwen3:8b` catalog digest was
`500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`.
Unchanged native `ollama-tools-v1` used temperature zero, think/stream false,
512 maximum predicted tokens, context setting 8192 and keep_alive 5m.
Each admitted episode had twenty decisions and 35 seconds. Overall limits
were 1,200 seconds, 640 chat attempts and 64 MiB original collector files.
All episodes are evaluation-only and excluded from training formats.

## Observed outcomes and timing

All 32 slots returned, were journaled exactly, and replay-verified. There were
zero inconclusive/unattempted slots, diagnostic markers, persistence failures
or collection retries. Total collector elapsed time was **441.572926583 seconds**.
All four provider cleanups completed within their three-second bound. Scoped
source was clean and the terminal source gate passed; the separate full-checkout
dirty flag remained true for out-of-scope guides/evidence.

Batch wall time is one continuous monotonic interval from first admission
through final-wave raw fsync and validation. It includes interwave source checks
and validation; phase times are **not subtracted**. Preparation and cleanup are
separate. Summing overlapping episode durations would be the wrong denominator.

| Batch | Admission / observed peak | Business passes | Clean successes | Continuous wall, seconds | Passes/second | Episodes/second | Decisions/second |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| 0 | 1 / 1 | 8/8 | 3/8 | 100.858585 | 0.079319 | 0.079319 | 0.594892 |
| 1 | 2 / 2 | 7/8 | 3/8 | 103.460102 | 0.067659 | 0.077324 | 0.560603 |
| 2 | 2 / 2 | 6/8 | 3/8 | 115.902943 | 0.051767 | 0.069023 | 0.474535 |
| 3 | 1 / 1 | 8/8 | 3/8 | 119.353499 | 0.067028 | 0.067028 | 0.502708 |

| Batch | Preparation, seconds | Validation included in wall, seconds | Cleanup, seconds | Decisions / invalid |
| --- | ---: | ---: | ---: | --- |
| 0 | 0.107354 | 0.051159 | 0.000217 | 60 / 8 |
| 1 | 0.081739 | 0.046046 | 0.000266 | 58 / 8 |
| 2 | 0.080484 | 0.044065 | 0.000291 | 55 / 8 |
| 3 | 0.091520 | 0.050557 | 0.000180 | 60 / 8 |

Overall there were **29 business passes, twelve clean successes, 233 executed
decisions and 32 semantic tool rejections**. Twenty-nine episodes finished with
completed status; three failed at the 35-second deadline. Seed 53004 timed out
in both two-admission batches; seed 53005 timed out in the second. All three
failed envelopes and their cancelled in-flight request records remain present.
There were no reported provider-error or internal-error terminations.

Descriptive pooling by admission level gives:

- Admission one: sixteen passes across sixteen attempts and 220.212083458 summed
  batch-wall seconds, or **0.072657230 verified passes/second**.
- Admission two: thirteen passes across sixteen attempts and 219.363044583
  summed batch-wall seconds, or **0.059262489 verified passes/second**.

Admission two did **not** improve observed useful throughput in this fixed run.
The similar summed wall times do not isolate daemon queuing, loading, caching or
GPU execution. Nor do they establish that one is an optimal admission policy.

## Matched task interpretation

Each predeclared round contains eight eligible pairs with identical task,
initial observation, split, world/grader fingerprints, policy and model digest.
Each contrast is admission two minus admission one, including the reversed
batch order in the second round.

| Round, one versus two | Both business pass | One only | Two only | Neither | Two-minus-one rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| Batches 0 versus 1 | 7 | 1 | 0 | 0 | -0.125 |
| Batches 3 versus 2 | 6 | 2 | 0 | 0 | -0.250 |

Both clean-success rounds have three both-pass, zero one-only/two-only, and five
neither. All eight tasks have all four eligible attempts. Per-task differences
in the fraction of passes, admission two minus one, are:

| Seed | One-admission passes / two attempts | Two-admission passes / two attempts | Difference |
| --- | --- | --- | ---: |
| 53000 | 2 | 2 | 0 |
| 53001 | 2 | 2 | 0 |
| 53002 | 2 | 2 | 0 |
| 53003 | 2 | 2 | 0 |
| 53004 | 2 | 0 | -1 |
| 53005 | 2 | 1 | -0.5 |
| 53006 | 2 | 2 | 0 |
| 53007 | 2 | 2 | 0 |

The public seed audit found no structured overlap in its declared 149-file
scope before collection. That is not proof of global novelty or absence of
pretraining contamination. New seeds in the existing eight refund cases are
not held-out rule-family generalization. No interval treating 32 attempts or
sixteen pairs as independent samples is reported.

## Request and usage accounting

The injected request hook counted **236 chat attempts and twelve metadata
requests**. Paired native records contain 233 accepted replies and three
cancelled requests, matching the hook count. All 233 accepted replies produced
decisions, including the 32 denied tool actions. Recorded request bodies total
1,496,132 bytes; observed response bodies total 98,587 bytes and are incomplete
for the cancelled calls.

Known daemon usage sums to **303,693 input tokens, 6,899 output tokens and
620,575,252,623 reported inference nanoseconds**, across 233 of 236 requests.
These are partial sums, not full totals, upper bounds or dollar costs. Admission
one has complete usage for its 120 requests: 157,200 input / 3,534 output tokens.
Admission two has known usage for 113 of 116 requests: 146,493 / 3,365. Summed
reported durations of overlapping requests are not batch wall time. Cancellation
does not attest immediate cessation of daemon work.

The API was idle background. Root performed lightweight image/proof activity
and the researcher performed brief read-only journal progress checks; no other
model inference, CPU benchmark or browser collection ran alongside this study.
Model warm loading, prefix-cache state, server queue policy, rendered tokenizer
input and actual GPU parallelism were not attested. Wire capture is not proof
that the full serialized context was consumed.

## Evidence and independent checks

| Original file | Bytes | SHA256 |
| --- | ---: | --- |
| `evaluation-episodes.jsonl` | 4,338,748 | `704f7b02eeb445d31333df6c299722afadebbb616cd60227594bacc3edb5773d` |
| `report.json` | 134,567 | `6720e6f31db4cc1760a28e30931e1e29c0858e1faa6d45f354e9c8ea4dc08882` |

Original accounting is exactly **4,473,315 bytes**, below 64 MiB. Later results
and validation-sidecar bytes are additional publication data, not silently
folded into that original amount. Thirty-two raw records retain all slots in
declared order. Reservations included every active episode; there was no
compression, deletion or truncation to recover quota.

Root and console separately checked all 32 replay results, all 32 documents
against the actual pinned Harbor 0.24.0 schema, and 96 real exporter exclusions
(32 unsupported-native-protocol exclusions per SFT/DPO/grouped format, no
candidate-pool lookup). Both checked all 22 captured hashes against the pinned
collection-revision Git blobs, raw/report row correspondence, outcome/request
aggregates, pair identities and original bytes before/after. Console additionally
checked wave event timestamps: 8/4/4/8 waves, overlap in all eight two-episode
waves, and no next-wave transport before prior-wave completion. This establishes
client overlap, not daemon/GPU scheduling.

Console's first proof command used a wrong body-field name and raised KeyError;
the corrected read-only proof succeeded. It was not a collection retry and did
not change original evidence. Interchange conformance and replay consistency
are not hostile-host authentication or training permission. Cleanup and time
bounds are cooperative; malicious or blocking trusted extensions are outside
this fixed collector's guarantee. No cloud scaling, production application
parity, model training or superiority claim follows from this sample.
