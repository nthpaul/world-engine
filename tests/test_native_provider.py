import asyncio
import base64
import copy
import gzip
import importlib.util
import json
import os
from itertools import product
from pathlib import Path

import httpx
import pytest

from world_engine import make_environment, provider_records
from world_engine.atif import HARBOR_SCHEMA_SHA256, export_episode
from world_engine.exports import export_records
from world_engine.models import RunConfig, canonical_json, digest
from world_engine.ollama_tools import PROTOCOL, OllamaToolsProvider, request_body
from world_engine.providers import ProviderError, ScriptedProvider
from world_engine.rollout import replay, rollout
from world_engine.store import Store

FIXTURE_DIGEST = "a" * 64


class RawBody(httpx.AsyncByteStream):
    def __init__(self, body):
        self.body = body

    async def __aiter__(self):
        yield self.body


def response(tool="finish", args=None, **extra):
    return {"model": "qwen3:8b", "done": True, "done_reason": "stop",
            "message": {"role": "assistant", "content": "", "tool_calls": [
                {"id": "reported-call-id", "function": {"index": 0, "name": tool, "arguments": args or {}}}]}, **extra}


async def prepared(config, reply, *, tags=None, shown=None, version="fixture-ollama"):
    requests = []

    async def respond(request):
        requests.append(request)
        if request.url.path == "/api/tags":
            body = tags or {"models": [{"name": "qwen3:8b", "digest": FIXTURE_DIGEST}]}
            return httpx.Response(200, stream=RawBody(json.dumps(body).encode()))
        if request.url.path == "/api/show":
            return httpx.Response(200, stream=RawBody(json.dumps(shown or {"capabilities": ["tools", "completion"]}).encode()))
        if request.url.path == "/api/version":
            return httpx.Response(200, stream=RawBody(json.dumps({"version": version}).encode()))
        if callable(reply):
            result = await reply(request)
        else:
            result = httpx.Response(200, json=reply)
        if result.is_stream_consumed:
            result = httpx.Response(result.status_code, headers=result.headers, stream=RawBody(result.content))
        return result

    provider = OllamaToolsProvider(config)
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        await provider.prepare()
    except BaseException:
        await provider.close()
        raise
    return provider, requests


async def native_episode(reply=None, **config_fields):
    config = RunConfig(environment_id="crm-merge", seed=730, provider_id="local", **config_fields)
    provider, requests = await prepared(config, reply if reply is not None else response())
    try:
        episode = await rollout(config, 0, provider)
    finally:
        await provider.close()
    return episode, requests


async def test_exact_request_response_ids_and_reported_usage():
    data = response(prompt_eval_count=0, eval_count=7, created_at="vendor-reported-time")
    episode, requests = await native_episode(data, evaluation_only=True)
    assert replay(episode)["verified"]
    start, end = episode["provider_events"]
    assert requests[-1].content == start["request_body"].encode()
    assert requests[-1].headers["content-type"] == "application/json"
    assert json.loads(provider_records.response_bytes(end)) == data
    assert end["complete"] and end["body_complete"] and end["outcome"] == "accepted"
    assert end["usage"] == {"model": "qwen3:8b", "input_tokens": 0, "output_tokens": 7}
    assert episode["usage"]["request_attempts"] == 1 and episode["usage"]["input_tokens"] == 0
    assert "127.0.0.1" not in canonical_json(episode["provider_events"])
    assert all("headers" not in event and "endpoint" not in event for event in episode["provider_events"])
    assert episode["provenance"]["provider_protocol"] == PROTOCOL
    assert episode["provenance"]["training_eligible"] is False
    assert episode["provenance"]["model_digest"] == FIXTURE_DIGEST
    assert episode["provenance"]["provider_evidence"]["ollama_version"] == "fixture-ollama"
    body = json.loads(start["request_body"])
    assert len(body["messages"]) == 2 and body["think"] is False and "format" not in body
    assert body == request_body("qwen3:8b", episode["initial_observation"], [])
    assert "initial_snapshot" not in start["request_body"] and "grader" not in start["request_body"]
    assert len(body["tools"]) == len(episode["initial_observation"]["tools"])


