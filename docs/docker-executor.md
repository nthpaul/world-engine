# Local Docker Executor

The Docker SDK runs trusted-packaged terminal/file tasks in fresh constrained containers. It does not change the in-process workflow API, execute a trainer, or provide a remote service. It makes no model calls and never pulls or builds images.

## Run a Task

Pass an exact `sha256:` image ID that is already installed and explicitly approved by the operator. The image must be Linux-based and contain `/bin/sh`, `/bin/tar`, and `sleep`; the synthetic example also needs Python. Image packaging, embedded data and licenses remain the operator's responsibility. An allowlisted image can contain baked-in secrets, so inspect its provenance before approving it. The executor does not print image environment variables.

```python
from world_engine.docker_executor import DockerExecutor, TaskSpec

task = TaskSpec(
    task_id="number-sum",
    version="1.0.0",
    image_id=approved_local_image_id,
    public_inputs={"numbers.txt": b"1\n2\n4\n"},
    artifact_paths=("answer.txt",),
)

async with DockerExecutor(allowed_images={approved_local_image_id}) as executor:
    async with executor.session(task) as session:
        result = await session.execute(
            "python -c 'from pathlib import Path; "
            "print(sum(map(int,Path(\"numbers.txt\").read_text().split())))' > answer.txt"
        )
        artifacts = await session.finish()
    passed = artifacts.files["answer.txt"] == b"7\n"
```

The final check runs in the trusted controller after both containers and their workspace volume have been removed. `ArtifactBundle` contains detached bytes, SHA256 hashes and a filtered inspection receipt. It contains no reward supplied by an agent.

`DockerExecutor` admits at most two sessions. Admission fails immediately with `AdmissionError`; it does not build an unbounded queue. One controller should own one executor instance. `session()` allocates no Docker resources until its async context is entered. Sessions cannot be reused, and overlapping operations on one session are rejected. A new episode always gets a new container and workspace volume.

`execute()` returns the command's exit code, bounded stdout/stderr, duration and optional `timeout` or `output_limit` reason. A nonzero command exit alone does not end a session. Timeout, cancellation, output overflow, budget exhaustion, invalid inspection or artifact failure ends it. `finish()` freezes the task, collects artifacts, destroys resources, and then returns. No command can execute after finish or closure. `close()` is idempotent and can retry failed cleanup.

## Isolation Policy

The controller accepts only a local Unix-socket or local Windows named-pipe Docker endpoint. It refuses TCP, SSH and remote named-pipe contexts, including remote `DOCKER_HOST` values. Docker commands pin the checked endpoint, so later context changes cannot redirect a session. The operator must ensure that the local socket belongs to a local daemon rather than a forwarding proxy.

Every agent and collector uses the same exact approved image ID, with an explicit `/bin/sh` entrypoint and fixed keepalive command. `--pull=never` prevents implicit downloads. Actual container inspection must match the required policy before any task operation:

- Nonroot UID/GID `65534:65534`, no new privileges, all capabilities dropped.
- Network `none`, read-only root filesystem, private IPC/PID/UTS/cgroup configuration and no device requests.
- Bounded memory and memory-swap, CPU and PIDs, file-size/core limits, and disabled Docker log storage.
- No host binds, host directories, Docker socket, private grader files or provider secrets.
- A single explicitly owned workspace volume and a bounded temporary `/tmp` mount.

The workspace is a fresh labeled Docker-managed volume using the `local` driver with exact `tmpfs` type/device/options. The controller verifies its name, ownership, driver and capacity options. It never reuses an existing volume. `volume-nocopy` prevents image files from being silently copied into it. Public input is initialized through bounded stdin to absolute `/bin/tar`, not Docker copy into a read-only root filesystem.

On macOS Docker Desktop, this tmpfs lives in the Docker Linux VM, not the macOS filesystem. Volume metadata belongs to Docker and is removed during cleanup. Docker containers share the daemon's Linux kernel. This is container isolation, not gVisor, a per-task VM or proof against adversarial kernel escapes. It does not protect against the privileged host or Docker owner. Docker itself, its local configuration, the approved image and the controller are trusted.

