from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

JsonObject = dict[str, Any]
ProviderId = Literal["scripted-oracle", "scripted-baseline", "openai", "anthropic", "local"]
EnvironmentId = Literal["crm-merge", "refund-ops", "incident-control"]
RunStatus = Literal["queued", "running", "completed", "cancelled", "failed", "interrupted"]


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BoundaryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Action(BoundaryModel):
    tool: str = Field(min_length=1, max_length=80)
    args: JsonObject = Field(default_factory=dict)


class RunConfig(BoundaryModel):
    environment_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9-]+$")
    provider_id: ProviderId = "scripted-oracle"
    episodes: int = Field(default=10, ge=1, le=100)
    seed: int = Field(default=42, ge=0, le=2**31 - 101)
    max_steps: int = Field(default=20, ge=1, le=100)
    concurrency: int = Field(default=4, ge=1, le=8)
    model: str | None = Field(default=None, min_length=1, max_length=200)
    allow_paid: bool = False
    timeout_seconds: int = Field(default=60, ge=1, le=300)
    label: str = Field(default="", max_length=120)
    evaluation_only: bool = False

    @field_validator("environment_id")
    @classmethod
    def registered_environment(cls, value: str) -> str:
        from world_engine.environments import ENVIRONMENTS
        if value not in ENVIRONMENTS:
            raise ValueError("environment is not registered by the trusted application")
        return value

    @field_validator("label", "model")
    @classmethod
    def printable(cls, value: str | None) -> str | None:
        if value is not None and any(ord(char) < 32 for char in value):
            raise ValueError("control characters are not allowed")
        return value


class Check(BoundaryModel):
    name: str
    passed: bool
    detail: str


class Grade(BoundaryModel):
    checks: list[Check]
    reward: float
    passed: bool


def grade(checks: list[tuple[str, bool, str]], *, safe: bool = True) -> Grade:
    values = [Check(name=name, passed=bool(passed), detail=detail) for name, passed, detail in checks]
    return Grade(
        checks=values,
        reward=sum(check.passed for check in values) / len(values) if safe else 0.0,
        passed=safe and all(check.passed for check in values),
    )
