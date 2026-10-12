import importlib.util
import json
from pathlib import Path

import httpx
import pytest

PATH = Path(__file__).resolve().parents[1] / "scripts/collect_gitlab_triage.py"
SPEC = importlib.util.spec_from_file_location("triage_collector", PATH)
COLLECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COLLECTOR)


def valid_result(passed=True):
    return {"status": "completed", "termination": "finished", "invalid_actions": 0,
            "reconciliation_required": False, "cleanup": {"status": "completed"},
            "passed": passed, "reward": float(passed), "outcome": {"checks": [{"passed": passed}]}}


def test_default_plan_no_contacts(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", [str(PATH)])
    monkeypatch.setattr(COLLECTOR, "collect", lambda *args: pytest.fail("default plan collected"))
    COLLECTOR.main()
    plan = json.loads(capsys.readouterr().out)
    assert plan["schema"] == "world-engine.triage-qualification.v9"
    assert plan["policy_protocol"] == "ollama-browser-tools-v3"
    assert plan["reference_protocol"] == "public-ax-triage-control-v7"
    assert [slot["seed"] for slot in plan["slots"]] == [42, 42, 43, 42, 42]
    assert plan["training_eligible"] is False and plan["automatic_retries"] == 0
    assert plan["model"] == "qwen3:8b"
    assert plan["model_transport_timeouts_seconds"] == {"connect": 10, "write": 10, "pool": 10, "read": 180}


@pytest.mark.parametrize("kind", ["file", "directory", "live", "dangling"])
def test_fresh_output_refuses_existing_before_source_or_network(tmp_path, monkeypatch, kind):
    output = tmp_path / "output"
    if kind == "file":
        output.write_text("original")
    elif kind == "directory":
        output.mkdir()
    else:
        output.symlink_to(tmp_path if kind == "live" else tmp_path / "missing")
    monkeypatch.setattr(COLLECTOR, "source_identity", lambda *args: pytest.fail("source work"))
    with pytest.raises(FileExistsError):
        COLLECTOR.collect(output, "a" * 40, "a" * 40)


def test_parent_symlink_refused(tmp_path):
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        COLLECTOR.reserve_output(link / "new")


def test_control_gate_requires_real_prefix_and_complete_outcomes():
    results = [valid_result(False)] + [valid_result() for _ in range(3)]
    assert COLLECTOR.controls_qualified(results)
    assert COLLECTOR.controls_qualified(results[:1], complete=False)
    assert not COLLECTOR.controls_qualified(results[:1])
    for field, value in (("passed", False), ("reward", 0), ("status", "failed"),
                         ("invalid_actions", 1), ("reconciliation_required", True)):
        changed = [dict(item) for item in results]
        changed[2][field] = value
        assert not COLLECTOR.controls_qualified(changed)
    results[1]["cleanup"] = {"status": "timeout"}
    assert not COLLECTOR.controls_qualified(results)


def test_raw_failed_api_response_saved_before_rejection(tmp_path):
    body = b'{"failed":true,"reward":0.0}'

    def handler(request):
        return httpx.Response(409, stream=httpx.ByteStream(body))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        api = COLLECTOR.Api(client, tmp_path)
        with pytest.raises(RuntimeError, match="no retry"):
            api.request("POST", "/api/browser/attempts", {})
    assert (tmp_path / "api-responses/00000.body").read_bytes() == body
    assert json.loads((tmp_path / "api-responses/00000.json").read_text())["status"] == 409


def test_api_deadline_precedes_network_and_redirect_is_not_followed(tmp_path):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://example.invalid"}, stream=httpx.ByteStream(b""))

    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False) as client:
        with pytest.raises(TimeoutError):
            COLLECTOR.Api(client, tmp_path, deadline=0).request("GET", "/api/health")
        assert not calls
        with pytest.raises(RuntimeError):
            COLLECTOR.Api(client, tmp_path).request("GET", "/api/health")
    assert calls == [COLLECTOR.API + "/api/health"]


