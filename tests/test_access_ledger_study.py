"""Collector tests use fabricated transport records and never contact a provider."""

from __future__ import annotations

import asyncio
import base64
import copy
import importlib.util
import json
from pathlib import Path

import pytest

from world_engine import provider_records
from world_engine.models import canonical_json, digest

PATH = Path(__file__).resolve().parents[1] / "examples/access_ledger_study.py"
SPEC = importlib.util.spec_from_file_location("access_ledger_study", PATH)
study = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(study)
REVISION = "a" * 40


def fake_events(selected, seed):
    events = []
    for index in range(2):
        request = canonical_json({"mock": True, "seed": seed, "index": index})
        response = canonical_json({"mock": True, "done": True}).encode()
        identity = {"schema": provider_records.RECORD_SCHEMA, "protocol": selected,
                    "call_id": f"mock-{seed}-{index}", "decision_index": index,
                    "observed_at": "2026-10-10T00:00:00Z"}
        usage = {"output_tokens": 5}
        if seed != 3:
            usage["input_tokens"] = 10
        if index == 0:
            usage["inference_ns"] = 1000
        events.extend([
            {**identity, "event": "request_started", "request_body": request,
             "request_bytes": len(request.encode()), "request_sha256": provider_records.byte_hash(request.encode())},
            {**identity, "event": "request_finished", "response_body_b64": base64.b64encode(response).decode(),
             "response_bytes": len(response), "response_sha256": provider_records.byte_hash(response),
             "response_hash_scope": "complete-body", "body_complete": True, "complete": True,
             "outcome": "accepted", "elapsed_ms": 2.0, "http_status": 200, "usage": usage},
        ])
    return events


def fake_episode(config, provider):
    seed, selected = config.seed, provider.provider_protocol
    passed = seed % 4 == 0 or seed % 4 == (1 if selected == study.PROTOCOL else 2)
    events = fake_events(selected, seed)
    return {
        "seed": seed, "index": 0, "scenario_id": f"case-{seed}", "split": "test",
        "initial_observation": {"public": True, "seed": seed}, "passed": passed,
        "reward": float(passed), "status": "completed", "termination": "finished", "steps": 2,
        "invalid_actions": int(seed == 4 and selected == study.PROTOCOL), "elapsed_seconds": 0.01,
        "usage": provider_records.usage_summary(events), "provider_events": events,
        "provenance": {
            "environment_id": study.WORLD, "environment_version": study.VERSION, "grader_version": "1.0.0",
            "environment_code_hash": study.ENVIRONMENT_HASH, "grader_code_hash": study.GRADER_HASH,
            "initial_state_hash": study.INITIAL_HASHES[seed], "task_hash": digest({"task": seed}),
            "prompt_hash": digest({"prompt": seed}), "evaluation_only": True, "training_eligible": False,
            "git_revision": REVISION, "implementation_dirty": False, "provider_protocol": selected,
            "provider_evidence": provider.evidence_metadata(), "model": study.MODEL, "model_digest": study.MODEL_DIGEST,
        },
    }


@pytest.fixture(scope="module")
def fixed_plan():
    return study.plan()


@pytest.fixture
def harness(monkeypatch, fixed_plan):
    providers, calls = [], []

    class MockProvider:
        def __init__(self, selected):
            self.provider_protocol, self.model, self.model_digest = selected, study.MODEL, study.MODEL_DIGEST
            self.prepared = self.closed = 0
            providers.append(self)

        async def prepare(self):
            self.prepared += 1

        async def close(self):
            self.closed += 1

        def evidence_metadata(self):
            return {"native_contract_hash": study.CONTRACT_HASHES[self.provider_protocol],
                    **study.module_hashes(self.provider_protocol)}

    async def mock_rollout(config, index, provider):
        assert index == 0 and config.evaluation_only and not config.allow_paid
        assert (config.max_steps, config.timeout_seconds, config.concurrency) == (20, 35, 1)
        calls.append((config.seed, provider.provider_protocol))
        return fake_episode(config, provider)

    source = {"git_revision": REVISION, "source_dirty": False, "checkout_dirty": True,
              "files_sha256": {"mock-source": "b" * 64}}
    monkeypatch.setattr(study, "plan", lambda: copy.deepcopy(fixed_plan))
    monkeypatch.setattr(study, "source_identity", lambda revision: copy.deepcopy(source))
    monkeypatch.setattr(study, "make_provider", MockProvider)
    monkeypatch.setattr(study, "rollout", mock_rollout)
    # The engine separately tests semantic replay. Here replay is a controlled boundary.
    monkeypatch.setattr(study, "replay", lambda episode: {"verified": True})
    return {"providers": providers, "calls": calls, "rollout": mock_rollout, "source": source}


