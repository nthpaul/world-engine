from __future__ import annotations

import json
import math
import os
import platform
import statistics
import time
from pathlib import Path

from world_engine.environments import ENVIRONMENTS
from world_engine.models import RunConfig, utc_now
from world_engine.rollout import RunManager
from world_engine.store import Store


def percentile(values: list[float], percent: float) -> float:
    values = sorted(values)
    return values[min(len(values) - 1, math.ceil(percent * len(values)) - 1)] if values else 0.0


def wilson(passed: int, total: int) -> list[float]:
    if not total:
        return [0.0, 1.0]
    z = 1.96
    proportion = passed / total
    denominator = 1 + z * z / total
    middle = (proportion + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total)) / denominator
    return [max(0, middle - margin), min(1, middle + margin)]


async def benchmark(output: Path, episodes: int = 30, trials: int = 3, *, schema_cache_mode: str = "enabled") -> dict:
    if not 1 <= episodes <= 100 or not 1 <= trials <= 10:
        raise ValueError("benchmark supports 1..100 episodes and 1..10 trials")
    output.mkdir(parents=True, exist_ok=True)
    manager = RunManager(Store(output / "benchmark.sqlite3"))
    rows = []
    raw = []
    try:
        for environment_id in ENVIRONMENTS:
            for provider_id in ("scripted-oracle", "scripted-baseline"):
                for concurrency in (1, 4, 8):
                    measurements = []
                    for trial in range(trials):
                        config = RunConfig(environment_id=environment_id, provider_id=provider_id, episodes=episodes,
                                           seed=42, concurrency=concurrency, label=f"benchmark trial {trial + 1}", evaluation_only=True)
                        started = time.perf_counter()
                        run = manager.submit(config)
                        result = await manager.wait(run["id"])
                        wall = time.perf_counter() - started
                        episodes_data = result["episodes"]
                        measurement = {"run_id": run["id"], "trial": trial + 1, "environment_id": environment_id,
                                       "provider_id": provider_id, "concurrency": concurrency, "wall_seconds": wall,
                                       "episodes_per_second": episodes / wall,
                                       "steps_per_second": sum(episode["steps"] for episode in episodes_data) / wall,
                                       "passed": sum(episode["passed"] for episode in episodes_data), "count": len(episodes_data),
                                       "invalid_actions": sum(episode["invalid_actions"] for episode in episodes_data),
                                       "errors": sum(episode["error"] is not None for episode in episodes_data),
                                       "cancelled": sum(episode["status"] == "cancelled" for episode in episodes_data),
                                       "episode_durations": [episode["elapsed_seconds"] for episode in episodes_data],
                                       "scenario_ids": [episode["scenario_id"] for episode in episodes_data]}
                        measurement["implementation"] = {key: episodes_data[0]["provenance"][key] for key in ("environment_code_hash", "grader_code_hash", "policy_code_hash", "runtime", "git_revision", "git_dirty")}
                        measurements.append(measurement)
                        raw.append(measurement)
                    durations = [duration for measurement in measurements for duration in measurement["episode_durations"]]
                    passed = sum(measurement["passed"] for measurement in measurements)
                    count = sum(measurement["count"] for measurement in measurements)
                    rows.append({"environment_id": environment_id, "provider_id": provider_id, "concurrency": concurrency,
                                 "trials": trials, "episodes": count, "passed": passed, "success_rate": passed / count,
                                 "pass_rate_wilson_95": wilson(passed, count),
                                 "independent_scenarios": measurements[0]["count"],
                                 "median_episodes_per_second": statistics.median(measurement["episodes_per_second"] for measurement in measurements),
                                 "median_steps_per_second": statistics.median(measurement["steps_per_second"] for measurement in measurements),
                                 "p50_episode_seconds": percentile(durations, .50), "p95_episode_seconds": percentile(durations, .95),
                                 "invalid_actions": sum(measurement["invalid_actions"] for measurement in measurements),
                                 "errors": sum(measurement["errors"] for measurement in measurements),
                                 "cancel_rate": sum(measurement["cancelled"] for measurement in measurements) / count})
                    rows[-1]["pass_rate_wilson_95"] = wilson(measurements[0]["passed"], measurements[0]["count"])
    finally:
        await manager.close()
    result = {"schema": "world-engine.benchmark.v1", "created_at": utc_now(), "runtime": platform.python_version(),
              "platform": platform.platform(), "machine": platform.machine(), "execution": "in-process scripted local CPU",
              "cpu_count": os.cpu_count(), "schema_cache_mode": schema_cache_mode,
              "global_concurrency_limit": 8, "measurement": "End-to-end batch scheduling, trusted grading, JSON hashing and SQLite persistence; no model latency.",
              "limitations": "Repeated seeds are paired deterministic cases, not independent task samples; Wilson intervals describe case outcomes, not a new-population guarantee. Concurrency is asyncio scheduling, not CPU parallelism.",
              "rows": rows, "raw_trials": raw}
    (output / "benchmark.json").write_text(json.dumps(result, indent=2) + "\n")
    lines = ["# Local Workflow Benchmark", "", f"Measured {result['created_at']} on {result['platform']}, Python {result['runtime']}.", "",
             result["measurement"], "", result["limitations"], "",
             "| World | Policy | Concurrency | Passed | Episodes/s | Steps/s | p50 ms | p95 ms | Invalid | Errors |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in rows:
        lines.append(f"| {row['environment_id']} | {row['provider_id']} | {row['concurrency']} | {row['passed']}/{row['episodes']} | {row['median_episodes_per_second']:.1f} | {row['median_steps_per_second']:.1f} | {row['p50_episode_seconds']*1000:.1f} | {row['p95_episode_seconds']*1000:.1f} | {row['invalid_actions']} | {row['errors']} |")
    lines.extend(["", "Reproduce: `uv run python -m world_engine benchmark --episodes 30 --trials 3`. Raw per-trial durations and matched scenario IDs are in benchmark.json.", ""])
    (output / "benchmark.md").write_text("\n".join(lines))
    print(json.dumps({"output": str(output.resolve()), "rows": len(rows), "episodes": sum(row["episodes"] for row in rows)}))
    return result
