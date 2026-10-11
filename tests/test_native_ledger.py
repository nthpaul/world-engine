import copy
import json
import traceback

import pytest

from world_engine import make_environment, provider_records
from world_engine.models import Action, canonical_json
from world_engine.native_ledger import (
    MAX_HISTORY,
    MAX_JSON_DEPTH,
    MAX_JSON_NODES,
    PROTOCOL,
    LedgerError,
    contract,
    reconstruct,
    request_body,
    request_from_context,
)
from world_engine.ollama_tools import LEDGER_PROTOCOL, OPTIONS, SYSTEM_PROMPT
from world_engine.ollama_tools import contract as native_v1_contract
from world_engine.providers import ScriptedProvider, policy_messages

MODEL = "qwen3:8b"
WORLDS = ("crm-merge", "refund-ops", "incident-control", "access-provisioning")


def small_observation():
    return {"environment_id": "fixture", "version": "1", "task": "Inspect then finish.",
            "role": "operator", "state": {"value": 0}, "tick": 0, "done": False,
            "tools": [{"name": "inspect", "description": "Read public state.",
                       "args_schema": {"type": "object", "properties": {}}}]}


def one_step(*, rejected=False):
    initial = small_observation()
    observation = copy.deepcopy(initial)
    observation["tick"] = 1
    step = {"index": 0, "action": {"tool": "inspect", "args": {}},
            "result": {"ok": not rejected, "message": "fixture result"}, "observation": observation,
            "policy_input": policy_messages(initial, [])}
    return initial, observation, [step]


