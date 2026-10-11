import asyncio
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from world_engine.models import digest

SPEC = importlib.util.spec_from_file_location("access_native_study", Path(__file__).parents[1] / "examples/access_native_study.py")
study = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(study)
REVISION = "a" * 40


class FakeProvider:
    model, model_digest = study.MODEL, study.MODEL_DIGEST

    def __init__(self, events):
        self.events = events
        self.closed = False

    async def prepare(self):
        self.events.append("prepare")

    def evidence_metadata(self):
        return {"native_contract_hash": study.NATIVE_CONTRACT_HASH}

    async def close(self):
        self.closed = True
        self.events.append("close")


@pytest.fixture
def harness(monkeypatch, tmp_path):
    events, attempted = [], []
    provider = FakeProvider(events)
    source = {"git_revision": REVISION, "source_dirty": False, "files_sha256": {"fixture.py": "b" * 64}}
    output = tmp_path / "receipt"
    monkeypatch.setattr(study, "source_identity", lambda revision: copy.deepcopy(source))
    monkeypatch.setattr(study, "make_provider", lambda: provider)
    monkeypatch.setattr(study, "replay", lambda episode: {"verified": True})

    async def rollout(config, index, supplied):
        assert supplied is provider and events[0] == "prepare"
        assert len((output / "evaluation-episodes.jsonl").read_text().splitlines()) == len(attempted)
        assert config.environment_id == study.WORLD and config.seed == len(attempted)
        assert (config.max_steps, config.timeout_seconds, config.concurrency, config.episodes) == (20, 35, 1, 1)
        assert config.evaluation_only and not config.allow_paid and config.model == study.MODEL
        attempted.append(config.seed)
        return {"seed": config.seed, "passed": True, "reward": 1.0, "status": "completed", "termination": "finished",
                "steps": 1, "invalid_actions": 0, "elapsed_seconds": .01, "usage": {"request_attempts": 1},
                "provider_events": [{"event": "request_started"}, {"event": "request_finished", "outcome": "accepted"}],
                "provenance": {"environment_id": study.WORLD, "environment_version": study.VERSION,
                               "environment_code_hash": study.ENVIRONMENT_HASH, "grader_code_hash": study.GRADER_HASH,
                               "initial_state_hash": study.INITIAL_HASHES[config.seed], "evaluation_only": True,
                               "training_eligible": False, "git_revision": REVISION, "implementation_dirty": False,
                               "provider_protocol": study.PROTOCOL, "provider_evidence": provider.evidence_metadata(),
                               "model": study.MODEL, "model_digest": study.MODEL_DIGEST}}

    monkeypatch.setattr(study, "rollout", rollout)
    return SimpleNamespace(output=output, provider=provider, source=source, events=events,
                           attempted=attempted, rollout=rollout)


def test_default_plan_never_contacts_provider_or_source(monkeypatch, capsys):
    def forbidden(*args):
        pytest.fail("plan must not contact provider, inspect Git or reserve output")

    monkeypatch.setattr(study, "make_provider", forbidden)
    monkeypatch.setattr(study, "source_identity", forbidden)
    monkeypatch.setattr(study, "collect", forbidden)
    assert study.main([]) == study.main(["--plan"]) == 0
    assert "plan-only" in capsys.readouterr().out
    plan = study.plan()
    assert plan["protocol_sha256"] == study.PROTOCOL_SHA256 == digest(study.protocol())
    assert [slot["seed"] for slot in plan["protocol"]["slots"]] == list(range(8))
    assert plan["reservation_bound"]["derived_upper_bytes"] <= study.EPISODE_RESERVE
    assert plan["protocol"]["max_model_requests"] == 160
    assert plan["protocol"]["overall_seconds"] == 600


@pytest.mark.parametrize("args", [["--collect"], ["--collect", "--output", "receipt"],
    ["--collect", "--source-revision", "short", "--output", "receipt"], ["--plan", "--collect"],
    ["--output", "receipt"], ["--source-revision", REVISION], ["--unknown"]])
