# Public task evaluation

Task: `terminal-bench/log-summary-date-ranges`
Source revision: `2fd12b88aafdd04a52c298e3940bcb189f9766d6`

Evaluation-only. Benchmark task, solutions, grader, and trajectories must never enter training exports.

| Policy / protocol | Execution outcome | Official grader | Commands | Model calls | Elapsed seconds |
| --- | --- | --- | ---: | ---: | ---: |
| reference / official-shell-control | commands_executed | pass | 1 | 0 | 3.4213 |
| zero / official-shell-control | commands_executed | fail | 1 | 0 | 0.6711 |
| local / native-tools-v2 | commands_executed | fail | 8 | 8 | 18.2688 |

The official solution omits only apt package installation. The verifier runs the unmodified official Python tests with pytest 8.4.1 installed at image build time. These protocol adaptations remove runtime network access.

Agent image: `sha256:0b72ffe8b722117253ecaa3088a3c5123ec0ce1de099728574d26f1f8d6ab1b9`
Verifier image: `sha256:7faf5c57294fd7925d8ded75fe72f093f67ecbb7c97611cf86f7b2c8dcd33178`
Official Python base: `python@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641`

One adapted task and one bounded local-model attempt do not represent the Terminal-Bench leaderboard protocol or a general agent benchmark score.
