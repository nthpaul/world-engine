import asyncio
import base64
import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest

from world_engine.browser_contracts import BrowserAttemptConfig, BrowserError, BrowserObservation
from world_engine.browser_policy import (
    ACCESSIBILITY_LIMIT,
    FULL_HISTORY_OBSERVATIONS,
    OPTIONS,
    PROTOCOL,
    RESPONSE_LIMIT,
    SHOW_RESPONSE_LIMIT,
    BrowserReferencePolicy,
    OllamaBrowserPolicy,
    ax_nodes,
    browser_tools,
    create_browser_policy,
)
from world_engine.models import canonical_json

PROMPT = ("In Release Operations, find the open issue whose description says Deployment reference: REL-2026-1042. "
          "Add exactly: Release checklist verified; ready for closure. Then close that issue. "
          "Leave other issues, existing comments and project access unchanged.")
DIGEST = "a" * 64


def observation(text="[3] link 'Release Operations'", url="http://127.0.0.1:8929/dashboard/projects"):
    return BrowserObservation(url=url, title="GitLab", accessibility_text=text, screenshot_artifact_id="screenshots/0000.png")


class RawStream(httpx.AsyncByteStream):
    def __init__(self, value):
        self.value = value

    async def __aiter__(self):
        yield json.dumps(self.value).encode()


def response(value):
    return httpx.Response(200, stream=RawStream(value))


class ChunkedBytes(httpx.AsyncByteStream):
    def __init__(self, raw):
        self.raw = raw

    async def __aiter__(self):
        for offset in range(0, len(self.raw), 16_384):
            yield self.raw[offset:offset + 16_384]


def show_body(size):
    value = {"capabilities": ["completion", "tools"], "template": "t" * 1723, "details": ""}
    value["details"] = "x" * (size - len(json.dumps(value).encode()))
    raw = json.dumps(value).encode()
    assert len(raw) == size
    return raw


@pytest.mark.parametrize("size", [RESPONSE_LIMIT + 1, 75_727, SHOW_RESPONSE_LIMIT])
async def test_large_show_metadata_prepares_without_chat(size):
    policy = OllamaBrowserPolicy("qwen3:32b", PROMPT)
    await policy.client.aclose()
    paths, events = [], []
    raw = show_body(size)

    def handler(request):
        paths.append(request.url.path)
        assert request.headers["Accept-Encoding"] == "identity"
        if request.url.path == "/api/tags":
            return response({"models": [{"name": "qwen3:32b", "digest": DIGEST, "size": 100}]})
        if request.url.path == "/api/version":
            return response({"version": "mock-daemon"})
        assert request.url.path == "/api/show" and request.method == "POST"
        assert json.loads(request.content) == {"model": "qwen3:32b"}
        return httpx.Response(200, stream=ChunkedBytes(raw))

    policy.client = httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False)
    policy.set_recorder(lambda kind, payload: events.append((kind, payload)))
    try:
        await policy.prepare()
        assert paths == ["/api/tags", "/api/version", "/api/show"]
        assert policy.prepared_model == "qwen3:32b" and policy.digest == DIGEST
        assert [kind for kind, _ in events] == ["policy_prepared"]
        assert policy.evidence_metadata["template_sha256"] == hashlib.sha256(("t" * 1723).encode()).hexdigest()
        assert "details" not in policy.evidence_metadata
    finally:
        await policy.close()


async def test_show_over_256kib_fails_before_prepared_or_chat():
    policy = OllamaBrowserPolicy("qwen3:32b", PROMPT)
    await policy.client.aclose()
    paths, events = [], []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path == "/api/tags":
            return response({"models": [{"name": "qwen3:32b", "digest": DIGEST, "size": 100}]})
        if request.url.path == "/api/version":
            return response({"version": "mock-daemon"})
        assert request.url.path == "/api/show"
        return httpx.Response(200, stream=ChunkedBytes(show_body(SHOW_RESPONSE_LIMIT + 1)))

    policy.client = httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False)
    policy.set_recorder(lambda kind, payload: events.append((kind, payload)))
    try:
        with pytest.raises(BrowserError, match="response exceeds its bound"):
            await policy.prepare()
        assert paths == ["/api/tags", "/api/version", "/api/show"]
        assert policy.prepared_model is None and policy.digest is None and policy.evidence_metadata == {}
        assert not events
    finally:
        await policy.close()


@pytest.mark.parametrize("path", ["/api/chat", "/api/tags", "/api/version", "/api/show/"])
@pytest.mark.parametrize("extra", [0, 1])
async def test_only_exact_show_path_gets_wider_response_allowance(path, extra):
    assert RESPONSE_LIMIT == 65_536 and SHOW_RESPONSE_LIMIT == 262_144
    policy = OllamaBrowserPolicy("qwen3:8b", PROMPT)
    await policy.client.aclose()
    raw, events = b"x" * (RESPONSE_LIMIT + extra), []
    policy.client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, stream=ChunkedBytes(raw))), trust_env=False)
    policy.set_recorder(lambda kind, payload: events.append((kind, payload)))
    try:
        if extra:
            with pytest.raises(BrowserError, match="response exceeds its bound"):
                await policy._read("POST" if path == "/api/chat" else "GET", path)
            if path == "/api/chat":
                assert events[0][0] == "inference_transport_failure"
                payload = events[0][1]
                assert payload["body_bytes"] == RESPONSE_LIMIT
                assert base64.b64decode(payload["partial_body_b64"]) == raw[:RESPONSE_LIMIT]
                assert payload["body_sha256"] == hashlib.sha256(raw[:RESPONSE_LIMIT]).hexdigest()
                assert payload["complete_reply_certified"] is False
            else:
                assert not events
        else:
            assert await policy._read("POST" if path == "/api/chat" else "GET", path) == raw
            assert not events
    finally:
        await policy.close()


async def policy_with_reply(reply, *, model_entry=None, show_data=None):
    policy = OllamaBrowserPolicy("qwen3:8b", PROMPT)
    await policy.client.aclose()
    events = []

    def transport(request):
        if request.url.path == "/api/tags":
            return response({"models": [model_entry or {"name": "qwen3:8b", "digest": DIGEST, "size": 100}]})
        if request.url.path == "/api/version":
            return response({"version": "test-local-daemon"})
        if request.url.path == "/api/show":
            return response(show_data if show_data is not None else {
                "capabilities": ["completion", "tools"], "template": "test-native-template"})
        if request.url.path == "/api/chat":
            assert events[-1][0] == "inference_intent"
            assert json.loads(request.content) == events[-1][1]["request_body"]
            return response(reply)
        raise AssertionError("unexpected request")

    policy.client = httpx.AsyncClient(transport=httpx.MockTransport(transport), trust_env=False)
    policy.set_recorder(lambda kind, payload: events.append((kind, payload)))
    return policy, events


def valid_reply(arguments=None, *, name="browser_finish"):
    return {"model": "qwen3:8b", "done": True, "done_reason": "stop", "message": {"role": "assistant",
            "tool_calls": [{"function": {"name": name, "arguments": {} if arguments is None else arguments}}]},
            "prompt_eval_count": 42, "eval_count": 8}


def context_policy(*, max_steps=30):
    policy = object.__new__(OllamaBrowserPolicy)
    policy.prepared_model, policy.instruction, policy.max_steps = "qwen3:8b", PROMPT, max_steps
    return policy


def public_transition(index, *, action=None, following=None, result=None):
    return {"step": index, "action": action or {"kind": "click", "bid": "385"},
            "result": {"ok": True} if result is None else result,
            "observation": (following or observation("[385] link 'New project'",
                "http://127.0.0.1:8929/projects/new#")).model_dump()}


def test_context_saturation_never_aliases_seventeen_late_decisions():
    policy = context_policy()
    current = observation("[385] link 'New project'", "http://127.0.0.1:8929/projects/new#")
    history = [public_transition(index, following=current) for index in range(29)]
    requests = [policy.request_body(current, history[:length]) for length in range(13, 30)]
    assert len({canonical_json(request) for request in requests}) == 17
    for length, request in zip(range(13, 30), requests, strict=True):
        final = json.loads(request["messages"][-1]["content"])
        assert final["next_step"] == length and final["remaining_actions"] == 30 - length
        assert final["feedback"] == {"consecutive_same_action": length,
            "consecutive_unchanged_observations": length - 1, "first_action_transition_known": False,
            "ok_means": "execution_only_not_task_progress"}
        assert sum(message["role"] == "tool" for message in request["messages"]) == length


def test_context_retains_chronological_linked_public_transitions_only():
    policy = context_policy()
    before = observation("[389] link 'New project'")
    after = observation("[385] link 'New project'", "http://127.0.0.1:8929/projects/new")
    row = public_transition(0, action={"kind": "click", "bid": "389"}, following=after)
    row.update(operator_snapshot={"sentinel": "protected"}, evidence={"sentinel": "protected"})
    body = policy.request_body(after, [row])
    assert [message["role"] for message in body["messages"]] == ["system", "user", "assistant", "tool", "user"]
    assert json.loads(body["messages"][1]["content"]) == {"task": PROMPT}
    assistant, tool = body["messages"][2:4]
    assert assistant == {"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": "browser_click", "arguments": {"bid": "389"}}}]}
    assert tool["tool_name"] == "browser_click"
    frame = json.loads(tool["content"])
    assert frame["completed_step"] == 0 and frame["result"] == {"ok": True}
    assert frame["observation"]["url"] == after.url
    assert frame["observation"]["accessibility_text"] == after.accessibility_text
    final = json.loads(body["messages"][-1]["content"])
    assert final["observation"]["accessibility_text"] == after.accessibility_text != before.accessibility_text
    assert final["feedback"]["consecutive_unchanged_observations"] == 0
    assert not any(value in canonical_json(body) for value in ("protected", "operator_snapshot", "screenshot_artifact_id"))
    assert "tool_call_id" not in tool  # Links are normalized adjacency+tool_name, not fabricated daemon IDs.


