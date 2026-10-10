# Learning labs

These six labs use the current SDK, CLI, tests and public-task runner. Read the immutable [foundation report](world-engine-report.md) for concepts and [operations guide](../OPERATIONS.md) for current lifecycle and export contracts. Run commands from the repository root after `uv sync --extra dev`. None requires paid model calls. Use a separate, fresh database from the running API. Inference-bearing commands require a separately authorized window and must not run alongside another locked experiment.

Historical verification on 2026-10-10 executed these experiments against the three-world foundation release `1675734`, not the current four-world source. Denied overpayment preserved state, fixture corruption returned zero reward, and paired reference/incomplete-policy runs, replay and split-aware exports behaved as described. The exact counts below belong to that foundation checkpoint. Current commands remain executable but new versions can change decision/export counts and grades; inspect their actual output rather than expecting historical totals. Scenario identity includes implementation fingerprints, while split membership uses stable environment-family/seed lineage so a grader repair does not move a related task between training and holdout.

The foundation's twenty paired seeds produced reference 20/20 and incomplete policy 0/20, with twenty successful replays. The reference source contained fourteen train, four validation and two test episodes. SFT selected 46 tool decisions and excluded all six held-out episodes. DPO and grouped selection each produced fourteen comparable scenarios; grouped records were `trainable: false` and `policy_consistent: false`. These are historical controls, not current-source collection or learned-model results. Use a pinned foundation checkout to reproduce these exact counts.

## 1. A transition is not a completed task

Run this SDK experiment:

```sh
uv run python - <<'PY'
from world_engine import Action, make_environment

env = make_environment("refund-ops", seed=42)
before = env.snapshot()
result = env.step(Action(tool="inspect"))
print("inspect", result["result"], "done", result["done"])
assert env.snapshot()["state"] == before["state"]
assert env.snapshot() != before
env.step(Action(tool="finish"))
grade = env.evaluate()
print("reward", grade.reward, "passed", grade.passed)
for check in grade.checks:
    print(check.name, check.passed)
assert not grade.passed
PY
```

**Questions.** Why can the snapshot change when the operational state does not? Why can a failed task receive positive reward? Does `finish` certify success?

**Worked answer.** The logical tick advances for an action, so the whole snapshot changes even for inspection. The legacy refund grader averages satisfied checks when no safety violation exists. Untouched state can preserve unrelated records and approval constraints while failing settlement. Foundation seed 42 returned 0.6 and `passed: false`; read the current experiment's printed reward/checks rather than assuming that value after a version change. `finish` terminates the attempt; trusted grading certifies success. A positive diagnostic shaped reward is not a passing workflow. Access uses binary outcome reward instead. A timed-out rollout receives zero episode reward even if its diagnostic `Grade` retains partial credit.

Verify the same distinction across worlds:

```sh
uv run pytest tests/test_environments.py -k baseline
```

## 2. Block an exploit, then test the grader independently

First attempt an overpayment through the agent's allowed interface. Then inject corruption directly as a trusted test fixture to exercise the grader's defense in depth:

```sh
uv run python - <<'PY'
from world_engine import Action, make_environment

env = make_environment("refund-ops", seed=42)
state = env.observe()["state"]
ticket = state["tickets"][0]
before = env.snapshot()["state"]
attempt = env.step(Action(tool="issue_refund", args={
    "order_id": ticket["order_id"],
    "amount_cents": ticket["requested_cents"] + 1,
    "idempotency_key": "lab-overpayment",
}))
assert not attempt["result"]["ok"]
assert env.snapshot()["state"] == before
print("blocked", attempt["result"], "reward", env.evaluate().reward)

# Trusted fixture corruption, not an action available to the agent.
env.state["ledger"].clear()
grade = env.evaluate()
assert grade.reward == 0 and not grade.passed
print("corrupted fixture", grade.model_dump())
PY
```

**Questions.** Why does the blocked attempt not necessarily receive zero reward? Why test direct corruption if tools already validate requests? Is this a security sandbox?

**Worked answer.** A rejected tool action cannot overpay, and the unchanged state still satisfies some checks. The independent corruption deletes payment history and violates the safety envelope, so the grader forces zero reward. Defense in depth catches mistakes in future tools or task fixtures, not only malformed requests. The direct fixture mutation demonstrates that the Python host is trusted. An untrusted extension sharing this process could reach environment internals; a separate process or VM boundary is required to prevent that access.

