"""Pure plan or explicitly supervised private local LoRA smoke/final experiment."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import math
import os
import re
import resource
import signal
import subprocess
import sys
import time
from copy import deepcopy
from pathlib import Path

from world_engine.models import Action, RunConfig, canonical_json, digest
from world_engine.providers import Decision, ProviderError, policy_messages
from world_engine.rollout import replay, rollout

HERE = Path(__file__).resolve()
spec = importlib.util.spec_from_file_location("sft_data_stage", HERE.with_name("local_sft_pilot.py"))
data = importlib.util.module_from_spec(spec)
spec.loader.exec_module(data)
SEED, WHOLE_SECONDS, TRAIN_SECONDS, OUTPUT_CAP = 20261011, 2400, 900, 4 * 1024**3
INPUT_TOKENS, NEW_TOKENS, EPISODE_SECONDS = 4096, 128, 60
DATA_REVISION = "a8b95a4df7a39d6e2884048fbf39c49095487bde"
DATA_REPORT_HASH = "8ef491474ca183b6622381db99c466ebcec32e366f809e7644504cbdcbcd1b41"
TRAIN_SCOPE = ("scripts/local_sft_train.py", "tests/test_local_sft_train.py", "docs/local-sft-training-protocol.md")
STAGES = ("source_validation", "data_validation", "tokenizer_validation", "device_initialization", "model_load",
          "base_loss", "base_live", "adapter_setup", "training", "post_training_verification", "adapter_save",
          "final_loss", "final_live", "reload", "source_postcondition", "data_postcondition")
CACHE_POINTS = ("backward_substep", "backward_step", "base_loss", "final_loss", "base_live_episode",
                "final_live_episode", "before_reload")


class TrainingStopped(RuntimeError):
    """Generic private-pilot boundary failure, with original evidence retained."""


def plan(mode="train"):
    if mode not in {"smoke", "train"}:
        raise TrainingStopped("unknown experiment mode")
    protocol = {"id": "private-local-lora-v2", "mode": mode, "seed": SEED,
                "model": "Qwen/Qwen2.5-0.5B-Instruct", "cache_revision": data.CACHE_REVISION,
                "cache_sha256": data.CACHE_HASHES, "template_sha256": data.TEMPLATE_HASH,
                "versions": data.VERSIONS, "device": "mps", "dtype": "float32", "attention": "eager",
                "rank": 8, "alpha": 16, "targets": ["q_proj", "v_proj"], "dropout": 0,
                "learning_rate": 0.0001, "batch_size": 1, "gradient_accumulation": 1 if mode == "smoke" else 4,
                "optimizer_steps": 1 if mode == "smoke" else 32, "optimizer": "adamw_torch",
                "lr_schedule": "constant", "weight_decay": 0, "max_grad_norm": 1,
                "whole_seconds": WHOLE_SECONDS, "training_seconds": TRAIN_SECONDS, "output_cap_bytes": OUTPUT_CAP,
                "max_input_tokens": INPUT_TOKENS, "max_new_tokens": NEW_TOKENS,
                "episode_seconds": EPISODE_SECONDS, "episode_decisions": 20, "decoding": "greedy",
                "generation_cache": True,
                "gradient_checkpointing": True, "checkpoint_use_reentrant": False,
                "mps_allocator_fraction": 0.5, "memory_observations": "sampled RSS peak and MPS allocated/driver bytes",
                "diagnostics_schema": "private-local-lora-diagnostics.v1", "diagnostics_stages": STAGES,
                "cache_maintenance": {"points": CACHE_POINTS, "order": ["deadline_check", "memory_before",
                    "durable_intent", "synchronize", "empty_cache", "memory_after", "durable_result", "deadline_check"],
                    "adaptive": False, "max_training_calls": 1 if mode == "smoke" else 128,
                    "max_phase_calls": 1 if mode == "smoke" else 19},
                "trainer_periodic_evaluation": "disabled", "trainer_periodic_checkpoints": "disabled",
                "trainer_external_reporting": "disabled",
                "heldout_live_tasks": 0 if mode == "smoke" else 8, "base_final_pairs": mode == "train",
                "heldout_loss": "all clean reference heldout decisions that fit exact full context",
                "rights": data.RIGHTS.__dict__, "retry_policy": "none", "fallback": "none",
                "data_revision": DATA_REVISION, "data_report_sha256": DATA_REPORT_HASH,
                "bounds_status": "fixed after stage-one length receipt, before any model outcome",
                "live_context_limit": "4096 input tokens; reject rather than truncate"}
    return {"status": "plan-only", "protocol": protocol, "protocol_sha256": digest(protocol)}


def regular(path):
    if path.is_symlink() or not path.is_file():
        raise TrainingStopped("regular evidence file required")
    return path


def reject_output_symlink_parents(path):
    if any(parent.is_symlink() for parent in path.absolute().parents):
        raise TrainingStopped("output symlink ancestors forbidden")


def source_identity(revision):
    scope = (*data.SOURCE_SCOPE, *TRAIN_SCOPE)
    if type(revision) is not str or not re.fullmatch("[0-9a-f]{40}", revision):
        raise TrainingStopped("reviewed full source revision required")
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=data.ROOT, capture_output=True,
                              text=True, check=True, timeout=5).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all", "--", *scope],
                               cwd=data.ROOT, capture_output=True, text=True, check=True, timeout=5).stdout
        files = subprocess.run(["git", "ls-files", "--", *scope], cwd=data.ROOT, capture_output=True,
                               text=True, check=True, timeout=5).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        raise TrainingStopped("source identity unavailable") from None
    if head != revision or dirty or not files:
        raise TrainingStopped("reviewed clean source required")
    hashes = {}
    for relative in files:
        hashes[relative] = data.sha256(regular(data.ROOT / relative))
        verify_blob(revision, relative, hashes[relative])
    return {"revision": revision, "files_sha256": hashes, "scope_clean": True}


def verify_blob(revision, relative, expected):
    if (not re.fullmatch("[0-9a-f]{40}", revision) or Path(relative).is_absolute()
            or ".." in Path(relative).parts or not re.fullmatch("[0-9a-f]{64}", expected)):
        raise TrainingStopped("source manifest malformed")
    try:
        result = subprocess.run(["git", "show", f"{revision}:{relative}"], cwd=data.ROOT,
                                capture_output=True, check=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        raise TrainingStopped("pinned source bytes unavailable") from None
    if data.hashlib.sha256(result.stdout).hexdigest() != expected:
        raise TrainingStopped("pinned source manifest differs")


def read_rows(path):
    return [json.loads(line) for line in regular(path).read_text().splitlines() if line.strip()]


def load_dataset(directory, report_hash):
    directory = Path(directory)
    report_path = regular(directory / "report.json")
    if report_hash != DATA_REPORT_HASH or data.sha256(report_path) != report_hash:
        raise TrainingStopped("exact reviewed data report required")
    report = json.loads(report_path.read_text())
    if (report.get("status") != "completed" or report.get("training_ready") is not True
            or report.get("protocol_sha256") != digest(data.protocol())
            or report.get("source_after") != report.get("source")
            or report["source"]["revision"] != DATA_REVISION):
        raise TrainingStopped("complete unchanged reviewed data stage required")
    for relative, expected in report["source"]["files_sha256"].items():
        verify_blob(report["source"]["revision"], relative, expected)
    manifest = report["files"]
    if {path.name for path in directory.iterdir()} != {*manifest, "report.json"}:
        raise TrainingStopped("data evidence inventory differs")
    total = report_path.stat().st_size
    for name, metadata in manifest.items():
        if Path(name).name != name:
            raise TrainingStopped("data artifact name malformed")
        path = regular(directory / name)
        total += path.stat().st_size
        if metadata != {"bytes": path.stat().st_size, "sha256": data.sha256(path)}:
            raise TrainingStopped("original data artifact differs")
    if total > data.CAP:
        raise TrainingStopped("data evidence exceeds fixed bound")
    episodes = read_rows(directory / "operator-episodes.jsonl")
    public = read_rows(directory / "public-decisions.jsonl")
    encoded = read_rows(directory / "masked-decisions.jsonl")
    expected_slots = [(world, seed) for world in data.WORLDS for seed in data.SEEDS]
    if len(episodes) != len(expected_slots) or len(report["rows"]) != len(expected_slots):
        raise TrainingStopped("data cohort incomplete")
    for wrapper, slot, row in zip(episodes, expected_slots, report["rows"], strict=True):
        episode = wrapper["episode"]
        if (wrapper.get("operator_evidence_only") is not True or wrapper.get("training_eligible") is not False
                or (row["world"], row["seed"]) != slot
                or (episode["provenance"]["environment_id"], episode["seed"]) != slot
                or episode["provenance"].get("evaluation_only") is not False
                or episode["provenance"].get("provider_id") != "scripted-oracle"
                or episode["provenance"].get("provider_class") != "world_engine.providers.ScriptedProvider"
                or episode.get("passed") is not True or episode.get("invalid_actions") != 0
                or replay(episode).get("verified") is not True):
            raise TrainingStopped("data episode identity/replay differs")
    expected_public = [example for wrapper in episodes
                       for example in data.select_episode(wrapper["episode"], data.RIGHTS).examples]
    if canonical_json(public) != canonical_json(expected_public):
        raise TrainingStopped("public supervision differs from replayed original train decisions")
    heldout_tasks = []
    for world in data.WORLDS:
        candidates = [wrapper["episode"] for wrapper in episodes if wrapper["episode"]["split"] in {"validation", "test"}
                      and wrapper["episode"]["provenance"]["environment_id"] == world]
        heldout_tasks.extend({"world": world, "seed": episode["seed"], "split": episode["split"],
                              "scenario_id": episode["scenario_id"]} for episode in candidates[:4])
    if report["heldout_live_evaluation"] != heldout_tasks or len(heldout_tasks) != 8:
        raise TrainingStopped("fixed heldout task selection differs")
    if len(encoded) != report["counts"]["tokenized"] or len(encoded) < 32:
        raise TrainingStopped("tokenized data counts differ")
    return report, episodes, public, encoded


def evaluation_mask(step, tokenizer):
    """Evaluation-only labels; never emitted as training examples or relabeled train."""
    messages = step["policy_input"]
    if (not isinstance(messages, list) or len(messages) != 2
            or [message.get("role") for message in messages] != ["system", "user"]
            or any(set(message) != {"role", "content"} or type(message["content"]) is not str for message in messages)):
        raise TrainingStopped("heldout public context malformed")
    assistant = {"role": "assistant", "content": canonical_json(Action.model_validate(step["action"]).model_dump())}
    prefix = tokenizer.apply_chat_template(deepcopy(messages), tokenize=True, add_generation_prompt=True)
    full = tokenizer.apply_chat_template(deepcopy(messages) + [assistant],
                                        tokenize=True, add_generation_prompt=False)
    if (not isinstance(prefix, list) or not isinstance(full, list) or not prefix
            or any(type(token) is not int or token < 0 for token in [*prefix, *full])
            or len(full) <= len(prefix) or full[:len(prefix)] != prefix
            or tokenizer.eos_token_id not in full[len(prefix):]):
        raise TrainingStopped("heldout exact prefix differs")
    if len(full) > INPUT_TOKENS:
        return None
    return {"input_ids": full, "attention_mask": [1] * len(full),
            "labels": [-100] * len(prefix) + full[len(prefix):], "evaluation_only": True}


class Journal:
    def __init__(self, output):
        self.output = output
        self.started = time.monotonic()

    def check(self):
        if time.monotonic() - self.started > WHOLE_SECONDS:
            raise TrainingStopped("whole pilot deadline reached")
        if sum(path.stat().st_size for path in self.output.rglob("*") if path.is_file()) > OUTPUT_CAP - 1024**2:
            raise TrainingStopped("checkpoint output budget reached")

    def write(self, name, value):
        content = (canonical_json(value) + "\n").encode()
        if len(content) > 16 * 1024**2:
            raise TrainingStopped("single evidence record exceeds bound")
        self.check()
        if sum(path.stat().st_size for path in self.output.rglob("*") if path.is_file()) + len(content) > OUTPUT_CAP - 1024**2:
            raise TrainingStopped("next evidence record exceeds reserved output bound")
        with (self.output / name).open("ab") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())


def validate_token_rows(public, encoded, tokenizer):
    keyed = {}
    for example in public:
        key = example["provenance"]["episode_id"], example["provenance"]["step_index"]
        if key in keyed:
            raise TrainingStopped("duplicate public decision")
        keyed[key] = example
    for row in encoded:
        key = row["provenance"]["episode_id"], row["provenance"]["step_index"]
        example = keyed.pop(key, None)
        if example is None or data.encode_example(example, tokenizer, max_tokens=INPUT_TOKENS) != row:
            raise TrainingStopped("exact token/label evidence differs")
    for example in keyed.values():
        try:
            data.encode_example(example, tokenizer, max_tokens=INPUT_TOKENS)
        except data.TrainingDataError as error:
            if str(error) == "oversize_decision":
                continue
        raise TrainingStopped("unexplained discarded training decision")


def tensors(row, torch):
    return {key: torch.tensor([row[key]], device="mps", dtype=torch.long)
            for key in ("input_ids", "attention_mask", "labels")}


def memory_sample(torch):
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {"rss_peak_bytes": int(usage.ru_maxrss) * (1 if sys.platform == "darwin" else 1024),
            "mps_allocated_bytes": torch.mps.current_allocated_memory(),
            "mps_driver_bytes": torch.mps.driver_allocated_memory(),
            "mps_recommended_max_bytes": torch.mps.recommended_max_memory(),
            "limitation": "observed samples and process RSS peak; not a whole-host memory quota"}


def failure_category(error, torch=None):
    if isinstance(error, TrainingStopped):
        return "training_guard"
    if isinstance(error, MemoryError):
        return "python_memory"
    oom = getattr(torch, "OutOfMemoryError", None)
    if isinstance(oom, type) and isinstance(error, oom):
        return "torch_out_of_memory"
    for kind, label in ((RuntimeError, "runtime_error"), (ValueError, "value_error"),
                        (TypeError, "type_error"), (OSError, "os_error")):
        if isinstance(error, kind):
            return label
    return "other_exception"


class Diagnostics:
    def __init__(self, report, journal):
        self.report, self.journal = report, journal
        self.stage, self.completed_steps, self.collated_batches, self.torch = "source_validation", 0, 0, None

    def mark(self, stage):
        if stage not in STAGES:
            raise TrainingStopped("unknown diagnostics stage")
        self.stage = stage
        self.journal.write("stages.jsonl", self.snapshot())

    def snapshot(self):
        return {"stage": self.stage, "completed_optimizer_steps": self.completed_steps,
                "collated_batches": self.collated_batches}

    def failed(self, error):
        failure = {**self.snapshot(), "category": failure_category(error, self.torch)}
        if "failure" in self.report:
            self.report.setdefault("postcondition_failures", []).append(failure)
            return
        self.report["failure"] = failure
        # Memory diagnostics are best effort and must never replace the first failure.
        if self.torch is None:
            failure["memory"] = {"status": "not_initialized"}
        else:
            try:
                failure["memory"] = {"status": "recorded", "sample": memory_sample(self.torch)}
            except Exception:
                failure["memory"] = {"status": "unavailable"}


def maintain_cache(torch, journal, point):
    if point not in CACHE_POINTS:
        raise TrainingStopped("unknown cache maintenance point")
    journal.check()
    before = memory_sample(torch)
    journal.write("cache-maintenance.jsonl", {"kind": "intent", "point": point, "before": before})
    torch.mps.synchronize()
    torch.mps.empty_cache()
    after = memory_sample(torch)
    journal.write("cache-maintenance.jsonl", {"kind": "result", "point": point, "after": after})
    journal.check()


def loss_report(model, rows, torch, journal):
    model.eval()
    total, count = 0.0, 0
    with torch.no_grad():
        for row in rows:
            journal.check()
            value = float(model(**tensors(row, torch)).loss.item())
            if not math.isfinite(value):
                raise TrainingStopped("nonfinite heldout loss")
            tokens = sum(token != -100 for token in row["labels"])
            total += value * tokens
            count += tokens
    return {"decisions": len(rows), "action_tokens": count,
            "action_token_weighted_loss": total / count if count else None}


def frozen_base_hash(model):
    value = data.hashlib.sha256()
    for name, parameter in model.named_parameters():
        if "lora_" not in name:
            if parameter.requires_grad:
                raise TrainingStopped("base parameter unexpectedly trainable")
            value.update(name.encode())
            value.update(str(tuple(parameter.shape)).encode())
            value.update(parameter.detach().cpu().contiguous().numpy().tobytes())
    return value.hexdigest()


class LocalPolicy:
    """Greedy cached checkpoint only; external calls and sampled-policy RL are absent."""
    def __init__(self, model, tokenizer, torch, journal, phase, task):
        self.network, self.tokenizer, self.torch, self.journal = model, tokenizer, torch, journal
        self.model = f"cached-Qwen2.5-0.5B-Instruct:{phase}"
        self.phase = phase
        self.task = task
        self.weights = {"base_weights_sha256": data.CACHE_HASHES["model.safetensors"],
                        "adapter_sha256": data.sha256(journal.output / "adapter/adapter_model.safetensors")
                        if phase == "final" else None}
        self.calls = 0

    async def decide(self, observation, history):
        self.journal.check()
        messages = policy_messages(observation, history)
        ids = self.tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True)
        if len(ids) > INPUT_TOKENS:
            raise ProviderError("live public context exceeds fixed token budget")
        self.calls += 1
        identity = {"phase": self.phase, "task": self.task, "weights": self.weights,
                    "call": self.calls, "messages": messages, "input_ids": ids}
        self.journal.write("live-decisions.jsonl", {**identity, "kind": "intent"})
        self.network.eval()
        with self.torch.no_grad():
            output = self.network.generate(input_ids=self.torch.tensor([ids], device="mps"),
                                         max_new_tokens=NEW_TOKENS, do_sample=False,
                                         use_cache=True,
                                         pad_token_id=self.tokenizer.pad_token_id,
                                         eos_token_id=self.tokenizer.eos_token_id)
        generated = output[0, len(ids):].tolist()
        reply = self.tokenizer.decode(generated, skip_special_tokens=True)
        self.journal.write("live-decisions.jsonl", {**identity, "kind": "result",
                                                   "generated_ids": generated, "reply": reply})
        try:
            action = Action.model_validate(json.loads(reply))
        except (ValueError, TypeError):
            raise ProviderError("local checkpoint returned invalid JSON action") from None
        return Decision(action, {"input_tokens": len(ids), "output_tokens": len(generated)})


async def live_evaluate(model, tokenizer, torch, rows, journal, phase):
    for row in rows:
        task = row["task"]
        journal.check()
        row["status"] = "attempted"
        config = RunConfig(environment_id=task["world"], seed=task["seed"], provider_id="scripted-oracle",
                           evaluation_only=True, max_steps=20, timeout_seconds=EPISODE_SECONDS, concurrency=1)
        provider = LocalPolicy(model, tokenizer, torch, journal, phase, task)
        episode = await rollout(config, 0, provider)
        journal.write("live-episodes.jsonl", {"phase": phase, "task": task, "episode": episode,
                                             "training_eligible": False})
        row.update(status=episode["status"], passed=episode["passed"], reward=episode["reward"],
                   steps=episode["steps"], invalid_actions=episode["invalid_actions"],
                   termination=episode["termination"], replay_verified=replay(episode)["verified"])
        maintain_cache(torch, journal, f"{phase}_live_episode")
    return rows


def execute(output, revision, dataset, report_hash, mode, confirmed):
    reject_output_symlink_parents(output)
    protocol = plan(mode)
    if confirmed != protocol["protocol_sha256"]:
        raise TrainingStopped("reviewed protocol digest confirmation required")
    expected_intent = {"source_revision": revision, "dataset": str(dataset), "data_report_sha256": report_hash,
                       "mode": mode, "protocol_sha256": confirmed}
    if (not output.is_dir() or output.is_symlink()
            or {path.name for path in output.iterdir()} != {"execution.log", "supervisor-intent.json"}
            or json.loads(regular(output / "supervisor-intent.json").read_text()) != expected_intent):
        raise TrainingStopped("fresh supervisor-owned output/intent required")
    journal = Journal(output)
    report = {**protocol, "status": "started",
              "data_report_sha256": report_hash, "base_live": [], "final_live": [], "training_completed": False}
    diagnostics = Diagnostics(report, journal)
    try:
        diagnostics.mark("source_validation")
        report["source"] = source_identity(revision)
        with data.offline():
            diagnostics.mark("data_validation")
            stage, raw, public, encoded = load_dataset(dataset, report_hash)
            diagnostics.mark("tokenizer_validation")
            data.cache_identity()
            tokenizer = data.load_tokenizer()
            validate_token_rows(public, encoded, tokenizer)
            if mode == "train":
                for phase in ("base_live", "final_live"):
                    report[phase] = [{"task": task, "status": "unattempted"}
                                     for task in stage["heldout_live_evaluation"]]
            diagnostics.mark("device_initialization")
            import torch
            from peft import LoraConfig, PeftModel, get_peft_model, get_peft_model_state_dict
            from transformers import (
                AutoModelForCausalLM,
                Trainer,
                TrainerCallback,
                TrainingArguments,
                set_seed,
            )

            diagnostics.torch = torch
            if os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK", "0") != "0":
                raise TrainingStopped("MPS operation fallback forbidden")
            if not torch.backends.mps.is_built() or not torch.backends.mps.is_available():
                raise TrainingStopped("required MPS device unavailable; no fallback")
            torch.mps.set_per_process_memory_fraction(0.5)
            report["memory_before_model"] = memory_sample(torch)
            set_seed(SEED)
            diagnostics.mark("model_load")
            model = AutoModelForCausalLM.from_pretrained(data.CACHE_PATH, local_files_only=True,
                                                       trust_remote_code=False, dtype=torch.float32,
                                                       attn_implementation="eager").to("mps")
            if model.device.type != "mps":
                raise TrainingStopped("model is not on required MPS device")
            model.config.use_cache = False
            heldout, skipped = [], 0
            for wrapper in raw:
                episode = wrapper["episode"]
                if episode["split"] in {"validation", "test"}:
                    for step in episode["trace"]:
                        masked = evaluation_mask(step, tokenizer)
                        if masked is None:
                            skipped += 1
                        else:
                            heldout.append(masked)
            report["heldout_loss_counts"] = {"eligible_decisions": len(heldout), "oversize_decisions": skipped}
            if mode == "train":
                diagnostics.mark("base_loss")
                report["base_loss"] = loss_report(model, heldout, torch, journal)
                maintain_cache(torch, journal, "base_loss")
                diagnostics.mark("base_live")
                asyncio.run(live_evaluate(model, tokenizer, torch, report["base_live"], journal, "base"))
            diagnostics.mark("adapter_setup")
            model = get_peft_model(model, LoraConfig(r=8, lora_alpha=16, target_modules=["q_proj", "v_proj"],
                                                     lora_dropout=0, bias="none", task_type="CAUSAL_LM"))
            if any(parameter.requires_grad and "lora_" not in name for name, parameter in model.named_parameters()):
                raise TrainingStopped("unexpected trainable base parameter")
            initial = {name: value.detach().cpu().clone() for name, value in get_peft_model_state_dict(model).items()}
            report["frozen_base_sha256_before"] = frozen_base_hash(model)
            report["trainable_parameters"] = sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad)
            training_started = time.monotonic()
            diagnostics.mark("training")

            class Bounds(TrainerCallback):
                def on_substep_end(self, args, state, control, **kwargs):
                    self.after_backward(state, "backward_substep")

                def on_step_end(self, args, state, control, **kwargs):
                    diagnostics.completed_steps = state.global_step
                    self.after_backward(state, "backward_step")

                def after_backward(self, state, point):
                    journal.check()
                    journal.write("memory.jsonl", {"step": state.global_step, **memory_sample(torch)})
                    if time.monotonic() - training_started > TRAIN_SECONDS:
                        raise TrainingStopped("training deadline reached")
                    maintain_cache(torch, journal, point)
                    if time.monotonic() - training_started > TRAIN_SECONDS:
                        raise TrainingStopped("training deadline reached")

                def on_log(self, args, state, control, logs=None, **kwargs):
                    numeric = {key: value for key, value in (logs or {}).items() if type(value) in (int, float)}
                    if any(not math.isfinite(value) for value in numeric.values()):
                        raise TrainingStopped("nonfinite training metric")
                    journal.write("training-log.jsonl", {"step": state.global_step, "metrics": numeric})

            args = TrainingArguments(output_dir=str(output / "trainer"), max_steps=protocol["protocol"]["optimizer_steps"],
                                     per_device_train_batch_size=1,
                                     gradient_accumulation_steps=protocol["protocol"]["gradient_accumulation"],
                                     learning_rate=0.0001, seed=SEED, data_seed=SEED, optim="adamw_torch",
                                     lr_scheduler_type="constant", weight_decay=0, max_grad_norm=1,
                                     save_strategy="no", logging_steps=1, report_to=[], dataloader_pin_memory=False,
                                     dataloader_num_workers=0, remove_unused_columns=False, disable_tqdm=True,
                                     eval_strategy="no", eval_on_start=False, load_best_model_at_end=False,
                                     gradient_checkpointing=True, gradient_checkpointing_kwargs={"use_reentrant": False},
                                     do_eval=False, bf16=False, fp16=False)
            if args.device.type != "mps":
                raise TrainingStopped("Trainer is not on required MPS device")
            samples = [{**{key: row[key] for key in ("input_ids", "attention_mask", "labels")}, "decision_index": index}
                       for index, row in enumerate(encoded[:1] if mode == "smoke" else encoded)]
            collated = 0

            def collate(batch):
                nonlocal collated
                if len(batch) != 1:
                    raise TrainingStopped("fixed batch size differs")
                collated += 1
                diagnostics.collated_batches = collated
                journal.write("training-samples.jsonl", {"collated_batch": collated,
                                                         "decision_index": batch[0]["decision_index"],
                                                         "provenance": encoded[batch[0]["decision_index"]]["provenance"]})
                return {key: torch.tensor([batch[0][key]], dtype=torch.long)
                        for key in ("input_ids", "attention_mask", "labels")}

            trainer = Trainer(model=model, args=args, train_dataset=samples, data_collator=collate, callbacks=[Bounds()])
            result = trainer.train()
            diagnostics.mark("post_training_verification")
            if trainer.state.global_step != protocol["protocol"]["optimizer_steps"] or not math.isfinite(result.training_loss):
                raise TrainingStopped("optimizer step count or loss differs")
            changed = get_peft_model_state_dict(model)
            if not any(not torch.equal(initial[name], value.detach().cpu()) for name, value in changed.items()):
                raise TrainingStopped("adapter did not change")
            report["frozen_base_sha256_after"] = frozen_base_hash(model)
            if report["frozen_base_sha256_after"] != report["frozen_base_sha256_before"]:
                raise TrainingStopped("frozen base parameters changed")
            diagnostics.mark("adapter_save")
            model.save_pretrained(output / "adapter", safe_serialization=True)
            tokenizer.save_pretrained(output / "tokenizer")
            report["training_completed"] = True
            report["optimizer_steps"] = trainer.state.global_step
            report["training_loss"] = result.training_loss
            report["training_seconds"] = time.monotonic() - training_started
            if mode == "train":
                diagnostics.mark("final_loss")
                report["final_loss"] = loss_report(model, heldout, torch, journal)
                maintain_cache(torch, journal, "final_loss")
                diagnostics.mark("final_live")
                asyncio.run(live_evaluate(model, tokenizer, torch, report["final_live"], journal, "final"))
            diagnostics.mark("reload")
            model.eval()
            with torch.no_grad():
                before_reload = model(**tensors(samples[0], torch)).logits[:, -1, :].detach().cpu()
            maintain_cache(torch, journal, "before_reload")
            fresh = AutoModelForCausalLM.from_pretrained(data.CACHE_PATH, local_files_only=True,
                                                        trust_remote_code=False, dtype=torch.float32,
                                                        attn_implementation="eager").to("mps")
            fresh.config.use_cache = False
            loaded = PeftModel.from_pretrained(fresh, output / "adapter", local_files_only=True,
                                              is_trainable=False).to("mps")
            loaded.eval()
            reloaded = get_peft_model_state_dict(loaded)
            if set(changed) != set(reloaded) or any(not torch.equal(changed[name].detach().cpu(), reloaded[name].detach().cpu())
                                                   for name in changed):
                raise TrainingStopped("saved adapter reload differs")
            with torch.no_grad():
                after_reload = loaded(**tensors(samples[0], torch)).logits[:, -1, :].detach().cpu()
            if not torch.allclose(before_reload, after_reload, atol=0.00001, rtol=0.00001):
                raise TrainingStopped("fresh checkpoint reload logits differ")
            report["adapter_reload_exact"] = True
            report["reload_logits_max_abs_difference"] = float((before_reload - after_reload).abs().max().item())
            report["memory_after_reload"] = memory_sample(torch)
            report["installed_packages"] = {package.metadata["Name"]: package.version
                                             for package in data.importlib.metadata.distributions()}
            report["status"] = "completed"
    except Exception as error:
        report["status"] = "stopped"
        report["error"] = "private pilot failed; evidence prefix retained; no fallback or retry"
        diagnostics.failed(error)
    finally:
        diagnostics.stage = "source_postcondition"
        try:
            report["source_after"] = source_identity(revision)
            report["source_unchanged"] = report["source_after"] == report.get("source")
            if not report["source_unchanged"]:
                raise TrainingStopped("source changed during pilot")
            report["source_postcondition"] = "verified"
        except Exception as error:
            report["source_postcondition"] = "failed"
            report["source_unchanged"] = False
            report["status"] = "stopped"
            report["error"] = "private pilot failed; evidence prefix retained; no fallback or retry"
            diagnostics.failed(error)
        diagnostics.stage = "data_postcondition"
        try:
            load_dataset(dataset, report_hash)
            report["original_data_unchanged"] = True
            report["data_postcondition"] = "verified"
        except Exception as error:
            report["original_data_unchanged"] = False
            report["data_postcondition"] = "failed"
            report["status"] = "stopped"
            report["error"] = "private pilot failed; evidence prefix retained; no fallback or retry"
            diagnostics.failed(error)
        report["diagnostics"] = diagnostics.snapshot()
        report["elapsed_seconds"] = time.monotonic() - journal.started
        report["files"] = {str(path.relative_to(output)): {"bytes": path.stat().st_size, "sha256": data.sha256(path)}
                           for path in output.rglob("*") if path.is_file() and path.name != "execution.log"}
        with (output / "report.json").open("x") as file:
            file.write(canonical_json(report) + "\n")
            file.flush()
            os.fsync(file.fileno())
    return report


def supervise(args):
    output = args.output
    reject_output_symlink_parents(output)
    if output.exists() or output.is_symlink():
        raise TrainingStopped("fresh output required before activity")
    if args.confirm_protocol != plan(args.mode)["protocol_sha256"]:
        raise TrainingStopped("explicit reviewed protocol confirmation required")
    source_identity(args.source_revision)
    load_dataset(args.dataset, args.data_report_sha256)
    output.mkdir(parents=True, mode=0o700)
    intent = {"source_revision": args.source_revision, "dataset": str(args.dataset),
              "data_report_sha256": args.data_report_sha256, "mode": args.mode,
              "protocol_sha256": args.confirm_protocol}
    with (output / "supervisor-intent.json").open("x") as file:
        file.write(canonical_json(intent) + "\n")
        file.flush()
        os.fsync(file.fileno())
    command = [sys.executable, str(HERE), "--worker", "--mode", args.mode, "--source-revision", args.source_revision,
               "--dataset", str(args.dataset), "--data-report-sha256", args.data_report_sha256,
               "--output", str(output), "--confirm-protocol", args.confirm_protocol]
    started, reason = time.monotonic(), None
    with (output / "execution.log").open("xb") as log:
        try:
            process = subprocess.Popen(command, stdout=log, stderr=log, start_new_session=True)
        except OSError:
            receipt = {"schema": "private-sft-supervisor.v1", "status": "launch_failed",
                       "error": "worker launch failed; no retry", "elapsed_seconds": time.monotonic() - started}
            with (output / "supervisor.json").open("x") as file:
                file.write(canonical_json(receipt) + "\n")
                file.flush()
                os.fsync(file.fileno())
            return receipt
        try:
            while process.poll() is None:
                if time.monotonic() - started > WHOLE_SECONDS:
                    reason = "whole_deadline"
                elif sum(path.stat().st_size for path in output.rglob("*") if path.is_file()) > OUTPUT_CAP - 1024**2:
                    reason = "output_budget"
                if reason:
                    break
                time.sleep(.2)
        except KeyboardInterrupt:
            reason = "operator_cancelled"
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
    receipt = {"schema": "private-sft-supervisor.v1", "status": reason or ("completed" if process.returncode == 0 else "worker_failed"),
               "elapsed_seconds": time.monotonic() - started, "returncode": process.returncode,
               "limits": "controller process-group deadline; cooperative sampled disk limit, not filesystem quota",
               "files": {str(path.relative_to(output)): {"bytes": path.stat().st_size, "sha256": data.sha256(path)}
                         for path in output.rglob("*") if path.is_file()}}
    with (output / "supervisor.json").open("x") as file:
        file.write(canonical_json(receipt) + "\n")
        file.flush()
        os.fsync(file.fileno())
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("smoke", "train"), default="train")
    parser.add_argument("--collect", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--source-revision")
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--data-report-sha256")
    parser.add_argument("--confirm-protocol")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.collect and not args.worker:
        print(canonical_json(plan(args.mode)))
        return 0
    if any(getattr(args, name) is None for name in ("source_revision", "dataset", "data_report_sha256", "confirm_protocol", "output")):
        parser.error("execution requires reviewed source, dataset/report hash, protocol confirmation and fresh output")
    if args.worker:
        result = execute(args.output, args.source_revision, args.dataset, args.data_report_sha256, args.mode, args.confirm_protocol)
    else:
        previous = signal.getsignal(signal.SIGTERM)

        def interrupted(signum, frame):
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, interrupted)
        try:
            result = supervise(args)
        finally:
            signal.signal(signal.SIGTERM, previous)
    print(canonical_json({"status": result["status"]}))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
