"""Private-use synthetic SFT selection and exact, assistant-only token preparation.

This does not train a model or make native/browser evaluation traces eligible.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Protocol

from world_engine.exports import json_training_compatible
from world_engine.models import Action, canonical_json, digest
from world_engine.rollout import replay

SCHEMA = "world-engine.private-sft-decision.v1"
MAX_PUBLIC_EXAMPLE_BYTES = 262_144
ALLOWED_WORLDS = frozenset({"refund-ops", "access-provisioning"})
IDENTITY_FIELDS = ("environment_id", "environment_version", "environment_code_hash", "grader_code_hash",
                   "task_hash", "initial_state_hash", "prompt_hash", "lineage_id", "scenario_id")
EXAMPLE_FIELDS = frozenset({*IDENTITY_FIELDS, "episode_id", "step_index", "split", "supervision",
                            "controller_context_hash", "source_rights"})


class TrainingDataError(ValueError):
    """Safe boundary error with no supplied content or private grader state."""


@dataclass(frozen=True)
class SourceRights:
    attestation: str
    origin: str = "original-world-engine-synthetic"
    permitted_use: str = "private-local-sft"
    benchmark_imported: bool = False
    redistribution_allowed: bool = False

    def __post_init__(self):
        if (type(self.attestation) is not str or not self.attestation.strip()
                or len(self.attestation) > 200 or any(not char.isprintable() for char in self.attestation)
                or self.origin != "original-world-engine-synthetic" or self.permitted_use != "private-local-sft"
                or self.benchmark_imported is not False or self.redistribution_allowed is not False):
            raise TrainingDataError("explicit private original-data rights required")


class ChatTokenizer(Protocol):
    eos_token_id: int

    def apply_chat_template(self, messages: list[dict], *, tokenize: bool,
                            add_generation_prompt: bool) -> list[int]: ...


@dataclass(frozen=True)
class EpisodeSelection:
    episode_id: str | None
    status: str
    reason: str | None
    examples: tuple[dict, ...] = ()


def _excluded(episode: object, reason: str) -> EpisodeSelection:
    identity = episode.get("id") if isinstance(episode, dict) else None
    return EpisodeSelection(identity if type(identity) is str else None, "excluded", reason)


def select_episode(episode: dict, rights: SourceRights) -> EpisodeSelection:
    """Select current replay-verified original reference decisions, retaining reasons."""
    if not isinstance(rights, SourceRights):
        raise TrainingDataError("parsed source rights required")
    SourceRights(**asdict(rights))
    if not isinstance(episode, dict) or not isinstance(episode.get("provenance"), dict):
        return _excluded(episode, "malformed_episode")
    provenance = episode["provenance"]
    if type(provenance.get("environment_id")) is not str or provenance["environment_id"] not in ALLOWED_WORLDS:
        return _excluded(episode, "unsupported_world")
    if provenance.get("evaluation_only") is not False:
        return _excluded(episode, "evaluation_only")
    if episode.get("split") != "train":
        return _excluded(episode, "heldout_split")
    if (provenance.get("provider_id") != "scripted-oracle"
            or provenance.get("provider_class") != "world_engine.providers.ScriptedProvider"):
        return _excluded(episode, "unsupported_supervision")
    if "training_eligible" in provenance and provenance["training_eligible"] is not True:
        return _excluded(episode, "unsupported_provider_protocol")
    try:
        compatible = json_training_compatible(episode)
    except (KeyError, TypeError, AttributeError):
        compatible = False
    if not compatible:
        return _excluded(episode, "unsupported_provider_protocol")
    if (episode.get("passed") is not True or episode.get("status") != "completed"
            or episode.get("termination") != "finished" or type(episode.get("invalid_actions")) is not int
            or episode["invalid_actions"] != 0):
        return _excluded(episode, "not_clean_business_success")
    try:
        verified = replay(episode)
    except (ValueError, TypeError, KeyError, RecursionError):
        return _excluded(episode, "replay_mismatch")
    if not isinstance(verified, dict) or verified.get("verified") is not True:
        return _excluded(episode, "replay_mismatch")
    trace = episode.get("trace")
    if not isinstance(trace, list) or not 1 <= len(trace) <= 20:
        return _excluded(episode, "malformed_trace")
    examples = []
    try:
        for step in trace:
            messages = step["policy_input"]
            if (not isinstance(messages, list) or len(messages) != 2
                    or [item.get("role") for item in messages] != ["system", "user"]
                    or any(set(item) != {"role", "content"} or type(item["content"]) is not str for item in messages)):
                raise TrainingDataError("controller context differs")
            action = Action.model_validate(step["action"]).model_dump()
            public = deepcopy(messages) + [{"role": "assistant", "content": canonical_json(action)}]
            if len(canonical_json(public).encode()) > MAX_PUBLIC_EXAMPLE_BYTES:
                return _excluded(episode, "public_example_size")
            identity = {key: provenance[key] for key in IDENTITY_FIELDS}
            examples.append({"schema": SCHEMA, "messages": public,
                             "provenance": {**identity, "episode_id": episode["id"], "step_index": step["index"],
                                            "split": "train", "supervision": "scripted-public-reference",
                                            "controller_context_hash": digest(messages),
                                            "source_rights": asdict(rights)}})
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return _excluded(episode, "malformed_public_decision")
    return EpisodeSelection(episode["id"], "accepted", None, tuple(examples))


def _tokens(value: object) -> list[int]:
    if not isinstance(value, list) or not value or len(value) > 131_072:
        raise TrainingDataError("tokenizer returned invalid token sequence")
    if any(type(token) is not int or token < 0 for token in value):
        raise TrainingDataError("tokenizer returned invalid token identity")
    return value


def encode_example(example: dict, tokenizer: ChatTokenizer, *, max_tokens: int = 4096) -> dict:
    """Mask the exact prompt prefix; never truncate context or target to fit."""
    if type(max_tokens) is not int or not 32 <= max_tokens <= 8192:
        raise TrainingDataError("invalid token budget")
    try:
        if (set(example) != {"schema", "messages", "provenance"} or example["schema"] != SCHEMA
                or set(example["provenance"]) != EXAMPLE_FIELDS
                or example["provenance"]["split"] != "train"
                or example["provenance"]["supervision"] != "scripted-public-reference"
                or type(example["provenance"]["step_index"]) is not int
                or not 0 <= example["provenance"]["step_index"] < 20
                or any(type(example["provenance"][key]) is not str for key in IDENTITY_FIELDS)
                or example["provenance"]["environment_id"] not in ALLOWED_WORLDS):
            raise TrainingDataError("unsupported training example")
        SourceRights(**example["provenance"]["source_rights"])
        messages = example["messages"]
        if (not isinstance(messages, list) or len(messages) != 3
                or [message["role"] for message in messages] != ["system", "user", "assistant"]
                or any(set(message) != {"role", "content"} or type(message["content"]) is not str for message in messages)
                or len(canonical_json(messages).encode()) > MAX_PUBLIC_EXAMPLE_BYTES):
            raise TrainingDataError("unsupported decision messages")
        Action.model_validate(json.loads(messages[-1]["content"]))
        if digest(messages[:-1]) != example["provenance"]["controller_context_hash"]:
            raise TrainingDataError("controller context hash differs")
        prefix = _tokens(tokenizer.apply_chat_template(deepcopy(messages[:-1]), tokenize=True, add_generation_prompt=True))
        full = _tokens(tokenizer.apply_chat_template(deepcopy(messages), tokenize=True, add_generation_prompt=False))
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        raise TrainingDataError("decision token preparation failed") from None
    if len(full) > max_tokens:
        raise TrainingDataError("oversize_decision")
    if len(full) <= len(prefix) or full[:len(prefix)] != prefix:
        raise TrainingDataError("chat template does not preserve exact generation prefix")
    target = full[len(prefix):]
    if type(tokenizer.eos_token_id) is not int or tokenizer.eos_token_id not in target:
        raise TrainingDataError("assistant end delimiter is missing")
    return {"input_ids": full, "attention_mask": [1] * len(full),
            "labels": [-100] * len(prefix) + target,
            "provenance": deepcopy(example["provenance"]), "schema": "world-engine.masked-sft.v1",
            "prompt_tokens": len(prefix), "action_tokens": len(target),
            "messages_hash": digest(messages), "tokenized_hash": digest(full)}