@pytest.mark.parametrize("length", [0, 4660, 31999, 32000, 65536])
def test_context_bounds_aggregate_ax_and_discloses_compaction(length):
    policy = context_policy()
    current = observation("x" * length)
    history = [public_transition(index, following=current) for index in range(5)]
    body = policy.request_body(current, history)
    frames = [json.loads(message["content"])["observation"] for message in body["messages"]
              if message["role"] == "tool"]
    final = json.loads(body["messages"][-1]["content"])["observation"]
    assert sum(len(frame.get("accessibility_text", "")) for frame in frames + [final]) <= ACCESSIBILITY_LIMIT
    assert all(frame["accessibility_omitted"] is True for frame in frames[:-FULL_HISTORY_OBSERVATIONS])
    assert all(frame["accessibility_sha256"] == hashlib.sha256(current.accessibility_text.encode()).hexdigest()
               and frame["accessibility_chars"] == length for frame in frames + [final])
    assert final["accessibility_truncated"] is (length > ACCESSIBILITY_LIMIT)
    assert final["accessibility_text"] == current.accessibility_text[:ACCESSIBILITY_LIMIT]


@pytest.mark.parametrize("mutation", ["missing_step", "bool_step", "wrong_step", "missing_action", "mixed_action",
    "missing_result", "list_result", "numeric_ok", "private_result", "bad_uncertain", "bad_message", "large_message",
    "missing_observation", "private_observation", "stale_url", "stale_ax", "stale_title", "list_row", "none_history"])
def test_context_rejects_noncontiguous_malformed_or_stale_public_history(mutation):
    current = observation()
    history = [public_transition(0, following=current)]
    row = history[0]
    if mutation == "missing_step":
        del row["step"]
    elif mutation == "bool_step":
        row["step"] = False
    elif mutation == "wrong_step":
        row["step"] = 1
    elif mutation == "missing_action":
        del row["action"]
    elif mutation == "mixed_action":
        row["action"]["shell"] = "not permitted"
    elif mutation == "missing_result":
        del row["result"]
    elif mutation == "list_result":
        row["result"] = []
    elif mutation == "numeric_ok":
        row["result"]["ok"] = 1
    elif mutation == "private_result":
        row["result"]["operator_snapshot"] = {"private": "not permitted"}
    elif mutation == "bad_uncertain":
        row["result"]["uncertain_effect"] = 0
    elif mutation == "bad_message":
        row["result"]["message"] = []
    elif mutation == "large_message":
        row["result"]["message"] = "x" * 4097
    elif mutation == "missing_observation":
        del row["observation"]
    elif mutation == "private_observation":
        row["observation"]["protected"] = "not permitted"
    elif mutation == "stale_url":
        row["observation"]["url"] += "/other"
    elif mutation == "stale_ax":
        row["observation"]["accessibility_text"] = "different current IDs"
    elif mutation == "stale_title":
        row["observation"]["title"] = "Different page"
    elif mutation == "list_row":
        history[0] = []
    else:
        history = None
    with pytest.raises(BrowserError, match="contiguous public"):
        context_policy().request_body(current, history)


def test_context_budget_boundary_and_oversized_request_fail_closed():
    current = observation()
    with pytest.raises(BrowserError, match="contiguous public"):
        context_policy(max_steps=1).request_body(current, [public_transition(0, following=current)])
    history = [public_transition(index, following=current, result={"ok": True, "message": "x" * 4096})
               for index in range(40)]
    with pytest.raises(BrowserError, match="request exceeds"):
        context_policy(max_steps=50).request_body(current, history)


def test_context_feedback_resets_only_on_observed_change_not_execution_ok():
    unchanged, changed = observation(), observation("[7] link 'Actual next page'")
    history = [public_transition(0, following=unchanged), public_transition(1, following=unchanged)]
    final = json.loads(context_policy().request_body(unchanged, history)["messages"][-1]["content"])
    assert final["feedback"]["consecutive_unchanged_observations"] == 1
    history.append(public_transition(2, following=changed))
    final = json.loads(context_policy().request_body(changed, history)["messages"][-1]["content"])
    assert final["feedback"]["consecutive_unchanged_observations"] == 0
    assert final["feedback"]["consecutive_same_action"] == 3
    assert final["observation"]["accessibility_text"] == changed.accessibility_text


def test_context_body_is_detached_from_history_policy_and_tool_schema():
    current = observation()
    history = [public_transition(0, following=current, result={"ok": False, "error": "node_not_visible",
                                                             "uncertain_effect": False})]
    original = canonical_json(history)
    policy = context_policy()
    body = policy.request_body(current, history)
    frame = json.loads(body["messages"][3]["content"])
    assert frame["result"] == history[0]["result"]
    body["messages"][2]["tool_calls"][0]["function"]["arguments"]["bid"] = "other"
    body["options"]["temperature"] = 99
    body["tools"][0]["function"]["name"] = "shell"
    assert canonical_json(history) == original
    fresh = policy.request_body(current, history)
    assert fresh["messages"][2]["tool_calls"][0]["function"]["arguments"]["bid"] == "385"
    assert fresh["options"]["temperature"] == 0 and fresh["tools"] == browser_tools()


@pytest.mark.parametrize("case", ["malformed", "stale", "overflow"])
async def test_invalid_context_cannot_emit_inference_intent_or_contact_chat(case):
    policy, events = await policy_with_reply(valid_reply())
    try:
        await policy.prepare()
        current = observation()
        history = [public_transition(0, following=current)]
        if case == "malformed":
            history[0]["result"]["ok"] = 1
        elif case == "stale":
            history[0]["observation"]["accessibility_text"] = "stale"
        else:
            policy.max_steps = 50
            history = [public_transition(index, following=current, result={"ok": True, "message": "x" * 4096})
                       for index in range(40)]
        with pytest.raises(BrowserError):
            await policy.decide(current, history)
        assert [kind for kind, _ in events] == ["policy_prepared"]
    finally:
        await policy.close()


@pytest.mark.parametrize("template", [None, "", "  ", 1, [], {}])
async def test_native_template_identity_required_before_prepared_or_chat(template):
    policy, events = await policy_with_reply(valid_reply(), show_data={"capabilities": ["tools"], "template": template})
    try:
        with pytest.raises(BrowserError, match="support native tools"):
            await policy.prepare()
        assert policy.prepared_model is None and policy.digest is None and policy.evidence_metadata == {}
        assert events == []
    finally:
        await policy.close()


async def test_local_policy_persists_exact_request_and_raw_reply_before_action():
    reply = valid_reply({"bid": "3"}, name="browser_click")
    policy, events = await policy_with_reply(reply)
    try:
        await policy.prepare()
        decision = await policy.decide(observation(), [])
        assert decision.action.kind == "click"
        assert decision.action.bid == "3"
        assert [kind for kind, _ in events] == ["policy_prepared", "inference_intent", "inference_result"]
        assert json.loads(base64.b64decode(events[-1][1]["response_body_b64"])) == reply
        request = events[1][1]["request_body"]
        public = json.loads(request["messages"][-1]["content"])
        assert "screenshot_artifact_id" not in public["observation"]
        assert public["observation"]["image_not_sent_to_model"] is True
        assert policy.evidence_metadata["model_digest"] == DIGEST
        assert policy.evidence_metadata["training_eligible"] is False
        assert policy.evidence_metadata["protocol"] == PROTOCOL == "ollama-browser-tools-v3"
        assert policy.evidence_metadata["template_sha256"] == hashlib.sha256(b"test-native-template").hexdigest()
        assert "test-native-template" not in canonical_json(policy.evidence_metadata)
        assert request["options"] == OPTIONS
        assert request["think"] is False and request["stream"] is False
        assert hashlib.sha256(canonical_json(request).encode()).hexdigest() == events[1][1]["request_sha256"]
        raw = base64.b64decode(events[-1][1]["response_body_b64"])
        assert hashlib.sha256(raw).hexdigest() == events[-1][1]["response_sha256"]
    finally:
        await policy.close()


ACTION_CASES = [
    ("navigate", {"url": "http://127.0.0.1:8929/dashboard/projects"}),
    ("click", {"bid": "3"}),
    ("fill", {"bid": "3", "text": "ordinary comment"}),
    ("press", {"bid": "3", "key": "Enter"}),
    ("scroll", {"direction": "down"}),
    ("wait", {"seconds": 3.0}),
    ("finish", {}),
]


@pytest.mark.parametrize("kind,arguments", ACTION_CASES)
def test_normalized_history_maps_all_seven_actions_without_content_suppression(kind, arguments):
    current = observation()
    history = [public_transition(0, following=current, action={"kind": kind, **arguments})]
    body = context_policy().request_body(current, history)
    assistant, tool = body["messages"][2:4]
    # Installed template's content OR calls branches require content to be empty.
    rendered = assistant["content"] if assistant["content"] else assistant["tool_calls"]
    assert rendered == [{"function": {"name": f"browser_{kind}", "arguments": arguments}}]
    assert tool["tool_name"] == f"browser_{kind}"
    assert "kind" not in canonical_json(rendered)


@pytest.mark.parametrize("max_steps", [0, 51, True, 1.0, "30", None])
def test_local_policy_rejects_invalid_budget_before_client_creation(max_steps, monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: pytest.fail("must validate budget first"))
    with pytest.raises(BrowserError, match="decision budget"):
        OllamaBrowserPolicy("qwen3:8b", PROMPT, max_steps=max_steps)


@pytest.mark.parametrize("timeout_seconds", [30, 180, 600])
def test_factory_passes_exact_episode_budget_without_reference_changes(monkeypatch, timeout_seconds):
    calls = []
    monkeypatch.setattr("world_engine.browser_policy.OllamaBrowserPolicy",
                        lambda model, instruction, **kwargs: calls.append((model, instruction, kwargs)))
    config = BrowserAttemptConfig(task_id="gitlab-issue-close", max_steps=17, timeout_seconds=timeout_seconds)
    create_browser_policy(config, SimpleNamespace(instruction=PROMPT))
    assert calls == [("qwen3:8b", PROMPT, {"max_steps": 17, "timeout_seconds": timeout_seconds})]


@pytest.mark.parametrize("timeout_seconds", [29, 601, True, 180.0, "180", None])
def test_invalid_transport_budget_rejected_before_endpoint_or_client(timeout_seconds, monkeypatch):
    monkeypatch.setattr("world_engine.browser_policy.local_endpoint", lambda: pytest.fail("endpoint inspected"))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: pytest.fail("client created"))
    with pytest.raises(BrowserError, match="episode timeout"):
        OllamaBrowserPolicy("qwen3:8b", PROMPT, timeout_seconds=timeout_seconds)


