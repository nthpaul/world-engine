"""Single-user loopback lesson server. No runtime/model integration."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import stat
from contextlib import closing
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit

BODY_LIMIT = 65_536
LESSON_LIMIT = 2_097_152
STATE_APP_ID = 0x57454C31
STATIC_FILES = {"/": "index.html", "/index.html": "index.html", "/styles.css": "styles.css", "/app.js": "app.js"}
MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".mp4": "video/mp4", ".webm": "video/webm"}
ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
CSP = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; media-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"


def require(condition, message="invalid lesson or progress"):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def json_document(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    return json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: require(False))


def path_boundary(value, *, exists=True):
    path = Path(value)
    require(path.is_absolute(), "paths must be absolute")
    require(".." not in path.parts, "path traversal is forbidden")
    for part in (path, *path.parents):
        require(not part.is_symlink(), "symlink paths are forbidden")
    require(path.parent.is_dir(), "parent directory must exist")
    if exists:
        require(path.is_file() and stat.S_ISREG(path.stat().st_mode), "a regular file is required")
    return path


def fields(value, required, optional=()):
    require(type(value) is dict and set(required) <= set(value) <= set(required) | set(optional))


def text(value, *, empty=False, limit=65_536):
    require(type(value) is str and len(value) <= limit and (empty or bool(value.strip())))


def identifier(value):
    require(type(value) is str and ID.fullmatch(value) is not None)


class Lesson:
    def __init__(self, path):
        self.path = path_boundary(path)
        require(self.path.stat().st_size <= LESSON_LIMIT, "lesson exceeds 2 MiB")
        with self.path.open("rb") as source:
            raw = source.read(LESSON_LIMIT + 1)
        require(len(raw) <= LESSON_LIMIT, "lesson exceeds 2 MiB")
        document = json_document(raw)
        fields(document, ("id", "title", "version", "attemptId", "sourceRevision", "model", "task", "sections", "questions", "media"))
        identifier(document["id"])
        require(type(document["version"]) is int and document["version"] == 1)
        for key in ("title", "attemptId", "sourceRevision", "model", "task"):
            text(document[key])
        require(type(document["sections"]) is list and 1 <= len(document["sections"]) <= 100)
        require(type(document["questions"]) is list and len(document["questions"]) <= 100)
        self.questions = {}
        for question in document["questions"]:
            fields(question, ("id", "kind", "prompt"), ("choices", "correctChoice", "explanations", "reviewFocus"))
            identifier(question["id"])
            require(question["id"] not in self.questions)
            require(question["kind"] in ("choice", "written"))
            text(question["prompt"])
            if "reviewFocus" in question:
                text(question["reviewFocus"])
            if question["kind"] == "choice":
                choices = question.get("choices")
                require(type(choices) is list and 2 <= len(choices) <= 20)
                ids = set()
                for choice in choices:
                    fields(choice, ("id", "label"))
                    identifier(choice["id"])
                    text(choice["label"])
                    require(choice["id"] not in ids)
                    ids.add(choice["id"])
                require(question.get("correctChoice") in ids)
                if "explanations" in question:
                    require(type(question["explanations"]) is dict and set(question["explanations"]) <= ids)
                    for explanation in question["explanations"].values():
                        text(explanation)
            else:
                require(not {"choices", "correctChoice", "explanations"} & set(question))
            self.questions[question["id"]] = question
        require(type(document["media"]) is dict and len(document["media"]) <= 100)
        self.media = {}
        for media_id, name in document["media"].items():
            identifier(media_id)
            require(type(name) is str)
            path = path_boundary(name)
            require(path.suffix.lower() in MEDIA_TYPES and path.stat().st_size <= 536_870_912, "unsupported or oversized media")
            self.media[media_id] = path
        sections = set()
        for section in document["sections"]:
            fields(section, ("id", "title", "kicker", "summary", "paragraphs", "facts"), ("evidence", "questionId"))
            identifier(section["id"])
            require(section["id"] not in sections)
            sections.add(section["id"])
            for key in ("title", "kicker", "summary"):
                text(section[key], empty=key != "title")
            require(type(section["paragraphs"]) is list and len(section["paragraphs"]) <= 100)
            for paragraph in section["paragraphs"]:
                text(paragraph)
            require(type(section["facts"]) is list and len(section["facts"]) <= 100)
            for fact in section["facts"]:
                fields(fact, ("label", "value"))
                text(fact["label"])
                text(fact["value"])
            if "questionId" in section:
                require(section["questionId"] in self.questions)
            if "evidence" in section:
                evidence = section["evidence"]
                fields(evidence, ("kind", "caption"), ("mediaId", "excerpt"))
                require(evidence["kind"] in ("image", "video", "text"))
                text(evidence["caption"], empty=True)
                if evidence["kind"] == "text":
                    require("mediaId" not in evidence and "excerpt" in evidence)
                    text(evidence["excerpt"], empty=True)
                else:
                    require(evidence.get("mediaId") in self.media and "excerpt" not in evidence)
                    suffix = self.media[evidence["mediaId"]].suffix.lower()
                    require(suffix in ({".png", ".jpg", ".jpeg"} if evidence["kind"] == "image" else {".mp4", ".webm"}))
        self.public = {key: value for key, value in document.items() if key != "media"}
        self.identity = hashlib.sha256(canonical(self.public)).hexdigest()

    def progress(self, value):
        fields(value, ("step", "answers", "checked"))
        require(type(value["step"]) is int and 0 <= value["step"] < len(self.public["sections"]))
        require(type(value["answers"]) is dict and type(value["checked"]) is dict)
        for key, answer in value["answers"].items():
            require(key in self.questions)
            text(answer, empty=True, limit=8000)
            if self.questions[key]["kind"] == "choice":
                require(answer in {c["id"] for c in self.questions[key]["choices"]})
        for key, checked in value["checked"].items():
            require(key in self.questions and self.questions[key]["kind"] == "choice" and type(checked) is bool)
        require(len(canonical(value)) <= BODY_LIMIT, "progress exceeds 64 KiB")
        return value


class ProgressStore:
    def __init__(self, path, lesson, static_root):
        self.path = path_boundary(path, exists=False)
        protected = {lesson.path, *lesson.media.values(),
                     *(static_root / name for name in set(STATIC_FILES.values()) if (static_root / name).is_file())}
        require(self.path not in protected and static_root not in self.path.parents
                and not (self.path.exists() and any(self.path.samefile(path) for path in protected)),
                "state must be separate from lesson, media and static files")
        self.lesson = lesson
        if self.path.exists():
            require(self.path.is_file(), "state must be a regular file")
            # Inspect read-only first: never initialize an unrelated existing SQLite file.
            with closing(sqlite3.connect(self.path.as_uri()+"?mode=ro", uri=True)) as db:
                require(db.execute("PRAGMA application_id").fetchone()[0] == STATE_APP_ID, "not a learning state database")
                require(db.execute("SELECT identity FROM lesson").fetchall() == [(lesson.identity,)], "state belongs to a different lesson revision")
        else:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            os.close(descriptor)
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute(f"PRAGMA application_id={STATE_APP_ID}")
                db.execute("PRAGMA user_version=1")
                db.execute("CREATE TABLE lesson(identity TEXT NOT NULL)")
                db.execute("INSERT INTO lesson VALUES (?)", (lesson.identity,))
                db.execute("CREATE TABLE revisions(id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
                db.execute("CREATE TABLE progress(id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)")

    def get(self):
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute("SELECT payload FROM progress WHERE id=1").fetchone()
        if row is None:
            return {"version": 1, "lessonId": self.lesson.public["id"], "step": 0, "answers": {}, "checked": {}, "updatedAt": None}
        saved = json_document(row[0])
        fields(saved, ("version", "lessonId", "step", "answers", "checked", "updatedAt"))
        require(type(saved["version"]) is int and saved["version"] == 1 and saved["lessonId"] == self.lesson.public["id"])
        self.lesson.progress({key: saved[key] for key in ("step", "answers", "checked")})
        text(saved["updatedAt"], limit=64)
        return saved

    def save(self, value):
        value = self.lesson.progress(value)
        saved = {"version": 1, "lessonId": self.lesson.public["id"], **value,
                 "updatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
        payload = canonical(saved).decode("utf-8")
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("PRAGMA max_page_count=8192")
            if db.execute("SELECT count(*) FROM revisions").fetchone()[0] >= 10_000:
                raise sqlite3.IntegrityError("revision limit reached")
            db.execute("INSERT INTO revisions(payload) VALUES (?)", (payload,))
            db.execute("INSERT INTO progress VALUES (1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (payload,))
        return saved


def byte_range(value, size):
    if value is None:
        return 0, size - 1
    match = re.fullmatch(r"bytes=([0-9]*)-([0-9]*)", value)
    require(match is not None and any(match.groups()) and size > 0, "invalid range")
    first, last = match.groups()
    if not first:
        amount = int(last)
        require(amount > 0, "invalid range")
        return max(0, size - amount), size - 1
    start, end = int(first), int(last) if last else size - 1
    require(start < size and start <= end, "invalid range")
    return start, min(end, size - 1)


class LearningServer(HTTPServer):
    def __init__(self, address, lesson, state, static_root=None):
        require(address[0] == "127.0.0.1" and type(address[1]) is int and 0 <= address[1] <= 65535, "loopback binding required")
        self.static_root = Path(static_root) if static_root else Path(__file__).parent / "static"
        self.lesson = Lesson(lesson)
        self.store = ProgressStore(state, self.lesson, self.static_root.absolute())
        super().__init__(address, LearningHandler)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(5)
        return connection, address


class LearningHandler(BaseHTTPRequestHandler):
    server_version = "LocalLesson/1"

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def log_message(self, *_):
        pass

    def send_bytes(self, status, raw, content_type="application/json; charset=utf-8", headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("Referrer-Policy", "no-referrer")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)

    def error(self, status, message):
        self.close_connection = True
        self.send_bytes(status, canonical({"error": message}))

    def boundary(self):
        try:
            hosts = self.headers.get_all("Host", [])
            require(len(hosts) == 1)
            host = hosts[0]
            require(host.isascii() and not any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in host))
            parsed = urlsplit("http://" + host)
            require(parsed.hostname in {"127.0.0.1", "localhost", "::1"} and parsed.port == self.server.server_port)
            require(not parsed.username and not parsed.password and not parsed.path and not parsed.query and not parsed.fragment)
            authority = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
            require(host == f"{authority}:{self.server.server_port}")
            origins = self.headers.get_all("Origin", [])
            require(not origins or origins == ["http://" + host])
            require(self.headers.get("Sec-Fetch-Site") != "cross-site")
            route = urlsplit(self.path)
            require(not route.scheme and not route.netloc and not route.query and not route.fragment and "%" not in route.path)
            return route.path
        except (ValueError, TypeError):
            self.error(403, "local request boundary rejected")
            return None

    def do_GET(self):
        path = self.boundary()
        if path is None:
            return
        try:
            if path == "/api/lesson":
                self.send_bytes(200, canonical({**self.server.lesson.public, "contentHash": self.server.lesson.identity}))
            elif path in {"/api/progress", "/api/export"}:
                headers = {"Content-Disposition": 'attachment; filename="lesson-progress.json"'} if path == "/api/export" else None
                self.send_bytes(200, canonical(self.server.store.get()), headers=headers)
            elif path in STATIC_FILES:
                target = path_boundary(self.server.static_root.absolute() / STATIC_FILES[path])
                content_type = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}[target.suffix]
                require(target.stat().st_size <= LESSON_LIMIT, "static file exceeds limit")
                with target.open("rb") as source:
                    raw = source.read(LESSON_LIMIT + 1)
                require(len(raw) <= LESSON_LIMIT, "static file exceeds limit")
                self.send_bytes(200, raw, content_type + "; charset=utf-8")
            elif path.startswith("/media/") and path[7:] in self.server.lesson.media:
                self.media(self.server.lesson.media[path[7:]])
            else:
                self.error(404, "not found")
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except (OSError, ValueError, sqlite3.Error, RecursionError):
            self.error(500, "local read failed")

    def media(self, path):
        path_boundary(path)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as source:
            metadata = os.fstat(source.fileno())
            require(stat.S_ISREG(metadata.st_mode) and metadata.st_size <= 536_870_912, "invalid media file")
            size = metadata.st_size
            ranges = self.headers.get_all("Range", [])
            try:
                require(len(ranges) <= 1)
                start, end = byte_range(ranges[0] if ranges else None, size)
            except (ValueError, OverflowError):
                self.send_bytes(416, b"", headers={"Content-Range": f"bytes */{size}"})
                return
            self.send_response(206 if ranges else 200)
            self.send_header("Content-Type", MEDIA_TYPES[path.suffix.lower()])
            self.send_header("Content-Length", str(max(0, end - start + 1)))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("Cache-Control", "no-store")
            if ranges:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if self.command == "HEAD":
                return
            source.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                block = source.read(min(65_536, remaining))
                if not block:
                    break
                self.wfile.write(block)
                remaining -= len(block)

    def do_HEAD(self):
        self.do_GET()

    def do_PUT(self):
        path = self.boundary()
        if path is None:
            return
        if path != "/api/progress":
            self.error(404, "not found")
            return
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") is not None or len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,8}", lengths[0]):
            self.error(411, "bounded content length required")
            return
        length = int(lengths[0])
        if length > BODY_LIMIT:
            self.error(413, "progress exceeds 64 KiB")
            return
        if self.headers.get_all("Content-Type", []) not in (["application/json"], ["application/json; charset=utf-8"]):
            self.error(415, "application/json required")
            return
        try:
            raw = self.rfile.read(length)
            require(len(raw) == length)
            value = json_document(raw)
            self.server.lesson.progress(value)
        except (ValueError, TypeError, RecursionError, OSError):
            self.error(400, "invalid progress")
            return
        try:
            saved = self.server.store.save(value)
        except sqlite3.Error:
            self.error(503, "progress could not be saved")
            return
        self.send_bytes(200, canonical(saved))

    def do_POST(self):
        self.error(405, "method not allowed")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Serve one private lesson and persistent learner progress on loopback")
    parser.add_argument("--lesson", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--port", type=int, default=5181)
    args = parser.parse_args(argv)
    try:
        require(1 <= args.port <= 65535, "port must be 1..65535")
        server = LearningServer(("127.0.0.1", args.port), args.lesson, args.state)
    except (ValueError, TypeError, OSError, sqlite3.Error, RecursionError):
        parser.exit(2, "Lesson server configuration rejected; verify lesson, media and separate state paths.\n")
    print(f"Lesson ready at http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
