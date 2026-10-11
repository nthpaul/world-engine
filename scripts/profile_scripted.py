"""Plan a fixed scripted CPU profile; collection requires reviewed committed source."""

from __future__ import annotations

import argparse
import asyncio
import cProfile
import hashlib
import io
import json
import os
import platform
import pstats
import re
import subprocess
import tempfile
import time
from pathlib import Path

from world_engine.environments import ENVIRONMENTS
from world_engine.models import RunConfig, canonical_json, digest, utc_now
from world_engine.rollout import collection_revision, replay, rollout
from world_engine.store import Store

ROOT = Path(__file__).resolve().parents[1]
WORLDS = ("crm-merge", "refund-ops", "incident-control", "access-provisioning")
TRIALS = ("unprofiled", "profiled")
EPISODES = 24
DECISIONS = (152, 64, 192, 320)
SETUP_OBSERVATIONS = (3, 3, 3, 4)
OLD_OBSERVATIONS = (528, 264, 648, 1056)
NEW_OBSERVATIONS = (376, 200, 456, 736)
OVERALL_SECONDS, FINALIZE_SECONDS = 240, 15
ARTIFACT_CAP, REPORT_RESERVE = 64 * 1024**2, 1024**2
SOURCE_SCOPE = ("src/world_engine", "pyproject.toml", "uv.lock", "scripts/profile_scripted.py",
                "tests/test_profile_scripted.py", "docs/scripted-profiling.md")
ORIGINAL = "artifacts/profiling/20261010-v1"
ORIGINAL_REVISION = "d71a05d35f8c95df930d957ff4ebecc2ef3b0b72"
ORIGINAL_HASHES = {
    "profile.json": "a9f1a202f0400cdca50beca6b7ac9c6d06f044ab0a3ae298b0b7ceb821e9a167",
    "episodes.jsonl": "14825518abf5063d3422c78ba0515ce377c71d533b6c4d3aad1982ad6d0a12a9",
    "profile.md": "7d66e175de00dc9f74dc0a862b0e71cdcb70c59ff8043383f777fb5fb8bfaa46",
    "producer.py": "ac0d5d7279c16235ab02ef89bf6f86a2744cefb7fbf8483a3f9ee0914aebb449",
}


class ProfileStopped(RuntimeError):
    """A safe fixed message explaining why no further work is allowed."""


def plan() -> dict:
    return {"schema": "world-engine.scripted-profile-plan.v1", "worlds": list(WORLDS),
            "seeds": list(range(EPISODES)), "trial_order_per_world": list(TRIALS),
            "provider": "scripted-oracle", "max_steps": 20, "episode_seconds": 30,
            "concurrency": 1, "evaluation_only": True, "training_eligible": False,
            "scheduled_episodes": len(WORLDS) * EPISODES * len(TRIALS),
            "replay_phase": {"trial": "profiled", "episodes": 96},
            "sqlite_phases": {"append": 96, "list_operations": 100, "detail_operations": 40,
                              "runs_per_list": 4, "episodes_per_crm_detail": 24},
            "expected_decisions_per_trial": dict(zip(WORLDS, DECISIONS, strict=True)),
            "observation_reads": {world: {"historical": old, "current": new,
                                          "setup_reads_per_episode": setup,
                                          "formula": "2 * decisions + setup_reads_per_episode * episodes"}
                                  for world, old, new, setup in zip(WORLDS, OLD_OBSERVATIONS,
                                                                 NEW_OBSERVATIONS, SETUP_OBSERVATIONS, strict=True)},
            "overall_seconds": OVERALL_SECONDS, "finalize_reserve_seconds": FINALIZE_SECONDS,
            "artifact_cap": ARTIFACT_CAP, "report_reserve": REPORT_RESERVE,
            "original": {"directory": ORIGINAL, "revision": ORIGINAL_REVISION,
                         "sha256": ORIGINAL_HASHES, "producer_was_retrospective_sidecar": True},
            "status": "plan-only; no episodes, database, profiler or source commands executed"}


