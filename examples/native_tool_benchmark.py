"""Locked, evaluation-only six-episode native tool experiment. No implicit inference."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import platform
import subprocess
import time
import uuid
from pathlib import Path

from world_engine.atif import export_episode
from world_engine.exports import export_records
from world_engine.models import RunConfig, canonical_json, utc_now
from world_engine.ollama_tools import PROTOCOL, OllamaToolsProvider, contract
from world_engine.rollout import collection_revision, replay, rollout
from world_engine.store import Store

WORLDS = ("crm-merge", "refund-ops", "incident-control")
SEEDS = (42, 730)
MODEL = "qwen3:8b"
EXPECTED_MODEL_DIGEST = "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41"
MAX_EPISODES = 6
MAX_STEPS = 20
EPISODE_TIMEOUT = 120
OVERALL_TIMEOUT = 900
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_EPISODE_JSON_BYTES = 12 * 1024 * 1024
REPORT_RESERVE_BYTES = 256 * 1024
NEXT_EPISODE_RESERVE_BYTES = 4 * MAX_EPISODE_JSON_BYTES + 1024 * 1024


def artifact_bytes(output: Path) -> int:
    return sum(path.stat().st_size for path in output.rglob("*") if path.is_file())


def reserve_episode(output: Path) -> None:
    if artifact_bytes(output) + NEXT_EPISODE_RESERVE_BYTES + REPORT_RESERVE_BYTES > MAX_ARTIFACT_BYTES:
        raise ValueError("artifact budget reached before the next episode; no additional request permitted")


def write_bounded(handle, content: str, output: Path) -> None:
    if artifact_bytes(output) + len(content.encode("utf-8")) + REPORT_RESERVE_BYTES > MAX_ARTIFACT_BYTES:
        raise ValueError("artifact cap reached; previously saved raw evidence is retained, no success claimed for collection")
    handle.write(content)
    handle.flush()


def source_identity(expected_revision: str) -> dict:
    root = Path(__file__).resolve().parents[1]
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True, timeout=3).stdout.strip()
    scope = ["src/world_engine", "pyproject.toml", "uv.lock", "examples/native_tool_benchmark.py",
             "tests/test_native_provider.py", "tests/test_atif.py", "tests/test_atif_integration.py"]
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=normal", "--", *scope],
                            cwd=root, capture_output=True, text=True, check=True, timeout=3).stdout
    if revision != expected_revision or status.strip():
        raise ValueError("collector requires the explicitly authorized committed revision and clean implementation/collector")
    paths = [*sorted((root / "src/world_engine").rglob("*.py")), Path(__file__).resolve(), root / "pyproject.toml", root / "uv.lock",
             *(root / path for path in scope if path.startswith("tests/"))]
    return {"git_revision": revision, "source_dirty": False, "source_dirty_scope": scope,
            "file_sha256": {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}}


async def collect(output: Path, expected_revision: str) -> dict:
    source = source_identity(expected_revision)
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    started = time.perf_counter()
    store = Store(output / "native-evaluation.sqlite3")
    rows, fatal_error = [], None
    config = RunConfig(environment_id=WORLDS[0], provider_id="local", model=MODEL,
                       episodes=1, concurrency=1, seed=SEEDS[0], max_steps=MAX_STEPS,
                       timeout_seconds=EPISODE_TIMEOUT, evaluation_only=True, allow_paid=False)
    provider = OllamaToolsProvider(config)
    report = {"schema": "world-engine.native-evaluation.v1", "protocol": PROTOCOL, "created_at": utc_now(),
              "source": source, "model": MODEL, "expected_model_digest": EXPECTED_MODEL_DIGEST,
              "worlds": list(WORLDS), "seeds": list(SEEDS), "max_episodes": MAX_EPISODES,
              "max_steps": MAX_STEPS, "episode_timeout_seconds": EPISODE_TIMEOUT,
              "overall_timeout_seconds": OVERALL_TIMEOUT, "concurrency": 1, "evaluation_only": True,
              "artifact_limit_bytes": MAX_ARTIFACT_BYTES, "episode_json_limit_bytes": MAX_EPISODE_JSON_BYTES,
              "training_eligible": False, "paid_calls": 0, "model_downloaded": False,
              "platform": platform.platform(), "contract": contract(), "episodes": rows}
    # Every completed/handled-abort episode is appended before another call begins.
    with (output / "evaluation-episodes.jsonl").open("x") as raw, (output / "operator-traces.jsonl").open("x") as traces, (output / "atif.jsonl").open("x") as atif:
        try:
            async with asyncio.timeout(OVERALL_TIMEOUT):
                await provider.prepare()
                if provider.model_digest != EXPECTED_MODEL_DIGEST:
                    raise ValueError("installed model digest differs from the predeclared experiment; no inference permitted")
                report["provider_evidence"] = provider.evidence_metadata()
                collection_revision.cache_clear()
                for world in WORLDS:
                    for seed in SEEDS:
                        if time.perf_counter() - started >= OVERALL_TIMEOUT:
                            raise TimeoutError("overall experiment deadline reached before the next request")
                        reserve_episode(output)
                        source_identity(expected_revision)
                        run_config = config.model_copy(update={"environment_id": world, "seed": seed,
                            "label": "native tool evaluation; operator-only"})
                        run_id = str(uuid.uuid4())
                        store.create_run(run_id, run_config)
                        store.update_run(run_id, "running")
                        episode = await rollout(run_config, 0, provider)
                        row = {key: episode[key] for key in ("id", "seed", "status", "termination", "reward", "passed",
                                                             "steps", "invalid_actions", "error", "usage", "elapsed_seconds", "split", "provenance")}
                        row.update(environment_id=world, run_id=run_id)
                        rows.append(row)
                        raw_line = canonical_json({"schema": "world-engine.evaluation-trace.v1", "evaluation_only": True,
                                                   "training_eligible": False, "episode": episode}) + "\n"
                        write_bounded(raw, raw_line, output)
                        if len(raw_line.encode("utf-8")) > MAX_EPISODE_JSON_BYTES:
                            row["replay_verified"] = False
                            raise ValueError("episode artifact cap reached; complete raw evidence saved, duplicate exports omitted")
                        store.append_episode(run_id, episode)
                        store.update_run(run_id, episode["status"], elapsed=episode["elapsed_seconds"], error=episode["error"])
                        try:
                            row["replay_verified"] = replay(episode)["verified"]
                        except ValueError as error:
                            row["replay_verified"] = False
                            row["replay_error"] = str(error)
                        records, _ = export_records(store, run_id, "traces", "all")
                        for record in records:
                            write_bounded(traces, canonical_json(record) + "\n", output)
                        if row["replay_verified"]:
                            write_bounded(atif, canonical_json(export_episode(episode, run_id=run_id)) + "\n", output)
                        print(canonical_json({key: row[key] for key in ("environment_id", "seed", "passed", "termination", "steps", "usage")}), flush=True)
                        if time.perf_counter() - started >= OVERALL_TIMEOUT:
                            raise TimeoutError("overall experiment deadline reached; handled episode preserved")
        except (TimeoutError, ValueError, RuntimeError) as error:
            fatal_error = f"experiment stopped ({type(error).__name__}): {error}"
        finally:
            await provider.close()
            report["elapsed_seconds"] = time.perf_counter() - started
            report["fatal_error"] = fatal_error
            report["recorded_episodes"] = len(rows)
            report["recorded_request_attempts"] = sum(row["usage"].get("request_attempts", 0) for row in rows)
            report["passes"] = sum(row["passed"] for row in rows)
            report["limitations"] = (
                "Six predeclared synthetic evaluation cases, not a population estimate, leaderboard result or policy comparison. "
                "Every request attempt and bounded response is retained in finalized episodes; not crash durable. "
                "Catalog digest/reported names and exact application bytes do not attest execution, frozen weights, "
                "server-rendered tokens, reproducibility, signed authenticity or trainer eligibility."
            )
            report["artifacts"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                   for path in (output / "evaluation-episodes.jsonl", output / "operator-traces.jsonl", output / "atif.jsonl")}
            report_json = json.dumps(report, indent=2) + "\n"
            lines = ["# Native Tool Evaluation", "", report["limitations"], "",
                     f"Source `{source['git_revision']}`; model `{MODEL}`, predeclared catalog digest `{EXPECTED_MODEL_DIGEST}`.", "",
                     "| World | Seed | Passed | Termination | Steps | Request attempts | Seconds |",
                     "|---|---:|---|---|---:|---:|---:|"]
            for row in rows:
                lines.append(f"| {row['environment_id']} | {row['seed']} | {row['passed']} | {row['termination']} | {row['steps']} | {row['usage'].get('request_attempts', 0)} | {row['elapsed_seconds']:.3f} |")
            lines.extend(["", f"Fatal collection error: `{fatal_error}`.", "",
                          "All data is evaluation-only/operator-only. Unknown usage is absent, not zero. No downloads or paid calls.", ""])
            report_md = "\n".join(lines)
            if len(report_json.encode()) + len(report_md.encode()) > REPORT_RESERVE_BYTES:
                raise ValueError("report exceeds reserved artifact budget; raw evidence retained")
            if artifact_bytes(output) + len(report_json.encode()) + len(report_md.encode()) > MAX_ARTIFACT_BYTES:
                raise ValueError("report would exceed artifact cap; raw evidence retained")
            (output / "report.json").write_text(report_json)
            (output / "report.md").write_text(report_md)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collect", action="store_true", help="Explicitly perform the six predeclared local inference episodes")
    parser.add_argument("--source-revision", required=True, help="Reviewed and committed source revision authorized for this experiment")
    parser.add_argument("--output", type=Path, required=True, help="New immutable experiment directory; existing paths are rejected")
    args = parser.parse_args()
    if not args.collect:
        parser.error("inference is disabled without --collect and an authorized committed --source-revision")
    result = asyncio.run(collect(args.output, args.source_revision))
    raise SystemExit(1 if result["fatal_error"] or not all(row.get("replay_verified", False) for row in result["episodes"]) else 0)
