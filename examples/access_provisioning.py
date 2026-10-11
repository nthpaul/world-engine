"""Collect free scripted controls for the synthetic access workflow after source commit."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from world_engine.models import RunConfig
from world_engine.rollout import replay, rollout

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("src/world_engine/access_provisioning.py", "src/world_engine/environments.py", "src/world_engine/providers.py",
           "tests/test_access_provisioning.py", "examples/access_provisioning.py", "docs/access-provisioning.md")
SOURCE_SCOPE = ("src/world_engine", "pyproject.toml", "uv.lock", *SOURCES[3:])
MAX_EPISODE_BYTES = 1024 * 1024
MAX_RECEIPT_BYTES = 16 * 1024 * 1024


def source_receipt(expected_revision: str):
    if not isinstance(expected_revision, str) or not re.fullmatch(r"[0-9a-f]{40}", expected_revision):
        raise ValueError("source revision must be a full reviewed Git commit ID")
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=2)
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=normal", "--", *SOURCE_SCOPE], cwd=ROOT,
                            capture_output=True, text=True, timeout=2)
    if revision.returncode or status.returncode or status.stdout.strip():
        raise RuntimeError("scripted collection requires a committed, clean complete runtime and owned collector files")
    if revision.stdout.strip() != expected_revision:
        raise RuntimeError("current source differs from the explicitly reviewed revision")
    overall = subprocess.run(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=ROOT,
                             capture_output=True, text=True, timeout=2)
    files = sorted({str(path.relative_to(ROOT)) for path in (ROOT / "src/world_engine").rglob("*.py")} | set(SOURCES[3:]) | {"pyproject.toml", "uv.lock"})
    return {"git_revision": revision.stdout.strip(), "source_dirty": False,
            "source_scope": SOURCE_SCOPE, "checkout_dirty": bool(overall.stdout.strip()) if not overall.returncode else None,
            "source_sha256": {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in files}}


async def collect(args):
    if not isinstance(args.output, Path):
        raise ValueError("a fresh receipt output path is required")
    if os.path.lexists(args.output):
        raise FileExistsError("output exists; refusing to collect")
    if type(args.cycles) is not int or not 1 <= args.cycles <= 4:
        raise ValueError("cycles must be an integer between one and four")
    source = source_receipt(args.source_revision)
    episodes = []
    recorded_bytes = 0
    for provider in ("scripted-oracle", "scripted-baseline"):
        for seed in range(args.cycles * 8):
            episode = await rollout(RunConfig(environment_id="access-provisioning", provider_id=provider, episodes=1,
                                              seed=seed, max_steps=20, timeout_seconds=30, concurrency=1, evaluation_only=True), 0)
            replay(episode)
            size = len(json.dumps(episode, sort_keys=True).encode())
            if size > MAX_EPISODE_BYTES or recorded_bytes + size > MAX_RECEIPT_BYTES - 64 * 1024:
                raise RuntimeError("scripted operator receipt exceeded its conservative byte budget; no output written")
            recorded_bytes += size
            episodes.append(episode)
    report = {"schema": "world-engine.access-controls.v1", "collected_at": datetime.now(timezone.utc).isoformat(),
              "source": source, "runtime": platform.python_version(), "evaluation_only": True, "training_eligible": False,
              "model_calls": 0, "outcome_control_only": True,
              "protocol": {"seeds": list(range(args.cycles * 8)), "providers": ["scripted-oracle", "scripted-baseline"],
                           "max_steps": 20, "timeout_seconds": 30, "concurrency": 1, "evaluation_only": True,
                           "max_episodes": 64, "max_episode_bytes": MAX_EPISODE_BYTES, "max_receipt_bytes": MAX_RECEIPT_BYTES},
              "note": "Synthetic scripted outcome controls; full operator snapshots are not training prompts. Not SCIM compliance or a model study.",
              "episodes": episodes, "summary": {provider: {"episodes": sum(row["provenance"]["provider_id"] == provider for row in episodes),
              "passed": sum(row["passed"] for row in episodes if row["provenance"]["provider_id"] == provider)}
              for provider in ("scripted-oracle", "scripted-baseline")}}
    encoded = json.dumps(report, sort_keys=True) + "\n"
    if len(encoded.encode()) > MAX_RECEIPT_BYTES:
        raise RuntimeError("scripted operator receipt exceeded its byte budget; no output written")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as target:
        target.write(encoded)
    print(json.dumps({"path": str(args.output.resolve()), "summary": report["summary"], "outcome_control_only": True}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, choices=range(1, 5), default=1)
    parser.add_argument("--source-revision", required=True, help="Full explicitly reviewed Git commit ID; runtime and collector must be clean")
    parser.add_argument("--output", type=Path, required=True, help="Fresh operator receipt path; full episode bodies are never printed")
    asyncio.run(collect(parser.parse_args()))


if __name__ == "__main__":
    main()
