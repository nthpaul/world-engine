import copy
import json
import subprocess
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

from world_engine.api import create_app
from world_engine.exports import export_records, jsonl
from world_engine.models import RunConfig, digest
from world_engine.rollout import rollout, scenario_split
from world_engine.store import Store


def seed_for_split(split):
    return next(seed for seed in range(100) if scenario_split(digest({"environment_family": "crm-merge", "seed": seed})) == split)


async def stored_episode(tmp_path, *, split="train", evaluation_only=False, provider="scripted-oracle", max_steps=20):
    config = RunConfig(environment_id="crm-merge", provider_id=provider, seed=seed_for_split(split),
                       evaluation_only=evaluation_only, max_steps=max_steps)
    episode = await rollout(config, 0)
    store = Store(tmp_path / "engine.sqlite3")
    run_id = str(uuid.uuid4())
    store.create_run(run_id, config)
    store.append_episode(run_id, episode)
    store.update_run(run_id, "completed")
    return store, run_id, episode


@pytest.mark.parametrize("split", ["train", "validation", "test"])
@pytest.mark.parametrize("evaluation_only", [False, True])
async def test_sdk_atif_is_verified_operator_interchange_across_all_splits(tmp_path, split, evaluation_only):
    store, run_id, episode = await stored_episode(tmp_path, split=split, evaluation_only=evaluation_only)
    records, report = export_records(store, run_id, "atif")
    assert len(records) == report["records"] == 1
    assert report["skipped"] == 0
    assert "operator interchange" in report["note"]
    assert "not a curated training batch" in report["note"]
    document = json.loads(jsonl(records))
    assert document["schema_version"] == "ATIF-v1.8"
    assert document["session_id"] == run_id
    assert document["trajectory_id"] == episode["id"]
    assert document["extra"]["training_eligible"] is False
    assert document["extra"]["evaluation_only"] is evaluation_only
    assert document["extra"]["world_engine"]["split"] == split
    assert "grader" not in document["extra"]["world_engine"]
    assert "initial_snapshot" not in document["extra"]["world_engine"]
    assert "final_snapshot" not in document["extra"]["world_engine"]
    assert all(step["llm_call_count"] == 0 for step in document["steps"] if step["source"] == "agent")
    if evaluation_only or split != "train":
        training_records, _ = export_records(store, run_id, "sft")
        assert training_records == []


async def test_sdk_atif_passed_quality_requires_a_clean_success(tmp_path):
    store, run_id, episode = await stored_episode(tmp_path, provider="scripted-baseline", max_steps=1, evaluation_only=True)
    assert not episode["passed"] and episode["invalid_actions"] == 1
    records, report = export_records(store, run_id, "atif", "passed")
    assert records == [] and report["excluded"]["quality"] == 1
    records, report = export_records(store, run_id, "atif", "all")
    assert len(records) == 1 and report["skipped"] == 0
    outcome = records[0]["extra"]["world_engine"]
    assert outcome["termination"] == "max_steps" and outcome["reward"] == 0
    assert outcome["invalid_actions"] == 1 and not outcome["passed"]


@pytest.mark.parametrize("corruption", ["reward", "policy_input", "missing_metadata"])
async def test_sdk_and_api_atif_reject_malformed_replay_even_for_operator_all_quality(tmp_path, corruption):
    config = RunConfig(environment_id="crm-merge", seed=730, max_steps=1, evaluation_only=True)
    episode = copy.deepcopy(await rollout(config, 0))
    if corruption == "reward":
        episode.update(reward=1.0, passed=True)
    elif corruption == "policy_input":
        episode["trace"][0]["policy_input"][0]["content"] = "forged prompt"
    else:
        del episode["provenance"]["task_hash"]
    store = Store(tmp_path / "engine.sqlite3")
    run_id = str(uuid.uuid4())
    store.create_run(run_id, config)
    store.append_episode(run_id, episode)
    store.update_run(run_id, "completed")
    records, report = export_records(store, run_id, "atif", "all")
    assert records == []
    assert report["excluded"]["replay_mismatch"] == 1
    with TestClient(create_app(store.path)) as client:
        response = client.get(f"/api/runs/{run_id}/export?format=atif&quality=all")
        assert response.status_code == 200 and response.text == ""
        assert response.headers["x-export-records"] == "0"
        assert response.headers["x-export-skipped"] == "1"


async def test_cli_atif_export_and_interchange_warning(tmp_path):
    store, run_id, episode = await stored_episode(tmp_path, split="test", evaluation_only=True)
    result = subprocess.run([sys.executable, "-m", "world_engine", "--db", str(store.path), "export", run_id,
                             "--format", "atif", "--quality", "all"], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    report = json.loads(result.stderr)
    assert document["trajectory_id"] == episode["id"]
    assert document["extra"]["world_engine"]["split"] == "test"
    assert document["extra"]["training_eligible"] is False
    assert report["format"] == "atif" and report["records"] == 1
    assert "operator interchange" in report["note"]


async def test_api_atif_download_uses_existing_contract_and_respects_quality(tmp_path):
    store, run_id, episode = await stored_episode(tmp_path, split="validation", evaluation_only=True,
                                                 provider="scripted-baseline", max_steps=1)
    with TestClient(create_app(store.path)) as client:
        response = client.get(f"/api/runs/{run_id}/export?format=atif&quality=all")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/x-ndjson")
        assert response.headers["content-disposition"] == f'attachment; filename="{run_id}-atif.jsonl"'
        assert response.headers["x-export-records"] == "1"
        assert response.headers["x-export-skipped"] == "0"
        document = response.json()
        assert document["trajectory_id"] == episode["id"]
        assert document["extra"]["world_engine"]["split"] == "validation"
        assert document["extra"]["evaluation_only"] is True
        assert document["extra"]["training_eligible"] is False
        assert len([step for step in document["steps"] if step["source"] == "agent"]) == 1
        empty = client.get(f"/api/runs/{run_id}/export?format=atif&quality=passed")
        assert empty.status_code == 200 and empty.text == ""
        assert empty.headers["x-export-records"] == "0" and empty.headers["x-export-skipped"] == "1"


@pytest.mark.parametrize("format,quality,error", [("unknown", "all", "format"), ("atif", "unknown", "quality")])
def test_sdk_export_rejects_unknown_format_and_quality_before_reading_run(tmp_path, format, quality, error):
    store = Store(tmp_path / "engine.sqlite3")
    with pytest.raises(ValueError, match=f"unsupported export {error}"):
        export_records(store, "missing-run", format, quality)
