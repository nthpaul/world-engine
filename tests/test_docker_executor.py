import asyncio
import io
import json
import os
import runpy
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from world_engine import docker_executor as sdk

IMAGE = "sha256:" + "a" * 64


def collector():
    return runpy.run_path(str(Path(__file__).resolve().parents[1] / "examples/docker_executor.py"))["collect"]


@pytest.mark.parametrize("symlink", [False, True])
async def test_collector_existing_output_rejected_before_source_or_docker(tmp_path, monkeypatch, symlink):
    output = tmp_path / "receipt.json"
    if symlink:
        output.symlink_to(tmp_path / "missing")
    else:
        output.write_text("existing receipt")
    collect = collector()

    def forbidden(*args, **kwargs):
        raise AssertionError("preflight must not invoke source inspection or Docker")

    monkeypatch.setitem(collect.__globals__, "source_receipt", forbidden)
    monkeypatch.setitem(collect.__globals__, "trial", forbidden)
    with pytest.raises(FileExistsError, match="refusing to run"):
        await collect(SimpleNamespace(output=output))


@pytest.mark.parametrize("dirty,revision", [(True, "revision"), (None, "revision"), (False, None)])
async def test_benchmark_requires_clean_committed_source_before_docker(monkeypatch, dirty, revision):
    collect = collector()
    monkeypatch.setitem(collect.__globals__, "source_receipt", lambda: {"source_dirty": dirty, "git_revision": revision})

    def forbidden(*args, **kwargs):
        raise AssertionError("dirty-source benchmark must not invoke Docker")

    monkeypatch.setitem(collect.__globals__, "trial", forbidden)
    with pytest.raises(RuntimeError, match="committed, clean"):
        await collect(SimpleNamespace(output=None, benchmark=True))


def archive_bytes(members):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for info, content in members:
            archive.addfile(info, io.BytesIO(content) if content is not None else None)
    return stream.getvalue()


def regular(name="answer.txt", content=b"7\n"):
    info = tarfile.TarInfo(name)
    info.size = len(content)
    return info, content


def task(**changes):
    values = dict(task_id="synthetic-count", version="1", image_id=IMAGE,
                  public_inputs={"input.txt": b"1\n2\n4\n"}, artifact_paths=("answer.txt",))
    return sdk.TaskSpec(**(values | changes))


