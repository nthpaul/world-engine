import asyncio
import copy
import importlib.util
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from world_engine.models import digest

SPEC = importlib.util.spec_from_file_location("workflow_model_study", Path(__file__).parents[1] / "examples/workflow_model_study.py")
study = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(study)
REVISION = "a" * 40


class FakeProvider:
    def __init__(self, policy, events):
        self.policy, self.events = policy, events
        self.model_digest, self.model = study.MODEL_DIGEST, study.MODEL
        self.closed = False

    async def prepare(self):
        self.events.append(("prepare", self.policy))

    def evidence_metadata(self):
        return {"fixture": True, "model_digest": self.model_digest}

    async def close(self):
        self.closed = True
        self.events.append(("close", self.policy))


@pytest.fixture
def harness(monkeypatch, tmp_path):
    events, attempted = [], []
    pool = {policy: FakeProvider(policy, events) for policy in ("native", "json", "oracle", "baseline")}
    source = {"git_revision": REVISION, "files_sha256": {"fixture.py": "b" * 64}, "source_dirty": False}
    monkeypatch.setattr(study, "source_identity", lambda revision: copy.deepcopy(source))
    monkeypatch.setattr(study, "providers", lambda: pool)
    monkeypatch.setattr(study, "machine_metadata", lambda: {"platform": "mock-machine"})
    monkeypatch.setattr(study, "replay", lambda episode: {"verified": True})
    output = tmp_path / "receipt"
    fixture_plan = study.plan()

    async def fake_rollout(config, index, provider):
        # Collection must flush the preceding complete raw row before another attempt.
        raw = (output / "evaluation-episodes.jsonl").read_text().splitlines()
        assert len(raw) == len(attempted)
        assert events[:2] == [("prepare", "native"), ("prepare", "json")]
        slot = study.slots()[len(attempted)]
        assert (config.environment_id, config.seed, provider.policy) == (slot["world"], slot["seed"], slot["policy"])
        assert config.evaluation_only and not config.allow_paid
        assert (config.max_steps, config.timeout_seconds, config.concurrency) == (20, 35, 1)
        attempted.append(slot)
        events.append(("attempt", provider.policy))
        fixture = fixture_plan["fixtures"][slot["task_index"]]
        model = provider.policy in {"native", "json"}
        episode = {"seed": config.seed, "passed": provider.policy != "baseline", "reward": 1.0,
                   "status": "completed", "termination": "finished", "steps": 2,
                   "invalid_actions": 0, "elapsed_seconds": .1,
                   "usage": {"request_attempts": 1} if model else {},
                   "trace": [], "provenance": {"environment_id": config.environment_id,
                   "environment_version": study.VERSIONS[config.environment_id],
                   "environment_code_hash": fixture["environment_hash"], "grader_code_hash": fixture["grader_hash"],
                   "initial_state_hash": fixture["initial_state_hash"], "evaluation_only": True}}
        episode["provenance"].update(git_revision=REVISION, implementation_dirty=False)
        if model:
            episode["provenance"].update(provider_protocol=study.PROTOCOL if provider.policy == "native"
                                         else study.json_evidence_contract()["protocol"],
                                         model_digest=study.MODEL_DIGEST, training_eligible=False)
            episode["provider_events"] = [{"event": "request_started", "request_body": "fixture exact wire"},
                                          {"event": "request_finished", "outcome": "accepted", "response_body_b64": "e30="}]
        return episode

    monkeypatch.setattr(study, "rollout", fake_rollout)
    return SimpleNamespace(output=output, events=events, attempted=attempted, pool=pool, source=source,
                           fake_rollout=fake_rollout)