@pytest.mark.parametrize("timeout_seconds", [30, 179, 180, 181, 600])
async def test_transport_limits_bound_phases_without_changing_v3_request(timeout_seconds):
    policy = OllamaBrowserPolicy("qwen3:8b", PROMPT, timeout_seconds=timeout_seconds)
    try:
        assert policy.client.timeout.as_dict() == {
            "connect": 10, "write": 10, "pool": 10, "read": min(timeout_seconds, 180)}
        policy.prepared_model = "qwen3:8b"
        current, history = observation(), [public_transition(0, following=observation())]
        assert canonical_json(policy.request_body(current, history)) == canonical_json(
            context_policy().request_body(current, history))
    finally:
        await policy.close()


async def test_direct_constructor_default_and_prepared_metadata_report_actual_client_limits():
    policy, events = await policy_with_reply(valid_reply())
    try:
        assert policy.timeout_seconds == 180
        await policy.prepare()
        metadata = events[-1][1]
        assert metadata["declared_episode_timeout_seconds"] == 180
        # The mock replaces the client; evidence must report its actual limits, not invent the defaults.
        assert metadata["transport_timeouts_seconds"] == policy.client.timeout.as_dict() == {
            "connect": 5, "write": 5, "pool": 5, "read": 5}
    finally:
        await policy.close()


TRANSPORT_FAILURES = [
    (httpx.ConnectTimeout, "connect_timeout"), (httpx.ReadTimeout, "read_timeout"),
    (httpx.WriteTimeout, "write_timeout"), (httpx.PoolTimeout, "pool_timeout"),
    (httpx.ConnectError, "connect_error"), (httpx.ReadError, "read_error"),
    (httpx.WriteError, "write_error"), (httpx.RemoteProtocolError, "protocol_error"),
    (httpx.LocalProtocolError, "protocol_error"), (httpx.HTTPError, "transport_error"),
    (asyncio.CancelledError, "cancelled"), (RuntimeError, "unexpected_error"),
]


@pytest.mark.parametrize("error_type,category", TRANSPORT_FAILURES)
@pytest.mark.parametrize("has_prefix", [False, True])
async def test_transport_diagnostics_preserve_prefix_and_fixed_redacted_category(
        error_type, category, has_prefix, monkeypatch):
    policy = OllamaBrowserPolicy("qwen3:8b", PROMPT, timeout_seconds=600)
    await policy.client.aclose()
    prefix, events = b'{"message":', []

    class FailingStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield prefix
            raise error_type("PRIVATE_ERROR_SENTINEL")

    def handler(request):
        assert request.extensions["timeout"] == {"connect": 10, "write": 10, "pool": 10, "read": 180}
        if has_prefix:
            return httpx.Response(200, stream=FailingStream())
        raise error_type("PRIVATE_ERROR_SENTINEL")

    policy.client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=httpx.Timeout(
        connect=10, write=10, pool=10, read=180), trust_env=False)
    policy.set_recorder(lambda kind, payload: events.append((kind, payload)))
    clock = iter([20.0, 20.25])
    monkeypatch.setattr("world_engine.browser_policy.time", SimpleNamespace(monotonic=lambda: next(clock)))
    try:
        expected_error = BrowserError if issubclass(error_type, httpx.HTTPError) else error_type
        with pytest.raises(expected_error) as caught:
            await policy._read("POST", "/api/chat", b"{}")
        if issubclass(error_type, httpx.HTTPError):
            assert str(caught.value) == "local inference request failed"
            assert caught.value.__cause__ is None and caught.value.__suppress_context__
        assert [kind for kind, _ in events] == ["inference_transport_failure"]
        retained = prefix if has_prefix else b""
        assert events[0][1] == {
            "status": 200 if has_prefix else None, "partial_body_b64": base64.b64encode(retained).decode(),
            "body_bytes": len(retained), "body_sha256": hashlib.sha256(retained).hexdigest(),
            "complete_reply_certified": False, "failure_category": category, "elapsed_seconds": 0.25,
            "transport_timeouts_seconds": {"connect": 10, "write": 10, "pool": 10, "read": 180}}
        assert "PRIVATE_ERROR_SENTINEL" not in canonical_json(events)
    finally:
        await policy.close()


@pytest.mark.parametrize("status,encoding,raw,category", [
    (500, "identity", b"bounded failure", "invalid_http_response"),
    (200, "gzip", b"bounded compressed failure", "invalid_http_response"),
    (200, "identity", b"x" * (RESPONSE_LIMIT + 1), "response_limit"),
])
async def test_transport_boundary_failures_have_fixed_categories(status, encoding, raw, category):
    policy = OllamaBrowserPolicy("qwen3:8b", PROMPT)
    await policy.client.aclose()
    events = []
    policy.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
        status, headers={"content-encoding": encoding}, stream=ChunkedBytes(raw))), trust_env=False)
    policy.set_recorder(lambda kind, payload: events.append((kind, payload)))
    try:
        with pytest.raises(BrowserError):
            await policy._read("POST", "/api/chat", b"{}")
        failure = events[0][1]
        assert failure["failure_category"] == category
        assert base64.b64decode(failure["partial_body_b64"]) == raw[:RESPONSE_LIMIT]
        assert failure["elapsed_seconds"] >= 0 and failure["complete_reply_certified"] is False
    finally:
        await policy.close()


async def test_transport_failure_durable_order_keeps_intent_prefix_then_failed_marker(monkeypatch):
    policy = OllamaBrowserPolicy("qwen3:8b", PROMPT, timeout_seconds=600)
    await policy.client.aclose()
    events = []

    def handler(request):
        assert events[-1][0] == "inference_intent"
        raise httpx.ReadTimeout("PRIVATE_ERROR_SENTINEL")

    async def identity(model):
        return DIGEST

    monkeypatch.setattr(policy, "_model_identity", identity)
    policy.digest, policy.prepared_model = DIGEST, "qwen3:8b"
    policy.client = httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False)
    policy.set_recorder(lambda kind, payload: events.append((kind, payload)))
    try:
        with pytest.raises(BrowserError, match="request failed"):
            await policy.decide(observation(), [])
        assert [kind for kind, _ in events] == [
            "inference_intent", "inference_transport_failure", "inference_failed"]
        assert events[1][1]["failure_category"] == "read_timeout"
        assert not any(kind == "inference_result" for kind, _ in events)
        assert "PRIVATE_ERROR_SENTINEL" not in canonical_json(events)
    finally:
        await policy.close()


def test_flat_tools_survive_object_properties_required_projection():
    tools = browser_tools()
    assert [tool["function"]["name"] for tool in tools] == [f"browser_{kind}" for kind, _ in ACTION_CASES]
    for tool, (_, arguments) in zip(tools, ACTION_CASES, strict=True):
        function = tool["function"]
        schema = function["parameters"]
        # The bounded object-property API projection must retain every action field.
        projected = {key: schema[key] for key in ("type", "properties", "required")}
        assert projected["type"] == "object"
        assert set(projected["properties"]) == set(projected["required"]) == set(arguments)
        assert schema["additionalProperties"] is False
        assert function["description"]
        assert not any(key in canonical_json(schema) for key in ('"$ref"', '"$defs"', '"oneOf"', '"discriminator"'))
        assert "kind" not in projected["properties"]
        assert all(field["type"] in ("string", "number") for field in projected["properties"].values())