class FakeDocker:
    def __init__(self):
        self.calls = []
        self.containers = set()
        self.volumes = set()
        self.paused = set()
        self.executor = None
        self.inspection_mutation = None
        self.archive = archive_bytes([regular()])
        self.exec_result = sdk._ProcessResult(0, b"ok\n")
        self.exec_entered = asyncio.Event()
        self.exec_block = False
        self.start_gate = None
        self.start_entered = asyncio.Event()
        self.fail_removal = False
        self.pause_entered = asyncio.Event()
        self.pause_gate = None
        self.volume_mutation = None

    def inspection(self, name):
        collector = name.endswith("-collector")
        session = self.executor.sessions[name.removesuffix("-collector")]
        limits = session.limits
        value = {"Name": "/" + name, "Image": IMAGE, "State": {"Running": True, "Paused": name in self.paused},
                 "Config": {"User": sdk.USER, "WorkingDir": "/workspace", "Entrypoint": ["/bin/sh"],
                            "Cmd": ["-c", sdk.KEEPALIVE], "Labels": {"world-engine.executor-owner": self.executor.owner},
                            "Env": ["BAKED_PRIVATE_VALUE=never-copy-into-receipt"]},
                 "HostConfig": {"NetworkMode": "none", "ReadonlyRootfs": True, "Privileged": False,
                                "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges"], "PidsLimit": limits.pids,
                                "Memory": limits.memory_bytes, "MemorySwap": limits.memory_bytes,
                                "NanoCpus": int(limits.cpus * 10 ** 9), "LogConfig": {"Type": "none"},
                                "Tmpfs": session._tmpfs(), "IpcMode": "private", "CgroupnsMode": "private",
                                "Mounts": [{"Type": "volume", "Source": session.volume, "Target": "/workspace",
                                            "ReadOnly": collector, "VolumeOptions": {"NoCopy": True}}],
                                "Ulimits": [{"Name": "fsize", "Soft": limits.artifact_bytes, "Hard": limits.artifact_bytes},
                                            {"Name": "core", "Soft": 0, "Hard": 0}]},
                 "Mounts": [{"Type": "volume", "Name": session.volume, "Destination": "/workspace",
                             "Driver": "local", "RW": not collector}]}
        if self.inspection_mutation:
            path, changed = self.inspection_mutation
            cursor = value
            for key in path[:-1]:
                cursor = cursor[key]
            cursor[path[-1]] = changed
        return value

    async def process(self, args, *, timeout, output_limit, stdin=None, env):
        self.calls.append((args, stdin, env))
        command = args[1:] if args[1] == "context" else args[3:]
        if command[:2] == ["context", "inspect"]:
            return sdk._ProcessResult(0, b'"unix:///local/docker.sock"')
        if command[:2] == ["image", "inspect"]:
            return sdk._ProcessResult(0, IMAGE.encode())
        if command[:2] == ["volume", "create"]:
            self.volumes.add(command[-1])
            return sdk._ProcessResult(0, command[-1].encode())
        if command[:2] == ["volume", "inspect"]:
            if command[-1] not in self.volumes:
                return sdk._ProcessResult(1, stderr=b"no such volume")
            session = self.executor.sessions[command[-1].removesuffix("-workspace")]
            metadata = {"Name": session.volume, "Driver": "local", "Options": session._volume_options(),
                        "Labels": {"world-engine.executor-owner": self.executor.owner}}
            if self.volume_mutation:
                key, value = self.volume_mutation
                metadata[key] = value
            return sdk._ProcessResult(0, json.dumps([metadata]).encode())
        if command[:2] == ["volume", "rm"]:
            self.volumes.discard(command[-1])
            return sdk._ProcessResult(0)
        if command[0] == "run":
            self.start_entered.set()
            if self.start_gate:
                await self.start_gate.wait()
            self.containers.add(command[command.index("--name") + 1])
            return sdk._ProcessResult(0, b"container-id")
        if command[0] == "inspect":
            if command[1] not in self.containers:
                return sdk._ProcessResult(1, stderr=b"No such container")
            return sdk._ProcessResult(0, json.dumps([self.inspection(command[1])]).encode())
        if command[0] == "exec":
            if command[1] == "-i":
                return sdk._ProcessResult(0)
            if command[1].endswith("-collector"):
                return sdk._ProcessResult(0, self.archive)
            self.exec_entered.set()
            if self.exec_block:
                await asyncio.Event().wait()
            return self.exec_result
        if command[0] == "cp":
            return sdk._ProcessResult(0, self.archive if stdin is None else b"")
        if command[0] == "pause":
            self.pause_entered.set()
            if self.pause_gate:
                await self.pause_gate.wait()
            self.paused.add(command[1])
            return sdk._ProcessResult(0)
        if command[0] == "rm":
            if self.fail_removal:
                return sdk._ProcessResult(1, stderr=b"daemon unavailable")
            self.containers.discard(command[-1])
            return sdk._ProcessResult(0)
        raise AssertionError(command)


@pytest.fixture
def fake(monkeypatch):
    for key in ("DOCKER_HOST", "DOCKER_CONTEXT"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "private-host-key")
    monkeypatch.setattr(sdk.shutil, "which", lambda _: "/fake/docker")
    value = FakeDocker()
    monkeypatch.setattr(sdk, "_process", value.process)
    return value


async def executor_for(fake, **kwargs):
    executor = sdk.DockerExecutor(allowed_images={IMAGE}, **kwargs)
    fake.executor = executor
    await executor.__aenter__()
    return executor


