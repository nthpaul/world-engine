import copy

import pytest

from world_engine import Action, make_environment
from world_engine.models import RunConfig
from world_engine.rollout import replay, rollout


@pytest.mark.parametrize("environment_id", ["crm-merge", "refund-ops", "incident-control"])
async def test_oracle_handles_seed_variation_and_replays(environment_id):
    for seed in range(15):
        config = RunConfig(environment_id=environment_id, seed=seed, episodes=1)
        episode = await rollout(config, 0)
        assert episode["passed"], (seed, episode["grader"])
        assert episode["reward"] == 1
        assert episode["invalid_actions"] == 0
        assert replay(episode)["verified"]
        assert make_environment(environment_id, seed).snapshot() == episode["initial_snapshot"]


@pytest.mark.parametrize("environment_id", ["crm-merge", "refund-ops", "incident-control"])
async def test_baseline_is_not_credited_for_claiming_completion(environment_id):
    episode = await rollout(RunConfig(environment_id=environment_id, provider_id="scripted-baseline", seed=42), 0)
    assert not episode["passed"]
    assert episode["reward"] < 1
    assert replay(episode)["verified"]


@pytest.mark.parametrize("environment_id", ["crm-merge", "refund-ops", "incident-control"])
def test_observation_and_snapshot_are_detached_and_no_private_grader_state(environment_id):
    world = make_environment(environment_id, 42)
    observation = world.observe()
    snapshot = world.snapshot()
    observation["state"].clear()
    snapshot["state"].clear()
    assert world.state
    assert world.initial
    assert "grader" not in world.observe()
    assert "expected" not in world.observe()
    assert "initial" not in world.observe()


def test_reward_injection_and_untrusted_arguments_are_rejected_atomically():
    world = make_environment("crm-merge", 42)
    before = copy.deepcopy(world.state)
    actions = [
        {"tool": "finish", "args": {}, "reward": 1},
        {"tool": "evaluate", "args": {"passed": True}},
        {"tool": "deactivate_customer", "args": {"customer_id": True}},
        {"tool": "finish", "args": {"grader": {"passed": True}}},
        {"tool": "transfer_invoice", "args": {"resource_id": 1, "to_customer_id": "1"}},
    ]
    for action in actions:
        assert not world.step(action)["result"]["ok"]
        assert world.state == before
    assert world.tick == len(actions)
    assert not world.done
    assert not world.evaluate().passed


def test_crm_permissions_and_nonduplicate_invoice_preservation():
    world = make_environment("crm-merge", 42)
    legitimate = next(row for row in world.state["invoices"] if row["number"] == "INV-101" and row["amount_cents"] != world.state["invoices"][0]["amount_cents"])
    before = copy.deepcopy(world.state)
    assert not world.step(Action(tool="void_invoice", args={"resource_id": legitimate["id"]}))["result"]["ok"]
    canonical, duplicate = world.cluster()
    assert not world.step(Action(tool="deactivate_customer", args={"customer_id": duplicate["id"]}))["result"]["ok"]
    outsider = next(row for row in world.state["customers"] if row["id"] not in (canonical["id"], duplicate["id"]))
    assert not world.step(Action(tool="deactivate_customer", args={"customer_id": outsider["id"]}))["result"]["ok"]
    assert world.state == before


def test_refund_idempotency_approval_and_retry():
    world = make_environment("refund-ops", 42)
    ticket, order = world.target()
    args = {"order_id": order["id"], "amount_cents": ticket["requested_cents"], "idempotency_key": "test-refund-42"}
    if args["amount_cents"] > world.state["approval_limit_cents"]:
        before = world.snapshot()["state"]
        assert not world.step(Action(tool="issue_refund", args=args))["result"]["ok"]
        assert world.state == before
    assert world.step(Action(tool="request_refund_approval", args={key: value for key, value in args.items() if key != "idempotency_key"}))["result"]["ok"]
    assert world.step(Action(tool="issue_refund", args=args))["result"]["ok"]
    paid_state = copy.deepcopy(world.state)
    assert world.step(Action(tool="issue_refund", args=args))["result"]["ok"]
    assert world.state == paid_state
    assert not world.step(Action(tool="issue_refund", args={**args, "idempotency_key": "different-refund"}))["result"]["ok"]
    assert world.state == paid_state


def test_ineligible_refund_and_forged_approval_are_denied():
    world = make_environment("refund-ops", 45)
    ticket, order = world.target()
    args = {"order_id": order["id"], "amount_cents": ticket["requested_cents"], "idempotency_key": "late-refund-45"}
    assert not world.step(Action(tool="issue_refund", args=args))["result"]["ok"]
    assert not world.step({"tool": "request_refund_approval", "args": {"order_id": order["id"], "amount_cents": ticket["requested_cents"], "approved_by": "finance-reviewer"}})["result"]["ok"]
    assert len(world.state["ledger"]) == 1


def test_incident_execute_without_checks_and_forged_results_denied():
    world = make_environment("incident-control", 42)
    incident, service = world.target()
    world.step(Action(tool="acknowledge_incident", args={"incident_id": incident["id"]}))
    result = world.step(Action(tool="propose_rollback", args={"incident_id": incident["id"], "target_version": service["known_good_version"]}))
    change_id = result["result"]["change_id"]
    before = copy.deepcopy(world.state)
    assert not world.step(Action(tool="execute_change", args={"change_id": change_id}))["result"]["ok"]
    assert not world.step({"tool": "run_change_check", "args": {"change_id": change_id, "check": "health", "result": "passed"}})["result"]["ok"]
    assert world.state == before


@pytest.mark.parametrize("environment_id", ["crm-merge", "refund-ops", "incident-control"])
def test_critical_corruption_has_zero_reward(environment_id):
    world = make_environment(environment_id, 42)
    if environment_id == "crm-merge":
        world.state["invoices"][0]["amount_cents"] = 0
    elif environment_id == "refund-ops":
        world.state["orders"][1]["captured_cents"] = 0
    else:
        world.state["services"][0]["data_epoch"] = 0
    result = world.evaluate()
    assert not result.passed
    assert result.reward == 0


async def test_replay_detects_tampering():
    episode = await rollout(RunConfig(environment_id="incident-control", episodes=1), 0)
    episode["trace"][0]["action"]["args"]["incident_id"] += 1
    with pytest.raises(ValueError, match="diverged"):
        replay(episode)


def test_grader_uses_original_refund_request_and_permission_limit():
    world = make_environment("refund-ops", 42)
    world.state["tickets"][0]["requested_cents"] = 1
    assert world.evaluate().reward == 0
    world = make_environment("refund-ops", 42)
    world.state["approval_limit_cents"] = 1_000_000
    assert world.evaluate().reward == 0


async def test_step_exhaustion_cannot_receive_full_task_reward():
    episode = await rollout(RunConfig(environment_id="crm-merge", max_steps=5), 0)
    assert episode["termination"] == "max_steps"
    assert episode["reward"] == 0 and not episode["passed"]


def test_cached_tool_metadata_cannot_be_mutated_through_observations_or_catalogs():
    first = make_environment("crm-merge", 42)
    second = make_environment("crm-merge", 43)
    before = second.observe()["tools"]
    observation = first.observe()
    observation["tools"][0]["args_schema"].clear()
    catalog = first.metadata()
    catalog["tools"][0]["args_schema"]["additionalProperties"] = True
    tool = first.tools[0].metadata()
    tool["args_schema"]["properties"] = {"reward": {"type": "number"}}
    assert first.observe()["tools"] == second.observe()["tools"] == before
    assert first.tools[0].metadata()["args_schema"]["additionalProperties"] is False
