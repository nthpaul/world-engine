"""Fixed local qualification; default plan is offline and contact-free."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path

import httpx

from world_engine.browser_contracts import relative_artifact_id
from world_engine.browser_policy import OPTIONS, PROTOCOL
from world_engine.gitlab_taskpacks import make_browser_task

ROOT = Path(__file__).resolve().parents[1]
API = "http://127.0.0.1:8000"
MODEL_DIGEST = "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41"
LIMIT = 640 * 1024 * 1024
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}
SLOTS = (
    {"name": "incomplete", "task_id": "gitlab-incident-triage", "seed": 42, "provider_id": "browser-baseline", "max_steps": 1, "timeout_seconds": 30},
    {"name": "triage-change", "task_id": "gitlab-incident-triage", "seed": 42, "provider_id": "browser-reference", "max_steps": 30, "timeout_seconds": 180},
    {"name": "triage-noop", "task_id": "gitlab-incident-triage", "seed": 43, "provider_id": "browser-reference", "max_steps": 30, "timeout_seconds": 180},
    {"name": "close-compatibility", "task_id": "gitlab-issue-close", "seed": 42, "provider_id": "browser-reference", "max_steps": 30, "timeout_seconds": 180},
    {"name": "model", "task_id": "gitlab-incident-triage", "seed": 42, "provider_id": "local-browser", "max_steps": 30, "timeout_seconds": 600},
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def plan():
    return {"schema": "world-engine.triage-qualification.v3", "slots": SLOTS, "model": "qwen3:8b",
            "model_digest": MODEL_DIGEST, "automatic_retries": 0, "paid_calls": False,
            "reference_protocol": "public-ax-triage-control-v3",
            "policy_protocol": PROTOCOL, "generation_options": dict(OPTIONS), "think": False,
            "max_total_seconds": 6000, "max_artifact_bytes": LIMIT, "evaluation_only": True,
            "training_eligible": False, "model_requires_explicit_flag_and_qualified_controls": True}


def source_identity(revision):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("a reviewed full source revision is required")
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    scope = ["src/world_engine", "pyproject.toml", "uv.lock", "scripts/collect_gitlab_triage.py",
             "tests/test_gitlab_triage_collector.py", "docs/gitlab-triage-protocol.md"]
    changed = subprocess.check_output(["git", "status", "--porcelain", "--", *scope], cwd=ROOT, text=True)
    if actual != revision or changed:
        raise RuntimeError("qualification requires pinned clean implementation and protocol")
    paths = subprocess.check_output(["git", "ls-files", "--", *scope], cwd=ROOT, text=True).splitlines()
    files = {path: sha((ROOT / path).read_bytes()) for path in paths}
    if not files or "scripts/collect_gitlab_triage.py" not in files:
        raise RuntimeError("collector source must be committed")
    modules = {name: sha((ROOT / "src/world_engine" / name).read_bytes()) for name in (
        "browser_contracts.py", "browser_runs.py", "browser_store.py", "browser_api.py",
        "browser_driver.py", "browser_policy.py", "gitlab_runtime.py", "gitlab_taskpacks.py")}
    return {"git_revision": actual, "files": files, "controller_modules": modules}


def reserve_output(output):
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError("fresh output required; existing evidence is never replaced")
    if any(parent.is_symlink() for parent in output.parents):
        raise ValueError("output parents must not be symlinks")
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    return output


def write(output, path, raw):
    used = sum(item.stat().st_size for item in output.rglob("*") if item.is_file())
    allowed = LIMIT if path == output / "report.json" else LIMIT - 1024 * 1024
    if used + len(raw) > allowed:
        raise RuntimeError("qualification artifact byte cap reached")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def save(output, path, value):
    write(output, path, (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode())


class Api:
    def __init__(self, client, output, deadline=float("inf")):
        self.client, self.output, self.index, self.deadline = client, output, 0, deadline

    def request(self, method, path, payload=None, limit=16 * 1024 * 1024):
        if method not in ("GET", "POST") or not path.startswith("/api/") or any(part in path for part in ("..", "?", "#")):
            raise ValueError("invalid fixed local API operation")
        if time.monotonic() >= self.deadline:
            raise TimeoutError("aggregate collection deadline reached")
        data = bytearray()
        with self.client.stream(method, API + path, json=payload, headers={"Accept-Encoding": "identity"}) as response:
            for chunk in response.iter_raw():
                if time.monotonic() >= self.deadline:
                    raise TimeoutError("aggregate collection deadline reached")
                if len(data) + len(chunk) > limit:
                    raise RuntimeError("bounded local response exceeded its cap")
                data.extend(chunk)
            raw = bytes(data)
            stem = self.output / "api-responses" / f"{self.index:05d}"
            self.index += 1
            write(self.output, stem.with_suffix(".body"), raw)
            save(self.output, stem.with_suffix(".json"), {"method": method, "path": path,
                 "status": response.status_code, "bytes": len(raw), "sha256": sha(raw)})
            if (response.status_code not in (200, 202) or str(response.url) != API + path
                    or response.headers.get("content-encoding", "identity") != "identity"):
                raise RuntimeError("local response rejected; no retry")
            return raw

    def json(self, method, path, payload=None):
        return json.loads(self.request(method, path, payload))


def validate_attempt(attempt, spec, source):
    expected = make_browser_task(spec["task_id"], spec["seed"]).model_dump()
    if attempt["task"] != expected:
        raise RuntimeError("attempt manifest does not match the fixed task")
    provenance = attempt["provenance"]
    if (provenance["source_git_revision"] != source["git_revision"] or provenance["source_dirty"] is not False
            or provenance["controller_modules"] != source["controller_modules"]):
        raise RuntimeError("API runtime source differs from reviewed collector pin")
    wanted = {key: value for key, value in spec.items() if key != "name"}
    wanted["model"] = "qwen3:8b"
    if attempt["config"] != wanted:
        raise RuntimeError("attempt configuration differs from fixed slot")


def controls_qualified(results, *, complete=True):
    if (complete and len(results) != 4) or not 1 <= len(results) <= 4:
        return False
    for index, result in enumerate(results):
        if (result["status"] != "completed" or result["termination"] != "finished"
                or result["invalid_actions"] != 0 or result["reconciliation_required"] is not False
                or result["cleanup"]["status"] != "completed"):
            return False
        expected = index != 0
        if result["passed"] is not expected or result["reward"] != float(expected):
            return False
        if expected and not all(check["passed"] is True for check in result["outcome"]["checks"]):
            return False
    return True


def validate_policy_identity(attempt, spec):
    prepared = [entry["data"] for entry in attempt["journal"] if entry["event"] == "policy_prepared"]
    if len(prepared) != 1:
        raise RuntimeError("one prepared policy identity is required; raw attempt retained")
    if spec["provider_id"] == "local-browser":
        if (prepared[0].get("model_digest") != MODEL_DIGEST
                or prepared[0].get("protocol") != PROTOCOL or prepared[0].get("options") != OPTIONS):
            raise RuntimeError("observed model identity differs; raw attempt retained")
    else:
        expected = {"protocol": "public-ax-triage-control-v3" if spec["task_id"] == "gitlab-incident-triage"
                    else "public-ax-browser-control-v1", "scripted_control": True,
                    "capability_measurement": False, "baseline": spec["provider_id"] == "browser-baseline",
                    "training_eligible": False}
        if prepared[0] != expected:
            raise RuntimeError("observed control identity differs; raw attempt retained")


def model_preflight():
    # Only selected public identity is used; no daemon catalogue or other model names are saved.
    with httpx.Client(timeout=10, trust_env=False, follow_redirects=False) as client:
        with client.stream("GET", "http://127.0.0.1:11434/api/tags", headers={"Accept-Encoding": "identity"}) as response:
            raw = bytearray()
            for chunk in response.iter_raw():
                if len(raw) + len(chunk) > 65536:
                    raise RuntimeError("local catalogue cap exceeded")
                raw.extend(chunk)
            if response.status_code != 200 or response.headers.get("content-encoding", "identity") != "identity":
                raise RuntimeError("local model identity preflight failed")
        entries = json.loads(raw)["models"]
        matches = [item for item in entries if item.get("name") == "qwen3:8b"]
        if (len(matches) != 1 or matches[0].get("digest") != MODEL_DIGEST
                or matches[0].get("remote_host") or matches[0].get("remote_model")):
            raise RuntimeError("fixed public local model identity differs")


def collect(output, revision, startup_revision, include_model=False):
    output = reserve_output(output)
    report = {**plan(), "slots": [{"name": spec["name"], "status": "unattempted"} for spec in SLOTS],
              "results": [], "status": "started", "api_startup_revision_attestation": startup_revision}
    started = time.monotonic()
    try:
        source = source_identity(revision)
        if startup_revision != revision:
            raise ValueError("operator API startup attestation must match source pin")
        report["source"] = source
        save(output, output / "protocol.json", plan())
        with httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
            api = Api(client, output, started + 6000)
            health = api.json("GET", "/api/health")
            status = api.json("GET", "/api/browser/status")
            if health["paid_calls_enabled"] is not False or status["paid_calls_enabled"] is not False or not status["available"] or status["active_attempts"]:
                raise RuntimeError("browser runtime must be available, idle and unpaid")
            for index, spec in enumerate(SLOTS):
                if index == 4:
                    if not include_model:
                        report["slots"][index]["reason"] = "model not explicitly authorized by invocation"
                        break
                    if not controls_qualified(report["results"]):
                        raise RuntimeError("all controls must qualify before the optional model slot")
                    model_preflight()
                if source_identity(revision) != source:
                    raise RuntimeError("source drift; later slots remain unattempted")
                if time.monotonic() - started > 4400:
                    raise RuntimeError("insufficient aggregate time for next attempt")
                directory = output / spec["name"]
                config = {key: value for key, value in spec.items() if key != "name"}
                config["model"] = "qwen3:8b"
                slot = report["slots"][index]
                save(output, directory / "submission-intent.json", config)
                slot["status"] = "submission_started"
                attempt = api.json("POST", "/api/browser/attempts", config)
                slot.update(status="submitted", id=attempt["id"])
                validate_attempt(attempt, spec, source)
                deadline = min(started + 6000, time.monotonic() + 1600)
                while attempt["status"] not in TERMINAL:
                    if time.monotonic() >= deadline:
                        slot["status"] = "active_completion_unknown"
                        raise RuntimeError("collector deadline; owned attempt preserved for operator reconciliation")
                    time.sleep(2)
                    raw = api.request("GET", f"/api/browser/attempts/{slot['id']}")
                    attempt = json.loads(raw)
                raw = api.request("GET", f"/api/browser/attempts/{slot['id']}")
                write(output, directory / "attempt.json", raw)
                attempt = json.loads(raw)
                validate_attempt(attempt, spec, source)
                slot["status"] = "terminal"
                report["results"].append({key: attempt[key] for key in ("id", "status", "termination", "steps",
                    "invalid_actions", "passed", "reward", "outcome", "cleanup", "reconciliation_required", "phase_seconds", "elapsed_seconds")})
                if len(attempt["artifacts"]) > 64:
                    raise RuntimeError("fixed attempt artifact count exceeded")
                for artifact in attempt["artifacts"]:
                    relative = relative_artifact_id(artifact["id"])
                    path = f"/api/browser/attempts/{slot['id']}/artifacts/{relative}"
                    if artifact["url"] != path:
                        raise RuntimeError("unexpected artifact URL")
                    body = api.request("GET", path, limit=128 * 1024 * 1024)
                    if len(body) != artifact["size_bytes"] or sha(body) != artifact["sha256"]:
                        raise RuntimeError("artifact integrity differs")
                    write(output, directory / relative, body)
                validate_policy_identity(attempt, spec)
                if index < 4 and not controls_qualified(report["results"], complete=False):
                    raise RuntimeError("control qualification failed; no retry or later attempts")
        if source_identity(revision) != source:
            raise RuntimeError("source drift after finalization")
        report["status"] = "completed"
    except Exception as error:
        report.update(status="stopped", error_category=type(error).__name__,
                      diagnostic="Qualification stopped; prior evidence and unattempted slots retained.")
    report["elapsed_seconds"] = time.monotonic() - started
    save(output, output / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collect", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--source-revision")
    parser.add_argument("--api-startup-revision")
    parser.add_argument("--include-model", action="store_true")
    args = parser.parse_args()
    if not args.collect:
        print(json.dumps(plan(), indent=2))
        return
    if args.output is None or args.source_revision is None or args.api_startup_revision is None:
        parser.error("collection requires fresh --output and both reviewed revision pins")
    report = collect(args.output, args.source_revision, args.api_startup_revision, args.include_model)
    print(json.dumps({"status": report["status"], "attempted": len(report["results"])}))
    if report["status"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
