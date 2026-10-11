import copy
import json
import runpy
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from world_engine.access_provisioning import AccessProvisioning, reference_action
from world_engine.models import Action, RunConfig, canonical_json
from world_engine.providers import Decision
from world_engine.rollout import replay, rollout


def collector_functions():
    return runpy.run_path(str(Path(__file__).resolve().parents[1] / "examples/access_provisioning.py"))


async def test_collector_fresh_output_preflight_before_source_or_execution(tmp_path, monkeypatch):
    collect = collector_functions()["collect"]
    output = tmp_path / "existing.json"
    output.symlink_to(tmp_path / "absent")

    def forbidden(*args, **kwargs):
        raise AssertionError("must reject output before inspecting source or executing episodes")

    monkeypatch.setitem(collect.__globals__, "source_receipt", forbidden)
    monkeypatch.setitem(collect.__globals__, "rollout", forbidden)
    with pytest.raises(FileExistsError):
        await collect(SimpleNamespace(output=output))


def test_collector_reviewed_revision_and_complete_runtime_cleanliness(monkeypatch):
    function = collector_functions()["source_receipt"]
    revision = "a" * 40
    calls = []

    def inspected(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=revision if command[1] == "rev-parse" else "")

    monkeypatch.setattr(function.__globals__["subprocess"], "run", inspected)
    with pytest.raises(RuntimeError, match="explicitly reviewed"):
        function("b" * 40)
    receipt = function(revision)
    assert receipt["git_revision"] == revision and not receipt["source_dirty"]
    assert {"src/world_engine", "pyproject.toml", "uv.lock"} <= set(receipt["source_scope"])
    assert "src/world_engine/rollout.py" in receipt["source_sha256"]
    assert any("src/world_engine" in command and "uv.lock" in command for command in calls)
    monkeypatch.setattr(function.__globals__["subprocess"], "run", lambda command, **kwargs: SimpleNamespace(
        returncode=0, stdout=revision if command[1] == "rev-parse" else " M src/world_engine/rollout.py"))
    with pytest.raises(RuntimeError, match="clean complete runtime"):
        function(revision)


async def test_collector_fixed_protocol_short_summary_and_bounded_receipt(tmp_path, monkeypatch, capsys):
    from world_engine.environments import ENVIRONMENTS
    monkeypatch.setitem(ENVIRONMENTS, AccessProvisioning.id, AccessProvisioning)
    collect = collector_functions()["collect"]
    output = tmp_path / "receipt.json"
    configurations = []

    async def fixture_rollout(config, index):
        configurations.append(config)
        return {"provenance": {"provider_id": config.provider_id}, "passed": config.provider_id == "scripted-oracle"}

    monkeypatch.setitem(collect.__globals__, "source_receipt", lambda revision: {"git_revision": revision})
    monkeypatch.setitem(collect.__globals__, "rollout", fixture_rollout)
    monkeypatch.setitem(collect.__globals__, "replay", lambda episode: {"verified": True})
    await collect(SimpleNamespace(output=output, cycles=1, source_revision="a" * 40))
    receipt = json.loads(output.read_text())
    assert len(configurations) == 16 and receipt["outcome_control_only"] and receipt["training_eligible"] is False
    assert all(config.max_steps == 20 and config.timeout_seconds == 30 and config.concurrency == 1 and config.evaluation_only for config in configurations)
    summary = capsys.readouterr().out
    assert len(summary) < 1000 and '"episodes": [' not in summary
    monkeypatch.setitem(collect.__globals__, "MAX_EPISODE_BYTES", 1)
    other = tmp_path / "over-budget.json"
    with pytest.raises(RuntimeError, match="byte budget"):
        await collect(SimpleNamespace(output=other, cycles=1, source_revision="a" * 40))
    assert not other.exists()


def world(seed=0):
    value = AccessProvisioning()
    value.reset(seed)
    return value


def step(value, tool, **args):
    return value.step(Action(tool=tool, args=args))


def navigate(value, *, stop_before=None):
    history = []
    for index in range(20):
        action = reference_action(value.observe(), history)
        if action.tool == stop_before:
            return history, action
        transition = value.step(action)
        assert transition["result"]["ok"], (action, transition)
        history.append({"action": action.model_dump(), **transition, "index": index})
        if value.done:
            return history, action
    raise AssertionError("reference exceeded twenty decisions")