def source_identity(expected: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise ProfileStopped("source revision must be a reviewed full lowercase SHA")

    def git(*args):
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                              check=True, timeout=3).stdout.strip()

    if git("rev-parse", "HEAD") != expected or git("status", "--porcelain", "--untracked-files=all", "--", *SOURCE_SCOPE):
        raise ProfileStopped("runtime, dependencies and profiling source must be committed and clean")
    files = [*sorted((ROOT / "src/world_engine").rglob("*.py")),
             *(ROOT / item for item in SOURCE_SCOPE if not (ROOT / item).is_dir())]
    original = {}
    for name, expected_hash in ORIGINAL_HASHES.items():
        path = ROOT / ORIGINAL / name
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected_hash:
            raise ProfileStopped("historical profiling evidence changed")
        original[name] = actual
    return {"git_revision": expected, "source_dirty": False, "scope": list(SOURCE_SCOPE),
            "checkout_dirty": bool(git("status", "--porcelain", "--untracked-files=all")),
            "files_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
            "original_files_sha256": original}


def artifact_bytes(output: Path) -> int:
    return sum(p.stat().st_size for p in output.iterdir() if p.is_file())


def write_file(output: Path, name: str, data: bytes, *, reserve: int = REPORT_RESERVE) -> None:
    if artifact_bytes(output) + len(data) + reserve > ARTIFACT_CAP:
        raise ProfileStopped("artifact cap reached; existing evidence retained")
    with (output / name).open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def save_episode(raw, output: Path, slot: dict, episode) -> None:
    record = {"schema": "world-engine.scripted-profile-episode.v1", "slot": {
        key: slot[key] for key in ("world", "trial", "index")}, "episode": episode,
        "evaluation_only": True, "training_eligible": False, "exact_envelope_preserved": True}
    try:
        data = (canonical_json(record) + "\n").encode()
    except (TypeError, ValueError, OverflowError, RecursionError):
        data = b""
    exact = bool(data) and artifact_bytes(output) + len(data) + REPORT_RESERVE + 1024 <= ARTIFACT_CAP
    if not exact:
        record.update(episode=None, exact_envelope_preserved=False,
                      diagnostic="envelope cannot serialize or fit raw cap; exact evidence not preserved")
        data = (canonical_json(record) + "\n").encode()
    if artifact_bytes(output) + len(data) + REPORT_RESERVE > ARTIFACT_CAP:
        raise ProfileStopped("diagnostic cannot fit reserved artifact cap")
    raw.write(data)
    raw.flush()
    os.fsync(raw.fileno())
    slot["status"] = "persisted" if exact else "diagnostic_saved"
    if not exact:
        raise ProfileStopped("current envelope not preserved; remaining work stopped")


def profile_snapshot(output: Path, name: str, profile, *, world: str | None = None) -> dict:
    with tempfile.TemporaryDirectory(prefix="world-engine-profile-stats-") as temporary:
        path = Path(temporary) / "stats.prof"
        profile.dump_stats(str(path))
        if path.stat().st_size > ARTIFACT_CAP - REPORT_RESERVE:
            raise ProfileStopped("profile statistics exceed artifact cap")
        write_file(output, name + ".prof", path.read_bytes())
    stream = io.StringIO()
    stats = pstats.Stats(profile, stream=stream).strip_dirs().sort_stats("cumulative")
    stats.print_stats(50)
    write_file(output, name + ".txt", stream.getvalue().encode())
    entries = [{"file": file, "line": line, "function": function, "primitive_calls": primitive,
                "calls": calls, "exclusive_seconds": exclusive, "cumulative_seconds": cumulative}
               for (file, line, function), (primitive, calls, exclusive, cumulative, _) in pstats.Stats(profile).stats.items()]
    result = {"total_profiled_seconds": stats.total_tt, "total_calls": stats.total_calls,
              "top_cumulative": sorted(entries, key=lambda row: row["cumulative_seconds"], reverse=True)[:50],
              "top_exclusive": sorted(entries, key=lambda row: row["exclusive_seconds"], reverse=True)[:50]}
    if world is not None:
        code = ENVIRONMENTS[world].observe.__code__
        key = (code.co_filename, code.co_firstlineno, code.co_name)
        result["observe_function"] = {"file": key[0], "line": key[1], "function": key[2]}
        result["observe_calls"] = pstats.Stats(profile).stats.get(key, (0, 0, 0, 0, {}))[1]
    return result