## Artifact Boundary

The controller pauses the agent and verifies its actual paused state. A separate constrained collector mounts that same workspace read-only. It has no grader, expected answers, model API keys or host socket. It streams the whole workspace through absolute `/bin/tar`; the controller captures stdout/stderr with a strict combined byte ceiling and parses the uncompressed tar sequentially.

Every physical tar header, including extended metadata headers, counts toward a bound. The parser verifies header checksums, record sizes, complete end markers, relative paths, depth, duplicate names, aggregate file bytes and file count. It rejects links, sparse files, devices, FIFOs, unsupported file types, traversal, truncated archives and appended nonzero data. It never calls `extractall` or writes archive paths to the host.

Only after validating the entire archive does it select the requested artifact paths. A requested directory includes its regular descendant files; missing or empty requested outputs fail. This deliberately rejects unsafe or excessive *unselected* files too. Parent-directory symlinks therefore cannot redirect an artifact read outside the workspace. Public inputs and temporary workspace files count toward the same aggregate artifact limits; tasks must fit this conservative export envelope. Default bounds are 256 KiB, 16 regular files, 64 physical headers and depth eight, with a 32 MiB workspace capacity.

The collector and paused agent are destroyed, then the volume is removed, before artifact bytes become available to trusted grading. Runtime receipts include only selected security configuration, storage options and cleanup outcomes, not image environment values or Docker's private mount-source paths.

## Deadlines and Cleanup

The episode clock starts before initialization and covers image inspection, volume/container creation, input initialization, commands, freeze and collection. A controller-owned watchdog initiates whole-session removal at the deadline even while the caller is idle. This is not a daemon TTL or crash-proof deadline. Command timeouts never exceed the remaining episode budget. Cancellation also removes the whole container rather than merely killing a Docker CLI process.

Cleanup has separate bounded control operations because an expired episode still needs removal, so completion of removal can extend beyond the nominal episode deadline. Docker scheduling and an unavailable daemon prevent a hard real-time kill guarantee. Removal failures raise `ExecutorError`, retain the session's admission slot, and remain retryable through `close()`; no artifact bundle is returned on cleanup failure. Cleanup checks ownership before removing resources and refuses to remove a foreign container or volume. A killed controller or host cannot run its watchdog and can leave containers or volumes: inspect resources by the recorded `world-engine.executor-owner` label and remove abandoned owned resources explicitly. There is no automatic cross-process scavenger or restart recovery in this standalone SDK.

## Verify and Measure

Default tests require no Docker daemon. They cover policy mismatch, remote endpoints, archive attacks, bounded subprocess capture, admission, reset names, cancellation, idle deadlines, active-operation close races and cleanup retries.

```sh
uv run pytest tests/test_docker_executor.py -q
WORLD_ENGINE_DOCKER_TEST_IMAGE=sha256:YOUR_APPROVED_IMAGE_ID \
  uv run pytest tests/test_docker_executor.py -q
uv run python examples/docker_executor.py --image sha256:YOUR_APPROVED_IMAGE_ID
uv run python examples/docker_executor.py --image sha256:YOUR_APPROVED_IMAGE_ID \
  --benchmark --episodes 4 --trials 3 --output examples/docker-results/lifecycle.json
```

The optional probes verify actual nonroot execution, filesystem/network denial, file/workspace limits, fresh reset, parent/final symlink rejection, idle/running deadlines, output overflow and absence of owned resources after cleanup. The example creates only synthetic public inputs. Its JSON receipt records source revision/fingerprints, machine/runtime, image ID, per-episode inspection and cleanup, outcomes, timings and `training_eligible=false`.

The benchmark compares bounded concurrency one and two with repeated fresh-container trials. It refuses to start unless the four executor source files are committed and clean; unrelated checkout changes are recorded separately. An existing output path, including a broken symlink, is rejected before any Docker operation. The final exclusive file creation also prevents overwrites if the path appears during collection. It includes Docker CLI, initialization, collector and cleanup overhead. It measures local container lifecycle I/O, not real-model, cloud, competitor or parallel Python CPU performance.