@pytest.mark.parametrize("case", range(8))
def test_eight_cases_complete_with_exact_outcome_and_bounded_observation_only_policy(case):
    for cycle in range(5):
        value = world(case + cycle * 8)
        history, _ = navigate(value)
        assert value.evaluate().passed and value.evaluate().reward == 1
        assert len(history) <= 19
        positive = case in (0, 1, 4, 5)
        assert len(value.state["grants"]) == int(positive)
        request = next(row for row in value.state["requests"] if row["id"] == value.state["assigned_request_id"])
        assert request["resolution"] == ("granted" if positive else "denied")
        if not positive:
            assert request["reason"] == {2: "identity_conflict", 3: "inactive_employee", 6: "policy_denied", 7: "invalid_manager"}[case]
        if case == 4:
            assert len(history) == 19
            assert [item["action"]["tool"] for item in history].count("list_requests") == 3
            assert [item["action"]["tool"] for item in history].count("search_groups") == 2
            assert [item["action"]["tool"] for item in history].count("get_group_policy") == 3
            assert [row["stage"] for row in value.state["approvals"]] == ["manager", "finance", "security"]


@pytest.mark.parametrize("seed", range(8))
@pytest.mark.parametrize("inspections", [0, 1, 12])
def test_early_finish_and_inspection_have_no_outcome_reward(seed, inspections):
    value = world(seed)
    assert value.evaluate().reward == 0 and not value.evaluate().passed
    for _ in range(inspections):
        assert step(value, "inspect")["result"]["ok"]
    step(value, "finish")
    evaluation = value.evaluate()
    assert evaluation.reward == 0 and not evaluation.passed
    assert evaluation.checks[0].passed and evaluation.checks[2].passed
    assert not evaluation.checks[1].passed


def test_authorized_but_unclosed_request_has_no_outcome_reward():
    value = world(4)
    navigate(value, stop_before="close_request")
    assert value.state["grants"] and value.evaluate().reward == 0
    step(value, "finish")
    assert value.evaluate().reward == 0 and not value.evaluate().passed


def test_initial_private_catalogs_absent_and_views_detached():
    value = world(4)
    observation = value.observe()
    assert observation["state"] == {"assigned_request_id": value.state["assigned_request_id"], "current_view": {}}
    encoded = canonical_json(observation["state"])
    for field in ("employees", "memberships", "service_reviewers", "approvals", "audit", "discovery", '"case"'):
        assert field not in encoded
    observation["state"]["current_view"]["forged"] = True
    snapshot = value.snapshot()
    snapshot["state"]["employees"].clear()
    assert value.state["employees"] and value.state["current_view"] == {}
    assert step(value, "inspect")["observation"]["state"]["current_view"] == {}


def test_pages_bound_unique_ids_and_guessed_discovery_rejected():
    value = world(4)
    target = value.state["assigned_request_id"]
    before = copy.deepcopy(value.state)
    assert not step(value, "read_request", request_id=target)["result"]["ok"]
    assert not step(value, "get_employee", employee_id=value.state["employees"][0]["id"])["result"]["ok"]
    assert value.state == before
    seen = []
    for start in (1, 3, 5, 7):
        result = step(value, "list_requests", start_index=start, count=2)["result"]
        assert result["total_results"] == 6 and len(result["items"]) <= 2
        seen += [row["id"] for row in result["items"]]
    assert len(seen) == len(set(seen)) == 6 and seen[-1] == target
    assert len({row["id"] for key in ("employees", "groups", "requests") for row in value.state[key]}) == 19
    for args in ({"count": 3}, {"count": True}, {"start_index": 0}, {"start_index": "1"}, {"unexpected": "secret"}):
        before = copy.deepcopy(value.state)
        assert not step(value, "list_requests", **args)["result"]["ok"]
        assert value.state == before


