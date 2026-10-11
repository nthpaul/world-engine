"""Plan or collect original private SFT decisions and offline tokenizer evidence.

No model tensors, forward passes, optimizer, inference, or checkpoint are loaded.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import os
import re
import socket
import subprocess
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

from world_engine.models import RunConfig, canonical_json, digest
from world_engine.rollout import rollout
from world_engine.training_data import SourceRights, TrainingDataError, encode_example, select_episode

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SCOPE = ("src/world_engine", "pyproject.toml", "uv.lock", "scripts/local_sft_pilot.py",
                "tests/test_training_data.py", "tests/test_local_sft_pilot.py",
                "docs/local-sft.md", "docs/local-sft-protocol.md")
WORLDS = ("refund-ops", "access-provisioning")
SEEDS = tuple(range(60000, 60064))
CACHE_REVISION = "7ae557604adf67be50417f59c2c2f167def9a775"
CACHE_PATH = Path.home() / ".cache/huggingface/hub/models--Qwen--Qwen2.5-0.5B-Instruct/snapshots" / CACHE_REVISION
CACHE_HASHES = {
    "config.json": "18e18afcaccafade98daf13a54092927904649e1dd4eba8299ab717d5d94ff45",
    "generation_config.json": "e558847a8b4402616f1273797b015104dc266fe4b520056fca88823ba8f8ebe6",
    "merges.txt": "599bab54075088774b1733fde865d5bd747cbcc7a547c5bc12610e874e26f5e3",
    "tokenizer.json": "c0382117ea329cdf097041132f6d735924b697924d6f6fc3945713e96ce87539",
    "tokenizer_config.json": "5b5d4f65d0acd3b2d56a35b56d374a36cbc1c8fa5cf3b3febbbfabf22f359583",
    "vocab.json": "ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910",
    "model.safetensors": "fdf756fa7fcbe7404d5c60e26bff1a0c8b8aa1f72ced49e7dd0210fe288fb7fe",
}
TEMPLATE_HASH = "cd8e9439f0570856fd70470bf8889ebd8b5d1107207f67a5efb46e342330527f"
VERSIONS = {"torch": "2.9.0", "transformers": "4.57.1", "peft": "0.17.1", "accelerate": "1.10.1",
            "tokenizers": "0.22.2", "safetensors": "0.8.0"}
RIGHTS = SourceRights("operator-approved-original-private-pilot-20261011")
CAP, RESERVE, SECONDS, MAX_TOKENS = 256 * 1024**2, 8 * 1024**2, 600, 4096


class PilotStopped(RuntimeError):
    """Safe stop; retain all original records, including rejected decisions."""


def protocol():
    return {"id": "private-original-sft-data-v1", "worlds": WORLDS, "seeds": SEEDS,
            "policy": "scripted-oracle", "evaluation_only": False, "max_steps": 20,
            "episode_seconds": 30, "concurrency": 1, "max_tokens": MAX_TOKENS,
            "artifact_cap_bytes": CAP, "next_episode_reserve_bytes": RESERVE, "overall_seconds": SECONDS,
            "retry_policy": "none", "model": "Qwen/Qwen2.5-0.5B-Instruct", "cache_revision": CACHE_REVISION,
            "cache_sha256": CACHE_HASHES, "template_sha256": TEMPLATE_HASH, "package_versions": VERSIONS,
            "source_rights": RIGHTS.__dict__, "minimum_decisions": 32, "minimum_train_instances_per_world": 8,
            "heldout_evaluation_selection": "first four validation/test seeds per world in fixed order",
            "model_execution": False, "training_execution": False,
            "network": "cooperative Python socket connect/create_connection guard plus HF offline flags; not OS isolation"}


def plan():
    return {"status": "plan-only", "protocol": protocol(), "protocol_sha256": digest(protocol()),
            "planned_episodes": len(WORLDS) * len(SEEDS),
            "limitations": "Private original synthetic supervision only; no checkpoint or transfer claim."
            " Same public rule families, seed holdout only. No validation/test examples enter training."}


def sha256(path):
    value = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(8 * 1024**2), b""):
            value.update(chunk)
    return value.hexdigest()


def source_identity(revision):
    if type(revision) is not str or not re.fullmatch("[0-9a-f]{40}", revision):
        raise PilotStopped("reviewed full source revision required")

    def git(*args):
        try:
            return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                                  check=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            raise PilotStopped("source identity unavailable") from None

    if git("rev-parse", "HEAD") != revision or git("status", "--porcelain", "--untracked-files=all", "--", *SOURCE_SCOPE):
        raise PilotStopped("source scope must be reviewed, committed and clean")
    files = git("ls-files", "--", *SOURCE_SCOPE).splitlines()
    hashes = {}
    for relative in files:
        path = ROOT / relative
        if path.is_symlink() or not path.is_file():
            raise PilotStopped("source scope requires regular files")
        hashes[relative] = sha256(path)
        blob = subprocess.run(["git", "show", f"{revision}:{relative}"], cwd=ROOT, capture_output=True, timeout=5)
        if blob.returncode or hashlib.sha256(blob.stdout).hexdigest() != hashes[relative]:
            raise PilotStopped("source bytes differ from committed revision")
    return {"revision": revision, "files_sha256": hashes, "scope_clean": True,
            "checkout_dirty": bool(git("status", "--porcelain", "--untracked-files=all"))}


def cache_identity():
    if not CACHE_PATH.is_dir() or {path.name for path in CACHE_PATH.iterdir()} != set(CACHE_HASHES):
        raise PilotStopped("exact installed model cache required; downloads forbidden")
    hashes = {name: sha256(CACHE_PATH / name) for name in CACHE_HASHES}
    if hashes != CACHE_HASHES:
        raise PilotStopped("installed model/tokenizer bytes differ")
    return {"revision": CACHE_REVISION, "files_sha256": hashes}


@contextmanager
def offline():
    keys = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY")
    previous = {key: os.environ.get(key) for key in keys}
    for key in keys:
        os.environ[key] = "1"
    connect, create = socket.socket.connect, socket.create_connection

    def blocked(*args, **kwargs):
        raise PilotStopped("network forbidden for offline private data stage")

    socket.socket.connect = socket.create_connection = blocked
    try:
        yield
    finally:
        socket.socket.connect, socket.create_connection = connect, create
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def load_tokenizer():
    if any(importlib.metadata.version(name) != version for name, version in VERSIONS.items()):
        raise PilotStopped("training packages differ from reviewed lock")
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(CACHE_PATH, local_files_only=True, trust_remote_code=False)
    if (hashlib.sha256(tokenizer.chat_template.encode()).hexdigest() != TEMPLATE_HASH
            or tokenizer.eos_token_id != 151645 or tokenizer.pad_token_id != 151643):
        raise PilotStopped("tokenizer/template identity differs")
    return tokenizer


class Output:
    def __init__(self, path):
        self.path, self.bytes = path, 0

    def append(self, name, value):
        content = (canonical_json(value) + "\n").encode()
        if self.bytes + len(content) > CAP - 1024**2:
            raise PilotStopped("output quota reached; final receipt reserve retained")
        with (self.path / name).open("ab") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        self.bytes += len(content)


async def collect(output, revision):
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise PilotStopped("fresh output directory required before activity")
    started = time.monotonic()
    source = source_identity(revision)
    cache = cache_identity()
    output.mkdir(parents=True, mode=0o700)
    writer = Output(output)
    rows = [{"world": world, "seed": seed, "status": "unattempted", "reason": None,
             "decisions": 0, "selected": 0, "tokenized": 0, "rejected_tokens": 0, "raw_persisted": False}
            for world in WORLDS for seed in SEEDS]
    report = {**plan(), "status": "started", "source": source, "cache": cache, "rows": rows,
              "heldout_live_evaluation": [], "training_ready": False}
    try:
        with offline():
            tokenizer = load_tokenizer()
            for row in rows:
                if time.monotonic() - started > SECONDS or writer.bytes + RESERVE > CAP - 1024**2:
                    raise PilotStopped("data-stage time or admission byte reserve reached")
                row["status"] = "attempted"
                episode = await rollout(RunConfig(environment_id=row["world"], seed=row["seed"],
                                        max_steps=20, timeout_seconds=30, concurrency=1, evaluation_only=False), 0)
                # Operator snapshots stay only in private raw evidence, before any selection or token work.
                writer.append("operator-episodes.jsonl", {"slot": dict(row), "episode": episode,
                                                       "training_eligible": False, "operator_evidence_only": True})
                row.update(status="persisted", raw_persisted=True)
                if (not isinstance(episode, dict) or type(episode.get("id")) is not str or not episode["id"]
                        or episode.get("split") not in ("train", "validation", "test")
                        or type(episode.get("steps")) is not int or not 1 <= episode["steps"] <= 20
                        or type(episode.get("scenario_id")) is not str or not episode["scenario_id"]):
                    raise PilotStopped("returned episode header malformed; raw retained")
                row.update(status="persisted", split=episode["split"], decisions=episode["steps"],
                           episode_id=episode["id"], scenario_id=episode["scenario_id"])
                selected = select_episode(episode, RIGHTS)
                row.update(status=selected.status, reason=selected.reason, selected=len(selected.examples))
                if episode["split"] in {"validation", "test"}:
                    heldout = [item for item in report["heldout_live_evaluation"] if item["world"] == row["world"]]
                    if len(heldout) < 4:
                        report["heldout_live_evaluation"].append({"world": row["world"], "seed": row["seed"],
                                                                "split": episode["split"], "scenario_id": episode["scenario_id"]})
                for example in selected.examples:
                    writer.append("public-decisions.jsonl", example)
                    try:
                        encoded = encode_example(example, tokenizer, max_tokens=MAX_TOKENS)
                    except TrainingDataError as error:
                        reason = str(error) if str(error) == "oversize_decision" else "token_boundary_rejected"
                        writer.append("token-rejections.jsonl", {"provenance": example["provenance"], "reason": reason})
                        row["rejected_tokens"] += 1
                        continue
                    writer.append("masked-decisions.jsonl", encoded)
                    row["tokenized"] += 1
                row["status"] = "prepared" if row["tokenized"] else "excluded"
                if row["selected"] and not row["tokenized"]:
                    row["reason"] = "all_decisions_token_rejected"
        report["source_after"] = source_identity(revision)
        if report["source_after"] != source:
            raise PilotStopped("source changed during data collection")
        per_world = Counter(row["world"] for row in rows if row["tokenized"])
        report["training_ready"] = (sum(row["tokenized"] for row in rows) >= 32
                                    and all(per_world[world] >= 8 for world in WORLDS)
                                    and len(report["heldout_live_evaluation"]) == 8)
        report["status"] = "completed" if report["training_ready"] else "insufficient_training_data"
    except (Exception, asyncio.CancelledError) as error:
        report["status"] = "cancelled" if isinstance(error, asyncio.CancelledError) else "stopped"
        report["error"] = "data-stage boundary failure; retained prefix only; no retry or training"
        for row in rows:
            if row["status"] in {"attempted", "persisted", "accepted"}:
                row["status"] = "inconclusive"
                row["reason"] = "data-stage stopped before decision preparation completed"
    finally:
        if "source_after" not in report:
            try:
                report["source_after"] = source_identity(revision)
                report["source_unchanged"] = report["source_after"] == source
            except Exception:
                report["source_unchanged"] = False
                report["status"] = "stopped"
            report["training_ready"] = False
        report["elapsed_seconds"] = time.monotonic() - started
        report["counts"] = {"planned": len(rows), "persisted": sum(row["raw_persisted"] for row in rows),
                            "tokenized": sum(row["tokenized"] for row in rows),
                            "rejected_tokens": sum(row["rejected_tokens"] for row in rows),
                            "heldout_instances": sum(row.get("split") in {"validation", "test"} for row in rows),
                            "heldout_decisions": sum(row["decisions"] for row in rows
                                                     if row.get("split") in {"validation", "test"}),
                            "unattempted": sum(row["status"] == "unattempted" for row in rows)}
        report["files"] = {path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
                           for path in output.iterdir() if path.is_file()}
        content = canonical_json(report).encode() + b"\n"
        if len(content) > 1024**2 or writer.bytes + len(content) > CAP:
            raise PilotStopped("final receipt exceeds reserved bound")
        with (output / "report.json").open("xb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collect", action="store_true")
    parser.add_argument("--source-revision")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.collect and (args.output is None or args.source_revision is None):
        parser.error("collection requires reviewed --source-revision and fresh --output")
    report = asyncio.run(collect(args.output, args.source_revision)) if args.collect else plan()
    print(canonical_json({key: report[key] for key in ("status", "protocol_sha256")}))
    return 0 if report["status"] in {"plan-only", "completed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
