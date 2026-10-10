# World Engine build board

Owner: research worker. Updated 2026-10-10. This board describes the current rebuild. Older specialist notes and the failure-to-intervention prototype are historical material.

## Intended result

A local, runnable platform for constructing workflow environments, running concurrent agent episodes, inspecting trusted grades and replayable traces, and exporting curated training data. A substantial research report explains the design and its limits. The delivered build must not claim to train models, provide cloud isolation, or match production applications without evidence.

## Ownership

| Worker | Owns | Does not edit |
| --- | --- | --- |
| Root | Integration, final QA, repository review, Git and GitHub delivery | Worker-owned files during active edits |
| Engine | Python SDK, FastAPI, SQLite state and persistence, workflow worlds, jobs, policy providers, exports, replay, backend tests | Web and report files |
| Console | Vite React console, assets, UI tests and browser QA; public-task runner, ATIF adapter, native Ollama adapter/recorder and their scoped tests/docs/receipts | Workflow generators/graders and foundation report files |
| Research | Foundation documentation and this board; approved CRM/refund generators and graders, `ScriptedProvider` fixes, variant tests/collector/docs; narrowly scoped IncidentControl grader/version and integrity tests/docs; read-only native review and proposal docs | Other backend modules, HTTPProvider, web, commits |

## Acceptance criteria

| Requirement | Evidence required | State |
| --- | --- | --- |
| Executable environment lifecycle | Reset, observation, step, terminal grade, episode cleanup, runnable SDK example | Delivered; foundation tests, replay, and executable labs verified |
| Meaningful workflow worlds | Three task families with trusted state, permissions, goals, and concrete reward-hacking tests | Implemented; backend tests green |
| Concurrent jobs | Bounded concurrency, independent episode state, persisted status, cancellation semantics | Implemented; writer lease and global limit 8 |
| Trace provenance | Version, seed, policy, action, observation, trusted outcome, digest or replay consistency | Implemented; code hashes and local model digest recorded |
| Honest data exports | Separate SFT, preference, and rollout schemas, curation rules, no hidden grader leakage | Implemented; train-only/replay gate and exact SFT inputs |
| Usable console | Create run, inspect progress and episode, compare grades, review provenance, download exports | Implemented; browser receipt records 35 connected checks |
| Local provider default | No credentials, paid model calls, paid infrastructure, or new accounts required | Verified existing Qwen3 8B; no download or paid call |
| Documentation | Verified startup commands, SDK guide, runbook, research report and source ledger | Written; 18-page PDF compiled and all final pages visually verified; executable labs verified |
| Security limits | In-process isolation explicitly distinguished from an untrusted-code sandbox | Documented; public task runtime limits, write probe and cleanup verified |
| Reproducible verification | Focused backend tests, frontend build, desktop and mobile browser evidence | Root verified 82 foundation tests and Ruff; nine delivered traces replay; 35 connected UI checks |
| Repository delivery | User-authorized GitHub workflow, atomic CI-passing changes, attached PR when created | Foundation PR #1 published; root verified backend, console, and GitGuardian CI success |

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

Root's independent review additionally found that a forged episode envelope could retain valid transitions/raw grade while falsifying reward or success labels for SDK ingestion. The final validator recomputes authoritative outcomes and validates status, termination, lineage, split, contexts, and counts. Root verified 82 foundation tests, including forgery regressions, and all nine delivered model records replayed at the foundation source. Later world revisions require the pinned foundation checkout for those historical records. The validator checks coherence, not collection authenticity or recursively imported dependency code. ATIF remains excluded from the foundation release record.

`examples/benchmark-results/benchmark.json` records 54 scripted batches and 1,620 executions with 30 unique seeds per world, three repetitions, and concurrency 1/4/8. Reference policies passed; incomplete baselines failed. `local-model.json` records nine paired attempts: Qwen passed the single sampled refund task, failed CRM and incident tasks at the 20-decision limit. No model improvement or population estimate is implied.

The evaluation-only public Terminal-Bench fixture passed its original Python tests under the reference algorithm and rejected the wrong-CSV control. The final native-tool attempt executed eight valid commands and failed the task with empty CSV; its immutable report is `artifacts/public-benchmark/native-tools-v2-final/report.json`, controller revision `4b753e319fd013790524ae440d1abb9ecae9f92a`, clean controller source. Earlier malformed-JSON attempts remain separate: the corrected JSON-v1 attempt made eight requests but no commands, and the initial receipt admits missing raw-response capture. Source attribution, Apache 2.0 license, canary, adaptation, resource probe, cleanup, and evaluator boundaries are documented in `docs/public-benchmark.md`.

