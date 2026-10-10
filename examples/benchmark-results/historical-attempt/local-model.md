# Paired Local Model Evaluation

Measured 2026-10-10T04:51:42.827797+00:00 on macOS-27.0-arm64-arm-64bit-Mach-O, Python 3.13.5.

Already-installed Ollama qwen3:8b; no downloads or paid calls. Temperature 0, thinking disabled, 512 output-token bound per decision, 20 decisions and 120 seconds per episode.

Tiny paired local evaluation, not a population estimate or comparison with hosted systems. Tool replay is deterministic; model inference may not be bitwise deterministic.

| World | Provider | Passes | Wall seconds | Invalid actions | Input tokens | Output tokens |
|---|---|---:|---:|---:|---:|---:|
| crm-merge | scripted-oracle | 1/1 | 0.02 | 0 | 0 | 0 |
| crm-merge | scripted-baseline | 0/1 | 0.01 | 1 | 0 | 0 |
| crm-merge | local | 0/1 | 61.02 | 0 | 25921 | 200 |
| refund-ops | scripted-oracle | 1/1 | 0.01 | 0 | 0 | 0 |
| refund-ops | scripted-baseline | 0/1 | 0.01 | 1 | 0 | 0 |
| refund-ops | local | 1/1 | 15.43 | 1 | 9487 | 217 |
| incident-control | scripted-oracle | 1/1 | 0.02 | 0 | 0 | 0 |
| incident-control | scripted-baseline | 0/1 | 0.01 | 1 | 0 | 0 |
| incident-control | local | 0/1 | 35.54 | 17 | 25326 | 372 |

Full model digest, actions, safe errors, matched scenario IDs, observed token counts and replay evidence are in local-model.json. Evaluation episodes are excluded from training exports.

Reproduce: `uv run python examples/local_model_benchmark.py --episodes 1 --seed 42`.
