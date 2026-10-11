"""Plan a locked native-v1/ledger-v2 comparison; inference requires explicit review."""

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
from collections import Counter
from pathlib import Path

from world_engine import provider_records
from world_engine.environments import make_environment
from world_engine.models import RunConfig, canonical_json, digest, utc_now
from world_engine.ollama_tools import LEDGER_PROTOCOL, PROTOCOL, OllamaToolsProvider, contract, module_hashes
from world_engine.rollout import collection_revision, replay, rollout, world_fingerprints

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SCOPE = ["src/world_engine", "pyproject.toml", "uv.lock", "examples/access_ledger_study.py",
                "tests/test_access_ledger_study.py", "docs/access-ledger-study.md"]
PROTOCOLS = (PROTOCOL, LEDGER_PROTOCOL)
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
CONTRACT_HASHES = {PROTOCOL: "0e57c609b4ef58ab4e28551997d9839f0bdd532bd80f6bd3c9fc3bbf4d3a688b",
                   LEDGER_PROTOCOL: "dc8151352b679e29f2490a27116a684128ad7dfabd3078c60e47f7f8585c9fe5"}
MAX_STEPS, EPISODE_SECONDS, OVERALL_SECONDS, SETUP_SECONDS = 20, 35, 660, 30
MAX_REQUESTS, CLEANUP_SECONDS, FINALIZE_RESERVE_SECONDS = 320, 3, 30
ARTIFACT_CAP, EPISODE_RESERVE, REPORT_RESERVE = 64*1024**2, 24*1024**2, 1024**2
PROTOCOL_SHA256 = "91e7782c305b5a66ec4ab8a5290b54850e102d232b045221480a048732ba49f6"


class StudyStopped(RuntimeError):
    """Stop without overwriting earlier evidence; supplied values stay redacted."""


def slots() -> list[dict]:
    return [{"index": index, "world": WORLD, "seed": seed, "protocol": selected}
            for index, (seed, selected) in enumerate((seed, selected) for seed in range(8)
                for selected in (PROTOCOLS if seed % 2 == 0 else PROTOCOLS[::-1]))]


def protocol() -> dict:
    return {"id": "access-native-context-comparison-v1", "slots": slots(), "world_version": VERSION,
            "environment_hash": ENVIRONMENT_HASH, "grader_hash": GRADER_HASH,
            "initial_state_hashes": INITIAL_HASHES,
            "contracts": {selected: contract(selected) for selected in PROTOCOLS},
            "contract_hashes": CONTRACT_HASHES, "model": MODEL, "model_digest": MODEL_DIGEST,
            "options": {"temperature": 0, "num_predict": 512, "num_ctx": 8192}, "think": False, "keep_alive": "5m",
            "max_steps": MAX_STEPS, "episode_seconds": EPISODE_SECONDS, "overall_seconds": OVERALL_SECONDS,
            "setup_seconds": SETUP_SECONDS, "concurrency": 1, "max_model_requests": MAX_REQUESTS,
            "cleanup_seconds_per_provider": CLEANUP_SECONDS, "finalize_reserve_seconds": FINALIZE_RESERVE_SECONDS,
            "artifact_cap": ARTIFACT_CAP, "next_episode_reserve": EPISODE_RESERVE, "report_reserve": REPORT_RESERVE,
            "retry_policy": "none", "evaluation_only": True, "training_eligible": False,
            "primary": "paired authoritative business and clean outcomes; cancelled pairs censored explicitly",
            "comparison": "full context contracts, not deduplication or cache causality",
            "sample": "eight repeated public access cases, not independent population or family holdouts"}