Final-core lab recollection verified 20 reference successes against 20 incomplete-policy failures, 20 deterministic replays, stable split counts 14 train/4 validation/2 test, 46 SFT decisions, and 14 comparable preference/grouped scenarios. All six held-out episodes were excluded. The local foundation is delivered; production-distributed execution, tenancy, real trainer integration, real application parity, and larger independent evaluations remain deferred evidence gates, not acceptance claims.

Final local-model collection used recoverable core revision `7fdf4c6ae511dc81cc4074ea54122c0671ba2469`, clean implementation scope, and preserved nine full operator episodes in `local-model-traces.jsonl`; all nine replayed on the foundation source. Use the pinned foundation checkout after subsequent environment revisions. The older uncommitted attempt is archived separately with no source-recovery guarantee. Final UI receipt at 05:03:19 UTC records 35 checks and no browser errors. Same-source schema-cache before/after records demonstrate observed local ratios 1.71--3.27x under uncontrolled background load; the separate 25-ms simulated-I/O control demonstrates scheduler overlap, not real inference/cloud performance.

Root separately verified the preserved historical failure-to-intervention prototype: `npm test` passed 179 tests in six files and `npm run typecheck` passed using its installed dependencies. This is historical regression evidence, not part of the new Python test count and not a dependency of the current platform.

