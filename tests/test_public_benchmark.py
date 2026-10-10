"""Small executable checks for the public-task runner's actual boundaries."""

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
