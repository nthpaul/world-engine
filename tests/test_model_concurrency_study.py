"""Offline fabricated provider/rollout receipts; no daemon or model calls."""

import asyncio
import base64
import copy
import gzip
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from world_engine import provider_records
from world_engine.models import canonical_json, digest

PATH = Path(__file__).resolve().parents[1]/"examples/model_concurrency_study.py"
SPEC = importlib.util.spec_from_file_location("model_concurrency_study", PATH)
study = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(study)
REVISION = "a"*40


def fake_episode(config, batch):
    request = canonical_json({"mock": True, "seed": config.seed})
    response = b'{"mock":true}'
    identity = {"schema": provider_records.RECORD_SCHEMA, "protocol": study.PROTOCOL,
                "call_id": f"{batch}-{config.seed}", "decision_index": 0, "observed_at": "2026-10-10T00:00:00Z"}
    usage = {"output_tokens": 3}
    if config.seed != study.SEEDS[0]:
        usage["input_tokens"] = 7
    events = [
        {**identity, "event": "request_started", "request_body": request, "request_bytes": len(request),
         "request_sha256": provider_records.byte_hash(request.encode())},
        {**identity, "event": "request_finished", "response_body_b64": base64.b64encode(response).decode(),
         "response_bytes": len(response), "response_sha256": provider_records.byte_hash(response),
         "response_hash_scope": "complete-body", "body_complete": True, "complete": True, "outcome": "accepted",
         "http_status": 200, "elapsed_ms": 1.0, "usage": usage},
    ]
    passed = config.seed % 4 == 0 or (batch in (1, 2) and config.seed % 4 == 1)
    return {"seed": config.seed, "index": 0, "scenario_id": f"case-{config.seed}", "split": "test",
            "initial_observation": {"public": True, "seed": config.seed}, "passed": passed, "reward": float(passed),
            "status": "completed", "termination": "finished", "steps": 1, "invalid_actions": 0,
            "elapsed_seconds": .01, "usage": provider_records.usage_summary(events), "provider_events": events,
            "provenance": {"environment_id": study.WORLD, "environment_version": study.VERSION,
                           "environment_code_hash": study.ENVIRONMENT_HASH, "grader_code_hash": study.GRADER_HASH,
                           "grader_version": "1.0.0", "initial_state_hash": study.INITIAL_HASHES[config.seed-study.SEEDS[0]],
                           "task_hash": digest({"task": config.seed}), "prompt_hash": digest({"prompt": config.seed}),
                           "evaluation_only": True, "training_eligible": False, "git_revision": REVISION,
                           "implementation_dirty": False, "provider_protocol": study.PROTOCOL,
                           "model": study.MODEL, "model_digest": study.MODEL_DIGEST,
                           "policy_hash": "fixed-policy",
                           "provider_evidence": {"mock": True}}}


@pytest.fixture
def harness(monkeypatch):
    providers, calls, active = [], [], {"count": 0, "peaks": {}}
    fixed_plan = study.plan()

    class MockProvider:
        def __init__(self, budget):
            self.budget = budget
            self.batch = len(providers)
            self.model, self.model_digest, self.prepared = study.MODEL, study.MODEL_DIGEST, False
            self.closed = 0
            providers.append(self)

        async def prepare(self):
            self.prepared = True
            self.budget.metadata += 3

        async def close(self):
            self.closed += 1
            self.prepared = False

        def evidence_metadata(self):
            return {"mock": True}

    async def rollout(config, index, provider):
        assert index == 0 and config.evaluation_only and not config.allow_paid
        assert (config.max_steps, config.timeout_seconds) == (20, 35)
        calls.append((provider.batch, config.seed))
        active["count"] += 1
        active["peaks"][provider.batch] = max(active["peaks"].get(provider.batch, 0), active["count"])
        try:
            await asyncio.sleep(.001)
            provider.budget.chat += 1
            return fake_episode(config, provider.batch)
        finally:
            active["count"] -= 1

    monkeypatch.setattr(study, "source_identity", lambda revision: {"git_revision": REVISION, "files_sha256": {"mock": "b"*64}})
    monkeypatch.setattr(study, "plan", lambda: copy.deepcopy(fixed_plan))
    monkeypatch.setattr(study, "public_seed_overlap", lambda: [])
    monkeypatch.setattr(study, "make_provider", MockProvider)
    monkeypatch.setattr(study, "rollout", rollout)
    monkeypatch.setattr(study, "replay", lambda episode: {"verified": True})
    return {"providers": providers, "calls": calls, "active": active, "rollout": rollout}


