import asyncio
import copy
import importlib
import traceback

import pytest

from world_engine.exports import export_records, json_training_compatible
from world_engine.models import RunConfig, digest
from world_engine.providers import ProviderError, ScriptedProvider
from world_engine.rollout import RunManager, replay, rollout, scenario_split
from world_engine.store import Store

module = importlib.import_module("world_engine.rollout")
SECRET = "cleanup-secret-must-not-appear"


class LifecycleProvider(ScriptedProvider):
    def __init__(self, *, close_mode="completed", prepare_error=None, oracle=True):
        super().__init__(oracle)
        self.close_mode = close_mode
        self.prepare_error = prepare_error
        self.prepare_calls = 0
        self.close_calls = 0
        self.cleanup_entered = asyncio.Event()
        self.cleanup_release = asyncio.Event()

    async def prepare(self):
        self.prepare_calls += 1
        if self.prepare_error is not None:
            raise self.prepare_error

    async def close(self):
        self.close_calls += 1
        self.cleanup_entered.set()
        if self.close_mode == "failed":
            raise RuntimeError(SECRET)
        if self.close_mode in {"blocked", "blocked-failed"}:
            await self.cleanup_release.wait()
            if self.close_mode == "blocked-failed":
                raise RuntimeError(SECRET)
        if self.close_mode == "timeout":
            await asyncio.sleep(60)
        if self.close_mode == "cancelled":
            raise asyncio.CancelledError


def own(monkeypatch, provider):
    monkeypatch.setattr(module, "make_provider", lambda config: provider)


@pytest.mark.parametrize("close_mode", ["completed", "failed", "timeout"])
@pytest.mark.parametrize("max_steps", [1, 20])
async def test_owned_episode_survives_cleanup_and_replays(monkeypatch, close_mode, max_steps):
    monkeypatch.setattr(module, "PROVIDER_CLEANUP_TIMEOUT_SECONDS", .02)
    provider = LifecycleProvider(close_mode=close_mode)
    own(monkeypatch, provider)
    episode = await rollout(RunConfig(environment_id="crm-merge", max_steps=max_steps), 0)
    assert provider.close_calls == provider.prepare_calls == 1
    assert episode["steps"] > 0
    assert episode["termination"] == ("finished" if max_steps == 20 else "max_steps")
    assert episode["provider_cleanup"]["status"] == close_mode
    assert episode["grader"]["passed"] == (max_steps == 20)
    assert episode["status"] == ("completed" if close_mode == "completed" else "failed")
    assert episode["passed"] == (close_mode == "completed" and max_steps == 20)
    if close_mode != "completed":
        assert episode["reward"] == 0
        assert SECRET not in str(episode)
        assert not json_training_compatible(episode)
    assert replay(episode)["verified"]


@pytest.mark.parametrize("close_mode", ["failed", "timeout"])
@pytest.mark.parametrize("primary", ["safe", "unexpected", "cancelled"])
async def test_prepare_failure_primary_survives_cleanup(monkeypatch, close_mode, primary):
    monkeypatch.setattr(module, "PROVIDER_CLEANUP_TIMEOUT_SECONDS", .02)
    errors = {"safe": ProviderError("safe preparation reason"), "unexpected": RuntimeError(SECRET),
              "cancelled": asyncio.CancelledError()}
    provider = LifecycleProvider(close_mode=close_mode, prepare_error=errors[primary])
    own(monkeypatch, provider)
    with pytest.raises(asyncio.CancelledError if primary == "cancelled" else ProviderError) as caught:
        await rollout(RunConfig(environment_id="crm-merge"), 0)
    rendered = "".join(traceback.format_exception(caught.value))
    assert SECRET not in rendered
    if primary == "safe":
        assert str(caught.value) == "safe preparation reason"
    assert provider.close_calls == 1


async def test_partial_owned_failure_keeps_primary_and_trace(monkeypatch):
    class PartialProvider(LifecycleProvider):
        async def decide(self, observation, history):
            if history:
                raise ProviderError("safe decision failure")
            return await super().decide(observation, history)

    provider = PartialProvider(close_mode="failed")
    own(monkeypatch, provider)
    episode = await rollout(RunConfig(environment_id="crm-merge"), 0)
    assert episode["steps"] == 1
    assert episode["status"] == "failed" and episode["termination"] == "provider_error"
    assert episode["error"] == "safe decision failure"
    assert episode["provider_cleanup"]["status"] == "failed"
    assert replay(episode)["verified"]


async def test_direct_cancellation_during_cleanup_retains_execution(monkeypatch):
    provider = LifecycleProvider(close_mode="blocked")
    own(monkeypatch, provider)
    task = asyncio.create_task(rollout(RunConfig(environment_id="crm-merge"), 0))
    await asyncio.wait_for(provider.cleanup_entered.wait(), 1)
    task.cancel()
    episode = await task
    assert episode["status"] == "cancelled" and episode["termination"] == "finished"
    assert episode["grader"]["passed"] and episode["reward"] == 0 and not episode["passed"]
    assert episode["provider_cleanup"]["status"] == "cancelled"
    assert not json_training_compatible(episode)
    assert replay(episode)["verified"]