async def test_lifecycle_freezes_destroys_and_returns_detached_artifacts(fake):
    executor = await executor_for(fake)
    original_inputs = {"input.txt": b"original"}
    specification = task(public_inputs=original_inputs)
    original_inputs["input.txt"] = b"mutated by caller"
    assert specification.public_inputs["input.txt"] == b"original"
    async with executor.session(specification) as session:
        result = await session.execute("printf 7 > answer.txt")
        assert result.exit_code == 0 and result.limit_reason is None
        bundle = await session.finish()
        assert session.state == "closed" and not fake.containers
        assert bundle.files == {"answer.txt": b"7\n"}
        assert bundle.hashes["answer.txt"] == sdk.sha256(b"7\n").hexdigest()
        assert "never-copy" not in json.dumps(bundle.runtime_receipt)
        with pytest.raises(TypeError):
            bundle.files["answer.txt"] = b"changed"
        with pytest.raises(sdk.ExecutorError, match="not running"):
            await session.execute("another command")
    await executor.close()
    assert not executor.sessions
    commands = [args[3:][0] for args, _, _ in fake.calls if args[1] == "--host"]
    assert commands.index("pause") < commands.index("rm")
    run = next(args for args, _, _ in fake.calls if "run" in args)
    assert "--pull=never" in run and "--network=none" in run and "--read-only" in run
    assert "--entrypoint" in run and "--mount" in run and "--volume" not in run
    assert "type=volume" in run[run.index("--mount") + 1]
    assert not fake.volumes
    assert all("OPENAI_API_KEY" not in env and "DOCKER_HOST" not in env for _, _, env in fake.calls)


async def test_admission_is_fail_fast_and_reset_uses_fresh_containers(fake):
    executor = await executor_for(fake)
    first, second, excess = (executor.session(task()) for _ in range(3))
    await first.__aenter__()
    await second.__aenter__()
    with pytest.raises(sdk.AdmissionError):
        await excess.__aenter__()
    assert len(fake.containers) == 2 and len(executor.sessions) == 2
    await first.close()
    await first.close()
    async with executor.session(task()) as replacement:
        assert replacement.name not in {first.name, second.name}
    await executor.close()
    assert not fake.containers and not executor.sessions


@pytest.mark.parametrize("path,value", [
    (("Image",), "sha256:" + "b" * 64), (("Name",), "/foreign-container"),
    (("Config", "User"), "0"), (("Config", "Entrypoint"), ["malicious"]),
    (("Config", "Cmd"), ["foreign-command"]), (("Config", "WorkingDir"), "/host"),
    (("HostConfig", "NetworkMode"), "host"), (("HostConfig", "ReadonlyRootfs"), False),
    (("HostConfig", "Privileged"), True), (("HostConfig", "CapDrop"), []),
    (("HostConfig", "SecurityOpt"), ["no-new-privileges", "seccomp=unconfined"]),
    (("HostConfig", "PidsLimit"), -1), (("HostConfig", "Memory"), 0),
    (("HostConfig", "MemorySwap"), -1), (("HostConfig", "NanoCpus"), 0),
    (("HostConfig", "LogConfig", "Type"), "json-file"), (("HostConfig", "Tmpfs"), {}),
    (("HostConfig", "Binds"), ["/private:/host"]), (("HostConfig", "DeviceRequests"), [{}]),
    (("HostConfig", "PidMode"), "host"), (("HostConfig", "IpcMode"), "host"),
    (("HostConfig", "CgroupnsMode"), "host"), (("Mounts",), [{"Type": "volume"}]),
    (("HostConfig", "Ulimits"), []),
])
async def test_actual_runtime_policy_mismatch_fails_closed_and_cleans_up(fake, path, value):
    executor = await executor_for(fake)
    fake.inspection_mutation = path, value
    with pytest.raises(sdk.ExecutorError, match="isolation policy"):
        async with executor.session(task()):
            pytest.fail("mismatched policy must not enter a running session")
    assert not fake.containers and not executor.sessions
    assert not any("exec" in args or "cp" in args for args, _, _ in fake.calls)
    await executor.close()


@pytest.mark.parametrize("endpoint", ["tcp://127.0.0.1:2375", "ssh://user@remote", "npipe:////remote/pipe/docker_engine", "https://remote", "unix:///local?secret=x"])
async def test_remote_daemon_is_rejected_before_container_operations(fake, monkeypatch, endpoint):
    monkeypatch.setenv("DOCKER_HOST", endpoint)
    executor = sdk.DockerExecutor(allowed_images={IMAGE})
    with pytest.raises(sdk.ExecutorError, match="remote contexts"):
        await executor.__aenter__()
    assert fake.calls == []


async def test_remote_context_metadata_is_rejected(fake, monkeypatch):
    async def remote(*args, **kwargs):
        return sdk._ProcessResult(0, b'"ssh://remote"')
    monkeypatch.setattr(sdk, "_process", remote)
    with pytest.raises(sdk.ExecutorError, match="remote contexts"):
        async with sdk.DockerExecutor(allowed_images={IMAGE}):
            pytest.fail("remote context accepted")


