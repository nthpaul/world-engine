# Scripted CPU profile

Collected 2026-10-10 09:02 UTC at source
`d71a05d35f8c95df930d957ff4ebecc2ef3b0b72` on Apple M4 Max, 16 logical
CPUs, 64 GiB RAM, macOS 27.0, Python 3.13.5. Implementation was clean;
the whole checkout was dirty because work outside the runtime scope was present.
Every captured source hash was unchanged at the end of execution.

Each world ran seeds 0 through 23 sequentially with `scripted-oracle`,
`evaluation_only=true`, concurrency 1, max 20 decisions, and a 30-second episode
timeout. An unprofiled trial ran first, followed by the same 24 cases under
stdlib cProfile. All 192 episodes passed, with zero invalid actions or errors.
The 96 profiled episodes independently replayed successfully.

| World | Episodes per trial | Decisions per trial | Unprofiled wall seconds | Profiled wall seconds | Deepcopy cumulative seconds | Observe cumulative seconds | Observe calls |
|---|---:|---:|---:|---:|---:|---:|---:|
| CRM merge | 24 | 152 | 0.089550 | 0.225526 | 0.200009 | 0.159955 | 528 |
| Refund operations | 24 | 64 | 0.025575 | 0.088779 | 0.075007 | 0.062613 | 264 |
| Incident control | 24 | 192 | 0.066820 | 0.275988 | 0.247372 | 0.203523 | 648 |
| Access provisioning | 24 | 320 | 0.224621 | 0.976806 | 0.904774 | 0.600493 | 1056 |

These are descriptive timings, not a before/after or parallel-CPU result.
Cumulative timings include nested calls and must not be added together.
cProfile disproportionately charges Python's recursive copy operations versus
C-backed JSON operations; its fractions are diagnostic, not predicted speedups.
The first CRM episode took 37.6 ms, including cold source/collection-revision
introspection, while its later unprofiled episodes took 1.5 to 3.3 ms.
Ordering, cache warmup, and shared-machine load were uncontrolled.

## Diagnosis

Deepcopy accounted for 84.5 to 92.6 percent of profiled rollout time. Public
observation generation alone accounted for 61.5 to 73.8 percent. Rollout obtains
two fresh observations before every action: one for `policy_messages`, then
another for `provider.decide`. `Tool.metadata` first detaches its cached schema,
and the enclosing observation then deep-copies that detached schema again.

JSON serialization consumed 0.004 to 0.031 profiled seconds per world.
`world_fingerprints` consumed 0.004 to 0.005 seconds, including fresh module-file
reads. Warmed schema/type introspection was not a dominant entry. There is no
evidence here that fingerprint caching or a process pool is the right next step.

The separate trusted-replay phase took 1.350787 profiled seconds for 96 episodes.
Deepcopy was 1.150032 cumulative seconds; JSON serialization was 0.118868,
and world fingerprints 0.021275. These overlap nested work, not separate costs.

SQLite ran only in an isolated temporary database, which was removed. Appending
96 full episodes took 0.187869 profiled seconds. Connection close/commit work
dominated; canonical serialization ran twice per episode and took 0.047719
seconds. One hundred four-run page reads took 0.217657 seconds. Forty CRM detail
reads of 24 episodes each took 0.520093 seconds: repeated JSON decode and
canonical rehash took 0.204 and 0.165 seconds respectively. This is not a
100-episode or large-history API latency measurement; no server was contacted.

## Proposed change, not implemented

First test one fresh `world.observe()` per rollout decision, serialize the
controller context from it, then pass that same detached observation to the
provider. Context serialization finishes before provider execution, so provider
mutation cannot change the stored context string. The world's existing detached
observation boundary still protects operational state. Do not reuse a previous
trace observation or add a mutable observation cache.

This removes exactly 728 duplicate observation reads from the measured profiled
workload without changing a world or grader. Regression coverage should include
a provider that mutates its received observation/tools, exact native v1/v2 wire
replay, all four reference paths, and comparison of action/result/state hashes.
Verify actual timings only after review and a committed implementation. Existing
source fingerprints must remain explicit; this is not permission to cache them.

A later small persistence change could hash the already canonical encoded
episode in `append_episode` rather than serialize it a second time. Prove
byte-identical stored content hashes and corruption checks first. Do not cache
detail traces, weaken integrity validation, or change connection ownership on
the strength of this small workload.

## Evidence

`profile.json` records configs, machine metadata, source fingerprints, per-world
counts/durations, and cumulative/exclusive cProfile entries. The `.prof` files
are original cProfile outputs; corresponding `.txt` files show the top 50
cumulative entries. `episodes.jsonl` contains all 96 full profiled synthetic
episodes with `evaluation_only=true` and `training_eligible=false` wrappers.
These operator records are not training data. Total execution was 4.355 seconds;
no model, network, primary database, Docker, or browser operations ran.
