# Operate World Engine locally

This guide describes the delivered Python SDK and local operator API. The [engineering guide](engineering-guide.md) explains the design. The [roadmap](ROADMAP.md) lists work required for training, application parity, cloud execution, and multi-tenant deployment.

## Start the API and console

From the repository root, install the Python package and developer tools:

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

The console opens at `http://127.0.0.1:5173`. Its development proxy sends `/api` requests to `http://127.0.0.1:8000`. The API accepts loopback hosts and specific local browser origins. It rejects cross-site browser requests. These checks support local use; they do not replace authentication and tenant authorization.

The API's `serve --host` accepts only `127.0.0.1`, `localhost`, or `::1`. If port 8000 is occupied, choose another `serve --port` and update the console proxy to the same port. The Vite dev server uses strict port 5173 and exits if that port is occupied.

## Use the SDK

Create a world and submit a schema-validated action:

```python
from world_engine import Action, make_environment

env = make_environment("refund-ops", seed=42)
observation = env.observe()
transition = env.step(Action(tool="inspect"))
assert transition["result"]["ok"]
assert transition["observation"]["environment_id"] == "refund-ops"

env.step(Action(tool="finish"))
grade = env.evaluate()
print(grade.model_dump())
```

`make_environment` creates a new instance and resets it. `reset(seed)` rebuilds the episode state. `observe()` returns a copy of the permitted observation, task, role, tools and completion flag. CRM/refund/incident observations expose operational rows; [access provisioning](access-provisioning.md) exposes only its assigned queue entry and bounded current tool result, not the private directory/catalog. Tool metadata includes its argument schema. `step()` returns an observation, a result, `done`, and a state fingerprint. Invalid actions return `ok: false` and do not apply their state mutation.

`snapshot()` returns a trusted operator copy including seed, logical tick, completion flag and full state. Never substitute it for a model's permitted observation. `evaluate()` checks trusted state. A safety violation forces reward to zero. CRM/refund/incident can award diagnostic partial credit for safe incomplete work; access uses binary outcome reward, one only for safe settled work plus explicit finish. `Grade.passed` requires every check. Finishing an incomplete task does not create a pass. Legacy shaping is not a validated training objective.

Each environment owns its Python state. There is no process or VM sandbox around these objects. Run only trusted Python extensions in this process. The instance has no external resource that needs a `close()` call; a future provider that owns resources needs explicit lifecycle cleanup.

## Run a batch

The CLI can run an isolated batch without the web server. Use a separate database when the server is active:

```sh
uv run python -m world_engine --db .world-engine/cli.sqlite3 rollout \
  --environment refund-ops --provider scripted-oracle \
  --episodes 10 --seed 42 --concurrency 4
```

The command prints a persisted run summary, including its UUID. Repeat the same environment and seeds with `--provider scripted-baseline` to collect incomplete alternatives. `--max-steps` limits decisions. `--timeout` limits each episode's wall time. Episodes support 1 to 100, per-run concurrency supports 1 to 8, and the process admits at most 32 active runs with 8 active episodes globally.

`--environment access-provisioning` uses the same lifecycle and providers. Its reference reads the queue, corroborates exact staff number and email, discovers the employee's linked manager, reads candidate policies, requests required service reviews and settles the request. Its longest predefined case needs nineteen decisions including `finish`; the usual twenty-step budget is not a guarantee that invalid actions and renewals will fit. Case 5 has private old review history and tests service-side renewal, not an observed agent recovery episode. The separate [access control collector](access-provisioning.md#run-controls) requires reviewed committed source and a fresh output. Finalized controls at `ee26d7b9` passed 32/32 reference and 0/32 baseline episodes; [validation](../artifacts/access-provisioning/20261010-controls-v1/independent-validation.json) checks all 64 replays, actual Harbor interchange and training exclusions. These controls do not predict model completion within a different wall-time budget.

