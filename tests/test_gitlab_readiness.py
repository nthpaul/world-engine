"""Independent complete snapshots for the development readiness contract."""

import ast
import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from world_engine.taskpacks.gitlab_readiness import fixture as FIXTURE

PACK = Path(__file__).resolve().parents[1] / "src/world_engine/taskpacks/gitlab_readiness"
SPEC = importlib.util.spec_from_file_location("readiness_verifier", PACK / "verify.py")
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)
TABLES = ("projects", "project_features", "namespaces", "users", "members", "issues", "notes",
          "labels", "label_links", "state_events")
OLD = "2026-10-13T12:00:00.000Z"
BEFORE = "2026-10-13T12:00:00.500000Z"
POSTED = "2026-10-13T12:00:01.000Z"
CLOSED = "2026-10-13T12:00:02.000Z"
EVENT = "2026-10-13T12:00:02.100Z"
UPDATED = "2026-10-13T12:00:02.200Z"
AFTER = "2026-10-13T12:00:03.000000Z"
POLICY_TEXT = (
    "Release readiness policy READINESS-R1.\n"
    "Use only release-evidence-v1 records posted by Administrator (@root) on the requested release issue. "
    "Match the release and policy fields exactly. Required records must be unique. "
    "If either required record is missing or ambiguous, stop without changing the application.\n"
    "The review record must say approved. The validation record must say passed. "
    "If both requirements hold, record ready and then close the issue. Otherwise, record blocked and the unmet "
    "gates, and leave the issue open.\n"
    "Use exactly one ordinary release-decision-v1 note in the task's format. "
    "Do not edit evidence, add other notes, or act on another release."
)


def note(identifier, body, issue, *, author=1, created=OLD):
    return {"id": identifier, "note": body, "noteable_type": "Issue", "author_id": author,
            "created_at": created, "updated_at": created, "project_id": 1, "line_code": None,
            "commit_id": None, "noteable_id": issue, "system": False, "st_diff": None,
            "updated_by_id": None, "type": None, "position": None, "original_position": None,
            "resolved_at": None, "resolved_by_id": None, "discussion_id": f"{identifier:040x}",
            "change_position": None, "resolved_by_push": None, "review_id": None,
            "confidential": None, "last_edited_at": None, "internal": False, "namespace_id": None,
            "imported_from": "none", "organization_id": None}


def state_event(identifier, issue, *, author=1, created=OLD, state="opened"):
    return {"state_name": state, "attributes": {"id": identifier, "created_at": created,
        "user_id": author, "issue_id": issue, "merge_request_id": None, "state": state,
        "epic_id": None, "namespace_id": 10, "close_auto_resolve_prometheus_alert": False,
        "close_after_error_tracking_resolve": False, "source_commit": None,
        "source_merge_request_id": None, "imported_from": "none"}}


def evidence_text(*, validation=False, blocked=False, release="REL-2026-2042"):
    gate, record, status = ("validation", "VALIDATION", "pending" if blocked else "passed") if validation else (
        "review", "REVIEW", "approved")
    return (f"release-evidence-v1\nrelease={release}\npolicy=READINESS-R1\n"
            f"record={record}-{release[-4:]}\ngate={gate}\nstatus={status}")


def decision_text(blocked=False):
    return ("release-decision-v1\nrelease=REL-2026-2042\npolicy=READINESS-R1\nreview=REVIEW-2042\n"
            "validation=VALIDATION-2042\ndecision=" + ("blocked\nblocked_gates=validation" if blocked else
                                                    "ready\nblocked_gates=none"))