async def test_missing_id_and_unknown_usage_are_not_invented():
    data = response()
    del data["message"]["tool_calls"][0]["id"]
    episode, _ = await native_episode(data)
    assert replay(episode)["verified"]
    assert "input_tokens" not in episode["usage"] and "output_tokens" not in episode["usage"]
    assert episode["usage"]["input_tokens_complete"] is False
    assert "id" not in json.loads(provider_records.response_bytes(episode["provider_events"][1]))["message"]["tool_calls"][0]
    document = export_episode(episode)
    assert "metrics" not in document["steps"][-1]
    assert "total_prompt_tokens" not in document["final_metrics"]
    assert document["extra"]["world_engine"]["provider_events"] == episode["provider_events"]
    assert document["extra"]["training_eligible"] is False


@pytest.mark.parametrize(("version", "expected"), [
    ("v" * 80, "v" * 80),
    ("v" * 60_000, None),
    ("daemon\ncontrol", None),
    ("daemon\x7fcontrol", None),
    ("", None),
    (None, None),
    (17, None),
], ids=["bounded", "oversized", "newline", "control", "empty", "missing", "nonstring"])
async def test_daemon_version_metadata_is_bounded_printable_or_unknown(version, expected):
    config = RunConfig(environment_id="crm-merge", provider_id="local")
    provider, requests = await prepared(config, response(), version=version)
    try:
        assert provider.daemon_version == expected
        assert provider.evidence_metadata()["ollama_version"] == expected
        assert all(request.url.path != "/api/chat" for request in requests)
    finally:
        await provider.close()


@pytest.mark.parametrize("value", [None, -1, True, 1.5, 2**63])
async def test_invalid_or_missing_usage_remains_unknown(value):
    episode, _ = await native_episode(response(prompt_eval_count=value, eval_count=3))
    assert "input_tokens" not in episode["trace"][0]["usage"]
    assert "input_tokens" not in episode["usage"] and not episode["usage"]["input_tokens_complete"]
    assert episode["usage"]["output_tokens"] == 3
    assert replay(episode)["verified"]


@pytest.mark.parametrize("name", ["x" * 201, "model\ncontrol", "model\x7fcontrol"])
async def test_out_of_bound_model_metadata_is_only_retained_raw(name):
    episode, _ = await native_episode(response(model=name))
    assert "model" not in episode["trace"][0]["usage"]
    assert json.loads(provider_records.response_bytes(episode["provider_events"][1]))["model"] == name
    assert replay(episode)["verified"]


async def test_near_episode_cap_malicious_metadata_keeps_pairs_and_stops_next_chat():
    data = response("inspect", model="x" * 60_000, prompt_eval_count=2**1024,
                    eval_count=2**1024, total_duration=2**1024)
    episode, requests = await native_episode(data, max_steps=100)
    count = len([request for request in requests if request.url.path == "/api/chat"])
    assert 50 < count < 100 and episode["steps"] == count
    assert episode["termination"] == "provider_error" and "evidence budget" in episode["error"]
    assert len(episode["provider_events"]) == 2 * count
    assert provider_records.recorded_bytes(episode["provider_events"]) <= provider_records.MAX_EPISODE_RECORD_BYTES
    assert provider_records.MAX_EPISODE_RECORD_BYTES - provider_records.recorded_bytes(episode["provider_events"]) < 2 * provider_records.MAX_FINISH_BYTES
    for end in episode["provider_events"][1::2]:
        assert end["outcome"] == "accepted" and end["body_complete"]
        assert end["usage"] == {} and json.loads(provider_records.response_bytes(end)) == data
    assert "input_tokens" not in episode["usage"] and episode["usage"]["request_attempts"] == count
    assert replay(episode)["verified"]


