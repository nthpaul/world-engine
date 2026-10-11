import copy
import importlib
import json

import pytest

from world_engine.models import RunConfig, digest
from world_engine.rollout import rollout
from world_engine.training_data import SCHEMA, SourceRights, TrainingDataError, encode_example, select_episode

module = importlib.import_module("world_engine.training_data")
RIGHTS = SourceRights("operator-approved-original-private-pilot-20261011")


@pytest.fixture
async def episode():
    for seed in range(8):
        record = await rollout(RunConfig(environment_id="refund-ops", seed=seed, max_steps=20), 0)
        if record["split"] == "train":
            return record
    raise RuntimeError("fixture did not produce train seed")


class Tokenizer:
    eos_token_id = 99

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        assert tokenize is True
        prefix = [1, 2, 3]
        return prefix if add_generation_prompt else prefix + [4, 5, self.eos_token_id]


def test_select_only_exact_replayed_public_context(episode):
    selected = select_episode(episode, RIGHTS)
    assert selected.status == "accepted" and len(selected.examples) == episode["steps"]
    for example, step in zip(selected.examples, episode["trace"], strict=True):
        assert example["schema"] == SCHEMA
        assert example["messages"][:-1] == step["policy_input"]
        assert json.loads(example["messages"][-1]["content"]) == step["action"]
        assert example["provenance"]["controller_context_hash"] == digest(step["policy_input"])
        assert example["provenance"]["source_rights"]["redistribution_allowed"] is False
        assert not {"initial_snapshot", "final_snapshot", "grader", "checks"} & example.keys()
    selected.examples[0]["messages"][0]["content"] = "detached"
    assert episode["trace"][0]["policy_input"][0]["content"] != "detached"


@pytest.mark.parametrize("world", ["refund-ops", "access-provisioning"])
async def test_reference_worlds_current_replay_selected(world):
    for seed in range(8):
        episode = await rollout(RunConfig(environment_id=world, seed=seed, max_steps=20), 0)
        selected = select_episode(episode, RIGHTS)
        assert selected.status == ("accepted" if episode["split"] == "train" else "excluded")
        if selected.status == "excluded":
            assert selected.reason == "heldout_split" and not selected.examples


@pytest.mark.parametrize(("field", "value", "reason"), [
    ("evaluation_only", True, "evaluation_only"),
    ("evaluation_only", 0, "evaluation_only"),
    ("environment_id", [], "unsupported_world"),
    ("environment_id", "crm-merge", "unsupported_world"),
    ("provider_id", "local", "unsupported_supervision"),
    ("provider_class", "world_engine.ollama_tools.OllamaToolsProvider", "unsupported_supervision"),
    ("provider_protocol", "ollama-tools-ledger-v2", "unsupported_provider_protocol"),
    ("training_eligible", False, "unsupported_provider_protocol"),
    ("provider_record_calls", True, "unsupported_provider_protocol"),
])
def test_exclusions_preserved(episode, field, value, reason):
    episode["provenance"][field] = value
    result = select_episode(episode, RIGHTS)
    assert result.reason == reason and not result.examples


@pytest.mark.parametrize("split", ["validation", "test", None, "TRAIN"])
def test_heldout_exclusion(episode, split):
    episode["split"] = split
    assert select_episode(episode, RIGHTS).reason == "heldout_split"


@pytest.mark.parametrize(("field", "value"), [
    ("passed", 1), ("passed", False), ("status", "cancelled"), ("termination", "max_steps"),
    ("invalid_actions", True), ("invalid_actions", 1),
])
def test_unclean_outcomes_excluded(episode, field, value):
    episode[field] = value
    assert select_episode(episode, RIGHTS).reason == "not_clean_business_success"


def test_replay_mutations_cannot_become_training(episode):
    episode["trace"][0]["policy_input"][1]["content"] = "PRIVATE_EXPECTED_SENTINEL"
    assert select_episode(episode, RIGHTS).reason == "replay_mismatch"