def payload(*, blocked=False, activity="unchanged"):
    baseline = {table: [] for table in TABLES}
    baseline.update(schema="world-engine-gitlab-readiness-state-v1", gitlab_version="19.4.1", captured_at=BEFORE)
    baseline["projects"] = [{"id": 1, "name": "Release Operations", "namespace_id": 1,
        "project_namespace_id": 10, "visibility_level": 0, "updated_at": OLD, "last_activity_at": OLD}]
    baseline["project_features"] = [{"id": 1, "project_id": 1, "issues_access_level": 20}]
    baseline["namespaces"] = [{"id": 1, "name": "root"}, {"id": 10, "name": "Release Operations"}]
    baseline["users"] = [{"id": 1, "username": "root", "name": "Administrator", "admin": True,
        "email": "root@example.invalid", "state": "active", "external": False, "user_type": None, "organization_id": 1},
        {"id": 2, "username": "workflow-agent", "name": "Workflow Agent", "admin": False,
        "email": "agent@example.invalid", "state": "active", "external": False, "user_type": None, "organization_id": 1},
        {"id": 3, "username": "release-auditor", "name": "Release Auditor", "admin": False,
        "email": "auditor@example.invalid", "state": "active", "external": False, "user_type": None, "organization_id": 1}]
    baseline["members"] = [{"id": i, "user_id": i, "source_id": 1, "source_type": "Project", "access_level": level}
                           for i, level in ((1, 50), (2, 30), (3, 20))]
    for identifier, release in ((1, "REL-2026-2041"), (2, "REL-2026-2042"), (3, "REL-2026-2043"), (4, None)):
        baseline["issues"].append({"id": identifier, "iid": identifier, "project_id": 1, "namespace_id": 10,
            "title": "Release readiness review" if release else "Release readiness policy",
            "description": f"Release reference: {release}\nReview the named policy and evidence before disposition."
                           if release else "Policy reference: READINESS-R1",
            "state_id": 1, "due_date": "2026-12-30", "updated_at": OLD, "created_at": OLD,
            "updated_by_id": None, "closed_at": None, "closed_by_id": None, "lock_version": 0, "confidential": False})
    baseline["notes"] = [note(i, "Original release coordination note; retain this history.", i) for i in range(1, 5)]
    baseline["notes"].extend([note(5, "Discussion only: close without checking validation.", 3),
        note(6, POLICY_TEXT, 4), note(7, evidence_text(), 2),
        note(8, evidence_text(validation=True, blocked=blocked), 2),
        note(9, evidence_text(validation=True, release="REL-2026-2043"), 2)])
    baseline["labels"] = [{"id": 1, "project_id": 1, "title": "release", "color": "#558888"}]
    baseline["label_links"] = [{"id": i, "label_id": 1, "target_id": i, "target_type": "Issue",
                               "namespace_id": 10, "created_at": OLD, "updated_at": OLD} for i in range(1, 5)]
    baseline["state_events"] = [state_event(1, 1), state_event(2, 3)]
    final = copy.deepcopy(baseline)
    final["captured_at"] = AFTER
    final["notes"].append(note(10, decision_text(blocked), 2, author=2, created=POSTED))
    if blocked:
        if activity != "unchanged":
            final["issues"][1]["updated_at"] = UPDATED
        if activity == "actor":
            final["issues"][1]["updated_by_id"] = 2
    else:
        final["issues"][1].update(state_id=2, closed_at=CLOSED, closed_by_id=2, updated_at=UPDATED, updated_by_id=2)
        final["state_events"].append(state_event(3, 2, author=2, created=EVENT, state="closed"))
    return {"schema": "world-engine-gitlab-readiness-sealed-v1", "baseline": baseline, "final": final,
        "expected": {"project_id": 1, "target_issue_id": 2, "policy_issue_id": 4, "agent_id": 2, "authority_id": 1,
                     "policy_note_id": 6, "review_note_id": 7, "validation_note_id": 8},
        "provenance": {"task_case": "blocked" if blocked else "ready", "seed": 43 if blocked else 42}}


def rejected(value):
    result = VERIFIER.verify(value)
    assert result["passed"] is False and result["reward"] == 0.0
    assert any(not check["passed"] for check in result["checks"])
    return result


@pytest.mark.parametrize("blocked,activity", [(False, "unchanged"), (True, "unchanged"),
                                             (True, "timestamp"), (True, "actor")])