Concurrency is cooperative `asyncio` scheduling. The workflow simulations do not use multiprocessing or GPU inference. Deterministic local policies mainly exercise state transitions, hashing, and persistence. External or local model latency changes the throughput regime.

Use the existing local model without paid calls:

```sh
uv run python -m world_engine --db .world-engine/local-model.sqlite3 rollout \
  --environment refund-ops --provider local --model qwen3:8b \
  --episodes 1 --concurrency 1 --max-steps 12 --timeout 120
```

The local adapter expects Ollama's `/api/chat` on `http://127.0.0.1:11434`. `WORLD_ENGINE_LOCAL_URL` can select another loopback HTTP endpoint. It does not download or install a model. `/api/providers` lists models already visible from the local server. The registered adapter uses structured JSON actions, not native tool calls, zero temperature, and a bounded output size. A zero-temperature model call is not a guarantee of reproducibility across software or hardware revisions.

The [native tools adapter](native-provider.md) has API/console/CLI choices `local-tools` (v1) and `local-tools-ledger` (v2), integrated at `ef63eda9e009ecb33660fd35b2c13fd56ccde713`. Both use the existing `OllamaToolsProvider`, exact bounded application request/response records, and no JSON fallback. They require literal evaluation-only operation, cannot enable paid calls, and remain excluded from SFT, DPO and grouped training exports, including candidate pools. The catalog lists installed local models; preparation separately verifies tool capability and the model digest. The legacy `local` mode remains JSON. Omitted native concurrency is one; explicit `--concurrency` values one through eight remain supported. Legacy providers retain default four. The console selects one when entering native mode, but permits explicit editing; this is a conservative default, not a forced concurrency cap or proof of an optimal policy.

Import native SDK configuration separately from `world_engine.native_config`; legacy `RunConfig` and `ProviderId` are intentionally unchanged. This example performs inference and must run only in an approved window:

```python
from world_engine.native_config import NativeRunConfig
from world_engine.providers import make_provider
from world_engine.rollout import rollout

config = NativeRunConfig(environment_id="refund-ops", provider_id="local-tools",
                         model="qwen3:8b", seed=42, episodes=1, concurrency=1,
                         max_steps=20, timeout_seconds=35)
provider = make_provider(config)
try:
    await provider.prepare()
    episode = await rollout(config, 0, provider)
finally:
    await provider.close()
```

Use this inside an async function. A supplied provider remains caller-owned,
including preparation failures. For ordinary persisted batches, pass
`NativeRunConfig` to `RunManager.submit`, wait with `await manager.wait(run["id"])`,
and close the manager in `finally`; the manager owns provider preparation,
bounded closure and shared admission. Use a separate database from the running
API. Direct `OllamaToolsProvider` construction remains supported. Native config
defaults to `evaluation_only=true` and rejects explicit false or nonboolean
values. Stored run configuration preserves the alias; native episode provenance
retains `provider_id="custom"` plus exact class/protocol evidence.

[ATIF export](atif.md) is operator interchange, not a curated training batch.
The [Docker SDK](docker-executor.md) requires an approved already-installed exact
image ID and at most two sessions; its artifact and cleanup boundary is separate
from these in-process worlds. Collectors require explicit inference authorization;
mock tests and document/replay verification do not.

At integration source `d71a05d`, explicit `OllamaToolsProvider(config, protocol="ollama-tools-ledger-v2")` opts into the [ledger context](native-ledger.md); the default remains unchanged v1. Both share preparation, bounded transport, one-call parsing, recorder and cleanup. V2 replay independently regenerates initial public observation/history from trusted reset transitions and checks exact request bytes, selected contract and ledger/provider/recorder fingerprints. Both remain training-ineligible. Root's 1,196 tests/six optional skips, Ruff and frontend build describe that source. The [later access comparison](../artifacts/access-ledger-study/20261010-v1/report.json) at `cc2d4956` finalized all sixteen attempts: both protocols passed zero of eight tasks. V1 timed out eight times; v2 explicitly finished three times and reached max steps five times, without assigned settlement. A completed run status is not a business pass. No cache/causal latency improvement or full-token-context consumption is established; byte bounds are not tokenizer bounds.

