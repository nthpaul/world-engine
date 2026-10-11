import gzip
import json
import traceback

import httpx
import pytest

from world_engine import make_environment, provider_records
from world_engine.models import RunConfig
from world_engine.ollama_tools import NativeResponseError, OllamaToolsProvider, parse_action
from world_engine.providers import ProviderError
from world_engine.rollout import replay, rollout

SENTINEL = "PRIVATE_NATIVE_ERROR_SENTINEL_20261010"
DEEP_JSON = b"[" * 30000 + b"0" + b"]" * 30000


class RawBody(httpx.AsyncByteStream):
    def __init__(self, body):
        self.body = body

    async def __aiter__(self):
        yield self.body


def native_response(arguments):
    return {"done": True, "done_reason": "stop", "message": {"role": "assistant", "tool_calls": [
        {"function": {"name": "finish", "arguments": arguments}}]}}


def provider_with_transport(respond):
    config = RunConfig(environment_id="crm-merge", provider_id="local", max_steps=1, evaluation_only=True)
    provider = OllamaToolsProvider(config)
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(respond), trust_env=False)
    provider.prepared = True
    provider.prepared_model = provider.model
    provider.model_digest = "a" * 64
    return provider, config


async def invoke(provider, operation):
    if operation == "metadata":
        return await provider._metadata("/api/tags")
    _, token = provider_records.begin_episode()
    try:
        return await provider.decide(make_environment("crm-merge", 730).observe(), [])
    finally:
        provider_records.end_episode(token)


def assert_public_error_redacted(error):
    assert SENTINEL not in str(error)
    assert SENTINEL not in "".join(traceback.format_exception(error))
    assert error.__cause__ is None
    assert error.__suppress_context__


@pytest.mark.parametrize("operation", ["metadata", "chat"])
@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ReadTimeout])
async def test_sdk_transport_traceback_does_not_reveal_connection_details(operation, failure):
    def respond(request):
        raise failure(SENTINEL, request=request)

    provider, _ = provider_with_transport(respond)
    try:
        with pytest.raises(ProviderError) as captured:
            await invoke(provider, operation)
        assert_public_error_redacted(captured.value)
    finally:
        await provider.close()


@pytest.mark.parametrize("operation", ["metadata", "chat"])
async def test_sdk_json_exception_traceback_does_not_reveal_parser_details(operation, monkeypatch):
    def fail_json(*args, **kwargs):
        raise json.JSONDecodeError(SENTINEL, SENTINEL, 0)

    monkeypatch.setattr("world_engine.ollama_tools.json.loads", fail_json)
    provider, _ = provider_with_transport(lambda request: httpx.Response(200, stream=RawBody(b"{}")))
    try:
        with pytest.raises(ProviderError) as captured:
            await invoke(provider, operation)
        assert_public_error_redacted(captured.value)
    finally:
        await provider.close()


async def test_sdk_protocol_traceback_does_not_reveal_pydantic_input():
    body = json.dumps(native_response(SENTINEL)).encode()
    provider, _ = provider_with_transport(lambda request: httpx.Response(200, stream=RawBody(body)))
    try:
        with pytest.raises(ProviderError) as captured:
            await invoke(provider, "chat")
        assert_public_error_redacted(captured.value)
    finally:
        await provider.close()


def test_public_native_parser_does_not_chain_pydantic_input():
    with pytest.raises(NativeResponseError) as captured:
        parse_action(native_response(SENTINEL))
    assert_public_error_redacted(captured.value)


def test_public_native_parser_normalizes_deep_action_serialization():
    nested = 0
    for _ in range(30000):
        nested = [nested]
    with pytest.raises(NativeResponseError) as captured:
        parse_action(native_response({"nested": nested}))
    assert_public_error_redacted(captured.value)


async def test_bounded_deep_metadata_is_normalized_to_provider_error():
    assert len(DEEP_JSON) < provider_records.MAX_RESPONSE_BYTES
    provider, _ = provider_with_transport(lambda request: httpx.Response(200, stream=RawBody(DEEP_JSON)))
    try:
        with pytest.raises(ProviderError) as captured:
            await invoke(provider, "metadata")
        assert_public_error_redacted(captured.value)
    finally:
        await provider.close()


