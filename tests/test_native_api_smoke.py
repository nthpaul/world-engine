import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from world_engine.models import canonical_json, digest

SPEC = importlib.util.spec_from_file_location("native_api_smoke", Path(__file__).parents[1] / "examples/native_api_smoke.py")
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)
REVISION = "a" * 40
IDS = ["00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002"]


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk


@pytest.fixture
def harness(monkeypatch, tmp_path):
    output = tmp_path / "receipt"
    state = SimpleNamespace(output=output, calls=[], models=[], submissions=[], details={},
                            health={"status": "ok", "version": "0.1.0", "paid_calls_enabled": False, "active_runs": 0},
                            catalog={"models": [{"name": smoke.MODEL, "digest": smoke.MODEL_DIGEST}]},
                            source={"git_revision": REVISION, "source_dirty": False, "checkout_dirty": False,
                                    "files_sha256": {"fixture": "b" * 64}},
                            running=False, bad_detail=None, response_override=None, verify_error=False)
    monkeypatch.setattr(smoke, "source_identity", lambda revision: copy.deepcopy(state.source))
    monkeypatch.setattr(smoke, "fixture_identity", lambda: {"initial_state_hash": smoke.INITIAL_HASH})

    async def metadata(client, endpoint, route, **kwargs):
        assert endpoint == smoke.OLLAMA and route == "/api/tags"
        state.models.append(route)
        return state.catalog

    monkeypatch.setattr(smoke, "local_metadata", metadata)

    def handler(request):
        state.calls.append((request.method, request.url.path))
        assert str(request.url).startswith(smoke.API) and request.headers["accept-encoding"] == "identity"
        if state.response_override:
            return state.response_override(request)
        if request.url.path == "/api/health":
            value, status = state.health, 200
        elif request.url.path == "/api/runs" and request.method == "POST":
            index = len(state.submissions)
            config = json.loads(request.content)
            assert config == smoke.config_for(smoke.ALIASES[index][0]).model_dump()
            assert index == 0 or (output / "local-tools-episode.jsonl").exists()
            state.submissions.append(config)
            episode = {"seed": smoke.SEED, "provenance": {"marker": "synthetic"}, "passed": False,
                       "reward": 0.0, "elapsed_seconds": 35.0, "status": "failed", "termination": "timeout"}
            state.details[IDS[index]] = {"id": IDS[index], "status": "failed", "config": config, "episodes": [episode]}
            value, status = {"id": IDS[index]}, 202
        elif request.url.path == "/api/runs":
            value, status = {"runs": [{"id": key, "status": "running" if state.running else "failed"}
                                     for key in state.details]}, 200
        elif request.url.path.endswith("/cancel"):
            assert request.url.path.split("/")[-2] in state.details
            value, status = {"status": "cancelled"}, 200
        else:
            run_id = request.url.path.split("/")[-1]
            assert run_id in state.details
            value, status = state.bad_detail if state.bad_detail is not None else state.details[run_id], 200
        return httpx.Response(status, stream=Chunks([(canonical_json(value) + "\n").encode()]))

    factory = httpx.AsyncClient
    monkeypatch.setattr(smoke.httpx, "AsyncClient", lambda **kwargs: factory(transport=httpx.MockTransport(handler), **kwargs))

    def verify(episode, alias, protocol, revision):
        assert (output / f"{alias}-episode.jsonl").exists()
        assert json.loads((output / f"{alias}-episode.jsonl").read_text())["episode"] == episode
        assert revision == REVISION and protocol == dict(smoke.ALIASES)[alias]
        if state.verify_error:
            raise ValueError("PRIVATE_PARSE_SENTINEL")
        return {"episode_status": episode["status"], "passed": False, "reward": 0.0, "termination": "timeout", "verified": True}

    monkeypatch.setattr(smoke, "check_episode", verify)
    return state


