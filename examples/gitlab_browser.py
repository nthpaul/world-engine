"""Run one local GitLab browser attempt through the Python SDK."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
from pathlib import Path

from world_engine.browser_contracts import BrowserAttemptConfig
from world_engine.browser_driver import BrowserGymDriver
from world_engine.browser_policy import create_browser_policy
from world_engine.browser_runs import BrowserRunManager
from world_engine.browser_store import BrowserStore
from world_engine.gitlab_runtime import GitLabRuntime, gitlab_task


def source_receipt() -> dict:
    root = Path(__file__).resolve().parents[1]
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    changed = subprocess.run(["git", "diff", "--quiet", "HEAD"], cwd=root, check=False).returncode
    untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=root, text=True)
    code_roots = ("src/", "tests/", "scripts/", "examples/", "environments/", "web/src/")
    if changed or any(path.startswith(code_roots) for path in untracked.splitlines()):
        raise RuntimeError("collection requires committed, unchanged source")
    return {"git_revision": revision, "tracked_source_unchanged": True,
            "untracked_non_source_paths": untracked.splitlines()}


async def collect(args: argparse.Namespace) -> dict:
    output = args.output.absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError("refusing to replace existing attempt evidence")
    config = BrowserAttemptConfig(task_id="gitlab-issue-close", provider_id=args.provider,
                                  model=args.model, seed=args.seed, max_steps=args.max_steps,
                                  timeout_seconds=args.timeout)
    task = gitlab_task(config.seed)
    protocol = {"schema": "world-engine.gitlab-sdk-protocol.v1", "config": config.model_dump(),
                "task": task.model_dump(), "paid_resources": False, "automatic_retries": 0,
                "interaction_timeout_excludes_startup_and_finalization": True}
    if args.plan:
        return protocol
    source = source_receipt()
    manager = BrowserRunManager(BrowserStore(output), {task.id: task}, GitLabRuntime(),
                                BrowserGymDriver, create_browser_policy, gitlab_task)
    try:
        with (output / "protocol.json").open("x") as stream:
            json.dump({**protocol, "source": source}, stream, indent=2, sort_keys=True)
        attempt = manager.submit(config)
        result = await manager.wait(attempt["id"])
        receipt = {"schema": "world-engine.gitlab-sdk-receipt.v1", "source": source,
                   "protocol_sha256": hashlib.sha256((output / "protocol.json").read_bytes()).hexdigest(),
                   "attempt_id": result["id"], "status": result["status"], "termination": result["termination"],
                   "passed": result["passed"], "outcome": result["outcome"], "cleanup": result["cleanup"],
                   "steps": result["steps"], "elapsed_seconds": result["elapsed_seconds"]}
        with (output / "receipt.json").open("x") as stream:
            json.dump(receipt, stream, indent=2, sort_keys=True)
        return receipt
    finally:
        await manager.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--provider", choices=["local-browser", "browser-reference", "browser-baseline"],
                        default="local-browser")
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-steps", type=int, default=30)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--plan", action="store_true", help="Print the contract without creating resources or contacting a model")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(collect(args)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
