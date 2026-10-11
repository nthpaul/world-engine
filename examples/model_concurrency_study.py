"""Plan a fixed SDK caller-wave admission study; collection needs separate review."""

from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import subprocess
import time
from collections import Counter
from pathlib import Path

import httpx

from world_engine import provider_records
from world_engine.environments import make_environment
from world_engine.models import RunConfig, canonical_json, digest, utc_now
from world_engine.ollama_tools import PROTOCOL, OllamaToolsProvider, contract
from world_engine.providers import ProviderError
from world_engine.rollout import collection_revision, replay, rollout, world_fingerprints

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SCOPE = ["src/world_engine", "pyproject.toml", "uv.lock", "examples/model_concurrency_study.py",
                "tests/test_model_concurrency_study.py", "docs/model-concurrency-study.md"]
WORLD, VERSION, MODEL = "refund-ops", "1.1.2", "qwen3:8b"
MODEL_DIGEST = "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41"
SEEDS, CONCURRENCIES = tuple(range(53000, 53008)), (1, 2, 2, 1)
ENVIRONMENT_HASH = "4a89c019ccf09faec523b10e61128e13c0689c4ee4e94bb88dde4f5bcbad7f06"
GRADER_HASH = "56ae60240d24e1fb3eed4d7f29434174d674bddd7e1cdd0c9ddb2368529d22c7"
INITIAL_HASHES = (
    "f1bcb1ddbdf40caeb5840a87f1914633dc06f5d5800e552d4fe526ea74e90675",
    "2266577604b3b5a799432f7aeed62181350c18841c75e7f4f878fea4e534e4bb",
    "11dd29e59da952d4ce2788a1fee3240fdc2cfbe506cb88bf92432fdb33c389bf",
    "6878a19e687f6477ef506b9d60704ccb2fe95bb664cabd95ae3cc1adea1f14e0",
    "bf2baac69c896d1a5453ebe71bb828df547a3c95421bfe7d7842cad10f6430ed",
    "fb054d0a77100b8cee4a58a5e643328372853731278ab0fe33b0c13ebe64c3d4",
    "83d90fa8bae0c7166a3fac90bbc6a037318b4e958e907d2624e9c629e459b577",
    "7ab807fd4b4404799d90ae49c2ede8269ea6a4ac91754ac2ff509d3621b2001d",
)
CONTRACT_HASH = "0e57c609b4ef58ab4e28551997d9839f0bdd532bd80f6bd3c9fc3bbf4d3a688b"
MAX_STEPS, EPISODE_SECONDS, OVERALL_SECONDS = 20, 35, 1200
SETUP_SECONDS, CLEANUP_SECONDS, FINAL_RESERVE = 30, 3, 60
MAX_REQUESTS, ARTIFACT_CAP, EPISODE_RESERVE, REPORT_RESERVE = 640, 64*1024**2, 24*1024**2, 1024**2
PROTOCOL_SHA256 = "46b07934df72ff4d88c020fe9f937018ef94e603e405c0a615b0ddaf7abf2b68"


class StudyStopped(RuntimeError):
    pass


def slots() -> list[dict]:
    return [{"index": batch*len(SEEDS)+offset, "batch": batch, "seed": seed,
             "concurrency": concurrency, "world": WORLD, "protocol": PROTOCOL}
            for batch, concurrency in enumerate(CONCURRENCIES) for offset, seed in enumerate(SEEDS)]


def protocol() -> dict:
    return {"id": "native-sdk-caller-wave-admission-v1", "slots": slots(), "world_version": VERSION,
            "environment_hash": ENVIRONMENT_HASH, "grader_hash": GRADER_HASH,
            "initial_state_hashes": INITIAL_HASHES, "contract": contract(), "contract_hash": CONTRACT_HASH,
            "model": MODEL, "model_digest": MODEL_DIGEST, "keep_alive": "5m", "max_steps": MAX_STEPS,
            "episode_seconds": EPISODE_SECONDS, "overall_seconds": OVERALL_SECONDS,
            "preparation_seconds_per_batch": SETUP_SECONDS, "cleanup_seconds_per_batch": CLEANUP_SECONDS,
            "finalization_reserve_seconds": FINAL_RESERVE, "max_chat_requests": MAX_REQUESTS,
            "artifact_cap": ARTIFACT_CAP, "episode_reserve": EPISODE_RESERVE, "report_reserve": REPORT_RESERVE,
            "clock": "continuous first admission through final wave raw fsync and validation; includes interwave source checks",
            "primary": "verified business passes per recorded batch wall second",
            "retry_policy": "none", "evaluation_only": True, "training_eligible": False,
            "scope": "SDK caller waves, not RunManager/API throughput or causal GPU parallelism",
            "pair_batches": [[0, 1], [3, 2]], "unique_tasks": 8, "repeats_per_task": 4}


