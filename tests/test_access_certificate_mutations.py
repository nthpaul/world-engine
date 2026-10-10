"""Controller-state counterfactuals, not exploits reachable through normal tools."""

import copy

import pytest

from world_engine.access_provisioning import AccessProvisioning
from world_engine.models import Action
from world_engine.providers import ScriptedProvider


async def observation_flow(world, stop_before=None):
    provider = ScriptedProvider()
    history = []
    for _ in range(20):
        action = (await provider.decide(world.observe(), history)).action
        if action.tool == stop_before:
            return history, action
        transition = world.step(action)
        assert transition["result"]["ok"]
        history.append({"action": action.model_dump(), **transition})
        if world.done:
            return history, None
    pytest.fail("observation-driven reference exceeded its fixed decision budget")


def fixture_world():
    world = AccessProvisioning()
    world.reset(4)
    return world


def assert_rejected(world):
    result = world.evaluate()
    assert result.reward == 0 and not result.passed
    assert not result.checks[0].passed


async def test_unjournaled_scoped_approvals_cannot_authorize_grader_certificate():
    donor = fixture_world()
    history, _ = await observation_flow(donor)
    assert donor.evaluate().reward == 1
    reviews = [entry["result"]["review"] for entry in history if entry["action"]["tool"] == "request_review"]
    assert len(reviews) == 3

    world = fixture_world()
    await observation_flow(world, stop_before="request_review")
    assert not world.state["approvals"]
    # Match legitimate issuance time without issuing any review certificate here.
    for _ in reviews:
        assert world.step(Action(tool="inspect"))["result"]["ok"]
    world.state["approvals"] = copy.deepcopy(reviews)
    settlement = [entry["action"] for entry in history if entry["action"]["tool"] in
                  ("grant_access", "close_request", "finish")]
    assert len(settlement) == 3
    for action in settlement:
        assert world.step(Action.model_validate(action))["result"]["ok"]

    assert world.done and world.state["grants"]
    assert all(event["tool"] != "request_review" for event in world.state["audit"])
    assert world.state["grants"][0]["review_ids"] == [review["id"] for review in reviews]
    assert_rejected(world)


@pytest.mark.parametrize("field", ["active", "risk_rank", "grant_tick", "issued_tick"])
async def test_type_only_completed_state_substitution_invalidates_certificate(field):
    world = fixture_world()
    await observation_flow(world)
    assert world.evaluate().reward == 1
    if field == "active":
        record = next(row for row in world.state["employees"] if row["active"] is True)
        replacement = 1
    elif field == "risk_rank":
        record = next(row["policy"] for row in world.state["groups"] if row["policy"][field] == 0)
        replacement = False
    elif field == "grant_tick":
        record = world.state["grants"][0]
        replacement = float(record[field])
    else:
        record = world.state["approvals"][0]
        replacement = float(record[field])
    assert record[field] == replacement and type(record[field]) is not type(replacement)
    record[field] = replacement
    assert_rejected(world)


@pytest.mark.parametrize("mutation", ["duplicate", "foreign"])
async def test_grant_review_id_substitution_invalidates_certificate(mutation):
    world = fixture_world()
    await observation_flow(world)
    assert world.evaluate().reward == 1
    review_ids = world.state["grants"][0]["review_ids"]
    assert len(review_ids) == 3 and len(set(review_ids)) == 3
    review_ids[-1] = review_ids[0] if mutation == "duplicate" else "foreign-review-certificate"
    assert_rejected(world)