def test_invalid_cli_flags_refuse_without_activity(monkeypatch, args):
    monkeypatch.setattr(study, "collect", lambda *args: pytest.fail("no collection"))
    with pytest.raises(SystemExit) as failure:
        study.main(args)
    assert failure.value.code == 2


@pytest.mark.parametrize("kind", ["file", "directory", "live-symlink", "dangling-symlink"])
async def test_existing_output_refused_before_source_or_provider(tmp_path, monkeypatch, kind):
    output = tmp_path / "receipt"
    if kind == "file":
        output.write_text("historical receipt")
    elif kind == "directory":
        output.mkdir()
        (output / "old.json").write_text("historical receipt")
    else:
        target = tmp_path / "target"
        if kind == "live-symlink":
            target.mkdir()
        output.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(study, "source_identity", lambda *args: pytest.fail("no source activity"))
    monkeypatch.setattr(study, "make_provider", lambda: pytest.fail("no provider activity"))
    with pytest.raises(FileExistsError):
        await study.collect(output, REVISION)
    if kind == "file":
        assert output.read_text() == "historical receipt"
    elif kind == "directory":
        assert (output / "old.json").read_text() == "historical receipt"
    else:
        assert output.is_symlink()


async def test_success_fsyncs_raw_before_next_attempt_and_exact_bytes(harness, monkeypatch):
    calls = []
    original = study.os.fsync

    def fsync(fd):
        calls.append(fd)
        return original(fd)

    monkeypatch.setattr(study.os, "fsync", fsync)
    report = await study.collect(harness.output, REVISION)
    assert report["status"] == "completed" and harness.provider.closed
    assert harness.events == ["prepare", "close"] and harness.attempted == list(range(8))
    assert report["verified_episodes"] == report["business_passes"] == report["clean_passes"] == 8
    assert report["model_request_attempts"] == 8 and report["model_request_attempts_complete"]
    assert report["unattempted_episodes"] == report["inconclusive_episodes"] == 0
    assert len(calls) == 9
    assert sorted(path.name for path in harness.output.iterdir()) == ["evaluation-episodes.jsonl", "report.json"]
    assert report["artifact_total_bytes"] == sum(path.stat().st_size for path in harness.output.iterdir())
    assert report["report_bytes"] == (harness.output / "report.json").stat().st_size
    with pytest.raises(FileExistsError):
        await study.collect(harness.output, REVISION)


@pytest.mark.parametrize("mismatch", ["digest", "contract"])
async def test_prepared_model_contract_mismatch_stops_before_chat(harness, mismatch):
    if mismatch == "digest":
        harness.provider.model_digest = "0" * 64
    else:
        harness.provider.evidence_metadata = lambda: {"native_contract_hash": "0" * 64}
    report = await study.collect(harness.output, REVISION)
    assert report["status"] == "stopped" and not harness.attempted
    assert report["unattempted_episodes"] == 8 and harness.provider.closed


async def test_source_change_between_episodes_stops_and_preserves_prior(harness, monkeypatch):
    count = 0

    def source(revision):
        nonlocal count
        count += 1
        result = copy.deepcopy(harness.source)
        if count >= 3:
            result["files_sha256"]["fixture.py"] = "c" * 64
        return result

    monkeypatch.setattr(study, "source_identity", source)
    report = await study.collect(harness.output, REVISION)
    assert harness.attempted == [0] and report["status"] == "stopped"
    assert report["rows"][0]["passed"] and report["rows"][0]["outcome_integrity"]
    assert report["slots"][1]["status"] == "not_attempted" and report["unattempted_episodes"] == 7


