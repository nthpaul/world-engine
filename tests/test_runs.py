import asyncio
import copy
import sqlite3

import pytest

from world_engine import Action
from world_engine.exports import export_records
from world_engine.models import RunConfig
from world_engine.providers import Decision
from world_engine.rollout import RunManager, rollout
from world_engine.store import Store


async def test_persistence_export_split_integrity_and_matched_preferences(tmp_path):
    store = Store(tmp_path / "engine.sqlite3")
    manager = RunManager(store)
    runs = []
    try:
        for provider_id in ("scripted-oracle", "scripted-baseline"):
            run = manager.submit(RunConfig(environment_id="crm-merge", provider_id=provider_id, episodes=10, seed=42))
            runs.append(await manager.wait(run["id"]))
        assert runs[0]["success_rate"] == 1
        assert runs[1]["success_rate"] == 0
        records, report = export_records(store, runs[0]["id"], "sft")
        assert records and report["records"] == len(records)
        assert all(record["provenance"]["split"] == "train" for record in records)
        assert all("grader" not in record and "checks" not in record for record in records)
        first = records[0]
        original = next(episode for episode in runs[0]["episodes"] if episode["id"] == first["provenance"]["episode_id"])
        assert first["messages"][:-1] == original["trace"][first["provenance"]["step_index"]]["policy_input"]
        pairs, _ = export_records(store, runs[0]["id"], "dpo")
        assert pairs
        for pair in pairs:
            chosen = next(candidate for candidate in store.candidates(pair["provenance"]["scenario_id"]) if candidate["id"] == pair["chosen_episode_id"])
            rejected = next(candidate for candidate in store.candidates(pair["provenance"]["scenario_id"]) if candidate["id"] == pair["rejected_episode_id"])
            assert chosen["scenario_id"] == rejected["scenario_id"]
            assert chosen["initial_observation"] == rejected["initial_observation"]
            assert chosen["split"] == rejected["split"] == "train"
            assert pair["chosen_reward"] > pair["rejected_reward"]
        groups, _ = export_records(store, runs[0]["id"], "grpo")
        assert groups and all(not group["trainable"] for group in groups)
        assert all(group["learning_signal"] for group in groups)
        with store.connect() as connection:
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                connection.execute("UPDATE episodes SET reward=1")
    finally:
        await manager.close()
    reopened = Store(tmp_path / "engine.sqlite3")
    assert reopened.get_run(runs[0]["id"], detail=True)["episodes"] == runs[0]["episodes"]


async def test_no_unmatched_preference_records(tmp_path):
    manager = RunManager(Store(tmp_path / "engine.sqlite3"))
    try:
        run = manager.submit(RunConfig(environment_id="refund-ops", episodes=3))
        await manager.wait(run["id"])
        records, report = export_records(manager.store, run["id"], "dpo")
        assert records == [] and report["skipped"] == 3
    finally:
        await manager.close()


async def test_evaluation_only_episodes_never_enter_training_exports(tmp_path):
    manager = RunManager(Store(tmp_path / "engine.sqlite3"))
    try:
        run = manager.submit(RunConfig(environment_id="crm-merge", episodes=4, evaluation_only=True))
        await manager.wait(run["id"])
        for format in ("sft", "dpo", "grpo"):
            records, report = export_records(manager.store, run["id"], format, "all")
            assert records == []
            assert report["excluded"]["evaluation_only"] == 4
        records, _ = export_records(manager.store, run["id"], "traces")
        assert len(records) == 4
    finally:
        await manager.close()


async def test_evaluation_only_candidates_cannot_supply_rejected_training_pairs(tmp_path):
    manager = RunManager(Store(tmp_path / "engine.sqlite3"))
    try:
        oracle = manager.submit(RunConfig(environment_id="crm-merge", episodes=10))
        await manager.wait(oracle["id"])
        heldout = manager.submit(RunConfig(environment_id="crm-merge", provider_id="scripted-baseline", episodes=10, evaluation_only=True))
        await manager.wait(heldout["id"])
        for format in ("dpo", "grpo"):
            records, report = export_records(manager.store, oracle["id"], format)
            assert records == []
            assert report["excluded"]["insufficient_alternatives"] > 0
    finally:
        await manager.close()


async def test_admission_bounds_pending_batches(tmp_path, monkeypatch):
    import importlib
    module = importlib.import_module("world_engine.rollout")
    monkeypatch.setattr(module, "MAX_ACTIVE_RUNS", 2)
    manager = RunManager(Store(tmp_path / "engine.sqlite3"))
    try:
        manager.submit(RunConfig(environment_id="crm-merge", episodes=100))
        manager.submit(RunConfig(environment_id="crm-merge", episodes=100))
        with pytest.raises(ValueError, match="admission"):
            manager.submit(RunConfig(environment_id="crm-merge"))
        assert len(manager.jobs) == 2
    finally:
        await manager.close()