def plan() -> dict:
    value = protocol()
    if digest(value) != PROTOCOL_SHA256 or any(digest(contract(p)) != CONTRACT_HASHES[p] for p in PROTOCOLS):
        raise StudyStopped("native contracts/protocol differ from the locked review")
    for seed, expected in enumerate(INITIAL_HASHES):
        world = make_environment(WORLD, seed)
        if (world.version != VERSION or digest(world.snapshot()) != expected
                or world_fingerprints(world) != (ENVIRONMENT_HASH, GRADER_HASH)
                or len(canonical_json(world.observe()).encode()) > 32*1024):
            raise StudyStopped("public fixture differs from locked fingerprints")
    components = {"provider_events": 8*1024**2,
                  "trace": MAX_STEPS*((132+384+64+64+4)*1024), "snapshots_metadata_and_wrapper": 1024**2}
    if sum(components.values()) > EPISODE_RESERVE:
        raise StudyStopped("fixed-world capacity exceeds next-episode reservation")
    return {"protocol": value, "protocol_sha256": digest(value),
            "reservation_bound": {"components_bytes": components, "derived_upper_bytes": sum(components.values()),
                                  "scope": "fixed access world and bounded native recorder, not hostile-host proof"},
            "status": "plan-only; no provider contact or inference"}


def source_identity(expected: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise StudyStopped("source revision must be a reviewed full lowercase SHA")

    def git(*args):
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                              check=True, timeout=3).stdout.strip()

    if git("rev-parse", "HEAD") != expected or git("status", "--porcelain", "--untracked-files=all", "--", *SOURCE_SCOPE):
        raise StudyStopped("runtime/dependencies/collector/test/protocol must be committed and clean")
    files = [*sorted((ROOT / "src/world_engine").rglob("*.py")),
             *(ROOT / item for item in SOURCE_SCOPE if not (ROOT / item).is_dir())]
    return {"git_revision": expected, "source_dirty": False, "scope": SOURCE_SCOPE,
            "files_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
            "checkout_dirty": bool(git("status", "--porcelain", "--untracked-files=all"))}


def artifact_bytes(output: Path) -> int:
    return sum(p.stat().st_size for p in output.iterdir() if p.is_file())


def append_raw(handle, episode, slot: dict, output: Path, *, error: str | None = None) -> dict:
    record = {"schema": "world-engine.evaluation-trace.v1", "slot": slot, "episode": episode,
              "evaluation_only": True, "training_eligible": False, "exact_envelope_preserved": error is None}
    if error is not None:
        record["attempt_error"] = error
    diagnostic = None
    try:
        content = (canonical_json(record)+"\n").encode()
    except (TypeError, ValueError, OverflowError, RecursionError):
        diagnostic = "returned envelope cannot serialize as JSON; exact envelope not preserved"
    if diagnostic is None and artifact_bytes(output)+len(content)+REPORT_RESERVE > ARTIFACT_CAP:
        diagnostic = "unexpected returned envelope cannot fit raw cap; exact envelope not preserved"
    if diagnostic is not None:
        record = {"schema": "world-engine.evaluation-trace.v1", "slot": slot, "episode": None,
                  "evaluation_only": True, "training_eligible": False,
                  "exact_envelope_preserved": False, "diagnostic": diagnostic}
        content = (canonical_json(record)+"\n").encode()
    if artifact_bytes(output)+len(content)+REPORT_RESERVE > ARTIFACT_CAP:
        raise StudyStopped("diagnostic cannot fit reserved artifact cap")
    handle.write(content)
    handle.flush()
    os.fsync(handle.fileno())
    return {"exact_envelope_preserved": diagnostic is None and error is None,
            "within_reservation": len(content) <= EPISODE_RESERVE, "diagnostic": diagnostic}


def make_provider(selected: str):
    return OllamaToolsProvider(RunConfig(environment_id=WORLD, provider_id="local", model=MODEL,
                                        episodes=1, concurrency=1, max_steps=MAX_STEPS,
                                        timeout_seconds=EPISODE_SECONDS,
                                        evaluation_only=True, allow_paid=False), protocol=selected)


def observed_attempts(episode) -> int | None:
    events = episode.get("provider_events") if type(episode) is dict else None
    if type(events) is not list or any(type(event) is not dict for event in events):
        return None
    return sum(event.get("event") == "request_started" for event in events)


