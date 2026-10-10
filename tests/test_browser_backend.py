"""Controller evidence tests use explicitly fake runtimes/drivers, never GitLab."""

import asyncio
import hashlib
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from world_engine.api import create_app
from world_engine.browser_contracts import (
    ACTION_ADAPTER,
    BrowserAttemptConfig,
    BrowserCleanupError,
    BrowserCredentials,
    BrowserDecision,
    BrowserError,
    BrowserObservation,
    CleanupResult,
    GradeResult,
    RuntimeHandle,
    SealedState,
    TaskPack,
    VerifierCheck,
    relative_artifact_id,
)
from world_engine.browser_runs import BrowserRunManager
from world_engine.browser_store import TERMINAL_RESERVE_BYTES, BrowserStore
from world_engine.rollout import RunManager
from world_engine.store import Store

TASK = TaskPack(id="fake-browser-task", version="test-v1", name="Explicitly fake controller task",
                instruction="Click the close button, then finish.", application="fake-test-application",
                application_version="fake-v1", image_digest="sha256:" + "a" * 64,
                fixture_hash="b" * 64, grader_version="fake-grader-v1")
SECRET = "FAKE_OPERATOR_PASSWORD_NOT_PUBLIC"


class FakeRuntime:
    def __init__(self):
        self.completed = False
        self.closed = 0
        self.sealed = 0
        self.driver_closed = False
        self.fail_grade = False
        self.cleanup_failed = False
        self.started = 0

    async def start(self, attempt_id, task, directory):
        self.started += 1
        return RuntimeHandle("fake-instance", "http://127.0.0.1:9999", "http://127.0.0.1:9999/project",
                             directory, BrowserCredentials("fake-agent", SecretStr(SECRET)))

    async def seal(self, handle):
        assert self.driver_closed, "agent browser must be closed before sealing"
        self.sealed += 1
        path = handle.artifact_root / "PRIVATE-sealed-state.json"
        raw = json.dumps({"completed": self.completed}).encode()
        path.write_bytes(raw)
        return SealedState(path, hashlib.sha256(raw).hexdigest(), len(raw))

    async def grade(self, sealed, task):
        if self.fail_grade:
            raise RuntimeError(SECRET)
        return GradeResult(passed=self.completed, reward=float(self.completed),
                           checks=[VerifierCheck(name="fake-completion", passed=self.completed, detail="Fake outcome check")],
                           grader_version=task.grader_version, sealed_state_sha256=sealed.sha256)

    async def close(self, handle):
        self.closed += 1
        return CleanupResult(status="failed", error_code="cleanup_failed") if self.cleanup_failed else CleanupResult(status="completed")


class FakeDriver:
    def __init__(self, runtime, handle, directory):
        self.runtime, self.directory = runtime, directory
        self.capture = 0
        self.execute_count = 0
        self.fail_close = False

    async def prepare(self):
        pass

    async def observe(self):
        artifact_id = f"screenshots/{self.capture:04}.png"
        path = self.directory / artifact_id
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"explicitly-fake-image-for-controller-tests")
        self.capture += 1
        return BrowserObservation(url="http://127.0.0.1:9999/project", title="Fake page",
                                  accessibility_text="[close] button Close", screenshot_artifact_id=artifact_id)

    async def execute(self, action):
        records = BrowserStore(self.directory.parent).journal(self.directory.name)
        assert records[-1]["event"] == "action_intent", "durable intent must precede effect"
        self.execute_count += 1
        if action.kind == "click" and action.bid == "close":
            self.runtime.completed = True
            return {"ok": True}
        return {"ok": False, "error_code": "fake-invalid-node"}

    async def close(self):
        if self.fail_close:
            raise RuntimeError(SECRET)
        self.runtime.driver_closed = True
        return []


class FakePolicy:
    def __init__(self, actions):
        self.actions = iter(actions)
        self.closed = 0
        self.recorder = None
        self.fail_decision = False
        self.blocked = None
        self.fail_prepare = False

    def set_recorder(self, recorder):
        self.recorder = recorder

    async def prepare(self):
        if self.fail_prepare:
            raise RuntimeError(SECRET)
        self.recorder("policy_prepared", {"model": "explicitly-fake-policy"})

    async def decide(self, observation, history):
        self.recorder("inference_intent", {"request_body": "explicitly-fake-request"})
        if self.blocked is not None:
            self.blocked.set()
            await asyncio.sleep(30)
        self.recorder("inference_result", {"raw_response": "explicitly-fake-response"})
        if self.fail_decision:
            raise RuntimeError(SECRET)
        return BrowserDecision(ACTION_ADAPTER.validate_python(next(self.actions)))

    async def close(self):
        self.closed += 1