async def test_maximum_printable_unicode_and_counts_fit_outcome_reservation():
    data = response(model="\U0001f600" * 200, prompt_eval_count=2**63 - 1,
                    eval_count=2**63 - 1, total_duration=2**63 - 1, padding="")
    data["padding"] = "x" * (provider_records.MAX_RESPONSE_BYTES - len(canonical_json(data).encode()))
    body = canonical_json(data).encode()
    assert len(body) == provider_records.MAX_RESPONSE_BYTES

    async def reply(request):
        return httpx.Response(200, stream=RawBody(body))

    episode, _ = await native_episode(reply)
    end = episode["provider_events"][1]
    assert len(canonical_json(end).encode()) <= provider_records.MAX_FINISH_BYTES
    assert end["usage"]["model"] == data["model"]
    assert end["usage"]["input_tokens"] == 2**63 - 1
    assert end["complete"] and replay(episode)["verified"]


async def test_native_contract_and_export_copies_do_not_share_mutable_state():
    episode, _ = await native_episode(response())
    original = copy.deepcopy(episode)
    document = export_episode(episode)
    document["extra"]["world_engine"]["provider_events"][0]["request_body"] = "mutated copy"
    document["extra"]["world_engine"]["provenance"]["provider_evidence"]["native_contract"]["options"]["num_predict"] = 1
    assert episode == original
    assert replay(episode)["verified"]
    assert "all recorded request-attempt usage" in document["final_metrics"]["extra"]["token_accounting_scope"]


@pytest.mark.parametrize(("data", "outcome"), [
    ({"done": True, "message": {"role": "assistant", "content": "I cannot comply"}}, "no_tool_call"),
    ({**response(), "done": False}, "truncated_response"),
    ({**response(), "done_reason": "length"}, "truncated_response"),
    ({**response(), "message": {"role": "assistant", "tool_calls": [
        {"function": {"name": "finish", "arguments": {}}},
        {"function": {"name": "inspect", "arguments": {}}}]}}, "multiple_tool_calls"),
    ({**response(), "message": {"role": "assistant", "tool_calls": [
        {"function": {"name": "finish", "arguments": "{}"}}]}}, "invalid_response"),
    ({**response(), "message": {"role": "user", "tool_calls": []}}, "invalid_response"),
])
async def test_invalid_response_keeps_call_but_never_executes_prefix(data, outcome):
    episode, requests = await native_episode(data)
    assert episode["termination"] == "provider_error" and episode["steps"] == 0
    assert episode["reward"] == 0 and not episode["passed"]
    assert len([request for request in requests if request.url.path == "/api/chat"]) == 1
    end = episode["provider_events"][1]
    assert end["outcome"] == outcome and end["complete"] is False
    assert json.loads(provider_records.response_bytes(end)) == data
    assert replay(episode)["verified"]
    assert "I cannot comply" not in episode["error"]


@pytest.mark.parametrize("forged_outcome", ["invalid_response", "no_tool_call", "multiple_tool_calls"])
async def test_replay_checks_complete_json_null_rejection_reason(forged_outcome):
    async def reply(request):
        return httpx.Response(200, stream=RawBody(b"null"))

    episode, _ = await native_episode(reply)
    end = episode["provider_events"][1]
    assert end["outcome"] == "truncated_response" and end["body_complete"]
    assert episode["steps"] == 0 and replay(episode)["verified"]
    end["outcome"] = forged_outcome
    with pytest.raises(ValueError, match="protocol failure is mislabeled"):
        replay(episode)


async def test_unknown_tool_is_an_environment_invalid_action():
    episode, _ = await native_episode(response("unknown_tool"), max_steps=1)
    assert episode["steps"] == 1 and episode["invalid_actions"] == 1
    assert episode["termination"] == "max_steps"
    assert episode["provider_events"][1]["outcome"] == "accepted"
    assert replay(episode)["verified"]


