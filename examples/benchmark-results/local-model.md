# Paired Local Model Evaluation

Measured 2026-10-10T05:04:21.271521+00:00 on macOS-27.0-arm64-arm-64bit-Mach-O, Python 3.13.5.

Already-installed Ollama qwen3:8b; no downloads or paid calls. Temperature 0, thinking disabled, 512 output-token bound per decision, 20 decisions and 120 seconds per episode.

Tiny paired local evaluation, not a population estimate or comparison with hosted systems. Tool replay is deterministic; model inference may not be bitwise deterministic.

A separate UI local-model request was submitted and immediately cancelled around 2026-10-10 05:03:10-05:03:15 UTC. Inference durations may include brief server contention; raw measured values are preserved.

| World | Provider | Passes | Wall seconds | Invalid actions | Input tokens | Output tokens |
|---|---|---:|---:|---:|---:|---:|
| crm-merge | scripted-oracle | 1/1 | 0.04 | 0 | 0 | 0 |
| crm-merge | scripted-baseline | 0/1 | 0.00 | 1 | 0 | 0 |
| crm-merge | local | 0/1 | 33.24 | 0 | 25921 | 200 |
| refund-ops | scripted-oracle | 1/1 | 0.01 | 0 | 0 | 0 |
| refund-ops | scripted-baseline | 0/1 | 0.00 | 1 | 0 | 0 |
| refund-ops | local | 1/1 | 15.13 | 1 | 9487 | 217 |
| incident-control | scripted-oracle | 1/1 | 0.01 | 0 | 0 | 0 |
| incident-control | scripted-baseline | 0/1 | 0.00 | 1 | 0 | 0 |
| incident-control | local | 0/1 | 34.38 | 17 | 25326 | 372 |

Full model digest, actions, safe errors, matched scenario IDs, observed token counts and replay evidence are in local-model.json. Full synthetic operator episodes are in local-model-traces.jsonl, explicitly evaluation_only=true and training_eligible=false; these are not training exports.

Collection Git revision: `7fdf4c6ae511dc81cc4074ea54122c0671ba2469`. Overall checkout dirty: `True`; implementation status and scope are recorded in each episode's provenance.

Replay delivered traces: `uv run python -m world_engine replay --file examples/benchmark-results/local-model-traces.jsonl`.

Reproduce: `uv run python examples/local_model_benchmark.py --episodes 1 --seed 42`.
