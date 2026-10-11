import copy
import importlib
import importlib.util
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from world_engine.models import digest
from world_engine.providers import policy_messages

SPEC = importlib.util.spec_from_file_location("scripted_candidate_corpus", Path(__file__).parents[1] / "examples/scripted_candidate_corpus.py")
study = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(study)
exports = importlib.import_module("world_engine.exports")
REVISION = "a" * 40


@pytest.fixture
def harness(tmp_path, monkeypatch):
    output = tmp_path / "corpus"
    source = {"git_revision": REVISION, "source_dirty": False, "files_sha256": {"fixture.py": "b"*64}}
    attempted = []
    fixed_plan = study.plan()
    monkeypatch.setattr(study, "plan", lambda: copy.deepcopy(fixed_plan))
    monkeypatch.setattr(study, "source_identity", lambda revision: copy.deepcopy(source))
    monkeypatch.setattr(study, "prior_seed_overlap", lambda: [])
    monkeypatch.setattr(study, "replay", lambda episode: {"verified": True})
    monkeypatch.setattr(exports, "replay", lambda episode: {"verified": True})

    async def rollout(config, index, provider):
        seed = config.seed + index
        attempted.append((config.environment_id, seed, config.provider_id))
        assert config.evaluation_only is False and not config.allow_paid
        assert (config.max_steps, config.timeout_seconds, config.concurrency) == (20, 30, 1)
        oracle = config.provider_id == "scripted-oracle"
        fixture = next(item for item in fixed_plan["fixtures"] if item["world"] == config.environment_id and item["seed"] == seed)
        observation = {"environment_id": config.environment_id, "task": "public task", "tools": [], "state": {"current_view": "public"}}
        history, trace = [], []
        for step_index, tool in enumerate(("inspect" if oracle else "invalid_tool", "finish")):
            action = {"tool": tool, "args": {}}
            result = {"ok": oracle or step_index == 1}
            trace.append({"index": step_index, "action": action, "result": result, "observation": observation,
                          "policy_input": policy_messages(observation, history), "usage": {}})
            history.append({"action": action, "result": result})
        return {"id": f"{config.environment_id}-{seed}-{config.provider_id}", "index": index, "seed": seed,
                "scenario_id": digest({"world": config.environment_id, "seed": seed}),
                "lineage_id": fixture["lineage_id"], "split": fixture["split"], "passed": oracle, "reward": float(oracle),
                "status": "completed", "termination": "finished", "steps": 2, "invalid_actions": 0 if oracle else 1,
                "elapsed_seconds": .01, "usage": {"input_tokens": 0, "output_tokens": 0}, "trace": trace,
                "initial_observation": observation, "final_state_hash": "a"*64,
                "initial_snapshot": {"private_expected_fixture": "PRIVATE_SENTINEL"},
                "grader": {"checks": [{"detail": "PRIVATE_SENTINEL"}]},
                "provenance": {"environment_id": config.environment_id, "environment_version": fixture["version"],
                               "grader_version": "1.0.0", "environment_code_hash": fixture["environment_hash"],
                               "grader_code_hash": fixture["grader_hash"], "initial_state_hash": fixture["initial_state_hash"],
                               "evaluation_only": False, "provider_id": config.provider_id,
                               "provider_class": "world_engine.providers.ScriptedProvider",
                               "provider_source_hash": study.source_fingerprint(study.ScriptedProvider),
                               "policy_hash": digest(config.provider_id), "task_hash": "a"*64, "prompt_hash": "b"*64,
                               "git_revision": REVISION, "implementation_dirty": False}}

    monkeypatch.setattr(study, "rollout", rollout)
    return SimpleNamespace(output=output, source=source, attempted=attempted, rollout=rollout)