async def test_final_source_change_is_reported(harness, monkeypatch):
    count = 0

    def source(revision):
        nonlocal count
        count += 1
        result = copy.deepcopy(harness.source)
        if count == 10:
            result["files_sha256"]["fixture.py"] = "c" * 64
        return result

    monkeypatch.setattr(study, "source_identity", source)
    report = await study.collect(harness.output, REVISION)
    assert report["status"] == "stopped" and "source changed" in report["stop_reason"]
    assert len(harness.attempted) == 8


@pytest.mark.parametrize("failure", ["malformed", "identity", "replay"])
async def test_second_bad_envelope_raw_saved_and_only_current_slot_inconclusive(harness, monkeypatch, failure):
    async def bad(config, index, provider):
        episode = await harness.rollout(config, index, provider)
        if config.seed == 1:
            if failure == "malformed":
                episode.pop("steps")
            elif failure == "identity":
                episode["provenance"]["initial_state_hash"] = "0" * 64
        return episode

    monkeypatch.setattr(study, "rollout", bad)
    if failure == "replay":
        monkeypatch.setattr(study, "replay", lambda episode: {"verified": episode["seed"] != 1})
    report = await study.collect(harness.output, REVISION)
    raw = list(map(json.loads, (harness.output / "evaluation-episodes.jsonl").read_text().splitlines()))
    assert [row["slot"]["seed"] for row in raw] == [0, 1] and raw[1]["episode"]["passed"] is True
    assert report["rows"][0]["passed"] and report["rows"][0]["outcome_integrity"]
    assert not report["rows"][1]["passed"] and not report["rows"][1]["outcome_integrity"]
    assert report["rows"][1]["observed_passed"] is True
    assert report["rows"][1]["model_request_attempts"] == 1
    assert report["model_request_attempts"] == 2 and report["model_request_attempts_complete"]
    assert report["slots"][1]["status"] == "finalized_inconclusive"
    assert report["inconclusive_episodes"] == 1 and report["unattempted_episodes"] == 6


async def test_raise_during_second_episode_keeps_unknown_attempts_and_prefix(harness, monkeypatch):
    async def partial(config, index, provider):
        if config.seed == 1:
            raise RuntimeError("sensitive mock transport details")
        return await harness.rollout(config, index, provider)

    monkeypatch.setattr(study, "rollout", partial)
    report = await study.collect(harness.output, REVISION)
    assert report["slots"][1]["status"] == "attempted_without_final_episode"
    assert report["rows"][0]["passed"] and not report["rows"][1]["episode_available"]
    assert report["model_request_attempts"] == 1 and not report["model_request_attempts_complete"]
    assert "sensitive" not in (harness.output / "report.json").read_text()
    assert harness.provider.closed


async def test_finalized_provider_failure_is_retained_without_retry(harness, monkeypatch):
    async def failure(config, index, provider):
        episode = await harness.rollout(config, index, provider)
        if config.seed == 1:
            episode.update(passed=False, reward=0.0, status="failed", termination="provider_error",
                           usage={"request_attempts": 1, "input_tokens_complete": False,
                                  "output_tokens_complete": False})
            episode["provider_events"][1]["outcome"] = "multiple_tool_calls"
        return episode

    monkeypatch.setattr(study, "rollout", failure)
    report = await study.collect(harness.output, REVISION)
    assert harness.attempted == list(range(8)) and report["status"] == "completed"
    assert report["business_passes"] == report["clean_passes"] == 7
    assert report["rows"][1]["termination"] == "provider_error" and report["rows"][1]["replay_verified"]
    assert "input_tokens" not in report["rows"][1]["usage"]
    assert report["model_request_attempts"] == 8


async def test_handled_cancelled_episode_saved_and_no_next_request(harness, monkeypatch):
    async def cancellation(config, index, provider):
        episode = await harness.rollout(config, index, provider)
        episode.update(passed=False, reward=0.0, status="cancelled", termination="cancelled")
        return episode

    monkeypatch.setattr(study, "rollout", cancellation)
    report = await study.collect(harness.output, REVISION)
    assert harness.attempted == [0] and harness.provider.closed
    assert report["status"] == "stopped" and report["unattempted_episodes"] == 7
    raw = json.loads((harness.output / "evaluation-episodes.jsonl").read_text())
    assert raw["episode"]["status"] == "cancelled"


