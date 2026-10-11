from __future__ import annotations

import asyncio
import fcntl
import hashlib
import inspect
import platform
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from world_engine import provider_records
from world_engine.environments import make_environment
from world_engine.models import JsonObject, RunConfig, digest, utc_now
from world_engine.providers import (
    JSON_EVIDENCE_PROTOCOL,
    SYSTEM_PROMPT,
    Provider,
    ProviderError,
    make_provider,
    policy_messages,
    reported_decision_usage,
)
from world_engine.store import Store

GRADER_VERSION = "1.0.0"
POLICY_VERSION = "workflow-json-v1"
MAX_GLOBAL_EPISODES = 8
MAX_ACTIVE_RUNS = 32
PROVIDER_CLEANUP_TIMEOUT_SECONDS = 2.0
PROVIDER_CLEANUP_SCHEMA = "world-engine.provider-cleanup.v1"
PROVIDER_CLEANUP_ERRORS = {
    "failed": "provider cleanup failed; details redacted",
    "timeout": "provider cleanup exceeded its cooperative timeout",
    "cancelled": "provider cleanup cancelled; resource closure unconfirmed",
}
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


async def cleanup_provider(provider: Provider) -> JsonObject | None:
    """Bound cooperative cleanup without exposing extension exception payloads."""
    status = "completed"
    try:
        close = getattr(provider, "close", None)
        if close is None:
            return None
        async with asyncio.timeout(PROVIDER_CLEANUP_TIMEOUT_SECONDS):
            await close()
    except TimeoutError:
        status = "timeout"
    except asyncio.CancelledError:
        status = "cancelled"
    except Exception:
        status = "failed"
    return {"schema": PROVIDER_CLEANUP_SCHEMA, "status": status,
            "error": PROVIDER_CLEANUP_ERRORS.get(status)}


async def rollout(config: RunConfig, index: int, provider: Provider | None = None) -> JsonObject:
    owns_provider = provider is None
    provider = provider or make_provider(config)
    if not owns_provider:
        return await _rollout(config, index, provider)
    started = time.perf_counter()
    try:
        if hasattr(provider, "prepare"):
            await provider.prepare()
        episode = await _rollout(config, index, provider)
    except BaseException as error:
        await cleanup_provider(provider)
        if isinstance(error, Exception) and not isinstance(error, ProviderError):
            raise ProviderError("episode initialization failed; details redacted") from None
        raise error from None
    cleanup = await cleanup_provider(provider)
    if cleanup is not None:
        episode["provider_cleanup"] = cleanup
        if cleanup["status"] != "completed":
            if cleanup["status"] == "cancelled":
                episode["status"] = "cancelled"
            elif episode["status"] == "completed":
                episode["status"] = "failed"
            episode["error"] = episode["error"] or cleanup["error"]
            episode["reward"], episode["passed"] = 0.0, False
    episode["elapsed_seconds"] = time.perf_counter() - started
    return episode


