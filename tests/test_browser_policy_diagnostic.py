import asyncio
import base64
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from world_engine.browser_contracts import BrowserError

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SPEC = importlib.util.spec_from_file_location("collect_gitlab_triage", SCRIPTS / "collect_gitlab_triage.py")
COLLECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COLLECTOR)
sys.modules["collect_gitlab_triage"] = COLLECTOR
SPEC = importlib.util.spec_from_file_location("browser_diagnostic", SCRIPTS / "diagnose_browser_policy.py")
DIAG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DIAG)


def observation():
    return {"url": "http://application.test/projects/new#", "title": "New project",
            "accessibility_text": "[385] link 'New project'\n[414] tab 'Member 1'",
            "screenshot_artifact_id": "images/0013.png", "observation_mode": "AX",
            "image_not_sent_to_model": True}


def archive(tmp_path, monkeypatch):
    records = []

    def append(event, data):
        record = {"schema": "world-engine.browser.v1", "attempt_id": DIAG.ARCHIVED_ATTEMPT,
                  "sequence": len(records), "at": "2026-10-11T01:00:00Z", "event": event,
                  "data": data, "previous_hash": records[-1]["content_hash"] if records else "0" * 64}
        record["content_hash"] = DIAG.content_hash(record)
        records.append(record)

    append("created", {"private_snapshot": "NEVER_PROJECT_THIS_MARKER"})
    append("observation", {"step": 0, "observation": observation()})
    history = []
    for step in range(13):
        append("inference_intent", {"older": True})
        action = {"kind": "click", "bid": "385"}
        append("action_intent", {"step": step, "action": action})
        append("action_result", {"step": step, "action": action, "result": {"ok": True}})
        append("observation", {"step": step + 1, "observation": observation()})
        history.append({"action": action, "result": {"ok": True}})
    view = {key: observation()[key] for key in ("url", "title", "accessibility_text", "observation_mode", "image_not_sent_to_model")}
    view["accessibility_truncated"] = False
    body = {"model": "qwen3:8b", "options": dict(DIAG.OPTIONS), "think": False,
            "messages": [{"role": "system", "content": "original archived system"},
                         {"role": "user", "content": DIAG.canonical_json({"task": "public instruction", "observation": view,
                                                                         "history": history[-12:]})}],
            "stream": False, "tools": [], "keep_alive": "5m"}
    encoded = DIAG.canonical_json(body).encode()
    monkeypatch.setattr(DIAG, "ARCHIVED_REQUEST_SHA256", DIAG.sha(encoded))
    append("inference_intent", {"request_body": body, "request_bytes": len(encoded),
                                "request_sha256": DIAG.sha(encoded), "model_digest": DIAG.MODELS["qwen3:8b"]})
    data = {"id": DIAG.ARCHIVED_ATTEMPT, "config": {"max_steps": 30, "model": "qwen3:8b"},
            "task": {"instruction": "public instruction"}, "journal": records,
            "outcome": {"private_grade": "NEVER_PROJECT_THIS_MARKER"}}
    path = tmp_path / "archive.json"
    path.write_text(json.dumps(data))
    monkeypatch.setattr(DIAG, "ARCHIVED_INPUT_BYTES", path.stat().st_size)
    monkeypatch.setattr(DIAG, "ARCHIVED_INPUT_SHA256", DIAG.sha(path.read_bytes()))
    return path, data, encoded


def reply(model="qwen3:8b", bid="385", **counts):
    return json.dumps({"model": model, "done": True, "done_reason": "stop", "message": {"role": "assistant",
                       "tool_calls": [{"function": {"name": "browser_click", "arguments": {"bid": bid}}}]}, **counts}).encode()


def test_default_plan_is_contact_free(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["diagnostic"])
    monkeypatch.setattr(DIAG, "collect", lambda *args: pytest.fail("collection"))
    DIAG.main()
    plan = json.loads(capsys.readouterr().out)
    assert plan["max_calls"] == 4 and plan["browser_actions_executed"] == 0
    assert plan["remaining_actions"] == 17
    assert plan["models"]["qwen3:32b"] == "030ee887880fc378860c2dd35101da424377520441ae4bfe7be6deff8ade7840"


