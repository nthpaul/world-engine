"""Small executable checks for the public-task runner's actual boundaries."""

import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import traceback
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("public_benchmark", ROOT / "scripts/public-benchmark.py")
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class PublicBenchmarkTests(unittest.TestCase):
    def test_loopback_only_without_credentials_or_redirect_destinations(self):
        for endpoint in ["https://127.0.0.1:11434", "http://example.com", "http://127.0.0.1@evil.test",
                         "http://user:secret@localhost", "http://localhost?token=value", "http://localhost/path",
                         "http://localhost:99999", "http://localhost#remote"]:
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                runner.local_endpoint(endpoint)
        self.assertEqual(runner.local_endpoint("http://127.0.0.1:11434/"), "http://127.0.0.1:11434")

    def test_command_schema_and_bounds(self):
        for value in [[], {"command": 1}, {"command": "pwd", "extra": True},
                      {"command": "x" * (runner.MAX_COMMAND_BYTES + 1)}, {"command": "\0"}]:
            with self.subTest(value=str(value)[:50]), self.assertRaises(ValueError):
                runner.validate_command(value)
        self.assertEqual(runner.validate_command({"command": "python - <<'PY'\nprint(1)\nPY"}), "python - <<'PY'\nprint(1)\nPY")

    def test_output_and_time_limits_are_executed(self):
        noisy = runner.bounded_process([sys.executable, "-c", "print('x' * 20000)"], timeout=2)
        self.assertEqual(noisy["limit"], "output_limit")
        self.assertLessEqual(len(noisy["output"].encode()), runner.MAX_OUTPUT)
        slow = runner.bounded_process([sys.executable, "-c", "import time; time.sleep(2)"], timeout=0.1)
        self.assertEqual(slow["limit"], "timeout")
        self.assertLess(slow["elapsed_seconds"], 1)

    def test_runtime_agent_mounts_only_output_with_nonroot_limits(self):
        flags = runner.runtime_args("test-agent", "sha256:abc", Path("/private/output.csv"))
        self.assertIn("65534:65534", flags)
        for flag in ["--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                     "--pids-limit=64", "--memory=2g", "--cpus=1"]:
            self.assertIn(flag, flags)
        mounts = [flags[index + 1] for index, value in enumerate(flags) if value == "--mount"]
        self.assertEqual(mounts, ["type=bind,src=/private/output.csv,dst=/app/summary.csv"])
        self.assertNotIn("/tests", " ".join(flags))
        self.assertNotIn("docker.sock", " ".join(flags))
        self.assertIn(f"fsize={runner.MAX_ARTIFACT}:{runner.MAX_ARTIFACT}", flags)
        self.assertIn("core=0:0", flags)
        self.assertIn("--log-driver=none", flags)
        verifier = runner.runtime_args("test-verifier", "sha256:abc", Path("/private/output.csv"), verifier=True)
        self.assertIn("dst=/tests/test_outputs.py,readonly", " ".join(verifier))
        for flag in [f"fsize={runner.MAX_ARTIFACT}:{runner.MAX_ARTIFACT}", "core=0:0", "--log-driver=none"]:
            self.assertIn(flag, verifier)

    def test_fixed_output_rejects_symlinks_and_large_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "summary.csv"
            source.write_text("period,severity,count\n")
            self.assertEqual(runner.read_output(source), "period,severity,count\n")
            link = Path(temporary) / "link.csv"
            link.symlink_to(source)
            with self.assertRaises(OSError):
                runner.read_output(link)
            source.write_bytes(b"x" * (runner.MAX_ARTIFACT + 1))
            with self.assertRaises(ValueError):
                runner.read_output(source)

    def test_native_tools_validate_one_whitelisted_function(self):
        name, arguments = runner.native_tool({"tool_calls": [{"function": {"name": "shell", "arguments": {"command": "pwd"}}}]})
        self.assertEqual((name, arguments), ("shell", {"command": "pwd"}))
        self.assertEqual(runner.native_tool({"tool_calls": [{"function": {"name": "finish", "arguments": {}}}]}), ("finish", {}))
        for value in [{}, {"tool_calls": []}, {"tool_calls": [{"function": {"name": "other", "arguments": {}}}]},
                      {"tool_calls": [{"function": {"name": "finish", "arguments": {"command": "pwd"}}}]}]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                runner.native_tool(value)

    def test_recorded_kernel_file_size_probe(self):
        artifact = ROOT / "artifacts/public-benchmark/native-tools-v2-hardened/report.json"
        if not artifact.exists():
            self.skipTest("Run hardened public benchmark to generate actual file-size probe evidence")
        probe = json.loads(artifact.read_text())["file_size_probe"]
        self.assertTrue(probe["passed"])
        self.assertLessEqual(probe["actual_bytes"], runner.MAX_ARTIFACT)
        self.assertNotEqual(probe["returncode"], 0)
        self.assertEqual(probe["log_config"]["Type"], "none")

    def test_task_source_is_verified_and_remains_evaluation_only(self):
        runner.verify_source()
        provenance = runner.source_provenance()
        self.assertFalse(provenance["training_eligible"])
        self.assertTrue(provenance["evaluation_only"])
        self.assertIn(runner.CANARY, (runner.TASK / "tests/test_outputs.py").read_text())
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "source"
            shutil.copytree(runner.SOURCE, copied)
            (copied / "log-summary-date-ranges/instruction.md").write_text("modified")
            with self.assertRaisesRegex(ValueError, "source hash changed"):
                runner.verify_source(copied)
            with self.assertRaisesRegex(ValueError, "evaluation-only"):
                runner.write_report(Path(temporary) / "unsafe", {"evaluation_only": False, "training_eligible": True})

    def test_recorded_official_grader_passes_reference_and_rejects_wrong_output(self):
        artifact = ROOT / "artifacts/public-benchmark/report.json"
        if not artifact.exists():
            self.skipTest("Run scripts/public-benchmark.py to generate real Docker grading evidence")
        report = json.loads(artifact.read_text())
        policies = {episode["policy"]: episode for episode in report["episodes"]}
        self.assertTrue(policies["reference"]["grader"]["passed"])
        self.assertFalse(policies["zero"]["grader"]["passed"])
        self.assertFalse(report["training_eligible"])
        for episode in policies.values():
            self.assertFalse(episode["training_eligible"])
            self.assertEqual(episode["runtime"]["user"], "65534:65534")
            self.assertEqual(episode["runtime"]["network_mode"], "none")
            self.assertTrue(episode["runtime"]["read_only_rootfs"])
            self.assertLessEqual(len(episode["trace"]), runner.MAX_COMMANDS)


class PublicPreflightTests(unittest.TestCase):
    sentinel = "PRIVATE_PREFLIGHT_SENTINEL"
    endpoint = "unix:///var/run/docker.sock"
    model = "qwen3:8b"

    def setUp(self):
        self.metadata = {"/api/tags": {"models": [{"name": self.model, "digest": "a" * 64}]},
                         "/api/show": {"capabilities": ["completion", "tools"]},
                         "/api/version": {"version": "0.12.0"}}
        self.addCleanup(setattr, runner, "_docker_endpoint", None)
        self.addCleanup(setattr, runner, "_docker_environment", None)

    def request(self, endpoint, route, payload, timeout, *, max_bytes):
        self.assertEqual(endpoint, "http://127.0.0.1:11434")
        self.assertEqual(max_bytes, runner.MAX_METADATA)
        self.assertEqual(timeout, 5)
        self.assertEqual(payload, {"model": self.model} if route == "/api/show" else None)
        return self.metadata[route]

    def preflight(self, protocol="native-tools-v2"):
        return runner.model_preflight("http://127.0.0.1:11434", self.model, protocol)

    def test_valid_model_identity_and_protocol_capabilities(self):
        for protocol in ("native-tools-v2", "json-command-v1"):
            with self.subTest(protocol=protocol), patch.object(runner, "json_request", side_effect=self.request) as request:
                result = self.preflight(protocol)
                self.assertEqual(result, {"name": self.model, "digest": "a" * 64,
                                          "capabilities": ["completion", "tools"], "daemon_version": "0.12.0"})
                self.assertEqual([call.args[1] for call in request.call_args_list], ["/api/tags", "/api/show", "/api/version"])

    def test_cloud_and_invalid_names_do_not_contact_model(self):
        for name in ("qwen:cloud", "CLOUD-alias", "", "x" * 201, "qwen\n" + self.sentinel):
            with self.subTest(name=name), patch.object(runner, "json_request") as request:
                with self.assertRaises(ValueError):
                    runner.model_preflight("http://127.0.0.1:11434", name, "native-tools-v2")
                request.assert_not_called()

    def test_invalid_catalog_identity_remote_metadata_and_capabilities(self):
        cases = [
            ("/api/tags", {}), ("/api/tags", {"models": {}}), ("/api/tags", {"models": [self.sentinel]}),
            ("/api/tags", {"models": [{"name": "other", "digest": "a" * 64}]}),
            ("/api/tags", {"models": [{"name": self.model, "digest": "a" * 64}] * 2}),
            ("/api/show", {"capabilities": "tools"}), ("/api/show", {"capabilities": ["completion"]}),
            ("/api/show", {"capabilities": ["tools", {}]}), ("/api/version", {}),
            ("/api/version", {"version": 1}), ("/api/version", {"version": self.sentinel + "\n"}),
        ]
        cases.extend(("/api/tags", {"models": [{"name": self.model, "digest": value}]})
                     for value in (None, "", "a" * 63, "A" * 64, "g" * 64, "sha256:" + "a" * 64))
        for route in self.metadata:
            for field in ("remote_host", "remote_model"):
                cases.append((route, {**self.metadata[route], field: self.sentinel}))
                if route == "/api/tags":
                    cases.append((route, {"models": [{**self.metadata[route]["models"][0], field: self.sentinel}]}))
        for route, value in cases:
            with self.subTest(route=route, value=value), patch.object(runner, "json_request", side_effect=lambda _e, path, *_a, **_k: value if path == route else self.metadata[path]):
                with self.assertRaises(ValueError) as caught:
                    self.preflight()
                self.assertNotIn(self.sentinel, str(caught.exception))
                self.assertNotIn(self.sentinel, "".join(traceback.format_exception(caught.exception)))
                self.assertIsNone(caught.exception.__cause__)

    def test_metadata_transport_errors_are_redacted(self):
        for error in (OSError(self.sentinel), ValueError(self.sentinel), RecursionError(self.sentinel)):
            with self.subTest(error=type(error)), patch.object(runner, "json_request", side_effect=error):
                with self.assertRaises(ValueError) as caught:
                    self.preflight()
                self.assertNotIn(self.sentinel, "".join(traceback.format_exception(caught.exception)))

    def test_direct_host_is_pinned_and_environment_overrides_are_removed(self):
        environment = {"DOCKER_HOST": self.endpoint, "DOCKER_CONTEXT": "remote", "DOCKER_TLS_VERIFY": "1",
                       "DOCKER_CERT_PATH": self.sentinel, "DOCKER_API_VERSION": "1.10", "HTTP_PROXY": self.sentinel,
                       "HOME": "/home/test", "PATH": "/bin", "DOCKER_CONFIG": "/home/test/.docker"}
        with patch.dict(os.environ, environment, clear=True), patch.object(runner, "_bounded_process") as process:
            runner.configure_docker()
            process.assert_not_called()
            for command in ("pull", "build", "run", "inspect", "exec", "rm", "tag", "image"):
                runner.bounded_process(["docker", command, "argument"], timeout=3, stdin="input", max_output=10)
                self.assertEqual(process.call_args.args[0], ["docker", "--host", self.endpoint, command, "argument"])
                self.assertEqual(process.call_args.kwargs["environment"],
                                 {"HOME": "/home/test", "PATH": "/bin", "DOCKER_CONFIG": "/home/test/.docker"})
                self.assertEqual(process.call_args.kwargs["timeout"], 3)

    def test_context_lookup_is_local_only_then_future_calls_remain_pinned(self):
        responses = [{"output": "desktop-linux\n", "returncode": 0, "limit": None},
                     {"output": json.dumps(self.endpoint), "returncode": 0, "limit": None}]
        with patch.dict(os.environ, {"PATH": "/bin", "DOCKER_TLS_VERIFY": "1"}, clear=True), patch.object(runner, "_bounded_process", side_effect=responses) as process:
            runner.configure_docker()
            self.assertEqual(process.call_args_list[0].args[0], ["docker", "context", "show"])
            self.assertEqual(process.call_args_list[1].args[0],
                             ["docker", "context", "inspect", "desktop-linux", "--format", "{{json .Endpoints.docker.Host}}"])
            for call in process.call_args_list:
                self.assertEqual(call.kwargs["environment"], {"PATH": "/bin"})
                self.assertEqual(call.kwargs["max_output"], 4096)
            self.assertEqual(runner._docker_endpoint, self.endpoint)
        with patch.dict(os.environ, {"DOCKER_HOST": "ssh://changed"}, clear=True), patch.object(runner, "_bounded_process") as process:
            runner.bounded_process(["docker", "rm", "--force", "test"], timeout=15)
            self.assertEqual(process.call_args.args[0][:3], ["docker", "--host", self.endpoint])
            self.assertEqual(process.call_args.kwargs["environment"], {"PATH": "/bin"})

    def test_remote_or_malformed_endpoint_resets_preflight_and_never_contacts_daemon(self):
        for endpoint in ("tcp://localhost:2375", "ssh://localhost", "npipe:////remote/pipe/docker_engine",
                         "unix://", "unix:///sock?" + self.sentinel, "unix:///sock\n" + self.sentinel, ""):
            with self.subTest(endpoint=endpoint), patch.dict(os.environ, {"DOCKER_HOST": endpoint}, clear=True), patch.object(runner, "_bounded_process") as process:
                runner._docker_endpoint, runner._docker_environment = self.endpoint, {}
                with self.assertRaises(RuntimeError) as caught:
                    runner.configure_docker()
                self.assertNotIn(self.sentinel, "".join(traceback.format_exception(caught.exception)))
                self.assertIsNone(runner._docker_endpoint)
                process.assert_not_called()
                with self.assertRaises(RuntimeError):
                    runner.bounded_process(["docker", "build", "."], timeout=1)
                process.assert_not_called()

    def test_context_failure_is_bounded_and_redacted(self):
        for result in ({"output": self.sentinel, "returncode": 1, "limit": None},
                       {"output": self.sentinel, "returncode": 0, "limit": "timeout"},
                       {"output": json.dumps("ssh://" + self.sentinel), "returncode": 0, "limit": None},
                       {"output": "not-json" + self.sentinel, "returncode": 0, "limit": None}):
            with self.subTest(result=result), patch.dict(os.environ, {"DOCKER_CONTEXT": "test"}, clear=True), patch.object(runner, "_bounded_process", return_value=result) as process:
                with self.assertRaises(RuntimeError) as caught:
                    runner.configure_docker()
                self.assertNotIn(self.sentinel, "".join(traceback.format_exception(caught.exception)))
                self.assertEqual(len(process.call_args_list), 1)
                self.assertIsNone(runner._docker_endpoint)
        with patch.dict(os.environ, {"DOCKER_CONTEXT": "--host=" + self.sentinel}, clear=True), patch.object(runner, "_bounded_process") as process:
            with self.assertRaises(RuntimeError):
                runner.configure_docker()
            process.assert_not_called()

    def test_valid_local_named_pipe(self):
        endpoint = "npipe:////./pipe/docker_engine"
        with patch.dict(os.environ, {"DOCKER_HOST": endpoint}, clear=True):
            runner.configure_docker()
        self.assertEqual(runner._docker_endpoint, endpoint)

    def test_all_build_and_episode_lifecycle_commands_use_pinned_boundary(self):
        inspected = {"Config": {"User": "65534:65534"}, "HostConfig": {
            "NetworkMode": "none", "ReadonlyRootfs": True, "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges"], "PidsLimit": 64, "Memory": 2 * 1024**3,
            "NanoCpus": 10**9, "Ulimits": [], "LogConfig": {"Type": "none"}}, "Mounts": []}
        commands = []
        runner._docker_endpoint, runner._docker_environment = self.endpoint, {"PATH": "/bin"}

        def process(args, **kwargs):
            self.assertEqual(args[:3], ["docker", "--host", self.endpoint])
            self.assertEqual(kwargs["environment"], {"PATH": "/bin"})
            command = args[3:]
            commands.append(command)
            output = ""
            limit = None
            if command[:2] == ["image", "inspect"]:
                output = "sha256:" + "a" * 64 if "--format" in command else json.dumps([{"RepoDigests": ["python@sha256:" + "a" * 64]}])
            elif command[0] == "inspect":
                output = json.dumps([inspected])
            elif command[0] == "exec":
                limit = "timeout"
            return {"output": output, "returncode": 0, "limit": limit, "elapsed_seconds": 0.01}

        with patch.object(runner, "_bounded_process", side_effect=process), patch("sys.stdout", new=io.StringIO()):
            images = runner.build_images()
            result = runner.evaluate("zero", images, "http://localhost:11434", self.model)
        self.assertEqual(result["termination"], "controller_error")
        self.assertIn("Command hit timeout", result["error"])
        self.assertTrue(result["grader"]["passed"])
        self.assertEqual([command[0] for command in commands[:8]],
                         ["pull", "image", "build", "image", "tag", "build", "image", "run"])
        exec_index = next(index for index, command in enumerate(commands) if command[0] == "exec")
        self.assertEqual(commands[exec_index + 1][0], "rm")
        self.assertEqual(commands[exec_index + 2][0], "run")
        self.assertEqual([command[0] for command in commands[-2:]], ["rm", "rm"])

    def test_file_probe_cleanup_uses_pinned_boundary(self):
        runner._docker_endpoint, runner._docker_environment = self.endpoint, {}
        calls = []

        def process(args, **kwargs):
            self.assertEqual(args[:3], ["docker", "--host", self.endpoint])
            self.assertEqual(kwargs["environment"], {})
            command = args[3:]
            calls.append(command)
            output = json.dumps([{"HostConfig": {"Ulimits": [], "LogConfig": {"Type": "none"}}}]) if command[0] == "inspect" else ""
            return {"output": output, "returncode": 1 if command[0] == "exec" else 0,
                    "limit": None, "elapsed_seconds": 0.01}

        with patch.object(runner, "_bounded_process", side_effect=process):
            self.assertTrue(runner.verify_file_limit("sha256:" + "a" * 64)["passed"])
        self.assertEqual([command[0] for command in calls], ["run", "inspect", "exec", "rm"])

    def test_local_origin_parse_errors_are_redacted_before_opener(self):
        for endpoint in ("http://localhost:" + self.sentinel, "http://[" + self.sentinel,
                         "http://localhost:0", "http://localhost:", "http://localhost/\n" + self.sentinel):
            with self.subTest(endpoint=endpoint), patch.object(runner.urllib.request, "build_opener") as opener:
                with self.assertRaises(ValueError) as caught:
                    runner.json_request(endpoint, "/api/tags", None, 5)
                self.assertNotIn(self.sentinel, "".join(traceback.format_exception(caught.exception)))
                opener.assert_not_called()

    def test_docker_errors_do_not_echo_raw_output_or_exception(self):
        runner._docker_endpoint, runner._docker_environment = self.endpoint, {}
        for result in ({"output": self.sentinel, "returncode": 1, "limit": None},
                       {"output": self.sentinel, "returncode": 0, "limit": "output_limit"}):
            with patch.object(runner, "_bounded_process", return_value=result):
                with self.assertRaises(RuntimeError) as caught:
                    runner.checked(["docker", "inspect", "test"])
                self.assertNotIn(self.sentinel, "".join(traceback.format_exception(caught.exception)))
        with patch.object(runner, "_bounded_process", side_effect=OSError(self.sentinel)):
            with self.assertRaises(RuntimeError) as caught:
                runner.bounded_process(["docker", "rm", "--force", "test"], timeout=15)
            self.assertNotIn(self.sentinel, "".join(traceback.format_exception(caught.exception)))

    def test_bounded_identity_http_metadata_and_no_redirect_proxy(self):
        for body, encoding, expected in ((b'{"version":"0.12"}', "identity", True),
                                         (b"x" * (runner.MAX_METADATA + 1), "identity", False),
                                         (b"secret-body", "gzip", False),
                                         ((b"[" * 2000) + self.sentinel.encode(), "identity", False)):
            stream = Mock()
            stream.headers = {"Content-Encoding": encoding}
            stream.read.return_value = body
            response = Mock()
            response.__enter__ = Mock(return_value=stream)
            response.__exit__ = Mock(return_value=False)
            opener = Mock()
            opener.open.return_value = response
            with self.subTest(encoding=encoding, size=len(body)), patch.object(runner.urllib.request, "build_opener", return_value=opener) as build:
                if expected:
                    self.assertEqual(runner.json_request("http://localhost:11434", "/api/version", None, 5,
                                                         max_bytes=runner.MAX_METADATA), {"version": "0.12"})
                else:
                    with self.assertRaises(ValueError) as caught:
                        runner.json_request("http://localhost:11434", "/api/version", None, 5,
                                            max_bytes=runner.MAX_METADATA)
                    self.assertNotIn(self.sentinel, "".join(traceback.format_exception(caught.exception)))
                self.assertEqual(opener.open.call_args.args[0].get_header("Accept-encoding"), "identity")
                proxy, redirect = build.call_args.args
                self.assertEqual(proxy.proxies, {})
                with self.assertRaises(ValueError):
                    redirect.redirect_request(None)
                if encoding == "gzip":
                    stream.read.assert_not_called()
                else:
                    stream.read.assert_called_once_with(runner.MAX_METADATA + 1)

    def test_fresh_output_gate_precedes_all_activity(self):
        with tempfile.TemporaryDirectory() as temporary:
            existing = Path(temporary) / "existing"
            existing.mkdir()
            link = Path(temporary) / "link"
            link.symlink_to(existing)
            dead = Path(temporary) / "dead"
            dead.symlink_to(Path(temporary) / "absent")
            file = Path(temporary) / "file"
            file.write_text("unchanged")
            for output in (existing, link, dead, file):
                with self.subTest(output=output), patch.object(sys, "argv", ["runner", "--output", str(output)]), patch.object(runner, "configure_docker") as docker, patch.object(runner, "json_request") as model, patch.object(runner, "build_images") as build:
                    with self.assertRaises(FileExistsError):
                        runner.main()
                    docker.assert_not_called()
                    model.assert_not_called()
                    build.assert_not_called()
            self.assertEqual(file.read_text(), "unchanged")

    def test_failed_preflight_never_builds_images(self):
        for failed in ("docker", "model"):
            with tempfile.TemporaryDirectory() as temporary, patch.object(sys, "argv", ["runner", "--output", str(Path(temporary) / "new")]), patch.object(runner, "verify_source"), patch.object(runner, "configure_docker", side_effect=RuntimeError("safe") if failed == "docker" else None) as docker, patch.object(runner, "model_preflight", side_effect=ValueError("safe")) as model, patch.object(runner, "build_images") as build:
                with self.assertRaises((RuntimeError, ValueError)):
                    runner.main()
                docker.assert_called_once()
                if failed == "docker":
                    model.assert_not_called()
                build.assert_not_called()

    def test_main_orders_gates_and_skip_local_has_zero_model_contact(self):
        for skip in (False, True):
            events = []
            with tempfile.TemporaryDirectory() as temporary, patch.object(sys, "argv", ["runner", "--output", str(Path(temporary) / "new"), *(["--skip-local"] if skip else [])]), patch.object(runner, "verify_source"), patch.object(runner, "configure_docker", side_effect=lambda: events.append("docker")), patch.object(runner, "model_preflight", side_effect=lambda *_: events.append("model")), patch.object(runner, "json_request") as contact, patch.object(runner, "build_images", side_effect=lambda: events.append("build") or {"agent_image_id": "test"}), patch.object(runner, "source_provenance", return_value={}), patch.object(runner, "controller_source", return_value={}), patch.object(runner, "verify_file_limit", return_value={}), patch.object(runner, "write_report"), patch.object(runner, "evaluate", side_effect=lambda policy, *_: {"policy": policy, "grader": {"passed": policy == "reference"}}) as evaluate, patch("sys.stdout", new=io.StringIO()):
                runner.main()
                self.assertEqual(events, ["docker", "build"] if skip else ["docker", "model", "build"])
                self.assertEqual([call.args[0] for call in evaluate.call_args_list], ["reference", "zero"] if skip else ["reference", "zero", "local"])
                contact.assert_not_called()


if __name__ == "__main__":
    unittest.main()
