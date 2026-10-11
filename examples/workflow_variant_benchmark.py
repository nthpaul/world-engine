"""Locked scripted workflow-variant evaluation; no inference or training calls."""

import argparse
import asyncio
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path

from world_engine.models import RunConfig, canonical_json, digest, utc_now
from world_engine.rollout import collection_revision, replay, rollout

CASES = {
    "crm-merge": (
        "standard-ownership", "equal-customer-timestamps", "noncanonical-invoice-copies",
        "noncanonical-copies-equal-timestamps",
    ),
    "refund-ops": (
        "standard-capture", "delivery-day-30", "request-5000-cents", "request-5001-cents",
        "delivery-day-31", "capture-one-cent-less", "chargeback-record", "damage-record-unverified",
    ),
}
PROTOCOL = {
    "name": "workflow-variants-scripted-v3",
    "world_versions": {"crm-merge": "1.1.1", "refund-ops": "1.1.2"},
    "seeds": list(range(32)),
    "policies": ["scripted-oracle", "scripted-baseline"],
    "max_steps": 20,
    "timeout_seconds": 30,
    "concurrency": 1,
    "evaluation_only": True,
    "case_mapping": CASES,
    "inference_calls": 0,
    "interpretation": "Reference implementation coverage only. No learned-model score, training, application parity, or speed comparison.",
}


async def collect(output: Path):
    if output.exists():
        raise SystemExit("Output already exists; choose a new immutable attempt directory.")
    revision = collection_revision()
    collector_path = Path(__file__).resolve()
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=normal", "--",
                             str(collector_path), "tests/test_workflow_variants.py"],
                            cwd=collector_path.parents[1], capture_output=True, text=True, check=True)
    if revision.get("implementation_dirty") is not False or status.stdout.strip():
        raise SystemExit("Commit implementation, collector, and tests before final collection.")
    episodes = []
    rows = []
    for world, cases in CASES.items():
        for seed in PROTOCOL["seeds"]:
            matched = []
            for policy in PROTOCOL["policies"]:
                episode = await rollout(RunConfig(environment_id=world, provider_id=policy, seed=seed,
                                                 episodes=1, max_steps=PROTOCOL["max_steps"],
                                                 timeout_seconds=PROTOCOL["timeout_seconds"],
                                                 concurrency=1, evaluation_only=True), 0)
                assert replay(episode)["verified"]
                assert episode["provenance"]["environment_version"] == PROTOCOL["world_versions"][world]
                assert episode["status"] == "completed" and episode["termination"] == "finished"
                assert episode["passed"] is (policy == "scripted-oracle")
                if policy == "scripted-oracle":
                    assert episode["invalid_actions"] == 0
                matched.append(episode)
                episodes.append(episode)
                rows.append({"episode_id": episode["id"], "environment_id": world, "seed": seed,
                             "case": cases[seed % len(cases)], "policy": policy,
                             "passed": episode["passed"], "reward": episode["reward"],
                             "steps": episode["steps"], "invalid_actions": episode["invalid_actions"],
                             "elapsed_seconds": episode["elapsed_seconds"], "scenario_id": episode["scenario_id"],
                             "lineage_id": episode["lineage_id"], "split": episode["split"],
                             "replay_verified": True, "provenance": episode["provenance"]})
            assert matched[0]["scenario_id"] == matched[1]["scenario_id"]
            assert matched[0]["lineage_id"] == matched[1]["lineage_id"]
            assert matched[0]["split"] == matched[1]["split"]
    summaries = []
    for world, cases in CASES.items():
        for case in cases:
            for policy in PROTOCOL["policies"]:
                selected = [row for row in rows if row["environment_id"] == world and row["case"] == case and row["policy"] == policy]
                summaries.append({"environment_id": world, "case": case, "policy": policy,
                                  "episodes": len(selected), "passed": sum(row["passed"] for row in selected),
                                  "invalid_actions": sum(row["invalid_actions"] for row in selected),
                                  "steps": sum(row["steps"] for row in selected),
                                  "splits": dict(Counter(row["split"] for row in selected))})
    traces = "".join(canonical_json(episode) + "\n" for episode in episodes).encode()
    if len(traces) > 16 * 1024 * 1024:
        raise SystemExit("Trace artifact exceeds the locked 16-MiB collection limit.")
    report = {"created_at": utc_now(), "collection_revision": revision, "protocol": PROTOCOL,
              "protocol_hash": digest(PROTOCOL), "collector_sha256": hashlib.sha256(collector_path.read_bytes()).hexdigest(),
              "episodes": len(rows), "unique_world_seed_tasks": len(rows) // 2,
              "all_replays_verified": True, "inference_calls": 0, "summary": summaries, "rows": rows,
              "trace_sha256": hashlib.sha256(traces).hexdigest(), "trace_bytes": len(traces),
              "limits": ["Synthetic policy fixtures, not public real-application tasks.",
                         "Case labels are receipt-only and absent from policy observations.",
                         "Two policies share each task; they are not independent task samples.",
                         "Seed holdout does not establish withheld-case or workflow-family generalization.",
                         "Timings are diagnostics under uncontrolled background load, not performance claims."]}
    output.mkdir(parents=True)
    (output / "traces.jsonl").write_bytes(traces)
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    lines = ["# Workflow Variant Evaluation", "", PROTOCOL["interpretation"], "",
             f"Source: `{revision['git_revision']}`; implementation scope clean. Protocol: `{report['protocol_hash']}`.",
             "", "64 unique world/seed tasks, 128 matched attempts, concurrency 1, 20-decision/30-second bounds per attempt. All are evaluation-only. No model calls.", "",
             "| World | Case | Policy | Passes | Invalid actions |", "|---|---|---|---:|---:|"]
    for row in summaries:
        lines.append(f"| {row['environment_id']} | {row['case']} | {row['policy']} | {row['passed']}/{row['episodes']} | {row['invalid_actions']} |")
    lines.extend(["", *report["limits"], "", "Full operator traces are evaluation-only. Every attempt replayed under the collected source. New source revisions may require its pinned checkout for replay.", ""])
    (output / "report.md").write_text("\n".join(lines))
    print(json.dumps({"output": str(output), "episodes": len(rows), "replays_verified": len(rows), "trace_bytes": len(traces)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/workflow-variants/hardened"))
    asyncio.run(collect(parser.parse_args().output))
