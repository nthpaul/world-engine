# Local Workflow Benchmark

Measured 2026-10-10T05:03:19.757119+00:00 on macOS-27.0-arm64-arm-64bit-Mach-O, Python 3.13.5.

End-to-end batch scheduling, trusted grading, JSON hashing and SQLite persistence; no model latency.

Repeated seeds are paired deterministic cases, not independent task samples; Wilson intervals describe case outcomes, not a new-population guarantee. Concurrency is asyncio scheduling, not CPU parallelism.

| World | Policy | Concurrency | Passed | Episodes/s | Steps/s | p50 ms | p95 ms | Invalid | Errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| crm-merge | scripted-oracle | 1 | 90/90 | 166.8 | 1000.7 | 1.9 | 2.3 | 0 | 0 |
| crm-merge | scripted-oracle | 4 | 90/90 | 186.5 | 1118.9 | 15.2 | 18.7 | 0 | 0 |
| crm-merge | scripted-oracle | 8 | 90/90 | 214.5 | 1286.9 | 29.4 | 31.4 | 0 | 0 |
| crm-merge | scripted-baseline | 1 | 0/90 | 337.4 | 674.8 | 0.6 | 0.7 | 90 | 0 |
| crm-merge | scripted-baseline | 4 | 0/90 | 358.4 | 716.8 | 7.7 | 8.7 | 90 | 0 |
| crm-merge | scripted-baseline | 8 | 0/90 | 294.7 | 589.5 | 18.2 | 22.3 | 90 | 0 |
| refund-ops | scripted-oracle | 1 | 90/90 | 300.2 | 980.5 | 0.8 | 1.1 | 0 | 0 |
| refund-ops | scripted-oracle | 4 | 90/90 | 251.4 | 821.4 | 10.1 | 16.7 | 0 | 0 |
| refund-ops | scripted-oracle | 8 | 90/90 | 260.0 | 849.3 | 22.8 | 34.5 | 0 | 0 |
| refund-ops | scripted-baseline | 1 | 0/90 | 309.4 | 618.7 | 0.5 | 0.6 | 90 | 0 |
| refund-ops | scripted-baseline | 4 | 0/90 | 326.6 | 653.2 | 7.7 | 10.8 | 90 | 0 |
| refund-ops | scripted-baseline | 8 | 0/90 | 335.1 | 670.2 | 16.2 | 22.1 | 90 | 0 |
| incident-control | scripted-oracle | 1 | 90/90 | 176.0 | 1408.1 | 2.3 | 2.7 | 0 | 0 |
| incident-control | scripted-oracle | 4 | 90/90 | 172.9 | 1383.1 | 16.8 | 18.1 | 0 | 0 |
| incident-control | scripted-oracle | 8 | 90/90 | 178.1 | 1425.0 | 34.9 | 36.6 | 0 | 0 |
| incident-control | scripted-baseline | 1 | 0/90 | 330.0 | 660.0 | 0.5 | 0.6 | 90 | 0 |
| incident-control | scripted-baseline | 4 | 0/90 | 280.1 | 560.2 | 8.1 | 12.0 | 90 | 0 |
| incident-control | scripted-baseline | 8 | 0/90 | 323.8 | 647.6 | 18.4 | 23.4 | 90 | 0 |

Reproduce: `uv run python -m world_engine benchmark --episodes 30 --trials 3`. Raw per-trial durations and matched scenario IDs are in benchmark.json.