def plan() -> dict:
    value = protocol()
    if digest(value) != PROTOCOL_SHA256 or digest(contract()) != CONTRACT_HASH:
        raise StudyStopped("protocol or native contract differs from reviewed lock")
    cases = []
    for seed, expected in zip(SEEDS, INITIAL_HASHES, strict=True):
        world = make_environment(WORLD, seed)
        if (world.version != VERSION or world_fingerprints(world) != (ENVIRONMENT_HASH, GRADER_HASH)
                or digest(world.snapshot()) != expected or len(canonical_json(world.observe()).encode()) > 32*1024):
            raise StudyStopped("world fixture differs from reviewed lock")
        cases.append({"seed": seed, "case": seed % 8})
    components = {"provider_events": 8*1024**2,
                  "trace": MAX_STEPS*((132+384+64+64+4)*1024), "snapshots_metadata_wrapper": 1024**2}
    if sum(components.values()) > EPISODE_RESERVE:
        raise StudyStopped("episode reservation derivation exceeds limit")
    return {"protocol": value, "protocol_sha256": digest(value), "case_metadata": cases,
            "reservation_components": components, "status": "plan-only; no provider or source contact"}


def source_identity(expected: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise StudyStopped("reviewed full lowercase source revision required")

    def git(*args):
        return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True, timeout=3).stdout.strip()

    if git("rev-parse", "HEAD") != expected or git("status", "--porcelain", "--untracked-files=all", "--", *SOURCE_SCOPE):
        raise StudyStopped("captured runtime/dependencies/collector/test/protocol must be committed and clean")
    files = [*sorted((ROOT/"src/world_engine").rglob("*.py")),
             *(ROOT/p for p in SOURCE_SCOPE if not (ROOT/p).is_dir())]
    return {"git_revision": expected, "source_dirty": False, "scope": SOURCE_SCOPE,
            "files_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
            "checkout_dirty": bool(git("status", "--porcelain", "--untracked-files=all"))}


def public_seed_overlap() -> list[dict]:
    """Scan structured public receipts, not the operator DB or arbitrary private files."""
    hits = []

    def visit(value, path):
        if isinstance(value, dict):
            seed = value.get("seed")
            world = value.get("world", value.get("environment_id", value.get("environment")))
            if type(seed) is int and seed in SEEDS and world in (None, WORLD):
                hits.append({"file": str(path.relative_to(ROOT)), "seed": seed,
                             "world": world, "scope": "structured seed field; world may be unspecified"})
            for child in value.values():
                visit(child, path)
        elif isinstance(value, list):
            for child in value:
                visit(child, path)

    for directory in ("artifacts", "examples/benchmark-results", "examples/datasets", "examples/candidate-corpus"):
        root = ROOT/directory
        for path in sorted(root.rglob("*")) if root.exists() else []:
            compressed = path.name.endswith(".jsonl.gz")
            if path.is_symlink() or not path.is_file() or not (compressed or path.suffix in (".json", ".jsonl")):
                continue
            try:
                if not compressed and path.stat().st_size > 256*1024**2:
                    raise StudyStopped("public receipt exceeds bounded scan; overlap unknown")
                with (gzip.open(path, "rt") if compressed else path.open()) as handle:
                    if compressed or path.suffix == ".jsonl":
                        expanded = 0
                        for line in handle:
                            expanded += len(line.encode())
                            if expanded > 256*1024**2:
                                raise StudyStopped("expanded public receipt exceeds bounded scan; overlap unknown")
                            if line.strip():
                                visit(json.loads(line), path)
                    else:
                        visit(json.load(handle), path)
            except (OSError, ValueError, RecursionError):
                raise StudyStopped("public receipt scan failed; overlap unknown") from None
    return sorted({canonical_json(hit): hit for hit in hits}.values(), key=lambda h: (h["file"], h["seed"]))


