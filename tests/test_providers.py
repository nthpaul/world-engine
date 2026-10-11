import asyncio
import json

import httpx
import pytest

from world_engine import make_environment
from world_engine.models import RunConfig
from world_engine.providers import HTTPProvider, ProviderError, policy_messages
from world_engine.rollout import rollout

FIXTURE_DIGEST = "a" * 64


class RawBody(httpx.AsyncByteStream):
    def __init__(self, body):
        self.body = body

    async def __aiter__(self):
        yield self.body


def raw_response(status=200, *, data=None, content=None):
    return httpx.Response(status, stream=RawBody(json.dumps(data).encode() if content is None else content))


def metadata_response(request):
    if request.url.path == "/api/tags":
        return raw_response(data={"models": [{"name": "qwen3:8b", "digest": FIXTURE_DIGEST}]})
    if request.url.path == "/api/show":
        return raw_response(data={"capabilities": ["completion"]})
    if request.url.path == "/api/version":
        return raw_response(data={"version": "fixture"})
    return None


async def test_local_uses_structured_actions_and_reuses_client():
    requests = []

    async def respond(request):
        requests.append(request)
        metadata = metadata_response(request)
        if metadata is not None:
            return metadata
        body = json.loads(request.content)
        assert body["think"] is False and body["stream"] is False
        assert body["options"]["num_predict"] == 512
        assert body["messages"] == policy_messages(make_environment("crm-merge", 42).observe(), [])
        assert body["format"]["additionalProperties"] is False
        return raw_response(data={"done": True, "done_reason": "stop", "message": {"role": "assistant", "content": '{"tool":"inspect","args":{}}'},
                                  "prompt_eval_count": 123, "eval_count": 9})

    provider = HTTPProvider(RunConfig(environment_id="crm-merge", provider_id="local"))
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    client = provider.client
    await provider.prepare()
    observation = make_environment("crm-merge", 42).observe()
    for _ in range(2):
        decision = await provider.decide(observation, [])
        assert decision.action.tool == "inspect"
        assert decision.usage["input_tokens"] == 123
        assert provider.client is client
    assert provider.model_digest == FIXTURE_DIGEST
    await provider.close()
    assert client.is_closed
    assert len(requests) == 5


async def test_provider_errors_never_reflect_remote_body():
    sentinel = "SYNTHETIC-SECRET-NEVER-REFLECT"

    async def respond(request):
        return metadata_response(request) or raw_response(403, content=sentinel.encode())

    provider = HTTPProvider(RunConfig(environment_id="crm-merge", provider_id="local"))
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        await provider.prepare()
        with pytest.raises(ProviderError) as error:
            await provider.decide(make_environment("crm-merge", 42).observe(), [])
        assert sentinel not in str(error.value)
        assert "HTTP 403" in str(error.value)
    finally:
        await provider.close()


@pytest.mark.parametrize("content", [b"x" * 256_001, b'{"done":true,"done_reason":"stop","message":{"role":"assistant","content":"{\\"tool\\":\\"finish\\",\\"reward\\":1}"}}'])
async def test_oversize_and_untrusted_reward_responses_rejected(content):
    async def respond(request):
        return metadata_response(request) or raw_response(content=content)

    provider = HTTPProvider(RunConfig(environment_id="crm-merge", provider_id="local"))
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        await provider.prepare()
        with pytest.raises(ProviderError):
            await provider.decide(make_environment("crm-merge", 42).observe(), [])
    finally:
        await provider.close()


async def test_episode_timeout_stops_a_pending_provider():
    stopped = asyncio.Event()

    class BlockingProvider:
        async def decide(self, observation, history):
            try:
                await asyncio.sleep(60)
            finally:
                stopped.set()

    episode = await rollout(RunConfig(environment_id="crm-merge", timeout_seconds=1), 0, BlockingProvider())
    assert episode["status"] == "failed" and episode["termination"] == "timeout"
    assert episode["reward"] == 0 and not episode["passed"]
    assert stopped.is_set()
