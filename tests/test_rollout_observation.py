import copy
import importlib
import json

import httpx
import pytest

from world_engine import make_environment, provider_records
from world_engine.models import RunConfig, canonical_json
from world_engine.native_ledger import reconstruct
from world_engine.ollama_tools import LEDGER_PROTOCOL, NATIVE_PROTOCOLS, OllamaToolsProvider, request_body
from world_engine.providers import ScriptedProvider, policy_messages
from world_engine.rollout import replay, rollout

module = importlib.import_module("world_engine.rollout")
WORLDS = ("crm-merge", "refund-ops", "incident-control", "access-provisioning")
MUTATION = "MUTATED_PROVIDER_INPUT"


@pytest.fixture(autouse=True)
def local_provenance(monkeypatch):
    monkeypatch.setattr(module, "collection_revision", lambda: {
        "git_revision": None, "git_dirty": None, "implementation_dirty": None})


def count_observations(monkeypatch):
    worlds = []

    def factory(environment_id, seed):
        world = make_environment(environment_id, seed)
        original_observe = world.observe
        counter = {"reads": 0}

        def observe():
            counter["reads"] += 1
            return original_observe()

        world.observe = observe
        worlds.append((world, counter))
        return world

    monkeypatch.setattr(module, "make_environment", factory)
    return worlds


class ObservingProvider(ScriptedProvider):
    def __init__(self, *, oracle=True, mutate=False):
        super().__init__(oracle)
        self.mutate = mutate
        self.before = []
        self.inputs = []

    async def decide(self, observation, history):
        self.before.append(copy.deepcopy(observation))
        self.inputs.append(observation)
        decision = await super().decide(observation, history)
        if self.mutate:
            observation["role"] = MUTATION
            observation["state"].clear()
            observation["state"][MUTATION] = True
            observation["tools"][0]["args_schema"].clear()
            observation["tools"][0]["args_schema"][MUTATION] = True
            observation["task"] = MUTATION
        return decision


def check_contexts(episode, observations):
    assert len(observations) == episode["steps"]
    for index, observation in enumerate(observations):
        prior = episode["trace"][index - 1]["observation"] if index else episode["initial_observation"]
        assert canonical_json(observation) == canonical_json(prior)
        assert episode["trace"][index]["policy_input"] == policy_messages(observation, episode["trace"][:index])


async def independently_execute(config):
    world = make_environment(config.environment_id, config.seed)
    oracle = ScriptedProvider(config.provider_id == "scripted-oracle")
    history = []
    for index in range(config.max_steps):
        observation = world.observe()
        action = (await oracle.decide(observation, history)).action
        transition = world.step(action)
        history.append({"index": index, "action": action.model_dump(), **transition})
        if world.done:
            break
    return world, history


@pytest.mark.parametrize("environment_id", WORLDS)
@pytest.mark.parametrize("oracle", [True, False], ids=["oracle", "baseline"])
@pytest.mark.parametrize("seed", [0, 7])
async def test_one_observation_per_decision_preserves_all_world_contexts(monkeypatch, environment_id, oracle, seed):
    worlds = count_observations(monkeypatch)
    provider = ObservingProvider(oracle=oracle)
    config = RunConfig(environment_id=environment_id, provider_id="scripted-oracle" if oracle else "scripted-baseline",
                       seed=seed, max_steps=20, timeout_seconds=30, evaluation_only=True)
    episode = await rollout(config, 0, provider)
    assert worlds[0][1]["reads"] == 2 * episode["steps"] + 2
    check_contexts(episode, provider.before)
    assert replay(episode)["verified"]
    expected_world, expected_history = await independently_execute(config)
    assert episode["final_snapshot"] == expected_world.snapshot()
    assert episode["grader"] == expected_world.evaluate().model_dump()
    assert len(episode["trace"]) == len(expected_history)
    for actual, expected in zip(episode["trace"], expected_history, strict=True):
        for field in ("action", "result", "observation", "state_hash"):
            assert canonical_json(actual[field]) == canonical_json(expected[field])


