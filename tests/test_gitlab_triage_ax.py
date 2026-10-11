import pytest

from world_engine.browser_contracts import BrowserError, BrowserObservation
from world_engine.browser_policy import BrowserReferencePolicy

MARKER = "StaticText 'Incident reference: INC-2026-0217'\n"


def observation(text):
    return BrowserObservation(
        url="http://127.0.0.1:8929/root/incident-operations/-/work_items/2",
        title="GitLab",
        accessibility_text=MARKER + text,
        screenshot_artifact_id="screenshots/0000.png",
    )


def control():
    return BrowserReferencePolicy("Incident reference: INC-2026-0217", triage=True)


def sidebar(*, heading="Assignee", assigned=False, classified=False, assignee_bid="1144", label_bid="1151"):
    # Minimal observed AX structure; the background issue is not the target sidebar.
    return (
        "[822] link 'severity::2'\n"
        "[829] link 'Assigned to Casey On-call @casey-oncall'\n"
        "[831] image 'Assigned to Casey On-call Backup'\n"
        "[960] button 'Edit'\n"
        "[1137] region 'Sidebar'\n"
        f"\t[1143] heading '{heading}'\n"
        f"\t\tInlineTextBox '{heading}'\n"
        f"\t[{assignee_bid}] button 'Edit'\n"
        + ("\t[2107] link 'Casey On-call @casey-oncall'\n" if assigned else "\tStaticText 'None'\n")
        + "\t[1150] heading 'Labels'\n"
        "\t\tInlineTextBox 'Labels'\n"
        f"\t[{label_bid}] button 'Edit'\n"
        "\t[1149] link 'incident'\n"
        + ("\t[1157] link 'severity::2'\n" if classified else "")
        + "\t[1162] heading 'Milestone'\n"
        "\t\tInlineTextBox 'Milestone'\n"
        "\t[1163] button 'Edit'\n"
        "\tStaticText 'Casey On-call @casey-oncall'\n"
        "\tStaticText 'severity::2'\n"
    )


def assignee_picker(*, option_bid="12", selected=False, apply_bid="15"):
    picker = (f"\t[{apply_bid}] button 'Apply'\n\t[10] combobox 'Search'\n"
              "\t[11] listbox 'Select assignee'\n"
              "\t\t[13] option 'Casey On-call Backup @casey-backup', selected=False\n"
              f"\t\t[{option_bid}] option 'Casey On-call @casey-oncall', selected={selected}\n")
    return sidebar().replace("\t[1144] button 'Edit'\n\tStaticText 'None'\n", picker)


def inspected_closed():
    return sidebar(assigned=True, classified=True).replace(
        "link 'Casey On-call @casey-oncall'", "link 'Casey On-call'")


def grouped_inspection(*, candidate_bid="2087", search_bid="1648"):
    # Public V6 no-op observation 13; offered accounts omit selection flags.
    picker = ("\t[1629] button 'Apply'\n"
              f"\t[{search_bid}] combobox 'Search', focused, expanded=True\n"
              "\t[2081] listbox 'Select assignee', multiselectable=False\n"
              "\t\t[2085] group 'Selected'\n"
              f"\t\t\t[{candidate_bid}] option 'Casey On-call @casey-oncall', selected=True\n"
              "\t\t\t\tStaticText 'Casey On-call'\n"
              "\t\t[2098] group 'All users'\n"
              "\t\t\t[2100] option 'Workflow Agent @workflow-agent'\n"
              "\t\t\t[2111] option 'Administrator @root'\n")
    return inspected_closed().replace("\t[1144] button 'Edit'\n\t[2107] link 'Casey On-call'\n", picker)


def record(history, decision):
    history.append({"step": len(history), "action": decision.action.model_dump(), "result": {"ok": True}})


async def owned_inspection():
    policy = control()
    history = []
    decision = await policy.decide(observation(inspected_closed()), history)
    assert decision.action.bid == "1144"
    record(history, decision)
    return policy, history


