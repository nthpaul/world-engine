# World Engine build board

Owner: research worker. Updated 2026-10-10. This board describes the current rebuild. Older specialist notes and the failure-to-intervention prototype are historical material.

## Intended result

A local, runnable platform for constructing workflow environments, running concurrent agent episodes, inspecting trusted grades and replayable traces, and exporting curated training data. A substantial research report explains the design and its limits. The delivered build must not claim to train models, provide cloud isolation, or match production applications without evidence.

## Ownership

| Worker | Owns | Does not edit |
| --- | --- | --- |
| Root | Integration, final QA, repository review, Git and GitHub delivery | Worker-owned files during active edits |
| Engine | Python SDK, FastAPI, SQLite state and persistence, workflow worlds, jobs, policy providers, exports, replay, backend tests | Web and report files |
| Console | Vite React console, assets, UI tests and browser QA; public-task runner scopes; next-phase only: `src/world_engine/atif.py`, `tests/test_atif.py`, `examples/export_atif.py`, `docs/atif.md`, `artifacts/atif/` | Existing backend modules and report files |
| Research | `docs/research/`, `docs/report/`, `docs/OPERATIONS.md`, `docs/ROADMAP.md`, `README.md`, `AGENTS.md`, `.gitignore`, this board | Backend, web, commits |

## Acceptance criteria

| Requirement | Evidence required | State |
| --- | --- | --- |
| Executable environment lifecycle | Reset, observation, step, terminal grade, episode cleanup, runnable SDK example | Implemented; verification in progress |
| Meaningful workflow worlds | Three task families with trusted state, permissions, goals, and concrete reward-hacking tests | Implemented; backend tests green |
| Concurrent jobs | Bounded concurrency, independent episode state, persisted status, cancellation semantics | Implemented; writer lease and global limit 8 |
| Trace provenance | Version, seed, policy, action, observation, trusted outcome, digest or replay consistency | Implemented; code hashes and local model digest recorded |
| Honest data exports | Separate SFT, preference, and rollout schemas, curation rules, no hidden grader leakage | Implemented; train-only/replay gate and exact SFT inputs |
| Usable console | Create run, inspect progress and episode, compare grades, review provenance, download exports | Implemented; browser receipt records 35 connected checks |
| Local provider default | No credentials, paid model calls, paid infrastructure, or new accounts required | Verified existing Qwen3 8B; no download or paid call |
| Documentation | Verified startup commands, SDK guide, runbook, research report and source ledger | Written; 18-page PDF compiled and all final pages visually verified; executable labs verified |
| Security limits | In-process isolation explicitly distinguished from an untrusted-code sandbox | Documented; public task runtime limits, write probe and cleanup verified |
| Reproducible verification | Focused backend tests, frontend build, desktop and mobile browser evidence | Root verified 82 foundation tests and Ruff; nine delivered traces replay; 35 connected UI checks |
| Repository delivery | User-authorized GitHub workflow, atomic CI-passing changes, attached PR when created | Root owns |

## Phases

1. Freeze concrete lifecycle and API contracts. Verify competitors against primary sources.
2. Build independent workflow state, local policies, bounded jobs, grades, and traces.
3. Connect the console to actual APIs. Exercise successful, failing, and cancelled runs.
4. Inspect the delivered code and revise docs to its exact capabilities.
5. Run focused checks and browser QA. Record measured evidence and remaining limits.
6. Root reviews the final diff and completes the authorized repository delivery.

## Evidence and limitations

Research sources will live in `docs/research/SOURCES.md`, with exact URLs and access dates. Runtime evidence belongs in `docs/OPERATIONS.md` and the final verification record.

The root created `codex/world-engine-platform` from clean `master` at `0561db5`. The user authorized an overnight continuation. The native heartbeat `complete-world-engine-overnight` checks useful work hourly for up to eight continuations, approximately eight hours. After the foundation release, it can pursue the ordered follow-up backlog below within the original window. Foundation acceptance is not authorization to claim the backlog delivered. Stop when the bounded window ends, the useful authorized backlog is complete, or a required external decision prevents safe progress. Do not make paid model calls, provision paid cloud resources, create accounts, download model weights, or send external messages. Root owns the automation, task selection, and Git delivery.

The build starts without production traffic, customer task distributions, human expert validation, real model training, multi-tenant security, or cloud sandbox provisioners. Synthetic successes establish implementation behavior. They do not establish model improvement, business task fidelity, transfer to production, or superiority to another platform.

## Review and verification

Root verified the API on `127.0.0.1:8000`: paid calls disabled, process-wide episode concurrency 8. Engine reported 31 passing tests and a clean Ruff check at this checkpoint. Root reported no known vulnerabilities from the console's npm audit. These are intermediate checks, not the final release record.

Independent research review identified four issues: held-out training exports, reconstructed rather than exact SFT policy inputs, shared database recovery ownership, and confidence inflation from repeated deterministic scenarios. Engine corrected the boundaries with train-only filtering, exact recorded decision inputs, a nonblocking scheduler lease, and unique-scenario success intervals. Final tests and evidence remain required.

