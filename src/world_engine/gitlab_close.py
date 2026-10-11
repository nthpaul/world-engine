"""Versioned close-task recipe; controller credentials never enter observations."""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Awaitable, Callable
from pathlib import Path

from .browser_contracts import TaskPack

GITLAB_VERSION = "19.4.1"
APP_DIGEST = "sha256:7fff8748a25202c1d38885797510afe055f555856f3f50c2b17466a853be5d24"
ROOT = Path(__file__).resolve().parent / "taskpacks" / "gitlab"
COMMENT = "Release checklist verified; ready for closure."
MARKER = "Deployment reference: REL-2026-1042"
FixturePost = Callable[[str, dict], Awaitable[dict]]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gitlab_task(seed: int = 42) -> TaskPack:
    fixture = json.dumps({
        "marker": MARKER, "comment": COMMENT, "comment_internal": False,
        "schema": "gitlab-fixture-v1", "seed": seed,
        "ordering": "rotate-three-descriptions-by-seed-modulo-three",
        "project": "Release Operations", "agent_role": 30, "auditor_role": 20,
        "issue_count": 3, "existing_note": "Original release coordination note; retain this history.",
        "fixture_source_sha256": sha256(Path(__file__)),
        "config_sha256": sha256(ROOT / "config.rb"), "export_sha256": sha256(ROOT / "export.rb"),
    }, sort_keys=True)
    return TaskPack(
        id="gitlab-issue-close", version="1.0.3", name="GitLab release issue closure",
        instruction=(f"In Release Operations, find the open issue whose description says {MARKER}. "
                     f"Add exactly this comment: {COMMENT} Then close that issue. "
                     "Use an ordinary comment, not an internal note. Leave other issues, "
                     "existing comments and project access unchanged."),
        application="GitLab CE", application_version=GITLAB_VERSION, image_digest=APP_DIGEST,
        fixture_hash=hashlib.sha256(fixture.encode()).hexdigest(), grader_version="gitlab-state-v3", seed=seed,
    )


async def fixture(post: FixturePost, seed: int, password: str) -> dict:
    agent = await post("/users", {"email": "agent@example.invalid", "username": "workflow-agent",
                                "name": "Workflow Agent", "password": password, "skip_confirmation": True})
    auditor = await post("/users", {"email": "auditor@example.invalid", "username": "release-auditor",
                                  "name": "Release Auditor", "password": secrets.token_urlsafe(30),
                                  "skip_confirmation": True})
    project = await post("/projects", {"name": "Release Operations", "path": "release-operations",
                                     "visibility": "private", "issues_enabled": True,
                                     "builds_enabled": False, "container_registry_enabled": False})
    project_id = project["id"]
    await post(f"/projects/{project_id}/members", {"user_id": agent["id"], "access_level": 30})
    await post(f"/projects/{project_id}/members", {"user_id": auditor["id"], "access_level": 20})
    descriptions = ["Deployment reference: REL-2026-1041", MARKER, "Deployment reference: REL-2026-1043"]
    offset = seed % 3
    descriptions = descriptions[offset:] + descriptions[:offset]
    target = None
    for description in descriptions:
        issue = await post(f"/projects/{project_id}/issues", {
            "title": "Release checklist review", "description": f"{description}\nReview the release checklist before closing."})
        await post(f"/projects/{project_id}/issues/{issue['iid']}/notes",
                   {"body": "Original release coordination note; retain this history."})
        if description == MARKER:
            target = issue["id"]
    return {"project_id": project_id, "target_issue_id": target, "agent_id": agent["id"], "comment": COMMENT}