@pytest.mark.parametrize("heading", ["Assignee", "Assignees"])
async def test_actual_heading_and_generic_edit_are_scoped(heading):
    decision = await control().decide(observation(sidebar(heading=heading)), [])
    assert decision.action.kind == "click" and decision.action.bid == "1144"
    assert decision.evidence["protocol"] == "public-ax-triage-control-v7"


async def test_uses_current_observed_bid_not_previous_observation():
    policy = control()
    first = await policy.decide(observation(sidebar()), [])
    second = await policy.decide(observation(assignee_picker(option_bid="2004")), [])
    assert first.action.bid == "1144" and second.action.bid == "2004"


async def test_labels_inline_child_is_not_a_section_boundary():
    decision = await control().decide(observation(sidebar(assigned=True)), [])
    assert decision.action.kind == "click" and decision.action.bid == "1151"


async def test_already_correct_target_finishes_without_edit():
    decision = await control().decide(observation(sidebar(assigned=True, classified=True)), [])
    assert decision.action.kind == "finish"


@pytest.mark.parametrize("name", ["Casey On-call Backup @casey-backup", "@casey-oncall-extra"])
async def test_similar_sidebar_user_is_not_exact_oncall(name):
    text = sidebar(assigned=True).replace("link 'Casey On-call @casey-oncall'", f"link '{name}'")
    with pytest.raises(BrowserError, match="ambiguous closed assignee"):
        await control().decide(observation(text), [])


@pytest.mark.parametrize("mutation", ["missing", "static", "duplicate", "alias_duplicate"])
async def test_missing_or_ambiguous_assignee_heading_fails_closed(mutation):
    text = sidebar()
    if mutation == "missing":
        text = text.replace("[1143] heading 'Assignee'", "[1143] heading 'Owner'")
    elif mutation == "static":
        text = text.replace("[1143] heading 'Assignee'", "StaticText 'Assignee'")
    else:
        text += "\t[2001] heading 'Assignees'\n" if mutation == "alias_duplicate" else "\t[2001] heading 'Assignee'\n"
    with pytest.raises(BrowserError, match="unambiguous observed sidebar"):
        await control().decide(observation(text), [])


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "similar", "global_only"])
async def test_field_edit_must_be_exact_unique_and_scoped(mutation):
    text = sidebar()
    if mutation == "duplicate":
        text = text.replace("[1144] button 'Edit'", "[1144] button 'Edit'\n\t[2010] button 'Edit'")
    else:
        text = text.replace("[1144] button 'Edit'", "[1144] button 'Edit assignment'" if mutation == "similar" else "")
        if mutation == "global_only":
            text = "[2010] button 'Edit assignees'\n" + text
    with pytest.raises(BrowserError, match="one observed sidebar edit"):
        await control().decide(observation(text), [])


async def test_label_section_must_also_be_unambiguous_before_any_edit():
    with pytest.raises(BrowserError, match="unambiguous observed sidebar"):
        await control().decide(observation(sidebar() + "\t[2010] heading 'Labels'\n"), [])


async def test_background_headings_and_peer_region_cannot_leak_into_sidebar():
    background = ("[2010] heading 'Assignee'\n[2011] button 'Edit'\n"
                  "[2012] heading 'Labels'\nStaticText 'severity::2'\n")
    peer = ("[2020] region 'Activity'\n\t[2021] heading 'Assignee'\n"
            "\tStaticText 'Casey On-call @casey-oncall'\n\t[2022] button 'Edit'\n"
            "\t[2023] heading 'Labels'\n\tStaticText 'severity::2'\n")
    decision = await control().decide(observation(background + sidebar() + peer), [])
    assert decision.action.bid == "1144"


@pytest.mark.parametrize("mutation", ["missing", "wrong_role", "duplicate"])
async def test_requires_one_sidebar_region(mutation):
    text = sidebar()
    if mutation == "duplicate":
        text += "[2020] region 'Sidebar'\n\t[2021] heading 'Assignee'\n"
    else:
        text = text.replace("[1137] region 'Sidebar'", "[1137] region 'Other'" if mutation == "missing"
                            else "[1137] heading 'Sidebar'")
    with pytest.raises(BrowserError, match="one observed Sidebar region"):
        await control().decide(observation(text), [])


