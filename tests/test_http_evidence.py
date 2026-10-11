import asyncio
import base64
import copy
import gzip
import json
import os
import traceback

import httpx
import pytest

from world_engine import make_environment, provider_records
from world_engine.atif import HARBOR_SCHEMA_SHA256, export_episode
from world_engine.exports import export_records
from world_engine.models import RunConfig, canonical_json, digest
from world_engine.providers import (
    JSON_EVIDENCE_PROTOCOL,
    HTTPProvider,
    ProviderError,
    ScriptedProvider,
    json_request_body,
    provider_metadata,
)
from world_engine.rollout import replay, rollout
from world_engine.store import Store

FIXTURE_DIGEST = "a" * 64


class RawBody(httpx.AsyncByteStream):
    def __init__(self, body):
        self.body = body

    async def __aiter__(self):
        yield self.body


def raw_response(data=None, *, body=None, status=200, headers=None):
    content = canonical_json(data).encode() if body is None else body
    return httpx.Response(status, headers=headers, stream=RawBody(content))


def answer(tool="finish", args=None, **extra):
    return {"done": True, "done_reason": "stop", "model": "observed-model",
            "message": {"role": "assistant", "content": canonical_json({"tool": tool, "args": args or {}})}, **extra}


async def prepared(config, reply, *, record_calls=True, tags=None, shown=None, version="fixture"):
    requests = []

    async def respond(request):
        requests.append(request)
        if request.url.path == "/api/tags":
            return raw_response(tags if tags is not None else {"models": [{"name": "qwen3:8b", "digest": FIXTURE_DIGEST}]})
        if request.url.path == "/api/show":
            return raw_response(shown if shown is not None else {"capabilities": ["completion"]})
        if request.url.path == "/api/version":
            return raw_response({"version": version})
        return await reply(request) if callable(reply) else raw_response(reply)

    provider = HTTPProvider(config, record_calls=record_calls)
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        await provider.prepare()
    except BaseException:
        await provider.close()
        raise
    return provider, requests


async def episode(reply=None, *, record_calls=True, **fields):
    config = RunConfig(environment_id="crm-merge", provider_id="local", seed=730, **fields)
    provider, requests = await prepared(config, reply if reply is not None else answer(), record_calls=record_calls)
    try:
        result = await rollout(config, 0, provider)
    finally:
        await provider.close()
    return result, requests


async def test_exact_json_bytes_provenance_usage_and_no_private_context():
    data = answer(prompt_eval_count=0, eval_count=7)
    ep, requests = await episode(data, evaluation_only=True)
    start, end = ep["provider_events"]
    assert requests[-1].content == start["request_body"].encode()
    assert start["request_body"] == canonical_json(json_request_body("local", "qwen3:8b", ep["initial_observation"], []))
    assert json.loads(start["request_body"])["format"]["additionalProperties"] is False
    assert provider_records.response_bytes(end) == canonical_json(data).encode()
    assert end["usage"] == {"model": "observed-model", "input_tokens": 0, "output_tokens": 7}
    assert ep["usage"]["request_attempts"] == 1 and ep["usage"]["input_tokens"] == 0
    assert ep["provenance"]["provider_protocol"] == JSON_EVIDENCE_PROTOCOL
    assert ep["provenance"]["provider_record_calls"] is True
    assert ep["provenance"]["training_eligible"] is False
    assert ep["provenance"]["provider_evidence"]["json_contract"]["record_calls"] is True
    assert all("headers" not in item and "endpoint" not in item for item in ep["provider_events"])
    assert "initial_snapshot" not in start["request_body"] and "grader" not in start["request_body"]
    assert "127.0.0.1" not in canonical_json(ep["provider_events"])
    assert replay(ep)["verified"]


@pytest.mark.parametrize("record_calls", [False, True])
async def test_direct_local_decide_requires_preflight_without_chat(record_calls):
    requests = []

    async def respond(request):
        requests.append(request)
        return raw_response(answer())

    provider = HTTPProvider(RunConfig(environment_id="crm-merge", provider_id="local"), record_calls=record_calls)
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(ProviderError, match="prepare"):
            await provider.decide(make_environment("crm-merge", 42).observe(), [])
        assert requests == []
    finally:
        await provider.close()


