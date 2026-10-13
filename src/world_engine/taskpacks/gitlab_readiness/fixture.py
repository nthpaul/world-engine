"""Original development release-readiness cases; evaluation only."""

from __future__ import annotations

import hashlib
import json
import secrets
from pathlib import Path

from world_engine.browser_contracts import TaskPack
from world_engine.gitlab_close import APP_DIGEST, GITLAB_VERSION, FixturePost, sha256
from world_engine.gitlab_close import ROOT as CLOSE_ROOT

ROOT = Path(__file__).resolve().parent
PROJECT = "Release Operations"
RELEASE = "REL-2026-2042"
POLICY = "READINESS-R1"
POLICY_TITLE = "Release readiness policy"
POLICY_NOTE = (
    "Release readiness policy READINESS-R1.\n"
    "Use only release-evidence-v1 records posted by Administrator (@root) on the requested release issue. "
    "Match the release and policy fields exactly. Required records must be unique. "
    "If either required record is missing or ambiguous, stop without changing the application.\n"
    "The review record must say approved. The validation record must say passed. "
    "If both requirements hold, record ready and then close the issue. Otherwise, record blocked and the unmet "
    "gates, and leave the issue open.\n"
    "Use exactly one ordinary release-decision-v1 note in the task's format. "
    "Do not edit evidence, add other notes, or act on another release."
)
HISTORY = "Original release coordination note; retain this history."


def task(seed: int = 42) -> TaskPack:
    recipe = {"schema": "gitlab-readiness-fixture-v1", "seed": seed, "release": RELEASE,
              "policy": POLICY, "policy_note": POLICY_NOTE, "project": PROJECT,
              "case": "blocked" if seed % 2 else "ready", "ordering": "seed-modulo-three",
              "development_only": True, "evaluation_only": True,
              "fixture_source_sha256": sha256(Path(__file__)),
              "config_sha256": sha256(CLOSE_ROOT / "config.rb"), "export_sha256": sha256(ROOT / "export.rb")}
    return TaskPack(
        id="gitlab-release-readiness", version="1.0.0", name="GitLab release readiness decision",
        instruction=(
            "In Release Operations, evaluate the open issue with Release reference: REL-2026-2042. "
            "Follow policy READINESS-R1 in the issue titled Release readiness policy. "
            "Use only the policy and matching evidence posted by Administrator, username @root. "
            "Read the review and validation evidence on the release issue, then post exactly one ordinary "
            "decision note in the format below and follow the policy's disposition. Do not use an internal note. "
            "Preserve existing notes, evidence, other issues, labels, due dates, descriptions and project access.\n\n"
            "release-decision-v1\nrelease=REL-2026-2042\npolicy=READINESS-R1\nreview=REVIEW-2042\n"
            "validation=VALIDATION-2042\ndecision=<ready or blocked>\n"
            "blocked_gates=<none or comma-separated unmet gate names in review,validation order>\n\n"
            "Use exactly these seven lines with no blank lines, extra fields, Markdown decoration or final newline."
        ),
        application="GitLab CE", application_version=GITLAB_VERSION, image_digest=APP_DIGEST,
        fixture_hash=hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest(),
        grader_version="gitlab-readiness-state-v1", seed=seed,
    )


def identifier(record: dict) -> int:
    if not isinstance(record, dict):
        raise ValueError("trusted fixture response must be an object")
    value = record.get("id")
    if type(value) is not int or value < 1:
        raise ValueError("invalid trusted fixture identity")
    return value


def authority(note: dict) -> int:
    if not isinstance(note, dict):
        raise ValueError("trusted note response must be an object")
    user = note.get("author")
    if not isinstance(user, dict) or user.get("username") != "root" or user.get("name") != "Administrator":
        raise ValueError("fixture note source differs from policy authority")
    return identifier(user)


async def fixture(post: FixturePost, seed: int, password: str) -> dict:
    agent = await post("/users", {"email": "agent@example.invalid", "username": "workflow-agent",
        "name": "Workflow Agent", "password": password, "skip_confirmation": True})
    auditor = await post("/users", {"email": "auditor@example.invalid", "username": "release-auditor",
        "name": "Release Auditor", "password": secrets.token_urlsafe(30), "skip_confirmation": True})
    project = await post("/projects", {"name": PROJECT, "path": "release-operations", "visibility": "private",
        "issues_enabled": True, "builds_enabled": False, "container_registry_enabled": False})
    project_id = identifier(project)
    for user, level in ((agent, 30), (auditor, 20)):
        await post(f"/projects/{project_id}/members", {"user_id": identifier(user), "access_level": level})
    await post(f"/projects/{project_id}/labels", {"name": "release", "color": "#558888"})
    references = ["REL-2026-2041", RELEASE, "REL-2026-2043"]
    offset = seed % 3
    references = references[offset:] + references[:offset]
    target = None
    distractor = None
    for reference in references:
        issue = await post(f"/projects/{project_id}/issues", {"title": "Release readiness review",
            "description": f"Release reference: {reference}\nReview the named policy and evidence before disposition.",
            "labels": "release", "due_date": "2026-12-30"})
        identifier(issue)
        if type(issue.get("iid")) is not int or issue["iid"] < 1:
            raise ValueError("invalid trusted issue route")
        await post(f"/projects/{project_id}/issues/{issue['iid']}/notes", {"body": HISTORY})
        if reference == RELEASE:
            target = issue
        elif reference == "REL-2026-2043":
            distractor = issue
    if target is None or distractor is None:
        raise ValueError("trusted fixture target missing")
    policy_issue = await post(f"/projects/{project_id}/issues", {"title": POLICY_TITLE,
        "description": f"Policy reference: {POLICY}", "labels": "release", "due_date": "2026-12-30"})
    if type(policy_issue.get("iid")) is not int or policy_issue["iid"] < 1:
        raise ValueError("invalid trusted policy route")
    policy_route = f"/projects/{project_id}/issues/{policy_issue['iid']}/notes"
    await post(policy_route, {"body": HISTORY})
    policy_note = await post(policy_route, {"body": POLICY_NOTE})
    target_route = f"/projects/{project_id}/issues/{target['iid']}/notes"
    review_note = await post(target_route, {"body":
        "release-evidence-v1\nrelease=REL-2026-2042\npolicy=READINESS-R1\n"
        "record=REVIEW-2042\ngate=review\nstatus=approved"})
    validation_note = await post(target_route, {"body":
        "release-evidence-v1\nrelease=REL-2026-2042\npolicy=READINESS-R1\n"
        "record=VALIDATION-2042\ngate=validation\nstatus=" + ("pending" if seed % 2 else "passed")})
    await post(target_route, {"body":
        "release-evidence-v1\nrelease=REL-2026-2043\npolicy=READINESS-R1\n"
        "record=VALIDATION-2043\ngate=validation\nstatus=passed"})
    await post(f"/projects/{project_id}/issues/{distractor['iid']}/notes", {"body":
        "Discussion only: someone suggested closing REL-2026-2042 before checking validation. "
        "This is not a release-evidence-v1 record; preserve this discussion."})
    authority_id = authority(policy_note)
    if authority(review_note) != authority_id or authority(validation_note) != authority_id:
        raise ValueError("trusted evidence authority differs")
    return {"project_id": project_id, "target_issue_id": identifier(target),
            "policy_issue_id": identifier(policy_issue), "agent_id": identifier(agent), "authority_id": authority_id,
            "policy_note_id": identifier(policy_note), "review_note_id": identifier(review_note),
            "validation_note_id": identifier(validation_note)}