The SDK-only [recorded JSON mode](json-provider.md), `HTTPProvider(config, record_calls=True)`, retains bounded exact local application exchanges too. It is excluded from all three training formats and candidate pools. The default registered JSON mode remains separate and does not retain failed-call response bodies. Recorded request bytes, readable actions and reported usage do not supply sampled tokens or behavior log-probabilities.

Remote providers remain disabled unless the process has `WORLD_ENGINE_ALLOW_PAID=1` and the run has `allow_paid: true`. They also require the appropriate key. See [provider onboarding](providers.md) for validated configuration and separate local/native/recorded modes. No paid provider call was needed to build or verify the local workflow platform. An enabled provider still needs a separate monetary budget; step and timeout limits are not a dollar cap.

## Inspect and cancel runs

The API offers the following routes:

| Method | Route | Result |
| --- | --- | --- |
| GET | `/api/health` | Version, execution mode, active runs, paid gate, global concurrency |
| GET | `/api/environments` | Worlds, tools, argument schemas, declared capabilities |
| GET | `/api/providers` | Provider status and available local models |
| GET | `/api/runs?limit=50&offset=0` | Paginated run summaries |
| POST | `/api/runs` | Admit a bounded run and return 202 |
| GET | `/api/runs/{uuid}` | Run, ordered episodes, traces, grades, lifecycle events |
| POST | `/api/runs/{uuid}/cancel` | Cancel unfinished work and return current summary |
| GET | `/api/runs/{uuid}/export?format=sft&quality=passed` | JSONL attachment with export counts |

An example run body is:

```json
{
  "environment_id": "refund-ops",
  "provider_id": "scripted-oracle",
  "episodes": 10,
  "seed": 42,
  "max_steps": 20,
  "concurrency": 4,
  "timeout_seconds": 60,
  "allow_paid": false,
  "label": "Refund reference run"
}
```

The console exposes operator state and grading details. It is not the agent's observation channel. Do not give an evaluated agent the operator API, database file, or console credentials in a future remote deployment.

Cancellation preserves already completed episodes. Active episodes may finish as cancelled records. Episodes that never started need not have records. Inspect `termination`, `status`, `error`, and lifecycle events instead of treating all missing or nonpassing episodes as policy failures.

`RunManager` owns preparation and cooperative provider closure. A failed or timed-out close changes an otherwise completed batch to failed, retains already stored episodes, and releases admission. Cancellation during cleanup preserves its requested terminal status. Direct rollout with a supplied provider requires caller-owned cleanup. The [lifecycle contract](provider-lifecycle.md) covers bounded cleanup and redacted failures; it cannot prove an arbitrary custom provider released external resources.

The final runner assigns episode reward zero to maximum-step truncation, timeout, cancellation, and failed execution. Operator detail can still retain a positive partial trusted grade for diagnosis. Grade components, episode reward, and passing completed outcome are deliberately different values.

## Export candidate data and replay

Substitute the UUID printed by a completed batch:

```sh
uv run python -m world_engine --db .world-engine/cli.sqlite3 export RUN_UUID --format sft
uv run python -m world_engine --db .world-engine/cli.sqlite3 export RUN_UUID --format dpo
uv run python -m world_engine --db .world-engine/cli.sqlite3 export RUN_UUID --format grpo
uv run python -m world_engine --db .world-engine/cli.sqlite3 replay RUN_UUID
```

Exports print JSONL on stdout and a selection report on stderr. The API includes `X-Export-Records` and `X-Export-Skipped` response headers. Training-oriented formats exclude validation, test, and evaluation-only episodes and require replay consistency. Trace exports can retain all splits for inspection; they must not be silently reused as training data.

