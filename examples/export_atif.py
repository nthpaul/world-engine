"""Export existing synthetic evaluation episodes; makes no provider calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import world_engine.atif as atif
from world_engine.atif import ATIF_VERSION, HARBOR_REVISION, HARBOR_SCHEMA_SHA256, export_episode
from world_engine.models import canonical_json


def exporter_source() -> dict:
    collector = Path(__file__).resolve()
    root = collector.parents[1]
    paths = [Path(atif.__file__).resolve(), collector]
    files = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    scope = [str(path.relative_to(root)) if path.is_relative_to(root) else str(path) for path in paths]
    metadata = {"files": files, "git_revision": None, "source_dirty": None, "source_dirty_scope": scope}
    try:
        revision = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                                  capture_output=True, text=True, timeout=2)
        metadata["git_revision"] = revision.stdout.strip() if revision.returncode == 0 else None
        if all(path.is_relative_to(root) for path in paths):
            status = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all", "--", *scope],
                                    capture_output=True, text=True, timeout=2)
            metadata["source_dirty"] = bool(status.stdout.strip()) if status.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        pass
    return metadata


def main(source: Path, output: Path, validate_upstream: bool) -> None:
    validator = None
    if validate_upstream:
        from harbor.models.trajectories.trajectory import Trajectory
        validator = Trajectory
        schema_hash = hashlib.sha256(canonical_json(validator.model_json_schema()).encode()).hexdigest()
        if schema_hash != HARBOR_SCHEMA_SHA256:
            raise ValueError("Installed upstream schema differs from the pinned validation target")
    if source.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("Example input is limited to 64 MiB")
    records = [json.loads(line) for line in source.read_text().splitlines() if line.strip()]
    if not 1 <= len(records) <= 100:
        raise ValueError("Example accepts 1 to 100 recorded episodes")
    trajectories = []
    for record in records:
        episode = record.get("episode", record)
        if "episode" in record and (record.get("schema") != "world-engine.evaluation-trace.v1"
                                   or record.get("evaluation_only") is not True
                                   or record.get("training_eligible") is not False
                                   or episode["provenance"]["evaluation_only"] is not True):
            raise ValueError("Evaluation wrapper or episode eligibility flags are inconsistent")
        trajectory = export_episode(episode)
        if validator:
            validator.model_validate(trajectory)
        trajectories.append(trajectory)
    output.mkdir(parents=True, exist_ok=True)
    files = []
    for index, trajectory in enumerate(trajectories):
        target = output / f"episode-{index:03d}.json"
        content = json.dumps(trajectory, indent=2) + "\n"
        target.write_text(content)
        files.append({"file": target.name, "sha256": hashlib.sha256(content.encode()).hexdigest(),
                      "episode_id": trajectory["trajectory_id"], "steps": len(trajectory["steps"]),
                      "evaluation_only": trajectory["extra"]["evaluation_only"], "training_eligible": False})
    receipt = {"schema_version": ATIF_VERSION, "harbor_revision": HARBOR_REVISION,
               "source": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
               "upstream_validation": bool(validator), "files": files,
               "provider_calls": 0, "paid_calls": 0, "training_eligible": False,
               "validation_command": [sys.executable, *sys.argv],
               "validation_pythonpath": os.environ.get("PYTHONPATH") if validator else None,
               "exporter_source": exporter_source()}
    if validator:
        import pydantic
        receipt["upstream_model"] = f"{validator.__module__}.{validator.__name__}"
        receipt["pydantic_version"] = pydantic.__version__
        receipt["schema_sha256"] = hashlib.sha256(canonical_json(validator.model_json_schema()).encode()).hexdigest()
    (output / "validation-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("examples/benchmark-results/local-model-traces.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/atif"))
    parser.add_argument("--validate-upstream", action="store_true", help="Require separately installed pinned Harbor model")
    args = parser.parse_args()
    main(args.source, args.output, args.validate_upstream)
