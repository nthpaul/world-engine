"""Dependency-free, text-only ATIF interchange for replay-verified workflow episodes."""

from __future__ import annotations

import copy

from world_engine.models import JsonObject, canonical_json
from world_engine.rollout import replay

ATIF_VERSION = "ATIF-v1.8"
HARBOR_REVISION = "09f5b964f8e5075f7e52fd08c9994dfc80ad5d24"
HARBOR_SCHEMA_SHA256 = "892a423ee9c710e8067740b36dd15c9de2f0157d05b6c1ea30acc25ff1c4da6c"
HTTP_PROVIDERS = {"local", "openai", "anthropic"}
SCRIPTED_PROVIDERS = {"scripted-oracle", "scripted-baseline"}


def export_episode(episode: JsonObject, *, run_id: str | None = None) -> JsonObject:
    """Export operator interchange, never a curated training batch or Harbor trial result."""
    replay(episode)
    provenance = episode["provenance"]
    evaluation_only = provenance["evaluation_only"]
    if type(evaluation_only) is not bool:
        raise ValueError("evaluation_only must be a recorded boolean")
    provider_id = provenance["provider_id"]
    deterministic = provider_id in SCRIPTED_PROVIDERS
    model = provenance["model"]
    trace = episode["trace"]
    if trace:
        steps = [{"step_id": index + 1, "source": message["role"], "message": message["content"]}
                 for index, message in enumerate(trace[0]["policy_input"])]
    else:
        # No successful decision recorded its input; retain the observation, not an invented model call.
        steps = [{"step_id": 1, "source": "user", "message": canonical_json(episode["initial_observation"]),
                  "extra": {"recorded_observation_only": True}}]
    for recorded in trace:
        action = recorded["action"]
        call_id = f"world-engine-{episode['id']}-{recorded['index']}"
        step: JsonObject = {
            "step_id": len(steps) + 1, "source": "agent", "message": canonical_json(action),
            "tool_calls": [{"tool_call_id": call_id, "function_name": action["tool"],
                            "arguments": copy.deepcopy(action["args"]), "extra": {"id_is_export_derived": True}}],
            "observation": {"results": [{"source_call_id": call_id,
                            "content": canonical_json({"tool_result": recorded["result"],
                                                       "observation": recorded["observation"]})}]},
            "extra": {"world_engine_step_index": recorded["index"],
                      "policy_input": copy.deepcopy(recorded["policy_input"]),
                      "policy_input_scope": "recorded controller context; not a provider transcript attestation",
                      "state_hash": recorded["state_hash"], "elapsed_ms": recorded["elapsed_ms"],
                      "recorded_usage": copy.deepcopy(recorded["usage"])},
        }
        if deterministic:
            step["llm_call_count"] = 0
        else:
            if provider_id in HTTP_PROVIDERS:
                step["llm_call_count"] = 1
            if model is not None:
                step["model_name"] = model
            reported_model = recorded["usage"].get("model")
            if isinstance(reported_model, str) and reported_model:
                step["model_name"] = reported_model
                step["extra"]["reported_model_name"] = reported_model
            step["extra"]["configured_model_name"] = model
            metrics = {}
            for source, target in (("input_tokens", "prompt_tokens"), ("output_tokens", "completion_tokens")):
                if source in recorded["usage"]:
                    value = recorded["usage"][source]
                    if type(value) is not int or value < 0:
                        raise ValueError("Recorded token counts must be nonnegative integers")
                    metrics[target] = value
            if metrics:
                step["metrics"] = metrics
        steps.append(step)
    agent: JsonObject = {
        "name": "world-engine", "version": provenance["policy_version"],
        "tool_definitions": [{"type": "function", "function": {"name": tool["name"],
                             "description": tool["description"], "parameters": copy.deepcopy(tool["args_schema"])}}
                             for tool in episode["initial_observation"]["tools"]],
        "extra": {"provider_id": provider_id, "model_digest": provenance.get("model_digest"),
                  "policy_identity": provenance["policy_identity"], "policy_hash": provenance["policy_hash"]},
    }
    if not deterministic and model is not None:
        agent["model_name"] = model
    final_metrics: JsonObject = {"total_steps": len(steps), "extra": {
        "recorded_decisions": len(trace), "episode_elapsed_seconds": episode["elapsed_seconds"],
        "token_accounting_scope": "recorded successful provider decisions only; failed requests are not captured",
    }}
    for source, target in (("prompt_tokens", "total_prompt_tokens"), ("completion_tokens", "total_completion_tokens")):
        model_steps = [step for step in steps if step["source"] == "agent"]
        if model_steps and all(source in step.get("metrics", {}) for step in model_steps):
            final_metrics[target] = sum(step["metrics"][source] for step in model_steps)
    output: JsonObject = {
        "schema_version": ATIF_VERSION, "trajectory_id": episode["id"], "agent": agent,
        "steps": steps, "final_metrics": final_metrics,
        "notes": "Text-only normalized actions, not raw model response bytes. Tool IDs are export-derived. "
                 "Recorded controller policy input is in extra, not a provider transcript attestation "
                 "or invented chronological context turns. Reported model names do not verify weights. "
                 "Step timestamps, token IDs, logprobs, costs, failed-call details, and reasoning are unavailable. "
                 "This is operator interchange, not a Harbor trial result or a trainer-ready batch.",
        "extra": {
            "evaluation_only": evaluation_only, "training_eligible": False,
            "compatibility": {"schema_version": ATIF_VERSION, "harbor_revision": HARBOR_REVISION,
                              "harbor_schema_sha256": HARBOR_SCHEMA_SHA256, "upstream_license": "Apache-2.0"},
            "world_engine": {"episode_id": episode["id"], "seed": episode["seed"],
                             "scenario_id": episode["scenario_id"], "lineage_id": episode["lineage_id"],
                             "split": episode["split"], "provenance": copy.deepcopy(provenance),
                             "recorded_at": episode["created_at"], "reward": episode["reward"],
                             "passed": episode["passed"], "status": episode["status"],
                             "termination": episode["termination"], "invalid_actions": episode["invalid_actions"],
                             "final_state_hash": episode["final_state_hash"], "error": episode["error"]},
        },
    }
    if run_id is not None:
        output["session_id"] = run_id
    return output
