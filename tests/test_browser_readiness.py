import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from world_engine.browser_contracts import BrowserAttemptConfig, BrowserError, BrowserObservation
from world_engine.browser_policy import (
    BrowserReferencePolicy,
    OllamaBrowserPolicy,
    ax_nodes,
    create_browser_policy,
)
from world_engine.browser_readiness import BrowserReadinessPolicy

INSTRUCTION = (
    "In Release Operations, evaluate the open issue with Release reference: REL-2026-2042. "
    "Follow policy READINESS-R1 in the issue titled Release readiness policy. "
    "Use only the policy and matching evidence posted by Administrator, username @root. "
    "Read the review and validation evidence on the release issue, then post exactly one ordinary decision note "
    "in the format below and follow the policy's disposition. Do not use an internal note. "
    "Preserve existing notes, evidence, other issues, labels, due dates, descriptions and project access.\n\n"
    "release-decision-v1\nrelease=REL-2026-2042\npolicy=READINESS-R1\nreview=REVIEW-2042\n"
    "validation=VALIDATION-2042\ndecision=<ready or blocked>\n"
    "blocked_gates=<none or comma-separated unmet gate names in review,validation order>"
)
POLICY = (
    "Release readiness policy READINESS-R1.\n"
    "Use only release-evidence-v1 records posted by Administrator (@root) on the requested release issue. "
    "Match the release and policy fields exactly. Required records must be unique. "
    "If either required record is missing or ambiguous, stop without changing the application.\n"
    "The review record must say approved. The validation record must say passed. "
    "If both requirements hold, record ready and then close the issue. Otherwise, record blocked "
    "and the unmet gates, and leave the issue open.\n"
    "Use exactly one ordinary release-decision-v1 note in the task's format. "
    "Do not edit evidence, add other notes, or act on another release."
)
ORIGIN = "http://127.0.0.1:8929"
LIST = ORIGIN + "/root/release-operations/-/work_items"
POLICY_URL = LIST + "/8"
TARGET_URL = LIST + "/6"
MENU = "\t[9] link 'Workflow Agent user\u2019s menu', visible\n"


def observation(text, url):
    return BrowserObservation(url=url, title="GitLab", accessibility_text=MENU + text,
                              screenshot_artifact_id="screenshots/current.png")


def evidence(gate, status, *, release="REL-2026-2042", policy="READINESS-R1", record=None):
    record = record or ("REVIEW-2042" if gate == "review" else "VALIDATION-2042")
    return (f"release-evidence-v1\nrelease={release}\npolicy={policy}\nrecord={record}\n"
            f"gate={gate}\nstatus={status}")


def note(body, *, author="Administrator", username="@root", internal=False, body_link=None):
    # This is the public nested activity shape retained from GitLab 19.4's AX trace.
    text = ("\t\t[50] listitem '', visible\n\t\t\t[51] list '', visible\n"
            "\t\t\t\t[52] listitem '', visible\n"
            f"\t\t\t\t\t[53] link {author!r}, visible\n"
            f"\t\t\t\t\t\t[54] image {author!r}, visible\n"
            f"\t\t\t\t\t[55] link {author!r}, visible\n")
    if username is not None:
        text += f"\t\t\t\t\t[56] link {username!r}, visible\n"
    if internal:
        text += "\t\t\t\t\tStaticText 'Internal note'\n"
    text += f"\t\t\t\t\t[57] paragraph '', visible\n\t\t\t\t\t\tStaticText {body!r}\n"
    if body_link:
        text += f"\t\t\t\t\t\t[58] link {body_link!r}, visible\n"
    return text


