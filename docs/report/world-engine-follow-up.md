# World Engine: follow-up evidence and boundaries

October 10, 2026. Separate appendix to the foundation report.

## 1. What changed, and what the evidence establishes

The platform adds CRM/refund boundary fixtures, stronger grading, pinned Harbor ATIF interchange, bounded native Ollama evidence, and local Docker execution. Later phases add recorded JSON, partial-observation access provisioning and the finalized collections in section 7. These improve testable coverage and execution boundaries, not production application parity, model improvement, trainer readiness, or cloud/multi-tenant operation.

The first follow-up cohort's receipts and guides were committed at **`0cf41c7`**, in dependent [PR #7](https://github.com/nthpaul/world-engine/pull/7). The table below describes that historical cohort; section 7 separately records newer evidence. Collection source and publication commit differ. The [foundation report](world-engine-report.md), PDF and earlier grades remain unchanged; historical replay requires pinned source, not today's generators.

| Evidence | Recorded source | Scope and result |
|---|---|---|
| Foundation | Release `1675734` | 82 tests; nine evaluation episodes; 35 browser checks. |
| ATIF interchange | Exporter `9938954`; Harbor `09f5b964` | Nine historical trajectories schema-valid; no new provider calls. |
| Hardened workflows | `4bc73fe6`; CRM 1.1.0, refund 1.1.1 | 64 tasks, 128 scripted attempts: reference 64 passes, baseline zero; replayed. |
| Native local model | `7de25124`; incident 1.0.1 | Six episodes, 48 transport requests: four passes, two clean; replay/schema checked. |
| Docker lifecycle | `4bc73fe6` | Four repeated inputs, six trials: 24 passes, no model calls; cleanup empty. |

At evidence commit `0cf41c7`, root verified 384 passing tests, five optional skips, Ruff and a clean diff, independently checked replay/schema/cleanup evidence, and confirmed receipt hashes. Those counts and outcomes describe that historical release, not the later grader or access source. Do not add later tests to the foundation's 82-test count.

**Interpretation rule.** A test establishes behavior under its tested conditions. Replay establishes seeded transition and grading consistency. Schema validation establishes interchange structure. A model attempt establishes one observed execution under its budget. None is a substitute for the others.