def event_counters(episode: dict, selected: str) -> dict:
    pairs = provider_records.validate_pairs(episode["provider_events"], selected)
    ends = [end for _, end in pairs]
    result = {"model_request_attempts": len(pairs), "counters_complete": True,
              "accepted_requests": sum(end["complete"] for end in ends),
              "request_body_bytes": sum(start["request_bytes"] for start, _ in pairs),
              "response_body_bytes_observed": sum(end["response_bytes"] for end in ends),
              "response_body_bytes_complete": all(end["body_complete"] for end in ends),
              "transport_elapsed_ms": sum(end["elapsed_ms"] for end in ends),
              "request_outcomes": dict(Counter(end["outcome"] for end in ends))}
    for field in ("input_tokens", "output_tokens", "inference_ns"):
        known = [end["usage"][field] for end in ends if field in end["usage"]]
        result[field+"_known"] = sum(known) if known else None
        result[field+"_known_requests"] = len(known)
        result[field+"_complete"] = bool(ends) and len(known) == len(ends)
    return result


def check_episode(episode, slot: dict, source: dict, evidence: dict) -> dict:
    if type(episode) is not dict:
        raise StudyStopped("malformed returned envelope; serialized raw retained")
    v = episode["provenance"]
    if (episode["seed"] != slot["seed"] or episode["index"] != 0 or v["environment_id"] != WORLD
            or v["environment_version"] != VERSION or v["environment_code_hash"] != ENVIRONMENT_HASH
            or v["grader_code_hash"] != GRADER_HASH or v["initial_state_hash"] != INITIAL_HASHES[slot["seed"]]
            or v["evaluation_only"] is not True or v.get("training_eligible") is not False
            or v.get("git_revision") != source["git_revision"] or v.get("implementation_dirty") is not False
            or v.get("provider_protocol") != slot["protocol"] or canonical_json(v.get("provider_evidence")) != canonical_json(evidence)
            or v.get("model") != MODEL or v.get("model_digest") != MODEL_DIGEST):
        raise StudyStopped("episode differs from locked source/case/provider")
    row = {key: episode[key] for key in ("passed", "reward", "status", "termination", "steps",
                                        "invalid_actions", "elapsed_seconds", "usage")}
    if (type(row["passed"]) is not bool or type(row["steps"]) is not int or not 0 <= row["steps"] <= MAX_STEPS
            or type(row["invalid_actions"]) is not int or not 0 <= row["invalid_actions"] <= row["steps"]
            or row["status"] not in {"completed", "failed", "cancelled"}
            or row["termination"] not in {"finished", "max_steps", "internal_error", "provider_error", "timeout", "cancelled"}
            or type(row["usage"]) is not dict):
        raise StudyStopped("malformed episode summary; raw retained")
    if any(type(row[k]) not in (int, float) or not math.isfinite(row[k]) or row[k] < 0
           for k in ("reward", "elapsed_seconds")) or row["reward"] > 1:
        raise StudyStopped("malformed episode numeric summary; raw retained")
    if replay(episode)["verified"] is not True:
        raise StudyStopped("replay rejected current envelope; raw retained")
    row.update(event_counters(episode, slot["protocol"]))
    if row["model_request_attempts"] > MAX_STEPS:
        raise StudyStopped("current request count exceeds locked decision cap")
    row.update(clean_success=row["passed"] and row["status"] == "completed" and row["invalid_actions"] == 0,
               replay_verified=True, outcome_integrity=True, primary_eligible=row["status"] != "cancelled")
    return row


def comparison_identity(episode: dict) -> dict:
    fields = ("environment_id", "environment_version", "grader_version", "environment_code_hash", "grader_code_hash",
              "initial_state_hash", "task_hash", "prompt_hash")
    return {"scenario_id": episode["scenario_id"], "split": episode["split"],
            "initial_observation_hash": digest(episode["initial_observation"]),
            **{key: episode["provenance"][key] for key in fields}}


