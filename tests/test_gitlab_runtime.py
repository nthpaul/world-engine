import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from pydantic import SecretStr

from world_engine.browser_contracts import BrowserCleanupError, BrowserCredentials, RuntimeHandle, SealedState
from world_engine.gitlab_runtime import (
    MAX_STATE_BYTES,
    OWNER_LABEL,
    GitLabRuntime,
    GitLabRuntimeError,
    gitlab_task,
)
from world_engine.gitlab_taskpacks import resolve_gitlab_pack

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "gitlab_verify", ROOT / "src/world_engine/taskpacks/gitlab/verify.py"
)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


@pytest.fixture
def completed():
    before = {
        "schema": "world-engine-gitlab-state-v1",
        "gitlab_version": "19.4.1",
        "projects": [
            {
                "id": 1,
                "name": "Release Operations",
                "visibility_level": 0,
                "updated_at": "2026-10-10T20:00:00Z",
                "last_activity_at": "2026-10-10T20:00:00Z",
            }
        ],
        "project_features": [{"id": 1, "issues_access_level": 20}],
        "namespaces": [{"id": 1, "name": "root"}],
        "users": [{"id": 2, "username": "workflow-agent", "admin": False}],
        "members": [{"id": 1, "user_id": 2, "source_id": 1, "source_type": "Project", "access_level": 30}],
        "issues": [
            {
                "id": 1,
                "project_id": 1,
                "namespace_id": 4,
                "state_id": 1,
                "description": "Deployment reference: REL-2026-1042",
                "title": "Review",
                "closed_by_id": None,
                "updated_by_id": None,
                "closed_at": None,
                "updated_at": "2026-10-10T20:00:00Z",
            },
            {"id": 2, "project_id": 1, "state_id": 1, "description": "distractor"},
        ],
        "notes": [{"id": 1, "note": "Retain this note"}],
        "labels": [],
        "label_links": [],
        "state_events": [],
    }
    after = copy.deepcopy(before)
    after["issues"][0].update(
        state_id=2,
        closed_by_id=2,
        updated_by_id=2,
        closed_at="2026-10-10T20:02:00Z",
        updated_at="2026-10-10T20:02:00Z",
    )
    for key, system, body, time in [
        (2, False, "Release checklist verified; ready for closure.", "20:01"),
    ]:
        after["notes"].append(
            {
                "id": key,
                "system": system,
                "internal": False,
                "note": body,
                "author_id": 2,
                "noteable_type": "Issue",
                "noteable_id": 1,
                "project_id": 1,
                "created_at": f"2026-10-10T{time}:00Z",
            }
        )
    after["state_events"] = [
        {
            "state_name": "closed",
            "attributes": {
                "id": 1, "issue_id": 1, "user_id": 2, "namespace_id": 4,
                "created_at": "2026-10-10T20:02:00Z", "state": "closed", "imported_from": "none",
                "merge_request_id": None, "epic_id": None, "source_commit": None,
                "source_merge_request_id": None, "close_auto_resolve_prometheus_alert": False,
                "close_after_error_tracking_resolve": False,
            },
        }
    ]
    return {
        "schema": "world-engine-gitlab-sealed-v1",
        "baseline": before,
        "final": after,
        "expected": {
            "project_id": 1,
            "target_issue_id": 1,
            "agent_id": 2,
            "comment": "Release checklist verified; ready for closure.",
        },
        "provenance": {},
    }


def test_grade_exact_browser_effects(completed):
    verdict = verifier.verify(completed)
    assert verdict["passed"] and verdict["reward"] == 1.0


@pytest.mark.parametrize("internal", [True, None, 0, 1, "false", [], {}])
def test_comment_must_be_explicitly_non_internal(completed, internal):
    completed["final"]["notes"][1]["internal"] = internal
    verdict = verifier.verify(completed)
    assert not verdict["passed"] and verdict["reward"] == 0.0


def test_comment_missing_internal_flag_fails(completed):
    del completed["final"]["notes"][1]["internal"]
    assert verifier.verify(completed)["reward"] == 0.0


@pytest.mark.parametrize("updater", [None, True, 2.0, "2", 999])
def test_updater_must_be_exact_ordinary_actor(completed, updater):
    completed["final"]["issues"][0]["updated_by_id"] = updater
    assert not verifier.verify(completed)["passed"]


def test_missing_updater_fails(completed):
    del completed["final"]["issues"][0]["updated_by_id"]
    assert not verifier.verify(completed)["passed"]


