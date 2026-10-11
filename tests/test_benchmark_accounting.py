import importlib
import itertools
import json

import pytest

module = importlib.import_module("world_engine.benchmark")


def episode(index):
    return {"steps": 4, "passed": True, "invalid_actions": 0, "error": None,
            "status": "completed", "elapsed_seconds": .25, "scenario_id": f"scenario-{index}",
            "provenance": {key: "fixture" for key in ("environment_code_hash", "grader_code_hash",
                "policy_code_hash", "runtime", "git_revision", "git_dirty")}}


def mock_scheduler(monkeypatch, outcomes):
    instances = []

    class Manager:
        def __init__(self, store):
            self.results = itertools.cycle(outcomes)
            self.configs = []
            self.closed = False
            instances.append(self)

        def submit(self, config):
            self.configs.append(config)
            return {"id": f"mock-run-{len(self.configs)}"}

        async def wait(self, run_id):
            outcome = next(self.results)
            status, count = outcome[:2]
            records = [episode(index) for index in range(count)]
            if len(outcome) == 3:
                for record in records:
                    record["passed"] = outcome[2]
            return {"status": status, "episodes": records}

        async def close(self):
            self.closed = True

    clock = itertools.count(step=2)
    monkeypatch.setattr(module, "Store", lambda path: None)
    monkeypatch.setattr(module, "RunManager", Manager)
    monkeypatch.setattr(module, "ENVIRONMENTS", {"crm-merge": object()})
    monkeypatch.setattr(module.time, "perf_counter", lambda: next(clock))
    return instances


async def test_successful_accounting_keeps_existing_rates_and_case_intervals(tmp_path, monkeypatch):
    managers = mock_scheduler(monkeypatch, [("completed", 2)])
    output = tmp_path / "complete"
    result = await module.benchmark(output, episodes=2, trials=3)
    assert managers[0].closed and len(managers[0].configs) == 18
    for trial in result["raw_trials"]:
        assert trial["requested_episodes"] == trial["persisted_episodes"] == trial["count"] == 2
        assert trial["run_status"] == "completed" and trial["measurement_status"] == "complete"
        assert trial["inconclusive_reason"] is None
        assert trial["episodes_per_second"] == 1 and trial["steps_per_second"] == 4
        assert trial["implementation"] == episode(0)["provenance"]
        assert trial["scenario_passed"] == [True, True]
    for row in result["rows"]:
        assert row["episodes"] == row["persisted_episodes"] == row["requested_episodes"] == 6
        assert row["measurement_status"] == "complete" and row["inconclusive_trials"] == 0
        assert row["independent_scenarios"] == 2 and row["pass_rate_wilson_95"] == module.wilson(2, 2)
        assert row["success_rate"] == 1 and row["cancel_rate"] == 0
        assert row["p50_episode_seconds"] == row["p95_episode_seconds"] == .25
    assert json.loads((output / "benchmark.json").read_text()) == result
    assert "inconclusive" not in (output / "benchmark.md").read_text().split("| World |")[1]
    assert "--output NEW_OUTPUT_DIRECTORY" in (output / "benchmark.md").read_text()


async def test_partial_persistence_uses_observed_count_not_requested_count(tmp_path, monkeypatch):
    managers = mock_scheduler(monkeypatch, [("failed", 1)])
    result = await module.benchmark(tmp_path / "partial", episodes=2, trials=1)
    assert managers[0].closed
    for trial in result["raw_trials"]:
        assert trial["requested_episodes"] == 2 and trial["persisted_episodes"] == trial["count"] == 1
        assert trial["run_status"] == "failed" and trial["measurement_status"] == "inconclusive"
        assert trial["inconclusive_reason"]
        assert trial["episodes_per_second"] == .5 and trial["steps_per_second"] == 2
    assert all(row["episodes"] == 1 and row["requested_episodes"] == 2 for row in result["rows"])
    assert all(row["inconclusive_trials"] == 1 for row in result["rows"])
    assert "1/1 inconclusive" in (tmp_path / "partial" / "benchmark.md").read_text()


async def test_zero_persisted_episodes_write_explicit_inconclusive_receipt(tmp_path, monkeypatch):
    managers = mock_scheduler(monkeypatch, [("failed", 0)])
    output = tmp_path / "empty"
    result = await module.benchmark(output, episodes=2, trials=1)
    assert managers[0].closed
    for trial in result["raw_trials"]:
        assert trial["requested_episodes"] == 2 and trial["persisted_episodes"] == trial["count"] == 0
        assert trial["run_status"] == "failed" and trial["measurement_status"] == "inconclusive"
        assert trial["implementation"] is None
        assert trial["episodes_per_second"] == trial["steps_per_second"] == 0
        assert trial["episode_durations"] == trial["scenario_ids"] == trial["scenario_passed"] == []
    for row in result["rows"]:
        assert row["episodes"] == row["persisted_episodes"] == row["independent_scenarios"] == 0
        assert row["success_rate"] is row["cancel_rate"] is None
        assert row["p50_episode_seconds"] is row["p95_episode_seconds"] is None
        assert row["pass_rate_wilson_95"] == [0, 1]
    assert json.loads((output / "benchmark.json").read_text()) == result
    assert "0/0 inconclusive" in (output / "benchmark.md").read_text()
    assert "n/a" in (output / "benchmark.md").read_text()


@pytest.mark.parametrize("status", ["failed", "cancelled", "interrupted"])
async def test_terminal_batch_failure_is_inconclusive_even_with_all_records(tmp_path, monkeypatch, status):
    mock_scheduler(monkeypatch, [(status, 2)])
    result = await module.benchmark(tmp_path / status, episodes=2, trials=1)
    assert all(trial["persisted_episodes"] == 2 and trial["run_status"] == status for trial in result["raw_trials"])
    assert all(row["measurement_status"] == "inconclusive" for row in result["rows"])


async def test_empty_first_trial_does_not_hide_later_observed_scenarios(tmp_path, monkeypatch):
    mock_scheduler(monkeypatch, [("failed", 0), ("completed", 2)])
    result = await module.benchmark(tmp_path / "mixed", episodes=2, trials=2)
    for row in result["rows"]:
        assert row["requested_episodes"] == 4 and row["persisted_episodes"] == row["episodes"] == 2
        assert row["inconclusive_trials"] == 1 and row["measurement_status"] == "inconclusive"
        assert row["independent_scenarios"] == 2 and row["pass_rate_wilson_95"] == module.wilson(2, 2)
        assert row["median_episodes_per_second"] == .5


async def test_repeated_conflicting_outcomes_label_first_observed_case_policy(tmp_path, monkeypatch):
    mock_scheduler(monkeypatch, [("completed", 2, True), ("completed", 2, False)])
    result = await module.benchmark(tmp_path / "conflicting", episodes=2, trials=2)
    for row in result["rows"]:
        assert row["episodes"] == 4 and row["passed"] == 2 and row["success_rate"] == .5
        assert row["independent_scenarios"] == 2 and row["pass_rate_wilson_95"] == module.wilson(2, 2)
        assert row["scenario_outcome_policy"] == "first-observed-per-scenario-id"
        assert row["conflicting_scenario_outcomes"] == 2
    assert "Conflicting repeated outcomes" in result["limitations"]
