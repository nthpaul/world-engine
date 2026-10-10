# Advanced workbook primary sources

Accessed October 10, 2026. This ledger supports [the advanced workbook](../report/advanced-environment-labs.md), not a new benchmark or implemented trainer. All linked technical sources are their authors' papers, repositories, or official documentation. No code, dataset, model, or enterprise record was imported. Live documentation is a dated observation, not a reproducible software version.

## Measurement, grading, and generalization

| ID | Source | Verified use and limits |
| --- | --- | --- |
| E1 | [Anthropic: Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) | January 9, 2026. Task, trial, transcript, outcome, expert calibration, and capability versus regression evaluation. An evaluation measures the model and its controller together. |
| E2 | [Agarwal et al.: Statistical precipice](https://arxiv.org/abs/2108.13264) | Few-run RL uncertainty and aggregation. Supports careful sampling units, not a universal sample-size threshold. |
| E3 | [Cobbe et al.: Procedural generation benchmark](https://arxiv.org/abs/1912.01588) | Distinct training and evaluation levels measure generalization within environments. A level holdout does not prove transfer to another workflow rule or application. |
| E4 | [Fleet Python SDK](https://github.com/fleet-ai/fleet-sdk) | Public Apache-2.0 archive, archived August 12, 2026. Versioned environment creation, seeded reset, SQL state access, and close. These client operations do not reveal private fidelity validation or grader security. |
| E5 | [OpenAI graders](https://developers.openai.com/api/docs/guides/graders) | Numeric graders and combined scoring. Grader availability does not establish a sound business contract or compatibility with arbitrary environment rollouts. |
| E6 | [DeepMind: Specification gaming](https://deepmind.google/blog/specification-gaming-the-flip-side-of-ai-ingenuity/) | April 21, 2020. Distinguishes satisfying a literal score from achieving the intended task. Workbook exploit classes are local design analysis, not a quoted canonical taxonomy. |
| E7 | [Anthropic: Natural emergent misalignment from reward hacking](https://www.anthropic.com/research/emergent-misalignment-reward-hacking) | November 21, 2025. Controlled coding-training experiments report broader behavioral effects. No extrapolation to every model or this untrained project. |
| E8 | [Ng, Harada, Russell: Policy invariance under reward transformations](https://ai.stanford.edu/~ang/papers/shaping-icml99.pdf) | ICML 1999. Potential-based shaping under specified Markov decision process conditions. Arbitrary averages of diagnostic checks do not inherit the theorem. |
| E9 | [Anthropic: Small-sample poisoning](https://www.anthropic.com/research/small-samples-poison) | Controlled training-data backdoor experiments. Motivates provenance checks; does not establish a universal safe poison count or rate. |

## Training representations and algorithms

| ID | Source | Verified use and limits |
| --- | --- | --- |
| T1 | [Rafailov et al.: DPO, version 3](https://arxiv.org/html/2305.18290v3) | July 29, 2024 revision. Reference-relative preference loss, Bradley-Terry assumptions, and sequence likelihood. Numerical examples are original workbook calculations. |
| T2 | [Schulman et al.: PPO](https://arxiv.org/pdf/1707.06347) | 2017 paper. Clipped surrogate, behavior-policy ratios, and advantages. Clipping is not a safety guarantee or an enforced global KL limit. |
| T3 | [Shao et al.: DeepSeekMath, version 3](https://arxiv.org/html/2402.03300v3) | April 27, 2024 revision. Original GRPO group-relative advantages and policy objective. Later implementations need their own pinned loss specification. |
| T4 | [Transformers chat templates](https://huggingface.co/docs/transformers/main/en/chat_templating) | Model-specific role/control-token formatting; duplicated special tokens can change inputs. `main` documentation does not prove the relevant libraries are installed locally. |
| T5 | [TRL DPO trainer](https://huggingface.co/docs/trl/main/en/dpo_trainer) | Explicit prompt and preference formats, conversational templating, and tokenization. Accepting a JSON structure does not validate multi-turn action masks or workflow preference semantics. |
| T6 | [TRL GRPO trainer](https://huggingface.co/docs/trl/main/en/grpo_trainer) | Reward scaling, different losses, and generation/training importance corrections. Defaults change; record an installed revision rather than assuming every GRPO implementation is equivalent. |
| T7 | [OpenAI RFT guide](https://developers.openai.com/api/docs/guides/reinforcement-fine-tuning) | At access time the guide says the fine-tuning platform is winding down and closed to new users. This is a dated availability warning, not a claim that this project's data is accepted by an existing user's job. |

## Scheduling, isolation, and rights

| ID | Source | Verified use and limits |
| --- | --- | --- |
| S1 | [Proximal post-training infrastructure](https://www.proximal.so/blog/posttraining-infra/) | October 8, 2026. Fixed adapter per rollout, inference-local token capture, staleness gates, and durable checkpoint/rollout storage. Its private experiments and speed results were not reproduced here. |
| S2 | [Hong et al.: MISA-T, version 1](https://arxiv.org/abs/2608.11152v1) | August 11, 2026. Session admission, KV capacity/residency, and preserving mixed rollout proportions. This is distinct from a local host semaphore. |
| S3 | [Kwon et al.: PagedAttention](https://arxiv.org/abs/2309.06180) | KV memory management for language-model serving. Workbook KV arithmetic is an explicitly simplified architecture example, not this installed model's measured memory use. |
| S4 | [vLLM automatic prefix caching](https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/) | Reuses shared-prefix computation. The documented benefit concerns prefill, not generating new output tokens. No vLLM inference was run. |
| S5 | [Harbor separate verifier](https://docs.harborframework.com/tasks/separate-verifier) | Separate verifier is an explicit option; default mode is shared. Image/resource configuration and network policy require independent review. Framework membership alone does not establish isolation. |
| S6 | [Docker Engine security](https://docs.docker.com/engine/security/) | Kernel, daemon, configuration, and capability risks. Resource cgroups and access-control boundaries have different purposes. No host escape testing is claimed. |
| S7 | [gVisor security model](https://gvisor.dev/docs/architecture_guide/security/) | Additional defense against untrusted-code exploitation, with stated limits and other attack classes. Sandbox labels do not establish freedom from side channels or every escape. |
| S8 | [NIST SP 800-53 Rev. 5](https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final) | Public security/privacy control catalog. Landing page notes release 5.2.0 in August 2025. Workbook gates are design checks, not certification or legal compliance. |
| R1 | [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0) | License grants and redistribution conditions. Open-source permission is different from public-domain status; review exact files and third-party notices. |
| R2 | [Creative Commons public-domain tools](https://creativecommons.org/public-domain/) | Distinguishes CC0 dedication from the Public Domain Mark. Do not apply either to someone else's work without an appropriate rights basis. |
| R3 | [FrontierSWE v2 repository](https://github.com/Proximal-Labs/frontier-swe-v2) | At access time its notice supplies task content/tests for evaluation and refers to per-task attribution. A public repository does not establish blanket training or redistribution rights. |

## How to read the workbook's evidence

Differential-testing plans, permission matrices, severity weights, examples, budgets, and numeric prices are workbook designs. They are not vendor specifications or delivered platform features. The [foundation report](../report/world-engine-report.md), [follow-up appendix](../report/world-engine-follow-up.md), and [matched-study results](../workflow-model-study-results.md) carry actual product evidence separately. No exercise changes those receipts or their grades.

Before an implementation or commercial use, verify the exact software release, model terms, dataset provenance, provider availability, and permission to process each record. These source checks support technical planning; they are not legal advice or an authorization to create hosted jobs.
