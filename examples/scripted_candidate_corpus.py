"""Plan or explicitly collect a bounded, paired scripted candidate corpus; never train a model."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

from world_engine.environments import make_environment
from world_engine.exports import comparable, export_records, jsonl
from world_engine.models import RunConfig, canonical_json, digest, utc_now
from world_engine.providers import ScriptedProvider
from world_engine.rollout import (
    POLICY_VERSION,
    collection_revision,
    replay,
    rollout,
    scenario_split,
    source_fingerprint,
    world_fingerprints,
)
from world_engine.store import Store

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SCOPE = ["src/world_engine", "pyproject.toml", "uv.lock", "examples/scripted_candidate_corpus.py",
                "tests/test_scripted_candidate_corpus.py", "docs/scripted-candidate-corpus.md"]
RECEIPT_ROOTS = ("artifacts", "examples/benchmark-results", "examples/datasets", "examples/candidate-corpus")
VERSIONS = {"crm-merge": "1.1.1", "refund-ops": "1.1.2", "incident-control": "1.0.1", "access-provisioning": "1.0.0"}
POLICIES = ("scripted-oracle", "scripted-baseline")
SEEDS = tuple(range(50000, 50016))
EXPECTED_SPLITS = {"train": 51, "validation": 6, "test": 7}
MAX_STEPS, EPISODE_SECONDS, OVERALL_SECONDS, FINALIZE_SECONDS = 20, 30, 600, 30
MIB = 1024**2
ARTIFACT_CAP, DB_CAP, JOURNAL_CAP, FAILURE_CAP, EXPORT_CAP, MANIFEST_CAP = (64*MIB, 16*MIB, 17*MIB, 16*MIB, 14*MIB, MIB)
EPISODE_RESERVE = 8*MIB
PAGE_BYTES = 4096
PROTOCOL_SHA256 = "d0b3a3c0c8ef9578f9d754ce137f4ca736db5f7a200d5acd22044907b2d49c2f"


class CorpusStopped(RuntimeError):
    """Stop without editing earlier candidate or historical records."""


class QuotaStore(Store):
    """Private collector DB; every connection has the same SQLite page quota."""

    def __init__(self, path):
        self.ready = False
        self.journal_sampled_peak_bytes = 0
        super().__init__(path)
        with self.connect() as connection:
            if connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0] != "delete":
                raise CorpusStopped("private database must use DELETE journaling")
        self.ready = True
        if any(Path(str(self.path) + suffix).exists() for suffix in ("-wal", "-shm")):
            raise CorpusStopped("private database retained unexpected WAL/SHM artifacts")

    @contextmanager
    def connect(self):
        with super().connect() as connection:
            if connection.execute("PRAGMA page_size").fetchone()[0] != PAGE_BYTES:
                raise CorpusStopped("private database page size differs from quota protocol")
            if connection.execute(f"PRAGMA max_page_count={DB_CAP // PAGE_BYTES}").fetchone()[0] != DB_CAP // PAGE_BYTES:
                raise CorpusStopped("private database exceeds page quota")
            if self.ready and connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                raise CorpusStopped("private database journaling changed")
            try:
                yield connection
            finally:
                journal = Path(str(self.path) + "-journal")
                if journal.exists():
                    size = journal.stat().st_size
                    self.journal_sampled_peak_bytes = max(self.journal_sampled_peak_bytes, size)
                    if size > JOURNAL_CAP:
                        raise CorpusStopped("private rollback journal exceeded fixed transaction bound")


def slots() -> list[dict]:
    return [{"index": index, "world": world, "seed": seed, "policy": policy}
            for index, (world, seed, policy) in enumerate((world, seed, policy) for world in VERSIONS
                                                         for seed in SEEDS for policy in POLICIES)]


def fixtures() -> list[dict]:
    result = []
    for world_id in VERSIONS:
        for seed in SEEDS:
            world = make_environment(world_id, seed)
            if world.version != VERSIONS[world_id] or len(canonical_json(world.snapshot()).encode()) > 32*1024:
                raise CorpusStopped("world version/initial size differs from fixed fixture protocol")
            environment_hash, grader_hash = world_fingerprints(world)
            lineage = digest({"environment_family": world_id, "seed": seed})
            result.append({"world": world_id, "seed": seed, "version": world.version,
                           "environment_hash": environment_hash, "grader_hash": grader_hash,
                           "initial_state_hash": digest(world.snapshot()), "lineage_id": lineage, "split": scenario_split(lineage)})
    return result


def protocol() -> dict:
    return {"id": "paired-scripted-candidate-corpus-v1", "slots": slots(), "world_versions": VERSIONS,
            "fixtures_sha256": digest(fixtures()), "scripted_policy_sha256": source_fingerprint(ScriptedProvider),
            "policy_version": POLICY_VERSION, "expected_task_splits": EXPECTED_SPLITS,
            "max_steps": MAX_STEPS, "episode_seconds": EPISODE_SECONDS, "concurrency": 1,
            "overall_seconds": OVERALL_SECONDS, "finalize_seconds": FINALIZE_SECONDS,
            "model_calls": 0, "paid_calls": 0, "training_executed": False, "evaluation_only": False,
            "artifact_cap": ARTIFACT_CAP, "database_cap": DB_CAP, "rollback_journal_cap": JOURNAL_CAP,
            "failure_cap": FAILURE_CAP, "exports_combined_cap": EXPORT_CAP, "manifest_cap": MANIFEST_CAP,
            "next_episode_reserve": EPISODE_RESERVE, "retry_policy": "none"}


def plan() -> dict:
    value = protocol()
    fixed = fixtures()
    if digest(value) != PROTOCOL_SHA256 or dict(Counter(item["split"] for item in fixed)) != EXPECTED_SPLITS:
        raise CorpusStopped("fixture/policy/protocol differs from the reviewed candidate plan")
    return {"protocol": value, "protocol_sha256": digest(value), "fixtures": fixed,
            "status": "plan-only; no Store, provider or training activity",
            "limitations": "New seeds in existing public synthetic families; not a new-family holdout or learning claim."}


def prior_seed_overlap() -> list[int]:
    found = set()

    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "seed" and type(item) is int:
                    found.add(item)
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    for root in (ROOT / relative for relative in RECEIPT_ROOTS):
        for path in root.rglob("*"):
            if path.suffix not in {".json", ".jsonl"} or not path.is_file():
                continue
            try:
                with path.open() as handle:
                    if path.suffix == ".jsonl":
                        for line in handle:
                            if line.strip():
                                visit(json.loads(line))
                    else:
                        visit(json.load(handle))
            except (OSError, ValueError):
                raise CorpusStopped("prior receipt cannot be read for seed-disjointness check") from None
    return sorted(found.intersection(SEEDS))


def source_identity(expected: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise CorpusStopped("source revision must be a reviewed full lowercase SHA")

    def git(*args):
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True, timeout=3).stdout.strip()

    if git("rev-parse", "HEAD") != expected or git("status", "--porcelain", "--untracked-files=all", "--", *SOURCE_SCOPE):
        raise CorpusStopped("runtime/dependencies/collector/test/protocol must be committed and clean")
    files = [*sorted((ROOT / "src/world_engine").rglob("*.py")),
             *(ROOT / path for path in SOURCE_SCOPE if not (ROOT / path).is_dir())]
    return {"git_revision": expected, "source_dirty": False, "scope": SOURCE_SCOPE,
            "files_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files},
            "checkout_dirty": bool(git("status", "--porcelain", "--untracked-files=all"))}


def artifact_bytes(output: Path) -> int:
    return sum(path.stat().st_size for path in output.iterdir() if path.is_file())


def save_failure(output: Path, record: dict) -> None:
    record = {**record, "exact_envelope_preserved": record.get("episode") is not None}
    try:
        content = (canonical_json(record) + "\n").encode()
    except (TypeError, ValueError, OverflowError, RecursionError):
        # Do not stringify an invalid object: repr/errors can expose protected data.
        record = {"slot": record["slot"], "episode": None, "exact_envelope_preserved": False,
                  "training_eligible": False,
                  "storage_error": "returned envelope is not serializable JSON; diagnostic marker only"}
        content = (canonical_json(record) + "\n").encode()
    path = output / "raw-failures.jsonl"
    used = path.stat().st_size if path.exists() else 0
    if used + len(content) > FAILURE_CAP or artifact_bytes(output) + len(content) + MANIFEST_CAP > ARTIFACT_CAP:
        raise CorpusStopped("raw failure cannot fit its reserved cap")
    with path.open("ab") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def check_episode(episode: dict, slot: dict, fixture: dict, source: dict) -> None:
    v = episode["provenance"]
    if (episode["seed"] != slot["seed"] or episode["lineage_id"] != fixture["lineage_id"]
            or episode["split"] != fixture["split"] or v["environment_id"] != slot["world"]
            or v["environment_version"] != fixture["version"] or v["initial_state_hash"] != fixture["initial_state_hash"]
            or v["environment_code_hash"] != fixture["environment_hash"] or v["grader_code_hash"] != fixture["grader_hash"]
            or v["evaluation_only"] is not False or v["provider_id"] != slot["policy"]
            or v["provider_class"] != "world_engine.providers.ScriptedProvider"
            or v.get("provider_protocol", POLICY_VERSION) != POLICY_VERSION or episode.get("provider_events")
            or v["provider_source_hash"] != source_fingerprint(ScriptedProvider)
            or v["git_revision"] != source["git_revision"] or v["implementation_dirty"] is not False
            or type(episode["steps"]) is not int or not 0 <= episode["steps"] <= MAX_STEPS):
        raise CorpusStopped("returned episode differs from fixed slot/source/provider")
    if replay(episode)["verified"] is not True:
        raise CorpusStopped("returned episode replay rejected")


def validate_exports(records: dict, episodes: list[dict]) -> None:
    by_id = {episode["id"]: episode for episode in episodes}
    for row in records["sft"]:
        episode = by_id[row["provenance"]["episode_id"]]
        step = episode["trace"][row["provenance"]["step_index"]]
        if (episode["split"] != "train" or episode["provenance"]["evaluation_only"]
                or row["messages"] != step["policy_input"] + [{"role": "assistant", "content": canonical_json(step["action"])}]):
            raise CorpusStopped("SFT is not exact recorded eligible decision context")
    for row in records["dpo"]:
        chosen, rejected = by_id[row["chosen_episode_id"]], by_id[row["rejected_episode_id"]]
        if (not comparable(chosen, rejected) or chosen["split"] != "train"
                or chosen["reward"] <= rejected["reward"] or not chosen["passed"] or chosen["invalid_actions"]):
            raise CorpusStopped("DPO candidates are not eligible comparable preferences")
    for row in records["grpo"]:
        candidates = [by_id[value["episode_id"]] for value in row["candidates"]]
        if row["trainable"] is not False or any(value["split"] != "train" or not comparable(candidates[0], value)
                                                for value in candidates):
            raise CorpusStopped("grouped candidates differ from raw comparable train interchange")


def write_exports(output: Path, store: Store, runs: dict, episodes: list[dict]) -> dict:
    combined = {format: [] for format in ("sft", "dpo", "grpo")}
    reports = {}
    for world, world_runs in runs.items():
        reports[world] = {}
        for format in combined:
            records, report = export_records(store, world_runs["scripted-oracle"], format, "passed")
            combined[format].extend(records)
            reports[world][format] = report
    validate_exports(combined, episodes)
    serialized = {format: jsonl(records).encode() for format, records in combined.items()}
    size = sum(map(len, serialized.values()))
    if size > EXPORT_CAP or artifact_bytes(output) + size + MANIFEST_CAP > ARTIFACT_CAP:
        raise CorpusStopped("combined exports exceed reserved cap before any export write")
    artifacts = {}
    for format, content in serialized.items():
        name = "grouped-rollouts.jsonl" if format == "grpo" else f"{format}.jsonl"
        with (output / name).open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        artifacts[format] = {"file": name, "records": len(combined[format]), "bytes": len(content),
                             "sha256": hashlib.sha256(content).hexdigest()}
    return {"artifacts": artifacts, "per_world_reports": reports}


def write_manifest(output: Path, report: dict) -> None:
    report.update(artifacts_bytes_before_manifest=artifact_bytes(output), manifest_bytes=0, artifact_total_bytes=0)
    content = (json.dumps(report, indent=2, allow_nan=False) + "\n").encode()
    while report["manifest_bytes"] != len(content):
        report["manifest_bytes"] = len(content)
        report["artifact_total_bytes"] = report["artifacts_bytes_before_manifest"] + len(content)
        content = (json.dumps(report, indent=2, allow_nan=False) + "\n").encode()
    if len(content) > MANIFEST_CAP or artifact_bytes(output) + len(content) > ARTIFACT_CAP:
        raise CorpusStopped("manifest cannot fit cap; existing evidence retained")
    with (output / "manifest.json").open("xb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def pair_counts(episodes: list[dict]) -> dict:
    pairs = {}
    for episode in episodes:
        v = episode["provenance"]
        pairs.setdefault((v["environment_id"], episode["seed"]), {})[v["provider_id"]] = episode
    complete = [value for value in pairs.values() if set(value) == set(POLICIES)]
    return {"complete_pairs": len(complete), "incomplete_pairs": len(pairs)-len(complete),
            "comparable_pairs": sum(comparable(value[POLICIES[0]], value[POLICIES[1]]) for value in complete),
            "distinct_action_trajectories": sum(digest([step["action"] for step in value[POLICIES[0]]["trace"]]) !=
                                               digest([step["action"] for step in value[POLICIES[1]]["trace"]]) for value in complete),
            "train_pairs": sum(value[POLICIES[0]]["split"] == "train" for value in complete)}


async def collect(output: Path, expected_revision: str) -> dict:
    started = time.monotonic()
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    source, fixed_plan = source_identity(expected_revision), plan()
    if prior_seed_overlap():
        raise CorpusStopped("candidate seeds overlap prior public receipts; choose a separately reviewed protocol")
    scheduled = [{**slot, "status": "not_attempted"} for slot in slots()]
    rows, episodes, runs = [], [], {world: {} for world in VERSIONS}
    report = {"schema": "world-engine.scripted-candidate-corpus.v1", "created_at": utc_now(), "source": source,
              "plan": fixed_plan, "slots": scheduled, "rows": rows, "prior_receipt_seed_overlap": [],
              "model_calls": 0, "paid_calls": 0, "training_executed": False, "trainer_token_count": None,
              "note": "Scripted candidates only. Grouped rollouts trainable=false; DPO trajectory messages need a trainer adapter."}
    store, current, current_row, stop = None, None, None, None
    try:
        store = QuotaStore(output / "candidates.sqlite3")
        for world, world_runs in runs.items():
            for policy in POLICIES:
                run_id = str(uuid.uuid4())
                store.create_run(run_id, RunConfig(environment_id=world, provider_id=policy, episodes=len(SEEDS),
                                                   seed=SEEDS[0], max_steps=MAX_STEPS, concurrency=1,
                                                   timeout_seconds=EPISODE_SECONDS, evaluation_only=False, allow_paid=False))
                world_runs[policy] = run_id
        collection_revision.cache_clear()
        async with asyncio.timeout(max(.01, OVERALL_SECONDS - FINALIZE_SECONDS - (time.monotonic() - started))):
            for slot in scheduled:
                failures = output / "raw-failures.jsonl"
                if ((failures.stat().st_size if failures.exists() else 0) + EPISODE_RESERVE > FAILURE_CAP
                        or artifact_bytes(output) + EPISODE_RESERVE + MANIFEST_CAP > ARTIFACT_CAP):
                    raise CorpusStopped("no next episode failure/finalization reservation")
                if source_identity(expected_revision)["files_sha256"] != source["files_sha256"] or plan() != fixed_plan:
                    raise CorpusStopped("source/fixture changed before next scripted decision")
                if time.monotonic() - started + EPISODE_SECONDS + FINALIZE_SECONDS > OVERALL_SECONDS:
                    raise CorpusStopped("no next full episode time budget")
                current, current_row = slot, None
                slot["status"] = "attempt_started"
                run_id = runs[slot["world"]][slot["policy"]]
                store.update_run(run_id, "running")
                config = RunConfig(environment_id=slot["world"], provider_id=slot["policy"], episodes=len(SEEDS),
                                   seed=SEEDS[0], max_steps=MAX_STEPS, concurrency=1, timeout_seconds=EPISODE_SECONDS,
                                   evaluation_only=False, allow_paid=False)
                # Only the built-in deterministic policies are reachable; no model registry.
                episode = await rollout(config, slot["seed"]-SEEDS[0], ScriptedProvider(slot["policy"] == "scripted-oracle"))
                current_row = {**slots()[slot["index"]], "episode_id": episode.get("id") if isinstance(episode, dict) else None,
                               "outcome_integrity": False,
                               "replay_verified": False, "passed": False, "clean_success": False,
                               "observed_passed": episode.get("passed") if isinstance(episode, dict)
                               and type(episode.get("passed")) is bool else None, "storage": None}
                rows.append(current_row)
                try:
                    encoded = canonical_json(episode).encode()
                    if len(encoded) > EPISODE_RESERVE:
                        raise CorpusStopped("returned episode exceeds reviewed capacity bound")
                    store.append_episode(run_id, episode)
                    current_row["storage"] = "candidates.sqlite3"
                except Exception:
                    save_failure(output, {"slot": slots()[slot["index"]], "episode": episode,
                                          "training_eligible": False, "storage_error": "episode could not be admitted to bounded Store"})
                    current_row["storage"] = "raw-failures.jsonl"
                    raise CorpusStopped("returned episode saved as raw failure; no next decision") from None
                slot["status"] = "persisted"
                fixture = next(item for item in fixed_plan["fixtures"] if item["world"] == slot["world"] and item["seed"] == slot["seed"])
                check_episode(episode, slot, fixture, source)
                current_row.update(outcome_integrity=True, replay_verified=True, split=episode["split"],
                                   status=episode["status"], termination=episode["termination"], steps=episode["steps"],
                                   passed=episode["passed"], clean_success=episode["passed"] and episode["invalid_actions"] == 0,
                                   invalid_actions=episode["invalid_actions"])
                if episode["status"] == "cancelled":
                    raise CorpusStopped("handled cancellation retained; no next decision")
                if slot["seed"] == SEEDS[-1]:
                    store.update_run(run_id, "completed", elapsed=time.monotonic()-started)
                slot["status"] = "verified"
                episodes.append(episode)
                current, current_row = None, None
    except (Exception, asyncio.CancelledError) as error:
        stop = str(error) if isinstance(error, CorpusStopped) else f"collector failed: {type(error).__name__}; details redacted"
        if current_row is not None:
            current_row.update(outcome_integrity=False, replay_verified=False, passed=False, clean_success=False)
            current["status"] = "persisted_inconclusive" if current_row["storage"] else "attempted_without_persisted_episode"
        elif current is not None:
            current["status"] = "attempted_without_final_episode"
            save_failure(output, {"slot": slots()[current["index"]], "episode": None, "error": stop, "training_eligible": False})
            rows.append({**slots()[current["index"]], "outcome_integrity": False, "replay_verified": False,
                         "passed": False, "clean_success": False, "storage": "raw-failures.jsonl"})
    finally:
        if store is not None:
            try:
                for world_runs in runs.values():
                    for run_id in world_runs.values():
                        if store.get_run(run_id)["status"] in {"queued", "running"}:
                            store.update_run(run_id, "interrupted", elapsed=time.monotonic()-started,
                                             error="candidate collection stopped; persisted episodes retained")
            except Exception:
                stop = stop or "database terminal-state cleanup failed; details redacted"
        try:
            final_source = source_identity(expected_revision)
            report["final_checkout_dirty"] = final_source.get("checkout_dirty")
            if final_source["files_sha256"] != source["files_sha256"]:
                stop = stop or "source changed during last episode/finalization"
        except Exception:
            stop = stop or "final source verification failed"
        if not stop and store is not None:
            try:
                report["exports"] = write_exports(output, store, runs, episodes)
            except Exception as error:
                stop = str(error) if isinstance(error, CorpusStopped) else "export validation failed; details redacted"
        try:
            if source_identity(expected_revision)["files_sha256"] != source["files_sha256"]:
                stop = stop or "source changed during export finalization"
        except Exception:
            stop = stop or "post-export source verification failed"
        if time.monotonic()-started > OVERALL_SECONDS:
            stop = stop or "overall duration exceeded"
        report.update(status="stopped" if stop else "completed", stop_reason=stop, candidate_batch_approved=stop is None, runs=runs,
                      elapsed_seconds=time.monotonic()-started, attempted_episodes=len(rows),
                      verified_episodes=sum(row["replay_verified"] for row in rows),
                      inconclusive_episodes=sum(not row["outcome_integrity"] for row in rows),
                      unattempted_episodes=sum(slot["status"] == "not_attempted" for slot in scheduled),
                      business_passes=sum(row["passed"] for row in rows), clean_passes=sum(row["clean_success"] for row in rows),
                      recorded_episode_splits=dict(Counter(row["split"] for row in rows if row.get("outcome_integrity"))),
                      pairs=pair_counts(episodes),
                      per_world_policy={world: {policy: {"attempted": sum(row["world"] == world and row["policy"] == policy for row in rows),
                                                        "verified": sum(row["world"] == world and row["policy"] == policy and row["outcome_integrity"] for row in rows),
                                                        "business_passes": sum(row["world"] == world and row["policy"] == policy and row["passed"] for row in rows),
                                                        "clean_passes": sum(row["world"] == world and row["policy"] == policy and row["clean_success"] for row in rows)}
                                               for policy in POLICIES} for world in VERSIONS},
                      journal_sampled_peak_bytes=store.journal_sampled_peak_bytes if store else None,
                      private_db_journal_mode="delete" if store else None)
        report["artifact_files"] = {path.name: {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                                    for path in output.iterdir() if path.is_file()}
        write_manifest(output, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--collect", action="store_true")
    parser.add_argument("--source-revision")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not args.collect:
        if args.source_revision is not None or args.output is not None:
            parser.error("collection arguments require --collect")
        print(json.dumps(plan(), indent=2))
        return 0
    if args.output is None or not args.source_revision or not re.fullmatch(r"[0-9a-f]{40}", args.source_revision):
        parser.error("--collect requires reviewed full --source-revision and fresh --output")
    result = asyncio.run(collect(args.output, args.source_revision))
    print(canonical_json({"status": result["status"], "verified_episodes": result["verified_episodes"], "stop_reason": result["stop_reason"]}))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