@pytest.mark.parametrize("kind", ["directory", "file", "live", "dangling"])
def test_existing_output_blocks_all_work(tmp_path, monkeypatch, kind):
    path = tmp_path / "out"
    if kind == "directory":
        path.mkdir()
    elif kind == "file":
        path.write_text("original")
    else:
        path.symlink_to(tmp_path if kind == "live" else tmp_path / "missing")
    monkeypatch.setattr(DIAG, "source_identity", lambda *args: pytest.fail("source work"))
    monkeypatch.setattr(DIAG, "public_context", lambda *args: pytest.fail("input work"))
    with pytest.raises(FileExistsError):
        asyncio.run(DIAG.collect(path, "a" * 40, "ignored"))


def test_public_projection_and_old_request_preserved(tmp_path, monkeypatch):
    path, _, encoded = archive(tmp_path, monkeypatch)
    context = DIAG.public_context(path)
    assert len(context["history"]) == 13
    assert all(row["observation"] == observation() for row in context["history"])
    assert DIAG.canonical_json(context["archived_request"]).encode() == encoded
    assert "NEVER_PROJECT" not in DIAG.canonical_json(context)


@pytest.mark.parametrize("change", ["content", "sequence", "previous_hash", "input_identity", "request_sha", "instruction"])
def test_archive_rejects_linkage_corruption(tmp_path, monkeypatch, change):
    path, data, _ = archive(tmp_path, monkeypatch)
    if change in ("content", "sequence", "previous_hash"):
        record = data["journal"][2]
        record["data"] = {"rewritten": True} if change == "content" else record["data"]
        if change != "content":
            record[change] = 99 if change == "sequence" else "f" * 64
    elif change == "input_identity":
        data["id"] = "different"
    elif change == "instruction":
        data["task"]["instruction"] = "changed"
    else:
        data["journal"][-1]["data"]["request_sha256"] = "f" * 64
        record = data["journal"][-1]
        record["content_hash"] = DIAG.content_hash({key: value for key, value in record.items() if key != "content_hash"})
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        DIAG.public_context(path)