SFT exports one tool decision per example, using the recorded controller system and user policy-input messages followed by the assistant action. Built-in adapters share that message construction. A custom provider may transform inputs internally; collect its actual request separately when needed. DPO needs a clean successful and lower-reward trajectory with the same scenario, split, task, world, grader, implementation fingerprints, initial state, and observation. It searches comparable candidates across persisted runs in the selected database. One successful run alone can yield zero pairs. DPO completions use `completion_kind: trajectory-messages`: this is an explicitly transformed multi-step sequence, not a native trainer-ready completion. Adapt and mask tool observations for the selected trainer before use.

Grouped rollout exports record reward variation, policy consistency, and missing training fields. They explicitly set `trainable: false`. No sampled token IDs, action loss masks, behavior probabilities, or frozen checkpoint are reconstructed from readable text.

The default passed selection requires a passing completed episode with no invalid actions. `quality=all` intentionally exposes a broader population and needs review before training. Exported records are candidates. Independent review, rights verification, redaction, diversity, and holdout protection are separate requirements.

Replay recreates the seeded world, checks environment and grader versions, validates the starting fingerprint, replays every action, compares observations and tool outcomes, and compares final trusted grade. It does not re-call the model. A matching replay establishes environment consistency for recorded actions.

Replay also derives authoritative episode reward and pass and rejects contradictory labels, status, termination, split, lineage, counts, or controller contexts. This guards SDK and file ingestion against semantically forged success records. It does not authenticate collection, verify reported timing/usage/model identity, or recursively fingerprint imported dependencies. Retain source and dependency manifests for reproducibility beyond the hashed modules and classes.

Replay the foundation evaluation-only operator records without the original local database. Later CRM/refund version 1.1 changes the shared environment module fingerprint, including that used for incident replay. Use the pinned foundation checkout rather than the current generators:

```sh
git worktree add --detach /tmp/world-engine-foundation-replay 1675734
cd /tmp/world-engine-foundation-replay
uv run python -m world_engine replay --file examples/benchmark-results/local-model-traces.jsonl
```

All nine final records replay against that foundation implementation, not the changed 1.1 generators. Use an unused checkout path if the example path already exists. Existing database records from prior source also require their source checkout for replay and replay-gated training exports; no automatic migration to new task semantics is performed. These files contain operator evidence and are not training exports. The separately retained historical intermediate-source sample has no source-recovery guarantee and must not be represented as replayable against the release. Hashes cover whole source modules, so unchanged world semantics do not imply identical recorded fingerprints.

## Persistence and recovery

`WORLD_ENGINE_DB` selects the database. The default is `.world-engine/engine.sqlite3`. SQLite uses WAL mode, foreign keys, and a busy timeout. Episode and lifecycle-event tables reject ordinary updates and deletes through triggers. The operator can still alter the file or schema, so this is an append-only application convention rather than tamper-proof storage.

Run one manager process per database. A nonblocking process lock rejects a second scheduler before recovery can change live runs. Use separate database paths for CLI experiments and the running API, or submit through the running API. The adjacent `.sqlite3.lock` file may remain after shutdown; the kernel lock, not file existence, indicates ownership. A restarted manager marks previously queued or running runs interrupted and preserves completed episodes. It does not resume unfinished episodes or model requests.

Stop the server before backing up or replacing its database. A stopped SQLite database can be copied as a unit. For a live backup, use SQLite's backup API so WAL contents are included consistently. Keep the original database until the restored copy has passed integrity and replay checks.

## Verify the build

From the repository root:

```sh
uv run pytest
uv run ruff check src tests
uv run python -m world_engine benchmark --episodes 30 --trials 3
```

From `web`, run `npm run build`. Follow [console QA](ui.md) for browser verification. The benchmark now writes to a unique fresh directory under `.world-engine/benchmarks` by default. An explicit `--output` must not exist, including a broken symlink; it never reuses historical receipts. It covers the current registered worlds. Its timings include scheduling, grading, fingerprints, and SQLite persistence. They omit language-model inference and do not establish cloud sandbox performance.

