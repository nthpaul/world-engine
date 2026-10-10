import asyncio
import hashlib
import importlib
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError

from world_engine.api import create_app
from world_engine.exports import export_records
from world_engine.models import RunConfig, canonical_json, digest
from world_engine.native_config import NativeRunConfig
from world_engine.native_ledger import reconstruct
from world_engine.ollama_tools import LEDGER_PROTOCOL, PROTOCOL, OllamaToolsProvider, contract, request_body
from world_engine.providers import HTTPProvider, ScriptedProvider, make_provider, provider_metadata
from world_engine.rollout import RunManager, replay, rollout
from world_engine.store import Store

ALIASES = [("local-tools", PROTOCOL), ("local-tools-ledger", LEDGER_PROTOCOL)]
WORLDS = ["crm-merge", "refund-ops", "incident-control", "access-provisioning"]
FIXTURE_DIGEST = "a" * 64
ROOT = Path(__file__).resolve().parents[1]
rollout_module = importlib.import_module("world_engine.rollout")


class RawBody(httpx.AsyncByteStream):
    def __init__(self, data):
        self.data = canonical_json(data).encode()

    async def __aiter__(self):
        yield self.data


@pytest.fixture(autouse=True)
def no_revision_subprocess(monkeypatch):
    monkeypatch.setattr(rollout_module, "collection_revision", lambda: {"git_revision": "mock-only"})


def mock_native_transport(monkeypatch, protocol, *, block_chat=None):
    requests, clients = [], []
    oracle = ScriptedProvider()

    async def respond(request):
        requests.append(request)
        if request.url.path == "/api/tags":
            data = {"models": [{"name": "qwen3:8b", "digest": FIXTURE_DIGEST}]}
        elif request.url.path == "/api/show":
            assert json.loads(request.content) == {"model": "qwen3:8b"}
            data = {"capabilities": ["tools", "completion"]}
        elif request.url.path == "/api/version":
            data = {"version": "fixture-ollama"}
        else:
            assert request.url.path == "/api/chat"
            if block_chat is not None:
                block_chat.set()
                await asyncio.Event().wait()
            body = json.loads(request.content)
            public = reconstruct(body) if protocol == LEDGER_PROTOCOL else json.loads(body["messages"][1]["content"])
            decision = await oracle.decide(public["observation"], public["history"])
            data = {"model": "qwen3:8b", "done": True, "done_reason": "stop",
                    "message": {"role": "assistant", "content": "", "tool_calls": [
                        {"function": {"name": decision.action.tool, "arguments": decision.action.args}}]},
                    "prompt_eval_count": 0, "eval_count": 2}
        return httpx.Response(200, stream=RawBody(data))

    def client(provider):
        if provider.client is None:
            provider.client = httpx.AsyncClient(transport=httpx.MockTransport(respond), trust_env=False)
            clients.append(provider.client)
        return provider.client

    monkeypatch.setattr(OllamaToolsProvider, "_client", client)
    return requests, clients


@pytest.mark.parametrize("alias,protocol", ALIASES)
def test_explicit_native_config_defaults_and_strict_evaluation_boundary(alias, protocol):
    config = NativeRunConfig(environment_id="crm-merge", provider_id=alias)
    assert config.evaluation_only is True and config.model is None and config.allow_paid is False
    assert config.model_dump()["provider_id"] == alias
    parsed = TypeAdapter(RunConfig | NativeRunConfig).validate_python(config.model_dump())
    assert type(parsed) is NativeRunConfig
    with pytest.raises(ValidationError):
        RunConfig(environment_id="crm-merge", provider_id=alias, evaluation_only=True)
    for invalid in (False, 1, 0, "true", "false", None):
        with pytest.raises(ValidationError):
            NativeRunConfig(environment_id="crm-merge", provider_id=alias, evaluation_only=invalid)