@pytest.mark.parametrize(("content", "status", "outcome"), [
    (b"not JSON", 200, "invalid_response"),
    (b"private raw error fixture", 403, "http_error"),
    (b"x" * (provider_records.MAX_RESPONSE_BYTES + 1), 200, "oversized_response"),
])
async def test_bounded_invalid_bytes_and_http_errors(content, status, outcome):
    async def reply(request):
        return httpx.Response(status, content=content)
    episode, _ = await native_episode(reply)
    end = episode["provider_events"][1]
    assert end["outcome"] == outcome and not end["complete"]
    assert provider_records.response_bytes(end) == content[:provider_records.MAX_RESPONSE_BYTES]
    assert end["body_complete"] is (outcome != "oversized_response")
    assert "private raw error fixture" not in episode["error"]
    assert replay(episode)["verified"]


async def test_compressed_body_is_recorded_raw_and_never_parsed():
    compressed = gzip.compress(canonical_json(response()).encode())

    async def reply(request):
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(200, headers={"content-encoding": "gzip"}, stream=RawBody(compressed))

    episode, _ = await native_episode(reply)
    end = episode["provider_events"][1]
    assert end["outcome"] == "unsupported_encoding" and end["body_complete"] and not end["complete"]
    assert end["content_encoding"] == "gzip" and end["usage"] == {}
    assert provider_records.response_bytes(end) == compressed
    assert episode["steps"] == 0 and replay(episode)["verified"]


async def test_episode_evidence_reservation_rejects_before_unpaired_start(monkeypatch):
    observation = make_environment("crm-merge", 730).observe()
    approximate_start = {"schema": provider_records.RECORD_SCHEMA, "protocol": PROTOCOL,
                         "call_id": "x" * 36, "decision_index": 0, "event": "request_started", "observed_at": "x" * 32,
                         "request_body": canonical_json(request_body("qwen3:8b", observation, [])), "request_bytes": 0,
                         "request_sha256": "x" * 64}
    budget = provider_records.MAX_FINISH_BYTES + len(canonical_json(approximate_start).encode()) + 2048
    monkeypatch.setattr(provider_records, "MAX_EPISODE_RECORD_BYTES", budget)
    episode, requests = await native_episode(response("inspect"), max_steps=20)
    assert episode["termination"] == "provider_error" and "evidence budget" in episode["error"]
    assert episode["steps"] == 1 and len(episode["provider_events"]) == 2
    assert len([request for request in requests if request.url.path == "/api/chat"]) == 1
    assert provider_records.recorded_bytes(episode["provider_events"]) <= budget
    assert replay(episode)["verified"]


@pytest.mark.parametrize(("error_class", "outcome"), [(httpx.ConnectError, "connection_error"), (httpx.ReadTimeout, "timeout")])
async def test_transport_errors_retain_unknown_usage(error_class, outcome):
    async def reply(request):
        raise error_class("SYNTHETIC-CONNECTION-DETAIL-PRIVATE")
    episode, _ = await native_episode(reply)
    assert episode["provider_events"][1]["outcome"] == outcome
    assert episode["usage"]["request_attempts"] == 1
    assert "input_tokens" not in episode["usage"]
    assert "PRIVATE" not in episode["error"]
    assert replay(episode)["verified"]


@pytest.mark.parametrize("cancel", [False, True])
async def test_cancellation_and_episode_timeout_always_pair_events(cancel):
    entered = asyncio.Event()

    async def reply(request):
        entered.set()
        await asyncio.sleep(20)
        return httpx.Response(200, json=response())

    config = RunConfig(environment_id="crm-merge", provider_id="local", timeout_seconds=1)
    provider, _ = await prepared(config, reply)
    try:
        task = asyncio.create_task(rollout(config, 0, provider))
        await entered.wait()
        if cancel:
            task.cancel()
        episode = await task
    finally:
        await provider.close()
    assert episode["termination"] == ("cancelled" if cancel else "timeout")
    assert len(episode["provider_events"]) == 2
    assert episode["provider_events"][1]["outcome"] == "cancelled"
    assert not episode["provider_events"][1]["body_complete"]
    assert replay(episode)["verified"]
    assert provider_records.recording() is False


