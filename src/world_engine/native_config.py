from typing import Literal

from pydantic import field_validator

from world_engine.models import RunConfig


class NativeRunConfig(RunConfig):
    """Explicit evaluation-only API entrypoints for the existing native protocols."""

    provider_id: Literal["local-tools", "local-tools-ledger"] = "local-tools"
    evaluation_only: Literal[True] = True

    @field_validator("evaluation_only", mode="before")
    @classmethod
    def native_evaluation_only(cls, value: bool) -> bool:
        if type(value) is not bool or value is not True:
            raise ValueError("native provider entrypoints require evaluation_only=true")
        return value