def test_plan_is_pure_and_locked(monkeypatch, capsys):
    for name in ("source_identity", "fixture_identity", "collect"):
        monkeypatch.setattr(smoke, name, lambda *args: pytest.fail("no activity in plan"))
    assert smoke.main([]) == smoke.main(["--plan"]) == 0
    assert "plan-only" in capsys.readouterr().out
    plan = smoke.plan()
    assert plan["protocol_sha256"] == digest(smoke.protocol())
    assert [alias for alias, _ in plan["protocol"]["aliases"]] == ["local-tools", "local-tools-ledger"]
    assert plan["protocol"]["seed"] == 54000 and plan["protocol"]["max_submissions"] == 2
    assert plan["protocol"]["overall_seconds"] == 180
    for alias, _ in smoke.ALIASES:
        config = smoke.config_for(alias)
        assert config.evaluation_only is True and config.allow_paid is False
        assert (config.episodes, config.concurrency, config.timeout_seconds, config.max_steps) == (1, 1, 35, 20)


@pytest.mark.parametrize("url", ["http://localhost:8000", "http://example.com", smoke.API + "?secret=PRIVATE",
    "http://PRIVATE:secret@127.0.0.1:8000", "http://[INVALID", smoke.API + "/api", smoke.API + "\n"])
async def test_api_url_rejects_before_any_activity(harness, url):
    with pytest.raises(smoke.SmokeStopped, match="approved fixed API"):
        await smoke.collect(harness.output, REVISION, REVISION, url)
    assert not harness.output.exists() and not harness.calls and not harness.models


@pytest.mark.parametrize("kind", ["directory", "file", "live-symlink", "dangling-symlink"])
async def test_existing_output_fails_before_source_or_http(harness, monkeypatch, tmp_path, kind):
    if kind == "directory":
        harness.output.mkdir()
    elif kind == "file":
        harness.output.write_text("old")
    else:
        target = tmp_path / "target"
        if kind == "live-symlink":
            target.mkdir()
        harness.output.symlink_to(target)
    monkeypatch.setattr(smoke, "source_identity", lambda *args: pytest.fail("existing output must fail first"))
    with pytest.raises(FileExistsError):
        await smoke.collect(harness.output, REVISION, REVISION)
    assert not harness.calls and not harness.models


async def test_fixed_attempts_save_exact_responses_and_wrappers_before_validation(harness):
    report = await smoke.collect(harness.output, REVISION, REVISION)
    assert report["status"] == "completed" and report["verified_episodes"] == 2
    assert report["submission_attempts"] == 2 and report["unattempted_slots"] == 0
    assert report["client_metadata_attempts"] == 2 and not report["cancel_attempts"]
    assert [value["provider_id"] for value in harness.submissions] == [alias for alias, _ in smoke.ALIASES]
    assert report["artifact_total_bytes"] == sum(path.stat().st_size for path in harness.output.iterdir())
    assert report["report_bytes"] == (harness.output / "report.json").stat().st_size
    assert not any(b"models" in path.read_bytes() for path in harness.output.glob("*.body"))
    for line in (harness.output / "api-responses.jsonl").read_text().splitlines():
        entry = json.loads(line)
        raw = (harness.output / entry["body_file"]).read_bytes()
        assert len(raw) == entry["body_bytes"] and entry["body_complete"] is True
    for alias, _ in smoke.ALIASES:
        row = next(row for row in report["rows"] if row["provider_id"] == alias)
        assert row["episode_file"] == f"{alias}-episode.jsonl"
        wrapper = (harness.output / row["episode_file"]).read_text()
        assert len(wrapper.splitlines()) == 1
        episode = json.loads(wrapper)["episode"]
        assert type(episode["reward"]) is float and type(episode["elapsed_seconds"]) is float
        assert type(episode["seed"]) is int


@pytest.mark.parametrize("field,value", [("paid_calls_enabled", True), ("active_runs", 1), ("active_runs", False),
                                       ("version", "other"), ("status", "offline")])
async def test_health_preflight_never_submits(harness, field, value):
    harness.health[field] = value
    report = await smoke.collect(harness.output, REVISION, REVISION)
    assert report["status"] == "stopped" and report["unattempted_slots"] == 2
    assert not harness.submissions and not harness.models