Foundation delivery: [PR #1](https://github.com/nthpaul/world-engine/pull/1), published at head `1675734`. Root verified backend, console, and GitGuardian checks succeeded. Replay-envelope hardening was committed separately at `8e000412` before the final documentation/evidence commit. The foundation report is an immutable historical release record; later follow-up capabilities and test counts must not be silently added to it.

## Overnight follow-up backlog

These are ordered proposed tasks, distinct from foundation acceptance and not delivered claims. Work must fit the original eight-continuation window, existing local resources, and zero paid-call/cloud budget. Do not add redundant polish merely to consume the window. Each completed task needs committed source, focused tests, reproducible artifacts, and an explicit account of limitations.

ATIF next-phase task: Console owns the upstream-validated adapter in the new files listed in ownership. Root reports collection completed and source/evidence committed at `b52542a`. It remains a separate integration/delivery from foundation PR #1. Eight unit tests plus one optional upstream-validation test are additional to, not part of, the 82-test foundation count. Do not retrofit the foundation report with this later capability.

Workflow expansion: Root approved CRM canonical/survivor ties and fallback fixtures plus refund eligibility/approval boundaries, not the optional blocked-incident outcome. Research implemented deterministic four-case CRM and eight-case refund generators, reference-policy funds handling, and a date-independent incomplete CRM baseline. The initial `1.1.0` source at `6cc84237384f04b5a205b04a127ce99ba9ff00d9` collected 128 replay-verified attempts; its source/receipts were committed before later review found an approval-history grader gap. Preserve those artifacts, with the integrity sidecar, as historical execution evidence. CRM remains `1.1.0`; refund is now `1.1.1`. A manually appended forged approval could pass on an ineligible request despite the normal tool boundary denying it; the corrected grader preserves initial approvals and allows at most one exact eligible finance approval, while allowing valid voluntary approval. The additional 105 focused tests pass. Root committed the correction at `afb66c7` and published dependent PR #3. The hardened receipt at source `4bc73fe6` now records 64 unique world/seed tasks, 128 matched attempts, 64 reference passes and 64 baseline failures, equal 20-decision/30-second bounds, concurrency 1, and no model calls. Root independently replayed all 128 rows. No learned-model improvement or production-application parity is claimed. Current docs require pinned source for old receipts; the foundation report and artifacts remain unchanged.

Incident integrity: Root reproduced four trusted-state corruption cases that could retain full credit in the historical grader. Research anchored incident/service/change identity, immutable change metadata, exact allowed audit sequence, review/check status, and at most one authorized execution to the initial fixture. Both check orders and legitimate partial/idempotent operations remain supported. Incident version is now `1.0.1`; 43 new integrity tests cover positive prefixes and counterfactual corruption. Root committed `b5e349b`, opened dependent PR #4, and reported 169 focused tests plus Ruff passing. No ordinary model-tool exploit was demonstrated; the correction strengthens trusted-state grading and does not establish hostile-host authenticity.

Current runtime source is committed at `7de25124fd752acf61571ec0860309c139652fff`; root reports all CI checks passing for PR #6 at that head. It includes local Docker integration `28172e5`, incident correction `b5e349b`, and the reviewed native JSON-null replay-label fix. The completed Docker receipt at source `4bc73fe6` records 24 successful fresh-session executions over four repeated synthetic inputs, concurrency 1/2 and three trials, zero model calls, and empty owned-resource cleanup per trial. Root independently checked the receipt hash and cleanup fields. This is local lifecycle I/O, not inference or cloud throughput.

Final native collection at `7de25124` is complete: six predeclared cases, 48 recorded transport attempts, four business-task passes and two clean successes. CRM seeds 42/730 failed with 7/9 decisions and 5/7 invalid actions; refund both passed with five decisions and zero invalid actions; incident both passed with 13/9 decisions and 5/1 invalid actions. Complete reported usage sums to 71,531 input and 1,258 output tokens; collection elapsed 88.289 seconds. Root and console independently verified six replays and six actual pinned Harbor schema validations. Console verified 18 training-format exclusions across SFT/DPO/grouped exports. Records are evaluation-only and do not attest frozen weights or establish a native-versus-JSON comparison. No paid calls or model downloads occurred. The separate earlier research native/ATIF mock review passed 65 tests with two optional skips and made no model calls.

Trainer preprocessing is evidence-blocked: project, bundled and system Python runtimes lack torch, transformers, TRL and tokenizers. Public installed Ollama metadata contains vocabulary, merges, chat template and special IDs, but there is no verified exact encoder/template executor or trainer/checkpoint path. `docs/trainer-preprocessing-feasibility.md` records the audit without claiming readiness. `docs/workflow-model-study.md` proposes, but does not authorize, a 32-task paired native-versus-JSON study with fixed seeds and resource caps. The discovery-based `docs/access-provisioning-proposal.md` is frozen to the root/engine agreement: four grant/recovery cases and four denials, independent exact staff/email searches plus employee/manager detail reads, broad-hint distractors on positive cases too, and a 19-decision worst reference path including finish. No implementation or model result is claimed by its design freeze.

Follow-up evidence/current guides were committed at `0cf41c7efcb5a1af345bae1c31ebfe6e096b7efa` and published as dependent PR #7, based on #6. Root verified 384 passing tests, five optional skips, Ruff and a clean diff at that release. These counts do not include later draft work. Research owns the separate dated appendix and current-guide updates; the foundation report/results remain unchanged. Appendix drafting was released after the evidence commit, then publication was held for the newly reproduced CRM/refund grader gaps below. The five-page draft compiles but is not yet a final visually verified publication.

Complete-state grader follow-up: root and research independently reproduced six completed-state corruptions retaining full reward in the `4bc73fe6`/`7de25124` worlds: CRM/refund role replacement, CRM marker-only/wrong-canonical audit, refund missing audit/payment ID/key. Normal tools were not exploited and forged transitions would not replay. Research now independently folds exact initial-derived change certificates and compares whole operational state, without calling `apply`, replay or a provider. CRM source is `1.1.1`; refund is `1.1.2`; source review/commit and corrected-source collection are pending. Legitimate CRM transfer-before-void ownership is now accepted as a separate behavior correction; all resource orders, valid prefixes and retries remain supported. Refund preserves eligible voluntary-review ordering before/after payment or closure while requiring above-limit review before payment. New integrity file has 97 tests; the focused integrity/variant/environment/incident run passed 266 tests, and affected Ruff passed. A production AST guard rejects `assert`, with actual `python -O` rejection proof. Protocol v3 refresh retains old seeds/controls/budgets and makes no collection claim. Historical JSON/outcomes remain untouched; sidecars document the newly discovered limits. The proposed, unexecuted larger study updates world versions only.

Current parallel phase ownership: console owns structured-JSON wire recording/HTTP lifecycle work, with no authorized inference; engine owns the new partial-observation access module and holds registry integration until root releases the HTTP barrier. Access grading must independently validate contracts with explicit guards, never `assert` or verifier `apply`. Provider-close failure handling and access integration are pending, not delivered by PR #7 or the selected receipts. Research owns only the approved CRM/refund graders, integrity tests, protocol-version refresh and documentation during this phase. No new collection starts before root commits and releases the complete runtime freeze.

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
