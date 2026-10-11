import copy
import hashlib
import json
import os

import httpx
import pytest

from world_engine.atif import ATIF_VERSION, HARBOR_SCHEMA_SHA256, export_episode
from world_engine.models import RunConfig, canonical_json
from world_engine.providers import HTTPProvider, ProviderError
from world_engine.rollout import rollout


class RawBody(httpx.AsyncByteStream):
    def __init__(self, data):
        self.body = json.dumps(data).encode()

    async def __aiter__(self):
        yield self.body


async def test_scripted_export_preserves_data_without_claiming_llm_tokens():
    episode = await rollout(RunConfig(environment_id="crm-merge", seed=730, evaluation_only=True), 0)
    original = copy.deepcopy(episode)
    document = export_episode(episode, run_id="recorded-run")
    assert episode == original
    assert document["schema_version"] == ATIF_VERSION
    assert document["session_id"] == "recorded-run"
    assert document["extra"]["evaluation_only"] is True
    assert document["extra"]["training_eligible"] is False
    assert document["extra"]["world_engine"]["provenance"] == episode["provenance"]
    agent_steps = [step for step in document["steps"] if step["source"] == "agent"]
    assert len(agent_steps) == episode["steps"]
    for step, recorded in zip(agent_steps, episode["trace"], strict=True):
        assert step["llm_call_count"] == 0
        assert "metrics" not in step and "timestamp" not in step
        assert step["message"] == canonical_json(recorded["action"])
        assert step["tool_calls"][0]["arguments"] == recorded["action"]["args"]
        assert step["extra"]["policy_input"] == recorded["policy_input"]
        assert "not a provider transcript" in step["extra"]["policy_input_scope"]
    assert "total_prompt_tokens" not in document["final_metrics"]
    assert "grader" not in document["extra"]["world_engine"]
    assert "initial_snapshot" not in document["extra"]["world_engine"]
    document["agent"]["tool_definitions"][0]["function"]["parameters"]["title"] = "mutated export"
    agent_steps[0]["extra"]["policy_input"][0]["content"] = "mutated export"
    assert episode == original


async def test_observed_http_tokens_and_model_identity_are_preserved():
    async def respond(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, stream=RawBody({"models": [{"name": "qwen3:8b", "digest": "a" * 64}]}))
        if request.url.path == "/api/show":
            return httpx.Response(200, stream=RawBody({"capabilities": ["completion"]}))
        if request.url.path == "/api/version":
            return httpx.Response(200, stream=RawBody({"version": "fixture"}))
        return httpx.Response(200, stream=RawBody({"done": True, "done_reason": "stop", "message": {"role": "assistant", "content": '{"tool":"finish","args":{}}'},
                                                  "prompt_eval_count": 123, "eval_count": 5, "model": "reported-resolved-model"}))
    config = RunConfig(environment_id="refund-ops", provider_id="local", evaluation_only=True)
    provider = HTTPProvider(config)
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        await provider.prepare()
        episode = await rollout(config, 0, provider)
    finally:
        await provider.close()
    document = export_episode(episode)
    step = document["steps"][-1]
    assert step["llm_call_count"] == 1
    assert step["model_name"] == "reported-resolved-model"
    assert step["extra"]["configured_model_name"] == "qwen3:8b"
    assert document["agent"]["model_name"] == "qwen3:8b"
    assert step["metrics"] == {"prompt_tokens": 123, "completion_tokens": 5}
    assert document["agent"]["extra"]["model_digest"] == "a" * 64
    assert document["final_metrics"]["total_prompt_tokens"] == 123
    assert "logprobs" not in step["metrics"] and "prompt_token_ids" not in step["metrics"]


@pytest.mark.parametrize(("provider", "max_steps", "termination"), [
    ("scripted-oracle", 20, "finished"), ("scripted-oracle", 1, "max_steps"),
    ("scripted-baseline", 20, "finished"), ("scripted-baseline", 1, "max_steps"),
])
async def test_outcomes_and_invalid_actions_remain_faithful(provider, max_steps, termination):
    episode = await rollout(RunConfig(environment_id="crm-merge", provider_id=provider,
                                      max_steps=max_steps, evaluation_only=True), 0)
    document = export_episode(episode)
    outcome = document["extra"]["world_engine"]
    assert outcome["termination"] == termination
    assert outcome["reward"] == episode["reward"]
    assert outcome["passed"] == episode["passed"]
    assert outcome["invalid_actions"] == episode["invalid_actions"]
    if provider == "scripted-baseline":
        assert outcome["invalid_actions"] == 1
    if termination == "max_steps":
        assert outcome["reward"] == 0 and not outcome["passed"]


async def test_no_recorded_decision_does_not_invent_an_inference():
    class FailingProvider:
        async def decide(self, observation, history):
            raise ProviderError("fixture provider failure")
    episode = await rollout(RunConfig(environment_id="crm-merge", evaluation_only=True), 0, FailingProvider())
    document = export_episode(episode)
    assert len(document["steps"]) == 1
    assert document["steps"][0]["extra"]["recorded_observation_only"] is True
    assert document["extra"]["world_engine"]["termination"] == "provider_error"
    assert "total_prompt_tokens" not in document["final_metrics"]


async def test_inconsistent_episode_is_rejected_before_export():
    original = await rollout(RunConfig(environment_id="crm-merge", seed=730, max_steps=1), 0)
    for field, value in (("reward", 1.0), ("passed", True), ("split", "test")):
        episode = copy.deepcopy(original)
        episode[field] = value
        with pytest.raises(ValueError):
            export_episode(episode)
    episode = copy.deepcopy(original)
    episode["trace"][0]["policy_input"][0]["content"] = "unrecorded prompt"
    with pytest.raises(ValueError):
        export_episode(episode)


async def test_actual_pinned_upstream_model_accepts_exported_outcomes():
    if os.environ.get("WORLD_ENGINE_ATIF_VALIDATE_UPSTREAM") != "1":
        pytest.skip("Enable isolated pinned Harbor validation using docs/atif.md")
    from harbor.models.trajectories.trajectory import Trajectory
    schema_hash = hashlib.sha256(canonical_json(Trajectory.model_json_schema()).encode()).hexdigest()
    assert schema_hash == HARBOR_SCHEMA_SHA256
    for provider in ("scripted-oracle", "scripted-baseline"):
        for max_steps in (1, 20):
            episode = await rollout(RunConfig(environment_id="crm-merge", provider_id=provider,
                                              max_steps=max_steps, evaluation_only=True), 0)
            Trajectory.model_validate(export_episode(episode))