class RequestBudget:
    def __init__(self):
        self.chat = self.metadata = 0
        self.phase = "metadata"
        self.violation = False

    async def hook(self, request: httpx.Request) -> None:
        path = request.url.path
        metadata = {"/api/tags": "GET", "/api/show": "POST", "/api/version": "GET"}
        valid = request.url.scheme == "http" and request.url.port == 11434 and request.url.host in ("localhost", "127.0.0.1", "::1")
        if not valid or request.url.query or request.url.fragment or request.url.username or request.url.password:
            self.violation = True
            raise ProviderError("study transport endpoint is outside its locked scope")
        if path in metadata and request.method == metadata[path] and self.phase == "metadata":
            if path == "/api/show" and json.loads(request.content) != {"model": MODEL}:
                self.violation = True
                raise ProviderError("study metadata model differs from lock")
            self.metadata += 1
            return
        if path != "/api/chat" or request.method != "POST" or self.phase != "chat" or self.chat >= MAX_REQUESTS:
            self.violation = True
            raise ProviderError("study request is outside admitted chat budget")
        body = json.loads(request.content)
        if (body.get("model") != MODEL or body.get("options") != contract()["options"]
                or body.get("stream") is not False or body.get("think") is not False or body.get("keep_alive") != "5m"):
            self.violation = True
            raise ProviderError("study chat settings differ from lock")
        self.chat += 1  # No await between the guard and increment: concurrent hooks share one counter.


def make_provider(budget: RequestBudget):
    provider = OllamaToolsProvider(RunConfig(environment_id=WORLD, provider_id="local", model=MODEL,
                                            max_steps=MAX_STEPS, timeout_seconds=EPISODE_SECONDS,
                                            evaluation_only=True), protocol=PROTOCOL)
    if provider.endpoint not in {"http://127.0.0.1:11434", "http://localhost:11434", "http://[::1]:11434"}:
        raise StudyStopped("study accepts only the existing loopback daemon on port11434")
    provider.client = httpx.AsyncClient(timeout=EPISODE_SECONDS, trust_env=False, follow_redirects=False,
                                       event_hooks={"request": [budget.hook]})
    return provider


def artifact_bytes(output: Path) -> int:
    return sum(p.stat().st_size for p in output.rglob("*") if p.is_file())


def append_raw(handle, slot: dict, episode, output: Path, error: str | None) -> dict:
    record = {"schema": "world-engine.evaluation-trace.v1", "slot": slot, "episode": episode,
              "evaluation_only": True, "training_eligible": False, "exact_envelope_preserved": error is None}
    diagnostic = error
    if error is not None:
        record["diagnostic"] = error
    try:
        content = (canonical_json(record)+"\n").encode()
    except (ValueError, TypeError, OverflowError, RecursionError):
        diagnostic = "returned envelope cannot serialize; exact evidence not preserved"
        content = b""
    if diagnostic is None and artifact_bytes(output)+len(content)+REPORT_RESERVE > ARTIFACT_CAP:
        diagnostic = "returned envelope cannot fit cap; exact evidence not preserved"
    if diagnostic is not None:
        record.update(episode=None, exact_envelope_preserved=False, diagnostic=diagnostic)
        content = (canonical_json(record)+"\n").encode()
    if artifact_bytes(output)+len(content)+REPORT_RESERVE > ARTIFACT_CAP:
        raise StudyStopped("reserved diagnostic capacity exhausted; existing raw retained")
    handle.write(content)
    handle.flush()
    os.fsync(handle.fileno())
    return {"exact_envelope_preserved": diagnostic is None, "diagnostic": diagnostic,
            "within_reservation": len(content) <= EPISODE_RESERVE}


def comparison_identity(episode: dict) -> dict:
    fields = ("environment_id", "environment_version", "grader_version", "environment_code_hash", "grader_code_hash",
              "initial_state_hash", "task_hash", "prompt_hash")
    return {"scenario_id": episode["scenario_id"], "split": episode["split"],
            "initial_observation_hash": digest(episode["initial_observation"]),
            "policy_hash": episode["provenance"]["policy_hash"],
            "model_digest": episode["provenance"]["model_digest"],
            **{key: episode["provenance"][key] for key in fields}}


def event_counters(episode: dict) -> dict:
    pairs = provider_records.validate_pairs(episode["provider_events"], PROTOCOL)
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