def test_missing_requested_comment_fails(completed):
    completed["final"]["notes"].pop()
    assert not verifier.verify(completed)["passed"]


@pytest.mark.parametrize("field,value", [
    ("state", "opened"), ("namespace_id", 999), ("namespace_id", True), ("user_id", True),
    ("issue_id", True), ("source_commit", "forged"), ("source_merge_request_id", 7),
    ("merge_request_id", 7), ("epic_id", 7), ("imported_from", "github"),
    ("close_auto_resolve_prometheus_alert", True), ("close_after_error_tracking_resolve", 0),
    ("created_at", "2026-10-10T20:00:30Z"), ("extra", "unattested"),
])
def test_closure_event_contract_and_comment_order(completed, field, value):
    completed["final"]["state_events"][0]["attributes"][field] = value
    assert not verifier.verify(completed)["passed"]


def test_existing_event_cannot_be_changed(completed):
    old = copy.deepcopy(completed["final"]["state_events"][0])
    old["attributes"].update(id=10, state="opened")
    old["state_name"] = "opened"
    completed["baseline"]["state_events"].append(copy.deepcopy(old))
    completed["final"]["state_events"].insert(0, old)
    assert verifier.verify(completed)["passed"]
    completed["final"]["state_events"][0]["attributes"]["user_id"] = 999
    assert not verifier.verify(completed)["passed"]


@pytest.mark.parametrize("field", sorted(verifier.STATE_EVENT_FIELDS))
def test_event_missing_contract_field_fails(completed, field):
    del completed["final"]["state_events"][0]["attributes"][field]
    assert not verifier.verify(completed)["passed"]


@pytest.mark.parametrize("field,value", [
    ("description", "different request"), ("namespace_id", 999), ("project_id", 999),
    ("new_metadata", "unattested"),
])
def test_target_immutable_fields_remain_anchored(completed, field, value):
    completed["final"]["issues"][0][field] = value
    assert not verifier.verify(completed)["passed"]


@pytest.mark.parametrize("time", ["2026-10-10T20:01:30Z", "2026-10-10T20:03:00Z"])
def test_closure_event_is_between_closure_and_final_update(completed, time):
    completed["final"]["state_events"][0]["attributes"]["created_at"] = time
    assert not verifier.verify(completed)["passed"]


def test_task_requires_ordinary_comment():
    task = gitlab_task()
    assert "Then close that issue. Use an ordinary comment, not an internal note." in task.instruction
    assert task.version == "1.0.3"
    assert task.grader_version == "gitlab-state-v3"


def test_early_finish_no_effect_fails(completed):
    completed["final"] = copy.deepcopy(completed["baseline"])
    assert verifier.verify(completed)["reward"] == 0.0


@pytest.mark.parametrize(
    "table", ["projects", "project_features", "namespaces", "users", "members", "labels", "label_links"]
)
def test_unrelated_added_row_fails(completed, table):
    completed["final"][table].append({"id": 999, "injected": True})
    assert not verifier.verify(completed)["passed"]


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_comment",
        "duplicate_close",
        "old_note_changed",
        "old_note_removed",
        "wrong_body",
        "wrong_author",
        "wrong_issue",
        "wrong_project",
        "wrong_target",
        "wrong_updater",
        "target_title",
        "outsider_closed",
        "permission",
        "admin",
        "event_wrong_actor",
        "event_wrong_issue",
        "event_duplicate",
        "event_missing",
        "order",
    ],
)
def test_corruption_fails(completed, mutation):
    state = completed["final"]
    if mutation == "duplicate_comment":
        row = dict(state["notes"][1], id=4)
        state["notes"].append(row)
    elif mutation == "duplicate_close":
        row = dict(state["notes"][1], id=4, system=True, note="closed")
        state["notes"].append(row)
    elif mutation == "old_note_changed":
        state["notes"][0]["note"] = "changed"
    elif mutation == "old_note_removed":
        state["notes"].pop(0)
    elif mutation == "wrong_body":
        state["notes"][1]["note"] += " extra"
    elif mutation == "wrong_author":
        state["notes"][1]["author_id"] = 3
    elif mutation == "wrong_issue":
        state["notes"][1]["noteable_id"] = 2
    elif mutation == "wrong_project":
        state["notes"][1]["project_id"] = 999
    elif mutation == "wrong_target":
        state["issues"][0]["closed_by_id"] = 999
    elif mutation == "wrong_updater":
        state["issues"][0]["updated_by_id"] = 999
    elif mutation == "target_title":
        state["issues"][0]["title"] = "changed"
    elif mutation == "outsider_closed":
        state["issues"][1]["state_id"] = 2
    elif mutation == "permission":
        state["members"][0]["access_level"] = 50
    elif mutation == "admin":
        state["users"][0]["admin"] = True
    elif mutation == "event_wrong_actor":
        state["state_events"][0]["attributes"]["user_id"] = 1
    elif mutation == "event_wrong_issue":
        state["state_events"][0]["attributes"]["issue_id"] = 2
    elif mutation == "event_duplicate":
        state["state_events"].append(copy.deepcopy(state["state_events"][0]))
    elif mutation == "event_missing":
        state["state_events"] = []
    elif mutation == "order":
        state["notes"][1]["created_at"] = "2026-10-10T20:03:00Z"
    assert not verifier.verify(completed)["passed"]