def test_default_plan_has_fixed_disjoint_seeds_splits_and_no_store_provider(monkeypatch, capsys):
    monkeypatch.setattr(study, "QuotaStore", lambda *args: pytest.fail("plan must not create Store"))
    monkeypatch.setattr(study, "source_identity", lambda *args: pytest.fail("plan must not inspect Git"))
    monkeypatch.setattr(study.ScriptedProvider, "__init__", lambda *args: pytest.fail("plan must not create provider"))
    assert study.main([]) == study.main(["--plan"]) == 0
    assert "plan-only" in capsys.readouterr().out
    assert len(study.slots()) == 128 and len({(s["world"], s["seed"], s["policy"]) for s in study.slots()}) == 128
    assert set(study.SEEDS) == set(range(50000, 50016))
    assert study.plan()["protocol_sha256"] == study.PROTOCOL_SHA256
    assert sum(study.EXPECTED_SPLITS.values()) == 64


@pytest.mark.parametrize("args", [["--collect"], ["--collect", "--output", "new"],
    ["--collect", "--source-revision", "short", "--output", "new"], ["--plan", "--collect"],
    ["--source-revision", REVISION], ["--output", "new"]])
def test_cli_preflight_never_collects_without_required_flags(monkeypatch, args):
    monkeypatch.setattr(study, "collect", lambda *args: pytest.fail("must not collect"))
    with pytest.raises(SystemExit) as failure:
        study.main(args)
    assert failure.value.code == 2


@pytest.mark.parametrize("kind", ["file", "directory", "live-symlink", "dangling-symlink"])
async def test_existing_output_preserved_before_source_or_store(tmp_path, monkeypatch, kind):
    path = tmp_path / "receipt"
    if kind == "file":
        path.write_text("old")
    elif kind == "directory":
        path.mkdir()
        (path / "old.json").write_text("old")
    else:
        target = tmp_path / "target"
        if kind == "live-symlink":
            target.mkdir()
        path.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(study, "source_identity", lambda *args: pytest.fail("no source activity"))
    monkeypatch.setattr(study, "QuotaStore", lambda *args: pytest.fail("no Store activity"))
    with pytest.raises(FileExistsError):
        await study.collect(path, REVISION)
    assert path.is_symlink() if "symlink" in kind else path.exists()


async def test_mock128_slots_reuse_exporter_exact_counts_no_hidden_sft(harness):
    report = await study.collect(harness.output, REVISION)
    assert report["status"] == "completed", report["stop_reason"]
    assert len(harness.attempted) == report["verified_episodes"] == 128
    assert report["business_passes"] == report["clean_passes"] == 64
    assert report["recorded_episode_splits"] == {"train": 102, "validation": 12, "test": 14}
    assert report["model_calls"] == report["paid_calls"] == 0 and report["training_executed"] is False
    assert report["trainer_token_count"] is None
    assert report["candidate_batch_approved"] is True
    assert report["pairs"] == {"complete_pairs": 64, "incomplete_pairs": 0, "comparable_pairs": 64,
                               "distinct_action_trajectories": 64, "train_pairs": 51}
    assert report["exports"]["artifacts"]["sft"]["records"] == 102
    assert report["exports"]["artifacts"]["dpo"]["records"] == report["exports"]["artifacts"]["grpo"]["records"] == 51
    for name in ("sft.jsonl", "dpo.jsonl", "grouped-rollouts.jsonl"):
        contents = (harness.output / name).read_text()
        assert "PRIVATE_SENTINEL" not in contents
        assert all(json.loads(line)["provenance"]["split"] == "train" for line in contents.splitlines())
    groups = list(map(json.loads, (harness.output / "grouped-rollouts.jsonl").read_text().splitlines()))
    assert all(row["trainable"] is False and row["policy_consistent"] is False for row in groups)
    assert report["artifact_total_bytes"] == sum(path.stat().st_size for path in harness.output.iterdir())
    assert report["artifact_total_bytes"] < study.ARTIFACT_CAP
    store = study.QuotaStore(harness.output / "candidates.sqlite3")
    assert all(store.get_run(run_id)["status"] == "completed" for runs in report["runs"].values() for run_id in runs.values())