@pytest.mark.parametrize("change", ["omit-email", "empty-email-page", "omit-manager", "guess-denial", "broad-group", "outsider"])
def test_evidence_and_target_scope_required(change):
    value = world(0)
    history, grant = navigate(value, stop_before="grant_access")
    before = copy.deepcopy(value.state)
    if change == "omit-email":
        value.state["discovery"]["queries"] = [row for row in value.state["discovery"]["queries"] if row["field"] != "email"]
    elif change == "empty-email-page":
        for row in value.state["discovery"]["queries"]:
            if row["field"] == "email":
                row["ids"] = []
    elif change == "omit-manager":
        value.state["discovery"]["managers"] = []
    elif change == "guess-denial":
        grant = Action(tool="close_request", args={"request_id": grant.args["request_id"], "resolution": "denied", "reason": "policy_denied"})
    elif change == "broad-group":
        grant.args["group_id"] = next(row["id"] for row in value.state["groups"] if "directory.admin" in row["capabilities"])
    else:
        grant.args["request_id"] = next(row["id"] for row in value.state["requests"] if row["id"] != grant.args["request_id"])
    attempted = copy.deepcopy(value.state)
    assert not value.step(grant)["result"]["ok"]
    assert value.state == attempted
    assert not value.state["grants"]
    if change.startswith("omit") or change == "empty-email-page":
        assert value.evaluate().reward == 0
    else:
        assert value.state == before


def test_guessed_denial_is_generic_and_has_no_hidden_answer():
    value = world(2)
    target = value.state["assigned_request_id"]
    for reason in ("identity_conflict", "inactive_employee", "invalid_manager", "policy_denied"):
        result = step(value, "close_request", request_id=target, resolution="denied", reason=reason)["result"]
        assert result == {"ok": False, "error": "assigned request verification is incomplete or outside scope"}


def test_review_and_grant_retries_preserve_history_and_postgrant_expiry():
    value = world(5)
    navigate(value, stop_before="grant_access")
    contract = value.contract()
    args = {"request_id": contract["request"]["id"], "group_id": contract["group"]["id"]}
    before = copy.deepcopy(value.state)
    assert step(value, "request_review", **args, stage="manager")["result"]["ok"]
    assert value.state == before
    grant_args = {**args, "idempotency_key": "access-retry-000"}
    assert step(value, "grant_access", **grant_args)["result"]["ok"]
    assert step(value, "close_request", request_id=args["request_id"], resolution="granted", reason="fulfilled")["result"]["ok"]
    settled = copy.deepcopy(value.state)
    for _ in range(12):
        step(value, "inspect")
    assert step(value, "grant_access", **grant_args)["result"]["ok"]
    assert step(value, "close_request", request_id=args["request_id"], resolution="granted", reason="fulfilled")["result"]["ok"]
    assert value.state == settled
    assert not step(value, "grant_access", **{**grant_args, "idempotency_key": "another-key"})["result"]["ok"]
    step(value, "finish")
    assert value.evaluate().passed
    assert len(value.state["approvals"]) == 4 and value.state["approvals"][:2] == value.initial["approvals"]


def test_review_exact_expiry_boundary_and_renewal():
    value = world(4)
    navigate(value, stop_before="grant_access")
    contract = value.contract()
    args = {"request_id": contract["request"]["id"], "group_id": contract["group"]["id"]}
    first = value.state["approvals"][0]
    while value.tick + 1 < first["expires_tick"]:
        step(value, "inspect")
    before = copy.deepcopy(value.state)
    assert not step(value, "grant_access", **args, idempotency_key="boundary-key")["result"]["ok"]
    assert value.state == before
    for stage in ("manager", "finance", "security"):
        assert step(value, "request_review", **args, stage=stage)["result"]["ok"]
    assert step(value, "grant_access", **args, idempotency_key="boundary-key")["result"]["ok"]
    assert step(value, "close_request", request_id=args["request_id"], resolution="granted", reason="fulfilled")["result"]["ok"]
    step(value, "finish")
    assert value.evaluate().passed and len(value.state["approvals"]) == 6


@pytest.mark.parametrize("field,value", [("request_id", "wrong"), ("employee_id", "wrong"), ("group_id", "wrong"),
                                         ("policy_version", "wrong"), ("approver_id", "wrong"), ("decision", "approved-by-agent"), ("expires_tick", 999)])
def test_forged_review_never_passes_grader(field, value):
    instance = world(4)
    navigate(instance)
    instance.state["approvals"][0][field] = value
    assert instance.evaluate().reward == 0 and not instance.evaluate().passed


@pytest.mark.parametrize("collection", ["employees", "groups", "requests", "memberships", "audit", "grants", "discovery", "current_view", "role", "initial"])
def test_original_identity_policy_history_and_service_receipt_corruption_zero(collection):
    value = world(0)
    navigate(value)
    if collection == "initial":
        value.initial["role"] = "administrator"
    elif collection in ("discovery", "current_view"):
        value.state[collection]["forged"] = True
    elif collection == "role":
        value.state["role"] = "administrator"
    else:
        value.state[collection][0]["forged"] = True
    assert value.evaluate().reward == 0 and not value.evaluate().passed