@pytest.mark.parametrize("key,value", [("Driver", "foreign-driver"), ("Options", {"type": "ext4", "device": "/host"})])
async def test_actual_volume_policy_mismatch_fails_closed(fake, key, value):
    executor = await executor_for(fake)
    fake.volume_mutation = key, value
    with pytest.raises(sdk.ExecutorError, match="tmpfs policy"):
        async with executor.session(task()):
            pytest.fail("invalid workspace policy accepted")
    assert not fake.containers and not fake.volumes and not executor.sessions
    await executor.close()


@pytest.mark.parametrize("reason", ["timeout", "output_limit"])
async def test_command_limits_destroy_the_whole_container(fake, reason):
    executor = await executor_for(fake)
    fake.exec_result = sdk._ProcessResult(-9, b"bounded", limit=reason)
    async with executor.session(task()) as session:
        result = await session.execute("untrusted command")
        assert result.limit_reason == reason
        assert session.state == "closed" and not fake.containers
        with pytest.raises(sdk.ExecutorError):
            await session.finish()
    await executor.close()


async def test_command_cancel_destroys_container_and_releases_admission(fake):
    executor = await executor_for(fake)
    async with executor.session(task()) as session:
        fake.exec_block = True
        operation = asyncio.create_task(session.execute("sleep forever"))
        await fake.exec_entered.wait()
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation
        assert session.state == "closed" and not fake.containers and not executor.sessions
    await executor.close()


async def test_cancel_during_start_waits_for_creation_before_removal(fake):
    executor = await executor_for(fake)
    fake.start_gate = asyncio.Event()
    session = executor.session(task())
    entering = asyncio.create_task(session.__aenter__())
    await fake.start_entered.wait()
    entering.cancel()
    await asyncio.sleep(0)
    assert not entering.done()
    fake.start_gate.set()
    with pytest.raises(asyncio.CancelledError):
        await entering
    assert not fake.containers and not executor.sessions
    await executor.close()


async def test_failed_cleanup_retains_admission_and_can_be_retried(fake):
    executor = await executor_for(fake)
    session = await executor.session(task()).__aenter__()
    fake.fail_removal = True
    with pytest.raises(sdk.ExecutorError, match="removal"):
        await session.close()
    assert session.name in executor.sessions and session.name in fake.containers
    fake.fail_removal = False
    await session.close()
    await session.close()
    assert not fake.containers and not executor.sessions
    await executor.close()


async def test_exhausted_command_budget_and_wall_clock_close_session(fake):
    executor = await executor_for(fake, limits=sdk.Limits(max_commands=1))
    async with executor.session(task()) as session:
        await session.execute("first")
        with pytest.raises(sdk.ExecutorError, match="command count"):
            await session.execute("second")
        assert session.state == "closed"
    async with executor.session(task()) as session:
        session.started -= 200
        with pytest.raises(sdk.ExecutorError, match="wall-clock"):
            await session.execute("too late")
        assert session.state == "closed"
    await executor.close()


@pytest.mark.parametrize("active_command", [False, True])
async def test_owned_watchdog_expires_idle_and_running_sessions(fake, active_command):
    executor = await executor_for(fake, limits=sdk.Limits(episode_seconds=.04, command_seconds=.03))
    session = await executor.session(task()).__aenter__()
    if active_command:
        fake.exec_block = True
        with pytest.raises(sdk.ExecutorError, match="wall-clock"):
            await session.execute("sleep forever")
    else:
        await asyncio.sleep(.08)
    assert session.expired and session.state == "closed"
    assert not fake.containers and not executor.sessions
    assert session._watchdog.done()
    with pytest.raises(sdk.ExecutorError):
        await session.execute("after expiry")
    await executor.close()