def test_tool_schema_bounds_enums_and_detachment():
    tools = {tool["function"]["name"]: tool["function"] for tool in browser_tools()}
    assert tools["browser_wait"]["parameters"]["properties"]["seconds"]["maximum"] == 3
    assert tools["browser_wait"]["parameters"]["properties"]["seconds"]["exclusiveMinimum"] == 0
    assert tools["browser_fill"]["parameters"]["properties"]["text"]["maxLength"] == 16384
    assert tools["browser_click"]["parameters"]["properties"]["bid"]["maxLength"] == 80
    assert tools["browser_press"]["parameters"]["properties"]["key"]["enum"] == [
        "Enter", "Tab", "Escape", "ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "Space"]
    assert tools["browser_scroll"]["parameters"]["properties"]["direction"]["enum"] == [
        "up", "down", "left", "right"]
    assert "700 pixels" in tools["browser_scroll"]["description"]
    assert "3 seconds" in tools["browser_wait"]["description"]
    tools["browser_fill"]["parameters"]["properties"]["text"]["maxLength"] = 1
    fresh = next(tool for tool in browser_tools() if tool["function"]["name"] == "browser_fill")
    assert fresh["function"]["parameters"]["properties"]["text"]["maxLength"] == 16384


@pytest.mark.parametrize("kind,arguments", ACTION_CASES)
async def test_each_flat_tool_maps_to_its_strict_action(kind, arguments):
    policy, events = await policy_with_reply(valid_reply(arguments, name=f"browser_{kind}"))
    try:
        await policy.prepare()
        action = (await policy.decide(observation(), [])).action
        assert action.model_dump() == {"kind": kind, **arguments}
        assert [event for event, _ in events] == ["policy_prepared", "inference_intent", "inference_result"]
    finally:
        await policy.close()


@pytest.mark.parametrize("kind,arguments", ACTION_CASES)
@pytest.mark.parametrize("supplied_kind", ["matching", "finish", None, True])
async def test_caller_kind_is_rejected_even_when_matching(kind, arguments, supplied_kind):
    arguments = {**arguments, "kind": kind if supplied_kind == "matching" else supplied_kind}
    policy, events = await policy_with_reply(valid_reply(arguments, name=f"browser_{kind}"))
    try:
        await policy.prepare()
        with pytest.raises(BrowserError, match="valid browser action"):
            await policy.decide(observation(), [])
        assert events[-1][0] == "inference_result"
    finally:
        await policy.close()


@pytest.mark.parametrize("name,arguments", [
    ("browser_action", {"kind": "finish"}), ("browser_shell", {}), ("finish", {}), (None, {}), ([], {}),
    ("browser_finish", None), ("browser_finish", []), ("browser_finish", "{}"),
    ("browser_finish", {"bid": "3"}), ("browser_click", {}), ("browser_click", {"bid": True}),
    ("browser_click", {"bid": 3}), ("browser_click", {"bid": "3", "text": "wrong action"}),
    ("browser_click", {"bid": "a" * 81}), ("browser_click", {"bid": "#css"}),
    ("browser_fill", {"bid": "3"}), ("browser_fill", {"bid": "3", "text": "a" * 16385}),
    ("browser_fill", {"bid": "3", "text": False}),
    ("browser_press", {"bid": "3", "key": "Control+R"}),
    ("browser_scroll", {"direction": "forward"}), ("browser_wait", {"seconds": 0.0}),
    ("browser_wait", {"seconds": 3.01}), ("browser_wait", {"seconds": True}),
    ("browser_wait", {"seconds": "1"}), ("browser_navigate", {"url": "file:///private/operator"}),
])
async def test_flat_tools_reject_invalid_or_mixed_arguments(name, arguments):
    reply = valid_reply(name=name)
    reply["message"]["tool_calls"][0]["function"]["arguments"] = arguments
    policy, events = await policy_with_reply(reply)
    try:
        await policy.prepare()
        with pytest.raises(BrowserError, match="valid browser action"):
            await policy.decide(observation(), [])
        assert events[-1][0] == "inference_result"
        assert json.loads(base64.b64decode(events[-1][1]["response_body_b64"])) == reply
    finally:
        await policy.close()


@pytest.mark.parametrize("message", [None, [], {}, {"role": "assistant", "content": ""},
    {"role": "assistant", "tool_calls": [None]},
    {"role": "assistant", "tool_calls": [{"function": None}]},
    {"role": "assistant", "tool_calls": [valid_reply()["message"]["tool_calls"][0]] * 2},
])
async def test_missing_malformed_or_multiple_calls_are_retained_and_rejected(message):
    policy, events = await policy_with_reply(valid_reply() | {"message": message})
    try:
        await policy.prepare()
        with pytest.raises(BrowserError, match="valid browser action"):
            await policy.decide(observation(), [])
        assert events[-1][0] == "inference_result"
    finally:
        await policy.close()


@pytest.mark.parametrize("reply", [None, [], "not an object", 1])
async def test_nonobject_reply_is_retained_and_rejected(reply):
    policy, events = await policy_with_reply(reply)
    try:
        await policy.prepare()
        with pytest.raises(BrowserError, match="valid browser action"):
            await policy.decide(observation(), [])
        assert events[-1][0] == "inference_result"
    finally:
        await policy.close()


async def test_failed_durable_intent_prevents_inference_request():
    policy, events = await policy_with_reply(valid_reply())
    try:
        await policy.prepare()

        def failed_record(kind, payload):
            if kind == "inference_intent":
                raise BrowserError("journal unavailable")
            events.append((kind, payload))

        policy.set_recorder(failed_record)
        with pytest.raises(BrowserError, match="journal unavailable"):
            await policy.decide(observation(), [])
        assert [event for event, _ in events] == ["policy_prepared"]
    finally:
        await policy.close()


@pytest.mark.parametrize("change", [
    {"done": False}, {"done_reason": "length"}, {"remote_host": "example.com"},
    {"model": "other"}, {"message": {"role": "assistant", "tool_calls": []}},
    {"message": {"role": "assistant", "tool_calls": [{"function": {"name": "shell", "arguments": {}}}]}},
])
async def test_local_policy_retains_rejected_reply(change):
    policy, events = await policy_with_reply(valid_reply() | change)
    try:
        await policy.prepare()
        with pytest.raises(BrowserError, match="valid browser action"):
            await policy.decide(observation(), [])
        assert events[-1][0] == "inference_result"
    finally:
        await policy.close()


async def test_local_policy_rejects_remote_or_missing_local_model_without_chat():
    policy, events = await policy_with_reply(valid_reply(), model_entry={
        "name": "qwen3:8b", "digest": DIGEST, "size": 100, "remote_host": "remote"})
    try:
        with pytest.raises(BrowserError, match="existing local model"):
            await policy.prepare()
        assert events == []
    finally:
        await policy.close()


async def test_failed_prepare_and_changed_model_cannot_make_inference_calls():
    policy, events = await policy_with_reply(valid_reply())
    try:
        with pytest.raises(BrowserError):
            await policy.decide(observation(), [])
        await policy.prepare()
        policy.model = "alias-with-the-same-digest"
        with pytest.raises(BrowserError):
            await policy.decide(observation(), [])
        policy.model = "missing-model"
        with pytest.raises(BrowserError):
            await policy.prepare()
        assert policy.digest is None
        assert policy.prepared_model is None
        with pytest.raises(BrowserError):
            await policy.decide(observation(), [])
        assert not any(kind == "inference_intent" for kind, _ in events)
    finally:
        await policy.close()


async def test_reference_uses_public_discovery_and_does_not_count_textbox_as_persisted_comment():
    policy = BrowserReferencePolicy(PROMPT)
    assert (await policy.decide(observation(), [])).action.bid == "3"
    text = ("StaticText 'Deployment reference: REL-2026-1042'\n"
            "[5] textbox 'Write a comment' value='Release checklist verified; ready for closure.'\n"
            "[6] button 'Comment'\n[7] button 'Close issue'")
    history = [{"action": {"kind": "fill", "bid": "5", "text": policy.comment}, "result": {"ok": True}}]
    decision = await policy.decide(observation(text, "http://127.0.0.1:8929/root/release-operations/-/issues/2"), history)
    assert decision.action.kind == "click"
    assert decision.action.bid == "6"


async def test_reference_requires_persisted_text_before_closing():
    policy = BrowserReferencePolicy(PROMPT)
    text = ("StaticText 'Deployment reference: REL-2026-1042'\n"
            "StaticText 'Release checklist verified; ready for closure.'\n"
            "[6] button 'Comment'\n[7] button 'Close issue'")
    history = [{"action": {"kind": "click", "bid": "6"}, "result": {"ok": True}}]
    assert (await policy.decide(observation(text, "http://127.0.0.1:8929/root/release-operations/-/issues/2"), history)).action.bid == "7"


async def test_reference_submits_draft_static_text_even_after_intervening_scroll():
    policy = BrowserReferencePolicy(PROMPT)
    text = ("StaticText 'Deployment reference: REL-2026-1042'\n"
            "[5] textbox 'Add a reply' value='Release checklist verified; ready for closure.'\n"
            "\tStaticText 'Release checklist verified; ready for closure.'\n"
            "[6] button 'Comment'\n[7] button 'Comment and close issue'")
    history = [{"action": {"kind": "scroll", "direction": "up"}, "result": {"ok": True}}]
    decision = await policy.decide(observation(text, "http://127.0.0.1:8929/root/release-operations/-/issues/2"), history)
    assert decision.action.kind == "click"
    assert decision.action.bid == "6"
    assert next(node for node in ax_nodes(text) if node.get("in_textbox"))["name"] == policy.comment


async def test_reference_does_not_repeat_comment_submission_while_ui_updates():
    policy = BrowserReferencePolicy(PROMPT)
    text = ("StaticText 'Deployment reference: REL-2026-1042'\n"
            "[5] textbox 'Add a reply' value='Release checklist verified; ready for closure.'\n"
            "\tStaticText 'Release checklist verified; ready for closure.'\n"
            "[6] button 'Comment'\n[7] button 'Close issue'")
    url = "http://127.0.0.1:8929/root/release-operations/-/issues/2"
    decision = await policy.decide(observation(text, url), [])
    assert decision.action.bid == "6"
    history = [{"action": decision.action.model_dump(), "result": {"ok": True}}]
    assert (await policy.decide(observation(text, url), history)).action.kind == "wait"
    posted = text + "\nStaticText 'Release checklist verified; ready for closure.'"
    assert (await policy.decide(observation(posted, url), history)).action.bid == "7"


def test_ax_parser_handles_quotes_as_literals_not_code():
    assert ax_nodes("[3] link \"O'Reilly project\", visible") == [
        {"bid": "3", "role": "link", "name": "O'Reilly project"}]
    assert ax_nodes("[3] link __import__('os').system('false')") == []


async def test_reference_discovers_identically_named_distractors_without_hidden_issue_ids():
    policy = BrowserReferencePolicy(PROMPT.replace("Add exactly:", "Add exactly this comment:"))
    url = "http://127.0.0.1:8929/root/release-operations/-/issues"
    listing = observation("[8] link 'Release checklist review'\n[10] link 'Release checklist review'", url)
    assert (await policy.decide(listing, [])).action.bid == "8"
    wrong = observation("StaticText 'Deployment reference: REL-2026-1043'", url + "/3")
    assert (await policy.decide(wrong, [])).action.url == url
    assert (await policy.decide(listing, [])).action.bid == "10"


async def test_reference_discovers_member_projects_when_default_tab_is_empty():
    policy = BrowserReferencePolicy(PROMPT)
    assert (await policy.decide(observation("[8] tab 'Contributed 0'\n[9] tab 'Member 1'"), [])).action.bid == "9"
    member = observation("[10] link 'Release Operations'\n[11] link 'Work items'",
                         "http://127.0.0.1:8929/dashboard/projects/member")
    assert (await policy.decide(member, [])).action.bid == "10"


async def test_reference_preserves_queried_work_item_list_url():
    policy = BrowserReferencePolicy(PROMPT)
    url = "http://127.0.0.1:8929/root/release-operations/-/work_items?state=opened"
    listing = observation("[8] link 'Release checklist review'", url)
    assert (await policy.decide(listing, [])).action.bid == "8"
    wrong = observation("StaticText 'Deployment reference: REL-2026-1043'", url.split("?")[0] + "/3")
    assert (await policy.decide(wrong, [])).action.url == url


async def test_reference_uses_side_panel_and_plain_text_editor_without_popup():
    policy = BrowserReferencePolicy(PROMPT)
    url = "http://127.0.0.1:8929/root/release-operations/-/work_items?state=opened"
    await policy.decide(observation("[8] link 'Release checklist review'", url), [])
    panel = observation("[10] link 'Open in full page'\nStaticText 'Deployment reference: REL-2026-1043'", url + "&show=opaque")
    assert (await policy.decide(panel, [])).action.url == url
    wrong = observation("StaticText 'Deployment reference: REL-2026-1043'", url.split("?")[0] + "/3")
    assert (await policy.decide(wrong, [])).action.url == url
    target = observation("StaticText 'Deployment reference: REL-2026-1042'\n[12] button 'Switch to plain text editing'",
                         url.split("?")[0] + "/2")
    assert (await policy.decide(target, [])).action.bid == "12"
    loading = observation("StaticText 'Loading'", url.split("?")[0] + "/1")
    assert (await policy.decide(loading, [])).action.kind == "wait"
    loading_target = observation("StaticText 'Deployment reference: REL-2026-1042'\n[15] image 'Loading'",
                                 url.split("?")[0] + "/2")
    assert (await policy.decide(loading_target, [])).action.kind == "wait"
    reply = observation("StaticText 'Deployment reference: REL-2026-1042'\n[16] textbox 'Add a reply'",
                        url.split("?")[0] + "/2")
    decision = await policy.decide(reply, [])
    assert decision.action.kind == "fill"
    assert decision.action.bid == "16"
    assert decision.action.text == policy.comment


async def test_local_policy_preserves_bounded_http_failure_body():
    policy, events = await policy_with_reply(valid_reply())
    try:
        await policy.prepare()
        await policy.client.aclose()
        policy.client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(500, stream=RawStream({"error": "local daemon rejected schema"}))))
        with pytest.raises(BrowserError, match="invalid HTTP"):
            await policy._read("POST", "/api/chat", b"{}")
        assert events[-1][0] == "inference_transport_failure"
        assert json.loads(base64.b64decode(events[-1][1]["partial_body_b64"]))["error"]
        assert events[-1][1]["complete_reply_certified"] is False
    finally:
        await policy.close()