Run the actual exploit and corruption checks:

```sh
uv run pytest tests/test_environments.py -k 'injection or forged or critical_corruption'
```

## 3. Compare paired attempts, not selected successes

Collect reference and incomplete-policy runs on the same seeded tasks. This creates a new isolated lab database and prints the run IDs used in later labs:

```sh
uv run python - <<'PY'
import asyncio
from pathlib import Path
from world_engine.models import RunConfig
from world_engine.rollout import RunManager
from world_engine.store import Store

async def main():
    database = Path(".world-engine/labs.sqlite3")
    if database.exists() or database.is_symlink():
        raise SystemExit("Choose a fresh database path in labs 3, 4 and 5; preserve old evidence")
    manager = RunManager(Store(database))
    try:
        runs = []
        for provider in ("scripted-oracle", "scripted-baseline"):
            run = manager.submit(RunConfig(
                environment_id="refund-ops", provider_id=provider,
                episodes=20, seed=42, concurrency=4, label="learning-lab"))
            runs.append(await manager.wait(run["id"]))
        for run in runs:
            print(run["config"]["provider_id"], run["id"])
        left, right = runs
        for a, b in zip(left["episodes"], right["episodes"]):
            assert a["scenario_id"] == b["scenario_id"]
            print(a["seed"], a["passed"], b["passed"],
                  a["reward"], b["reward"], b["termination"])
    finally:
        await manager.close()

asyncio.run(main())
PY
```

**Questions.** Which variable changed? How should you classify an incomplete baseline, a timeout, and cancellation? Is the reference policy's success a language-model result?

**Worked answer.** The policy changed while the scenario identity, initial state, rules, and grading implementation stayed fixed. The baseline reaches a normal `finished` termination without the required outcome: a policy failure. Timeout is an execution-budget failure; inspect whether model latency or environment work exhausted it. Cancellation is an operator outcome and should not silently enter a policy-only score. The reference knows the synthetic business rules. Its success tests the environment implementation and rollout system, not learned competence or production transfer.

Replay either printed run ID:

```sh
uv run python -m world_engine --db .world-engine/labs.sqlite3 replay RUN_ID
```

Replay checks the recorded action sequence. It does not ask a model to produce the same actions again.

## 4. Follow the export boundary and deduplication

Inspect split counts and default SFT selection for the reference run from lab 3:

```sh
uv run python - <<'PY'
from collections import Counter
from world_engine.exports import export_records
from world_engine.store import Store

store = Store(".world-engine/labs.sqlite3")
run = next(r for r in store.list_runs(limit=100)
           if r["label"] == "learning-lab"
           and r["config"]["provider_id"] == "scripted-oracle")
episodes = store.episodes(run["id"])
print("source splits", Counter(e["split"] for e in episodes))
records, selection = export_records(store, run["id"], "sft")
assert all(r["provenance"]["split"] == "train" for r in records)
print("selection", selection)
if records:
    print("first decision", records[0])
PY
```

**Questions.** Why can export record count exceed episode count? What happens to test and validation episodes? What if the same scenario is collected again? Do hash-based seed splits prove generalization?

**Worked answer.** SFT emits one example for each tool decision, using exact recorded decision inputs. Training formats exclude held-out splits and evaluation-only records; trace exports are a separate inspection format. Scenario identity remains stable under unchanged source fingerprints, seed, and initial state. A separate stable environment-family/seed lineage determines the split, preventing a source revision from moving a related task into training. Grouped and preference candidate selection deduplicates identical action trajectories, but SFT is not a global corpus deduplicator. A downstream manifest must deduplicate repeated demonstrations and related task families. New seeds mostly vary records within the same synthetic rule templates. They do not establish generalization to new business rules, applications, or incident families.

Run the split and provenance boundary regression:

```sh
uv run pytest tests/test_runs.py -k persistence_export_split
```

## 5. A preference pair is not an on-policy RL batch

Using the reference run ID from lab 3, inspect both candidate formats:

```sh
uv run python -m world_engine --db .world-engine/labs.sqlite3 export RUN_ID --format dpo
uv run python -m world_engine --db .world-engine/labs.sqlite3 export RUN_ID --format grpo
```

