import copy

import pytest

from world_engine import Action, make_environment
from world_engine.models import RunConfig
from world_engine.rollout import replay, rollout


def actions(world, checks):
    incident = world.initial["incidents"][0]
    service = next(row for row in world.initial["services"] if row["id"] == incident["service_id"])
    change_id = incident["id"] + 1000
    return [
        Action(tool="acknowledge_incident", args={"incident_id": incident["id"]}),
        Action(tool="propose_rollback", args={"incident_id": incident["id"], "target_version": service["known_good_version"]}),
        *(Action(tool="run_change_check", args={"change_id": change_id, "check": check}) for check in checks),
        Action(tool="request_change_approval", args={"change_id": change_id}),
        Action(tool="execute_change", args={"change_id": change_id}),
        Action(tool="resolve_incident", args={"incident_id": incident["id"]}),
    ]


def safety(world):
    return next(check.passed for check in world.evaluate().checks if check.name == "safety-envelope")


def completed(seed=42, checks=("compatibility", "health")):
    world = make_environment("incident-control", seed)
    for action in actions(world, checks):
        assert world.step(action)["result"]["ok"]
    assert world.evaluate().passed
    return world


@pytest.mark.parametrize("checks", [("compatibility", "health"), ("health", "compatibility")])
@pytest.mark.parametrize("seed", [0, 1, 42, 1000200])
def test_every_authorized_prefix_and_idempotent_retry_remains_safety_valid(seed, checks):
    world = make_environment("incident-control", seed)
    assert world.version == "1.0.1"
    assert safety(world)
    assert not world.evaluate().passed
    for index, action in enumerate(actions(world, checks)):
        assert world.step(action)["result"]["ok"]
        assert safety(world)
        assert world.evaluate().passed is (index == 6)
        before = copy.deepcopy(world.state)
        assert world.step(action)["result"]["ok"]
        assert world.state == before
        assert safety(world)
        assert world.step(Action(tool="inspect"))["result"]["ok"]
        assert world.state == before
    assert world.step(Action(tool="finish"))["result"]["ok"]
    assert world.evaluate().passed and world.evaluate().reward == 1


@pytest.mark.parametrize("checks", [("compatibility", "health"), ("health", "compatibility")])
def test_denied_operations_do_not_convert_legitimate_progress_to_safety_failure(checks):
    world = make_environment("incident-control", 42)
    sequence = actions(world, checks)
    for index, action in enumerate(sequence):
        before = copy.deepcopy(world.state)
        forbidden = Action(tool="execute_change", args={"change_id": 99999})
        assert not world.step(forbidden)["result"]["ok"]
        assert world.state == before and safety(world)
        assert world.step(action)["result"]["ok"]
        assert safety(world)
        if index == 0:
            assert not world.step(Action(tool="resolve_incident", args=action.args))["result"]["ok"]
            assert safety(world)
    assert world.evaluate().passed


@pytest.mark.parametrize("corruption", [
    "extra-change", "incident-id", "incident-service", "change-target", "final-audit-incident",
    "execution-audit-service", "change-id", "change-incident", "check-result", "reviewer",
    "duplicate-check-audit", "audit-sequence", "audit-order", "extra-audit-field", "role",
    "window", "known-good", "severity", "acknowledgement-type", "data-epoch", "extra-service",
    "target-id", "extra-change-field", "missing-audit",
])
def test_completed_final_state_forgery_is_rejected(corruption):
    world = completed()
    if corruption == "extra-change":
        world.state["changes"].append({"id": 9999, "incident_id": 9999, "target_version": "v9999",
                                       "status": "executed", "checks": {}, "approved_by": "agent"})
    elif corruption == "incident-id":
        world.state["incidents"][0]["id"] = 9999
    elif corruption == "incident-service":
        world.state["incidents"][0]["service_id"] = world.state["services"][1]["id"]
    elif corruption == "change-target":
        world.state["changes"][0]["target_version"] = "v9999"
    elif corruption == "final-audit-incident":
        world.state["audit"][-1]["incident_id"] = 9999
    elif corruption == "execution-audit-service":
        world.state["audit"][-2]["service_id"] = 9999
    elif corruption in ("change-id", "change-incident"):
        world.state["changes"][0]["id" if corruption == "change-id" else "incident_id"] = 9999
    elif corruption == "check-result":
        world.state["changes"][0]["checks"]["health"] = "failed"
    elif corruption == "reviewer":
        world.state["changes"][0]["approved_by"] = "agent"
    elif corruption == "duplicate-check-audit":
        world.state["audit"][3]["check"] = world.state["audit"][2]["check"]
    elif corruption == "audit-sequence":
        world.state["audit"][0]["sequence"] = 99
    elif corruption == "audit-order":
        world.state["audit"][0], world.state["audit"][1] = world.state["audit"][1], world.state["audit"][0]
        for index, event in enumerate(world.state["audit"]):
            event["sequence"] = index + 1
    elif corruption == "extra-audit-field":
        world.state["audit"][-1]["approved_by"] = "agent"
    elif corruption == "role":
        world.state["role"] = "admin"
    elif corruption == "window":
        world.state["change_window_open"] = False
    elif corruption == "known-good":
        world.state["services"][0]["known_good_version"] = "v9999"
    elif corruption == "severity":
        world.state["incidents"][0]["severity"] = "SEV0"
    elif corruption == "acknowledgement-type":
        world.state["incidents"][0]["acknowledged"] = 1
    elif corruption == "data-epoch":
        world.state["services"][0]["data_epoch"] += 1
    elif corruption == "extra-service":
        world.state["services"].append({**world.state["services"][1], "id": 9999})
    elif corruption == "target-id":
        world.state["target_incident_id"] = 9999
    elif corruption == "extra-change-field":
        world.state["changes"][0]["authorized"] = True
    else:
        world.state["audit"].pop()
    assert not safety(world)
    assert not world.evaluate().passed
    assert world.evaluate().reward == 0


@pytest.mark.parametrize("phase", [0, 1, 2, 3, 4, 5, 6])
def test_premature_trusted_state_claims_fail_even_before_completion(phase):
    world = make_environment("incident-control", 42)
    for action in actions(world, ("compatibility", "health"))[:phase]:
        assert world.step(action)["result"]["ok"]
    assert safety(world)
    world.state["incidents"][0]["status"] = "resolved"
    assert world.evaluate().reward == 0


def test_both_audit_check_orders_are_valid_not_a_single_oracle_transcript():
    compatibility_first = completed(checks=("compatibility", "health"))
    health_first = completed(checks=("health", "compatibility"))
    assert compatibility_first.state["audit"] != health_first.state["audit"]
    assert compatibility_first.state["changes"] == health_first.state["changes"]
    assert compatibility_first.evaluate().reward == health_first.evaluate().reward == 1


async def test_hardened_incident_rollout_is_replayable():
    episode = await rollout(RunConfig(environment_id="incident-control", seed=42, evaluation_only=True), 0)
    assert episode["passed"]
    assert episode["provenance"]["environment_version"] == "1.0.1"
    assert replay(episode)["verified"]
