import hashlib
import importlib
import json
import re
import sys
from pathlib import Path

import pytest

module = importlib.import_module("world_engine.benchmark")


@pytest.mark.parametrize("kind", ["directory", "file", "symlink", "dangling-symlink"])
async def test_existing_output_rejected_before_database_or_runs(tmp_path, monkeypatch, kind):
    output = tmp_path / "receipt"
    target = tmp_path / "target"
    if kind == "directory":
        output.mkdir()
        (output / "benchmark.json").write_text("historical receipt")
    elif kind == "file":
        output.write_text("historical receipt")
    else:
        if kind == "symlink":
            target.mkdir()
            (target / "benchmark.json").write_text("historical receipt")
        output.symlink_to(target, target_is_directory=True)
    before = {str(path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    def forbidden(*args, **kwargs):
        pytest.fail("existing output must be rejected before database or manager activity")

    monkeypatch.setattr(module, "Store", forbidden)
    monkeypatch.setattr(module, "RunManager", forbidden)
    with pytest.raises(FileExistsError):
        await module.benchmark(output, episodes=1, trials=1)
    assert output.is_symlink() == ("symlink" in kind)
    assert {str(path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before
    if kind == "dangling-symlink":
        assert not target.exists()


def test_cli_default_outputs_are_fresh_local_paths(monkeypatch):
    cli = importlib.import_module("world_engine.__main__")
    outputs = []

    async def fake_benchmark(output, episodes, trials):
        outputs.append(output)
        assert episodes == trials == 1

    monkeypatch.setattr(cli, "benchmark", fake_benchmark)
    monkeypatch.setattr(sys, "argv", ["world-engine", "benchmark", "--episodes", "1", "--trials", "1"])
    cli.main()
    cli.main()
    assert len(set(outputs)) == 2
    assert all(output.parent == Path(".world-engine/benchmarks") for output in outputs)
    assert all(re.fullmatch(r"\d{8}T\d{6}\.\d{6}Z-[0-9a-f]{32}", output.name) for output in outputs)


async def test_tiny_benchmark_creates_receipt_and_never_reuses_it(tmp_path, monkeypatch):
    output = tmp_path / "nested" / "fresh"
    result = await module.benchmark(output, episodes=1, trials=1)
    assert result["execution"] == "in-process scripted local CPU"
    assert result["rows"] and all(row["episodes"] == 1 for row in result["rows"])
    assert json.loads((output / "benchmark.json").read_text()) == result
    assert (output / "benchmark.md").read_text().startswith("# Local Workflow Benchmark")
    assert (output / "benchmark.sqlite3").is_file()
    before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in output.iterdir() if path.is_file()}

    def forbidden(*args, **kwargs):
        pytest.fail("repeated benchmark must not open the existing database")

    monkeypatch.setattr(module, "Store", forbidden)
    with pytest.raises(FileExistsError):
        await module.benchmark(output, episodes=1, trials=1)
    assert {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in output.iterdir() if path.is_file()} == before