def collect(tmp_path):
    output = tmp_path/"fresh"
    return output, asyncio.run(study.collect(output, REVISION))


def raw(output):
    return [json.loads(line) for line in (output/"evaluation-episodes.jsonl").read_text().splitlines()]


def test_pure_plan_fixed_order_and_contract(monkeypatch, capsys):
    def forbidden(*args):
        pytest.fail("plan reached collection side effect")
    for name in ("make_provider", "source_identity", "public_seed_overlap", "collect"):
        monkeypatch.setattr(study, name, forbidden)
    assert study.main([]) == 0
    p = json.loads(capsys.readouterr().out)
    assert p["protocol_sha256"] == study.PROTOCOL_SHA256 == digest(study.protocol())
    assert [s["concurrency"] for s in study.slots()] == [1]*8+[2]*16+[1]*8
    assert sum(p["reservation_components"].values()) < study.EPISODE_RESERVE


@pytest.mark.parametrize("args", [["--collect"], ["--output", "x"], ["--source-revision", REVISION],
                                 ["--collect", "--output", "x", "--source-revision", "A"*40], ["--plan", "--collect"]])
def test_invalid_cli_no_collection(monkeypatch, args):
    monkeypatch.setattr(study, "collect", lambda *a: pytest.fail("invalid flags collected"))
    with pytest.raises(SystemExit) as error:
        study.main(args)
    assert error.value.code == 2


@pytest.mark.parametrize("kind", ["file", "directory", "live", "dangling"])
def test_existing_output_never_touched(tmp_path, monkeypatch, kind):
    output = tmp_path/"existing"
    if kind == "file":
        output.write_text("keep")
    elif kind == "directory":
        output.mkdir()
    else:
        target = tmp_path/"target"
        if kind == "live":
            target.mkdir()
        output.symlink_to(target)
    monkeypatch.setattr(study, "source_identity", lambda *a: pytest.fail("existing output reached source"))
    with pytest.raises(FileExistsError):
        asyncio.run(study.collect(output, REVISION))


def test_complete_wave_order_metrics_counts_and_no_duplicates(tmp_path, harness):
    output, report = collect(tmp_path)
    assert report["status"] == "completed" and report["comparison_approved"]
    assert report["verified_episodes"] == report["attempted_episodes"] == 32
    assert report["inconclusive_episodes"] == report["unattempted_episodes"] == 0
    assert harness["calls"] == [(s["batch"], s["seed"]) for s in study.slots()]
    assert list(harness["active"]["peaks"].values()) == [1, 2, 2, 1]
    assert all(p.closed == 1 for p in harness["providers"])
    assert report["chat_requests_started"] == 32 and report["metadata_requests_started"] == 12
    assert len(raw(output)) == 32 and report["artifact_total_bytes"] == study.artifact_bytes(output)
    assert canonical_json(json.loads((output/"report.json").read_text())) == canonical_json(report)
    for round_ in report["analysis"]["rounds"]:
        assert round_["eligible_pairs"] == 8
        assert round_["business"]["cells"] == {"both_pass": 2, "one_only": 0, "two_only": 2, "neither": 4}
        assert round_["business"]["two_minus_one"] == .25
    assert not report["analysis"]["counters"]["input_tokens_complete"]
    assert report["analysis"]["counters"]["input_tokens_known"] == 196
    for batch in report["batches"]:
        assert batch["passes_per_second"] == batch["business_passes"]/batch["wall_seconds"]
        assert batch["episodes_per_second"] == 8/batch["wall_seconds"]


