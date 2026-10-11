import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ("examples/schema_cache_comparison.py", "examples/io_overlap_benchmark.py",
           "examples/local_model_benchmark.py", "examples/generate_dataset.py", "scripts/public-benchmark.py")


def load_script(relative):
    spec = importlib.util.spec_from_file_location("collector_" + Path(relative).stem.replace("-", "_"), ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("relative", SCRIPTS)
@pytest.mark.parametrize("kind", ["directory", "file", "symlink", "dangling-symlink"])
async def test_existing_output_rejected_before_any_activity(tmp_path, monkeypatch, relative, kind):
    module = load_script(relative)
    output, target = tmp_path / "output", tmp_path / "target"
    if kind == "directory":
        output.mkdir()
        (output / "receipt.json").write_text("historical receipt")
    elif kind == "file":
        output.write_text("historical receipt")
    else:
        if kind == "symlink":
            target.mkdir()
            (target / "receipt.json").write_text("historical receipt")
        output.symlink_to(target, target_is_directory=True)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    def forbidden(*args, **kwargs):
        pytest.fail("fresh output must be reserved before database, provider, Docker or network activity")

    for name in ("Store", "RunManager", "benchmark", "local_endpoint", "verify_source", "build_images",
                 "json_request", "evaluate", "verify_file_limit"):
        if hasattr(module, name):
            monkeypatch.setattr(module, name, forbidden)
    with pytest.raises(FileExistsError):
        if relative.startswith("scripts/"):
            monkeypatch.setattr(sys, "argv", [relative, "--output", str(output), "--skip-local"])
            module.main()
        elif relative.endswith("local_model_benchmark.py"):
            await module.main(output, 1, 42)
        else:
            await module.main(output)
    assert {path: path.read_bytes() for path in before} == before
    assert output.is_symlink() == ("symlink" in kind)
    if kind == "dangling-symlink":
        assert not target.exists()


@pytest.mark.parametrize("relative", SCRIPTS)
def test_cli_requires_explicit_output(tmp_path, relative):
    result = subprocess.run([sys.executable, str(ROOT / relative)], cwd=tmp_path,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert "--output" in result.stderr and "required" in result.stderr
    assert list(tmp_path.iterdir()) == []


async def test_schema_cache_uses_two_distinct_fresh_children_and_restores_cache(tmp_path, monkeypatch):
    module = load_script(SCRIPTS[0])
    cached = module.environments._argument_schema
    output = tmp_path / "new/cache-control"
    historical = tmp_path / "old-receipt.json"
    historical.write_text("unchanged prior receipt")
    calls = []

    async def tiny_benchmark(path, episodes, trials, **kwargs):
        assert not path.exists()
        assert path.parent == output and output.is_dir()
        path.mkdir()
        calls.append((path, episodes, trials, kwargs, module.environments._argument_schema))
        row = {"environment_id": "crm-merge", "provider_id": "scripted-oracle", "concurrency": 1,
               "passed": 90, "episodes": 90, "median_episodes_per_second": 2 if kwargs else 4}
        report = {"rows": [row], "raw_trials": [{"scenario_ids": ["fixed-case"], "implementation": {"source": "fixed"}}]}
        (path / "benchmark.json").write_text(json.dumps(report))
        return report

    monkeypatch.setattr(module, "benchmark", tiny_benchmark)
    await module.main(output)
    assert [call[0].name for call in calls] == ["uncached-control", "cached-control"]
    assert all(call[1:3] == (30, 3) for call in calls)
    assert calls[0][4] is cached.__wrapped__ and calls[1][4] is cached
    assert module.environments._argument_schema is cached
    assert json.loads((output / "schema-cache-comparison.json").read_text())["pairs"][0]["ratio"] == 2
    assert historical.read_text() == "unchanged prior receipt"
    before = {path: path.read_bytes() for path in output.rglob("*") if path.is_file()}
    with pytest.raises(FileExistsError):
        await module.main(output)
    assert len(calls) == 2 and {path: path.read_bytes() for path in before} == before


async def test_schema_cache_exception_restores_cache(tmp_path, monkeypatch):
    module = load_script(SCRIPTS[0])
    cached = module.environments._argument_schema

    async def fail(*args, **kwargs):
        raise RuntimeError("fake measurement failure")

    monkeypatch.setattr(module, "benchmark", fail)
    with pytest.raises(RuntimeError, match="fake measurement failure"):
        await module.main(tmp_path / "fresh")
    assert module.environments._argument_schema is cached


async def test_local_report_preserves_missing_usage_without_inference(tmp_path, monkeypatch):
    module = load_script(SCRIPTS[2])
    configs = []
    closed = []
    base_episode = {"id": "fake-episode", "seed": 42, "scenario_id": "fake-scenario",
                    "provenance": {"git_revision": "fake-revision", "git_dirty": False}, "status": "completed",
                    "termination": "finished", "reward": 0, "passed": False, "steps": 1,
                    "elapsed_seconds": 1, "invalid_actions": 0, "error": None, "usage": {},
                    "split": "train", "final_state_hash": "fake-hash", "trace": [
                        {"action": {"tool": "finish", "args": {}}, "result": {"ok": True}, "elapsed_ms": 0, "usage": {}}]}

    class FakeManager:
        def __init__(self, store):
            pass

        def submit(self, config):
            configs.append(config)
            return {"id": str(len(configs))}

        async def wait(self, run_id):
            return {"id": run_id, "status": "completed", "passed_episodes": 0, "completed_episodes": 1,
                    "success_rate": 0, "elapsed_seconds": 1, "error": None, "episodes": [copy.deepcopy(base_episode)]}

        async def close(self):
            closed.append(True)

    monkeypatch.setattr(module, "ENVIRONMENTS", ["crm-merge"])
    monkeypatch.setattr(module, "Store", lambda path: None)
    monkeypatch.setattr(module, "RunManager", FakeManager)
    monkeypatch.setattr(module, "replay", lambda episode: {"verified": True})
    output = tmp_path / "fresh"
    await module.main(output, 1, 42)
    assert [config.provider_id for config in configs] == ["scripted-oracle", "scripted-baseline", "local"]
    assert all(config.max_steps == 20 and config.timeout_seconds == 120 and config.evaluation_only for config in configs)
    assert closed == [True]
    report = json.loads((output / "local-model.json").read_text())
    assert all(row["episodes"][0]["usage"] == {} for row in report["rows"])
    assert "| unknown | unknown |" in (output / "local-model.md").read_text()
    assert len((output / "local-model-traces.jsonl").read_text().splitlines()) == 3
    assert module.token_total([], "input_tokens") is None
    assert module.token_total([{"usage": {"input_tokens": 0}}], "input_tokens") == 0
    assert module.token_total([{"usage": {"input_tokens": 2, "input_tokens_complete": False}}], "input_tokens") is None


def test_public_run_keeps_each_policy_raw_receipt_in_new_root(tmp_path, monkeypatch):
    module = load_script(SCRIPTS[4])
    output = tmp_path / "fresh"
    monkeypatch.setattr(sys, "argv", ["public-benchmark", "--output", str(output), "--skip-local"])
    for name in ("verify_source", "source_provenance", "controller_source", "verify_file_limit"):
        monkeypatch.setattr(module, name, lambda *args: {})
    images = {"agent_image_id": "fake-agent", "verifier_image_id": "fake-verifier", "base_digest": "fake-base"}
    monkeypatch.setattr(module, "build_images", lambda: images)
    original_reference = {}

    def fake_evaluate(policy, *args):
        if policy == "zero":
            path = output / "attempts/reference/episode.json"
            original_reference[path] = path.read_bytes()
        return {"policy": policy, "model_calls": [], "trace": [], "grader": {"passed": policy == "reference"},
                "summary_csv": policy + "-fake-csv", "elapsed_seconds": 0, "evaluation_only": True, "training_eligible": False}

    monkeypatch.setattr(module, "evaluate", fake_evaluate)
    module.main()
    assert [episode["policy"] for episode in json.loads((output / "report.json").read_text())["episodes"]] == ["reference", "zero"]
    assert all(path.read_bytes() == content for path, content in original_reference.items())
    for policy in ("reference", "zero"):
        raw = output / "attempts" / policy
        assert json.loads((raw / "episode.json").read_text())["policy"] == policy
        assert (raw / f"{policy}-summary.csv").read_text() == policy + "-fake-csv"
    first = json.loads((output / "attempts/reference/report.json").read_text())
    with pytest.raises(FileExistsError):
        module.write_report(output / "attempts/reference", first)
    assert all(path.read_bytes() == content for path, content in original_reference.items())
