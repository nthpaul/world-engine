# Learning labs

These six labs use the delivered SDK, CLI, tests, and public-task runner. Read the [technical report](world-engine-report.md) for the underlying concepts and [operations guide](../OPERATIONS.md) for lifecycle and export contracts. Run commands from the repository root after `uv sync --extra dev`. None requires paid model calls. Use a separate database from the running API.

Verification on 2026-10-10 executed every embedded Python experiment against the final core. Denied overpayment preserved state, fixture corruption returned zero reward, and paired reference/incomplete-policy runs, replay, and split-aware exports behaved as described. Exact final counts appear below. Scenario identity includes implementation fingerprints, while split membership uses stable environment-family/seed lineage so a grader repair does not move a related task between training and holdout. The selected exploit and curation regression tests also passed.

The final twenty paired seeds produced reference 20/20 and incomplete policy 0/20, with twenty successful replays. The reference source contained fourteen train, four validation, and two test episodes. SFT selected 46 tool decisions and excluded all six held-out episodes. DPO and grouped selection each produced fourteen comparable scenarios; grouped records were `trainable: false` and `policy_consistent: false` as expected.

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

**Worked answer.** The logical tick advances for an action, so the whole snapshot changes even for inspection. The grader averages satisfied checks when no safety violation exists. An untouched eligible refund can preserve unrelated records and approval constraints while failing payment conservation and resolution. Seed 42 gives reward 0.6 and `passed: false` in this version. `finish` terminates the attempt; trusted grading, not the stop action, certifies success. A positive shaped reward is not a passing workflow.

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
from world_engine.models import RunConfig
from world_engine.rollout import RunManager
from world_engine.store import Store

async def main():
    manager = RunManager(Store(".world-engine/labs.sqlite3"))
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

For group rewards `[1, 1, 1, 1]`, the mean is 1 and standard deviation is 0. With epsilon stabilization, each normalized reward advantage is zero. There is no relative reward direction for the update, though a separate KL term can still have an effect. The right response is to inspect task difficulty, sampling diversity, and the algorithm's handling of zero-variance groups, not fabricate preferences. For `[0, 0, 1, 1]`, population mean is 0.5 and standard deviation is 0.5, so advantages are approximately `[-1, -1, 1, 1]`. Those numbers alone do not supply the missing policy probabilities.

## 6. Measure the bottleneck and the isolation boundary

Profile scripted workloads at concurrency 1, 4, and 8, with repeated timings:

```sh
uv run python -m world_engine benchmark \
  --episodes 30 --trials 3 --output .world-engine/lab-benchmark
```

Read `benchmark.json` and `benchmark.md` in that directory. The matrix includes all three workflow worlds and both scripted policies. Repeated trials measure timing variation; success intervals use unique first-trial scenarios rather than counting the same deterministic task repeatedly as independent evidence.

Compare [the same-source schema-cache measurement](../../examples/benchmark-results/schema-cache-comparison.md) to see a measured CPU optimization with unchanged outcomes. Run `uv run python examples/io_overlap_benchmark.py` for a separate control that inserts a simulated 25-millisecond wait per decision. Its concurrency gains demonstrate awaited I/O overlap, not a GPU or cloud benchmark. Do not merge these regimes into a single throughput claim.

Then, only when an existing local Ollama model is available, compare the latency regime:

```sh
uv run python -m world_engine --db .world-engine/lab-local.sqlite3 rollout \
  --environment refund-ops --provider local --model qwen3:8b \
  --episodes 1 --concurrency 1 --max-steps 12 --timeout 120 --evaluation-only
```

**Questions.** Why might more concurrency fail to improve scripted throughput? Why can a fast simulator still produce slow model episodes? Can a single local-model attempt estimate general capability?

**Worked answer.** These small workflows are synchronous Python transitions with hashing and SQLite persistence. Cooperative scheduling is not additional CPU execution capacity, and higher concurrency can add overhead. A model episode waits on repeated inference calls, so model capacity and context length can dominate environment cost. One attempt is a functional integration sample, not a reliable capability estimate or controlled policy comparison. Count provider failures separately from attempted task failures.

Finally inspect the public task's distinct trust boundary:

```sh
python3 scripts/public-benchmark.py --skip-local
python3 -m unittest discover -s tests -p test_public_benchmark.py
```

Docker image builds need network access and local storage; task execution and grading have container networking disabled. The public task runner is separate from the synthetic-workflow training exporter. Review [the exact protocol](../public-benchmark.md) and the manifest rather than inferring safety from the word Docker.

**Questions.** Which principal can see the grader? Which data crosses from the agent to the verifier? What would violate the protocol?

**Worked answer.** The trusted controller mounts the official tests only in a fresh verifier after removing the agent container. Only a bounded regular CSV artifact crosses the boundary. The agent runs nonroot with read-only root filesystem, no network, no host repository or Docker socket, and a narrow writable output mount. Mounting the repository, grader, or socket into the agent; accepting a symlink artifact; or grading while a writer remains active would undermine the intended boundary. Containers still share a host kernel, and this is a disclosed single-task adaptation, not the full Terminal-Bench leaderboard protocol. Keep its canary, license, and evaluation-only exclusion intact.