def triage_control():
    return BrowserReferencePolicy("Incident reference: INC-2026-0217", triage=True)


def triage_closed(*, assigned=False, classified=False):
    assignee = "\t[2107] link '@casey-oncall'\n" if assigned else "\tStaticText 'None'\n"
    labels = "\t[1155] link 'incident'\n" + ("\t[1157] link 'severity::2'\n" if classified else "")
    return ("StaticText 'Incident reference: INC-2026-0217'\n"
            "[100] heading 'Assignee'\n[101] button 'Edit'\n"
            "StaticText '@casey-oncall'\nStaticText 'severity::2'\n"
            "[1137] region 'Sidebar'\n"
            "\t[1143] heading 'Assignee'\n\t\tInlineTextBox 'Assignee'\n"
            "\t[1144] button 'Edit'\n" + assignee
            + "\t[1150] heading 'Labels'\n\t\tInlineTextBox 'Labels'\n"
            "\t[1151] button 'Edit'\n" + labels
            + "\t[1162] heading 'Milestone'\n\t[1163] button 'Edit'\n"
            "[1191] region 'Activity'\n\t[1192] button 'Apply'\n")


def triage_picker(*, field="assignee", bid="2049", selected=False, apply_bid="1446", search_bid="1462",
                  option_name=None, option_role="option"):
    if field == "labels":
        return triage_labels_picker(bid=bid, selected=selected, apply_bid=apply_bid,
                                    search_bid=search_bid, option_role=option_role)
    # Assignee structure comes from observed AX.
    option_name = option_name or ("Casey On-call @casey-oncall" if field == "assignee" else "severity::2")
    state = "selected" if option_role == "option" else "checked"
    prefix = f"[{bid}] " if bid is not None else ""
    flag = "" if selected is None else f", {state}={selected}"
    picker = (f"\t[{apply_bid}] button 'Apply'\n"
              "\t[1449] button 'No assignees'\n"
              f"\t[{search_bid}] combobox 'Search', expanded=True\n"
              f"\t[2023] listbox 'Select {'assignee' if field == 'assignee' else 'labels'}'\n"
              f"\t\t{prefix}{option_role} {option_name!r}{flag}\n"
              "\t\t\tStaticText '@casey-oncall'\n"
              "\t\t[2060] option 'Casey On-call Backup @casey-backup', selected=False\n")
    text = triage_closed(assigned=field == "labels")
    edit = "\t[1144] button 'Edit'\n\tStaticText 'None'\n" if field == "assignee" else "\t[1151] button 'Edit'\n\t[1155] link 'incident'\n"
    return text.replace(edit, picker)


def triage_labels_picker(*, bid="2049", selected=False, apply_bid="1446", search_bid="1462",
                         option_role="option", prior=("incident",), search_value=None, refreshed=True):
    selected_names = prior + (("severity::2",) if selected is True and refreshed else ())
    prefix = f"[{bid}] " if bid is not None else ""
    flag = "" if selected is None else f", selected={selected}"
    value = "" if search_value is None else f" value={search_value!r}"
    selected_rows = "".join(f"\t\t\t[7{index}] option {name!r}, selected=True\n"
                            for index, name in enumerate(selected_names))
    all_rows = "".join(f"\t\t\t[8{index}] option {name!r}, selected=True\n"
                       for index, name in enumerate(prior))
    picker = (f"\t[{apply_bid}] button 'Apply'\n"
              f"\t[{search_bid}] combobox 'Search'{value}, expanded=True\n"
              "\t[2023] listbox 'Select labels', multiselectable=True\n"
              "\t\t[2155] group 'Selected'\n" + selected_rows
              + "\t\t[2163] group 'All'\n" + all_rows
              + f"\t\t\t{prefix}{option_role} 'severity::2'{flag}\n"
              "\t\t\t\tStaticText 'severity::2'\n"
              "\t\t\tInlineTextBox 'severity::3'\n")
    return triage_closed(assigned=True).replace("\t[1151] button 'Edit'\n\t[1155] link 'incident'\n", picker)


def triage_observation(text):
    return observation(text, "http://127.0.0.1:8929/root/incident-operations/-/work_items/2")


def triage_activity(text, *, username="@casey-oncall", date="now", comment=False):
    row = ("\t\t[2114] listitem ''\n\t\t\t[2120] link 'Workflow Agent'\n"
           "\t\t\tStaticText 'assigned to'\n"
           f"\t\t\t[2125] link '{username}'\n\t\t\t[2127] link '{date}'\n")
    if comment:
        row = "\t\t[2114] listitem ''\n\t\t\tparagraph ''\n" + "\n".join(
            "\t" + line for line in row.splitlines()[1:]) + "\n"
    return text + "[1500] heading 'Activity'\n\t[1557] list ''\n" + row


async def test_triage_v4_actual_picker_no_bid_waits_then_selects_current_bid():
    policy = triage_control()
    opened = await policy.decide(triage_observation(triage_closed()), [])
    assert opened.action.bid == "1144" and opened.evidence["protocol"] == "public-ax-triage-control-v7"
    transient = await policy.decide(triage_observation(triage_picker(bid=None)), [])
    assert transient.action.kind == "wait"
    selected = await policy.decide(triage_observation(triage_picker(bid="3001")), [])
    assert selected.action.kind == "click" and selected.action.bid == "3001"
    # The unselected option and child username never imply persisted membership.
    pending = await policy.decide(triage_observation(triage_picker(bid="3002")), [])
    assert pending.action.kind == "wait"


async def test_triage_apply_requires_observed_selection_then_closed_field_confirmation():
    policy = triage_control()
    assert (await policy.decide(triage_observation(triage_picker()), [])).action.bid == "2049"
    applied = await policy.decide(triage_observation(triage_picker(selected=True, apply_bid="4001")), [])
    assert applied.action.bid == "4001"
    still_open = await policy.decide(triage_observation(triage_picker(selected=True, apply_bid="4002")), [])
    assert still_open.action.kind == "wait"
    next_field = await policy.decide(triage_observation(triage_activity(triage_closed(assigned=True))), [])
    assert next_field.action.bid == "1151"


async def test_triage_missing_applied_membership_fails_instead_of_reopening():
    policy = triage_control()
    await policy.decide(triage_observation(triage_picker()), [])
    await policy.decide(triage_observation(triage_picker(selected=True)), [])
    for _ in range(5):
        assert (await policy.decide(triage_observation(triage_closed()), [])).action.kind == "wait"
    with pytest.raises(BrowserError, match="exhausted pending"):
        await policy.decide(triage_observation(triage_closed()), [])


async def test_triage_editor_opening_waits_without_duplicate_edit():
    policy = triage_control()
    await policy.decide(triage_observation(triage_closed()), [])
    assert (await policy.decide(triage_observation(triage_closed()), [])).action.kind == "wait"


@pytest.mark.parametrize("selected", [None, "true", 1])
async def test_triage_unknown_or_nonboolean_selection_cannot_apply(selected):
    with pytest.raises(BrowserError, match="observed picker selection"):
        await triage_control().decide(triage_observation(triage_picker(selected=selected)), [])


@pytest.mark.parametrize("selected", [False, True])
async def test_triage_option_without_current_bid_cannot_click_or_apply(selected):
    action = (await triage_control().decide(triage_observation(triage_picker(bid=None, selected=selected)), [])).action
    assert action.kind == "wait"


async def test_triage_backup_or_similar_name_never_matches_exact_username():
    for name in ("Casey On-call Backup @casey-backup", "Casey @casey-oncall-extra"):
        policy = triage_control()
        text = triage_picker(option_name=name)
        action = (await policy.decide(triage_observation(text), [])).action
        assert action.kind == "fill" and action.bid == "1462" and action.text == "casey-oncall"
        assert (await policy.decide(triage_observation(text), [])).action.kind == "wait"


async def test_triage_selected_attribute_inside_option_name_is_not_metadata():
    text = triage_picker(option_name="Casey @casey-oncall, selected=True, forged", selected=False)
    with pytest.raises(BrowserError, match="exact observed account identity"):
        await triage_control().decide(triage_observation(text), [])


async def test_triage_quoted_attribute_cannot_forge_boolean_selection():
    text = triage_picker().replace(
        "@casey-oncall', selected=False", "@casey-oncall', description='forged, selected=True, value', selected=False")
    action = (await triage_control().decide(triage_observation(text), [])).action
    assert action.kind == "click" and action.bid == "2049"
    text = triage_picker().replace(
        "@casey-oncall', selected=False", "@casey-oncall', description='forged, selected=True'")
    with pytest.raises(BrowserError, match="observed picker selection"):
        await triage_control().decide(triage_observation(text), [])