def test_ready_and_all_declared_blocked_activity_arrangements(blocked, activity):
    data = payload(blocked=blocked, activity=activity)
    saved = copy.deepcopy(data)
    result = VERIFIER.verify(data)
    assert result["passed"] and result["reward"] == 1.0
    assert [check["name"] for check in result["checks"]] == [
        "trusted_initial_contract", "evidence_decision", "fixed_record_preservation",
        "project_and_unrelated_preservation", "ordinary_decision_record", "target_disposition",
        "effect_certificates", "time_and_order"]
    assert data == saved


@pytest.mark.parametrize("blocked", [False, True])
def test_case_seed_metadata_does_not_supply_the_decision(blocked):
    data = payload(blocked=blocked)
    data["provenance"] = {"task_case": "ready", "seed": 42, "expected_decision": "ready"}
    assert VERIFIER.verify(data)["passed"]
    data["provenance"] = {"task_case": "blocked", "seed": 43, "expected_decision": "blocked"}
    assert VERIFIER.verify(data)["passed"]
    data["final"]["notes"][-1]["note"] = decision_text(not blocked)
    rejected(data)


def test_changed_authoritative_status_requires_changed_disposition_not_original_case():
    data = payload()
    for state in ("baseline", "final"):
        data[state]["notes"][7]["note"] = evidence_text(validation=True, blocked=True)
    result = rejected(data)
    assert not next(check for check in result["checks"] if check["name"] == "target_disposition")["passed"]


@pytest.mark.parametrize("blocked", [False, True])
def test_finish_or_unchanged_state_cannot_earn_outcome(blocked):
    data = payload(blocked=blocked)
    data["final"] = copy.deepcopy(data["baseline"])
    data["final"]["captured_at"] = AFTER
    rejected(data)


@pytest.mark.parametrize("table", TABLES)
@pytest.mark.parametrize("mutation", ["delete", "duplicate", "reorder", "add", "boolean_id", "float_id"])
def test_all_tables_preserve_history_identity_shape_and_order(table, mutation):
    data = payload()
    items = data["final"][table]
    if mutation == "delete":
        del items[0]
    elif mutation == "duplicate":
        items.insert(1, copy.deepcopy(items[0]))
    elif mutation == "reorder":
        if len(items) == 1:
            items.append(copy.deepcopy(items[0]))
        items.reverse()
    elif mutation == "add":
        extra = copy.deepcopy(items[-1])
        (extra["attributes"] if table == "state_events" else extra)["id"] = 100
        items.append(extra)
    else:
        (items[0]["attributes"] if table == "state_events" else items[0])["id"] = True if mutation == "boolean_id" else 1.0
    rejected(data)


@pytest.mark.parametrize("table,index,field,value", [
    ("users", 1, "email", "changed@example.invalid"), ("users", 1, "admin", True),
    ("members", 1, "access_level", 40), ("members", 2, "source_type", "Namespace"),
    ("namespaces", 1, "name", "changed"), ("project_features", 0, "issues_access_level", 0),
    ("labels", 0, "color", "#000000"), ("label_links", 1, "target_id", 3),
    ("projects", 0, "last_activity_at", UPDATED), ("projects", 0, "updated_at", UPDATED),
    ("projects", 0, "visibility_level", 20), ("issues", 0, "state_id", 2),
    ("issues", 2, "description", "replaced"), ("issues", 3, "title", "replaced"),
    ("issues", 1, "lock_version", 1), ("issues", 1, "due_date", "2026-12-31"),
    ("issues", 1, "description", "replaced"), ("issues", 1, "namespace_id", 1),
    ("issues", 1, "confidential", True), ("notes", 0, "note", "edited old history"),
    ("notes", 5, "confidential", True),
])
@pytest.mark.parametrize("blocked", [False, True])
def test_preservation_includes_every_field_not_just_selected_business_fields(table, index, field, value, blocked):
    data = payload(blocked=blocked)
    data["final"][table][index][field] = value
    rejected(data)


