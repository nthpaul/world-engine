"""Locked matched local-adapter study; printing its plan never contacts a provider."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import platform
import random
import re
import subprocess
import time
from importlib import metadata
from pathlib import Path

from world_engine.environments import make_environment
from world_engine.models import RunConfig, canonical_json, digest, utc_now
from world_engine.ollama_tools import PROTOCOL, OllamaToolsProvider, contract
from world_engine.providers import HTTPProvider, ScriptedProvider, json_evidence_contract
from world_engine.rollout import collection_revision, replay, rollout, world_fingerprints

MODEL = "qwen3:8b"
MODEL_DIGEST = "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41"
VERSIONS = {"crm-merge": "1.1.1", "refund-ops": "1.1.2", "incident-control": "1.0.1"}
SEEDS = {"crm-merge": tuple(range(1000000, 1000008)), "refund-ops": tuple(range(1000104, 1000120)),
         "incident-control": (1000200, 1000201, 1000202, 1000203, 1000204, 1000206, 1000208, 1000210)}
NATIVE_FIRST_INCIDENT = {1000200, 1000201, 1000202, 1000206}
MAX_STEPS, EPISODE_SECONDS, OVERALL_SECONDS = 20, 35, 2700
PROTOCOL_SHA256 = "6abb1350ea008d962624bc2561bb486b461ffd426a01cbd1bfcd51c33ff391bc"
ARTIFACT_CAP = 64 * 1024 * 1024
# Recorder <=8 MiB; twenty bounded wire contexts/actions plus fixed workflow
# snapshots fit in the remainder. No duplicate SQLite/ATIF files are generated.
EPISODE_RESERVE = 24 * 1024 * 1024
REPORT_RESERVE = 1024 * 1024
BOOTSTRAP_SAMPLES, BOOTSTRAP_SEED = 2000, 20261010
CLEANUP_RESERVE_SECONDS = 10
ROOT = Path(__file__).resolve().parents[1]
SOURCE_SCOPE = ["src/world_engine", "pyproject.toml", "uv.lock", "examples/workflow_model_study.py",
                "tests/test_workflow_model_study.py", "docs/workflow-model-study.md"]


class StudyStopped(RuntimeError):
    """A bounded collection stopped; existing raw evidence must remain available."""


def tasks() -> list[dict]:
    ordered = []
    for index, seed in enumerate(SEEDS["refund-ops"]):
        ordered.append({"world": "refund-ops", "seed": seed, "native_first": index < 8})
        world = "crm-merge" if index % 2 == 0 else "incident-control"
        other_seed = SEEDS[world][index // 2]
        ordered.append({"world": world, "seed": other_seed,
                        "native_first": index // 2 < 4 if world == "crm-merge"
                        else other_seed in NATIVE_FIRST_INCIDENT})
    return ordered


def slots() -> list[dict]:
    result = []
    for task_index, task in enumerate(tasks()):
        adapters = ["native", "json"] if task["native_first"] else ["json", "native"]
        for policy in ["oracle", "baseline", *adapters]:
            result.append({"index": len(result), "task_index": task_index,
                           "world": task["world"], "seed": task["seed"], "policy": policy})
    return result


def protocol() -> dict:
    return {"id": "workflow-matched-adapters-v1", "world_versions": VERSIONS, "slots": slots(),
            "model": MODEL, "model_digest": MODEL_DIGEST, "max_steps": MAX_STEPS,
            "episode_seconds": EPISODE_SECONDS, "overall_seconds": OVERALL_SECONDS,
            "concurrency": 1, "max_model_attempts": 64, "max_model_decisions": 1280,
            "options": {"temperature": 0, "num_predict": 512, "num_ctx": 8192}, "think": False,
            "artifact_cap": ARTIFACT_CAP, "next_episode_reserve": EPISODE_RESERVE,
            "report_reserve": REPORT_RESERVE, "bootstrap_samples": BOOTSTRAP_SAMPLES,
            "bootstrap_seed": BOOTSTRAP_SEED, "cleanup_reserve_seconds": CLEANUP_RESERVE_SECONDS,
            "controls_order": "oracle, baseline, adapter pair",
            "retry_policy": "none; one attempt per slot", "evaluation_only": True}


def plan() -> dict:
    if digest(protocol()) != PROTOCOL_SHA256:
        raise StudyStopped("protocol differs from the reviewed fixed plan")
    # Fixtures are public synthetic operator metadata, not model requests.
    fixtures = []
    for task in tasks():
        world = make_environment(task["world"], task["seed"])
        if world.version != VERSIONS[world.id]:
            raise StudyStopped("world version differs from the locked protocol")
        if len(canonical_json(world.observe()).encode()) > 32 * 1024:
            raise StudyStopped("fixture exceeds the fixed-world artifact reservation bound")
        environment_hash, grader_hash = world_fingerprints(world)
        fixtures.append({"world": world.id, "seed": task["seed"], "version": world.version,
                         "case": (f"case-{task['seed'] % (4 if world.id == 'crm-merge' else 8)}"
                                  if world.id != "incident-control" else world.initial["incidents"][0]["severity"]),
                         "initial_state_hash": digest(world.snapshot()), "environment_hash": environment_hash,
                         "grader_hash": grader_hash})
    return {"protocol": protocol(), "protocol_sha256": digest(protocol()), "fixtures": fixtures,
            "reservation_bound": reservation_bound(),
            "status": "plan-only; no provider contact or inference"}


def reservation_bound() -> dict:
    # This is scoped to the three pinned built-ins, not arbitrary Python worlds.
    # Valid audit arguments are bounded primitives; at most twenty <=1 KiB
    # certificates grow a <=32 KiB observation to less than the 64 KiB allowance.
    components = {"provider_events": 8 * 1024 * 1024,
                  "trace": MAX_STEPS * ((128 + 4 + 6 * 64 + 64 + 64 + 4) * 1024),
                  "snapshots_metadata_and_wrapper": 1024 * 1024}
    total = sum(components.values())
    if total > EPISODE_RESERVE:
        raise StudyStopped("episode reservation is smaller than the fixed-world capacity derivation")
    return {"components_bytes": components, "derived_upper_bytes": total,
            "scope": "fixed built-ins; 132 KiB contexts, 384 KiB normalized actions, 64 KiB observations/results, "
                     "4 KiB step overhead; fixed-source audit growth and raw recorder caps, not hostile-host proof"}


def source_identity(expected_revision: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", expected_revision):
        raise StudyStopped("source revision must be a reviewed full lowercase commit SHA")
    def git(*arguments):
        return subprocess.run(["git", *arguments], cwd=ROOT, text=True, capture_output=True,
                              check=True, timeout=3).stdout.strip()
    revision = git("rev-parse", "HEAD")
    if revision != expected_revision or git("status", "--porcelain", "--untracked-files=all", "--", *SOURCE_SCOPE):
        raise StudyStopped("authorized source/collector/protocol must be committed and clean")
    paths = [*sorted((ROOT / "src/world_engine").rglob("*.py")),
             *(ROOT / path for path in SOURCE_SCOPE if not (ROOT / path).is_dir())]
    return {"git_revision": revision, "source_dirty": False, "scope": SOURCE_SCOPE,
            "files_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                             for path in paths},
            "checkout_dirty": bool(git("status", "--porcelain", "--untracked-files=all"))}


def artifact_bytes(output: Path) -> int:
    # Include every file, including report temporaries; symlinks are never produced.
    return sum(path.stat().st_size for path in output.rglob("*") if path.is_file())


def machine_metadata() -> dict:
    result = {"platform": platform.platform(), "python": platform.python_version(),
              "architecture": platform.machine(), "logical_cpus": os.cpu_count(), "libraries": {}}
    for package in ("httpx", "pydantic"):
        try:
            value = metadata.version(package)
        except metadata.PackageNotFoundError:
            continue
        if isinstance(value, str) and value.isprintable() and 0 < len(value) <= 80:
            result["libraries"][package] = value
    if platform.system() == "Darwin":
        for name, key in (("machdep.cpu.brand_string", "cpu_brand"), ("hw.memsize", "memory_bytes")):
            try:
                value = subprocess.run(["/usr/sbin/sysctl", "-n", name], capture_output=True, text=True,
                                       timeout=1, check=True).stdout.strip()
                if key == "memory_bytes":
                    if value.isascii() and value.isdecimal() and len(value) <= 20 and 0 < int(value) < 2**64:
                        result[key] = int(value)
                elif value.isprintable() and 0 < len(value) <= 200:
                    result[key] = value
            except (OSError, subprocess.SubprocessError):
                continue
    return result


def reserve_next(output: Path) -> None:
    if artifact_bytes(output) + EPISODE_RESERVE + REPORT_RESERVE > ARTIFACT_CAP:
        raise StudyStopped("artifact-cap: insufficient reserved space before next attempt")


def append_raw(handle, record: dict, output: Path) -> bool:
    content = (canonical_json(record) + "\n").encode("utf-8")
    if artifact_bytes(output) + len(content) + REPORT_RESERVE > ARTIFACT_CAP:
        raise StudyStopped("unexpected raw-size bound violation; collection is inconclusive")
    handle.write(content)
    handle.flush()
    os.fsync(handle.fileno())
    return len(content) <= EPISODE_RESERVE


def failure_category(episode: dict) -> str:
    if episode["passed"]:
        return "success"
    if episode["termination"] in {"internal_error", "cancelled", "timeout"}:
        return "provider-harness"
    outcomes = {event.get("outcome") for event in episode.get("provider_events", [])
                if event.get("event") == "request_finished"}
    if outcomes & {"invalid_response", "no_tool_call", "multiple_tool_calls", "truncated_response"}:
        return "protocol"
    if episode["termination"] == "provider_error":
        return "provider-harness"
    if episode["invalid_actions"]:
        return "tool-permission-or-argument"
    return "max-steps" if episode["termination"] == "max_steps" else "valid-incorrect"


def wilson(passes: int, total: int) -> list[float] | None:
    if not total:
        return None
    z, proportion = 1.959963984540054, passes / total
    scale = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / scale
    radius = z * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total)) / scale
    return [max(0.0, center - radius), min(1.0, center + radius)]


def rate(rows: list[dict]) -> dict:
    total, passed = len(rows), sum(row["passed"] for row in rows)
    return {"attempted_unique_tasks": total, "passes": passed, "rate": passed / total if total else None,
            "wilson_95": wilson(passed, total)}


def analysis(rows: list[dict]) -> dict:
    unique = {(row["world"], row["seed"], row["policy"]) for row in rows}
    if len(unique) != len(rows):
        raise ValueError("duplicate task-policy rows would inflate the study denominator")
    adapters = {}
    for policy in ("native", "json"):
        selected = [row for row in rows if row["policy"] == policy]
        per_world = {world: rate([row for row in selected if row["world"] == world]) for world in VERSIONS}
        values = [value["rate"] for value in per_world.values()]
        adapters[policy] = {"per_world": per_world, "micro": rate(selected),
                            "clean_micro": rate([{**row, "passed": row.get("clean_success", False)} for row in selected]),
                            "equal_world_macro": sum(values) / 3 if all(value is not None for value in values) else None}
    by_task = {}
    for row in rows:
        if row["policy"] in ("native", "json"):
            by_task.setdefault((row["world"], row["seed"]), {})[row["policy"]] = (
                row["passed"] if row.get("episode_available", True) and row.get("outcome_integrity", True) else None)
    pairs = {world: [] for world in VERSIONS}
    outcomes = dict.fromkeys(("both", "native_only", "json_only", "neither"), 0)
    for (world, _), pair in by_task.items():
        if set(pair) != {"native", "json"} or any(value is None for value in pair.values()):
            continue
        native, structured = pair["native"], pair["json"]
        label = "both" if native and structured else "native_only" if native else "json_only" if structured else "neither"
        outcomes[label] += 1
        pairs[world].append(int(native) - int(structured))
    differences = [difference for group in pairs.values() for difference in group]
    rng = random.Random(BOOTSTRAP_SEED)
    micro_samples, macro_samples = [], []
    if differences:
        for _ in range(BOOTSTRAP_SAMPLES):
            sampled = {world: [rng.choice(group) for _ in group] for world, group in pairs.items() if group}
            micro_samples.append(sum(map(sum, sampled.values())) / len(differences))
            if len(sampled) == 3:
                macro_samples.append(sum(sum(group) / len(group) for group in sampled.values()) / 3)
    def interval(samples):
        ordered = sorted(samples)
        return [ordered[int(.025 * (len(ordered) - 1))], ordered[int(.975 * (len(ordered) - 1))]] if ordered else None
    return {"adapters": adapters, "paired": {"outcomes": outcomes, "complete_pairs": len(differences),
        "incomplete_pairs": sum(len(pair) != 2 or any(value is None for value in pair.values())
                                for pair in by_task.values()),
        "pairs_per_world": {world: len(group) for world, group in pairs.items()},
        "native_minus_json_micro": sum(differences) / len(differences) if differences else None,
        "native_minus_json_equal_world_macro": (sum(sum(group) / len(group) for group in pairs.values()) / 3
                                                 if all(pairs.values()) else None),
        "world_stratified_whole_pair_bootstrap_micro_95": interval(micro_samples),
        "world_stratified_whole_pair_bootstrap_macro_95": interval(macro_samples)},
        "limitations": "Fixed public fixtures, not independent population sampling or new-rule generalization; "
                        "Wilson coverage and bootstrap intervals are descriptive, not a guarantee of representativeness."}


def providers() -> dict:
    config = RunConfig(environment_id="crm-merge", provider_id="local", model=MODEL, episodes=1,
                       concurrency=1, max_steps=MAX_STEPS, timeout_seconds=EPISODE_SECONDS, evaluation_only=True)
    return {"native": OllamaToolsProvider(config), "json": HTTPProvider(config, record_calls=True),
            "oracle": ScriptedProvider(), "baseline": ScriptedProvider(oracle=False)}


def check_contracts() -> None:
    for value in (contract(), json_evidence_contract()):
        if (value["options"] != protocol()["options"] or value["think"] is not False
                or value["stream"] is not False or value["one_call_per_decision"] is not True
                or value["request_limit"] != 128 * 1024 or value["response_limit"] != 64 * 1024
                or value["episode_record_limit"] != 8 * 1024 * 1024):
            raise StudyStopped("adapter inference contract differs from the locked study")


def check_episode(episode: dict, slot: dict, study_plan: dict, source: dict) -> None:
    provenance = episode["provenance"]
    fixture = study_plan["fixtures"][slot["task_index"]]
    if (episode["seed"] != slot["seed"] or provenance["environment_id"] != slot["world"]
            or provenance["environment_version"] != VERSIONS[slot["world"]]
            or provenance["environment_code_hash"] != fixture["environment_hash"]
            or provenance["grader_code_hash"] != fixture["grader_hash"]
            or provenance["initial_state_hash"] != fixture["initial_state_hash"]
            or provenance["evaluation_only"] is not True
            or provenance.get("git_revision") != source["git_revision"]
            or provenance.get("implementation_dirty") is not False):
        raise StudyStopped("episode identity differs from its locked task")
    if slot["policy"] in {"native", "json"}:
        expected = PROTOCOL if slot["policy"] == "native" else json_evidence_contract()["protocol"]
        if (provenance.get("provider_protocol") != expected or provenance.get("training_eligible") is not False
                or provenance.get("model_digest") != MODEL_DIGEST or "provider_events" not in episode):
            raise StudyStopped("model episode lacks the locked evaluation evidence identity")


def episode_summary(episode: dict) -> dict:
    row = {key: episode[key] for key in ("passed", "reward", "status", "termination", "steps",
                                         "invalid_actions", "elapsed_seconds", "usage")}
    if (type(row["passed"]) is not bool or type(row["steps"]) is not int
            or not 0 <= row["steps"] <= MAX_STEPS or type(row["invalid_actions"]) is not int
            or not 0 <= row["invalid_actions"] <= row["steps"] or not isinstance(row["usage"], dict)
            or row["status"] not in {"completed", "failed", "cancelled"}
            or row["termination"] not in {"finished", "max_steps", "internal_error", "provider_error", "timeout", "cancelled"}):
        raise StudyStopped("malformed episode summary; raw evidence retained")
    for key in ("reward", "elapsed_seconds"):
        if type(row[key]) not in (int, float) or not math.isfinite(row[key]) or row[key] < 0:
            raise StudyStopped("malformed episode numeric summary; raw evidence retained")
    if row["reward"] > 1:
        raise StudyStopped("malformed reward range; raw evidence retained")
    return row


async def collect(output: Path, expected_revision: str) -> dict:
    started = time.monotonic()
    source = source_identity(expected_revision)
    study_plan = plan()
    check_contracts()
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    rows, stopped, cleanup_errors, active_slot, current_row = [], None, [], None, None
    scheduled = [{**slot, "status": "not_attempted"} for slot in slots()]
    report = {"schema": "world-engine.matched-study.v1", "created_at": utc_now(), "source": source,
              "plan": study_plan, "evaluation_only": True, "training_eligible": False,
              "paid_calls": 0, "model_downloaded": False, "slots": scheduled, "rows": rows,
              "machine": machine_metadata(),
              "raw_durability": "Finalized episodes flushed/fsynced before next attempt; not mid-episode crash durable"}
    pool = {}
    raw_path = output / "evaluation-episodes.jsonl"
    with raw_path.open("xb") as raw:
        try:
            pool = providers()
            remaining = OVERALL_SECONDS - CLEANUP_RESERVE_SECONDS - (time.monotonic() - started)
            if remaining <= 0:
                raise StudyStopped("wall-cap: preflight exhausted collection time")
            async with asyncio.timeout(remaining):
                # Both metadata checks finish before the first control or chat.
                for policy in ("native", "json"):
                    await pool[policy].prepare()
                    if pool[policy].model_digest != MODEL_DIGEST or pool[policy].model != MODEL:
                        raise StudyStopped("model-mismatch: predeclared installed digest/name required before any chat")
                report["provider_evidence"] = {policy: pool[policy].evidence_metadata() for policy in ("native", "json")}
                collection_revision.cache_clear()
                for slot in scheduled:
                    if time.monotonic() - started + EPISODE_SECONDS + CLEANUP_RESERVE_SECONDS > OVERALL_SECONDS:
                        raise StudyStopped("wall-cap: no next attempt permitted")
                    reserve_next(output)
                    if source_identity(expected_revision)["files_sha256"] != source["files_sha256"]:
                        raise StudyStopped("source-mismatch: runtime/collector/protocol changed")
                    if plan() != study_plan:
                        raise StudyStopped("fixture-mismatch: generated task fingerprints changed")
                    if time.monotonic() - started + EPISODE_SECONDS + CLEANUP_RESERVE_SECONDS > OVERALL_SECONDS:
                        raise StudyStopped("wall-cap: preflight left no full next-episode budget")
                    active_slot = slot
                    current_row = None
                    slot["status"] = "attempt_started"
                    config = RunConfig(environment_id=slot["world"], provider_id="local" if slot["policy"] in {"native", "json"}
                                       else "scripted-oracle" if slot["policy"] == "oracle" else "scripted-baseline",
                                       model=MODEL if slot["policy"] in {"native", "json"} else None,
                                       episodes=1, seed=slot["seed"], max_steps=MAX_STEPS, concurrency=1,
                                       timeout_seconds=EPISODE_SECONDS, evaluation_only=True, allow_paid=False,
                                       label="locked matched evaluation; operator-only")
                    episode = await rollout(config, 0, pool[slot["policy"]])
                    # Retain even an invalid envelope before validation or another request.
                    within_reserve = append_raw(raw, {"schema": "world-engine.evaluation-trace.v1", "slot": {key: slot[key] for key in
                        ("index", "task_index", "world", "seed", "policy")}, "evaluation_only": True,
                        "training_eligible": False, "episode": episode}, output)
                    slot["status"] = "finalized"
                    # Bind a conservative row to this saved slot before inspecting
                    # an untrusted envelope. A malformed later row cannot mutate its predecessor.
                    current_row = {key: slot[key] for key in ("index", "task_index", "world", "seed", "policy")}
                    current_row.update(passed=False, clean_success=False, outcome_integrity=False,
                                       replay_verified=False, episode_available=True, usage={},
                                       model_request_attempts=0, failure_category="provider-harness")
                    rows.append(current_row)
                    row = current_row
                    row.update(episode_summary(episode))
                    row.update(failure_category=failure_category(episode),
                               clean_success=episode["passed"] and episode["invalid_actions"] == 0,
                               model_request_attempts=sum(event.get("event") == "request_started"
                                                          for event in episode.get("provider_events", [])))
                    if not within_reserve:
                        raise StudyStopped("unexpected episode-size bound violation: full raw saved; no next attempt")
                    check_episode(episode, slot, study_plan, source)
                    row["replay_verified"] = replay(episode)["verified"]
                    if row["replay_verified"] is not True:
                        raise StudyStopped("replay-mismatch: raw episode retained; no next request")
                    row["outcome_integrity"] = True
                    if (row["model_request_attempts"] > MAX_STEPS or
                        sum(row["model_request_attempts"] for row in rows if row["policy"] in {"native", "json"}) > 1280):
                        raise StudyStopped("decision-cap: unexpected model attempt limit violation")
                    active_slot = None
                    current_row = None
                    if episode["status"] == "cancelled":
                        raise StudyStopped("interrupted: handled cancelled episode retained")
        except (Exception, asyncio.CancelledError) as error:
            stopped = str(error) if isinstance(error, StudyStopped) else f"provider-harness: {type(error).__name__}; details redacted"
            if active_slot is not None and active_slot["status"] == "attempt_started":
                active_slot["status"] = "attempted_without_final_episode"
                append_raw(raw, {"slot": active_slot, "attempt_error": stopped, "episode": None,
                                 "evaluation_only": True, "training_eligible": False}, output)
                rows.append({key: active_slot[key] for key in ("index", "task_index", "world", "seed", "policy")}
                            | {"passed": False, "clean_success": False, "failure_category": "provider-harness",
                               "episode_available": False, "replay_verified": False, "usage": {}})
            elif current_row is not None:
                current_row.update(observed_passed=current_row["passed"], passed=False, clean_success=False,
                                   outcome_integrity=False, failure_category="provider-harness")
        finally:
            for policy, provider in pool.items():
                if hasattr(provider, "close"):
                    try:
                        await asyncio.wait_for(provider.close(), timeout=3)
                    except (Exception, asyncio.CancelledError) as error:
                        cleanup_errors.append({"policy": policy, "error_type": type(error).__name__})
            if cleanup_errors:
                stopped = stopped or "provider-harness: provider cleanup failed"
            if time.monotonic() - started > OVERALL_SECONDS:
                stopped = stopped or "wall-cap: finalization exceeded declared duration; receipt is stopped"
            try:
                final_source = source_identity(expected_revision)
                report["final_checkout_dirty"] = final_source.get("checkout_dirty")
                if final_source["files_sha256"] != source["files_sha256"]:
                    stopped = stopped or "source-mismatch: source changed during the last attempt"
            except Exception:
                stopped = stopped or "source-mismatch: final source verification failed"
            report.update(status="stopped" if stopped else "completed", stop_reason=stopped,
                          cleanup_errors=cleanup_errors, elapsed_seconds=time.monotonic() - started,
                          finalized_episodes=sum(row["episode_available"] for row in rows), analysis=analysis(rows),
                          verified_episodes=sum(row["replay_verified"] for row in rows),
                          inconclusive_episodes=sum(row["episode_available"] and not row.get("outcome_integrity", False)
                                                    for row in rows),
                          raw_sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest())
            report["artifacts_bytes_before_report"] = artifact_bytes(output)
            report["report_bytes"] = 0
            report["artifact_total_bytes"] = 0
            serialized = (json.dumps(report, indent=2, allow_nan=False) + "\n").encode()
            while report["report_bytes"] != len(serialized):
                report["report_bytes"] = len(serialized)
                report["artifact_total_bytes"] = report["artifacts_bytes_before_report"] + len(serialized)
                serialized = (json.dumps(report, indent=2, allow_nan=False) + "\n").encode()
            if len(serialized) > REPORT_RESERVE or artifact_bytes(output) + len(serialized) > ARTIFACT_CAP:
                raise StudyStopped("report-cap: raw evidence retained; report cannot fit declared cap")
            # No report temporary is needed: only the final bounded report is written.
            with (output / "report.json").open("xb") as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--collect", action="store_true", help="Authorized collection only; performs local inference")
    mode.add_argument("--plan", action="store_true", help="Print fixed plan without contacting any provider (default)")
    parser.add_argument("--source-revision", help="Reviewed, committed full source SHA; mandatory for --collect")
    parser.add_argument("--output", type=Path, help="Fresh receipt directory; mandatory for --collect")
    args = parser.parse_args(argv)
    if not args.collect:
        print(json.dumps(plan(), indent=2))
        return 0
    if not args.source_revision or args.output is None:
        parser.error("--collect requires explicit reviewed --source-revision and fresh --output")
    result = asyncio.run(collect(args.output, args.source_revision))
    print(canonical_json({"status": result["status"], "finalized_episodes": result["finalized_episodes"],
                          "stop_reason": result["stop_reason"]}))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
