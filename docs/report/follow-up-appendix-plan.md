# Follow-up evidence appendix plan

Status: documentation plan, not a revised foundation report or a new evaluation. The access-world design is frozen; its implementation and evaluation remain separate work. No inference or runtime edit is required by this plan.

Keep `world-engine-report.md`, its TeX/PDF, and original receipts unchanged. Author a separate dated follow-up appendix after root confirms the selected source and receipt commits. The appendix should explain what changed, show bounded evidence, and identify what remains unmeasured. Link to the foundation report rather than merging later counts into its release record.

## Proposed structure

Target four to six pages, plus direct evidence links. Use the foundation's restrained document style, but give the appendix its own title, source manifest, build file, and publication date. Do not rebuild or replace the foundation PDF.

1. A release table distinguishes foundation, ATIF, workflow variants, grader corrections, native evidence recording, and local Docker execution. Each row records source revision, world/protocol version, collection revision, dirty scope, and evidence commit. A source commit and a later artifact commit are different facts.
2. A worked consistency example follows one action from observed tool schema through exact request bytes, bounded response, trusted transition, replay, and export eligibility. Native response evidence is not a chronological training transcript. The JSON-null review correction explains why decoding success cannot be inferred from a nullable value.
3. A workflow coverage table shows CRM/refund fixture cases and trusted-state corruption defenses. Explain the corrected approval and incident invariants, including legitimate partial progress and retries. Do not turn scripted reference successes into a model score.
4. A local execution section draws the agent/collector/controller boundary and explains artifact freezing, detached bytes, grading after destruction, and cleanup. Present the repeated Docker lifecycle measurements with their small unique workload and resource limits.
5. A QA and limitations section separates browser checks, native schema validation, replay coherence, model execution, and security probes. Finish with the unimplemented trainer path, proposed matched study, and proposed partial-observation world, clearly labeled as future work.

## Existing evidence inventory

These artifacts were inspected for this plan. Published foundation and committed ATIF evidence are historical release records. The recently collected workflow and Docker files below record committed source, but root must confirm their artifact-release commit before the appendix calls those receipts committed delivery.

| Evidence | Source and scope | What the appendix may say | What it must not imply |
|---|---|---|---|
| [Foundation report](world-engine-report.md), [UI receipt](../../artifacts/qa/ui-report.json) | Foundation PR #1, head `1675734`; receipt records its own earlier source | Foundation had 82 backend tests, nine full replayable evaluation episodes, and 35 connected browser checks at release | Current world revisions replay old records; counts include later work |
| [ATIF validation receipt](../../artifacts/atif/validation-receipt.json) | Exporter revision `993895462766e232b4f920a03fb5a2860756fe47`, clean exporter scope; Harbor `09f5b964f8e5075f7e52fd08c9994dfc80ad5d24` | Nine existing evaluation trajectories passed pinned upstream schema validation; no new provider call; training disabled | A Harbor trial ran, interchange equals a trainer batch, or schema validation proves policy quality |
| [ATIF browser receipt](../../artifacts/atif/qa/ui-report.json), [download validation](../../artifacts/atif/qa/upstream-validation.json) | UI controller `9938954`; API episode reports `d8fcd414d69c857b7516d28bbcdec0430f6583c2`, clean implementation scope | Thirteen recorded connected checks, two evaluation-only failed episodes exported and validated; passed-only export empty; no browser error | UI and API used one identical Git revision; two failed scripted episodes are model evaluations; 35 plus 13 checks are independent coverage |
| [Original variant receipt](../../artifacts/workflow-variants/final/report.json), [integrity sidecar](../../artifacts/workflow-variants/final/INTEGRITY-NOTE.md) | Original CRM/refund `1.1.0` source `6cc84237384f04b5a205b04a127ce99ba9ff00d9` | Historical executions are retained with the subsequently discovered approval-grader limit | Every corruption defense worked at that source, or old grades were silently corrected |
| [Hardened variant receipt](../../artifacts/workflow-variants/hardened/report.json), [summary](../../artifacts/workflow-variants/hardened/report.md) | Collection source `4bc73fe6fd92df242900f08b6844fab4f3ff83be`; CRM `1.1.0`, refund `1.1.1`; clean implementation scope | 64 unique world/seed tasks, 128 matched scripted attempts; 64 reference passes, 64 baseline failures; all attempts replayed at collection source; zero inference | 128 independent tasks, learned-model improvement, seed holdout establishes unseen rule/family transfer |
| [Incident integrity correction](../incident-integrity.md) | Corrected source `b5e349b`, incident `1.0.1`, included in `4bc73fe6` | Four reproduced direct state corruptions motivated initial-identity, immutable-field, exact audit/phase checks; 43 new integrity tests described | An ordinary model tool exploit or hostile-host authenticity was demonstrated; blocked-window/failing-preflight tasks were added |
| [Docker lifecycle receipt](../../artifacts/docker-executor/final/lifecycle.json), [SDK boundaries](../docker-executor.md) | Executor collection `4bc73fe6`; exact approved image ID and source-file hashes recorded; relevant scope clean, checkout dirty | 24 successful fresh-session executions across concurrency 1/2 and three trials; four unique number-sum inputs repeated; no model call; each trial records empty owned-resource cleanup | 24 independent tasks, real-model throughput, cloud scaling, application fidelity, or protection from the Docker owner/kernel escapes |