@pytest.mark.parametrize("field,value", [
    ("id", True), ("note", "agent claims success"), ("noteable_type", "MergeRequest"),
    ("author_id", 3), ("created_at", BEFORE), ("updated_at", UPDATED), ("project_id", 2),
    ("line_code", "different"), ("commit_id", "a" * 40), ("noteable_id", 3), ("system", True),
    ("st_diff", "different"), ("updated_by_id", 2), ("type", "DiscussionNote"),
    ("position", {}), ("original_position", {}), ("resolved_at", UPDATED), ("resolved_by_id", 2),
    ("discussion_id", "!" * 40), ("change_position", {}), ("resolved_by_push", False),
    ("review_id", 1), ("confidential", False), ("last_edited_at", UPDATED), ("internal", True),
    ("namespace_id", 10), ("imported_from", "gitlab"), ("organization_id", 1),
])
@pytest.mark.parametrize("blocked", [False, True])
def test_every_ordinary_note_value_is_exact(field, value, blocked):
    data = payload(blocked=blocked)
    data["final"]["notes"][-1][field] = value
    rejected(data)


@pytest.mark.parametrize("mutation", ["missing_key", "extra_key", "duplicate", "reused_id", "reused_discussion",
                                       "boolean_author", "floating_target", "empty_discussion", "missing_note"])
def test_note_shape_freshness_and_exactly_one_effect(mutation):
    data = payload()
    row = data["final"]["notes"][-1]
    if mutation == "missing_key":
        del row["confidential"]
    elif mutation == "extra_key":
        row["additional"] = None
    elif mutation == "duplicate":
        data["final"]["notes"].append(note(11, decision_text(), 2, author=2, created=POSTED))
    elif mutation == "reused_id":
        row["id"] = 9
    elif mutation == "reused_discussion":
        row["discussion_id"] = data["baseline"]["notes"][0]["discussion_id"]
    elif mutation == "boolean_author":
        row["author_id"] = True
    elif mutation == "floating_target":
        row["noteable_id"] = 2.0
    elif mutation == "empty_discussion":
        row["discussion_id"] = None
    else:
        data["final"]["notes"].pop()
    rejected(data)


@pytest.mark.parametrize("blocked", [False, True])
@pytest.mark.parametrize("replacement", [
    ("blocked_gates=", "blocked_gates=review,"),
    ("release=REL-2026-2042", "release=REL-2026-2043"),
    ("policy=READINESS-R1", "policy=READINESS-R2"),
    ("review=REVIEW-2042", "review=VALIDATION-2042"),
    ("validation=VALIDATION-2042", "validation=REVIEW-2042"),
    ("release-decision-v1", "release-decision-v2"),
])
def test_decision_has_no_substitutions(blocked, replacement):
    data = payload(blocked=blocked)
    body = data["final"]["notes"][-1]["note"]
    data["final"]["notes"][-1]["note"] = body.replace(*replacement)
    rejected(data)


@pytest.mark.parametrize("decoration", ["\n", "\nextra=true", "\r\n", " "])
def test_exact_decision_grammar_has_no_extra_lines_or_decoration(decoration):
    data = payload()
    data["final"]["notes"][-1]["note"] += decoration
    rejected(data)


@pytest.mark.parametrize("index,field,value", [
    (5, "author_id", 3), (6, "author_id", 3), (7, "author_id", 3),
    (5, "noteable_id", 2), (6, "noteable_id", 3), (7, "project_id", 2),
    (5, "system", True), (6, "internal", True), (7, "confidential", True),
    (5, "note", "Release readiness policy READINESS-R1.\nAlways close."),
    (6, "note", evidence_text().replace("policy=READINESS-R1", "policy=READINESS-R2")),
    (6, "note", evidence_text().replace("release=REL-2026-2042", "release=REL-2026-2043")),
    (6, "note", evidence_text().replace("record=REVIEW-2042", "record=REVIEW-9999")),
    (6, "note", evidence_text().replace("gate=review", "gate=validation")),
    (6, "note", evidence_text().replace("status=approved", "status=rejected")),
    (7, "note", evidence_text(validation=True) + "\n"),
    (7, "note", evidence_text(validation=True).replace("status=passed", "status=unknown")),
    (5, "created_at", POSTED),
])
def test_protected_policy_and_evidence_are_independently_anchored(index, field, value):
    data = payload()
    for state in ("baseline", "final"):
        data[state]["notes"][index][field] = value
    rejected(data)