@pytest.mark.parametrize("close_mode", ["completed", "failed", "timeout"])
async def test_batch_cleanup_terminal_status_admission_and_lease(tmp_path, monkeypatch, close_mode):
    monkeypatch.setattr(module, "PROVIDER_CLEANUP_TIMEOUT_SECONDS", .02)
    store = Store(tmp_path / "batch.sqlite3")
    manager = RunManager(store)
    provider = LifecycleProvider(close_mode=close_mode)
    run = manager.submit(RunConfig(environment_id="crm-merge", episodes=1), provider)
    try:
        result = await manager.wait(run["id"])
        assert result["status"] == ("completed" if close_mode == "completed" else "failed")
        assert len(result["episodes"]) == 1
        episode = result["episodes"][0]
        assert episode["passed"] and episode["status"] == "completed"
        assert "provider_cleanup" not in episode  # Shared batch resource is not episode-owned.
        assert provider.close_calls == 1 and not manager.jobs
        assert SECRET not in str(result)
        assert await manager.wait(run["id"]) == result
        assert (await manager.cancel(run["id"]))["status"] == result["status"]
        replay(episode)
    finally:
        await manager.close()
    replacement = RunManager(Store(store.path))
    await replacement.close()


@pytest.mark.parametrize("close_mode", ["failed", "timeout"])
async def test_batch_prepare_failure_has_no_fake_episode(tmp_path, monkeypatch, close_mode):
    monkeypatch.setattr(module, "PROVIDER_CLEANUP_TIMEOUT_SECONDS", .02)
    manager = RunManager(Store(tmp_path / "prepare.sqlite3"))
    provider = LifecycleProvider(close_mode=close_mode, prepare_error=ProviderError("safe preparation reason"))
    try:
        run = manager.submit(RunConfig(environment_id="crm-merge"), provider)
        result = await manager.wait(run["id"])
        assert result["status"] == "failed"
        assert result["error"].startswith("safe preparation reason; provider cleanup")
        assert result["episodes"] == [] and not manager.jobs and provider.close_calls == 1
    finally:
        await manager.close()


@pytest.mark.parametrize("shutdown", [False, True])
@pytest.mark.parametrize("close_mode", ["blocked", "blocked-failed", "timeout"])
async def test_stop_during_batch_cleanup_is_authoritative(tmp_path, monkeypatch, shutdown, close_mode):
    monkeypatch.setattr(module, "PROVIDER_CLEANUP_TIMEOUT_SECONDS", .05)
    store = Store(tmp_path / "stop.sqlite3")
    manager = RunManager(store)
    provider = LifecycleProvider(close_mode=close_mode)
    run = manager.submit(RunConfig(environment_id="crm-merge", episodes=1), provider)
    await asyncio.wait_for(provider.cleanup_entered.wait(), 1)
    waiter = asyncio.create_task(manager.wait(run["id"]))
    stopping = asyncio.create_task(manager.close() if shutdown else manager.cancel(run["id"]))
    await asyncio.sleep(0)
    provider.cleanup_release.set()
    await stopping
    result = await waiter
    assert result["status"] == ("interrupted" if shutdown else "cancelled")
    assert len(result["episodes"]) == 1 and result["episodes"][0]["passed"]
    assert provider.close_calls == 1 and not manager.jobs
    assert (result["error"] is not None) == (close_mode != "blocked")
    assert SECRET not in str(result)
    await manager.close()
    replacement = RunManager(Store(store.path))
    await replacement.close()


@pytest.mark.parametrize("shutdown", [False, True])
async def test_queued_stop_closes_provider_without_preparation(tmp_path, shutdown):
    manager = RunManager(Store(tmp_path / "queued.sqlite3"))
    provider = LifecycleProvider(close_mode="failed")
    run = manager.submit(RunConfig(environment_id="crm-merge"), provider)
    if shutdown:
        await manager.close()
    else:
        await asyncio.gather(manager.cancel(run["id"]), manager.cancel(run["id"]))
    result = await manager.wait(run["id"])
    assert result["status"] == ("interrupted" if shutdown else "cancelled")
    assert result["episodes"] == [] and provider.prepare_calls == 0 and provider.close_calls == 1
    assert not manager.jobs and result["error"]
    await manager.close()


@pytest.mark.parametrize("shutdown", [False, True])
async def test_stop_during_decide_preserves_partial_episode(tmp_path, shutdown):
    entered = asyncio.Event()

    class PartialProvider(LifecycleProvider):
        async def decide(self, observation, history):
            if history:
                entered.set()
                await asyncio.sleep(60)
            return await super().decide(observation, history)

    provider = PartialProvider(close_mode="failed")
    manager = RunManager(Store(tmp_path / "partial.sqlite3"))
    run = manager.submit(RunConfig(environment_id="crm-merge", episodes=3, concurrency=1), provider)
    await asyncio.wait_for(entered.wait(), 1)
    if shutdown:
        await manager.close()
    else:
        await manager.cancel(run["id"])
    result = await manager.wait(run["id"])
    assert result["status"] == ("interrupted" if shutdown else "cancelled")
    assert len(result["episodes"]) == 1 and result["episodes"][0]["steps"] == 1
    assert result["episodes"][0]["status"] == "cancelled"
    assert provider.close_calls == 1 and result["error"] and not manager.jobs
    replay(result["episodes"][0])
    await manager.close()