@pytest.mark.parametrize("table", sorted(verifier.TABLES))
def test_missing_table_fails(completed, table):
    del completed["final"][table]
    assert not verifier.verify(completed)["passed"]


@pytest.mark.parametrize("field", ["state_id", "closed_by_id", "updated_by_id", "project_id"])
def test_bool_cannot_forge_numeric_identity(completed, field):
    completed["final"]["issues"][0][field] = True
    assert not verifier.verify(completed)["passed"]


def test_task_seed_and_code_locked():
    assert gitlab_task(42) == gitlab_task(42)
    assert gitlab_task(42).fixture_hash != gitlab_task(43).fixture_hash
    assert "target_issue_id" not in gitlab_task().instruction
    assert gitlab_task().evaluation_only is True


@pytest.mark.parametrize("value", [0, -1, 451, float("inf"), float("nan"), True, "450"])
def test_readiness_bounds(value):
    with pytest.raises(ValueError):
        GitLabRuntime(readiness_seconds=value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint", ["tcp://host:2375", "ssh://remote", "unix:///tmp/a?x", "", "unix:///tmp/a\n"]
)
async def test_remote_daemon_refused(monkeypatch, endpoint):
    monkeypatch.setenv("DOCKER_HOST", endpoint)
    runtime = GitLabRuntime()
    with pytest.raises(GitLabRuntimeError):
        await runtime._local_docker()
    assert runtime._endpoint is None


@pytest.mark.asyncio
async def test_local_endpoint_frozen_and_context_not_inherited(monkeypatch):
    monkeypatch.setenv("DOCKER_HOST", "unix:///tmp/local.sock")
    runtime = GitLabRuntime()
    await runtime._local_docker()
    monkeypatch.setenv("DOCKER_HOST", "tcp://remote:2375")
    await runtime._local_docker()
    assert runtime._endpoint == "unix:///tmp/local.sock"
    assert "DOCKER_HOST" not in runtime._env


@pytest.mark.asyncio
async def test_symlink_directory_refused_before_docker(tmp_path):
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    runtime = GitLabRuntime()
    with pytest.raises(GitLabRuntimeError):
        await runtime.start("attempt", gitlab_task(), link)
    assert runtime._endpoint is None


@pytest.mark.asyncio
async def test_admission_refuses_overlap(tmp_path):
    runtime = GitLabRuntime()
    await runtime._admission.acquire()
    try:
        with pytest.raises(GitLabRuntimeError):
            await runtime.start("attempt", gitlab_task(), tmp_path)
    finally:
        runtime._admission.release()


def owned_runtime(tmp_path):
    runtime = GitLabRuntime()
    handle = RuntimeHandle(
        "owned",
        "http://127.0.0.1:1234",
        "http://127.0.0.1:1234/dashboard/projects",
        tmp_path,
        BrowserCredentials("workflow-agent", SecretStr("ordinary-secret")),
    )
    runtime._instances["owned"] = {
        "handle": handle,
        "owner": "owner-token",
        "containers": ["relay", "owned"],
        "volumes": ["data"],
        "networks": ["internal", "front"],
        "sealed": False,
        "definition": resolve_gitlab_pack("gitlab-issue-close"),
        "verifier_image": "sha256:" + "a" * 64,
    }
    return runtime, handle