async def test_following_peer_region_cannot_supply_missing_edit():
    text = sidebar().replace("\t[1144] button 'Edit'\n", "")
    text += "[2020] region 'Activity'\n\t[2021] button 'Edit'\n"
    with pytest.raises(BrowserError, match="one observed sidebar edit"):
        await control().decide(observation(text), [])


async def test_scoped_picker_excludes_backup_and_requires_selection_before_apply():
    policy = control()
    text = assignee_picker()
    assert (await policy.decide(observation(text), [])).action.bid == "12"
    applied = await policy.decide(observation(assignee_picker(selected=True, apply_bid="20")), [])
    assert applied.action.kind == "click" and applied.action.bid == "20"


async def test_conservative_scoped_label_picker_requires_exact_option():
    # Initial group structure follows observed public AX; post-selection remains mock-only.
    picker = ("\t[10] button 'Apply'\n\t[11] combobox 'Search'\n"
              "\t[12] listbox 'Select labels', multiselectable=True\n"
              "\t\t[2155] group 'Selected'\n"
              "\t\t\t[2157] option 'incident', selected=True\n"
              "\t\t[2163] group 'All'\n"
              "\t\t\t[2165] option 'incident', selected=True\n"
              "\t\t\t[13] option 'severity::20', selected=False\n"
              "\t\t\t[14] option 'severity::2'\n")
    policy = control()
    opened = await policy.decide(observation(sidebar(assigned=True)), [])
    history = [{"step": 0, "action": opened.action.model_dump(), "result": {"ok": True}}]
    text = sidebar(assigned=True).replace("\t[1151] button 'Edit'\n\t[1149] link 'incident'\n", picker)
    assert (await policy.decide(observation(text), history)).action.bid == "14"


async def test_close_control_identity_unchanged():
    policy = BrowserReferencePolicy("Deployment reference: REL-2026-0217. Add exactly: ready Then close")
    assert policy.evidence_metadata["protocol"] == "public-ax-browser-control-v1"


async def test_actual_display_only_commit_and_ordinary_activity_corroborate_identity():
    policy = control()
    await policy.decide(observation(sidebar()), [])
    await policy.decide(observation(assignee_picker(option_bid="2058")), [])
    closed = sidebar(assigned=True).replace("link 'Casey On-call @casey-oncall'", "link 'Casey On-call'")
    activity = ("[1500] heading 'Activity'\n\t[1557] list ''\n\t\t[2114] listitem ''\n"
                "\t\t\t[2120] link 'Workflow Agent'\n\t\t\tStaticText 'assigned to'\n"
                "\t\t\t[2125] link '@casey-oncall'\n\t\t\t[2127] link 'Sunday, October 11, 2026 at 2:55:01 PM EDT'\n")
    decision = await policy.decide(observation(closed + activity), [])
    assert decision.action.kind == "click" and decision.action.bid == "1151"


async def test_display_only_existing_assignee_is_not_trusted_without_picker_inspection():
    policy, history = await owned_inspection()
    decision = await policy.decide(observation(grouped_inspection()), history)
    assert decision.action.model_dump() == {"kind": "press", "bid": "1648", "key": "Escape"}
    record(history, decision)
    assert (await policy.decide(observation(inspected_closed()), history)).action.kind == "finish"


@pytest.mark.parametrize("phase", ["edit", "escape"])
@pytest.mark.parametrize("mutation", ["absent", "none", "list", "bad_step", "bool_step", "wrong_bid", "extra_action",
                                     "false", "numeric_ok", "missing_ok", "uncertain", "unknown_uncertainty", "wrong_slot"])
