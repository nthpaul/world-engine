import asyncio
import hashlib
import json
from dataclasses import FrozenInstanceError

import pytest
from pydantic import SecretStr

from world_engine.browser_contracts import (
    BrowserAttemptConfig,
    BrowserCredentials,
    BrowserError,
    BrowserObservation,
    RuntimeHandle,
)
from world_engine.browser_policy import BrowserReferencePolicy, create_browser_policy
from world_engine.browser_runs import default_browser_manager
from world_engine.gitlab_runtime import GitLabRuntime
from world_engine.gitlab_taskpacks import gitlab_catalog, make_browser_task, resolve_gitlab_pack


def test_catalog_versions_and_stable_case_lineage():
    catalog = gitlab_catalog()
    assert set(catalog) == {"gitlab-issue-close", "gitlab-incident-triage"}
    assert catalog["gitlab-issue-close"].version == "1.0.3"
    assert catalog["gitlab-issue-close"].grader_version == "gitlab-state-v3"
    triage = resolve_gitlab_pack("gitlab-incident-triage")
    for seed, case in ((42, "changes-required"), (43, "already-correct")):
        provenance = triage.provenance(seed)
        assert provenance["lineage_id"] == hashlib.sha256(f"incident-triage:{case}:{seed}".encode()).hexdigest()
        assert provenance["task_case"] == case
        assert provenance["source_rights"]["training_eligible"] is False
        assert all(len(value) == 64 for value in provenance["pack_sources"].values())
    with pytest.raises(FrozenInstanceError):
        triage.version = "2"
    with pytest.raises(BrowserError, match="unsupported"):
        resolve_gitlab_pack("unregistered-agent-pack")


async def test_default_manager_catalog_is_two_packs_but_no_runtime_start(tmp_path, monkeypatch):
    monkeypatch.delenv("WORLD_ENGINE_BROWSER_ENABLED", raising=False)
    manager = default_browser_manager(tmp_path)
    try:
        assert set(manager.tasks) == {"gitlab-issue-close", "gitlab-incident-triage"}
        assert manager.task_factory is make_browser_task
        assert manager.status()["available"] is False and not manager.jobs
        with pytest.raises(BrowserError, match="unavailable"):
            manager.submit(BrowserAttemptConfig(task_id="gitlab-incident-triage"))
    finally:
        await manager.close()


@pytest.mark.parametrize("seed", [0, 1, 42, 43])
async def test_fixture_seed_roles_similar_names_and_noop_variant(seed):
    pack = resolve_gitlab_pack("gitlab-incident-triage")
    calls = []

    async def post(path, data):
        calls.append((path, data.copy()))
        return {"id": len(calls), "iid": len(calls)}

    expected = await pack.fixture(post, seed, "fixture-password")
    user_posts = [data for path, data in calls if path == "/users"]
    assert {data["username"] for data in user_posts} == {
        "workflow-agent", "casey-oncall", "casey-backup", "incident-auditor"}
    assert next(data for data in user_posts if data["username"] == "casey-backup")["name"] == "Casey On-call Backup"
    assert [data["access_level"] for path, data in calls if path.endswith("/members")] == [30, 30, 30, 20]
    issues = [data for path, data in calls if path.endswith("/issues")]
    assert len(issues) == 3 and len({data["title"] for data in issues}) == 1
    wanted = next(data for data in issues if "INC-2026-0217" in data["description"])
    assert wanted["due_date"] == "2026-12-30"
    assert wanted["labels"] == ("incident,severity::2" if seed % 2 else "incident")
    assert wanted["assignee_ids"] == ([expected["oncall_id"]] if seed % 2 else [])
    distractor = next(data for data in issues if "INC-2026-0218" in data["description"])
    assert distractor["assignee_ids"] == [3] and distractor["labels"] == "incident,severity::3"
    untouched = next(data for data in issues if "INC-2026-0216" in data["description"])
    assert untouched["assignee_ids"] == [] and untouched["labels"] == "incident"
    task_json = json.dumps(pack.public_task(seed).model_dump())
    assert "fixture-password" not in task_json and "target_issue_id" not in task_json
    assert "@casey-oncall" in task_json and "Do not post an ordinary comment" in task_json


async def test_runtime_unknown_or_modified_manifest_fails_before_docker(tmp_path, monkeypatch):
    runtime = GitLabRuntime()

    async def forbidden(*args, **kwargs):
        pytest.fail("Docker was invoked before task validation")

    monkeypatch.setattr(runtime, "_local_docker", forbidden)
    for task in (make_browser_task("gitlab-incident-triage", 42).model_copy(update={"version": "forged"}),
                 make_browser_task("gitlab-incident-triage", 42).model_copy(update={"id": "agent-selected"})):
        with pytest.raises(BrowserError):
            await runtime.start("attempt", task, tmp_path)
    assert not runtime._instances


def observation(text, path="/root/incident-operations/-/issues/2"):
    return BrowserObservation(url="http://127.0.0.1:8929" + path, title="GitLab",
                              accessibility_text=text, screenshot_artifact_id="screenshots/0000.png")