def collect(tmp_path):
    output = tmp_path / "fresh"
    return output, asyncio.run(study.collect(output, REVISION))


def raw_records(output):
    return [json.loads(line) for line in (output / "evaluation-episodes.jsonl").read_text().splitlines()]


def test_plan_has_locked_contracts_balanced_order_and_no_provider_activity(monkeypatch, fixed_plan, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("plan attempted collection activity")

    monkeypatch.setattr(study, "make_provider", forbidden)
    monkeypatch.setattr(study, "source_identity", forbidden)
    assert study.main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert canonical_json(result) == canonical_json(fixed_plan)
    assert digest(study.protocol()) == study.PROTOCOL_SHA256
    assert [slot["protocol"] for slot in study.slots()] == list(study.PROTOCOLS + study.PROTOCOLS[::-1]) * 4
    assert result["reservation_bound"]["derived_upper_bytes"] < study.EPISODE_RESERVE
    assert all(digest(study.contract(p)) == study.CONTRACT_HASHES[p] for p in study.PROTOCOLS)


@pytest.mark.parametrize("args", [["--output", "x"], ["--source-revision", REVISION], ["--collect"],
                                 ["--collect", "--output", "x"],
                                 ["--collect", "--output", "x", "--source-revision", "short"],
                                 ["--collect", "--output", "x", "--source-revision", "A" * 40],
                                 ["--plan", "--collect"]])
def test_cli_rejects_bad_flags_before_collection(monkeypatch, args):
    monkeypatch.setattr(study, "collect", lambda *args: pytest.fail("invalid flags reached collection"))
    with pytest.raises(SystemExit) as error:
        study.main(args)
    assert error.value.code == 2


@pytest.mark.parametrize("kind", ["file", "directory", "live_symlink", "dangling_symlink"])
def test_existing_output_refused_before_source_or_provider(tmp_path, monkeypatch, kind):
    output = tmp_path / "existing"
    if kind == "file":
        output.write_text("old receipt")
    elif kind == "directory":
        output.mkdir()
        (output / "old.json").write_text("old receipt")
    else:
        target = tmp_path / "target"
        if kind == "live_symlink":
            target.mkdir()
        output.symlink_to(target)
    monkeypatch.setattr(study, "source_identity", lambda *args: pytest.fail("existing path reached source"))
    monkeypatch.setattr(study, "make_provider", lambda *args: pytest.fail("existing path reached provider"))
    with pytest.raises(FileExistsError):
        asyncio.run(study.collect(output, REVISION))
    assert output.is_symlink() if "symlink" in kind else output.exists()


def test_happy_order_raw_accounting_pairs_and_cleanup(tmp_path, harness):
    output, result = collect(tmp_path)
    assert result["status"] == "completed" and result["comparison_approved"]
    assert harness["calls"] == [(slot["seed"], slot["protocol"]) for slot in study.slots()]
    assert (result["attempted_episodes"], result["verified_episodes"], result["unattempted_episodes"]) == (16, 16, 0)
    assert all(provider.prepared == provider.closed == 1 for provider in harness["providers"])
    assert len(raw_records(output)) == 16
    assert result["counters"]["model_request_attempts_observed"] == 32
    assert result["counters"]["model_request_attempts_complete"]
    assert result["counters"]["output_tokens_known"] == 160 and result["counters"]["output_tokens_complete"]
    assert result["counters"]["input_tokens_known"] == 280 and not result["counters"]["input_tokens_complete"]
    assert result["counters"]["inference_ns_known"] == 16000 and not result["counters"]["inference_ns_complete"]
    assert result["setup"]["metadata_http_requests"] is None
    assert not result["setup"]["metadata_http_requests_complete"]
    paired = result["analysis"]["paired"]
    assert paired["eligible_pairs"] == 8
    assert paired["business"]["cells"] == dict(both_pass=2, v1_only=2, v2_only=2, neither_pass=2)
    assert paired["business"]["v2_minus_v1_pass_fraction"] == 0
    assert paired["clean"]["cells"] == dict(both_pass=1, v1_only=2, v2_only=3, neither_pass=2)
    assert paired["clean"]["v2_minus_v1_pass_fraction"] == 1/8
    assert result["artifact_total_bytes"] == study.artifact_bytes(output) < study.ARTIFACT_CAP
    assert canonical_json(json.loads((output / "report.json").read_text())) == canonical_json(result)


def test_raw_fsynced_before_validation(tmp_path, harness, monkeypatch):
    original = study.check_episode
    original_fsync = study.os.fsync
    synced = []

    def fsync(descriptor):
        original_fsync(descriptor)
        synced.append(descriptor)

    def check(episode, slot, source, evidence):
        output = tmp_path / "fresh"
        assert raw_records(output)[-1]["episode"] == episode
        assert len(synced) == slot["index"]+1
        return original(episode, slot, source, evidence)

    monkeypatch.setattr(study.os, "fsync", fsync)
    monkeypatch.setattr(study, "check_episode", check)
    assert collect(tmp_path)[1]["verified_episodes"] == 16


@pytest.mark.parametrize("failure", ["prepare", "digest", "contract", "prepare_timeout"])
def test_prepare_failure_before_chat_closes_all_constructed_pools(tmp_path, harness, monkeypatch, failure):
    original = study.make_provider

    def factory(selected):
        provider = original(selected)
        if selected == study.LEDGER_PROTOCOL:
            if failure in {"prepare", "prepare_timeout"}:
                async def prepare():
                    if failure == "prepare_timeout":
                        await asyncio.sleep(1)
                    raise RuntimeError("secret sentinel")
                provider.prepare = prepare
            elif failure == "digest":
                provider.model_digest = "wrong"
            else:
                provider.evidence_metadata = lambda: {"native_contract_hash": "wrong"}
        return provider

    monkeypatch.setattr(study, "make_provider", factory)
    if failure == "prepare_timeout":
        monkeypatch.setattr(study, "SETUP_SECONDS", 0.01)
    output, result = collect(tmp_path)
    assert result["status"] == "stopped" and result["attempted_episodes"] == 0
    assert harness["calls"] == [] and raw_records(output) == []
    assert all(provider.closed == 1 for provider in harness["providers"])
    assert "secret sentinel" not in (output / "report.json").read_text()


@pytest.mark.parametrize("failure", ["raise", "timeout"])
def test_cleanup_failure_keeps_full_raw_and_honest_stop(tmp_path, harness, monkeypatch, failure):
    original = study.make_provider

    def factory(selected):
        provider = original(selected)
        if selected == study.PROTOCOL:
            async def close():
                provider.closed += 1
                if failure == "timeout":
                    await asyncio.sleep(1)
                raise RuntimeError("secret sentinel")
            provider.close = close
        return provider

    monkeypatch.setattr(study, "make_provider", factory)
    monkeypatch.setattr(study, "CLEANUP_SECONDS", 0.01)
    output, result = collect(tmp_path)
    assert result["status"] == "stopped" and not result["comparison_approved"]
    assert result["verified_episodes"] == len(raw_records(output)) == 16
    assert [p.closed for p in harness["providers"]] == [1, 1]
    assert result["cleanup"][0]["status"] == "failed"
    assert all(not record["resource_closure_attested"] for record in result["cleanup"])
    assert "secret sentinel" not in (output / "report.json").read_text()


@pytest.mark.parametrize("moment", ["third_slot", "cleanup"])
def test_source_change_stops_and_retains_prefix(tmp_path, harness, monkeypatch, moment):
    calls = 0

    def source(revision):
        nonlocal calls
        calls += 1
        value = copy.deepcopy(harness["source"])
        if (moment == "third_slot" and calls >= 4) or (moment == "cleanup" and calls >= 18):
            value["files_sha256"]["mock-source"] = "changed"
        return value

    monkeypatch.setattr(study, "source_identity", source)
    output, result = collect(tmp_path)
    expected = 2 if moment == "third_slot" else 16
    assert result["status"] == "stopped" and not result["comparison_approved"]
    assert result["verified_episodes"] == len(raw_records(output)) == expected
    assert result["unattempted_episodes"] == 16-expected


@pytest.mark.parametrize("failure", ["missing", "list", "nan", "opaque", "seed", "replay", "pair"])
def test_current_malformed_slot_inconclusive_not_prior_prefix(tmp_path, harness, monkeypatch, failure):
    class Opaque:
        def __repr__(self):
            return "secret sentinel"

    async def rollout(config, index, provider):
        episode = await harness["rollout"](config, index, provider)
        if len(harness["calls"]) == 2:
            if failure == "missing":
                del episode["steps"]
            elif failure == "list":
                episode = ["malformed"]
            elif failure == "nan":
                episode["reward"] = float("nan")
            elif failure == "opaque":
                episode["opaque"] = Opaque()
            elif failure == "seed":
                episode["seed"] = 7
            elif failure == "pair":
                episode["scenario_id"] = "different-case"
        return episode

    monkeypatch.setattr(study, "rollout", rollout)
    if failure == "replay":
        def replay(episode):
            if episode["provenance"]["provider_protocol"] == study.LEDGER_PROTOCOL:
                raise ValueError("secret sentinel")
            return {"verified": True}
        monkeypatch.setattr(study, "replay", replay)
    output, result = collect(tmp_path)
    records = raw_records(output)
    assert result["status"] == "stopped" and result["verified_episodes"] == 1
    assert result["attempted_episodes"] == 2 and result["unattempted_episodes"] == 14
    assert result["rows"][0]["outcome_integrity"] and not result["rows"][1]["outcome_integrity"]
    assert not result["rows"][1]["primary_eligible"] and not result["rows"][1]["passed"]
    assert result["analysis"]["paired"]["eligible_pairs"] == 0
    assert len(records) == 2 and records[0]["exact_envelope_preserved"]
    if failure in {"nan", "opaque"}:
        assert records[1]["episode"] is None and not records[1]["exact_envelope_preserved"]
        assert result["diagnostic_envelopes"] == 1 and result["finalized_envelopes"] == 1
    else:
        assert records[1]["episode"] is not None and records[1]["exact_envelope_preserved"]
    assert "secret sentinel" not in (output / "report.json").read_text()
    assert "secret sentinel" not in (output / "evaluation-episodes.jsonl").read_text()


def test_cancelled_episode_replayed_but_pair_censored(tmp_path, harness, monkeypatch):
    async def rollout(config, index, provider):
        episode = await harness["rollout"](config, index, provider)
        if len(harness["calls"]) == 2:
            episode.update(status="cancelled", termination="cancelled", passed=False, reward=0.0)
        return episode

    monkeypatch.setattr(study, "rollout", rollout)
    output, result = collect(tmp_path)
    assert result["verified_episodes"] == 2 and result["inconclusive_episodes"] == 0
    assert len(raw_records(output)) == 2 and result["unattempted_episodes"] == 14
    row = result["rows"][1]
    assert row["replay_verified"] and not row["primary_eligible"]
    paired = result["analysis"]["paired"]
    assert paired["eligible_pairs"] == 0 and paired["business"]["v2_minus_v1_pass_fraction"] is None
    assert paired["incomplete_pairs"][0]["reasons"][study.LEDGER_PROTOCOL] == "cancelled"


@pytest.mark.parametrize("cancel", [False, True])
def test_attempt_without_returned_episode_unknown_accounting_and_safe_marker(tmp_path, harness, monkeypatch, cancel):
    async def rollout(config, index, provider):
        if len(harness["calls"]) == 1:
            raise asyncio.CancelledError if cancel else RuntimeError("secret sentinel")
        return await harness["rollout"](config, index, provider)

    monkeypatch.setattr(study, "rollout", rollout)
    output, result = collect(tmp_path)
    assert result["attempted_episodes"] == 2 and result["verified_episodes"] == 1
    assert result["returned_envelopes"] == result["finalized_envelopes"] == 1
    assert result["diagnostic_envelopes"] == 1
    assert result["counters"]["model_request_attempts_observed"] == 2
    assert not result["counters"]["model_request_attempts_complete"]
    assert not result["rows"][1]["counters_complete"]
    assert raw_records(output)[1]["episode"] is None
    assert not raw_records(output)[1]["exact_envelope_preserved"]
    assert "secret sentinel" not in (output / "evaluation-episodes.jsonl").read_text()
    assert all(provider.closed == 1 for provider in harness["providers"])


@pytest.mark.parametrize("bound", ["artifact", "requests", "time"])
def test_next_episode_reservation_stops_before_chat(tmp_path, harness, monkeypatch, bound):
    if bound == "artifact":
        monkeypatch.setattr(study, "EPISODE_RESERVE", study.ARTIFACT_CAP)
    elif bound == "requests":
        monkeypatch.setattr(study, "MAX_REQUESTS", 19)
    else:
        monkeypatch.setattr(study, "OVERALL_SECONDS", 64)
    output, result = collect(tmp_path)
    assert result["status"] == "stopped" and result["attempted_episodes"] == 0
    assert raw_records(output) == [] and harness["calls"] == []
    assert all(provider.closed == 1 for provider in harness["providers"])


def test_unexpected_large_envelope_retained_before_reservation_stop(tmp_path, harness, monkeypatch):
    monkeypatch.setattr(study, "EPISODE_RESERVE", 100)
    output, result = collect(tmp_path)
    assert result["status"] == "stopped" and result["attempted_episodes"] == 1
    assert raw_records(output)[0]["episode"] is not None
    assert result["rows"][0]["exact_envelope_preserved"] and not result["rows"][0]["within_reservation"]
    assert result["verified_episodes"] == 0


def test_oversize_raw_preserves_generic_marker_not_success(tmp_path, harness, monkeypatch):
    monkeypatch.setattr(study, "EPISODE_RESERVE", 1024)
    monkeypatch.setattr(study, "ARTIFACT_CAP", study.REPORT_RESERVE+2000)
    output, result = collect(tmp_path)
    assert result["attempted_episodes"] == 1 and result["verified_episodes"] == 0
    assert not raw_records(output)[0]["exact_envelope_preserved"]
    assert raw_records(output)[0]["episode"] is None
    assert result["artifact_total_bytes"] <= study.ARTIFACT_CAP


def test_source_scope_and_clean_gate_without_git_activity(tmp_path, monkeypatch):
    for name in ("src/world_engine/module.py", *study.SOURCE_SCOPE[1:]):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("source\n")
    monkeypatch.setattr(study, "ROOT", tmp_path)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        class Result:
            stdout = REVISION if command[1] == "rev-parse" else ""
        return Result()

    monkeypatch.setattr(study.subprocess, "run", run)
    source = study.source_identity(REVISION)
    assert not source["source_dirty"] and len(source["files_sha256"]) == 6
    assert "tests/test_access_ledger_study.py" in source["files_sha256"]
    assert calls[1][-len(study.SOURCE_SCOPE):] == study.SOURCE_SCOPE

    def dirty(command, **kwargs):
        class Result:
            stdout = REVISION if command[1] == "rev-parse" else " M src/world_engine/module.py"
        return Result()

    monkeypatch.setattr(study.subprocess, "run", dirty)
    with pytest.raises(study.StudyStopped, match="committed and clean"):
        study.source_identity(REVISION)


def test_report_exclusive_and_bounded(tmp_path, monkeypatch):
    output = tmp_path / "report"
    output.mkdir()
    study.write_report(output, {"mock": True})
    original = (output / "report.json").read_bytes()
    with pytest.raises(FileExistsError):
        study.write_report(output, {"mock": False})
    assert (output / "report.json").read_bytes() == original
    monkeypatch.setattr(study, "REPORT_RESERVE", 10)
    with pytest.raises(study.StudyStopped, match="reserved cap"):
        study.write_report(output, {"big": "x" * 100})


def test_locked_plan_rejects_contract_or_fixture_drift(monkeypatch):
    with monkeypatch.context() as context:
        context.setattr(study, "contract", lambda selected: {"different": True})
        with pytest.raises(study.StudyStopped, match="locked review"):
            study.plan()
    with monkeypatch.context() as context:
        context.setattr(study, "world_fingerprints", lambda world: ("different", "different"))
        with pytest.raises(study.StudyStopped, match="locked fingerprints"):
            study.plan()


def test_provider_constructor_uses_explicit_episode_limits_without_contact(monkeypatch):
    captured = []
    monkeypatch.setattr(study, "OllamaToolsProvider", lambda config, **kwargs: captured.append((config, kwargs)))
    for selected in study.PROTOCOLS:
        study.make_provider(selected)
    assert len(captured) == 2
    for selected, (config, kwargs) in zip(study.PROTOCOLS, captured, strict=True):
        assert (config.episodes, config.concurrency, config.max_steps, config.timeout_seconds) == (1, 1, 20, 35)
        assert config.evaluation_only and not config.allow_paid
        assert kwargs == {"protocol": selected}
@pytest.mark.parametrize("moment", ["request_count", "provider_identity"])
def test_request_cap_or_prepared_identity_change_retains_evidence(tmp_path, harness, monkeypatch, moment):
    async def rollout(config, index, provider):
        episode = await harness["rollout"](config, index, provider)
        if moment == "request_count":
            events = []
            for decision in range(21):
                pair = copy.deepcopy(episode["provider_events"][:2])
                for event in pair:
                    event.update(call_id=f"too-many-{decision}", decision_index=decision)
                events.extend(pair)
            episode["provider_events"] = events
        else:
            harness["providers"][1].model_digest = "changed"
        return episode

    monkeypatch.setattr(study, "rollout", rollout)
    output, result = collect(tmp_path)
    assert result["status"] == "stopped" and result["attempted_episodes"] == 1
    assert len(raw_records(output)) == 1
    assert result["unattempted_episodes"] == 15
    assert result["verified_episodes"] == (0 if moment == "request_count" else 1)