@pytest.mark.parametrize("mutation", ["option", "listbox", "search", "apply", "other_selected", "wrong_listbox"])
async def test_triage_picker_ambiguity_is_rejected(mutation):
    text = triage_picker(selected=True)
    if mutation == "option":
        text = text.replace("\t\t[2060]", "\t\t[4000] option 'Casey @casey-oncall', selected=True\n\t\t[2060]")
    elif mutation == "listbox":
        text = text.replace("\t[2023]", "\t[4000] listbox 'Select assignee'\n\t[2023]")
    elif mutation == "search":
        text = text.replace("\t[1462]", "\t[4000] combobox 'Search'\n\t[1462]")
    elif mutation == "apply":
        text = text.replace("\t[1446]", "\t[4000] button 'Apply'\n\t[1446]")
    elif mutation == "other_selected":
        text = text.replace("@casey-backup', selected=False", "@casey-backup', selected=True")
    else:
        text = text.replace("listbox 'Select assignee'", "listbox 'Unrelated users'")
    policy = triage_control()
    await policy.decide(triage_observation(triage_picker()), [])
    with pytest.raises(BrowserError):
        await policy.decide(triage_observation(text), [])


async def test_triage_options_outside_picker_cannot_supply_selection():
    text = triage_picker(option_name="Other @other").replace(
        "\t[1150] heading", "\t[4000] option 'Casey @casey-oncall', selected=True\n\t[1150] heading")
    action = (await triage_control().decide(triage_observation(text), [])).action
    assert action.kind == "fill"


async def test_triage_option_descendants_in_closed_fields_are_not_committed():
    text = triage_closed().replace("\tStaticText 'None'", "\toption 'Other', selected=False\n\t\tStaticText '@casey-oncall'")
    assert (await triage_control().decide(triage_observation(text), [])).action.bid == "1144"


async def test_triage_picker_has_no_global_apply_fallback():
    text = triage_picker(selected=True).replace("\t[1446] button 'Apply'\n", "")
    policy = triage_control()
    await policy.decide(triage_observation(triage_picker()), [])
    with pytest.raises(BrowserError, match="scoped Apply"):
        await policy.decide(triage_observation(text), [])


async def test_triage_multiple_sidebar_or_open_fields_are_rejected():
    text = triage_picker() + "[5000] region 'Sidebar'\n"
    with pytest.raises(BrowserError, match="Sidebar region"):
        await triage_control().decide(triage_observation(text), [])
    text = triage_picker().replace("\t[1151] button 'Edit'", "\t[1151] combobox 'Search'")
    with pytest.raises(BrowserError, match="scoped active picker"):
        await triage_control().decide(triage_observation(text), [])


async def test_triage_field_switch_while_editor_active_is_rejected():
    policy = triage_control()
    await policy.decide(triage_observation(triage_closed()), [])
    with pytest.raises(BrowserError, match="scoped active picker"):
        await policy.decide(triage_observation(triage_picker(field="labels")), [])


async def test_triage_grouped_label_picker_exactness_and_apply():
    policy = await opened_label_control()
    text = triage_labels_picker(selected=None).replace(
        "\t\t\tInlineTextBox", "\t\t\t[5000] option 'severity::20', selected=False\n\t\t\tInlineTextBox")
    assert (await policy.decide(triage_observation(text), [])).action.bid == "2049"
    selected = triage_labels_picker(selected=True)
    assert (await policy.decide(triage_observation(selected), [])).action.bid == "1446"
    assert (await policy.decide(triage_observation(triage_closed(assigned=True, classified=True)), [])).action.kind == "finish"


async def test_triage_already_correct_noop_and_state_are_instance_local():
    first, second = triage_control(), triage_control()
    await first.decide(triage_observation(triage_closed()), [])
    decision = await second.decide(triage_observation(triage_closed(assigned=True, classified=True)), [])
    assert decision.action.kind == "finish" and second.triage_edit is None


def triage_display_closed(*, classified=False):
    return triage_closed(assigned=True, classified=classified).replace("link '@casey-oncall'", "link 'Casey On-call'")


def triage_inspection_picker(*, search_bid="9999"):
    picker = (f"\t[{search_bid}] combobox 'Search'\n"
              "\t[2081] listbox 'Select assignee', multiselectable=False\n"
              "\t\t[2085] group 'Selected'\n"
              "\t\t\t[2087] option 'Casey On-call @casey-oncall', selected=True\n"
              "\t\t[2098] group 'All users'\n"
              "\t\t\t[2100] option 'Workflow Agent @workflow-agent'\n"
              "\t\t\t[2111] option 'Administrator @root'\n")
    return triage_display_closed(classified=True).replace(
        "\t[1144] button 'Edit'\n\t[2107] link 'Casey On-call'\n", picker)


def completed_action(history, decision):
    history.append({"step": len(history), "action": decision.action.model_dump(), "result": {"ok": True}})


async def test_triage_v4_observed_immediate_commit_requires_new_activity_then_switches_field():
    policy = triage_control()
    assert (await policy.decide(triage_observation(triage_closed()), [])).action.bid == "1144"
    assert (await policy.decide(triage_observation(triage_picker()), [])).action.bid == "2049"
    assert (await policy.decide(triage_observation(triage_display_closed()), [])).action.kind == "wait"
    confirmed = await policy.decide(triage_observation(triage_activity(triage_display_closed())), [])
    assert confirmed.action.bid == "1151" and policy.triage_confirmed_assignee


@pytest.mark.parametrize("phase", ["selecting", "applying"])
async def test_triage_v4_closed_membership_and_activity_are_both_required(phase):
    policy = triage_control()
    await policy.decide(triage_observation(triage_picker()), [])
    if phase == "applying":
        await policy.decide(triage_observation(triage_picker(selected=True)), [])
    assert (await policy.decide(triage_observation(triage_activity(triage_closed())), [])).action.kind == "wait"
    assert (await policy.decide(triage_observation(triage_activity(triage_display_closed())), [])).action.bid == "1151"


@pytest.mark.parametrize("mutation", ["stale", "wrong_user", "comment", "background", "duplicate_heading"])
async def test_triage_v4_stale_spoofed_or_unscoped_activity_cannot_confirm(mutation):
    policy = triage_control()
    before = triage_activity(triage_picker()) if mutation == "stale" else triage_picker()
    await policy.decide(triage_observation(before), [])
    text = triage_activity(triage_display_closed(), username="@casey-backup" if mutation == "wrong_user" else "@casey-oncall",
                           comment=mutation == "comment")
    if mutation == "background":
        text = text.replace("heading 'Activity'", "heading 'Background activity'")
    elif mutation == "duplicate_heading":
        with pytest.raises(BrowserError, match="one target Activity"):
            await policy.decide(triage_observation(text + "[5000] heading 'Activity'\n"), [])
        return
    for _ in range(5):
        assert (await policy.decide(triage_observation(text), [])).action.kind == "wait"
    with pytest.raises(BrowserError, match="exhausted pending"):
        await policy.decide(triage_observation(text), [])


async def test_triage_v4_already_correct_display_identity_inspected_and_dismissed_without_write():
    policy = triage_control()
    closed = triage_display_closed(classified=True)
    history = []
    opened = await policy.decide(triage_observation(closed), history)
    assert opened.action.bid == "1144"
    completed_action(history, opened)
    dismissed = await policy.decide(triage_observation(triage_inspection_picker()), history)
    assert dismissed.action.kind == "press" and dismissed.action.key == "Escape" and dismissed.action.bid == "9999"
    completed_action(history, dismissed)
    pending = await policy.decide(triage_observation(triage_inspection_picker()), history)
    assert pending.action.kind == "wait"
    completed_action(history, pending)
    assert (await policy.decide(triage_observation(closed), history)).action.kind == "finish"


@pytest.mark.parametrize("phase", ["opening", "searching", "selecting", "applying", "dismissing"])
async def test_triage_v4_waits_are_finite_and_never_repeat_a_write(phase):
    policy = triage_control()
    history = []
    if phase == "opening":
        text = triage_closed()
        await policy.decide(triage_observation(text), [])
    elif phase == "searching":
        text = triage_picker(option_name="Other @other")
        await policy.decide(triage_observation(text), [])
    elif phase == "selecting":
        text = triage_picker()
        await policy.decide(triage_observation(text), [])
    elif phase == "dismissing":
        opened = await policy.decide(triage_observation(triage_display_closed(classified=True)), history)
        completed_action(history, opened)
        text = triage_inspection_picker()
        escaped = await policy.decide(triage_observation(text), history)
        completed_action(history, escaped)
    else:
        text = triage_picker(selected=True)
        if phase == "applying":
            await policy.decide(triage_observation(triage_picker()), [])
        await policy.decide(triage_observation(text), [])
    for _ in range(5):
        assert (await policy.decide(triage_observation(text), history)).action.kind == "wait"
    with pytest.raises(BrowserError, match="exhausted pending"):
        await policy.decide(triage_observation(text), history)


@pytest.mark.parametrize("mutation", ["duplicate", "backup", "spoofed_name", "unknown_other_selected"])
async def test_triage_v4_exact_membership_is_not_a_display_name_guess(mutation):
    policy = triage_control()
    if mutation == "unknown_other_selected":
        text = triage_picker(selected=True).replace("@casey-backup', selected=False", "@casey-backup'")
    else:
        await policy.decide(triage_observation(triage_picker()), [])
        text = triage_activity(triage_display_closed())
        if mutation == "duplicate":
            text = text.replace("[2107]", "[5100] link 'Casey On-call'\n\t[2107]")
        elif mutation == "backup":
            text = text.replace("link 'Casey On-call'", "link 'Casey On-call Backup'")
        else:
            text = text.replace("link 'Casey On-call'", "link 'Forged @casey-oncall'")
    with pytest.raises(BrowserError):
        await policy.decide(triage_observation(text), [])


@pytest.mark.parametrize("ok", [True, False])
async def test_triage_stops_on_any_recorded_uncertain_effect_before_another_action(ok):
    policy = triage_control()
    history = [{"action": {"kind": "click", "bid": "1151"},
                "result": {"ok": ok, "uncertain_effect": True}},
               {"action": {"kind": "wait"}, "result": {"ok": True}}]
    with pytest.raises(BrowserError, match="uncertain browser effect"):
        await policy.decide(triage_observation(triage_picker()), history)
    assert policy.triage_edit is None