@pytest.mark.parametrize("failure", ["missing-field", "nondict", "identity", "replay", "quota"])
async def test_bad_current_envelope_preserves_prefix_and_raw_before_gate(harness, monkeypatch, failure):
    async def bad(config, index, provider):
        episode = await harness.rollout(config, index, provider)
        if len(harness.attempted) == 2:
            if failure == "missing-field":
                episode.pop("steps")
            elif failure == "nondict":
                return ["malformed returned envelope"]
            elif failure == "identity":
                episode["provenance"]["initial_state_hash"] = "wrong"
        return episode

    monkeypatch.setattr(study, "rollout", bad)
    if failure == "replay":
        monkeypatch.setattr(study, "replay", lambda episode: {"verified": "baseline" not in episode["id"]})
    if failure == "quota":
        original = study.QuotaStore.append_episode

        def full(store, run_id, episode):
            if "baseline" in episode["id"]:
                raise sqlite3.OperationalError("database or disk is full")
            original(store, run_id, episode)

        monkeypatch.setattr(study.QuotaStore, "append_episode", full)
    report = await study.collect(harness.output, REVISION)
    assert report["status"] == "stopped" and len(harness.attempted) == 2
    assert report["rows"][0]["passed"] and report["rows"][0]["outcome_integrity"]
    assert report["inconclusive_episodes"] == 1 and report["unattempted_episodes"] == 126
    row = report["rows"][1]
    assert not row["outcome_integrity"]
    if failure in {"missing-field", "nondict", "quota"}:
        saved = json.loads((harness.output / "raw-failures.jsonl").read_text())
        assert saved["episode"] is not None and row["storage"] == "raw-failures.jsonl"
        assert saved["exact_envelope_preserved"] is True
    else:
        store = study.QuotaStore(harness.output / "candidates.sqlite3")
        assert len(store.episodes(report["runs"]["crm-merge"]["scripted-baseline"])) == 1
    assert not (harness.output / "sft.jsonl").exists()


async def test_cancelled_after_oracle_is_retained_but_unverified_unpaired(harness, monkeypatch):
    async def cancelled(config, index, provider):
        episode = await harness.rollout(config, index, provider)
        if len(harness.attempted) == 2:
            episode.update(status="cancelled", termination="cancelled", reward=0.0, passed=False)
        return episode

    monkeypatch.setattr(study, "rollout", cancelled)
    report = await study.collect(harness.output, REVISION)
    assert report["status"] == "stopped" and report["verified_episodes"] == 1
    assert report["inconclusive_episodes"] == 1 and report["unattempted_episodes"] == 126
    row = report["rows"][1]
    assert not row["outcome_integrity"] and not row["replay_verified"] and not row["passed"]
    assert report["pairs"]["complete_pairs"] == 0 and report["pairs"]["incomplete_pairs"] == 1
    store = study.QuotaStore(harness.output / "candidates.sqlite3")
    saved = store.episodes(report["runs"]["crm-merge"]["scripted-baseline"])
    assert len(saved) == 1 and saved[0]["status"] == "cancelled"
    assert not (harness.output / "sft.jsonl").exists()


async def test_terminal_update_failure_excludes_current_verified_episode_from_pairs(harness, monkeypatch):
    original = study.QuotaStore.update_run
    failed = False

    def update(store, run_id, status, **kwargs):
        nonlocal failed
        if status == "completed" and not failed:
            failed = True
            raise sqlite3.OperationalError("sensitive terminal update details")
        original(store, run_id, status, **kwargs)

    monkeypatch.setattr(study.QuotaStore, "update_run", update)
    report = await study.collect(harness.output, REVISION)
    assert len(harness.attempted) == report["attempted_episodes"] == 31
    assert report["verified_episodes"] == 30 and report["inconclusive_episodes"] == 1
    assert report["unattempted_episodes"] == 97 and report["pairs"]["complete_pairs"] == 15
    assert report["pairs"]["incomplete_pairs"] == 0
    row = report["rows"][-1]
    assert row["storage"] == "candidates.sqlite3"
    assert not row["outcome_integrity"] and not row["replay_verified"] and not row["passed"]
    store = study.QuotaStore(harness.output / "candidates.sqlite3")
    assert len(store.episodes(report["runs"]["crm-merge"]["scripted-oracle"])) == 16
    assert "sensitive terminal" not in (harness.output / "manifest.json").read_text()
    assert not (harness.output / "sft.jsonl").exists()