@pytest.mark.parametrize("phase", ["starting", "execute", "finish"])
async def test_external_executor_close_races_active_session_operations(fake, phase):
    executor = await executor_for(fake)
    session = executor.session(task())
    if phase == "starting":
        fake.start_gate = asyncio.Event()
        operation = asyncio.create_task(session.__aenter__())
        await fake.start_entered.wait()
    else:
        await session.__aenter__()
        if phase == "execute":
            fake.exec_block = True
            operation = asyncio.create_task(session.execute("sleep forever"))
            await fake.exec_entered.wait()
        else:
            fake.pause_gate = asyncio.Event()
            operation = asyncio.create_task(session.finish())
            await fake.pause_entered.wait()
    closing = asyncio.create_task(executor.close())
    await asyncio.sleep(0)
    if phase == "starting":
        fake.start_gate.set()
    with pytest.raises(asyncio.CancelledError):
        await operation
    await closing
    assert session.state == "closed" and not fake.containers and not executor.sessions


@pytest.mark.parametrize("name", ["../answer.txt", "/answer.txt", "answer.txt/../x", "answer.txt\\evil", "unrequested.txt"])
def test_tar_rejects_unsafe_or_unrequested_names(name):
    with pytest.raises(ValueError):
        sdk._artifact_tar(archive_bytes([regular(name)]), "answer.txt", sdk.Limits(), {}, {"bytes": 0, "members": 0})


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE])
def test_tar_rejects_links_and_special_files(kind):
    info = tarfile.TarInfo("answer.txt")
    info.type, info.linkname = kind, "../../private"
    with pytest.raises(ValueError, match="links, special"):
        sdk._artifact_tar(archive_bytes([(info, None)]), "answer.txt", sdk.Limits(), {}, {"bytes": 0, "members": 0})


def test_full_workspace_tar_rejects_unselected_links_and_sparse_metadata():
    info = tarfile.TarInfo("unselected")
    info.type, info.linkname = tarfile.SYMTYPE, "/etc"
    with pytest.raises(ValueError, match="links, special"):
        sdk._artifact_tar(archive_bytes([regular("answer.txt"), (info, None)]), ".", sdk.Limits(), {}, {"bytes": 0, "members": 0})
    info, content = regular()
    info.pax_headers = {"GNU.sparse.name": "answer.txt"}
    with pytest.raises(ValueError):
        sdk._artifact_tar(archive_bytes([(info, content)]), ".", sdk.Limits(), {}, {"bytes": 0, "members": 0})


def test_tar_rejects_duplicate_truncated_oversized_and_trailing_payloads():
    raw = archive_bytes([regular()])
    cases = [archive_bytes([regular(), regular()]), raw[:513], raw + raw,
             archive_bytes([regular(content=b"x" * 100)])]
    for index, data in enumerate(cases):
        with pytest.raises(ValueError):
            sdk._artifact_tar(data, "answer.txt", sdk.Limits(artifact_bytes=50) if index == 3 else sdk.Limits(), {}, {"bytes": 0, "members": 0})


def test_tar_enforces_aggregate_bytes_members_files_depth_and_pax_paths():
    one = archive_bytes([regular("reports/a", b"12"), regular("reports/b", b"34")])
    for limits in (sdk.Limits(artifact_bytes=3), sdk.Limits(artifact_files=1), sdk.Limits(artifact_members=1, artifact_files=1), sdk.Limits(artifact_depth=1)):
        with pytest.raises(ValueError):
            sdk._artifact_tar(one, "reports", limits, {}, {"bytes": 0, "members": 0})
    info, content = regular()
    info.pax_headers = {"path": "../outside"}
    with pytest.raises(ValueError):
        sdk._artifact_tar(archive_bytes([(info, content)]), "answer.txt", sdk.Limits(), {}, {"bytes": 0, "members": 0})
    files, counts = {}, {"bytes": 0, "members": 0}
    sdk._artifact_tar(archive_bytes([regular("a", b"12")]), "a", sdk.Limits(artifact_bytes=3), files, counts)
    with pytest.raises(ValueError, match="byte limits"):
        sdk._artifact_tar(archive_bytes([regular("b", b"34")]), "b", sdk.Limits(artifact_bytes=3), files, counts)


async def test_bad_artifact_stream_destroys_container(fake):
    executor = await executor_for(fake)
    fake.archive = archive_bytes([regular("../escape")])
    async with executor.session(task()) as session:
        with pytest.raises(ValueError):
            await session.finish()
        assert not fake.containers and not executor.sessions
    await executor.close()


@pytest.mark.parametrize("change", [{"image_id": "python:latest"}, {"artifact_paths": ("../secret",)},
                                    {"artifact_paths": ("reports", "reports/a")}, {"public_inputs": {"x": "not bytes"}}])
