import json

import httpx
import pytest

from world_engine import make_environment, provider_records
from world_engine.models import RunConfig
from world_engine.providers import HTTPProvider, ProviderError

MODEL = "qwen3:8b"
DIGEST = "a" * 64


class RawBody(httpx.AsyncByteStream):
    def __init__(self, data):
        self.body = json.dumps(data).encode()

    async def __aiter__(self):
        yield self.body


def fixture_provider():
    return HTTPProvider(RunConfig(environment_id="crm-merge", provider_id="local", model=MODEL), record_calls=True)


def metadata(path):
    if path == "/api/tags":
        return {"models": [{"name": MODEL, "digest": DIGEST}]}
    if path == "/api/show":
        return {"capabilities": ["completion"]}
    if path == "/api/version":
        return {"version": "fixture-version"}
    return {"done": True, "done_reason": "stop", "message": {
        "role": "assistant", "content": json.dumps({"tool": "finish", "args": {}})}}


@pytest.mark.parametrize("stage", ["/api/tags", "/api/show", "/api/version"])
@pytest.mark.parametrize("changed_model", ["unprepared-cloud-alias", "different-local-model"])
@pytest.mark.parametrize("was_prepared", [False, True])
async def test_identity_changed_during_metadata_cannot_publish_or_send_chat(stage, changed_model, was_prepared):
    provider = fixture_provider()
    requests = []
    mutation_enabled = False

    def respond(request):
        requests.append(request)
        if request.url.path == "/api/show":
            assert json.loads(request.content) == {"model": MODEL}
        if mutation_enabled and request.url.path == stage:
            provider.model = changed_model
        return httpx.Response(200, stream=RawBody(metadata(request.url.path)))

    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(respond), trust_env=False)
    events, token = provider_records.begin_episode()
    try:
        if was_prepared:
            await provider.prepare()
            assert provider.prepared_model == MODEL and provider.model_digest == DIGEST
            requests.clear()
        mutation_enabled = True
        with pytest.raises(ProviderError, match="changed during preparation"):
            await provider.prepare()
        assert provider.model == changed_model
        assert not provider.prepared and provider.prepared_model is None
        assert provider.model_digest is None and provider.daemon_version is None
        with pytest.raises(ProviderError, match="prepare"):
            await provider.decide(make_environment("crm-merge", 730).observe(), [])
        assert [request.url.path for request in requests] == ["/api/tags", "/api/show", "/api/version"]
        assert events == []

        mutation_enabled = False
        provider.model = MODEL
        await provider.prepare()
        assert provider.prepared and provider.prepared_model == MODEL
        assert provider.model_digest == DIGEST and provider.daemon_version == "fixture-version"
        decision = await provider.decide(make_environment("crm-merge", 730).observe(), [])
        assert decision.action.tool == "finish"
        assert requests[-1].url.path == "/api/chat" and json.loads(requests[-1].content)["model"] == MODEL
        assert len(events) == 2 and events[0]["event"] == "request_started"
    finally:
        provider_records.end_episode(token)
        await provider.close()
    assert not provider.prepared and provider.prepared_model is None


@pytest.mark.parametrize("changed_model", ["unprepared-cloud-alias", "different-local-model"])
async def test_identity_changed_after_prepare_cannot_send_chat_or_attempt(changed_model):
    provider = fixture_provider()
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, stream=RawBody(metadata(request.url.path)))

    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(respond), trust_env=False)
    events, token = provider_records.begin_episode()
    try:
        await provider.prepare()
        provider.model = changed_model
        with pytest.raises(ProviderError, match="prepare"):
            await provider.decide(make_environment("crm-merge", 730).observe(), [])
        assert [request.url.path for request in requests] == ["/api/tags", "/api/show", "/api/version"]
        assert events == []
    finally:
        provider_records.end_episode(token)
        await provider.close()
