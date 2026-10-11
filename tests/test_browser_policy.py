import base64
import hashlib
import json

import httpx
import pytest

from world_engine.browser_contracts import BrowserError, BrowserObservation
from world_engine.browser_policy import (
    OPTIONS,
    PROTOCOL,
    BrowserReferencePolicy,
    OllamaBrowserPolicy,
    ax_nodes,
    browser_tools,
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


def valid_reply(arguments=None, *, name="browser_finish"):
    return {"model": "qwen3:8b", "done": True, "done_reason": "stop", "message": {"role": "assistant",
            "tool_calls": [{"function": {"name": name, "arguments": {} if arguments is None else arguments}}]},
            "prompt_eval_count": 42, "eval_count": 8}


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
        public = json.loads(request["messages"][1]["content"])
        assert "screenshot_artifact_id" not in public["observation"]
        assert public["observation"]["image_not_sent_to_model"] is True
        assert policy.evidence_metadata["model_digest"] == DIGEST
        assert policy.evidence_metadata["training_eligible"] is False
        assert policy.evidence_metadata["protocol"] == PROTOCOL == "ollama-browser-tools-v2"
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
    assignee = "\tStaticText '@casey-oncall'\n" if assigned else "\tStaticText 'None'\n"
    labels = "\t[1157] link 'severity::2'\n" if classified else "\t[1155] link 'incident'\n"
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
    # Assignee structure comes from observed AX; labels are conservative mocks only.
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


def triage_observation(text):
    return observation(text, "http://127.0.0.1:8929/root/incident-operations/-/work_items/2")


async def test_triage_v3_actual_picker_no_bid_waits_then_selects_current_bid():
    policy = triage_control()
    opened = await policy.decide(triage_observation(triage_closed()), [])
    assert opened.action.bid == "1144" and opened.evidence["protocol"] == "public-ax-triage-control-v3"
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
    next_field = await policy.decide(triage_observation(triage_closed(assigned=True)), [])
    assert next_field.action.bid == "1151"


async def test_triage_missing_applied_membership_fails_instead_of_reopening():
    policy = triage_control()
    await policy.decide(triage_observation(triage_picker(selected=True)), [])
    with pytest.raises(BrowserError, match="confirm the applied field"):
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
    action = (await triage_control().decide(triage_observation(text), [])).action
    assert action.kind == "click" and action.bid == "2049"


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
    with pytest.raises(BrowserError):
        await triage_control().decide(triage_observation(text), [])


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
    with pytest.raises(BrowserError, match="scoped Apply"):
        await triage_control().decide(triage_observation(text), [])


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


@pytest.mark.parametrize("role", ["option", "checkbox"])
async def test_triage_conservative_label_picker_exactness_and_apply(role):
    policy = triage_control()
    text = triage_picker(field="labels", option_role=role).replace(
        "\t\t[2060]", "\t\t[5000] option 'severity::20', selected=False\n\t\t[2060]")
    assert (await policy.decide(triage_observation(text), [])).action.bid == "2049"
    selected = triage_picker(field="labels", option_role=role, selected=True)
    assert (await policy.decide(triage_observation(selected), [])).action.bid == "1446"
    assert (await policy.decide(triage_observation(triage_closed(assigned=True, classified=True)), [])).action.kind == "finish"


async def test_triage_already_correct_noop_and_state_are_instance_local():
    first, second = triage_control(), triage_control()
    await first.decide(triage_observation(triage_closed()), [])
    decision = await second.decide(triage_observation(triage_closed(assigned=True, classified=True)), [])
    assert decision.action.kind == "finish" and second.triage_edit is None


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
