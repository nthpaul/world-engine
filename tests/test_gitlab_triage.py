import copy
import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / "src/world_engine/taskpacks/gitlab_triage/verify.py"
SPEC = importlib.util.spec_from_file_location("triage_verifier", PATH)
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)
BEFORE = "2026-10-11T12:00:00Z"
CHANGE = "2026-10-11T12:00:01Z"
AFTER = "2026-10-11T12:00:02Z"


def payload(*, assignment=True, label=True):
    baseline = {name: [] for name in VERIFIER.TABLES}
    baseline.update(schema="world-engine-gitlab-triage-state-v1", gitlab_version="19.4.1")
    baseline["projects"] = [{"id": 1, "name": "Incident Operations", "updated_at": BEFORE,
                              "last_activity_at": BEFORE, "visibility_level": 0}]
    baseline["namespaces"] = [{"id": 10, "name": "root"}]
    baseline["project_features"] = [{"id": 1, "project_id": 1, "issues_access_level": 20}]
    baseline["users"] = [{"id": 1, "username": "workflow-agent", "admin": False},
                          {"id": 2, "username": "casey-oncall", "admin": False},
                          {"id": 3, "username": "casey-backup", "admin": False}]
    baseline["members"] = [{"id": i, "user_id": i, "source_id": 1, "source_type": "Project", "access_level": 30}
                            for i in range(1, 4)]
    baseline["issues"] = [{"id": 1, "project_id": 1, "namespace_id": 10, "state_id": 1,
                           "description": "Incident reference: INC-2026-0217", "due_date": "2026-12-30",
                           "updated_at": BEFORE, "updated_by_id": None, "lock_version": 0},
                          {"id": 2, "project_id": 1, "namespace_id": 10, "state_id": 1,
                           "description": "Incident reference: INC-2026-0218", "updated_at": BEFORE}]
    baseline["labels"] = [{"id": 1, "project_id": 1, "title": "incident"},
                          {"id": 2, "project_id": 1, "title": "severity::2"}]
    baseline["label_links"] = [link(1, 1)]
    baseline["notes"] = [{"id": 1, "note": "Existing handoff", "system": False, "internal": False}]
    if not assignment:
        baseline["issue_assignees"] = [{"user_id": 2, "issue_id": 1, "namespace_id": 10}]
    if not label:
        baseline["label_links"].append(link(2, 2))
    final = copy.deepcopy(baseline)
    if assignment or label:
        final["issues"][0].update(updated_at=AFTER, updated_by_id=1, lock_version=1)
    if assignment:
        final["issue_assignees"].append({"user_id": 2, "issue_id": 1, "namespace_id": 10})
        note = dict.fromkeys(VERIFIER.NOTE_FIELDS)
        note.update(id=2, note="assigned to @casey-oncall", noteable_type="Issue", author_id=1,
                    created_at=CHANGE, updated_at=CHANGE, project_id=1, noteable_id=1, system=True,
                    discussion_id="a" * 40, internal=False, namespace_id=10, imported_from="none")
        final["notes"].append(note)
        final["note_metadata"] = [{"id": 1, "note_id": 2, "action": "assignee", "created_at": CHANGE,
                                    "updated_at": CHANGE, "commit_count": None, "description_version_id": None,
                                    "namespace_id": 10}]
    if label:
        final["label_links"].append(link(2, 2))
        final["label_events"] = [{"action_name": "add", "attributes": {"id": 1, "action": "add",
            "issue_id": 1, "merge_request_id": None, "epic_id": None, "label_id": 2, "user_id": 1,
            "created_at": CHANGE, "reference": None, "imported_from": "none", "namespace_id": 10}}]
    return {"schema": "world-engine-gitlab-triage-sealed-v1", "baseline": baseline, "final": final,
            "expected": {"project_id": 1, "target_issue_id": 1, "agent_id": 1, "oncall_id": 2,
                         "severity_label_id": 2}, "provenance": {}}


def link(identifier, label):
    return {"id": identifier, "label_id": label, "target_id": 1, "target_type": "Issue",
            "created_at": CHANGE, "updated_at": CHANGE, "namespace_id": 10}


@pytest.mark.parametrize("assignment,label", [(True, True), (False, False), (True, False), (False, True)])
def test_candidate_legal_changes_and_legitimate_noop(assignment, label):
    value = payload(assignment=assignment, label=label)
    original = copy.deepcopy(value)
    result = VERIFIER.verify(value)
    assert result["passed"] and result["reward"] == 1.0
    assert len(result["checks"]) == 7
    assert value == original