async def test_v7_owned_edit_and_escape_require_exact_certain_receipts(phase, mutation):
    policy, history = await owned_inspection()
    if phase == "escape":
        record(history, await policy.decide(observation(grouped_inspection()), history))
    index = len(history) - 1
    row = history[index]
    if mutation == "absent":
        history.pop()
    elif mutation == "none":
        row["result"] = None
    elif mutation == "list":
        row["result"] = []
    elif mutation == "bad_step":
        row["step"] += 1
    elif mutation == "bool_step":
        row["step"] = bool(index)
    elif mutation == "wrong_bid":
        row["action"]["bid"] = "stale"
    elif mutation == "extra_action":
        row["action"]["extra"] = "not emitted"
    elif mutation == "false":
        row["result"] = {"ok": False}
    elif mutation == "numeric_ok":
        row["result"] = {"ok": 1}
    elif mutation == "missing_ok":
        row["result"] = {}
    elif mutation == "uncertain":
        row["result"] = {"ok": True, "uncertain_effect": True}
    elif mutation == "unknown_uncertainty":
        row["result"] = {"ok": True, "uncertain_effect": None}
    else:
        history.insert(index, {"step": index, "action": {"kind": "wait", "seconds": 1}, "result": {"ok": True}})
    with pytest.raises(BrowserError):
        await policy.decide(observation(inspected_closed() if phase == "escape" else grouped_inspection()), history)
    assert not policy.triage_confirmed_assignee


@pytest.mark.parametrize("mutation", ["missing_group", "duplicate_group", "nested_group", "extra_selected", "duplicate_bid",
                                     "duplicate_identity", "backup", "false_candidate", "missing_candidate_flag", "nonempty_search",
                                     "loading", "multiselect", "ungrouped", "changed_labels", "checked_true"])
async def test_v7_grouped_readonly_inspection_rejects_ambiguous_or_changed_context(mutation):
    policy, history = await owned_inspection()
    text = grouped_inspection()
    if mutation == "missing_group":
        text = text.replace("group 'All users'", "group 'Other users'")
    elif mutation == "duplicate_group":
        text = text.replace("\t\t[2098]", "\t\t[3000] group 'Selected'\n\t\t[2098]")
    elif mutation == "nested_group":
        text = text.replace("\t\t[2098]", "\t\t\t[2098]")
    elif mutation == "extra_selected":
        text = text.replace("@workflow-agent'", "@workflow-agent', selected=True")
    elif mutation == "duplicate_bid":
        text = text.replace("[2100]", "[2087]")
    elif mutation == "duplicate_identity":
        text = text.replace("Administrator @root", "Workflow Agent @workflow-agent")
    elif mutation == "backup":
        text = text.replace("Casey On-call @casey-oncall", "Casey On-call Backup @casey-backup")
    elif mutation == "false_candidate":
        text = text.replace("selected=True", "selected=False")
    elif mutation == "missing_candidate_flag":
        text = text.replace(", selected=True", "")
    elif mutation == "nonempty_search":
        text = text.replace("focused, expanded=True", "focused, expanded=True, value='casey'")
    elif mutation == "loading":
        text = text.replace("[1629]", "[3000] status 'Loading users'\n\t[1629]")
    elif mutation == "multiselect":
        text = text.replace("multiselectable=False", "multiselectable=True")
    elif mutation == "ungrouped":
        text = text.replace("[2081]", "[3000] option 'Other @other', selected=False\n\t[2081]")
    elif mutation == "changed_labels":
        text = text.replace("link 'incident'", "link 'unrelated'")
    else:
        text = text.replace("@workflow-agent'", "@workflow-agent', checked=True")
    with pytest.raises(BrowserError):
        await policy.decide(observation(text), history)


@pytest.mark.parametrize("property_text", ["selected=1", "selected='False'", "selected=None", "selected False",
                                          "selected: False", "selected", "selected=False, selected=False",
                                          "checked=0", "checked='False'", "checked=False, checked=True"])
