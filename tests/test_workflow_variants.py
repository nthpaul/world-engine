import copy

import pytest

from world_engine import Action, make_environment
from world_engine.environments import CRMMerge, RefundOps
from world_engine.models import RunConfig
from world_engine.providers import ScriptedProvider
from world_engine.rollout import replay, rollout


def complete(world):
    oracle = ScriptedProvider()
    decide = oracle.crm if world.id == "crm-merge" else oracle.refund
    for _ in range(20):
        result = world.step(decide(world.observe()["state"]))
        assert result["result"]["ok"], result["result"]
        if world.done:
            break
    assert world.done
    assert world.evaluate().passed
    return world


def fixture(world, state):
    # Counterfactuals are new trusted test fixtures, not permitted agent mutations.
    world.state = copy.deepcopy(state)
    world.initial = copy.deepcopy(state)
    return world


def crm_outcome(world):
    return {
        "customers": sorted((row["id"], row["status"]) for row in world.state["customers"]),
        "invoices": sorted((row["id"], row["customer_id"], row["status"]) for row in world.state["invoices"]),
        "tickets": sorted((row["id"], row["customer_id"]) for row in world.state["tickets"]),
    }


@pytest.mark.parametrize("environment_id", ["crm-merge", "refund-ops"])
@pytest.mark.parametrize("seed", range(24))
async def test_variant_oracle_and_baseline_are_replayable(environment_id, seed):
    config = RunConfig(environment_id=environment_id, seed=seed, episodes=1, max_steps=20,
                       timeout_seconds=30, evaluation_only=True)
    oracle = await rollout(config, 0)
    baseline = await rollout(config.model_copy(update={"provider_id": "scripted-baseline"}), 0)
    assert oracle["passed"] and oracle["reward"] == 1
    assert oracle["invalid_actions"] == 0
    assert not baseline["passed"] and baseline["reward"] < 1
    assert replay(oracle)["verified"] and replay(baseline)["verified"]
    assert oracle["lineage_id"] == baseline["lineage_id"]
    assert oracle["split"] == baseline["split"]
    assert oracle["scenario_id"] == baseline["scenario_id"]
    assert "variant" not in oracle["initial_observation"]["state"]


@pytest.mark.parametrize("seed", range(12))
def test_crm_seed_mapping_exercises_original_survivor_rules(seed):
    world = make_environment("crm-merge", seed)
    assert world.version == "1.1.1"
    canonical, duplicate = world.cluster()
    copies = world.state["invoices"][:2]
    survivor = min(copies, key=lambda row: (row["customer_id"] != canonical["id"], row["issued_at"], row["id"]))
    if seed % 4 == 1:
        assert canonical["created_at"] == duplicate["created_at"]
        assert canonical["id"] < duplicate["id"]
    if seed % 4 in (2, 3):
        assert all(row["customer_id"] == duplicate["id"] for row in copies)
        if seed % 4 == 3:
            assert copies[0]["issued_at"] == copies[1]["issued_at"]
            assert survivor["id"] == min(row["id"] for row in copies)
        else:
            assert survivor["issued_at"] < max(row["issued_at"] for row in copies)
    assert survivor["id"] not in world.duplicate_invoice_ids()
    complete(world)
    assert world.row("invoices", survivor["id"])["customer_id"] == canonical["id"]
    assert world.row("invoices", survivor["id"])["status"] == "open"


@pytest.mark.parametrize("seed", range(4))
def test_crm_permutation_and_email_normalization_preserve_semantic_outcome(seed):
    reference = complete(make_environment("crm-merge", seed))
    changed = make_environment("crm-merge", seed)
    state = changed.snapshot()["state"]
    for collection in ("customers", "invoices", "tickets"):
        state[collection].reverse()
    for customer in state["customers"]:
        customer["email"] = f"  {customer['email'].strip().swapcase()}  "
    complete(fixture(changed, state))
    assert crm_outcome(changed) == crm_outcome(reference)
    assert changed.evaluate().reward == reference.evaluate().reward == 1


def test_crm_unrelated_collision_does_not_change_the_solution():
    reference = complete(make_environment("crm-merge", 3))
    changed = make_environment("crm-merge", 3)
    state = changed.snapshot()["state"]
    canonical, duplicate = changed.cluster()
    outsider = next(row for row in state["customers"] if row["id"] not in (canonical["id"], duplicate["id"]))
    extra = {**state["invoices"][0], "id": 2000, "customer_id": outsider["id"]}
    state["invoices"].append(extra)
    complete(fixture(changed, state))
    assert changed.row("invoices", extra["id"]) == extra
    assert crm_outcome(changed)["invoices"][:-1] == crm_outcome(reference)["invoices"]


