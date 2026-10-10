# Scripted Profiling Results

Two independent read-only audits, by root and console on 2026-10-10, verified the saved collection at `b4501029a332d7675a12fbf84b00358230d3d154`. All 22 captured runtime, dependency and profiling-source hashes matched that commit's blobs and the unchanged files at publication checkout `1d9f2315348cbea192f7ae5c4f1cf0343ba6618a`. The latter revision did not recollect this evidence.

The [validation receipt](../artifacts/profiling/20261010-v2/independent-validation.json) is an additional publication sidecar. It does not alter or count toward the original collection's 18 files and **21,824,261 bytes**.

## Verified Evidence

- All **192** full envelopes replayed: four synthetic worlds, two trials per world, 24 seeds `0..23` per trial.
- All 192 passed, with 1,456 total decisions, zero invalid actions, errors, diagnostics or unattempted slots.
- All 192 ATIF conversions validated against Harbor 0.24.0's actual `Trajectory` model, pinned at `09f5b964f8e5075f7e52fd08c9994dfc80ad5d24`. Its ATIF-v1.8 schema SHA256 was `892a423ee9c710e8067740b36dd15c9de2f0157d05b6c1ea30acc25ff1c4da6c`.
- Actual SFT, DPO and grouped-RL exports each excluded all 192 evaluation-only episodes: **576 exclusions**, zero training records and no candidate-pool lookup.
- The 96 saved historical profiled cases matched the new profiled cases' trusted initial/final states, grades, actions, intermediate observations, results and state hashes. Both new trials also matched logically. Timing and generated episode IDs were not required to match.
- All eight binary profiles matched the report's call totals, profiled durations and every top-50 cumulative/exclusive entry. The isolated temporary database was removed.

The collector measured replay of only **96 profiled episodes**, followed by 96 SQLite appends, 100 four-run page reads and 40 CRM detail reads of 24 episodes. The independent 192-episode proof covers both saved trials; it is not the measured replay phase.

The collection recorded 4.604685 seconds in total. Its 240-second deadline is cooperative; the 64 MiB artifact cap is not a process-memory or temporary-storage limit. No model, API, paid-provider or Docker calls were made.

## Observation Reads

| World | Decisions Per Trial | Historical Reads | Current Reads | Removed Reads |
|---|---:|---:|---:|---:|
| CRM merge | 152 | 528 | 376 | 152 |
| Refund operations | 64 | 264 | 200 | 64 |
| Incident control | 192 | 648 | 456 | 192 |
| Access provisioning | 320 | 1,056 | 736 | 320 |
| Total | 728 | 2,496 | 1,768 | 728 |

Saved cProfile statistics identify the exact `observe` method by filename, first line and function name. Historical counts follow `3 * decisions + setup * 24`; current counts follow `2 * decisions + setup * 24`. Setup is three reads per episode for the first three worlds and four for access. This confirms removal of **728 duplicate observation calls in one profiled trial**, with the 96 historical saved cases' trusted outputs and actions unchanged. Unprofiled reads were not instrumented.

## Descriptive Timings

| World | Historical Unprofiled Seconds | Current Unprofiled Seconds | Historical Profiled Seconds | Current Profiled Seconds |
|---|---:|---:|---:|---:|
| CRM merge | 0.089550 | 0.082007 | 0.225526 | 0.187220 |
| Refund operations | 0.025575 | 0.023287 | 0.088779 | 0.075602 |
| Incident control | 0.066820 | 0.057378 | 0.275988 | 0.226987 |
| Access provisioning | 0.224621 | 0.200825 | 0.976806 | 0.841626 |

These are separate descriptive observations, not a causal speedup estimate. Each world ran unprofiled first, then profiled. Cold/warm caches, source introspection, shared-machine load, cProfile overhead and differing collection guards are uncontrolled. Output serialization and fsync occur outside each timed rollout block. Nested cumulative times cannot be added together. This does not measure CPU/GPU parallelism, inference parallelism, cloud throughput, large-history server performance or competitor superiority.

## Artifact Identity

The new [raw JSONL](../artifacts/profiling/20261010-v2/episodes.jsonl) is 21,325,782 bytes, SHA256 `31cb7c7be5b217a6b5762973ec98e9db50b4368645dcaf5629fe2188e09e98a7`. The [original report](../artifacts/profiling/20261010-v2/profile.json) is 314,785 bytes, SHA256 `72ae6a730f2452b4f542b4125eb696cb70915dcf618aabcfb792f5203ec89d95`. All 18 original byte counts and hashes remained unchanged before and after validation and are listed in the sidecar.

The historical `20261010-v1` directory contains 20 files totaling **11,115,988 bytes**: 18 measurement files totaling **11,101,259 bytes**, plus the retrospective `producer.py` and `profile.md` sidecars totaling 14,729 bytes. Those additions are publication bytes, not original collection bytes. Only 96 historical profiled envelopes were saved. The reported 96 unprofiled outcomes cannot receive independent raw-envelope replay proof. All four historical input hashes remain unchanged.

Replay checks semantic coherence; Harbor checks schema conformance. Neither is signed execution authenticity or downstream training consent. These evaluation-only synthetic records remain operator evidence.

## Reproduction

Use a checkout whose HEAD is exactly the reviewed collection revision below, with the collector's captured source scope committed and clean. The four hash-pinned historical inputs under `artifacts/profiling/20261010-v1` (`profile.json`, `episodes.jsonl`, `producer.py`, `profile.md`) must also be present from the published evidence. They are read-only prerequisites, not optional downloads or outputs to regenerate. Use a new output directory; the collector refuses existing files, directories and symlinks.

```sh
uv run python scripts/profile_scripted.py --collect \
  --source-revision b4501029a332d7675a12fbf84b00358230d3d154 \
  --output artifacts/profiling/NEW_REVIEWED_RUN
```

See the [locked protocol](scripted-profiling.md) for the pure default plan and bounds. Reproduction creates new evidence; it must not replace either historical collection. The independent audits did not rerun profiling or contact a model.

