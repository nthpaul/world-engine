"""Create paired demonstrations and preferences on train scenarios using free scripted policies."""

import asyncio
import json
from pathlib import Path

from world_engine.exports import export_records, jsonl
from world_engine.models import RunConfig
from world_engine.rollout import RunManager, replay
from world_engine.store import Store


async def main():
    output = Path("examples/datasets")
    output.mkdir(parents=True, exist_ok=True)
    manager = RunManager(Store(output / "demonstrations.sqlite3"))
    manifest = {"training_split": "train", "worlds": [], "note": "GRPO files contain raw grouped candidates, trainable=false. DPO trajectory messages require a trainer adapter."}
    try:
        for environment_id in ("crm-merge", "refund-ops", "incident-control"):
            runs = {}
            for provider_id in ("scripted-oracle", "scripted-baseline"):
                run = manager.submit(RunConfig(environment_id=environment_id, provider_id=provider_id, episodes=6, seed=42))
                result = await manager.wait(run["id"])
                assert all(replay(episode)["verified"] for episode in result["episodes"])
                runs[provider_id] = run["id"]
            reports = {}
            for format in ("sft", "dpo", "grpo"):
                records, report = export_records(manager.store, runs["scripted-oracle"], format)
                (output / f"{environment_id}-{format}.jsonl").write_text(jsonl(records))
                reports[format] = report
            manifest["worlds"].append({"environment_id": environment_id, "runs": runs, "exports": reports})
    finally:
        await manager.close()
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
