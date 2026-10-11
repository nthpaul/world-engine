"""Run a synthetic Docker task or bounded local container-lifecycle benchmark."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import platform
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from world_engine.docker_executor import DockerExecutor, Limits, TaskSpec

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATHS = ["src/world_engine/docker_executor.py", "tests/test_docker_executor.py",
                "examples/docker_executor.py", "docs/docker-executor.md"]


def source_receipt():
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=2)
    status = subprocess.run(["git", "status", "--porcelain", "--", *SOURCE_PATHS], cwd=ROOT, capture_output=True, text=True, timeout=2)
    overall = subprocess.run(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=ROOT, capture_output=True, text=True, timeout=2)
    return {"git_revision": revision.stdout.strip() if revision.returncode == 0 else None,
            "source_dirty": bool(status.stdout.strip()) if status.returncode == 0 else None,
            "source_paths": SOURCE_PATHS, "checkout_dirty": bool(overall.stdout.strip()) if overall.returncode == 0 else None,
            "source_sha256": {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in SOURCE_PATHS}}


async def one_episode(executor: DockerExecutor, image: str, seed: int):
    started = time.monotonic()
    numbers = [seed + 1, seed + 2, seed + 4]
    public_input = "\n".join(map(str, numbers)).encode() + b"\n"
    specification = TaskSpec("synthetic-number-sum", "1.0.0", image, {"numbers.txt": public_input}, ("answer.txt",))
    async with executor.session(specification) as session:
        name, volume = session.name, session.volume
        command = "python -c 'from pathlib import Path; print(sum(map(int,Path(\"numbers.txt\").read_text().split())))' > answer.txt"
        result = await session.execute(command)
        if result.exit_code or result.limit_reason:
            raise RuntimeError("synthetic reference command did not complete")
        artifacts = await session.finish()
    # The executor has removed both containers and the volume before this trusted check.
    expected = str(sum(numbers)).encode() + b"\n"
    return {"seed": seed, "task_id": specification.task_id, "task_version": specification.version,
            "public_input_sha256": hashlib.sha256(public_input).hexdigest(), "passed": artifacts.files["answer.txt"] == expected,
            "artifact_sha256": dict(artifacts.hashes), "elapsed_seconds": time.monotonic() - started,
            "command": command, "command_result": result.__dict__, "runtime": artifacts.runtime_receipt,
            "container_name": name, "workspace_volume": volume, "graded_after_destruction": session.state == "closed",
            "evaluation_only": True, "training_eligible": False}


async def trial(image: str, episodes: int, concurrency: int, limits: Limits):
    start = time.monotonic()
    records = []
    async with DockerExecutor(allowed_images={image}, max_sessions=concurrency, limits=limits) as executor:
        seeds = iter(range(episodes))

        async def worker():
            while (seed := next(seeds, None)) is not None:
                records.append(await one_episode(executor, image, seed))

        await asyncio.gather(*(worker() for _ in range(concurrency)))
        cleanup = {}
        for key, command in {"containers": ["ps", "--all", "--filter", f"label=world-engine.executor-owner={executor.owner}", "--format", "{{.Names}}"],
                             "volumes": ["volume", "ls", "--filter", f"label=world-engine.executor-owner={executor.owner}", "--format", "{{.Name}}"]}.items():
            result = await executor.command(command, timeout=10, output_limit=4096)
            if result.code or result.limit:
                raise RuntimeError("cannot verify Docker cleanup")
            cleanup[key] = result.stdout.decode().splitlines()
            if cleanup[key]:
                raise RuntimeError("owned Docker resources remain after trial")
    elapsed = time.monotonic() - start
    durations = sorted(record["elapsed_seconds"] for record in records)
    return {"concurrency": concurrency, "episodes": episodes, "passed": sum(record["passed"] for record in records),
            "elapsed_seconds": elapsed, "episodes_per_second": episodes / elapsed,
            "p50_episode_seconds": statistics.median(durations), "p95_episode_seconds": durations[math.ceil(.95 * len(durations)) - 1],
            "cleanup": cleanup, "records": sorted(records, key=lambda record: record["seed"])}


async def collect(args):
    if args.output and os.path.lexists(args.output):
        raise FileExistsError("output already exists; refusing to run Docker collection")
    source = source_receipt()
    if args.benchmark and (source["source_dirty"] is not False or not source["git_revision"]):
        raise RuntimeError("benchmark collection requires committed, clean executor source files")
    modes = (1, 2) if args.benchmark else (1,)
    episodes = args.episodes if args.benchmark else 1
    trials = args.trials if args.benchmark else 1
    limits = Limits()
    report = {"schema": "world-engine.docker-sdk-evaluation.v1", "collected_at": datetime.now(timezone.utc).isoformat(),
              "source": source, "machine": {"system": platform.system(), "release": platform.release(),
              "architecture": platform.machine(), "python": platform.python_version(), "logical_cpus": os.cpu_count()},
              "image_id": args.image, "limits": limits.__dict__, "model_calls": 0, "training_eligible": False,
              "note": "Synthetic reference commands only. Timings include Docker CLI, fresh volume/container setup, "
                      "freeze, collector, parsing, destruction and cleanup checks. This measures local lifecycle I/O, not LLM or cloud throughput.",
              "trials": []}
    for concurrency in modes:
        for index in range(trials):
            result = await trial(args.image, episodes, concurrency, limits)
            result["trial_index"] = index
            report["trials"].append(result)
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x") as output:
            output.write(encoded)
    print(encoded, end="")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="Explicit allowlisted sha256 ID of an already installed Linux image with sh, tar and Python")
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--episodes", type=int, choices=range(1, 21), default=4)
    parser.add_argument("--trials", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--output", type=Path, help="Create a new JSON receipt; existing files are never overwritten")
    asyncio.run(collect(parser.parse_args()))


if __name__ == "__main__":
    main()