def test_source_failure_saved_as_stopped_without_http(tmp_path, monkeypatch):
    def failure(*args):
        raise RuntimeError("SECRET_SHOULD_NOT_APPEAR")

    monkeypatch.setattr(COLLECTOR, "source_identity", failure)
    monkeypatch.setattr(COLLECTOR.httpx, "Client", lambda *args, **kwargs: pytest.fail("HTTP contact"))
    report = COLLECTOR.collect(tmp_path / "new", "a" * 40, "a" * 40)
    assert report["status"] == "stopped"
    assert all(slot["status"] == "unattempted" for slot in report["slots"])
    assert "SECRET" not in (tmp_path / "new/report.json").read_text()


def test_byte_cap_reserves_final_report_and_never_replaces(tmp_path, monkeypatch):
    monkeypatch.setattr(COLLECTOR, "LIMIT", 1024 * 1024 + 10)
    COLLECTOR.write(tmp_path, tmp_path / "body", b"a" * 10)
    with pytest.raises(RuntimeError):
        COLLECTOR.write(tmp_path, tmp_path / "other", b"a")
    with pytest.raises(FileExistsError):
        COLLECTOR.write(tmp_path, tmp_path / "body", b"")
    COLLECTOR.save(tmp_path, tmp_path / "report.json", {"status": "stopped"})


def test_pinned_api_manifest_and_source_identity():
    spec = COLLECTOR.SLOTS[1]
    source = {"git_revision": "a" * 40, "controller_modules": {"x": "b" * 64}}
    attempt = {"task": COLLECTOR.make_browser_task(spec["task_id"], spec["seed"]).model_dump(),
               "config": {key: value for key, value in spec.items() if key != "name"},
               "provenance": {"source_git_revision": "a" * 40, "source_dirty": False,
                              "controller_modules": source["controller_modules"]}}
    attempt["config"]["model"] = "qwen3:8b"
    COLLECTOR.validate_attempt(attempt, spec, source)
    attempt["task"]["version"] = "forged"
    with pytest.raises(RuntimeError):
        COLLECTOR.validate_attempt(attempt, spec, source)


@pytest.mark.parametrize("include_model,failed_slot", [(False, None), (True, None), (True, 1)])
def test_fixed_fake_cohort_and_failure_stop(tmp_path, monkeypatch, include_model, failed_slot):
    source = {"git_revision": "a" * 40, "files": {}, "controller_modules": {}}
    monkeypatch.setattr(COLLECTOR, "source_identity", lambda revision: source)
    monkeypatch.setattr(COLLECTOR, "PROTOCOL", COLLECTOR.POLICY_PROTOCOL)
    preflights = []
    monkeypatch.setattr(COLLECTOR, "model_preflight", lambda model: preflights.append(model))
    posts = []

    class FakeApi:
        def __init__(self, client, output, deadline):
            pass

        def json(self, method, path, payload=None):
            if path == "/api/health":
                return {"paid_calls_enabled": False}
            if path == "/api/browser/status":
                return {"paid_calls_enabled": False, "available": True, "active_attempts": 0}
            assert method == "POST" and path == "/api/browser/attempts"
            posts.append(payload)
            return self.attempt(len(posts) - 1)

        def attempt(self, index):
            spec = COLLECTOR.SLOTS[index]
            passed = index != 0 and index != failed_slot
            return {**valid_result(passed), "id": f"attempt-{index}", "steps": 1,
                    "phase_seconds": {}, "elapsed_seconds": 1.0,
                    "task": COLLECTOR.make_browser_task(spec["task_id"], spec["seed"]).model_dump(),
                    "config": posts[index], "artifacts": [],
                    "provenance": {"source_git_revision": "a" * 40, "source_dirty": False, "controller_modules": {}},
                    "journal": [{"event": "policy_prepared", "data":
                        {"model_digest": COLLECTOR.MODEL_DIGEST, "protocol": COLLECTOR.POLICY_PROTOCOL,
                         "options": COLLECTOR.OPTIONS, "template_sha256": "c" * 64,
                         "declared_episode_timeout_seconds": 600,
                         "transport_timeouts_seconds": {"connect": 10, "write": 10, "pool": 10, "read": 180}} if index == 4 else
                        {"protocol": "public-ax-triage-control-v7" if index < 3 else "public-ax-browser-control-v1",
                         "scripted_control": True, "capability_measurement": False,
                         "baseline": index == 0, "training_eligible": False}}]}

        def request(self, method, path):
            assert method == "GET"
            index = int(path.rsplit("-", 1)[1])
            return json.dumps(self.attempt(index)).encode()

    monkeypatch.setattr(COLLECTOR, "Api", FakeApi)
    report = COLLECTOR.collect(tmp_path / "new", "a" * 40, "a" * 40, include_model)
    count = 2 if failed_slot is not None else 5 if include_model else 4
    assert len(posts) == count and len(report["results"]) == count
    assert report["status"] == ("stopped" if failed_slot is not None else "completed")
    assert len(preflights) == int(include_model and failed_slot is None)
    assert all(slot["status"] == "unattempted" for slot in report["slots"][count:])
    assert (tmp_path / "new/triage-change/attempt.json").exists()


