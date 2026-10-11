"""Controlled simulated provider latency, explicitly separate from real model inference."""

import argparse
import asyncio
import json
import statistics
from pathlib import Path

from world_engine.models import RunConfig, utc_now
from world_engine.providers import ScriptedProvider
from world_engine.rollout import RunManager
from world_engine.store import Store


class LatencyOracle:
    model = "scripted-oracle-plus-simulated-25ms-io"

    def __init__(self):
        self.oracle = ScriptedProvider()
        self.active = self.maximum = 0

    async def decide(self, observation, history):
        self.active += 1
        self.maximum = max(self.maximum, self.active)
        try:
            await asyncio.sleep(.025)
            return await self.oracle.decide(observation, history)
        finally:
            self.active -= 1


async def main(output: Path):
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    manager = RunManager(Store(output / "io-overlap.sqlite3"))
    rows = []
    try:
        for concurrency in (1, 4, 8):
            trials = []
            for trial in range(3):
                provider = LatencyOracle()
                run = manager.submit(RunConfig(environment_id="crm-merge", episodes=24, seed=42,
                                               concurrency=concurrency, evaluation_only=True), provider)
                result = await manager.wait(run["id"])
                assert result["passed_episodes"] == 24
                trials.append({"trial": trial + 1, "run_id": run["id"], "wall_seconds": result["elapsed_seconds"],
                               "episodes_per_second": 24 / result["elapsed_seconds"], "maximum_inflight_decisions": provider.maximum,
                               "steps": sum(episode["steps"] for episode in result["episodes"]),
                               "provenance": result["episodes"][0]["provenance"]})
            rows.append({"concurrency": concurrency, "median_episodes_per_second": statistics.median(trial["episodes_per_second"] for trial in trials),
                         "passed": 72, "episodes": 72, "trials": trials})
    finally:
        await manager.close()
    report = {"created_at": utc_now(), "simulated_io_latency_ms": 25, "world": "crm-merge", "global_concurrency_cap": 8,
              "interpretation": "Awaiting 25ms per decision proves I/O overlap in the scheduler. This is explicitly simulated latency, not measured LLM/cloud throughput or CPU parallelism.", "rows": rows}
    with (output / "io-overlap.json").open("x") as target:
        target.write(json.dumps(report, indent=2) + "\n")
    lines = ["# Simulated Provider I/O Overlap", "", report["interpretation"], "",
             "24 matched CRM episodes per trial, three timing trials, six decisions per episode. Every decision waits 25ms before the real scripted oracle and trusted workflow transition.", "",
             "| Concurrency | Median episodes/s | Peak in-flight decisions | Passes |", "|---:|---:|---:|---:|"]
    for row in rows:
        lines.append(f"| {row['concurrency']} | {row['median_episodes_per_second']:.2f} | {max(trial['maximum_inflight_decisions'] for trial in row['trials'])} | {row['passed']}/{row['episodes']} |")
    lines.extend(["", "Reproduce: `uv run python examples/io_overlap_benchmark.py --output <fresh-directory>`. Full per-trial timings and frozen provenance are in io-overlap.json.", ""])
    with (output / "io-overlap.md").open("x") as target:
        target.write("\n".join(lines))
    print(json.dumps({"rows": len(rows), "passed": sum(row["passed"] for row in rows)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Fresh evidence directory; existing paths are refused")
    args = parser.parse_args()
    asyncio.run(main(args.output))