Root's independent review additionally found that a forged episode envelope could retain valid transitions/raw grade while falsifying reward or success labels for SDK ingestion. The final validator recomputes authoritative outcomes and validates status, termination, lineage, split, contexts, and counts. Root verified 82 foundation tests, including forgery regressions, and all nine delivered model records still replay. The validator checks coherence, not collection authenticity or recursively imported dependency code. ATIF next-phase work remains excluded.

`examples/benchmark-results/benchmark.json` records 54 scripted batches and 1,620 executions with 30 unique seeds per world, three repetitions, and concurrency 1/4/8. Reference policies passed; incomplete baselines failed. `local-model.json` records nine paired attempts: Qwen passed the single sampled refund task, failed CRM and incident tasks at the 20-decision limit. No model improvement or population estimate is implied.

The evaluation-only public Terminal-Bench fixture passed its original Python tests under the reference algorithm and rejected the wrong-CSV control. The final native-tool attempt executed eight valid commands and failed the task with empty CSV; its immutable report is `artifacts/public-benchmark/native-tools-v2-final/report.json`, controller revision `4b753e319fd013790524ae440d1abb9ecae9f92a`, clean controller source. Earlier malformed-JSON attempts remain separate: the corrected JSON-v1 attempt made eight requests but no commands, and the initial receipt admits missing raw-response capture. Source attribution, Apache 2.0 license, canary, adaptation, resource probe, cleanup, and evaluator boundaries are documented in `docs/public-benchmark.md`.

Final-core lab recollection verified 20 reference successes against 20 incomplete-policy failures, 20 deterministic replays, stable split counts 14 train/4 validation/2 test, 46 SFT decisions, and 14 comparable preference/grouped scenarios. All six held-out episodes were excluded. The local foundation is delivered; production-distributed execution, tenancy, real trainer integration, real application parity, and larger independent evaluations remain deferred evidence gates, not acceptance claims.

Final local-model collection used recoverable core revision `7fdf4c6ae511dc81cc4074ea54122c0671ba2469`, clean implementation scope, and preserved nine full operator episodes in `local-model-traces.jsonl`; all nine replay on delivered source. The older uncommitted attempt is archived separately with no source-recovery guarantee. Final UI receipt at 05:03:19 UTC records 35 checks and no browser errors. Same-source schema-cache before/after records demonstrate observed local ratios 1.71--3.27x under uncontrolled background load; the separate 25-ms simulated-I/O control demonstrates scheduler overlap, not real inference/cloud performance.

Root separately verified the preserved historical failure-to-intervention prototype: `npm test` passed 179 tests in six files and `npm run typecheck` passed using its installed dependencies. This is historical regression evidence, not part of the new Python test count and not a dependency of the current platform.

## Overnight follow-up backlog

These are ordered proposed tasks, distinct from foundation acceptance and not delivered claims. Work must fit the original eight-continuation window, existing local resources, and zero paid-call/cloud budget. Do not add redundant polish merely to consume the window. Each completed task needs committed source, focused tests, reproducible artifacts, and an explicit account of limitations.

Active next-phase task: Console is implementing the upstream-validated ATIF adapter in the new files listed in ownership. Status: in progress. It is excluded from foundation-release claims and will be reviewed and verified separately, potentially in a dependent GitHub PR. Do not delay the foundation's report for this new feature or mark native Harbor compatibility complete from a draft exporter.

1. Add a real Harbor/ATIF compatibility adapter. Validate output against the pinned native schema and test supported and rejected structures. Preserve tool, timing, source, and usage provenance without inventing missing fields or importing hidden tests into agent observations.
2. Reuse the proven standalone Docker lifecycle for a narrowly scoped local execution integration. Keep separate evaluation, no-egress/nonroot/resource boundaries, artifact checks, and cleanup tests intact. Do not replace a tested boundary with a speculative general provider layer.
3. Add meaningful workflow variants and red-team cases. Vary rules, dependencies, ambiguity, permissions, and retry failures, not just names. Keep stable task lineage across source revisions and test cross-split contamination defenses.
4. Add a native tool-calling model adapter when the installed model/runtime supports it. Record exact request and response transcripts, tool identities, refusals, and usage. Do not fabricate sampled tokens or old-policy probabilities from text.
5. Run a larger locked same-budget evaluation using the already-installed small model. Commit the protocol first, fix task identities and bounds, retain all outcomes and repeated-attempt grouping, and distinguish integration failures from executed-policy failures. Set local duration and concurrency caps before starting.
6. Add a concrete trainer preprocessing adapter only when an appropriate tokenizer and trainer are already available locally. Verify chat formatting, role boundaries, loss masks, source rights, and split exclusion. No new weights, hosted training, cloud provisioning, or claims of learning without an actual checkpoint and controlled evaluation.

The distributed execution, multi-tenant deployment, application-parity, and training claims in the roadmap remain gated even if some local follow-up tasks complete. Root must update this board with actual evidence rather than converting proposed tasks into retrospective claims.

## Ongoing boundaries

- SDK and API usage are documented in `docs/OPERATIONS.md`; commands must remain checked against the final build.
- Snapshot isolation and deterministic replay need separate proof. A seed alone does not make networked execution deterministic.
- Curated exports must retain failure and selection provenance. A successful reference policy is not an independently evaluated learned model.
- Hidden evaluator state must be omitted from agent observations and training exports. Operator access in the local console is a different trust level.