@pytest.mark.parametrize("index", range(5))
@pytest.mark.parametrize("corruption", ["missing", "duplicate", "protocol", "eligibility"])
def test_prepared_policy_identity_rejects_drift(index, corruption):
    spec = COLLECTOR.SLOTS[index]
    metadata = ({"model_digest": COLLECTOR.MODEL_DIGEST, "protocol": COLLECTOR.POLICY_PROTOCOL,
                 "options": COLLECTOR.OPTIONS, "template_sha256": "c" * 64,
                 "declared_episode_timeout_seconds": 600,
                 "transport_timeouts_seconds": {"connect": 10, "write": 10, "pool": 10, "read": 180}} if index == 4 else
                {"protocol": "public-ax-triage-control-v7" if index < 3 else "public-ax-browser-control-v1",
                 "scripted_control": True, "capability_measurement": False,
                 "baseline": index == 0, "training_eligible": False})
    attempt = {"journal": [{"event": "policy_prepared", "data": metadata}]}
    COLLECTOR.validate_policy_identity(attempt, spec)
    if corruption == "missing":
        attempt["journal"] = []
    elif corruption == "duplicate":
        attempt["journal"] *= 2
    elif corruption == "protocol":
        metadata["protocol"] = "public-ax-triage-control-v2"
    elif index == 4:
        metadata["model_digest"] = "forged"
    else:
        metadata["training_eligible"] = True
    with pytest.raises(RuntimeError, match="identity"):
        COLLECTOR.validate_policy_identity(attempt, spec)


@pytest.mark.parametrize("index", range(3))
@pytest.mark.parametrize("protocol", ["public-ax-triage-control-v2", "public-ax-triage-control-v3",
                                      "public-ax-triage-control-v4", "public-ax-triage-control-v5",
                                      "public-ax-triage-control-v6"])
def test_historical_control_identity_cannot_qualify_v7(index, protocol):
    spec = COLLECTOR.SLOTS[index]
    metadata = {"protocol": protocol, "scripted_control": True,
                "capability_measurement": False, "baseline": index == 0,
                "training_eligible": False}
    attempt = {"journal": [{"event": "policy_prepared", "data": metadata}]}
    with pytest.raises(RuntimeError, match="identity"):
        COLLECTOR.validate_policy_identity(attempt, spec)


@pytest.mark.parametrize("model", ["qwen3:8b", "qwen3:32b", "qwen3:30b-a3b"])
def test_explicit_public_model_plan_and_fixed_limits(model):
    protocol = COLLECTOR.plan(model)
    assert protocol["model_digest"] == COLLECTOR.MODELS[model]
    assert protocol["schema"] == "world-engine.triage-qualification.v9"
    assert protocol["slots"][-1]["max_steps"] == 30
    assert protocol["slots"][-1]["timeout_seconds"] == 600
    assert protocol["reference_protocol"] == "public-ax-triage-control-v7"
    with pytest.raises(ValueError):
        COLLECTOR.plan("private-model")