def aggregate_counters(rows: list[dict]) -> dict:
    valid = [r for r in rows if r["counters_complete"]]
    result = {"model_request_attempts_observed": sum(r["model_request_attempts"] or 0 for r in rows),
              "model_request_attempts_complete": len(valid) == len(rows),
              "request_body_bytes_known": sum(r["request_body_bytes"] for r in valid) if valid else None,
              "response_body_bytes_observed_known": sum(r["response_body_bytes_observed"] for r in valid) if valid else None,
              "response_body_bytes_complete": bool(valid) and len(valid) == len(rows) and all(r["response_body_bytes_complete"] for r in valid),
              "transport_elapsed_ms_known": sum(r["transport_elapsed_ms"] for r in valid) if valid else None,
              "request_outcomes": dict(sum((Counter(r["request_outcomes"]) for r in valid), Counter()))}
    for field in ("input_tokens", "output_tokens", "inference_ns"):
        known = [r[field+"_known"] for r in valid if r[field+"_known"] is not None]
        result[field+"_known"] = sum(known) if known else None
        result[field+"_known_requests"] = sum(r[field+"_known_requests"] for r in valid)
        result[field+"_complete"] = bool(valid) and len(valid) == len(rows) and all(r[field+"_complete"] for r in valid)
    return result


def check_episode(episode, slot: dict, source: dict, evidence: dict) -> dict:
    if type(episode) is not dict:
        raise StudyStopped("malformed envelope; raw retained")
    v = episode["provenance"]
    if (episode["seed"] != slot["seed"] or episode["index"] != 0 or v["environment_id"] != WORLD
            or v["environment_version"] != VERSION or v["environment_code_hash"] != ENVIRONMENT_HASH
            or v["grader_code_hash"] != GRADER_HASH or v["initial_state_hash"] != INITIAL_HASHES[slot["seed"]-SEEDS[0]]
            or v["evaluation_only"] is not True or v.get("training_eligible") is not False
            or v.get("provider_protocol") != PROTOCOL or v.get("model") != MODEL or v.get("model_digest") != MODEL_DIGEST
            or v.get("git_revision") != source["git_revision"] or v.get("implementation_dirty") is not False
            or canonical_json(v.get("provider_evidence")) != canonical_json(evidence)):
        raise StudyStopped("returned envelope differs from reviewed source/provider/case")
    row = {k: episode[k] for k in ("passed", "reward", "status", "termination", "steps", "invalid_actions", "elapsed_seconds", "usage")}
    if (type(row["passed"]) is not bool or type(row["steps"]) is not int or not 0 <= row["steps"] <= MAX_STEPS
            or type(row["invalid_actions"]) is not int or not 0 <= row["invalid_actions"] <= row["steps"]
            or row["status"] not in {"completed", "failed", "cancelled"}
            or row["termination"] not in {"finished", "max_steps", "internal_error", "provider_error", "timeout", "cancelled"}
            or type(row["usage"]) is not dict or any(type(row[k]) not in (int, float) or not math.isfinite(row[k])
                or row[k] < 0 for k in ("elapsed_seconds", "reward")) or row["reward"] > 1):
        raise StudyStopped("malformed summary; raw retained")
    if replay(episode).get("verified") is not True:
        raise StudyStopped("semantic replay rejected raw envelope")
    row.update(event_counters(episode))
    if row["model_request_attempts"] > MAX_STEPS:
        raise StudyStopped("episode exceeded twenty recorded requests")
    row.update(verified=True, primary_eligible=row["status"] != "cancelled",
               clean_success=row["passed"] and row["status"] == "completed" and row["invalid_actions"] == 0,
               identity=comparison_identity(episode))
    return row