@pytest.mark.parametrize("malformed", ["nan", "object", "recursive"])
async def test_non_json_envelope_uses_redacted_diagnostic_not_exact_raw(harness, monkeypatch, malformed):
    class ProtectedObject:
        def __repr__(self):
            return "PRIVATE_REPR_SENTINEL"

    async def invalid(config, index, provider):
        episode = await harness.rollout(config, index, provider)
        if len(harness.attempted) == 2:
            value = float("nan") if malformed == "nan" else ProtectedObject()
            if malformed == "recursive":
                value = []
                value.append(value)
            episode["non_json"] = value
            episode["protected"] = "PRIVATE_STRING_SENTINEL"
        return episode

    monkeypatch.setattr(study, "rollout", invalid)
    report = await study.collect(harness.output, REVISION)
    saved = json.loads((harness.output / "raw-failures.jsonl").read_text())
    assert saved["episode"] is None and saved["exact_envelope_preserved"] is False
    assert saved["training_eligible"] is False and "diagnostic marker only" in saved["storage_error"]
    assert saved["slot"]["index"] == 1
    assert report["verified_episodes"] == report["inconclusive_episodes"] == 1
    assert report["unattempted_episodes"] == 126 and not report["rows"][1]["replay_verified"]
    for path in harness.output.glob("*.json*"):
        assert "PRIVATE_REPR_SENTINEL" not in path.read_text() and "PRIVATE_STRING_SENTINEL" not in path.read_text()


async def test_partial_exception_keeps_error_marker_and_interrupted_runs(harness, monkeypatch):
    async def fail(config, index, provider):
        if harness.attempted:
            raise RuntimeError("sensitive mock details")
        return await harness.rollout(config, index, provider)

    monkeypatch.setattr(study, "rollout", fail)
    report = await study.collect(harness.output, REVISION)
    saved = json.loads((harness.output / "raw-failures.jsonl").read_text())
    assert saved["episode"] is None and "sensitive" not in (harness.output / "manifest.json").read_text()
    assert report["attempted_episodes"] == 2 and report["verified_episodes"] == 1
    store = study.QuotaStore(harness.output / "candidates.sqlite3")
    assert all(store.get_run(run_id)["status"] == "interrupted" for runs in report["runs"].values() for run_id in runs.values())


async def test_source_change_before_second_slot_no_extra_decision(harness, monkeypatch):
    calls = 0

    def source(revision):
        nonlocal calls
        calls += 1
        result = copy.deepcopy(harness.source)
        if calls >= 3:
            result["files_sha256"]["fixture.py"] = "c"*64
        return result

    monkeypatch.setattr(study, "source_identity", source)
    report = await study.collect(harness.output, REVISION)
    assert len(harness.attempted) == 1 and report["unattempted_episodes"] == 127
    assert report["rows"][0]["outcome_integrity"] and report["status"] == "stopped"


@pytest.mark.parametrize("budget", ["failure", "artifact", "time"])
async def test_no_next_decision_without_full_reservations(harness, monkeypatch, budget):
    if budget == "failure":
        monkeypatch.setattr(study, "FAILURE_CAP", study.EPISODE_RESERVE - 1)
    elif budget == "artifact":
        monkeypatch.setattr(study, "ARTIFACT_CAP", study.EPISODE_RESERVE + study.MANIFEST_CAP)
    else:
        monkeypatch.setattr(study, "OVERALL_SECONDS", study.FINALIZE_SECONDS)
    report = await study.collect(harness.output, REVISION)
    assert not harness.attempted and report["attempted_episodes"] == 0
    assert report["unattempted_episodes"] == 128 and report["status"] == "stopped"
    assert report["candidate_batch_approved"] is False