def test_v9_rejects_archived_runtime_before_contact(tmp_path, monkeypatch):
    monkeypatch.setattr(COLLECTOR, "source_identity", lambda revision: {})
    monkeypatch.setattr(COLLECTOR, "PROTOCOL", "ollama-browser-tools-v2")
    monkeypatch.setattr(COLLECTOR.httpx, "Client", lambda *args, **kwargs: pytest.fail("HTTP contact"))
    result = COLLECTOR.collect(tmp_path / "new", "a" * 40, "a" * 40, True, "qwen3:32b")
    assert result["status"] == "stopped"
    assert not result["results"]


@pytest.mark.parametrize("model", ["qwen3:32b", "qwen3:30b-a3b"])
def test_large_model_identity_does_not_accept_small_or_unhashed_template(model):
    spec = COLLECTOR.SLOTS[-1]
    metadata = {"model_digest": COLLECTOR.MODELS[model],
                "protocol": COLLECTOR.POLICY_PROTOCOL, "options": COLLECTOR.OPTIONS,
                "template_sha256": "c" * 64, "declared_episode_timeout_seconds": 600,
                "transport_timeouts_seconds": {"connect": 10, "write": 10, "pool": 10, "read": 180}}
    attempt = {"journal": [{"event": "policy_prepared", "data": metadata}]}
    COLLECTOR.validate_policy_identity(attempt, spec, model)
    metadata["model_digest"] = COLLECTOR.MODEL_DIGEST
    with pytest.raises(RuntimeError):
        COLLECTOR.validate_policy_identity(attempt, spec, model)
    metadata["model_digest"] = COLLECTOR.MODELS[model]
    del metadata["template_sha256"]
    with pytest.raises(RuntimeError):
        COLLECTOR.validate_policy_identity(attempt, spec, model)


@pytest.mark.parametrize("field,value", [
    ("declared_episode_timeout_seconds", None), ("declared_episode_timeout_seconds", 180),
    ("transport_timeouts_seconds", None),
    ("transport_timeouts_seconds", {"connect": 90, "write": 90, "pool": 90, "read": 90}),
    ("transport_timeouts_seconds", {"connect": 10, "write": 10, "pool": 10, "read": 600}),
    ("transport_timeouts_seconds", {"connect": 10, "write": 10, "pool": 10, "read": 180, "total": 600}),
])
def test_v9_requires_explicit_reviewed_transport_identity(field, value):
    metadata = {"model_digest": COLLECTOR.MODELS["qwen3:30b-a3b"],
                "protocol": COLLECTOR.POLICY_PROTOCOL, "options": COLLECTOR.OPTIONS,
                "template_sha256": "c" * 64, "declared_episode_timeout_seconds": 600,
                "transport_timeouts_seconds": {"connect": 10, "write": 10, "pool": 10, "read": 180}}
    metadata[field] = value
    with pytest.raises(RuntimeError, match="identity"):
        COLLECTOR.validate_policy_identity({"journal": [{"event": "policy_prepared", "data": metadata}]},
                                          COLLECTOR.SLOTS[-1], "qwen3:30b-a3b")


@pytest.mark.parametrize("corruption", [None, "digest", "remote", "duplicate", "missing"])
def test_moe_preflight_uses_only_fixed_public_local_digest(corruption, monkeypatch):
    model = "qwen3:30b-a3b"
    entry = {"name": model, "digest": "0b28110b7a3364296d5cef609095537189fbb81547761de69fd22dd68d2166c2"}
    if corruption == "digest":
        entry["digest"] = "a" * 64
    if corruption == "remote":
        entry["remote_host"] = "https://example.invalid"
    entries = [] if corruption == "missing" else [entry] * (2 if corruption == "duplicate" else 1)
    calls = []

    def handler(request):
        calls.append(str(request.url))
        assert request.method == "GET" and request.headers["Accept-Encoding"] == "identity"
        return httpx.Response(200, stream=httpx.ByteStream(json.dumps({"models": entries}).encode()))

    client_class = httpx.Client
    monkeypatch.setattr(COLLECTOR.httpx, "Client", lambda **kwargs: client_class(
        transport=httpx.MockTransport(handler), **kwargs))
    if corruption:
        with pytest.raises(RuntimeError, match="identity differs"):
            COLLECTOR.model_preflight(model)
    else:
        COLLECTOR.model_preflight(model)
    assert calls == ["http://127.0.0.1:11434/api/tags"]