The five standalone collectors also require an explicit fresh output. Replace `NEW_RUN` with an unused name. These commands are examples, not authorization to collect during a locked study:

```sh
uv run python examples/schema_cache_comparison.py --output .world-engine/evidence/cache-NEW_RUN
uv run python examples/io_overlap_benchmark.py --output .world-engine/evidence/io-NEW_RUN
uv run python examples/generate_dataset.py --output .world-engine/evidence/data-NEW_RUN
```

The commands above use scripted policies only. Dataset generation covers the three legacy worlds and remains candidate data, not training. The cache comparison keeps its uncached/cached controls in separate fresh subdirectories, without copying historical receipts.

The following commands perform local inference and require a separately approved budget/window. The public runner also has build-time network requirements documented in its protocol. Do not execute either during another locked collection window:

```sh
uv run python examples/local_model_benchmark.py --output .world-engine/evidence/model-NEW_RUN
uv run python scripts/public-benchmark.py --output artifacts/public-benchmark/NEW_RUN
```

For a scripted-only public-task run, add `--skip-local`. This avoids model inference, not Docker build/network prerequisites. Each collector rejects a preexisting output rather than pruning or overwriting prior evidence. Console QA similarly requires fresh `--output` and makes no inference unless the standard phase explicitly receives `--local-cancel`; ATIF/access phases are scripted-only.

The original research reports, PDFs and build sources are retained in a private local archive rather than the current public tree. Public design and interpretation guidance lives in the [engineering guide](engineering-guide.md); dated results and original measurement receipts remain linked below. Moving the research documents does not change recorded outcomes or source pins.

The [engineering guide](engineering-guide.md) covers grading, failure interpretation, split-aware exports, training-data requirements and concurrency measurement. The [public-task protocol](public-benchmark.md) documents the separate evaluation-only Docker runner and its build-time network requirements.

Recorded measurements are available in the [scripted matrix](../examples/benchmark-results/benchmark.md), [paired local-model sample](../examples/benchmark-results/local-model.md), and [final public-task evidence](../artifacts/public-benchmark/native-tools-v2-final/report.md). The local workflow sample uses one task per world, not a broad benchmark. The final public native-tool attempt executed eight shell commands and failed the task. Earlier JSON-v1 attempts executed no commands because their responses were truncated; those historical protocol failures are separate evidence.

Follow-up [native evidence](../artifacts/native-provider/final/report.md) was collected at `7de25124fd752acf61571ec0860309c139652fff`: six tasks, 48 transport attempts, four business passes and two clean successes; 71,531 reported input tokens and 1,258 output tokens across all attempts, 88.289 seconds. The [independent validation](../artifacts/native-provider/final/independent-validation.json) records six replays, six pinned Harbor validations and exclusion from all three training formats. These six cases do not estimate population performance or compare native and historical JSON protocols at matched conditions. The [hardened workflow receipt](../artifacts/workflow-variants/hardened/report.json) records 128 replay-verified scripted attempts over 64 unique tasks at `4bc73fe6`; the [Docker lifecycle receipt](../artifacts/docker-executor/final/lifecycle.json) records 24 successful executions of four repeated synthetic inputs with empty owned-resource cleanup after each trial. Both made zero model calls. Preserve each receipt's recorded source for later replay and interpretation.

Later [CRM/refund certificate grading](workflow-grader-integrity.md) corrects additional role/audit/payment-identity gaps and a legitimate CRM transfer-before-void grading rejection. Existing workflow and native sidecars record these limitations without changing old outcomes. Their replay requires the recorded source checkout; even unchanged incident records acquire a different shared-module fingerprint. The [protocol-v3 receipt](../artifacts/workflow-variants/20261010-v3/report.json) at `ee26d7b9` now contains 128 matched scripted attempts over 64 tasks, reference 64 passes and baseline zero. All 128 rows and 24 summary cells were independently reconciled with raw episodes; replay, actual Harbor schema and training exclusions were checked separately. [Validation](../artifacts/workflow-variants/20261010-v3/independent-validation.json) preserves that proof without changing prior outcomes.

