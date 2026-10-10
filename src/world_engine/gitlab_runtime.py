"""One local, controller-owned GitLab CE instance per real-browser attempt."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import secrets
import socket
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr

from .browser_contracts import (
    BrowserCleanupError,
    BrowserCredentials,
    BrowserError,
    CleanupResult,
    GradeResult,
    RuntimeHandle,
    SealedState,
    TaskPack,
)

GITLAB_VERSION = "19.4.1"
APP_DIGEST = "sha256:7fff8748a25202c1d38885797510afe055f555856f3f50c2b17466a853be5d24"
APP_IMAGE = f"gitlab/gitlab-ce@{APP_DIGEST}"
VERIFIER_BASE = "sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641"
OWNER_LABEL = "world-engine.gitlab-owner"
MAX_STATE_BYTES = 8 * 1024 * 1024
ROOT = Path(__file__).resolve().parent / "taskpacks" / "gitlab"
COMMENT = "Release checklist verified; ready for closure."
MARKER = "Deployment reference: REL-2026-1042"


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def gitlab_task(seed: int = 42) -> TaskPack:
    fixture = json.dumps(
        {
            "marker": MARKER,
            "comment": COMMENT,
            "comment_internal": False,
            "schema": "gitlab-fixture-v1",
            "seed": seed,
            "ordering": "rotate-three-descriptions-by-seed-modulo-three",
            "project": "Release Operations",
            "agent_role": 30,
            "auditor_role": 20,
            "issue_count": 3,
            "existing_note": "Original release coordination note; retain this history.",
            "fixture_source_sha256": _hash(Path(__file__).read_bytes()),
            "config_sha256": _hash((ROOT / "config.rb").read_bytes()),
            "export_sha256": _hash((ROOT / "export.rb").read_bytes()),
        },
        sort_keys=True,
    )
    return TaskPack(
        id="gitlab-issue-close",
        version="1.0.1",
        name="GitLab release issue closure",
        instruction=(
            f"In Release Operations, find the open issue whose description says {MARKER}. "
            f"Add exactly this comment: {COMMENT} Then close that issue. "
            "Use an ordinary comment, not an internal note. Leave other issues, "
            "existing comments and project access unchanged."
        ),
        application="GitLab CE",
        application_version=GITLAB_VERSION,
        image_digest=APP_DIGEST,
        fixture_hash=_hash(fixture.encode()),
        grader_version="gitlab-state-v2",
        seed=seed,
    )


TASK_PACK = gitlab_task()


class GitLabRuntimeError(BrowserError):
    """Public errors never contain controller credentials or Docker stderr."""


class GitLabRuntime:
    def __init__(self, *, readiness_seconds: float = 450, verifier_image: str | None = None):
        if (
            type(readiness_seconds) not in (int, float)
            or not math.isfinite(readiness_seconds)
            or not 0 < readiness_seconds <= 450
        ):
            raise ValueError("readiness must be finite and at most 450 seconds")
        self.readiness_seconds = readiness_seconds
        self.verifier_image = verifier_image
        self._instances: dict[str, dict[str, Any]] = {}
        self._closed: dict[str, RuntimeHandle] = {}
        self._admission = asyncio.Lock()
        self._endpoint: str | None = None
        self._env = {key: os.environ[key] for key in ("HOME", "PATH", "DOCKER_CONFIG") if key in os.environ}

    async def _docker(
        self, *args: str, data: bytes | None = None, timeout: float = 60, env: dict[str, str] | None = None
    ) -> bytes:
        process = await asyncio.create_subprocess_exec(
            "docker",
            *(["--host", self._endpoint] if self._endpoint else []),
            *args,
            stdin=asyncio.subprocess.PIPE if data is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=self._env if env is None else env,
        )

        async def exchange() -> bytes:
            if data is not None:
                process.stdin.write(data)
                await process.stdin.drain()
                process.stdin.close()
            chunks, size = [], 0
            while chunk := await process.stdout.read(65_536):
                size += len(chunk)
                if size > MAX_STATE_BYTES:
                    raise GitLabRuntimeError("GitLab state exceeds bounded export size")
                chunks.append(chunk)
            await process.wait()
            return b"".join(chunks)

        try:
            out = await asyncio.wait_for(exchange(), timeout)
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        if process.returncode:
            raise GitLabRuntimeError("owned GitLab Docker operation failed")
        return out

    async def _inspect(self, kind: str, name: str) -> dict:
        raw = await self._docker(kind, "inspect", name)
        result = json.loads(raw)
        if not isinstance(result, list) or len(result) != 1 or not isinstance(result[0], dict):
            raise GitLabRuntimeError("invalid owned-resource inspection")
        return result[0]

    async def _local_docker(self) -> None:
        if self._endpoint is not None:
            return
        endpoint = os.environ.get("DOCKER_HOST")
        if endpoint is None:
            context = os.environ.get("DOCKER_CONTEXT")
            if context and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", context):
                raise GitLabRuntimeError("invalid local Docker context")
            raw = await self._docker(
                "context",
                "inspect",
                *([context] if context else []),
                "--format",
                "{{json .Endpoints.docker.Host}}",
            )
            endpoint = json.loads(raw)
        if (
            not isinstance(endpoint, str)
            or not endpoint.startswith("unix:///")
            or len(endpoint) > 4096
            or any(char in endpoint for char in ("\x00", "?", "#", "\n", "\r"))
        ):
            raise GitLabRuntimeError("only a local Unix Docker daemon is permitted")
        self._endpoint = endpoint

    async def start(self, attempt_id: str, task: TaskPack, directory: Path) -> RuntimeHandle:
        if self._instances or self._admission.locked():
            raise GitLabRuntimeError("GitLab admission is limited to one instance")
        async with self._admission:
            return await self._start(attempt_id, task, directory)

    async def _prepare_verifier(self) -> str:
        code_hash = _hash((ROOT / "verify.py").read_bytes())
        build_hash = _hash((ROOT / "verifier.Dockerfile").read_bytes())
        if self.verifier_image is None:
            await self._inspect("image", VERIFIER_BASE)
            tag = f"world-engine-gitlab-verifier:{code_hash[:24]}"
            await self._docker(
                "build",
                "--pull=false",
                "--network=none",
                "--label",
                f"world-engine.gitlab-grader-sha256={code_hash}",
                "--label",
                f"world-engine.gitlab-grader-build-sha256={build_hash}",
                "--tag",
                tag,
                "--file",
                str(ROOT / "verifier.Dockerfile"),
                str(ROOT),
                timeout=120,
            )
            image = await self._inspect("image", tag)
        else:
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.verifier_image):
                raise GitLabRuntimeError("verifier must be pinned to an image digest")
            image = await self._inspect("image", self.verifier_image)
        if image.get("Config", {}).get("Labels", {}).get("world-engine.gitlab-grader-sha256") != code_hash:
            raise GitLabRuntimeError("verifier image does not attest current grader source")
        if (
            image.get("Config", {}).get("Labels", {}).get("world-engine.gitlab-grader-build-sha256")
            != build_hash
        ):
            raise GitLabRuntimeError("verifier image does not match current build recipe")
        self.verifier_image = image["Id"]
        return image["Id"]

    async def _prepare_relay(self) -> str:
        code_hash = _hash((ROOT / "relay.py").read_bytes())
        tag = f"world-engine-gitlab-relay:{code_hash[:24]}"
        await self._docker(
            "build",
            "--pull=false",
            "--network=none",
            "--label",
            f"world-engine.gitlab-relay-sha256={code_hash}",
            "--tag",
            tag,
            "--file",
            str(ROOT / "relay.Dockerfile"),
            str(ROOT),
            timeout=120,
        )
        image = await self._inspect("image", tag)
        return image["Id"]

    async def _start(self, attempt_id: str, task: TaskPack, directory: Path) -> RuntimeHandle:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", attempt_id) or task.id != "gitlab-issue-close":
            raise GitLabRuntimeError("unsupported GitLab attempt or task")
        expected = gitlab_task(task.seed)
        if task != expected:
            raise GitLabRuntimeError("GitLab task manifest does not match trusted implementation")
        directory = Path(directory)
        if directory.is_symlink() or not directory.is_dir():
            raise GitLabRuntimeError("attempt directory must be an existing real directory")
        if directory.stat().st_uid != os.getuid():
            raise GitLabRuntimeError("attempt directory must belong to the controller user")
        directory = directory.resolve()
        directory.chmod(0o700)
        await self._local_docker()
        for kind in ("container", "volume", "network"):
            ids = await self._docker(
                kind,
                "ls",
                *(["--all"] if kind == "container" else []),
                "--quiet",
                "--filter",
                f"label={OWNER_LABEL}",
            )
            if ids.strip():
                raise BrowserCleanupError("unreconciled GitLab resources require operator cleanup")
        image = json.loads(await self._docker("image", "inspect", APP_IMAGE))
        if image[0]["Architecture"] != "arm64":
            raise GitLabRuntimeError("approved native arm64 GitLab image is required")
        verifier_image = await self._prepare_verifier()
        relay_image = await self._prepare_relay()
        owner = secrets.token_hex(12)
        name = f"world-engine-gitlab-{owner}"
        network = f"{name}-net"
        frontend = f"{name}-front"
        relay_name = f"{name}-relay"
        volumes = [f"{name}-{suffix}" for suffix in ("config", "logs", "data")]
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        origin = f"http://127.0.0.1:{port}"
        password = secrets.token_urlsafe(30)
        handle = RuntimeHandle(
            instance_id=name,
            origin=origin,
            start_url=f"{origin}/dashboard/projects",
            artifact_root=directory,
            agent_credentials=BrowserCredentials("workflow-agent", SecretStr(password)),
            runtime_metadata={
                "application_version": GITLAB_VERSION,
                "image_digest": APP_DIGEST,
                "image_id": image[0]["Id"],
                "config_sha256": _hash((ROOT / "config.rb").read_bytes()),
                "fixture_sha256": task.fixture_hash,
                "grader_sha256": _hash((ROOT / "verify.py").read_bytes()),
                "export_sha256": _hash((ROOT / "export.rb").read_bytes()),
                "grader_build_sha256": _hash((ROOT / "verifier.Dockerfile").read_bytes()),
                "grader_image_id": verifier_image,
                "relay_image_id": relay_image,
                "relay_sha256": _hash((ROOT / "relay.py").read_bytes()),
                "isolation": "local Docker development only; privileged host trusted",
            },
        )
        record = {
            "handle": handle,
            "owner": owner,
            "networks": [network, frontend],
            "containers": [relay_name, name],
            "volumes": volumes,
            "baseline": None,
            "expected": None,
            "task": task,
            "sealed": False,
        }
        self._instances[name] = record
        try:
            path = directory / "runtime-resources.json"
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "w") as stream:
                json.dump(
                    {
                        "owner_label": OWNER_LABEL,
                        "owner": owner,
                        "containers": record["containers"],
                        "volumes": volumes,
                        "networks": record["networks"],
                    },
                    stream,
                    sort_keys=True,
                )
                stream.flush()
                os.fsync(stream.fileno())
            await self._docker(
                "network", "create", "--internal", "--label", f"{OWNER_LABEL}={owner}", network
            )
            await self._docker("network", "create", "--label", f"{OWNER_LABEL}={owner}", frontend)
            for volume in volumes:
                await self._docker("volume", "create", "--label", f"{OWNER_LABEL}={owner}", volume)
            config = (ROOT / "config.rb").read_text()
            await self._docker(
                "run",
                "--detach",
                "--pull",
                "never",
                "--platform",
                "linux/arm64",
                "--name",
                name,
                "--label",
                f"{OWNER_LABEL}={owner}",
                "--network",
                network,
                "--memory",
                "4g",
                "--memory-swap",
                "4g",
                "--cpus",
                "4",
                "--pids-limit",
                "1024",
                "--shm-size",
                "256m",
                "--log-driver",
                "local",
                "--log-opt",
                "max-size=10m",
                "--log-opt",
                "max-file=2",
                "--env",
                f"WORLD_ENGINE_GITLAB_URL={origin}",
                "--env",
                f"GITLAB_OMNIBUS_CONFIG={config}",
                "--mount",
                f"type=volume,source={volumes[0]},target=/etc/gitlab",
                "--mount",
                f"type=volume,source={volumes[1]},target=/var/log/gitlab",
                "--mount",
                f"type=volume,source={volumes[2]},target=/var/opt/gitlab",
                APP_IMAGE,
            )
            await self._docker(
                "run",
                "--detach",
                "--pull",
                "never",
                "--name",
                relay_name,
                "--label",
                f"{OWNER_LABEL}={owner}",
                "--network",
                frontend,
                "--publish",
                f"127.0.0.1:{port}:8080",
                "--env",
                f"GITLAB_UPSTREAM={name}",
                "--read-only",
                "--user",
                "65534:65534",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--memory",
                "64m",
                "--memory-swap",
                "64m",
                "--cpus",
                "0.5",
                "--pids-limit",
                "32",
                "--log-driver",
                "none",
                relay_image,
            )
            await self._docker("network", "connect", network, relay_name)
            await self._ready(handle)
            await self._fixture(record, task, password)
            await self._docker("exec", handle.instance_id, "gitlab-ctl", "stop", "sidekiq", timeout=40)
            record["baseline"] = await self._export(handle)
            handle.runtime_metadata["baseline_sha256"] = _hash(
                json.dumps(
                    record["baseline"], sort_keys=True, separators=(",", ":"), ensure_ascii=True
                ).encode()
            )
            return handle
        except BaseException:
            # Persist selected status only, never startup logs or inspect/config secrets.
            try:
                info = await self._inspect("container", name)
                safe = {key: info["State"].get(key) for key in ("Status", "Running", "OOMKilled", "ExitCode")}
                with (directory / "runtime-startup-failure.json").open("x") as stream:
                    json.dump(safe, stream, sort_keys=True)
                    stream.flush()
                    os.fsync(stream.fileno())
            except Exception:
                pass
            cleanup = await asyncio.shield(self.close(handle))
            if cleanup.status != "completed":
                raise BrowserCleanupError("GitLab startup cleanup failed; runtime remains blocked") from None
            raise

    async def _ready(self, handle: RuntimeHandle) -> None:
        deadline = asyncio.get_running_loop().time() + self.readiness_seconds
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            while asyncio.get_running_loop().time() < deadline:
                info = await self._inspect("container", handle.instance_id)
                if info["State"].get("OOMKilled") or not info["State"]["Running"]:
                    raise GitLabRuntimeError("GitLab exited before readiness")
                try:
                    response = await client.get(f"{handle.origin}/users/sign_in")
                    if (
                        response.status_code == 200
                        and info["State"].get("Health", {}).get("Status") == "healthy"
                    ):
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(3)
        raise GitLabRuntimeError("GitLab readiness deadline exceeded")

    async def _rails(self, handle: RuntimeHandle, script: str) -> bytes:
        return await self._docker(
            "exec",
            "--interactive",
            handle.instance_id,
            "gitlab-rails",
            "runner",
            "-",
            data=script.encode(),
            timeout=90,
        )

    async def _fixture(self, record: dict, task: TaskPack, password: str) -> None:
        handle = record["handle"]
        token = secrets.token_hex(24)
        script = (
            "u=User.find_by!(username: 'root'); "
            "t=u.personal_access_tokens.create!(name: 'world-engine-reset', scopes: ['api'], "
            f"expires_at: 1.day.from_now); t.set_token({json.dumps(token)}); t.save!"
        )
        await self._rails(handle, script)
        try:
            async with httpx.AsyncClient(
                base_url=f"{handle.origin}/api/v4",
                timeout=30,
                headers={"PRIVATE-TOKEN": token},
                trust_env=False,
            ) as client:

                async def post(path: str, data: dict) -> dict:
                    response = await client.post(path, json=data)
                    if response.status_code not in (200, 201):
                        raise GitLabRuntimeError("trusted GitLab fixture creation failed")
                    return response.json()

                agent = await post(
                    "/users",
                    {
                        "email": "agent@example.invalid",
                        "username": "workflow-agent",
                        "name": "Workflow Agent",
                        "password": password,
                        "skip_confirmation": True,
                    },
                )
                auditor = await post(
                    "/users",
                    {
                        "email": "auditor@example.invalid",
                        "username": "release-auditor",
                        "name": "Release Auditor",
                        "password": secrets.token_urlsafe(30),
                        "skip_confirmation": True,
                    },
                )
                project = await post(
                    "/projects",
                    {
                        "name": "Release Operations",
                        "path": "release-operations",
                        "visibility": "private",
                        "issues_enabled": True,
                        "builds_enabled": False,
                        "container_registry_enabled": False,
                    },
                )
                project_id = project["id"]
                await post(f"/projects/{project_id}/members", {"user_id": agent["id"], "access_level": 30})
                await post(f"/projects/{project_id}/members", {"user_id": auditor["id"], "access_level": 20})
                descriptions = [
                    "Deployment reference: REL-2026-1041",
                    MARKER,
                    "Deployment reference: REL-2026-1043",
                ]
                # Seed controls fixture ordering, not an answer exposed through the observation contract.
                offset = task.seed % 3
                descriptions = descriptions[offset:] + descriptions[:offset]
                target = None
                for description in descriptions:
                    issue = await post(
                        f"/projects/{project_id}/issues",
                        {
                            "title": "Release checklist review",
                            "description": f"{description}\nReview the release checklist before closing.",
                        },
                    )
                    await post(
                        f"/projects/{project_id}/issues/{issue['iid']}/notes",
                        {"body": "Original release coordination note; retain this history."},
                    )
                    if description == MARKER:
                        target = issue["id"]
                record["expected"] = {
                    "project_id": project_id,
                    "target_issue_id": target,
                    "agent_id": agent["id"],
                    "comment": COMMENT,
                }
        finally:
            await self._rails(
                handle,
                "User.find_by!(username: 'root').personal_access_tokens."
                "where(name: 'world-engine-reset').update_all(revoked: true); "
                "Users::Internal.duo_code_review_bot; "
                "Project.update_all(has_external_wiki: false)",
            )

    async def _export(self, handle: RuntimeHandle) -> dict:
        raw = await self._rails(handle, (ROOT / "export.rb").read_text())
        try:
            value = json.loads(raw)
        except (ValueError, TypeError):
            raise GitLabRuntimeError("trusted GitLab state export was malformed") from None
        return value

    def _owned(self, handle: RuntimeHandle) -> dict:
        record = self._instances.get(handle.instance_id)
        if record is None or record["handle"] is not handle:
            raise GitLabRuntimeError("unknown GitLab runtime handle")
        return record

    async def seal(self, handle: RuntimeHandle) -> SealedState:
        record = self._owned(handle)
        if record["sealed"]:
            raise GitLabRuntimeError("GitLab state already sealed")
        await self._docker("stop", "--time", "5", record["containers"][0], timeout=15)
        await self._docker("exec", handle.instance_id, "gitlab-ctl", "stop", "puma")
        await self._docker("exec", handle.instance_id, "gitlab-ctl", "stop", "sidekiq")
        final = await self._export(handle)
        await self._docker("stop", "--time", "30", handle.instance_id, timeout=60)
        payload = {
            "schema": "world-engine-gitlab-sealed-v1",
            "baseline": record["baseline"],
            "final": final,
            "expected": record["expected"],
            "provenance": handle.runtime_metadata,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        if len(raw) > MAX_STATE_BYTES:
            raise GitLabRuntimeError("sealed GitLab state exceeds size bound")
        path = handle.artifact_root / "gitlab-sealed-state.json"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        record["sealed"] = True
        sealed = SealedState(path=path, sha256=_hash(raw), size_bytes=len(raw))
        record["sealed_state"] = sealed
        return sealed

    async def grade(self, sealed: SealedState, task: TaskPack) -> GradeResult:
        await self._local_docker()
        if self.verifier_image is None or not re.fullmatch(r"sha256:[0-9a-f]{64}", self.verifier_image):
            raise GitLabRuntimeError("a pinned built verifier image is required")
        if sealed.path.is_symlink() or sealed.path.stat().st_size > MAX_STATE_BYTES:
            raise GitLabRuntimeError("sealed GitLab artifact must be a bounded regular file")
        raw = sealed.path.read_bytes()
        if len(raw) != sealed.size_bytes or _hash(raw) != sealed.sha256 or len(raw) > MAX_STATE_BYTES:
            raise GitLabRuntimeError("sealed GitLab artifact integrity mismatch")
        record = next(
            (
                record
                for record in self._instances.values()
                if record.get("sealed_state") == sealed and record.get("task") == task
            ),
            None,
        )
        if record is None:
            raise GitLabRuntimeError("grading requires this runtime's owned sealed attempt")
        verifier_name = f"{record['handle'].instance_id}-verifier-{secrets.token_hex(6)}"
        record["containers"].append(verifier_name)
        result = await self._docker(
            "run",
            "--rm",
            "--interactive",
            "--pull",
            "never",
            "--name",
            verifier_name,
            "--label",
            f"{OWNER_LABEL}={record['owner']}",
            "--network",
            "none",
            "--read-only",
            "--user",
            "65534:65534",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--memory",
            "128m",
            "--memory-swap",
            "128m",
            "--cpus",
            "1",
            "--pids-limit",
            "32",
            "--log-driver",
            "none",
            "--label",
            "world-engine.gitlab-verifier=true",
            self.verifier_image,
            data=raw,
            timeout=30,
        )
        verdict = json.loads(result)
        return GradeResult(**verdict, grader_version=task.grader_version, sealed_state_sha256=sealed.sha256)

    async def close(self, handle: RuntimeHandle) -> CleanupResult:
        if self._closed.get(handle.instance_id) is handle:
            return CleanupResult(status="completed")
        record = self._owned(handle)
        try:
            resources = [
                *[("container", v) for v in record["containers"]],
                *[("volume", v) for v in record["volumes"]],
                *[("network", v) for v in record["networks"]],
            ]
            for kind, name in resources:
                try:
                    info = await self._inspect(kind, name)
                except GitLabRuntimeError:
                    # Confirm absence without assuming every inspection failure means removal.
                    ids = await self._docker(
                        kind,
                        "ls",
                        *(["--all"] if kind == "container" else []),
                        "--quiet",
                        "--filter",
                        f"name={name}",
                    )
                    if ids.strip():
                        raise
                    continue
                labels = (
                    info.get("Config", {}).get("Labels", {})
                    if kind == "container"
                    else info.get("Labels", {})
                )
                if labels.get(OWNER_LABEL) != record["owner"]:
                    raise GitLabRuntimeError("foreign GitLab resource ownership")
                await self._docker(kind, "rm", *(["--force"] if kind == "container" else []), name)
            for kind, name in resources:
                ids = await self._docker(
                    kind,
                    "ls",
                    *(["--all"] if kind == "container" else []),
                    "--quiet",
                    "--filter",
                    f"name={name}",
                )
                if ids.strip():
                    raise GitLabRuntimeError("owned GitLab resource removal was not certified")
            del self._instances[handle.instance_id]
            self._closed[handle.instance_id] = handle
            return CleanupResult(status="completed")
        except asyncio.TimeoutError:
            return CleanupResult(status="timeout", error_code="cleanup_timeout")
        except Exception:
            return CleanupResult(status="failed", error_code="cleanup_failed")