def aggregate_counters(rows: list[dict]) -> dict:
    valid = [row for row in rows if row["counters_complete"]]
    counts = [row["model_request_attempts"] for row in rows]
    result = {"model_request_attempts_observed": sum(n for n in counts if n is not None),
              "model_request_attempts_complete": all(row["counters_complete"] for row in rows),
              "request_body_bytes_known": sum(r["request_body_bytes"] for r in valid) if valid else None,
              "response_body_bytes_observed_known": sum(r["response_body_bytes_observed"] for r in valid) if valid else None,
              "body_bytes_accounting_complete": len(valid) == len(rows),
              "response_body_bytes_complete": len(valid) == len(rows) and all(r["response_body_bytes_complete"] for r in valid),
              "transport_elapsed_ms_known": sum(r["transport_elapsed_ms"] for r in valid) if valid else None,
              "transport_elapsed_ms_complete": len(valid) == len(rows),
              "request_outcomes": dict(sum((Counter(r["request_outcomes"]) for r in valid), Counter()))}
    for field in ("input_tokens", "output_tokens", "inference_ns"):
        known = [r[field+"_known"] for r in valid if r[field+"_known"] is not None]
        result[field+"_known"] = sum(known) if known else None
        result[field+"_known_requests"] = sum(r[field+"_known_requests"] for r in valid)
        result[field+"_complete"] = bool(valid) and len(valid) == len(rows) and all(r[field+"_complete"] for r in valid)
    return result


def summarize(rows: list[dict], scheduled: list[dict]) -> dict:
    by_case = {(row["seed"], row["protocol"]): row for row in rows}
    cells = {name: Counter({"both_pass": 0, "v1_only": 0, "v2_only": 0, "neither_pass": 0})
             for name in ("business", "clean")}
    complete, incomplete = [], []
    for seed in range(8):
        pair = [by_case.get((seed, p)) for p in PROTOCOLS]
        if all(row is not None and row["primary_eligible"] for row in pair):
            complete.append(seed)
            for name, field in (("business", "passed"), ("clean", "clean_success")):
                left, right = (row[field] for row in pair)
                cells[name]["both_pass" if left and right else "v1_only" if left else "v2_only" if right else "neither_pass"] += 1
        else:
            incomplete.append({"seed": seed, "reasons": {p: "unattempted" if row is None else
                               "cancelled" if row.get("status") == "cancelled" else "inconclusive"
                               for p, row in zip(PROTOCOLS, pair, strict=True) if row is None or not row["primary_eligible"]}})
    per_protocol = {}
    for selected in PROTOCOLS:
        values = [row for row in rows if row["protocol"] == selected]
        eligible = [row for row in values if row["primary_eligible"]]
        per_protocol[selected] = {"scheduled": 8, "attempted": len(values), "primary_eligible": len(eligible),
                                  "verified": sum(r["replay_verified"] for r in values),
                                  "inconclusive": sum(not r["outcome_integrity"] for r in values),
                                  "cancelled": sum(r.get("status") == "cancelled" for r in values),
                                  "unattempted": sum(s["protocol"] == selected and s["status"] == "not_attempted" for s in scheduled),
                                  "business_passes": sum(r["passed"] for r in eligible),
                                  "clean_passes": sum(r["clean_success"] for r in eligible),
                                  "statuses": dict(Counter(r.get("status", "inconclusive") for r in values)),
                                  "terminations": dict(Counter(r.get("termination", "unknown") for r in values)),
                                  "counters": aggregate_counters(values)}
    return {"per_protocol": per_protocol, "paired": {"scheduled_pairs": 8, "eligible_pairs": len(complete),
            "eligible_seeds": complete, "incomplete_pairs": incomplete,
            **{name: {"cells": dict(counts), "v2_minus_v1_pass_fraction":
                      (counts["v2_only"]-counts["v1_only"])/len(complete) if complete else None}
               for name, counts in cells.items()}}}


def write_report(output: Path, report: dict) -> None:
    report.update(artifacts_bytes_before_report=artifact_bytes(output), report_bytes=0, artifact_total_bytes=0)
    data = (json.dumps(report, indent=2, allow_nan=False)+"\n").encode()
    while report["report_bytes"] != len(data):
        report["report_bytes"] = len(data)
        report["artifact_total_bytes"] = report["artifacts_bytes_before_report"]+len(data)
        data = (json.dumps(report, indent=2, allow_nan=False)+"\n").encode()
    if len(data) > REPORT_RESERVE or artifact_bytes(output)+len(data) > ARTIFACT_CAP:
        raise StudyStopped("report cannot fit reserved cap; raw retained")
    with (output / "report.json").open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


