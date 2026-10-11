from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import uvicorn

from world_engine.api import create_app
from world_engine.benchmark import benchmark
from world_engine.environments import ENVIRONMENTS
from world_engine.exports import export_records, jsonl
from world_engine.models import RunConfig, canonical_json
from world_engine.native_config import NativeRunConfig
from world_engine.rollout import RunManager, replay
from world_engine.store import Store


async def execute_run(args: argparse.Namespace) -> None:
    native = args.provider in ("local-tools", "local-tools-ledger")
    config_type = NativeRunConfig if native else RunConfig
    config = config_type(environment_id=args.environment, provider_id=args.provider, episodes=args.episodes,
                         seed=args.seed, max_steps=args.max_steps, model=args.model,
                         timeout_seconds=args.timeout, allow_paid=False if native else args.allow_paid,
                         label=args.label, evaluation_only=native or args.evaluation_only,
                         **({"concurrency": args.concurrency} if args.concurrency is not None else {}))
    manager = RunManager(Store(args.db))
    try:
        run = manager.submit(config)
        completed = await manager.wait(run["id"])
        print(canonical_json({key: value for key, value in completed.items() if key != "episodes"}))
    finally:
        await manager.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="world-engine")
    parser.add_argument("--db", default=os.environ.get("WORLD_ENGINE_DB", ".world-engine/engine.sqlite3"))
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Serve the local operator API")
    serve.add_argument("--host", choices=["127.0.0.1", "localhost", "::1"], default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    run = commands.add_parser("rollout", help="Execute and persist a bounded batch")
    run.add_argument("--environment", choices=tuple(ENVIRONMENTS), required=True)
    run.add_argument("--provider", choices=["scripted-oracle", "scripted-baseline", "local", "local-tools", "local-tools-ledger", "openai", "anthropic"], default="scripted-oracle")
    run.add_argument("--episodes", type=int, default=10)
    run.add_argument("--seed", type=int, default=42)
    run.add_argument("--concurrency", type=int, default=None,
                     help="Concurrent episodes (default: 1 for native providers, 4 otherwise)")
    run.add_argument("--max-steps", type=int, default=20)
    run.add_argument("--timeout", type=int, default=60)
    run.add_argument("--model")
    run.add_argument("--allow-paid", action="store_true")
    run.add_argument("--label", default="")
    run.add_argument("--evaluation-only", action="store_true", help="Exclude these evaluation episodes from training exports")
    bench = commands.add_parser("benchmark", help="Measure local scripted workflows; no external model calls")
    bench.add_argument("--output", type=Path,
                       default=Path(".world-engine/benchmarks") / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S.%fZ}-{uuid4().hex}",
                       help="Fresh output directory; existing paths are never reused")
    bench.add_argument("--episodes", type=int, default=30)
    bench.add_argument("--trials", type=int, default=3)
    export = commands.add_parser("export", help="Write dataset/operator-interchange JSONL to stdout")
    export.add_argument("run_id")
    export.add_argument("--format", choices=["sft", "dpo", "grpo", "traces", "atif"], default="sft",
                        help="ATIF is replay-verified operator interchange, not training-ready data")
    export.add_argument("--quality", choices=["passed", "all"], default="passed")
    verify = commands.add_parser("replay", help="Verify every stored transition and trusted final grade")
    verify.add_argument("run_id", nargs="?")
    verify.add_argument("--file", type=Path, help="Replay full episode/evaluation-wrapper JSONL without a database")
    args = parser.parse_args()
    if args.command == "serve":
        uvicorn.run(create_app(args.db), host=args.host, port=args.port, log_level="info")
    elif args.command == "rollout":
        asyncio.run(execute_run(args))
    elif args.command == "benchmark":
        asyncio.run(benchmark(args.output, args.episodes, args.trials))
    elif args.command == "export":
        records, report = export_records(Store(args.db), args.run_id, args.format, args.quality)
        print(jsonl(records), end="")
        import sys
        print(json.dumps(report), file=sys.stderr)
    else:
        if bool(args.run_id) == bool(args.file):
            parser.error("replay requires exactly one run_id or --file")
        if args.file:
            with args.file.open() as source:
                records = [json.loads(line) for line in source if line.strip()]
            episodes = [record.get("episode", record) for record in records]
        else:
            episodes = Store(args.db).episodes(args.run_id)
        if not episodes:
            parser.error("run has no stored episodes")
        print(canonical_json({"run_id": args.run_id, "verified_episodes": len(episodes),
                              "results": [replay(episode) for episode in episodes]}))


if __name__ == "__main__":
    main()