def test_full_wave_raw_fsynced_before_validation_or_next_admission(tmp_path, harness, monkeypatch):
    original_check, original_fsync = study.check_episode, study.os.fsync
    syncs = []
    def fsync(fd):
        original_fsync(fd)
        syncs.append(fd)
    def check(episode, slot, source, evidence):
        records = raw(tmp_path/"fresh")
        expected = slot["index"]+1 if slot["concurrency"] == 1 else (slot["index"]//2+1)*2
        assert len(records) == len(syncs) == expected
        assert any(r["episode"] == episode for r in records)
        return original_check(episode, slot, source, evidence)
    monkeypatch.setattr(study.os, "fsync", fsync)
    monkeypatch.setattr(study, "check_episode", check)
    assert collect(tmp_path)[1]["verified_episodes"] == 32


@pytest.mark.parametrize("index,field", [(0, "usage"), (1, "passed"), (8, "usage"), (9, "invalid_actions")])
def test_malformed_first_later_wave_preserves_prior_rows(tmp_path, harness, monkeypatch, index, field):
    async def malformed(config, i, provider):
        episode = await harness["rollout"](config, i, provider)
        if provider.batch*8+config.seed-study.SEEDS[0] == index:
            del episode[field]
        return episode
    monkeypatch.setattr(study, "rollout", malformed)
    output, report = collect(tmp_path)
    end = index+1 if index < 8 else 10
    assert len(raw(output)) == report["attempted_episodes"] == end
    assert report["inconclusive_episodes"] == 1 and report["verified_episodes"] == end-1
    assert report["rows"][index]["exact_envelope_preserved"] and not report["rows"][index]["verified"]
    assert all(r["verified"] for r in report["rows"] if r["index"] != index)
    assert report["status"] == "stopped" and report["unattempted_episodes"] == 32-end


def test_cleanup_failure_stops_next_batch_preserves_records(tmp_path, harness, monkeypatch):
    original = study.make_provider
    def make(budget):
        provider = original(budget)
        async def broken_close():
            provider.closed += 1
            raise RuntimeError("secret")
        provider.close = broken_close
        return provider
    monkeypatch.setattr(study, "make_provider", make)
    output, report = collect(tmp_path)
    assert report["status"] == "stopped" and len(raw(output)) == report["verified_episodes"] == 8
    assert "secret" not in canonical_json(report) and len(harness["providers"]) == 1


@pytest.mark.parametrize("phase", ["prepare", "after_wave"])
def test_source_drift_no_new_admission(tmp_path, harness, monkeypatch, phase):
    checks = 0
    def identity(revision):
        nonlocal checks
        checks += 1
        if (phase == "prepare" and checks == 1) or (phase == "after_wave" and checks == 3):
            raise study.StudyStopped("source drift")
        return {"git_revision": REVISION, "files_sha256": {"mock": "b"*64}}
    monkeypatch.setattr(study, "source_identity", identity)
    output, report = collect(tmp_path)
    assert report["attempted_episodes"] == (0 if phase == "prepare" else 1)
    assert report["status"] == "stopped" and len(raw(output)) == report["attempted_episodes"]


def test_model_mismatch_before_any_chat_still_closes(tmp_path, harness, monkeypatch):
    original = study.make_provider
    def make(budget):
        p = original(budget)
        p.model_digest = "b"*64
        return p
    monkeypatch.setattr(study, "make_provider", make)
    output, report = collect(tmp_path)
    assert report["attempted_episodes"] == report["chat_requests_started"] == 0
    assert harness["providers"][0].closed == 1 and raw(output) == []


def test_artifact_reservation_stops_before_provider_rollout(tmp_path, harness, monkeypatch):
    monkeypatch.setattr(study, "ARTIFACT_CAP", study.EPISODE_RESERVE)
    output, report = collect(tmp_path)
    assert report["status"] == "stopped" and report["attempted_episodes"] == 0 and raw(output) == []
    assert harness["providers"][0].closed == 1


def test_chat_reservation_stops_prefix_no_retry(tmp_path, harness, monkeypatch):
    monkeypatch.setattr(study, "MAX_REQUESTS", 20)
    output, report = collect(tmp_path)
    assert report["attempted_episodes"] == report["verified_episodes"] == 1 and len(raw(output)) == 1
    assert report["unattempted_episodes"] == 31


@pytest.mark.parametrize("bad", ["nan", "object", "exception"])
def test_unserializable_or_no_return_marker_redacts(tmp_path, harness, monkeypatch, bad):
    async def broken(config, index, provider):
        if bad == "exception":
            raise RuntimeError("secret")
        return {"secret": float("nan") if bad == "nan" else object()}
    monkeypatch.setattr(study, "rollout", broken)
    output, report = collect(tmp_path)
    assert report["inconclusive_episodes"] == 1 and report["attempted_episodes"] == 1
    assert raw(output)[0]["episode"] is None and not raw(output)[0]["exact_envelope_preserved"]
    assert "secret" not in (output/"evaluation-episodes.jsonl").read_text()+canonical_json(report)


@pytest.mark.parametrize("url,method,body", [
    ("http://evil.example:11434/api/chat", "POST", {}),
    ("http://127.0.0.1:9999/api/chat", "POST", {}),
    ("http://127.0.0.1:11434/api/pull", "POST", {"model": study.MODEL}),
    ("http://127.0.0.1:11434/api/show", "POST", {"model": "private"}),
])
async def test_request_hook_rejects_other_endpoints_without_send(url, method, body):
    budget = study.RequestBudget()
    with pytest.raises((study.ProviderError, study.StudyStopped)):
        await budget.hook(httpx.Request(method, url, json=body))
    assert budget.violation and budget.chat == 0


async def test_shared_hook_counts_metadata_and_chat_without_races(monkeypatch):
    budget = study.RequestBudget()
    await budget.hook(httpx.Request("GET", "http://127.0.0.1:11434/api/tags"))
    assert budget.metadata == 1
    budget.phase = "chat"
    body = {"model": study.MODEL, "options": study.contract()["options"], "stream": False, "think": False, "keep_alive": "5m"}
    monkeypatch.setattr(study, "MAX_REQUESTS", 2)
    await asyncio.gather(*(budget.hook(httpx.Request("POST", "http://127.0.0.1:11434/api/chat", json=body)) for _ in range(2)))
    with pytest.raises(study.ProviderError):
        await budget.hook(httpx.Request("POST", "http://127.0.0.1:11434/api/chat", json=body))
    assert budget.chat == 2


def test_overlap_structured_json_and_compressed_seed_not_substrings(tmp_path, monkeypatch):
    public = tmp_path/"artifacts"
    public.mkdir()
    (public/"manifest.json").write_text(json.dumps({"episodes": [{"seed": 53000, "world": study.WORLD}, {"seed": 53001, "world": "other"}],
                                                  "text": "seed53002"}))
    with gzip.open(public/"episodes.jsonl.gz", "wt") as handle:
        handle.write(json.dumps({"episode": {"seed": 53003}})+"\n")
    monkeypatch.setattr(study, "ROOT", tmp_path)
    assert {r["seed"] for r in study.public_seed_overlap()} == {53000, 53003}


def test_protocol_drift_blocks_plan(monkeypatch):
    monkeypatch.setattr(study, "CONCURRENCIES", (2, 1, 1, 2))
    with pytest.raises(study.StudyStopped, match="protocol"):
        study.plan()


def test_validation_time_is_in_continuous_batch_wall(tmp_path, harness, monkeypatch):
    original = study.check_episode
    def slow_check(*args):
        study.time.sleep(.002)
        return original(*args)
    monkeypatch.setattr(study, "check_episode", slow_check)
    _, report = collect(tmp_path)
    assert all(b["wall_seconds"] >= b["validation_seconds"] >= .016 for b in report["batches"])


async def test_interrupt_two_slot_wave_preserves_returned_peer_and_cleanup(tmp_path, harness, monkeypatch):
    wave_started = asyncio.Event()
    peer_finished = asyncio.Event()
    async def partial(config, index, provider):
        if provider.batch == 1 and config.seed == study.SEEDS[1]:
            wave_started.set()
            await asyncio.Event().wait()
        result = await harness["rollout"](config, index, provider)
        if provider.batch == 1:
            peer_finished.set()
        return result
    monkeypatch.setattr(study, "rollout", partial)
    output = tmp_path/"fresh"
    task = asyncio.create_task(study.collect(output, REVISION))
    await wave_started.wait()
    await peer_finished.wait()
    task.cancel()
    report = await task
    assert report["status"] == "stopped" and report["attempted_episodes"] == 10
    assert report["verified_episodes"] == report["exact_raw_values"] == 9
    assert report["diagnostic_markers"] == 1 and report["unattempted_episodes"] == 22
    assert raw(output)[8]["episode"] is not None and raw(output)[9]["episode"] is None
    assert [p.closed for p in harness["providers"]] == [1, 1]
    assert report["batches"][1]["peak_admitted"] == 2


def test_wave_reservation_requires_both_episodes(tmp_path, harness, monkeypatch):
    original_bytes = study.artifact_bytes
    def used(output):
        value = original_bytes(output)
        return value + (17*1024**2 if len(harness["calls"]) == 8 else 0)
    monkeypatch.setattr(study, "artifact_bytes", used)
    output, report = collect(tmp_path)
    assert report["verified_episodes"] == 8 and len(raw(output)) == 8
    assert report["stop_reason"] == "remaining artifact capacity cannot reserve whole wave"
    assert report["batches"][1]["peak_admitted"] == 0
    assert [p.closed for p in harness["providers"]] == [1, 1]


@pytest.mark.parametrize("fits", [True, False])
def test_unexpected_oversize_return_full_when_fits_else_marker(tmp_path, harness, monkeypatch, fits):
    # Smaller limits exercise the same admission/persistence branches without a huge fixture.
    monkeypatch.setattr(study, "EPISODE_RESERVE", 4096)
    monkeypatch.setattr(study, "REPORT_RESERVE", 32768)
    monkeypatch.setattr(study, "ARTIFACT_CAP", 200000 if fits else 40000)
    async def large(config, index, provider):
        episode = await harness["rollout"](config, index, provider)
        episode["extra_operator_evidence"] = "x"*16384
        return episode
    monkeypatch.setattr(study, "rollout", large)
    output, report = collect(tmp_path)
    record = raw(output)[0]
    assert report["status"] == "stopped" and report["attempted_episodes"] == 1
    assert record["exact_envelope_preserved"] is fits
    assert (record["episode"] is not None) is fits
    assert report["artifact_total_bytes"] <= study.ARTIFACT_CAP
    assert report["verified_episodes"] == int(fits)


def test_escaped_near_limit_reservation_serialization(tmp_path):
    # Each component is budgeted in serialized bytes, not decoded character count.
    def payload(limit):
        return "\x00"*((limit-2)//6)
    p = study.plan()
    trace = [{"policy_input": payload(132*1024), "observation": payload(384*1024),
              "action": payload(64*1024), "result": payload(64*1024), "metadata": payload(4*1024)}
             for _ in range(study.MAX_STEPS)]
    episode = {"provider_events": payload(8*1024**2), "trace": trace,
               "snapshots_and_metadata": payload(1024**2)}
    encoded = canonical_json(episode).encode()
    assert sum(p["reservation_components"].values()) < study.EPISODE_RESERVE
    assert len(encoded) < study.EPISODE_RESERVE
    output = tmp_path/"raw"
    output.mkdir()
    with (output/"evaluation-episodes.jsonl").open("xb") as handle:
        saved = study.append_raw(handle, study.slots()[0], episode, output, None)
    assert saved["within_reservation"] and saved["exact_envelope_preserved"]
    assert raw(output)[0]["episode"] == episode


@pytest.mark.parametrize("phase", ["prepare", "cleanup_timeout", "post_cleanup_model"])
def test_preparation_and_cleanup_failures_never_admit_next_batch(tmp_path, harness, monkeypatch, phase):
    original = study.make_provider
    def make(budget):
        provider = original(budget)
        if phase == "prepare":
            async def fail():
                raise RuntimeError("private setup detail")
            provider.prepare = fail
        elif phase == "cleanup_timeout":
            async def block():
                provider.closed += 1
                await asyncio.Event().wait()
            provider.close = block
        else:
            close = provider.close
            async def drift():
                await close()
                provider.model_digest = "b"*64
            provider.close = drift
        return provider
    monkeypatch.setattr(study, "make_provider", make)
    monkeypatch.setattr(study, "CLEANUP_SECONDS", .005)
    output, report = collect(tmp_path)
    expected = 0 if phase == "prepare" else 8
    assert report["status"] == "stopped" and report["verified_episodes"] == expected
    assert len(raw(output)) == expected and len(harness["providers"]) == 1
    assert harness["providers"][0].closed == 1
    assert "private setup detail" not in canonical_json(report)


def test_time_reservation_stops_before_rollout(tmp_path, harness, monkeypatch):
    monkeypatch.setattr(study, "OVERALL_SECONDS", study.SETUP_SECONDS+study.CLEANUP_SECONDS+study.FINAL_RESERVE)
    _, report = collect(tmp_path)
    assert report["attempted_episodes"] == 0 and not harness["providers"]
    assert report["unattempted_episodes"] == 32


def test_final_source_gate_prevents_completed_claim(tmp_path, harness, monkeypatch):
    calls = 0
    def identity(revision):
        nonlocal calls
        calls += 1
        return {"git_revision": REVISION, "files_sha256": {"mock": "c"*64 if calls == 30 else "b"*64}}
    # Initial + 24 wave gates + four cleanup gates + final gate = 30.
    monkeypatch.setattr(study, "source_identity", identity)
    _, report = collect(tmp_path)
    assert report["verified_episodes"] == 32 and report["status"] == "stopped"
    assert not report["source_post_valid"] and not report["comparison_approved"]


@pytest.mark.parametrize("bad", ["head", "dirty_scope", "short_revision"])
def test_source_revision_and_clean_scope_guards_without_git(tmp_path, monkeypatch, bad):
    root = tmp_path
    (root/"src/world_engine").mkdir(parents=True)
    (root/"src/world_engine/module.py").write_text("public = True\n")
    (root/"protocol.md").write_text("locked\n")
    monkeypatch.setattr(study, "ROOT", root)
    monkeypatch.setattr(study, "SOURCE_SCOPE", ["src/world_engine", "protocol.md"])
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        assert kwargs["cwd"] == root and kwargs["timeout"] == 3
        result = "b"*40 if bad == "head" else REVISION
        if command[1] == "status":
            result = " M protocol.md" if bad == "dirty_scope" and "--" in command else ""
        return SimpleNamespace(stdout=result)
    monkeypatch.setattr(study.subprocess, "run", run)
    with pytest.raises(study.StudyStopped):
        study.source_identity("short" if bad == "short_revision" else REVISION)
    assert bool(calls) is (bad != "short_revision")


def test_source_hashes_and_out_of_scope_dirty_flag(tmp_path, monkeypatch):
    (tmp_path/"src/world_engine").mkdir(parents=True)
    module = tmp_path/"src/world_engine/module.py"
    module.write_text("public = True\n")
    (tmp_path/"protocol.md").write_text("locked\n")
    monkeypatch.setattr(study, "ROOT", tmp_path)
    monkeypatch.setattr(study, "SOURCE_SCOPE", ["src/world_engine", "protocol.md"])
    def run(command, **kwargs):
        return SimpleNamespace(stdout=REVISION if command[1] == "rev-parse" else "" if "--" in command else "?? notes.md")
    monkeypatch.setattr(study.subprocess, "run", run)
    result = study.source_identity(REVISION)
    assert result["checkout_dirty"] and result["source_dirty"] is False
    assert result["files_sha256"]["src/world_engine/module.py"] == study.hashlib.sha256(module.read_bytes()).hexdigest()


async def test_real_httpx_mock_transport_hook_blocks_before_transport(monkeypatch):
    sent = []
    def handler(request):
        sent.append(request.url.path)
        return httpx.Response(200, json={"public": True})
    budget = study.RequestBudget()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), event_hooks={"request": [budget.hook]}) as client:
        await client.get("http://127.0.0.1:11434/api/tags")
        budget.phase = "chat"
        body = {"model": study.MODEL, "options": study.contract()["options"], "stream": False,
                "think": False, "keep_alive": "5m"}
        monkeypatch.setattr(study, "MAX_REQUESTS", 1)
        await client.post("http://127.0.0.1:11434/api/chat", json=body)
        with pytest.raises(study.ProviderError):
            await client.post("http://127.0.0.1:11434/api/chat", json=body)
    assert sent == ["/api/tags", "/api/chat"] and budget.chat == budget.metadata == 1