def detail(*, policy=False, release="REL-2026-2042", notes=None, draft="", closed=False,
           textbox="70", comment="73", close="74", internal="false", extra=""):
    title = "Release readiness policy" if policy else "Release readiness review"
    description = "Policy reference: READINESS-R1" if policy else f"Release reference: {release}"
    if notes is None:
        notes = [note(POLICY)] if policy else [note("Original coordination history."),
                                             note(evidence("review", "approved")),
                                             note(evidence("validation", "passed")),
                                             note(evidence("review", "approved", release="REL-2026-2043"))]
    return (f"\t[10] banner '', visible\n\t\t[11] heading {title!r}, visible\n"
            f"\t\tStaticText {'Closed' if closed else 'Open'!r}\n"
            f"\t[12] paragraph '', visible\n\t\tStaticText {description!r}\n"
            "\t[13] region 'Sidebar', visible\n\t\t[14] paragraph '', visible\n\t\t\tStaticText 'Due: None'\n"
            "\t[40] heading 'Activity', visible\n\t[41] list '', visible\n" + "".join(notes)
            + "\t[60] list '', visible\n\t\t[61] listitem '', visible\n\t\t\t[62] form '', visible\n"
            + f"\t\t\t\t[{textbox}] textbox 'Add a reply' value={draft!r}, visible\n"
            + f"\t\t\t\t\tStaticText {draft!r}\n"
            + "\t\t\t\t[71] button 'Switch to rich text editing', visible\n"
            + f"\t\t\t\t[72] checkbox 'Make this an internal note', visible, checked='{internal}'\n"
            + f"\t\t\t\t[{comment}] button 'Comment', visible\n"
            + f"\t\t\t\t[{close}] button 'Close issue', visible\n" + extra)


def issue_list(offset=0, total=4):
    return (f"\tStaticText '{total} items'\n"
            f"\t[{100 + offset}] link 'Release readiness policy', visible\n"
            + "".join(f"\t[{101 + offset + i}] link 'Release readiness review', visible\n" for i in range(3)))


async def action(policy, history, text, url, *, result=None):
    decision = await policy.decide(observation(text, url), history)
    history.append({"step": len(history), "action": decision.action.model_dump(),
                    "result": {"ok": True} if result is None else result})
    return decision.action


async def discovered(*, policy_notes=None, releases=None):
    policy, history = BrowserReadinessPolicy(INSTRUCTION, ax_nodes), []
    assert (await action(policy, history, "\t[2] link 'Release Operations'", ORIGIN + "/dashboard/projects")).bid == "2"
    assert (await action(policy, history, "\t[3] link 'Work items'", ORIGIN + "/root/release-operations")).bid == "3"
    assert (await action(policy, history, issue_list(), LIST)).bid == "100"
    assert (await action(policy, history, detail(policy=True, notes=policy_notes), POLICY_URL)).url == LIST
    for index, release in enumerate(releases or ["REL-2026-2041", "REL-2026-2042", "REL-2026-2043"]):
        assert (await action(policy, history, issue_list(10 * index), LIST)).bid == str(101 + 11 * index)
        assert (await action(policy, history, detail(release=release), LIST + f"/{5 + index}")).url == LIST
    assert (await action(policy, history, issue_list(), LIST)).url == TARGET_URL
    return policy, history


@pytest.mark.parametrize("review,validation,decision,blocked", [
    ("approved", "passed", "ready", "none"),
    ("approved", "pending", "blocked", "validation"),
    ("pending", "passed", "blocked", "review"),
    ("rejected", "pending", "blocked", "review,validation"),
])
async def test_public_control_derives_note_and_ordered_disposition(review, validation, decision, blocked):
    policy, history = await discovered()
    notes = [note("Existing unrelated history."), note(evidence("review", review)),
             note(evidence("validation", validation)),
             note(evidence("review", "approved", release="REL-2026-2043")),
             note(evidence("validation", "passed"), author="Other User", username="@other")]
    fill = await action(policy, history, detail(notes=notes, textbox="801"), TARGET_URL)
    expected = ("release-decision-v1\nrelease=REL-2026-2042\npolicy=READINESS-R1\nreview=REVIEW-2042\n"
                f"validation=VALIDATION-2042\ndecision={decision}\nblocked_gates={blocked}")
    assert fill.model_dump() == {"kind": "fill", "bid": "801", "text": expected}
    submitted = await action(policy, history, detail(notes=notes, draft=expected, comment="902"), TARGET_URL)
    assert submitted.model_dump() == {"kind": "click", "bid": "902"}
    posted = notes + [note(expected, author="Workflow Agent", username="@workflow-agent")]
    next_action = await action(policy, history, detail(notes=posted, close="903"), TARGET_URL)
    if decision == "ready":
        assert next_action.model_dump() == {"kind": "click", "bid": "903"}
        assert (await action(policy, history, detail(notes=posted, closed=True), TARGET_URL)).kind == "finish"
    else:
        assert next_action.kind == "finish"
    assert sum(row["action"] == {"kind": "click", "bid": "902"} for row in history) == 1