@pytest.mark.parametrize("provider_id", ["local", "openai", "anthropic", "scripted-oracle", "unknown", "local-tools-v3"])
def test_native_config_cannot_select_other_transports(provider_id):
    with pytest.raises(ValidationError):
        NativeRunConfig(environment_id="crm-merge", provider_id=provider_id)


@pytest.mark.parametrize("alias,protocol", ALIASES)
def test_factory_uses_exact_existing_native_class_and_contract_without_contact(alias, protocol, monkeypatch):
    monkeypatch.delenv("WORLD_ENGINE_ALLOW_PAID", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    provider = make_provider(NativeRunConfig(environment_id="crm-merge", provider_id=alias))
    assert type(provider) is OllamaToolsProvider
    assert provider.provider_protocol == protocol and provider.client is None and not provider.prepared
    assert provider.training_eligible is False and provider.model == "qwen3:8b"
    assert provider.evidence_metadata()["native_contract"] == contract(protocol)


def test_legacy_json_factory_and_explicit_native_sdk_are_unchanged():
    config = RunConfig(environment_id="crm-merge", provider_id="local")
    assert config.evaluation_only is False
    assert type(make_provider(config)) is HTTPProvider
    assert OllamaToolsProvider(config).provider_protocol == PROTOCOL
    assert OllamaToolsProvider(config, protocol=LEDGER_PROTOCOL).provider_protocol == LEDGER_PROTOCOL
    assert digest(contract()) == "0e57c609b4ef58ab4e28551997d9839f0bdd532bd80f6bd3c9fc3bbf4d3a688b"
    assert digest(contract(LEDGER_PROTOCOL)) == "dc8151352b679e29f2490a27116a684128ad7dfabd3078c60e47f7f8585c9fe5"


@pytest.mark.parametrize("available", [True, False])
async def test_catalog_reuses_one_bounded_local_discovery_for_all_three_choices(monkeypatch, available):
    requests, options = [], []
    client_type = httpx.AsyncClient

    async def respond(request):
        requests.append(request)
        assert request.url.path == "/api/tags"
        if not available:
            raise httpx.ConnectError("synthetic offline", request=request)
        return httpx.Response(200, stream=RawBody({"models": [
            {"name": "qwen3:8b", "digest": FIXTURE_DIGEST},
            {"name": "cloud:latest", "digest": FIXTURE_DIGEST},
            {"name": "remote", "digest": FIXTURE_DIGEST, "remote_host": "remote.invalid"},
            {"name": "invalid", "digest": "bad"}, "not-an-object"]}))

    def client(**kwargs):
        options.append(kwargs)
        return client_type(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    rows = {row["id"]: row for row in await provider_metadata()}
    assert len(requests) == 1 and options == [{"timeout": .5, "trust_env": False}]
    assert requests[0].headers["accept-encoding"] == "identity"
    for provider_id in ("local", "local-tools", "local-tools-ledger"):
        row = rows[provider_id]
        assert row["kind"] == "local" and row["requires_opt_in"] is False
        assert row["configured"] is available
        assert row["models"] == (["qwen3:8b"] if available else [])
    assert rows["local-tools"]["name"] == "Native Tools"
    assert rows["local-tools-ledger"]["name"] == "Native Ledger"


@pytest.mark.parametrize("alias,protocol", ALIASES)
@pytest.mark.parametrize("environment_id", WORLDS)
async def test_alias_owned_rollout_exact_wire_replay_and_training_exclusions(tmp_path, monkeypatch, alias, protocol, environment_id):
    requests, clients = mock_native_transport(monkeypatch, protocol)
    config = NativeRunConfig(environment_id=environment_id, provider_id=alias, episodes=1, seed=1,
                             max_steps=20, timeout_seconds=35)
    episode = await rollout(config, 0)
    assert episode["passed"] and replay(episode)["verified"]
    assert all(client.is_closed for client in clients) and len(clients) == 1
    assert episode["provider_cleanup"]["status"] == "completed"
    assert episode["provenance"]["provider_protocol"] == protocol
    assert episode["provenance"]["evaluation_only"] is True
    assert episode["provenance"]["training_eligible"] is False
    chats = [request for request in requests if request.url.path == "/api/chat"]
    assert len(chats) == episode["steps"]
    for index, request in enumerate(chats):
        observation = episode["initial_observation"] if not index else episode["trace"][index - 1]["observation"]
        assert json.loads(request.content) == request_body(
            "qwen3:8b", observation, episode["trace"][:index], protocol=protocol,
            initial_observation=episode["initial_observation"])
    store = Store(tmp_path / "mock.sqlite3")
    run_id = str(uuid4())
    store.create_run(run_id, config)
    store.append_episode(run_id, episode)
    for format in ("sft", "dpo", "grpo"):
        records, report = export_records(store, run_id, format, "all")
        assert records == [] and report["excluded"]["unsupported_provider_protocol"] == 1
    records, report = export_records(store, run_id, "atif", "all")
    assert len(records) == report["records"] == 1
    assert records[0]["extra"]["training_eligible"] is False


@pytest.mark.parametrize("alias,protocol", ALIASES)
async def test_alias_scheduler_persists_config_and_closes_owned_provider(tmp_path, monkeypatch, alias, protocol):
    requests, clients = mock_native_transport(monkeypatch, protocol)
    manager = RunManager(Store(tmp_path / "scheduler.sqlite3"), global_concurrency=1)
    try:
        config = NativeRunConfig(environment_id="crm-merge", provider_id=alias, episodes=2, concurrency=2)
        run = manager.submit(config)
        result = await manager.wait(run["id"])
        assert result["status"] == "completed" and result["passed_episodes"] == 2
        assert result["config"]["provider_id"] == alias and result["config"]["evaluation_only"] is True
        assert len([request for request in requests if request.url.path == "/api/tags"]) == 1
        assert all(replay(episode)["verified"] for episode in result["episodes"])
        assert all(client.is_closed for client in clients) and not manager.jobs
    finally:
        await manager.close()
    assert manager.owner_lock.closed


@pytest.mark.parametrize("alias,protocol", ALIASES)
async def test_alias_cancel_closes_transport_and_preserves_cancelled_episode(tmp_path, monkeypatch, alias, protocol):
    entered = asyncio.Event()
    requests, clients = mock_native_transport(monkeypatch, protocol, block_chat=entered)
    manager = RunManager(Store(tmp_path / "cancel.sqlite3"))
    try:
        run = manager.submit(NativeRunConfig(environment_id="crm-merge", provider_id=alias, episodes=1))
        await asyncio.wait_for(entered.wait(), 2)
        result = await manager.cancel(run["id"])
        assert result["status"] == "cancelled"
        episodes = manager.store.episodes(run["id"])
        assert len(episodes) == 1 and episodes[0]["status"] == "cancelled"
        assert replay(episodes[0])["verified"]
        assert episodes[0]["provider_events"][-1]["outcome"] == "cancelled"
        assert len([request for request in requests if request.url.path == "/api/chat"]) == 1
        assert all(client.is_closed for client in clients) and not manager.jobs
    finally:
        await manager.close()


@pytest.mark.parametrize("alias,protocol", ALIASES)
@pytest.mark.parametrize("mode", ["cloud-model", "missing-tools"])
async def test_alias_preflight_fails_closed_without_chat_and_closes_client(tmp_path, monkeypatch, alias, protocol, mode):
    requests = []

    async def respond(request):
        requests.append(request)
        if request.url.path == "/api/tags":
            model = {"name": "qwen3:8b", "digest": FIXTURE_DIGEST}
            if mode == "cloud-model":
                model["remote_host"] = "remote.invalid"
            data = {"models": [model]}
        else:
            assert request.url.path == "/api/show"
            data = {"capabilities": ["completion"]}
        return httpx.Response(200, stream=RawBody(data))

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond), trust_env=False)
    monkeypatch.setattr(OllamaToolsProvider, "_client", lambda provider: client)
    provider = make_provider(NativeRunConfig(environment_id="crm-merge", provider_id=alias))
    provider.client = client
    manager = RunManager(Store(tmp_path / "preflight.sqlite3"))
    try:
        run = manager.submit(NativeRunConfig(environment_id="crm-merge", provider_id=alias, episodes=1), provider)
        result = await manager.wait(run["id"])
        assert result["status"] == "failed" and result["episodes"] == []
        assert client.is_closed and not provider.prepared and provider.model_digest is None
        assert [request.url.path for request in requests] == (
            ["/api/tags"] if mode == "cloud-model" else ["/api/tags", "/api/show"])
    finally:
        await manager.close()