@pytest.mark.parametrize("close_mode", ["failed", "timeout", "cancelled"])
async def test_failed_cleanup_not_training_or_candidate_pool(tmp_path, monkeypatch, close_mode):
    monkeypatch.setattr(module, "PROVIDER_CLEANUP_TIMEOUT_SECONDS", .02)
    seed = next(seed for seed in range(20) if scenario_split(digest({"environment_family": "crm-merge", "seed": seed})) == "train")
    config = RunConfig(environment_id="crm-merge", seed=seed)
    clean = await rollout(config, 0, ScriptedProvider())
    own(monkeypatch, LifecycleProvider(close_mode=close_mode, oracle=False))
    failed = await rollout(config, 0)
    store = Store(tmp_path / "exports.sqlite3")
    for run_id, episode in (("clean", clean), ("failed", failed)):
        store.create_run(run_id, config)
        store.append_episode(run_id, episode)
    for format in ("sft", "dpo", "grpo"):
        assert export_records(store, "failed", format, "all")[0] == []
    for format in ("dpo", "grpo"):
        assert export_records(store, "clean", format, "all")[0] == []
    assert export_records(store, "clean", "sft", "all")[0]
    records, _ = export_records(store, "failed", "traces", "all")
    assert records[0]["provider_cleanup"]["status"] == close_mode
    assert records[0]["training_eligible"] is False
    assert json_training_compatible(clean)
    clean["provider_cleanup"] = {"schema": module.PROVIDER_CLEANUP_SCHEMA, "status": "completed", "error": None}
    assert json_training_compatible(clean) and replay(clean)["verified"]


async def test_borrowed_provider_is_caller_owned():
    provider = LifecycleProvider(close_mode="failed")
    episode = await rollout(RunConfig(environment_id="crm-merge"), 0, provider)
    assert episode["passed"] and "provider_cleanup" not in episode
    assert provider.prepare_calls == provider.close_calls == 0


async def test_direct_cancel_during_decide_then_failed_cleanup(monkeypatch):
    entered = asyncio.Event()

    class PartialProvider(LifecycleProvider):
        async def decide(self, observation, history):
            if history:
                entered.set()
                await asyncio.sleep(60)
            return await super().decide(observation, history)

    provider = PartialProvider(close_mode="failed")
    own(monkeypatch, provider)
    task = asyncio.create_task(rollout(RunConfig(environment_id="crm-merge"), 0))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    episode = await task
    assert episode["status"] == episode["termination"] == "cancelled"
    assert episode["error"] == "episode cancelled" and episode["steps"] == 1
    assert episode["provider_cleanup"]["status"] == "failed"
    assert provider.close_calls == 1 and replay(episode)["verified"]


async def test_replay_requires_cleanup_evidence_for_new_outcome(monkeypatch):
    own(monkeypatch, LifecycleProvider(close_mode="failed"))
    episode = await rollout(RunConfig(environment_id="crm-merge"), 0)
    for mutation in ("missing", "status", "error", "schema", "reward", "passed", "completed"):
        tampered = copy.deepcopy(episode)
        if mutation == "missing":
            del tampered["provider_cleanup"]
        elif mutation == "completed":
            tampered["status"] = "completed"
        elif mutation in {"reward", "passed"}:
            tampered[mutation] = 1 if mutation == "reward" else True
        else:
            tampered["provider_cleanup"][mutation] = "forged"
        with pytest.raises(ValueError):
            replay(tampered)


async def test_store_terminal_update_failure_still_releases_admission(tmp_path, monkeypatch):
    store = Store(tmp_path / "write.sqlite3")
    manager = RunManager(store)
    original = store.update_run

    def fail_terminal(run_id, status, **kwargs):
        if status == "completed":
            raise OSError("write failed")
        return original(run_id, status, **kwargs)

    monkeypatch.setattr(store, "update_run", fail_terminal)
    run = manager.submit(RunConfig(environment_id="crm-merge", episodes=1), LifecycleProvider())
    with pytest.raises(OSError):
        await manager.wait(run["id"])
    assert not manager.jobs
    await manager.close()
    replacement = RunManager(Store(store.path))
    assert replacement.store.get_run(run["id"])["status"] == "interrupted"
    await replacement.close()


async def test_cleanup_method_lookup_error_is_redacted_and_terminal(tmp_path):
    class BrokenCloseProvider(ScriptedProvider):
        @property
        def close(self):
            raise RuntimeError(SECRET)

    manager = RunManager(Store(tmp_path / "lookup.sqlite3"))
    try:
        run = manager.submit(RunConfig(environment_id="crm-merge", episodes=1), BrokenCloseProvider())
        result = await manager.wait(run["id"])
        assert result["status"] == "failed" and result["episodes"][0]["passed"]
        assert not manager.jobs and SECRET not in str(result)
    finally:
        await manager.close()