async def collect(output: Path, expected_revision: str) -> dict:
    started = time.monotonic()
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    source, fixed_plan = source_identity(expected_revision), plan()
    scheduled = [{**slot, "status": "not_attempted"} for slot in slots()]
    rows, providers, evidence, cleanup, identities = [], {}, {}, [], {}
    report = {"schema": "world-engine.access-ledger-study.v1", "created_at": utc_now(), "source": source,
              "plan": fixed_plan, "slots": scheduled, "rows": rows, "evaluation_only": True,
              "training_eligible": False, "paid_calls": 0, "model_downloaded": False, "training_executed": False,
              "setup": {"prepare_attempts": 0, "prepare_completed": 0, "metadata_http_requests": None,
                        "metadata_http_requests_complete": False},
              "raw_durability": "finalized envelopes fsynced before validation; not mid-episode crash durable"}
    current, row, stopped = None, None, None
    raw_path = output / "evaluation-episodes.jsonl"
    with raw_path.open("xb") as raw:
        try:
            remaining = OVERALL_SECONDS-FINALIZE_RESERVE_SECONDS-(time.monotonic()-started)
            if remaining <= 0:
                raise StudyStopped("aggregate budget exhausted before preparation")
            async with asyncio.timeout(remaining):
                async with asyncio.timeout(SETUP_SECONDS):
                    for selected in PROTOCOLS:
                        provider = providers[selected] = make_provider(selected)
                        report["setup"]["prepare_attempts"] += 1
                        await provider.prepare()
                        report["setup"]["prepare_completed"] += 1
                        evidence[selected] = provider.evidence_metadata()
                        if (provider.model != MODEL or provider.model_digest != MODEL_DIGEST
                                or provider.provider_protocol != selected
                                or evidence[selected].get("native_contract_hash") != CONTRACT_HASHES[selected]
                                or any(evidence[selected].get(k) != v for k, v in module_hashes(selected).items())):
                            raise StudyStopped("prepared model/protocol/source differs before first chat")
                report["provider_evidence"] = evidence
                collection_revision.cache_clear()
                for slot in scheduled:
                    if artifact_bytes(output)+EPISODE_RESERVE+REPORT_RESERVE > ARTIFACT_CAP:
                        raise StudyStopped("no next episode artifact reservation")
                    if source_identity(expected_revision)["files_sha256"] != source["files_sha256"] or plan() != fixed_plan:
                        raise StudyStopped("source/fixture/contract changed before next episode")
                    if time.monotonic()-started+EPISODE_SECONDS+FINALIZE_RESERVE_SECONDS > OVERALL_SECONDS:
                        raise StudyStopped("no next full episode time reservation")
                    if sum(r["model_request_attempts"] for r in rows if r["model_request_attempts"] is not None)+MAX_STEPS > MAX_REQUESTS:
                        raise StudyStopped("no next full episode chat reservation")
                    provider = providers[slot["protocol"]]
                    if (provider.model != MODEL or provider.model_digest != MODEL_DIGEST
                            or canonical_json(provider.evidence_metadata()) != canonical_json(evidence[slot["protocol"]])):
                        raise StudyStopped("prepared provider identity changed before episode")
                    current, row = slot, None
                    slot["status"] = "attempt_started"
                    config = RunConfig(environment_id=WORLD, provider_id="local", model=MODEL, seed=slot["seed"],
                                       episodes=1, concurrency=1, max_steps=MAX_STEPS, timeout_seconds=EPISODE_SECONDS,
                                       evaluation_only=True, allow_paid=False, label="locked native context comparison; operator-only")
                    episode = await rollout(config, 0, provider)
                    saved = append_raw(raw, episode, slots()[slot["index"]], output)
                    slot["status"] = "finalized" if saved["exact_envelope_preserved"] else "diagnostic_saved"
                    row = {**slots()[slot["index"]], **saved, "episode_available": episode is not None,
                           "passed": False, "clean_success": False, "outcome_integrity": False, "replay_verified": False,
                           "primary_eligible": False, "counters_complete": False,
                           "model_request_attempts": observed_attempts(episode),
                           "observed_passed": episode.get("passed") if type(episode) is dict and type(episode.get("passed")) is bool else None}
                    rows.append(row)
                    if not saved["exact_envelope_preserved"] or not saved["within_reservation"]:
                        raise StudyStopped("current envelope exceeded serialization/reservation bounds; no next chat")
                    checked = check_episode(episode, slot, source, evidence[slot["protocol"]])
                    row.update(checked)
                    identity = comparison_identity(episode)
                    previous = identities.get(slot["seed"])
                    if previous is not None and canonical_json(previous) != canonical_json(identity):
                        raise StudyStopped("paired task identity differs; current raw retained")
                    identities[slot["seed"]] = identity
                    slot["status"] = "verified"
                    if episode["status"] == "cancelled":
                        slot["status"] = "verified_cancelled"
                        raise StudyStopped("cancelled current episode retained; remaining slots unattempted")
                    current, row = None, None
        except (Exception, asyncio.CancelledError) as error:
            stopped = str(error) if isinstance(error, StudyStopped) else f"collector failed: {type(error).__name__}; details redacted"
            if current is not None and current["status"] == "attempt_started":
                append_raw(raw, None, slots()[current["index"]], output, error=stopped)
                current["status"] = "attempted_without_final_episode"
                rows.append({**slots()[current["index"]], "episode_available": False,
                             "exact_envelope_preserved": False, "passed": False,
                             "clean_success": False, "outcome_integrity": False, "replay_verified": False,
                             "primary_eligible": False, "counters_complete": False, "model_request_attempts": None})
            elif row is not None and current["status"] != "verified_cancelled":
                row.update(passed=False, clean_success=False, outcome_integrity=False, replay_verified=False, primary_eligible=False)
                current["status"] = "finalized_inconclusive"
        finally:
            for selected, provider in providers.items():
                try:
                    await asyncio.wait_for(provider.close(), timeout=CLEANUP_SECONDS)
                    cleanup.append({"protocol": selected, "status": "completed", "resource_closure_attested": False})
                except (Exception, asyncio.CancelledError) as error:
                    cleanup.append({"protocol": selected, "status": "failed", "error_type": type(error).__name__,
                                    "resource_closure_attested": False})
                    stopped = stopped or "provider cleanup failed; external resource closure unconfirmed"
            try:
                final_source = source_identity(expected_revision)
                report["final_checkout_dirty"] = final_source.get("checkout_dirty")
                if final_source["files_sha256"] != source["files_sha256"] or plan() != fixed_plan:
                    stopped = stopped or "source/fixture/contract changed during last episode or cleanup"
            except Exception:
                stopped = stopped or "final source verification failed"
            if time.monotonic()-started > OVERALL_SECONDS:
                stopped = stopped or "aggregate duration exceeded"
            report.update(status="stopped" if stopped else "completed", stop_reason=stopped,
                          comparison_approved=stopped is None, cleanup=cleanup, elapsed_seconds=time.monotonic()-started,
                          attempted_episodes=len(rows), unattempted_episodes=sum(s["status"] == "not_attempted" for s in scheduled),
                          returned_envelopes=sum(r["episode_available"] for r in rows),
                          finalized_envelopes=sum(r["episode_available"] and r.get("exact_envelope_preserved", False) for r in rows),
                          diagnostic_envelopes=sum(r.get("exact_envelope_preserved") is False for r in rows),
                          verified_episodes=sum(r["replay_verified"] for r in rows),
                          inconclusive_episodes=sum(not r["outcome_integrity"] for r in rows),
                          counters=aggregate_counters(rows), analysis=summarize(rows, scheduled),
                          raw_sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest())
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
    print(canonical_json({"status": result["status"], "verified_episodes": result["verified_episodes"], "stop_reason": result["stop_reason"]}))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