@pytest.mark.parametrize("value", [None, [], {}, {"provenance": []}])
def test_malformed_episode_is_countable_exclusion(value):
    result = select_episode(value, RIGHTS)
    assert result.status == "excluded" and result.reason == "malformed_episode"


@pytest.mark.parametrize("kwargs", [
    {"attestation": ""}, {"attestation": "secret\n"}, {"attestation": 1},
    {"attestation": "okay", "permitted_use": "public"},
    {"attestation": "okay", "redistribution_allowed": 0},
    {"attestation": "okay", "benchmark_imported": True},
])
def test_rights_literal_gate(kwargs):
    with pytest.raises(TrainingDataError):
        SourceRights(**kwargs)


def test_assistant_only_exact_prefix_labels(episode):
    example = select_episode(episode, RIGHTS).examples[0]
    encoded = encode_example(example, Tokenizer())
    assert encoded["input_ids"] == [1, 2, 3, 4, 5, 99]
    assert encoded["attention_mask"] == [1] * 6
    assert encoded["labels"] == [-100, -100, -100, 4, 5, 99]
    assert encoded["prompt_tokens"] == 3 and encoded["action_tokens"] == 3
    assert encoded["tokenized_hash"] == digest(encoded["input_ids"])
    encoded["provenance"]["source_rights"]["attestation"] = "changed"
    assert example["provenance"]["source_rights"]["attestation"] == RIGHTS.attestation


@pytest.mark.parametrize("mode", ["prefix", "empty", "bool", "negative", "no_eos", "oversize"])
def test_tokenizer_mismatch_and_no_truncation(episode, mode):
    class Bad(Tokenizer):
        def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
            result = super().apply_chat_template(messages, tokenize=tokenize,
                                                 add_generation_prompt=add_generation_prompt)
            if not add_generation_prompt:
                return {"prefix": [2, 2, 3, 99], "empty": [], "bool": [True, 99],
                        "negative": [-1, 99], "no_eos": [1, 2, 3, 4],
                        "oversize": [1, 2, 3] + [99] * 40}[mode]
            return result
    example = select_episode(episode, RIGHTS).examples[0]
    with pytest.raises(TrainingDataError):
        encode_example(example, Bad(), max_tokens=32)


@pytest.mark.parametrize("budget", [0, 31, 8193, True, 32.0, "4096"])
def test_strict_token_budget(episode, budget):
    with pytest.raises(TrainingDataError):
        encode_example(select_episode(episode, RIGHTS).examples[0], Tokenizer(), max_tokens=budget)


@pytest.mark.parametrize("mutation", ["private", "context", "heldout", "action", "extra_message", "step_bool"])
def test_encoded_boundary_refuses_private_or_inconsistent_examples(episode, mutation):
    example = copy.deepcopy(select_episode(episode, RIGHTS).examples[0])
    if mutation == "private":
        example["provenance"]["expected"] = "PRIVATE_EXPECTED_SENTINEL"
    elif mutation == "context":
        example["messages"][1]["content"] += "altered"
    elif mutation == "heldout":
        example["provenance"]["split"] = "test"
    elif mutation == "action":
        example["messages"][-1]["content"] = '{"tool":"finish","args":{},"grade":1}'
    elif mutation == "extra_message":
        example["messages"][0]["expected"] = "private"
    else:
        example["provenance"]["step_index"] = True
    with pytest.raises(TrainingDataError) as error:
        encode_example(example, Tokenizer())
    assert "SENTINEL" not in str(error.value)


def test_tokenizer_cannot_mutate_retained_messages(episode):
    class Mutating(Tokenizer):
        def apply_chat_template(self, messages, **kwargs):
            result = super().apply_chat_template(messages, **kwargs)
            messages[0]["content"] = "MUTATED"
            return result
    example = select_episode(episode, RIGHTS).examples[0]
    original = copy.deepcopy(example)
    encode_example(example, Mutating())
    assert example == original