async def test_bounded_deep_chat_is_recorded_failure_with_replayable_envelope():
    provider, config = provider_with_transport(lambda request: httpx.Response(200, stream=RawBody(DEEP_JSON)))
    try:
        episode = await rollout(config, 0, provider)
    finally:
        await provider.close()
    assert episode["termination"] == "provider_error"
    assert episode["steps"] == 0 and not episode["passed"] and episode["reward"] == 0
    end = episode["provider_events"][1]
    assert end["outcome"] == "invalid_response" and end["body_complete"]
    assert provider_records.response_bytes(end) == DEEP_JSON
    assert replay(episode)["verified"]


async def test_metadata_rejects_encoding_before_reading_or_expanding_body():
    packed = gzip.compress(b" " * 1048576 + b"{}")
    assert len(packed) < provider_records.MAX_RESPONSE_BYTES
    reads = []
    requests = []

    class EncodedBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            reads.append(len(packed))
            yield packed

    def respond(request):
        requests.append(request)
        return httpx.Response(200, headers={"content-encoding": "gzip"}, stream=EncodedBody())

    provider, _ = provider_with_transport(respond)
    try:
        with pytest.raises(ProviderError):
            await invoke(provider, "metadata")
        assert requests[0].headers["accept-encoding"] == "identity"
        assert reads == [], "compressed metadata must be rejected before decompressor allocation"
    finally:
        await provider.close()


async def test_multichunk_identity_metadata_stops_at_raw_limit():
    reads = []
    half = provider_records.MAX_RESPONSE_BYTES // 2

    class ChunkedBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            for chunk in (b" " * half, b" " * (half + 1), b"must-not-read"):
                reads.append(len(chunk))
                yield chunk

    provider, _ = provider_with_transport(lambda request: httpx.Response(200, stream=ChunkedBody()))
    try:
        with pytest.raises(ProviderError, match="exceeded its limit"):
            await invoke(provider, "metadata")
        assert reads == [half, half + 1]
    finally:
        await provider.close()


async def test_failed_reprepare_clears_old_identity_and_blocks_chat():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, stream=RawBody(b'{"models":[]}'))

    provider, _ = provider_with_transport(respond)
    provider.daemon_version = "old-daemon"
    try:
        with pytest.raises(ProviderError):
            await provider.prepare()
        assert not provider.prepared
        assert provider.prepared_model is None
        assert provider.model_digest is None and provider.daemon_version is None
        with pytest.raises(ProviderError):
            await invoke(provider, "chat")
        assert [request.url.path for request in requests] == ["/api/tags"]
    finally:
        await provider.close()


@pytest.mark.parametrize("changed_model", ["different-local-model", "unprepared-cloud-alias"])
async def test_changed_model_after_preflight_sends_no_chat_or_attempt(changed_model):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, stream=RawBody(json.dumps(native_response({})).encode()))

    provider, _ = provider_with_transport(respond)
    provider.model = changed_model
    events, token = provider_records.begin_episode()
    try:
        with pytest.raises(ProviderError):
            await provider.decide(make_environment("crm-merge", 730).observe(), [])
        assert requests == []
        assert events == []
    finally:
        provider_records.end_episode(token)
        await provider.close()


async def test_model_changed_during_preflight_cannot_publish_identity():
    requests = []
    provider, _ = provider_with_transport(lambda request: None)
    original_model = provider.model

    def respond(request):
        requests.append(request)
        if request.url.path == "/api/tags":
            provider.model = "changed-during-prepare"
            body = {"models": [{"name": original_model, "digest": "a" * 64}]}
        elif request.url.path == "/api/show":
            assert json.loads(request.content)["model"] == original_model
            body = {"capabilities": ["tools"]}
        else:
            body = {"version": "fixture-version"}
        return httpx.Response(200, stream=RawBody(json.dumps(body).encode()))

    await provider.client.aclose()
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(respond), trust_env=False)
    try:
        with pytest.raises(ProviderError, match="changed during preparation"):
            await provider.prepare()
        assert not provider.prepared and provider.prepared_model is None
        assert provider.model_digest is None and provider.daemon_version is None
        with pytest.raises(ProviderError):
            await invoke(provider, "chat")
        assert [request.url.path for request in requests] == ["/api/tags", "/api/show", "/api/version"]
    finally:
        await provider.close()
    assert not provider.prepared and provider.prepared_model is None
