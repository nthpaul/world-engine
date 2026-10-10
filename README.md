# World Engine

Local workflow environments, bounded agent rollouts, trusted grading and trace curation. The Python SDK and operator console work with scripted policies without model credentials. Optional providers use an already-installed Ollama model or explicitly enabled remote inference.

The new [real GitLab browser path](docs/gitlab-browser.md) uses a pinned GitLab CE
instance, ordinary-user browser actions, post-login screenshots/video, durable
traces and a separate persisted-state verifier. Start there for the phases 1--3
architecture, local prerequisites and SDK. The four Python worlds below remain
simulation diagnostics; their historical results are unchanged.
The [GitLab results and media guide](docs/gitlab-browser-results.md) records the
successful browser reference, the failed local-model rollout, isolated grading,
screenshots, videos, timings and preserved qualification failures.

## Run locally

Use Python 3.11 or newer, `uv`, and Node.js 22 or newer. Start the API:

```sh
uv sync --extra dev
uv run python -m world_engine serve
```

In another terminal, start the console:

```sh
cd web
npm ci
npm run dev
```

Open [the console](http://127.0.0.1:5173). It uses the API at [127.0.0.1:8000](http://127.0.0.1:8000/api/health); the default local SQLite history persists across restarts. Start with Scripted Oracle and Scripted Baseline to inspect successful and incomplete workflows. A new clone does not require the development team's experiment database.

## Four workflows

| World / version | Trusted outcome |
| --- | --- |
| `crm-merge` / `1.1.1` | Canonical customer, resource ownership, invoice conservation and merge audit |
| `refund-ops` / `1.1.2` | Eligibility, exact payment, finance review, idempotency and ticket resolution |
| `incident-control` / `1.0.1` | Acknowledgement, preflight checks, approval, healthy rollback and preserved service data |
| `access-provisioning` / `1.0.0` | Discovered identity/manager, least privilege, service reviews and exact grant or justified denial |

Access exposes bounded paged discovery rather than its private directory/catalog. Its outcome reward is binary; legacy worlds retain diagnostic shaping, which can be positive without a business pass. [Workflow variants](docs/workflow-variants.md), [grader integrity](docs/workflow-grader-integrity.md) and [access design](docs/access-provisioning.md) explain the rules and adversarial checks.

## Providers and SDK

`scripted-oracle` and `scripted-baseline` require no credentials. `local` uses structured JSON with an installed Ollama model. Native aliases `local-tools` (v1) and `local-tools-ledger` (v2) work in the API, console and CLI, with mandatory evaluation-only operation; the CLI disables paid calls for them. Native default concurrency is one, explicitly editable within one through eight. Legacy providers retain default four. Remote OpenAI/Anthropic calls require both a server-wide paid-call gate and explicit per-run opt-in.

The native SDK configuration is imported separately from `world_engine.native_config.NativeRunConfig`; legacy `RunConfig` and shared grader fingerprints remain unchanged. Native v2 regenerates replay requests from trusted reset observations and verified transitions. [Operations](docs/OPERATIONS.md) includes provider ownership and cleanup; [SDK world](examples/sdk_world.py) and [custom provider](examples/custom_provider.py) are executable extensions. The [architecture guide](docs/architecture.md) describes lifecycle, admission, storage and trust boundaries.

The separate [local Docker executor](docs/docker-executor.md) runs constrained terminal/file sessions with detached artifact grading. It is not the isolation mechanism for ordinary Python worlds or a cloud execution service.

## Data contracts

SQLite retains append-only episode/tool records, trusted grades, scenario splits and source fingerprints. Replay recomputes transitions and outcomes; old receipts require their recorded source checkout. Historical grader gaps, failed attempts and original grades remain preserved rather than relabeled.

Exports provide exact-context SFT candidates, strictly comparable DPO pairs, traces and raw grouped trajectories. Heldout/evaluation records and unsupported native/recorded-JSON protocols are excluded from training formats, including alternative candidate pools. Groups remain `trainable: false`: sampled tokens, masks, behavior probabilities and a fixed checkpoint are not supplied. [ATIF](docs/atif.md) is pinned Harbor-schema operator interchange, not a trainer batch. The [scripted candidate corpus](docs/scripted-candidate-results.md) contains 128 verified episodes and train-only exports of 397 SFT decisions, 51 DPO pairs and 51 nontrainable groups; no model was trained.

## Evidence and teaching

- [Foundation report](docs/report/world-engine-report.pdf): environment design, behavioral fidelity, reward hacking, post-training and evaluation. Its three-world release and 82-test count are immutable historical evidence.
- [Follow-up appendix](docs/report/world-engine-follow-up.md) and [PDF](docs/report/world-engine-follow-up.pdf): dated source corrections, measured outcomes, failed attempts and boundaries.
- [Learning labs](docs/report/learning-labs.md) and [advanced workbook](docs/report/advanced-environment-labs.pdf): worked exercises; the advanced PDF has twelve pages, nine labs and 27 primary sources.
- [Matched adapter results](docs/workflow-model-study-results.md), [access context results](docs/access-ledger-study-results.md) and [admission results](docs/model-concurrency-study-results.md): separate locked experiments, not pooled capability scores.
- [Public benchmark](docs/public-benchmark.md), [console proof](docs/ui.md), [primary sources](docs/research/SOURCES.md), [roadmap](docs/ROADMAP.md) and [build board](coordination/BUILD.md): reproducibility, rights and remaining gates.
- [Historical prototype](prototypes/failure-to-intervention/README.md): preserved earlier failure-to-intervention work, separate from the current SDK.

At source `0f51b903` on October 10, 2026, verification passed all 1,743 tests, including optional actual Harbor and approved-existing-image Docker checks, with Ruff and the frontend build. The five-phase console receipt at `b4501029` passed 129 checks, with 34 new scripted episodes and two unchanged model imports; it is not new native API inference. The CPU profile saved 192 episodes and measured 728 redundant observation reads removed in profiled trials. The separate SDK admission study at `1d9f2315` observed sixteen business passes at admission one versus thirteen at two on eight repeated tasks; client overlap did not improve useful throughput in that run. Detailed denominators, partial usage and independent validations live in the linked evidence, not a production-performance claim. The later [native API smoke](artifacts/native-api-smoke/20261010-v1/report.json) verified two clean admissions on the same refund task, not a capability comparison. The preserved first controls attempt failed 360px visual acceptance; corrected controls/readonly receipt QA passed 65 checks without new inference.

Run `uv run pytest` and `uv run ruff check src tests`. Build the console with `npm run build` in `web`; [browser QA](docs/ui.md) requires a fresh output directory and makes no model calls by default.

## Scope

The four original worlds are synthetic trusted-Python tool workflows. The new
browser path runs real GitLab but covers one original workflow and a selected
persisted-state projection, not complete production parity. Both use a loopback,
single-process operator service without authentication or tenant isolation. No
trained checkpoint, cloud orchestration, production transfer, tokenizer-context
guarantee or competitor advantage is claimed. Scripted passes establish
implementation behavior; model results require their fixed tasks and failures.