def summarize(rows: list[dict], batches: list[dict]) -> dict:
    by_slot = {(r["batch"], r["seed"]): r for r in rows}
    rounds = []
    for left_batch, right_batch in ((0, 1), (3, 2)):
        cells = {name: Counter({"both_pass": 0, "one_only": 0, "two_only": 0, "neither": 0}) for name in ("business", "clean")}
        missing = []
        for seed in SEEDS:
            left, right = by_slot.get((left_batch, seed)), by_slot.get((right_batch, seed))
            if not left or not right or not left["primary_eligible"] or not right["primary_eligible"] or left["identity"] != right["identity"]:
                missing.append(seed)
                continue
            for name, field in (("business", "passed"), ("clean", "clean_success")):
                a, b = left[field], right[field]
                cells[name]["both_pass" if a and b else "one_only" if a else "two_only" if b else "neither"] += 1
        denominator = len(SEEDS)-len(missing)
        rounds.append({"batch_pair": [left_batch, right_batch], "eligible_pairs": denominator, "incomplete_seeds": missing,
                       **{name: {"cells": dict(c), "two_minus_one": (c["two_only"]-c["one_only"])/denominator if denominator else None}
                          for name, c in cells.items()}})
    task_counts = []
    for seed in SEEDS:
        values = [by_slot.get((batch, seed)) for batch in range(4)]
        complete = all(r and r["primary_eligible"] for r in values)
        complete = complete and len({digest(r["identity"]) for r in values}) == 1
        one = sum(bool(r and r["primary_eligible"] and r["passed"]) for r in (values[0], values[3]))
        two = sum(bool(r and r["primary_eligible"] and r["passed"]) for r in (values[1], values[2]))
        task_counts.append({"seed": seed, "all_four_eligible": complete, "one_passes": one, "two_passes": two,
                            "two_minus_one_fraction": (two-one)/2 if complete else None})
    for batch in batches:
        values = [r for r in rows if r["batch"] == batch["index"]]
        valid = [r for r in values if r["verified"]]
        seconds = batch.get("wall_seconds")
        batch.update(attempted=len(values), verified=len(valid), business_passes=sum(r["passed"] for r in valid),
                     clean_successes=sum(r["clean_success"] for r in valid), invalid_actions=sum(r["invalid_actions"] for r in valid),
                     statuses=dict(Counter(r.get("status", "inconclusive") for r in values)),
                     terminations=dict(Counter(r.get("termination", "unknown") for r in values)),
                     provider_failures=sum(r.get("termination") == "provider_error" for r in values),
                     harness_failures=sum(r.get("termination") == "internal_error" for r in values))
        batch.update(passes_per_second=batch["business_passes"]/seconds if seconds else None,
                     episodes_per_second=sum(r["exact_envelope_preserved"] for r in values)/seconds if seconds else None,
                     steps_per_second=sum(r["steps"] for r in valid)/seconds if seconds else None,
                     counters=aggregate_counters(values))
    return {"rounds": rounds, "unique_task_counts": task_counts, "unique_tasks": 8,
            "repeats_per_task": 4, "batches": batches, "counters": aggregate_counters(rows)}


def write_report(output: Path, report: dict) -> None:
    report.update(artifacts_bytes_before_report=artifact_bytes(output), report_bytes=0, artifact_total_bytes=0)
    data = b""
    while report["report_bytes"] != len(data) or not data:
        report["report_bytes"] = len(data)
        report["artifact_total_bytes"] = report["artifacts_bytes_before_report"]+len(data)
        data = (json.dumps(report, indent=2, allow_nan=False)+"\n").encode()
    if len(data) > REPORT_RESERVE or artifact_bytes(output)+len(data) > ARTIFACT_CAP:
        raise StudyStopped("report exceeded reserved cap; raw retained")
    with (output/"report.json").open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