def check_trial(episodes: list[dict], world: str, revision: str) -> dict:
    if len(episodes) != EPISODES:
        raise ProfileStopped("trial ended before all fixed episodes returned")
    if any(e["seed"] != i or e["index"] != i or e["provenance"]["environment_id"] != world
           or e["provenance"].get("git_revision") != revision
           or e["provenance"].get("implementation_dirty") is not False
           or e["provenance"].get("evaluation_only") is not True
           or e["provenance"]["provider_id"] != "scripted-oracle"
           or e["passed"] is not True or e["status"] != "completed" or e["termination"] != "finished"
           or e["invalid_actions"] != 0 or e["error"] is not None for i, e in enumerate(episodes)):
        raise ProfileStopped("fixed scripted trial differs from trusted successful workload")
    decisions = sum(e["steps"] for e in episodes)
    if decisions != DECISIONS[WORLDS.index(world)]:
        raise ProfileStopped("fixed decision workload changed")
    return {"episodes": len(episodes), "decisions": decisions, "passed": len(episodes),
            "invalid_actions": 0, "errors": 0, "episode_seconds": [e["elapsed_seconds"] for e in episodes],
            "episode_sha256": [digest(e) for e in episodes], "scenario_ids": [e["scenario_id"] for e in episodes]}


def comparable_trials(left: list[dict], right: list[dict]) -> bool:
    keys = ("scenario_id", "lineage_id", "split", "initial_observation", "initial_snapshot",
            "final_observation", "final_snapshot", "final_state_hash", "grader", "reward", "passed")
    return all(canonical_json({k: a[k] for k in keys}) == canonical_json({k: b[k] for k in keys})
               and canonical_json([s["action"] for s in a["trace"]]) == canonical_json([s["action"] for s in b["trace"]])
               for a, b in zip(left, right, strict=True))


def machine_metadata() -> dict:
    values = {}
    for key in ("hw.model", "hw.memsize", "machdep.cpu.brand_string"):
        try:
            result = subprocess.run(["sysctl", "-n", key], capture_output=True, text=True, timeout=2)
            values[key] = result.stdout.strip() if result.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            values[key] = None
    return {"runtime": platform.python_version(), "platform": platform.platform(),
            "machine": platform.machine(), "cpu_count": os.cpu_count(), "machine_metadata": values}


def write_report(output: Path, report: dict) -> None:
    report.update(artifacts_bytes_before_report=artifact_bytes(output), report_bytes=0, artifact_total_bytes=0)
    data = b""
    while report["report_bytes"] != len(data) or not data:
        report["report_bytes"] = len(data)
        report["artifact_total_bytes"] = report["artifacts_bytes_before_report"] + len(data)
        data = (json.dumps(report, indent=2, allow_nan=False) + "\n").encode()
    if len(data) > REPORT_RESERVE:
        raise ProfileStopped("report exceeds reserved bytes; raw retained")
    write_file(output, "profile.json", data, reserve=0)