def test_plan_exact_order_balanced_and_noninference(monkeypatch, capsys):
    def forbidden():
        raise AssertionError("plan must never instantiate a provider")
    monkeypatch.setattr(study, "providers", forbidden)
    assert study.main([]) == study.main(["--plan"]) == 0
    assert "plan-only" in capsys.readouterr().out
    plan = study.plan()
    assert plan["protocol_sha256"] == digest(study.protocol())
    assert plan["protocol_sha256"] == "6abb1350ea008d962624bc2561bb486b461ffd426a01cbd1bfcd51c33ff391bc"
    assert len(study.tasks()) == 32 and len(study.slots()) == 128
    assert len({(slot["world"], slot["seed"], slot["policy"]) for slot in study.slots()}) == 128
    assert Counter(slot["policy"] for slot in study.slots()) == dict.fromkeys(("oracle", "baseline", "native", "json"), 32)
    assert sum(task["native_first"] for task in study.tasks()) == 16
    assert [slot["policy"] for slot in study.slots()[:4]] == ["oracle", "baseline", "native", "json"]
    assert [(task["world"], task["seed"]) for task in study.tasks()[:4]] == [
        ("refund-ops", 1000104), ("crm-merge", 1000000), ("refund-ops", 1000105), ("incident-control", 1000200)]
    assert Counter(fixture["case"] for fixture in plan["fixtures"] if fixture["world"] == "incident-control") == {"SEV1": 4, "SEV2": 4}


@pytest.mark.parametrize("arguments", [["--collect"], ["--collect", "--source-revision", REVISION],
                                      ["--collect", "--output", "unused"], ["--collect", "--plan"]])
def test_cli_requires_collection_gates(arguments):
    with pytest.raises(SystemExit) as error:
        study.main(arguments)
    assert error.value.code == 2


async def test_complete_mock_study_one_journal_no_database(harness):
    result = await study.collect(harness.output, REVISION)
    assert result["status"] == "completed" and result["finalized_episodes"] == 128
    assert len(harness.attempted) == 128
    assert all(provider.closed for provider in harness.pool.values())
    assert {path.name for path in harness.output.iterdir()} == {"evaluation-episodes.jsonl", "report.json"}
    assert study.artifact_bytes(harness.output) <= study.ARTIFACT_CAP
    assert result["artifact_total_bytes"] == study.artifact_bytes(harness.output)
    assert result["machine"] == {"platform": "mock-machine"}
    assert result["report_bytes"] == (harness.output / "report.json").stat().st_size
    rows = [json.loads(line) for line in (harness.output / "evaluation-episodes.jsonl").read_text().splitlines()]
    assert len(rows) == 128 and rows[2]["episode"]["provider_events"][0]["request_body"] == "fixture exact wire"
    assert result["analysis"]["paired"]["outcomes"] == {"both": 32, "native_only": 0, "json_only": 0, "neither": 0}
    assert all(slot["status"] == "finalized" for slot in result["slots"])
    assert sum(row["usage"].get("request_attempts", 0) for row in result["rows"]) == 64


@pytest.mark.parametrize("policy", ["native", "json"])
async def test_digest_mismatch_before_any_attempt(harness, policy):
    harness.pool[policy].model_digest = "f" * 64
    result = await study.collect(harness.output, REVISION)
    assert result["status"] == "stopped" and "model-mismatch" in result["stop_reason"]
    assert not harness.attempted and result["finalized_episodes"] == 0
    assert all(slot["status"] == "not_attempted" for slot in result["slots"])
    assert all(provider.closed for provider in harness.pool.values())


async def test_fresh_output_required(harness):
    harness.output.mkdir()
    with pytest.raises(FileExistsError):
        await study.collect(harness.output, REVISION)
    assert not harness.events


async def test_partial_stop_keeps_rows_and_incomplete_pair(monkeypatch, harness):
    original = study.reserve_next
    def reserve(output):
        if len(harness.attempted) == 3:
            raise study.StudyStopped("artifact-cap: test stop")
        original(output)
    monkeypatch.setattr(study, "reserve_next", reserve)
    result = await study.collect(harness.output, REVISION)
    assert result["finalized_episodes"] == 3 and len(harness.attempted) == 3
    assert Counter(slot["status"] for slot in result["slots"]) == {"finalized": 3, "not_attempted": 125}
    assert result["analysis"]["paired"]["complete_pairs"] == 0
    assert result["analysis"]["paired"]["incomplete_pairs"] == 1
    assert result["analysis"]["adapters"]["native"]["micro"]["attempted_unique_tasks"] == 1