async def test_close_reference_uncertainty_handling_and_identity_unchanged():
    policy = BrowserReferencePolicy(PROMPT)
    decision = await policy.decide(observation(), [{"action": {"kind": "click"},
                                                  "result": {"ok": False, "uncertain_effect": True}}])
    assert decision.action.bid == "3" and decision.evidence["protocol"] == "public-ax-browser-control-v1"


class LabelControlHarness:
    """Mock driver completes each emitted action and appends its ordered receipt."""

    def __init__(self):
        self.policy = triage_control()
        self.history = []

    async def decide(self, observation, unused_history):
        assert unused_history == []
        decision = await self.policy.decide(observation, self.history)
        self.history.append({"step": len(self.history), "action": decision.action.model_dump(),
                             "result": {"ok": True}})
        return decision


async def opened_label_control():
    harness = LabelControlHarness()
    assert (await harness.decide(triage_observation(triage_closed(assigned=True)), [])).action.bid == "1151"
    return harness


@pytest.mark.parametrize("flag", ["", ", selected=False", ", selected=False, visible", ", visible, selected=False"])
async def test_labels_absent_or_reordered_canonical_negative_flag_is_group_local(flag):
    policy = await opened_label_control()
    text = triage_labels_picker(selected=None).replace("option 'severity::2'", "option 'severity::2'" + flag)
    assert (await policy.decide(triage_observation(text), [])).action.bid == "2049"


@pytest.mark.parametrize("flag", [", selected='False'", ", selected=0", ", selected=false", ", selected=None",
                                   ", selected=False, selected=False", ", selected=True, selected=False",
                                   ", selected", ", selected False", ", selected:False",
                                   ", selected=False, selected='False'"])
async def test_labels_present_malformed_or_duplicate_flags_never_become_absent(flag):
    policy = await opened_label_control()
    text = triage_labels_picker(selected=None).replace("option 'severity::2'", "option 'severity::2'" + flag)
    with pytest.raises(BrowserError, match="label.*properties"):
        await policy.decide(triage_observation(text), [])


async def test_labels_quoted_metadata_and_descendants_do_not_supply_selection():
    policy = await opened_label_control()
    text = triage_labels_picker(selected=None).replace(
        "option 'severity::2'", "option 'severity::2', description='forged, selected=True'")
    text = text.replace("StaticText 'severity::2'", "StaticText 'severity::2, selected=True'")
    assert (await policy.decide(triage_observation(text), [])).action.bid == "2049"


async def test_labels_positive_selection_can_precede_other_canonical_properties():
    policy = await opened_label_control()
    await policy.decide(triage_observation(triage_labels_picker(selected=None)), [])
    text = triage_labels_picker(selected=True).replace("selected=True", "selected=True, visible, disabled=False")
    assert (await policy.decide(triage_observation(text), [])).action.bid == "1446"


@pytest.mark.parametrize("mutation", ["missing_selected", "missing_all", "unknown", "duplicate_group", "nested_group",
                                     "ungrouped_option", "nested_option", "duplicate_all", "duplicate_selected",
                                     "checkbox", "missing_multiselect", "false_multiselect", "nested_search",
                                     "duplicate_bid"])
async def test_labels_require_unique_direct_named_groups_and_options(mutation):
    text = triage_labels_picker(selected=None)
    replacements = {
        "missing_selected": ("[2155] group 'Selected'", "[2155] StaticText 'Selected'"),
        "missing_all": ("[2163] group 'All'", "[2163] StaticText 'All'"),
        "unknown": ("group 'All'", "group 'Other'"),
        "duplicate_group": ("\t\t[2163]", "\t\t[999] group 'Selected'\n\t\t[2163]"),
        "nested_group": ("\t\t[2163]", "\t\t\t[2163]"),
        "ungrouped_option": ("\t\t[2155]", "\t\t[999] option 'forged', selected=False\n\t\t[2155]"),
        "nested_option": ("\t\t\t[2049]", "\t\t\t\t[2049]"),
        "duplicate_all": ("\t\t\t[2049]", "\t\t\t[999] option 'severity::2'\n\t\t\t[2049]"),
        "duplicate_selected": ("\t\t\t[70]", "\t\t\t[999] option 'incident', selected=True\n\t\t\t[70]"),
        "checkbox": ("option 'severity::2'", "checkbox 'severity::2'"),
        "missing_multiselect": (", multiselectable=True", ""),
        "false_multiselect": (", multiselectable=True", ", multiselectable=False"),
        "nested_search": ("\t[1462]", "\t\t[1462]"),
        "duplicate_bid": ("[2049] option", "[80] option"),
    }
    text = text.replace(*replacements[mutation])
    policy = await opened_label_control()
    with pytest.raises(BrowserError):
        await policy.decide(triage_observation(text), [])


@pytest.mark.parametrize("mutation", ["selected_absent", "selected_false", "all_absent", "all_false",
                                     "all_true_extra", "selected_missing_all", "prior_omitted"])
async def test_labels_selected_all_and_prior_closed_membership_must_agree(mutation):
    text = triage_labels_picker(selected=None)
    replacements = {
        "selected_absent": ("[70] option 'incident', selected=True", "[70] option 'incident'"),
        "selected_false": ("[70] option 'incident', selected=True", "[70] option 'incident', selected=False"),
        "all_absent": ("[80] option 'incident', selected=True", "[80] option 'incident'"),
        "all_false": ("[80] option 'incident', selected=True", "[80] option 'incident', selected=False"),
        "all_true_extra": ("option 'severity::2'", "option 'severity::2', selected=True"),
        "selected_missing_all": ("[80] option 'incident', selected=True", "[80] option 'other', selected=False"),
        "prior_omitted": ("\t\t\t[70] option 'incident', selected=True\n", ""),
    }
    text = text.replace(*replacements[mutation])
    if mutation == "prior_omitted":
        text = text.replace("[80] option 'incident', selected=True", "[80] option 'incident', selected=False")
    policy = await opened_label_control()
    with pytest.raises(BrowserError):
        await policy.decide(triage_observation(text), [])


@pytest.mark.parametrize("mutation", ["search", "malformed_search", "loading", "busy", "missing_target", "name_spoof"])
async def test_labels_never_search_or_infer_membership_from_filtered_or_missing_inventory(mutation):
    text = triage_labels_picker(selected=None)
    replacements = {
        "search": ("combobox 'Search'", "combobox 'Search' value='severity'"),
        "malformed_search": ("combobox 'Search'", "combobox 'Search' value=False"),
        "loading": ("\t[2023]", "\tStaticText 'Loading...'\n\t[2023]"),
        "busy": ("multiselectable=True", "multiselectable=True, busy=True"),
        "missing_target": ("option 'severity::2'", "option 'severity::20'"),
        "name_spoof": ("option 'severity::2'", "option 'severity::2, selected=True'"),
    }
    text = text.replace(*replacements[mutation])
    policy = await opened_label_control()
    if mutation in ("missing_target", "name_spoof"):
        for _ in range(5):
            assert (await policy.decide(triage_observation(text), [])).action.kind == "wait"
        with pytest.raises(BrowserError, match="exhausted pending"):
            await policy.decide(triage_observation(text), [])
    else:
        with pytest.raises(BrowserError):
            await policy.decide(triage_observation(text), [])


async def test_labels_delayed_inventory_waits_once_per_observation_then_uses_current_apply():
    policy = await opened_label_control()
    assert (await policy.decide(triage_observation(triage_labels_picker(selected=None)), [])).action.bid == "2049"
    assert (await policy.decide(triage_observation(triage_labels_picker(bid="5000", selected=None)), [])).action.kind == "wait"
    action = (await policy.decide(triage_observation(triage_labels_picker(bid="5001", selected=True,
                                                                         apply_bid="6000")), [])).action
    assert action.bid == "6000" and action.bid != "71"
    assert (await policy.decide(triage_observation(triage_labels_picker(selected=True)), [])).action.kind == "wait"
    assert (await policy.decide(triage_observation(triage_closed(assigned=True, classified=True)), [])).action.kind == "finish"


@pytest.mark.parametrize("phase", ["opening", "selecting", "applying"])
async def test_labels_each_delayed_transition_has_five_waits_without_repeated_write(phase):
    policy = await opened_label_control()
    text = triage_labels_picker(bid=None, selected=None)
    if phase != "opening":
        await policy.decide(triage_observation(triage_labels_picker(selected=None)), [])
        text = triage_labels_picker(selected=None)
    if phase == "applying":
        await policy.decide(triage_observation(triage_labels_picker(selected=True)), [])
        text = triage_labels_picker(selected=True)
    for _ in range(5):
        assert (await policy.decide(triage_observation(text), [])).action.kind == "wait"
    with pytest.raises(BrowserError, match="exhausted pending"):
        await policy.decide(triage_observation(text), [])


@pytest.mark.parametrize("phase", ["selecting", "applying"])
@pytest.mark.parametrize("mutation", ["removed", "extra"])
async def test_labels_pending_inventory_cannot_remove_or_add_other_labels(phase, mutation):
    policy = await opened_label_control()
    await policy.decide(triage_observation(triage_labels_picker(selected=None)), [])
    if phase == "applying":
        await policy.decide(triage_observation(triage_labels_picker(selected=True)), [])
    text = triage_labels_picker(selected=True, prior=() if mutation == "removed" else ("incident", "severity::3"))
    with pytest.raises(BrowserError, match="changed pending label membership"):
        await policy.decide(triage_observation(text), [])


@pytest.mark.parametrize("mutation", ["removed", "extra", "duplicate", "nested"])
async def test_labels_closed_confirmation_requires_exact_preserved_membership(mutation):
    policy = await opened_label_control()
    await policy.decide(triage_observation(triage_labels_picker(selected=None)), [])
    await policy.decide(triage_observation(triage_labels_picker(selected=True)), [])
    text = triage_closed(assigned=True, classified=True)
    if mutation == "removed":
        text = text.replace("\t[1155] link 'incident'\n", "")
    elif mutation == "extra":
        text = text.replace("\t[1155]", "\t[999] link 'severity::3'\n\t[1155]")
    elif mutation == "duplicate":
        text = text.replace("\t[1155]", "\t[999] link 'incident'\n\t[1155]")
    else:
        text = text.replace("\t[1155]", "\t\t[1155]")
    with pytest.raises(BrowserError, match="closed label membership"):
        await policy.decide(triage_observation(text), [])