@pytest.mark.parametrize("catalog", [{}, {"models": "bad"}, {"models": []},
    {"models": [{"name": smoke.MODEL, "digest": "0" * 64}]},
    {"models": [{"name": smoke.MODEL, "digest": smoke.MODEL_DIGEST, "remote_host": "cloud"}]}])
async def test_missing_remote_or_changed_model_does_not_submit_or_save_catalog(harness, catalog):
    harness.catalog = catalog
    report = await smoke.collect(harness.output, REVISION, REVISION)
    assert report["status"] == "stopped" and not harness.submissions
    assert not any("catalog" in key or "models" in key for key in report)


async def test_source_preflight_failure_preserves_unattempted_slots(harness, monkeypatch):
    monkeypatch.setattr(smoke, "source_identity", lambda *args: (_ for _ in ()).throw(ValueError("PRIVATE_SOURCE_SENTINEL")))
    report = await smoke.collect(harness.output, REVISION, REVISION)
    assert report["status"] == "stopped" and not harness.calls and not harness.submissions
    assert "PRIVATE" not in canonical_json(report)


async def test_changed_source_during_metadata_prevents_submission(harness, monkeypatch):
    async def metadata(*args, **kwargs):
        harness.source["files_sha256"]["fixture"] = "c" * 64
        return harness.catalog
    monkeypatch.setattr(smoke, "local_metadata", metadata)
    report = await smoke.collect(harness.output, REVISION, REVISION)
    assert report["status"] == "stopped" and not harness.submissions


@pytest.mark.parametrize("response", [httpx.Response(302, headers={"location": "https://example.com/PRIVATE"}, stream=Chunks([b"redirect"])),
    httpx.Response(200, stream=Chunks([b"not json PRIVATE_RAW_SENTINEL"])),
    httpx.Response(200, stream=Chunks([b"[]"])),
    httpx.Response(200, headers={"content-encoding": "gzip"}, stream=Chunks([b"gzip raw bytes"]))])
async def test_bad_api_raw_is_persisted_before_protocol_failure(harness, response):
    harness.response_override = lambda request: response
    report = await smoke.collect(harness.output, REVISION, REVISION)
    assert report["status"] == "stopped" and not harness.submissions
    calls = [json.loads(line) for line in (harness.output / "api-responses.jsonl").read_text().splitlines()]
    assert len(calls) == 1 and (harness.output / calls[0]["body_file"]).exists()
    assert "PRIVATE" not in canonical_json(report)


async def test_multichunk_raw_cap_keeps_only_bounded_prefix(harness, monkeypatch):
    monkeypatch.setattr(smoke, "SMALL_CAP", 5)
    # Default arguments were bound at definition; exercise explicit transport cap.
    harness.output.mkdir()
    evidence = smoke.Evidence(harness.output)
    harness.response_override = lambda request: httpx.Response(200, stream=Chunks([b"123", b"456", b"789"]))
    async with smoke.httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
        with pytest.raises(smoke.SmokeStopped):
            await evidence.exchange(client, "GET", "/api/health", cap=5)
    assert evidence.calls[0]["body_bytes"] == 5 and evidence.calls[0]["body_complete"] is False
    assert (harness.output / evidence.calls[0]["body_file"]).read_bytes() == b"12345"


async def test_malformed_terminal_response_is_raw_first_and_cancels_only_owned(harness):
    harness.bad_detail = {"id": IDS[0], "episodes": "malformed PRIVATE_RAW_SENTINEL"}
    report = await smoke.collect(harness.output, REVISION, REVISION)
    assert report["status"] == "stopped" and len(harness.submissions) == 1
    assert harness.calls.count(("POST", f"/api/runs/{IDS[0]}/cancel")) == 1
    assert report["unattempted_slots"] == 1
    assert any(b"PRIVATE_RAW_SENTINEL" in path.read_bytes() for path in harness.output.glob("*.body"))
    assert "PRIVATE" not in report["error"]