**Questions.** Why can DPO yield zero records? Why label its completion `trajectory-messages`? What does `policy_consistent: false` mean? What is the learning signal for equal rewards?

**Worked answer.** A DPO pair needs a clean passing trajectory and a lower-reward alternative with the same scenario, prompt, initial state, split, and implementation fingerprints. The baseline run supplies candidates only where those conditions hold. The completion is a transformed multi-turn trajectory containing tool observations, not a single native assistant response. A trainer adapter must preserve boundaries and mask non-agent tokens correctly.

The reference and baseline are different policies, so their grouped candidates are not an on-policy GRPO batch. Even a policy-consistent group lacks exact sampled token IDs, action masks, behavior log probabilities, and a frozen checkpoint here; `trainable: false` is intentional. Model token counts are not token sequences or probabilities.

**Later measured example.** The [scripted corpus](../../artifacts/candidate-corpus/20261010-v1/manifest.json) at `5e5eb0d9` verified 128 episodes on 64 tasks: 51 train, six validation and seven test. It produced 397 exact train SFT decisions, 51 strict DPO pairs and 51 mixed-policy nontrainable groups. Each format excluded thirteen heldout reference cases. Why does 128 episodes not imply 128 preference pairs? Each pair uses one comparable task's two alternatives, and heldout tasks are excluded; only 51 train tasks remain. These are candidate outputs, not a checkpoint or an independent rule-family evaluation. Baseline business failures may retain positive legacy shaped rewards.

For group rewards `[1, 1, 1, 1]`, the mean is 1 and standard deviation is 0. With epsilon stabilization, each normalized reward advantage is zero. There is no relative reward direction for the update, though a separate KL term can still have an effect. The right response is to inspect task difficulty, sampling diversity, and the algorithm's handling of zero-variance groups, not fabricate preferences. For `[0, 0, 1, 1]`, population mean is 0.5 and standard deviation is 0.5, so advantages are approximately `[-1, -1, 1, 1]`. Those numbers alone do not supply the missing policy probabilities.

## 6. Measure the bottleneck and the isolation boundary

Profile scripted workloads at concurrency 1, 4, and 8, with repeated timings:

```sh
uv run python -m world_engine benchmark \
  --episodes 30 --trials 3 --output .world-engine/lab-benchmark
```

Use a new unused output directory each time; a preexisting path or symlink is rejected. Read `benchmark.json` and `benchmark.md` there. The current matrix includes all four registered workflow worlds and both scripted policies; the foundation receipt covered three. Repeated trials measure timing variation; success intervals use the first observed outcome per distinct scenario across trials, rather than counting deterministic repeats as independent evidence. An empty first trial does not erase later observations; conflicting repeated outcomes are counted separately.

Compare [the historical same-source schema-cache measurement](../../examples/benchmark-results/schema-cache-comparison.md) to see a CPU optimization with unchanged outcomes at its recorded source. Run `uv run python examples/io_overlap_benchmark.py --output .world-engine/lab-io-NEW_RUN` for a fresh control that inserts a simulated 25-millisecond wait per decision. Its concurrency gains demonstrate awaited I/O overlap, not a GPU or cloud benchmark. Do not merge these regimes into a single throughput claim.

The later [four-world receipt](../../artifacts/benchmarks/20261010-four-world-v1/benchmark.json) has 2,160 episodes, 72 batches and 24 summary cells at source `ee26d7b9`. Only 120 world/seed tasks are unique; each repeats nine times. Independently recomputed rates use each recorded batch wall time, medians use three trial rates, percentiles use the declared nearest-rank rule, and Wilson intervals count thirty distinct scenarios per world/policy/concurrency cell. [Validation](../../artifacts/benchmarks/20261010-four-world-v1/independent-validation.json) correlates SQLite and the full gzip journal. This is a newer scripted receipt, not a replacement for this workbook's foundation counts.

The [later CPU profile](../../artifacts/profiling/20261010-v2/independent-validation.json)
at `b4501029` saved both trials: 192 episodes and 1,456 decisions. Exact saved
profile counts confirm 728 redundant observation reads removed across the four
profiled trials, without changed logical outcomes. The historical run saved only
96 profiled episodes; its 96 unprofiled records were not saved and its producer
was retrospective. Why not claim 1,456 measured read removals? The unprofiled
read counts were not instrumented. Also distinguish fewer simulator reads from
a measured model-speed gain: this collection made no inference calls.