@pytest.mark.parametrize("seed", range(4))
def test_crm_wrong_survivor_and_unrelated_mutations_cannot_earn_reward(seed):
    world = make_environment("crm-merge", seed)
    canonical, _ = world.cluster()
    copies = world.state["invoices"][:2]
    survivor = min(copies, key=lambda row: (row["customer_id"] != canonical["id"], row["issued_at"], row["id"]))
    before = copy.deepcopy(world.state)
    assert not world.step(Action(tool="void_invoice", args={"resource_id": survivor["id"]}))["result"]["ok"]
    assert world.state == before and world.tick == 1
    world.row("invoices", survivor["id"])["status"] = "void"
    assert world.evaluate().reward == 0
    world = complete(make_environment("crm-merge", seed))
    world.state["invoices"][3]["customer_id"] = canonical["id"]
    assert world.evaluate().reward == 0


@pytest.mark.parametrize("seed", range(8))
def test_refund_case_fields_and_exact_operational_outcome(seed):
    world = make_environment("refund-ops", seed)
    assert world.version == "1.1.2"
    ticket, order = world.target()
    expected_eligible = seed in (0, 1, 2, 3)
    assert world.eligible() is expected_eligible
    if seed == 1:
        assert order["delivery_age_days"] == 30
    elif seed in (2, 3):
        assert ticket["requested_cents"] == (5000 if seed == 2 else 5001)
    elif seed == 4:
        assert order["delivery_age_days"] == 31
    elif seed == 5:
        assert order["captured_cents"] - order["refunded_cents"] == ticket["requested_cents"] - 1
    elif seed == 6:
        assert order["chargeback"]
    elif seed == 7:
        assert not ticket["damage_verified"]
    original_ledger = copy.deepcopy(world.state["ledger"])
    complete(world)
    ticket, order = world.target()
    assert ticket["resolution"] == ("refunded" if expected_eligible else "denied")
    assert world.state["ledger"][:1] == original_ledger
    assert len(world.state["ledger"]) == 1 + int(expected_eligible)
    if not expected_eligible:
        assert world.state["approvals"] == []
        assert order["refunded_cents"] == 1000
    if seed == 2:
        assert world.state["approvals"] == []
    elif seed == 3:
        assert len(world.state["approvals"]) == 1


@pytest.mark.parametrize("field,eligible_value,ineligible_value", [
    ("delivery_age_days", 30, 31),
    ("chargeback", False, True),
    ("damage_verified", True, False),
    ("remaining_offset", 0, -1),
])
def test_refund_one_field_counterfactual_changes_only_permitted_resolution(field, eligible_value, ineligible_value):
    completed = []
    for value in (eligible_value, ineligible_value):
        world = make_environment("refund-ops", 8)
        state = world.snapshot()["state"]
        if field == "damage_verified":
            state["tickets"][0][field] = value
        elif field == "remaining_offset":
            state["orders"][0]["captured_cents"] += value
        else:
            state["orders"][0][field] = value
        complete(fixture(world, state))
        completed.append(world)
    eligible, ineligible = completed
    assert eligible.target()[0]["resolution"] == "refunded"
    assert ineligible.target()[0]["resolution"] == "denied"
    assert eligible.state["orders"][1:] == ineligible.state["orders"][1:]
    assert eligible.state["ledger"][:1] == ineligible.state["ledger"]


def test_refund_one_cent_approval_boundary_requires_exact_reviewer_payment():
    for amount in (5000, 5001):
        world = make_environment("refund-ops", 2)
        state = world.snapshot()["state"]
        state["tickets"][0]["requested_cents"] = amount
        state["orders"][0]["captured_cents"] = amount + 1000
        fixture(world, state)
        ticket, order = world.target()
        args = {"order_id": order["id"], "amount_cents": amount, "idempotency_key": "boundary-refund"}
        before = copy.deepcopy(world.state)
        result = world.step(Action(tool="issue_refund", args=args))
        assert result["result"]["ok"] is (amount == 5000)
        if amount == 5001:
            assert world.state == before
            assert world.step(Action(tool="request_refund_approval", args={"order_id": order["id"], "amount_cents": amount}))["result"]["ok"]
            assert world.step(Action(tool="issue_refund", args=args))["result"]["ok"]
        assert world.step(Action(tool="close_ticket", args={"ticket_id": ticket["id"], "resolution": "refunded"}))["result"]["ok"]
        world.step(Action(tool="finish"))
        assert world.evaluate().passed


@pytest.mark.parametrize("seed", range(4))
def test_refund_exact_key_retries_are_idempotent_before_and_after_closure(seed):
    world = make_environment("refund-ops", seed)
    ticket, order = world.target()
    args = {"order_id": order["id"], "amount_cents": ticket["requested_cents"], "idempotency_key": "retry-payment-key"}
    if args["amount_cents"] > world.state["approval_limit_cents"]:
        world.step(Action(tool="request_refund_approval", args={key: value for key, value in args.items() if key != "idempotency_key"}))
    assert world.step(Action(tool="issue_refund", args=args))["result"]["ok"]
    paid = copy.deepcopy(world.state)
    assert world.step(Action(tool="issue_refund", args=args))["result"]["ok"]
    assert world.state == paid
    assert not world.step(Action(tool="issue_refund", args={**args, "idempotency_key": "fresh-payment-key"}))["result"]["ok"]
    assert world.state == paid
    world.step(Action(tool="close_ticket", args={"ticket_id": ticket["id"], "resolution": "refunded"}))
    closed = copy.deepcopy(world.state)
    assert world.step(Action(tool="issue_refund", args=args))["result"]["ok"]
    assert world.state == closed
    world.step(Action(tool="finish"))
    assert world.evaluate().passed


