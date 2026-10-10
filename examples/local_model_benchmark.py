"""Evaluate an already-installed local model. Never downloads models or uses paid endpoints."""

import argparse
import asyncio
import json
import platform
from pathlib import Path

from world_engine.environments import ENVIRONMENTS
from world_engine.models import RunConfig, utc_now
from world_engine.rollout import RunManager, replay
from world_engine.store import Store


async def main(output: Path, episodes: int, seed: int):
    output.mkdir(parents=True, exist_ok=True)
    manager = RunManager(Store(output / "local-model.sqlite3"))
    rows = []
    evaluation_traces = []
    try:
        for environment_id in ENVIRONMENTS:
            for provider_id in ("scripted-oracle", "scripted-baseline", "local"):
                config = RunConfig(environment_id=environment_id, provider_id=provider_id,
                                   episodes=episodes, seed=seed, concurrency=1, max_steps=20,
                                   timeout_seconds=120, model="qwen3:8b" if provider_id == "local" else None,
                                   label="paired local model evaluation", evaluation_only=True)
                run = manager.submit(config)
                result = await manager.wait(run["id"])
                records = []
                for episode in result["episodes"]:
                    verified = replay(episode)["verified"]
                    evaluation_traces.append({"schema": "world-engine.evaluation-trace.v1", "evaluation_only": True,
                                              "training_eligible": False, "episode": episode})
                    records.append({key: episode[key] for key in (
                        "id", "seed", "scenario_id", "provenance", "status", "termination", "reward", "passed", "steps",
                        "elapsed_seconds", "invalid_actions", "error", "usage", "split", "final_state_hash")})
                    records[-1]["replay_verified"] = verified
                    records[-1]["actions"] = [{"action": step["action"], "result": step["result"], "elapsed_ms": step["elapsed_ms"], "usage": step["usage"]} for step in episode["trace"]]
                row = {"environment_id": environment_id, "provider_id": provider_id, "run_id": run["id"],
                       "status": result["status"], "passed": result["passed_episodes"], "count": result["completed_episodes"],
                       "success_rate": result["success_rate"], "elapsed_seconds": result["elapsed_seconds"], "error": result["error"], "episodes": records}
                rows.append(row)
                print(json.dumps({key: row[key] for key in ("environment_id", "provider_id", "status", "passed", "count", "elapsed_seconds", "error")}), flush=True)
    finally:
        await manager.close()
    result = {"created_at": utc_now(), "platform": platform.platform(), "python": platform.python_version(),
              "model": "qwen3:8b", "model_downloaded": False, "paid_calls": 0, "seed": seed,
              "evaluation_only": True, "max_steps": 20, "episode_timeout_seconds": 120,
              "limitations": "Tiny paired local evaluation, not a population estimate or comparison with hosted systems. Tool replay is deterministic; model inference may not be bitwise deterministic.", "rows": rows}
    result["collection_revision"] = rows[0]["episodes"][0]["provenance"]["git_revision"]
    result["collection_dirty"] = rows[0]["episodes"][0]["provenance"]["git_dirty"]
    (output / "local-model.json").write_text(json.dumps(result, indent=2) + "\n")
    (output / "local-model-traces.jsonl").write_text("".join(json.dumps(record, separators=(",", ":")) + "\n" for record in evaluation_traces))
    lines = ["# Paired Local Model Evaluation", "", f"Measured {result['created_at']} on {result['platform']}, Python {result['python']}.", "",
             "Already-installed Ollama qwen3:8b; no downloads or paid calls. Temperature 0, thinking disabled, 512 output-token bound per decision, 20 decisions and 120 seconds per episode.", "", result["limitations"], "",
             "| World | Provider | Passes | Wall seconds | Invalid actions | Input tokens | Output tokens |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for row in rows:
        lines.append(f"| {row['environment_id']} | {row['provider_id']} | {row['passed']}/{row['count']} | {row['elapsed_seconds']:.2f} | {sum(e['invalid_actions'] for e in row['episodes'])} | {sum(e['usage']['input_tokens'] for e in row['episodes'])} | {sum(e['usage']['output_tokens'] for e in row['episodes'])} |")
    lines.extend(["", "Full model digest, actions, safe errors, matched scenario IDs, observed token counts and replay evidence are in local-model.json. Full synthetic operator episodes are in local-model-traces.jsonl, explicitly evaluation_only=true and training_eligible=false; these are not training exports.", "",
                  f"Collection Git revision: `{result['collection_revision']}`. Overall checkout dirty: `{result['collection_dirty']}`; implementation status and scope are recorded in each episode's provenance.", "",
                  "Replay delivered traces: `uv run python -m world_engine replay --file examples/benchmark-results/local-model-traces.jsonl`.", "",
                  f"Reproduce: `uv run python examples/local_model_benchmark.py --episodes {episodes} --seed {seed}`.", ""])
    (output / "local-model.md").write_text("\n".join(lines))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("examples/benchmark-results"))
    parser.add_argument("--episodes", type=int, choices=[1, 2, 3], default=1)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    asyncio.run(main(args.output, args.episodes, args.seed))