async def test_failed_replay_retains_wrapper_and_cancels_no_unrelated_run(harness):
    harness.verify_error = True
    report = await smoke.collect(harness.output, REVISION, REVISION)
    assert report["status"] == "stopped" and (harness.output / "local-tools-episode.jsonl").exists()
    assert len(report["cancel_attempts"]) == 1 and report["cancel_attempts"][0]["run_id"] == IDS[0]
    assert report["rows"][0]["status"] == "raw_saved" and report["rows"][1]["status"] == "unattempted"
    assert "PRIVATE" not in canonical_json(report)


async def test_deadline_cancels_once_and_never_admits_next_slot(harness, monkeypatch):
    harness.running = True
    monkeypatch.setattr(smoke, "OVERALL_SECONDS", .03)
    monkeypatch.setattr(smoke, "FINALIZE_SECONDS", 0)
    report = await smoke.collect(harness.output, REVISION, REVISION)
    assert report["status"] == "stopped" and len(harness.submissions) == 1
    assert harness.calls.count(("POST", f"/api/runs/{IDS[0]}/cancel")) == 1
    assert len(report["cancel_attempts"]) == 1


async def test_quota_prevents_any_submission(harness, monkeypatch):
    monkeypatch.setattr(smoke, "SLOT_RESERVE", smoke.ARTIFACT_CAP)
    report = await smoke.collect(harness.output, REVISION, REVISION)
    assert report["status"] == "stopped" and not harness.calls and not harness.models


async def test_reserved_cancel_budget_is_consumable_without_re_reserving_it(harness, monkeypatch):
    harness.output.mkdir()
    harness.details[IDS[0]] = {}
    evidence = smoke.Evidence(harness.output)
    monkeypatch.setattr(evidence, "size", lambda: smoke.ARTIFACT_CAP - smoke.REPORT_RESERVE - smoke.CANCEL_RESERVE)
    async with smoke.httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
        with pytest.raises(smoke.SmokeStopped, match="reservation unavailable"):
            await evidence.exchange(client, "GET", "/api/health")
        result = await evidence.exchange(client, "POST", f"/api/runs/{IDS[0]}/cancel", reserve=smoke.REPORT_RESERVE)
    assert result == {"status": "cancelled"}
    assert harness.calls == [("POST", f"/api/runs/{IDS[0]}/cancel")]
    assert len(evidence.calls) == 1 and evidence.calls[0]["body_complete"] is True


@pytest.mark.parametrize("args", [["--collect"], ["--output", "out"], ["--source-revision", REVISION],
    ["--collect", "--source-revision", REVISION, "--api-startup-revision", "b" * 40, "--output", "out"],
    ["--plan", "--collect"], ["--api", "http://example.com"]])
def test_invalid_cli_arguments_never_collect(monkeypatch, args):
    monkeypatch.setattr(smoke, "collect", lambda *args: pytest.fail("no collection"))
    with pytest.raises(SystemExit) as failure:
        smoke.main(args)
    assert failure.value.code == 2


@pytest.mark.parametrize("change", ["head", "dirty", "blob"])
def test_source_gate_rejects_head_dirty_or_blob_changes(monkeypatch, tmp_path, change):
    source = tmp_path / "src/world_engine"
    source.mkdir(parents=True)
    (source / "fixture.py").write_text("public synthetic fixture")
    monkeypatch.setattr(smoke, "ROOT", tmp_path)
    monkeypatch.setattr(smoke, "SOURCE_SCOPE", ["src/world_engine"])

    def git(command, **kwargs):
        assert command[0] == "git" and kwargs["timeout"] == 3
        if command[1] == "rev-parse":
            value = (("b" * 40) if change == "head" else REVISION).encode()
        elif command[1] == "status":
            value = b" M src/world_engine/fixture.py" if change == "dirty" else b""
        else:
            value = b"changed" if change == "blob" else b"public synthetic fixture"
        return SimpleNamespace(stdout=value)

    monkeypatch.setattr(smoke.subprocess, "run", git)
    with pytest.raises(smoke.SmokeStopped):
        smoke.source_identity(REVISION)


