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
        + ("\tStaticText 'Casey On-call @casey-oncall'\n" if assigned else "\tStaticText 'None'\n")
        + "\t[1150] heading 'Labels'\n"
        "\t\tInlineTextBox 'Labels'\n"
        f"\t[{label_bid}] button 'Edit'\n"
        "\tStaticText 'incident'\n"
        + ("\t[1157] link 'severity::2'\n" if classified else "")
        + "\t[1162] heading 'Milestone'\n"
        "\t\tInlineTextBox 'Milestone'\n"
        "\t[1163] button 'Edit'\n"
        "\tStaticText 'Casey On-call @casey-oncall'\n"
        "\tStaticText 'severity::2'\n"
    )


@pytest.mark.parametrize("heading", ["Assignee", "Assignees"])
async def test_actual_heading_and_generic_edit_are_scoped(heading):
    decision = await control().decide(observation(sidebar(heading=heading)), [])
    assert decision.action.kind == "click" and decision.action.bid == "1144"
    assert decision.evidence["protocol"] == "public-ax-triage-control-v2"


async def test_uses_current_observed_bid_not_previous_observation():
    policy = control()
    first = await policy.decide(observation(sidebar()), [])
    second = await policy.decide(observation(sidebar(assignee_bid="2004")), [])
    assert first.action.bid == "1144" and second.action.bid == "2004"


async def test_labels_inline_child_is_not_a_section_boundary():
    decision = await control().decide(observation(sidebar(assigned=True)), [])
    assert decision.action.kind == "click" and decision.action.bid == "1151"


async def test_already_correct_target_finishes_without_edit():
    decision = await control().decide(observation(sidebar(assigned=True, classified=True)), [])
    assert decision.action.kind == "finish"


@pytest.mark.parametrize("name", ["Casey On-call Backup @casey-backup", "@casey-oncall-extra"])
async def test_similar_sidebar_user_is_not_exact_oncall(name):
    text = sidebar(assigned=True).replace("StaticText 'Casey On-call @casey-oncall'", f"StaticText '{name}'")
    assert (await control().decide(observation(text), [])).action.bid == "1144"


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


async def test_existing_picker_excludes_backup_and_closes_after_selection():
    policy = control()
    text = ("[10] textbox 'Search users' value='casey-oncall'\n"
            "[11] checkbox 'Casey On-call Backup @casey-backup'\n"
            "[12] checkbox 'Casey On-call @casey-oncall'")
    assert (await policy.decide(observation(text), [])).action.bid == "12"
    closed = await policy.decide(observation("[20] textbox 'Search users' value='casey-oncall'"), [])
    assert closed.action.kind == "press" and closed.action.bid == "20" and closed.action.key == "Escape"


async def test_existing_label_picker_requires_exact_option():
    text = ("[10] textbox 'Search labels' value='severity::2'\n"
            "[11] checkbox 'severity::20'\n[12] checkbox 'severity::2'")
    assert (await control().decide(observation(text), [])).action.bid == "12"


async def test_close_control_identity_unchanged():
    policy = BrowserReferencePolicy("Deployment reference: REL-2026-0217. Add exactly: ready Then close")
    assert policy.evidence_metadata["protocol"] == "public-ax-browser-control-v1"
