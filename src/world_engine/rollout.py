from __future__ import annotations

import asyncio
import fcntl
import hashlib
import inspect
import platform
import subprocess
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from world_engine.environments import make_environment
from world_engine.models import JsonObject, RunConfig, digest, utc_now
from world_engine.providers import SYSTEM_PROMPT, Provider, ProviderError, make_provider, policy_messages
from world_engine.store import Store

GRADER_VERSION = "1.0.0"
POLICY_VERSION = "workflow-json-v1"
MAX_GLOBAL_EPISODES = 8
MAX_ACTIVE_RUNS = 32
ENVIRONMENT_CODE_HASH = hashlib.sha256(Path(__file__).with_name("environments.py").read_bytes()).hexdigest()
GRADER_CODE_HASH = digest({"environments": ENVIRONMENT_CODE_HASH,
                          "models": hashlib.sha256(Path(__file__).with_name("models.py").read_bytes()).hexdigest()})
POLICY_CODE_HASH = hashlib.sha256(Path(__file__).with_name("providers.py").read_bytes()).hexdigest()


def scenario_split(scenario_id: str) -> str:
    bucket = int(scenario_id[:8], 16) % 10
    return "train" if bucket < 8 else "validation" if bucket == 8 else "test"


@lru_cache(maxsize=128)
def source_fingerprint(cls: type) -> str:
    try:
        return hashlib.sha256(inspect.getsource(cls).encode()).hexdigest()
    except (OSError, TypeError):
        return digest(f"{cls.__module__}.{cls.__qualname__}")


def world_fingerprints(world) -> tuple[str, str]:
    module = inspect.getmodule(type(world))
    path = getattr(module, "__file__", None)
    module_hash = hashlib.sha256(Path(path).read_bytes()).hexdigest() if path and Path(path).is_file() else source_fingerprint(type(world))
    environment_hash = digest({"core_module": ENVIRONMENT_CODE_HASH, "world_module": module_hash,
                               "class": source_fingerprint(type(world))})
    return environment_hash, digest({"core": GRADER_CODE_HASH, "world": environment_hash})


@lru_cache(maxsize=1)
def collection_revision() -> JsonObject:
    directory = Path(__file__).resolve().parents[2]
    try:
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=directory, capture_output=True, text=True, timeout=2)
        status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=directory, capture_output=True, text=True, timeout=2)
        implementation = subprocess.run(["git", "status", "--porcelain", "--untracked-files=normal", "--", "src/world_engine", "pyproject.toml", "uv.lock"], cwd=directory, capture_output=True, text=True, timeout=2)
        return {"git_revision": revision.stdout.strip() if revision.returncode == 0 else None,
                "git_dirty": bool(status.stdout.strip()) if status.returncode == 0 else None,
                "git_dirty_scope": "entire checkout including docs and generated artifacts",
                "implementation_dirty": bool(implementation.stdout.strip()) if implementation.returncode == 0 else None,
                "implementation_dirty_scope": ["src/world_engine", "pyproject.toml", "uv.lock"]}
    except (OSError, subprocess.TimeoutExpired):
        return {"git_revision": None, "git_dirty": None, "implementation_dirty": None}