def controller(tmp_path, actions=None, runtime=None, policy=None):
    runtime = runtime or FakeRuntime()
    policy = policy or FakePolicy(actions or [{"kind": "click", "bid": "close"}, {"kind": "finish"}])
    drivers = []

    def driver_factory(handle, directory):
        driver = FakeDriver(runtime, handle, directory)
        drivers.append(driver)
        return driver

    manager = BrowserRunManager(BrowserStore(tmp_path / "browser"), {TASK.id: TASK}, runtime,
                                driver_factory, lambda config, task: policy)
    return manager, runtime, policy, drivers


async def test_fake_success_durable_order_and_separate_grading(tmp_path):
    manager, runtime, policy, drivers = controller(tmp_path)
    try:
        run = manager.submit(BrowserAttemptConfig(task_id=TASK.id, provider_id="browser-reference"))
        result = await manager.wait(run["id"])
        assert result["passed"] and result["reward"] == 1.0 and result["termination"] == "finished"
        assert result["steps"] == 2 and result["invalid_actions"] == 0
        events = [event["event"] for event in result["journal"]]
        assert events.index("browser_closed") < events.index("state_sealed") < events.index("graded")
        assert events.index("inference_result") < events.index("action_intent") < events.index("action_result")
        assert events.count("policy_prepared") == 1
        assert events.index("policy_prepared") < events.index("runtime_start_intent")
        assert len(result["artifacts"]) == 3 and all(a["kind"] == "screenshot" for a in result["artifacts"])
        assert SECRET not in json.dumps(result)
        assert runtime.closed == policy.closed == 1 and drivers[0].execute_count == 1
        assert "startup" in result["phase_seconds"] and "rollout" in result["phase_seconds"]
    finally:
        await manager.close()


async def test_max_steps_can_retain_business_grade_but_no_episode_pass(tmp_path):
    manager, runtime, policy, drivers = controller(tmp_path, [{"kind": "click", "bid": "close"}])
    try:
        run = manager.submit(BrowserAttemptConfig(task_id=TASK.id, max_steps=1))
        result = await manager.wait(run["id"])
        assert result["outcome"]["passed"] is True
        assert result["termination"] == "max_steps" and not result["passed"] and result["reward"] == 0
    finally:
        await manager.close()


async def test_early_finish_and_invalid_browser_actions_are_not_business_pass(tmp_path):
    manager, runtime, policy, drivers = controller(tmp_path, [{"kind": "click", "bid": "wrong"}, {"kind": "finish"}])
    try:
        result = await manager.wait(manager.submit(BrowserAttemptConfig(task_id=TASK.id))["id"])
        assert result["status"] == "completed" and not result["passed"] and result["reward"] == 0
        assert result["invalid_actions"] == 1
    finally:
        await manager.close()


async def test_model_failure_retains_raw_journal_but_redacts_exception(tmp_path):
    policy = FakePolicy([])
    policy.fail_decision = True
    manager, runtime, policy, drivers = controller(tmp_path, policy=policy)
    try:
        result = await manager.wait(manager.submit(BrowserAttemptConfig(task_id=TASK.id))["id"])
        assert result["status"] == "failed" and result["termination"] == "provider_error"
        assert SECRET not in json.dumps(result)
        assert [e["event"] for e in result["journal"]].count("inference_result") == 1
        assert runtime.closed == policy.closed == 1
    finally:
        await manager.close()


async def test_cancel_preserves_intent_and_cleans_once(tmp_path):
    policy = FakePolicy([])
    policy.blocked = asyncio.Event()
    manager, runtime, policy, drivers = controller(tmp_path, policy=policy)
    try:
        run = manager.submit(BrowserAttemptConfig(task_id=TASK.id))
        await policy.blocked.wait()
        with pytest.raises(BrowserError, match="admission"):
            manager.submit(BrowserAttemptConfig(task_id=TASK.id))
        result = await manager.cancel(run["id"])
        assert result["status"] == "cancelled" and result["reward"] == 0
        assert runtime.closed == policy.closed == 1
        result = await manager.cancel(run["id"])
        assert result["status"] == "cancelled" and runtime.closed == 1
        journal = manager.store.journal(run["id"])
        assert any(e["event"] == "inference_intent" for e in journal)
        assert not any(e["event"] == "inference_result" for e in journal)
    finally:
        await manager.close()