@pytest.mark.parametrize("table,field,value", [
    ("issues", "state_id", 2), ("issues", "due_date", "2026-12-31"),
    ("issues", "description", "replaced"), ("issues", "namespace_id", 11),
    ("issues", "updated_by_id", 3), ("users", "admin", True),
    ("members", "access_level", 40), ("labels", "title", "severity::1"),
    ("projects", "visibility_level", 20), ("namespaces", "name", "different"),
    ("projects", "updated_at", {"forged": True}), ("projects", "last_activity_at", True),
    ("projects", "updated_at", "2000-01-01T00:00:00Z"),
    ("project_features", "issues_access_level", 0),
])
def test_preservation_and_actor_exploits(table, field, value):
    data = payload()
    data["final"][table][0][field] = value
    assert not VERIFIER.verify(data)["passed"]


@pytest.mark.parametrize("table", ["notes", "members", "labels", "namespaces", "label_links", "users", "issues"])
def test_prior_history_deletion_rejected(table):
    data = payload()
    del data["final"][table][0]
    assert not VERIFIER.verify(data)["passed"]


@pytest.mark.parametrize("table", ["notes", "note_metadata", "label_events", "label_links", "issue_assignees"])
def test_duplicate_effect_rejected(table):
    data = payload()
    data["final"][table].append(copy.deepcopy(data["final"][table][-1]))
    assert not VERIFIER.verify(data)["passed"]


@pytest.mark.parametrize("field,value", [("user_id", 3), ("issue_id", 2), ("namespace_id", 11),
                                         ("user_id", True), ("issue_id", 1.0)])
def test_assignment_wrong_target_identity_and_bool_rejected(field, value):
    data = payload()
    data["final"]["issue_assignees"][0][field] = value
    assert not VERIFIER.verify(data)["passed"]


@pytest.mark.parametrize("field,value", [("label_id", 1), ("user_id", 3), ("issue_id", 2),
                                         ("action", "remove"), ("namespace_id", 11),
                                         ("created_at", BEFORE), ("reference", "~999")])
def test_label_event_wrong_certificate_rejected(field, value):
    data = payload()
    data["final"]["label_events"][0]["attributes"][field] = value
    if field == "created_at":
        data["final"]["label_events"][0]["attributes"][field] = "2026-10-11T11:59:00Z"
    assert not VERIFIER.verify(data)["passed"]


@pytest.mark.parametrize("field,value", [("author_id", 3), ("noteable_id", 2), ("system", False),
                                         ("internal", True), ("note", "Agent says assigned"),
                                         ("discussion_id", "!" * 40),
                                         ("updated_at", "2027-01-01T00:00:00Z")])
def test_assignment_note_wrong_certificate_rejected(field, value):
    data = payload()
    data["final"]["notes"][1][field] = value
    assert not VERIFIER.verify(data)["passed"]


@pytest.mark.parametrize("field,value", [("action", "label"), ("note_id", 1), ("namespace_id", 11),
                                         ("created_at", "2026-10-11T11:59:00Z")])
def test_assignment_metadata_wrong_certificate_rejected(field, value):
    data = payload()
    data["final"]["note_metadata"][0][field] = value
    assert not VERIFIER.verify(data)["passed"]


def test_unrelated_change_extra_comment_missing_and_reordered_certificates():
    for mutate in (
        lambda d: d["final"]["issues"][1].update(state_id=2),
        lambda d: d["final"]["notes"].append({"id": 3, "note": "extra comment"}),
        lambda d: d["final"]["label_events"].clear(),
        lambda d: d["final"]["notes"].reverse(),
        lambda d: d["final"]["label_links"][1].update(created_at="2027-01-01T00:00:00Z"),
    ):
        data = payload()
        mutate(data)
        assert not VERIFIER.verify(data)["passed"]


def test_assignment_join_order_matches_exporter_and_preserves_crossed_pairs():
    data = payload(assignment=False, label=False)
    joins = [{"issue_id": 1, "user_id": 2, "namespace_id": 10},
             {"issue_id": 2, "user_id": 3, "namespace_id": 10},
             {"issue_id": 3, "user_id": 2, "namespace_id": 10}]
    data["baseline"]["issue_assignees"] = copy.deepcopy(joins)
    data["final"]["issue_assignees"] = copy.deepcopy(joins)
    assert VERIFIER.verify(data)["passed"]
    data["final"]["issue_assignees"][2]["user_id"] = 3
    assert not VERIFIER.verify(data)["passed"]


@pytest.mark.parametrize("value", [None, [], {"schema": "wrong"}, float("nan")])
def test_malformed_envelope_fails_redacted(value):
    result = VERIFIER.verify(value)
    assert not result["passed"] and result["reward"] == 0.0
    assert result["checks"][-1]["name"] == "sealed_state_integrity"