async def test_wall_cap_preserves_finalized_episode(monkeypatch, harness):
    elapsed = [0]
    monkeypatch.setattr(study.time, "monotonic", lambda: elapsed[0])
    async def clocked(*args):
        episode = await harness.fake_rollout(*args)
        elapsed[0] = 2690
        return episode
    monkeypatch.setattr(study, "rollout", clocked)
    result = await study.collect(harness.output, REVISION)
    assert result["status"] == "stopped" and result["finalized_episodes"] == 1
    assert "wall-cap" in result["stop_reason"]


async def test_cancelled_episode_finalized_then_stop(monkeypatch, harness):
    async def cancelled(*args):
        episode = await harness.fake_rollout(*args)
        episode.update(status="cancelled", termination="cancelled", reward=0.0, passed=False)
        return episode
    monkeypatch.setattr(study, "rollout", cancelled)
    result = await study.collect(harness.output, REVISION)
    assert result["finalized_episodes"] == 1 and "interrupted" in result["stop_reason"]
    assert result["rows"][0]["failure_category"] == "provider-harness"


async def test_raised_interruption_has_explicit_attempt_error(monkeypatch, harness):
    async def cancelled(*args):
        raise asyncio.CancelledError()
    monkeypatch.setattr(study, "rollout", cancelled)
    result = await study.collect(harness.output, REVISION)
    assert result["status"] == "stopped" and result["finalized_episodes"] == 0
    assert result["slots"][0]["status"] == "attempted_without_final_episode"
    assert json.loads((harness.output / "evaluation-episodes.jsonl").read_text())["episode"] is None
    assert result["rows"][0]["episode_available"] is False


async def test_cleanup_failure_still_writes_stopped_report(monkeypatch, harness):
    def stop(output):
        raise study.StudyStopped("bounded stop")
    monkeypatch.setattr(study, "reserve_next", stop)
    async def fail_close():
        raise RuntimeError("private endpoint must not enter report")
    harness.pool["native"].close = fail_close
    result = await study.collect(harness.output, REVISION)
    assert result["cleanup_errors"] == [{"policy": "native", "error_type": "RuntimeError"}]
    assert "private endpoint" not in (harness.output / "report.json").read_text()
    assert harness.pool["json"].closed


async def test_changed_source_stops_before_next_attempt(monkeypatch, harness):
    original = study.source_identity
    def changed(revision):
        result = original(revision)
        if harness.attempted:
            result["files_sha256"]["fixture.py"] = "c" * 64
        return result
    monkeypatch.setattr(study, "source_identity", changed)
    result = await study.collect(harness.output, REVISION)
    assert result["finalized_episodes"] == 1 and "source-mismatch" in result["stop_reason"]


async def test_bad_episode_is_saved_before_identity_rejection(monkeypatch, harness):
    async def mismatch(*args):
        episode = await harness.fake_rollout(*args)
        episode["provenance"]["environment_version"] = "9.9.9"
        return episode
    monkeypatch.setattr(study, "rollout", mismatch)
    result = await study.collect(harness.output, REVISION)
    assert result["status"] == "stopped" and result["finalized_episodes"] == 1
    assert json.loads((harness.output / "evaluation-episodes.jsonl").read_text())["episode"]["provenance"]["environment_version"] == "9.9.9"
    assert not result["rows"][0]["replay_verified"]
    assert result["rows"][0]["observed_passed"] is True and result["rows"][0]["passed"] is False