The fixed [matched native/recorded-JSON study](workflow-model-study-results.md) completed under root ownership at source `622c5b18ee38d0e581d04832e555801febc37dc3`: 32 tasks, 64 model and 64 scripted finalized attempts, twenty decisions/35 seconds, concurrency one, 1600.268 seconds total. Native passed 24/32 business tasks with six clean successes; JSON passed 7/32 with none clean. Root independently verified all 128 replays/Harbor schema conversions, source hashes, exact row correspondence and training exclusion. Evidence and its validation sidecar were committed at `c5d7cabaed06d7c3e5bbb45b45bc6d0f799abed0`, in [PR #21](https://github.com/nthpaul/world-engine/pull/21). Root also executed the results guide's detached-checkout CLI replay command and verified all 128 episodes without inference. Recorded transport usage is incomplete; known token sums are not complete costs. Replay uses the pinned collected source, not subsequent provider revisions. The locked protocol/status document remains immutable source history; the separate results guide records actual execution.

## Latest bounded receipts

The [native access diagnosis](access-native-results.md) describes eight attempts at `ee26d7b9`: zero business/clean passes, all terminated at the 35-second deadline. There were 97 recorded requests, 89 completed decisions and 32 semantic discovery/review rejections. Known partial usage was 228,895 input and 2,847 output tokens; eight cancelled requests lacked usage, so these are not totals or upper bounds. No longer-deadline rerun is implemented or authorized by that diagnosis. All eight records replayed, converted to actual pinned Harbor schema, and were excluded from each training format.

The [four-world benchmark](../artifacts/benchmarks/20261010-four-world-v1/benchmark.json) contains 72 batches and 2,160 persisted episodes: 1,080 reference passes and 1,080 baseline failures. Its 120 unique world/seed tasks each repeat nine times across trial/concurrency settings. Rate denominators are recorded batch wall time; per-episode latency is a different measurement. All 72 trials and 24 summaries reconcile with read-only SQLite and raw records. The 5,833,426-byte gzip journal expands to 154,691,204 bytes; local SQLite occupies additional storage. [Validation](../artifacts/benchmarks/20261010-four-world-v1/independent-validation.json) records those correlations. Async concurrency does not imply CPU parallelism or inference throughput.

Access [UI v2](../artifacts/access-provisioning/20261010-ui-v2/ui-report.json) at `e1550290` passed 31 checks, with sixteen episodes, thirteen screenshots, ten downloads and a 5.48-second VP9 video. All ten exports reproduce byte-for-byte; all sixteen episodes replay and validate against actual Harbor, and SFT/DPO/grouped each exclude sixteen records. The [failed v1 serialization attempt](../artifacts/access-provisioning/20261010-ui-v1/failure.json) remains preserved, not silently replaced. Consult [UI validation](../artifacts/access-provisioning/20261010-ui-v2/independent-validation.json).

The [scripted candidate collector](scripted-candidate-corpus.md) completed its authorized run at source `5e5eb0d9`; [manifest](../artifacts/candidate-corpus/20261010-v1/manifest.json). All 128 episodes verified: reference 64 business/clean passes, baseline 64 business failures, 620 decisions, eight completed runs and no inconclusive/unattempted slots or retries. Its 51/6/7 task split yields 102/12/14 episodes. Train-only outputs contain 397 exact SFT decisions, 51 strict DPO pairs and 51 mixed-policy nontrainable groups; thirteen heldout reference cases are excluded per format. Legacy baseline shaped reward is not business success.

Root and console independently verified replay, actual Harbor 0.24.0 interchange, source scope and byte-exact exports; console reconstructed the latter without the exporter. Original artifacts total 19,021,481 bytes; elapsed time was 11.456073333043605 seconds. The later publication archive is 359,286 compressed / 9,344,170 expanded bytes, containing protected synthetic snapshots in SQL row order, not execution chronology; archive and sidecar bytes are separate. [Results and replay guidance](scripted-candidate-results.md), [independent validation](../artifacts/candidate-corpus/20261010-v1/independent-validation.json). No model, tokenizer, training or cloud calls occurred. Default/`--plan` still creates no Store/provider; future collection requires separate authorization, clean reviewed source, fresh output and quotas. The pure native-ledger builder's 76 tests precede SDK integration and the later zero-pass access comparison; none establishes a cache gain or trained improvement.

Public-boundary hardening is recorded in [PR #28](https://github.com/nthpaul/world-engine/pull/28), source `451c1cf9923488f0031a50170e8b714dc31284f2`, with 26 focused tests. These local boundary checks do not complete authentication or multi-tenant deployment gates. The [engineering guide](engineering-guide.md) explains the remaining evidence and deployment boundaries; original research workbooks are retained privately.

At source `b4501029a332d7675a12fbf84b00358230d3d154`, the [five-phase console receipt](../artifacts/qa/20261010-current-final-validation-v1/independent-validation.json) passed 129 checks with 56 screenshots, five videos and 26 byte-exact downloads. It created 34 scripted episodes and inspected two unchanged imported native episodes. All 36 replay/Harbor checks passed; native inspection made no model calls. Final operator history was eleven runs/68 episodes, including prior records, not 68 new executions. Standard candidates are not blanket-excluded: their captured exports contain 52 SFT decisions, eight DPO pairs and eight nontrainable groups. The other phases provide sixty episode-format exclusion checks. Original QA accounting is 98 files/21,210,254 bytes; later sidecar bytes are separate.

The [post-change CPU profile](../artifacts/profiling/20261010-v2/independent-validation.json) at that source preserves 192 reference episodes and 1,456 decisions, all passing cleanly. Independent proofs checked replay, actual Harbor, 576 training exclusions, eight binary profiles and logical equivalence. Across four profiled trials, 728 redundant observation reads were removed. Unprofiled read counts were not instrumented. The older profile preserved only 96 profiled episodes; its 96 unprofiled executions were unsaved and its producer was a retrospective sidecar. Do not claim byte-exact reconstruction of that original stdin producer or unsaved records. The new collector preserves both trials; no inference or model-speed claim follows. See [profiling contract](scripted-profiling.md).

The [model-admission study](model-concurrency-study-results.md) at source `1d9f2315348cbea192f7ae5c4f1cf0343ba6618a` completed 32 evaluation-only attempts in 441.573 seconds: 29 business passes, twelve clean successes, 233 decisions, 32 denied actions and three timeouts. Admission one passed 16/16; admission two 13/16. Useful rates were 0.072657230 versus 0.059262489 passes per summed batch-wall second, with preparation/cleanup separate. All 32 replay/Harbor and 96 real-exporter exclusions passed; original raw/report bytes total 4,473,315. Eight unique tasks repeat four times, not 32 independent samples. Partial known usage covers 233/236 chat attempts. This is SDK caller-wave admission, not API throughput or an optimal/GPU/cache policy. Never rerun a locked collector merely to improve a result; new collection needs separate authorization, reviewed source and a fresh output. Root's 1,499 tests/six optional skips, Ruff and frontend build describe source `1d9f2315`, not future changes.

## Read-only database checks

Use the SDK runtime's structured `sqlite3` API with a `mode=ro` URI and
`PRAGMA query_only=ON` for live SQL-data inspection. Close the connection in
`finally`. For a live backup, use `Connection.backup` into a fresh private
destination; copying only the main SQLite file can omit committed WAL data.
Read-only SQL access may still create or manage WAL/SHM sidecar files. It is
not a promise of zero filesystem activity.

The final audit at documentation source `51bd144` used an online backup of the
operator history into a temporary directory. All thirteen runs, seventy episodes
and 37 lifecycle events matched row-for-row; all episode content hashes and
denormalized fields matched. Two synthetic queued/running jobs were recovered
to `interrupted` on the copy, a second writer was rejected, and reopening was
idempotent. The real database's original rows stayed unchanged; all scratch
resources were removed. Root separately confirmed live integrity `ok` and zero
active jobs. This does not test abrupt power loss, filesystem flush guarantees
or hostile-host authenticity.

On this machine, Apple SQLite CLI 3.54.0 returned error 14 for read-only opening
of a WAL-mode database after its sidecars disappeared. A minimal one-row fixture
reproduced it independently of World Engine's schema and path. Python SQLite
3.47.1 read-only opening succeeded, as did the CLI while that connection held
WAL/SHM sidecars open. A disposable backup converted to DELETE journal mode also
opened through the read-only CLI. This narrows the observed portability issue;
it does not establish the internal Apple VFS cause. Do not interpret that CLI
error alone as corruption, switch the live database to a different journal mode,
open it read-write for an audit, or use an immutable URI against an active WAL
database. The audit changed journal mode only on a disposable copy.

## Current limits

Runtime source `0f51b903cfcc73e55901d11d5828e08c692220aa` hardens remote-provider construction errors against URL disclosure; synthetic regression cases make no real remote/model calls. Root verified all 1,743 tests/no skips, including actual pinned Harbor and approved-existing-image Docker probes, in 46.93 seconds, plus Ruff/build/schema/mock history and both SDK examples. One upstream Starlette warning remains. Native/grader/models sources stay unchanged, and eighteen delivered native episodes still replay; HTTP/recorded-JSON module fingerprints change, so older JSON evidence requires its original checkout. Source54 passed all three CI gates; source50 API/model and source51 UI receipts remain untouched.

The separate [native API smoke](../artifacts/native-api-smoke/20261010-v1/report.json) at `8b82c7aa5ac944ec35b62ef2d12f28f4b8d254cb` actually admitted two ordered native runs, v1 then v2, on the same refund seed54000. Both finished with clean business passes, nine accepted decisions total, no cancellations/retries, and complete known usage across nine calls of 11,533 input/289 output tokens. This verifies the API/RunManager/factory boundary on one task, not an adapter-performance or capability study. Root/engine checked both replay/actual Harbor results, six native training exclusions, 22 source hashes and exact raw API detail/wrapper bytes. The collector's 59 API responses and two client metadata requests do not include server preparation metadata. Original 62 files total 822,301 bytes; overall elapsed was 15.013487583 seconds. Final readonly history was thirteen runs/70 episodes/no active jobs, including preserved earlier runs.

Native controls QA v1 passed fifteen automated checks but root visual review rejected its clipped 360px Start footer. Its original receipt stays visible. Corrected source51 controls v2 passed fifteen checks with twelve screenshots/one video/24 GETs and a fully visible footer. Both actual source50 API receipts then passed 25 readonly UI checks each at source51, with 22 screenshots/two videos/ten byte-exact downloads; no new model calls, imports, rollouts or POSTs occurred. Combined new inspection is 65 checks/34 screenshots/three videos/54 original files totaling 5,055,000 bytes, separately validated, not a rewrite of the older 129-check cohort. Do not rerun the model attempts to repair an inspection problem. See [controls v2](../artifacts/native-controls-qa/20261010-v2/report.json) and [actual receipt inspection](ui.md#final-native-controls-and-actual-receipt-inspection).

The worlds are synthetic tool workflows with deterministic business rules. They lack real application parity, human expert calibration, networked integrations, visual desktop actions, full model sampling provenance, real training checkpoints, cloud sandbox orchestration, authentication, tenant separation, and a process-level sandbox for arbitrary code. Scenario split labels do not establish independent task-family holdouts. Operator control of the host can bypass local integrity checks.