async def rollout(config: RunConfig, index: int, provider: Provider | None = None) -> JsonObject:
    owns_provider = provider is None
    provider = provider or make_provider(config)
    if owns_provider and hasattr(provider, "prepare"):
        try:
            await provider.prepare()
        except BaseException:
            if hasattr(provider, "close"):
                await provider.close()
            raise
    seed = config.seed + index
    world = make_environment(config.environment_id, seed)
    initial_observation = world.observe()
    initial_snapshot = world.snapshot()
    environment_code_hash, grader_code_hash = world_fingerprints(world)
    lineage_id = digest({"environment_family": world.id, "seed": seed})
    task_hash = digest({"task": initial_observation["task"], "tools": initial_observation["tools"]})
    scenario_id = digest({"environment": world.id, "version": world.version, "grader_version": GRADER_VERSION,
                          "environment_code_hash": environment_code_hash, "grader_code_hash": grader_code_hash,
                          "seed": seed, "initial_state_hash": digest(initial_snapshot), "task_hash": task_hash})
    provenance = {
        **collection_revision(),
        "schema_version": "1.0.0", "environment_id": world.id, "environment_version": world.version,
        "grader_version": GRADER_VERSION, "task_hash": task_hash, "policy_version": POLICY_VERSION,
        "seed": seed, "scenario_id": scenario_id, "prompt_hash": digest(policy_messages(initial_observation, [])),
        "environment_code_hash": environment_code_hash, "grader_code_hash": grader_code_hash, "lineage_id": lineage_id,
        "policy_code_hash": POLICY_CODE_HASH, "system_prompt_hash": digest(SYSTEM_PROMPT),
        "runtime": platform.python_version(), "model_digest": getattr(provider, "model_digest", None),
        "evaluation_only": config.evaluation_only,
        "policy_identity": "local-catalog-digest" if getattr(provider, "model_digest", None) else "configuration-only; weights unverified",
        "initial_state_hash": digest(initial_snapshot), "provider_id": config.provider_id,
        "model": getattr(provider, "model", config.provider_id),
        "policy_hash": digest({"provider": config.provider_id, "model": getattr(provider, "model", config.provider_id), "prompt_version": POLICY_VERSION, "temperature": 0}),
    }
    provider_class = type(provider)
    provider_identity = f"{provider_class.__module__}.{provider_class.__qualname__}"
    provider_source_hash = source_fingerprint(provider_class)
    provenance["provider_class"] = provider_identity
    provenance["provider_source_hash"] = provider_source_hash
    if provider_class.__module__ != "world_engine.providers":
        provenance["provider_id"] = "custom"
        provenance["model"] = getattr(provider, "model", provider_identity)
    provenance["policy_hash"] = digest({"provider_id": provenance["provider_id"], "provider_class": provider_identity,
                                        "provider_source_hash": provider_source_hash, "model": provenance["model"],
                                        "model_digest": provenance["model_digest"], "policy_code_hash": POLICY_CODE_HASH,
                                        "system_prompt_hash": provenance["system_prompt_hash"], "temperature": 0})
    trace: list[JsonObject] = []
    started = time.perf_counter()
    status, error, termination = "completed", None, "max_steps"
    try:
        async with asyncio.timeout(config.timeout_seconds):
            for step_index in range(config.max_steps):
                step_started = time.perf_counter()
                context = policy_messages(world.observe(), trace)
                decision = await provider.decide(world.observe(), trace)
                transition = world.step(decision.action)
                trace.append({"index": step_index, "action": decision.action.model_dump(),
                              "observation": transition["observation"], "result": transition["result"],
                              "state_hash": transition["state_hash"],
                              "elapsed_ms": (time.perf_counter() - step_started) * 1000,
                              "usage": decision.usage, "policy_input": context})
                if transition["done"]:
                    termination = "finished"
                    break
    except asyncio.CancelledError:
        status, termination, error = "cancelled", "cancelled", "episode cancelled"
    except TimeoutError:
        status, termination, error = "failed", "timeout", "episode exceeded its wall-clock timeout"
    except ProviderError as provider_error:
        status, termination, error = "failed", "provider_error", str(provider_error)
    except Exception as unexpected:
        status, termination, error = "failed", "internal_error", f"episode failed ({type(unexpected).__name__}); details redacted"
    finally:
        if owns_provider and hasattr(provider, "close"):
            await provider.close()
    evaluation = world.evaluate().model_dump()
    passed = evaluation["passed"] and status == "completed" and termination == "finished"
    reward = evaluation["reward"] if status == "completed" and termination == "finished" else 0.0
    return {
        "id": str(uuid.uuid4()), "index": index, "seed": seed, "status": status,
        "reward": reward, "passed": passed, "steps": len(trace),
        "elapsed_seconds": time.perf_counter() - started, "error": error,
        "termination": termination, "grader": evaluation, "initial_observation": initial_observation,
        "final_observation": world.observe(), "trace": trace, "initial_snapshot": initial_snapshot,
        "final_snapshot": world.snapshot(), "final_state_hash": world.state_hash(),
        "scenario_id": scenario_id, "lineage_id": lineage_id, "split": scenario_split(lineage_id), "provenance": provenance,
        "created_at": utc_now(), "invalid_actions": sum(not step["result"]["ok"] for step in trace),
        "usage": {"input_tokens": sum(step["usage"].get("input_tokens", 0) for step in trace),
                  "output_tokens": sum(step["usage"].get("output_tokens", 0) for step in trace)},
    }


@dataclass
class Job:
    task: asyncio.Task[None]
    shutdown: bool = False