async def test_real_reservation_stops_before_second_attempt(monkeypatch, harness):
    monkeypatch.setattr(study, "ARTIFACT_CAP", study.EPISODE_RESERVE + study.REPORT_RESERVE + 1)
    monkeypatch.setattr(study, "PROTOCOL_SHA256", digest(study.protocol()))
    result = await study.collect(harness.output, REVISION)
    assert result["finalized_episodes"] == 1 and "artifact-cap" in result["stop_reason"]
    assert len(harness.attempted) == 1
    assert result["artifact_total_bytes"] <= study.ARTIFACT_CAP


async def test_preflight_failure_cleanup_and_zero_inference(harness):
    async def failed_prepare():
        raise RuntimeError("metadata backend failed; private body")
    harness.pool["json"].prepare = failed_prepare
    result = await study.collect(harness.output, REVISION)
    assert result["finalized_episodes"] == 0 and not harness.attempted
    assert result["status"] == "stopped"
    assert all(provider.closed for provider in harness.pool.values())
    assert "private body" not in (harness.output / "report.json").read_text()


async def test_unexpected_large_episode_saved_then_collection_stops(monkeypatch, harness):
    monkeypatch.setattr(study, "EPISODE_RESERVE", 1)
    monkeypatch.setattr(study, "PROTOCOL_SHA256", digest(study.protocol()))
    monkeypatch.setattr(study, "reservation_bound", lambda: {"mock_reduced_reserve": True})
    result = await study.collect(harness.output, REVISION)
    assert result["status"] == "stopped" and result["finalized_episodes"] == 1
    assert len(harness.attempted) == 1 and "full raw saved" in result["stop_reason"]
    assert json.loads((harness.output / "evaluation-episodes.jsonl").read_text())["episode"]["passed"] is True
    assert result["rows"][0]["passed"] is False and result["rows"][0]["outcome_integrity"] is False


async def test_initial_source_refusal_precedes_provider_factory(monkeypatch, harness):
    def refused(revision):
        raise study.StudyStopped("dirty source")
    monkeypatch.setattr(study, "source_identity", refused)
    with pytest.raises(study.StudyStopped, match="dirty source"):
        await study.collect(harness.output, REVISION)
    assert not harness.output.exists() and not harness.events


async def test_replay_failure_keeps_raw_and_stops(monkeypatch, harness):
    def rejected(episode):
        raise ValueError("forged envelope")
    monkeypatch.setattr(study, "replay", rejected)
    result = await study.collect(harness.output, REVISION)
    assert result["status"] == "stopped" and result["finalized_episodes"] == 1
    assert result["rows"][0]["passed"] is False and result["rows"][0]["observed_passed"] is True
    assert len((harness.output / "evaluation-episodes.jsonl").read_text().splitlines()) == 1


@pytest.mark.parametrize("bad_index", [0, 3])
@pytest.mark.parametrize("field,mutation", [("usage", "missing"), ("passed", "missing"),
                                          ("passed", "invalid"), ("invalid_actions", "invalid")])
async def test_malformed_first_or_later_row_cannot_mutate_previous(monkeypatch, harness, bad_index, field, mutation):
    async def malformed(*args):
        episode = await harness.fake_rollout(*args)
        if len(harness.attempted) - 1 == bad_index:
            if mutation == "missing":
                del episode[field]
            else:
                episode[field] = "malformed scalar"
        return episode
    monkeypatch.setattr(study, "rollout", malformed)
    result = await study.collect(harness.output, REVISION)
    raw = [json.loads(line) for line in (harness.output / "evaluation-episodes.jsonl").read_text().splitlines()]
    assert result["status"] == "stopped" and result["finalized_episodes"] == len(raw) == bad_index + 1
    assert result["verified_episodes"] == bad_index and result["inconclusive_episodes"] == 1
    assert result["rows"][-1]["index"] == bad_index and result["rows"][-1]["passed"] is False
    assert result["slots"][bad_index]["status"] == "finalized"
    assert all(slot["status"] == "not_attempted" for slot in result["slots"][bad_index + 1:])
    for row in result["rows"][:-1]:
        assert row["outcome_integrity"] is True
        assert row["passed"] == (row["policy"] != "baseline")
    if mutation == "missing":
        assert field not in raw[-1]["episode"]
    else:
        assert raw[-1]["episode"][field] == "malformed scalar"


