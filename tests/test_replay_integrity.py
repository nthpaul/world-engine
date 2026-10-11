import asyncio
import copy

import pytest

from world_engine import Action
from world_engine.exports import export_records
from world_engine.models import RunConfig
from world_engine.providers import Decision, ProviderError
from world_engine.rollout import replay, rollout
from world_engine.store import Store


async def test_failed_max_steps_cannot_be_relabelled_as_training_success(tmp_path):
    config = RunConfig(environment_id="crm-merge", seed=730, max_steps=1)
    episode = await rollout(config, 0)
    assert episode["split"] == "train"
    assert episode["termination"] == "max_steps"
    assert episode["grader"]["reward"] == .2
    assert episode["reward"] == 0 and not episode["passed"]
    assert replay(episode)["verified"]
    forged = copy.deepcopy(episode)
    forged.update(reward=1.0, passed=True)
    with pytest.raises(ValueError, match="authoritative reward"):
        replay(forged)
    # Storage integrity alone is not semantic verification. Even a correctly
    # hashed, SDK-appended forgery cannot pass the training export's replay gate.
    store = Store(tmp_path / "engine.sqlite3")
    store.create_run("untrusted-ingestion", config)
    store.append_episode("untrusted-ingestion", forged)
    for format in ("sft", "dpo", "grpo"):
        records, report = export_records(store, "untrusted-ingestion", format)
        assert records == []
        assert report["excluded"]["replay_mismatch"] == 1


@pytest.mark.parametrize("path,value", [
    (("passed",), False),
    (("reward",), 0.0),
    (("status",), "failed"),
    (("termination",), "max_steps"),
    (("error",), "made-up failure"),
    (("split",), "test"),
    (("lineage_id",), "0" * 64),
    (("scenario_id",), "0" * 64),
    (("provenance", "seed"), 731),
    (("provenance", "task_hash"), "0" * 64),
    (("provenance", "lineage_id"), "0" * 64),
    (("provenance", "scenario_id"), "0" * 64),
    (("provenance", "prompt_hash"), "0" * 64),
    (("provenance", "policy_hash"), "0" * 64),
    (("initial_observation", "task"), "tampered public task"),
    (("initial_snapshot", "tick"), 9),
    (("final_observation", "done"), False),
    (("final_snapshot", "done"), False),
    (("steps",), 1),
    (("invalid_actions",), 1),
    (("trace", 0, "index"), True),
    (("trace", 0, "policy_input", 0, "content"), "forged model instructions"),
    (("trace", 1, "policy_input", 1, "content"), "forged prior tool history"),
])
async def test_replay_rejects_inconsistent_envelope_fields(path, value):
    episode = await rollout(RunConfig(environment_id="crm-merge", seed=730), 0)
    assert episode["passed"] and replay(episode)["verified"]
    forged = copy.deepcopy(episode)
    target = forged
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        replay(forged)


async def test_replay_rejects_missing_metadata_and_post_terminal_actions():
    episode = await rollout(RunConfig(environment_id="crm-merge", seed=730), 0)
    malformed = copy.deepcopy(episode)
    del malformed["provenance"]["task_hash"]
    with pytest.raises(ValueError, match="malformed episode"):
        replay(malformed)
    episode["trace"].append(copy.deepcopy(episode["trace"][-1]))
    with pytest.raises(ValueError, match="after the world finished"):
        replay(episode)


class InterruptedProvider:
    def __init__(self, cause):
        self.cause = cause

    async def decide(self, observation, history):
        if not history:
            return Decision(Action(tool="inspect"))
        raise self.cause


@pytest.mark.parametrize("cause,termination", [
    (asyncio.CancelledError(), "cancelled"),
    (TimeoutError(), "timeout"),
    (ProviderError("provider unavailable"), "provider_error"),
    (RuntimeError("private diagnostics"), "internal_error"),
])
async def test_valid_partial_custom_provider_episode_still_replays(cause, termination):
    episode = await rollout(RunConfig(environment_id="crm-merge", seed=730), 0, InterruptedProvider(cause))
    assert episode["termination"] == termination
    assert episode["steps"] == 1
    assert episode["provenance"]["provider_id"] == "custom"
    assert replay(episode)["verified"]
