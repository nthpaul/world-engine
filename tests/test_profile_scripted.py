"""Mock-only checks: no real rollout, profiling workload, database or source commands."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / "scripts/profile_scripted.py"
SPEC = importlib.util.spec_from_file_location("profile_scripted", PATH)
profile_scripted = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(profile_scripted)
REVISION = "a" * 40


def episode(config, index):
    world_index = profile_scripted.WORLDS.index(config.environment_id)
    quotient, remainder = divmod(profile_scripted.DECISIONS[world_index], 24)
    steps = quotient + (index < remainder)
    return {"id": f"{config.environment_id}-{index}", "seed": index, "index": index,
            "scenario_id": f"scenario-{config.environment_id}-{index}", "lineage_id": f"lineage-{index}",
            "split": "train", "initial_observation": {"public": index}, "initial_snapshot": {"state": index},
            "final_observation": {"public": index, "done": True}, "final_snapshot": {"state": index, "done": True},
            "final_state_hash": "mock-final", "grader": {"passed": True}, "reward": 1.0,
            "passed": True, "status": "completed", "termination": "finished", "steps": steps,
            "invalid_actions": 0, "error": None, "elapsed_seconds": 0.01,
            "trace": [{"action": {"tool": "finish" if i == steps - 1 else "inspect", "args": {}}}
                      for i in range(steps)],
            "provenance": {"environment_id": config.environment_id, "git_revision": REVISION,
                           "implementation_dirty": False, "evaluation_only": True, "provider_id": "scripted-oracle"}}


@pytest.fixture
def harness(monkeypatch):
    calls, replays, databases, operations, profiles = [], [], [], [], []
    source = {"git_revision": REVISION, "files_sha256": {"mock": "fixed"}, "source_dirty": False,
              "checkout_dirty": True}

    class FakeProfile:
        def enable(self):
            profiles.append("enable")

        def disable(self):
            profiles.append("disable")

    class FakeStore:
        def __init__(self, path):
            databases.append(path)

        def create_run(self, run_id, config):
            operations.append(("create", run_id))

        def append_episode(self, run_id, value):
            operations.append(("append", run_id, value["index"]))

        def update_run(self, run_id, status, **kwargs):
            operations.append(("update", run_id, status))

        def list_runs(self, **kwargs):
            assert kwargs == {"limit": 100, "offset": 0}
            operations.append(("list",))
            return [{"mock": True}] * 4

        def get_run(self, run_id, **kwargs):
            assert run_id == "crm-merge" and kwargs == {"detail": True}
            operations.append(("detail",))
            return {"episodes": [{}] * 24}

    async def rollout(config, index):
        assert (config.provider_id, config.seed, config.episodes, config.concurrency,
                config.max_steps, config.timeout_seconds) == ("scripted-oracle", 0, 24, 1, 20, 30)
        assert config.evaluation_only and not config.allow_paid
        calls.append((config.environment_id, index))
        return episode(config, index)

    def replay(value):
        replays.append((value["provenance"]["environment_id"], value["index"]))
        return {"verified": True}

    def snapshot(output, name, value, *, world=None):
        profile_scripted.write_file(output, name + ".prof", b"mock-stats")
        profile_scripted.write_file(output, name + ".txt", b"mock-profile")
        result = {"total_profiled_seconds": 0.01, "total_calls": 1, "top_cumulative": [], "top_exclusive": []}
        if world is not None:
            result["observe_calls"] = profile_scripted.NEW_OBSERVATIONS[profile_scripted.WORLDS.index(world)]
        return result

    monkeypatch.setattr(profile_scripted, "source_identity", lambda revision: copy.deepcopy(source))
    monkeypatch.setattr(profile_scripted, "rollout", rollout)
    monkeypatch.setattr(profile_scripted, "replay", replay)
    monkeypatch.setattr(profile_scripted, "Store", FakeStore)
    monkeypatch.setattr(profile_scripted.cProfile, "Profile", FakeProfile)
    monkeypatch.setattr(profile_scripted, "profile_snapshot", snapshot)
    monkeypatch.setattr(profile_scripted, "machine_metadata", lambda: {"runtime": "mock"})
    return {"calls": calls, "replays": replays, "databases": databases, "operations": operations,
            "profiles": profiles, "source": source, "rollout": rollout, "snapshot": snapshot}


def collect(tmp_path):
    output = tmp_path / "fresh"
    return output, asyncio.run(profile_scripted.collect(output, REVISION))


def raws(output):
    return [json.loads(line) for line in (output / "episodes.jsonl").read_text().splitlines()]


@pytest.mark.parametrize("args", [[], ["--plan"]])
def test_default_and_plan_do_not_execute(monkeypatch, args, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("plan attempted collection work")

    for name in ("source_identity", "rollout", "replay", "Store", "machine_metadata"):
        monkeypatch.setattr(profile_scripted, name, forbidden)
    monkeypatch.setattr(profile_scripted.cProfile, "Profile", forbidden)
    assert profile_scripted.main(args) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["scheduled_episodes"] == 192
    assert plan["replay_phase"]["episodes"] == 96
    assert plan["observation_reads"]["access-provisioning"] == {
        "historical": 1056, "current": 736, "setup_reads_per_episode": 4,
        "formula": "2 * decisions + setup_reads_per_episode * episodes"}


@pytest.mark.parametrize("args", [["--collect"], ["--output", "x"], ["--source-revision", REVISION],
                                 ["--collect", "--output", "x", "--source-revision", "short"],
                                 ["--collect", "--output", "x", "--source-revision", "A" * 40],
                                 ["--plan", "--collect"]])
def test_invalid_cli_flags_fail_before_collection(monkeypatch, args):
    monkeypatch.setattr(profile_scripted, "collect", lambda *args: pytest.fail("invalid arguments reached collection"))
    with pytest.raises(SystemExit) as error:
        profile_scripted.main(args)
    assert error.value.code == 2


@pytest.mark.parametrize("kind", ["file", "directory", "live_symlink", "dangling_symlink"])
def test_fresh_output_gate_precedes_activity(tmp_path, monkeypatch, kind):
    output = tmp_path / "existing"
    if kind == "file":
        output.write_text("old")
    elif kind == "directory":
        output.mkdir()
    else:
        target = tmp_path / "target"
        if kind == "live_symlink":
            target.mkdir()
        output.symlink_to(target)
    monkeypatch.setattr(profile_scripted, "source_identity", lambda *args: pytest.fail("existing path reached source"))
    with pytest.raises(FileExistsError):
        asyncio.run(profile_scripted.collect(output, REVISION))


def test_full_mock_workload_all192_raw_labels_original96_replay_and_sqlite(tmp_path, harness):
    output, report = collect(tmp_path)
    assert report["status"] == "completed" and report["persisted_episodes"] == 192
    assert report["attempted_episodes"] == 192 and report["unattempted_episodes"] == 0
    expected = [(world, index) for world in profile_scripted.WORLDS for _ in range(2) for index in range(24)]
    assert harness["calls"] == expected
    assert harness["replays"] == [(world, index) for world in profile_scripted.WORLDS for index in range(24)]
    records = raws(output)
    assert [record["slot"] for record in records] == [
        {"world": world, "trial": trial, "index": index}
        for world in profile_scripted.WORLDS for trial in profile_scripted.TRIALS for index in range(24)]
    assert all(r["evaluation_only"] and not r["training_eligible"] and r["exact_envelope_preserved"] for r in records)
    assert all(r["episode"]["initial_snapshot"] and r["episode"]["final_snapshot"] for r in records)
    assert [row["profiled"]["observe_calls"] for row in report["worlds"]] == [376, 200, 456, 736]
    counts = {name: sum(operation[0] == name for operation in harness["operations"])
              for name in ("create", "append", "update", "list", "detail")}
    assert counts == {"create": 4, "append": 96, "update": 4, "list": 100, "detail": 40}
    assert all(not path.parent.exists() for path in harness["databases"])
    assert report["temporary_database_removed"]
    assert len(list(output.iterdir())) == 18
    assert report["artifact_total_bytes"] == profile_scripted.artifact_bytes(output)
    assert report["report_bytes"] == (output / "profile.json").stat().st_size
    assert report["raw_sha256"] == hashlib.sha256((output / "episodes.jsonl").read_bytes()).hexdigest()


@pytest.mark.parametrize("failure", ["raise", "cancel", "unsafe"])
def test_partial_block_retained_before_failure(tmp_path, harness, monkeypatch, failure):
    async def rollout(config, index):
        if index == 3:
            if failure == "raise":
                raise ValueError("secret sentinel")
            if failure == "cancel":
                raise asyncio.CancelledError
        value = await harness["rollout"](config, index)
        if failure == "unsafe" and index == 3:
            value["passed"] = False
        return value

    monkeypatch.setattr(profile_scripted, "rollout", rollout)
    output, report = collect(tmp_path)
    assert report["status"] == "stopped"
    expected = 24 if failure == "unsafe" else 3
    assert report["persisted_episodes"] == len(raws(output)) == expected
    assert report["attempted_episodes"] == (24 if failure == "unsafe" else 4)
    assert report["unattempted_episodes"] == (168 if failure == "unsafe" else 188)
    assert "secret sentinel" not in (output / "profile.json").read_text()
    assert harness["replays"] == []
    assert harness["profiles"] == []


@pytest.mark.parametrize("moment", ["before", "second_world", "after"])
def test_source_drift_blocks_execution_or_stops_with_retained_raw(tmp_path, harness, monkeypatch, moment):
    calls = 0

    def source(expected):
        nonlocal calls
        calls += 1
        if moment == "before":
            raise profile_scripted.ProfileStopped("scoped source dirty")
        value = copy.deepcopy(harness["source"])
        if calls >= (3 if moment == "second_world" else 7):
            value["files_sha256"]["mock"] = "changed"
        return value

    monkeypatch.setattr(profile_scripted, "source_identity", source)
    if moment == "before":
        with pytest.raises(profile_scripted.ProfileStopped, match="source dirty"):
            collect(tmp_path)
        assert harness["calls"] == []
    else:
        output, report = collect(tmp_path)
        assert report["status"] == "stopped"
        assert report["persisted_episodes"] == len(raws(output)) == (48 if moment == "second_world" else 192)


def test_unexpected_observation_count_retains_full_trial_but_stops(tmp_path, harness, monkeypatch):
    def snapshot(*args, **kwargs):
        value = harness["snapshot"](*args, **kwargs)
        if kwargs.get("world"):
            value["observe_calls"] += 1
        return value

    monkeypatch.setattr(profile_scripted, "profile_snapshot", snapshot)
    output, report = collect(tmp_path)
    assert report["status"] == "stopped" and report["persisted_episodes"] == len(raws(output)) == 48
    assert "observation read count" in report["stop_reason"]
    assert harness["replays"] == []


def test_logical_trial_mismatch_detected_after_raw_is_saved(tmp_path, harness, monkeypatch):
    async def rollout(config, index):
        value = await harness["rollout"](config, index)
        if len(harness["calls"]) == 25:
            value["trace"][0]["action"]["tool"] = "different"
        return value

    monkeypatch.setattr(profile_scripted, "rollout", rollout)
    output, report = collect(tmp_path)
    assert report["status"] == "stopped" and len(raws(output)) == 48
    assert "paired scripted trials differ" in report["stop_reason"]


def test_time_reservation_exhausted_before_rollout(tmp_path, harness, monkeypatch):
    monkeypatch.setattr(profile_scripted, "OVERALL_SECONDS", 0)
    output, report = collect(tmp_path)
    assert report["status"] == "stopped" and report["attempted_episodes"] == 0
    assert raws(output) == [] and harness["calls"] == []


def test_deadline_mid_block_retains_returned_prefix_and_unattempted_slots(tmp_path, harness, monkeypatch):
    monkeypatch.setattr(profile_scripted, "OVERALL_SECONDS", 30)
    monkeypatch.setattr(profile_scripted, "FINALIZE_SECONDS", 5)
    monkeypatch.setattr(profile_scripted.time, "perf_counter", lambda: 100 if len(harness["calls"]) >= 3 else 0)
    output, report = collect(tmp_path)
    assert report["status"] == "stopped" and report["persisted_episodes"] == len(raws(output)) == 3
    assert report["attempted_episodes"] == 3 and report["unattempted_episodes"] == 189
    assert "deadline" in report["stop_reason"]


def test_unserializable_returned_envelope_gets_safe_marker(tmp_path, harness, monkeypatch):
    class Opaque:
        def __repr__(self):
            return "secret sentinel"

    async def rollout(config, index):
        value = await harness["rollout"](config, index)
        if index == 3:
            value["opaque"] = Opaque()
        return value

    monkeypatch.setattr(profile_scripted, "rollout", rollout)
    output, report = collect(tmp_path)
    assert report["status"] == "stopped" and report["persisted_episodes"] == 3
    assert report["diagnostic_episodes"] == 1 and report["returned_without_persistence"] == 20
    assert raws(output)[-1]["episode"] is None
    assert "secret sentinel" not in (output / "episodes.jsonl").read_text()


def test_full_returned_block_durable_before_workload_check(tmp_path, harness, monkeypatch):
    original = profile_scripted.check_trial
    observations = []

    def check(episodes, world, revision):
        observations.append(len(raws(tmp_path / "fresh")))
        return original(episodes, world, revision)

    monkeypatch.setattr(profile_scripted, "check_trial", check)
    collect(tmp_path)
    assert observations == list(range(24, 193, 24))


def test_cap_overflow_preserves_prior_records_and_explicit_current_marker(tmp_path, harness, monkeypatch):
    monkeypatch.setattr(profile_scripted, "ARTIFACT_CAP", profile_scripted.REPORT_RESERVE + 10_000)
    output, report = collect(tmp_path)
    records = raws(output)
    assert report["status"] == "stopped" and report["attempted_episodes"] == 24
    assert report["persisted_episodes"] > 0 and report["diagnostic_episodes"] == 1
    assert report["returned_without_persistence"] > 0
    assert records[-1]["episode"] is None and not records[-1]["exact_envelope_preserved"]
    assert profile_scripted.artifact_bytes(output) <= profile_scripted.ARTIFACT_CAP


def test_temporary_database_removed_even_on_append_failure(tmp_path, harness, monkeypatch):
    original = profile_scripted.Store

    class FailingStore(original):
        def append_episode(self, *args):
            raise ValueError("secret sentinel")

    monkeypatch.setattr(profile_scripted, "Store", FailingStore)
    output, report = collect(tmp_path)
    assert report["status"] == "stopped" and report["persisted_episodes"] == len(raws(output)) == 192
    assert report["phases"][-1]["completed_operations"] == 0
    assert all(not path.parent.exists() for path in harness["databases"])
    assert report["temporary_database_removed"]
    assert "secret sentinel" not in (output / "profile.json").read_text()


def test_source_gate_hashes_full_scope_and_historical_inputs_without_git_calls(tmp_path, monkeypatch):
    for name in ("src/world_engine/module.py", *profile_scripted.SOURCE_SCOPE[1:]):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"source")
    historical = {}
    for name in profile_scripted.ORIGINAL_HASHES:
        path = tmp_path / profile_scripted.ORIGINAL / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"old")
        historical[name] = hashlib.sha256(b"old").hexdigest()
    monkeypatch.setattr(profile_scripted, "ROOT", tmp_path)
    monkeypatch.setattr(profile_scripted, "ORIGINAL_HASHES", historical)
    commands = []

    def run(command, **kwargs):
        commands.append(command)

        class Result:
            stdout = REVISION if command[1] == "rev-parse" else ""

        return Result()

    monkeypatch.setattr(profile_scripted.subprocess, "run", run)
    identity = profile_scripted.source_identity(REVISION)
    assert len(identity["files_sha256"]) == 6 and identity["original_files_sha256"] == historical
    assert commands[1][-len(profile_scripted.SOURCE_SCOPE):] == list(profile_scripted.SOURCE_SCOPE)
    (tmp_path / profile_scripted.ORIGINAL / "producer.py").write_bytes(b"modified")
    with pytest.raises(profile_scripted.ProfileStopped, match="historical"):
        profile_scripted.source_identity(REVISION)


@pytest.mark.parametrize("world", profile_scripted.WORLDS)
def test_profile_observation_counter_uses_exact_public_boundary_code_only(tmp_path, monkeypatch, world):
    output = tmp_path / "profiles"
    output.mkdir()
    code = profile_scripted.ENVIRONMENTS[world].observe.__code__
    expected = profile_scripted.NEW_OBSERVATIONS[profile_scripted.WORLDS.index(world)]

    class FakeStats:
        total_tt = 0.1
        total_calls = 9999
        stats = {(code.co_filename, code.co_firstlineno, code.co_name): (expected, expected, 0.01, 0.1, {}),
                 ("other-file.py", 1, "observe"): (999, 999, 0, 0, {})}

        def __init__(self, profile, **kwargs):
            pass

        def strip_dirs(self):
            return self

        def sort_stats(self, *args):
            return self

        def print_stats(self, *args):
            pass

    class FakeProfile:
        def dump_stats(self, path):
            Path(path).write_bytes(b"mock-stats")

    monkeypatch.setattr(profile_scripted.pstats, "Stats", FakeStats)
    result = profile_scripted.profile_snapshot(output, world, FakeProfile(), world=world)
    assert result["observe_calls"] == expected
    assert result["observe_function"] == {"file": code.co_filename, "line": code.co_firstlineno, "function": "observe"}


def test_raw_and_final_files_exclusive(tmp_path):
    profile_scripted.write_file(tmp_path, "existing", b"old")
    with pytest.raises(FileExistsError):
        profile_scripted.write_file(tmp_path, "existing", b"new")
    assert (tmp_path / "existing").read_bytes() == b"old"
    report = {"status": "mock"}
    profile_scripted.write_report(tmp_path, report)
    assert report["artifact_total_bytes"] == profile_scripted.artifact_bytes(tmp_path)
    with pytest.raises(FileExistsError):
        profile_scripted.write_report(tmp_path, report)


@pytest.mark.parametrize("world_index", range(4))
def test_both_read_count_formulas_include_correct_world_setup(world_index):
    decisions = profile_scripted.DECISIONS[world_index]
    setup = profile_scripted.SETUP_OBSERVATIONS[world_index]
    assert 3 * decisions + setup * 24 == profile_scripted.OLD_OBSERVATIONS[world_index]
    assert 2 * decisions + setup * 24 == profile_scripted.NEW_OBSERVATIONS[world_index]