@pytest.mark.parametrize("seed", [4, 5, 6, 7])
def test_ineligible_payment_and_forged_approval_arguments_leave_operational_state_unchanged(seed):
    world = make_environment("refund-ops", seed)
    ticket, order = world.target()
    args = {"order_id": order["id"], "amount_cents": ticket["requested_cents"]}
    before = copy.deepcopy(world.state)
    for action in (
        Action(tool="request_refund_approval", args=args),
        Action(tool="issue_refund", args={**args, "idempotency_key": "ineligible-payment"}),
        Action(tool="request_refund_approval", args={**args, "approved_by": "finance-reviewer"}),
    ):
        assert not world.step(action)["result"]["ok"]
        assert world.state == before
    assert world.tick == 3
    complete(world)


@pytest.mark.parametrize("corruption", ["request", "limit", "payment", "reviewer", "outsider", "history"])
def test_refund_forged_final_state_is_not_accepted(corruption):
    world = complete(make_environment("refund-ops", 3))
    if corruption == "request":
        world.state["tickets"][0]["requested_cents"] = 1
    elif corruption == "limit":
        world.state["approval_limit_cents"] = 1_000_000
    elif corruption == "payment":
        world.state["ledger"][-1]["amount_cents"] += 1
    elif corruption == "reviewer":
        world.state["approvals"][0]["approved_by"] = "agent"
    elif corruption == "outsider":
        world.state["orders"][1]["refunded_cents"] += 1
    else:
        world.state["ledger"][0]["amount_cents"] = 0
    assert not world.evaluate().passed
    assert world.evaluate().reward == 0


@pytest.mark.parametrize("seed,corruption", [(6, "exact"), (2, "reviewer"), (2, "amount"),
                                           (2, "outsider"), (2, "duplicate")])
def test_refund_approval_collection_cannot_bypass_trusted_final_state_grading(seed, corruption):
    world = complete(make_environment("refund-ops", seed))
    ticket, order = world.target()
    approval = {"order_id": order["id"], "amount_cents": ticket["requested_cents"], "approved_by": "finance-reviewer"}
    if corruption == "reviewer":
        approval["approved_by"] = "agent"
    elif corruption == "amount":
        approval["amount_cents"] -= 1
    elif corruption == "outsider":
        approval["order_id"] = world.state["orders"][1]["id"]
    world.state["approvals"].append(approval)
    if corruption == "duplicate":
        world.state["approvals"].append(copy.deepcopy(approval))
    assert world.evaluate().reward == 0
    assert not world.evaluate().passed


def test_voluntary_valid_approval_at_role_limit_remains_permitted():
    world = make_environment("refund-ops", 2)
    ticket, order = world.target()
    args = {"order_id": order["id"], "amount_cents": ticket["requested_cents"]}
    assert world.step(Action(tool="request_refund_approval", args=args))["result"]["ok"]
    before = copy.deepcopy(world.state)
    assert world.step(Action(tool="request_refund_approval", args=args))["result"]["ok"]
    assert world.state == before
    complete(world)
    assert len(world.state["approvals"]) == 1


def test_refund_unrelated_order_permutation_does_not_change_target_resolution():
    reference = complete(make_environment("refund-ops", 3))
    changed = make_environment("refund-ops", 3)
    state = changed.snapshot()["state"]
    state["orders"].append({**state["orders"][1], "id": 10000})
    state["orders"][1:] = reversed(state["orders"][1:])
    complete(fixture(changed, state))
    assert changed.target()[0] == reference.target()[0]
    assert changed.target()[1] == reference.target()[1]
    assert changed.state["orders"][1:] == changed.initial["orders"][1:]


@pytest.mark.parametrize("world_class", [CRMMerge, RefundOps])
async def test_version_changes_scenario_identity_but_not_seed_lineage_or_split(world_class, monkeypatch):
    config = RunConfig(environment_id=world_class.id, seed=42, evaluation_only=True)
    current = await rollout(config, 0)
    monkeypatch.setattr(world_class, "version", "1.0.0")
    prior_version_label = await rollout(config, 0)
    assert current["scenario_id"] != prior_version_label["scenario_id"]
    assert current["lineage_id"] == prior_version_label["lineage_id"]
    assert current["split"] == prior_version_label["split"]
    # This tests identity semantics, not reproduction of the historical generator.
    assert current["initial_snapshot"]["state"] == prior_version_label["initial_snapshot"]["state"]
