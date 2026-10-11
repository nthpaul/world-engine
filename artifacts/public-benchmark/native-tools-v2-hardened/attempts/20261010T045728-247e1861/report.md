# Public task evaluation

Task: `terminal-bench/log-summary-date-ranges`
Source revision: `2fd12b88aafdd04a52c298e3940bcb189f9766d6`

Evaluation-only. Benchmark task, solutions, grader, and trajectories must never enter training exports.

| Policy / protocol | Execution outcome | Official grader | Commands | Model calls | Elapsed seconds |
| --- | --- | --- | ---: | ---: | ---: |
| reference / official-shell-control | commands_executed | pass | 1 | 0 | 3.3574 |
| zero / official-shell-control | commands_executed | fail | 1 | 0 | 0.6557 |
| local / native-tools-v2 | commands_executed | fail | 8 | 8 | 18.4644 |

The official solution omits only apt package installation. The verifier runs the unmodified official Python tests with pytest 8.4.1 installed at image build time. These protocol adaptations remove runtime network access.

Agent image: `sha256:751339ca494078b4e44082a5f61f5206e30a535cc1604c7f2b548521c3b0b9d4`
Verifier image: `sha256:94df73de10816016374aaa16eed15861cfe7c87ba215eae5d53ae95fab8e30c2`
Official Python base: `python@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641`

One adapted task and one bounded local-model attempt do not represent the Terminal-Bench leaderboard protocol or a general agent benchmark score.