@pytest.mark.parametrize("environment_id", WORLDS)
@pytest.mark.parametrize("seed", [0, 7])
async def test_provider_mutation_cannot_change_world_context_or_other_observations(monkeypatch, environment_id, seed):
    worlds = count_observations(monkeypatch)
    provider = ObservingProvider(mutate=True)
    config = RunConfig(environment_id=environment_id, seed=seed, max_steps=20, timeout_seconds=30, evaluation_only=True)
    episode = await rollout(config, 0, provider)
    assert worlds[0][1]["reads"] == 2 * episode["steps"] + 2
    assert episode["passed"] and replay(episode)["verified"]
    check_contexts(episode, provider.before)
    assert len({id(observation) for observation in provider.inputs}) == episode["steps"]
    assert all(observation["state"] == {MUTATION: True} for observation in provider.inputs)
    assert all(observation["role"] == MUTATION for observation in provider.inputs)
    assert all(observation["tools"][0]["args_schema"] == {MUTATION: True} for observation in provider.inputs)
    assert MUTATION not in canonical_json(episode)
    for observation in provider.inputs:
        assert all(observation is not step["observation"] for step in episode["trace"])
    assert make_environment(environment_id, seed).observe()["tools"] == episode["initial_observation"]["tools"]


class RawBody(httpx.AsyncByteStream):
    def __init__(self, data):
        self.data = canonical_json(data).encode()

    async def __aiter__(self):
        yield self.data


@pytest.mark.parametrize("environment_id", WORLDS)
@pytest.mark.parametrize("protocol", NATIVE_PROTOCOLS)
@pytest.mark.parametrize("seed", [0, 7])
async def test_one_observation_preserves_native_v1_v2_wire_and_replay(monkeypatch, environment_id, protocol, seed):
    worlds = count_observations(monkeypatch)
    oracle = ScriptedProvider()
    requests = []
    observations = []

    async def respond(request):
        if request.url.path == "/api/tags":
            data = {"models": [{"name": "qwen3:8b", "digest": "a" * 64}]}
        elif request.url.path == "/api/show":
            data = {"capabilities": ["tools", "completion"]}
        elif request.url.path == "/api/version":
            data = {"version": "fixture-daemon"}
        else:
            assert request.url.path == "/api/chat"
            body = json.loads(request.content)
            requests.append(body)
            public = reconstruct(body) if protocol == LEDGER_PROTOCOL else json.loads(body["messages"][1]["content"])
            observations.append(public["observation"])
            action = (await oracle.decide(public["observation"], public["history"])).action
            data = {"model": "qwen3:8b", "done": True, "done_reason": "stop", "message": {
                "role": "assistant", "content": "", "tool_calls": [{"function": {"name": action.tool, "arguments": action.args}}]}}
        return httpx.Response(200, stream=RawBody(data))

    config = RunConfig(environment_id=environment_id, seed=seed, provider_id="local", max_steps=20,
                       timeout_seconds=30, evaluation_only=True)
    provider = OllamaToolsProvider(config, protocol=protocol)
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        await provider.prepare()
        episode = await rollout(config, 0, provider)
    finally:
        await provider.close()
    assert worlds[0][1]["reads"] == 2 * episode["steps"] + 2
    assert episode["passed"] and replay(episode)["verified"]
    check_contexts(episode, observations)
    assert len(requests) == episode["steps"]
    for index, body in enumerate(requests):
        expected = request_body("qwen3:8b", observations[index], episode["trace"][:index], protocol=protocol,
                                initial_observation=episode["initial_observation"])
        assert canonical_json(body) == canonical_json(expected)
        recorded = episode["provider_events"][2 * index]
        assert recorded["request_body"] == canonical_json(body)
        assert recorded["request_sha256"] == provider_records.byte_hash(canonical_json(body).encode())
