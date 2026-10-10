"""Offline persisted-state verifier; input is operator-only sealed JSON on stdin."""

import json
import sys
from datetime import datetime

MAX_BYTES = 8 * 1024 * 1024
TABLES = {
    "projects",
    "project_features",
    "namespaces",
    "users",
    "members",
    "issues",
    "notes",
    "labels",
    "label_links",
    "state_events",
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def rows(items):
    result = {}
    if not isinstance(items, list):
        raise ValueError("table must be a list")
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("row must be an object")
        key = item.get("id")
        if type(key) is not int or key < 1 or key in result:
            raise ValueError("invalid or duplicate row identity")
        result[key] = item
    return result


def timestamp(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except ValueError:
        return None


def events_by_id(items):
    if not isinstance(items, list):
        raise ValueError("state events must be a list")
    records = {}
    for event in items:
        if not isinstance(event, dict) or set(event) != {"attributes", "state_name"}:
            raise ValueError("invalid event schema")
        attributes = event["attributes"]
        key = attributes.get("id") if isinstance(attributes, dict) else None
        if type(key) is not int or key < 1 or key in records:
            raise ValueError("invalid or duplicate event identity")
        records[key] = event
    return records


def unchanged_except(before, after, allowed):
    if before.keys() != after.keys():
        return False
    return all(canonical(before[key]) == canonical(after[key]) for key in before if key not in allowed)


def verify(payload):
    checks = []

    def check(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    try:
        if set(payload) != {"schema", "baseline", "final", "expected", "provenance"}:
            raise ValueError("sealed envelope fields differ")
        if payload["schema"] != "world-engine-gitlab-sealed-v1":
            raise ValueError("wrong sealed schema")
        initial, final, expected = payload["baseline"], payload["final"], payload["expected"]
        for state in (initial, final):
            if set(state) != TABLES | {"schema", "gitlab_version"}:
                raise ValueError("snapshot schema differs")
            if state["schema"] != "world-engine-gitlab-state-v1" or state["gitlab_version"] != "19.4.1":
                raise ValueError("unsupported application revision")
        if set(expected) != {"project_id", "target_issue_id", "agent_id", "comment"}:
            raise ValueError("invalid trusted fixture facts")
        project, target, agent = [expected[key] for key in ("project_id", "target_issue_id", "agent_id")]
        if any(type(value) is not int or value < 1 for value in (project, target, agent)):
            raise ValueError("invalid fixture identities")
        if expected["comment"] != "Release checklist verified; ready for closure.":
            raise ValueError("invalid task comment")
        before = {key: rows(initial[key]) for key in TABLES - {"state_events"}}
        after = {key: rows(final[key]) for key in TABLES - {"state_events"}}
        original = before["issues"][target]
        completed = after["issues"][target]
        if (
            type(original.get("project_id")) is not int
            or original["project_id"] != project
            or type(original.get("state_id")) is not int
            or original["state_id"] != 1
        ):
            raise ValueError("trusted target was not initially open in its project")
        candidates = [
            row["id"]
            for row in before["issues"].values()
            if "Deployment reference: REL-2026-1042" in str(row.get("description", ""))
        ]
        if candidates != [target]:
            raise ValueError("trusted target does not match the unique public request")
        if (
            before["users"][agent].get("admin") is not False
            or before["users"][agent].get("username") != "workflow-agent"
        ):
            raise ValueError("browser actor is not an ordinary account")
        if not any(
            type(row.get("user_id")) is int
            and row["user_id"] == agent
            and type(row.get("source_id")) is int
            and row["source_id"] == project
            and row.get("source_type") == "Project"
            and type(row.get("access_level")) is int
            and row["access_level"] == 30
            for row in before["members"].values()
        ):
            raise ValueError("browser actor is not the assigned project developer")
        check(
            "fixed_records",
            all(
                canonical(initial[key]) == canonical(final[key])
                for key in ("project_features", "namespaces", "users", "members", "labels", "label_links")
            ),
            "Project access, accounts, labels and namespaces remain unchanged.",
        )
        check(
            "project_preservation",
            before["projects"].keys() == after["projects"].keys()
            and all(
                unchanged_except(
                    row,
                    after["projects"][key],
                    {"last_activity_at", "updated_at"} if key == project else set(),
                )
                for key, row in before["projects"].items()
            ),
            "No project creation/deletion or settings changes; activity timestamps may advance.",
        )
        check(
            "issue_preservation",
            before["issues"].keys() == after["issues"].keys()
            and all(
                canonical(row) == canonical(after["issues"][key])
                for key, row in before["issues"].items()
                if key != target
            ),
            "All unrelated issues remain byte-equivalent in the exported projection.",
        )
        allowed = {"state_id", "closed_at", "closed_by_id", "updated_at", "lock_version"}
        closed = (
            type(completed.get("state_id")) is int
            and completed["state_id"] == 2
            and type(completed.get("closed_by_id")) is int
            and completed["closed_by_id"] == agent
            and timestamp(completed.get("closed_at"))
            and timestamp(completed.get("updated_at"))
        )
        check(
            "authorized_closure",
            closed and unchanged_except(original, completed, allowed),
            "Exactly the assigned issue is closed by the ordinary browser actor, with immutable fields intact.",
        )
        old_notes = before["notes"]
        new_notes = after["notes"]
        preserved = all(
            key in new_notes and canonical(row) == canonical(new_notes[key]) for key, row in old_notes.items()
        )
        additions = [row for key, row in new_notes.items() if key not in old_notes]
        comments = [row for row in additions if row.get("system") is False]
        closures = [row for row in additions if row.get("system") is True]
        scoped = all(
            type(row.get("author_id")) is int
            and row["author_id"] == agent
            and row.get("noteable_type") == "Issue"
            and type(row.get("noteable_id")) is int
            and row["noteable_id"] == target
            and type(row.get("project_id")) is int
            and row["project_id"] == project
            and timestamp(row.get("created_at"))
            for row in additions
        )
        check(
            "exact_comment_and_history",
            preserved
            and scoped
            and len(comments) == 1
            and comments[0].get("note") == expected["comment"]
            and comments[0].get("internal") is False
            and len(closures) == 1
            and closures[0].get("note") == "closed"
            and len(additions) == 2,
            "One exact ordinary, non-internal comment and one closure system note; existing notes are preserved.",
        )
        old_events = initial["state_events"]
        events = final["state_events"]
        if not isinstance(old_events, list) or not isinstance(events, list):
            raise ValueError("invalid state-event history")
        old_ids = events_by_id(old_events)
        event_ids = events_by_id(events)
        delta = [event for key, event in event_ids.items() if key not in old_ids]
        event_ok = (
            len(event_ids) == len(events)
            and all(
                key in event_ids and canonical(event) == canonical(event_ids[key])
                for key, event in old_ids.items()
            )
            and len(delta) == 1
        )
        if event_ok:
            event = delta[0]
            event_ok = (
                event["state_name"] == "closed"
                and type(event["attributes"].get("issue_id")) is int
                and event["attributes"].get("issue_id") == target
                and type(event["attributes"].get("user_id")) is int
                and event["attributes"].get("user_id") == agent
                and timestamp(event["attributes"].get("created_at"))
            )
        check(
            "closure_certificate",
            event_ok,
            "One target closure state event, attributed to the ordinary actor.",
        )
        order_ok = False
        if closed and len(comments) == len(closures) == len(delta) == 1 and scoped and event_ok:
            posted = timestamp(comments[0]["created_at"])
            closed_at = timestamp(completed["closed_at"])
            original_updated = timestamp(original.get("updated_at"))
            order_ok = (
                original_updated is not None
                and original_updated <= posted <= closed_at
                and posted <= timestamp(closures[0]["created_at"])
                and posted <= timestamp(delta[0]["attributes"]["created_at"])
                and closed_at <= timestamp(completed["updated_at"])
            )
        check("requested_order", order_ok, "The exact comment precedes authorized closure.")
    except (KeyError, TypeError, ValueError, OverflowError):
        check("snapshot_integrity", False, "Malformed or incomplete trusted state cannot pass.")
    passed = bool(checks) and all(item["passed"] for item in checks)
    return {"passed": passed, "reward": 1.0 if passed else 0.0, "checks": checks}


if __name__ == "__main__":
    raw = sys.stdin.buffer.read(MAX_BYTES + 1)
    try:
        if len(raw) > MAX_BYTES:
            raise ValueError("oversize")
        payload = json.loads(raw)
    except (ValueError, TypeError):
        payload = {}
    print(json.dumps(verify(payload), sort_keys=True))