@pytest.mark.parametrize("notes", [
    [], [note(POLICY), note(POLICY)], [note(POLICY, author="Other User", username="@other")],
    [note(POLICY, username=None)], [note(POLICY, author="Spoof", username="@root")],
    [note(POLICY, internal=True)], [note(POLICY.replace("READINESS-R1", "READINESS-R2"))],
    [note(POLICY.replace("leave the issue open", "close the issue"))],
    [note(POLICY, author="Other User", username="@other", body_link="@root")],
])
async def test_policy_requires_scoped_unique_corroborated_author(notes):
    with pytest.raises(BrowserError):
        await discovered(policy_notes=notes)


@pytest.mark.parametrize("notes", [
    [note(evidence("review", "approved"))],
    [note(evidence("review", "approved")), note(evidence("validation", "passed")),
     note(evidence("validation", "pending"))],
    [note(evidence("review", "approved")), note(evidence("validation", "passed"), username=None)],
    [note(evidence("review", "approved")), note(evidence("validation", "passed"), author="Other", username="@other")],
    [note(evidence("review", "approved")), note(evidence("validation", "passed", release="REL-2026-2043"))],
    [note(evidence("review", "approved")), note(evidence("validation", "passed", policy="READINESS-R2"))],
    [note(evidence("review", "approved")), note(evidence("validation", "passed", record="REVIEW-2042"))],
    [note(evidence("review", "approved")), note(evidence("validation", "passed") + "\nextra=true")],
    [note(evidence("review", "approved")), note(evidence("validation", "passed"), internal=True)],
    [note(evidence("review", "approved")), note(evidence("validation", "passed"), author="Forged", username="@root")],
    [note("release-decision-v1\nrelease=REL-2026-2042"), note(evidence("review", "approved")),
     note(evidence("validation", "passed"))],
])
async def test_missing_ambiguous_forged_or_wrong_scope_evidence_never_mutates(notes):
    policy, history = await discovered()
    before = list(history)
    with pytest.raises(BrowserError):
        await policy.decide(observation(detail(notes=notes), TARGET_URL), history)
    assert history == before
    assert policy.submitted is False


async def test_description_and_activity_cannot_borrow_background_or_editor_authority():
    policy, history = await discovered()
    fake = evidence("validation", "passed")
    text = detail(notes=[note(evidence("review", "approved"))], draft=fake)
    text += "\t[99] paragraph ''\n\t\tStaticText " + repr(fake) + "\n"
    with pytest.raises(BrowserError, match="unique authoritative"):
        await policy.decide(observation(text, TARGET_URL), history)


@pytest.mark.parametrize("releases", [
    ["REL-2026-2042", "REL-2026-2042", "REL-2026-2043"],
    ["REL-2026-2041", "REL-2026-2044", "REL-2026-2043"],
])
async def test_discovery_rejects_duplicate_or_missing_release_before_mutation(releases):
    with pytest.raises(BrowserError):
        await discovered(releases=releases)


async def test_side_panel_uses_current_full_page_link_without_background_parsing():
    policy, history = BrowserReadinessPolicy(INSTRUCTION, ax_nodes), []
    await action(policy, history, "\t[2] link 'Release Operations'", ORIGIN + "/dashboard/projects")
    await action(policy, history, "\t[3] link 'Work items'", ORIGIN + "/root/release-operations")
    await action(policy, history, issue_list(), LIST)
    text = issue_list() + detail(policy=True) + "\t[997] link 'Open in full page', visible\n"
    selected = await action(policy, history, text, LIST + "?show=8")
    assert selected.model_dump() == {"kind": "click", "bid": "997"}
    assert policy.required_status is None
    assert (await action(policy, history, detail(policy=True), POLICY_URL)).url == LIST


@pytest.mark.parametrize("result", [{"ok": False}, {"ok": True, "uncertain_effect": True},
                                  {"ok": True, "uncertain_effect": 0}])
