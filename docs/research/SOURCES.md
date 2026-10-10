# Primary source ledger

Accessed 2026-10-10. These are the primary sources used for the report. A repository's default branch and a documentation page can change. Reproduction requires a pinned commit or release, image digest, and dataset version. Source statements below describe documentation, not independently measured performance.

## Environment platforms and infrastructure

| ID | Primary source | Evidence used and limits |
| --- | --- | --- |
| F1 | [Fleet](https://fleetai.com/) | Confirms the simulated-world company. `fleet.so` redirects here. Sparse homepage does not establish fidelity or performance. |
| F2 | [Fleet Python SDK](https://github.com/fleet-ai/fleet-sdk) | Archived public SDK. Documents `env.make`, seeded reset, SQL state access, versioned environment keys, instance lookup, and close. Apache-2.0 code. Does not disclose private grading implementation. |
| F3 | [Fleet harbor-train](https://github.com/fleet-ai/harbor-train) | Public training integration described as upstream SkyRL plus SkyPilot. Its existence does not validate this project's training integration. |
| P1 | [Proximal post-training infrastructure](https://www.proximal.so/blog/posttraining-infra/) | Published 2026-10-08. Modal model compute, Kubernetes sandboxes, fixed adapter per rollout, exact token capture, stale rollout limits, durable storage. Reported measurements are internal experiments. |
| P2 | [FrontierSWE v2 methodology](https://www.frontierswe.com/blog/v2) | September 2026. Long-horizon tasks, submission and anti-cheating methodology, evaluation limitations. |
| P3 | [FrontierSWE v2 repository](https://github.com/Proximal-Labs/frontier-swe-v2) | Public Harbor tasks with pinned images, reference solutions, and preflight checks. Evaluation-purpose notice and per-task upstream attribution require license review before training reuse. |
| H1 | [Harbor repository](https://github.com/harbor-framework/harbor) | Framework separates tasks, agents, sandboxes, trials, and jobs. Provides sandbox integrations and RL rollout generation. |
| H2 | [Harbor separate verifier](https://docs.harborframework.com/tasks/separate-verifier) | Documents verifier execution in a separate environment. A useful trust boundary, not proof every task is secure. |
| H3 | [Harbor ATIF](https://docs.harborframework.com/agents/atif) | Agent trajectory interchange format supports trace portability. JSON compatibility alone does not supply training tensor correctness. |
| V1 | [Prime Intellect Verifiers](https://github.com/PrimeIntellect-ai/verifiers) | Environment and evaluation library relevant to reusable rollout and rubric contracts. |
| U1 | [PufferLib](https://github.com/PufferAI/PufferLib) | RL simulator and training library. Its workload differs from long-context language agents. |
| U2 | [PufferLib 4.0 engineering](https://puffer.ai/blog/engineering-4.0/) | Explains profiling and native implementation choices. Its simulator step-rate claims cannot predict workflow-agent throughput. |
| M1 | [Modal Sandboxes](https://modal.com/docs/guide/sandboxes) | Runtime creation, execution, lifecycle, readiness, limits, and cleanup. Documents gVisor and VM runtimes. No Modal resources were created. |
| E1 | [E2B sandbox lifecycle](https://docs.e2b.dev/sandbox) | Create, connect, pause, resume, and terminate Linux VM lifecycle. Product limits depend on plan and may change. No E2B resources were created. |
| L1 | [Ollama chat API](https://docs.ollama.com/api/chat) | Documents JSON or schema format, stream control, thinking control, counts, timings, and log probabilities. Installed versions require separate capability checks. |
| H4 | [Terminal-Bench 2 log task](https://github.com/harbor-framework/terminal-bench-2/tree/2fd12b88aafdd04a52c298e3940bcb189f9766d6/log-summary-date-ranges) | Pinned CPU log-analysis task. Repository Apache-2.0 license and no-training canary must be retained. Official verifier downloads dependencies at runtime; an offline verifier needs a disclosed adaptation. |

## Workflow and computer-use benchmarks

| ID | Primary source | Evidence used and limits |
| --- | --- | --- |
| B1 | [WebArena](https://github.com/web-arena-x/webarena) | Self-hosted web task benchmark. Apache-2.0 repository. UI appearance alone is insufficient for outcome grading. |
| B2 | [BrowserGym](https://github.com/ServiceNow/BrowserGym) | Gymnasium browser lifecycle with reset, step, termination, truncation, and close. Integrates several task suites. |
| B3 | [OSWorld](https://github.com/xlang-ai/OSWorld) | Real desktop environments, execution-based tasks, parallel runners, and manual task examination. Real applications introduce heavier reset and dependency costs. |
| B4 | [tau-bench original paper](https://arxiv.org/abs/2406.12045) | Tool-agent-user workflow evaluation and repeated-trial reliability. |
| B5 | [tau2-bench repository](https://github.com/sierra-research/tau2-bench) | Policy-governed domain tools and user simulation. Current repository also documents tau3 updates and task fixes. Pin a version before comparing scores. MIT repository license. |
| B6 | [AgentBench](https://github.com/THUDM/AgentBench) | Multi-environment agent benchmark useful for broader cross-domain testing. Aggregate scores do not replace task-level analysis. |

## Post-training and evaluation

| ID | Primary source | Evidence used and limits |
| --- | --- | --- |
| T1 | [InstructGPT](https://arxiv.org/abs/2203.02155) | Demonstrations, preference rankings, reward learning, and RLHF pipeline. Historical experiment, not current model API guarantees. |
| T2 | [Direct preference optimization](https://arxiv.org/abs/2305.18290) | Preference objective relative to a reference policy. Preferences need comparable prompts and defensible labels. |
| T3 | [Proximal policy optimization](https://arxiv.org/abs/1707.06347) | Clipped surrogate policy optimization. Clipping does not guarantee safety or a fixed KL bound. |
| T4 | [DeepSeekMath](https://arxiv.org/abs/2402.03300) | Original GRPO formulation. Group-relative advantages remove the learned value model, not the need for fresh policy samples. |
| T5 | [TRL GRPO trainer](https://huggingface.co/docs/trl/main/en/grpo_trainer) | Practical current trainer settings and reward handling. Defaults and supported integrations change. |
| T6 | [verl](https://github.com/verl-project/verl) | Distributed post-training and rollout integration. Former `volcengine/verl` redirects to the current project. |
| T7 | [OpenRLHF](https://github.com/OpenRLHF/OpenRLHF) | Ray and vLLM based post-training framework with agentic and asynchronous training paths. |
| T8 | [RAGEN](https://github.com/mll-lab-nu/RAGEN) | Multi-turn agent RL and reasoning-collapse diagnostics. Prior organization URL redirects here. |
| T9 | [Miles](https://github.com/radixark/miles) | Public distributed training project underlying Proximal's internal fork. The internal fork is not publicly reproduced here. |
| A1 | [Anthropic agent evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) | Distinguishes task, trial, grader, transcript, and outcome. Supports combining final-state checks with targeted rubrics. |
| A2 | [Anthropic reward hacking study](https://www.anthropic.com/research/emergent-misalignment-reward-hacking) | Controlled coding reward-hacking study reports broader behavioral effects. Does not establish effects for every training setup. |
| A3 | [Anthropic data poisoning study](https://www.anthropic.com/research/small-samples-poison) | Motivates provenance and contamination review. Specific experiment cannot provide a universal safe contamination threshold. |
| O1 | [OpenAI working with evals](https://developers.openai.com/api/docs/guides/evals) | Hosted evaluation concepts and graders. This build runs its own local workflow evaluations. |
| O2 | [OpenAI reinforcement fine-tuning](https://developers.openai.com/api/docs/guides/reinforcement-fine-tuning) | Hosted reward-based fine-tuning workflow. JSONL export is not evidence a hosted trainer accepts an arbitrary multi-turn environment. |
| T10 | [Potential-based reward shaping](https://ai.stanford.edu/~ang/papers/shaping-icml99.pdf) | Ng, Harada, and Russell, ICML 1999. Policy-invariance conditions for shaping. |
| T11 | [Statistical uncertainty in RL evaluation](https://arxiv.org/abs/2108.13264) | Agarwal et al., 2021. Few-run evaluation uncertainty and more robust aggregate metrics. |

## Source discipline

No third-party marketing comparison establishes a numerical advantage for World Engine. Fleet's archived SDK is evidence of its documented client lifecycle, not a complete description of its hosted system. Proximal's public benchmark repository is evidence of task structure, while its private training fork and cluster configuration remain unavailable.

The separate public-task runner vendors one evaluation fixture from [Terminal-Bench 2](https://github.com/harbor-framework/terminal-bench-2/tree/2fd12b88aafdd04a52c298e3940bcb189f9766d6/log-summary-date-ranges), pinned to revision `2fd12b88aafdd04a52c298e3940bcb189f9766d6`. Its Apache 2.0 license, author attribution, canary, and source manifest are retained. This fixture and its traces remain evaluation-only and outside training exports. The [public-task protocol](../public-benchmark.md) discloses the offline verifier adaptation. Before importing any further source, inspect its exact revision's license, data terms, model license, attribution requirements, and restrictions on training use. Publicly readable material is not necessarily public domain.