async def test_v7_present_malformed_flags_are_not_unknown(property_text):
    policy, history = await owned_inspection()
    text = grouped_inspection().replace("@workflow-agent'", f"@workflow-agent', {property_text}")
    with pytest.raises(BrowserError):
        await policy.decide(observation(text), history)


async def test_v7_valid_trailing_properties_and_quoted_commas_remain_readonly():
    policy, history = await owned_inspection()
    text = grouped_inspection().replace("selected=True", "selected=True, visible").replace(
        "Workflow Agent @workflow-agent", "Workflow, Agent @workflow-agent")
    decision = await policy.decide(observation(text), history)
    assert decision.action.model_dump() == {"kind": "press", "bid": "1648", "key": "Escape"}


@pytest.mark.parametrize("missing", ["candidate", "search"])
async def test_v7_current_ids_required_and_receipts_remain_bound_through_waits(missing):
    policy, history = await owned_inspection()
    text = grouped_inspection().replace("[2087] " if missing == "candidate" else "[1648] ", "")
    pending = await policy.decide(observation(text), history)
    assert pending.action.kind == "wait"
    record(history, pending)
    escaped = await policy.decide(observation(grouped_inspection(search_bid="9999")), history)
    assert escaped.action.bid == "9999"
    record(history, escaped)
    pending = await policy.decide(observation(grouped_inspection()), history)
    assert pending.action.kind == "wait"
    record(history, pending)
    assert (await policy.decide(observation(inspected_closed()), history)).action.kind == "finish"


@pytest.mark.parametrize("mutation", ["extra_assignee", "missing_assignee", "changed_labels", "extra_label"])
async def test_v7_dismissal_does_not_certify_changed_closed_state(mutation):
    policy, history = await owned_inspection()
    record(history, await policy.decide(observation(grouped_inspection()), history))
    text = inspected_closed()
    if mutation == "extra_assignee":
        text = text.replace("[2107]", "[3000] link 'Other @other'\n\t[2107]")
    elif mutation == "missing_assignee":
        text = text.replace("link 'Casey On-call'", "StaticText 'None'")
    elif mutation == "changed_labels":
        text = text.replace("link 'incident'", "link 'other'")
    else:
        text = text.replace("[1149]", "[3000] link 'other'\n\t[1149]")
    if mutation == "missing_assignee":
        for _ in range(5):
            decision = await policy.decide(observation(text), history)
            assert decision.action.kind == "wait"
            record(history, decision)
    with pytest.raises(BrowserError):
        await policy.decide(observation(text), history)
    assert not policy.triage_confirmed_assignee


async def test_v7_unsolicited_grouped_picker_cannot_use_unknown_flags():
    with pytest.raises(BrowserError):
        await control().decide(observation(grouped_inspection()), [])


async def test_current_picker_bid_can_select_but_cannot_certify_closed_commit():
    policy = control()
    await policy.decide(observation(assignee_picker(option_bid="2058")), [])
    closed = sidebar(assigned=True).replace("link 'Casey On-call @casey-oncall'", "link 'Casey On-call'")
    text = closed + "[5000] link '@casey-oncall'\nStaticText 'assigned to'\n"
    assert (await policy.decide(observation(text), [])).action.kind == "wait"