The existing public Terminal-Bench receipt remains a separate evaluation-only task. Reuse its original source/license/canary and explicit adaptations if cited. It is not evidence that the new generic Docker SDK ran that benchmark.

## Gates for pending sections

Native six-case local-model results are now frozen in `artifacts/native-provider/final` at source `7de25124fd752acf61571ec0860309c139652fff`: 48 transport attempts, four business passes, two clean successes, six replays and six pinned Harbor validations. Root and console independently checked the finalized evidence; console also verified exclusion from all three training formats. The selected artifact commit remains pending root confirmation. The appendix must retain every finalized success and failure, report attempted versus planned cases, verify request/action linkage and replay under the collected source, and show missing usage as unknown. Do not compare these cases against old JSON-mode receipts as a matched protocol study.

The proposed larger matched study has 32 tasks and one attempt per adapter, not repeated reliability trials. It has no result yet. The proposed access world has four grant/recovery cases and four denials, mandatory independent staff/email lookup, manager discovery, and a 19-decision reference-path budget. It has no runtime or task-quality evidence yet. The installed-library audit blocks exact trainer preprocessing; vocabulary/template metadata alone is not an encoder or trainer.

## Current guide updates

Research owns these documentation changes; root supplies release/commit confirmation and reviews claims. Do not ask another worker to rewrite the same guides concurrently. Make the release-specific updates after native collection and selected artifact commits freeze, without changing the historical report or receipts.

| Guide | Planned change and verification |
|---|---|
| `README.md` | Link the separate follow-up appendix, current variant/incident docs, ATIF, native SDK and Docker SDK. State precise current world versions and receipt sample counts. Keep registered `local` JSON actions distinct from SDK-only native tools; do not present the Docker executor as an HTTP workflow provider. Retain foundation-source replay instructions and the failed eight-command public attempt. Check every link and startup command against the committed release. |
| `docs/OPERATIONS.md` | Add exact SDK/import and recorded-source replay guidance for follow-up capabilities, native preparation/closure and training exclusion, ATIF operator interchange, and Docker image allowlisting/admission/artifact/cleanup limits. Explain which verification commands are mock-only, Docker-only, or inference-bearing; inference commands require separate authorization and caps. Keep older database/export fingerprints pinned rather than proposing silent migration. Cite independent source and receipt revisions. |
| `docs/ROADMAP.md` | Correct the stale public-task outcome now: final native attempt executed eight commands and failed CSV output; truncated JSON was an earlier protocol failure. Classify ATIF interchange and constrained local Docker execution as delivered scoped capabilities, not native Harbor jobs or cloud execution. Keep real application validation, tenancy, trainer prerequisites/checkpoints, and larger matched evaluation gated. New access-world implementation and model evidence require their own acceptance receipts. |
| `coordination/BUILD.md` | Record actual source/receipt commits and test scopes as root confirms them. Mark source-complete, collected, reviewed, committed, and proposed work distinctly; do not add follow-up tests to the 82-test foundation count. |

The roadmap's public-task correction and trainer-blocker link are factual guide fixes, not new experiment results. Minimal README and operations receipt claims now reflect frozen native results; formal appendix publication still waits for artifact commit confirmation.

## QA plan before publication

Verify every evidence link exists and every cited artifact hash matches its receipt. Read JSONL rows and compare counts, flags, world versions, unique task keys, source fingerprints, and outcomes against the summary; do not rely on narrative totals alone. Pin replay to the recorded source rather than updating old grades. Record the exact command and result for any new verification, and make no model calls during document QA.

Check ATIF fields against the recorded pinned Harbor schema, not an unpinned current library. Preserve the UI-controller/API-source distinction. Browser screenshots and videos are demonstrations of the recorded phase; they do not prove later runtime changes remain connected. A new connected browser pass is a separate gate when the new world becomes available.

Inspect a small number of representative screenshots: desktop ATIF inspector and provenance, mobile controls/inspector, and foundation run/grade pages as historical context. Verify labels, no incoherent overlap, mobile overflow, and displayed provenance. Keep the recorded sampled contrast measurement qualified; it is not a full accessibility audit. Decode the retained phase video and verify a real render, without counting video frames as tests.

Compile the appendix separately and visually inspect every page, especially evidence tables, revision strings, links, figure labels, and long paths. Fix layout without truncating caveats. Exported text must preserve the source table, measured denominators, limits, and proposed/delivered distinctions. Root reviews the actual PDF and evidence manifest before publication.

## Stopping condition

The appendix is complete when the selected receipts have confirmed artifact commits, all claims resolve to inspected evidence, the separate PDF passes visual QA, and the release table accurately labels pending work. Missing native/access/model-study evidence stays pending. Do not add experiments or filler merely to complete a section or consume the overnight window.