async def test_close_invalidates_local_preflight_and_recording_needs_rollout():
    config = RunConfig(environment_id="crm-merge", provider_id="local")
    provider, requests = await prepared(config, answer())
    with pytest.raises(ProviderError, match="active rollout"):
        await provider.decide(make_environment("crm-merge", 42).observe(), [])
    assert len(requests) == 3
    await provider.close()
    with pytest.raises(ProviderError, match="prepare"):
        await provider.decide(make_environment("crm-merge", 42).observe(), [])


async def test_model_change_requires_new_preflight_before_chat():
    config = RunConfig(environment_id="crm-merge", provider_id="local")
    provider, requests = await prepared(config, answer(), record_calls=False)
    try:
        provider.model = "different-model"
        with pytest.raises(ProviderError, match="prepare"):
            await provider.decide(make_environment("crm-merge", 42).observe(), [])
        assert len(requests) == 3
    finally:
        await provider.close()


@pytest.mark.parametrize("version", ["x" * 60_000, "bad\nversion", "", None], ids=["oversize", "control", "empty", "missing"])
async def test_daemon_metadata_never_expands_provenance_unbounded(version):
    provider, _ = await prepared(RunConfig(environment_id="crm-merge", provider_id="local"), answer(), version=version)
    try:
        assert provider.daemon_version is None and provider.evidence_metadata()["ollama_version"] is None
    finally:
        await provider.close()


@pytest.mark.parametrize("record_calls", [True, "yes", 1])
def test_record_option_is_boolean_and_local_only(record_calls):
    with pytest.raises(ProviderError, match="local-only"):
        HTTPProvider(RunConfig(environment_id="crm-merge", provider_id="openai"), record_calls=record_calls)


@pytest.mark.parametrize(("tags", "shown"), [
    ({"models": [{"name": "qwen3:8b", "digest": FIXTURE_DIGEST, "remote_host": "cloud.invalid"}]}, None),
    ({"models": [{"name": "qwen3:8b", "digest": FIXTURE_DIGEST, "remote_model": "cloud"}]}, None),
    ({"models": [{"name": "qwen3:8b", "digest": "mutable-name"}]}, None),
    ({"models": []}, None), ({"models": {}}, None),
    (None, {"capabilities": ["completion"], "remote_model": "cloud"}),
    (None, {"capabilities": "completion"}), (None, {"capabilities": ["embedding"]}),
])
async def test_cloud_invalid_catalog_and_capability_fail_before_chat(tags, shown):
    with pytest.raises(ProviderError):
        await prepared(RunConfig(environment_id="crm-merge", provider_id="local"), answer(), tags=tags, shown=shown)


async def test_cloud_model_name_fails_before_any_metadata_request():
    requests = []
    provider = HTTPProvider(RunConfig(environment_id="crm-merge", provider_id="local", model="cloud-model"))
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: requests.append(request)))
    try:
        with pytest.raises(ProviderError, match="cloud"):
            await provider.prepare()
        assert requests == []
    finally:
        await provider.close()


@pytest.mark.parametrize("stage", ["/api/tags", "/api/show", "/api/version"])
@pytest.mark.parametrize("encoding", ["oversize", "gzip", "not-object"])
async def test_metadata_is_raw_bounded_and_fails_closed_at_every_stage(stage, encoding):
    requests = []

    async def respond(request):
        requests.append(request.url.path)
        if request.url.path == stage:
            if encoding == "oversize":
                return raw_response(body=b"x" * (provider_records.MAX_RESPONSE_BYTES + 1))
            if encoding == "gzip":
                return raw_response(body=gzip.compress(b"{}" * 100_000), headers={"content-encoding": "gzip"})
            return raw_response(body=b"null")
        data = {"models": [{"name": "qwen3:8b", "digest": FIXTURE_DIGEST}]} if request.url.path == "/api/tags" else {"capabilities": ["completion"]}
        return raw_response(data)

    provider = HTTPProvider(RunConfig(environment_id="crm-merge", provider_id="local"))
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(ProviderError):
            await provider.prepare()
        assert not provider.prepared and "/api/chat" not in requests
    finally:
        await provider.close()


