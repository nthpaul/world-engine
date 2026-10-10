# Public task evaluation

Task: `terminal-bench/log-summary-date-ranges`
Source revision: `2fd12b88aafdd04a52c298e3940bcb189f9766d6`

Evaluation-only. Benchmark task, solutions, grader, and trajectories must never enter training exports.

| Policy | Official grader | Commands | Model calls | Elapsed seconds |
| --- | --- | ---: | ---: | ---: |
| reference | pass | 1 | 0 | 3.4234 |
| zero | fail | 1 | 0 | 0.6575 |
| local | fail | 0 | 8 | 141.362 |

The official solution omits only apt package installation. The verifier runs the unmodified official Python tests with pytest 8.4.1 installed at image build time. These protocol adaptations remove runtime network access.

Agent image: `sha256:f5aec0bc7779a87d4f24df099abcb84a8c44b722694ab8a7d88e65bb972c7cf8`
Verifier image: `sha256:9a863c09b4d88c302f2a59f9a59b105af211df40da95518e479ce575916f30b5`
Official Python base: `python@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641`

One adapted task and one bounded local-model attempt do not represent the Terminal-Bench leaderboard protocol or a general agent benchmark score.
