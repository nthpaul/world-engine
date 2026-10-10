# World Engine

Local workflow environments, bounded agent rollouts, trusted grades, and trace curation. The Python SDK and operator console run without model credentials. An optional local Ollama provider runs an existing model. Remote model calls require explicit opt-in.

## Run locally

Use Python 3.11 or newer, `uv`, and Node.js 22 or newer. In one terminal:

```sh
uv sync --extra dev
uv run python -m world_engine serve
```

In a second terminal:

```sh
cd web
npm ci
npm run dev
```

Open [the console](http://127.0.0.1:5173). The API listens on [loopback port 8000](http://127.0.0.1:8000/api/health). Start with the scripted reference and baseline providers to inspect successful and incomplete workflows.

## Workflows and data

| World | Outcome checked |
| --- | --- |
| `crm-merge` | Canonical customer, ticket ownership, invoice conservation, unrelated records, merge audit |
| `refund-ops` | Eligibility, exact payment, finance approval, idempotency, ticket resolution |
| `incident-control` | Acknowledgement, preflight checks, approval, healthy rollback, preserved service data |

Current versions are CRM `1.1.0`, refund `1.1.1`, and incident `1.0.1`. [Workflow variants](docs/workflow-variants.md) and [incident integrity](docs/incident-integrity.md) document their rule-boundary coverage and authoritative grader corrections.

Runs persist episode state, tool events, grades, scenario splits, provenance, and fingerprints in SQLite. Replay recomputes transitions and final grades. Exports provide SFT candidates, comparable DPO pairs, raw grouped rollouts, and traces. Raw grouped rollouts are explicitly `trainable: false`; a PPO or GRPO trainer still needs sampled tokens, masks, behavior probabilities, and a fixed policy checkpoint.

[ATIF](docs/atif.md) provides pinned-schema operator interchange. The [native Ollama tool adapter](docs/native-provider.md) is SDK-only and excluded from SFT/DPO/grouped training exports; the registered `local` provider still uses JSON actions. The separate [local Docker executor](docs/docker-executor.md) runs constrained terminal/file sessions with detached artifact grading, not a new HTTP workflow provider.

## Read and verify

- [Operations guide](docs/OPERATIONS.md): startup, SDK use, API routes, exports, recovery, and limits.
- [Technical report](docs/report/world-engine-report.md) and [formal PDF](docs/report/world-engine-report.pdf): environment design, fidelity, reward hacking, post-training, evaluation, and throughput.
- [Learning labs](docs/report/learning-labs.md): six reproducible experiments with worked interpretation.
- [Primary sources](docs/research/SOURCES.md): verified Fleet, Proximal, Harbor, PufferLib, benchmark, and training references.
- [Roadmap](docs/ROADMAP.md) and [build evidence](coordination/BUILD.md): explicit completion gates and remaining work.
- [Historical prototype](prototypes/failure-to-intervention/README.md): earlier SQLite failure-to-intervention experiment.

Run focused backend checks with `uv run pytest` and `uv run ruff check src tests`. Build the console with `npm run build` in `web`. Browser QA instructions live in [the console guide](docs/ui.md).

Measured evidence includes [the scripted workload matrix](examples/benchmark-results/benchmark.md), [paired local-model/reference/baseline attempts](examples/benchmark-results/local-model.md), and [one adapted public Terminal-Bench task](docs/public-benchmark.md). The public native-tool attempt executed eight shell commands but failed to produce the required CSV; earlier malformed-JSON attempts are retained separately. These are bounded integration samples, not general capability scores.

The foundation local model passed the single sampled refund task and failed the sampled CRM and incident tasks. Its nine records, the report, and learning labs describe foundation source, not later workflow versions. CRM/refund version 1.1 adds deterministic rule-boundary fixtures; module fingerprints change for all built-in worlds. Replay older receipts in the pinned foundation checkout `1675734`, as shown in [operations](docs/OPERATIONS.md#export-candidate-data-and-replay). Do not overwrite or relabel foundation evidence under new generators.

The separate [six-case native evaluation](artifacts/native-provider/final/report.md) at source `7de2512` recorded 48 transport attempts: four business-task passes, but only two clean successes with no invalid actions. Both CRM cases failed; refund and incident cases passed, with invalid incident actions retained. All six episodes replayed and their ATIF documents passed pinned Harbor schema validation. This is not a matched comparison against the historical JSON sample. The [hardened scripted study](artifacts/workflow-variants/hardened/report.md) covers 64 unique tasks and 128 attempts without inference; the [Docker receipt](artifacts/docker-executor/final/lifecycle.json) covers 24 executions of four repeated synthetic inputs, also without inference.

## Scope

The included worlds simulate business rules in trusted Python objects. They do not replicate a production application's visual interface or sandbox arbitrary code. The local API is a single-process operator service, not a multi-tenant deployment. No model training, cloud sandbox orchestration, production-transfer result, or competitor speed advantage is claimed. A successful scripted reference execution verifies implementation behavior; any actual model or public benchmark result must be read with its sample count and execution protocol.
