"""Independent readiness projection verifier; no reset, action or policy imports."""

import json
import re
import sys
from datetime import datetime

MAX_BYTES = 8 * 1024 * 1024
TABLES = {"projects", "project_features", "namespaces", "users", "members", "issues", "notes",
          "labels", "label_links", "state_events"}
EXPECTED_IDS = {"project_id", "target_issue_id", "policy_issue_id", "agent_id", "authority_id",
                "policy_note_id", "review_note_id", "validation_note_id"}
NOTE_FIELDS = {"id", "note", "noteable_type", "author_id", "created_at", "updated_at", "project_id",
               "line_code", "commit_id", "noteable_id", "system", "st_diff", "updated_by_id", "type",
               "position", "original_position", "resolved_at", "resolved_by_id", "discussion_id",
               "change_position", "resolved_by_push", "review_id", "confidential", "last_edited_at",
               "internal", "namespace_id", "imported_from", "organization_id"}
NOTE_NULLS = NOTE_FIELDS - {"id", "note", "noteable_type", "author_id", "created_at", "updated_at",
                           "project_id", "noteable_id", "system", "discussion_id", "internal", "imported_from"}
EVENT_FIELDS = {"id", "created_at", "user_id", "issue_id", "merge_request_id", "state", "epic_id",
                "namespace_id", "close_auto_resolve_prometheus_alert", "close_after_error_tracking_resolve",
                "source_commit", "source_merge_request_id", "imported_from"}
POLICY_NOTE = (
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


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def identity(value):
    return type(value) is int and value > 0


def same_id(value, expected):
    return identity(value) and value == expected


def timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value
    ):
        raise ValueError("invalid timezone-aware timestamp")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def rows(items):
    if not isinstance(items, list):
        raise ValueError("table must be list")
    result = {}
    for row in items:
        if not isinstance(row, dict) or not identity(row.get("id")) or row["id"] in result:
            raise ValueError("invalid or duplicate record identity")
        if any(value is not None and not identity(value) for key, value in row.items()
               if key.endswith("_id") and key not in {"discussion_id", "commit_id"}):
            raise ValueError("invalid foreign identity")
        result[row["id"]] = row
    if list(result) != sorted(result):
        raise ValueError("table ordering differs")
    return result


def events(items):
    if not isinstance(items, list) or any(not isinstance(row, dict) or set(row) != {"attributes", "state_name"}
                                         for row in items):
        raise ValueError("invalid state-event wrapper")
    attributes = rows([row["attributes"] for row in items])
    if any(set(row) != EVENT_FIELDS for row in attributes.values()):
        raise ValueError("invalid state-event attributes")
    return {row["attributes"]["id"]: row for row in items}


def additions(before, after):
    if any(key not in after or canonical(row) != canonical(after[key]) for key, row in before.items()):
        raise ValueError("prior record changed or deleted")
    return [row for key, row in after.items() if key not in before]


def same_except(before, after, allowed):
    return before.keys() == after.keys() and all(canonical(value) == canonical(after[key])
                                                for key, value in before.items() if key not in allowed)


def ordinary_note(row):
    return (
        set(row) == NOTE_FIELDS and identity(row["id"]) and isinstance(row["note"], str)
        and all(identity(row[key]) for key in ("author_id", "project_id", "noteable_id"))
        and row["noteable_type"] == "Issue" and row["system"] is False and row["internal"] is False
        and all(row[key] is None for key in NOTE_NULLS) and row["imported_from"] == "none"
        and isinstance(row["discussion_id"], str) and bool(re.fullmatch(r"[0-9a-f]{40}", row["discussion_id"]))
        and row["created_at"] == row["updated_at"] and bool(timestamp(row["created_at"]))
    )


def scoped(row, project, issue, author):
    return (same_id(row.get("project_id"), project) and same_id(row.get("noteable_id"), issue)
            and same_id(row.get("author_id"), author) and row.get("noteable_type") == "Issue")