async def test_shared_provider_has_no_cross_episode_history_or_records():
    async def reply(request):
        payload = json.loads(json.loads(request.content)["messages"][1]["content"])
        await asyncio.sleep(0.001)
        return httpx.Response(200, json=response("inspect" if not payload["history"] else "finish"))
    config = RunConfig(environment_id="crm-merge", provider_id="local", seed=730)
    provider, requests = await prepared(config, reply)
    try:
        episodes = await asyncio.gather(*(rollout(config, index, provider) for index in range(3)))
    finally:
        await provider.close()
    all_ids = []
    for episode in episodes:
        assert episode["steps"] == 2 and replay(episode)["verified"]
        assert len(episode["provider_events"]) == 4
        all_ids.extend(event["call_id"] for event in episode["provider_events"][::2])
        first = json.loads(json.loads(episode["provider_events"][0]["request_body"])["messages"][1]["content"])
        assert first["history"] == [] and first["observation"] == episode["initial_observation"]
    assert len(set(all_ids)) == 6
    assert len([request for request in requests if request.url.path == "/api/chat"]) == 6


@pytest.mark.parametrize(("tags", "shown"), [
    ({"models": []}, None),
    ({"models": [{"name": "qwen3:8b", "digest": FIXTURE_DIGEST, "remote_host": "https://cloud.invalid"}]}, None),
    ({"models": [{"name": "qwen3:8b", "digest": FIXTURE_DIGEST, "remote_model": "remote"}]}, None),
    ({"models": [{"name": "qwen3:8b", "digest": "not-a-digest"}]}, None),
    (None, {"capabilities": ["completion"]}),
    (None, {"capabilities": "tools"}),
    (None, {"capabilities": ["tools"], "remote_host": "https://cloud.invalid"}),
])
async def test_catalog_and_cloud_rejected_before_chat(tags, shown):
    config = RunConfig(environment_id="crm-merge", provider_id="local")
    with pytest.raises(ProviderError):
        await prepared(config, response(), tags=tags, shown=shown)


async def test_request_limit_and_missing_recorder_prevent_transport():
    config = RunConfig(environment_id="crm-merge", provider_id="local")
    provider, requests = await prepared(config, response())
    observation = make_environment("crm-merge", 730).observe()
    try:
        with pytest.raises(ProviderError, match="rollout"):
            await provider.decide(observation, [])
        events, token = provider_records.begin_episode()
        try:
            observation["large_fixture"] = "x" * provider_records.MAX_REQUEST_BYTES
            with pytest.raises(ProviderError, match="no request sent"):
                await provider.decide(observation, [])
            assert events == []
        finally:
            provider_records.end_episode(token)
    finally:
        await provider.close()
    assert all(request.url.path != "/api/chat" for request in requests)


async def test_replay_rejects_native_record_and_eligibility_mutations():
    original, _ = await native_episode(response())
    mutations = [
        lambda ep: ep["provider_events"][0].update(request_sha256="0" * 64),
        lambda ep: ep["provider_events"][1].update(response_sha256="0" * 64),
        lambda ep: ep["provider_events"][1].update(call_id="not-paired"),
        lambda ep: ep["provider_events"][1].update(usage={"input_tokens": 5}),
        lambda ep: ep["provenance"].update(training_eligible=True),
        lambda ep: ep["provenance"].pop("provider_protocol"),
        lambda ep: ep["provenance"]["provider_evidence"].update(native_contract_hash="0" * 64),
    ]
    for mutate in mutations:
        episode = copy.deepcopy(original)
        mutate(episode)
        with pytest.raises(ValueError):
            replay(episode)
    episode = copy.deepcopy(original)
    start = episode["provider_events"][0]
    body = json.loads(start["request_body"])
    body["model"] = "forged-model"
    start["request_body"] = canonical_json(body)
    start["request_bytes"] = len(start["request_body"].encode())
    start["request_sha256"] = provider_records.byte_hash(start["request_body"].encode())
    with pytest.raises(ValueError, match="native request"):
        replay(episode)
    episode = copy.deepcopy(original)
    end = episode["provider_events"][1]
    body = canonical_json(response("inspect")).encode()
    end.update(response_body_b64=base64.b64encode(body).decode(), response_bytes=len(body), response_sha256=provider_records.byte_hash(body))
    with pytest.raises(ValueError, match="native response"):
        replay(episode)