def test_plan_rejects_changed_protocol(monkeypatch):
    monkeypatch.setattr(study, "MAX_STEPS", 21)
    with pytest.raises(study.StudyStopped, match="reviewed fixed plan"):
        study.plan()


def test_reserve_counts_temporary_files(monkeypatch, tmp_path):
    monkeypatch.setattr(study, "ARTIFACT_CAP", study.EPISODE_RESERVE + study.REPORT_RESERVE + 2)
    (tmp_path / "unfinished-report.tmp").write_bytes(b"123")
    with pytest.raises(study.StudyStopped, match="artifact-cap"):
        study.reserve_next(tmp_path)


def test_near_limit_envelope_serialization_fits_reserved_disk(tmp_path):
    # Deliberately fill conservative component limits simultaneously; this is
    # a capacity stress fixture, not a valid model exchange or task success.
    events = [{"padding": "\\" * (4 * 1024 * 1024 - 100)}]
    assert len(study.canonical_json(events).encode()) < 8 * 1024 * 1024
    step = {"policy_input": "x" * (132 * 1024 - 100),
            "action": {"tool": "finish", "args": {"padding": "\u00e9" * (64 * 1024 - 100)}},
            "observation": {"padding": "x" * (64 * 1024 - 100)},
            "result": {"padding": "x" * (64 * 1024 - 100)}}
    episode = {"provider_events": events, "trace": [step] * 20, "metadata": "x" * (512 * 1024)}
    record = {"episode": episode, "evaluation_only": True, "training_eligible": False}
    encoded_bytes = len((study.canonical_json(record) + "\n").encode())
    assert 20 * 1024 * 1024 < encoded_bytes < study.reservation_bound()["derived_upper_bytes"] <= study.EPISODE_RESERVE
    study.reserve_next(tmp_path)
    with (tmp_path / "raw.jsonl").open("xb") as raw:
        assert study.append_raw(raw, record, tmp_path) is True
    assert study.artifact_bytes(tmp_path) == encoded_bytes


@pytest.mark.parametrize("dirty,revision", [(True, REVISION), (False, "b" * 40)])
def test_source_dirty_or_revision_mismatch_rejected(monkeypatch, dirty, revision):
    def git(arguments, **kwargs):
        output = revision if arguments[1] == "rev-parse" else " M src/world_engine/providers.py" if dirty else ""
        return SimpleNamespace(stdout=output)
    monkeypatch.setattr(study.subprocess, "run", git)
    with pytest.raises(study.StudyStopped, match="committed and clean"):
        study.source_identity(REVISION)


def test_source_scope_complete_and_fingerprints(monkeypatch):
    calls = []
    def git(arguments, **kwargs):
        calls.append(arguments)
        return SimpleNamespace(stdout=REVISION if arguments[1] == "rev-parse" else "")
    monkeypatch.setattr(study.subprocess, "run", git)
    source = study.source_identity(REVISION)
    assert "src/world_engine/providers.py" in source["files_sha256"]
    assert "src/world_engine/ollama_tools.py" in source["files_sha256"]
    assert "examples/workflow_model_study.py" in source["files_sha256"]
    assert "docs/workflow-model-study.md" in source["files_sha256"]
    assert "--untracked-files=all" in calls[1]


@pytest.mark.parametrize("revision", ["short", "A" * 40, "f" * 39])
def test_revision_format_before_git(revision):
    with pytest.raises(study.StudyStopped, match="full lowercase"):
        study.source_identity(revision)


