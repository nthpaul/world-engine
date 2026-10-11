"""Pure normalized native request builder and public-context reconstruction."""

from __future__ import annotations

import copy
import json
import math

from world_engine import provider_records
from world_engine.models import Action, JsonObject, canonical_json
from world_engine.ollama_tools import OPTIONS, SYSTEM_PROMPT
from world_engine.providers import policy_messages

PROTOCOL = "ollama-tools-ledger-v2"
STATIC_FIELDS = ("environment_id", "version", "task", "tools")
OBSERVATION_FIELDS = {*STATIC_FIELDS, "role", "state", "done", "tick"}
MAX_HISTORY = provider_records.MAX_EVENTS // 2 - 1
MAX_JSON_DEPTH = 64
MAX_JSON_NODES = 32768


class LedgerError(ValueError):
    """Bounded public-context validation failed; never includes supplied values."""


def _require(condition: bool, message: str = "invalid native ledger context") -> None:
    if not condition:
        raise LedgerError(message) from None


def _bytes(text: str) -> int:
    try:
        return len(text.encode("utf-8"))
    except UnicodeError:
        raise LedgerError("native ledger text is not valid UTF-8") from None


def _json(value: object) -> None:
    # Walk iterators instead of allocating a stack containing every child.
    stack = [iter((value,))]
    active: set[int] = set()
    containers: list[int | None] = [None]
    nodes = 0
    text_bytes = 0
    while stack:
        try:
            item = next(stack[-1])
        except StopIteration:
            stack.pop()
            identity = containers.pop()
            if identity is not None:
                active.remove(identity)
            continue
        nodes += 1
        _require(nodes <= MAX_JSON_NODES, "native ledger JSON node limit exceeded")
        kind = type(item)
        if kind in (dict, list):
            _require(len(stack) <= MAX_JSON_DEPTH and len(item) <= MAX_JSON_NODES,
                     "native ledger JSON depth or node limit exceeded")
            identity = id(item)
            _require(identity not in active, "native ledger JSON contains a cycle")
            active.add(identity)
            if kind is dict:
                for key in item:
                    _require(type(key) is str and len(key) <= provider_records.MAX_REQUEST_BYTES)
                    text_bytes += _bytes(key)
                children = iter(item.values())
            else:
                children = iter(item)
            stack.append(children)
            containers.append(identity)
        elif kind is str:
            _require(len(item) <= provider_records.MAX_REQUEST_BYTES)
            text_bytes += _bytes(item)
        elif kind is float:
            _require(math.isfinite(item))
        else:
            _require(kind in (type(None), bool, int))
            if kind is int:
                _require(item.bit_length() <= 4096, "native ledger integer limit exceeded")
        _require(text_bytes <= provider_records.MAX_REQUEST_BYTES, "native ledger JSON text limit exceeded")


def _same(left: object, right: object) -> bool:
    return canonical_json(left) == canonical_json(right)


def _observation(value: object) -> None:
    _json(value)
    _require(type(value) is dict)
    _require(set(value) <= OBSERVATION_FIELDS and set(value) >= OBSERVATION_FIELDS - {"tick"})
    for key in ("environment_id", "version", "role"):
        item = value[key]
        _require(type(item) is str and 0 < len(item) <= 80 and item.isprintable())
    _require(type(value["task"]) is str and type(value["state"]) is dict and type(value["done"]) is bool)
    if "tick" in value:
        _require(type(value["tick"]) is int and value["tick"] >= 0)
    tools = value["tools"]
    _require(type(tools) is list and 0 < len(tools) <= 80)
    names = set()
    for tool in tools:
        _require(type(tool) is dict and set(tool) == {"name", "description", "args_schema"})
        name = tool["name"]
        _require(type(name) is str and 0 < len(name) <= 80 and name.isprintable() and name not in names)
        _require(type(tool["description"]) is str and type(tool["args_schema"]) is dict)
        names.add(name)


def _content(initial: JsonObject, current: JsonObject, history: list[JsonObject]) -> str:
    _observation(initial)
    _observation(current)
    _require(not initial["done"] and not current["done"], "native ledger cannot request after finish")
    _require("tick" not in initial or initial["tick"] == 0, "native ledger initial tick must be zero")
    _require(type(history) is list and len(history) <= MAX_HISTORY, "native ledger decision limit exceeded")
    first = {key: value for key, value in initial.items() if key != "tools"}
    content = canonical_json({"initial_observation": first})
    _require(_bytes(content) <= provider_records.MAX_REQUEST_BYTES, "native ledger request exceeded 128 KiB")
    previous = initial
    for index, step in enumerate(history):
        _require(type(step) is dict and {"index", "action", "result", "observation"} <= set(step))
        _require(type(step["index"]) is int and step["index"] == index)
        _json(step["action"])
        _json(step["result"])
        try:
            action = Action.model_validate(step["action"])
        except ValueError:
            raise LedgerError("invalid native ledger action") from None
        _require(_same(action.model_dump(), step["action"]))
        result = step["result"]
        _require(type(result) is dict and type(result.get("ok")) is bool)
        following = step["observation"]
        _observation(following)
        _require(set(following) == set(initial), "native ledger observation fields changed")
        _require(all(_same(following[key], initial[key]) for key in STATIC_FIELDS),
                 "native ledger static metadata changed")
        _require(not previous["done"] and not following["done"], "native ledger cannot request after finish")
        if "tick" in initial:
            _require(following["tick"] == previous["tick"] + 1, "native ledger tick chain differs")
        if not result["ok"]:
            _require(_same(following["state"], previous["state"]) and following["role"] == previous["role"],
                     "native ledger rejected action changed public state")
        dynamic = {key: value for key, value in following.items() if key not in STATIC_FIELDS}
        content += "\n" + canonical_json({"decision_index": index, "action": step["action"],
                                        "result": result, "observation": dynamic})
        _require(_bytes(content) <= provider_records.MAX_REQUEST_BYTES, "native ledger request exceeded 128 KiB")
        if "policy_input" in step:
            _json(step["policy_input"])
            _require(_same(step["policy_input"], policy_messages(previous, history[:index])),
                     "native ledger controller context differs")
        previous = following
    _require(_same(previous, current), "native ledger current observation differs from chain")
    return content


