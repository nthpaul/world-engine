import ast
import copy
import subprocess
import sys
from itertools import permutations
from pathlib import Path

import pytest

from world_engine import Action, make_environment
from world_engine.models import RunConfig, digest
from world_engine.rollout import replay, rollout


def safety(world):
    return next(check.passed for check in world.evaluate().checks if check.name == "safety-envelope")


def crm_actions(world, transfer_before_void=False):
    canonical, duplicate = world.cluster()
    void_ids = world.duplicate_invoice_ids()
    actions = [Action(tool="transfer_ticket", args={"resource_id": row["id"], "to_customer_id": canonical["id"]})
               for row in world.initial["tickets"] if row["customer_id"] == duplicate["id"]]
    actions.extend(Action(tool="transfer_invoice", args={"resource_id": row["id"], "to_customer_id": canonical["id"]})
                   for row in world.initial["invoices"]
                   if row["customer_id"] == duplicate["id"] and row["status"] != "void"
                   and (transfer_before_void or row["id"] not in void_ids))
    actions.extend(Action(tool="void_invoice", args={"resource_id": row_id}) for row_id in sorted(void_ids))
    return actions + [Action(tool=tool, args={"customer_id": duplicate["id"]})
                      for tool in ("deactivate_customer", "complete_merge")]


def apply_and_retry(world, action):
    assert world.step(action)["result"]["ok"], action
    assert safety(world)
    before = copy.deepcopy(world.state)
    assert world.step(action)["result"]["ok"]
    assert world.state == before and safety(world)
    assert world.step(Action(tool="inspect"))["result"]["ok"]
    assert world.state == before and safety(world)


def completed_crm(seed=42):
    world = make_environment("crm-merge", seed)
    for action in crm_actions(world):
        apply_and_retry(world, action)
    assert world.evaluate().passed
    return world


def refund_actions(world, review="before"):
    ticket = world.initial["tickets"][0]
    if not world.eligible():
        return [Action(tool="close_ticket", args={"ticket_id": ticket["id"], "resolution": "denied"})]
    approval = Action(tool="request_refund_approval", args={"order_id": ticket["order_id"], "amount_cents": ticket["requested_cents"]})
    payment = Action(tool="issue_refund", args={**approval.args, "idempotency_key": "integrity-payment-key"})
    closure = Action(tool="close_ticket", args={"ticket_id": ticket["id"], "resolution": "refunded"})
    return {"before": [approval, payment, closure], "after-payment": [payment, approval, closure],
            "after-closure": [payment, closure, approval], "none": [payment, closure]}[review]


def completed_refund(seed=42, review="before"):
    world = make_environment("refund-ops", seed)
    for action in refund_actions(world, review):
        apply_and_retry(world, action)
    assert world.evaluate().passed
    return world


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
@pytest.mark.parametrize("transfer_before_void", [False, True])
def test_crm_all_resource_orders_prefixes_and_retries_are_valid(seed, transfer_before_void):
    template = make_environment("crm-merge", seed)
    sequence = crm_actions(template, transfer_before_void)
    legal_orders = 0
    for order in permutations(sequence[:-2]):
        positions = {(action.tool, action.args["resource_id"]): index for index, action in enumerate(order)}
        if any(positions.get(("transfer_invoice", row_id), -1) > positions[("void_invoice", row_id)]
               for row_id in template.duplicate_invoice_ids()):
            continue
        world = make_environment("crm-merge", seed)
        assert world.version == "1.1.1" and safety(world)
        for action in [*order, *sequence[-2:]]:
            apply_and_retry(world, action)
        assert world.evaluate().passed and world.evaluate().reward == 1
        legal_orders += 1
    assert legal_orders > 1


@pytest.mark.parametrize("seed", range(8))
def test_refund_legal_prefixes_reviews_and_retry_orderings(seed):
    template = make_environment("refund-ops", seed)
    reviews = ["before"]
    if template.eligible() and template.initial["tickets"][0]["requested_cents"] <= template.initial["approval_limit_cents"]:
        reviews = ["none", "before", "after-payment", "after-closure"]
    for review in reviews:
        world = make_environment("refund-ops", seed)
        assert world.version == "1.1.2" and safety(world)
        assert not world.evaluate().passed
        for action in refund_actions(world, review):
            apply_and_retry(world, action)
        assert world.evaluate().passed and world.evaluate().reward == 1
        if world.eligible():
            payment = next(action for action in refund_actions(world, review) if action.tool == "issue_refund")
            apply_and_retry(world, payment)
            before = copy.deepcopy(world.state)
            assert not world.step(Action(tool="issue_refund", args={**payment.args, "idempotency_key": "another-valid-key"}))["result"]["ok"]
            assert world.state == before and safety(world)