class RunManager:
    """One process owns admission and a global concurrency budget for all submitted batches."""

    def __init__(self, store: Store, *, global_concurrency: int = MAX_GLOBAL_EPISODES):
        self.store = store
        self.owner_lock = open(str(store.path) + ".lock", "a+")
        try:
            fcntl.flock(self.owner_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            self.owner_lock.close()
            raise RuntimeError("database already owned by a running scheduler; use its HTTP API or a separate --db") from error
        self.store.recover()
        self.global_limit = asyncio.Semaphore(global_concurrency)
        self.jobs: dict[str, Job] = {}
        self.closing = False

    def submit(self, config: RunConfig, provider: Provider | None = None) -> JsonObject:
        if self.closing:
            raise ValueError("server is shutting down")
        if len(self.jobs) >= MAX_ACTIVE_RUNS:
            raise ValueError("active-run admission limit reached (32); wait for a batch to finish")
        provider = provider or make_provider(config)
        run_id = str(uuid.uuid4())
        run = self.store.create_run(run_id, config)
        task = asyncio.create_task(self._execute(run_id, config, provider), name=f"run-{run_id}")
        self.jobs[run_id] = Job(task)
        return run

    async def _execute(self, run_id: str, config: RunConfig, provider: Provider) -> None:
        started = time.perf_counter()
        self.store.update_run(run_id, "running")
        indices = iter(range(config.episodes))
        workers: list[asyncio.Task[None]] = []

        async def worker() -> None:
            while True:
                try:
                    index = next(indices)
                except StopIteration:
                    return
                async with self.global_limit:
                    episode = await rollout(config, index, provider)
                    self.store.append_episode(run_id, episode)
                    if episode["status"] == "cancelled":
                        return

        final_status, error = "completed", None
        try:
            if hasattr(provider, "prepare"):
                await provider.prepare()
            workers = [asyncio.create_task(worker()) for _ in range(min(config.concurrency, config.episodes))]
            await asyncio.gather(*workers)
        except asyncio.CancelledError:
            job = self.jobs.get(run_id)
            final_status = "interrupted" if job and job.shutdown else "cancelled"
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
        except Exception as unexpected:
            final_status, error = "failed", str(unexpected) if isinstance(unexpected, ProviderError) else f"batch failed ({type(unexpected).__name__}); details redacted"
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
        finally:
            if hasattr(provider, "close"):
                await provider.close()
            self.store.update_run(run_id, final_status, elapsed=time.perf_counter() - started, error=error)
            self.jobs.pop(run_id, None)

    async def wait(self, run_id: str) -> JsonObject:
        job = self.jobs.get(run_id)
        if job:
            await asyncio.shield(job.task)
        return self.store.get_run(run_id, detail=True)

    async def cancel(self, run_id: str) -> JsonObject:
        self.store.get_run(run_id)
        job = self.jobs.get(run_id)
        if job:
            job.task.cancel()
            await asyncio.gather(job.task, return_exceptions=True)
            if self.store.get_run(run_id)["status"] == "queued":
                self.store.update_run(run_id, "cancelled")
                self.jobs.pop(run_id, None)
        return self.store.get_run(run_id)

    async def close(self) -> None:
        self.closing = True
        jobs = list(self.jobs.values())
        for job in jobs:
            job.shutdown = True
            job.task.cancel()
        await asyncio.gather(*(job.task for job in jobs), return_exceptions=True)
        for run_id in list(self.jobs):
            if self.store.get_run(run_id)["status"] == "queued":
                self.store.update_run(run_id, "interrupted")
            self.jobs.pop(run_id, None)
        self.owner_lock.close()


def replay(episode: JsonObject) -> JsonObject:
    provenance = episode["provenance"]
    world = make_environment(provenance["environment_id"], episode["seed"])
    if provenance["environment_version"] != world.version or provenance["grader_version"] != GRADER_VERSION:
        raise ValueError("environment or grader version differs from the recorded episode")
    current_environment_hash, current_grader_hash = world_fingerprints(world)
    if provenance["environment_code_hash"] != current_environment_hash or provenance["grader_code_hash"] != current_grader_hash:
        raise ValueError("environment or grader implementation fingerprint differs from the recorded episode")
    if digest(world.snapshot()) != provenance["initial_state_hash"]:
        raise ValueError("initial state hash differs from the recorded episode")
    for step in episode["trace"]:
        transition = world.step(step["action"])
        if transition["state_hash"] != step["state_hash"] or transition["result"] != step["result"] or transition["observation"] != step["observation"]:
            raise ValueError(f"replay diverged at step {step['index']}")
    evaluation = world.evaluate().model_dump()
    if world.state_hash() != episode["final_state_hash"] or evaluation != episode["grader"]:
        raise ValueError("final state or trusted grade differs from the recorded episode")
    return {"verified": True, "steps": len(episode["trace"]), "final_state_hash": world.state_hash(), "grader": evaluation}
