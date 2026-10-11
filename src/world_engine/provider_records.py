"""Episode-local, finalized-only evidence for bounded provider requests."""

from __future__ import annotations

import base64
import copy
import hashlib
from contextvars import ContextVar, Token

from world_engine.models import JsonObject, canonical_json

MAX_REQUEST_BYTES = 128 * 1024
MAX_RESPONSE_BYTES = 64 * 1024
MAX_EVENTS = 200
MAX_EPISODE_RECORD_BYTES = 8 * 1024 * 1024
MAX_FINISH_BYTES = 4 * ((MAX_RESPONSE_BYTES + 2) // 3) + 4096
RECORD_SCHEMA = "world-engine.provider-events.v1"
_events: ContextVar[list[JsonObject] | None] = ContextVar("world_engine_provider_events", default=None)


def begin_episode() -> tuple[list[JsonObject], Token]:
    events: list[JsonObject] = []
    return events, _events.set(events)


def end_episode(token: Token) -> None:
    _events.reset(token)


def recording() -> bool:
    return _events.get() is not None


def record(event: JsonObject) -> None:
    events = _events.get()
    if events is None:
        raise RuntimeError("provider recording requires an active rollout episode")
    if len(events) >= MAX_EVENTS:
        raise ValueError("provider event limit reached")
    if recorded_bytes(events) + len(canonical_json(event).encode("utf-8")) + bool(events) > MAX_EPISODE_RECORD_BYTES:
        raise ValueError("provider episode evidence byte limit reached")
    # Copy at the boundary so later provider mutation cannot rewrite prior evidence.
    events.append(copy.deepcopy(event))


def recorded_bytes(events: list[JsonObject]) -> int:
    return len(canonical_json(events).encode("utf-8"))


def reserve_request(start: JsonObject) -> bool:
    events = _events.get()
    return (events is not None and len(events) + 2 <= MAX_EVENTS
            and recorded_bytes(events) + len(canonical_json(start).encode("utf-8")) + bool(events) + MAX_FINISH_BYTES + 1
            <= MAX_EPISODE_RECORD_BYTES)


def byte_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def response_bytes(event: JsonObject) -> bytes:
    value = event["response_body_b64"]
    if not isinstance(value, str) or len(value) > 4 * ((MAX_RESPONSE_BYTES + 2) // 3):
        raise ValueError("provider response record exceeds its limit")
    try:
        body = base64.b64decode(value, validate=True)
    except ValueError as error:
        raise ValueError("provider response record is not base64") from error
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("provider response record exceeds its limit")
    return body


def validate_pairs(events: list[JsonObject], protocol: str) -> list[tuple[JsonObject, JsonObject]]:
    if not isinstance(events, list) or len(events) > MAX_EVENTS or len(events) % 2:
        raise ValueError("provider events are not bounded request/outcome pairs")
    if recorded_bytes(events) > MAX_EPISODE_RECORD_BYTES:
        raise ValueError("provider episode evidence byte limit reached")
    pairs = []
    seen = set()
    for index in range(0, len(events), 2):
        start, end = events[index:index + 2]
        if start["event"] != "request_started" or end["event"] != "request_finished":
            raise ValueError("provider event ordering is invalid")
        for key in ("schema", "protocol", "call_id", "decision_index"):
            if canonical_json(start[key]) != canonical_json(end[key]):
                raise ValueError("provider event pair identity differs")
        if start["schema"] != RECORD_SCHEMA or start["protocol"] != protocol:
            raise ValueError("provider event protocol is unsupported")
        call_id = start["call_id"]
        if not isinstance(call_id, str) or not call_id or len(call_id) > 80 or call_id in seen:
            raise ValueError("provider call identity is invalid")
        seen.add(call_id)
        if type(start["decision_index"]) is not int or start["decision_index"] != index // 2:
            raise ValueError("provider decision index is invalid")
        request = start["request_body"]
        if not isinstance(request, str):
            raise ValueError("provider request body is invalid")
        request_bytes = request.encode("utf-8")
        if (len(request_bytes) > MAX_REQUEST_BYTES or type(start["request_bytes"]) is not int
                or start["request_bytes"] != len(request_bytes)):
            raise ValueError("provider request record exceeds its limit")
        if start["request_sha256"] != byte_hash(request_bytes):
            raise ValueError("provider request byte hash differs")
        body = response_bytes(end)
        if type(end["response_bytes"]) is not int or end["response_bytes"] != len(body) or end["response_sha256"] != byte_hash(body):
            raise ValueError("provider response byte hash differs")
        if type(end["complete"]) is not bool or type(end["body_complete"]) is not bool:
            raise ValueError("provider completeness flags are invalid")
        if end["response_hash_scope"] != ("complete-body" if end["body_complete"] else "observed-prefix"):
            raise ValueError("provider response hash scope is invalid")
        if end["http_status"] is not None and (type(end["http_status"]) is not int or not 100 <= end["http_status"] <= 599):
            raise ValueError("provider HTTP status is invalid")
        if type(end["elapsed_ms"]) not in (int, float) or end["elapsed_ms"] < 0:
            raise ValueError("provider elapsed time is invalid")
        for value in (start["observed_at"], end["observed_at"]):
            if not isinstance(value, str) or len(value) > 80:
                raise ValueError("provider observed timestamp is invalid")
        usage = end["usage"]
        if not isinstance(usage, dict):
            raise ValueError("provider usage is invalid")
        for key in ("input_tokens", "output_tokens"):
            if key in usage and (type(usage[key]) is not int or usage[key] < 0):
                raise ValueError("provider reported token count is invalid")
        canonical_json(end)
        pairs.append((start, end))
    return pairs


def usage_summary(events: list[JsonObject]) -> JsonObject:
    outcomes = [event for event in events if event["event"] == "request_finished"]
    output: JsonObject = {"request_attempts": len(outcomes), "accounting_scope": "recorded transport attempts, not attested model executions"}
    for key in ("input_tokens", "output_tokens"):
        known = [event["usage"][key] for event in outcomes if key in event["usage"]]
        output[key + "_complete"] = bool(outcomes) and len(known) == len(outcomes)
        if known:
            output[key + "_known"] = sum(known)
        if output[key + "_complete"]:
            output[key] = sum(known)
    return output