async def test_cleanup_failure_blocks_admission_and_no_pass(tmp_path):
    runtime = FakeRuntime()
    runtime.cleanup_failed = True
    manager, runtime, policy, drivers = controller(tmp_path, runtime=runtime)
    try:
        result = await manager.wait(manager.submit(BrowserAttemptConfig(task_id=TASK.id))["id"])
        assert result["outcome"]["passed"] is True and result["status"] == "failed" and result["reward"] == 0
        assert manager.status()["available"] is False
        with pytest.raises(BrowserError, match="reconciliation"):
            manager.submit(BrowserAttemptConfig(task_id=TASK.id))
    finally:
        await manager.close()


async def test_grader_failure_and_hash_mismatch_fail_closed(tmp_path):
    runtime = FakeRuntime()
    runtime.fail_grade = True
    manager, runtime, policy, drivers = controller(tmp_path, runtime=runtime)
    try:
        result = await manager.wait(manager.submit(BrowserAttemptConfig(task_id=TASK.id))["id"])
        assert result["status"] == "failed" and result["outcome"] is None and result["reward"] == 0
        assert SECRET not in json.dumps(result) and runtime.closed == 1
    finally:
        await manager.close()


@pytest.mark.parametrize("identifier", ["../private", "/etc/passwd", "a//b", "a/../b", "a\\b", "a/%2e%2e/b", "./a", ""])
def test_artifact_identifiers_reject_traversal(identifier):
    with pytest.raises(ValueError):
        relative_artifact_id(identifier)


@pytest.mark.parametrize("action", [{"kind": "eval", "js": "1"}, {"kind": "click", "selector": "#button"},
                                     {"kind": "wait", "seconds": 4.0}, {"kind": "press", "bid": "1", "key": "Control+L"}])
def test_only_allowlisted_browser_action_shapes(action):
    with pytest.raises(ValidationError):
        ACTION_ADAPTER.validate_python(action)


def test_journal_tampering_and_unregistered_private_artifacts_rejected(tmp_path):
    store = BrowserStore(tmp_path)
    key = str(uuid4())
    store.create(key, BrowserAttemptConfig(task_id=TASK.id), TASK, {})
    private = store.directory(key) / "private.json"
    private.write_text(SECRET)
    with pytest.raises(KeyError):
        store.artifact(key, "private.json")
    path = store.directory(key) / "journal.jsonl"
    data = path.read_bytes().replace(b'"queued"', b'"failed"')
    path.write_bytes(data)
    with pytest.raises(BrowserError, match="integrity"):
        store.journal(key)


async def test_recovery_repairs_index_then_interrupts_without_rerun_and_requires_reconciliation(tmp_path):
    store = BrowserStore(tmp_path)
    key = str(uuid4())
    store.create(key, BrowserAttemptConfig(task_id=TASK.id), TASK, {})
    with store.connect() as connection:
        connection.execute("DELETE FROM attempts")
    manager = BrowserRunManager(store, {TASK.id: TASK})
    try:
        assert store.get(key)["status"] == "interrupted"
        assert manager.blocked
        with pytest.raises(BlockingIOError):
            BrowserRunManager(store, {TASK.id: TASK})
    finally:
        await manager.close()


def test_browser_api_explicit_fake_lifecycle_and_safe_artifact_routes(tmp_path):
    constructed = []

    def factory(directory):
        manager, runtime, policy, drivers = controller(directory.parent)
        constructed.append(manager)
        return manager

    with TestClient(create_app(tmp_path / "legacy.sqlite3", browser_factory=factory)) as client:
        assert client.get("/api/browser/tasks").json()["tasks"][0]["application"] == "fake-test-application"
        assert client.get("/api/browser/status").json()["paid_calls_enabled"] is False
        invalid = client.post("/api/browser/attempts", json={"task_id": TASK.id, "api_key": SECRET})
        assert invalid.status_code == 422 and SECRET not in invalid.text
        response = client.post("/api/browser/attempts", json={"task_id": TASK.id, "provider_id": "browser-reference"})
        assert response.status_code == 202
        key = response.json()["id"]
        for _ in range(100):
            detail = client.get(f"/api/browser/attempts/{key}").json()
            if detail["status"] == "completed":
                break
        assert detail["passed"] and SECRET not in json.dumps(detail)
        artifact = detail["artifacts"][0]
        assert client.get(artifact["url"]).status_code == 200
        assert client.get(f"/api/browser/attempts/{key}/artifacts/PRIVATE-sealed-state.json").status_code == 404
        assert client.get("/api/browser/attempts/not-a-uuid").status_code == 404
        assert client.get("/api/browser/attempts?limit=101").status_code == 422
        assert client.get("/api/browser/attempts").json()["attempts"][0]["id"] == key
        assert client.post(f"/api/browser/attempts/{key}/cancel").json()["status"] == "completed"
    assert constructed[0].closing and constructed[0].lock.closed


