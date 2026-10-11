from __future__ import annotations

from typing import Literal, get_args

from world_engine.atif import export_episode
from world_engine.models import JsonObject, canonical_json, digest
from world_engine.providers import policy_messages
from world_engine.rollout import replay
from world_engine.store import Store

ExportFormat = Literal["sft", "dpo", "grpo", "traces", "atif"]
Quality = Literal["passed", "all"]


def prompt(episode: JsonObject) -> list[JsonObject]:
    return policy_messages(episode["initial_observation"], [])


def completion(episode: JsonObject) -> list[JsonObject]:
    messages = []
    for index, step in enumerate(episode["trace"]):
        messages.append({"role": "assistant", "content": canonical_json(step["action"])})
        if index != len(episode["trace"]) - 1:
            messages.append({"role": "user", "content": canonical_json({"tool_result": step["result"], "observation": step["observation"]})})
    return messages


def clean_success(episode: JsonObject) -> bool:
    return episode["passed"] and episode["status"] == "completed" and episode["invalid_actions"] == 0


def json_training_compatible(episode: JsonObject) -> bool:
    provenance = episode["provenance"]
    cleanup = episode.get("provider_cleanup")
    return (provenance.get("provider_protocol", "workflow-json-v1") == "workflow-json-v1"
            and provenance.get("provider_class") != "world_engine.ollama_tools.OllamaToolsProvider"
            and provenance.get("provider_record_calls") is not True
            and (cleanup is None or isinstance(cleanup, dict) and cleanup.get("status") == "completed")
            and provenance.get("training_eligible", True) is not False and not episode.get("provider_events"))


def comparable(left: JsonObject, right: JsonObject) -> bool:
    fields = ("environment_id", "environment_version", "grader_version", "environment_code_hash", "grader_code_hash", "task_hash", "prompt_hash", "initial_state_hash")
    return (left["scenario_id"] == right["scenario_id"] and left["split"] == right["split"]
            and all(left["provenance"][key] == right["provenance"][key] for key in fields)
            and left["initial_observation"] == right["initial_observation"])