async def test_native_training_exclusion_and_operator_exports(tmp_path):
    oracle = ScriptedProvider()

    async def reply(request):
        payload = json.loads(json.loads(request.content)["messages"][1]["content"])
        decision = await oracle.decide(payload["observation"], payload["history"])
        return httpx.Response(200, json=response(decision.action.tool, decision.action.args))

    native_success, _ = await native_episode(reply)
    native_failure, _ = await native_episode(response())
    assert native_success["passed"] and native_success["split"] == "train"
    assert not native_failure["passed"]
    store = Store(tmp_path / "test.db")
    config = RunConfig(environment_id="crm-merge", seed=730)
    for run_id, episode in (("native-success", native_success), ("native-failure", native_failure)):
        store.create_run(run_id, config)
        store.append_episode(run_id, episode)
        for format in ("sft", "dpo", "grpo"):
            records, report = export_records(store, run_id, format, "all")
            assert records == [] and report["excluded"]["unsupported_provider_protocol"] == 1
        records, _ = export_records(store, run_id, "traces", "all")
        assert records[0]["provider_events"] == episode["provider_events"]
        assert records[0]["training_eligible"] is False and "initial_snapshot" not in records[0]
        documents, _ = export_records(store, run_id, "atif", "all")
        assert documents[0]["extra"]["world_engine"]["provider_events"] == episode["provider_events"]
    scripted = await rollout(config, 0)
    store.create_run("json-success", config)
    store.append_episode("json-success", scripted)
    for format in ("dpo", "grpo"):
        records, report = export_records(store, "json-success", format, "all")
        assert records == [] and report["excluded"]["insufficient_alternatives"] == 1
    records, _ = export_records(store, "json-success", "sft", "all")
    assert len(records) == scripted["steps"]


