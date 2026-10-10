# Local Workflow Benchmark

Measured 2026-10-10T05:03:13.155518+00:00 on macOS-27.0-arm64-arm-64bit-Mach-O, Python 3.13.5.

End-to-end batch scheduling, trusted grading, JSON hashing and SQLite persistence; no model latency.

Repeated seeds are paired deterministic cases, not independent task samples; Wilson intervals describe case outcomes, not a new-population guarantee. Concurrency is asyncio scheduling, not CPU parallelism.

| World | Policy | Concurrency | Passed | Episodes/s | Steps/s | p50 ms | p95 ms | Invalid | Errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| crm-merge | scripted-oracle | 1 | 90/90 | 76.7 | 460.1 | 8.2 | 10.0 | 0 | 0 |
| crm-merge | scripted-oracle | 4 | 90/90 | 79.0 | 473.8 | 44.2 | 47.7 | 0 | 0 |
| crm-merge | scripted-oracle | 8 | 90/90 | 75.2 | 451.0 | 94.4 | 99.5 | 0 | 0 |
| crm-merge | scripted-baseline | 1 | 0/90 | 142.3 | 284.6 | 2.9 | 3.5 | 90 | 0 |
| crm-merge | scripted-baseline | 4 | 0/90 | 150.0 | 299.9 | 21.0 | 22.8 | 90 | 0 |
| crm-merge | scripted-baseline | 8 | 0/90 | 148.9 | 297.8 | 45.7 | 50.5 | 90 | 0 |
| refund-ops | scripted-oracle | 1 | 90/90 | 137.6 | 449.6 | 3.4 | 4.7 | 0 | 0 |
| refund-ops | scripted-oracle | 4 | 90/90 | 126.8 | 414.1 | 24.0 | 36.6 | 0 | 0 |
| refund-ops | scripted-oracle | 8 | 90/90 | 134.3 | 438.8 | 47.8 | 67.4 | 0 | 0 |
| refund-ops | scripted-baseline | 1 | 0/90 | 180.7 | 361.4 | 2.1 | 2.4 | 90 | 0 |
| refund-ops | scripted-baseline | 4 | 0/90 | 174.9 | 349.7 | 17.6 | 21.9 | 90 | 0 |
| refund-ops | scripted-baseline | 8 | 0/90 | 177.5 | 355.1 | 38.5 | 42.2 | 90 | 0 |
| incident-control | scripted-oracle | 1 | 90/90 | 55.4 | 443.3 | 12.5 | 16.5 | 0 | 0 |
| incident-control | scripted-oracle | 4 | 90/90 | 54.3 | 434.4 | 63.8 | 72.8 | 0 | 0 |
| incident-control | scripted-oracle | 8 | 90/90 | 54.5 | 435.9 | 132.9 | 141.9 | 0 | 0 |
| incident-control | scripted-baseline | 1 | 0/90 | 137.7 | 275.3 | 3.1 | 3.4 | 90 | 0 |
| incident-control | scripted-baseline | 4 | 0/90 | 142.1 | 284.1 | 22.3 | 25.0 | 90 | 0 |
| incident-control | scripted-baseline | 8 | 0/90 | 126.1 | 252.1 | 52.6 | 58.2 | 90 | 0 |

Reproduce: `uv run python -m world_engine benchmark --episodes 30 --trials 3`. Raw per-trial durations and matched scenario IDs are in benchmark.json.