The [native-ledger SDK](../native-ledger.md) now supports explicit v2 at `d71a05d`; default v1 remains unchanged. Mock/source checks establish public-context regeneration and replay guards, not cache reuse. Why does an append-stable UTF-8 user message not prove a speed gain or full context consumption? The daemon's template/tokenizer and serving scheduler determine token prefixes, truncation and cache behavior. The [later eight-pair comparison](../../artifacts/access-ledger-study/20261010-v1/report.json) recorded zero business/clean passes for either protocol, despite lower aggregate v2 request-body bytes. V2 terminated earlier with different actions and many more invalid actions; those unequal trajectories do not isolate caching or prove useful speed. Independent tokenizer/context proof remains absent.

Then, only in a separately approved inference window with an existing local Ollama model, compare the latency regime. Do not execute this during another locked experiment:

```sh
uv run python -m world_engine --db .world-engine/lab-local.sqlite3 rollout \
  --environment refund-ops --provider local --model qwen3:8b \
  --episodes 1 --concurrency 1 --max-steps 12 --timeout 120 --evaluation-only
```

**Questions.** Why might more concurrency fail to improve scripted throughput? Why can a fast simulator still produce slow model episodes? Can a single local-model attempt estimate general capability?

**Worked answer.** These small workflows are synchronous Python transitions with hashing and SQLite persistence. Cooperative scheduling is not additional CPU execution capacity, and higher concurrency can add overhead. A model episode waits on repeated inference calls, so model capacity and context length can dominate environment cost. One attempt is a functional integration sample, not a reliable capability estimate or controlled policy comparison. Count provider failures separately from attempted task failures.

**Later real-model counterexample.** The [SDK admission study](../model-concurrency-study-results.md)
at `1d9f2315` repeats eight refund tasks in fixed waves 1/2/2/1. Admission one
passed 16/16, admission two 13/16, with three timeouts retained. Useful rates
were 0.072657230 versus 0.059262489 passes per summed continuous batch-wall
second. Twelve attempts were clean successes overall, not 29 clean passes.
Why does higher client overlap not guarantee better useful throughput? Requests
can wait or contend inside the daemon, and the episode deadline includes that
wait. The experiment does not isolate a GPU/queue/cache mechanism or establish
an optimal policy. Count eight distinct fixed task clusters, not 32 independent
attempts; keep preparation/cleanup outside, but validation inside, the declared
batch clock. All 32 records replayed, passed actual Harbor schema checks and
were excluded from training. Known usage over 233/236 requests is partial.

The later [native API smoke](../native-api-smoke-results.md) passes two clean
attempts on the same refund seed54000 through the actual API/RunManager/factory.
Why does that not overturn the zero-pass access study or establish a better
adapter? These are different tasks and study purposes; no new weights, tuning
or matched performance design was used. Its two actual episodes, source50,
stay separate from source51 read-only UI checks, which make no model calls.

Finally inspect the public task's distinct trust boundary:

```sh
uv run python scripts/public-benchmark.py --skip-local \
  --output artifacts/public-benchmark/lab-NEW_RUN
python3 -m unittest discover -s tests -p test_public_benchmark.py
```

Docker image builds need network access and local storage; task execution and grading have container networking disabled. The public task runner is separate from the synthetic-workflow training exporter. Review [the exact protocol](../public-benchmark.md) and the manifest rather than inferring safety from the word Docker.

**Questions.** Which principal can see the grader? Which data crosses from the agent to the verifier? What would violate the protocol?

**Worked answer.** The trusted controller mounts the official tests only in a fresh verifier after removing the agent container. Only a bounded regular CSV artifact crosses the boundary. The agent runs nonroot with read-only root filesystem, no network, no host repository or Docker socket, and a narrow writable output mount. Mounting the repository, grader, or socket into the agent; accepting a symlink artifact; or grading while a writer remains active would undermine the intended boundary. Containers still share a host kernel, and this is a disclosed single-task adaptation, not the full Terminal-Bench leaderboard protocol. Keep its canary, license, and evaluation-only exclusion intact.