def export_records(store: Store, run_id: str, format: ExportFormat = "sft", quality: Quality = "passed") -> tuple[list[JsonObject], JsonObject]:
    if format not in get_args(ExportFormat):
        raise ValueError("unsupported export format")
    if quality not in get_args(Quality):
        raise ValueError("unsupported export quality")
    store.get_run(run_id)
    episodes = store.episodes(run_id)
    records: list[JsonObject] = []
    seen: set[str] = set()
    skipped = 0
    excluded = {"heldout_split": 0, "evaluation_only": 0, "quality": 0, "replay_mismatch": 0,
                "insufficient_alternatives": 0, "unsupported_provider_protocol": 0}
    for episode in episodes:
        if format == "atif":
            try:
                record = export_episode(episode, run_id=run_id)
            except ValueError:
                skipped += 1
                excluded["replay_mismatch"] += 1
                continue
            if quality == "passed" and not clean_success(episode):
                skipped += 1
                excluded["quality"] += 1
                continue
            records.append(record)
            continue
        if format != "traces" and not json_training_compatible(episode):
            skipped += 1
            excluded["unsupported_provider_protocol"] += 1
            continue
        if format != "traces" and episode["provenance"].get("evaluation_only"):
            skipped += 1
            excluded["evaluation_only"] += 1
            continue
        if format != "traces" and episode["split"] != "train":
            skipped += 1
            excluded["heldout_split"] += 1
            continue
        if format != "traces":
            try:
                replay(episode)
            except ValueError:
                skipped += 1
                excluded["replay_mismatch"] += 1
                continue
        provenance = {**episode["provenance"], "episode_id": episode["id"], "run_id": run_id, "split": episode["split"]}
        if format in ("sft", "traces"):
            if quality == "passed" and not clean_success(episode):
                skipped += 1
                excluded["quality"] += 1
                continue
            if format == "sft":
                if not episode["trace"]:
                    skipped += 1
                    continue
                for step in episode["trace"]:
                    records.append({"schema": "world-engine.sft.v1", "messages": step["policy_input"] + [
                        {"role": "assistant", "content": canonical_json(step["action"])}],
                                    "provenance": {**provenance, "step_index": step["index"], "policy_input_hash": digest(step["policy_input"])},
                                    "reward": episode["reward"], "passed": episode["passed"], "training_unit": "single-tool-decision"})
            else:
                # Operator detail exposes check descriptions; dataset exports do not copy the grader rubric.
                record = {"schema": "world-engine.trace.v1", "provenance": provenance,
                                "initial_observation": episode["initial_observation"], "trace": episode["trace"],
                                "final_state_hash": episode["final_state_hash"], "reward": episode["reward"],
                                "passed": episode["passed"], "termination": episode["termination"]}
                if "provider_events" in episode:
                    record["provider_events"] = episode["provider_events"]
                    record["provider_recording"] = episode["provider_recording"]
                    record["usage"] = episode["usage"]
                    record["training_eligible"] = False
                if "provider_cleanup" in episode:
                    record["provider_cleanup"] = episode["provider_cleanup"]
                    if episode["provider_cleanup"]["status"] != "completed":
                        record["training_eligible"] = False
                records.append(record)
            continue
        if episode["scenario_id"] in seen:
            continue
        seen.add(episode["scenario_id"])
        candidates = [candidate for candidate in store.candidates(episode["scenario_id"])
                      if comparable(episode, candidate) and candidate["trace"] and candidate["status"] == "completed"
                      and not candidate["provenance"].get("evaluation_only") and json_training_compatible(candidate)]
        unique: dict[str, JsonObject] = {}
        for candidate in candidates:
            try:
                replay(candidate)
            except ValueError:
                continue
            unique.setdefault(digest([step["action"] for step in candidate["trace"]]), candidate)
        candidates = sorted(unique.values(), key=lambda candidate: (candidate["reward"], candidate["id"]))
        if len(candidates) < 2:
            skipped += 1
            excluded["insufficient_alternatives"] += 1
            continue
        if format == "dpo":
            chosen = next((candidate for candidate in reversed(candidates) if clean_success(candidate)), None)
            rejected = candidates[0]
            if chosen is None or chosen["reward"] <= rejected["reward"]:
                skipped += 1
                excluded["insufficient_alternatives"] += 1
                continue
            records.append({"schema": "world-engine.dpo.v1", "prompt": prompt(episode),
                            "chosen": completion(chosen), "rejected": completion(rejected), "provenance": provenance,
                            "chosen_episode_id": chosen["id"], "rejected_episode_id": rejected["id"],
                            "chosen_reward": chosen["reward"], "rejected_reward": rejected["reward"],
                            "chosen_provenance": chosen["provenance"], "rejected_provenance": rejected["provenance"],
                            "completion_kind": "trajectory-messages"})
        else:
            if quality == "passed" and not any(clean_success(candidate) for candidate in candidates):
                skipped += 1
                continue
            records.append({"schema": "world-engine.grouped-rollouts.v1", "prompt": prompt(episode),
                            "provenance": provenance, "candidates": [
                                {"episode_id": candidate["id"], "completion": completion(candidate), "reward": candidate["reward"],
                                 "provider_id": candidate["provenance"]["provider_id"], "policy_hash": candidate["provenance"]["policy_hash"]}
                                for candidate in candidates],
                            "learning_signal": len({candidate["reward"] for candidate in candidates}) > 1,
                            "policy_consistent": len({candidate["provenance"]["policy_hash"] for candidate in candidates}) == 1,
                            "trainable": False,
                            "missing_training_fields": ["sampled_token_ids", "action_loss_mask", "behavior_logprobs", "frozen_policy_checkpoint"]})
    note = ("ATIF is replay-verified operator interchange across all splits and evaluation-only episodes. "
            "Every record is training_eligible=false; this is not a curated training batch or a Harbor trial result."
            if format == "atif" else
            "DPO requires matching successful and lower-reward trajectories. GRPO is raw grouped rollout data, not an on-policy training batch.")
    return records, {"format": format, "quality": quality, "records": len(records), "source_episodes": len(episodes), "skipped": skipped,
                     "excluded": excluded,
                     "note": note}


def jsonl(records: list[JsonObject]) -> str:
    return "".join(canonical_json(record) + "\n" for record in records)