async def test_uncertain_or_failed_submit_never_retries(result):
    policy, history = await discovered()
    fill = await action(policy, history, detail(), TARGET_URL)
    await action(policy, history, detail(draft=fill.text), TARGET_URL, result=result)
    with pytest.raises(BrowserError, match="uncertain"):
        await policy.decide(observation(detail(draft=fill.text), TARGET_URL), history)
    assert policy.submitted
    assert sum(row["action"] == {"kind": "click", "bid": "73"} for row in history) == 1


async def test_missing_or_mismatched_receipt_stops_before_submit():
    policy, history = await discovered()
    decision = await policy.decide(observation(detail(), TARGET_URL), history)
    with pytest.raises(BrowserError, match="lacks"):
        await policy.decide(observation(detail(draft=decision.action.text), TARGET_URL), history)
    history.append({"step": len(history), "action": {"kind": "click", "bid": "73"}, "result": {"ok": True}})
    with pytest.raises(BrowserError, match="unsuccessful"):
        await policy.decide(observation(detail(draft=decision.action.text), TARGET_URL), history)


@pytest.mark.parametrize("extra,internal,draft", [
    ("\t[99] dialog 'Confirm'\n", "false", ""),
    ("", "true", ""), ("", "unknown", ""), ("", "false", "Existing unrelated draft"),
])
async def test_modal_internal_or_existing_draft_uncertainty_stops(extra, internal, draft):
    policy, history = await discovered()
    with pytest.raises(BrowserError):
        await policy.decide(observation(detail(extra=extra, internal=internal, draft=draft), TARGET_URL), history)
    assert not policy.submitted


async def test_changed_evidence_after_fill_stops_before_submit():
    policy, history = await discovered()
    fill = await action(policy, history, detail(), TARGET_URL)
    text = detail(draft=fill.text).replace("status=passed", "status=pending")
    with pytest.raises(BrowserError, match="changed public evidence"):
        await policy.decide(observation(text, TARGET_URL), history)


async def test_conflicting_author_links_cannot_corroborate_evidence():
    policy, history = await discovered()
    conflicting = note(evidence("validation", "passed")).replace(
        "\t\t\t\t\t[56] link '@root', visible\n",
        "\t\t\t\t\t[56] link '@root', visible\n\t\t\t\t\t[59] link 'Other User', visible\n")
    with pytest.raises(BrowserError, match="author identities"):
        await policy.decide(observation(detail(notes=[note(evidence("review", "approved")), conflicting]),
                                        TARGET_URL), history)


async def test_author_timestamp_link_is_not_a_second_author():
    policy, history = await discovered()
    notes = [note(evidence("review", "approved")), note(evidence("validation", "passed"))]
    notes[0] = notes[0].replace("\t\t\t\t\t[57] paragraph", (
        "\t\t\t\t\t[59] link 'Tuesday, October 13, 2026 at 8:00 AM'\n"
        "\t\t\t\t\t\t[599] time ''\n\t\t\t\t\t[57] paragraph"))
    assert (await action(policy, history, detail(notes=notes), TARGET_URL)).kind == "fill"


async def test_plain_editor_switch_is_confirmed_before_exact_fill():
    policy, history = await discovered()
    rich = detail().replace("Switch to rich text editing", "Switch to plain text editing")
    assert (await action(policy, history, rich, TARGET_URL)).model_dump() == {"kind": "click", "bid": "71"}
    assert (await action(policy, history, rich, TARGET_URL)).kind == "wait"
    assert (await action(policy, history, detail(textbox="870"), TARGET_URL)).bid == "870"


async def test_unknown_editor_mode_never_fills():
    policy, history = await discovered()
    text = detail().replace("\t\t\t\t[71] button 'Switch to rich text editing', visible\n", "")
    with pytest.raises(BrowserError, match="plain text editing"):
        await policy.decide(observation(text, TARGET_URL), history)


async def test_uncertain_close_is_not_retried_or_treated_as_completion():
    policy, history = await discovered()
    fill = await action(policy, history, detail(), TARGET_URL)
    await action(policy, history, detail(draft=fill.text), TARGET_URL)
    base = [note("Original coordination history."), note(evidence("review", "approved")),
            note(evidence("validation", "passed")),
            note(evidence("review", "approved", release="REL-2026-2043"))]
    posted = base + [note(fill.text, author="Workflow Agent", username="@workflow-agent")]
    await action(policy, history, detail(notes=posted), TARGET_URL, result={"ok": True, "uncertain_effect": True})
    with pytest.raises(BrowserError, match="uncertain"):
        await policy.decide(observation(detail(notes=posted, closed=True), TARGET_URL), history)
    assert sum(row["action"] == {"kind": "click", "bid": "74"} for row in history) == 1