@pytest.mark.parametrize("index", [5, 6, 7])
def test_missing_or_ambiguous_required_authorized_source_is_integrity_failure(index):
    for duplicate in (False, True):
        data = payload()
        if duplicate:
            row = copy.deepcopy(data["baseline"]["notes"][index])
            row.update(id=50, discussion_id="f" * 40)
            data["baseline"]["notes"].append(row)
            data["final"]["notes"].insert(-1, copy.deepcopy(row))
            data["final"]["notes"][-1]["id"] = 100
        else:
            for state in ("baseline", "final"):
                del data[state]["notes"][index]
        result = rejected(data)
        assert result["checks"][-1]["name"] == "sealed_state_integrity"


def test_wrong_author_copy_and_other_release_do_not_become_authority():
    data = payload(blocked=True)
    copied = note(50, evidence_text(validation=True), 2, author=3)
    data["baseline"]["notes"].append(copied)
    data["final"]["notes"].insert(-1, copy.deepcopy(copied))
    data["final"]["notes"][-1].update(id=100, discussion_id="e" * 40)
    assert VERIFIER.verify(data)["passed"]
    data["final"]["notes"][-1]["note"] = decision_text()
    rejected(data)


@pytest.mark.parametrize("table,index,field,value", [
    ("users", 0, "username", "source-spoof"), ("users", 0, "name", "Other Administrator"),
    ("users", 0, "admin", 1), ("users", 1, "username", "root"),
    ("users", 1, "name", "Administrator"), ("users", 1, "admin", True),
    ("members", 1, "access_level", True), ("members", 1, "access_level", 40),
    ("members", 1, "source_id", 2), ("members", 1, "source_type", "Namespace"),
    ("projects", 0, "name", "Other Operations"), ("projects", 0, "project_namespace_id", 1),
    ("issues", 1, "state_id", True), ("issues", 1, "closed_at", OLD),
    ("issues", 1, "closed_by_id", 1), ("issues", 1, "due_date", "2026-12-31"),
    ("issues", 3, "description", "Policy reference: READINESS-R2"),
    ("issues", 3, "namespace_id", 1), ("issues", 3, "state_id", 2),
])
def test_initial_role_identity_and_immutable_metadata_cannot_be_substituted(table, index, field, value):
    data = payload()
    for state in ("baseline", "final"):
        data[state][table][index][field] = value
    rejected(data)


@pytest.mark.parametrize("field", sorted(VERIFIER.EXPECTED_IDS))
@pytest.mark.parametrize("value", [None, True, 0, -1, 1.0, "1"])
def test_all_expected_identities_are_strict_positive_integers(field, value):
    data = payload()
    data["expected"][field] = value
    rejected(data)


@pytest.mark.parametrize("mutation", ["swap_actor_authority", "swap_target_policy", "swap_evidence",
                                       "extra_decision", "missing_id", "duplicate_marker", "duplicate_policy"])
def test_expected_keys_and_public_targets_are_exact(mutation):
    data = payload()
    if mutation == "swap_actor_authority":
        data["expected"].update(agent_id=1, authority_id=2)
    elif mutation == "swap_target_policy":
        data["expected"].update(target_issue_id=4, policy_issue_id=2)
    elif mutation == "swap_evidence":
        data["expected"].update(review_note_id=8, validation_note_id=7)
    elif mutation == "extra_decision":
        data["expected"]["decision"] = "ready"
    elif mutation == "missing_id":
        del data["expected"]["authority_id"]
    else:
        index = 1 if mutation == "duplicate_marker" else 3
        for state in ("baseline", "final"):
            data[state]["issues"][0]["description" if index == 1 else "title"] = data[state]["issues"][index][
                "description" if index == 1 else "title"]
    rejected(data)