@pytest.mark.parametrize("text", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'])
def test_strict_json(text):
    with pytest.raises(ValueError):
        DIAG.strict_json(text)


def test_old32_request_has_only_model_substitution(tmp_path, monkeypatch):
    path, _, encoded = archive(tmp_path, monkeypatch)
    monkeypatch.setattr(DIAG, "PROTOCOL", "ollama-browser-tools-v3")

    class Builder:
        def request_body(self, obs, history):
            assert len(history) == 13 and self.max_steps == 30
            return {"model": self.prepared_model, "corrected": True}

    monkeypatch.setattr(DIAG, "OllamaBrowserPolicy", Builder)
    bodies = DIAG.requests(DIAG.public_context(path))
    assert bodies["archived-8b"] == encoded
    old32 = json.loads(bodies["archived-32b"])
    old32["model"] = "qwen3:8b"
    assert DIAG.canonical_json(old32).encode() == encoded
    assert bodies["corrected-8b"] != encoded


@pytest.mark.parametrize("bid,expected", [("385", "repeated_click"), ("414", "other_valid_action"), ("hidden", "invalid_response")])
def test_classification_requires_current_unique_bid(bid, expected):
    assert DIAG.classify(reply(bid=bid), "qwen3:8b", observation())["classification"] == expected
    duplicate = observation()
    duplicate["accessibility_text"] += "\n[385] button 'Duplicate'"
    assert DIAG.classify(reply(), "qwen3:8b", duplicate)["classification"] == "invalid_response"


@pytest.mark.parametrize("raw", [b"null", b"[]", b"not json", b'{"message":null}', reply(model="remote")])
def test_invalid_replies_are_categories_not_exception_text(raw):
    assert DIAG.classify(raw, "qwen3:8b", observation())["classification"] == "invalid_response"


def test_unknown_usage_and_bounded_counts():
    assert DIAG.classify(reply(eval_count=2), "qwen3:8b", observation())["usage"] == {"eval_count": 2}
    result = DIAG.classify(reply(prompt_eval_count=True, eval_count=-1, total_duration=2**64), "qwen3:8b", observation())
    assert result["usage"] == {} and result["token_usage_complete"] is False


def fake_collection(monkeypatch, *, failure=None):
    context = {"instruction": "public task", "observation": observation(), "history": [],
               "input_sha256": "e" * 64, "input_bytes": 100, "prefix_hash": "f" * 64}
    source = {"git_revision": "a" * 40, "files": {}}
    monkeypatch.setattr(DIAG, "source_identity", lambda revision: source)
    monkeypatch.setattr(DIAG, "public_context", lambda path: context)
    bodies = {name: DIAG.canonical_json({"model": model}).encode() for name, _, model in DIAG.CELLS}
    monkeypatch.setattr(DIAG, "requests", lambda context: bodies)
    chats, closed = [], []

    class Policy:
        def __init__(self, model, instruction, *, max_steps):
            self.model, self.endpoint, self.client = model, DIAG.ENDPOINT, SimpleNamespace()
            self.digest = DIAG.MODELS[model]
            self.evidence_metadata = {"model_digest": self.digest, "template_sha256": "b" * 64,
                                      "protocol": "ollama-browser-tools-v3", "ollama_version": "0.22.0"}

        async def prepare(self):
            if failure == "prepare":
                raise ValueError("SECRET_SENTINEL")

        def set_recorder(self, recorder):
            self.recorder = recorder

        async def _model_identity(self, model):
            return self.digest

        async def _read(self, method, path, encoded):
            assert method == "POST" and path == "/api/chat"
            chats.append(encoded)
            if failure == "transport":
                self.recorder("inference_transport_failure", {"partial_body_b64": base64.b64encode(b"partial").decode(),
                              "status": 500, "body_bytes": 7, "body_sha256": DIAG.sha(b"partial"),
                              "complete_reply_certified": False})
                raise BrowserError("SECRET_SENTINEL")
            if failure == "cancel":
                raise asyncio.CancelledError
            return b"null" if failure == "null" else reply(self.model)

        async def close(self):
            closed.append(self.model)
            if failure == "close":
                raise RuntimeError("SECRET_SENTINEL")

    monkeypatch.setattr(DIAG, "OllamaBrowserPolicy", Policy)
    return chats, closed


@pytest.mark.parametrize("failure,count,status", [(None, 4, "completed"), ("null", 4, "completed"),
                                                ("transport", 1, "stopped"), ("prepare", 0, "stopped"),
                                                ("cancel", 1, "stopped"), ("close", 1, "stopped")])
def test_fixed_cells_raw_preservation_cleanup_no_retry(tmp_path, monkeypatch, failure, count, status):
    chats, closed = fake_collection(monkeypatch, failure=failure)
    output = tmp_path / "out"
    report = asyncio.run(DIAG.collect(output, "a" * 40, "private-input"))
    assert report["chat_attempts"] == len(chats) == count
    assert report["status"] == status
    assert len(closed) == max(count, 1)
    if failure in (None, "null"):
        for cell in report["cells"]:
            raw = (output / cell["name"] / "response.bin").read_bytes()
            assert cell["response_sha256"] == DIAG.sha(raw)
            assert raw == (b"null" if failure else reply(cell["model"]))
    if failure == "transport":
        assert (output / DIAG.CELLS[0][0] / "response-prefix.bin").read_bytes() == b"partial"
        assert all(cell["status"] == "unattempted" for cell in report["cells"][1:])
    assert "SECRET_SENTINEL" not in (output / "report.json").read_text()


def test_source_drift_stops_before_chat(tmp_path, monkeypatch):
    chats, closed = fake_collection(monkeypatch)
    calls = []

    def source(revision):
        calls.append(True)
        return {"version": len(calls) > 2}

    monkeypatch.setattr(DIAG, "source_identity", source)
    report = asyncio.run(DIAG.collect(tmp_path / "out", "a" * 40, "private-input"))
    assert report["status"] == "stopped" and not chats
    assert len(closed) == 1
    assert all(cell["status"] == "unattempted" for cell in report["cells"][1:])


def test_diagnostic_total_byte_cap_reserves_report(tmp_path):
    with pytest.raises(RuntimeError):
        DIAG.write(tmp_path, tmp_path / "too-big", b"x" * DIAG.LIMIT, limit=DIAG.LIMIT)
    assert not (tmp_path / "too-big").exists()


@pytest.mark.parametrize("url", ["https://application.test/projects", "http://application.test/users/password",
                                 "http://application.test/projects?private_token=sentinel", "http://other.test/projects"])
def test_navigation_must_match_driver_document_boundary(url):
    raw = json.loads(reply())
    raw["message"]["tool_calls"][0]["function"] = {"name": "browser_navigate", "arguments": {"url": url}}
    assert DIAG.classify(json.dumps(raw).encode(), "qwen3:8b", observation())["classification"] == "invalid_response"


def test_full_input_pin_rejects_even_recomputed_journal(tmp_path, monkeypatch):
    path, data, _ = archive(tmp_path, monkeypatch)
    data["journal"][0]["data"] = {"changed": True}
    previous = "0" * 64
    for record in data["journal"]:
        record["previous_hash"] = previous
        record["content_hash"] = DIAG.content_hash({key: value for key, value in record.items() if key != "content_hash"})
        previous = record["content_hash"]
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="reviewed original"):
        DIAG.public_context(path)