def test_browser_factory_failure_releases_legacy_writer_lease(tmp_path):
    path = tmp_path / "legacy.sqlite3"

    def failure(directory):
        raise RuntimeError("explicit fake browser initialization failure")

    with pytest.raises(RuntimeError, match="fake browser"):
        with TestClient(create_app(path, browser_factory=failure)):
            pass
    manager = RunManager(Store(path))
    asyncio.run(manager.close())


async def test_bad_model_preparation_never_provisions_application_and_closes_client(tmp_path):
    policy = FakePolicy([])
    policy.fail_prepare = True
    manager, runtime, policy, drivers = controller(tmp_path, policy=policy)
    try:
        result = await manager.wait(manager.submit(BrowserAttemptConfig(task_id=TASK.id))["id"])
        assert result["termination"] == "provider_error" and result["reward"] == 0
        assert runtime.started == runtime.closed == 0 and not drivers
        assert policy.closed == 1 and SECRET not in json.dumps(result)
        assert not any(e["event"] == "runtime_start_intent" for e in result["journal"])
    finally:
        await manager.close()


async def test_uncertified_partial_startup_cleanup_blocks_after_restart(tmp_path):
    class FailedStartup(FakeRuntime):
        async def start(self, attempt_id, task, directory):
            raise BrowserCleanupError("generic owned resource cleanup uncertainty")

    manager, runtime, policy, drivers = controller(tmp_path, runtime=FailedStartup())
    try:
        result = await manager.wait(manager.submit(BrowserAttemptConfig(task_id=TASK.id))["id"])
        assert result["cleanup"]["status"] == "failed" and result["reward"] == 0
        assert manager.blocked and result["reconciliation_required"] and not drivers
        assert policy.closed == 1
    finally:
        await manager.close()
    restarted, _, _, _ = controller(tmp_path)
    try:
        assert restarted.blocked
    finally:
        await restarted.close()


async def test_failed_durable_action_intent_prevents_browser_effect(tmp_path, monkeypatch):
    manager, runtime, policy, drivers = controller(tmp_path)
    original = manager.store.append

    def fail_intent(key, event, data, **kwargs):
        if event == "action_intent":
            raise OSError("explicitly-fake-fsync-failure")
        return original(key, event, data, **kwargs)

    monkeypatch.setattr(manager.store, "append", fail_intent)
    try:
        result = await manager.wait(manager.submit(BrowserAttemptConfig(task_id=TASK.id))["id"])
        assert result["status"] == "failed" and result["steps"] == 0
        assert drivers[0].execute_count == 0 and not runtime.completed
        assert runtime.closed == policy.closed == 1
    finally:
        await manager.close()


async def test_capability_close_failure_skips_grade_and_blocks(tmp_path, monkeypatch):
    manager, runtime, policy, drivers = controller(tmp_path)

    async def failure(driver):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(FakeDriver, "close", failure)
    try:
        result = await manager.wait(manager.submit(BrowserAttemptConfig(task_id=TASK.id))["id"])
        assert result["outcome"] is None and result["reward"] == 0 and manager.blocked
        assert runtime.sealed == 0 and runtime.closed == 1
        assert SECRET not in json.dumps(result)
    finally:
        await manager.close()