@pytest.mark.parametrize("field,value", [
    ("id", True), ("created_at", OLD), ("user_id", 3), ("issue_id", 3), ("merge_request_id", 1),
    ("state", "opened"), ("epic_id", 1), ("namespace_id", 1),
    ("close_auto_resolve_prometheus_alert", True), ("close_after_error_tracking_resolve", True),
    ("source_commit", "a" * 40), ("source_merge_request_id", 1), ("imported_from", "gitlab"),
])
def test_all_direct_closure_event_values_are_exact(field, value):
    data = payload()
    data["final"]["state_events"][-1]["attributes"][field] = value
    rejected(data)


@pytest.mark.parametrize("mutation", ["missing", "extra", "wrapper", "wrapper_key", "missing_key", "extra_key",
                                       "blocked_closed", "ready_open", "edited_old_event"])
def test_disposition_and_event_certificates_are_required(mutation):
    data = payload(blocked=mutation == "blocked_closed")
    if mutation == "blocked_closed":
        data["final"]["issues"][1].update(state_id=2, closed_at=CLOSED, closed_by_id=2)
    elif mutation == "ready_open":
        data["final"]["issues"][1].update(state_id=1, closed_at=None, closed_by_id=None)
    elif mutation == "missing":
        data["final"]["state_events"].pop()
    elif mutation == "extra":
        data["final"]["state_events"].append(state_event(4, 2, author=2, created=EVENT, state="closed"))
    elif mutation == "edited_old_event":
        data["final"]["state_events"][0]["attributes"]["state"] = "closed"
    elif mutation == "wrapper":
        data["final"]["state_events"][-1]["state_name"] = "opened"
    elif mutation == "wrapper_key":
        data["final"]["state_events"][-1]["additional"] = None
    elif mutation == "missing_key":
        del data["final"]["state_events"][-1]["attributes"]["imported_from"]
    else:
        data["final"]["state_events"][-1]["attributes"]["extra"] = None
    rejected(data)


@pytest.mark.parametrize("value", ["2026-10-13T11:59:59Z", "2026-10-13T12:00:00.499999Z",
                                  "2026-10-13T12:00:04Z", "2026-10-13T12:00:01", True, None, {}, "bad"])
@pytest.mark.parametrize("blocked", [False, True])
def test_note_clock_requires_equality_timezone_and_capture_bounds(value, blocked):
    data = payload(blocked=blocked)
    data["final"]["notes"][-1].update(created_at=value, updated_at=value)
    rejected(data)


@pytest.mark.parametrize("field,value", [("closed_at", OLD), ("closed_at", AFTER),
                                         ("updated_at", POSTED), ("updated_at", "2026-10-13T12:00:04Z"),
                                         ("closed_by_id", 1), ("updated_by_id", 1)])
def test_ready_order_and_actor_constraints(field, value):
    data = payload()
    data["final"]["issues"][1][field] = value
    rejected(data)


@pytest.mark.parametrize("created", [POSTED, AFTER, None, "2026-10-13T12:00:02.100"])
def test_event_time_must_follow_closure_and_precede_target_update(created):
    data = payload()
    data["final"]["state_events"][-1]["attributes"]["created_at"] = created
    rejected(data)


