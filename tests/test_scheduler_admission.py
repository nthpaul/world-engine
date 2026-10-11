import asyncio
import fcntl
import importlib

import pytest

from world_engine.models import RunConfig
from world_engine.rollout import RunManager

module = importlib.import_module("world_engine.rollout")


class FakeStore:
    def __init__(self, path, *, fail_recover=False):
        self.path = path
        self.fail_recover = fail_recover
        self.recover_calls = 0
        self.runs = {}
        self.episodes = []

    def recover(self):
        self.recover_calls += 1
        if self.fail_recover:
            self.fail_recover = False
            raise RuntimeError("mock recovery failure")

    def create_run(self, run_id, config):
        self.runs[run_id] = {"id": run_id, "status": "queued"}
        return self.runs[run_id].copy()

    def update_run(self, run_id, status, **kwargs):
        self.runs[run_id]["status"] = status

    def append_episode(self, run_id, episode):
        self.episodes.append((run_id, episode))

    def get_run(self, run_id, **kwargs):
        return self.runs[run_id].copy()


@pytest.mark.parametrize("budget", [0, -1, True, False, 1.5, "1", 9, 100, None])
def test_invalid_budget_rejected_before_open_lock_or_recovery(tmp_path, monkeypatch, budget):
    store = FakeStore(tmp_path / "mock.sqlite3")

    def forbidden(*args, **kwargs):
        pytest.fail("invalid scheduler budget must not open a lease or recover the store")

    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr(store, "recover", forbidden)
    with pytest.raises(ValueError, match="global_concurrency"):
        RunManager(store, global_concurrency=budget)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("budget", [1, 8])
async def test_legal_budget_bounds_mock_episodes_across_batches(tmp_path, monkeypatch, budget):
    store = FakeStore(tmp_path / "mock.sqlite3")
    active = peak = 0

    async def short_rollout(config, index, provider):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(.005)
            return {"status": "completed", "index": index}
        finally:
            active -= 1

    monkeypatch.setattr(module, "rollout", short_rollout)
    manager = RunManager(store, global_concurrency=budget)
    try:
        runs = [manager.submit(RunConfig(environment_id="crm-merge", episodes=8, concurrency=8), object())
                for _ in range(2)]
        results = await asyncio.gather(*(manager.wait(run["id"]) for run in runs))
        assert all(run["status"] == "completed" for run in results)
        assert peak == budget and active == 0 and len(store.episodes) == 16
        assert store.recover_calls == 1 and not manager.jobs
    finally:
        await manager.close()


def test_recovery_failure_explicitly_releases_lease_with_traceback_alive(tmp_path):
    store = FakeStore(tmp_path / "recover.sqlite3", fail_recover=True)
    with pytest.raises(RuntimeError, match="mock recovery failure") as failure:
        RunManager(store)
    # Keeping the failure traceback retains the partially constructed manager.
    assert failure.value.__traceback__ is not None
    with open(str(store.path) + ".lock", "a+") as lease:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
    replacement = RunManager(store)
    replacement.owner_lock.close()
    assert store.recover_calls == 2


def test_semaphore_construction_failure_explicitly_releases_lease(tmp_path, monkeypatch):
    store = FakeStore(tmp_path / "semaphore.sqlite3")

    def failing_semaphore(value):
        raise RuntimeError("mock semaphore failure")

    monkeypatch.setattr(module.asyncio, "Semaphore", failing_semaphore)
    with pytest.raises(RuntimeError, match="mock semaphore failure") as failure:
        RunManager(store)
    assert failure.value.__traceback__ is not None
    with open(str(store.path) + ".lock", "a+") as lease:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert store.recover_calls == 1


@pytest.mark.parametrize("error", [OSError("mock lock failure"), KeyboardInterrupt("mock interrupted setup")])
def test_lock_setup_failure_closes_open_lease_before_recovery(tmp_path, monkeypatch, error):
    store = FakeStore(tmp_path / "lock-error.sqlite3")
    leases = []

    def fail_lock(lease, flags):
        leases.append(lease)
        raise error

    monkeypatch.setattr(module.fcntl, "flock", fail_lock)
    with pytest.raises(type(error), match="mock") as failure:
        RunManager(store)
    assert failure.value.__traceback__ is not None
    assert len(leases) == 1 and leases[0].closed
    assert store.recover_calls == 0


def test_recovery_base_exception_closes_acquired_lease(tmp_path, monkeypatch):
    store = FakeStore(tmp_path / "recovery-interrupt.sqlite3")

    def interrupt():
        raise KeyboardInterrupt("mock recovery interrupt")

    monkeypatch.setattr(store, "recover", interrupt)
    with pytest.raises(KeyboardInterrupt, match="mock recovery interrupt") as failure:
        RunManager(store)
    assert failure.value.__traceback__ is not None
    with open(str(store.path) + ".lock", "a+") as lease:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_owner_conflict_message_and_existing_owner_lease_preserved(tmp_path):
    store = FakeStore(tmp_path / "owned.sqlite3")
    owner = RunManager(store)
    try:
        with pytest.raises(RuntimeError, match="database already owned by a running scheduler"):
            RunManager(store)
        assert not owner.owner_lock.closed and store.recover_calls == 1
    finally:
        owner.owner_lock.close()
