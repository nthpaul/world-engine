import asyncio
import importlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from world_engine.models import RunConfig
from world_engine.native_config import NativeRunConfig
from world_engine.ollama_tools import LEDGER_PROTOCOL, PROTOCOL, OllamaToolsProvider
from world_engine.providers import ProviderError, make_provider
from world_engine.rollout import replay

cli = importlib.import_module("world_engine.__main__")
ALIASES = [("local-tools", PROTOCOL), ("local-tools-ledger", LEDGER_PROTOCOL)]


@pytest.fixture
def harness(monkeypatch):
    state = {"stores": [], "managers": [], "configs": [], "closed": 0, "submit_error": None, "wait_error": None}

    def store(path):
        state["stores"].append(path)
        return object()

    class Manager:
        def __init__(self, store):
            state["managers"].append(self)

        def submit(self, config):
            state["configs"].append(config)
            if state["submit_error"] is not None:
                raise state["submit_error"]
            return {"id": "mock-run"}

        async def wait(self, run_id):
            assert run_id == "mock-run"
            if state["wait_error"] is not None:
                raise state["wait_error"]
            return {"id": run_id, "status": "completed", "config": state["configs"][-1].model_dump(),
                    "episodes": ["not printed"], "error": None}

        async def close(self):
            state["closed"] += 1

    monkeypatch.setattr(cli, "Store", store)
    monkeypatch.setattr(cli, "RunManager", Manager)
    return state


def invoke(monkeypatch, *args):
    monkeypatch.setattr("sys.argv", ["world-engine", "--db", "mock.sqlite3", "rollout", "--environment", "crm-merge", *args])
    cli.main()


@pytest.mark.parametrize("alias,protocol", ALIASES)
@pytest.mark.parametrize("evaluation_flag", [[], ["--evaluation-only"]])
def test_native_cli_defaults_force_evaluation_without_paid_consent(monkeypatch, harness, capsys, alias, protocol, evaluation_flag):
    invoke(monkeypatch, "--provider", alias, *evaluation_flag)
    config = harness["configs"][0]
    assert type(config) is NativeRunConfig and config.provider_id == alias
    assert config.evaluation_only is True and config.allow_paid is False
    assert config.concurrency == 1 and config.model is None
    assert config.episodes == 10 and config.seed == 42 and config.max_steps == 20 and config.timeout_seconds == 60
    assert harness["stores"] == ["mock.sqlite3"] and harness["closed"] == 1
    output = json.loads(capsys.readouterr().out)
    assert output["config"] == config.model_dump() and "episodes" not in output


@pytest.mark.parametrize("alias,protocol", ALIASES)
@pytest.mark.parametrize("concurrency", [2, 8])
def test_native_cli_explicit_bounds_model_and_alias_reach_existing_factory(monkeypatch, harness, alias, protocol, concurrency):
    invoke(monkeypatch, "--provider", alias, "--model", "operator-model:custom", "--concurrency", str(concurrency),
           "--episodes", "2", "--seed", "7", "--max-steps", "12", "--timeout", "35", "--label", "CLI fixture",
           "--allow-paid")
    config = harness["configs"][0]
    assert config.provider_id == alias and config.model == "operator-model:custom"
    assert config.concurrency == concurrency and config.evaluation_only is True and config.allow_paid is False
    assert config.episodes == 2 and config.seed == 7 and config.max_steps == 12 and config.timeout_seconds == 35
    assert config.label == "CLI fixture"
    provider = make_provider(config)
    assert type(provider) is OllamaToolsProvider and provider.provider_protocol == protocol
    assert provider.client is None and not provider.prepared and provider.model == config.model
    asyncio.run(provider.close())
    assert provider.client is None and harness["closed"] == 1


@pytest.mark.parametrize("provider", ["scripted-oracle", "scripted-baseline", "local", "openai", "anthropic"])
def test_legacy_cli_default_and_explicit_consent_remain_unchanged(monkeypatch, harness, provider):
    invoke(monkeypatch, "--provider", provider)
    config = harness["configs"][-1]
    assert type(config) is RunConfig and config.provider_id == provider
    assert config.concurrency == 4 and config.evaluation_only is False and config.allow_paid is False
    invoke(monkeypatch, "--provider", provider, "--concurrency", "2", "--evaluation-only", "--allow-paid")
    config = harness["configs"][-1]
    assert config.concurrency == 2 and config.evaluation_only is True and config.allow_paid is True
    assert harness["closed"] == 2


def test_default_cli_is_still_scripted_oracle(monkeypatch, harness):
    invoke(monkeypatch)
    config = harness["configs"][0]
    assert type(config) is RunConfig and config.provider_id == "scripted-oracle" and config.concurrency == 4
    assert harness["closed"] == 1


@pytest.mark.parametrize("provider", ["local-tools", "local-tools-ledger", "scripted-oracle"])
@pytest.mark.parametrize("flag,value", [("--concurrency", "0"), ("--concurrency", "9"), ("--episodes", "0"),
                                        ("--max-steps", "101"), ("--timeout", "0"), ("--seed", "-1"),
                                        ("--model", "bad\nmodel")])
def test_invalid_config_is_rejected_before_store_or_manager(monkeypatch, harness, provider, flag, value):
    with pytest.raises(ValidationError):
        invoke(monkeypatch, "--provider", provider, flag, value)
    assert harness["stores"] == harness["managers"] == harness["configs"] == []
    assert harness["closed"] == 0


@pytest.mark.parametrize("flag,value", [("--provider", "local-tools-v3"), ("--environment", "unknown-world"),
                                        ("--concurrency", "not-an-int")])
def test_invalid_cli_arguments_do_not_acquire_resources(monkeypatch, harness, flag, value):
    with pytest.raises(SystemExit) as failure:
        invoke(monkeypatch, flag, value)
    assert failure.value.code == 2
    assert harness["stores"] == harness["managers"] == []


@pytest.mark.parametrize("alias,protocol", ALIASES)
@pytest.mark.parametrize("phase,error", [("submit", ProviderError("mock preflight boundary")),
                                        ("wait", ProviderError("mock provider failure")),
                                        ("wait", TimeoutError("mock timeout")),
                                        ("wait", asyncio.CancelledError("mock cancellation"))])
def test_native_cli_finally_closes_manager_on_failures(monkeypatch, harness, alias, protocol, phase, error):
    harness[phase+"_error"] = error
    with pytest.raises(type(error)):
        invoke(monkeypatch, "--provider", alias)
    assert len(harness["stores"]) == len(harness["managers"]) == len(harness["configs"]) == 1
    assert harness["closed"] == 1 and harness["configs"][0].evaluation_only is True


def test_rollout_help_lists_both_native_modes_without_any_execution(monkeypatch, harness, capsys):
    with pytest.raises(SystemExit) as failure:
        invoke(monkeypatch, "--help")
    assert failure.value.code == 0
    text = capsys.readouterr().out
    assert "local-tools" in text and "local-tools-ledger" in text
    assert "default: 1 for native providers, 4 otherwise" in " ".join(text.split())
    assert harness["stores"] == harness["managers"] == []


def test_all16_original_native_episodes_replay_after_cli_only_extension():
    root = Path(__file__).resolve().parents[1]
    path = root/"artifacts/access-ledger-study/20261010-v1/evaluation-episodes.jsonl"
    episodes = [json.loads(line)["episode"] for line in path.read_text().splitlines()]
    assert len(episodes) == 16 and all(replay(episode)["verified"] for episode in episodes)