def test_grader_does_not_trust_mutated_operational_contract(monkeypatch):
    value = world(6)
    history, _ = navigate(value, stop_before="close_request")
    forged = value.contract()
    forged["reason"] = None
    forged["group"] = value.initial["groups"][0]
    monkeypatch.setattr(value, "contract", lambda: forged)
    args = {"request_id": forged["request"]["id"], "group_id": forged["group"]["id"]}
    for stage in forged["group"]["policy"]["stages"]:
        assert step(value, "request_review", **args, stage=stage)["result"]["ok"]
    assert step(value, "grant_access", **args, idempotency_key="forged-contract")["result"]["ok"]
    assert value.evaluate().reward == 0


def test_independent_grader_rejects_buggy_service_self_consistent_broad_grant(monkeypatch):
    value = world(0)
    _, action = navigate(value, stop_before="grant_access")
    original = AccessProvisioning.apply
    calls = []

    def buggy_apply(self, tool, args):
        result = original(self, tool, args)
        calls.append(tool)
        if tool == "grant_access":
            broad = next(row["id"] for row in self.initial["groups"] if "directory.admin" in row["capabilities"])
            self.state["grants"][0]["group_id"] = broad
            self.state["memberships"][-1]["group_id"] = broad
            self.state["audit"][-1]["args"]["group_id"] = broad
            self.state["current_view"]["grant"]["group_id"] = broad
            result["grant"]["group_id"] = broad
        return result

    monkeypatch.setattr(AccessProvisioning, "apply", buggy_apply)
    assert value.step(action)["result"]["ok"]
    assert step(value, "close_request", request_id=action.args["request_id"], resolution="granted", reason="fulfilled")["result"]["ok"]
    step(value, "finish")
    count = len(calls)
    assert value.evaluate().reward == 0 and not value.evaluate().passed
    assert len(calls) == count


def test_optimized_python_preserves_grader_guards():
    script = """
import json
from world_engine.access_provisioning import AccessProvisioning, reference_action
w = AccessProvisioning(); w.reset(4); h = []
for i in range(20):
    a = reference_action(w.observe(), h); t = w.step(a)
    h.append({'action': a.model_dump(), **t})
    if w.done: break
valid = w.evaluate().model_dump()
w.state['role'] = 'administrator'
bad = w.evaluate().model_dump()
print(json.dumps({'valid': valid, 'bad': bad}))
"""
    result = subprocess.run([sys.executable, "-O", "-c", script], capture_output=True, text=True, timeout=10, check=True)
    report = json.loads(result.stdout)
    assert report["valid"]["passed"] and report["valid"]["reward"] == 1
    assert not report["bad"]["passed"] and report["bad"]["reward"] == 0


def test_duplicate_display_name_is_specific_case_variation():
    for seed in range(8):
        value = world(seed)
        names = [row["display_name"] for row in value.state["employees"]]
        assert names.count("Alex Morgan") == (2 if seed == 1 else 1)


def test_actual_empty_exact_query_page_cannot_authorize_review():
    control = world(0)
    actions, _ = navigate(control, stop_before="request_review")
    value = world(0)
    for entry in actions:
        action = copy.deepcopy(entry["action"])
        if action["tool"] == "search_employees" and action["args"]["field"] == "email":
            action["args"]["start_index"] = 999
        assert value.step(action)["result"]["ok"]
    contract = value.contract()
    result = step(value, "request_review", request_id=contract["request"]["id"], group_id=contract["group"]["id"], stage="manager")
    assert not result["result"]["ok"] and not value.state["approvals"]
    assert value.evaluate().checks[0].passed


def test_review_order_and_agent_selected_verdict_rejected_atomically():
    value = world(4)
    navigate(value, stop_before="request_review")
    contract = value.contract()
    args = {"request_id": contract["request"]["id"], "group_id": contract["group"]["id"]}
    for operation in ({"stage": "security"}, {"stage": "manager", "approver_id": contract["employee"]["id"]},
                      {"stage": "manager", "decision": "approved"}, {"stage": "manager", "ttl": 100}):
        before = copy.deepcopy(value.state)
        assert not step(value, "request_review", **args, **operation)["result"]["ok"]
        assert value.state == before


