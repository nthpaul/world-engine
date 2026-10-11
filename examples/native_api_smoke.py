"""Plan two fixed native API integration attempts; collection needs separate approval."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from uuid import UUID

import httpx

from world_engine.models import canonical_json, digest
from world_engine.native_config import NativeRunConfig
from world_engine.providers import local_metadata, local_model_entry

ROOT = Path(__file__).resolve().parents[1]
API, OLLAMA = "http://127.0.0.1:8000", "http://127.0.0.1:11434"
MODEL = "qwen3:8b"
MODEL_DIGEST = "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41"
ALIASES = (("local-tools", "ollama-tools-v1"), ("local-tools-ledger", "ollama-tools-ledger-v2"))
WORLD, VERSION, SEED = "refund-ops", "1.1.2", 54000
INITIAL_HASH = "754f37937fb65be8eeb6a7af4253de94e609fbb272aa382c0a46e6a95816ce04"
ENVIRONMENT_HASH = "4a89c019ccf09faec523b10e61128e13c0689c4ee4e94bb88dde4f5bcbad7f06"
GRADER_HASH = "56ae60240d24e1fb3eed4d7f29434174d674bddd7e1cdd0c9ddb2368529d22c7"
OVERALL_SECONDS, FINALIZE_SECONDS, POLL_SECONDS = 180, 10, .25
ARTIFACT_CAP, SLOT_RESERVE, REPORT_RESERVE = 64 * 1024**2, 31 * 1024**2, 1024**2
DETAIL_CAP, SMALL_CAP, CANCEL_RESERVE = 15 * 1024**2, 256 * 1024, 512 * 1024
JOURNAL_ENTRY_CAP = 2048
SOURCE_SCOPE = ["src/world_engine", "pyproject.toml", "uv.lock", "examples/native_api_smoke.py",
                "tests/test_native_api_smoke.py", "docs/native-api-smoke-protocol.md"]


class SmokeStopped(RuntimeError):
    """A safe failure that preserves the original evidence."""


def protocol() -> dict:
    return {"id": "native-api-smoke-v1", "api": API, "metadata_endpoint": OLLAMA,
            "aliases": ALIASES, "world": WORLD, "world_version": VERSION, "seed": SEED,
            "initial_hash": INITIAL_HASH, "environment_hash": ENVIRONMENT_HASH, "grader_hash": GRADER_HASH,
            "model": MODEL, "model_digest": MODEL_DIGEST, "episodes_per_alias": 1,
            "max_steps": 20, "episode_seconds": 35, "concurrency": 1,
            "evaluation_only": True, "allow_paid": False, "max_submissions": 2,
            "overall_seconds": OVERALL_SECONDS, "finalize_seconds": FINALIZE_SECONDS,
            "poll_seconds": POLL_SECONDS, "artifact_cap": ARTIFACT_CAP,
            "slot_reserve": SLOT_RESERVE, "report_reserve": REPORT_RESERVE,
            "detail_cap": DETAIL_CAP, "small_response_cap": SMALL_CAP,
            "cancel_reserve": CANCEL_RESERVE, "journal_entry_cap": JOURNAL_ENTRY_CAP, "retry_policy": "none",
            "options": {"temperature": 0, "num_predict": 512, "num_ctx": 8192}, "think": False}


def plan() -> dict:
    return {"protocol": protocol(), "protocol_sha256": digest(protocol()),
            "status": "plan-only; no API, source inspection, output files, or model contact"}


def source_identity(expected: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise SmokeStopped("source revision must be a reviewed full lowercase SHA")

    def git(*args):
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, timeout=3, check=True).stdout

    if git("rev-parse", "HEAD").decode().strip() != expected or git("status", "--porcelain", "--untracked-files=all", "--", *SOURCE_SCOPE):
        raise SmokeStopped("runtime, dependencies, collector, tests, and protocol must be committed and clean")
    paths = [*sorted((ROOT / "src/world_engine").rglob("*.py")),
             *(ROOT / name for name in SOURCE_SCOPE if not (ROOT / name).is_dir())]
    hashes = {}
    for path in paths:
        name = str(path.relative_to(ROOT))
        value = path.read_bytes()
        if value != git("show", f"{expected}:{name}"):
            raise SmokeStopped("source bytes differ from the reviewed commit")
        hashes[name] = hashlib.sha256(value).hexdigest()
    return {"git_revision": expected, "source_dirty": False, "files_sha256": hashes,
            "checkout_dirty": bool(git("status", "--porcelain", "--untracked-files=all"))}


def config_for(alias: str) -> NativeRunConfig:
    return NativeRunConfig(environment_id=WORLD, provider_id=alias, model=MODEL, seed=SEED,
                           episodes=1, max_steps=20, timeout_seconds=35, concurrency=1,
                           evaluation_only=True, allow_paid=False, label="native-api-smoke-v1")


def fixture_identity() -> dict:
    from world_engine.environments import make_environment
    from world_engine.rollout import world_fingerprints
    world = make_environment(WORLD, SEED)
    if (world.version != VERSION or digest(world.snapshot()) != INITIAL_HASH
            or world_fingerprints(world) != (ENVIRONMENT_HASH, GRADER_HASH)):
        raise SmokeStopped("fixed refund fixture differs from the reviewed protocol")
    return {"initial_state_hash": INITIAL_HASH, "environment_code_hash": ENVIRONMENT_HASH,
            "grader_code_hash": GRADER_HASH, "world_version": VERSION}


class Evidence:
    def __init__(self, output: Path):
        self.output, self.calls = output, []

    def size(self) -> int:
        return sum(path.stat().st_size for path in self.output.iterdir() if path.is_file())

    def write(self, name: str, body: bytes, *, reserve: int = REPORT_RESERVE + CANCEL_RESERVE):
        if self.size() + len(body) + reserve > ARTIFACT_CAP:
            raise SmokeStopped("artifact quota reached; prior raw evidence retained")
        with (self.output / name).open("xb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())

    async def exchange(self, client, method: str, route: str, payload=None, *, cap=SMALL_CAP,
                       reserve=REPORT_RESERVE + CANCEL_RESERVE):
        if self.size() + cap + JOURNAL_ENTRY_CAP + reserve > ARTIFACT_CAP:
            raise SmokeStopped("response reservation unavailable; no API request sent")
        body, status, complete, encoding, failed = bytearray(), None, False, "unknown", False
        try:
            async with client.stream(method, API + route, json=payload,
                                     headers={"Accept-Encoding": "identity"}, timeout=5) as response:
                status = response.status_code
                encoding = "identity" if response.headers.get("content-encoding", "identity").lower() == "identity" else "unsupported"
                async for chunk in response.aiter_raw(chunk_size=64 * 1024):
                    remaining = cap - len(body)
                    body.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        failed = True
                        break
                else:
                    complete = True
        except (httpx.HTTPError, asyncio.CancelledError):
            failed = True
        raw = bytes(body)
        name = hashlib.sha256(raw).hexdigest() + ".body"
        if not (self.output / name).exists():
            self.write(name, raw, reserve=reserve + JOURNAL_ENTRY_CAP)
        entry = {"index": len(self.calls), "method": method, "route": route, "http_status": status,
                 "body_file": name, "body_bytes": len(raw), "body_complete": complete,
                 "encoding": encoding, "response_sha256": hashlib.sha256(raw).hexdigest(),
                 "response_hash_scope": "complete-body" if complete else "observed-prefix"}
        self.calls.append(entry)
        encoded = (canonical_json(entry) + "\n").encode()
        if len(encoded) > JOURNAL_ENTRY_CAP or self.size() + len(encoded) + reserve > ARTIFACT_CAP:
            raise SmokeStopped("API journal quota reached; response body retained")
        with (self.output / "api-responses.jsonl").open("ab") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        if failed or not complete or encoding != "identity" or status not in (200, 202):
            raise SmokeStopped("API response failed its bounded protocol; raw retained")
        try:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError
            return value
        except (ValueError, UnicodeError, RecursionError):
            raise SmokeStopped("API JSON invalid; raw retained") from None


def check_episode(episode: dict, alias: str, selected_protocol: str, revision: str) -> dict:
    from world_engine.exports import export_records
    from world_engine.provider_records import usage_summary, validate_pairs
    from world_engine.rollout import replay
    provenance = episode["provenance"]
    expected = {"environment_id": WORLD, "environment_version": VERSION, "initial_state_hash": INITIAL_HASH,
                "environment_code_hash": ENVIRONMENT_HASH, "grader_code_hash": GRADER_HASH,
                "model": MODEL, "model_digest": MODEL_DIGEST, "provider_protocol": selected_protocol,
                "evaluation_only": True, "training_eligible": False, "git_revision": revision, "implementation_dirty": False}
    if any(canonical_json(provenance.get(key)) != canonical_json(value) for key, value in expected.items()) or episode["seed"] != SEED:
        raise SmokeStopped("episode identity differs from the fixed API/source/model contract")
    if replay(episode)["verified"] is not True:
        raise SmokeStopped("episode replay failed; raw retained")
    pairs = validate_pairs(episode["provider_events"], selected_protocol)
    if len(pairs) > 20:
        raise SmokeStopped("native request count exceeds the fixed decision budget")

    class CapturedStore:
        def get_run(self, run_id):
            return {}

        def episodes(self, run_id):
            return [episode]

        def candidates(self, *args):
            raise SmokeStopped("native training exclusion unexpectedly queried candidates")

    exclusions = {}
    for kind in ("sft", "dpo", "grpo"):
        records, selection = export_records(CapturedStore(), "captured-api-run", kind, "all")
        if records or selection["excluded"]["unsupported_provider_protocol"] != 1:
            raise SmokeStopped("native training exclusion failed")
        exclusions[kind] = selection["excluded"]
    return {"provider_id": alias, "verified": True, "episode_status": episode["status"], **{key: episode[key] for key in
            ("termination", "passed", "reward", "steps", "invalid_actions", "elapsed_seconds")},
            "native_request_attempts": len(pairs), "accepted": sum(end["outcome"] == "accepted" for _, end in pairs),
            "cancelled": sum(end["outcome"] == "cancelled" for _, end in pairs),
            "usage": usage_summary(episode["provider_events"]), "training_exclusions": exclusions}


async def collect(output: Path, revision: str, startup_revision: str, api: str = API) -> dict:
    if api not in (API, API + "/") or revision != startup_revision or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise SmokeStopped("approved fixed API and matching full startup/source revisions are required")
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    evidence, started = Evidence(output), time.monotonic()
    report = {"schema": "world-engine.native-api-smoke.v1", "protocol": protocol(), "protocol_sha256": digest(protocol()),
              "api_startup_revision": startup_revision, "startup_attestation": "operator supplied, not package-version source proof",
              "rows": [{"provider_id": alias, "protocol": selected, "status": "unattempted", "run_id": None}
                       for alias, selected in ALIASES], "status": "stopped", "error": None, "cancel_attempts": [],
              "client_metadata_attempts": 0, "server_metadata_requests": "not observed by this collector"}
    owned, cancelled = set(), set()
    try:
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
            try:
                async with asyncio.timeout(OVERALL_SECONDS - FINALIZE_SECONDS):
                    source = source_identity(revision)
                    report["source"], report["fixture"] = source, fixture_identity()
                    for row in report["rows"]:
                        if evidence.size() + SLOT_RESERVE + REPORT_RESERVE + CANCEL_RESERVE > ARTIFACT_CAP:
                            raise SmokeStopped("next-run reservation unavailable; no submission")
                        if source_identity(revision)["files_sha256"] != source["files_sha256"]:
                            raise SmokeStopped("source changed before submission")
                        health = await evidence.exchange(client, "GET", "/api/health")
                        if (health.get("status") != "ok" or health.get("version") != "0.1.0"
                                or health.get("paid_calls_enabled") is not False or type(health.get("active_runs")) is not int
                                or health["active_runs"] != 0):
                            raise SmokeStopped("API must be idle, healthy, expected-version, and paid-disabled")
                        report["client_metadata_attempts"] += 1
                        tags = await local_metadata(client, OLLAMA, "/api/tags", timeout=3)
                        models = tags.get("models", [])
                        selected = next((item for item in models if local_model_entry(item) and item["name"] == MODEL), None) if isinstance(models, list) else None
                        if selected is None or selected["digest"] != MODEL_DIGEST:
                            raise SmokeStopped("fixed installed public model digest unavailable; no submission")
                        row["preflight_model"] = {"name": MODEL, "digest": selected["digest"], "local_model_eligible": True}
                        if source_identity(revision)["files_sha256"] != source["files_sha256"]:
                            raise SmokeStopped("source changed during preflight; no submission")
                        config = config_for(row["provider_id"]).model_dump()
                        row["status"] = "admission_unknown"
                        admitted = await evidence.exchange(client, "POST", "/api/runs", config)
                        run_id = admitted.get("id")
                        if not isinstance(run_id, str) or str(UUID(run_id)) != run_id:
                            raise SmokeStopped("admission returned no canonical owned run identity")
                        owned.add(run_id)
                        row.update(run_id=run_id, status="started", config=config)
                        while True:
                            summaries = await evidence.exchange(client, "GET", "/api/runs?limit=100&offset=0")
                            run = next((item for item in summaries.get("runs", []) if isinstance(item, dict) and item.get("id") == run_id), None)
                            if run is None:
                                raise SmokeStopped("owned run missing from bounded summary page")
                            if run.get("status") in ("completed", "cancelled", "failed", "interrupted"):
                                break
                            if run.get("status") not in ("queued", "running"):
                                raise SmokeStopped("owned run status invalid")
                            await asyncio.sleep(POLL_SECONDS)
                        detail = await evidence.exchange(client, "GET", f"/api/runs/{run_id}", cap=DETAIL_CAP)
                        episodes = detail.get("episodes")
                        if not isinstance(episodes, list) or len(episodes) != 1 or not isinstance(episodes[0], dict):
                            raise SmokeStopped("terminal run has no single finalized episode; raw retained")
                        episode = episodes[0]
                        episode_file = f"{row['provider_id']}-episode.jsonl"
                        evidence.write(episode_file, (canonical_json({"evaluation_only": True,
                                       "training_eligible": False, "run_id": run_id, "episode": episode}) + "\n").encode())
                        row.update(status="raw_saved", episode_file=episode_file)
                        if detail.get("id") != run_id or canonical_json(detail.get("config")) != canonical_json(config):
                            raise SmokeStopped("terminal run/config identity mismatch; raw retained")
                        row.update(check_episode(episode, row["provider_id"], row["protocol"], revision))
                        row["status"] = "verified"
                        owned.remove(run_id)
                    if source_identity(revision)["files_sha256"] != source["files_sha256"]:
                        raise SmokeStopped("terminal source gate differs")
                    report["status"] = "completed"
            except (Exception, asyncio.CancelledError) as error:
                report["error"] = str(error) if isinstance(error, SmokeStopped) else "collector stopped; details redacted"
            finally:
                for run_id in owned:
                    if run_id in cancelled:
                        continue
                    cancelled.add(run_id)
                    item = {"run_id": run_id, "status": "attempted"}
                    report["cancel_attempts"].append(item)
                    try:
                        async with asyncio.timeout(3):
                            await evidence.exchange(client, "POST", f"/api/runs/{run_id}/cancel", reserve=REPORT_RESERVE)
                        item["status"] = "response_received; not proof of daemon closure"
                    except (Exception, asyncio.CancelledError):
                        item["status"] = "failed; details redacted"
    except (Exception, asyncio.CancelledError):
        report["error"] = report["error"] or "collector transport setup/closure failed; details redacted"
        report["status"] = "stopped"
    try:
        report["source_post"] = source_identity(revision)
        if report["source_post"]["files_sha256"] != report["source"]["files_sha256"]:
            raise SmokeStopped("terminal source changed; raw retained")
    except (Exception, asyncio.CancelledError):
        report["status"] = "stopped"
        report["source_post_error"] = "terminal source could not be verified; details redacted"
    report.update(api_response_count=len(evidence.calls), elapsed_seconds=time.monotonic() - started,
                  elapsed_scope="preflight through cleanup/source postcheck, before final report write",
                  submission_attempts=sum(call["method"] == "POST" and call["route"] == "/api/runs" for call in evidence.calls),
                  verified_episodes=sum(row["status"] == "verified" for row in report["rows"]),
                  unattempted_slots=sum(row["status"] == "unattempted" for row in report["rows"]))
    counted = [row for row in report["rows"] if "native_request_attempts" in row]
    report["native_counts"] = {"scope": "recorded native transport, not attested model executions",
                               "complete": len(counted) == 2,
                               **{key: sum(row[key] for row in counted) if counted else None
                                  for key in ("native_request_attempts", "accepted", "cancelled")}}
    report["files"] = {path.name: {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                       for path in output.iterdir() if path.is_file()}
    for _ in range(8):
        data = (canonical_json(report) + "\n").encode()
        if report.get("report_bytes") == len(data):
            break
        report.update(report_bytes=len(data), artifact_total_bytes=evidence.size() + len(data))
    if len(data) > REPORT_RESERVE:
        raise SmokeStopped("report exceeded its reserved limit; raw retained")
    evidence.write("report.json", data, reserve=0)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--collect", action="store_true")
    parser.add_argument("--source-revision")
    parser.add_argument("--api-startup-revision")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--api", "--API", default=API)
    args = parser.parse_args(argv)
    if not args.collect:
        if args.source_revision or args.api_startup_revision or args.output or args.api != API:
            parser.error("collection flags require --collect")
        print(json.dumps(plan(), indent=2))
        return 0
    if (args.output is None or args.source_revision != args.api_startup_revision
            or not re.fullmatch(r"[0-9a-f]{40}", args.source_revision or "") or args.api not in (API, API + "/")):
        parser.error("collection requires matching reviewed source/startup SHA, fresh output, and fixed loopback API")
    report = asyncio.run(collect(args.output, args.source_revision, args.api_startup_revision, args.api))
    print(json.dumps({key: report[key] for key in ("status", "error", "verified_episodes", "unattempted_slots", "artifact_total_bytes")}))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