def test_identity_mismatch_and_unverified_pairs_not_eligible(tmp_path, harness):
    _, report = collect(tmp_path)
    rows = copy.deepcopy(report["rows"])
    rows[8]["identity"]["policy_hash"] = "another-policy"
    rows[9]["primary_eligible"] = False
    analysis = study.summarize(rows, copy.deepcopy(report["batches"]))
    assert analysis["rounds"][0]["eligible_pairs"] == 6
    assert analysis["unique_task_counts"][0]["two_minus_one_fraction"] is None
    assert analysis["unique_task_counts"][1]["two_minus_one_fraction"] is None


def test_write_failure_accounts_for_whole_admitted_wave_without_fake_markers(tmp_path, harness, monkeypatch):
    original = study.append_raw
    def failed_write(handle, slot, episode, output, error):
        if slot["index"] == 9:
            raise OSError("private disk detail")
        return original(handle, slot, episode, output, error)
    monkeypatch.setattr(study, "append_raw", failed_write)
    output, report = collect(tmp_path)
    assert report["status"] == "stopped" and report["attempted_episodes"] == report["returned_values"] == 10
    assert report["raw_records_preserved"] == report["exact_raw_values"] == len(raw(output)) == 9
    assert report["raw_persistence_failures"] == 1 and report["diagnostic_markers"] == 0
    assert report["verified_episodes"] == 8 and report["unattempted_episodes"] == 22
    assert "private disk detail" not in canonical_json(report)
    assert [p.closed for p in harness["providers"]] == [1, 1]