async def _rollout(config: RunConfig, index: int, provider: Provider) -> JsonObject:
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
    provider_protocol = getattr(provider, "provider_protocol", POLICY_VERSION)
    if hasattr(provider, "record_calls"):
        provenance["provider_record_calls"] = provider.record_calls
    if getattr(provider, "tracks_reported_usage", False):
        provenance["usage_accounting"] = "reported-http-decisions-v1"
    if provider_protocol != POLICY_VERSION:
        provenance["provider_protocol"] = provider_protocol
        provenance["training_eligible"] = False
        if hasattr(provider, "evidence_metadata"):
            provenance["provider_evidence"] = provider.evidence_metadata()
    policy_configuration = {"provider_id": provenance["provider_id"], "provider_class": provider_identity,
                            "provider_source_hash": provider_source_hash, "model": provenance["model"],
                            "model_digest": provenance["model_digest"], "policy_code_hash": POLICY_CODE_HASH,
                            "system_prompt_hash": provenance["system_prompt_hash"], "temperature": 0}
    if provider_protocol == JSON_EVIDENCE_PROTOCOL:
        policy_configuration.update(provider_protocol=provider_protocol, provider_record_calls=True,
                                    provider_evidence_hash=digest(provenance["provider_evidence"]))
    elif provider_protocol == "ollama-tools-ledger-v2":
        policy_configuration.update(provider_protocol=provider_protocol,
                                    provider_evidence_hash=digest(provenance["provider_evidence"]))
    provenance["policy_hash"] = digest(policy_configuration)
    trace: list[JsonObject] = []
    provider_events, recorder_token = provider_records.begin_episode()
    started = time.perf_counter()
    status, error, termination = "completed", None, "max_steps"
    try:
        async with asyncio.timeout(config.timeout_seconds):
            for step_index in range(config.max_steps):
                step_started = time.perf_counter()
                observation = world.observe()
                context = policy_messages(observation, trace)
                decision = await provider.decide(observation, trace)
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
        provider_records.end_episode(recorder_token)
    evaluation = world.evaluate().model_dump()
    passed = evaluation["passed"] and status == "completed" and termination == "finished"
    reward = evaluation["reward"] if status == "completed" and termination == "finished" else 0.0
    episode = {
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
    if provider_protocol != POLICY_VERSION or provider_events:
        episode["provider_events"] = provider_events
        episode["provider_recording"] = {"schema": provider_records.RECORD_SCHEMA,
                                         "durability": "finalized episode only; not process-crash durable"}
        episode["usage"] = provider_records.usage_summary(provider_events)
    elif getattr(provider, "tracks_reported_usage", False):
        episode["usage"] = reported_decision_usage(trace, termination)
    return episode


@dataclass
class Job:
    task: asyncio.Task[None]
    started: asyncio.Event = field(default_factory=asyncio.Event)
    stop_requested: bool = False
    cleanup_started: bool = False
    shutdown: bool = False


class RunManager:
    """One process owns admission and a global concurrency budget for all submitted batches."""

    def __init__(self, store: Store, *, global_concurrency: int = MAX_GLOBAL_EPISODES):
        if type(global_concurrency) is not int or not 1 <= global_concurrency <= MAX_GLOBAL_EPISODES:
            raise ValueError(f"global_concurrency must be an integer from 1 to {MAX_GLOBAL_EPISODES}")
        self.store = store
        self.owner_lock = open(str(store.path) + ".lock", "a+")
        try:
            try:
                fcntl.flock(self.owner_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError("database already owned by a running scheduler; use its HTTP API or a separate --db") from error
            self.store.recover()
            self.global_limit = asyncio.Semaphore(global_concurrency)
            self.jobs: dict[str, Job] = {}
            self.closing = False
        except BaseException:
            self.owner_lock.close()
            raise

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
        job = self.jobs[run_id]
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
            # Cancellation before scheduling must still enter provider ownership's finally.
            job.started.set()
            await asyncio.sleep(0)
            if job.stop_requested:
                raise asyncio.CancelledError
            self.store.update_run(run_id, "running")
            if hasattr(provider, "prepare"):
                await provider.prepare()
            workers = [asyncio.create_task(worker()) for _ in range(min(config.concurrency, config.episodes))]
            await asyncio.gather(*workers)
        except asyncio.CancelledError:
            final_status = "interrupted" if job.shutdown else "cancelled"
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
        except Exception as unexpected:
            final_status, error = "failed", str(unexpected) if isinstance(unexpected, ProviderError) else f"batch failed ({type(unexpected).__name__}); details redacted"
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
        finally:
            job.cleanup_started = True
            try:
                cleanup = await cleanup_provider(provider)
                if job.stop_requested:
                    final_status = "interrupted" if job.shutdown else "cancelled"
                if cleanup is not None and cleanup["status"] != "completed":
                    if final_status == "completed":
                        final_status = "failed"
                    error = f"{error}; {cleanup['error']}" if error else cleanup["error"]
                self.store.update_run(run_id, final_status, elapsed=time.perf_counter() - started, error=error)
            finally:
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
            await self._request_stop(job)
            await asyncio.gather(job.task, return_exceptions=True)
        return self.store.get_run(run_id)

    async def _request_stop(self, job: Job) -> None:
        already_requested = job.stop_requested
        job.stop_requested = True
        await job.started.wait()
        if not already_requested and not job.cleanup_started:
            job.task.cancel()

    async def close(self) -> None:
        self.closing = True
        jobs = list(self.jobs.values())
        try:
            for job in jobs:
                job.shutdown = True
            await asyncio.gather(*(self._request_stop(job) for job in jobs))
            await asyncio.gather(*(job.task for job in jobs), return_exceptions=True)
        finally:
            self.owner_lock.close()


def replay(episode: JsonObject) -> JsonObject:
    """Verify seeded state, grading and envelope consistency, not collection authenticity.

    ``policy_input`` is the controller's recorded context. A custom Provider may
    transform it internally; replay cannot attest its actual model request.
    Timing, usage, external failure causes and model identity remain reported data.
    """
    try:
        return _replay(episode)
    except (KeyError, TypeError, IndexError, AttributeError) as error:
        raise ValueError("malformed episode envelope") from error


def _replay(episode: JsonObject) -> JsonObject:
    def matches(actual, expected, label: str) -> None:
        # Canonical comparison also distinguishes booleans from numeric labels.
        if digest(actual) != digest(expected):
            raise ValueError(f"{label} differs from the replayed episode")

    provenance = episode["provenance"]
    from world_engine.ollama_tools import NATIVE_PROTOCOLS, OllamaToolsProvider
    native_protocol = provenance.get("provider_protocol")
    if "provider_record_calls" in provenance and type(provenance["provider_record_calls"]) is not bool:
        raise ValueError("provider recording mode must be boolean")
    if (provenance.get("provider_class") == "world_engine.ollama_tools.OllamaToolsProvider"
            and native_protocol not in NATIVE_PROTOCOLS):
        raise ValueError("native provider is missing its native protocol contract")
    provider_pairs = None
    evidence_label = "native"
    if native_protocol in NATIVE_PROTOCOLS:
        from world_engine.ollama_tools import contract, module_hashes, verify_exchange
        evidence = provenance["provider_evidence"]
        matches(provenance["provider_class"], "world_engine.ollama_tools.OllamaToolsProvider", "native provider class")
        matches(provenance["provider_source_hash"], source_fingerprint(OllamaToolsProvider), "native provider source")
        for key, value in module_hashes(native_protocol).items():
            matches(evidence[key], value, f"native {key}")
        matches(evidence["native_contract"], contract(native_protocol), "native contract")
        matches(evidence["native_contract_hash"], digest(contract(native_protocol)), "native contract hash")
        matches(provenance["training_eligible"], False, "native training eligibility")
        provider_pairs = provider_records.validate_pairs(episode["provider_events"], native_protocol)
    elif provenance.get("provider_protocol") == JSON_EVIDENCE_PROTOCOL:
        from world_engine.providers import (
            HTTPProvider,
            json_evidence_contract,
            json_evidence_module_hashes,
            verify_json_exchange,
        )
        evidence_label = "JSON"
        evidence = provenance["provider_evidence"]
        for key, value in json_evidence_module_hashes().items():
            matches(evidence[key], value, f"JSON {key}")
        matches(evidence["json_contract"], json_evidence_contract(), "JSON contract")
        matches(evidence["json_contract_hash"], digest(json_evidence_contract()), "JSON contract hash")
        matches(provenance["provider_record_calls"], True, "JSON recording mode")
        matches(provenance["provider_id"], "local", "JSON provider kind")
        matches(provenance["provider_class"], "world_engine.providers.HTTPProvider", "JSON provider class")
        matches(provenance["provider_source_hash"], source_fingerprint(HTTPProvider), "JSON provider source")
        matches(provenance["policy_code_hash"], POLICY_CODE_HASH, "JSON policy source")
        matches(provenance["training_eligible"], False, "JSON training eligibility")
        provider_pairs = provider_records.validate_pairs(episode["provider_events"], JSON_EVIDENCE_PROTOCOL)
        verify_exchange = verify_json_exchange
    elif (provenance.get("provider_record_calls") is True
          or any(event.get("protocol") == JSON_EVIDENCE_PROTOCOL for event in episode.get("provider_events", []))):
        raise ValueError("recorded JSON provider is missing its protocol contract")
    elif any(event.get("protocol") in NATIVE_PROTOCOLS for event in episode.get("provider_events", [])):
        raise ValueError("recorded native provider is missing its protocol contract")
    if type(episode["seed"]) is not int or not 0 <= episode["seed"] < 2 ** 31:
        raise ValueError("episode seed is invalid")
    if not isinstance(episode["trace"], list) or len(episode["trace"]) > 100:
        raise ValueError("episode trace is invalid")
    world = make_environment(provenance["environment_id"], episode["seed"])
    if provenance["environment_version"] != world.version or provenance["grader_version"] != GRADER_VERSION:
        raise ValueError("environment or grader version differs from the recorded episode")
    current_environment_hash, current_grader_hash = world_fingerprints(world)
    if provenance["environment_code_hash"] != current_environment_hash or provenance["grader_code_hash"] != current_grader_hash:
        raise ValueError("environment or grader implementation fingerprint differs from the recorded episode")
    initial_snapshot = world.snapshot()
    initial_observation = world.observe()
    exchange_options = ({"protocol": native_protocol, "initial_observation": initial_observation}
                        if native_protocol in NATIVE_PROTOCOLS else {})
    initial_state_hash = digest(initial_snapshot)
    task_hash = digest({"task": initial_observation["task"], "tools": initial_observation["tools"]})
    lineage_id = digest({"environment_family": world.id, "seed": episode["seed"]})
    scenario_id = digest({"environment": world.id, "version": world.version, "grader_version": GRADER_VERSION,
                          "environment_code_hash": current_environment_hash, "grader_code_hash": current_grader_hash,
                          "seed": episode["seed"], "initial_state_hash": initial_state_hash, "task_hash": task_hash})
    for key, expected in {"schema_version": "1.0.0", "seed": episode["seed"], "initial_state_hash": initial_state_hash,
                          "task_hash": task_hash, "lineage_id": lineage_id, "scenario_id": scenario_id,
                          "prompt_hash": digest(policy_messages(initial_observation, [])),
                          "policy_version": POLICY_VERSION, "system_prompt_hash": digest(SYSTEM_PROMPT)}.items():
        matches(provenance[key], expected, f"provenance {key}")
    for key, expected in {"initial_snapshot": initial_snapshot, "initial_observation": initial_observation,
                          "lineage_id": lineage_id, "scenario_id": scenario_id,
                          "split": scenario_split(lineage_id)}.items():
        matches(episode[key], expected, key)
    policy_configuration = {"provider_id": provenance["provider_id"], "provider_class": provenance["provider_class"],
                            "provider_source_hash": provenance["provider_source_hash"], "model": provenance["model"],
                            "model_digest": provenance["model_digest"], "policy_code_hash": provenance["policy_code_hash"],
                            "system_prompt_hash": provenance["system_prompt_hash"], "temperature": 0}
    if provenance.get("provider_protocol") == JSON_EVIDENCE_PROTOCOL:
        policy_configuration.update(provider_protocol=JSON_EVIDENCE_PROTOCOL, provider_record_calls=True,
                                    provider_evidence_hash=digest(provenance["provider_evidence"]))
    elif native_protocol == "ollama-tools-ledger-v2":
        policy_configuration.update(provider_protocol=native_protocol,
                                    provider_evidence_hash=digest(provenance["provider_evidence"]))
    policy_hash = digest(policy_configuration)
    matches(provenance["policy_hash"], policy_hash, "policy configuration hash")
    history = []
    for index, step in enumerate(episode["trace"]):
        if world.done:
            raise ValueError("episode trace continues after the world finished")
        matches(step["index"], index, "step index")
        matches(step["policy_input"], policy_messages(world.observe(), history), f"policy input at step {index}")
        if provider_pairs is not None:
            if index >= len(provider_pairs):
                raise ValueError(f"{evidence_label} executed action has no recorded request")
            start, end = provider_pairs[index]
            verify_exchange(start, end, provenance["model"], world.observe(), history, step["action"], **exchange_options)
            matches(step["usage"], end["usage"], f"{evidence_label} usage at step {index}")
        transition = world.step(step["action"])
        for key in ("state_hash", "result", "observation"):
            matches(step[key], transition[key], f"replay diverged: {key} at step {index}")
        history.append(step)
    if provider_pairs is not None:
        if not len(history) <= len(provider_pairs) <= len(history) + 1:
            raise ValueError(f"{evidence_label} request count differs from executed decisions")
        if len(provider_pairs) > len(history):
            if episode["status"] == "completed":
                raise ValueError(f"completed {evidence_label} episode has an unexecuted request")
            start, end = provider_pairs[-1]
            verify_exchange(start, end, provenance["model"], world.observe(), history, None, **exchange_options)
        matches(episode["usage"], provider_records.usage_summary(episode["provider_events"]), f"{evidence_label} aggregate usage")
    elif provenance.get("usage_accounting") == "reported-http-decisions-v1":
        matches(episode["usage"], reported_decision_usage(history, episode["termination"]), "HTTP aggregate usage")
    evaluation = world.evaluate().model_dump()
    for key, expected in {"final_state_hash": world.state_hash(), "grader": evaluation,
                          "final_snapshot": world.snapshot(), "final_observation": world.observe(),
                          "steps": len(history), "invalid_actions": sum(not step["result"]["ok"] for step in history)}.items():
        matches(episode[key], expected, key)
    status, termination = episode["status"], episode["termination"]
    valid_outcomes = {("completed", "finished"), ("completed", "max_steps"), ("cancelled", "cancelled"),
                      ("failed", "timeout"), ("failed", "provider_error"), ("failed", "internal_error")}
    cleanup = episode.get("provider_cleanup")
    if cleanup is not None:
        if (not isinstance(cleanup, dict) or set(cleanup) != {"schema", "status", "error"}
                or cleanup["schema"] != PROVIDER_CLEANUP_SCHEMA
                or cleanup["status"] not in {"completed", *PROVIDER_CLEANUP_ERRORS}
                or cleanup["error"] != PROVIDER_CLEANUP_ERRORS.get(cleanup["status"])):
            raise ValueError("provider cleanup metadata is invalid")
        if cleanup["status"] in {"failed", "timeout"}:
            valid_outcomes.update({("failed", "finished"), ("failed", "max_steps")})
            if status == "completed":
                raise ValueError("failed provider cleanup contradicts completed status")
        elif cleanup["status"] == "cancelled":
            valid_outcomes.update(("cancelled", value) for value in
                                  ("finished", "max_steps", "timeout", "provider_error", "internal_error"))
            if status != "cancelled":
                raise ValueError("cancelled provider cleanup contradicts episode status")
        if cleanup["status"] != "completed" and termination in {"finished", "max_steps"}:
            matches(episode["error"], cleanup["error"], "provider cleanup outcome error")
    if (status, termination) not in valid_outcomes or world.done != (termination == "finished"):
        raise ValueError("status or termination contradicts the replayed world")
    if status == "completed" and (episode["error"] is not None or not history):
        raise ValueError("completed episode has an error or no executed steps")
    if status != "completed" and (not isinstance(episode["error"], str) or not episode["error"]):
        raise ValueError("failed or cancelled episode has no reported error")
    finished = status == "completed" and termination == "finished"
    reward = evaluation["reward"] if finished else 0.0
    passed = evaluation["passed"] and finished
    matches(episode["reward"], reward, "authoritative reward")
    matches(episode["passed"], passed, "authoritative passed label")
    return {"verified": True, "steps": len(history), "final_state_hash": world.state_hash(), "grader": evaluation,
            "reward": reward, "passed": passed, "status": status, "termination": termination}