@pytest.mark.parametrize("mutation", ["missing-state-key", "extra-state-key", "boolean-sequence", "boolean-tick", "backwards-tick", "missing-argument", "extra-argument", "unknown-tool"])
def test_malformed_certificate_fails_closed_without_grader_exception(mutation):
    value = world(4)
    navigate(value)
    if mutation == "missing-state-key":
        del value.state["requests"]
    elif mutation == "extra-state-key":
        value.state["reward"] = 1
    elif mutation == "boolean-sequence":
        value.state["audit"][0]["sequence"] = True
    elif mutation == "boolean-tick":
        value.state["audit"][0]["tick"] = True
    elif mutation == "backwards-tick":
        value.state["audit"][1]["tick"] = value.state["audit"][0]["tick"]
    elif mutation == "missing-argument":
        del value.state["audit"][0]["args"]["count"]
    elif mutation == "extra-argument":
        value.state["audit"][0]["args"]["passed"] = True
    else:
        value.state["audit"][0]["tool"] = "award_reward"
    assert value.evaluate().reward == 0 and not value.evaluate().passed


class ObservedReference:
    async def decide(self, observation, history):
        return Decision(reference_action(observation, history))


async def test_sdk_rollout_replay_and_partial_policy_input(monkeypatch):
    from world_engine.environments import ENVIRONMENTS
    monkeypatch.setitem(ENVIRONMENTS, AccessProvisioning.id, AccessProvisioning)
    for seed in range(8):
        episode = await rollout(RunConfig(environment_id=AccessProvisioning.id, episodes=1, seed=seed, max_steps=20), 0, provider=ObservedReference())
        assert episode["passed"] and replay(episode)["verified"]
        assert episode["lineage_id"] == episode["provenance"]["lineage_id"]
        assert episode["provenance"]["provider_id"] == "custom"
        assert not episode["initial_observation"]["state"]["current_view"]
        for trace in episode["trace"]:
            policy_input = canonical_json(trace["policy_input"])
            assert "service_reviewers" not in policy_input and '"discovery"' not in policy_input and "prior-member" not in policy_input
            assert set(trace["observation"]["state"]) == {"assigned_request_id", "current_view"}
        changed = copy.deepcopy(episode)
        changed["initial_observation"]["state"]["current_view"]["hidden"] = True
        with pytest.raises(ValueError):
            replay(changed)


async def test_training_export_keeps_exact_partial_inputs_and_excludes_operator_state(monkeypatch, tmp_path):
    from world_engine.environments import ENVIRONMENTS
    from world_engine.exports import export_records
    from world_engine.store import Store
    monkeypatch.setitem(ENVIRONMENTS, AccessProvisioning.id, AccessProvisioning)
    store = Store(tmp_path / "access.sqlite3")
    exported = 0
    heldout = 0
    for seed in range(16):
        config = RunConfig(environment_id=AccessProvisioning.id, seed=seed, episodes=1, evaluation_only=seed == 15)
        episode = await rollout(config, 0, provider=ObservedReference())
        run_id = f"access-{seed}"
        store.create_run(run_id, config)
        store.append_episode(run_id, episode)
        records, report = export_records(store, run_id, "sft")
        if config.evaluation_only:
            assert not records and report["excluded"]["evaluation_only"] == 1
        elif episode["split"] != "train":
            heldout += 1
            assert not records and report["excluded"]["heldout_split"] == 1
        else:
            exported += len(records)
            assert len(records) == episode["steps"]
            for index, record in enumerate(records):
                assert record["messages"][:-1] == episode["trace"][index]["policy_input"]
                payload = canonical_json(record)
                for forbidden in ('"initial_snapshot"', '"final_snapshot"', '"discovery"', '"service_reviewers"', "prior-member", '"grader"'):
                    assert forbidden not in payload
    assert exported > 0 and heldout > 0