async def test_v4_public_closed_labels_then_actual_grouped_picker_selects_only_current_all_bid():
    policy = control()
    first = await policy.decide(observation(assignee_picker(option_bid="2058")), [])
    history = [{"step": 0, "action": first.action.model_dump(), "result": {"ok": True}}]
    # Minimal public observation 11: committed display name plus ordinary target Activity.
    closed = sidebar(assigned=True, label_bid="1145").replace(
        "link 'Casey On-call @casey-oncall'", "link 'Casey On-call'")
    activity = ("[1500] heading 'Activity'\n\t[1557] list ''\n\t\t[2114] listitem ''\n"
                "\t\t\t[2120] link 'Workflow Agent'\n\t\t\tStaticText 'assigned to'\n"
                "\t\t\t[2125] link '@casey-oncall'\n\t\t\t[2127] link 'Sunday, October 11, 2026 at 2:55:01 PM EDT'\n")
    opened = await policy.decide(observation(closed + activity), history)
    assert opened.action.bid == "1145"
    history.append({"step": 1, "action": opened.action.model_dump(), "result": {"ok": True}})
    # Observation 12 has no selected flag on severity::2, while incident appears in both groups.
    picker = ("\t[2132] button 'Apply', visible\n"
              "\t[2135] button 'incident', visible, hasPopup='listbox', expanded=True\n"
              "\tStaticText 'Select labels'\n\t[2145] button 'Clear', visible\n"
              "\t[2150] combobox 'Search', visible, focused, hasPopup='listbox', expanded=True\n"
              "\t[2151] listbox 'Select labels', visible, multiselectable=True, orientation='vertical'\n"
              "\t\t[2155] group 'Selected', visible\n\t\t\tInlineTextBox 'Selected'\n"
              "\t\t\t[2157] option 'incident', visible, selected=True\n"
              "\t\t\t\tStaticText 'incident'\n\t\t\t\t\tInlineTextBox 'incident'\n"
              "\t\t[2163] group 'All', visible\n\t\t\tInlineTextBox 'All'\n"
              "\t\t\t[2165] option 'incident', visible, selected=True\n"
              "\t\t\t\tStaticText 'incident'\n\t\t\t\t\tInlineTextBox 'incident'\n"
              "\t\t\t[2171] option 'severity::2', visible\n"
              "\t\t\t\tStaticText 'severity::2'\n\t\t\t\t\tInlineTextBox 'severity::2'\n"
              "\t\t\tInlineTextBox 'severity::3'\n\tInlineTextBox '4 results'\n"
              "\t[2188] button 'Create project label'\n\t[2190] link 'Manage project labels'\n")
    opened = closed.replace("\t[1145] button 'Edit'\n\t[1149] link 'incident'\n", picker)
    action = (await policy.decide(observation(opened + activity), history)).action
    assert action.kind == "click" and action.bid == "2171"


async def test_v5_public_prior_selected_new_all_requires_exact_receipt_before_current_apply():
    policy = control()
    history = []

    async def completed(text):
        decision = await policy.decide(observation(text), history)
        history.append({"step": len(history), "action": decision.action.model_dump(), "result": {"ok": True}})
        return decision.action

    assert (await completed(sidebar(assigned=True))).bid == "1151"
    # Public V5 labels field, with Selected still incident after the All target click.
    picker = ("\t[2130] button 'Apply', visible\n"
              "\t[2133] button 'incident', visible, expanded=True\n"
              "\t[2148] combobox 'Search', visible, focused, expanded=True\n"
              "\t[2149] listbox 'Select labels', visible, multiselectable=True, orientation='vertical'\n"
              "\t\t[2153] group 'Selected', visible\n"
              "\t\t\t[2155] option 'incident', visible, selected=True\n"
              "\t\t[2161] group 'All', visible\n"
              "\t\t\t[2163] option 'incident', visible, selected=True\n"
              "\t\t\t[2169] option 'severity::2', visible\n"
              "\t\t\tInlineTextBox 'severity::3'\n")
    opened = sidebar(assigned=True).replace("\t[1151] button 'Edit'\n\t[1149] link 'incident'\n", picker)
    assert (await completed(opened)).bid == "2169"
    draft = opened.replace("button 'incident'", "button 'incident and severity::2'").replace(
        "option 'severity::2', visible", "option 'severity::2', visible, selected=True")
    action = (await policy.decide(observation(draft), history)).action
    assert action.kind == "click" and action.bid == "2130"
    # Phase is pre-result state; no accepted Apply receipt exists yet.
    with pytest.raises(BrowserError, match="emitted label action receipt"):
        await policy.decide(observation(sidebar(assigned=True, classified=True)), history)
    history.append({"step": 2, "action": action.model_dump(), "result": {"ok": True}})
    assert (await policy.decide(observation(sidebar(assigned=True, classified=True)), history)).action.kind == "finish"