@pytest.mark.asyncio
async def test_cleanup_certified_and_idempotent(tmp_path, monkeypatch):
    runtime, handle = owned_runtime(tmp_path)
    calls = []

    async def inspect(kind, name):
        labels = {OWNER_LABEL: "owner-token"}
        return {"Config": {"Labels": labels}} if kind == "container" else {"Labels": labels}

    async def docker(*args, **kwargs):
        calls.append(args)
        return b""

    monkeypatch.setattr(runtime, "_inspect", inspect)
    monkeypatch.setattr(runtime, "_docker", docker)
    assert (await runtime.close(handle)).status == "completed"
    before = len(calls)
    assert (await runtime.close(handle)).status == "completed" and len(calls) == before
    assert [args[2] for args in calls if args[:2] == ("container", "rm")] == ["--force", "--force"]
    assert len([args for args in calls if "ls" in args]) == 5
    assert not runtime._instances


@pytest.mark.asyncio
async def test_foreign_resource_never_removed_and_blocks_admission(tmp_path, monkeypatch):
    runtime, handle = owned_runtime(tmp_path)
    removed = []

    async def inspect(kind, name):
        return {"Config": {"Labels": {OWNER_LABEL: "not-owned"}}}

    async def docker(*args, **kwargs):
        removed.append(args)
        return b""

    monkeypatch.setattr(runtime, "_inspect", inspect)
    monkeypatch.setattr(runtime, "_docker", docker)
    assert (await runtime.close(handle)).status == "failed"
    assert not removed
    with pytest.raises(GitLabRuntimeError):
        await runtime.start("other", gitlab_task(), tmp_path)


@pytest.mark.asyncio
async def test_cleanup_inspection_failure_checks_stopped_containers(tmp_path, monkeypatch):
    runtime, handle = owned_runtime(tmp_path)

    async def inspect(kind, name):
        raise GitLabRuntimeError("inspection failed")

    async def docker(*args, **kwargs):
        assert args[:3] == ("container", "ls", "--all")
        return b"container-still-present\n"

    monkeypatch.setattr(runtime, "_inspect", inspect)
    monkeypatch.setattr(runtime, "_docker", docker)
    assert (await runtime.close(handle)).status == "failed"
    assert "owned" in runtime._instances


@pytest.mark.asyncio
async def test_removal_without_absence_certificate_fails(tmp_path, monkeypatch):
    runtime, handle = owned_runtime(tmp_path)

    async def inspect(kind, name):
        labels = {OWNER_LABEL: "owner-token"}
        return {"Config": {"Labels": labels}} if kind == "container" else {"Labels": labels}

    async def docker(*args, **kwargs):
        return b"still-present" if "ls" in args else b""

    monkeypatch.setattr(runtime, "_inspect", inspect)
    monkeypatch.setattr(runtime, "_docker", docker)
    assert (await runtime.close(handle)).status == "failed"
    assert "owned" in runtime._instances


@pytest.mark.asyncio
async def test_seal_revokes_ingress_before_export(tmp_path, monkeypatch):
    runtime, handle = owned_runtime(tmp_path)
    runtime._instances["owned"].update(baseline={}, expected={})
    calls = []

    async def docker(*args, **kwargs):
        calls.append(args)
        return b""

    async def export(_):
        assert calls[0] == ("stop", "--time", "5", "relay")
        assert calls[1][-2:] == ("stop", "puma")
        assert calls[2][-2:] == ("stop", "sidekiq")
        return {"final": "state"}

    monkeypatch.setattr(runtime, "_docker", docker)
    monkeypatch.setattr(runtime, "_export", export)
    sealed = await runtime.seal(handle)
    assert json.loads(sealed.path.read_bytes())["final"] == {"final": "state"}
    assert sealed.path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(GitLabRuntimeError):
        await runtime.seal(handle)


@pytest.mark.asyncio
async def test_seal_existing_artifact_never_overwritten(tmp_path, monkeypatch):
    runtime, handle = owned_runtime(tmp_path)
    runtime._instances["owned"].update(baseline={}, expected={})
    path = tmp_path / "gitlab-sealed-state.json"
    path.write_bytes(b"original")

    async def docker(*args, **kwargs):
        return b""

    async def export(_):
        return {}

    monkeypatch.setattr(runtime, "_docker", docker)
    monkeypatch.setattr(runtime, "_export", export)
    with pytest.raises(FileExistsError):
        await runtime.seal(handle)
    assert path.read_bytes() == b"original"


@pytest.mark.asyncio
async def test_seal_dangling_symlink_never_followed(tmp_path, monkeypatch):
    runtime, handle = owned_runtime(tmp_path)
    runtime._instances["owned"].update(baseline={}, expected={})
    victim = tmp_path / "victim"
    path = tmp_path / "gitlab-sealed-state.json"
    path.symlink_to(victim)

    async def docker(*args, **kwargs):
        return b""

    async def export(_):
        return {}

    monkeypatch.setattr(runtime, "_docker", docker)
    monkeypatch.setattr(runtime, "_export", export)
    with pytest.raises(FileExistsError):
        await runtime.seal(handle)
    assert not victim.exists()


