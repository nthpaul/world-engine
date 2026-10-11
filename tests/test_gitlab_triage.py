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
CAPTURE_BEFORE = "2026-10-11T12:00:00.500000Z"
CAPTURE_AFTER = "2026-10-11T12:00:03.000000Z"


def payload(*, assignment=True, label=True):
    baseline = {name: [] for name in VERIFIER.TABLES}
    baseline.update(schema="world-engine-gitlab-triage-state-v2", gitlab_version="19.4.1",
                    captured_at=CAPTURE_BEFORE)
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
    final["captured_at"] = CAPTURE_AFTER
    if assignment or label:
        final["issues"][0].update(updated_at=AFTER, updated_by_id=1, lock_version=1)
    if assignment:
        final["issue_assignees"].append({"user_id": 2, "issue_id": 1, "namespace_id": 10})
        note = dict.fromkeys(VERIFIER.NOTE_FIELDS)
        note.update(id=2, note="assigned to @casey-oncall", noteable_type="Issue", author_id=1,
                    created_at=CHANGE, updated_at=CHANGE, project_id=1, noteable_id=1, system=True,
                    discussion_id="a" * 40, internal=False, namespace_id=None, imported_from="none")
        final["notes"].append(note)
        final["note_metadata"] = [{"id": 1, "note_id": 2, "action": "assignee", "created_at": CHANGE,
                                    "updated_at": CHANGE, "commit_count": None, "description_version_id": None,
                                    "namespace_id": 10}]
    if label:
        final["label_links"].append(link(2, 2))
        final["label_events"] = [{"action_name": "add", "attributes": {"id": 1, "action": "add",
            "issue_id": 1, "merge_request_id": None, "epic_id": None, "label_id": 2, "user_id": 1,
            "created_at": CHANGE, "reference": None, "imported_from": "none", "namespace_id": 10}}]
    return {"schema": "world-engine-gitlab-triage-sealed-v2", "baseline": baseline, "final": final,
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


def prior_label_events_payload(*, assignment=True, label=True, reference=None):
    data = payload(assignment=assignment, label=label)
    template = payload()["final"]["label_events"][0]
    prior = []
    for identifier in (1, 2):
        event = copy.deepcopy(template)
        event["attributes"].update(id=identifier, label_id=1, issue_id=identifier,
                                   created_at=BEFORE, reference=reference)
        prior.append(event)
    data["baseline"]["label_events"] = copy.deepcopy(prior)
    for event in data["final"]["label_events"]:
        event["attributes"]["id"] += len(prior)
    data["final"]["label_events"] = copy.deepcopy(prior) + data["final"]["label_events"]
    return data


@pytest.mark.parametrize("assignment,label", [(True, True), (False, False), (True, False), (False, True)])
@pytest.mark.parametrize("reference", [None, "~1"])
def test_prior_label_event_reference_unchanged_or_exact_display_population(assignment, label, reference):
    data = prior_label_events_payload(assignment=assignment, label=label, reference=reference)
    for event in data["final"]["label_events"][:2]:
        event["attributes"]["reference"] = "~1"
    original = copy.deepcopy(data)
    result = VERIFIER.verify(data)
    assert result["passed"] and result["reward"] == 1.0
    assert data == original
    assert VERIFIER.verify(prior_label_events_payload(assignment=assignment, label=label,
                                                     reference=reference))["passed"]


@pytest.mark.parametrize("field,value", [
    ("reference", "~2"), ("reference", 1), ("reference", True),
    ("reference", "1"), ("reference", "~01"), ("reference", "~1 "),
    ("id", 9), ("label_id", 2), ("label_id", True), ("label_id", 1.0),
    ("user_id", 3), ("user_id", True), ("issue_id", 2), ("issue_id", 1.0),
    ("namespace_id", 11), ("action", "remove"), ("created_at", AFTER),
    ("merge_request_id", 99), ("imported_from", "github"),
])
def test_prior_label_event_display_population_does_not_authorize_history_mutation(field, value):
    data = prior_label_events_payload()
    data["final"]["label_events"][0]["attributes"].update(reference="~1")
    data["final"]["label_events"][0]["attributes"][field] = value
    assert not VERIFIER.verify(data)["passed"]


@pytest.mark.parametrize("value", [None, "~2", True, 1, "~01"])
def test_populated_prior_label_reference_cannot_revert_or_change(value):
    data = prior_label_events_payload(reference="~1")
    data["final"]["label_events"][0]["attributes"]["reference"] = value
    assert not VERIFIER.verify(data)["passed"]


@pytest.mark.parametrize("mutation", ["delete", "duplicate", "reorder", "wrapper_action", "extra_wrapper",
                                       "drop_reference", "drop_attribute", "extra_attribute"])
def test_prior_label_history_shape_and_order_stay_exact(mutation):
    data = prior_label_events_payload()
    history = data["final"]["label_events"]
    history[0]["attributes"]["reference"] = "~1"
    if mutation == "delete":
        del history[0]
    elif mutation == "duplicate":
        history.insert(1, copy.deepcopy(history[0]))
    elif mutation == "reorder":
        history[0], history[1] = history[1], history[0]
    elif mutation == "wrapper_action":
        history[0]["action_name"] = "remove"
    elif mutation == "extra_wrapper":
        history[0]["claimed_authorized"] = True
    elif mutation == "drop_reference":
        del history[0]["attributes"]["reference"]
    elif mutation == "drop_attribute":
        del history[0]["attributes"]["user_id"]
    else:
        history[0]["attributes"]["claimed_authorized"] = True
    assert not VERIFIER.verify(data)["passed"]


@pytest.mark.parametrize("value", [None, [], {"schema": "wrong"}, float("nan")])
def test_malformed_envelope_fails_redacted(value):
    result = VERIFIER.verify(value)
    assert not result["passed"] and result["reward"] == 0.0
    assert result["checks"][-1]["name"] == "sealed_state_integrity"


def test_assignment_note_schema_matches_retained_gitlab_19_project_note_shape():
    # Reduced, declared fixture shape; this is not a regrade of the original V3 attempt.
    expected = {"author_id", "change_position", "commit_id", "confidential", "created_at", "discussion_id",
                "id", "imported_from", "internal", "last_edited_at", "line_code", "namespace_id", "note",
                "noteable_id", "noteable_type", "organization_id", "original_position", "position", "project_id",
                "resolved_at", "resolved_by_id", "resolved_by_push", "review_id", "st_diff", "system", "type",
                "updated_at", "updated_by_id"}
    assert VERIFIER.NOTE_FIELDS == expected and len(expected) == 28


@pytest.mark.parametrize("assignment_first", [True, False])
def test_independent_capture_bound_accepts_both_legal_operation_orders(assignment_first):
    data = payload()
    assignment_time = "2026-10-11T12:00:01.500Z" if assignment_first else "2026-10-11T12:00:02.500Z"
    label_time = "2026-10-11T12:00:02.500Z" if assignment_first else "2026-10-11T12:00:01.500Z"
    data["final"]["notes"][1].update(created_at=assignment_time, updated_at=assignment_time)
    data["final"]["note_metadata"][0].update(created_at=assignment_time, updated_at=assignment_time)
    data["final"]["label_links"][1].update(created_at=label_time, updated_at=label_time)
    data["final"]["label_events"][0]["attributes"]["created_at"] = label_time
    # Both certificate families can be committed after the issue's own timestamp.
    assert VERIFIER.verify(data)["passed"]


def test_observed_assignment_timing_shape_is_valid_partial_progress_not_success():
    data = payload()
    data["final"]["issues"][0]["updated_at"] = "2026-10-11T12:00:01.983Z"
    data["final"]["notes"][1].update(created_at="2026-10-11T12:00:01.996Z",
                                       updated_at="2026-10-11T12:00:01.996Z")
    data["final"]["note_metadata"][0].update(created_at="2026-10-11T12:00:02.007Z",
                                             updated_at="2026-10-11T12:00:02.007Z")
    data["final"]["label_links"] = copy.deepcopy(data["baseline"]["label_links"])
    data["final"]["label_events"] = []
    result = VERIFIER.verify(data)
    checks = {item["name"]: item["passed"] for item in result["checks"]}
    assert checks["assignment_certificate"] and checks["exact_assignment"] and checks["issue_preservation"]
    assert not checks["exact_severity"] and not checks["label_certificate"]
    assert result["reward"] == 0.0 and not result["passed"]


@pytest.mark.parametrize("state", ["baseline", "final"])
@pytest.mark.parametrize("value", [None, True, 1, {}, "invalid", "2026-10-11T12:00:00Z",
                                  "2026-10-11T12:00:00.000000+00:00", "2026-13-11T12:00:00.000000Z"])
def test_capture_timestamp_requires_exact_utc_database_format(state, value):
    data = payload()
    data[state]["captured_at"] = value
    result = VERIFIER.verify(data)
    assert result["reward"] == 0.0 and result["checks"][-1]["name"] == "sealed_state_integrity"


@pytest.mark.parametrize("state", ["baseline", "final"])
def test_capture_timestamp_cannot_be_missing(state):
    data = payload()
    del data[state]["captured_at"]
    assert VERIFIER.verify(data)["reward"] == 0.0


def test_reversed_capture_interval_rejected_even_for_noop():
    data = payload(assignment=False, label=False)
    data["baseline"]["captured_at"], data["final"]["captured_at"] = CAPTURE_AFTER, CAPTURE_BEFORE
    assert VERIFIER.verify(data)["reward"] == 0.0


def test_baseline_capture_cannot_predate_the_initial_target_record():
    data = payload(assignment=False, label=False)
    data["baseline"]["captured_at"] = "2026-10-11T11:59:59.999999Z"
    assert VERIFIER.verify(data)["reward"] == 0.0


@pytest.mark.parametrize("table,index,wrapped,field", [
    ("issues", 0, False, "updated_at"), ("notes", 1, False, "created_at"),
    ("notes", 1, False, "updated_at"), ("note_metadata", 0, False, "created_at"),
    ("note_metadata", 0, False, "updated_at"), ("label_links", 1, False, "created_at"),
    ("label_links", 1, False, "updated_at"), ("label_events", 0, True, "created_at"),
    ("projects", 0, False, "updated_at"), ("projects", 0, False, "last_activity_at"),
])
@pytest.mark.parametrize("value", ["2026-10-11T12:00:00.499999Z", "2026-10-11T12:00:03.000001Z"])
def test_changed_timestamp_must_be_inside_trusted_capture_interval(table, index, wrapped, field, value):
    data = payload()
    row = data["final"][table][index]
    if wrapped:
        row = row["attributes"]
    row[field] = value
    assert VERIFIER.verify(data)["reward"] == 0.0


def test_unchanged_old_project_timestamps_need_not_fall_inside_attempt_interval():
    data = payload()
    assert data["final"]["projects"][0]["updated_at"] == BEFORE
    assert VERIFIER.verify(data)["passed"]
    data["final"]["projects"][0].update(updated_at=AFTER, last_activity_at=AFTER)
    assert VERIFIER.verify(data)["passed"]


@pytest.mark.parametrize("value", [False, 0, 10, 11, "10", 10.0, {}])
def test_project_note_namespace_is_exactly_null_not_a_relaxed_namespace_match(value):
    data = payload()
    data["final"]["notes"][1]["namespace_id"] = value
    assert VERIFIER.verify(data)["reward"] == 0.0


@pytest.mark.parametrize("table,index", [("note_metadata", 0), ("issue_assignees", 0), ("label_links", 1)])
@pytest.mark.parametrize("value", [None, False, 0, 10.0, "10", 11])
def test_related_certificate_namespaces_remain_exact_positive_target_identity(table, index, value):
    data = payload()
    data["final"][table][index]["namespace_id"] = value
    assert VERIFIER.verify(data)["reward"] == 0.0


@pytest.mark.parametrize("table,index", [("notes", 1), ("note_metadata", 0)])
@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_certificate_fields_are_exact_not_a_subset(table, index, mutation):
    data = payload()
    row = data["final"][table][index]
    if mutation == "missing":
        del row["namespace_id"]
    else:
        row["note_html"] = None
    assert VERIFIER.verify(data)["reward"] == 0.0


@pytest.mark.parametrize("field", sorted(VERIFIER.NOTE_FIELDS - {
    "id", "note", "noteable_type", "author_id", "created_at", "updated_at", "project_id",
    "noteable_id", "system", "discussion_id", "internal", "namespace_id", "imported_from"}))
def test_every_assignment_note_fixed_null_default_is_preserved(field):
    data = payload()
    data["final"]["notes"][1][field] = False
    assert VERIFIER.verify(data)["reward"] == 0.0


def test_note_metadata_causal_order_not_just_membership_in_capture_interval():
    data = payload()
    data["final"]["notes"][1]["updated_at"] = "2026-10-11T12:00:00.900Z"
    assert VERIFIER.verify(data)["reward"] == 0.0
    data = payload()
    data["final"]["note_metadata"][0].update(created_at="2026-10-11T12:00:00.900Z")
    assert VERIFIER.verify(data)["reward"] == 0.0
    data = payload()
    data["final"]["note_metadata"][0].update(updated_at="2026-10-11T12:00:00.900Z")
    assert VERIFIER.verify(data)["reward"] == 0.0


def test_legacy_schema_is_not_silently_regraded_with_current_contract():
    data = payload()
    data["schema"] = "world-engine-gitlab-triage-sealed-v1"
    for state in (data["baseline"], data["final"]):
        state["schema"] = "world-engine-gitlab-triage-state-v1"
        del state["captured_at"]
    assert VERIFIER.verify(data)["reward"] == 0.0


@pytest.mark.parametrize("field,value", [
    ("id", True), ("id", 1), ("author_id", True), ("author_id", 1.0),
    ("project_id", 2), ("project_id", True), ("noteable_id", 1.0),
    ("noteable_type", "MergeRequest"), ("system", 1), ("internal", 0),
    ("imported_from", "github"),
])
def test_new_project_note_null_namespace_never_substitutes_for_exact_scope(field, value):
    data = payload()
    data["final"]["notes"][1][field] = value
    assert VERIFIER.verify(data)["reward"] == 0.0


@pytest.mark.parametrize("field,value", [("note_id", True), ("note_id", 2.0),
                                         ("commit_count", 0), ("description_version_id", False)])
def test_metadata_link_and_fixed_defaults_remain_type_sensitive(field, value):
    data = payload()
    data["final"]["note_metadata"][0][field] = value
    assert VERIFIER.verify(data)["reward"] == 0.0


def test_equal_capture_times_allow_unchanged_state_without_new_certificates():
    data = payload(assignment=False, label=False)
    data["final"]["captured_at"] = data["baseline"]["captured_at"]
    assert VERIFIER.verify(data)["passed"]


def test_exporter_records_database_clock_inside_read_only_repeatable_read_transaction():
    source = PATH.with_name("export.rb").read_text()
    assert "transaction(isolation: :repeatable_read)" in source
    assert "SET TRANSACTION READ ONLY" in source
    assert source.index("SET TRANSACTION READ ONLY") < source.index("'captured_at'")
    assert "SELECT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"')" in source
    assert "world-engine-gitlab-triage-state-v2" in source
    assert "Time.now" not in source and "clock_timestamp" not in source