async def test_close_completion_requires_the_target_banner_not_unrelated_closed_text():
    policy, history = await discovered()
    fill = await action(policy, history, detail(), TARGET_URL)
    await action(policy, history, detail(draft=fill.text), TARGET_URL)
    base = [note("Original coordination history."), note(evidence("review", "approved")),
            note(evidence("validation", "passed")),
            note(evidence("review", "approved", release="REL-2026-2043"))]
    posted = base + [note(fill.text, author="Workflow Agent", username="@workflow-agent")]
    await action(policy, history, detail(notes=posted), TARGET_URL)
    assert (await action(policy, history, detail(notes=posted, extra="\tStaticText 'Closed'\n"), TARGET_URL)).kind == "wait"
    assert (await action(policy, history, detail(notes=posted, closed=True), TARGET_URL)).kind == "finish"


async def test_evidence_can_render_as_separate_static_text_lines():
    policy, history = await discovered()
    notes = [note(evidence("review", "approved")), note(evidence("validation", "pending"))]
    for index, body in enumerate([evidence("review", "approved"), evidence("validation", "pending")]):
        notes[index] = notes[index].replace(f"StaticText {body!r}",
                                           "\n\t\t\t\t\t\t".join(f"StaticText {line!r}" for line in body.splitlines()))
    assert "decision=blocked" in (await action(policy, history, detail(notes=notes), TARGET_URL)).text


async def test_policy_expected_status_is_read_from_its_public_body():
    changed = POLICY.replace("review record must say approved", "review record must say accepted")
    policy, history = await discovered(policy_notes=[note(changed)])
    fill = await action(policy, history, detail(), TARGET_URL)
    assert fill.text.endswith("decision=blocked\nblocked_gates=review")


async def test_submit_confirmation_is_scoped_not_draft_and_does_not_repeat():
    policy, history = await discovered()
    fill = await action(policy, history, detail(), TARGET_URL)
    await action(policy, history, detail(draft=fill.text), TARGET_URL)
    for _ in range(3):
        assert (await action(policy, history, detail(draft=fill.text), TARGET_URL)).kind == "wait"
    with pytest.raises(BrowserError, match="could not confirm"):
        await policy.decide(observation(detail(draft=fill.text), TARGET_URL), history)
    assert sum(row["action"] == {"kind": "click", "bid": "73"} for row in history) == 1
    assert not policy.close_requested


async def test_posted_markdown_whitespace_is_observed_semantics_not_raw_body_attestation():
    policy, history = await discovered()
    fill = await action(policy, history, detail(), TARGET_URL)
    await action(policy, history, detail(draft=fill.text), TARGET_URL)
    base = [note("Original coordination history."), note(evidence("review", "approved")),
            note(evidence("validation", "passed")),
            note(evidence("review", "approved", release="REL-2026-2043"))]
    posted = base + [note(fill.text.replace("\n", " "), author="Workflow Agent", username="@workflow-agent")]
    assert (await action(policy, history, detail(notes=posted), TARGET_URL)).bid == "74"


@pytest.mark.parametrize("author,internal,count", [("Other User", False, 1), ("Workflow Agent", True, 1),
                                                  ("Workflow Agent", False, 2)])
async def test_posted_decision_requires_one_ordinary_actor_note(author, internal, count):
    policy, history = await discovered()
    fill = await action(policy, history, detail(), TARGET_URL)
    await action(policy, history, detail(draft=fill.text), TARGET_URL)
    base = [note("Original coordination history."), note(evidence("review", "approved")),
            note(evidence("validation", "passed")),
            note(evidence("review", "approved", release="REL-2026-2043"))]
    posted = base + [note(fill.text, author=author, username="@workflow-agent", internal=internal)] * count
    with pytest.raises(BrowserError, match="ordinary actor decision"):
        await policy.decide(observation(detail(notes=posted), TARGET_URL), history)
    assert not policy.close_requested


