"""Local Docker task execution, separate from providers and trusted grading."""

from __future__ import annotations

import asyncio
import copy
import io
import json
import math
import os
import re
import shutil
import tarfile
import time
import uuid
from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Mapping

IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
KEEPALIVE = "while :; do sleep 3600; done"
USER = "65534:65534"


class ExecutorError(RuntimeError):
    pass


class AdmissionError(ExecutorError):
    pass


def relative_path(value: str) -> str:
    if (not isinstance(value, str) or not value or len(value.encode()) > 1024
            or "\\" in value or "\x00" in value or value.startswith("/")):
        raise ValueError("task paths must be bounded relative POSIX paths")
    parts = value.split("/")
    if any(part in {"", ".", ".."} or len(part.encode()) > 255 for part in parts):
        raise ValueError("task paths cannot contain traversal or empty components")
    return value


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    version: str
    image_id: str
    public_inputs: Mapping[str, bytes]
    artifact_paths: tuple[str, ...]

    def __post_init__(self):
        if not isinstance(self.task_id, str) or not 1 <= len(self.task_id) <= 120:
            raise ValueError("task_id must be a bounded nonempty string")
        if not isinstance(self.version, str) or not 1 <= len(self.version) <= 80:
            raise ValueError("version must be a bounded nonempty string")
        if not isinstance(self.image_id, str) or not IMAGE_ID.fullmatch(self.image_id):
            raise ValueError("an exact sha256 Docker image ID is required")
        if not isinstance(self.public_inputs, Mapping) or not isinstance(self.artifact_paths, tuple):
            raise ValueError("public_inputs must be a mapping and artifact_paths a tuple")
        inputs = {relative_path(path): value for path, value in self.public_inputs.items()}
        if any(type(value) is not bytes for value in inputs.values()):
            raise ValueError("public input contents must be bytes")
        paths = tuple(relative_path(path) for path in self.artifact_paths)
        if not paths or len(paths) != len(set(paths)):
            raise ValueError("artifact paths must be nonempty and unique")
        for paths_to_check in (tuple(inputs), paths):
            if any(a != b and b.startswith(a + "/") for a in paths_to_check for b in paths_to_check):
                raise ValueError("task paths cannot overlap files and directories")
        object.__setattr__(self, "public_inputs", MappingProxyType(inputs))
        object.__setattr__(self, "artifact_paths", paths)