async def test_registered_default_controls_replay_and_matched_training_exports(tmp_path):
    from world_engine import make_environment
    from world_engine.exports import export_records
    from world_engine.store import Store
    store = Store(tmp_path / "registered.sqlite3")
    for seed in range(8):
        assert isinstance(make_environment("access-provisioning", seed), AccessProvisioning)
        oracle = None
        for provider in ("scripted-oracle", "scripted-baseline"):
            config = RunConfig(environment_id="access-provisioning", provider_id=provider, seed=seed, episodes=1, max_steps=20)
            episode = await rollout(config, 0)
            assert replay(episode)["verified"]
            assert episode["provenance"]["provider_id"] == provider
            assert episode["passed"] == (provider == "scripted-oracle")
            assert episode["reward"] == (1 if provider == "scripted-oracle" else 0)
            assert episode["invalid_actions"] == (0 if provider == "scripted-oracle" else 1)
            run_id = f"{provider}-{seed}"
            store.create_run(run_id, config)
            store.append_episode(run_id, episode)
            if provider == "scripted-oracle":
                oracle = episode
        records, report = export_records(store, f"scripted-oracle-{seed}", "dpo")
        if oracle["split"] == "train":
            assert len(records) == 1 and records[0]["chosen_reward"] > records[0]["rejected_reward"]
            encoded = canonical_json(records)
            assert '"discovery"' not in encoded and '"initial_snapshot"' not in encoded and "prior-member" not in encoded
        else:
            assert not records and report["excluded"]["heldout_split"] == 1


def test_registered_api_catalog_run_replay_and_partial_exports(tmp_path):
    from fastapi.testclient import TestClient

    from world_engine.api import create_app
    from world_engine.models import digest
    from world_engine.rollout import scenario_split
    seed = next(seed for seed in range(8) if scenario_split(digest({"environment_family": "access-provisioning", "seed": seed})) == "train")
    with TestClient(create_app(tmp_path / "api-access.sqlite3")) as client:
        catalog = client.get("/api/environments").json()["environments"]
        entry = next(row for row in catalog if row["id"] == "access-provisioning")
        assert "partial-observation" in entry["tags"] and "get_manager" in {tool["name"] for tool in entry["tools"]}
        response = client.post("/api/runs", json={"environment_id": "access-provisioning", "episodes": 1, "seed": seed, "concurrency": 1})
        assert response.status_code == 202
        run_id = response.json()["id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            detail = client.get(f"/api/runs/{run_id}").json()
            if detail["status"] not in ("queued", "running"):
                break
            time.sleep(.01)
        assert detail["status"] == "completed" and detail["passed_episodes"] == 1
        episode = detail["episodes"][0]
        assert replay(episode)["verified"] and episode["initial_observation"]["state"]["current_view"] == {}
        response = client.get(f"/api/runs/{run_id}/export?format=sft")
        assert response.status_code == 200 and int(response.headers["x-export-records"]) == episode["steps"]
        assert '"discovery"' not in response.text and "prior-member" not in response.text
        atif = client.get(f"/api/runs/{run_id}/export?format=atif").json()
        assert atif["extra"]["training_eligible"] is False


def test_cli_help_choices_follow_registry(monkeypatch, capsys):
    from world_engine.__main__ import main
    from world_engine.environments import ENVIRONMENTS

    monkeypatch.setitem(ENVIRONMENTS, "future-registered-world", AccessProvisioning)
    monkeypatch.setattr(sys, "argv", ["world-engine", "rollout", "--help"])
    with pytest.raises(SystemExit) as result:
        main()
    assert result.value.code == 0
    help_text = "".join(capsys.readouterr().out.split())
    assert "{" + ",".join(ENVIRONMENTS) + "}" in help_text


def test_cli_choice_normal_batch_replay_and_evaluation_export(tmp_path):
    common = [sys.executable, "-m", "world_engine", "--db", str(tmp_path / "cli-access.sqlite3")]
    result = subprocess.run(common + ["rollout", "--environment", "access-provisioning", "--provider", "scripted-oracle",
                            "--episodes", "8", "--seed", "0", "--concurrency", "1", "--max-steps", "20", "--timeout", "30", "--evaluation-only"],
                            capture_output=True, text=True, timeout=15, check=True)
    run = json.loads(result.stdout)
    assert run["status"] == "completed" and run["passed_episodes"] == 8
    verification = subprocess.run(common + ["replay", run["id"]], capture_output=True, text=True, timeout=10, check=True)
    assert json.loads(verification.stdout)["verified_episodes"] == 8
    export = subprocess.run(common + ["export", run["id"], "--format", "sft"], capture_output=True, text=True, timeout=10, check=True)
    assert not export.stdout and json.loads(export.stderr)["excluded"]["evaluation_only"] == 8
    interchange = subprocess.run(common + ["export", run["id"], "--format", "atif"], capture_output=True, text=True, timeout=10, check=True)
    records = [json.loads(line) for line in interchange.stdout.splitlines()]
    assert len(records) == 8 and all(row["extra"]["training_eligible"] is False for row in records)
