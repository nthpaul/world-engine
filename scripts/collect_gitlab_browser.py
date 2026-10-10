"""Collect the fixed, local-only GitLab pilot through its operator API."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from world_engine.browser_contracts import relative_artifact_id

ROOT = Path(__file__).resolve().parents[1]
API = "http://127.0.0.1:8000"
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}
MODULES = ("browser_contracts.py", "browser_runs.py", "browser_store.py", "browser_api.py",
           "browser_driver.py", "browser_policy.py", "gitlab_runtime.py")
ATTEMPTS = (
    {"name": "incomplete", "provider_id": "browser-baseline", "max_steps": 1, "timeout_seconds": 30},
    {"name": "reference", "provider_id": "browser-reference", "max_steps": 30, "timeout_seconds": 180},
    {"name": "model", "provider_id": "local-browser", "max_steps": 30, "timeout_seconds": 600},
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save(path: Path, value: dict) -> None:
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def source_identity() -> dict:
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if subprocess.run(["git", "diff", "--quiet", "HEAD"], cwd=ROOT, check=False).returncode:
        raise RuntimeError("collection requires unchanged committed source")
    untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"],
                                       cwd=ROOT, text=True).splitlines()
    if any(path.startswith(("src/", "tests/", "scripts/", "examples/", "web/src/")) for path in untracked):
        raise RuntimeError("collection refuses untracked runtime or collector source")
    return {"git_revision": revision, "controller_modules": {
        name: digest((ROOT / "src/world_engine" / name).read_bytes()) for name in MODULES},
        "protocol_sha256": digest((ROOT / "docs/gitlab-browser-protocol.md").read_bytes()),
        "collector_sha256": digest(Path(__file__).read_bytes()), "untracked_non_source_paths": untracked}


def request(client: httpx.Client, method: str, path: str, *, payload: dict | None = None,
            limit: int = 32 * 1024 * 1024, evidence: Path | None = None) -> bytes:
    if not path.startswith("/api/") or ".." in path or "?" in path or "#" in path:
        raise ValueError("invalid local API path")
    with client.stream(method, API + path, json=payload) as response:
        chunks, size = [], 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > limit:
                raise RuntimeError("local API response exceeded its bound")
            chunks.append(chunk)
        raw = b"".join(chunks)
        if evidence is not None:
            evidence.mkdir(exist_ok=True, mode=0o700)
            if sum(file.stat().st_size for file in evidence.iterdir()) + len(raw) > 256 * 1024 * 1024:
                raise RuntimeError("API response evidence exceeds its bound")
            index = len(list(evidence.glob("*.json")))
            with (evidence / f"{index:04d}.body").open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            save(evidence / f"{index:04d}.json", {"method": method, "path": path, "status": response.status_code,
                                               "bytes": len(raw), "sha256": digest(raw)})
        if response.status_code not in (200, 202) or response.url.host != "127.0.0.1":
            raise RuntimeError("local API request failed; no automatic retry")
        return raw


def json_request(client, method, path, payload=None, *, evidence=None):
    return json.loads(request(client, method, path, payload=payload, evidence=evidence))


def validate_source(attempt: dict, source: dict) -> None:
    provenance = attempt["provenance"]
    if (provenance["source_git_revision"] != source["git_revision"] or provenance["source_dirty"] is not False
            or provenance["controller_modules"] != source["controller_modules"]):
        raise RuntimeError("running controller does not match the pinned source")


def collect_attempt(client, output: Path, spec: dict, source: dict, slot: dict) -> dict:
    directory = output / spec["name"]
    directory.mkdir(mode=0o700)
    config = {key: value for key, value in spec.items() if key != "name"}
    config.update(task_id="gitlab-issue-close", model="qwen3:8b", seed=42)
    save(directory / "submission-intent.json", {"at": datetime.now(timezone.utc).isoformat(), "config": config})
    slot["status"] = "submission_started"
    attempt = json_request(client, "POST", "/api/browser/attempts", config, evidence=output / "api-responses")
    slot.update(status="submitted", id=attempt["id"])
    save(directory / "submission-result.json", attempt)
    validate_source(attempt, source)
    key = attempt["id"]
    previous = None
    deadline = time.monotonic() + 1600
    with (directory / "progress.jsonl").open("x") as progress:
        while True:
            summaries = json_request(client, "GET", "/api/browser/attempts", evidence=output / "api-responses")
            attempt = next(item for item in summaries["attempts"] if item["id"] == key)
            state = {name: attempt[name] for name in ("id", "status", "steps", "termination", "updated_at")}
            if state != previous:
                progress.write(json.dumps(state, sort_keys=True) + "\n")
                progress.flush()
                print(spec["name"], state["status"], "steps", state["steps"], flush=True)
                previous = state
            if attempt["status"] in TERMINAL:
                attempt = json_request(client, "GET", f"/api/browser/attempts/{key}", evidence=output / "api-responses")
                break
            if time.monotonic() > deadline:
                save(directory / "collector-timeout.json", {"attempt_id": key, "active_attempt_preserved": True})
                raise RuntimeError("collector deadline exceeded; attempt is preserved, no retry")
            time.sleep(2)
    validate_source(attempt, source)
    save(directory / "attempt.json", attempt)
    total = 0
    for artifact in attempt["artifacts"]:
        relative = relative_artifact_id(artifact["id"])
        expected_url = f"/api/browser/attempts/{key}/artifacts/{relative}"
        if artifact["url"] != expected_url:
            raise RuntimeError("unexpected artifact URL")
        total += artifact["size_bytes"]
        if total > 128 * 1024 * 1024:
            raise RuntimeError("collected media exceeds its bound")
        data = request(client, "GET", expected_url, limit=128 * 1024 * 1024)
        if len(data) != artifact["size_bytes"] or digest(data) != artifact["sha256"]:
            raise RuntimeError("artifact integrity mismatch")
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with target.open("xb") as stream:
            stream.write(data)
    return {name: attempt[name] for name in ("id", "status", "termination", "passed", "reward", "steps",
                                            "invalid_actions", "outcome", "cleanup", "elapsed_seconds", "phase_seconds")}


def collect(output: Path) -> dict:
    output = output.absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError("refusing to replace existing collection evidence")
    source = source_identity()
    output.mkdir(parents=True, mode=0o700)
    receipt = {"schema": "world-engine.gitlab-cohort.v1", "source": source, "results": [],
               "slots": [{"name": spec["name"], "status": "unattempted"} for spec in ATTEMPTS],
               "automatic_retries": 0, "paid_resources": False, "status": "started"}
    save(output / "protocol.json", {**receipt, "attempts": ATTEMPTS, "api": API})
    try:
        with httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
            health = json_request(client, "GET", "/api/health", evidence=output / "api-responses")
            status = json_request(client, "GET", "/api/browser/status", evidence=output / "api-responses")
            if health.get("paid_calls_enabled") or status.get("paid_calls_enabled") or not status["available"] or status["active_attempts"]:
                raise RuntimeError("local runtime is unavailable, busy, or paid calls are enabled")
            save(output / "preflight.json", {"health": health, "browser_status": status,
                                           "tasks": json_request(client, "GET", "/api/browser/tasks", evidence=output / "api-responses")})
            for spec, slot in zip(ATTEMPTS, receipt["slots"], strict=True):
                result = collect_attempt(client, output, spec, source, slot)
                slot.update(result)
                receipt["results"].append({"name": spec["name"], **result})
                save(output / f"{spec['name']}-receipt.json", result)
                required_outcome = spec["name"] == "reference"
                if (spec["name"] != "model" and (result["status"] != "completed"
                        or result["cleanup"]["status"] != "completed" or result["passed"] != required_outcome)):
                    receipt["unattempted"] = [entry["name"] for entry in ATTEMPTS[len(receipt["results"]):]]
                    raise RuntimeError("control qualification failed; later attempts remain unattempted")
        if source_identity()["controller_modules"] != source["controller_modules"]:
            raise RuntimeError("source changed during collection")
        receipt["status"] = "completed"
    except Exception as error:
        receipt["status"] = "failed"
        receipt["error_type"] = type(error).__name__
        receipt["error"] = str(error) if isinstance(error, (RuntimeError, FileExistsError)) else "collection failed; details redacted"
        raise
    finally:
        save(output / "receipt.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    if args.plan:
        print(json.dumps({"attempts": ATTEMPTS, "automatic_retries": 0, "paid_resources": False}, indent=2))
    else:
        print(json.dumps(collect(args.output), indent=2))


if __name__ == "__main__":
    main()
