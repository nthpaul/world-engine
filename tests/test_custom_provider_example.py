import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from world_engine.providers import ProviderError
from world_engine.rollout import replay, rollout

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "examples/custom_provider.py"
spec = importlib.util.spec_from_file_location("custom_provider_example", SCRIPT)
example = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = example
spec.loader.exec_module(example)


async def test_example_is_public_observation_only_replayable_and_caller_closed(monkeypatch):
    provider = example.MockObservationProvider()
    observations = []
    original = provider.decide

    async def observe(observation, history):
        observations.append(observation)
        assert provider.prepared and not provider.closed
        assert set(observation["state"]) == {"assigned_request_id", "current_view"}
        assert "initial_snapshot" not in observation and "grader" not in observation
        return await original(observation, history)

    monkeypatch.setattr(provider, "decide", observe)
    monkeypatch.setattr(example, "MockObservationProvider", lambda: provider)
    result = await example.run_example()
    episode = result["episode"]
    assert result["provider_closed"] and provider.closed and not provider.prepared
    assert result["model_calls"] == result["paid_calls"] == 0
    assert episode["steps"] == 2 and [step["action"]["tool"] for step in episode["trace"]] == ["inspect", "finish"]
    assert episode["status"] == "completed" and episode["termination"] == "finished"
    assert episode["passed"] is False and result["replay"]["verified"]
    assert episode["provenance"]["provider_id"] == "custom"
    assert episode["provenance"]["provider_class"] == "custom_provider_example.MockObservationProvider"
    assert len(episode["provenance"]["provider_source_hash"]) == 64
    assert episode["provenance"]["evaluation_only"] is True
    assert episode["provenance"]["model"] == provider.model and episode["provenance"]["model_digest"] is None
    assert all(step["usage"] == {} for step in episode["trace"])
    assert len(observations) == 2 and "provider_cleanup" not in episode
    config = result["config"]
    assert config["max_steps"] == 2 and config["timeout_seconds"] == 5
    assert config["concurrency"] == config["episodes"] == 1 and config["allow_paid"] is False
    assert replay(episode)["verified"]


async def test_borrowed_provider_prepare_and_close_are_not_implicit():
    provider = example.MockObservationProvider()
    with pytest.raises(ProviderError, match="prepare"):
        await provider.decide({"tools": []}, [])
    config = example.RunConfig(environment_id="access-provisioning", max_steps=2, evaluation_only=True)
    await provider.prepare()
    try:
        episode = await rollout(config, 0, provider)
        assert provider.prepared and not provider.closed and replay(episode)["verified"]
    finally:
        await provider.close()
    assert provider.closed


async def test_example_closes_resource_when_preparation_fails(monkeypatch):
    provider = example.MockObservationProvider()

    async def fail():
        raise ProviderError("mock preparation failure")

    monkeypatch.setattr(provider, "prepare", fail)
    monkeypatch.setattr(example, "MockObservationProvider", lambda: provider)
    with pytest.raises(ProviderError, match="mock preparation failure"):
        await example.run_example()
    assert provider.closed


async def test_custom_reported_usage_keeps_missing_input_unknown():
    class ReportedMockProvider(example.MockObservationProvider):
        tracks_reported_usage = True

        async def decide(self, observation, history):
            decision = await super().decide(observation, history)
            return example.Decision(decision.action, usage={"output_tokens": 7})

    provider = ReportedMockProvider()
    config = example.RunConfig(environment_id="access-provisioning", max_steps=1,
                               evaluation_only=True, allow_paid=False)
    await provider.prepare()
    try:
        episode = await rollout(config, 0, provider)
        usage = episode["usage"]
        assert usage["input_tokens_complete"] is False
        assert "input_tokens" not in usage and "input_tokens_known" not in usage
        assert usage["output_tokens_complete"] is True
        assert usage["output_tokens"] == usage["output_tokens_known"] == 7
        assert usage["recorded_decisions"] == 1
        assert episode["trace"][0]["usage"] == {"output_tokens": 7}
        assert episode["provenance"]["provider_id"] == "custom" and replay(episode)["verified"]
    finally:
        await provider.close()
    assert provider.closed


def test_cli_default_is_mock_only_and_writes_no_artifacts(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=tmp_path,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["model_calls"] == summary["paid_calls"] == 0
    assert summary["replay_verified"] and summary["provider_closed"]
    assert summary["provider_id"] == "custom" and summary["provider_class"] == "__main__.MockObservationProvider"
    assert summary["evaluation_only"] and not summary["passed"]
    assert list(tmp_path.iterdir()) == []
