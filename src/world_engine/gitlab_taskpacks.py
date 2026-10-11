"""Trusted, immutable registration for the two built-in GitLab task recipes."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from .browser_contracts import BrowserError, TaskPack
from .gitlab_close import ROOT as CLOSE_ROOT
from .gitlab_close import FixturePost, gitlab_task, sha256
from .gitlab_close import fixture as close_fixture
from .taskpacks.gitlab_triage.fixture import ROOT as TRIAGE_ROOT
from .taskpacks.gitlab_triage.fixture import fixture as triage_fixture
from .taskpacks.gitlab_triage.fixture import task as triage_task


@dataclass(frozen=True)
class GitLabPackDefinition:
    task_id: str
    version: str
    family: str
    public_task: Callable[[int], TaskPack]
    fixture: Callable[[FixturePost, int, str], Awaitable[dict]]
    recipe_path: Path
    export_path: Path
    verifier_path: Path
    verifier_recipe_path: Path
    sealed_schema: str

    def provenance(self, seed: int) -> dict:
        case = "already-correct" if self.task_id == "gitlab-incident-triage" and seed % 2 else "changes-required"
        return {"task_family": self.family, "task_case": case,
                "lineage_id": hashlib.sha256(f"{self.family}:{case}:{seed}".encode()).hexdigest(),
                "pack_version": self.version, "pack_sources": {
                    "recipe_sha256": sha256(self.recipe_path), "export_sha256": sha256(self.export_path),
                    "verifier_sha256": sha256(self.verifier_path), "verifier_build_sha256": sha256(self.verifier_recipe_path)},
                "source_rights": {"task_origin": "original local fixture", "benchmark_imported": False,
                                  "application_source_url": "https://gitlab.com/gitlab-org/gitlab-foss",
                                  "application_license": "GitLab CE MIT; dependency/image licenses separate",
                                  "permitted_use": "evaluation-only", "training_eligible": False}}


_PACKS = (
    GitLabPackDefinition("gitlab-issue-close", "1.0.3", "release-closure", gitlab_task, close_fixture,
                         Path(__file__).with_name("gitlab_close.py"), CLOSE_ROOT / "export.rb", CLOSE_ROOT / "verify.py",
                         CLOSE_ROOT / "verifier.Dockerfile", "world-engine-gitlab-sealed-v1"),
    GitLabPackDefinition("gitlab-incident-triage", "1.0.0", "incident-triage", triage_task, triage_fixture,
                         TRIAGE_ROOT / "fixture.py", TRIAGE_ROOT / "export.rb", TRIAGE_ROOT / "verify.py",
                         TRIAGE_ROOT / "verifier.Dockerfile", "world-engine-gitlab-triage-sealed-v1"),
)


def resolve_gitlab_pack(task_id: str) -> GitLabPackDefinition:
    for pack in _PACKS:
        if pack.task_id == task_id:
            return pack
    raise BrowserError("unsupported GitLab task pack")


def make_browser_task(task_id: str, seed: int) -> TaskPack:
    return resolve_gitlab_pack(task_id).public_task(seed)


def gitlab_catalog() -> dict[str, TaskPack]:
    return {pack.task_id: pack.public_task(42) for pack in _PACKS}
