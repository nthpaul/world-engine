"""Original incident assignment/classification fixture, evaluation only."""

from __future__ import annotations

import hashlib
import json
import secrets
from pathlib import Path

from world_engine.browser_contracts import TaskPack
from world_engine.gitlab_close import APP_DIGEST, GITLAB_VERSION, FixturePost, sha256
from world_engine.gitlab_close import ROOT as CLOSE_ROOT

ROOT = Path(__file__).resolve().parent
MARKER = "Incident reference: INC-2026-0217"
ONCALL = "casey-oncall"
SEVERITY = "severity::2"
PROJECT = "Incident Operations"


def task(seed: int = 42) -> TaskPack:
    recipe = {"schema": "gitlab-triage-fixture-v1", "seed": seed, "marker": MARKER,
              "oncall_username": ONCALL, "severity": SEVERITY, "project": PROJECT,
              "preserved_distractor": "INC-2026-0218 assigned to casey-backup with severity::3",
              "already_correct": seed % 2 == 1, "ordering": "seed-modulo-three",
              "fixture_source_sha256": sha256(Path(__file__)),
              "config_sha256": sha256(CLOSE_ROOT / "config.rb"), "export_sha256": sha256(ROOT / "export.rb")}
    return TaskPack(id="gitlab-incident-triage", version="1.0.2", name="GitLab incident assignment and classification",
                    instruction=(f"In {PROJECT}, find the open issue whose description says {MARKER}. "
                                 f"Assign it to Casey On-call, username @{ONCALL}, and add the {SEVERITY} label. "
                                 "Corroborate the username before choosing the similarly named account. "
                                 "If either requested setting is already correct, leave it unchanged. "
                                 "Preserve all other labels, issue status, due date, descriptions, existing history, "
                                 "unrelated issues and project access. Do not post an ordinary comment."),
                    application="GitLab CE", application_version=GITLAB_VERSION, image_digest=APP_DIGEST,
                    fixture_hash=hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest(),
                    grader_version="gitlab-triage-state-v3", seed=seed)


async def fixture(post: FixturePost, seed: int, password: str) -> dict:
    users = {}
    for username, name, level in (("workflow-agent", "Workflow Agent", 30),
                                   (ONCALL, "Casey On-call", 30),
                                   ("casey-backup", "Casey On-call Backup", 30),
                                   ("incident-auditor", "Incident Auditor", 20)):
        users[username] = await post("/users", {"email": f"{username}@example.invalid", "username": username,
            "name": name, "password": password if username == "workflow-agent" else secrets.token_urlsafe(30),
            "skip_confirmation": True})
        users[username]["fixture_access_level"] = level
    project = await post("/projects", {"name": PROJECT, "path": "incident-operations", "visibility": "private",
        "issues_enabled": True, "builds_enabled": False, "container_registry_enabled": False})
    project_id = project["id"]
    for user in users.values():
        await post(f"/projects/{project_id}/members", {"user_id": user["id"], "access_level": user["fixture_access_level"]})
    labels = {}
    for name, color in (("incident", "#555555"), (SEVERITY, "#cc5555"), ("severity::3", "#558888")):
        labels[name] = await post(f"/projects/{project_id}/labels", {"name": name, "color": color})
    descriptions = ["Incident reference: INC-2026-0216", MARKER, "Incident reference: INC-2026-0218"]
    offset = seed % 3
    descriptions = descriptions[offset:] + descriptions[:offset]
    target = None
    for description in descriptions:
        correct = description == MARKER and seed % 2 == 1
        distractor = description == "Incident reference: INC-2026-0218"
        assigned = [users[ONCALL]["id"]] if correct else [users["casey-backup"]["id"]] if distractor else []
        issue_labels = "incident," + SEVERITY if correct else "incident,severity::3" if distractor else "incident"
        issue = await post(f"/projects/{project_id}/issues", {"title": "Checkout incident investigation",
            "description": f"{description}\nCorroborate the on-call account and severity in the request.",
            "labels": issue_labels, "assignee_ids": assigned, "due_date": "2026-12-30"})
        await post(f"/projects/{project_id}/issues/{issue['iid']}/notes", {"body": "Initial incident handoff; preserve this history."})
        if description == MARKER:
            target = issue["id"]
    return {"project_id": project_id, "target_issue_id": target, "agent_id": users["workflow-agent"]["id"],
            "oncall_id": users[ONCALL]["id"], "severity_label_id": labels[SEVERITY]["id"]}
