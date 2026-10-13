"""Public-AX feasibility control for the release-readiness task, not a model."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from world_engine.browser_contracts import (
    BrowserDecision,
    BrowserError,
    BrowserObservation,
    Click,
    Fill,
    Finish,
    Navigate,
    Wait,
)


def _one(nodes: list[dict], role: str, name: str) -> dict | None:
    matches = [node for node in nodes if node["role"] == role and node["name"] == name]
    if len(matches) > 1:
        raise BrowserError("readiness control found ambiguous public controls")
    return matches[0] if matches else None


def _children(nodes: list[dict], index: int) -> list[dict]:
    end = index + 1
    while end < len(nodes) and nodes[end]["indent"] > nodes[index]["indent"]:
        end += 1
    return nodes[index + 1:end]


def _paragraphs(nodes: list[dict]) -> str:
    texts = []
    for index, node in enumerate(nodes):
        if node["role"] == "paragraph":
            texts.extend(child["name"] for child in _children(nodes, index)
                         if child["role"] == "StaticText")
    return "\n".join(texts)


@dataclass(frozen=True)
class _Note:
    body: str
    author: str | None
    usernames: frozenset[str]
    internal: bool

    def authoritative(self) -> bool:
        if self.author == "Administrator" and not self.usernames:
            raise BrowserError("readiness control cannot corroborate the policy author")
        if "@root" in self.usernames and (self.author != "Administrator" or len(self.usernames) != 1):
            raise BrowserError("readiness control found conflicting public author identities")
        if self.author is None:
            raise BrowserError("readiness control cannot identify a record author")
        return self.author == "Administrator" and self.usernames == frozenset({"@root"}) and not self.internal


def _notes(nodes: list[dict]) -> list[_Note]:
    activity = _one(nodes, "heading", "Activity")
    if activity is None:
        raise BrowserError("readiness control cannot find scoped issue activity")
    start = nodes.index(activity) + 1
    lists = [index for index in range(start, len(nodes)) if nodes[index]["role"] == "list"]
    if not lists:
        raise BrowserError("readiness control cannot find the activity list")
    rows = _children(nodes, lists[0])
    notes = []
    # GitLab nests each ordinary comment inside an outer discussion list item.
    for index, row in enumerate(rows):
        if row["role"] != "listitem":
            continue
        children = _children(rows, index)
        if any(child["role"] == "listitem" for child in children):
            continue
        paragraph = next((i for i, child in enumerate(children) if child["role"] == "paragraph"), None)
        if paragraph is None:
            continue
        header = children[:paragraph]
        links = [child["name"] for child in header if child["role"] == "link"]
        usernames = frozenset(name for name in links if re.fullmatch(r"@[a-zA-Z0-9_.-]+", name))
        names = {child["name"] for index, child in enumerate(header) if child["role"] == "link"
                 and child["name"] not in usernames
                 and not any(descendant["role"] == "time" for descendant in _children(header, index))}
        author = next(iter(names)) if len(names) == 1 else None
        notes.append(_Note(_paragraphs(children[paragraph:]), author, usernames,
                           any("internal note" in child["name"].lower() for child in header)))
    return notes


class BrowserReadinessPolicy:
    def __init__(self, instruction: str, ax_parser: Callable[[str], list[dict]], *, baseline: bool = False):
        match = re.search(r"\AIn (.+?), evaluate the open issue with Release reference: ([A-Z0-9-]+)\. "
                          r"Follow policy ([A-Z0-9-]+) in the issue titled (.+?)\. "
                          r"Use only the policy and matching evidence posted by Administrator, username @root\.",
                          instruction)
        grammar = re.search(r"release-decision-v1\nrelease=([A-Z0-9-]+)\npolicy=([A-Z0-9-]+)\n"
                            r"review=([A-Z0-9-]+)\nvalidation=([A-Z0-9-]+)\n"
                            r"decision=<ready or blocked>\nblocked_gates="
                            r"<none or comma-separated unmet gate names in review,validation order>", instruction)
        if not match or not grammar or match.groups()[1:3] != grammar.groups()[:2]:
            raise BrowserError("readiness control requires the supported public instruction and note grammar")
        self.project, self.release, self.policy, self.policy_title = match.groups()
        self.records = {"review": grammar[3], "validation": grammar[4]}
        self.baseline, self.ax_parser = baseline, ax_parser
        self.recorder: Callable[[str, dict], None] = lambda *_: None
        self.origin: str | None = None
        self.project_path: str | None = None
        self.project_selected = False
        self.list_url: str | None = None
        self.policy_url: str | None = None
        self.target_url: str | None = None
        self.required_status: dict[str, str] | None = None
        self.cursor = 0
        self.candidate_count: int | None = None
        self.visited: set[str] = set()
        self.discovery_done = False
        self.note_text: str | None = None
        self.prior_notes: tuple[_Note, ...] | None = None
        self.decision: str | None = None
        self.actor: str | None = None
        self.submitted = False
        self.close_requested = False
        self.plain_requested = False
        self.pending: tuple[int, dict] | None = None
        self.waits = 0
        self.evidence_metadata = {"protocol": "public-ax-release-readiness-v1",
                                  "scripted_control": True, "capability_measurement": False,
                                  "baseline": baseline, "training_eligible": False}

    def set_recorder(self, recorder: Callable[[str, dict], None]) -> None:
        self.recorder = recorder

    async def prepare(self) -> None:
        self.recorder("policy_prepared", self.evidence_metadata)

    async def close(self) -> None:
        return None

    def _emit(self, action, history: list[dict]) -> BrowserDecision:
        self.pending = (len(history), action.model_dump())
        if action.kind != "wait":
            self.waits = 0
        return BrowserDecision(action, evidence=self.evidence_metadata)

    def _wait(self, history: list[dict]) -> BrowserDecision:
        self.waits += 1
        if self.waits > 3:
            raise BrowserError("readiness control could not confirm the public browser state")
        return self._emit(Wait(seconds=1.0), history)

    def _receipt(self, history: list[dict]) -> None:
        if self.pending is None:
            return
        index, action = self.pending
        if len(history) <= index:
            raise BrowserError("readiness control lacks its browser action receipt")
        row = history[index]
        result = row.get("result") if type(row) is dict else None
        if (type(row) is not dict or type(row.get("step")) is not int or row["step"] != index
                or row.get("action") != action or type(result) is not dict or result.get("ok") is not True
                or ("uncertain_effect" in result and result["uncertain_effect"] is not False)):
            raise BrowserError("readiness control stopped after an unsuccessful or uncertain browser effect")
        self.pending = None

    def _nodes(self, text: str) -> list[dict]:
        nodes = []
        for line in text.splitlines():
            parsed = self.ax_parser(line)
            if parsed:
                nodes.append({**parsed[0], "indent": len(line) - len(line.lstrip()), "attributes": line})
        return nodes

    def _load_policy(self, notes: list[_Note]) -> None:
        candidates = [note for note in notes if note.body.startswith("Release readiness policy ")
                      and note.authoritative()]
        if len(candidates) != 1:
            raise BrowserError("readiness control requires one authoritative policy record")
        pattern = (r"Release readiness policy " + re.escape(self.policy) + r"\. "
                   r"Use only release-evidence-v1 records posted by Administrator \(@root\) on the requested "
                   r"release issue\. Match the release and policy fields exactly\. Required records must be unique\. "
                   r"If either required record is missing or ambiguous, stop without changing the application\. "
                   r"The review record must say ([a-z][a-z-]*)\. The validation record must say ([a-z][a-z-]*)\. "
                   r"If both requirements hold, record ready and then close the issue\. Otherwise, record blocked "
                   r"and the unmet gates, and leave the issue open\. Use exactly one ordinary release-decision-v1 "
                   r"note in the task's format\. Do not edit evidence, add other notes, or act on another release\.")
        match = re.fullmatch(pattern, " ".join(candidates[0].body.split()))
        if not match:
            raise BrowserError("readiness control cannot parse the authoritative public policy")
        self.required_status = dict(zip(("review", "validation"), match.groups(), strict=True))

    def _derive_note(self, notes: list[_Note]) -> None:
        records: dict[str, list[str]] = {"review": [], "validation": []}
        for note in notes:
            if note.body.startswith("release-decision-v1"):
                raise BrowserError("readiness control refuses a pre-existing decision note")
            if not note.body.startswith("release-evidence-v1"):
                continue
            match = re.fullmatch(r"release-evidence-v1\s+release=([A-Z0-9-]+)\s+policy=([A-Z0-9-]+)\s+"
                                 r"record=([A-Z0-9-]+)\s+gate=(review|validation)\s+status=([a-z][a-z-]*)",
                                 note.body)
            if not match:
                raise BrowserError("readiness control found malformed public evidence")
            release, policy, record, gate, status = match.groups()
            if release != self.release or policy != self.policy:
                continue
            if not note.authoritative():
                continue
            if record != self.records[gate]:
                raise BrowserError("readiness control found conflicting public record identities")
            records[gate].append(status)
        if any(len(values) != 1 for values in records.values()) or self.required_status is None:
            raise BrowserError("readiness control requires unique authoritative review and validation records")
        blocked = [gate for gate in ("review", "validation") if records[gate][0] != self.required_status[gate]]
        self.decision = "blocked" if blocked else "ready"
        self.note_text = "\n".join(("release-decision-v1", f"release={self.release}", f"policy={self.policy}",
                                    f"review={self.records['review']}", f"validation={self.records['validation']}",
                                    f"decision={self.decision}", f"blocked_gates={','.join(blocked) or 'none'}"))

    async def decide(self, observation: BrowserObservation, history: list[dict]) -> BrowserDecision:
        if self.baseline:
            return BrowserDecision(Finish(), evidence=self.evidence_metadata)
        self._receipt(history)
        if any(type(row) is dict and type(row.get("result")) is dict
               and row["result"].get("uncertain_effect") is True for row in history):
            raise BrowserError("readiness control stopped after an uncertain browser effect")
        nodes = self._nodes(observation.accessibility_text)
        if any(node["role"] in ("dialog", "alertdialog") for node in nodes):
            raise BrowserError("readiness control stopped at an unexpected public dialog")
        parsed = urlsplit(observation.url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if self.origin is None:
            self.origin = origin
        if origin != self.origin:
            raise BrowserError("readiness control left the observed application origin")
        actor_menus = [node["name"] for node in nodes if node["role"] == "link"
                       and node["name"].endswith(" user\u2019s menu")]
        if len(actor_menus) == 1:
            actor = actor_menus[0].removesuffix(" user\u2019s menu")
            if self.actor is not None and actor != self.actor:
                raise BrowserError("readiness control found a changed public actor")
            self.actor = actor
        if parsed.path.startswith("/dashboard/projects"):
            project = _one(nodes, "link", self.project)
            if project and project["bid"]:
                self.project_selected = True
                return self._emit(Click(bid=project["bid"]), history)
            member = [node for node in nodes if node["role"] == "tab" and node["name"].startswith("Member ")]
            if len(member) == 1 and member[0]["bid"]:
                return self._emit(Click(bid=member[0]["bid"]), history)
            return self._wait(history)
        if not self.project_selected:
            raise BrowserError("readiness control has not discovered the requested public project")
        if self.project_path is None:
            self.project_path = parsed.path.split("/-/", 1)[0].rstrip("/")
        if parsed.path != self.project_path and not parsed.path.startswith(self.project_path + "/-/"):
            raise BrowserError("readiness control left the discovered project")
        full_page = _one(nodes, "link", "Open in full page")
        if full_page and full_page["bid"]:
            return self._emit(Click(bid=full_page["bid"]), history)
        if re.fullmatch(re.escape(self.project_path) + r"/-/(?:issues|work_items)/?", parsed.path):
            query = urlencode([(key, value) for key, value in parse_qsl(parsed.query) if key != "show"])
            self.list_url = urlunsplit(parsed._replace(query=query))
            policy = _one(nodes, "link", self.policy_title)
            candidates = [node for node in nodes if node["role"] == "link"
                          and node["name"] == "Release readiness review" and node["bid"]]
            totals = [int(match[1]) for node in nodes if node["role"] == "StaticText"
                      and (match := re.fullmatch(r"([0-9]+) items", node["name"]))]
            if (policy is None or not policy["bid"] or not candidates
                    or totals != [len(candidates) + 1]
                    or self.candidate_count is not None and self.candidate_count != len(candidates)):
                raise BrowserError("readiness control requires a complete unambiguous public issue list")
            self.candidate_count = len(candidates)
            if self.required_status is None:
                return self._emit(Click(bid=policy["bid"]), history)
            if self.cursor < len(candidates):
                return self._emit(Click(bid=candidates[self.cursor]["bid"]), history)
            if self.target_url is None:
                raise BrowserError("readiness control could not discover a unique requested release")
            self.discovery_done = True
            return self._emit(Navigate(url=self.target_url), history)
        if re.fullmatch(re.escape(self.project_path) + r"/-/(?:issues|work_items)/[0-9]+", parsed.path):
            activity = _one(nodes, "heading", "Activity")
            if activity is None:
                return self._wait(history)
            before_activity = nodes[:nodes.index(activity)]
            headings = [node for node in before_activity if node["role"] == "heading"
                        and node["name"] in (self.policy_title, "Release readiness review")]
            if len(headings) != 1 or self.list_url is None:
                raise BrowserError("readiness control cannot identify the discovered issue")
            description_nodes = before_activity[before_activity.index(headings[0]) + 1:]
            sidebar = next((index for index, node in enumerate(description_nodes)
                            if node["role"] == "region" and node["name"] == "Sidebar"), len(description_nodes))
            description = _paragraphs(description_nodes[:sidebar])
            if headings[0]["name"] == self.policy_title:
                if self.required_status is not None or description != f"Policy reference: {self.policy}":
                    raise BrowserError("readiness control found an unexpected policy issue")
                self._load_policy(_notes(nodes))
                self.policy_url = observation.url
                return self._emit(Navigate(url=self.list_url), history)
            markers = re.findall(r"Release reference: ([A-Z0-9-]+)", description)
            if len(markers) != 1:
                raise BrowserError("readiness control requires one release description marker")
            if not self.discovery_done:
                if observation.url in self.visited:
                    raise BrowserError("readiness control encountered a repeated issue candidate")
                self.visited.add(observation.url)
                self.cursor += 1
                if markers[0] == self.release:
                    if self.target_url is not None:
                        raise BrowserError("readiness control found duplicate requested releases")
                    self.target_url = observation.url
                return self._emit(Navigate(url=self.list_url), history)
            if observation.url != self.target_url or markers[0] != self.release:
                raise BrowserError("readiness control refuses effects on another release")
            return self._target_action(nodes, history)
        navigation = [node for node in nodes if node["role"] == "link" and node["bid"]
                      and node["name"] in ("Issues", "Work items")]
        if navigation:
            return self._emit(Click(bid=navigation[0]["bid"]), history)
        plan = _one(nodes, "button", "Plan")
        return self._emit(Click(bid=plan["bid"]), history) if plan and plan["bid"] else self._wait(history)

    def _target_action(self, nodes: list[dict], history: list[dict]) -> BrowserDecision:
        notes = _notes(nodes)
        if self.note_text is None:
            self._derive_note(notes)
            self.prior_notes = tuple(notes)
        retained = tuple(note for note in notes if not note.body.startswith("release-decision-v1"))
        if retained != self.prior_notes:
            raise BrowserError("readiness control found changed public evidence or history")
        if not self.submitted and any(note.body.startswith("release-decision-v1") for note in notes):
            raise BrowserError("readiness control refuses a pre-existing decision note")
        heading = _one(nodes, "heading", "Release readiness review")
        banner = next((node for index, node in enumerate(nodes) if node["role"] == "banner"
                       and heading in _children(nodes, index)), None)
        status = [node["name"] for node in _children(nodes, nodes.index(banner))
                  if node["role"] == "StaticText" and node["name"] in ("Open", "Closed")] if banner else []
        if len(status) != 1:
            raise BrowserError("readiness control cannot confirm the target disposition")
        if self.submitted:
            posted = [note for note in notes if " ".join(note.body.split()) == " ".join(self.note_text.split())]
            decisions = [note for note in notes if note.body.startswith("release-decision-v1")]
            if not posted and not decisions:
                return self._wait(history)
            if len(posted) != 1 or len(decisions) != 1 or posted[0].internal or posted[0].author != self.actor:
                raise BrowserError("readiness control cannot confirm one ordinary actor decision")
            if self.decision == "blocked":
                if status != ["Open"]:
                    raise BrowserError("readiness control found a closed blocked release")
                return self._emit(Finish(), history)
            if self.close_requested:
                return self._emit(Finish(), history) if status == ["Closed"] else self._wait(history)
            if status != ["Open"]:
                raise BrowserError("readiness control found an unrequested release closure")
            close = _one(nodes, "button", "Close issue") or _one(nodes, "button", "Close item")
            if close is None or not close["bid"] or "disabled=True" in close["attributes"]:
                return self._wait(history)
            self.close_requested = True
            return self._emit(Click(bid=close["bid"]), history)
        if status != ["Open"] or self.actor is None:
            raise BrowserError("readiness control requires an open release and a public actor identity")
        internal = _one(nodes, "checkbox", "Make this an internal note")
        if internal is None or not re.search(r"checked=(?:'false'|False|false)(?:,|$)", internal["attributes"]):
            raise BrowserError("readiness control cannot confirm an ordinary note editor")
        plain = _one(nodes, "button", "Switch to plain text editing")
        if plain and plain["bid"]:
            if self.plain_requested:
                return self._wait(history)
            self.plain_requested = True
            return self._emit(Click(bid=plain["bid"]), history)
        if _one(nodes, "button", "Switch to rich text editing") is None:
            raise BrowserError("readiness control cannot confirm plain text editing")
        textbox = _one(nodes, "textbox", "Add a reply")
        if textbox is None or not textbox["bid"]:
            return self._wait(history)
        if "disabled=True" in textbox["attributes"]:
            raise BrowserError("readiness control found a disabled note editor")
        if textbox.get("value", "") != self.note_text:
            if textbox.get("value", ""):
                raise BrowserError("readiness control refuses to overwrite an existing draft")
            return self._emit(Fill(bid=textbox["bid"], text=self.note_text), history)
        comment = _one(nodes, "button", "Comment")
        if comment is None or not comment["bid"] or "disabled=True" in comment["attributes"]:
            return self._wait(history)
        self.submitted = True
        return self._emit(Click(bid=comment["bid"]), history)
