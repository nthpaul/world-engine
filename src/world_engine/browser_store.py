"""Durable browser attempt journals with a separate rebuildable SQLite index."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from world_engine.browser_contracts import (
    MAX_ATTEMPT_BYTES,
    MAX_JOURNAL_RECORD_BYTES,
    SCHEMA_VERSION,
    BrowserArtifact,
    BrowserAttemptConfig,
    BrowserError,
    TaskPack,
    relative_artifact_id,
)

ACTIVE_STATUSES = {"queued", "starting", "running", "sealing", "grading"}
TERMINAL_RESERVE_BYTES = 1_048_576


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def content_hash(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def attempt_key(value: str) -> str:
    try:
        key = str(UUID(value))
        if key != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise KeyError("browser attempt not found") from None
    return key


class BrowserStore:
    def __init__(self, directory: Path | str):
        self.root = Path(directory).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / "browser.sqlite3"
        with self.connect() as connection:
            connection.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS attempts (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, status TEXT NOT NULL, summary TEXT NOT NULL
                );
            """)
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def directory(self, attempt_id: str) -> Path:
        return self.root / attempt_key(attempt_id)

    def create(self, attempt_id: str, config: BrowserAttemptConfig, task: TaskPack, provenance: dict) -> dict:
        directory = self.directory(attempt_id)
        directory.mkdir(mode=0o700)
        at = now()
        summary = {"schema": SCHEMA_VERSION, "id": attempt_id, "config": config.model_dump(),
                   "task": task.model_dump(), "provenance": provenance, "created_at": at, "updated_at": at,
                   "status": "queued", "termination": None, "steps": 0, "invalid_actions": 0,
                   "passed": False, "reward": 0.0, "outcome": None, "error": None,
                   "elapsed_seconds": 0.0, "phase_seconds": {}, "cleanup": None}
        self.append(attempt_id, "created", {"summary": summary})
        self._index(summary)
        return summary

    def _index(self, summary: dict) -> None:
        with self.connect() as connection:
            connection.execute("""INSERT INTO attempts VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                updated_at=excluded.updated_at,status=excluded.status,summary=excluded.summary""",
                (summary["id"], summary["created_at"], summary["updated_at"], summary["status"], canonical(summary).decode()))

    def journal(self, attempt_id: str) -> list[dict]:
        path = self.directory(attempt_id) / "journal.jsonl"
        if not path.is_file() or path.is_symlink():
            raise KeyError("browser attempt not found")
        if path.stat().st_size > MAX_ATTEMPT_BYTES:
            raise BrowserError("browser journal exceeds its byte budget")
        records, previous = [], "0" * 64
        with path.open("rb") as source:
            for sequence, line in enumerate(source):
                if len(line) > MAX_JOURNAL_RECORD_BYTES or not line.endswith(b"\n"):
                    raise BrowserError("browser journal is incomplete or oversized")
                try:
                    record = json.loads(line)
                    stored = record.pop("content_hash")
                    if (record["schema"] != SCHEMA_VERSION or record["attempt_id"] != attempt_id
                            or type(record["sequence"]) is not int or record["sequence"] != sequence
                            or record["previous_hash"] != previous or content_hash(record) != stored):
                        raise ValueError
                    record["content_hash"] = stored
                except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
                    raise BrowserError("browser journal integrity check failed") from None
                records.append(record)
                previous = stored
        return records

    def check_quota(self, attempt_id: str, extra: int = 0, *, terminal: bool = False) -> None:
        total = extra
        for path in self.directory(attempt_id).rglob("*"):
            if path.is_symlink():
                raise BrowserError("browser evidence contains a symbolic link")
            if path.is_file():
                total += path.stat().st_size
        budget = MAX_ATTEMPT_BYTES if terminal else MAX_ATTEMPT_BYTES - TERMINAL_RESERVE_BYTES
        if total > budget:
            raise BrowserError("browser attempt exceeds its 128 MiB evidence budget")

    def append(self, attempt_id: str, event: str, data: dict, *, terminal: bool = False) -> dict:
        path = self.directory(attempt_id) / "journal.jsonl"
        records = self.journal(attempt_id) if path.exists() else []
        record = {"schema": SCHEMA_VERSION, "attempt_id": attempt_id, "sequence": len(records), "at": now(),
                  "event": event, "data": data,
                  "previous_hash": records[-1]["content_hash"] if records else "0" * 64}
        record["content_hash"] = content_hash(record)
        encoded = canonical(record) + b"\n"
        if len(encoded) > MAX_JOURNAL_RECORD_BYTES:
            raise BrowserError("browser journal event exceeds its byte budget")
        if terminal and len(encoded) > TERMINAL_RESERVE_BYTES // 2:
            raise BrowserError("browser terminal event exceeds its reserved budget")
        self.check_quota(attempt_id, len(encoded), terminal=terminal)
        descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(descriptor, "ab", closefd=False) as target:
                target.write(encoded)
                target.flush()
                os.fsync(target.fileno())
        finally:
            os.close(descriptor)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return record

    def update(self, attempt_id: str, *, terminal: bool = False, **changes) -> dict:
        summary = self.get(attempt_id)
        summary.update(changes, updated_at=now())
        self.append(attempt_id, "lifecycle", {"summary": summary}, terminal=terminal)
        self._index(summary)
        return summary

    def fail_finalization(self, attempt_id: str, **changes) -> None:
        """Persist uncertainty in the index if the authoritative journal cannot finish."""
        summary = self.get(attempt_id)
        summary.update(changes, updated_at=now(), status="failed", termination="evidence_error",
                       passed=False, reward=0.0, outcome=None, journal_finalization_failed=True,
                       reconciliation_required=True,
                       error="terminal evidence persistence failed; manual reconciliation required")
        self._index(summary)

    def get(self, attempt_id: str, *, detail: bool = False) -> dict:
        attempt_key(attempt_id)
        with self.connect() as connection:
            row = connection.execute("SELECT summary FROM attempts WHERE id=?", (attempt_id,)).fetchone()
        if row is None:
            raise KeyError("browser attempt not found")
        summary = json.loads(row[0])
        if detail:
            summary["journal"] = self.journal(attempt_id)
            summary["artifacts"] = self.artifacts(attempt_id)
        return summary

    def list(self, limit: int = 25, offset: int = 0) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or not 0 <= offset <= 100_000:
            raise ValueError("invalid browser attempt pagination")
        with self.connect() as connection:
            rows = connection.execute("SELECT summary FROM attempts ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?",
                                      (limit, offset)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def recover(self) -> list[str]:
        interrupted = []
        # The journal is authoritative when a crash separates fsync from index publication.
        for directory in self.root.iterdir():
            if not directory.is_dir() or directory.is_symlink():
                continue
            try:
                key = attempt_key(directory.name)
            except KeyError:
                continue
            records = self.journal(key)
            try:
                indexed = self.get(key)
            except KeyError:
                indexed = {}
            if indexed.get("journal_finalization_failed"):
                interrupted.append(key)
                continue
            summaries = [record["data"]["summary"] for record in records if record["event"] in ("created", "lifecycle")]
            if not summaries:
                raise BrowserError("browser attempt has no durable creation record")
            self._index(summaries[-1])
            if summaries[-1].get("reconciliation_required"):
                interrupted.append(key)
            if summaries[-1]["status"] in ACTIVE_STATUSES:
                interrupted.append(key)
                self.update(key, terminal=True, status="interrupted", termination="interrupted", passed=False, reward=0.0,
                            reconciliation_required=True, error="controller stopped; resource reconciliation required")
        return interrupted

    def artifact_path(self, attempt_id: str, artifact_id: str) -> Path:
        relative_artifact_id(artifact_id)
        root = self.directory(attempt_id)
        path = root
        for component in artifact_id.split("/"):
            path = path / component
            if path.is_symlink():
                raise BrowserError("artifact links are not allowed")
        if not path.is_file() or not path.resolve().is_relative_to(root):
            raise KeyError("browser artifact not found")
        return path

    def register_artifact(self, attempt_id: str, artifact: BrowserArtifact) -> None:
        path = self.artifact_path(attempt_id, artifact.id)
        if path.stat().st_size != artifact.size_bytes or hashlib.sha256(path.read_bytes()).hexdigest() != artifact.sha256:
            raise BrowserError("browser artifact integrity check failed")
        self.check_quota(attempt_id)
        existing = self.artifacts(attempt_id)
        if any(row["id"] == artifact.id for row in existing):
            if next(row for row in existing if row["id"] == artifact.id) != artifact.model_dump():
                raise BrowserError("browser artifact identity changed")
            return
        self.append(attempt_id, "artifact", artifact.model_dump())

    def artifacts(self, attempt_id: str) -> list[dict]:
        return [record["data"] for record in self.journal(attempt_id) if record["event"] == "artifact"]

    def artifact(self, attempt_id: str, artifact_id: str) -> tuple[Path, dict]:
        relative_artifact_id(artifact_id)
        descriptor = next((row for row in self.artifacts(attempt_id) if row["id"] == artifact_id), None)
        if descriptor is None:
            raise KeyError("browser artifact not found")
        path = self.artifact_path(attempt_id, artifact_id)
        if path.stat().st_size != descriptor["size_bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != descriptor["sha256"]:
            raise BrowserError("browser artifact integrity check failed")
        return path, descriptor