@pytest.mark.parametrize("environment_id", WORLDS)
@pytest.mark.parametrize("seed", [0, 7])
async def test_reference_flow_exact_prefix_and_reconstruction(environment_id, seed):
    world = make_environment(environment_id, seed)
    initial = world.observe()
    history = []
    prior = None
    provider = ScriptedProvider()
    for _ in range(20):
        current = world.observe()
        body = request_body(MODEL, initial, current, history)
        assert body == request_from_context(MODEL, current, history)
        restored = reconstruct(body)
        assert canonical_json(restored["initial_observation"]) == canonical_json(initial)
        assert canonical_json(restored["observation"]) == canonical_json(current)
        assert restored["history"] == [{key: step[key] for key in ("index", "action", "result", "observation")}
                                       for step in history]
        assert request_body(MODEL, restored["initial_observation"], restored["observation"], restored["history"]) == body
        assert body["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
        assert body["options"] == OPTIONS and not body["think"] and not body["stream"]
        assert len(canonical_json(body).encode()) <= provider_records.MAX_REQUEST_BYTES
        lines = body["messages"][1]["content"].split("\n")
        assert len(lines) == len(history) + 1
        assert "tools" not in json.loads(lines[0])["initial_observation"]
        assert all(set(json.loads(line)["observation"]) == set(initial) - {"environment_id", "version", "task", "tools"}
                   for line in lines[1:])
        if prior is not None:
            assert body["messages"][1]["content"].startswith(prior["messages"][1]["content"] + "\n")
            assert {key: value for key, value in body.items() if key != "messages"} == {
                key: value for key, value in prior.items() if key != "messages"}
        context = policy_messages(current, history)
        action = (await provider.decide(current, history)).action
        transition = world.step(action)
        history.append({"index": len(history), "action": action.model_dump(), "result": transition["result"],
                        "observation": transition["observation"], "policy_input": context})
        prior = body
        if world.done:
            assert world.evaluate().passed
            with pytest.raises(LedgerError, match="after finish"):
                request_body(MODEL, initial, world.observe(), history)
            break
    else:
        pytest.fail("reference flow exceeded 20 decisions")


@pytest.mark.parametrize("environment_id", WORLDS)
def test_rejected_action_is_preserved_with_unchanged_public_state(environment_id):
    world = make_environment(environment_id, 0)
    initial = world.observe()
    action = Action(tool="unavailable_tool", args={})
    result = world.step(action)
    assert not result["result"]["ok"]
    history = [{"index": 0, "action": action.model_dump(), "result": result["result"],
                "observation": result["observation"], "policy_input": policy_messages(initial, [])}]
    restored = reconstruct(request_from_context(MODEL, world.observe(), history))
    assert restored["history"][0]["result"] == result["result"]
    assert restored["history"][0]["observation"] == world.observe()


@pytest.mark.parametrize("field", ["environment_id", "version", "task", "tools"])
def test_static_metadata_mutation_is_rejected(field):
    initial, current, history = one_step()
    if field == "tools":
        current[field][0]["args_schema"]["changed"] = True
    else:
        current[field] += "changed"
    with pytest.raises(LedgerError, match="static metadata changed"):
        request_body(MODEL, initial, current, history)


@pytest.mark.parametrize("mutation", [
    "index-bool", "index-gap", "action-extra", "action-tool-int", "result-ok-int", "result-missing-ok",
    "tick-float", "tick-gap", "done-int", "terminal", "field-added", "field-removed", "current-differs",
    "controller-observation", "controller-history", "controller-system", "rejected-state", "rejected-role",
])
def test_chain_mutations_fail_closed(mutation):
    initial, current, history = one_step()
    step = history[0]
    if mutation == "index-bool":
        step["index"] = False
    elif mutation == "index-gap":
        step["index"] = 1
    elif mutation == "action-extra":
        step["action"]["grade"] = 1
    elif mutation == "action-tool-int":
        step["action"]["tool"] = 1
    elif mutation == "result-ok-int":
        step["result"]["ok"] = 1
    elif mutation == "result-missing-ok":
        del step["result"]["ok"]
    elif mutation == "tick-float":
        current["tick"] = 1.0
    elif mutation == "tick-gap":
        current["tick"] = 2
    elif mutation == "done-int":
        current["done"] = 0
    elif mutation == "terminal":
        current["done"] = True
    elif mutation == "field-added":
        current["initial_snapshot"] = {}
    elif mutation == "field-removed":
        del current["tick"]
    elif mutation == "current-differs":
        current = copy.deepcopy(current)
        current["state"]["value"] = 1
    elif mutation.startswith("controller"):
        if mutation == "controller-system":
            step["policy_input"][0]["content"] += "changed"
        else:
            payload = json.loads(step["policy_input"][1]["content"])
            if mutation == "controller-observation":
                payload["observation"]["state"]["value"] = 1
            else:
                payload["history"] = [{"action": step["action"], "result": step["result"]}]
            step["policy_input"][1]["content"] = canonical_json(payload)
    else:
        step["result"]["ok"] = False
        if mutation == "rejected-state":
            current["state"]["value"] = 1
        else:
            current["role"] = "changed"
    with pytest.raises(LedgerError):
        request_body(MODEL, initial, current, history)


@pytest.mark.parametrize("context", [None, {}, [], [{}, {}], [{}, {"content": "not JSON"}],
                                    [{}, {"content": '{"observation":{},"history":[]}'}]])
def test_context_derivation_rejects_missing_or_malformed_initial(context):
    _, current, history = one_step()
    history[0]["policy_input"] = context
    with pytest.raises(LedgerError, match="initial controller context"):
        request_from_context(MODEL, current, history)


def test_context_derivation_requires_initial_context_but_explicit_builder_does_not():
    initial, current, history = one_step()
    del history[0]["policy_input"]
    assert reconstruct(request_body(MODEL, initial, current, history))["observation"] == current
    with pytest.raises(LedgerError):
        request_from_context(MODEL, current, history)


@pytest.mark.parametrize("mutation", ["system", "stream", "think", "options", "keep-alive", "model",
                                    "tools-extra", "duplicate-tool", "schema", "header-private", "dynamic-static",
                                    "frame-index", "noncanonical", "extra-line", "extra-body"])
def test_reconstruction_rejects_wire_mutations(mutation):
    initial, current, history = one_step()
    body = request_body(MODEL, initial, current, history)
    if mutation == "system":
        body["messages"][0]["content"] += "changed"
    elif mutation in ("stream", "think"):
        body[mutation] = 0
    elif mutation == "options":
        body["options"]["temperature"] = False
    elif mutation == "keep-alive":
        body["keep_alive"] = "10m"
    elif mutation == "model":
        body["model"] = "unprepared-cloud"
    elif mutation == "tools-extra":
        body["tools"][0]["function"]["endpoint"] = "hidden"
    elif mutation == "duplicate-tool":
        body["tools"].append(copy.deepcopy(body["tools"][0]))
    elif mutation == "schema":
        body["tools"][0]["function"]["parameters"] = []
    elif mutation == "extra-body":
        body["snapshot"] = {}
    else:
        lines = body["messages"][1]["content"].split("\n")
        header, frame = map(json.loads, lines)
        if mutation == "header-private":
            header["initial_observation"]["grader"] = {}
        elif mutation == "dynamic-static":
            frame["observation"]["task"] = initial["task"]
        elif mutation == "frame-index":
            frame["decision_index"] = False
        elif mutation == "noncanonical":
            lines[0] = json.dumps(header, indent=2)
        elif mutation == "extra-line":
            lines.append("{}")
        if mutation not in ("noncanonical", "extra-line"):
            lines = [canonical_json(header), canonical_json(frame)]
        body["messages"][1]["content"] = "\n".join(lines)
    with pytest.raises(LedgerError):
        reconstruct(body)


def test_private_step_fields_are_ignored_and_output_is_detached():
    initial, current, history = one_step()
    history[0].update(initial_snapshot={"private": "DO_NOT_SEND"}, grade={"expected": "DO_NOT_SEND"})
    original = copy.deepcopy((initial, current, history))
    body = request_body(MODEL, initial, current, history)
    assert "DO_NOT_SEND" not in canonical_json(body)
    restored = reconstruct(body)
    restored["initial_observation"]["tools"][0]["args_schema"]["mutated"] = True
    restored["history"][0]["observation"]["state"]["value"] = 7
    body["tools"][0]["function"]["parameters"]["mutated"] = True
    body["options"]["temperature"] = 7
    assert (initial, current, history) == original
    assert request_body(MODEL, initial, current, history)["options"] == OPTIONS


def test_embedded_newline_is_data_not_a_frame_and_calls_are_stateless():
    first = small_observation()
    first["task"] = 'Line one\n{"decision_index":99}\nLine three'
    second = copy.deepcopy(first)
    second["state"]["value"] = 9
    a = request_body(MODEL, first, first, [])
    b = request_body(MODEL, second, second, [])
    assert len(a["messages"][1]["content"].split("\n")) == 1
    assert reconstruct(a)["observation"] == first
    assert reconstruct(b)["observation"] == second
    assert request_body(MODEL, first, first, []) == a


@pytest.mark.parametrize("kind", ["cycle", "depth", "nodes", "large-string", "escaped-string", "large-int",
                                 "nan", "infinity", "surrogate", "non-json", "non-string-key"])
def test_bounded_json_errors_are_redacted(kind):
    observation = small_observation()
    sentinel = "PRIVATE_SENTINEL"
    if kind == "cycle":
        value = []
        value.append(value)
    elif kind == "depth":
        value = sentinel
        for _ in range(MAX_JSON_DEPTH + 1):
            value = [value]
    elif kind == "nodes":
        value = [None] * (MAX_JSON_NODES + 1)
    elif kind == "large-string":
        value = sentinel + "x" * provider_records.MAX_REQUEST_BYTES
    elif kind == "escaped-string":
        value = "\x01" * (provider_records.MAX_REQUEST_BYTES // 5)
    elif kind == "large-int":
        value = 2**5000
    elif kind in ("nan", "infinity"):
        value = float("nan" if kind == "nan" else "inf")
    elif kind == "surrogate":
        value = sentinel + "\ud800"
    elif kind == "non-json":
        value = (sentinel,)
    else:
        value = {1: sentinel}
    observation["state"]["value"] = value
    with pytest.raises(LedgerError) as caught:
        request_body(MODEL, observation, observation, [])
    assert sentinel not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize("model", [None, True, "", "x" * 201, "model\ncontrol", "model-cloud"])
def test_invalid_model_is_rejected_before_building(model):
    observation = small_observation()
    with pytest.raises(LedgerError):
        request_body(model, observation, observation, [])


def test_history_bound_and_contract_preserve_native_transport_limits():
    initial = small_observation()
    current = initial
    history = []
    for index in range(MAX_HISTORY):
        following = copy.deepcopy(current)
        following["tick"] += 1
        history.append({"index": index, "action": {"tool": "inspect", "args": {}}, "result": {"ok": True},
                        "observation": following})
        current = following
    assert len(reconstruct(request_body(MODEL, initial, current, history))["history"]) == MAX_HISTORY
    with pytest.raises(LedgerError, match="decision limit"):
        request_body(MODEL, initial, current, history + [history[-1]])
    v1 = native_v1_contract()
    v2 = contract()
    assert v2["protocol"] == PROTOCOL == LEDGER_PROTOCOL != v1["protocol"]
    for key in ("system_prompt", "options", "stream", "think", "request_limit", "response_limit",
                "one_call_per_decision", "episode_record_limit", "response_encoding"):
        assert v1[key] == v2[key]
    v2["options"]["temperature"] = 99
    v2["static_observation_fields"].append("private")
    assert contract()["options"] == OPTIONS
    assert "private" not in contract()["static_observation_fields"]