async def collect(output: Path, revision: str) -> dict:
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    started = time.monotonic()
    rows, batches, scheduled = [], [], [{**s, "status": "not_attempted"} for s in slots()]
    budget, stop, source, fixed = RequestBudget(), None, None, None
    report = {"schema": "world-engine.model-concurrency-study.v1", "created_at": utc_now(), "rows": rows,
              "slots": scheduled, "batches": batches, "evaluation_only": True, "training_eligible": False,
              "paid_calls": 0, "model_downloaded": False, "training_executed": False}
    raw_path = output/"evaluation-episodes.jsonl"
    with raw_path.open("xb") as raw:
        try:
            source, fixed = source_identity(revision), plan()
            overlap = public_seed_overlap()
            report.update(source=source, plan=fixed, prior_seed_overlap=overlap,
                          machine={"platform": platform.platform(), "python": platform.python_version(),
                                   "architecture": platform.machine(), "logical_cpu_count": os.cpu_count()},
                          libraries={name: importlib.metadata.version(name) for name in ("httpx", "pydantic")})
            if overlap:
                raise StudyStopped("public seed overlap requires a newly reviewed protocol")
            collection_revision.cache_clear()
            for batch_index, concurrency in enumerate(CONCURRENCIES):
                batch = {"index": batch_index, "concurrency": concurrency, "wall_seconds": None,
                         "prepare_seconds": None, "validation_seconds": None, "cleanup": None, "peak_admitted": 0}
                batches.append(batch)
                provider, evidence, batch_start = None, None, None
                active = 0
                values = []
                batch["validation_seconds"] = 0.0
                try:
                    if time.monotonic()-started+SETUP_SECONDS+CLEANUP_SECONDS+FINAL_RESERVE+EPISODE_SECONDS > OVERALL_SECONDS:
                        raise StudyStopped("remaining overall time cannot reserve preparation and episode")
                    provider = make_provider(budget)
                    budget.phase = "metadata"
                    setup_started = time.monotonic()
                    async with asyncio.timeout(SETUP_SECONDS):
                        await provider.prepare()
                    batch["prepare_seconds"] = time.monotonic()-setup_started
                    if provider.model != MODEL or provider.model_digest != MODEL_DIGEST or not provider.prepared:
                        raise StudyStopped("prepared model identity differs; no chat permitted")
                    evidence = provider.evidence_metadata()
                    batch["provider_evidence"] = evidence
                    budget.phase = "chat"
                    batch_slots = scheduled[batch_index*8:(batch_index+1)*8]
                    for offset in range(0, 8, concurrency):
                        wave = batch_slots[offset:offset+concurrency]
                        current = source_identity(revision)
                        if current["files_sha256"] != source["files_sha256"] or plan()["protocol_sha256"] != fixed["protocol_sha256"]:
                            raise StudyStopped("source or fixture drift before wave admission")
                        if provider.model != MODEL or provider.model_digest != MODEL_DIGEST or provider.evidence_metadata() != evidence:
                            raise StudyStopped("provider drift before wave admission")
                        if budget.chat+MAX_STEPS*len(wave) > MAX_REQUESTS:
                            raise StudyStopped("remaining request budget cannot reserve whole wave")
                        if artifact_bytes(output)+EPISODE_RESERVE*len(wave)+REPORT_RESERVE > ARTIFACT_CAP:
                            raise StudyStopped("remaining artifact capacity cannot reserve whole wave")
                        if time.monotonic()-started+EPISODE_SECONDS+CLEANUP_SECONDS+FINAL_RESERVE > OVERALL_SECONDS:
                            raise StudyStopped("remaining overall time cannot reserve whole wave")

                        async def attempt(slot):
                            nonlocal active
                            slot["status"] = "attempted"
                            active += 1
                            batch["peak_admitted"] = max(batch["peak_admitted"], active)
                            try:
                                config = RunConfig(environment_id=WORLD, provider_id="local", model=MODEL, seed=slot["seed"],
                                                   episodes=1, concurrency=concurrency, max_steps=MAX_STEPS,
                                                   timeout_seconds=EPISODE_SECONDS, evaluation_only=True)
                                return slot, await rollout(config, 0, provider), None
                            except BaseException:
                                return slot, None, "rollout did not return a finalized envelope; details redacted"
                            finally:
                                active -= 1

                        if batch_start is None:
                            batch_start = time.monotonic()
                        for slot in wave:
                            slot["status"] = "attempted"
                        tasks = [asyncio.create_task(attempt(slot)) for slot in wave]
                        try:
                            results = await asyncio.gather(*tasks)
                        except asyncio.CancelledError:
                            for task in tasks:
                                task.cancel()
                            results = await asyncio.gather(*tasks, return_exceptions=True)
                            stop = "collection interrupted; remaining slots unattempted"
                        returned_wave = []
                        for planned, returned in zip(wave, results, strict=True):
                            slot, episode, error = (returned if isinstance(returned, tuple) else
                                (planned, None, "admitted rollout did not finalize; details redacted"))
                            row = {**slot, "verified": False, "primary_eligible": False, "passed": False,
                                   "clean_success": False, "counters_complete": False, "model_request_attempts": None}
                            row.update(status="inconclusive", raw_record_preserved=False,
                                       exact_envelope_preserved=False, diagnostic="raw persistence incomplete")
                            row["returned_value_available"] = error is None
                            rows.append(row)
                            returned_wave.append((slot, episode, error, row))
                        for slot, episode, error, row in returned_wave:
                            row.update(append_raw(raw, slot, episode, output, error))
                            row["raw_record_preserved"] = True
                            slot["status"] = "finalized" if row["exact_envelope_preserved"] else "inconclusive"
                            values.append((episode, slot, row))
                            if not row["exact_envelope_preserved"] or not row["within_reservation"]:
                                stop = row["diagnostic"] or "episode exceeded conservative reservation; full raw retained"
                        validation_start = time.monotonic()
                        for episode, slot, row in values:
                            if row["exact_envelope_preserved"]:
                                try:
                                    row.update(check_episode(episode, slot, source, evidence))
                                except (StudyStopped, ValueError, KeyError, TypeError, IndexError, AttributeError):
                                    row["diagnostic"] = "semantic or summary validation failed; exact raw retained"
                                    stop = stop or row["diagnostic"]
                        batch["validation_seconds"] += time.monotonic()-validation_start
                        values.clear()
                        if budget.violation or stop:
                            raise StudyStopped(stop or "request hook rejected scope or quota")
                        if sum(r["model_request_attempts"] for r in rows) != budget.chat:
                            raise StudyStopped("raw finalized request counts differ from transport hook; no later admission")
                    batch["wall_seconds"] = time.monotonic()-batch_start if batch_start is not None else None
                finally:
                    if batch_start is not None and batch["wall_seconds"] is None:
                        batch["wall_seconds"] = time.monotonic()-batch_start
                    if provider is not None:
                        try:
                            cleanup_started = time.monotonic()
                            async with asyncio.timeout(CLEANUP_SECONDS):
                                await provider.close()
                            batch["cleanup"] = {"status": "completed", "seconds": time.monotonic()-cleanup_started}
                        except BaseException:
                            batch["cleanup"] = {"status": "unconfirmed", "error": "provider cleanup incomplete; details redacted"}
                            stop = stop or "provider cleanup incomplete; no later batch admitted"
                if stop:
                    raise StudyStopped(stop)
                if source_identity(revision)["files_sha256"] != source["files_sha256"]:
                    raise StudyStopped("source drift after batch cleanup")
                if provider.model != MODEL or provider.model_digest != MODEL_DIGEST or provider.evidence_metadata() != evidence:
                    raise StudyStopped("provider identity drift after batch cleanup")
        except BaseException as error:
            stop = stop or (str(error) if isinstance(error, StudyStopped) else "collector stopped; details redacted")
        try:
            final_source = source_identity(revision)
            report["source_post"] = final_source
            if source is None or final_source["files_sha256"] != source["files_sha256"]:
                raise StudyStopped("source differs at final receipt gate")
        except BaseException:
            report["source_post_valid"] = False
            stop = stop or "final source verification incomplete; existing raw retained"
        else:
            report["source_post_valid"] = True
        report.update(status="stopped" if stop else "completed", stop_reason=stop,
                      comparison_approved=stop is None, elapsed_seconds=time.monotonic()-started,
                      chat_requests_started=budget.chat, metadata_requests_started=budget.metadata,
                      verified_episodes=sum(r["verified"] for r in rows), attempted_episodes=len(rows),
                      returned_values=sum(r["returned_value_available"] for r in rows),
                      raw_records_preserved=sum(r["raw_record_preserved"] for r in rows),
                      exact_raw_values=sum(r["exact_envelope_preserved"] for r in rows),
                      diagnostic_markers=sum(r["raw_record_preserved"] and not r["exact_envelope_preserved"] for r in rows),
                      raw_persistence_failures=sum(not r["raw_record_preserved"] for r in rows),
                      inconclusive_episodes=sum(not r["verified"] for r in rows),
                      unattempted_episodes=sum(s["status"] == "not_attempted" for s in scheduled),
                      analysis=summarize(rows, batches), raw_sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest())
        write_report(output, report)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--collect", action="store_true")
    mode.add_argument("--plan", action="store_true")
    parser.add_argument("--source-revision")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not args.collect:
        if args.output is not None or args.source_revision is not None:
            parser.error("collection flags require --collect")
        print(json.dumps(plan(), indent=2))
        return 0
    if args.output is None or not args.source_revision or not re.fullmatch(r"[0-9a-f]{40}", args.source_revision):
        parser.error("collection requires reviewed full --source-revision and fresh --output")
    result = asyncio.run(collect(args.output, args.source_revision))
    print(canonical_json({"status": result["status"], "verified_episodes": result["verified_episodes"], "stop_reason": result["stop_reason"]}))
    return int(result["status"] != "completed")


if __name__ == "__main__":
    raise SystemExit(main())