async def test_source_changed_terminal_gate_preserves_both_raw_slots(harness, monkeypatch):
    original = smoke.check_episode

    def verify(*args):
        value = original(*args)
        if args[1] == "local-tools-ledger":
            harness.source["files_sha256"]["fixture"] = "c" * 64
        return value

    monkeypatch.setattr(smoke, "check_episode", verify)
    report = await smoke.collect(harness.output, REVISION, REVISION)
    assert report["status"] == "stopped" and report["verified_episodes"] == 2
    assert report["source_post_error"] and report["unattempted_slots"] == 0


async def test_metadata_failure_never_persists_private_catalog_prefix(harness, monkeypatch):
    async def metadata(*args, **kwargs):
        raise ValueError("PRIVATE_MODEL_CATALOG_SENTINEL")
    monkeypatch.setattr(smoke, "local_metadata", metadata)
    report = await smoke.collect(harness.output, REVISION, REVISION)
    assert report["status"] == "stopped" and not harness.submissions
    assert all(b"PRIVATE_MODEL_CATALOG_SENTINEL" not in path.read_bytes() for path in harness.output.iterdir())


@pytest.fixture
def episode_contract(monkeypatch):
    import world_engine.provider_records as records
    import world_engine.rollout as rollout
    provenance = {"environment_id": smoke.WORLD, "environment_version": smoke.VERSION,
                  "initial_state_hash": smoke.INITIAL_HASH, "environment_code_hash": smoke.ENVIRONMENT_HASH,
                  "grader_code_hash": smoke.GRADER_HASH, "model": smoke.MODEL, "model_digest": smoke.MODEL_DIGEST,
                  "provider_protocol": smoke.ALIASES[0][1], "evaluation_only": True, "training_eligible": False,
                  "git_revision": REVISION, "implementation_dirty": False}
    start = {"event": "request_started"}
    end = {"event": "request_finished", "outcome": "accepted", "usage": {"input_tokens": 0, "output_tokens": 3}}
    episode = {"seed": smoke.SEED, "provenance": provenance, "provider_events": [start, end],
               "status": "completed", "termination": "finished", "passed": False, "reward": .4,
               "steps": 1, "invalid_actions": 0, "elapsed_seconds": .25}
    monkeypatch.setattr(rollout, "replay", lambda value: {"verified": True})
    monkeypatch.setattr(records, "validate_pairs", lambda events, protocol: [(events[0], events[1])])
    return episode


def test_verification_derives_counts_usage_and_real_training_exclusions(episode_contract):
    row = smoke.check_episode(episode_contract, *smoke.ALIASES[0], REVISION)
    assert row["native_request_attempts"] == row["accepted"] == 1 and row["cancelled"] == 0
    assert row["usage"]["input_tokens"] == 0 and row["usage"]["input_tokens_complete"] is True
    assert row["passed"] is False and row["reward"] == .4
    assert all(value["unsupported_provider_protocol"] == 1 for value in row["training_exclusions"].values())


@pytest.mark.parametrize("key,value", [("environment_version", "other"), ("model_digest", "0" * 64),
    ("provider_protocol", "ollama-json-v1"), ("evaluation_only", 1), ("training_eligible", True),
    ("git_revision", "b" * 40), ("implementation_dirty", True), ("initial_state_hash", "0" * 64)])
def test_episode_identity_changes_fail_closed(episode_contract, key, value):
    episode_contract["provenance"][key] = value
    with pytest.raises(smoke.SmokeStopped, match="episode identity"):
        smoke.check_episode(episode_contract, *smoke.ALIASES[0], REVISION)


def test_replay_failure_prevents_verified_label(episode_contract, monkeypatch):
    import world_engine.rollout as rollout
    monkeypatch.setattr(rollout, "replay", lambda value: {"verified": False})
    with pytest.raises(smoke.SmokeStopped, match="replay failed"):
        smoke.check_episode(episode_contract, *smoke.ALIASES[0], REVISION)
