# Simulated Provider I/O Overlap

Awaiting 25ms per decision proves I/O overlap in the scheduler. This is explicitly simulated latency, not measured LLM/cloud throughput or CPU parallelism.

24 matched CRM episodes per trial, three timing trials, six decisions per episode. Every decision waits 25ms before the real scripted oracle and trusted workflow transition.

| Concurrency | Median episodes/s | Peak in-flight decisions | Passes |
|---:|---:|---:|---:|
| 1 | 6.02 | 1 | 72/72 |
| 4 | 23.75 | 4 | 72/72 |
| 8 | 46.49 | 8 | 72/72 |

Reproduce: `uv run python examples/io_overlap_benchmark.py`. Full per-trial timings and frozen provenance are in io-overlap.json.
