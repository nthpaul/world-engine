# Operate World Engine locally

This guide describes the delivered Python SDK and local operator API. The [technical report](report/world-engine-report.md) explains the design. The [roadmap](ROADMAP.md) lists work required for training, application parity, cloud execution, and multi-tenant deployment.

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

`make_environment` creates a new instance and resets it. `reset(seed)` rebuilds the episode state. `observe()` returns a copy of the permitted operational state, task, role, tools, and completion flag. Tool metadata includes its argument schema. `step()` returns an observation, a tool result, `done`, and a state fingerprint. Invalid actions return `ok: false` and do not apply their state mutation.

`snapshot()` returns an operator copy including seed, logical tick, completion flag, and state. `evaluate()` checks trusted state. A safety-envelope violation forces reward to zero. Other incomplete outcomes can receive partial credit. `Grade.passed` requires every check to pass. Finishing an incomplete task does not create a passing grade.

Each environment owns its Python state. There is no process or VM sandbox around these objects. Run only trusted Python extensions in this process. The instance has no external resource that needs a `close()` call; a future provider that owns resources needs explicit lifecycle cleanup.

## Run a batch

The CLI can run an isolated batch without the web server. Use a separate database when the server is active:

```sh
uv run python -m world_engine --db .world-engine/cli.sqlite3 rollout \
  --environment refund-ops --provider scripted-oracle \
  --episodes 10 --seed 42 --concurrency 4
```

The command prints a persisted run summary, including its UUID. Repeat the same environment and seeds with `--provider scripted-baseline` to collect incomplete alternatives. `--max-steps` limits decisions. `--timeout` limits each episode's wall time. Episodes support 1 to 100, per-run concurrency supports 1 to 8, and the process admits at most 32 active runs with 8 active episodes globally.

Concurrency is cooperative `asyncio` scheduling. The workflow simulations do not use multiprocessing or GPU inference. Deterministic local policies mainly exercise state transitions, hashing, and persistence. External or local model latency changes the throughput regime.

Use the existing local model without paid calls:

```sh
uv run python -m world_engine --db .world-engine/local-model.sqlite3 rollout \
  --environment refund-ops --provider local --model qwen3:8b \
  --episodes 1 --concurrency 1 --max-steps 12 --timeout 120
```

The local adapter expects Ollama's native `/api/chat` on `http://127.0.0.1:11434`. `WORLD_ENGINE_LOCAL_URL` can select another loopback HTTP endpoint. It does not download or install a model. `/api/providers` lists models already visible from the local server. The adapter uses structured JSON actions, zero temperature, and a bounded output size. A zero-temperature model call is not a guarantee of reproducibility across software or hardware revisions.

Remote providers remain disabled unless the process has `WORLD_ENGINE_ALLOW_PAID=1` and the run has `allow_paid: true`. They also require the appropriate key. No paid provider call was needed to build or verify the local workflow platform. An enabled provider still needs a separate monetary budget; step and timeout limits are not a dollar cap.

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

From `web`, run `npm run build`. Follow [console QA](ui.md) for browser verification. The benchmark writes raw trials and a readable summary under `examples/benchmark-results` by default. Its timings include scheduling, grading, fingerprints, and SQLite persistence. They omit language-model inference and do not establish cloud sandbox performance.

The report PDF can be regenerated with `bash docs/report/build-report.sh` when Pandoc, Tectonic, and Poppler are installed. The build leaves editable standalone TeX, metadata, link lists, text extraction, and page renders for QA. Reinspect renders after any content change.

The [learning labs](report/learning-labs.md) walk through executable SDK grading, exploit attempts, paired policies, split-aware exports, RL batch requirements, and concurrency profiling. The [public-task protocol](public-benchmark.md) documents the separate evaluation-only Docker runner and its build-time network requirements.

Recorded measurements are available in the [scripted matrix](../examples/benchmark-results/benchmark.md), [paired local-model sample](../examples/benchmark-results/local-model.md), and [final public-task evidence](../artifacts/public-benchmark/native-tools-v2-final/report.md). The local workflow sample uses one task per world, not a broad benchmark. The final public native-tool attempt executed eight shell commands and failed the task. Earlier JSON-v1 attempts executed no commands because their responses were truncated; those historical protocol failures are separate evidence.

## Current limits

The worlds are synthetic tool workflows with deterministic business rules. They lack real application parity, human expert calibration, networked integrations, visual desktop actions, full model sampling provenance, real training checkpoints, cloud sandbox orchestration, authentication, tenant separation, and a process-level sandbox for arbitrary code. Scenario split labels do not establish independent task-family holdouts. Operator control of the host can bypass local integrity checks.