def collector_module():
    path = Path(__file__).resolve().parents[1] / "examples/native_tool_benchmark.py"
    spec = importlib.util.spec_from_file_location("native_collector_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_collector_locks_plan_and_rejects_wrong_digest_before_chat(tmp_path, monkeypatch):
    collector = collector_module()
    assert len(collector.WORLDS) * len(collector.SEEDS) == collector.MAX_EPISODES == 6
    assert collector.MAX_STEPS == 20 and collector.EPISODE_TIMEOUT == 120 and collector.OVERALL_TIMEOUT == 900
    assert collector.MAX_ARTIFACT_BYTES == 64 * 1024 * 1024
    monkeypatch.setattr(collector, "source_identity", lambda revision: {"git_revision": revision, "source_dirty": False})
    config = RunConfig(environment_id="crm-merge", provider_id="local")
    provider, requests = await prepared(config, response())
    monkeypatch.setattr(collector, "OllamaToolsProvider", lambda config: provider)
    report = await collector.collect(tmp_path / "new-evidence", "authorized-fixture-revision")
    assert "digest differs" in report["fatal_error"]
    assert report["recorded_episodes"] == report["recorded_request_attempts"] == 0
    assert all(request.url.path != "/api/chat" for request in requests)
    with pytest.raises(FileExistsError):
        await collector.collect(tmp_path / "new-evidence", "authorized-fixture-revision")


async def test_collector_artifact_cap_prevents_next_episode_and_overwrite(tmp_path, monkeypatch):
    collector = collector_module()
    monkeypatch.setattr(collector, "source_identity", lambda revision: {"git_revision": revision, "source_dirty": False})
    monkeypatch.setattr(collector, "EXPECTED_MODEL_DIGEST", FIXTURE_DIGEST)
    monkeypatch.setattr(collector, "NEXT_EPISODE_RESERVE_BYTES", collector.MAX_ARTIFACT_BYTES)
    config = RunConfig(environment_id="crm-merge", provider_id="local")
    provider, requests = await prepared(config, response())
    monkeypatch.setattr(collector, "OllamaToolsProvider", lambda config: provider)
    output = tmp_path / "capped-evidence"
    report = await collector.collect(output, "authorized-fixture-revision")
    assert "artifact budget" in report["fatal_error"]
    assert report["recorded_request_attempts"] == 0 and report["recorded_episodes"] == 0
    assert all(request.url.path != "/api/chat" for request in requests)
    assert collector.artifact_bytes(output) <= collector.MAX_ARTIFACT_BYTES
    handle_path = tmp_path / "bounded-writer.txt"
    with handle_path.open("x") as handle:
        monkeypatch.setattr(collector, "MAX_ARTIFACT_BYTES", collector.artifact_bytes(output) + collector.REPORT_RESERVE_BYTES + 1)
        with pytest.raises(ValueError, match="artifact cap"):
            collector.write_bounded(handle, "too large", output)
    assert handle_path.read_bytes() == b""


async def test_collector_retains_every_failure_and_all_six_cases(tmp_path, monkeypatch):
    collector = collector_module()
    monkeypatch.setattr(collector, "source_identity", lambda revision: {"git_revision": revision, "source_dirty": False})
    monkeypatch.setattr(collector, "EXPECTED_MODEL_DIGEST", FIXTURE_DIGEST)
    config = RunConfig(environment_id="crm-merge", provider_id="local")
    provider, requests = await prepared(config, {"done": True, "message": {"role": "assistant", "content": "fixture no-call"}})
    monkeypatch.setattr(collector, "OllamaToolsProvider", lambda config: provider)
    output = tmp_path / "complete-evidence"
    report = await collector.collect(output, "authorized-fixture-revision")
    assert report["fatal_error"] is None and report["recorded_episodes"] == 6
    assert report["recorded_request_attempts"] == 6 and report["passes"] == 0
    assert len([request for request in requests if request.url.path == "/api/chat"]) == 6
    assert {(row["environment_id"], row["seed"]) for row in report["episodes"]} == set(product(collector.WORLDS, collector.SEEDS))
    saved = [json.loads(line) for line in (output / "evaluation-episodes.jsonl").read_text().splitlines()]
    assert len(saved) == 6 and all(row["episode"]["termination"] == "provider_error" for row in saved)
    assert all(row["evaluation_only"] is True and row["training_eligible"] is False for row in saved)
    assert all(replay(row["episode"])["verified"] for row in saved)
    assert len((output / "operator-traces.jsonl").read_text().splitlines()) == 6
    assert len((output / "atif.jsonl").read_text().splitlines()) == 6


async def test_actual_pinned_upstream_accepts_native_success_and_failure():
    if os.environ.get("WORLD_ENGINE_ATIF_VALIDATE_UPSTREAM") != "1":
        pytest.skip("Enable isolated pinned Harbor validation using docs/atif.md")
    from harbor.models.trajectories.trajectory import Trajectory
    assert digest(Trajectory.model_json_schema()) == HARBOR_SCHEMA_SHA256
    for data in (response(), {"done": True, "message": {"role": "assistant", "content": "fixture no-call"}}):
        episode, _ = await native_episode(data, evaluation_only=True)
        Trajectory.model_validate(export_episode(episode))