@pytest.mark.parametrize("where", ["prepare", "cleanup", "cleanup-timeout"])
async def test_cleanup_bounds_and_prepare_failure_redacted(harness, monkeypatch, where):
    async def fail():
        raise RuntimeError("sensitive mock cleanup details")

    async def hang():
        await asyncio.sleep(1)

    if where == "prepare":
        harness.provider.prepare = fail
    else:
        harness.provider.close = fail if where == "cleanup" else hang
        monkeypatch.setattr(study, "CLEANUP_SECONDS", .01)
        monkeypatch.setattr(study, "plan", lambda: {"mock": True})
    report = await study.collect(harness.output, REVISION)
    assert report["status"] == "stopped" and "sensitive" not in (harness.output / "report.json").read_text()
    if where == "prepare":
        assert harness.provider.closed and not harness.attempted
    else:
        assert report["finalized_episodes"] == 8 and report["cleanup_errors"][0]["resource_closed"] is False


async def test_cap_refuses_next_request_and_preserves_prior(harness, monkeypatch):
    def size(output):
        return study.ARTIFACT_CAP if harness.attempted else 0

    monkeypatch.setattr(study, "artifact_bytes", size)
    monkeypatch.setattr(study, "append_raw", lambda handle, record, output: (handle.write((json.dumps(record) + "\n").encode()), True)[1])
    monkeypatch.setattr(study, "write_report", lambda output, report: None)
    report = await study.collect(harness.output, REVISION)
    assert harness.attempted == [0] and report["status"] == "stopped" and "artifact cap" in report["stop_reason"]
    assert report["unattempted_episodes"] == 7


async def test_oversize_reservation_retains_full_current_raw_and_stops(harness, monkeypatch):
    original = study.append_raw

    def oversized(handle, record, output):
        original(handle, record, output)
        return False

    monkeypatch.setattr(study, "append_raw", oversized)
    report = await study.collect(harness.output, REVISION)
    assert len((harness.output / "evaluation-episodes.jsonl").read_text().splitlines()) == 1
    assert report["inconclusive_episodes"] == 1 and report["unattempted_episodes"] == 7


async def test_wall_budget_stops_before_prepare_and_still_writes_receipt(harness, monkeypatch):
    monkeypatch.setattr(study, "OVERALL_SECONDS", 0)
    monkeypatch.setattr(study, "plan", lambda: {"mock": True})
    report = await study.collect(harness.output, REVISION)
    assert report["status"] == "stopped" and not harness.events and not harness.attempted
    assert report["unattempted_episodes"] == 8


def test_source_scope_requires_exact_committed_full_sha(tmp_path, monkeypatch):
    monkeypatch.setattr(study, "ROOT", tmp_path)
    for relative in study.SOURCE_SCOPE:
        path = tmp_path / relative
        if relative == "src/world_engine":
            path.mkdir(parents=True)
            (path / "fixture.py").write_text("fixture\n")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture\n")
    calls = []

    def git(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout=REVISION if args[1] == "rev-parse" else "")

    monkeypatch.setattr(study.subprocess, "run", git)
    source = study.source_identity(REVISION)
    assert source["source_dirty"] is False and "src/world_engine/fixture.py" in source["files_sha256"]
    assert calls[1][-len(study.SOURCE_SCOPE):] == study.SOURCE_SCOPE
    with pytest.raises(study.StudyStopped, match="full lowercase"):
        study.source_identity("short")
    monkeypatch.setattr(study.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout="dirty"))
    with pytest.raises(study.StudyStopped, match="committed and clean"):
        study.source_identity(REVISION)
