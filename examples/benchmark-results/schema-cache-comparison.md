# Tool Schema Cache Measurement

Same committed implementation, 30 seeded cases, three timing trials, three worlds, two scripted policies, concurrency 1/4/8, SQLite persistence. The standalone control bypasses only the schema memoization wrapper; the after run enables it. Sequential runs on the same host; background load is uncontrolled. This compares tool-schema caching within this engine, not model or competitor performance.

| World | Policy | Concurrency | Before episodes/s | After episodes/s | Ratio |
|---|---|---:|---:|---:|---:|
| crm-merge | scripted-oracle | 1 | 76.7 | 166.8 | 2.17x |
| crm-merge | scripted-oracle | 4 | 79.0 | 186.5 | 2.36x |
| crm-merge | scripted-oracle | 8 | 75.2 | 214.5 | 2.85x |
| crm-merge | scripted-baseline | 1 | 142.3 | 337.4 | 2.37x |
| crm-merge | scripted-baseline | 4 | 150.0 | 358.4 | 2.39x |
| crm-merge | scripted-baseline | 8 | 148.9 | 294.7 | 1.98x |
| refund-ops | scripted-oracle | 1 | 137.6 | 300.2 | 2.18x |
| refund-ops | scripted-oracle | 4 | 126.8 | 251.4 | 1.98x |
| refund-ops | scripted-oracle | 8 | 134.3 | 260.0 | 1.94x |
| refund-ops | scripted-baseline | 1 | 180.7 | 309.4 | 1.71x |
| refund-ops | scripted-baseline | 4 | 174.9 | 326.6 | 1.87x |
| refund-ops | scripted-baseline | 8 | 177.5 | 335.1 | 1.89x |
| incident-control | scripted-oracle | 1 | 55.4 | 176.0 | 3.18x |
| incident-control | scripted-oracle | 4 | 54.3 | 172.9 | 3.18x |
| incident-control | scripted-oracle | 8 | 54.5 | 178.1 | 3.27x |
| incident-control | scripted-baseline | 1 | 137.7 | 330.0 | 2.40x |
| incident-control | scripted-baseline | 4 | 142.1 | 280.1 | 1.97x |
| incident-control | scripted-baseline | 8 | 126.1 | 323.8 | 2.57x |

Raw timing trials and exact environment/grader/policy/runtime fingerprints are in schema-cache-before.json and schema-cache-after.json. Both runs preserve all outcome counts. Async concurrency is not CPU parallelism.