def test_regular_evidence_cannot_consume_terminal_reserve(tmp_path, monkeypatch):
    import world_engine.browser_store as store_module

    monkeypatch.setattr(store_module, "MAX_ATTEMPT_BYTES", TERMINAL_RESERVE_BYTES + 16_384)
    store = BrowserStore(tmp_path)
    key = str(uuid4())
    store.create(key, BrowserAttemptConfig(task_id=TASK.id), TASK, {})
    (store.directory(key) / "explicitly-fake-quota-file").write_bytes(b"x" * 16_384)
    with pytest.raises(BrowserError, match="budget"):
        store.append(key, "inference_intent", {})
    store.append(key, "cleanup", {"status": "completed"}, terminal=True)
    store.update(key, terminal=True, status="failed", termination="quota_error")
    assert store.get(key)["status"] == "failed"
    assert store.journal(key)[-1]["event"] == "lifecycle"


async def test_terminal_journal_failure_index_is_uncertain_and_restart_stays_blocked(tmp_path, monkeypatch):
    manager, runtime, policy, drivers = controller(tmp_path)
    original = manager.store.append

    def fail_terminal(key, event, data, **kwargs):
        if kwargs.get("terminal"):
            raise OSError("explicitly-fake-terminal-fsync-failure")
        return original(key, event, data, **kwargs)

    monkeypatch.setattr(manager.store, "append", fail_terminal)
    try:
        result = await manager.wait(manager.submit(BrowserAttemptConfig(task_id=TASK.id))["id"])
        assert result["status"] == "failed" and result["termination"] == "evidence_error"
        assert result["journal_finalization_failed"] and result["reconciliation_required"]
        assert result["outcome"] is None and result["reward"] == 0 and manager.blocked
        assert not manager.jobs and runtime.closed == policy.closed == 1
    finally:
        await manager.close()
    restarted, _, _, _ = controller(tmp_path)
    try:
        assert restarted.blocked and restarted.store.get(result["id"])["journal_finalization_failed"]
    finally:
        await restarted.close()


async def test_created_source_receipt_is_explicit_and_seed_is_consistent(tmp_path):
    manager, _, _, _ = controller(tmp_path)
    try:
        result = await manager.wait(manager.submit(BrowserAttemptConfig(task_id=TASK.id, seed=123))["id"])
        assert result["task"]["seed"] == result["config"]["seed"] == 123
        assert len(result["provenance"]["source_git_revision"]) == 40
        assert type(result["provenance"]["source_dirty"]) is bool
        assert result["provenance"]["training_eligible"] is False
    finally:
        await manager.close()


async def test_navigation_cannot_leave_application_origin(tmp_path):
    manager, runtime, _, drivers = controller(tmp_path, [{"kind": "navigate", "url": "http://127.0.0.1:9998/private"}])
    try:
        result = await manager.wait(manager.submit(BrowserAttemptConfig(task_id=TASK.id))["id"])
        assert result["status"] == "failed" and result["steps"] == 0 and result["reward"] == 0
        assert drivers[0].execute_count == 0 and not runtime.completed
    finally:
        await manager.close()


async def test_cancel_queued_attempt_creates_no_policy_or_application(tmp_path):
    manager, runtime, policy, drivers = controller(tmp_path)
    try:
        run = manager.submit(BrowserAttemptConfig(task_id=TASK.id))
        result = await manager.cancel(run["id"])
        assert result["status"] == "cancelled" and result["cleanup"]["status"] == "completed"
        assert runtime.started == policy.closed == 0 and not drivers
    finally:
        await manager.close()


@pytest.mark.parametrize("changes", [{"provider_id": "openai"}, {"allow_paid": True},
                                     {"max_steps": 51}, {"max_steps": True}, {"timeout_seconds": 29},
                                     {"timeout_seconds": 601}, {"seed": True}])
def test_browser_config_strict_local_only_bounded(changes):
    with pytest.raises(ValidationError):
        BrowserAttemptConfig.model_validate({"task_id": TASK.id, **changes})


async def test_sealed_hash_mismatch_never_invokes_verifier(tmp_path):
    class BadSeal(FakeRuntime):
        async def seal(self, handle):
            sealed = await super().seal(handle)
            return SealedState(sealed.path, "0" * 64, sealed.size_bytes)

        async def grade(self, sealed, task):
            raise AssertionError("verifier must not receive corrupt state")

    manager, runtime, _, _ = controller(tmp_path, runtime=BadSeal())
    try:
        result = await manager.wait(manager.submit(BrowserAttemptConfig(task_id=TASK.id))["id"])
        assert result["termination"] == "grader_error" and result["outcome"] is None
        assert result["reward"] == 0 and runtime.closed == 1
    finally:
        await manager.close()