def policy():
    task = make_browser_task("gitlab-incident-triage", 42)
    return create_browser_policy(BrowserAttemptConfig(task_id=task.id, provider_id="browser-reference"), task)


async def test_public_reference_discovers_project_and_target_before_edit():
    control = policy()
    assert isinstance(control, BrowserReferencePolicy)
    decision = await control.decide(observation("[3] link 'Incident Operations'", "/dashboard/projects"), [])
    assert decision.action.bid == "3"
    decision = await control.decide(observation("[7] button 'Edit assignees'"), [])
    assert decision.action.kind == "wait"
    decision = await control.decide(observation("StaticText 'Incident reference: INC-2026-0217'\n[7] button 'Edit assignees'"), [])
    assert decision.action.bid == "7"
    assert decision.evidence["protocol"] == "public-ax-triage-control-v1"


async def test_reference_corroborates_username_and_current_bid_then_closes_picker():
    control = policy()
    marker = "StaticText 'Incident reference: INC-2026-0217'\n"
    first = marker + "[10] textbox 'Search users' value=''"
    decision = await control.decide(observation(first), [])
    assert decision.action.kind == "fill" and decision.action.text == "casey-oncall"
    picker = marker + "[11] textbox 'Search users' value='casey-oncall'\n[12] checkbox 'Casey On-call Backup @casey-backup'\n[13] checkbox 'Casey On-call @casey-oncall'"
    decision = await control.decide(observation(picker), [])
    assert decision.action.bid == "13"
    decision = await control.decide(observation(marker + "[15] textbox 'Search users' value='casey-oncall'"), [])
    assert decision.action.kind == "press" and decision.action.bid == "15" and decision.action.key == "Escape"


async def test_reference_noop_and_only_missing_label():
    control = policy()
    text = ("StaticText 'Incident reference: INC-2026-0217'\nStaticText 'Assignees'\n"
            "StaticText 'Casey On-call @casey-oncall'\n[10] button 'Edit'\nStaticText 'Labels'\n"
            "StaticText 'incident'\n[11] button 'Edit'\nStaticText 'Due date'")
    decision = await control.decide(observation(text), [])
    assert decision.action.bid == "11"
    decision = await control.decide(observation(text.replace("StaticText 'incident'", "StaticText 'severity::2'")), [])
    assert decision.action.kind == "finish"


async def test_reference_requires_exact_severity_option_not_prefix_match():
    control = policy()
    text = ("StaticText 'Incident reference: INC-2026-0217'\n[1] textbox 'Search labels' value='severity::2'\n"
            "[2] checkbox 'severity::20'\n[3] checkbox 'severity::2'")
    decision = await control.decide(observation(text), [])
    assert decision.action.bid == "3"


async def test_baseline_finishes_without_read_or_mutation():
    task = make_browser_task("gitlab-incident-triage", 42)
    control = create_browser_policy(BrowserAttemptConfig(task_id=task.id, provider_id="browser-baseline"), task)
    assert (await control.decide(observation(""), [])).action.kind == "finish"
    await asyncio.wait_for(control.close(), 1)


@pytest.mark.parametrize("task_id", ["gitlab-issue-close", "gitlab-incident-triage"])
async def test_owned_pack_selects_export_seal_and_verifier(tmp_path, monkeypatch, task_id):
    pack = resolve_gitlab_pack(task_id)
    task = pack.public_task(42)
    runtime = GitLabRuntime()
    handle = RuntimeHandle("owned", "http://127.0.0.1:1234", "http://127.0.0.1:1234/dashboard/projects",
                           tmp_path, BrowserCredentials("workflow-agent", SecretStr("fixture-secret")))
    record = {"handle": handle, "definition": pack, "task": task, "baseline": {}, "expected": {},
              "owner": "trusted-owner", "containers": ["ingress", "owned"], "sealed": False,
              "verifier_image": "sha256:" + "a" * 64}
    runtime._instances["owned"] = record
    calls = []

    async def rails(actual, code):
        assert actual is handle and code == pack.export_path.read_text()
        return "{}"

    async def docker(*args, **kwargs):
        calls.append(args)
        return b'{"passed":true,"reward":1.0,"checks":[{"name":"mock","passed":true,"detail":"Mock-only verifier dispatch."}]}'

    async def local():
        pass

    monkeypatch.setattr(runtime, "_rails", rails)
    monkeypatch.setattr(runtime, "_docker", docker)
    monkeypatch.setattr(runtime, "_local_docker", local)
    sealed = await runtime.seal(handle)
    assert json.loads(sealed.path.read_text())["schema"] == pack.sealed_schema
    foreign = make_browser_task("gitlab-incident-triage" if task_id == "gitlab-issue-close" else "gitlab-issue-close", 42)
    with pytest.raises(BrowserError, match="owned sealed"):
        await runtime.grade(sealed, foreign)
    assert not any(call[0] == "run" for call in calls)
    result = await runtime.grade(sealed, task)
    assert result.passed
    assert calls[-1][-1] == record["verifier_image"]
    assert record["definition"] is pack