async def test_source_change_during_export_preserves_raw_but_rejects_batch(harness, monkeypatch):
    def source(revision):
        result = copy.deepcopy(harness.source)
        if (harness.output / "sft.jsonl").exists():
            result["files_sha256"]["fixture.py"] = "c"*64
        return result

    monkeypatch.setattr(study, "source_identity", source)
    report = await study.collect(harness.output, REVISION)
    assert len(harness.attempted) == report["verified_episodes"] == 128
    assert report["status"] == "stopped" and report["candidate_batch_approved"] is False
    assert "export finalization" in report["stop_reason"]
    store = study.QuotaStore(harness.output / "candidates.sqlite3")
    assert sum(len(store.episodes(run_id)) for runs in report["runs"].values() for run_id in runs.values()) == 128
    assert (harness.output / "sft.jsonl").exists()


def test_prior_seed_overlap_reads_only_receipts_and_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(study, "ROOT", tmp_path)
    root = tmp_path / "artifacts/history"
    root.mkdir(parents=True)
    (root / "rows.jsonl").write_text('{"episode":{"seed":50003}}\n{"seed":42}\n')
    assert study.prior_seed_overlap() == [50003]
    (root / "bad.json").write_text("not JSON")
    with pytest.raises(study.CorpusStopped, match="prior receipt"):
        study.prior_seed_overlap()


def test_prior_seed_scan_includes_candidate_root_not_arbitrary_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(study, "ROOT", tmp_path)
    candidate = tmp_path / "examples/candidate-corpus/old-run"
    candidate.mkdir(parents=True)
    (candidate / "manifest.json").write_text('{"rows":[{"seed":50009}]}')
    (candidate / "ignored.txt").write_text('{"seed":50010}')
    elsewhere = tmp_path / "unscanned"
    elsewhere.mkdir()
    (elsewhere / "receipt.json").write_text('{"seed":50011}')
    assert study.prior_seed_overlap() == [50009]


def test_full_source_scope_requires_clean_reviewed_sha(tmp_path, monkeypatch):
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
    with pytest.raises(study.CorpusStopped, match="full lowercase"):
        study.source_identity("short")
    monkeypatch.setattr(study.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout="dirty"))
    with pytest.raises(study.CorpusStopped, match="committed and clean"):
        study.source_identity(REVISION)


async def test_prior_seed_overlap_blocks_before_store(harness, monkeypatch):
    monkeypatch.setattr(study, "prior_seed_overlap", lambda: [50003])
    monkeypatch.setattr(study, "QuotaStore", lambda *args: pytest.fail("no Store activity"))
    with pytest.raises(study.CorpusStopped, match="overlap"):
        await study.collect(harness.output, REVISION)
    assert not harness.attempted and list(harness.output.iterdir()) == []


def test_private_sqlite_quota_every_connection_rollback_and_reopen(tmp_path):
    path = tmp_path / "bounded.sqlite3"
    store = study.QuotaStore(path)
    with store.connect() as connection:
        assert connection.execute("PRAGMA max_page_count").fetchone()[0] == study.DB_CAP // study.PAGE_BYTES
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        connection.execute("CREATE TABLE fixture(value BLOB)")
        connection.execute("INSERT INTO fixture VALUES(?)", (b"unchanged",))
    with pytest.raises(sqlite3.OperationalError, match="full"):
        with store.connect() as connection:
            connection.execute("INSERT INTO fixture VALUES(zeroblob(?))", (study.DB_CAP,))
    reopened = study.QuotaStore(path)
    with reopened.connect() as connection:
        assert connection.execute("SELECT value FROM fixture").fetchall()[0][0] == b"unchanged"
        assert connection.execute("SELECT COUNT(*) FROM fixture").fetchone()[0] == 1
        assert connection.execute("PRAGMA max_page_count").fetchone()[0] == study.DB_CAP // study.PAGE_BYTES
    assert path.stat().st_size <= study.DB_CAP
    assert not Path(str(path)+"-wal").exists() and not Path(str(path)+"-shm").exists()