Source anchors: [hardened workflow receipt](https://github.com/nthpaul/world-engine/blob/0cf41c7efcb5a1af345bae1c31ebfe6e096b7efa/artifacts/workflow-variants/hardened/report.json), [native independent validation](https://github.com/nthpaul/world-engine/blob/0cf41c7efcb5a1af345bae1c31ebfe6e096b7efa/artifacts/native-provider/final/independent-validation.json), and [Docker lifecycle receipt](https://github.com/nthpaul/world-engine/blob/0cf41c7efcb5a1af345bae1c31ebfe6e096b7efa/artifacts/docker-executor/final/lifecycle.json).

\newpage

## 2. Workflow coverage and authoritative grading

The historical receipt covers four CRM cases: ordinary ownership, equal customer timestamps, noncanonical invoice survivors, and invoice-ID tie-breaks. Eight refund cases cover the inclusive 30-day window, 5,000/5,001-cent review boundary, exact funds/one-cent shortfall, chargeback and unverified damage. Distractors and unrelated histories remain.

Seeds 0--31 per world, two scripted policies, 20 decisions/30 seconds and concurrency one produced 128 evaluation-only attempts over 64 tasks: reference 64 passes, baseline zero. These test implementation, not learning. Seed holdout does not withhold a rule family. [Variant protocol](../workflow-variants.md).

### A tool boundary and a grader answer different questions

A normal tool can deny an agent-written approval while an incomplete grader accepts a forged record inserted directly by a trusted test. Refund 1.1.1 corrected one such gap: an ineligible denied request could retain full credit after an extra approval was appended. The original receipt and its [integrity sidecar](../../artifacts/workflow-variants/final/INTEGRITY-NOTE.md) remain unchanged.

Incident 1.0.1 anchors incident/service/change identities, immutable target fields, review/check status and audit sequence. Its predecessor accepted an extra executed change or altered incident ID, rollback version or audit incident ID. The correction permits both check orders and legitimate prefixes/retries, not new blocked-maintenance or failed-check scenarios. [Incident contract](../incident-integrity.md).

A later review reproduced six more corruption cases against the frozen workflow/native source: unauthorized CRM/refund roles, CRM marker-only or wrong-canonical audit, missing refund audit, and missing payment ID/key. Each retained full credit. No ordinary tool exploit was demonstrated; replay would reject forged transitions. The trusted grader nevertheless lacked a complete state/history contract.

CRM **1.1.1** and refund **1.1.2** independently fold initial-derived audit certificates, without `apply`, replay or a reference policy, then compare whole state including outsiders/metadata. Missing/extra/duplicate/misordered certificates fail safety; booleans differ from numbers. A separate repair accepts legal transfer-before-void ownership. Root verified 266 focused tests, including 97 integrity cases and optimized-Python proof; an AST guard rejects production `assert`. [Corrected contract](../workflow-grader-integrity.md). Section 6 preserves the matched study; section 7 adds wider protocol-v3 scripted coverage. Old results remain unchanged.

The three legacy worlds retain shaped grading for a safe state:

$$r_{\mathrm{grade}}=\frac{1}{m}\sum_{j=1}^{m}\mathbf{1}[c_j].$$

Unsafe, timed-out or unfinished execution receives zero **episode reward**. Diagnostic `Grade` can retain partial credit after timeout. Passing requires all checks and normal completion. Preservation/finish checks are not calibrated goal progress. Access uses binary safe-settlement-plus-finish reward. The matched study measures business `passed`, not mean shaped reward.

**Worked interpretation.** Historical native CRM seed 42 earned 0.2: safety passed, but ownership, tickets, invoices and merge audit did not. `passed=false`. Denial preserved safety without completing the task. Calibrate or replace shaping before training.

\newpage

## 3. Native evidence: four task passes are two clean successes

The frozen native experiment used the already-installed Qwen3 8B model, catalog digest `500a1f06...b2b8b41`, source `7de25124`, and protocol `ollama-tools-v1`. It fixed seeds 42 and 730 in each of three worlds, concurrency one, 20 decisions and 120 seconds per episode, and a 15-minute aggregate cap. Settings were temperature zero, thinking disabled, 512 output tokens, and an 8,192-token context setting. No retries, prompt repair, JSON fallback, model download, or paid call occurred. A catalog digest does not attest server execution or frozen weights. [Exact protocol](../native-provider.md).

| World / seed | Decisions | Invalid actions | Business pass | Clean success |
|---|---:|---:|---|---|
| CRM / 42 | 7 | 5 | No | No |
| CRM / 730 | 9 | 7 | No | No |
| Refund / 42 | 5 | 0 | Yes | Yes |
| Refund / 730 | 5 | 0 | Yes | Yes |
| Incident / 42 | 13 | 5 | Yes | No |
| Incident / 730 | 9 | 1 | Yes | No |

All 48 recorded transport attempts supplied accepted native actions; environment permission errors accounted for 18 invalid actions. Every episode stopped with `finish`. Reported token counts were complete across attempts: 71,531 input and 1,258 output tokens. Collection took 88.289 seconds. This is six targeted cases, not a population estimate or a matched native-versus-JSON comparison. [Frozen report](../../artifacts/native-provider/final/report.md).

**Worked trace.** Incident seed 42 acknowledged the incident, proposed rollback, and ran compatibility. It then requested approval five times before running health; each premature request was denied. After health passed, the service issued approval, executed the exact change, and resolved the incident. Final business state was correct, but the execution was not clean. Clean selection requires a passing completed episode with zero invalid actions. Both refund traces qualified; incident traces did not.

### From request bytes to an export decision

Each decision sends one frozen system message plus current observation and normalized action/result history, with observed native tool definitions. The recorder retains the exact UTF-8 request body sent and raw HTTP entity-body response bytes, not HTTP framing or hidden server-rendered tokens. Limits are 128 KiB request, 64 KiB response and 8 MiB serialized episode events. Before transport, it reserves a start event and maximum bounded finish event. Oversized responses declare an observed-prefix hash; compressed bodies are recorded but not parsed as actions. Timeout/cancellation still pairs a finalized outcome. This is not a crash-durable journal.

Replay checks hashes, pairing, frozen source/contract, exact request reconstruction, parsed action linkage, transitions and authoritative outcome. A review corrected JSON `null` handling: a decoded null is a successful decode with invalid protocol content, not absence of a decode. Replay cannot authenticate the host, failed network cause, model execution, or reported timing.

Native SFT, DPO and grouped exports are disabled even on successful training-split episodes, including alternative pools. Console verification exercised 18 exclusions across six episodes and three formats. Readable actions and token counts cannot reconstruct sampled IDs, loss masks, behavior log-probabilities or a frozen checkpoint.

\newpage

## 4. Interchange and isolated local execution

ATIF-v1.8 export was checked against actual Harbor `Trajectory` at revision `09f5b964`, schema hash `892a423e...ff1c4da6c`. Nine historical episodes and the six new native documents passed the pinned schema. This is operator interchange, not a Harbor trial or trainer batch. Actions and observations are normalized; tool correlation IDs are export-derived. Native request/response records stay separately in `extra`, rather than becoming invented chronological assistant/tool turns. All exported ATIF records declare training ineligibility. [ATIF contract](../atif.md).

The separate ATIF browser receipt records 13 connected checks, two evaluation-only failed scripted episodes, an empty passed-only download, no browser errors or document overflow, and sampled label contrast at least 4.756:1. Both downloaded documents passed the actual pinned schema. UI controller source was `9938954`; API episode provenance recorded `d8fcd414` with clean implementation scope. Do not collapse those into one revision or treat 35 foundation plus 13 follow-up checks as independent coverage. [Browser receipt](../../artifacts/atif/qa/ui-report.json).

### The Docker trust boundary

The SDK uses an exact approved already-installed image and a local Docker endpoint. It never pulls/builds images and admits at most two sessions. Each fresh nonroot agent has no network, read-only root filesystem, dropped capabilities, bounded CPU/memory/PIDs, file/core limits and disabled log storage. There are no host bind mounts or grader/model secrets. The workspace is a fresh 32 MiB Docker-managed tmpfs volume. [Executor policy](../docker-executor.md).

The sequence is deliberately ordered:

**Agent writes -> agent paused and inspected -> separate read-only collector -> bounded archive validation -> containers and volume destroyed -> detached bytes graded by controller.**

The controller validates the entire archive before selecting outputs. It rejects traversal, links, devices, sparse/unsupported entries, duplicate paths, truncated archives and excessive unselected files. Default bounds include 256 KiB aggregate regular-file bytes, 16 files, 64 physical headers and depth eight. Expected answers remain outside the agent/collector; no agent-supplied reward is accepted. Containers still share the Docker Linux kernel. The daemon, image, controller and privileged host remain trusted; this is not VM isolation or protection against kernel escapes.

| Concurrency | Trials x inputs | Passes | Observed executions/second |
|---:|---:|---:|---:|
| 1 | 3 x 4 | 12/12 | 1.398--1.420 |
| 2 | 3 x 4 | 12/12 | 2.484--2.591 |

The [lifecycle receipt](../../artifacts/docker-executor/final/lifecycle.json) includes setup, Docker CLI, initialization, freeze, collection, parsing, destruction and cleanup. It records empty owned containers/volumes after each trial and grading after destruction. Twenty-four executions repeat four unique inputs; they are not 24 independent tasks. Background load was uncontrolled. These timings measure local lifecycle I/O, not model inference, cloud throughput or a competitor comparison. Controller crashes can leave resources; bounded cleanup can outlast the nominal episode deadline, and failed cleanup returns no artifact bundle.

\newpage

## 5. Reproducible interpretation and remaining gates

Evidence commit: `0cf41c7efcb5a1af345bae1c31ebfe6e096b7efa`.\
Native source: `7de25124fd752acf61571ec0860309c139652fff`.\
Workflow/Docker source: `4bc73fe6fd92df242900f08b6844fab4f3ff83be`.

Relevant collection scopes were clean; unrelated changes were recorded separately. Full hashes live in receipts; they establish byte consistency, not signed authenticity or recursive dependency attestation.

Replay the selected traces under their recorded source, without inference. For example, in an unused detached checkout of the evidence commit:

```sh
uv run python -m world_engine replay --file \
  artifacts/native-provider/final/evaluation-episodes.jsonl
```

The evidence commit contains the native collection implementation. Replay other wrappers according to their documented schema. Never replace old grades after a repair. [Operations](../OPERATIONS.md) describes pinned foundation replay; [variant documentation](../workflow-variants.md) describes newer operator records.

### Three short interpretation exercises

**Question:** Why not report only four successes? **Answer:** That hides the distinction between completing correct state and doing so without invalid actions. Report four business passes, two clean successes, all six outcomes and their failures. Curation can select clean traces, but must preserve selection and rejected-sample provenance.

**Question:** Does matching the Harbor schema prove native training readiness? **Answer:** No. It verifies document structure. The normalized interchange deliberately lacks exact sampled tokens, action loss boundaries and old-policy probabilities. Native training exports remain disabled; grouped JSON explicitly remains nontrainable.

**Question:** Do the concurrency-two Docker results prove a scalable rollout service? **Answer:** No. They demonstrate overlapping local lifecycle I/O on four repeated toy inputs under fixed bounds. They do not measure a model scheduler, large task distribution, recovery after host failure, tenancy, cloud cost or real application behavior.

Python audits found no installed torch, transformers, TRL or tokenizers. Public Ollama metadata exposes vocabulary/merges, template and special IDs, but no verified encoder/template executor or trainer/checkpoint path exists. [Feasibility audit](../trainer-preprocessing-feasibility.md). Do not infer log-probabilities from text or claim training. SFT needs verified formatting/masks; PPO/GRPO also need fresh policy sampling provenance. Application differential validation, expert grading, distributed execution, tenancy and data-rights/deletion processes remain separate gates.

Public licenses/canaries and evaluation-only exclusions remain in force. The adapted Terminal-Bench native attempt executed eight commands and failed CSV output; its separate runner did not evaluate this Docker SDK. [Public protocol](../public-benchmark.md).

The October 8 [Proximal infrastructure article](https://www.proximal.so/blog/posttraining-infra/) reinforces the missing training boundary: sampled IDs/log-probabilities, fixed rollout adapter versions and staleness gates. Its internal performance gains are not ours. The linked [MISA-T paper](https://arxiv.org/abs/2608.11152v1) addresses mixed-workload KV admission, not this SDK semaphore. [Follow-up source checks](../research/FOLLOWUP-SOURCES.md) separate these design implications from reproduced measurements and public-task rights.

\newpage

## 6. Current source and a matched adapter comparison

Later source adds recorded JSON (`d9a452c1`), independent certificates (`1cb46225`), access (`2e3c08dd`), cooperative closure (`40c62993`) and fresh-output preservation (`9a3b414a`). These are separate from historical receipts. Root verified 777 full tests and green CI at study source `622c5b18`; later tests do not change earlier release counts.

Access uses paged queue/identity/manager/policy discovery rather than exposing its private catalog. Four grant/recovery and four denial cases use service-owned scoped, expiring reviews and binary outcome reward. Its longest reference path is nineteen decisions. Private expired-review history tests service renewal, not observed agent recovery. Access was not a task in this matched study; its later controls and separate model receipt are in section 7.

The [matched study](../workflow-model-study-results.md) completed at source `622c5b18`, protocol `6abb1350...f391bc`: 32 fixed tasks, 64 model and 64 scripted attempts, all 128 finalized. Each adapter received one attempt per task, twenty decisions/35 seconds, concurrency one, temperature zero and no retries/tuning. Collection took 1600.268 seconds under a 45-minute/64-MiB cap, on Apple M4 Max/64 GiB with reported Ollama 0.22.0. Scoped source was clean; overall dirtiness was retained.

| World | Native business pass | JSON business pass | Native / JSON clean |
|---|---:|---:|---:|
| CRM | 0/8 | 0/8 | 0 / 0 |
| Refund | 16/16 | 7/16 | 6 / 0 |
| Incident | 8/8 | 0/8 | 0 / 0 |
| Total | 24/32 | 7/32 | 6 / 0 |

Reference controls passed 32/32; baseline passed zero. Native micro-rate was 75.0%, JSON 21.875%; descriptive 95% Wilson intervals were 57.9--86.7% and 11.0--38.8%. Equal-world macro-rates were 66.67% and 14.58%. Refunds comprise half the micro-sample; neither weighting represents a measured production mix.

Pairs were seven both-pass, seventeen native-only, zero JSON-only and eight neither. The observed micro-difference was 53.125 points. Predeclared whole-pair, world-stratified bootstrap, 2000 resamples, gave a descriptive 40.625--65.625-point interval. Fixed fixtures/new seeds are not new-rule generalization. Different prompts/schemas/parsers mean a comparison of complete adapter contracts, not an isolated formatting effect or trained improvement.

Five native CRM attempts failed the one-call protocol after inspection; no multi-call prefix ran. JSON had 23 timeouts and two step-limit terminations, not blanket malformed-JSON failure. Native retained 85 denied actions; JSON retained 280. There were 775 transport attempts. Known reported usage was 979,980 input/18,638 output tokens, **incomplete sums**, not complete cost accounting.

Root independently verified 128 replays, 128 actual pinned Harbor schema validations, exact source/row/grade correspondence and 384 training exclusions. Original raw/report bytes were 17,729,163; later validation-sidecar bytes are separate. Evidence was published at **`c5d7caba`**, in [PR #21](https://github.com/nthpaul/world-engine/pull/21). Root ran the documented detached-checkout CLI replay and verified all 128 episodes without inference. Replay the original source; do not relabel outcomes after later fixes.

\newpage

## 7. Finalized four-world evidence, not a training result

The following independent collections used frozen source `ee26d7b9`; access UI v2 used controller/runtime `e1550290`. They do not revise the historical matched study or six-case model outcomes. No new model calls were made during receipt audits or report preparation.

| Collection | Actual denominator | Recorded result |
|---|---|---|
| Access controls | 32 tasks, 64 scripted episodes | Reference 32 passes; baseline zero. |
| Workflow protocol v3 | 64 tasks, 128 scripted episodes | Reference 64 passes; baseline zero. |
| Four-world CPU matrix | 120 unique tasks, 2,160 executions | Reference 1,080 passes; baseline 1,080 failures. |
| Native access | Eight tasks, one attempt each | Zero business/clean passes; all timed out. |
| Access UI v2 | Sixteen scripted episodes | 31 checks, ten downloads; failed v1 retained. |

Controls and variants have full independent replay, actual pinned Harbor validation and exclusion from SFT, DPO and grouped training exports. Research also reconciled all 128 variant raw/report identities and 24 case/policy aggregate cells, including steps, invalid actions and splits. The v3 journal has 415 decisions and 64 invalid baseline actions; 104 train, fourteen validation and ten test rows remain evaluation-only. Seed labels do not override that exclusion. [Control validation](../../artifacts/access-provisioning/20261010-controls-v1/independent-validation.json), [variant validation](../../artifacts/workflow-variants/20261010-v3/independent-validation.json).

### What the native access failures show

The eight installed-Qwen attempts used the fixed native protocol, concurrency one, twenty decisions and a 35-second deadline. There were **97 requests, 89 completed decisions and eight cancelled in-flight requests**. All completed responses became validly shaped environment decisions; 32 were rejected for unmet discovery/review prerequisites. This is semantic workflow failure, not malformed native JSON.

Every queue/group listing stayed on the first page, using `start_index=1, count=1`. Only two attempts read the assigned request. None called policy lookup, grant, closure or finish; assigned requests stayed pending. Seed 5 had zero invalid actions but navigated another request, so it was neither a business pass nor a clean success. Safe partial state is not settlement.

The longest reference path needs nineteen decisions, while these deadlines allowed ten to twelve completed decisions. The traces show repeated rejected actions as well as a time bound; they do not establish that doubling the deadline would complete the task. The separately described longer-deadline study is **proposal only**, not executed, implemented or authorized here.

Known reported usage was **228,895 input and 2,847 output tokens**; eight cancelled requests lacked usage. These sums are not complete totals, dollar cost or upper bounds. A cancelled client call does not prove immediate daemon cessation. All eight episodes replayed, converted to actual Harbor, and were excluded from each training format. [Diagnosis and independent validation](../access-native-results.md).

### Read a CPU rate with its denominator

The matrix uses four worlds, two scripted policies, concurrency 1/4/8 and three trials of thirty episodes per cell: 72 batches and 24 aggregates. Each of the 120 world/seed tasks repeats nine times. Per-cell Wilson intervals count thirty distinct first-observed scenarios, not ninety independent trials. Repeated outcomes had no conflicts.

All persisted SQLite envelopes correlate one-to-one with the compressed raw journal. Independent audits recomputed per-trial counts, outcomes, invalid actions, errors, cancellations and rates; all medians, nearest-rank p50/p95 and Wilson intervals match. Rates use **recorded batch wall time**; episode duration and recovered database timestamps are not substitute clocks. Async scheduling is not CPU parallelism, and no inference was measured. Median cell rates ranged from 69.98 to 416.11 episodes/second under uncontrolled background load, not a competitor comparison.

The gzip journal is 5,833,426 bytes but expands to 154,691,204 bytes; local SQLite is additional storage. Compressed size does not describe memory, export or database footprint. [Benchmark and validation](../../artifacts/benchmarks/20261010-four-world-v1/independent-validation.json).

## 8. UI evidence, candidate-data gates and remaining work

### Keep failed collection attempts visible

Access UI v1 failed because JavaScript numeric reserialization changed operator JSON during replay extraction. Its original raw records and [failure receipt](../../artifacts/access-provisioning/20261010-ui-v1/failure.json) remain preserved. Corrected v2 preserves recorded numerals, not a rewritten earlier success.

At source `e1550290`, v2 passed 31 connected checks with sixteen evaluation-only episodes and 121 decisions: reference eight passes, baseline zero. Evidence includes thirteen desktop/360px/390px screenshots, ten downloads and a 5.48-second VP9 video. Sampled small-label contrast was at least 4.756:1; no browser errors or document overflow were recorded. Narrow provenance tables intentionally scroll internally. All screenshots and three video frames were independently inspected; the full video decoded without errors. Fixed-canvas gray letterboxing after viewport changes is recorder output, not a blank application.

All 25 recorded controller-source file hashes matched files at the recorded source revision. All sixteen episodes independently replay and validate against actual Harbor 0.24.0, canonical schema hash `892a423e...ff1c4da6c`. The real exporter reproduces all ten downloads byte-for-byte. SFT, DPO and grouped formats each exclude sixteen evaluation-only records; no alternative pool is queried. The raw operator journal is 2,380,262 bytes, containing full diagnostic evidence, not a training batch. [UI report and validation](../../artifacts/access-provisioning/20261010-ui-v2/independent-validation.json).

**Worked interpretation.** Thirty-one UI checks do not measure model competence. Zero native access passes do not invalidate a scripted UI acceptance check. Replay demonstrates transition consistency; schema validation demonstrates structure; byte-exact downloads demonstrate serialization consistency. None authenticates a hostile host or establishes production-directory parity.

### A measured scripted corpus is not a trained model

At source `5e5eb0d94b504e84a0d903811ad60ae5ca602c95`, the authorized [candidate collection](../../artifacts/candidate-corpus/20261010-v1/manifest.json) completed 128 verified episodes: 64 reference business/clean passes and 64 baseline business failures, 620 decisions and eight completed run rows. There were zero retries, inconclusive or unattempted slots. Legacy baseline shaped rewards can be positive despite business failure; clean success, business pass and reward are separate fields.

The 64 tasks split 51 train, six validation and seven test, producing 102/12/14 episodes. Train-only exports contain **397 exact SFT decisions, 51 strict comparable DPO pairs and 51 mixed-policy nontrainable groups**. Thirteen heldout reference cases are excluded per format. This is structural split protection, not unseen-rule generalization. DPO's trajectory-message completion still needs a verified tokenizer/masking adapter; the grouped interchange is not an on-policy training batch.

Root and console independently checked all 128 replays, actual Harbor 0.24.0 interchange, source scope, original accounting and byte-exact exports; console also reconstructed exports without calling the exporter. Full finalized evidence precedes replay/selection in the private quota-limited Store. SFT inputs preserve exact public controller contexts. Original artifacts total **19,021,481 bytes**; collection took 11.456073333043605 seconds. The later operator archive is 359,286 compressed / 9,344,170 expanded bytes, ordered by SQL run/episode keys rather than chronology; archive/sidecar bytes are separate. No model, tokenizer, training or cloud calls occurred. [Results](../scripted-candidate-results.md), [independent validation](../../artifacts/candidate-corpus/20261010-v1/independent-validation.json), [predeclared contract](../scripted-candidate-corpus.md).

**Worked interpretation.** Why only 51 DPO pairs from 128 episodes? The two policies supply one comparable pair per task, and thirteen heldout tasks are excluded. A successful export establishes its data contract, not learning: no checkpoint, optimizer run or heldout model comparison exists.

The earlier pure native-ledger builder has 76 reviewed tests. SDK integration at `d71a05d` now permits explicit `ollama-tools-ledger-v2` opt-in through the shared provider; default v1 request/contract/configuration rules remain unchanged. V2 replay regenerates exact requests from trusted reset observations and verified transitions, with protocol/module/eligibility guards. Root verified 1,196 tests, six optional skips, Ruff and frontend build at that source, not every later checkpoint. Both native formats stay training-ineligible.

Public-boundary source `451c1cf9` has 26 focused tests; remote authentication and tenant isolation remain incomplete. [Integration contract](../native-ledger.md), [boundary PR #28](https://github.com/nthpaul/world-engine/pull/28).

## 9. Native context comparison: zero settlement in both protocols

At source `cc2d4956c320867569e866bea3adbb53123a477f`, the locked eight-seed access study finalized sixteen verified attempts in **381.299 seconds**, without retries, inconclusive records or unattempted slots. Each pair compares default native v1 with native-ledger v2 under the same 20-decision/35-second budget and installed model. Both had **zero of eight business passes and zero clean successes**; all eight paired outcomes are neither, observed difference zero. [Results](../access-ledger-study-results.md), [original report](../../artifacts/access-ledger-study/20261010-v1/report.json), [locked protocol](../access-ledger-study.md).

| Recorded quantity | Native v1 | Native-ledger v2 |
| --- | --- | --- |
| Transport requests / accepted decisions | 97 / 89 | 125 / 125 |
| Cancelled requests / invalid actions | 8 / 33 | 0 / 101 |
| Termination | Eight 35-second timeouts | Three finishes, five max-step terminations |
| Business / clean passes | 0 / 0 | 0 / 0 |
| Known input / output tokens | 229,146 / 2,847, partial across 89/97 | 211,175 / 3,951, complete across 125/125 |
| Request-body bytes | 1,364,914 | 1,178,809 |

All eight v2 run statuses are completed, but none settles its assigned request. Root and engine independently checked sixteen replays, sixteen actual Harbor 0.24.0 schema validations, 48 real-exporter exclusions, 21 source hashes and **7,003,636 original raw/report bytes**. Combined known usage is partial: 440,321 input and 6,798 output tokens over 214 of 222 requests. Cancelled work lacks complete counters. The later [validation sidecar](../../artifacts/access-ledger-study/20261010-v1/independent-validation.json) is additional publication data, outside the original two-file accounting.

**Worked interpretation.** Does fewer v2 request bytes mean a faster successful agent? No. The trajectories and termination reasons differ, v2 makes more invalid decisions, and neither completes the business task. Completed-response counters exclude cancelled work; aggregate wire bytes do not isolate cache reuse, tokenization or scheduler effects. Eight fixed pairs also do not establish equality across a broader task population.

The recorded v2 seed-zero tool definition includes `start_index` minimum/default one, while its first three list calls use zero and are rejected. A bounded metadata-only inspection of the installed public model shows a template that serializes `.Function` from `.Tools`; it does not visibly discard those constraints. V2 removes duplicate schemas from the user content, not from the tools array. Schema salience is an untested hypothesis, not a proven template bug. UTF-8 bounds and append-stable application content do not attest tokenizer prefixes, untruncated daemon consumption or cache hits. [Primary/source distinction](../research/FOLLOWUP-SOURCES.md).

## 10. Current console proof and a measured CPU correction

The five-phase console collection at **`b4501029`** passed 129 checks with 56 screenshots, five videos and 26 byte-exact downloads. Standard/ATIF/access phases created 34 scripted episodes; two native inspection phases read unchanged imported v1/v2 attempts. All 36 records replayed and passed actual pinned Harbor validation. Final operator history contained eleven runs/68 episodes, including earlier history. Imported model evidence is not newly executed native API inference. [Independent reconciliation](../../artifacts/qa/20261010-current-final-validation-v1/independent-validation.json).

The 98 original files totaled 21,210,254 bytes; the later validation sidecar is additional publication data. Sixty episode-format training exclusions were checked. Standard exports instead contained 52 exact SFT decisions, eight DPO pairs and eight nontrainable groups; all selected pairs came from fresh reference/baseline records despite older candidates being available. Root inspected all screenshots, decoded every video and reviewed fifteen frames. Recorded source hashes matched the pinned source; the standard report's absent controller-source field was not invented, and fresh episode provenance supplied its source evidence. These measurements do not supersede or conceal failed historical UI v1.

### Remove a redundant observation, then prove the scope

A rollout correction uses one detached public observation for both exact controller-context serialization and the provider decision, rather than independently reading the environment twice. It introduces no shared observation cache. Provider mutation cannot change world state, cached tool definitions or stored context strings. The [post-change CPU receipt](../../artifacts/profiling/20261010-v2/independent-validation.json) at `b4501029` saves **192 complete scripted episodes and 1,456 decisions** over four worlds, with all business/clean passes. Root and console checked 192 replay/actual Harbor results and 576 training exclusions; all eight binary profiles and recorded statistics were independently recalculated.

Across the four profiled 24-episode trials, measured `observe` calls changed from 528/264/648/1,056 to 376/200/456/736 for CRM/refund/incident/access: **728 redundant reads removed**. Logical reference trajectories matched. This is a measured reduction in those profiled trials, not 1,456 instrumented removals, model-serving acceleration or a causal GPU result. Both 96 profiled and 96 unprofiled post-change envelopes are saved. The older `d71a05d` receipt saved only its 96 profiled episodes; its retrospective producer does not independently establish original stdin bytes or the unsaved unprofiled outcomes. Those gaps remain visible.

Post-change collection took 4.604684542 seconds under its 240-second/64-MiB bounds. Eighteen original files totaled 21,824,261 bytes; temporary SQLite was removed, and later validation bytes are separate. Optimization evidence compares pinned source and logical behavior rather than rewriting historical traces.

## 11. Real-model admission: overlap did not improve useful throughput

One authorized [SDK caller-wave study](../model-concurrency-study-results.md) collected at **`1d9f2315`** with unchanged native v1 and refund 1.1.2. Seeds 53000--53007 repeated in four ascending-seed batches with admission **1, 2, 2, 1**. The installed Qwen digest, temperature zero, disabled thinking/streaming, 512 output-token limit and 8,192 context setting were fixed. Every attempt had twenty decisions/35 seconds; aggregate bounds were 1,200 seconds, 640 chat requests and 64 MiB. No retries, fallback, downloads, paid calls or training occurred.

All 32 slots were returned, durably journaled and verified, with no inconclusive/unattempted records. Collection took **441.572926583 seconds**; all four cleanups completed within three seconds. Batch wall clocks run continuously from first admission through final-wave raw fsync and validation, including interwave checks. Preparation and cleanup are separate; overlapping episode durations are not summed as wall time.

| Batch / admission | Continuous wall seconds | Business passes | Clean successes | Verified passes/second |
|---|---:|---:|---:|---:|
| 0 / one | 100.858585 | 8/8 | 3/8 | 0.079319 |
| 1 / two | 103.460102 | 7/8 | 3/8 | 0.067659 |
| 2 / two | 115.902943 | 6/8 | 3/8 | 0.051767 |
| 3 / one | 119.353499 | 8/8 | 3/8 | 0.067028 |

Pooling each admission level descriptively gives **sixteen passes / 220.212083458 seconds = 0.072657230 passes/second** for one, versus **thirteen / 219.363044583 = 0.059262489** for two. Admission two did not improve observed useful throughput in this workload. There were twelve clean successes, 233 executed decisions and 32 invalid actions. Three two-admission attempts timed out; none is dropped from denominators. The two matched rounds have seven/six both-pass, one/two one-only, zero two-only and zero neither. Eight tasks repeated four times are the clusters, not 32 independent tasks or sixteen independent pairs.

The hook counted **236 chat requests and twelve metadata requests**; paired recorder events contain 233 accepted replies and three cancellations. Known usage is partial: 303,693 input/6,899 output tokens and 620,575,252,623 reported inference nanoseconds across 233/236 requests. One-admission usage is complete for 120 requests; two-admission usage is known for 113/116. Summed overlapping request durations are not batch wall time, and cancelled client requests do not attest daemon cessation.

Root and console independently verified all 32 replay/actual Harbor results, 96 native-protocol export exclusions, 22 pinned source hashes, row/pair/counter correspondence and original byte accounting. The original journal/report remain unchanged at **4,473,315 bytes**; the [validation sidecar](../../artifacts/model-concurrency-study/20261010-v1/independent-validation.json) is additional publication data. All eight two-episode waves overlap at the client; this does not attest GPU parallelism. The API was idle background, with light artifact/proof work and brief journal progress reads; no other model inference, CPU benchmark or browser collection ran alongside. Warm loading, cache state, daemon queue policy and rendered token input remain unmeasured.

**Worked interpretation.** Why not choose concurrency two because its episode rate can be higher? The primary outcome is verified task completion per wall second, not admitted work. Timeouts reduced useful output here. The observation motivates a conservative default, but does not prove one is optimal for other models, policies, budgets or task distributions.

### Collection source and publication evidence differ

The profile was published in green-CI [PR #46](https://github.com/nthpaul/world-engine/pull/46) at `5bcdedc550051a665c730869b06b1c86d1496d98`, the five-phase QA in [PR #47](https://github.com/nthpaul/world-engine/pull/47) at `f3b59adbeb1ee196d1486ec697ade0da3ebf9872`, and admission evidence in [PR #48](https://github.com/nthpaul/world-engine/pull/48) at `c722f2975b06d430c85b680dad4553dcec903ec8`. Their collection source remains `b4501029` or `1d9f2315`. Root rechecked original bytes before each publication. Later sidecars/results are additional data, not revised collection accounting.

### Entrypoint source is not another model evaluation

Native API/console/SDK configuration uses separately imported `NativeRunConfig`; default registered `local` remains JSON. At **`ef63eda9`**, CLI aliases `local-tools` and `local-tools-ledger` are also admitted with mandatory evaluation-only and no paid calls, published in green-CI [PR #45](https://github.com/nthpaul/world-engine/pull/45). Omitted native concurrency is one, explicit one through eight remains supported, and legacy default four is unchanged. The native classes/contracts, models.py and shared grader fingerprints remain unchanged. Root verified 1,547 tests/six optional skips, Ruff, frontend build, mock history and sixteen historical native compatibility checks at this source. Engine independently tested a read-only source archive with socket connections blocked: nine help/pure-plan/custom-SDK checks and 83 entrypoint tests passed. That archive covers tracked source, not these later guide edits or hostile-host security.

### Two actual API admissions, one task

The separately locked [API smoke protocol](../native-api-smoke-protocol.md) collected at **`8b82c7aa`** through the API, RunManager and native provider factory, ordered v1 then v2 on the **same refund seed54000**, with one episode each, twenty decisions/35 seconds and concurrency one. Both explicitly finished with clean business passes: v1 made five decisions in 8.936292375 seconds, v2 four in 4.022780750. This is two integration attempts on one distinct task, not independent capability samples or a causal adapter-speed comparison. Installed model/options, evaluation-only status and no-paid settings remained fixed. [Original report](../../artifacts/native-api-smoke/20261010-v1/report.json).

All nine native transport attempts received accepted replies, with zero cancellations or invalid actions; known reported usage is complete across those nine attempts at 11,533 input/289 output tokens. The collector recorded 59 API responses and two client metadata attempts; server-owned provider-preparation metadata calls are not observed by that counter. Total collection elapsed was 15.013487583 seconds. Original 62 files total 822,301 bytes. Root and engine independently checked both replays, actual Harbor validation, six native-protocol training exclusions, 22 pinned source hashes, exact raw-detail/wrapper correspondence and readonly database integrity. Final history reached thirteen runs/70 episodes with no active jobs, not seventy new executions. No retries, downloads, paid calls or training occurred; earlier failed studies remain unchanged.

The configuration-controls v1 receipt at the same source passed fifteen automated checks with twelve screenshots, but root's complete visual review found a clipped Start footer at 360px. Its fourteen original files/1,782,398 bytes are retained as **visual nonacceptance**, not rewritten final UI success. No rollout, import, download or inference occurred in that GET-only controls phase. This failure is distinct from the earlier numeric-serialization access UI failure.

### Corrected controls and read-only inspection

After source51 fixed the nonshrinking action footer and scrolling form body, fresh controls v2 passed fifteen checks with twelve screenshots and one video. All 24 recorded network requests were GETs (sixteen UI assets and eight API requests); there were zero POSTs, rollouts, imports, downloads or model calls. Source pre/post checks validated 31 recorded file hashes; full button-bound checks and root visual review confirmed the 360px footer is visible. Original fourteen files total **1,784,739 bytes**. [Corrected report](../../artifacts/native-controls-qa/20261010-v2/report.json), [preserved v1](../../artifacts/native-controls-qa/20261010-v1/report.json).

The two actual source50 API episodes were then inspected read-only at controller/API startup source51, not rerun or imported. Each phase passed 25 checks with eleven screenshots and one video. Together they preserve forty original files/**3,270,261 bytes**, ten byte-exact downloads, two replays/actual Harbor validations and six unsupported-native-protocol training exclusions. The downloads contain four operator/ATIF records totaling 336,303 bytes and six empty training files, not four new episodes. Each phase verified 28 controller-source hashes and exact source50 wrappers; readonly SQLite integrity/history stayed thirteen runs/70 episodes/no active jobs. The historical import-only wrapper incompatibility was identified offline; no preflight, output reservation or browser was attempted. It was not a failed model or browser collection. A separately reviewed exact-wrapper mode made the new inspection possible. [V1 inspection](../../artifacts/native-api-smoke/qa/20261010-v1/ui-report.json), [v2 inspection](../../artifacts/native-api-smoke/qa/20261010-v2/ui-report.json).

This final three-phase cohort is **65 checks, 34 screenshots and three videos**, across 54 original files/**5,055,000 bytes**, separate from the earlier 129-check/56-screenshot/five-video cohort. Root inspected all 34 screenshots, decoded all three videos without errors and viewed nine frames. VP9 video durations are 2.68/2.44/2.44 seconds with 1440x960 canvases; gray mobile letterboxing is intentional recorder output. The UI created no episodes, imports, model calls or POSTs. Source50 API execution plus its two source51 inspection phases have 102 original files/**4,092,562 bytes**; later validation/publication files are additional. Automated checks, human visual acceptance and business outcomes remain distinct evidence.

Controls evidence was published at **`4dea6946094a95f9b9844e5467a204548f79f66b`**, in [PR #52](https://github.com/nthpaul/world-engine/pull/52); API/readonly UI evidence at **`e2dcec73e2b93405533308c278c027236bda47de`**, in [PR #53](https://github.com/nthpaul/world-engine/pull/53). These publication commits do not replace source50 model collection or source51 controller/runtime pins. Root rehashed all 130 original files/**7,659,699 bytes** and checked 140 pinned source-hash entries before publication. Historical source50 controls require their recorded pre-fix frontend; current source51 frontend is not silently described as identical. [Controls results](../native-controls-qa-results.md), [API/inspection results](../native-api-smoke-results.md). All three CI gates passed for both evidence publications; source51 CI and all-optional verification also passed.

### Continue with evidence gates

The measured UI source **`6bdec4f0281e51d502c505bda502ae5fe0c3dd2a`** passed 1,657 tests/no skips and all CI gates. Model API collection remains source50 `8b82c7aa`, not that UI fix; corrected controls/readonly inspection passed independently without new inference.

A final synthetic audit reproduced remote URL disclosure through provider-construction errors. Source **`0f51b903cfcc73e55901d11d5828e08c692220aa`**, [PR #54](https://github.com/nthpaul/world-engine/pull/54), adds generic constructor-boundary errors while retaining valid HTTPS/base-path handling. Eighty-six regression cases use synthetic transports/inputs; no real remote or paid model was called. Root's full all-optional suite passed **1,743 tests/no skips in 46.93 seconds**, plus Ruff/build/schema/mock history and executable SDK examples; one upstream Starlette warning remains. Actual Harbor and approved-existing-image Docker probes used no new downloads, and owned Docker resources were empty. Root and engine independently replayed eighteen native records (sixteen context-study plus both API episodes); root additionally checked all eighteen against the actual pinned Harbor model. The original three journals stayed byte-exact. These checks do not create new model results. Native/grader/models modules are unchanged; HTTP/recorded-JSON provider fingerprints intentionally change, so older JSON receipts require pinned source. Neither their original bytes nor their outcomes are rewritten. Source54 passed all three CI gates. Root also replayed both original API receipts through the committed source54 CLI, verifying their five/four decisions without new inference. The operator-owned final source54 restart retained thirteen runs/70 episodes/no active jobs and paid calls disabled; it did not recollect the source50/51 evidence.

The published [advanced workbook](advanced-environment-labs.pdf), twelve pages with nine labs and 27 primary sources in [PR #29](https://github.com/nthpaul/world-engine/pull/29), develops fidelity measurement, adversarial grading, family holdouts, exact DPO/PPO/GRPO contracts, KV/admission scheduling, cost accounting and deployment threat models. Its worked arithmetic is explicitly hypothetical, not a product speed/cost result.

Production transfer still requires differential application tests and expert calibration. Training still requires an executable exact tokenizer/template, sampled IDs, masks, behavior likelihoods where needed, a pinned trainer, an actual checkpoint and an equal-budget heldout evaluation. Distributed execution and tenancy still require their own isolation, admission, recovery, rights and cost proof. More traces, hashes, screenshots or passing scripted controls do not silently complete those gates.