@pytest.mark.parametrize("compressed", [False, True])
def test_actual_provider_transport_exact_wire_and_bounded_failure(tmp_path, monkeypatch, compressed):
    real_policy = DIAG.OllamaBrowserPolicy
    fake_collection(monkeypatch)
    monkeypatch.setattr(DIAG, "OllamaBrowserPolicy", real_policy)
    monkeypatch.delenv("WORLD_ENGINE_LOCAL_URL", raising=False)
    chats = []

    def handler(request):
        assert str(request.url).startswith(DIAG.ENDPOINT + "/api/")
        assert request.headers["Accept-Encoding"] == "identity"
        if request.url.path == "/api/tags":
            body = json.dumps({"models": [{"name": model, "digest": digest, "size": 1}
                                         for model, digest in DIAG.MODELS.items()]}).encode()
        elif request.url.path == "/api/version":
            body = b'{"version":"0.22.0"}'
        elif request.url.path == "/api/show":
            body = b'{"template":"mock public template","capabilities":["tools"]}'
        else:
            assert request.url.path == "/api/chat" and request.method == "POST"
            chats.append(request.content)
            body = b"compressed-prefix" if compressed else reply(json.loads(request.content)["model"])
            return httpx.Response(200, stream=httpx.ByteStream(body), headers={"Content-Encoding": "gzip"} if compressed else {})
        return httpx.Response(200, stream=httpx.ByteStream(body))

    client_type = httpx.AsyncClient
    monkeypatch.setattr(DIAG.httpx, "AsyncClient", lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs))
    output = tmp_path / "out"
    report = asyncio.run(DIAG.collect(output, "a" * 40, "private-input"))
    assert report["chat_attempts"] == len(chats) == (1 if compressed else 4)
    assert report["status"] == ("stopped" if compressed else "completed")
    for index, encoded in enumerate(chats):
        cell = report["cells"][index]
        assert (output / cell["name"] / "request.json").read_bytes() == encoded
        assert cell["request_sha256"] == DIAG.sha(encoded)
    if compressed:
        cell = report["cells"][0]
        assert (output / cell["name"] / "response-prefix.bin").read_bytes() == b"compressed-prefix"
        assert cell["transport_failure"]["complete_reply_certified"] is False


def test_reply_identity_drift_retains_raw_and_stops(tmp_path, monkeypatch):
    chats, _ = fake_collection(monkeypatch)
    calls = []

    async def identity(self, model):
        calls.append(True)
        return self.digest if len(calls) == 1 else "changed"

    monkeypatch.setattr(DIAG.OllamaBrowserPolicy, "_model_identity", identity)
    output = tmp_path / "out"
    report = asyncio.run(DIAG.collect(output, "a" * 40, "private-input"))
    assert len(chats) == 1 and report["status"] == "stopped"
    assert (output / "archived-8b/response.bin").read_bytes() == reply()
    assert "classification" not in report["cells"][0]
    assert all(cell["status"] == "unattempted" for cell in report["cells"][1:])
