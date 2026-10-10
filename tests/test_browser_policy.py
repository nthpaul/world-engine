import base64
import json

import httpx
import pytest

from world_engine.browser_contracts import BrowserError, BrowserObservation
from world_engine.browser_policy import BrowserReferencePolicy, OllamaBrowserPolicy, ax_nodes

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


async def policy_with_reply(reply, *, model_entry=None):
    policy = OllamaBrowserPolicy("qwen3:8b", PROMPT)
    await policy.client.aclose()
    events = []

    def transport(request):
        if request.url.path == "/api/tags":
            return response({"models": [model_entry or {"name": "qwen3:8b", "digest": DIGEST, "size": 100}]})
        if request.url.path == "/api/version":
            return response({"version": "test-local-daemon"})
        if request.url.path == "/api/show":
            return response({"capabilities": ["completion", "tools"]})
        if request.url.path == "/api/chat":
            assert events[-1][0] == "inference_intent"
            assert json.loads(request.content) == events[-1][1]["request_body"]
            return response(reply)
        raise AssertionError("unexpected request")

    policy.client = httpx.AsyncClient(transport=httpx.MockTransport(transport), trust_env=False)
    policy.set_recorder(lambda kind, payload: events.append((kind, payload)))
    return policy, events


def valid_reply(arguments=None):
    return {"model": "qwen3:8b", "done": True, "done_reason": "stop", "message": {"role": "assistant",
            "tool_calls": [{"function": {"name": "browser_action", "arguments": arguments or {"kind": "finish"}}}]},
            "prompt_eval_count": 42, "eval_count": 8}


async def test_local_policy_persists_exact_request_and_raw_reply_before_action():
    reply = valid_reply({"kind": "click", "bid": "3"})
    policy, events = await policy_with_reply(reply)
    try:
        await policy.prepare()
        decision = await policy.decide(observation(), [])
        assert decision.action.kind == "click"
        assert decision.action.bid == "3"
        assert [kind for kind, _ in events] == ["policy_prepared", "inference_intent", "inference_result"]
        assert json.loads(base64.b64decode(events[-1][1]["response_body_b64"])) == reply
        request = events[1][1]["request_body"]
        public = json.loads(request["messages"][1]["content"])
        assert "screenshot_artifact_id" not in public["observation"]
        assert public["observation"]["image_not_sent_to_model"] is True
        assert policy.evidence_metadata["model_digest"] == DIGEST
        assert policy.evidence_metadata["training_eligible"] is False
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
