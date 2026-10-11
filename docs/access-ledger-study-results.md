# Native context comparison results

The [locked protocol](access-ledger-study.md) completed at source
`cc2d4956c320867569e866bea3adbb53123a477f` on 2026-10-10. All sixteen
episodes finalized and replayed in 381.299 seconds, without retries,
inconclusive episodes, unattempted slots, cleanup errors or paid calls.
The existing public `qwen3:8b` catalog digest and reported Ollama `0.22.0`
matched preparation. No weights were downloaded and no training ran.

This is a comparison of complete native context contracts on eight repeated
synthetic access cases. It is not an isolated deduplication, cache or population
experiment. The [original eight native failures](access-native-results.md)
remain unchanged and are not replaced by these sixteen new attempts.

## Outcomes

| Result | Native v1 | Native ledger v2 |
| --- | ---: | ---: |
| Verified attempts | 8 | 8 |
| Business passes / clean successes | 0 / 0 | 0 / 0 |
| Completed decisions | 89 | 125 |
| Semantically rejected actions | 33 | 101 |
| Recorded chat attempts | 97 | 125 |
| Accepted native replies | 89 | 125 |
| Cancelled in-flight requests | 8 | 0 |
| Termination | Eight timeouts | Three finishes, five step limits |

All eight pairs have matching initial public context, task, scenario, split,
world and grader identity. Both business and clean four-cell tables contain
eight neither-pass pairs and zero in every other cell. The paired observed
v2-minus-v1 pass fraction is zero. This small fixed sample does not establish
equivalence or a population success rate.

`completed` is an execution status, not a business pass. V2's three explicit
finishes occurred on seeds 0, 5 and 7 after eight, eight and nine decisions.
Their assigned requests were still unsettled. Every episode preserved the
trusted safety envelope but failed request settlement and received reward zero.
Safe abandonment and early `finish` did not earn outcome credit.

## Failure interpretation

V1 made 21 undiscovered-record attempts and twelve review attempts before the
required verification was complete or within scope. It never read a policy,
granted access, denied the assigned request, or finished. All eight episodes
reached their 35-second deadline. Its 33 invalid actions belong to this new
receipt; the original historical receipt still records 32.

V2 made 85 calls rejected for argument shapes or values and sixteen
undiscovered-record reads. Observed examples include zero-based
`start_index=0` where the tool requires a positive index. Employee searches
supplied a query and the permitted `staff_number` field, but their zero-based
page arguments were rejected before a search executed. It called only inspect,
listing, request reading,
employee search and finish. No assigned request was settled.

These categories describe recorded tool results, not an inferred hidden model
state or a proven cause in the daemon's template. V2 reached more decisions
inside its wall-time budget, but most were invalid. Fewer elapsed seconds or
more decisions per second do not establish better useful throughput. Optimize
verified task outcomes as well as resource use.

## Resource evidence

The raw events contain 222 chat attempts: 214 accepted replies and eight
cancelled requests. Known reported usage sums to 440,321 input tokens and
6,798 output tokens over 214 attempts. The other eight lack usage; these sums
are incomplete, not total cost or upper bounds.

V1 reports 229,146 known input / 2,847 output tokens for 89 of 97 attempts.
V2 reports 211,175 input / 3,951 output tokens for all 125 attempts. All v2
token-accounting flags are complete; do not describe its usage as partial.
The summed known daemon inference duration is 363,631,938,297 ns across
214 attempts, excluding cancelled-call work.

Observed serialized request bodies total 1,364,914 bytes for v1 and 1,178,809
for v2. Response evidence contains 38,172 observed bytes for v1 and 53,245 for
v2; v1 includes bounded incomplete bodies. The protocols produced different
numbers and kinds of actions. These totals do not isolate compression,
tokenizer consumption, prefix-cache hits or a causal latency improvement.
Balanced attempt order does not eliminate shared-machine, warmup or daemon
effects. Metadata HTTP request counts remain unknown, separately from chat
counts. Catalog identity is not signed executed-weight attestation.

## Reproduce the proof

[The report](../artifacts/access-ledger-study/20261010-v1/report.json) records
the complete protocol, twenty-one source hashes, ordered rows, byte counts,
usage completeness and cleanup. [Raw operator records](../artifacts/access-ledger-study/20261010-v1/evaluation-episodes.jsonl)
retain every full finalized envelope. The two original files total 7,003,636
bytes; the later [independent validation](../artifacts/access-ledger-study/20261010-v1/independent-validation.json)
is additional publication data.

Root and engine independently checked all sixteen replays, sixteen actual
pinned Harbor 0.24.0 `Trajectory` validations, forty-eight SFT/DPO/grouped
training exclusions, committed source correspondence, exact row/slot identity,
paired outcomes, and known counters. Isolated validation databases were removed.
This establishes transition, format and accounting consistency, not signed
collection authenticity, enterprise parity or a trained-model improvement.

At the recorded compatible source, replay without inference:

```sh
uv run python -m world_engine replay --file \
  artifacts/access-ledger-study/20261010-v1/evaluation-episodes.jsonl
```

Use that pinned recoverable revision when runtime fingerprints change. Never
rewrite historical labels to make them match a newer source. Raw operator
snapshots are not agent observations or trainer inputs; both native protocols
remain excluded from all three training-oriented formats.
