from __future__ import annotations

import copy
import hashlib
import http.client
import importlib.util
import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location("lesson_server", Path(__file__).parents[1] / "learning/server.py")
server_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server_module)


@pytest.fixture
def lesson_files(tmp_path):
    media = tmp_path / "video.webm"
    media.write_bytes(b"0123456789")
    picture = tmp_path / "picture.png"
    picture.write_bytes(b"image-fixture")
    static = tmp_path / "static"
    static.mkdir()
    for name in ("index.html", "styles.css", "app.js"):
        (static / name).write_text("fixture " + name)
    value = {"id": "gitlab-01", "title": "A recorded browser attempt", "version": 1,
             "attemptId": "synthetic-test-only", "sourceRevision": "a" * 40, "model": "local-fixture",
             "task": "Inspect this retained record", "sections": [
                 {"id": "start", "title": "Inspect", "kicker": "", "summary": "Read first", "paragraphs": ["Public lesson"],
                  "facts": [{"label": "Outcome", "value": "Incomplete"}], "questionId": "q-choice",
                  "evidence": {"kind": "video", "mediaId": "clip", "caption": "Recorded evidence"}},
                 {"id": "finish", "title": "Explain", "kicker": "", "summary": "", "paragraphs": [],
                  "facts": [], "questionId": "q-written", "evidence": {"kind": "text", "caption": "Excerpt", "excerpt": "Visible text"}}],
             "questions": [{"id": "q-choice", "kind": "choice", "prompt": "What happened?",
                            "choices": [{"id": "a", "label": "Incomplete"}, {"id": "b", "label": "Passed"}],
                            "correctChoice": "a", "explanations": {"a": "The task is incomplete"}},
                           {"id": "q-written", "kind": "written", "prompt": "Explain", "reviewFocus": "Evidence"}],
             "media": {"clip": str(media), "shot": str(picture)}}
    lesson = tmp_path / "lesson.json"
    lesson.write_text(json.dumps(value))
    return lesson, tmp_path / "progress.sqlite3", static, value