@pytest.mark.parametrize("url", [ORIGIN + "/other/project/-/work_items/6", "http://127.0.0.1:8930" + "/6"])
async def test_effect_scope_cannot_leave_discovered_project_or_origin(url):
    policy, history = await discovered()
    with pytest.raises(BrowserError):
        await policy.decide(observation(detail(), url), history)


async def test_larger_or_changing_issue_list_is_not_a_complete_discovery():
    policy, history = BrowserReadinessPolicy(INSTRUCTION, ax_nodes), []
    await action(policy, history, "\t[2] link 'Release Operations'", ORIGIN + "/dashboard/projects")
    with pytest.raises(BrowserError, match="complete unambiguous"):
        await policy.decide(observation(issue_list(total=24), LIST), history)


async def test_missing_list_total_cannot_establish_complete_discovery():
    policy, history = BrowserReadinessPolicy(INSTRUCTION, ax_nodes), []
    await action(policy, history, "\t[2] link 'Release Operations'", ORIGIN + "/dashboard/projects")
    with pytest.raises(BrowserError, match="complete unambiguous"):
        await policy.decide(observation(issue_list().replace("\tStaticText '4 items'\n", ""), LIST), history)


async def test_another_issue_description_cannot_replace_the_target_after_discovery():
    policy, history = await discovered()
    with pytest.raises(BrowserError, match="another release"):
        await policy.decide(observation(detail(release="REL-2026-2043"), TARGET_URL), history)


async def test_duplicate_description_markers_are_not_unique_scope():
    policy, history = await discovered()
    text = detail().replace("Release reference: REL-2026-2042", "Release reference: REL-2026-2042 "
                            "Release reference: REL-2026-2043")
    with pytest.raises(BrowserError, match="one release description"):
        await policy.decide(observation(text, TARGET_URL), history)


async def test_baseline_and_reference_factory_do_not_consume_recipe_metadata():
    class PublicTask:
        id = "gitlab-release-readiness"
        instruction = INSTRUCTION

        def __getattr__(self, name):
            raise AssertionError(f"privileged task attribute requested: {name}")

    events = []
    for provider, baseline in [("browser-reference", False), ("browser-baseline", True)]:
        policy = create_browser_policy(BrowserAttemptConfig(task_id=PublicTask.id, provider_id=provider), PublicTask())
        assert isinstance(policy, BrowserReadinessPolicy)
        policy.set_recorder(lambda event, data: events.append((event, data)))
        await policy.prepare()
        assert policy.evidence_metadata["baseline"] is baseline
        assert policy.evidence_metadata["capability_measurement"] is False
        assert policy.evidence_metadata["training_eligible"] is False
        if baseline:
            assert (await policy.decide(observation("", ORIGIN + "/dashboard/projects"), [])).action.kind == "finish"
        await policy.close()
    assert len(events) == 2
    legacy = SimpleNamespace(id="gitlab-release-close", instruction="In Release Operations, "
                             "find Deployment reference: REL-2026-1042. Add exactly: Ready. Then close that issue.")
    assert isinstance(create_browser_policy(BrowserAttemptConfig(task_id=legacy.id, provider_id="browser-baseline"),
                                           legacy), BrowserReferencePolicy)
    model = create_browser_policy(BrowserAttemptConfig(task_id=PublicTask.id), PublicTask())
    assert isinstance(model, OllamaBrowserPolicy)
    await model.close()


def test_control_source_has_no_privileged_import_or_recipe_input():
    import world_engine.browser_readiness as module

    tree = ast.parse(Path(module.__file__).read_text())
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    assert all(not any(term in name for term in ("fixture", "verify", "runtime", "taskpacks")) for name in imports)
    assert not any(isinstance(node, ast.Attribute) and node.attr in ("seed", "case", "expected", "protected")
                   for node in ast.walk(tree))
    assert not any(isinstance(node, ast.Assert) for node in ast.walk(tree))


@pytest.mark.parametrize("instruction", ["", INSTRUCTION.replace("username @root", "username @other"),
                                         INSTRUCTION.replace("release=REL-2026-2042", "release=REL-2026-2043")])
def test_malformed_public_instruction_fails_closed(instruction):
    with pytest.raises(BrowserError, match="public instruction"):
        BrowserReadinessPolicy(instruction, ax_nodes)