async def test_labels_cannot_take_the_assignee_immediate_commit_shortcut():
    policy = await opened_label_control()
    await policy.decide(triage_observation(triage_labels_picker(selected=None)), [])
    with pytest.raises(BrowserError, match="selection and Apply before label closure"):
        await policy.decide(triage_observation(triage_closed(assigned=True, classified=True)), [])


async def test_labels_open_without_prior_closed_snapshot_is_rejected():
    with pytest.raises(BrowserError, match="prior closed label membership"):
        await triage_control().decide(triage_observation(triage_labels_picker()), [])


@pytest.mark.parametrize("mutation", ["duplicate", "background", "disabled", "missing_bid"])
async def test_labels_apply_must_be_current_unique_enabled_and_scoped(mutation):
    policy = await opened_label_control()
    await policy.decide(triage_observation(triage_labels_picker(selected=None)), [])
    text = triage_labels_picker(selected=True)
    replacements = {
        "duplicate": ("\t[1446]", "\t[999] button 'Apply'\n\t[1446]"),
        "background": ("\t[1446] button 'Apply'\n", ""),
        "disabled": ("[1446] button 'Apply'", "[1446] button 'Apply', disabled=True"),
        "missing_bid": ("[1446] button", "button"),
    }
    text = text.replace(*replacements[mutation])
    if mutation == "missing_bid":
        assert (await policy.decide(triage_observation(text), [])).action.kind == "wait"
    else:
        with pytest.raises(BrowserError):
            await policy.decide(triage_observation(text), [])


async def test_labels_explicit_empty_selected_group_is_not_a_missing_group():
    policy = triage_control()
    closed = triage_closed(assigned=True).replace("\t[1155] link 'incident'\n", "")
    await policy.decide(triage_observation(closed), [])
    assert (await policy.decide(triage_observation(triage_labels_picker(selected=None, prior=())), [])).action.bid == "2049"


@pytest.mark.parametrize("refreshed", [False, True])
async def test_labels_exact_accepted_click_all_draft_permits_one_apply_then_wait_or_closed(refreshed):
    harness = await opened_label_control()
    selected = await harness.decide(triage_observation(triage_labels_picker(selected=None)), [])
    assert selected.action.bid == "2049"
    draft = triage_labels_picker(selected=True, refreshed=refreshed, bid="5000", apply_bid="6000")
    applied = await harness.decide(triage_observation(draft), [])
    assert applied.action.bid == "6000"
    for _ in range(5):
        assert (await harness.decide(triage_observation(draft), [])).action.kind == "wait"
    assert [row["action"]["bid"] for row in harness.history if row["action"]["kind"] == "click"] == [
        "1151", "2049", "6000"]
    assert (await harness.decide(triage_observation(triage_closed(assigned=True, classified=True)), [])).action.kind == "finish"


async def test_labels_opening_rejects_the_observed_draft_exception_before_own_click():
    harness = await opened_label_control()
    with pytest.raises(BrowserError, match="initial label membership"):
        await harness.decide(triage_observation(triage_labels_picker(selected=True, refreshed=False)), [])


@pytest.mark.parametrize("phase", ["selecting", "applying"])
@pytest.mark.parametrize("observation_kind", ["draft", "closed", "missing_picker"])
@pytest.mark.parametrize("mutation", ["absent", "none_row", "list_row", "missing_step", "bool_step", "wrong_step",
                                     "missing_action", "none_action", "wrong_bid", "extra_action_key",
                                     "wrong_kind", "missing_result", "none_result", "list_result", "missing_ok",
                                     "false_ok", "numeric_ok", "string_ok", "uncertain", "string_uncertain",
                                     "numeric_uncertain", "null_uncertain", "shifted_slot"])
async def test_labels_exact_action_receipt_is_required_before_any_transition(phase, observation_kind, mutation):
    harness = await opened_label_control()
    await harness.decide(triage_observation(triage_labels_picker(selected=None)), [])
    if phase == "applying":
        await harness.decide(triage_observation(triage_labels_picker(selected=True, refreshed=False)), [])
    index = 1 if phase == "selecting" else 2
    row = harness.history[index]
    if mutation == "absent":
        harness.history.pop()
    elif mutation in ("none_row", "list_row"):
        harness.history[index] = None if mutation == "none_row" else []
    elif mutation == "missing_step":
        del row["step"]
    elif mutation in ("bool_step", "wrong_step"):
        row["step"] = True if mutation == "bool_step" else index - 1
    elif mutation == "missing_action":
        del row["action"]
    elif mutation == "none_action":
        row["action"] = None
    elif mutation == "wrong_bid":
        row["action"]["bid"] = "other-current-node"
    elif mutation == "extra_action_key":
        row["action"]["ignored"] = True
    elif mutation == "wrong_kind":
        row["action"] = {"kind": "wait", "seconds": 1}
    elif mutation == "missing_result":
        del row["result"]
    elif mutation in ("none_result", "list_result"):
        row["result"] = None if mutation == "none_result" else []
    elif mutation == "missing_ok":
        row["result"] = {}
    elif mutation in ("false_ok", "numeric_ok", "string_ok"):
        row["result"]["ok"] = {"false_ok": False, "numeric_ok": 1, "string_ok": "True"}[mutation]
    elif mutation in ("uncertain", "string_uncertain", "numeric_uncertain", "null_uncertain"):
        row["result"]["uncertain_effect"] = {
            "uncertain": True, "string_uncertain": "False", "numeric_uncertain": 0, "null_uncertain": None}[mutation]
    elif mutation == "shifted_slot":
        harness.history.insert(index, {"step": index, "action": {"kind": "wait", "seconds": 1}, "result": {"ok": True}})
        harness.history[index + 1]["step"] = index + 1
    if observation_kind == "draft":
        text = triage_labels_picker(selected=True, refreshed=False)
    elif observation_kind == "closed":
        text = triage_closed(assigned=True, classified=True)
    else:
        text = triage_labels_picker(selected=True).replace("listbox 'Select labels'", "StaticText 'Select labels'")
    with pytest.raises(BrowserError):
        await harness.decide(triage_observation(text), [])


async def test_labels_unrelated_or_later_success_cannot_replace_failed_target_receipt():
    harness = await opened_label_control()
    await harness.decide(triage_observation(triage_labels_picker(selected=None)), [])
    harness.history[1]["result"] = {"ok": False}
    harness.history.append({"step": 2, "action": {"kind": "click", "bid": "2049"}, "result": {"ok": True}})
    with pytest.raises(BrowserError, match="successful certain label action receipt"):
        await harness.decide(triage_observation(triage_labels_picker(selected=True, refreshed=False)), [])


async def test_labels_known_false_uncertainty_and_extra_driver_message_are_valid_receipt_metadata():
    harness = await opened_label_control()
    await harness.decide(triage_observation(triage_labels_picker(selected=None)), [])
    harness.history[1]["result"] = {"ok": True, "uncertain_effect": False, "message": "accepted"}
    assert (await harness.decide(triage_observation(triage_labels_picker(selected=True, refreshed=False)), [])).action.bid == "1446"


@pytest.mark.parametrize("phase", ["selecting", "applying"])
async def test_labels_receipts_remain_at_their_emitted_slots_during_finite_waits(phase):
    harness = await opened_label_control()
    await harness.decide(triage_observation(triage_labels_picker(selected=None)), [])
    if phase == "applying":
        await harness.decide(triage_observation(triage_labels_picker(selected=True, refreshed=False)), [])
    draft = triage_labels_picker(selected=phase == "applying", refreshed=False)
    for _ in range(5):
        assert (await harness.decide(triage_observation(draft), [])).action.kind == "wait"
    with pytest.raises(BrowserError, match="exhausted pending"):
        await harness.decide(triage_observation(draft), [])
    assert sum(row["action"]["kind"] == "click" for row in harness.history) == (3 if phase == "applying" else 2)


async def test_labels_refreshed_selected_requires_positive_all_counterpart_after_click():
    harness = await opened_label_control()
    await harness.decide(triage_observation(triage_labels_picker(selected=None)), [])
    text = triage_labels_picker(selected=True).replace("[2049] option 'severity::2', selected=True",
                                                    "[2049] option 'severity::2', selected=False")
    with pytest.raises(BrowserError, match="inconsistent label membership"):
        await harness.decide(triage_observation(text), [])


async def test_labels_partial_selected_set_is_not_a_valid_prior_or_expected_draft():
    harness = LabelControlHarness()
    closed = triage_closed(assigned=True).replace("[1155] link 'incident'", "[1155] link 'incident'\n\t[999] link 'keep'")
    await harness.decide(triage_observation(closed), [])
    await harness.decide(triage_observation(triage_labels_picker(prior=("incident", "keep"), selected=None)), [])
    text = triage_labels_picker(prior=("incident", "keep"), selected=True)
    text = text.replace("\t\t\t[71] option 'keep', selected=True\n", "")
    with pytest.raises(BrowserError, match="changed pending label membership"):
        await harness.decide(triage_observation(text), [])


async def test_labels_already_correct_prior_cannot_be_toggled_even_with_corrupted_opening_state():
    from dataclasses import replace

    harness = await opened_label_control()
    harness.policy.triage_edit = replace(harness.policy.triage_edit, prior_labels=frozenset({"incident", "severity::2"}))
    with pytest.raises(BrowserError, match="will not toggle a prior label"):
        await harness.decide(triage_observation(triage_labels_picker(selected=True)), [])


async def test_labels_missing_apply_receipt_blocks_generic_navigation_or_wait_too():
    harness = await opened_label_control()
    await harness.decide(triage_observation(triage_labels_picker(selected=None)), [])
    await harness.decide(triage_observation(triage_labels_picker(selected=True, refreshed=False)), [])
    harness.history.pop()
    with pytest.raises(BrowserError, match="emitted label action receipt"):
        await harness.policy.decide(observation("[3] link 'Incident Operations'"), harness.history)


async def test_labels_valid_apply_does_not_replace_the_required_target_receipt():
    harness = await opened_label_control()
    await harness.decide(triage_observation(triage_labels_picker(selected=None)), [])
    await harness.decide(triage_observation(triage_labels_picker(selected=True, refreshed=False)), [])
    harness.history[1]["result"]["ok"] = False
    with pytest.raises(BrowserError, match="successful certain label action receipt"):
        await harness.decide(triage_observation(triage_closed(assigned=True, classified=True)), [])
