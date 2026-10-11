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
    assert plan["schema"] == "world-engine.triage-qualification.v3"
    assert plan["reference_protocol"] == "public-ax-triage-control-v3"
    assert [slot["seed"] for slot in plan["slots"]] == [42, 42, 43, 42, 42]
    assert plan["training_eligible"] is False and plan["automatic_retries"] == 0


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
    preflights = []
    monkeypatch.setattr(COLLECTOR, "model_preflight", lambda: preflights.append(True))
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
                        {"model_digest": COLLECTOR.MODEL_DIGEST, "protocol": COLLECTOR.PROTOCOL,
                         "options": COLLECTOR.OPTIONS} if index == 4 else
                        {"protocol": "public-ax-triage-control-v3" if index < 3 else "public-ax-browser-control-v1",
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
    metadata = ({"model_digest": COLLECTOR.MODEL_DIGEST, "protocol": COLLECTOR.PROTOCOL,
                 "options": COLLECTOR.OPTIONS} if index == 4 else
                {"protocol": "public-ax-triage-control-v3" if index < 3 else "public-ax-browser-control-v1",
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
