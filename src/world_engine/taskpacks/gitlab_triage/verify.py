"""Independent triage projection verifier; no application calls or action replay."""

import json
import re
import sys
from datetime import datetime

MAX_BYTES = 8 * 1024 * 1024
TABLES = {"projects", "project_features", "namespaces", "users", "members", "issues", "notes",
          "labels", "label_links", "issue_assignees", "note_metadata", "label_events", "state_events"}
LINK_FIELDS = {"id", "label_id", "target_id", "target_type", "created_at", "updated_at", "namespace_id"}
LABEL_EVENT_FIELDS = {"id", "action", "issue_id", "merge_request_id", "epic_id", "label_id", "user_id",
                      "created_at", "reference", "imported_from", "namespace_id"}
NOTE_FIELDS = {"id", "note", "noteable_type", "author_id", "created_at", "updated_at", "project_id",
               "line_code", "commit_id", "noteable_id", "system", "st_diff", "updated_by_id", "type",
               "position", "original_position", "resolved_at", "resolved_by_id", "discussion_id", "note_html",
               "cached_markdown_version", "change_position", "resolved_by_push", "review_id", "confidential",
               "last_edited_at", "internal", "namespace_id", "imported_from", "organization_id"}
NOTE_METADATA_FIELDS = {"id", "note_id", "action", "created_at", "updated_at", "commit_count",
                        "description_version_id", "namespace_id"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def identity(value):
    return type(value) is int and value > 0


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("invalid timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp needs timezone")
    return result


def rows(items, keys=("id",)):
    if not isinstance(items, list):
        raise ValueError("table must be list")
    result = {}
    for row in items:
        if not isinstance(row, dict) or any(not identity(row.get(key)) for key in keys):
            raise ValueError("invalid record identity")
        key = tuple(row[field] for field in keys)
        if key in result:
            raise ValueError("duplicate record")
        result[key] = row
    if list(result) != sorted(result):
        raise ValueError("table ordering differs")
    return result


def events(items):
    if not isinstance(items, list):
        raise ValueError("event table must be list")
    result = {}
    for row in items:
        if not isinstance(row, dict) or set(row) != {"attributes", "action_name"}:
            raise ValueError("invalid label event wrapper")
        attributes = row["attributes"]
        if not isinstance(attributes, dict) or not identity(attributes.get("id")):
            raise ValueError("invalid event identity")
        key = attributes["id"]
        if key in result:
            raise ValueError("duplicate event")
        result[key] = row
    if list(result) != sorted(result):
        raise ValueError("event ordering differs")
    return result


def additions(before, after):
    if not all(key in after and canonical(row) == canonical(after[key]) for key, row in before.items()):
        raise ValueError("prior record changed or deleted")
    return [row for key, row in after.items() if key not in before]


def fresh_ids(before, added):
    maximum = max((key[0] if isinstance(key, tuple) else key for key in before), default=0)
    return all(row["id"] > maximum for row in added)


def same_except(before, after, allowed):
    return before.keys() == after.keys() and all(canonical(value) == canonical(after[key])
                                                 for key, value in before.items() if key not in allowed)


def label_event_additions(before, after):
    for key, previous in before.items():
        if key not in after:
            raise ValueError("prior label event deleted")
        current = after[key]
        old, new = previous["attributes"], current["attributes"]
        unchanged = canonical(previous) == canonical(current)
        display_only = (
            canonical(previous["action_name"]) == canonical(current["action_name"])
            and same_except(old, new, {"reference"})
            and old["reference"] is None
            and identity(old["label_id"])
            and new["reference"] == f"~{old['label_id']}"
        )
        if not (unchanged or display_only):
            raise ValueError("prior label event changed")
    return [row for key, row in after.items() if key not in before]


def verify(payload):
    checks = []

    def check(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    try:
        if not isinstance(payload, dict) or set(payload) != {"schema", "baseline", "final", "expected", "provenance"}:
            raise ValueError("sealed envelope schema differs")
        if payload["schema"] != "world-engine-gitlab-triage-sealed-v1":
            raise ValueError("wrong sealed schema")
        initial, final, expected = payload["baseline"], payload["final"], payload["expected"]
        for state in (initial, final):
            if not isinstance(state, dict) or set(state) != TABLES | {"schema", "gitlab_version"}:
                raise ValueError("snapshot schema differs")
            if state["schema"] != "world-engine-gitlab-triage-state-v1" or state["gitlab_version"] != "19.4.1":
                raise ValueError("unsupported snapshot version")
        if not isinstance(expected, dict) or set(expected) != {"project_id", "target_issue_id", "agent_id", "oncall_id", "severity_label_id"}:
            raise ValueError("invalid fixture facts")
        if not all(identity(value) for value in expected.values()):
            raise ValueError("invalid fixture identities")
        project, target, agent, oncall, label = (expected[key] for key in
            ("project_id", "target_issue_id", "agent_id", "oncall_id", "severity_label_id"))
        before = {table: rows(initial[table], ("issue_id", "user_id") if table == "issue_assignees" else ("id",))
                  for table in TABLES - {"label_events", "state_events"}}
        after = {table: rows(final[table], ("issue_id", "user_id") if table == "issue_assignees" else ("id",))
                 for table in TABLES - {"label_events", "state_events"}}
        original, completed = before["issues"][(target,)], after["issues"][(target,)]
        namespace = original["namespace_id"]
        if not identity(namespace) or type(original.get("project_id")) is not int or original["project_id"] != project or original.get("state_id") != 1 or type(original["state_id"]) is not int:
            raise ValueError("invalid initial issue")
        candidates = [row["id"] for row in before["issues"].values()
                      if "Incident reference: INC-2026-0217" in str(row.get("description", ""))]
        if candidates != [target] or before["projects"][(project,)].get("name") != "Incident Operations":
            raise ValueError("target differs from public request")
        for user_id, username in ((agent, "workflow-agent"), (oncall, "casey-oncall")):
            user = before["users"][(user_id,)]
            if user.get("username") != username or user.get("admin") is not False or not any(
                type(member.get("user_id")) is int and member["user_id"] == user_id
                and type(member.get("source_id")) is int and member["source_id"] == project
                and member.get("source_type") == "Project" and type(member.get("access_level")) is int
                and member["access_level"] == 30 for member in before["members"].values()):
                raise ValueError("ordinary actor/on-call membership missing")
        wanted = before["labels"][(label,)]
        if wanted.get("title") != "severity::2" or type(wanted.get("project_id")) is not int or wanted["project_id"] != project:
            raise ValueError("severity label differs from request")
        check("fixed_records", all(canonical(initial[table]) == canonical(final[table]) for table in
              ("users", "members", "labels", "namespaces", "project_features", "state_events")),
              "Accounts, access, labels, namespaces and state-event history are unchanged.")
        project_ok = before["projects"].keys() == after["projects"].keys() and all(
            same_except(row, after["projects"][key], {"updated_at", "last_activity_at"} if key == (project,) else set())
            for key, row in before["projects"].items())
        for field in ("updated_at", "last_activity_at"):
            project_ok = project_ok and timestamp(after["projects"][(project,)][field]) >= timestamp(before["projects"][(project,)][field])
        check("project_preservation", project_ok, "Only valid nondecreasing activity timestamps may change on the assigned project.")
        initial_assignees = [row for row in before["issue_assignees"].values() if row["issue_id"] == target]
        if initial_assignees and (len(initial_assignees) != 1 or initial_assignees[0]["user_id"] != oncall):
            raise ValueError("unexpected initial assignee")
        if any(set(row) != {"user_id", "issue_id", "namespace_id"}
               or not identity(row["namespace_id"]) for row in before["issue_assignees"].values()):
            raise ValueError("invalid initial assignment join")
        need_assignment = not initial_assignees
        assignee_delta = additions(before["issue_assignees"], after["issue_assignees"])
        assignment_ok = len(assignee_delta) == int(need_assignment) and all(
            set(row) == {"user_id", "issue_id", "namespace_id"} and type(row["namespace_id"]) is int
            and row == {"user_id": oncall, "issue_id": target, "namespace_id": namespace} for row in assignee_delta)
        check("exact_assignment", assignment_ok, "Only the requested ordinary on-call account is assigned.")
        initial_links = [row for row in before["label_links"].values() if row.get("target_type") == "Issue"
                         and type(row.get("target_id")) is int and row["target_id"] == target
                         and type(row.get("label_id")) is int and row["label_id"] == label]
        if len(initial_links) > 1:
            raise ValueError("duplicate initial severity link")
        need_label = not initial_links
        link_delta = additions(before["label_links"], after["label_links"])
        link_ok = len(link_delta) == int(need_label) and fresh_ids(before["label_links"], link_delta)
        for row in link_delta:
            link_ok = link_ok and set(row) == LINK_FIELDS and all(type(row[key]) is int and row[key] == value
                for key, value in (("label_id", label), ("target_id", target), ("namespace_id", namespace))) and row["target_type"] == "Issue"
            link_ok = link_ok and timestamp(original["updated_at"]) <= timestamp(row["created_at"]) <= timestamp(completed["updated_at"])
            link_ok = link_ok and timestamp(row["created_at"]) <= timestamp(row["updated_at"]) <= timestamp(completed["updated_at"])
        check("exact_severity", link_ok, "Exactly the requested severity label is added; all prior links remain intact.")
        changed = need_assignment or need_label
        issue_ok = before["issues"].keys() == after["issues"].keys()
        for key, row in before["issues"].items():
            allowed = {"updated_at", "updated_by_id", "lock_version"} if key == (target,) and changed else set()
            issue_ok = issue_ok and same_except(row, after["issues"][key], allowed)
        if changed:
            issue_ok = issue_ok and type(completed.get("updated_by_id")) is int and completed["updated_by_id"] == agent
            issue_ok = issue_ok and timestamp(completed["updated_at"]) >= timestamp(original["updated_at"])
            if "lock_version" in original:
                issue_ok = issue_ok and type(completed["lock_version"]) is int and completed["lock_version"] >= original["lock_version"]
        check("issue_preservation", issue_ok, "Status, due date, descriptions, unrelated issues and immutable fields stay intact.")
        note_delta = additions(before["notes"], after["notes"])
        metadata_delta = additions(before["note_metadata"], after["note_metadata"])
        note_ok = len(note_delta) == int(need_assignment) and len(metadata_delta) == int(need_assignment)
        note_ok = note_ok and fresh_ids(before["notes"], note_delta) and fresh_ids(before["note_metadata"], metadata_delta)
        for row in note_delta:
            note_ok = note_ok and set(row) == NOTE_FIELDS and row.get("note") == "assigned to @casey-oncall"
            note_ok = note_ok and row.get("system") is True and row.get("internal") is False and row.get("noteable_type") == "Issue"
            note_ok = note_ok and all(type(row.get(key)) is int and row[key] == value for key, value in
                (("author_id", agent), ("project_id", project), ("noteable_id", target), ("namespace_id", namespace)))
            # These candidate defaults fail closed until qualified against a real reference receipt.
            nullable = NOTE_FIELDS - {"id", "note", "noteable_type", "author_id", "created_at", "updated_at", "project_id",
                                      "noteable_id", "system", "discussion_id", "internal", "namespace_id", "imported_from"}
            note_ok = note_ok and all(row[key] is None for key in nullable)
            note_ok = note_ok and row["imported_from"] == "none" and isinstance(row["discussion_id"], str) and bool(re.fullmatch(r"[0-9a-f]{40}", row["discussion_id"]))
            note_ok = note_ok and timestamp(original["updated_at"]) <= timestamp(row["created_at"]) <= timestamp(completed["updated_at"])
            note_ok = note_ok and timestamp(row["created_at"]) <= timestamp(row["updated_at"]) <= timestamp(completed["updated_at"])
        for row in metadata_delta:
            note_ok = note_ok and set(row) == NOTE_METADATA_FIELDS and row.get("action") == "assignee"
            note_ok = note_ok and len(note_delta) == 1 and type(row.get("note_id")) is int and row["note_id"] == note_delta[0]["id"]
            note_ok = note_ok and type(row.get("namespace_id")) is int and row["namespace_id"] == namespace
            note_ok = note_ok and row.get("commit_count") is None and row.get("description_version_id") is None
            note_ok = note_ok and len(note_delta) == 1 and timestamp(note_delta[0]["created_at"]) <= timestamp(row["created_at"]) <= timestamp(completed["updated_at"])
            note_ok = note_ok and timestamp(row["created_at"]) <= timestamp(row["updated_at"]) <= timestamp(completed["updated_at"])
        check("assignment_certificate", note_ok, "One exact system assignment certificate, no ordinary comments or unrelated history changes.")
        old_events, new_events = events(initial["label_events"]), events(final["label_events"])
        event_delta = label_event_additions(old_events, new_events)
        event_ok = len(event_delta) == int(need_label) and fresh_ids(old_events, [row["attributes"] for row in event_delta])
        for row in event_delta:
            attrs = row["attributes"]
            event_ok = event_ok and set(attrs) == LABEL_EVENT_FIELDS and row["action_name"] == "add" and attrs.get("action") == "add"
            event_ok = event_ok and all(type(attrs.get(key)) is int and attrs[key] == value for key, value in
                (("issue_id", target), ("label_id", label), ("user_id", agent), ("namespace_id", namespace)))
            event_ok = event_ok and attrs.get("merge_request_id") is None and attrs.get("epic_id") is None and attrs.get("imported_from") == "none"
            event_ok = event_ok and attrs.get("reference") in (None, f"~{label}")
            event_ok = event_ok and timestamp(original["updated_at"]) <= timestamp(attrs["created_at"]) <= timestamp(completed["updated_at"])
        check("label_certificate", event_ok, "Exactly one actor-scoped label-add event when needed; existing label history is preserved.")
    except (KeyError, TypeError, ValueError, OverflowError):
        check("sealed_state_integrity", False, "Unsupported or inconsistent sealed fixture/state/certificate schema.")
    passed = bool(checks) and all(item["passed"] for item in checks)
    return {"passed": passed, "reward": 1.0 if passed else 0.0, "checks": checks}


def main():
    raw = sys.stdin.buffer.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        payload = None
    else:
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeError):
            payload = None
    print(canonical(verify(payload)))


if __name__ == "__main__":
    main()