@pytest.mark.parametrize("alias,protocol", ALIASES)
async def test_alias_admission_rejects_before_provider_factory(tmp_path, monkeypatch, alias, protocol):
    manager = RunManager(Store(tmp_path / "admission.sqlite3"))

    def forbidden(config):
        pytest.fail("rejected admission reached provider factory")

    monkeypatch.setattr(rollout_module, "make_provider", forbidden)
    try:
        manager.jobs = {str(index): object() for index in range(32)}
        with pytest.raises(ValueError, match="admission limit"):
            manager.submit(NativeRunConfig(environment_id="crm-merge", provider_id=alias))
        assert manager.store.list_runs() == []
    finally:
        manager.jobs.clear()
        await manager.close()


@pytest.mark.parametrize("alias,protocol", ALIASES)
def test_api_union_admits_native_typed_config_without_execution(alias, protocol):
    captured = []

    class Manager:
        def submit(self, config):
            captured.append(config)
            return {"id": "mock-no-execution", "provider_id": config.provider_id}

    app = create_app()
    app.state.manager = Manager()
    client = TestClient(app)
    for evaluation_only in (True, "omitted"):
        payload = {"environment_id": "crm-merge", "provider_id": alias}
        if evaluation_only != "omitted":
            payload["evaluation_only"] = evaluation_only
        response = client.post("/api/runs", json=payload)
        assert response.status_code == 202
        assert type(captured[-1]) is NativeRunConfig and captured[-1].evaluation_only is True
    for value in (False, 1, "true"):
        response = client.post("/api/runs", json={"environment_id": "crm-merge", "provider_id": alias,
                                                  "evaluation_only": value})
        assert response.status_code == 422
    assert len(captured) == 2
    response = client.post("/api/runs", json={"environment_id": "crm-merge", "provider_id": "local"})
    assert response.status_code == 202 and type(captured[-1]) is RunConfig
    assert captured[-1].evaluation_only is False


def test_api_union_keeps_unknown_field_errors_redacted():
    client = TestClient(create_app())
    response = client.post("/api/runs", json={"environment_id": "crm-merge", "provider_id": "local-tools",
                                              "api_key": "NATIVE_ENTRYPOINT_SECRET_SENTINEL"})
    assert response.status_code == 422 and "NATIVE_ENTRYPOINT_SECRET_SENTINEL" not in response.text


def test_models_grader_dependency_and_all16_historical_native_replays_remain_valid():
    report = json.loads((ROOT / "artifacts/access-ledger-study/20261010-v1/report.json").read_text())
    expected = report["source"]["files_sha256"]["src/world_engine/models.py"]
    assert hashlib.sha256((ROOT / "src/world_engine/models.py").read_bytes()).hexdigest() == expected
    raw = ROOT / "artifacts/access-ledger-study/20261010-v1/evaluation-episodes.jsonl"
    episodes = [json.loads(line)["episode"] for line in raw.read_text().splitlines()]
    assert len(episodes) == 16 and all(replay(episode)["verified"] for episode in episodes)