async def test_provider_metadata_filters_cloud_invalid_entries_and_uses_bounded_stream(monkeypatch):
    valid = {"name": "qwen3:8b", "digest": FIXTURE_DIGEST}
    entries = [valid, {**valid, "name": "cloud:latest"}, {**valid, "remote_host": "cloud.invalid"},
               {**valid, "remote_model": "remote"}, {**valid, "digest": "invalid"},
               {**valid, "name": "x" * 201}, {**valid, "name": "bad\nname"}, "not-object"]
    client_type = httpx.AsyncClient
    requests = []

    async def respond(request):
        requests.append(request)
        return raw_response({"models": entries})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs))
    result = await provider_metadata()
    local = next(row for row in result if row["id"] == "local")
    assert local["models"] == ["qwen3:8b"] and local["configured"]
    assert len(requests) == 1 and requests[0].headers["accept-encoding"] == "identity"


@pytest.mark.parametrize("mode", ["gzip", "oversize", "invalid"])
async def test_provider_metadata_unavailable_states_do_not_offer_invalid_models(monkeypatch, mode):
    client_type = httpx.AsyncClient

    async def respond(request):
        if mode == "gzip":
            return raw_response(body=gzip.compress(b"{}"), headers={"content-encoding": "gzip"})
        return raw_response(body=b"x" * (provider_records.MAX_RESPONSE_BYTES + 1) if mode == "oversize" else b"null")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs))
    local = next(row for row in await provider_metadata() if row["id"] == "local")
    assert local["models"] == [] and local["configured"] is False


@pytest.mark.parametrize("endpoint", ["http://service.invalid/v1", "https://user:secret@service.invalid/v1",
                                      "https://service.invalid/v1?key=secret", "https://service.invalid/v1#secret"])
def test_remote_endpoint_requires_secure_plain_url(monkeypatch, endpoint):
    monkeypatch.setenv("WORLD_ENGINE_ALLOW_PAID", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key")
    monkeypatch.setenv("WORLD_ENGINE_OPENAI_URL", endpoint)
    with pytest.raises(ProviderError):
        HTTPProvider(RunConfig(environment_id="crm-merge", provider_id="openai", allow_paid=True))


@pytest.mark.parametrize("kind", ["openai", "anthropic"])
async def test_remote_actual_reported_names_and_unknown_usage_without_live_calls(monkeypatch, kind):
    monkeypatch.setenv("WORLD_ENGINE_ALLOW_PAID", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-key")
    content = canonical_json({"tool": "finish", "args": {}})
    data = ({"model": "observed-remote", "choices": [{"message": {"content": content}}],
             "usage": {"prompt_tokens": 0, "completion_tokens": -1}} if kind == "openai" else
            {"model": "observed-remote", "content": [{"type": "text", "text": content}],
             "usage": {"input_tokens": 0, "output_tokens": True}})
    provider = HTTPProvider(RunConfig(environment_id="crm-merge", provider_id=kind, model="configured-model", allow_paid=True))
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: raw_response(data)))
    try:
        result = await provider.decide(make_environment("crm-merge", 42).observe(), [])
        assert result.usage == {"model": "observed-remote", "input_tokens": 0}
    finally:
        await provider.close()


@pytest.mark.parametrize(("kind", "data"), [
    ("openai", {"choices": [1]}), ("openai", {"choices": []}),
    ("openai", {"choices": {}}), ("openai", {"choices": [{"message": None}]}),
    ("openai", {"choices": [{"message": {"content": {}}}]}),
    ("anthropic", {"content": [1]}), ("anthropic", {"content": {}}),
    ("anthropic", {"content": [{"type": "text", "text": None}]}),
])
async def test_remote_malformed_objects_raise_redacted_provider_error(monkeypatch, kind, data):
    monkeypatch.setenv("WORLD_ENGINE_ALLOW_PAID", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-key")
    provider = HTTPProvider(RunConfig(environment_id="crm-merge", provider_id=kind, allow_paid=True))
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: raw_response(data)))
    try:
        with pytest.raises(ProviderError, match="invalid action"):
            await provider.decide(make_environment("crm-merge", 42).observe(), [])
    finally:
        await provider.close()


