"""Preserve the measured pre-cache receipt and collect a matched post-cache CPU matrix."""

import asyncio
import json
from pathlib import Path

import world_engine.environments as environments
from world_engine.benchmark import benchmark


async def main():
    output = Path("examples/benchmark-results")
    historical = output / "schema-cache-historical-before.json"
    if not historical.exists() and (output / "benchmark.json").exists():
        historical.write_text((output / "benchmark.json").read_text())
    cached = environments._argument_schema
    try:
        # This standalone benchmark process bypasses only the memoization wrapper.
        environments._argument_schema = cached.__wrapped__
        before = await benchmark(output / "uncached-control", episodes=30, trials=3, schema_cache_mode="disabled-in-benchmark")
    finally:
        environments._argument_schema = cached
    (output / "schema-cache-before.json").write_text(json.dumps(before, indent=2) + "\n")
    after = await benchmark(output, episodes=30, trials=3)
    (output / "schema-cache-after.json").write_text(json.dumps(after, indent=2) + "\n")
    pairs = []
    for left, right in zip(before["rows"], after["rows"], strict=True):
        assert (left["environment_id"], left["provider_id"], left["concurrency"]) == (right["environment_id"], right["provider_id"], right["concurrency"])
        assert left["passed"] == right["passed"] and left["episodes"] == right["episodes"]
        pairs.append({"environment_id": left["environment_id"], "provider_id": left["provider_id"], "concurrency": left["concurrency"],
                      "before_episodes_per_second": left["median_episodes_per_second"], "after_episodes_per_second": right["median_episodes_per_second"],
                      "ratio": right["median_episodes_per_second"] / left["median_episodes_per_second"]})
    comparison = {"before": "schema-cache-before.json", "after": "schema-cache-after.json", "pairs": pairs,
                  "method": "Same committed implementation, 30 seeded cases, three timing trials, three worlds, two scripted policies, concurrency 1/4/8, SQLite persistence. The standalone control bypasses only the schema memoization wrapper; the after run enables it. Sequential runs on the same host; background load is uncontrolled. This compares tool-schema caching within this engine, not model or competitor performance."}
    for left, right in zip(before["raw_trials"], after["raw_trials"], strict=True):
        assert left["scenario_ids"] == right["scenario_ids"]
        assert left["implementation"] == right["implementation"]
    (output / "schema-cache-comparison.json").write_text(json.dumps(comparison, indent=2) + "\n")
    lines = ["# Tool Schema Cache Measurement", "", comparison["method"], "",
             "| World | Policy | Concurrency | Before episodes/s | After episodes/s | Ratio |", "|---|---|---:|---:|---:|---:|"]
    for pair in pairs:
        lines.append(f"| {pair['environment_id']} | {pair['provider_id']} | {pair['concurrency']} | {pair['before_episodes_per_second']:.1f} | {pair['after_episodes_per_second']:.1f} | {pair['ratio']:.2f}x |")
    lines.extend(["", "Raw timing trials and exact environment/grader/policy/runtime fingerprints are in schema-cache-before.json and schema-cache-after.json. Both runs preserve all outcome counts. Async concurrency is not CPU parallelism.", ""])
    (output / "schema-cache-comparison.md").write_text("\n".join(lines))


if __name__ == "__main__":
    asyncio.run(main())