@dataclass(frozen=True)
class Limits:
    episode_seconds: float = 120
    command_seconds: float = 15
    max_commands: int = 16
    command_bytes: int = 8192
    output_bytes: int = 16384
    workspace_bytes: int = 32 * 1024 * 1024
    artifact_bytes: int = 256 * 1024
    artifact_files: int = 16
    artifact_members: int = 64
    artifact_depth: int = 8
    memory_bytes: int = 512 * 1024 * 1024
    cpus: float = 1
    pids: int = 64

    def __post_init__(self):
        for name in ("episode_seconds", "command_seconds", "cpus"):
            value = getattr(self, name)
            if type(value) not in {int, float} or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        for name in ("max_commands", "command_bytes", "output_bytes", "workspace_bytes", "artifact_bytes",
                     "artifact_files", "artifact_members", "artifact_depth", "memory_bytes", "pids"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if not (self.command_seconds <= self.episode_seconds <= 600 and self.cpus <= 8
                and self.max_commands <= 100 and self.command_bytes <= 65536 and self.output_bytes <= 1024 * 1024
                and self.artifact_bytes <= self.workspace_bytes <= 256 * 1024 * 1024
                and self.artifact_files <= self.artifact_members <= 1024 and self.artifact_depth <= 32
                and 64 * 1024 * 1024 <= self.memory_bytes <= 8 * 1024 ** 3 and 4 <= self.pids <= 256):
            raise ValueError("executor limits exceed the local SDK safety bounds")


@dataclass(frozen=True)
class CommandResult:
    exit_code: int | None
    stdout: str
    stderr: str
    elapsed_seconds: float
    limit_reason: str | None


@dataclass(frozen=True)
class ArtifactBundle:
    files: Mapping[str, bytes]
    hashes: Mapping[str, str]
    image_id: str
    runtime_receipt: dict


@dataclass
class _ProcessResult:
    code: int | None
    stdout: bytes = b""
    stderr: bytes = b""
    elapsed: float = 0
    limit: str | None = None


class _OutputLimit(Exception):
    pass


async def _process(args: list[str], *, timeout: float, output_limit: int,
                   stdin: bytes | None = None, env: dict[str, str]) -> _ProcessResult:
    start = time.monotonic()
    process = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
                                                   stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
    buffers = [bytearray(), bytearray()]
    total = 0

    async def read(stream, buffer):
        nonlocal total
        while chunk := await stream.read(16384):
            accepted = min(len(chunk), output_limit - total)
            buffer.extend(chunk[:accepted])
            total += accepted
            if accepted != len(chunk):
                raise _OutputLimit

    async def write():
        if stdin is not None:
            try:
                process.stdin.write(stdin)
                await process.stdin.drain()
                process.stdin.close()
                await process.stdin.wait_closed()
            except (BrokenPipeError, ConnectionResetError):
                pass

    tasks = [asyncio.create_task(read(process.stdout, buffers[0])), asyncio.create_task(read(process.stderr, buffers[1])),
             asyncio.create_task(write()), asyncio.create_task(process.wait())]
    reason = None
    try:
        await asyncio.wait_for(asyncio.gather(*tasks), timeout)
    except _OutputLimit:
        reason = "output_limit"
    except TimeoutError:
        reason = "timeout"
    finally:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await process.wait()
    return _ProcessResult(process.returncode, bytes(buffers[0]), bytes(buffers[1]), time.monotonic() - start, reason)


def _input_tar(inputs: Mapping[str, bytes]) -> bytes:
    data = io.BytesIO()
    directories = set()
    with tarfile.open(fileobj=data, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for path, content in sorted(inputs.items()):
            for parent in reversed(PurePosixPath(path).parents):
                if str(parent) != "." and str(parent) not in directories:
                    info = tarfile.TarInfo(str(parent))
                    info.type, info.mode, info.uid, info.gid = tarfile.DIRTYPE, 0o700, 65534, 65534
                    archive.addfile(info)
                    directories.add(str(parent))
            info = tarfile.TarInfo(path)
            info.size, info.mode, info.uid, info.gid = len(content), 0o600, 65534, 65534
            archive.addfile(info, io.BytesIO(content))
    return data.getvalue()


def _artifact_tar(raw: bytes, requested: str, limits: Limits, files: dict[str, bytes], counts: dict[str, int]) -> None:
    if len(raw) > limits.artifact_bytes + limits.artifact_members * 8192 + 10240:
        raise ValueError("artifact tar stream exceeded its byte ceiling")
    offset, headers = 0, 0
    while offset + 512 <= len(raw):
        block = raw[offset:offset + 512]
        if not any(block):
            if len(raw) - offset < 1024 or any(raw[offset:]):
                raise ValueError("artifact archive has incomplete or nonzero trailing data")
            break
        try:
            header = tarfile.TarInfo.frombuf(block, "utf-8", "strict")
        except (tarfile.TarError, UnicodeError) as error:
            raise ValueError("invalid artifact tar header") from error
        headers += 1
        offset += 512 + ((header.size + 511) // 512) * 512
        if headers > limits.artifact_members or header.size < 0 or offset > len(raw):
            raise ValueError("artifact archive exceeded header bounds or has truncated data")
    else:
        raise ValueError("artifact archive has no complete end marker")
    root = PurePosixPath(requested).name
    parent = PurePosixPath(requested).parent
    seen = set()
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r|") as archive:
            for member in archive:
                counts["members"] += 1
                raw_name = member.name.rstrip("/") if member.isdir() else member.name
                if requested == "." and raw_name == "." and member.isdir() and not member.size:
                    if "." in seen:
                        raise ValueError("artifact archive contains duplicate root directories")
                    seen.add(".")
                    continue
                name = relative_path(raw_name[2:] if requested == "." and raw_name.startswith("./") else raw_name)
                if requested != "." and name != root and not name.startswith(root + "/"):
                    raise ValueError("artifact archive escaped its requested path")
                path = relative_path(str(parent / name))
                if path in seen:
                    raise ValueError("artifact archive contains duplicate members")
                seen.add(path)
                if len(PurePosixPath(path).parts) > limits.artifact_depth or counts["members"] > limits.artifact_members:
                    raise ValueError("artifact archive exceeded path depth or member count")
                if member.isdir():
                    if member.size:
                        raise ValueError("artifact directory has unexpected content")
                    continue
                if (member.type not in {tarfile.REGTYPE, tarfile.AREGTYPE} or member.linkname or path in files
                        or member.sparse is not None or any(key.startswith("GNU.sparse") for key in member.pax_headers)):
                    raise ValueError("artifact archive contains links, special files or duplicate paths")
                if member.size < 0 or counts["bytes"] + member.size > limits.artifact_bytes or len(files) >= limits.artifact_files:
                    raise ValueError("artifact archive exceeded file or byte limits")
                stream = archive.extractfile(member)
                content = stream.read(member.size + 1)
                if len(content) != member.size:
                    raise ValueError("artifact archive contains a truncated file")
                files[path] = content
                counts["bytes"] += len(content)
            if any(raw[archive.offset:]):
                raise ValueError("artifact archive has trailing nonzero data")
            if not seen:
                raise ValueError("requested artifact was missing from its archive")
    except (tarfile.TarError, OSError, UnicodeError, KeyError, TypeError, IndexError, OverflowError) as error:
        raise ValueError("invalid artifact tar stream") from error


class DockerExecutor:
    """One local controller owns at most two fresh container sessions; admission never queues."""

    def __init__(self, *, allowed_images: set[str] | frozenset[str], limits: Limits | None = None, max_sessions: int = 2):
        if type(max_sessions) is not int or not 1 <= max_sessions <= 2:
            raise ValueError("max_sessions must be 1 or 2")
        if not allowed_images or any(not isinstance(image, str) or not IMAGE_ID.fullmatch(image) for image in allowed_images):
            raise ValueError("allowed_images must explicitly contain exact sha256 image IDs")
        self.allowed_images = frozenset(allowed_images)
        if limits is not None and not isinstance(limits, Limits):
            raise ValueError("limits must be a Limits instance")
        self.limits = limits or Limits()
        self.max_sessions = max_sessions
        self.owner = uuid.uuid4().hex
        self.binary = shutil.which("docker")
        if not self.binary:
            raise ExecutorError("Docker CLI is unavailable")
        self.env = {key: os.environ[key] for key in ("HOME", "PATH", "DOCKER_CONFIG") if key in os.environ}
        self.endpoint = None
        self.sessions: dict[str, DockerSession] = {}
        self.closed = False

    async def __aenter__(self):
        if self.closed or self.endpoint is not None:
            raise ExecutorError("executor cannot be entered twice or after closure")
        endpoint = os.environ.get("DOCKER_HOST")
        if endpoint is None:
            args = [self.binary, "context", "inspect", "--format", "{{json .Endpoints.docker.Host}}"]
            context = os.environ.get("DOCKER_CONTEXT")
            if context:
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", context):
                    raise ExecutorError("invalid Docker context name")
                args.append(context)
            result = await _process(args, timeout=10, output_limit=4096, env=self.env)
            if result.code or result.limit:
                raise ExecutorError("cannot inspect the local Docker context")
            try:
                endpoint = json.loads(result.stdout)
            except (ValueError, TypeError) as error:
                raise ExecutorError("invalid Docker context metadata") from error
        local_socket = isinstance(endpoint, str) and (endpoint.startswith("unix:///") or bool(re.fullmatch(r"npipe:////\./pipe/[A-Za-z0-9_.-]+", endpoint)))
        if not local_socket or len(endpoint.encode()) > 4096 or any(character in endpoint for character in ("\x00", "?", "#", "\n", "\r")):
            raise ExecutorError("only a local Unix socket or named pipe Docker daemon is supported; remote contexts are refused")
        self.endpoint = endpoint
        return self

    async def __aexit__(self, *_):
        await self.close()

    def session(self, task: TaskSpec) -> DockerSession:
        if self.closed or self.endpoint is None:
            raise ExecutorError("executor must be entered and open")
        if task.image_id not in self.allowed_images:
            raise ValueError("task image is not explicitly allowlisted")
        limits = self.limits
        if len(task.public_inputs) > limits.artifact_files or len(task.artifact_paths) > limits.artifact_files:
            raise ValueError("task input or output path count exceeds limits")
        if sum(len(content) for content in task.public_inputs.values()) > limits.artifact_bytes:
            raise ValueError("public inputs exceed the byte limit")
        if any(len(PurePosixPath(path).parts) > limits.artifact_depth for path in (*task.public_inputs, *task.artifact_paths)):
            raise ValueError("task paths exceed the depth limit")
        return DockerSession(self, task)

    async def command(self, args: list[str], *, timeout: float, output_limit: int = 131072, stdin: bytes | None = None) -> _ProcessResult:
        return await _process([self.binary, "--host", self.endpoint, *args], timeout=timeout,
                              output_limit=output_limit, stdin=stdin, env=self.env)

    async def close(self):
        self.closed = True
        results = await asyncio.gather(*(session.close() for session in list(self.sessions.values())), return_exceptions=True)
        if any(isinstance(result, BaseException) for result in results):
            raise ExecutorError("container cleanup failed; retry close and inspect owned containers")


class DockerSession:
    def __init__(self, executor: DockerExecutor, task: TaskSpec):
        self.executor, self.task, self.limits = executor, task, executor.limits
        self.name = f"we-sdk-{executor.owner[:12]}-{uuid.uuid4().hex[:12]}"
        self.volume = self.name + "-workspace"
        self.collector = self.name + "-collector"
        self.state = "new"
        self.started = 0.0
        self.commands = 0
        self.runtime = {}
        self._operation: asyncio.Task | None = None
        self._creation: asyncio.Task | None = None
        self._volume_creation: asyncio.Task | None = None
        self._collector_creation: asyncio.Task | None = None
        self._cleanup: asyncio.Task | None = None
        self._watchdog: asyncio.Task | None = None
        self.expired = False
        self.expiry_cleanup_failed = False

    async def _expire(self):
        try:
            await asyncio.sleep(self.limits.episode_seconds)
            self.expired = True
            await self.close()
        except asyncio.CancelledError:
            pass
        except ExecutorError:
            self.expiry_cleanup_failed = True

    def _timeout(self, ceiling: float) -> float:
        remaining = self.limits.episode_seconds - (time.monotonic() - self.started)
        if remaining <= 0:
            raise ExecutorError("episode wall-clock limit exceeded")
        return min(ceiling, remaining)

    def _tmpfs(self):
        return {"/tmp": "rw,noexec,nosuid,nodev,size=16777216,mode=1777"}

    def _volume_options(self):
        return {"type": "tmpfs", "device": "tmpfs",
                "o": f"size={self.limits.workspace_bytes},uid=65534,gid=65534,mode=0700,nosuid,nodev"}

    def _run_args(self, *, collector: bool = False):
        limits = self.limits
        mount = f"type=volume,src={self.volume},dst=/workspace,volume-nocopy" + (",readonly" if collector else "")
        return ["run", "--pull=never", "--detach", "--name", self.collector if collector else self.name,
                "--label", f"world-engine.executor-owner={self.executor.owner}", "--user", USER,
                "--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                "--pids-limit", str(limits.pids), "--memory", str(limits.memory_bytes), "--memory-swap", str(limits.memory_bytes),
                "--cpus", str(limits.cpus), "--ulimit", f"fsize={limits.artifact_bytes}:{limits.artifact_bytes}",
                "--ulimit", "core=0:0", "--log-driver=none", "--workdir", "/workspace",
                "--mount", mount,
                *[item for path, options in self._tmpfs().items() for item in ("--tmpfs", f"{path}:{options}")],
                "--entrypoint", "/bin/sh", self.task.image_id, "-c", KEEPALIVE]

    def _verify_runtime(self, data: dict, *, collector: bool = False):
        config, host = data["Config"], data["HostConfig"]
        checks = [data["Name"] == "/" + (self.collector if collector else self.name), data["Image"] == self.task.image_id, data["State"]["Running"] is True,
                  config["User"] == USER, config["WorkingDir"] == "/workspace",
                  config["Entrypoint"] == ["/bin/sh"], config["Cmd"] == ["-c", KEEPALIVE],
                  config["Labels"].get("world-engine.executor-owner") == self.executor.owner,
                  host["NetworkMode"] == "none", host["ReadonlyRootfs"] is True, host["Privileged"] is False,
                  set(host["CapDrop"] or []) == {"ALL"}, not host.get("CapAdd"),
                  set(host["SecurityOpt"] or []) == {"no-new-privileges"},
                  host["PidsLimit"] == self.limits.pids, host["Memory"] == self.limits.memory_bytes,
                  host["MemorySwap"] == self.limits.memory_bytes, host["NanoCpus"] == int(self.limits.cpus * 10 ** 9),
                  host["LogConfig"]["Type"] == "none", host["Tmpfs"] == self._tmpfs(),
                  not host.get("Binds"), not host.get("VolumesFrom"), not host.get("Devices"), not host.get("DeviceRequests"),
                  not host.get("PortBindings"), host.get("PidMode", "") == "", host.get("IpcMode") == "private",
                  host.get("UTSMode", "") == "", host.get("CgroupnsMode") == "private",
                  len(data["Mounts"]) == 1, len(host["Mounts"]) == 1]
        mount, configured_mount = data["Mounts"][0], host["Mounts"][0]
        checks += [mount["Type"] == "volume", mount["Name"] == self.volume, mount["Destination"] == "/workspace",
                   mount["Driver"] == "local", mount["RW"] is not collector,
                   configured_mount["Type"] == "volume", configured_mount["Source"] == self.volume,
                   configured_mount["Target"] == "/workspace", configured_mount.get("ReadOnly", False) is collector,
                   configured_mount["VolumeOptions"]["NoCopy"] is True]
        ulimits = {entry["Name"]: (entry["Soft"], entry["Hard"]) for entry in host["Ulimits"]}
        checks += [ulimits.get("fsize") == (self.limits.artifact_bytes, self.limits.artifact_bytes), ulimits.get("core") == (0, 0)]
        if not all(checks):
            raise ExecutorError("actual Docker runtime violates the required isolation policy")
        return {"image_id": data["Image"], "user": config["User"], "network": host["NetworkMode"], "paused": data["State"].get("Paused", False),
                        "read_only_rootfs": host["ReadonlyRootfs"], "cap_drop": host["CapDrop"],
                        "security_opt": host["SecurityOpt"], "pids_limit": host["PidsLimit"], "memory_bytes": host["Memory"],
                        "nano_cpus": host["NanoCpus"], "tmpfs": copy.deepcopy(host["Tmpfs"]), "ulimits": copy.deepcopy(host["Ulimits"]),
                        "log_driver": host["LogConfig"]["Type"], "mounts": [{"type": "volume", "destination": "/workspace", "read_only": collector}], "entrypoint": config["Entrypoint"],
                        "command": config["Cmd"]}

    def _verify_volume(self, data: dict):
        if (data["Name"] != self.volume or data["Driver"] != "local" or data["Options"] != self._volume_options()
                or data["Labels"].get("world-engine.executor-owner") != self.executor.owner):
            raise ExecutorError("actual workspace volume violates the required tmpfs policy")

    async def _inspect_container(self, name: str, *, collector: bool = False):
        result = await self.executor.command(["inspect", name], timeout=self._timeout(10))
        if result.code or result.limit:
            raise ExecutorError("cannot verify the started container")
        try:
            return self._verify_runtime(json.loads(result.stdout)[0], collector=collector)
        except (KeyError, TypeError, ValueError, IndexError) as error:
            raise ExecutorError("invalid container inspection metadata or isolation policy") from error

    async def __aenter__(self):
        if self.state != "new" or self.executor.closed:
            raise ExecutorError("session cannot be entered twice or after executor closure")
        if len(self.executor.sessions) >= self.executor.max_sessions:
            raise AdmissionError("local Docker session admission limit reached")
        self.executor.sessions[self.name] = self
        self.state, self.started, self._operation = "starting", time.monotonic(), asyncio.current_task()
        self._watchdog = asyncio.create_task(self._expire())
        try:
            image = await self.executor.command(["image", "inspect", self.task.image_id, "--format", "{{.Id}}"], timeout=self._timeout(10), output_limit=1024)
            if image.code or image.limit or image.stdout.decode().strip() != self.task.image_id:
                raise ExecutorError("allowlisted image is not already available locally")
            existing = await self.executor.command(["volume", "inspect", self.volume], timeout=self._timeout(10))
            if existing.code == 0 or existing.limit or b"no such volume" not in existing.stderr.lower():
                raise ExecutorError("workspace volume name is not verified fresh")
            volume_args = ["volume", "create", "--driver", "local", "--label", f"world-engine.executor-owner={self.executor.owner}"]
            volume_args += [item for key, value in self._volume_options().items() for item in ("--opt", f"{key}={value}")]
            self._volume_creation = asyncio.create_task(self.executor.command(volume_args + [self.volume], timeout=self._timeout(15), output_limit=4096))
            volume_result = await asyncio.shield(self._volume_creation)
            if volume_result.code or volume_result.limit or volume_result.stdout.decode().strip() != self.volume:
                raise ExecutorError("workspace volume creation failed")
            volume_inspection = await self.executor.command(["volume", "inspect", self.volume], timeout=self._timeout(10))
            if volume_inspection.code or volume_inspection.limit:
                raise ExecutorError("cannot verify the workspace volume")
            try:
                self._verify_volume(json.loads(volume_inspection.stdout)[0])
            except (KeyError, TypeError, ValueError, IndexError) as error:
                raise ExecutorError("invalid workspace volume metadata") from error
            self._creation = asyncio.create_task(self.executor.command(self._run_args(), timeout=self._timeout(15), output_limit=4096))
            result = await asyncio.shield(self._creation)
            if result.code or result.limit:
                raise ExecutorError("container start failed or exceeded its limit")
            self.runtime = await self._inspect_container(self.name)
            if self.task.public_inputs:
                copied = await self.executor.command(["exec", "-i", self.name, "/bin/tar", "-xf", "-", "-C", "/workspace"],
                                                     timeout=self._timeout(15), output_limit=4096, stdin=_input_tar(self.task.public_inputs))
                if copied.code or copied.limit:
                    raise ExecutorError("public input initialization failed")
            self.state = "running"
            return self
        except BaseException:
            await self.close()
            if self.expired:
                raise ExecutorError("episode wall-clock limit exceeded") from None
            raise
        finally:
            self._operation = None

    async def __aexit__(self, *_):
        await self.close()

    def _begin_operation(self):
        if self.state != "running" or self._operation is not None:
            raise ExecutorError("session is not running or another operation is active")
        self._operation = asyncio.current_task()

    async def execute(self, command: str) -> CommandResult:
        if not isinstance(command, str) or not command or "\x00" in command or len(command.encode()) > self.limits.command_bytes:
            raise ValueError("command must be a bounded nonempty string without NUL bytes")
        self._begin_operation()
        try:
            if self.commands >= self.limits.max_commands:
                raise ExecutorError("command count limit exceeded")
            self.commands += 1
            remaining = self._timeout(self.limits.command_seconds)
            result = await self.executor.command(["exec", self.name, "/bin/sh", "-c", command],
                                                 timeout=remaining, output_limit=self.limits.output_bytes)
            if result.limit:
                await self.close()
            return CommandResult(result.code, result.stdout.decode(errors="replace"), result.stderr.decode(errors="replace"), result.elapsed, result.limit)
        except BaseException:
            await self.close()
            if self.expired:
                raise ExecutorError("episode wall-clock limit exceeded") from None
            raise
        finally:
            self._operation = None

    async def finish(self) -> ArtifactBundle:
        self._begin_operation()
        try:
            result = await self.executor.command(["pause", self.name], timeout=self._timeout(10), output_limit=4096)
            if result.code or result.limit:
                raise ExecutorError("cannot freeze the task container")
            self.runtime = await self._inspect_container(self.name)
            if self.runtime["paused"] is not True:
                raise ExecutorError("actual task container is not paused")
            self.state = "frozen"
            self._collector_creation = asyncio.create_task(self.executor.command(self._run_args(collector=True), timeout=self._timeout(15), output_limit=4096))
            started = await asyncio.shield(self._collector_creation)
            if started.code or started.limit:
                raise ExecutorError("read-only collector start failed")
            collector_receipt = await self._inspect_container(self.collector, collector=True)
            files, counts = {}, {"members": 0, "bytes": 0}
            archive_bound = self.limits.artifact_bytes + self.limits.artifact_members * 8192 + 10240
            result = await self.executor.command(["exec", self.collector, "/bin/tar", "-C", "/workspace", "-cf", "-", "."],
                                                 timeout=self._timeout(15), output_limit=archive_bound)
            if result.code or result.limit:
                raise ExecutorError("artifact collection failed or exceeded its stream limit")
            _artifact_tar(result.stdout, ".", self.limits, files, counts)
            selected = {path: content for path, content in files.items()
                        if any(path == allowed or path.startswith(allowed + "/") for allowed in self.task.artifact_paths)}
            if any(not any(path == allowed or path.startswith(allowed + "/") for path in selected) for allowed in self.task.artifact_paths):
                raise ValueError("requested artifact is missing or empty")
            await self.close()
            receipt = copy.deepcopy(self.runtime) | {"collector": collector_receipt, "storage": self._volume_options(),
                                                   "containers_removed": True, "volume_removed": True,
                                                   "workspace_files": len(files), "workspace_bytes": counts["bytes"]}
            return ArtifactBundle(MappingProxyType(selected), MappingProxyType({path: sha256(content).hexdigest() for path, content in selected.items()}),
                                  self.task.image_id, receipt)
        except BaseException:
            await self.close()
            if self.expired:
                raise ExecutorError("episode wall-clock limit exceeded") from None
            raise
        finally:
            self._operation = None

    async def _remove(self):
        pending = [item for item in (self._volume_creation, self._creation, self._collector_creation) if item is not None]
        await asyncio.gather(*pending, return_exceptions=True)
        for name in (self.collector, self.name):
            inspected = await self.executor.command(["inspect", name], timeout=10)
            if inspected.limit:
                raise ExecutorError("container ownership inspection failed; retry close")
            if inspected.code:
                if b"no such" in inspected.stderr.lower():
                    continue
                raise ExecutorError("container ownership inspection failed; retry close")
            try:
                owner = json.loads(inspected.stdout)[0]["Config"]["Labels"].get("world-engine.executor-owner")
            except (KeyError, ValueError, TypeError, IndexError) as error:
                raise ExecutorError("invalid container ownership metadata") from error
            if owner != self.executor.owner:
                raise ExecutorError("foreign container ownership; refusing removal")
            result = await self.executor.command(["rm", "--force", "--volumes", name], timeout=15, output_limit=4096)
            if result.limit or (result.code and b"no such container" not in result.stderr.lower()):
                raise ExecutorError("container removal failed; retry close")
        if self._volume_creation is not None:
            inspected = await self.executor.command(["volume", "inspect", self.volume], timeout=10)
            if inspected.limit or (inspected.code and b"no such volume" not in inspected.stderr.lower()):
                raise ExecutorError("volume ownership inspection failed; retry close")
            if not inspected.code:
                try:
                    owner = json.loads(inspected.stdout)[0]["Labels"].get("world-engine.executor-owner")
                except (KeyError, ValueError, TypeError, IndexError) as error:
                    raise ExecutorError("invalid volume ownership metadata") from error
                if owner != self.executor.owner:
                    raise ExecutorError("foreign volume ownership; refusing removal")
                result = await self.executor.command(["volume", "rm", self.volume], timeout=15, output_limit=4096)
                if result.code or result.limit:
                    raise ExecutorError("workspace volume removal failed; retry close")
        self.state = "closed"
        self.executor.sessions.pop(self.name, None)

    async def close(self):
        if self.state == "closed":
            return
        if self.state == "new":
            self.state = "closed"
            return
        if self._operation is not None and self._operation is not asyncio.current_task():
            self._operation.cancel()
        watchdog = self._watchdog
        if watchdog is not None and watchdog is not asyncio.current_task() and not watchdog.done():
            watchdog.cancel()
        if self._cleanup is None or (self._cleanup.done() and self._cleanup.exception() is not None):
            self.state = "closing"
            self._cleanup = asyncio.create_task(self._remove())
        cancelled = False
        while not self._cleanup.done():
            try:
                await asyncio.shield(self._cleanup)
            except asyncio.CancelledError:
                cancelled = True
        self._cleanup.result()
        if watchdog is not None and watchdog is not asyncio.current_task():
            await asyncio.gather(watchdog, return_exceptions=True)
        if cancelled:
            raise asyncio.CancelledError
