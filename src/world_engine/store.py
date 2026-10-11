from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from world_engine.models import JsonObject, RunConfig, canonical_json, digest, utc_now


class Store:
    """SQLite WAL owner. Completed episodes and lifecycle events cannot be edited via SQL."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as connection:
            connection.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, config TEXT NOT NULL, status TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    elapsed_seconds REAL NOT NULL DEFAULT 0, started_at REAL, error TEXT
                );
                CREATE INDEX IF NOT EXISTS runs_created_at ON runs(created_at DESC,id DESC);
                CREATE TABLE IF NOT EXISTS episodes (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                    episode_index INTEGER NOT NULL, scenario_id TEXT NOT NULL,
                    data TEXT NOT NULL, content_hash TEXT NOT NULL,
                    reward REAL NOT NULL, passed INTEGER NOT NULL, steps INTEGER NOT NULL,
                    elapsed_seconds REAL NOT NULL, status TEXT NOT NULL,
                    UNIQUE(run_id, episode_index)
                );
                CREATE INDEX IF NOT EXISTS episodes_scenario ON episodes(scenario_id);
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(id), status TEXT NOT NULL, at TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS episodes_no_update BEFORE UPDATE ON episodes
                    BEGIN SELECT RAISE(ABORT, 'episode records are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS episodes_no_delete BEFORE DELETE ON episodes
                    BEGIN SELECT RAISE(ABORT, 'episode records are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
                    BEGIN SELECT RAISE(ABORT, 'lifecycle events are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
                    BEGIN SELECT RAISE(ABORT, 'lifecycle events are append-only'); END;
            """)
        self.path.chmod(0o600)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def recover(self) -> int:
        with self.connect() as connection:
            rows = connection.execute("SELECT id FROM runs WHERE status IN ('queued','running')").fetchall()
            for row in rows:
                at = utc_now()
                connection.execute("UPDATE runs SET status='interrupted', updated_at=?, error=? WHERE id=?", (at, "process stopped before completion; completed episodes preserved", row["id"]))
                connection.execute("INSERT INTO events(run_id,status,at) VALUES (?,?,?)", (row["id"], "interrupted", at))
        return len(rows)

    def create_run(self, run_id: str, config: RunConfig) -> JsonObject:
        at = utc_now()
        with self.connect() as connection:
            connection.execute("INSERT INTO runs(id,config,status,created_at,updated_at) VALUES (?,?,?,?,?)", (run_id, canonical_json(config.model_dump()), "queued", at, at))
            connection.execute("INSERT INTO events(run_id,status,at) VALUES (?,?,?)", (run_id, "queued", at))
        return self.get_run(run_id)

    def update_run(self, run_id: str, status: str, *, elapsed: float | None = None, error: str | None = None) -> None:
        at = utc_now()
        with self.connect() as connection:
            if elapsed is None:
                connection.execute("UPDATE runs SET status=?,updated_at=?,error=? WHERE id=?", (status, at, error, run_id))
                if status == "running":
                    connection.execute("UPDATE runs SET started_at=? WHERE id=?", (time.time(), run_id))
            else:
                connection.execute("UPDATE runs SET status=?,updated_at=?,elapsed_seconds=?,error=? WHERE id=?", (status, at, elapsed, error, run_id))
            connection.execute("INSERT INTO events(run_id,status,at) VALUES (?,?,?)", (run_id, status, at))

    def append_episode(self, run_id: str, episode: JsonObject) -> None:
        encoded = canonical_json(episode)
        with self.connect() as connection:
            connection.execute("INSERT INTO episodes(id,run_id,episode_index,scenario_id,data,content_hash,reward,passed,steps,elapsed_seconds,status) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (episode["id"], run_id, episode["index"], episode["scenario_id"], encoded, digest(episode), episode["reward"], int(episode["passed"]), episode["steps"], episode["elapsed_seconds"], episode["status"]))
            connection.execute("UPDATE runs SET updated_at=? WHERE id=?", (utc_now(), run_id))

    def episodes(self, run_id: str) -> list[JsonObject]:
        with self.connect() as connection:
            rows = connection.execute("SELECT data,content_hash FROM episodes WHERE run_id=? ORDER BY episode_index", (run_id,)).fetchall()
        episodes = []
        for row in rows:
            episode = json.loads(row["data"])
            if digest(episode) != row["content_hash"]:
                raise ValueError("stored episode integrity check failed")
            episodes.append(episode)
        return episodes

    def candidates(self, scenario_id: str) -> list[JsonObject]:
        with self.connect() as connection:
            rows = connection.execute("SELECT data,content_hash FROM episodes WHERE scenario_id=? ORDER BY run_id,episode_index LIMIT 1000", (scenario_id,)).fetchall()
        result = []
        for row in rows:
            episode = json.loads(row["data"])
            if digest(episode) != row["content_hash"]:
                raise ValueError("stored episode integrity check failed")
            result.append(episode)
        return result

    def get_run(self, run_id: str, *, detail: bool = False) -> JsonObject:
        with self.connect() as connection:
            row = connection.execute(self.summary_query + " WHERE runs.id=? GROUP BY runs.id", (run_id,)).fetchone()
        if row is None:
            raise KeyError("run not found")
        result = self.summary(row)
        if detail:
            result["episodes"] = self.episodes(run_id)
            with self.connect() as connection:
                result["events"] = [dict(row) for row in connection.execute("SELECT sequence,status,at FROM events WHERE run_id=? ORDER BY sequence", (run_id,))]
        return result

    summary_query = """SELECT runs.*, COUNT(episodes.id) AS episode_count,
        COALESCE(SUM(episodes.passed),0) AS pass_count, COALESCE(SUM(episodes.steps),0) AS step_count,
        COALESCE(AVG(episodes.reward),0) AS average_reward
        FROM runs LEFT JOIN episodes ON episodes.run_id=runs.id"""

    def summary(self, row: sqlite3.Row) -> JsonObject:
        config = json.loads(row["config"])
        count, passed = row["episode_count"], row["pass_count"]
        elapsed = max(0, time.time() - row["started_at"]) if row["status"] == "running" and row["started_at"] else row["elapsed_seconds"]
        result = {
            "id": row["id"], "label": config["label"], "status": row["status"],
            "created_at": row["created_at"], "updated_at": row["updated_at"], "config": config,
            "total_episodes": config["episodes"], "completed_episodes": count, "passed_episodes": passed,
            "failed_episodes": count - passed, "mean_reward": row["average_reward"],
            "success_rate": passed / count if count else 0, "elapsed_seconds": elapsed,
            "steps_per_second": row["step_count"] / elapsed if elapsed else 0,
            "error": row["error"],
        }
        return result

    def list_runs(self, limit: int = 50, offset: int = 0) -> list[JsonObject]:
        with self.connect() as connection:
            rows = connection.execute("""SELECT runs.*, COUNT(episodes.id) AS episode_count,
                COALESCE(SUM(episodes.passed),0) AS pass_count, COALESCE(SUM(episodes.steps),0) AS step_count,
                COALESCE(AVG(episodes.reward),0) AS average_reward
                FROM (SELECT * FROM runs ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?) AS runs
                LEFT JOIN episodes ON episodes.run_id=runs.id
                GROUP BY runs.id ORDER BY runs.created_at DESC,runs.id DESC""", (limit, offset)).fetchall()
        return [self.summary(row) for row in rows]