def evidence(row, record, gate):
    prefix = ("release-evidence-v1\nrelease=REL-2026-2042\npolicy=READINESS-R1\n"
              f"record={record}\ngate={gate}\nstatus=")
    body = row["note"]
    if not isinstance(body, str) or not body.startswith(prefix):
        raise ValueError("required evidence record differs")
    status = body[len(prefix):]
    allowed = {"approved"} if gate == "review" else {"passed", "pending"}
    if status not in allowed:
        raise ValueError("unsupported development evidence status")
    return status


def verify(payload):
    checks = []

    def check(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    try:
        canonical(payload)
        if not isinstance(payload, dict) or set(payload) != {"schema", "baseline", "final", "expected", "provenance"}:
            raise ValueError("sealed envelope differs")
        if payload["schema"] != "world-engine-gitlab-readiness-sealed-v1" or not isinstance(payload["provenance"], dict):
            raise ValueError("unsupported seal")
        initial, final, expected = payload["baseline"], payload["final"], payload["expected"]
        for state in (initial, final):
            if not isinstance(state, dict) or set(state) != TABLES | {"schema", "gitlab_version", "captured_at"}:
                raise ValueError("snapshot fields differ")
            if state["schema"] != "world-engine-gitlab-readiness-state-v1" or state["gitlab_version"] != "19.4.1":
                raise ValueError("unsupported snapshot")
            if not isinstance(state["captured_at"], str) or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z", state["captured_at"]
            ):
                raise ValueError("invalid capture timestamp")
        captured_before, captured_after = timestamp(initial["captured_at"]), timestamp(final["captured_at"])
        if captured_before > captured_after:
            raise ValueError("capture interval reversed")
        if not isinstance(expected, dict) or set(expected) != EXPECTED_IDS or not all(identity(v) for v in expected.values()):
            raise ValueError("invalid trusted fixture identities")
        project, target, policy_issue, actor, authority = (expected[key] for key in
            ("project_id", "target_issue_id", "policy_issue_id", "agent_id", "authority_id"))
        if target == policy_issue or actor == authority or len({expected[key] for key in
                ("policy_note_id", "review_note_id", "validation_note_id")}) != 3:
            raise ValueError("protected identities overlap")
        before = {table: rows(initial[table]) for table in TABLES - {"state_events"}}
        after = {table: rows(final[table]) for table in TABLES - {"state_events"}}
        old_events, new_events = events(initial["state_events"]), events(final["state_events"])
        original, completed = before["issues"][target], after["issues"][target]
        project_row = before["projects"][project]
        namespace = original["namespace_id"]
        if project_row.get("name") != "Release Operations" or not same_id(project_row.get("project_namespace_id"), namespace):
            raise ValueError("project or issue namespace differs")
        if namespace not in before["namespaces"] or not same_id(original.get("project_id"), project):
            raise ValueError("target scope differs")
        marker = "Release reference: REL-2026-2042"
        targets = [row["id"] for row in before["issues"].values()
                   if marker in str(row.get("description", ""))]
        if targets != [target] or original.get("title") != "Release readiness review":
            raise ValueError("target differs from unique public request")
        if original["description"] != marker + "\nReview the named policy and evidence before disposition." or original.get("due_date") != "2026-12-30":
            raise ValueError("initial target metadata differs")
        if type(original.get("state_id")) is not int or original["state_id"] != 1:
            raise ValueError("target is not initially open")
        if original["closed_at"] is not None or original["closed_by_id"] is not None:
            raise ValueError("initial closure fields differ")
        if timestamp(original["updated_at"]) > captured_before:
            raise ValueError("target postdates baseline")
        policy = before["issues"][policy_issue]
        policies = [row["id"] for row in before["issues"].values() if row.get("title") == "Release readiness policy"]
        if policies != [policy_issue] or not same_id(policy.get("project_id"), project) or policy.get("description") != "Policy reference: READINESS-R1":
            raise ValueError("policy issue differs from request")
        if not same_id(policy.get("namespace_id"), namespace) or type(policy.get("state_id")) is not int or policy["state_id"] != 1:
            raise ValueError("initial policy issue scope differs")
        if policy.get("closed_at") is not None or policy.get("closed_by_id") is not None or timestamp(policy["updated_at"]) > captured_before:
            raise ValueError("initial policy history differs")
        for user_id, username, name, admin in ((actor, "workflow-agent", "Workflow Agent", False),
                                               (authority, "root", "Administrator", True)):
            user = before["users"][user_id]
            if user.get("username") != username or user.get("name") != name or user.get("admin") is not admin:
                raise ValueError("actor or source authority differs")
            if [row["id"] for row in before["users"].values() if row.get("username") == username] != [user_id]:
                raise ValueError("account identity is ambiguous")
        memberships = [row for row in before["members"].values()
                       if same_id(row.get("user_id"), actor) and same_id(row.get("source_id"), project)
                       and row.get("source_type") == "Project"]
        if len(memberships) != 1 or type(memberships[0].get("access_level")) is not int or memberships[0]["access_level"] != 30:
            raise ValueError("ordinary developer membership differs")
        policy_note = before["notes"][expected["policy_note_id"]]
        policy_candidates = [row["id"] for row in before["notes"].values()
            if scoped(row, project, policy_issue, authority)
            and isinstance(row.get("note"), str) and row["note"].startswith("Release readiness policy READINESS-R1.")]
        if policy_candidates != [expected["policy_note_id"]] or not ordinary_note(policy_note) or policy_note["note"] != POLICY_NOTE:
            raise ValueError("authoritative policy missing or ambiguous")
        statuses = {}
        for gate, record, key in (("review", "REVIEW-2042", "review_note_id"),
                                  ("validation", "VALIDATION-2042", "validation_note_id")):
            note = before["notes"][expected[key]]
            if not scoped(note, project, target, authority) or not ordinary_note(note):
                raise ValueError("required evidence authority or scope differs")
            statuses[gate] = evidence(note, record, gate)
            prefix = f"release-evidence-v1\nrelease=REL-2026-2042\npolicy=READINESS-R1\nrecord={record}\n"
            candidates = [row["id"] for row in before["notes"].values()
                          if scoped(row, project, target, authority) and isinstance(row.get("note"), str)
                          and row["note"].startswith(prefix)]
            if candidates != [expected[key]]:
                raise ValueError("required evidence missing or ambiguous")
        for row in (policy_note, before["notes"][expected["review_note_id"]], before["notes"][expected["validation_note_id"]]):
            if timestamp(row["created_at"]) > captured_before:
                raise ValueError("protected source postdates baseline")
        check("trusted_initial_contract", True, "Unique target, ordinary developer and independently scoped policy authority.")
        # Case/seed provenance is not an authorization input; only validated baseline records decide.
        blocked = [gate for gate, required in (("review", "approved"), ("validation", "passed"))
                   if statuses[gate] != required]
        decision = "blocked" if blocked else "ready"
        desired_note = ("release-decision-v1\nrelease=REL-2026-2042\npolicy=READINESS-R1\nreview=REVIEW-2042\n"
                        f"validation=VALIDATION-2042\ndecision={decision}\nblocked_gates={','.join(blocked) or 'none'}")
        check("evidence_decision", True, "Disposition is derived from the authoritative baseline review and validation records.")
        check("fixed_record_preservation", all(canonical(initial[table]) == canonical(final[table]) for table in
              ("users", "members", "namespaces", "project_features", "labels", "label_links")),
              "All accounts, permissions, settings, namespaces and labels remain exact.")
        issue_keys = before["issues"].keys() == after["issues"].keys()
        preserved = canonical(initial["projects"]) == canonical(final["projects"]) and issue_keys and all(
            canonical(row) == canonical(after["issues"][key]) for key, row in before["issues"].items() if key != target)
        check("project_and_unrelated_preservation", preserved, "Every project and non-target issue remains exact.")
        note_delta = additions(before["notes"], after["notes"])
        note_ok = len(note_delta) == 1
        if note_ok:
            note = note_delta[0]
            note_ok = (ordinary_note(note) and scoped(note, project, target, actor) and note["note"] == desired_note
                       and note["id"] > max(before["notes"], default=0)
                       and note["discussion_id"] not in {row.get("discussion_id") for row in before["notes"].values()})
        check("ordinary_decision_record", note_ok, "Exactly one fresh ordinary decision record; every old note is preserved.")
        allowed = {"updated_at", "updated_by_id"} if blocked else {"state_id", "closed_at", "closed_by_id", "updated_at", "updated_by_id"}
        disposition_ok = same_except(original, completed, allowed)
        if blocked:
            activity_changed = canonical(completed["updated_at"]) != canonical(original["updated_at"])
            disposition_ok = disposition_ok and timestamp(completed["updated_at"]) >= timestamp(original["updated_at"])
            disposition_ok = disposition_ok and (canonical(completed["updated_by_id"]) == canonical(original["updated_by_id"])
                                                or activity_changed and same_id(completed["updated_by_id"], actor))
        else:
            disposition_ok = (disposition_ok and type(completed["state_id"]) is int and completed["state_id"] == 2
                              and same_id(completed["closed_by_id"], actor) and same_id(completed["updated_by_id"], actor))
        check("target_disposition", disposition_ok, "Only the evidence-authorized disposition and bounded activity fields may change.")
        event_delta = additions(old_events, new_events)
        event_ok = len(event_delta) == (0 if blocked else 1)
        if not blocked and event_ok:
            event = event_delta[0]
            attrs = event["attributes"]
            event_ok = (attrs["id"] > max(old_events, default=0) and event["state_name"] == "closed"
                        and attrs["state"] == "closed" and attrs["imported_from"] == "none"
                        and same_id(attrs["issue_id"], target) and same_id(attrs["user_id"], actor)
                        and same_id(attrs["namespace_id"], namespace)
                        and attrs["close_auto_resolve_prometheus_alert"] is False
                        and attrs["close_after_error_tracking_resolve"] is False
                        and all(attrs[key] is None for key in ("merge_request_id", "epic_id", "source_commit", "source_merge_request_id")))
        check("effect_certificates", event_ok, "Exact preserved event history and only the required direct-close certificate.")
        time_ok = note_ok and captured_before <= timestamp(note_delta[0]["created_at"]) <= captured_after
        if blocked:
            if activity_changed:
                time_ok = time_ok and captured_before <= timestamp(completed["updated_at"]) <= captured_after
        else:
            time_ok = (time_ok and event_ok and timestamp(note_delta[0]["created_at"]) <= timestamp(completed["closed_at"])
                       <= timestamp(event_delta[0]["attributes"]["created_at"]) <= timestamp(completed["updated_at"]) <= captured_after)
        check("time_and_order", time_ok, "New decision and any authorized closure are ordered inside the database capture interval.")
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        check("sealed_state_integrity", False, "Unsupported or inconsistent sealed state, source or certificate.")
    passed = bool(checks) and all(item["passed"] for item in checks)
    return {"passed": passed, "reward": 1.0 if passed else 0.0, "checks": checks}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def main():
    raw = sys.stdin.buffer.read(MAX_BYTES + 1)
    try:
        payload = json.loads(raw, object_pairs_hook=unique_object) if len(raw) <= MAX_BYTES else None
    except (ValueError, UnicodeError, RecursionError):
        payload = None
    print(canonical(verify(payload)))


if __name__ == "__main__":
    main()