@contextmanager
def running(files):
    lesson, state, static, _ = files
    server = server_module.LearningServer(("127.0.0.1", 0), lesson, state, static)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def request(server, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def progress():
    return {"step": 1, "answers": {"q-choice": "a", "q-written": "The goal was not completed."}, "checked": {"q-choice": True}}


def put(server, value, headers=None):
    return request(server, "PUT", "/api/progress", json.dumps(value), {"Content-Type": "application/json", **(headers or {})})


def test_lesson_public_state_persists_after_restart_and_export(lesson_files):
    original = lesson_files[0].read_bytes()
    media_before = Path(lesson_files[3]["media"]["clip"]).read_bytes()
    with running(lesson_files) as server:
        status, headers, raw = request(server, "GET", "/api/lesson")
        assert status == 200 and "media" not in json.loads(raw)
        public_input = {key: value for key, value in lesson_files[3].items() if key != "media"}
        expected_hash = hashlib.sha256(server_module.canonical(public_input)).hexdigest()
        assert json.loads(raw) == {**public_input, "contentHash": expected_hash}
        assert server.lesson.identity == expected_hash and "contentHash" not in server.lesson.public
        assert str(lesson_files[0].parent).encode() not in raw
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert "default-src 'self'" in headers["Content-Security-Policy"]
        initial = json.loads(request(server, "GET", "/api/progress")[2])
        assert initial == {"version": 1, "lessonId": "gitlab-01", "step": 0, "answers": {}, "checked": {}, "updatedAt": None}
        status, _, raw = put(server, progress())
        saved = json.loads(raw)
        assert status == 200 and saved["answers"] == progress()["answers"] and saved["updatedAt"]
    with running(lesson_files) as restarted:
        assert json.loads(request(restarted, "GET", "/api/progress")[2]) == saved
        status, headers, raw = request(restarted, "GET", "/api/export")
        assert status == 200 and json.loads(raw) == saved
        assert "attachment" in headers["Content-Disposition"]
        changed = {"step": 0, "answers": {"q-choice": "b"}, "checked": {"q-choice": False}}
        assert put(restarted, changed)[0] == 200
    with sqlite3.connect(lesson_files[1]) as db:
        rows = db.execute("SELECT payload FROM revisions ORDER BY id").fetchall()
    assert len(rows) == 2 and json.loads(rows[0][0]) == saved
    assert lesson_files[0].read_bytes() == original
    assert Path(lesson_files[3]["media"]["clip"]).read_bytes() == media_before


@pytest.mark.parametrize("field,value", [
    ("step", True), ("step", -1), ("step", 2), ("step", 0.0), ("step", "0"),
    ("answers", []), ("answers", {"unknown": "a"}), ("answers", {"q-choice": "wrong"}),
    ("answers", {"q-written": 1}), ("answers", {"q-written": "x" * 8001}),
    ("checked", []), ("checked", {"q-choice": 1}), ("checked", {"q-written": True}),
    ("checked", {"unknown": False})])
def test_rejected_snapshot_never_changes_saved_state(lesson_files, field, value):
    with running(lesson_files) as server:
        assert put(server, progress())[0] == 200
        before = request(server, "GET", "/api/progress")[2]
        rejected = progress()
        rejected[field] = value
        assert put(server, rejected)[0] == 400
        assert request(server, "GET", "/api/progress")[2] == before
    with sqlite3.connect(lesson_files[1]) as db:
        assert db.execute("SELECT count(*) FROM revisions").fetchone()[0] == 1


@pytest.mark.parametrize("headers,status", [
    ({"Origin": "https://attacker.example"}, 403), ({"Sec-Fetch-Site": "cross-site"}, 403),
    ({"Host": "attacker.example:5181"}, 403), ({"Host": "[broken"}, 403),
    ({"Host": "user@127.0.0.1:5181"}, 403), ({"Host": "127.0.0.1:0"}, 403),
    ({"Content-Type": "text/plain"}, 415), ({"Content-Type": "application/x-www-form-urlencoded"}, 415),
    ({"Transfer-Encoding": "chunked"}, 411), ({"Content-Length": "-1"}, 411),
    ({"Content-Length": "65537"}, 413)])
def test_http_write_boundaries_do_not_mutate(lesson_files, headers, status):
    with running(lesson_files) as server:
        assert put(server, progress(), headers)[0] == status
        assert server.store.get()["updatedAt"] is None


def test_same_origin_and_full_unicode_written_limit(lesson_files):
    with running(lesson_files) as server:
        value = progress()
        value["answers"]["q-written"] = "\u00e9" * 8000
        assert put(server, value, {"Origin": f"http://127.0.0.1:{server.server_port}"})[0] == 200
        assert server.store.get()["answers"]["q-written"] == value["answers"]["q-written"]


@pytest.mark.parametrize("raw", [b'{}', b'null', b'[]', b'{"step":0,"step":1,"answers":{},"checked":{}}',
                                 b'{"step":NaN,"answers":{},"checked":{}}', b'"' + b'[' * 10000 + b'"',
                                 b'{"step":0,"answers":{},"checked":{},"version":1}'])
def test_malformed_json_or_extra_fields_rejected(lesson_files, raw):
    with running(lesson_files) as server:
        assert request(server, "PUT", "/api/progress", raw, {"Content-Type": "application/json"})[0] == 400
        assert server.store.get()["updatedAt"] is None


@pytest.mark.parametrize("path", ["/../lesson.json", "/media/../lesson.json", "/media/%2e%2e%2flesson.json", "/media/unknown", "/server.py", "/api/reset"])
def test_paths_and_unregistered_files_not_served(lesson_files, path):
    with running(lesson_files) as server:
        assert request(server, "GET", path)[0] in (403, 404)
        assert request(server, "POST", "/api/reset")[0] == 405


@pytest.mark.parametrize("header,status,expected,content_range", [
    (None, 200, b"0123456789", None), ("bytes=2-5", 206, b"2345", "bytes 2-5/10"),
    ("bytes=7-", 206, b"789", "bytes 7-9/10"), ("bytes=-3", 206, b"789", "bytes 7-9/10"),
    ("bytes=8-100", 206, b"89", "bytes 8-9/10"), ("bytes=10-", 416, b"", "bytes */10"),
    ("bytes=7-2", 416, b"", "bytes */10"), ("bytes=-0", 416, b"", "bytes */10"),
    ("bytes=1-2,4-5", 416, b"", "bytes */10"), ("items=1-2", 416, b"", "bytes */10")])
def test_video_byte_ranges(lesson_files, header, status, expected, content_range):
    with running(lesson_files) as server:
        received, headers, raw = request(server, "GET", "/media/clip", headers={"Range": header} if header else {})
        assert (received, raw) == (status, expected)
        assert headers.get("Content-Range") == content_range
        assert int(headers["Content-Length"]) == len(raw)


def test_static_allowlist_and_media_head(lesson_files):
    with running(lesson_files) as server:
        for route in ("/", "/index.html", "/app.js", "/styles.css"):
            assert request(server, "GET", route)[0] == 200
        status, headers, raw = request(server, "HEAD", "/media/clip")
        assert status == 200 and headers["Content-Length"] == "10" and raw == b""


def test_state_collision_or_unrelated_file_never_overwritten(lesson_files, tmp_path):
    lesson, _, static, _ = lesson_files
    arbitrary = tmp_path / "not-state.sqlite3"
    arbitrary.write_bytes(b"original evidence")
    for state in (lesson, Path(lesson_files[3]["media"]["clip"]), static / "app.js", arbitrary):
        before = state.read_bytes()
        with pytest.raises((ValueError, sqlite3.Error)):
            server_module.LearningServer(("127.0.0.1", 0), lesson, state, static)
        assert state.read_bytes() == before


def test_symlink_parent_media_and_existing_state_refused(lesson_files, tmp_path):
    lesson, state, static, value = lesson_files
    directory_link = tmp_path / "linked"
    directory_link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        server_module.LearningServer(("127.0.0.1", 0), lesson, directory_link / "new.sqlite3", static)
    assert not (tmp_path / "new.sqlite3").exists()
    state.symlink_to(lesson)
    with pytest.raises(ValueError):
        server_module.LearningServer(("127.0.0.1", 0), lesson, state, static)
    linked_media = tmp_path / "linked.png"
    linked_media.symlink_to(value["media"]["shot"])
    value["media"]["shot"] = str(linked_media)
    lesson.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        server_module.Lesson(lesson)


def test_changed_lesson_revision_refuses_reuse_without_changing_state(lesson_files):
    with running(lesson_files) as server:
        put(server, progress())
    state_before = hashlib.sha256(lesson_files[1].read_bytes()).hexdigest()
    value = copy.deepcopy(lesson_files[3])
    value["title"] = "Different revision"
    lesson_files[0].write_text(json.dumps(value))
    with pytest.raises(ValueError):
        server_module.LearningServer(("127.0.0.1", 0), *lesson_files[:3])
    assert hashlib.sha256(lesson_files[1].read_bytes()).hexdigest() == state_before


@pytest.mark.parametrize("mutation", [
    lambda v: v.update(version=True), lambda v: v.update(private="not public"),
    lambda v: v["questions"][0].update(correctChoice="missing"),
    lambda v: v["questions"].append(copy.deepcopy(v["questions"][0])),
    lambda v: v["sections"][0].update(questionId="missing"),
    lambda v: v["media"].update(clip="relative.webm"),
    lambda v: v["sections"][0]["evidence"].update(mediaId="missing"),
    lambda v: v["sections"][0]["facts"][0].update(value=123)])
def test_lesson_validation_before_state_creation(lesson_files, mutation):
    mutation(lesson_files[3])
    lesson_files[0].write_text(json.dumps(lesson_files[3]))
    with pytest.raises((ValueError, TypeError)):
        server_module.LearningServer(("127.0.0.1", 0), *lesson_files[:3])
    assert not lesson_files[1].exists()


def test_sqlite_revision_and_current_save_are_one_transaction(lesson_files):
    with running(lesson_files) as server:
        put(server, progress())
        with sqlite3.connect(lesson_files[1]) as db:
            db.execute("CREATE TRIGGER reject_update BEFORE UPDATE ON progress BEGIN SELECT RAISE(ABORT,'test'); END")
        before = server.store.get()
        assert put(server, {"step": 0, "answers": {}, "checked": {}})[0] == 503
        assert server.store.get() == before
    with sqlite3.connect(lesson_files[1]) as db:
        assert db.execute("SELECT count(*) FROM revisions").fetchone()[0] == 1


def test_cli_invalid_paths_fail_without_state_or_listener(tmp_path, capsys):
    with pytest.raises(SystemExit) as error:
        server_module.main(["--lesson", "relative.json", "--state", str(tmp_path / "new.sqlite3")])
    assert error.value.code == 2
    assert not (tmp_path / "new.sqlite3").exists()
    assert "configuration rejected" in capsys.readouterr().err


@pytest.mark.parametrize("name,values,status", [
    ("Host", ["127.0.0.1", "127.0.0.1"], 403),
    ("Origin", ["same", "same"], 403),
    ("Content-Length", ["2", "2"], 411),
    ("Content-Type", ["application/json", "application/json"], 415)])
def test_duplicate_authority_and_write_headers_rejected(lesson_files, name, values, status):
    with running(lesson_files) as server:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        connection.putrequest("PUT", "/api/progress", skip_host=True)
        headers = {"Host": f"127.0.0.1:{server.server_port}", "Content-Length": "2", "Content-Type": "application/json"}
        for key, value in headers.items():
            if key != name:
                connection.putheader(key, value)
        for value in values:
            value = f"http://127.0.0.1:{server.server_port}" if value == "same" else value
            connection.putheader(name, value)
        connection.endheaders(b"{}")
        response = connection.getresponse()
        assert response.status == status
        response.read()
        connection.close()
        assert server.store.get()["updatedAt"] is None


def test_deep_json_and_actual_oversize_body_do_not_mutate(lesson_files):
    with running(lesson_files) as server:
        nested = b"[" * 1500 + b"0" + b"]" * 1500
        assert request(server, "PUT", "/api/progress", nested, {"Content-Type": "application/json"})[0] == 400
        assert request(server, "PUT", "/api/progress", b"x" * 65537, {"Content-Type": "application/json"})[0] == 413
        assert server.store.get()["updatedAt"] is None


@pytest.mark.parametrize("authority", ["localhost", "[::1]"])
def test_exact_loopback_alias_and_same_origin(lesson_files, authority):
    with running(lesson_files) as server:
        host = f"{authority}:{server.server_port}"
        assert put(server, progress(), {"Host": host, "Origin": "http://" + host})[0] == 200
        assert put(server, progress(), {"Host": host, "Origin": f"http://127.0.0.1:{server.server_port}"})[0] == 403


def test_revision_cap_keeps_latest_and_history(lesson_files):
    with running(lesson_files) as server:
        put(server, progress())
        before = server.store.get()
        with sqlite3.connect(lesson_files[1]) as db:
            db.executemany("INSERT INTO revisions(payload) VALUES (?)", [("{}",)] * 9999)
        assert put(server, {"step": 0, "answers": {}, "checked": {}})[0] == 503
        assert server.store.get() == before
    with sqlite3.connect(lesson_files[1]) as db:
        assert db.execute("SELECT count(*) FROM revisions").fetchone()[0] == 10000


def test_deleted_or_changed_media_never_serves_symlink_target(lesson_files, tmp_path):
    with running(lesson_files) as server:
        target = Path(lesson_files[3]["media"]["clip"])
        target.unlink()
        target.symlink_to(lesson_files[0])
        status, _, raw = request(server, "GET", "/media/clip")
        assert status == 500 and b"gitlab-01" not in raw


def test_existing_foreign_sqlite_untouched(lesson_files, tmp_path):
    foreign = tmp_path / "foreign.sqlite3"
    with sqlite3.connect(foreign) as db:
        db.execute("CREATE TABLE unrelated(value TEXT)")
    before = foreign.read_bytes()
    with pytest.raises(ValueError):
        server_module.LearningServer(("127.0.0.1", 0), lesson_files[0], foreign, lesson_files[2])
    assert foreign.read_bytes() == before


def test_public_content_revision_changes_hash_without_changing_id_or_version(lesson_files):
    with running(lesson_files) as server:
        before = json.loads(request(server, "GET", "/api/lesson")[2])
    revised = copy.deepcopy(lesson_files[3])
    revised["sections"][0]["summary"] = "A revised public explanation"
    lesson_files[0].write_text(json.dumps(revised))
    revised_files = (lesson_files[0], lesson_files[1].with_name("revised.sqlite3"), *lesson_files[2:])
    with running(revised_files) as server:
        after = json.loads(request(server, "GET", "/api/lesson")[2])
    assert before["id"] == after["id"] and before["version"] == after["version"]
    assert before["contentHash"] != after["contentHash"]
    expected = {key: value for key, value in revised.items() if key != "media"}
    assert after["contentHash"] == hashlib.sha256(server_module.canonical(expected)).hexdigest()


def test_input_cannot_supply_its_own_computed_content_hash(lesson_files):
    lesson_files[3]["contentHash"] = "0" * 64
    lesson_files[0].write_text(json.dumps(lesson_files[3]))
    with pytest.raises(ValueError):
        server_module.LearningServer(("127.0.0.1", 0), *lesson_files[:3])
    assert not lesson_files[1].exists()


@pytest.mark.parametrize("error", [BrokenPipeError(), ConnectionResetError(), OSError("fixture disk read failed")])
def test_media_disconnect_does_not_attempt_second_response(error):
    handler = object.__new__(server_module.LearningHandler)
    handler.server = SimpleNamespace(lesson=SimpleNamespace(media={"clip": Path("/synthetic/video.webm")}))
    handler.close_connection = False
    handler.boundary = lambda: "/media/clip"
    responses = []
    handler.error = lambda status, message: responses.append((status, message))

    def failed_media(_):
        raise error

    handler.media = failed_media
    handler.do_GET()
    if isinstance(error, (BrokenPipeError, ConnectionResetError)):
        assert handler.close_connection and responses == []
    else:
        assert responses == [(500, "local read failed")]


@pytest.mark.parametrize("error", [BrokenPipeError(), ConnectionResetError()])
def test_common_handler_disconnect_guard(error, monkeypatch):
    handler = object.__new__(server_module.LearningHandler)
    handler.close_connection = False

    def disconnected(_):
        raise error

    monkeypatch.setattr(server_module.BaseHTTPRequestHandler, "handle", disconnected)
    handler.handle()
    assert handler.close_connection is True


def test_common_handler_keeps_other_errors_visible(monkeypatch):
    handler = object.__new__(server_module.LearningHandler)

    def unrelated_error(_):
        raise OSError("synthetic unrelated failure")

    monkeypatch.setattr(server_module.BaseHTTPRequestHandler, "handle", unrelated_error)
    with pytest.raises(OSError, match="synthetic unrelated failure"):
        handler.handle()