def test_task_boundary_rejects_unsafe_configuration(change):
    with pytest.raises(ValueError):
        task(**change)


@pytest.mark.parametrize("change", [{"max_commands": True}, {"episode_seconds": float("inf")}, {"cpus": 0},
                                    {"artifact_bytes": 1024 ** 3}, {"pids": 1000}])
def test_limits_boundary_rejects_unsafe_configuration(change):
    with pytest.raises(ValueError):
        sdk.Limits(**change)


async def test_only_explicitly_allowlisted_images_are_accepted(fake):
    executor = await executor_for(fake)
    with pytest.raises(ValueError, match="allowlisted"):
        executor.session(task(image_id="sha256:" + "b" * 64))
    with pytest.raises(ValueError):
        sdk.DockerExecutor(allowed_images={IMAGE}, max_sessions=3)
    await executor.close()


async def test_executor_context_cannot_be_reentered_or_retargeted(fake):
    executor = await executor_for(fake)
    with pytest.raises(sdk.ExecutorError, match="entered twice"):
        await executor.__aenter__()
    await executor.close()
    with pytest.raises(sdk.ExecutorError, match="after closure"):
        await executor.__aenter__()


async def test_existing_workspace_volume_is_never_reused_or_removed(fake):
    executor = await executor_for(fake)
    session = executor.session(task())
    fake.volumes.add(session.volume)
    with pytest.raises(sdk.ExecutorError, match="verified fresh"):
        await session.__aenter__()
    assert session.volume in fake.volumes
    assert not any(args[3:5] == ["volume", "rm"] for args, _, _ in fake.calls)
    await executor.close()


async def test_cleanup_refuses_foreign_container_ownership(fake):
    executor = await executor_for(fake)
    session = await executor.session(task()).__aenter__()
    fake.inspection_mutation = ("Config", "Labels"), {"world-engine.executor-owner": "foreign"}
    with pytest.raises(sdk.ExecutorError, match="foreign container"):
        await session.close()
    assert session.name in fake.containers and session.name in executor.sessions
    assert not any("rm" in args for args, _, _ in fake.calls)
    fake.inspection_mutation = None
    await session.close()
    assert not fake.containers and not fake.volumes
    await executor.close()


async def test_cleanup_refuses_foreign_volume_ownership(fake):
    executor = await executor_for(fake)
    session = await executor.session(task()).__aenter__()
    fake.volume_mutation = "Labels", {"world-engine.executor-owner": "foreign"}
    with pytest.raises(sdk.ExecutorError, match="foreign volume"):
        await session.close()
    assert not fake.containers and session.volume in fake.volumes and session.name in executor.sessions
    fake.volume_mutation = None
    await session.close()
    assert not fake.volumes
    await executor.close()


async def test_process_capture_bounds_both_streams_timeout_and_cancellation():
    env = {key: os.environ[key] for key in ("PATH", "HOME") if key in os.environ}
    result = await sdk._process([sys.executable, "-c", "import os; os.write(1,b'x'*10000); os.write(2,b'y'*10000)"],
                                timeout=2, output_limit=100, env=env)
    assert result.limit == "output_limit" and len(result.stdout) + len(result.stderr) == 100
    result = await sdk._process([sys.executable, "-c", "import time; time.sleep(60)"], timeout=.03, output_limit=100, env=env)
    assert result.limit == "timeout"
    operation = asyncio.create_task(sdk._process([sys.executable, "-c", "import time; time.sleep(60)"], timeout=60, output_limit=100, env=env))
    await asyncio.sleep(.03)
    operation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await operation


