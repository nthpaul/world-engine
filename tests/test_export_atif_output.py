import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from world_engine.models import RunConfig
from world_engine.rollout import rollout

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "examples/export_atif.py"
SPEC = importlib.util.spec_from_file_location("export_atif_example", SCRIPT)
EXAMPLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXAMPLE)


@pytest.mark.parametrize("kind", ["directory", "file", "live-symlink", "dangling-symlink"])
def test_existing_destination_rejected_before_source_or_upstream_work(tmp_path, kind):
    output = tmp_path / "receipt"
    retained = tmp_path / "original.json"
    retained.write_text("retained original evidence\n")
    if kind == "directory":
        output.mkdir()
        (output / "episode-000.json").write_text("retained trajectory\n")
    elif kind == "file":
        output.write_text("retained output\n")
    elif kind == "live-symlink":
        output.symlink_to(retained)
    else:
        output.symlink_to(tmp_path / "missing-target")
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    with pytest.raises(FileExistsError):
        EXAMPLE.main(tmp_path / "missing-input.jsonl", output, validate_upstream=True)
    assert {path: path.read_bytes() for path in before} == before
    if kind.endswith("symlink"):
        assert output.is_symlink()


async def test_fresh_export_retains_replayable_episode_and_exclusive_receipt(tmp_path, capsys):
    episode = await rollout(RunConfig(environment_id="refund-ops", episodes=1, seed=42,
                                      concurrency=1, evaluation_only=True), 0)
    source = tmp_path / "source.jsonl"
    source.write_text(json.dumps(episode) + "\n")
    output = tmp_path / "new-export"
    EXAMPLE.main(source, output, validate_upstream=False)
    document = json.loads((output / "episode-000.json").read_text())
    receipt = json.loads((output / "validation-receipt.json").read_text())
    assert document["trajectory_id"] == episode["id"]
    assert document["extra"]["evaluation_only"] is True
    assert document["extra"]["training_eligible"] is False
    assert receipt["provider_calls"] == receipt["paid_calls"] == 0
    assert receipt["files"][0]["episode_id"] == episode["id"]
    assert output.stat().st_mode & 0o777 == 0o700
    assert json.loads(capsys.readouterr().out)["files"] == receipt["files"]
    before = {path: path.read_bytes() for path in output.iterdir()}
    with pytest.raises(FileExistsError):
        EXAMPLE.main(source, output, validate_upstream=False)
    assert {path: path.read_bytes() for path in before} == before


def test_cli_requires_explicit_output_before_reading_historical_inputs():
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, capture_output=True,
                            text=True, timeout=10)
    assert result.returncode == 2
    assert "--output" in result.stderr and "required" in result.stderr
