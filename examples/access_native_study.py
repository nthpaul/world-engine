"""Locked eight-case native access integration study; default plan has no provider contact."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import subprocess
import time
from pathlib import Path

from world_engine.environments import make_environment
from world_engine.models import RunConfig, canonical_json, digest, utc_now
from world_engine.ollama_tools import PROTOCOL, OllamaToolsProvider, contract
from world_engine.rollout import collection_revision, replay, rollout, world_fingerprints

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SCOPE = ["src/world_engine", "pyproject.toml", "uv.lock", "examples/access_native_study.py",
                "tests/test_access_native_study.py", "docs/access-native-study.md"]
MODEL = "qwen3:8b"
MODEL_DIGEST = "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41"
WORLD, VERSION = "access-provisioning", "1.0.0"
ENVIRONMENT_HASH = "6554a45b3c38fbc6718735890fb3d9c5734ff11e20f65a7ba9195c4e52ab1ed8"
GRADER_HASH = "6f6e7dfa28e087a141b78d1d0835106f99283ccf11ec4709144a2bc1f4e1dd78"
INITIAL_HASHES = (
    "ceec376206e9067ff551e1b8897c2db35f016e53e2c7f010b7adf3adb36ec71f",
    "40c60aaf51398a39594330bfe55a3cefbd2659b877f35c2641f6d8f74ec57fd3",
    "f0a3207b21c80a7c4a4b7d562218c14b75f41f15123d91a2b56eba26f7c9d473",
    "728277f6837f4d39bf7cf9246cdccfdc87f7105bdc6399d677221bca144e444b",
    "c6ce86ce4c7d573311608e48a45d39332fc46a8e6467bdc8c6bb7f8b603f55b1",
    "4742c6af9fd9aa26da53bd9bc492b6077acbcb84bfebe0fe13bbc47788d8a5e1",
    "87338b4e33c0979e31f284a8b04ced2d04c9c1470fb4b2820026eeae581363ac",
    "fc298fcc1cb0b17ead693df6814e8d45fcaa39c38291446f11136ee364a5dbad",
)
MAX_STEPS, EPISODE_SECONDS, OVERALL_SECONDS = 20, 35, 600
CLEANUP_SECONDS, FINALIZE_RESERVE_SECONDS = 3, 15
ARTIFACT_CAP, EPISODE_RESERVE, REPORT_RESERVE = 64 * 1024**2, 24 * 1024**2, 1024**2
NATIVE_CONTRACT_HASH = "0e57c609b4ef58ab4e28551997d9839f0bdd532bd80f6bd3c9fc3bbf4d3a688b"
PROTOCOL_SHA256 = "9aa85f8ab1d5bae48b1c9231d6649cf274d80377059ae6e0fd85c6ad6ff2fc76"


class StudyStopped(RuntimeError):
    """Stop collection without changing previously saved evidence."""


def slots() -> list[dict]:
    return [{"index": seed, "world": WORLD, "seed": seed, "case": seed, "policy": "native"}
            for seed in range(8)]


def protocol() -> dict:
    return {"id": "access-native-integration-v1", "slots": slots(), "world_version": VERSION,
            "environment_hash": ENVIRONMENT_HASH, "grader_hash": GRADER_HASH,
            "initial_state_hashes": INITIAL_HASHES, "native_contract_hash": NATIVE_CONTRACT_HASH,
            "model": MODEL, "model_digest": MODEL_DIGEST, "max_steps": MAX_STEPS,
            "episode_seconds": EPISODE_SECONDS, "overall_seconds": OVERALL_SECONDS,
            "concurrency": 1, "max_model_episode_attempts": 8, "max_model_requests": 160,
            "options": {"temperature": 0, "num_predict": 512, "num_ctx": 8192}, "think": False,
            "cleanup_seconds": CLEANUP_SECONDS, "finalize_reserve_seconds": FINALIZE_RESERVE_SECONDS,
            "artifact_cap": ARTIFACT_CAP, "next_episode_reserve": EPISODE_RESERVE,
            "report_reserve": REPORT_RESERVE, "retry_policy": "none", "evaluation_only": True,
            "training_eligible": False, "controls": "separate scripted access receipt; not paired"}


def plan() -> dict:
    if digest(protocol()) != PROTOCOL_SHA256 or digest(contract()) != NATIVE_CONTRACT_HASH:
        raise StudyStopped("protocol differs from the locked review")
    for seed, expected in enumerate(INITIAL_HASHES):
        world = make_environment(WORLD, seed)
        if (world.version != VERSION or digest(world.snapshot()) != expected
                or world_fingerprints(world) != (ENVIRONMENT_HASH, GRADER_HASH)
                or len(canonical_json(world.observe()).encode()) > 32 * 1024):
            raise StudyStopped("public synthetic fixture differs from locked fingerprints")
    components = {"provider_events": 8 * 1024**2,
                  "trace": MAX_STEPS * ((132 + 384 + 64 + 64 + 4) * 1024),
                  "snapshots_metadata_and_wrapper": 1024**2}
    if sum(components.values()) > EPISODE_RESERVE:
        raise StudyStopped("fixed-world capacity exceeds next-episode reservation")
    return {"protocol": protocol(), "protocol_sha256": digest(protocol()),
            "reservation_bound": {"components_bytes": components, "derived_upper_bytes": sum(components.values()),
                                  "scope": "fixed access world and bounded recorder/actions; not hostile-host proof"},
            "status": "plan-only; no provider contact or inference"}


def source_identity(expected: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise StudyStopped("source revision must be a reviewed full lowercase commit SHA")

    def git(*args):
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                              timeout=3, check=True).stdout.strip()

    if git("rev-parse", "HEAD") != expected or git("status", "--porcelain", "--untracked-files=all", "--", *SOURCE_SCOPE):
        raise StudyStopped("authorized runtime/collector/test/protocol must be committed and clean")
    files = [*sorted((ROOT / "src/world_engine").rglob("*.py")),
             *(ROOT / path for path in SOURCE_SCOPE if not (ROOT / path).is_dir())]
    return {"git_revision": expected, "source_dirty": False, "scope": SOURCE_SCOPE,
            "files_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files},
            "checkout_dirty": bool(git("status", "--porcelain", "--untracked-files=all"))}


def artifact_bytes(output: Path) -> int:
    return sum(path.stat().st_size for path in output.iterdir() if path.is_file())


def append_raw(handle, record: dict, output: Path) -> bool:
    data = (canonical_json(record) + "\n").encode()
    if artifact_bytes(output) + len(data) + REPORT_RESERVE > ARTIFACT_CAP:
        raise StudyStopped("unexpected raw-size violation; collection inconclusive")
    handle.write(data)
    handle.flush()
    os.fsync(handle.fileno())
    return len(data) <= EPISODE_RESERVE


def make_provider():
    return OllamaToolsProvider(RunConfig(environment_id=WORLD, provider_id="local", model=MODEL,
                                        evaluation_only=True, allow_paid=False))


def check_episode(episode: dict, slot: dict, source: dict, evidence: dict) -> dict:
    v = episode["provenance"]
    if (episode["seed"] != slot["seed"] or v["environment_id"] != WORLD or v["environment_version"] != VERSION
            or v["environment_code_hash"] != ENVIRONMENT_HASH or v["grader_code_hash"] != GRADER_HASH
            or v["initial_state_hash"] != INITIAL_HASHES[slot["seed"]]
            or v["evaluation_only"] is not True or v.get("training_eligible") is not False
            or v.get("git_revision") != source["git_revision"] or v.get("implementation_dirty") is not False
            or v.get("provider_protocol") != PROTOCOL or v.get("provider_evidence") != evidence
            or v.get("model") != MODEL or v.get("model_digest") != MODEL_DIGEST):
        raise StudyStopped("episode identity differs from its locked case/source/provider")
    row = {key: episode[key] for key in ("passed", "reward", "status", "termination", "steps",
                                        "invalid_actions", "elapsed_seconds", "usage")}
    if (type(row["passed"]) is not bool or type(row["steps"]) is not int or not 0 <= row["steps"] <= MAX_STEPS
            or type(row["invalid_actions"]) is not int or not 0 <= row["invalid_actions"] <= row["steps"]
            or row["status"] not in {"completed", "failed", "cancelled"}
            or row["termination"] not in {"finished", "max_steps", "internal_error", "provider_error", "timeout", "cancelled"}
            or not isinstance(row["usage"], dict)):
        raise StudyStopped("malformed episode summary; raw retained")
    for key in ("reward", "elapsed_seconds"):
        if type(row[key]) not in (int, float) or not math.isfinite(row[key]) or row[key] < 0:
            raise StudyStopped("malformed episode numeric summary; raw retained")
    if row["reward"] > 1:
        raise StudyStopped("malformed reward range; raw retained")
    row["model_request_attempts"] = sum(ev["event"] == "request_started" for ev in episode["provider_events"])
    if row["model_request_attempts"] > MAX_STEPS or replay(episode)["verified"] is not True:
        raise StudyStopped("request cap/replay mismatch; raw retained")
    row.update(clean_success=row["passed"] and row["invalid_actions"] == 0,
               replay_verified=True, outcome_integrity=True)
    return row


def write_report(output: Path, report: dict) -> None:
    report.update(artifacts_bytes_before_report=artifact_bytes(output), report_bytes=0, artifact_total_bytes=0)
    data = (json.dumps(report, indent=2, allow_nan=False) + "\n").encode()
    while report["report_bytes"] != len(data):
        report["report_bytes"] = len(data)
        report["artifact_total_bytes"] = report["artifacts_bytes_before_report"] + len(data)
        data = (json.dumps(report, indent=2, allow_nan=False) + "\n").encode()
    if len(data) > REPORT_RESERVE or artifact_bytes(output) + len(data) > ARTIFACT_CAP:
        raise StudyStopped("report cap exceeded; raw retained")
    with (output / "report.json").open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


async def collect(output: Path, expected_revision: str) -> dict:
    started = time.monotonic()
    # Exclusive leaf reservation precedes source subprocesses and provider preparation.
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    source, study_plan = source_identity(expected_revision), plan()
    scheduled = [{**slot, "status": "not_attempted"} for slot in slots()]
    rows, cleanup_errors = [], []
    report = {"schema": "world-engine.access-native-study.v1", "created_at": utc_now(), "source": source,
              "plan": study_plan, "slots": scheduled, "rows": rows, "evaluation_only": True,
              "training_eligible": False, "paid_calls": 0, "model_downloaded": False,
              "raw_durability": "finalized rows fsynced before next request; not mid-episode crash durable"}
    provider, current, row, stopped = None, None, None, None
    raw_path = output / "evaluation-episodes.jsonl"
    with raw_path.open("xb") as raw:
        try:
            remaining = OVERALL_SECONDS - FINALIZE_RESERVE_SECONDS - (time.monotonic() - started)
            if remaining <= 0:
                raise StudyStopped("wall cap exhausted before provider preparation")
            async with asyncio.timeout(remaining):
                provider = make_provider()
                await provider.prepare()
                if provider.model != MODEL or provider.model_digest != MODEL_DIGEST:
                    raise StudyStopped("installed model name/digest differs before first chat")
                evidence = report["provider_evidence"] = provider.evidence_metadata()
                if evidence.get("native_contract_hash") != NATIVE_CONTRACT_HASH:
                    raise StudyStopped("prepared provider contract differs before first chat")
                collection_revision.cache_clear()
                for slot in scheduled:
                    if artifact_bytes(output) + EPISODE_RESERVE + REPORT_RESERVE > ARTIFACT_CAP:
                        raise StudyStopped("artifact cap: no next episode reservation")
                    if source_identity(expected_revision)["files_sha256"] != source["files_sha256"] or plan() != study_plan:
                        raise StudyStopped("source/fixture changed before next request")
                    if time.monotonic() - started + EPISODE_SECONDS + FINALIZE_RESERVE_SECONDS > OVERALL_SECONDS:
                        raise StudyStopped("wall cap: no next complete episode budget")
                    current, row = slot, None
                    slot["status"] = "attempt_started"
                    config = RunConfig(environment_id=WORLD, provider_id="local", model=MODEL, seed=slot["seed"],
                                       episodes=1, concurrency=1, max_steps=MAX_STEPS, timeout_seconds=EPISODE_SECONDS,
                                       evaluation_only=True, allow_paid=False, label="locked native access integration; operator-only")
                    episode = await rollout(config, 0, provider)
                    within = append_raw(raw, {"schema": "world-engine.evaluation-trace.v1", "slot": slots()[slot["index"]],
                                              "evaluation_only": True, "training_eligible": False, "episode": episode}, output)
                    slot["status"] = "finalized"
                    row = {**slots()[slot["index"]], "passed": False, "clean_success": False, "episode_available": True,
                           "outcome_integrity": False, "replay_verified": False, "usage": {}, "model_request_attempts": None,
                           "observed_passed": episode.get("passed") if isinstance(episode, dict)
                           and type(episode.get("passed")) is bool else None}
                    events = episode.get("provider_events") if isinstance(episode, dict) else None
                    if isinstance(events, list) and all(isinstance(event, dict) for event in events):
                        row["model_request_attempts"] = sum(event.get("event") == "request_started" for event in events)
                    rows.append(row)
                    if not within:
                        raise StudyStopped("episode reservation exceeded; full raw retained, no next request")
                    row.update(check_episode(episode, slot, source, evidence))
                    if episode["status"] == "cancelled":
                        raise StudyStopped("handled cancelled episode retained; no next request")
                    current, row = None, None
        except (Exception, asyncio.CancelledError) as error:
            stopped = str(error) if isinstance(error, StudyStopped) else f"provider-harness: {type(error).__name__}; details redacted"
            if current is not None and current["status"] == "attempt_started":
                current["status"] = "attempted_without_final_episode"
                append_raw(raw, {"slot": current, "episode": None, "attempt_error": stopped,
                                 "evaluation_only": True, "training_eligible": False}, output)
                rows.append({**slots()[current["index"]], "passed": False, "clean_success": False,
                             "episode_available": False, "replay_verified": False, "outcome_integrity": False,
                             "usage": {}, "model_request_attempts": None})
            elif row is not None:
                row.update(passed=False, clean_success=False, outcome_integrity=False)
                current["status"] = "finalized_inconclusive"
        finally:
            if provider is not None:
                try:
                    await asyncio.wait_for(provider.close(), timeout=CLEANUP_SECONDS)
                except (Exception, asyncio.CancelledError) as error:
                    cleanup_errors.append({"error_type": type(error).__name__, "resource_closed": False})
                    stopped = stopped or "provider cleanup failed; actual resource closure unconfirmed"
            try:
                final_source = source_identity(expected_revision)
                report["final_checkout_dirty"] = final_source.get("checkout_dirty")
                if final_source["files_sha256"] != source["files_sha256"]:
                    stopped = stopped or "source changed during final attempt/cleanup"
            except Exception:
                stopped = stopped or "final source verification failed"
            if time.monotonic() - started > OVERALL_SECONDS:
                stopped = stopped or "aggregate duration exceeded; receipt stopped"
            attempts = [value["model_request_attempts"] for value in rows]
            report.update(status="stopped" if stopped else "completed", stop_reason=stopped,
                          cleanup_errors=cleanup_errors, elapsed_seconds=time.monotonic() - started,
                          attempted_episodes=len(rows), unattempted_episodes=sum(s["status"] == "not_attempted" for s in scheduled),
                          finalized_episodes=sum(value["episode_available"] for value in rows),
                          verified_episodes=sum(value["replay_verified"] for value in rows),
                          inconclusive_episodes=sum(not value["outcome_integrity"] for value in rows),
                          business_passes=sum(value["passed"] for value in rows), clean_passes=sum(value["clean_success"] for value in rows),
                          model_request_attempts=sum(a for a in attempts if a is not None),
                          model_request_attempts_complete=all(a is not None for a in attempts),
                          raw_sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest())
            write_report(output, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="Default; no provider contact")
    mode.add_argument("--collect", action="store_true", help="Authorized local inference only")
    parser.add_argument("--source-revision")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not args.collect:
        if args.output is not None or args.source_revision is not None:
            parser.error("collection arguments require --collect")
        print(json.dumps(plan(), indent=2))
        return 0
    if args.output is None or not args.source_revision or not re.fullmatch(r"[0-9a-f]{40}", args.source_revision):
        parser.error("--collect requires reviewed full --source-revision and fresh --output")
    result = asyncio.run(collect(args.output, args.source_revision))
    print(canonical_json({"status": result["status"], "finalized_episodes": result["finalized_episodes"],
                          "stop_reason": result["stop_reason"]}))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