async def collect(output: Path, expected_revision: str) -> dict:
    started = time.perf_counter()
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    source = source_identity(expected_revision)
    if tuple(ENVIRONMENTS) != WORLDS:
        raise ProfileStopped("world registry differs from the original four-world order")
    scheduled = [{"world": world, "trial": trial, "index": index, "status": "not_attempted"}
                 for world in WORLDS for trial in TRIALS for index in range(EPISODES)]
    report = {"schema": "world-engine.scripted-profile.v1", "created_at": utc_now(), "source": source,
              "plan": plan(), "slots": scheduled, "worlds": [], "phases": [],
              "evaluation_only": True, "training_eligible": False, "model_calls": 0,
              "database": "isolated TemporaryDirectory; never the API or primary database",
              "raw_durability": "fsynced after each 24-episode block; not mid-block crash durable",
              "limitations": ["Ordering, cold caches and shared-machine load are uncontrolled; no causal speedup claim.",
                              "cProfile changes timing; nested cumulative values are not additive.",
                              "Deadline guards differ from the original ad-hoc producer; workloads and phase sizes match.",
                              "Observation counts include factory reset calls; unprofiled reads are not instrumented.",
                              "240-second deadline is cooperative for trusted Python; not a hard process or memory sandbox.",
                              "64 MiB bounds all output files, not in-process memory or temporary profile/SQLite files.",
                              "Both trials are retained; only the original 96 profiled episodes enter measured replay/SQLite phases."]}
    profiled, current, stopped, temporary_path = {}, None, None, None

    def deadline():
        if time.perf_counter() - started > OVERALL_SECONDS - FINALIZE_SECONDS:
            raise ProfileStopped("collection deadline reached; completed evidence retained")

    def unchanged():
        if source_identity(expected_revision)["files_sha256"] != source["files_sha256"]:
            raise ProfileStopped("source changed during profiling")

    with (output / "episodes.jsonl").open("xb") as raw:
        try:
            collection_revision.cache_clear()
            remaining = OVERALL_SECONDS - FINALIZE_SECONDS - (time.perf_counter() - started)
            if remaining <= 0:
                raise ProfileStopped("collection deadline exhausted before episodes")
            async with asyncio.timeout(remaining):
                for world in WORLDS:
                    unchanged()
                    config = RunConfig(environment_id=world, provider_id="scripted-oracle", episodes=EPISODES,
                                       seed=0, max_steps=20, timeout_seconds=30, concurrency=1,
                                       evaluation_only=True, label="CPU profile: synthetic scripted reference only")
                    world_row = {"environment_id": world, "config": config.model_dump()}
                    report["worlds"].append(world_row)
                    plain = []
                    for trial in TRIALS:
                        if artifact_bytes(output) + REPORT_RESERVE + 1024 > ARTIFACT_CAP:
                            raise ProfileStopped("no next block diagnostic reservation")
                        episodes, profile = [], cProfile.Profile() if trial == "profiled" else None
                        trial_start = time.perf_counter()
                        if profile is not None:
                            profile.enable()
                        try:
                            for current in (s for s in scheduled if s["world"] == world and s["trial"] == trial):
                                deadline()
                                current["status"] = "attempt_started"
                                episode = await rollout(config, current["index"])
                                current["status"] = "returned"
                                episodes.append(episode)
                                current = None
                        finally:
                            if profile is not None:
                                profile.disable()
                            wall = time.perf_counter() - trial_start
                            for slot, episode in zip((s for s in scheduled if s["world"] == world and s["trial"] == trial), episodes):
                                save_episode(raw, output, slot, episode)
                            world_row[trial] = {"returned_episodes": len(episodes), "wall_seconds": wall,
                                                "episodes_per_second": len(episodes) / wall if wall else None}
                        world_row[trial].update(check_trial(episodes, world, expected_revision))
                        if profile is not None:
                            world_row[trial].update(profile_snapshot(output, world + "-rollout", profile, world=world))
                            expected = NEW_OBSERVATIONS[WORLDS.index(world)]
                            if world_row[trial]["observe_calls"] != expected:
                                raise ProfileStopped("observation read count differs from fixed current formula")
                            if not comparable_trials(plain, episodes):
                                raise ProfileStopped("paired scripted trials differ in actions or trusted states")
                            world_row["trials_logically_matched"] = True
                            profiled[world] = episodes
                        else:
                            plain = episodes
                        deadline()
                unchanged()
                profile = cProfile.Profile()
                phase = {"phase": "trusted-replay", "attempted": 0, "verified": 0}
                report["phases"].append(phase)
                phase_start = time.perf_counter()
                profile.enable()
                try:
                    for episodes in profiled.values():
                        for episode in episodes:
                            deadline()
                            phase["attempted"] += 1
                            if replay(episode)["verified"] is not True:
                                raise ProfileStopped("trusted replay rejected current envelope")
                            phase["verified"] += 1
                finally:
                    profile.disable()
                    phase["wall_seconds"] = time.perf_counter() - phase_start
                phase.update(profile_snapshot(output, "trusted-replay", profile))
                with tempfile.TemporaryDirectory(prefix="world-engine-cpu-profile-") as temporary:
                    temporary_path = Path(temporary)
                    report["temporary_database_removed"] = False
                    store = Store(temporary_path / "profile.sqlite3")
                    for world_row in report["worlds"]:
                        store.create_run(world_row["environment_id"], RunConfig.model_validate(world_row["config"]))
                    for name, count, operation in (
                        ("sqlite-append", 96, lambda index: store.append_episode(WORLDS[index // EPISODES],
                                                                                 profiled[WORLDS[index // EPISODES]][index % EPISODES])),
                        ("sqlite-list-page", 100, lambda index: store.list_runs(limit=100, offset=0)),
                        ("sqlite-detail-24", 40, lambda index: store.get_run(WORLDS[0], detail=True)),
                    ):
                        if name == "sqlite-list-page":
                            for world_row in report["worlds"]:
                                store.update_run(world_row["environment_id"], "completed", elapsed=world_row["unprofiled"]["wall_seconds"])
                        phase = {"phase": name, "scheduled_operations": count, "completed_operations": 0}
                        report["phases"].append(phase)
                        results, profile = [], cProfile.Profile()
                        phase_start = time.perf_counter()
                        profile.enable()
                        try:
                            for index in range(count):
                                deadline()
                                results.append(operation(index))
                                phase["completed_operations"] += 1
                        finally:
                            profile.disable()
                            phase["wall_seconds"] = time.perf_counter() - phase_start
                        phase.update(profile_snapshot(output, name, profile))
                        del results
                report["temporary_database_removed"] = not Path(temporary).exists()
        except (Exception, asyncio.CancelledError) as error:
            stopped = str(error) if isinstance(error, ProfileStopped) else f"collector failed: {type(error).__name__}; details redacted"
            if current is not None and current["status"] == "attempt_started":
                current["status"] = "attempted_without_final_episode"
        finally:
            if temporary_path is not None:
                report["temporary_database_removed"] = not temporary_path.exists()
            try:
                unchanged()
            except Exception:
                stopped = stopped or "final source verification failed"
            metadata = machine_metadata()
            if time.perf_counter() - started > OVERALL_SECONDS:
                stopped = stopped or "overall duration exceeded"
            report.update(status="stopped" if stopped else "completed", stop_reason=stopped,
                          scheduled_episodes=len(scheduled), attempted_episodes=sum(s["status"] != "not_attempted" for s in scheduled),
                          persisted_episodes=sum(s["status"] == "persisted" for s in scheduled),
                          diagnostic_episodes=sum(s["status"] == "diagnostic_saved" for s in scheduled),
                          unattempted_episodes=sum(s["status"] == "not_attempted" for s in scheduled),
                          returned_without_persistence=sum(s["status"] == "returned" for s in scheduled),
                          raw_sha256=hashlib.sha256((output / "episodes.jsonl").read_bytes()).hexdigest(),
                          execution_seconds=time.perf_counter() - started, **metadata)
            write_report(output, report)
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
            parser.error("collection flags require --collect")
        print(json.dumps(plan(), indent=2))
        return 0
    if args.output is None or not args.source_revision or not re.fullmatch(r"[0-9a-f]{40}", args.source_revision):
        parser.error("--collect requires reviewed full --source-revision and fresh --output")
    result = asyncio.run(collect(args.output, args.source_revision))
    print(canonical_json({"status": result["status"], "persisted_episodes": result["persisted_episodes"],
                          "stop_reason": result["stop_reason"]}))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