@pytest.mark.asyncio
async def test_grade_oversize_before_read_or_docker(tmp_path, monkeypatch):
    runtime = GitLabRuntime(verifier_image="sha256:" + "a" * 64)
    path = tmp_path / "sealed"
    with path.open("wb") as stream:
        stream.truncate(MAX_STATE_BYTES + 1)

    async def local():
        pass

    monkeypatch.setattr(runtime, "_local_docker", local)
    with pytest.raises(GitLabRuntimeError):
        await runtime.grade(SealedState(path, "0" * 64, MAX_STATE_BYTES + 1), gitlab_task())


@pytest.mark.parametrize("field", ["project_id", "target_issue_id", "agent_id"])
def test_trusted_ids_reject_boolean(completed, field):
    completed["expected"][field] = True
    assert not verifier.verify(completed)["passed"]


@pytest.mark.parametrize("field", ["id", "issue_id", "user_id"])
def test_state_event_ids_reject_boolean(completed, field):
    completed["final"]["state_events"][0]["attributes"][field] = True
    assert not verifier.verify(completed)["passed"]


@pytest.mark.asyncio
async def test_timed_out_verifier_remains_owned_until_certified_close(tmp_path, monkeypatch):
    runtime, handle = owned_runtime(tmp_path)
    runtime._endpoint = "unix:///tmp/local.sock"
    runtime.verifier_image = "sha256:" + "a" * 64
    task = gitlab_task()
    raw = b"{}"
    path = tmp_path / "state.json"
    path.write_bytes(raw)
    sealed = SealedState(path, hashlib.sha256(raw).hexdigest(), len(raw))
    runtime._instances["owned"].update(sealed_state=sealed, task=task)
    calls = []

    async def docker(*args, **kwargs):
        calls.append(args)
        if args[0] == "run":
            assert args[args.index("--network") + 1] == "none"
            assert "--mount" not in args and "--volume" not in args
            assert args[args.index("--name") + 1].startswith("owned-verifier-")
            raise TimeoutError
        return b""

    async def inspect(kind, name):
        labels = {OWNER_LABEL: "owner-token"}
        return {"Config": {"Labels": labels}} if kind == "container" else {"Labels": labels}

    monkeypatch.setattr(runtime, "_docker", docker)
    monkeypatch.setattr(runtime, "_inspect", inspect)
    with pytest.raises(TimeoutError):
        await runtime.grade(sealed, task)
    name = runtime._instances["owned"]["containers"][-1]
    assert name.startswith("owned-verifier-")
    assert (await runtime.close(handle)).status == "completed"
    assert ("container", "rm", "--force", name) in calls
    assert ("container", "ls", "--all", "--quiet", "--filter", f"name={name}") in calls


@pytest.mark.asyncio
async def test_arbitrary_sealed_state_cannot_launch_unowned_verifier(tmp_path, monkeypatch):
    runtime = GitLabRuntime(verifier_image="sha256:" + "a" * 64)
    runtime._endpoint = "unix:///tmp/local.sock"
    path = tmp_path / "state.json"
    path.write_bytes(b"{}")
    with pytest.raises(GitLabRuntimeError, match="owned sealed"):
        await runtime.grade(SealedState(path, hashlib.sha256(b"{}").hexdigest(), 2), gitlab_task())


@pytest.mark.asyncio
async def test_orphans_block_new_allocation_before_image_or_network_work(tmp_path, monkeypatch):
    runtime = GitLabRuntime()
    runtime._endpoint = "unix:///tmp/local.sock"
    calls = []

    async def docker(*args, **kwargs):
        calls.append(args)
        return b"owned-orphan"

    monkeypatch.setattr(runtime, "_docker", docker)
    with pytest.raises(BrowserCleanupError):
        await runtime.start("attempt", gitlab_task(), tmp_path)
    assert calls == [("container", "ls", "--all", "--quiet", "--filter", f"label={OWNER_LABEL}")]
    assert not runtime._instances


@pytest.mark.asyncio
async def test_modified_task_manifest_rejected_before_runtime_work(tmp_path):
    runtime = GitLabRuntime()
    task = gitlab_task().model_copy(update={"fixture_hash": "f" * 64})
    with pytest.raises(GitLabRuntimeError):
        await runtime.start("attempt", task, tmp_path)
    assert runtime._endpoint is None