@pytest.mark.skipif(not os.environ.get("WORLD_ENGINE_DOCKER_TEST_IMAGE"), reason="explicit existing local image required for Docker probes")
async def test_real_docker_isolation_reset_artifacts_and_cleanup():
    image = os.environ["WORLD_ENGINE_DOCKER_TEST_IMAGE"]
    specification = task(image_id=image)
    async with sdk.DockerExecutor(allowed_images={image}) as executor:
        names = []
        for _ in range(2):
            async with executor.session(specification) as session:
                names.append(session.name)
                probe = await session.execute("test ! -e answer.txt && python -c 'import os; from pathlib import Path; assert os.getuid()==65534; assert not Path(\"/var/run/docker.sock\").exists(); print(sum(map(int,Path(\"input.txt\").read_text().split())))' > answer.txt")
                assert probe.exit_code == 0, probe.stderr
                bundle = await session.finish()
                assert bundle.files["answer.txt"] == b"7\n"
                assert bundle.runtime_receipt["network"] == "none"
                assert bundle.runtime_receipt["read_only_rootfs"] is True
                assert not executor.sessions
        assert names[0] != names[1]
        async with executor.session(specification) as session:
            assert (await session.execute("touch /read-only-root")).exit_code != 0
            assert (await session.execute("python -c 'import socket; socket.create_connection((\"1.1.1.1\",80),timeout=.2)' ")).exit_code != 0
            assert (await session.execute("python -c 'from pathlib import Path; Path(\"huge\").write_bytes(b\"x\"*300000)' ")).exit_code != 0
            await session.execute("ln -s /etc/passwd answer.txt")
            with pytest.raises(ValueError):
                await session.finish()
        async with executor.session(specification) as session:
            operation = asyncio.create_task(session.execute("sleep 60"))
            await asyncio.sleep(.15)
            operation.cancel()
            with pytest.raises(asyncio.CancelledError):
                await operation
            assert session.state == "closed"
        assert not executor.sessions
        for command in (["ps", "--all", "--filter", f"label=world-engine.executor-owner={executor.owner}", "--format", "{{.Names}}"],
                        ["volume", "ls", "--filter", f"label=world-engine.executor-owner={executor.owner}", "--format", "{{.Name}}"]):
            result = await executor.command(command, timeout=5)
            assert result.code == 0 and not result.stdout.strip()


@pytest.mark.skipif(not os.environ.get("WORLD_ENGINE_DOCKER_TEST_IMAGE"), reason="explicit existing local image required for Docker probes")
async def test_real_docker_parent_link_idle_expiry_and_output_limits():
    image = os.environ["WORLD_ENGINE_DOCKER_TEST_IMAGE"]
    async with sdk.DockerExecutor(allowed_images={image}, limits=sdk.Limits(episode_seconds=1.2, command_seconds=1)) as executor:
        specification = task(image_id=image, artifact_paths=("out/passwd",))
        async with executor.session(specification) as session:
            assert (await session.execute("ln -s /etc out")).exit_code == 0
            with pytest.raises(ValueError, match="links, special"):
                await session.finish()
        async with executor.session(task(image_id=image)) as session:
            await asyncio.sleep(1.3)
            assert session.expired and session.state == "closed"
            with pytest.raises(sdk.ExecutorError):
                await session.execute("after deadline")
        async with executor.session(task(image_id=image)) as session:
            result = await session.execute("python -c 'import os; os.write(1,b\"x\"*1000000)' ")
            assert result.limit_reason == "output_limit" and session.state == "closed"
        assert not executor.sessions
        for command in (["ps", "--all", "--filter", f"label=world-engine.executor-owner={executor.owner}", "--format", "{{.Names}}"],
                        ["volume", "ls", "--filter", f"label=world-engine.executor-owner={executor.owner}", "--format", "{{.Name}}"]):
            result = await executor.command(command, timeout=5)
            assert result.code == 0 and not result.stdout.strip()


@pytest.mark.skipif(not os.environ.get("WORLD_ENGINE_DOCKER_TEST_IMAGE"), reason="explicit existing local image required for Docker probes")
async def test_real_docker_workspace_capacity_and_running_episode_expiry():
    image = os.environ["WORLD_ENGINE_DOCKER_TEST_IMAGE"]
    limits = sdk.Limits(workspace_bytes=1024 * 1024, episode_seconds=1.2, command_seconds=1.2)
    async with sdk.DockerExecutor(allowed_images={image}, limits=limits) as executor:
        async with executor.session(task(image_id=image)) as session:
            result = await session.execute("python -c 'from pathlib import Path; [Path(str(i)).write_bytes(b\"x\"*80000) for i in range(30)]'")
            assert result.exit_code != 0 and "No space left" in result.stderr
        async with executor.session(task(image_id=image)) as session:
            try:
                result = await session.execute("sleep 60")
                assert result.limit_reason == "timeout"
            except sdk.ExecutorError as error:
                assert "wall-clock" in str(error)
            assert session.state == "closed"
        assert not executor.sessions