@pytest.mark.parametrize("blocked", [False, True])
def test_capture_boundaries_are_inclusive_and_old_event_history_may_be_empty(blocked):
    data = payload(blocked=blocked)
    data["baseline"]["state_events"] = []
    data["final"]["state_events"] = [] if blocked else [state_event(1, 2, author=2, created=EVENT, state="closed")]
    data["final"]["notes"][-1].update(created_at=BEFORE, updated_at=BEFORE)
    assert VERIFIER.verify(data)["passed"]
    if blocked:
        data["final"]["notes"][-1].update(created_at=AFTER, updated_at=AFTER)
    else:
        data["final"]["notes"][-1].update(created_at=AFTER, updated_at=AFTER)
        data["final"]["issues"][1].update(closed_at=AFTER, updated_at=AFTER)
        data["final"]["state_events"][-1]["attributes"]["created_at"] = AFTER
    assert VERIFIER.verify(data)["passed"]


@pytest.mark.parametrize("updated,updater", [(OLD, 2), (UPDATED, 3), ("2026-10-13T11:59:59Z", None),
    ("2026-10-13T12:00:00.400Z", None), ("2026-10-13T12:00:04Z", 2), (UPDATED, True), (None, None)])
def test_blocked_activity_changes_are_bounded_and_paired(updated, updater):
    data = payload(blocked=True)
    data["final"]["issues"][1].update(updated_at=updated, updated_by_id=updater)
    rejected(data)


@pytest.mark.parametrize("location", ["baseline", "final"])
@pytest.mark.parametrize("mutation", ["schema", "version", "table_missing", "table_extra", "capture_naive",
                                       "capture_precision", "capture_reversed", "not_object"])
def test_snapshot_schemas_and_captures_fail_closed(location, mutation):
    data = payload()
    state = data[location]
    if mutation == "schema":
        state["schema"] = "world-engine-gitlab-state-v1"
    elif mutation == "version":
        state["gitlab_version"] = "19.4.0"
    elif mutation == "table_missing":
        del state["labels"]
    elif mutation == "table_extra":
        state["extra"] = []
    elif mutation == "capture_naive":
        state["captured_at"] = "2026-10-13T12:00:00.500000"
    elif mutation == "capture_precision":
        state["captured_at"] = "2026-10-13T12:00:00.5Z"
    elif mutation == "capture_reversed":
        state["captured_at"] = "2026-10-14T12:00:00.500000Z" if location == "baseline" else "2026-10-12T12:00:00.500000Z"
    else:
        data[location] = []
    rejected(data)


@pytest.mark.parametrize("value", [None, [], {}, True, {"schema": "wrong"}])
def test_malformed_envelopes_return_zero(value):
    rejected(value)


@pytest.mark.parametrize("raw", [b"invalid", b"\xff", b"[]", b'{"schema": NaN}', b"[" * 1200 + b"]" * 1200])
def test_standalone_verifier_malformed_input_returns_redacted_zero(raw):
    completed = subprocess.run([sys.executable, "-I", str(PACK / "verify.py")], input=raw,
                               capture_output=True, check=True)
    result = json.loads(completed.stdout)
    assert result["passed"] is False and result["reward"] == 0.0 and completed.stderr == b""
    assert b"Traceback" not in completed.stdout


def test_json_duplicate_fields_and_oversize_input_fail_closed():
    good = json.dumps(payload()).encode()
    duplicate = b'{"schema":"wrong",' + good[1:]
    for raw in (duplicate, b" " * (VERIFIER.MAX_BYTES + 1)):
        completed = subprocess.run([sys.executable, "-I", str(PACK / "verify.py")], input=raw,
                                   capture_output=True, check=True)
        result = json.loads(completed.stdout)
        assert result["passed"] is False and result["reward"] == 0.0 and completed.stderr == b""


def test_note_schema_pins_all_28_observed_fields_and_their_values():
    # The retained ordinary Note has 28 attributes; the design review's 29 was a counting error.
    expected = {"author_id", "change_position", "commit_id", "confidential", "created_at", "discussion_id",
        "id", "imported_from", "internal", "last_edited_at", "line_code", "namespace_id", "note",
        "noteable_id", "noteable_type", "organization_id", "original_position", "position", "project_id",
        "resolved_at", "resolved_by_id", "resolved_by_push", "review_id", "st_diff", "system", "type",
        "updated_at", "updated_by_id"}
    assert len(expected) == 28 and VERIFIER.NOTE_FIELDS == expected
    assert set(note(10, decision_text(), 2, author=2, created=POSTED)) == expected


