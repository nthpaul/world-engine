# Local Workflow Benchmark

Measured 2026-10-10T08:05:06.071004+00:00 on macOS-27.0-arm64-arm-64bit-Mach-O, Python 3.13.5.

End-to-end batch scheduling, trusted grading, JSON hashing and SQLite persistence; no model latency.

Repeated seeds are paired deterministic cases, not independent task samples; Wilson intervals use the first observed outcome per distinct scenario ID and describe case outcomes, not a new-population guarantee. Conflicting repeated outcomes are counted explicitly. Concurrency is asyncio scheduling, not CPU parallelism. Throughput counts persisted episodes. Inconclusive trials retain observed work but are not complete benchmark measurements.

| World | Policy | Concurrency | Passed | Episodes/s | Steps/s | p50 ms | p95 ms | Invalid | Errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| crm-merge | scripted-oracle | 1 | 90/90 | 183.8 | 1164.0 | 2.0 | 2.3 | 0 | 0 |
| crm-merge | scripted-oracle | 4 | 90/90 | 208.5 | 1320.3 | 12.9 | 20.5 | 0 | 0 |
| crm-merge | scripted-oracle | 8 | 90/90 | 201.4 | 1275.4 | 29.1 | 41.7 | 0 | 0 |
| crm-merge | scripted-baseline | 1 | 0/90 | 355.1 | 710.2 | 0.6 | 0.6 | 90 | 0 |
| crm-merge | scripted-baseline | 4 | 0/90 | 387.4 | 774.9 | 7.2 | 7.5 | 90 | 0 |
| crm-merge | scripted-baseline | 8 | 0/90 | 379.4 | 758.8 | 16.0 | 17.4 | 90 | 0 |
| refund-ops | scripted-oracle | 1 | 90/90 | 381.9 | 1031.1 | 0.5 | 1.0 | 0 | 0 |
| refund-ops | scripted-oracle | 4 | 90/90 | 363.8 | 982.4 | 6.9 | 10.6 | 0 | 0 |
| refund-ops | scripted-oracle | 8 | 90/90 | 381.8 | 1030.9 | 12.1 | 25.4 | 0 | 0 |
| refund-ops | scripted-baseline | 1 | 0/90 | 415.9 | 831.8 | 0.4 | 0.4 | 90 | 0 |
| refund-ops | scripted-baseline | 4 | 0/90 | 412.5 | 825.0 | 6.6 | 7.5 | 90 | 0 |
| refund-ops | scripted-baseline | 8 | 0/90 | 416.1 | 832.2 | 14.6 | 15.4 | 90 | 0 |
| incident-control | scripted-oracle | 1 | 90/90 | 193.8 | 1550.4 | 2.3 | 2.3 | 0 | 0 |
| incident-control | scripted-oracle | 4 | 90/90 | 191.6 | 1532.7 | 15.8 | 17.2 | 0 | 0 |
| incident-control | scripted-oracle | 8 | 90/90 | 180.7 | 1445.8 | 33.9 | 37.8 | 0 | 0 |
| incident-control | scripted-baseline | 1 | 0/90 | 354.0 | 707.9 | 0.7 | 0.7 | 90 | 0 |
| incident-control | scripted-baseline | 4 | 0/90 | 355.0 | 709.9 | 7.8 | 8.5 | 90 | 0 |
| incident-control | scripted-baseline | 8 | 0/90 | 344.8 | 689.7 | 17.3 | 20.3 | 90 | 0 |
| access-provisioning | scripted-oracle | 1 | 90/90 | 70.0 | 919.1 | 8.7 | 12.3 | 0 | 0 |
| access-provisioning | scripted-oracle | 4 | 90/90 | 70.0 | 919.3 | 49.1 | 70.0 | 0 | 0 |
| access-provisioning | scripted-oracle | 8 | 90/90 | 70.2 | 921.5 | 88.6 | 141.7 | 0 | 0 |
| access-provisioning | scripted-baseline | 1 | 0/90 | 233.1 | 466.2 | 1.4 | 1.4 | 90 | 0 |
| access-provisioning | scripted-baseline | 4 | 0/90 | 240.2 | 480.4 | 12.3 | 12.7 | 90 | 0 |
| access-provisioning | scripted-baseline | 8 | 0/90 | 228.4 | 456.8 | 27.6 | 31.1 | 90 | 0 |

Reproduce: `uv run python -m world_engine benchmark --episodes 30 --trials 3 --output NEW_OUTPUT_DIRECTORY`. Replace NEW_OUTPUT_DIRECTORY with a fresh path that does not exist. Raw per-trial durations and matched scenario IDs are in benchmark.json.