def test_large_rollback_transaction_journal_peak_bound_and_no_mutation(tmp_path):
    path = tmp_path / "journal.sqlite3"
    store = study.QuotaStore(path)
    payload = b"a"*(256*1024)
    with store.connect() as connection:
        connection.execute("CREATE TABLE fixture(value BLOB)")
        connection.executemany("INSERT INTO fixture VALUES(?)", [(payload,)]*60)
    with pytest.raises(RuntimeError, match="rollback"):
        with store.connect() as connection:
            connection.execute("UPDATE fixture SET value=zeroblob(?)", (len(payload),))
            journal = Path(str(path)+"-journal")
            assert 14*study.MIB < journal.stat().st_size <= study.JOURNAL_CAP
            assert path.stat().st_size + journal.stat().st_size <= study.DB_CAP + study.JOURNAL_CAP
            raise RuntimeError("rollback")
    with store.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM fixture WHERE value=?", (payload,)).fetchone()[0] == 60
    assert not Path(str(path)+"-journal").exists()
    assert 14*study.MIB < store.journal_sampled_peak_bytes <= study.JOURNAL_CAP


async def test_exports_cap_before_any_export_write_and_raw_data_retained(harness, monkeypatch):
    monkeypatch.setattr(study, "EXPORT_CAP", 1)
    monkeypatch.setattr(study, "plan", lambda: {"fixtures": study.fixtures()})
    report = await study.collect(harness.output, REVISION)
    assert report["status"] == "stopped" and report["verified_episodes"] == 128
    assert not any((harness.output / name).exists() for name in ("sft.jsonl", "dpo.jsonl", "grouped-rollouts.jsonl"))


@pytest.mark.parametrize("excluded", ["evaluation_only", "unsupported_protocol", "replay", "noncomparable", "duplicate", "cleanup"])
async def test_exporter_exclusion_gates_are_not_bypassed(harness, monkeypatch, excluded):
    # Exercise the real exporter with mocked replay, not synthetic model calls.
    report = await study.collect(harness.output, REVISION)
    store = study.QuotaStore(harness.output / "candidates.sqlite3")
    run_id = report["runs"]["crm-merge"]["scripted-oracle"]
    original = store.episodes
    episodes = original(run_id)
    candidate = next(value for value in episodes if value["split"] == "train")
    if excluded == "evaluation_only":
        candidate["provenance"]["evaluation_only"] = True
    elif excluded == "unsupported_protocol":
        candidate["provenance"]["provider_protocol"] = "operator-only"
    elif excluded == "replay":
        monkeypatch.setattr(exports, "replay", lambda episode: (_ for _ in ()).throw(ValueError("mock")))
    elif excluded == "cleanup":
        candidate["provider_cleanup"] = {"status": "failed"}
    elif excluded == "duplicate":
        original_candidates = store.candidates

        def duplicate(scenario):
            values = original_candidates(scenario)
            if values:
                for value in values:
                    value["trace"] = copy.deepcopy(values[0]["trace"])
            return values

        monkeypatch.setattr(store, "candidates", duplicate)
    else:
        monkeypatch.setattr(store, "candidates", lambda scenario: [])
    monkeypatch.setattr(store, "episodes", lambda requested: episodes if requested == run_id else original(requested))
    records, summary = study.export_records(store, run_id, "dpo", "passed")
    assert len(records) < 12
    key = {"evaluation_only": "evaluation_only", "unsupported_protocol": "unsupported_provider_protocol",
           "replay": "replay_mismatch", "noncomparable": "insufficient_alternatives",
           "duplicate": "insufficient_alternatives", "cleanup": "unsupported_provider_protocol"}[excluded]
    assert summary["excluded"][key] > 0