@pytest.mark.parametrize("boundary", ["response", "network", "metadata"])
async def test_direct_sdk_exception_traceback_never_reflects_provider_secret(monkeypatch, boundary):
    sentinel = "SYNTHETIC-SECRET-NEVER-REFLECT"
    monkeypatch.setenv("WORLD_ENGINE_ALLOW_PAID", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key")
    kind = "local" if boundary == "metadata" else "openai"
    provider = HTTPProvider(RunConfig(environment_id="crm-merge", provider_id=kind, allow_paid=True))
    async def respond(request):
        if boundary == "network":
            raise httpx.ConnectError(sentinel)
        if boundary == "metadata":
            raise httpx.ReadError(sentinel)
        return raw_response({"choices": [{"message": {"content": canonical_json({"tool": sentinel, "args": sentinel})}}]})
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(ProviderError) as captured:
            if boundary == "metadata":
                await provider.prepare()
            else:
                await provider.decide(make_environment("crm-merge", 42).observe(), [])
        formatted = "".join(traceback.format_exception(captured.value))
        assert sentinel not in formatted and captured.value.__suppress_context__
    finally:
        await provider.close()


@pytest.mark.parametrize("record_calls", [False, True])
@pytest.mark.parametrize("value", [None, True, -1, 1.5, 2**63])
async def test_missing_invalid_usage_and_model_not_invented(record_calls, value):
    ep, _ = await episode(answer(model="bad\nname", prompt_eval_count=value, eval_count=3), record_calls=record_calls)
    assert ep["trace"][0]["usage"] == {"output_tokens": 3}
    assert "input_tokens" not in ep["usage"] and ep["usage"]["input_tokens_complete"] is False
    assert ep["usage"]["output_tokens"] == 3 and ep["usage"]["output_tokens_complete"] is True
    assert replay(ep)["verified"]


@pytest.mark.parametrize("record_calls", [False, True])
@pytest.mark.parametrize(("field", "value", "missing"), [
    ("done", None, True), ("done", False, False), ("done", 0, False), ("done", 1, False),
    ("done", "false", False), ("done", "true", False),
    ("done_reason", None, True), ("done_reason", None, False), ("done_reason", "unknown", False),
    ("done_reason", "length", False), ("done_reason", True, False),
], ids=["missing-done", "false", "zero", "one", "string-false", "string-true",
        "missing-reason", "null-reason", "unknown-reason", "length", "boolean-reason"])
async def test_only_exact_local_completion_metadata_can_supply_action(record_calls, field, value, missing):
    data = answer()
    if missing:
        del data[field]
    else:
        data[field] = value
    ep, requests = await episode(data, record_calls=record_calls)
    assert ep["steps"] == 0 and ep["termination"] == "provider_error"
    assert len([request for request in requests if request.url.path == "/api/chat"]) == 1
    if record_calls:
        end = ep["provider_events"][1]
        assert end["outcome"] == "invalid_response" and end["body_complete"] and not end["complete"]
        assert json.loads(provider_records.response_bytes(end)) == data
    assert replay(ep)["verified"]


@pytest.mark.parametrize("record_calls", [False, True])
@pytest.mark.parametrize("case", ["missing-message", "null", "list", "string", "missing-role", "wrong-role",
                                 "native-call", "malformed-calls"])
async def test_local_json_rejects_wrong_speaker_and_competing_actions(record_calls, case):
    data = answer()
    if case == "missing-message":
        del data["message"]
    elif case in ("null", "list", "string"):
        data["message"] = {"null": None, "list": [], "string": "not-object"}[case]
    elif case == "missing-role":
        del data["message"]["role"]
    elif case == "wrong-role":
        data["message"]["role"] = "user"
    else:
        data["message"]["tool_calls"] = ([{"function": {"name": "inspect", "arguments": {}}}]
                                          if case == "native-call" else None)
    ep, _ = await episode(data, record_calls=record_calls)
    assert ep["steps"] == 0 and ep["termination"] == "provider_error"
    if record_calls:
        end = ep["provider_events"][1]
        assert end["outcome"] == "invalid_response" and end["body_complete"] and not end["complete"]
        assert json.loads(provider_records.response_bytes(end)) == data
    assert replay(ep)["verified"]


@pytest.mark.parametrize("record_calls", [False, True])
async def test_local_json_allows_explicit_empty_native_calls(record_calls):
    data = answer()
    data["message"]["tool_calls"] = []
    ep, _ = await episode(data, record_calls=record_calls)
    assert ep["steps"] == 1 and ep["termination"] == "finished" and replay(ep)["verified"]


@pytest.mark.parametrize("model", [None, "", "x" * 201, "model\x7fcontrol"], ids=["missing", "empty", "oversize", "control"])
async def test_unknown_reported_name_is_absent_not_configured_model(model):
    ep, _ = await episode(answer(model=model))
    assert "model" not in ep["trace"][0]["usage"]
    assert json.loads(provider_records.response_bytes(ep["provider_events"][1]))["model"] == model
    assert replay(ep)["verified"]


async def test_maximum_unicode_reported_metadata_fits_finish_reservation():
    data = answer(model="\U0001f600" * 200, prompt_eval_count=2**63 - 1, eval_count=2**63 - 1,
                  total_duration=2**63 - 1, padding="")
    data["padding"] = "x" * (provider_records.MAX_RESPONSE_BYTES - len(canonical_json(data).encode()))
    body = canonical_json(data).encode()
    assert len(body) == provider_records.MAX_RESPONSE_BYTES
    async def reply(request):
        return raw_response(body=body)
    ep, _ = await episode(reply)
    end = ep["provider_events"][1]
    assert len(canonical_json(end).encode()) <= provider_records.MAX_FINISH_BYTES
    assert end["usage"]["model"] == data["model"] and end["usage"]["input_tokens"] == 2**63 - 1
    assert replay(ep)["verified"]


@pytest.mark.parametrize(("body", "status", "headers", "outcome"), [
    (b"null", 200, {}, "invalid_response"), (b"not JSON", 200, {}, "invalid_response"),
    (b"private secret response", 403, {}, "http_error"),
    (b"x" * (provider_records.MAX_RESPONSE_BYTES + 1), 200, {}, "oversized_response"),
    (gzip.compress(canonical_json(answer()).encode()), 200, {"content-encoding": "gzip"}, "unsupported_encoding"),
], ids=["null", "invalid-json", "http", "oversize", "compressed"])
async def test_failed_json_calls_retain_bounded_raw_evidence(body, status, headers, outcome):
    async def reply(request):
        return raw_response(body=body, status=status, headers=headers)
    ep, requests = await episode(reply)
    end = ep["provider_events"][1]
    assert ep["steps"] == 0 and ep["termination"] == "provider_error"
    assert end["outcome"] == outcome and not end["complete"]
    assert provider_records.response_bytes(end) == body[:provider_records.MAX_RESPONSE_BYTES]
    assert end["body_complete"] is (outcome != "oversized_response")
    assert len([r for r in requests if r.url.path == "/api/chat"]) == 1
    assert "secret" not in ep["error"] and replay(ep)["verified"]
    if outcome == "invalid_response":
        end["outcome"] = "connection_error"
        with pytest.raises(ValueError, match="mislabeled"):
            replay(ep)


@pytest.mark.parametrize("failure", ["connection", "timeout"])
async def test_failed_response_prefix_is_paired_and_usage_unknown(failure):
    class FailedBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"bounded-prefix"
            error = httpx.ReadTimeout if failure == "timeout" else httpx.ReadError
            raise error("secret connection detail")
    async def reply(request):
        return httpx.Response(200, stream=FailedBody())
    ep, _ = await episode(reply)
    end = ep["provider_events"][1]
    assert end["outcome"] == ("timeout" if failure == "timeout" else "connection_error")
    assert not end["body_complete"] and end["usage"] == {}
    assert provider_records.response_bytes(end) == b"bounded-prefix"
    assert "secret" not in ep["error"] and "input_tokens" not in ep["usage"]
    assert replay(ep)["verified"]


@pytest.mark.parametrize("cancel", [False, True])
async def test_timeout_and_cancellation_always_finalize_paired_call(cancel):
    started = asyncio.Event()
    async def reply(request):
        started.set()
        await asyncio.sleep(60)
        return raw_response(answer())
    config = RunConfig(environment_id="crm-merge", provider_id="local", timeout_seconds=1)
    provider, _ = await prepared(config, reply)
    try:
        task = asyncio.create_task(rollout(config, 0, provider))
        await started.wait()
        if cancel:
            task.cancel()
        ep = await task
        assert ep["termination"] == ("cancelled" if cancel else "timeout")
        assert ep["provider_events"][1]["outcome"] == "cancelled"
        assert len(ep["provider_events"]) == 2 and replay(ep)["verified"]
    finally:
        await provider.close()


async def test_concurrent_shared_provider_has_episode_local_records():
    async def reply(request):
        await asyncio.sleep(0)
        return raw_response(answer())
    config = RunConfig(environment_id="crm-merge", provider_id="local", seed=42)
    provider, _ = await prepared(config, reply)
    try:
        results = await asyncio.gather(*(rollout(config, index, provider) for index in range(3)))
    finally:
        await provider.close()
    assert len({ep["provider_events"][0]["call_id"] for ep in results}) == 3
    for ep in results:
        assert len(ep["provider_events"]) == 2 and replay(ep)["verified"]
        payload = json.loads(json.loads(ep["provider_events"][0]["request_body"])["messages"][1]["content"])
        assert payload["history"] == [] and payload["observation"] == ep["initial_observation"]


async def test_request_and_episode_budget_stop_before_transport(monkeypatch):
    config = RunConfig(environment_id="crm-merge", provider_id="local")
    provider, requests = await prepared(config, answer())
    try:
        observation = make_environment("crm-merge", 42).observe()
        observation["state"]["padding"] = "x" * provider_records.MAX_REQUEST_BYTES
        events, token = provider_records.begin_episode()
        try:
            with pytest.raises(ProviderError, match="128 KiB"):
                await provider.decide(observation, [])
            assert events == []
        finally:
            provider_records.end_episode(token)
        monkeypatch.setattr(provider_records, "MAX_EPISODE_RECORD_BYTES", 50)
        ep = await rollout(config, 0, provider)
        assert ep["provider_events"] == [] and "evidence budget" in ep["error"]
        assert all(request.url.path != "/api/chat" for request in requests)
        assert replay(ep)["verified"]
    finally:
        await provider.close()


async def test_near_cap_huge_metadata_stays_paired_and_next_call_blocked(monkeypatch):
    monkeypatch.setattr(provider_records, "MAX_EPISODE_RECORD_BYTES", 150_000)
    data = answer("inspect", model="x" * 60_000, prompt_eval_count=2**1024, eval_count=2**1024)
    ep, requests = await episode(data, max_steps=20)
    chats = [request for request in requests if request.url.path == "/api/chat"]
    assert len(chats) == ep["steps"] == 1 and len(ep["provider_events"]) == 2
    assert ep["provider_events"][1]["usage"] == {}
    assert "evidence budget" in ep["error"] and ep["termination"] == "provider_error"
    assert provider_records.recorded_bytes(ep["provider_events"]) <= 150_000
    assert replay(ep)["verified"]


async def test_replay_rejects_bytes_contract_source_mode_usage_and_action_mutations():
    original, _ = await episode(answer(prompt_eval_count=3))
    mutations = [
        lambda ep: ep["provider_events"][0].update(request_sha256="0" * 64),
        lambda ep: ep["provider_events"][1].update(response_sha256="0" * 64),
        lambda ep: ep["provider_events"][1].update(usage={"input_tokens": 4}),
        lambda ep: ep["provenance"].update(provider_record_calls=False),
        lambda ep: ep["provenance"].pop("provider_protocol"),
        lambda ep: ep["provenance"].update(training_eligible=True),
        lambda ep: ep["provenance"]["provider_evidence"].update(json_contract_hash="0" * 64),
        lambda ep: ep["provenance"]["provider_evidence"].update(provider_module_sha256="0" * 64),
        lambda ep: ep["provenance"].update(provider_source_hash="0" * 64),
        lambda ep: ep["provenance"].update(policy_hash="0" * 64),
    ]
    for mutate in mutations:
        ep = copy.deepcopy(original)
        mutate(ep)
        with pytest.raises(ValueError):
            replay(ep)
    ep = copy.deepcopy(original)
    start = ep["provider_events"][0]
    body = json.loads(start["request_body"])
    body["options"]["num_predict"] = 1024
    start["request_body"] = canonical_json(body)
    start["request_bytes"] = len(start["request_body"].encode())
    start["request_sha256"] = provider_records.byte_hash(start["request_body"].encode())
    with pytest.raises(ValueError, match="JSON request"):
        replay(ep)
    ep = copy.deepcopy(original)
    end = ep["provider_events"][1]
    body = canonical_json(answer("inspect", prompt_eval_count=3)).encode()
    end.update(response_body_b64=base64.b64encode(body).decode(), response_bytes=len(body),
               response_sha256=provider_records.byte_hash(body))
    with pytest.raises(ValueError, match="JSON response action"):
        replay(ep)


async def test_default_training_stays_eligible_recorded_json_and_candidates_do_not(tmp_path):
    oracle = ScriptedProvider()
    async def reply(request):
        payload = json.loads(json.loads(request.content)["messages"][1]["content"])
        decision = await oracle.decide(payload["observation"], payload["history"])
        return raw_response(answer(decision.action.tool, decision.action.args))
    recorded, _ = await episode(reply)
    legacy, _ = await episode(reply, record_calls=False)
    assert recorded["passed"] and legacy["passed"]
    assert legacy["provenance"]["provider_record_calls"] is False and "provider_events" not in legacy
    assert legacy["provenance"]["policy_hash"] != recorded["provenance"]["policy_hash"]
    store = Store(tmp_path / "export.sqlite3")
    config = RunConfig(environment_id="crm-merge", provider_id="local", seed=730)
    for name, ep in (("recorded", recorded), ("legacy", legacy)):
        store.create_run(name, config)
        store.append_episode(name, ep)
    for fmt in ("sft", "dpo", "grpo"):
        records, report = export_records(store, "recorded", fmt, "all")
        assert records == [] and report["excluded"]["unsupported_provider_protocol"] == 1
    records, _ = export_records(store, "legacy", "sft", "all")
    assert len(records) == legacy["steps"]
    for fmt in ("dpo", "grpo"):
        records, report = export_records(store, "legacy", fmt, "all")
        assert records == [] and report["excluded"]["insufficient_alternatives"] == 1
    records, _ = export_records(store, "recorded", "traces", "all")
    assert records[0]["provider_events"] == recorded["provider_events"]
    document = export_episode(recorded)
    assert document["extra"]["world_engine"]["provider_events"] == recorded["provider_events"]
    assert document["extra"]["training_eligible"] is False
    assert "provider request/response" in document["notes"]


async def test_legacy_failed_call_keeps_known_usage_without_claiming_complete_total():
    calls = 0
    async def reply(request):
        nonlocal calls
        calls += 1
        return raw_response(answer("inspect", prompt_eval_count=2, eval_count=3)) if calls == 1 else raw_response(body=b"null")
    ep, _ = await episode(reply, record_calls=False)
    assert ep["steps"] == 1 and ep["termination"] == "provider_error"
    assert ep["usage"]["input_tokens_known"] == 2 and ep["usage"]["output_tokens_known"] == 3
    assert not ep["usage"]["input_tokens_complete"] and "input_tokens" not in ep["usage"]
    assert replay(ep)["verified"]


async def test_pinned_upstream_accepts_recorded_json_success_and_failure():
    if os.environ.get("WORLD_ENGINE_ATIF_VALIDATE_UPSTREAM") != "1":
        pytest.skip("Enable isolated pinned Harbor validation using docs/atif.md")
    from harbor.models.trajectories.trajectory import Trajectory
    assert digest(Trajectory.model_json_schema()) == HARBOR_SCHEMA_SHA256
    async def bad(request):
        return raw_response(body=b"null")
    for reply in (answer(), bad):
        ep, _ = await episode(reply)
        Trajectory.model_validate(export_episode(ep))