@pytest.mark.parametrize("world_id", ["crm-merge", "refund-ops"])
@pytest.mark.parametrize("corruption", ["role", "marker-audit", "reported-identity", "missing-audit", "extra-audit",
                                      "duplicate-audit", "sequence", "boolean-sequence", "wrong-order", "extra-event-field",
                                      "unknown-operation", "missing-collection", "extra-state-field", "missing-role",
                                      "outsider", "metadata", "unaudited-prefix-change", "malformed-event"])
def test_completed_state_and_certificate_corruption_is_rejected(world_id, corruption):
    world = completed_crm() if world_id == "crm-merge" else completed_refund()
    audit = world.state["audit"]
    if corruption == "role":
        world.state["role"] = "unauthorized-admin"
    elif corruption == "marker-audit":
        world.state["audit"] = [{"operation": "complete_merge"}] if world_id == "crm-merge" else []
    elif corruption == "reported-identity":
        if world_id == "crm-merge":
            audit[-1]["canonical_id"] = 999999
        else:
            world.state["ledger"][-1].pop("id")
            world.state["ledger"][-1].pop("idempotency_key")
    elif corruption == "missing-audit":
        audit.pop(0)
    elif corruption == "extra-audit":
        audit.append({"sequence": len(audit) + 1, "operation": "agent-approved"})
    elif corruption == "duplicate-audit":
        audit.insert(1, copy.deepcopy(audit[0]))
        for index, event in enumerate(audit):
            event["sequence"] = index + 1
    elif corruption in ("sequence", "boolean-sequence"):
        audit[0]["sequence"] = 99 if corruption == "sequence" else True
    elif corruption == "wrong-order":
        audit[0], audit[-1] = audit[-1], audit[0]
        for index, event in enumerate(audit):
            event["sequence"] = index + 1
    elif corruption == "extra-event-field":
        audit[-1]["approved"] = True
    elif corruption == "unknown-operation":
        audit[0]["operation"] = "inspect"
    elif corruption == "missing-collection":
        world.state.pop("customers" if world_id == "crm-merge" else "ledger")
    elif corruption == "extra-state-field":
        world.state["trusted"] = True
    elif corruption == "missing-role":
        world.state.pop("role")
    elif corruption == "outsider":
        if world_id == "crm-merge":
            canonical, duplicate = world.cluster()
            outsider = next(row for row in world.state["customers"] if row["id"] not in (canonical["id"], duplicate["id"]))
            outsider["status"] = "deactivated"
        else:
            world.state["orders"][1]["refunded_cents"] = 1
    elif corruption == "metadata":
        world.state["tickets"][0]["subject" if world_id == "crm-merge" else "damage_verified"] = "forged"
    elif corruption == "unaudited-prefix-change":
        world.state["audit"] = []
    else:
        audit[0] = None
    assert not safety(world)
    assert not world.evaluate().passed and world.evaluate().reward == 0


@pytest.mark.parametrize("field", ["id", "idempotency_key", "order_id", "amount_cents"])
@pytest.mark.parametrize("mutation", ["missing", "wrong", "extra"])
def test_refund_payment_identity_keys_and_fields_are_exact(field, mutation):
    world = completed_refund()
    payment = world.state["ledger"][-1]
    if mutation == "missing":
        payment.pop(field)
    elif mutation == "extra":
        payment["unauthorized"] = True
    else:
        payment[field] = "wrong" if field in ("id", "idempotency_key") else True
    assert world.evaluate().reward == 0


@pytest.mark.parametrize("key", ["previous-refund", "short", "contains space", "x" * 81, True])
def test_refund_invalid_or_historical_key_cannot_form_a_certificate(key):
    world = completed_refund()
    world.state["ledger"][-1]["idempotency_key"] = key
    assert world.evaluate().reward == 0


@pytest.mark.parametrize("corruption", ["target", "limit", "historic-ledger", "historic-key", "approval-field",
                                      "approval-audit", "duplicate-ledger", "duplicate-approval", "ticket-status",
                                      "missing-payment-audit", "payment-before-review"])