def test_standalone_verifier_works_in_isolation_and_optimized_mode():
    raw = json.dumps(payload(blocked=True)).encode()
    completed = subprocess.run([sys.executable, "-O", "-I", str(PACK / "verify.py")], input=raw,
                               capture_output=True, check=True)
    assert json.loads(completed.stdout)["passed"] and completed.stderr == b""
    tree = ast.parse((PACK / "verify.py").read_text())
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imports.update(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
    assert imports == {"json", "re", "sys", "datetime"}
    assert not any(isinstance(node, ast.Assert) for node in ast.walk(tree))
    recipe = (PACK / "verifier.Dockerfile").read_text()
    assert "COPY verify.py /grader/verify.py" in recipe and "USER 65534:65534" in recipe
    assert '["python", "-I", "/grader/verify.py"]' in recipe
    assert (PACK / "export.rb").read_text().count("=>") > 10


@pytest.mark.parametrize("seed", [42, 43, 44, 45])
@pytest.mark.asyncio
async def test_fixture_task_and_trusted_ids_do_not_return_an_answer(seed):
    calls, counts = [], {}

    async def post(path, body):
        calls.append((path, copy.deepcopy(body)))
        kind = "notes" if path.endswith("/notes") else "issues" if path.endswith("/issues") else path
        counts[kind] = counts.get(kind, 0) + 1
        result = {"id": counts[kind]}
        if kind == "issues":
            result["iid"] = counts[kind]
        if kind == "notes":
            result["author"] = {"id": 1, "username": "root", "name": "Administrator"}
        return result

    facts = await FIXTURE.fixture(post, seed, "operator-owned-test-password")
    assert set(facts) == VERIFIER.EXPECTED_IDS and all(type(value) is int and value > 0 for value in facts.values())
    assert len({facts[key] for key in ("policy_note_id", "review_note_id", "validation_note_id")}) == 3
    assert FIXTURE.task(seed).instruction == FIXTURE.task(42).instruction
    assert FIXTURE.task(seed).evaluation_only is True and FIXTURE.task(seed).version == "1.0.0"
    assert FIXTURE.task(seed).grader_version == "gitlab-readiness-state-v1"
    assert FIXTURE.POLICY_NOTE == POLICY_TEXT
    records = [body["body"] for path, body in calls if path.endswith("/notes")]
    assert evidence_text() in records and evidence_text(validation=True, blocked=bool(seed % 2)) in records
    assert evidence_text(validation=True, release="REL-2026-2043") in records
    assert POLICY_TEXT in records and not any(body.startswith("release-decision-v1") for body in records)
    assert all("internal" not in body for path, body in calls if path.endswith("/notes"))
    assert len([path for path, _ in calls if path.endswith("/issues")]) == 4
    roles = [body["access_level"] for path, body in calls if path.endswith("/members")]
    assert roles == [30, 20]
    assert FIXTURE.task(42).fixture_hash != FIXTURE.task(43).fixture_hash


@pytest.mark.parametrize("value", [None, [], {"id": True}, {"id": 0}, {"id": "1"}, {"id": 1.0}])
def test_fixture_api_identity_boundary_rejects_malformed_values(value):
    with pytest.raises(ValueError):
        FIXTURE.identifier(value)


@pytest.mark.parametrize("value", [None, [], {}, {"author": True},
    {"author": {"id": 1, "username": "other", "name": "Administrator"}},
    {"author": {"id": True, "username": "root", "name": "Administrator"}}])
def test_fixture_api_source_boundary_rejects_display_name_only_or_boolean_ids(value):
    with pytest.raises(ValueError):
        FIXTURE.authority(value)
