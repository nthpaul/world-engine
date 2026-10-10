"""Versioned contracts for the single-controller real-application browser pilot."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Annotated, Callable, Literal, Protocol
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, SecretStr, TypeAdapter, field_validator

SCHEMA_VERSION = "world-engine.browser.v1"
MAX_JOURNAL_RECORD_BYTES = 1_048_576
MAX_ATTEMPT_BYTES = 134_217_728


class BrowserBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


def relative_artifact_id(value: str) -> str:
    path = PurePosixPath(value)
    if (not value or len(value) > 240 or path.is_absolute() or str(path) != value
            or any(part in (".", "..") for part in path.parts)
            or any(not (char.isascii() and (char.isalnum() or char in "-._/")) for char in value)):
        raise ValueError("invalid relative artifact identifier")
    return value


class TaskPack(BrowserBoundary):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$")
    version: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    instruction: str = Field(min_length=1, max_length=16_384)
    application: str = Field(min_length=1, max_length=80)
    application_version: str = Field(min_length=1, max_length=80)
    image_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    fixture_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    grader_version: str = Field(min_length=1, max_length=80)
    seed: int = Field(default=42, ge=0, le=2_147_483_647)
    observation_mode: Literal["AX"] = "AX"
    evaluation_only: Literal[True] = True


class BrowserAttemptConfig(BrowserBoundary):
    task_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$")
    provider_id: Literal["local-browser", "browser-reference", "browser-baseline"] = "local-browser"
    model: str = Field(default="qwen3:8b", min_length=1, max_length=160)
    seed: int = Field(default=42, ge=0, le=2_147_483_647)
    max_steps: int = Field(default=30, ge=1, le=50)
    timeout_seconds: int = Field(default=180, ge=30, le=600)


class Navigate(BrowserBoundary):
    kind: Literal["navigate"] = "navigate"
    url: str = Field(min_length=1, max_length=4096)

    @field_validator("url")
    @classmethod
    def plain_http_url(cls, value: str) -> str:
        try:
            if value != value.strip() or any(not char.isprintable() for char in value):
                raise ValueError
            parsed = urlparse(value)
            if (parsed.scheme not in ("http", "https") or not parsed.hostname
                    or parsed.username is not None or parsed.password is not None
                    or parsed.netloc.endswith(":") or parsed.port is not None and not 1 <= parsed.port <= 65535):
                raise ValueError
        except ValueError:
            raise ValueError("navigation requires a plain HTTP URL") from None
        return value


class Click(BrowserBoundary):
    kind: Literal["click"] = "click"
    bid: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")


class Fill(BrowserBoundary):
    kind: Literal["fill"] = "fill"
    bid: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    text: str = Field(max_length=16_384)


class Press(BrowserBoundary):
    kind: Literal["press"] = "press"
    bid: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    key: Literal["Enter", "Tab", "Escape", "ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "Space"]


class Scroll(BrowserBoundary):
    kind: Literal["scroll"] = "scroll"
    direction: Literal["up", "down", "left", "right"]


class Wait(BrowserBoundary):
    kind: Literal["wait"] = "wait"
    seconds: float = Field(gt=0, le=3)


class Finish(BrowserBoundary):
    kind: Literal["finish"] = "finish"


BrowserAction = Annotated[Navigate | Click | Fill | Press | Scroll | Wait | Finish, Field(discriminator="kind")]
ACTION_ADAPTER = TypeAdapter(BrowserAction)


class BrowserObservation(BrowserBoundary):
    url: str = Field(max_length=4096)
    title: str = Field(max_length=4096)
    accessibility_text: str = Field(max_length=65_536)
    screenshot_artifact_id: str
    observation_mode: Literal["AX"] = "AX"
    image_not_sent_to_model: Literal[True] = True

    _artifact = field_validator("screenshot_artifact_id")(relative_artifact_id)


class BrowserArtifact(BrowserBoundary):
    id: str
    kind: Literal["screenshot", "video", "public_trace"]
    mime_type: Literal["image/png", "image/jpeg", "video/webm", "application/x-ndjson"]
    size_bytes: int = Field(ge=0, le=MAX_ATTEMPT_BYTES)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    _artifact = field_validator("id")(relative_artifact_id)


class VerifierCheck(BrowserBoundary):
    name: str = Field(min_length=1, max_length=160)
    passed: bool
    detail: str = Field(max_length=4096)


class GradeResult(BrowserBoundary):
    passed: bool
    reward: Literal[0.0, 1.0]
    checks: list[VerifierCheck] = Field(min_length=1, max_length=64)
    grader_version: str
    sealed_state_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class CleanupResult(BrowserBoundary):
    status: Literal["completed", "failed", "timeout"]
    error_code: Literal["cleanup_failed", "cleanup_timeout"] | None = None


@dataclass(frozen=True)
class BrowserCredentials:
    username: str = field(repr=False)
    password: SecretStr = field(repr=False)


@dataclass(frozen=True)
class RuntimeHandle:
    instance_id: str
    origin: str
    start_url: str
    artifact_root: Path
    agent_credentials: BrowserCredentials = field(repr=False)
    runtime_metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SealedState:
    path: Path
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class BrowserDecision:
    action: BrowserAction
    evidence: dict = field(default_factory=dict)


class BrowserRuntime(Protocol):
    async def start(self, attempt_id: str, task: TaskPack, directory: Path) -> RuntimeHandle: ...
    async def seal(self, handle: RuntimeHandle) -> SealedState: ...
    async def grade(self, sealed: SealedState, task: TaskPack) -> GradeResult: ...
    async def close(self, handle: RuntimeHandle) -> CleanupResult: ...


class BrowserDriver(Protocol):
    async def prepare(self) -> None: ...
    async def observe(self) -> BrowserObservation: ...
    async def execute(self, action: BrowserAction) -> dict: ...
    async def close(self) -> list[BrowserArtifact]: ...


class BrowserPolicy(Protocol):
    def set_recorder(self, recorder: Callable[[str, dict], None]) -> None: ...
    async def prepare(self) -> None: ...
    async def decide(self, observation: BrowserObservation, history: list[dict]) -> BrowserDecision: ...
    async def close(self) -> None: ...


class BrowserError(RuntimeError):
    """Only generic, public-safe controller errors cross the API boundary."""


class BrowserCleanupError(BrowserError):
    """Provisioning failed and owned resources could not be certified removed."""