def test_machine_metadata_bounded_public_fields(monkeypatch):
    calls = []
    monkeypatch.setattr(study.platform, "platform", lambda: "mock-Darwin")
    monkeypatch.setattr(study.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(study.metadata, "version", lambda package: "1.2.3")
    def sysctl(arguments, **kwargs):
        calls.append(arguments)
        return SimpleNamespace(stdout="Mock Public CPU" if arguments[-1] == "machdep.cpu.brand_string" else "17179869184")
    monkeypatch.setattr(study.subprocess, "run", sysctl)
    result = study.machine_metadata()
    assert result["cpu_brand"] == "Mock Public CPU" and result["memory_bytes"] == 17179869184
    assert result["libraries"] == {"httpx": "1.2.3", "pydantic": "1.2.3"}
    assert calls == [["/usr/sbin/sysctl", "-n", "machdep.cpu.brand_string"], ["/usr/sbin/sysctl", "-n", "hw.memsize"]]


def test_unknown_or_invalid_metadata_omitted(monkeypatch):
    monkeypatch.setattr(study.platform, "platform", lambda: "mock-Darwin")
    monkeypatch.setattr(study.platform, "system", lambda: "Darwin")
    def missing(package):
        raise study.metadata.PackageNotFoundError(package)
    monkeypatch.setattr(study.metadata, "version", missing)
    monkeypatch.setattr(study.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout="bad\x00value"))
    result = study.machine_metadata()
    assert result["libraries"] == {} and "cpu_brand" not in result and "memory_bytes" not in result


def test_contract_change_rejected(monkeypatch):
    original = study.contract()
    original["options"]["num_predict"] = 1024
    monkeypatch.setattr(study, "contract", lambda: original)
    with pytest.raises(study.StudyStopped, match="inference contract"):
        study.check_contracts()


@pytest.mark.parametrize("termination,invalid,outcomes,expected", [
    ("finished", 0, [], "valid-incorrect"), ("max_steps", 0, [], "max-steps"),
    ("finished", 1, [], "tool-permission-or-argument"), ("timeout", 0, [], "provider-harness"),
    ("provider_error", 0, ["invalid_response"], "protocol"),
    ("provider_error", 0, ["connection_error"], "provider-harness")])
def test_failure_taxonomy(termination, invalid, outcomes, expected):
    episode = {"passed": False, "termination": termination, "invalid_actions": invalid,
               "provider_events": [{"event": "request_finished", "outcome": outcome} for outcome in outcomes]}
    assert study.failure_category(episode) == expected
    episode["passed"] = True
    assert study.failure_category(episode) == "success"


def test_statistics_unique_pairs_stratified_macro_micro():
    rows = []
    for world, total in (("crm-merge", 2), ("refund-ops", 4), ("incident-control", 2)):
        for seed in range(total):
            rows.extend({"world": world, "seed": seed, "policy": policy,
                         "passed": (world == "refund-ops" if policy == "native" else seed == 0)}
                        for policy in ("native", "json"))
    result = study.analysis(rows)
    assert result["adapters"]["native"]["micro"]["rate"] == .5
    assert result["adapters"]["native"]["equal_world_macro"] == pytest.approx(1 / 3)
    assert result["paired"]["outcomes"] == {"both": 1, "native_only": 3, "json_only": 2, "neither": 2}
    assert result["paired"]["complete_pairs"] == 8
    assert result["paired"]["native_minus_json_micro"] == .125
    assert result == study.analysis(rows)
    assert study.wilson(0, 0) is None
    assert study.wilson(0, 1)[1] == pytest.approx(.7934506856)
    with pytest.raises(ValueError, match="duplicate"):
        study.analysis(rows + [rows[0]])
    missing = copy.deepcopy(rows)
    missing[0]["episode_available"] = False
    incomplete = study.analysis(missing)
    assert incomplete["paired"]["complete_pairs"] == 7
    assert incomplete["paired"]["incomplete_pairs"] == 1
