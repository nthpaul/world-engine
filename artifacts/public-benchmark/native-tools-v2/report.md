# Public task evaluation

Task: `terminal-bench/log-summary-date-ranges`
Source revision: `2fd12b88aafdd04a52c298e3940bcb189f9766d6`

Evaluation-only. Benchmark task, solutions, grader, and trajectories must never enter training exports.

| Policy / protocol | Execution outcome | Official grader | Commands | Model calls | Elapsed seconds |
| --- | --- | --- | ---: | ---: | ---: |
| reference / official-shell-control | commands_executed | pass | 1 | 0 | 3.3267 |
| zero / official-shell-control | commands_executed | fail | 1 | 0 | 0.6825 |
| local / native-tools-v2 | commands_executed | fail | 8 | 8 | 19.3598 |

The official solution omits only apt package installation. The verifier runs the unmodified official Python tests with pytest 8.4.1 installed at image build time. These protocol adaptations remove runtime network access.

Agent image: `sha256:c66c1ca915a22a2d18ff3077e17cdba408196e5a4286ab11436696925657cdf7`
Verifier image: `sha256:345339779330c1af733343e3c2b3b0d29c66c4c74c5ca1c13fa1b9ce177e4420`
Official Python base: `python@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641`

One adapted task and one bounded local-model attempt do not represent the Terminal-Bench leaderboard protocol or a general agent benchmark score.
