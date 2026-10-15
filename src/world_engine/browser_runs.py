"""Bounded real-browser lifecycle; application grading never runs in the agent."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse
from uuid import uuid4

from world_engine.browser_contracts import (
    ACTION_ADAPTER,
    BrowserArtifact,
    BrowserAttemptConfig,
    BrowserCleanupError,
    BrowserDriver,
    BrowserError,
    BrowserObservation,
    BrowserPolicy,
    BrowserRuntime,
    CleanupResult,
    GradeResult,
    RuntimeHandle,
    TaskPack,
)
from world_engine.browser_store import BrowserStore
from world_engine.gitlab_taskpacks import make_browser_task, resolve_gitlab_pack

STARTUP_SECONDS = 600
SEAL_SECONDS = 120
CLEANUP_SECONDS = 60


def source_receipt() -> dict:
    root = Path(__file__).resolve().parents[2]
    try:
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                                  text=True, check=True, timeout=3).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "src/world_engine",
                                "environments/gitlab", "pyproject.toml", "uv.lock"], cwd=root,
                               capture_output=True, text=True, check=True, timeout=3).stdout
        if len(revision) != 40 or any(char not in "0123456789abcdef" for char in revision):
            raise ValueError
        return {"source_git_revision": revision, "source_dirty": bool(dirty),
                "source_scope": ["src/world_engine", "environments/gitlab", "pyproject.toml", "uv.lock"]}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"source_git_revision": None, "source_dirty": None, "source_unavailable": True}


@dataclass
class BrowserJob:
    task: asyncio.Task | None = None
    started: asyncio.Event = field(default_factory=asyncio.Event)
    stop_requested: bool = False
    finalizing: bool = False


class BrowserRunManager:
    def __init__(self, store: BrowserStore, tasks: dict[str, TaskPack], runtime: BrowserRuntime | None = None,
                 driver_factory: Callable[[RuntimeHandle, Path], BrowserDriver] | None = None,
                 policy_factory: Callable[[BrowserAttemptConfig, TaskPack], BrowserPolicy] | None = None,
                 task_factory: Callable[[str, int], TaskPack] | None = None):
        self.store, self.tasks = store, tasks
        self.runtime, self.driver_factory, self.policy_factory = runtime, driver_factory, policy_factory
        self.task_factory = task_factory
        self.jobs: dict[str, BrowserJob] = {}
        self.closing = False
        self.lock = open(str(store.path) + ".lock", "a+")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.blocked = bool(store.recover())
        except BaseException:
            self.lock.close()
            raise

    def status(self) -> dict:
        available = all(value is not None for value in (self.runtime, self.driver_factory, self.policy_factory))
        return {"available": available and not self.blocked and not self.closing,
                "reason": "resource reconciliation required" if self.blocked else None if available else "browser runtime not enabled",
                "active_attempts": len(self.jobs), "max_active_attempts": 1, "paid_calls_enabled": False,
                "providers": [{"id": identifier, "name": name, "configured": available,
                               "model": "qwen3:8b" if identifier == "local-browser" else None,
                               "readiness": "checked during attempt preparation"}
                              for identifier, name in (("local-browser", "Local Browser"),
                                                       ("browser-reference", "Browser Reference Control"),
                                                       ("browser-baseline", "Browser Incomplete Control"))]}

    def submit(self, config: BrowserAttemptConfig) -> dict:
        if not self.status()["available"]:
            raise BrowserError("browser runtime unavailable or requires resource reconciliation")
        if self.jobs:
            raise BrowserError("browser admission limit reached (1); wait for the active attempt")
        if config.task_id not in self.tasks:
            raise BrowserError("unknown browser task")
        task = self.task_factory(config.task_id, config.seed) if self.task_factory else self.tasks[config.task_id].model_copy(update={"seed": config.seed})
        if task.id != config.task_id or task.seed != config.seed:
            raise BrowserError("browser task generator returned an inconsistent task")
        key = str(uuid4())
        provenance = {**source_receipt(), "controller_modules": {
            name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ("browser_contracts.py", "browser_runs.py", "browser_store.py", "browser_api.py",
                         "browser_driver.py", "browser_policy.py", "gitlab_runtime.py", "gitlab_taskpacks.py")},
                      "evaluation_only": True, "training_eligible": False, "agent_interface": "browser-only",
                      "source_rights": {"task_origin": "original local fixture", "benchmark_imported": False,
                                        "application_source_url": "https://gitlab.com/gitlab-org/gitlab-foss",
                                        "application_license": "GitLab CE MIT; dependency/image licenses separate",
                                        "permitted_use": "evaluation-only", "training_eligible": False},
                      "isolation": "local Docker trusted operator pilot; not multi-tenant security"}
        if task.id == "gitlab-release-readiness":
            provenance["controller_modules"]["browser_readiness.py"] = hashlib.sha256(
                Path(__file__).with_name("browser_readiness.py").read_bytes()).hexdigest()
        if self.task_factory is make_browser_task:
            provenance.update(resolve_gitlab_pack(task.id).provenance(config.seed))
        result = self.store.create(key, config, task, provenance)
        job = BrowserJob()
        self.jobs[key] = job
        job.task = asyncio.create_task(self._execute(key, config, task, job), name=f"browser-{key}")
        return result

    def _observation(self, key: str, step: int, observation: BrowserObservation) -> dict:
        parsed = BrowserObservation.model_validate(observation)
        path = self.store.artifact_path(key, parsed.screenshot_artifact_id)
        artifact = BrowserArtifact(id=parsed.screenshot_artifact_id, kind="screenshot", mime_type="image/png",
                                   size_bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        self.store.register_artifact(key, artifact)
        self.store.append(key, "observation", {"step": step, "observation": parsed.model_dump()})
        return parsed.model_dump()

    async def _execute(self, key: str, config: BrowserAttemptConfig, task: TaskPack, job: BrowserJob) -> None:
        started = time.perf_counter()
        handle, driver, policy = None, None, None
        status, termination, error = "completed", "max_steps", None
        phases, steps, invalid = {}, 0, 0
        outcome = None
        phase = "startup"
        driver_closed = False
        startup_cleanup_failed = False
        phase_started = started
        startup_started = rollout_started = None
        job.started.set()
        try:
            await asyncio.sleep(0)
            if job.stop_requested:
                raise asyncio.CancelledError
            self.store.update(key, status="starting")
            phase_started = time.perf_counter()
            phase = "provider"
            policy = self.policy_factory(config, task)
            policy.set_recorder(lambda kind, payload: self.store.append(key, kind, payload))
            async with asyncio.timeout(30):
                await policy.prepare()
            phases["provider_prepare"] = time.perf_counter() - phase_started
            phase = "startup"
            phase_started = time.perf_counter()
            startup_started = phase_started
            async with asyncio.timeout(STARTUP_SECONDS):
                self.store.append(key, "runtime_start_intent", {"task_id": task.id, "seed": config.seed})
                handle = await self.runtime.start(key, task, self.store.directory(key))
                self.store.append(key, "runtime_started", {"instance_id": handle.instance_id,
                                                         "origin": handle.origin, "metadata": handle.runtime_metadata})
                driver = self.driver_factory(handle, self.store.directory(key))
                self.store.append(key, "browser_prepare_intent", {})
                await driver.prepare()
                self.store.append(key, "browser_prepared", {"metadata": getattr(driver, "evidence_metadata", {})})
            phases["startup"] = time.perf_counter() - phase_started
            phase = "rollout"
            phase_started = time.perf_counter()
            rollout_started = phase_started
            self.store.update(key, status="running", phase_seconds=phases)
            history = []
            async with asyncio.timeout(config.timeout_seconds):
                observation = await driver.observe()
                self._observation(key, 0, observation)
                for index in range(config.max_steps):
                    phase = "provider"
                    decision = await policy.decide(observation.model_copy(deep=True), list(history))
                    phase = "rollout"
                    action = ACTION_ADAPTER.validate_python(decision.action)
                    if action.kind == "navigate":
                        parsed = urlparse(action.url)
                        if f"{parsed.scheme}://{parsed.netloc}" != handle.origin:
                            raise BrowserError("navigation outside the episode application is forbidden")
                    self.store.append(key, "action_intent", {"step": index, "action": action.model_dump(),
                                                            "evidence": decision.evidence})
                    action_started = time.perf_counter()
                    result = {"ok": True, "message": "agent requested finish"} if action.kind == "finish" else await driver.execute(action)
                    if not isinstance(result, dict) or type(result.get("ok")) is not bool:
                        raise BrowserError("browser driver returned an invalid result")
                    event = {"step": index, "action": action.model_dump(), "result": result,
                             "elapsed_ms": (time.perf_counter() - action_started) * 1000}
                    self.store.append(key, "action_result", event)
                    steps += 1
                    invalid += int(not result["ok"])
                    observation = await driver.observe()
                    public_observation = self._observation(key, steps, observation)
                    history.append({**event, "observation": public_observation})
                    self.store.update(key, steps=steps, invalid_actions=invalid,
                                      elapsed_seconds=time.perf_counter() - started)
                    if action.kind == "finish":
                        termination = "finished"
                        break
            phases["rollout"] = time.perf_counter() - phase_started
        except asyncio.CancelledError:
            status, termination, error = "cancelled", "cancelled", "browser attempt cancelled"
        except TimeoutError:
            status, termination, error = "failed", "timeout", f"browser {phase} exceeded its wall-clock deadline"
        except BrowserCleanupError:
            startup_cleanup_failed = True
            self.blocked = True
            status, termination, error = "failed", "cleanup_error", "startup cleanup incomplete; further admission blocked"
        except Exception:
            status, termination, error = "failed", f"{phase}_error", f"browser {phase} failed; details redacted"
        finally:
            job.finalizing = True
            if rollout_started is not None:
                phases.setdefault("rollout", time.perf_counter() - rollout_started)
            elif startup_started is not None:
                phases.setdefault("startup", time.perf_counter() - startup_started)
            else:
                phases.setdefault("provider_prepare", time.perf_counter() - phase_started)
            # Close agent capabilities/video before trusted sealing, even on partial/error paths.
            if driver is not None:
                phase_started = time.perf_counter()
                try:
                    async with asyncio.timeout(CLEANUP_SECONDS):
                        artifacts = await driver.close()
                    driver_closed = True
                    for artifact in artifacts:
                        self.store.register_artifact(key, BrowserArtifact.model_validate(artifact))
                    self.store.append(key, "browser_closed", {})
                except BaseException:
                    status, termination, error = "failed", "cleanup_error", "browser capability closure failed; grading skipped"
                phases["browser_close"] = time.perf_counter() - phase_started
            if handle is not None and driver_closed:
                try:
                    self.store.update(key, status="sealing")
                    phase_started = time.perf_counter()
                    self.store.append(key, "state_seal_intent", {})
                    async with asyncio.timeout(SEAL_SECONDS):
                        sealed = await self.runtime.seal(handle)
                    self.store.check_quota(key)
                    if (not sealed.path.is_file() or sealed.path.is_symlink() or sealed.path.stat().st_size != sealed.size_bytes
                            or hashlib.sha256(sealed.path.read_bytes()).hexdigest() != sealed.sha256):
                        raise BrowserError("sealed application state integrity failed")
                    self.store.append(key, "state_sealed", {"sha256": sealed.sha256, "size_bytes": sealed.size_bytes})
                    phases["seal"] = time.perf_counter() - phase_started
                    self.store.update(key, status="grading")
                    phase_started = time.perf_counter()
                    async with asyncio.timeout(SEAL_SECONDS):
                        grade = GradeResult.model_validate(await self.runtime.grade(sealed, task))
                    if (grade.sealed_state_sha256 != sealed.sha256 or grade.grader_version != task.grader_version
                            or grade.passed != all(check.passed for check in grade.checks)
                            or grade.reward != float(grade.passed)):
                        raise BrowserError("trusted grade contradicts the sealed contract")
                    outcome = grade.model_dump()
                    self.store.append(key, "graded", {"outcome": outcome})
                    phases["grade"] = time.perf_counter() - phase_started
                except BaseException:
                    status, termination, error = "failed", "grader_error", "trusted state sealing or grading failed; no outcome certified"
            cleanup = CleanupResult(status="failed", error_code="cleanup_failed") if startup_cleanup_failed or (driver is not None and not driver_closed) else CleanupResult(status="completed")
            phase_started = time.perf_counter()
            if policy is not None:
                try:
                    async with asyncio.timeout(CLEANUP_SECONDS):
                        await policy.close()
                except BaseException:
                    cleanup = CleanupResult(status="failed", error_code="cleanup_failed")
            if handle is not None:
                try:
                    async with asyncio.timeout(CLEANUP_SECONDS):
                        runtime_cleanup = CleanupResult.model_validate(await self.runtime.close(handle))
                    if runtime_cleanup.status != "completed":
                        cleanup = runtime_cleanup
                except TimeoutError:
                    cleanup = CleanupResult(status="timeout", error_code="cleanup_timeout")
                except BaseException:
                    cleanup = CleanupResult(status="failed", error_code="cleanup_failed")
            phases["cleanup"] = time.perf_counter() - phase_started
            if cleanup.status != "completed":
                self.blocked = True
                if status == "completed":
                    status, termination = "failed", "cleanup_error"
                error = "browser cleanup incomplete; further admission blocked"
            if job.stop_requested and status != "failed":
                status, termination = "cancelled", "cancelled"
            passed = bool(outcome and outcome["passed"] and status == "completed" and termination == "finished")
            try:
                self.store.append(key, "cleanup", cleanup.model_dump(), terminal=True)
                self.store.update(key, terminal=True, status=status, termination=termination, error=error, outcome=outcome,
                                  passed=passed, reward=float(passed), steps=steps, invalid_actions=invalid,
                                  cleanup=cleanup.model_dump(), phase_seconds=phases,
                                  reconciliation_required=cleanup.status != "completed",
                                  elapsed_seconds=time.perf_counter() - started)
            except Exception:
                self.blocked = True
                self.store.fail_finalization(key, steps=steps, invalid_actions=invalid,
                                             cleanup=cleanup.model_dump(), phase_seconds=phases,
                                             elapsed_seconds=time.perf_counter() - started)
            finally:
                self.jobs.pop(key, None)

    async def wait(self, key: str) -> dict:
        job = self.jobs.get(key)
        if job is not None:
            await asyncio.shield(job.task)
        return self.store.get(key, detail=True)

    async def cancel(self, key: str) -> dict:
        self.store.get(key)
        job = self.jobs.get(key)
        if job is not None:
            already_requested = job.stop_requested
            job.stop_requested = True
            await job.started.wait()
            if not job.finalizing and not already_requested:
                job.task.cancel()
            await asyncio.shield(job.task)
        return self.store.get(key)

    async def close(self) -> None:
        self.closing = True
        try:
            await asyncio.gather(*(self.cancel(key) for key in list(self.jobs)))
        finally:
            self.lock.close()


def default_browser_manager(directory: Path) -> BrowserRunManager:
    """Disabled by default; constructing the local pilot never starts an application."""
    from world_engine.gitlab_runtime import GitLabRuntime
    from world_engine.gitlab_taskpacks import gitlab_catalog, make_browser_task

    tasks = gitlab_catalog()
    store = BrowserStore(directory)
    if os.environ.get("WORLD_ENGINE_BROWSER_ENABLED") != "1":
        return BrowserRunManager(store, tasks, task_factory=make_browser_task)
    from world_engine.browser_driver import BrowserGymDriver
    from world_engine.browser_policy import create_browser_policy

    return BrowserRunManager(store, tasks, GitLabRuntime(), BrowserGymDriver, create_browser_policy, make_browser_task)
