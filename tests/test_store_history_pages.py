import importlib
import sqlite3
from contextlib import contextmanager

import pytest

from world_engine.models import RunConfig, canonical_json, digest
from world_engine.store import Store

module = importlib.import_module("world_engine.store")


@pytest.fixture
def history(tmp_path, monkeypatch):
    store = Store(tmp_path / "history.sqlite3")
    monkeypatch.setattr(module.time, "time", lambda: 500.0)
    config = canonical_json(RunConfig(environment_id="crm-merge", episodes=5, label="fixture").model_dump())
    expected_order, counts = [], {}
    with store.connect() as connection:
        for index in range(120):
            run_id = f"run-{index:03}"
            created = f"2026-10-{index % 4 + 1:02}T12:00:00+00:00"
            status = ("running", "completed", "failed")[index % 3]
            connection.execute("INSERT INTO runs(id,config,status,created_at,updated_at,elapsed_seconds,started_at,error) VALUES(?,?,?,?,?,?,?,?)",
                               (run_id, config, status, created, created, 10.0, 400.0,
                                "mock failure" if status == "failed" else None))
            expected_order.append((created, run_id))
            counts[run_id] = 0 if index == 0 else 5
            for episode_index in range(counts[run_id]):
                episode = {"id": f"episode-{index:03}-{episode_index}", "index": episode_index,
                           "scenario_id": "mock-scenario", "passed": episode_index % 2 == 0,
                           "reward": episode_index / 4, "steps": episode_index + 1,
                           "elapsed_seconds": .25, "status": "completed" if episode_index % 2 == 0 else "failed"}
                connection.execute("INSERT INTO episodes VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                   (episode["id"], run_id, episode_index, episode["scenario_id"], canonical_json(episode),
                                    digest(episode), episode["reward"], int(episode["passed"]), episode["steps"],
                                    episode["elapsed_seconds"], episode["status"]))
    return store, [run_id for _, run_id in sorted(expected_order, reverse=True)], counts


@pytest.mark.parametrize("limit,offset", [(7, 0), (7, 9), (7, 117), (7, 120), (1, 119), (50, 0)])
def test_history_page_order_and_summary_match_single_run(history, limit, offset):
    store, ordered, _ = history
    page = store.list_runs(limit, offset)
    expected_ids = ordered[offset:offset + limit]
    assert [run["id"] for run in page] == expected_ids
    assert page == [store.get_run(run_id) for run_id in expected_ids]


def test_default_and_successive_pages_have_no_duplicate_or_missing_runs(history):
    store, ordered, _ = history
    assert [run["id"] for run in store.list_runs()] == ordered[:50]
    pages = [store.list_runs(13, offset) for offset in range(0, 130, 13)]
    assert [run["id"] for page in pages for run in page] == ordered


def test_zero_episode_and_mixed_aggregates_preserve_existing_shape(history):
    store, _, _ = history
    runs = {run["id"]: run for run in store.list_runs(120)}
    empty = runs["run-000"]
    assert empty["completed_episodes"] == empty["passed_episodes"] == empty["failed_episodes"] == 0
    assert empty["mean_reward"] == empty["success_rate"] == empty["steps_per_second"] == 0
    assert empty["elapsed_seconds"] == 100
    mixed = runs["run-001"]
    assert mixed["completed_episodes"] == 5 and mixed["passed_episodes"] == 3 and mixed["failed_episodes"] == 2
    assert mixed["mean_reward"] == .5 and mixed["success_rate"] == .6
    assert mixed["elapsed_seconds"] == 10 and mixed["steps_per_second"] == 1.5
    assert set(mixed) == {"id", "label", "status", "created_at", "updated_at", "config", "total_episodes",
                          "completed_episodes", "passed_episodes", "failed_episodes", "mean_reward", "success_rate",
                          "elapsed_seconds", "steps_per_second", "error"}


@pytest.mark.parametrize("limit,offset", [(7, 9), (1, 119), (7, 120)])
def test_only_selected_page_episode_ids_are_visited(history, monkeypatch, limit, offset):
    store, ordered, counts = history
    visited = []
    original_connect = store.connect

    def visit(episode_id):
        if episode_id is not None:
            visited.append(episode_id)
        return episode_id

    @contextmanager
    def instrumented():
        with original_connect() as connection:
            connection.create_function("visit", 1, visit)
            # Shadow only this connection's episode table; every COUNT input
            # records a real joined row without parsing raw episode JSON.
            connection.execute("""CREATE TEMP VIEW episodes AS
                SELECT visit(id) AS id, run_id, passed, steps, reward FROM main.episodes""")
            yield connection

    monkeypatch.setattr(store, "connect", instrumented)
    page = store.list_runs(limit, offset)
    selected = ordered[offset:offset + limit]
    assert [run["id"] for run in page] == selected
    assert len(visited) == sum(counts[run_id] for run_id in selected)
    expected_ids = {f"episode-{run_id.removeprefix('run-')}-{index}" for run_id in selected
                    for index in range(counts[run_id])}
    assert set(visited) == expected_ids


def test_reopen_migrates_ordered_index_idempotently_and_preserves_data(history):
    store, ordered, _ = history
    before = store.list_runs(120)
    with store.connect() as connection:
        connection.execute("DROP INDEX runs_created_at")
    for _ in range(2):
        reopened = Store(store.path)
        with reopened.connect() as connection:
            index = connection.execute("PRAGMA index_xinfo(runs_created_at)").fetchall()
            fields = [(row["name"], row["desc"]) for row in index if row["key"]]
            assert fields == [("created_at", 1), ("id", 1)]
            assert connection.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == 595
        assert reopened.list_runs(120) == before
        assert [run["id"] for run in reopened.list_runs(7, 9)] == ordered[9:16]


def test_index_addition_preserves_append_only_guards(history):
    store, _, _ = history
    Store(store.path)
    with store.connect() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("UPDATE episodes SET reward=1")