def contract() -> JsonObject:
    return {"protocol": PROTOCOL, "system_prompt": SYSTEM_PROMPT, "options": dict(OPTIONS),
            "stream": False, "think": False, "one_call_per_decision": True,
            "request_limit": provider_records.MAX_REQUEST_BYTES,
            "response_limit": provider_records.MAX_RESPONSE_BYTES,
            "episode_record_limit": provider_records.MAX_EPISODE_RECORD_BYTES,
            "response_encoding": "identity-only", "max_history": MAX_HISTORY,
            "history_mode": "initial-public-observation-and-append-only-normalized-event-lines",
            "static_observation_fields": list(STATIC_FIELDS)}


def request_body(model: str, initial_observation: JsonObject, observation: JsonObject,
                 history: list[JsonObject]) -> JsonObject:
    """Build from an explicit public reset observation, without retaining state."""
    _require(type(model) is str and 0 < len(model) <= 200 and model.isprintable() and "cloud" not in model.lower(),
             "native ledger requires a bounded local model name")
    content = _content(initial_observation, observation, history)
    body = {"model": model, "messages": [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content}],
            "tools": [{"type": "function", "function": {"name": tool["name"],
                       "description": tool["description"], "parameters": copy.deepcopy(tool["args_schema"])}}
                      for tool in initial_observation["tools"]],
            "stream": False, "think": False, "options": dict(OPTIONS), "keep_alive": "5m"}
    _require(_bytes(canonical_json(body)) <= provider_records.MAX_REQUEST_BYTES,
             "native ledger request exceeded 128 KiB")
    return body


def request_from_context(model: str, observation: JsonObject, history: list[JsonObject]) -> JsonObject:
    """Use the first controller context as public initial data, not grading truth."""
    _require(type(history) is list and len(history) <= MAX_HISTORY)
    initial = observation
    if history:
        try:
            context = history[0]["policy_input"]
            _json(context)
            _require(type(context) is list and len(context) == 2 and type(context[1]) is dict)
            text = context[1]["content"]
            _require(type(text) is str and _bytes(text) <= provider_records.MAX_REQUEST_BYTES)
            payload = json.loads(text)
            _json(payload)
            _require(type(payload) is dict and set(payload) == {"observation", "history"} and payload["history"] == [])
            initial = payload["observation"]
            _require(_same(context, policy_messages(initial, [])))
        except (ValueError, TypeError, KeyError, IndexError, RecursionError):
            raise LedgerError("native ledger initial controller context unavailable or invalid") from None
    return request_body(model, initial, observation, history)


def reconstruct(body: JsonObject) -> JsonObject:
    """Expand a candidate wire body; rebuilding it must produce identical bytes."""
    try:
        _json(body)
        _require(type(body) is dict and set(body) == {"model", "messages", "tools", "stream", "think", "options", "keep_alive"})
        messages = body["messages"]
        _require(type(messages) is list and len(messages) == 2)
        _require(messages[0] == {"role": "system", "content": SYSTEM_PROMPT})
        _require(type(messages[1]) is dict and set(messages[1]) == {"role", "content"} and messages[1]["role"] == "user")
        text = messages[1]["content"]
        _require(type(text) is str and _bytes(text) <= provider_records.MAX_REQUEST_BYTES)
        lines = text.split("\n")
        _require(len(lines) <= MAX_HISTORY + 1)
        header = json.loads(lines[0])
        _require(type(header) is dict and set(header) == {"initial_observation"})
        initial = header["initial_observation"]
        _require(type(initial) is dict and "tools" not in initial)
        tools = body["tools"]
        _require(type(tools) is list and len(tools) <= 80)
        public_tools = []
        for tool in tools:
            _require(type(tool) is dict and set(tool) == {"type", "function"} and tool["type"] == "function")
            function = tool["function"]
            _require(type(function) is dict and set(function) == {"name", "description", "parameters"})
            public_tools.append({"name": function["name"], "description": function["description"], "args_schema": function["parameters"]})
        initial = {**initial, "tools": public_tools}
        static = {key: initial[key] for key in STATIC_FIELDS}
        history = []
        for index, line in enumerate(lines[1:]):
            frame = json.loads(line)
            _require(type(frame) is dict and set(frame) == {"decision_index", "action", "result", "observation"})
            _require(type(frame["decision_index"]) is int and frame["decision_index"] == index)
            dynamic = frame["observation"]
            _require(type(dynamic) is dict and set(dynamic).isdisjoint(STATIC_FIELDS))
            history.append({"index": index, "action": frame["action"], "result": frame["result"],
                            "observation": {**static, **dynamic}})
        current = history[-1]["observation"] if history else initial
        rebuilt = request_body(body["model"], initial, current, history)
        _require(_same(body, rebuilt), "native ledger request is not canonical or coherent")
        return copy.deepcopy({"initial_observation": initial, "history": history, "observation": current})
    except (ValueError, TypeError, KeyError, IndexError, RecursionError):
        raise LedgerError("native ledger wire body failed reconstruction") from None