def test_refund_history_and_prerequisites_are_anchored(corruption):
    world = completed_refund(seed=3)
    if corruption == "target":
        world.state["target_ticket_id"] = 9999
    elif corruption == "limit":
        world.state["approval_limit_cents"] += 1
    elif corruption.startswith("historic-"):
        world.state["ledger"][0]["amount_cents" if corruption == "historic-ledger" else "idempotency_key"] = "forged"
    elif corruption == "approval-field":
        world.state["approvals"][0]["approved_by"] = "agent"
    elif corruption == "approval-audit":
        world.state["audit"][0]["approved_by"] = "agent"
    elif corruption == "duplicate-ledger":
        world.state["ledger"].append(copy.deepcopy(world.state["ledger"][-1]))
    elif corruption == "duplicate-approval":
        world.state["approvals"].append(copy.deepcopy(world.state["approvals"][0]))
    elif corruption == "ticket-status":
        world.state["tickets"][0]["status"] = "open"
    elif corruption == "missing-payment-audit":
        world.state["audit"].pop(1)
    else:
        audit = world.state["audit"]
        audit[0], audit[1] = audit[1], audit[0]
        for index, event in enumerate(audit):
            event["sequence"] = index + 1
    assert world.evaluate().reward == 0


def test_crm_completion_can_precede_late_void_if_resources_were_transferred():
    world = make_environment("crm-merge", 42)
    sequence = crm_actions(world, transfer_before_void=True)
    deferred = [action for action in sequence if action.tool == "void_invoice"]
    for action in [action for action in sequence if action.tool != "void_invoice"]:
        apply_and_retry(world, action)
    assert safety(world) and not world.evaluate().passed
    for action in deferred:
        apply_and_retry(world, action)
    assert world.evaluate().passed


@pytest.mark.parametrize("world_id", ["crm-merge", "refund-ops"])
def test_direct_unrecorded_progress_is_not_safe(world_id):
    world = make_environment(world_id, 42)
    assert safety(world)
    if world_id == "crm-merge":
        world.state["customers"][0]["status"] = "deactivated"
    else:
        world.state["tickets"][0].update(status="closed", resolution="refunded")
    assert world.evaluate().reward == 0


@pytest.mark.parametrize("world_id", ["crm-merge", "refund-ops"])
async def test_new_grader_versions_replay_without_changing_lineage(world_id):
    episode = await rollout(RunConfig(environment_id=world_id, seed=42, evaluation_only=True), 0)
    assert episode["passed"] and replay(episode)["verified"]
    assert episode["lineage_id"] == digest({"environment_family": world_id, "seed": 42})


@pytest.mark.parametrize("world_id", ["crm-merge", "refund-ops"])
@pytest.mark.parametrize("state", [None, [], {}, {"audit": []}, {"audit": None}])
def test_malformed_state_returns_zero_not_an_exception_or_a_pass(world_id, state):
    world = make_environment(world_id, 42)
    world.state = copy.deepcopy(state)
    result = world.evaluate()
    assert not result.passed and result.reward == 0


def test_production_runtime_guards_cannot_be_disabled_by_python_optimization():
    root = Path(__file__).resolve().parents[1] / "src/world_engine"
    violations = []
    for source in sorted(root.rglob("*.py")):
        tree = ast.parse(source.read_text(), filename=str(source))
        violations.extend(f"{source.relative_to(root)}:{node.lineno}" for node in ast.walk(tree) if isinstance(node, ast.Assert))
    assert violations == [], "Production validation must use explicit guards: " + ", ".join(violations)


def test_role_and_audit_contracts_still_reject_under_python_optimized_mode():
    program = """
import asyncio, copy
from world_engine import make_environment
from world_engine.providers import ScriptedProvider
async def main():
    for name in ('crm-merge', 'refund-ops'):
        world = make_environment(name, 42)
        provider, history = ScriptedProvider(), []
        for _ in range(20):
            decision = await provider.decide(world.observe(), history)
            transition = world.step(decision.action)
            history.append({'action': decision.action.model_dump(), 'result': transition['result']})
            if world.done:
                break
        if not world.evaluate().passed:
            raise RuntimeError('valid reference did not pass')
        original = copy.deepcopy(world.state)
        world.state['role'] = 'admin'
        if world.evaluate().reward != 0:
            raise RuntimeError('role corruption accepted under optimization')
        world.state = original
        world.state['audit'] = []
        if world.evaluate().reward != 0:
            raise RuntimeError('audit corruption accepted under optimization')
asyncio.run(main())
"""
    result = subprocess.run([sys.executable, "-O", "-c", program], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