async def test_split_lineage_is_stable_when_grader_implementation_changes(monkeypatch):
    import importlib
    module = importlib.import_module("world_engine.rollout")
    config = RunConfig(environment_id="crm-merge", episodes=1)
    initial = await rollout(config, 0)
    monkeypatch.setattr(module, "GRADER_CODE_HASH", "changed-grader-source")
    revised = await rollout(config, 0)
    assert initial["scenario_id"] != revised["scenario_id"]
    assert initial["lineage_id"] == revised["lineage_id"]
    assert initial["split"] == revised["split"]


class SlowProvider:
    active = 0
    maximum = 0

    async def decide(self, observation, history):
        type(self).active += 1
        type(self).maximum = max(type(self).maximum, type(self).active)
        try:
            await asyncio.sleep(.01)
            return Decision(Action(tool="finish"))
        finally:
            type(self).active -= 1


async def test_global_concurrency_budget_across_batches_and_single_writer(tmp_path, monkeypatch):
    import importlib
    module = importlib.import_module("world_engine.rollout")
    monkeypatch.setattr(module, "make_provider", lambda config: SlowProvider())
    SlowProvider.active = SlowProvider.maximum = 0
    store = Store(tmp_path / "engine.sqlite3")
    manager = RunManager(store, global_concurrency=3)
    try:
        runs = [manager.submit(RunConfig(environment_id="crm-merge", episodes=8, concurrency=8)) for _ in range(3)]
        with pytest.raises(RuntimeError, match="already owned"):
            RunManager(Store(store.path))
        assert store.get_run(runs[0]["id"])["status"] == "queued"
        await asyncio.gather(*(manager.wait(run["id"]) for run in runs))
        assert SlowProvider.maximum == 3
    finally:
        await manager.close()
    recovered = RunManager(Store(store.path))
    await recovered.close()


async def test_cancel_before_start_is_terminal_and_idempotent(tmp_path):
    manager = RunManager(Store(tmp_path / "engine.sqlite3"))
    try:
        run = manager.submit(RunConfig(environment_id="crm-merge", episodes=100))
        cancelled = await manager.cancel(run["id"])
        assert cancelled["status"] == "cancelled"
        assert run["id"] not in manager.jobs
        assert (await manager.cancel(run["id"]))["status"] == "cancelled"
    finally:
        await manager.close()


async def test_cancel_inflight_preserves_partial_episode(tmp_path, monkeypatch):
    import importlib
    module = importlib.import_module("world_engine.rollout")
    entered = asyncio.Event()

    class BlockingProvider:
        async def decide(self, observation, history):
            if not history:
                return Decision(Action(tool="inspect"))
            entered.set()
            await asyncio.sleep(60)
            return Decision(Action(tool="finish"))

    monkeypatch.setattr(module, "make_provider", lambda config: BlockingProvider())
    manager = RunManager(Store(tmp_path / "engine.sqlite3"))
    try:
        run = manager.submit(RunConfig(environment_id="crm-merge", episodes=4, concurrency=1))
        await asyncio.wait_for(entered.wait(), 1)
        result = await manager.cancel(run["id"])
        assert result["status"] == "cancelled"
        episodes = manager.store.episodes(run["id"])
        assert len(episodes) == 1
        assert episodes[0]["status"] == "cancelled" and episodes[0]["steps"] == 1
        assert episodes[0]["reward"] == 0
    finally:
        await manager.close()


async def test_restart_recovery_preserves_episodes(tmp_path):
    store = Store(tmp_path / "engine.sqlite3")
    run = store.create_run("crashed", RunConfig(environment_id="crm-merge", episodes=2))
    episode = await rollout(RunConfig(environment_id="crm-merge", episodes=1), 0)
    store.append_episode(run["id"], episode)
    store.update_run(run["id"], "running")
    manager = RunManager(store)
    try:
        recovered = store.get_run(run["id"], detail=True)
        assert recovered["status"] == "interrupted"
        assert recovered["episodes"] == [episode]
    finally:
        await manager.close()


async def test_storage_hash_detects_out_of_band_corruption(tmp_path):
    store = Store(tmp_path / "engine.sqlite3")
    store.create_run("test", RunConfig(environment_id="crm-merge"))
    episode = await rollout(RunConfig(environment_id="crm-merge"), 0)
    store.append_episode("test", episode)
    tampered = copy.deepcopy(episode)
    tampered["reward"] = 123
    with store.connect() as connection:
        connection.execute("DROP TRIGGER episodes_no_update")
        connection.execute("UPDATE episodes SET data=?", (__import__("json").dumps(tampered),))
    with pytest.raises(ValueError, match="integrity"):
        store.episodes("test")
