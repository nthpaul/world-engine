import copy
import importlib.util
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

PATH = Path(__file__).resolve().parents[1] / "scripts/local_sft_train.py"
spec = importlib.util.spec_from_file_location("local_sft_train_test", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize("mode", ["smoke", "train"])
def test_pure_plan_no_imports_files_models(monkeypatch, mode):
    for name in ("source_identity", "load_dataset", "supervise", "execute"):
        monkeypatch.setattr(module, name, lambda *args: pytest.fail("plan executed"))
    value = module.plan(mode)
    assert value["status"] == "plan-only"
    protocol = value["protocol"]
    assert protocol["optimizer_steps"] == (1 if mode == "smoke" else 32)
    assert protocol["gradient_accumulation"] == (1 if mode == "smoke" else 4)
    assert protocol["device"] == "mps" and protocol["fallback"] == "none"
    assert protocol["data_report_sha256"] == module.DATA_REPORT_HASH
    assert protocol["max_input_tokens"] == 4096 and protocol["max_new_tokens"] == 128
    assert protocol["episode_seconds"] == 60
    assert value["protocol_sha256"] == module.digest(protocol)


def test_unknown_mode_rejected():
    with pytest.raises(module.TrainingStopped):
        module.plan("unknown")


class Tokenizer:
    eos_token_id = 99
    pad_token_id = 0

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        assert tokenize
        return [1, 2, 3] if add_generation_prompt else [1, 2, 3, 4, 99]


def step():
    return {"policy_input": [{"role": "system", "content": "public rules"},
                             {"role": "user", "content": "public observation"}],
            "action": {"tool": "finish", "args": {}}}


def test_heldout_labels_are_separate_evaluation_only(monkeypatch):
    monkeypatch.setattr(module.data, "encode_example", lambda *args, **kwargs: pytest.fail("training mask reused"))
    masked = module.evaluation_mask(step(), Tokenizer())
    assert masked == {"input_ids": [1, 2, 3, 4, 99], "attention_mask": [1] * 5,
                      "labels": [-100, -100, -100, 4, 99], "evaluation_only": True}
    assert "provenance" not in masked and "split" not in masked


@pytest.mark.parametrize("mode", ["prefix", "eos", "bool", "empty", "oversize"])
def test_heldout_mismatches_and_oversize_never_truncate(monkeypatch, mode):
    class Bad(Tokenizer):
        def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
            if add_generation_prompt:
                return [1, 2, 3]
            return {"prefix": [2, 2, 3, 99], "eos": [1, 2, 3, 4], "bool": [1, 2, True, 99],
                    "empty": [], "oversize": [1, 2, 3] + [99] * 32}[mode]
    monkeypatch.setattr(module, "INPUT_TOKENS", 32)
    if mode == "oversize":
        assert module.evaluation_mask(step(), Bad()) is None
    else:
        with pytest.raises(module.TrainingStopped):
            module.evaluation_mask(step(), Bad())


def test_heldout_tokenizer_mutations_do_not_change_public_evidence():
    class Mutating(Tokenizer):
        def apply_chat_template(self, messages, **kwargs):
            result = super().apply_chat_template(messages, **kwargs)
            messages[0]["content"] = "MUTATED"
            return result
    value = step()
    original = copy.deepcopy(value)
    module.evaluation_mask(value, Mutating())
    assert value == original


@pytest.mark.parametrize("messages", [[], [{"role": "user", "content": "wrong"}],
                                     [{"role": "system", "content": 1}, {"role": "user", "content": "okay"}]])
def test_heldout_context_shape(messages):
    value = step()
    value["policy_input"] = messages
    with pytest.raises(module.TrainingStopped):
        module.evaluation_mask(value, Tokenizer())


def fake_dataset(monkeypatch, tmp_path):
    directory = tmp_path / "data"
    directory.mkdir()
    monkeypatch.setattr(module.data, "WORLDS", ("refund-ops", "access-provisioning"))
    monkeypatch.setattr(module.data, "SEEDS", tuple(range(12)))
    monkeypatch.setattr(module, "verify_blob", lambda *args: None)
    monkeypatch.setattr(module, "replay", lambda episode: {"verified": True})
    raw, public, encoded, rows, heldout = [], [], [], [], []
    for world in module.data.WORLDS:
        for seed in module.data.SEEDS:
            episode = {"id": f"fake-{world}-{seed}", "seed": seed, "scenario_id": f"scenario-{world}-{seed}",
                       "split": "train" if seed < 8 else "test", "passed": True, "invalid_actions": 0,
                       "provenance": {"environment_id": world, "evaluation_only": False,
                                      "provider_id": "scripted-oracle",
                                      "provider_class": "world_engine.providers.ScriptedProvider"}}
            episode["examples"] = [{"provenance": {"episode_id": episode["id"], "step_index": index}}
                                   for index in range(2)] if seed < 8 else []
            raw.append({"episode": episode, "operator_evidence_only": True, "training_eligible": False})
            public.extend(episode["examples"])
            encoded.extend(episode["examples"])
            rows.append({"world": world, "seed": seed})
            if seed >= 8:
                heldout.append({"world": world, "seed": seed, "split": "test", "scenario_id": episode["scenario_id"]})
    monkeypatch.setattr(module.data, "select_episode", lambda episode, rights:
                        SimpleNamespace(examples=episode["examples"]))
    for name, values in (("operator-episodes.jsonl", raw), ("public-decisions.jsonl", public),
                         ("masked-decisions.jsonl", encoded)):
        (directory / name).write_text("\n".join(module.canonical_json(value) for value in values) + "\n")
    source = {"revision": module.DATA_REVISION, "files_sha256": {"src/world_engine/example.py": "a" * 64}}
    report = {"status": "completed", "training_ready": True, "source": source, "source_after": source,
              "protocol_sha256": module.digest(module.data.protocol()), "rows": rows,
              "counts": {"tokenized": len(encoded)}, "heldout_live_evaluation": heldout,
              "files": {path.name: {"bytes": path.stat().st_size, "sha256": module.data.sha256(path)}
                        for path in directory.iterdir()}}
    (directory / "report.json").write_text(module.canonical_json(report))
    monkeypatch.setattr(module, "DATA_REPORT_HASH", module.data.sha256(directory / "report.json"))
    return directory, report


def update_report(monkeypatch, directory, report):
    (directory / "report.json").write_text(module.canonical_json(report))
    monkeypatch.setattr(module, "DATA_REPORT_HASH", module.data.sha256(directory / "report.json"))


def test_dataset_all_original_manifests_slots_and_heldouts_checked(monkeypatch, tmp_path):
    directory, _ = fake_dataset(monkeypatch, tmp_path)
    report, raw, public, encoded = module.load_dataset(directory, module.DATA_REPORT_HASH)
    assert len(raw) == 24 and len(public) == len(encoded) == 32
    assert len(report["heldout_live_evaluation"]) == 8


@pytest.mark.parametrize("mutation", ["report_hash", "artifact_bytes", "extra_file", "source", "counts", "heldouts", "status"])
def test_dataset_mutations_fail_closed(monkeypatch, tmp_path, mutation):
    directory, report = fake_dataset(monkeypatch, tmp_path)
    if mutation == "report_hash":
        with pytest.raises(module.TrainingStopped):
            module.load_dataset(directory, "b" * 64)
        return
    if mutation == "artifact_bytes":
        (directory / "public-decisions.jsonl").write_text("changed")
    elif mutation == "extra_file":
        (directory / "unexpected").write_text("extra")
    elif mutation == "source":
        report["source_after"] = {}
    elif mutation == "counts":
        report["counts"]["tokenized"] += 1
    elif mutation == "heldouts":
        report["heldout_live_evaluation"].reverse()
    else:
        report["status"] = "stopped"
    update_report(monkeypatch, directory, report)
    with pytest.raises(module.TrainingStopped):
        module.load_dataset(directory, module.DATA_REPORT_HASH)


def test_dataset_public_supervision_must_equal_original_replayed_actions(monkeypatch, tmp_path):
    directory, report = fake_dataset(monkeypatch, tmp_path)
    values = module.read_rows(directory / "public-decisions.jsonl")
    values[0]["private_expected"] = "NOT_A_PUBLIC_CONTEXT"
    path = directory / "public-decisions.jsonl"
    path.write_text("\n".join(module.canonical_json(value) for value in values) + "\n")
    report["files"][path.name] = {"bytes": path.stat().st_size, "sha256": module.data.sha256(path)}
    update_report(monkeypatch, directory, report)
    with pytest.raises(module.TrainingStopped, match="public supervision"):
        module.load_dataset(directory, module.DATA_REPORT_HASH)


def test_exact_token_masks_validated_and_unexplained_drops_rejected(monkeypatch):
    example = {"provenance": {"episode_id": "fake", "step_index": 0}}
    encoded = {**example, "labels": [-100, 99]}
    monkeypatch.setattr(module.data, "encode_example", lambda *args, **kwargs: encoded)
    module.validate_token_rows([example], [encoded], object())
    with pytest.raises(module.TrainingStopped):
        module.validate_token_rows([example, example], [encoded], object())
    with pytest.raises(module.TrainingStopped):
        module.validate_token_rows([example], [{**encoded, "labels": [1, 99]}], object())
    with pytest.raises(module.TrainingStopped):
        module.validate_token_rows([example], [], object())


def test_expected_oversize_only_explains_omitted_decision(monkeypatch):
    example = {"provenance": {"episode_id": "fake", "step_index": 0}}

    def reject(*args, **kwargs):
        raise module.data.TrainingDataError("oversize_decision")

    monkeypatch.setattr(module.data, "encode_example", reject)
    module.validate_token_rows([example], [], object())


@pytest.mark.parametrize("kind", ["file", "directory", "symlink", "dangling"])
def test_fresh_output_before_source_data_or_child(monkeypatch, tmp_path, kind):
    output = tmp_path / "output"
    if kind == "file":
        output.write_text("preserve")
    elif kind == "directory":
        output.mkdir()
    else:
        output.symlink_to(tmp_path if kind == "symlink" else tmp_path / "absent")
    monkeypatch.setattr(module, "source_identity", lambda *args: pytest.fail("fresh gate late"))
    with pytest.raises(module.TrainingStopped, match="fresh"):
        module.supervise(SimpleNamespace(output=output))


@pytest.mark.parametrize("depth", [1, 3])
def test_symlink_ancestor_rejected_before_preflight_or_child(monkeypatch, tmp_path, depth):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    output = link.joinpath(*(["nested"] * depth), "new")
    for name in ("source_identity", "load_dataset"):
        monkeypatch.setattr(module, name, lambda *args: pytest.fail("symlink gate too late"))
    monkeypatch.setattr(module.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("child launched"))
    with pytest.raises(module.TrainingStopped, match="symlink ancestors"):
        module.supervise(SimpleNamespace(output=output))
    assert not list(real.iterdir())
    assert link.is_symlink()


def test_worker_symlink_ancestor_rejected_before_intent_or_tensor_import(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    output = link / "new"
    with pytest.raises(module.TrainingStopped, match="symlink ancestors"):
        module.execute(output, "a" * 40, tmp_path / "data", module.DATA_REPORT_HASH, "smoke",
                       module.plan("smoke")["protocol_sha256"])
    assert not list(real.iterdir())


def arguments(tmp_path):
    return SimpleNamespace(output=tmp_path / "new", mode="smoke", source_revision="a" * 40,
                           dataset=tmp_path / "data", data_report_sha256=module.DATA_REPORT_HASH,
                           confirm_protocol=module.plan("smoke")["protocol_sha256"])


def supervisor_mocks(monkeypatch, tmp_path, *, forever=False, cancel=False, launch_fail=False):
    calls = []
    monkeypatch.setattr(module, "source_identity", lambda *args: {"fake_source": True})
    monkeypatch.setattr(module, "load_dataset", lambda *args: ({}, [], [], []))
    monkeypatch.setattr(module.time, "sleep", lambda *args: None)
    class Process:
        pid = 123
        returncode = None

        def __init__(self):
            self.polls = 0

        def poll(self):
            self.polls += 1
            if not forever and self.polls > 1:
                self.returncode = 0
            return self.returncode

        def wait(self, timeout=None):
            self.returncode = -15
            return self.returncode

    process = Process()

    def launch(command, **kwargs):
        calls.append(command)
        assert json.loads((tmp_path / "new/supervisor-intent.json").read_text())["mode"] == "smoke"
        assert kwargs["start_new_session"] is True
        if launch_fail:
            raise OSError("SECRET_ERROR")
        return process

    monkeypatch.setattr(module.subprocess, "Popen", launch)
    kills = []
    monkeypatch.setattr(module.os, "killpg", lambda pid, signal: kills.append((pid, signal)))
    if cancel:
        def cancelled(*args):
            raise KeyboardInterrupt
        monkeypatch.setattr(module.time, "sleep", cancelled)
    return calls, process, kills


def test_supervisor_launch_intent_and_final_receipt(monkeypatch, tmp_path):
    calls, process, kills = supervisor_mocks(monkeypatch, tmp_path)
    args = arguments(tmp_path)
    receipt = module.supervise(args)
    assert receipt["status"] == "completed" and process.returncode == 0 and not kills
    assert len(calls) == 1 and "--worker" in calls[0] and "--mode" in calls[0]
    for name, metadata in receipt["files"].items():
        assert metadata["sha256"] == module.data.sha256(args.output / name)


@pytest.mark.parametrize("stop", ["deadline", "quota", "cancel"])
def test_supervisor_kills_only_owned_process_group(monkeypatch, tmp_path, stop):
    calls, _, kills = supervisor_mocks(monkeypatch, tmp_path, forever=True, cancel=stop == "cancel")
    if stop == "deadline":
        monkeypatch.setattr(module, "WHOLE_SECONDS", -1)
    elif stop == "quota":
        monkeypatch.setattr(module, "OUTPUT_CAP", 1024**2 + 1)
    receipt = module.supervise(arguments(tmp_path))
    assert len(calls) == 1 and kills == [(123, module.signal.SIGTERM)]
    assert receipt["status"] == {"deadline": "whole_deadline", "quota": "output_budget", "cancel": "operator_cancelled"}[stop]
    assert (tmp_path / "new/supervisor.json").is_file()


def test_launch_failure_is_preserved_without_raw_exception(monkeypatch, tmp_path):
    supervisor_mocks(monkeypatch, tmp_path, launch_fail=True)
    result = module.supervise(arguments(tmp_path))
    assert result["status"] == "launch_failed"
    assert "SECRET_ERROR" not in (tmp_path / "new/supervisor.json").read_text()


def test_protocol_confirmation_before_child(monkeypatch, tmp_path):
    args = arguments(tmp_path)
    args.confirm_protocol = "wrong"
    monkeypatch.setattr(module, "source_identity", lambda *args: pytest.fail("protocol gate late"))
    with pytest.raises(module.TrainingStopped, match="confirmation"):
        module.supervise(args)
    assert not args.output.exists()


def test_worker_refuses_unowned_or_reused_output_before_importing_tensor_runtime(tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    with pytest.raises(module.TrainingStopped, match="supervisor-owned"):
        module.execute(output, "a" * 40, tmp_path / "data", module.DATA_REPORT_HASH, "smoke",
                       module.plan("smoke")["protocol_sha256"])


@pytest.mark.parametrize("revision", [None, "main", "a" * 39, "A" * 40, 1])
def test_source_full_revision_before_git(revision):
    with pytest.raises(module.TrainingStopped):
        module.source_identity(revision)


@pytest.mark.parametrize("args", [[], ["--mode", "smoke"]])
def test_main_pure_plan(monkeypatch, capsys, args):
    monkeypatch.setattr("sys.argv", [str(PATH), *args])
    monkeypatch.setattr(module, "supervise", lambda *args: pytest.fail("default ran"))
    assert module.main() == 0
    assert json.loads(capsys.readouterr().out)["status"] == "plan-only"


def test_main_collect_requires_all_gates(monkeypatch):
    monkeypatch.setattr("sys.argv", [str(PATH), "--collect"])
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 2


@pytest.mark.parametrize("reply", ['{"tool":"finish","args":{}}', 'MALFORMED',
                                  '{"tool":"finish","args":{},"reward":1}'])
async def test_local_policy_exact_intent_result_precede_strict_action_validation(reply):
    entries = []
    journal = SimpleNamespace(output=Path("unused"), check=lambda: None,
                              write=lambda name, value: entries.append((name, value)))
    tokenizer = Tokenizer()
    tokenizer.decode = lambda value, **kwargs: reply
    torch = SimpleNamespace(no_grad=nullcontext, tensor=lambda value, **kwargs: value)
    class Output:
        def __getitem__(self, index):
            assert index == (0, slice(3, None))
            return SimpleNamespace(tolist=lambda: [5, 99])
    class Model:
        def eval(self):
            pass

        def generate(self, **kwargs):
            assert len(entries) == 1 and entries[0][1]["kind"] == "intent"
            assert kwargs["use_cache"] is True and kwargs["do_sample"] is False
            assert kwargs["max_new_tokens"] == 128
            return Output()
    task = {"world": "refund-ops", "seed": 42}
    provider = module.LocalPolicy(Model(), tokenizer, torch, journal, "base", task)
    if reply.startswith('{"tool":"finish","args":{}}'):
        result = await provider.decide({"public": True}, [])
        assert result.action.tool == "finish"
    else:
        with pytest.raises(module.ProviderError):
            await provider.decide({"public": True}, [])
    assert [entry[1]["kind"] for entry in entries] == ["intent", "result"]
    assert entries[1][1]["reply"] == reply and entries[1][1]["generated_ids"] == [5, 99]
    assert entries[0][1]["task"] == task
    assert isinstance(provider.model, str)  # Provenance never serializes a model object.


async def test_live_context_overflow_refused_before_model_execution():
    tokenizer = Tokenizer()
    tokenizer.apply_chat_template = lambda *args, **kwargs: [1] * 4097
    journal = SimpleNamespace(output=Path("unused"), check=lambda: None,
                              write=lambda *args: pytest.fail("oversize intent"))
    provider = module.LocalPolicy(None, tokenizer, None, journal, "base", {"world": "refund-ops", "seed": 42})
    with pytest.raises(module.ProviderError, match="token budget"):
        await provider.decide({}, [])
    assert provider.calls == 0


async def test_live_outcome_slots_keep_complete_failed_and_unattempted_prefix(monkeypatch):
    rows = [{"task": {"world": "refund-ops", "seed": seed}, "status": "unattempted"} for seed in range(3)]
    checks, raw = [], []
    def check():
        checks.append(True)
        if len(checks) == 3:
            raise module.TrainingStopped("deadline")
    journal = SimpleNamespace(output=Path("unused"), check=check, write=lambda *args: raw.append(args))
    async def returned(config, index, provider):
        assert config.evaluation_only is True and config.timeout_seconds == 60 and config.max_steps == 20
        return {"status": "failed" if config.seed else "completed", "passed": not config.seed,
                "reward": 0 if config.seed else 1, "steps": 1, "invalid_actions": 0,
                "termination": "provider_error" if config.seed else "finished"}
    monkeypatch.setattr(module, "rollout", returned)
    monkeypatch.setattr(module, "replay", lambda episode: {"verified": True})
    with pytest.raises(module.TrainingStopped):
        await module.live_evaluate(None, Tokenizer(), None, rows, journal, "base")
    assert [row["status"] for row in rows] == ["completed", "failed", "unattempted"]
    assert len(raw) == 2 and all(record[1]["training_eligible"] is False for record in raw)


def test_frozen_base_requires_nontrainable_and_detects_bytes():
    class Parameter:
        shape = (1,)
        requires_grad = False
        def __init__(self, value):
            self.value = value
        def detach(self):
            return self
        cpu = contiguous = numpy = detach
        def tobytes(self):
            return self.value
    parameter = Parameter(b"first")
    model = SimpleNamespace(named_parameters=lambda: [("base.weight", parameter)])
    first = module.frozen_base_hash(model)
    parameter.value = b"second"
    assert module.frozen_base_hash(model) != first
    parameter.requires_grad = True
    with pytest.raises(module.TrainingStopped):
        module.frozen_base_hash(model)


def test_main_supervisor_restores_sigterm_handler(monkeypatch, tmp_path):
    args = arguments(tmp_path)
    monkeypatch.setattr("sys.argv", [str(PATH), "--collect", "--mode", "smoke", "--source-revision", args.source_revision,
                                  "--dataset", str(args.dataset), "--data-report-sha256", args.data_report_sha256,
                                  "--output", str(args.output), "--confirm-protocol", args.confirm_protocol])
    previous = module.signal.getsignal(module.signal.SIGTERM)
    def execute(args):
        handler = module.signal.getsignal(module.signal.SIGTERM)
        assert handler != previous
        with pytest.raises(KeyboardInterrupt):
            handler(module.signal.SIGTERM, None)
        return {"status": "completed"}
    monkeypatch.setattr(module, "supervise", execute)
    assert module.main() == 0
    assert module.signal.getsignal(module.signal.SIGTERM) == previous


def fake_smoke_runtime(monkeypatch, tmp_path, *, defect=None):
    """Explicit fakes prove orchestration only; they perform no tensor work."""
    output = tmp_path / "smoke"
    output.mkdir()
    (output / "execution.log").write_text("")
    confirmed = module.plan("smoke")["protocol_sha256"]
    dataset = tmp_path / "dataset"
    intent = {"source_revision": "a" * 40, "dataset": str(dataset), "data_report_sha256": module.DATA_REPORT_HASH,
              "mode": "smoke", "protocol_sha256": confirmed}
    (output / "supervisor-intent.json").write_text(module.canonical_json(intent))
    sample = {"input_ids": [1, 2, 3, 4, 99], "attention_mask": [1] * 5,
              "labels": [-100, -100, -100, 4, 99], "provenance": {"episode_id": "fake"}}
    monkeypatch.setattr(module, "source_identity", lambda revision: {"revision": revision})
    monkeypatch.setattr(module, "load_dataset", lambda *args: ({"heldout_live_evaluation": []}, [], [], [sample]))
    monkeypatch.setattr(module, "validate_token_rows", lambda *args: None)
    monkeypatch.setattr(module.data, "cache_identity", lambda: {})
    tokenizer = Tokenizer()
    def save_tokenizer(path):
        path.mkdir()
        (path / "tokenizer.json").write_text("explicit fake tokenizer")
    tokenizer.save_pretrained = save_tokenizer
    monkeypatch.setattr(module.data, "load_tokenizer", lambda: tokenizer)

    class Tensor:
        shape = (1,)
        def __init__(self, value, trainable=False):
            self.value, self.requires_grad = value, trainable
        def detach(self):
            return self
        cpu = contiguous = numpy = abs = max = detach
        def clone(self):
            return Tensor(self.value, self.requires_grad)
        def tobytes(self):
            return module.canonical_json(self.value).encode()
        def numel(self):
            return 1
        def __getitem__(self, key):
            return self
        def __sub__(self, other):
            return Tensor(self.value - other.value)
        def item(self):
            return self.value

    models, args_seen, caps = [], [], []
    class Model:
        def __init__(self):
            self.device = SimpleNamespace(type="mps")
            self.config = SimpleNamespace(use_cache=True)
            self.base, self.adapter = Tensor(1), Tensor(1, True)
        def to(self, device):
            assert device == "mps"
            return self
        def eval(self):
            return self
        def named_parameters(self):
            return [("base.weight", self.base), ("lora_weight", self.adapter)]
        def parameters(self):
            return [self.base, self.adapter]
        def __call__(self, **kwargs):
            return SimpleNamespace(logits=Tensor(1.0), loss=Tensor(.25))
        def save_pretrained(self, path, **kwargs):
            assert kwargs == {"safe_serialization": True}
            path.mkdir()
            (path / "adapter_model.safetensors").write_text(module.canonical_json(self.adapter.value))

    def load_model(path, **kwargs):
        assert kwargs["local_files_only"] is True and kwargs["trust_remote_code"] is False
        assert kwargs["attn_implementation"] == "eager" and kwargs["dtype"] == "float32"
        model = Model()
        models.append(model)
        return model

    def load_adapter(fresh, path, **kwargs):
        assert kwargs == {"local_files_only": True, "is_trainable": False}
        fresh.adapter = Tensor(json.loads((path / "adapter_model.safetensors").read_text()))
        if defect == "reload":
            fresh.adapter.value += 1
        return fresh

    class Callback:
        pass

    class Trainer:
        def __init__(self, model, args, train_dataset, data_collator, callbacks):
            self.model, self.args, self.samples = model, args, train_dataset
            self.collator, self.callbacks = data_collator, callbacks
            self.state = SimpleNamespace(global_step=0)
        def train(self):
            assert len(self.samples) == 1
            batch = self.collator(self.samples)
            assert set(batch) == {"input_ids", "attention_mask", "labels"}
            if defect != "unchanged_adapter":
                self.model.adapter.value = 2
            if defect == "base_changed":
                self.model.base.value = 2
            self.state.global_step = 2 if defect == "step_count" else 1
            for callback in self.callbacks:
                callback.on_step_end(self.args, self.state, None)
                callback.on_log(self.args, self.state, None, {"loss": .25})
            return SimpleNamespace(training_loss=float("nan") if defect == "nonfinite" else .25)

    def arguments(**kwargs):
        args_seen.append(kwargs)
        return SimpleNamespace(device=SimpleNamespace(type="mps"), **kwargs)

    torch = SimpleNamespace(float32="float32", long="long", no_grad=nullcontext,
                            tensor=lambda value, **kwargs: Tensor(value), equal=lambda a, b: a.value == b.value,
                            allclose=lambda a, b, **kwargs: a.value == b.value,
                            backends=SimpleNamespace(mps=SimpleNamespace(is_built=lambda: True,
                                                                       is_available=lambda: defect != "no_mps")),
                            mps=SimpleNamespace(set_per_process_memory_fraction=lambda value: caps.append(value),
                                                current_allocated_memory=lambda: 10,
                                                driver_allocated_memory=lambda: 20,
                                                recommended_max_memory=lambda: 100))
    monkeypatch.setitem(__import__("sys").modules, "torch", torch)
    monkeypatch.setitem(__import__("sys").modules, "transformers", SimpleNamespace(
        AutoModelForCausalLM=SimpleNamespace(from_pretrained=load_model), Trainer=Trainer,
        TrainerCallback=Callback, TrainingArguments=arguments, set_seed=lambda seed: None))
    monkeypatch.setitem(__import__("sys").modules, "peft", SimpleNamespace(
        LoraConfig=lambda **kwargs: kwargs, get_peft_model=lambda model, config: model,
        get_peft_model_state_dict=lambda model: {"lora_weight": model.adapter},
        PeftModel=SimpleNamespace(from_pretrained=load_adapter)))
    return output, dataset, confirmed, models, args_seen, caps


def test_explicit_fake_smoke_complete_orchestration_and_resource_contract(monkeypatch, tmp_path):
    output, dataset, confirmed, models, args_seen, caps = fake_smoke_runtime(monkeypatch, tmp_path)
    report = module.execute(output, "a" * 40, dataset, module.DATA_REPORT_HASH, "smoke", confirmed)
    assert report["status"] == "completed" and report["training_completed"]
    assert report["optimizer_steps"] == 1 and report["adapter_reload_exact"]
    assert report["frozen_base_sha256_before"] == report["frozen_base_sha256_after"]
    assert len(models) == 2 and caps == [.5] and report["original_data_unchanged"]
    assert args_seen[0]["save_strategy"] == args_seen[0]["eval_strategy"] == "no"
    assert args_seen[0]["eval_on_start"] is args_seen[0]["load_best_model_at_end"] is False
    assert args_seen[0]["report_to"] == [] and not args_seen[0]["dataloader_pin_memory"]
    assert args_seen[0]["gradient_checkpointing"] is True
    assert args_seen[0]["gradient_checkpointing_kwargs"] == {"use_reentrant": False}
    assert "execution.log" not in report["files"]
    assert json.loads((output / "report.json").read_text())["status"] == "completed"


@pytest.mark.parametrize("defect", ["no_mps", "base_changed", "unchanged_adapter", "step_count", "nonfinite", "reload"])
def test_explicit_fake_smoke_rejects_hardware_training_and_checkpoint_defects(monkeypatch, tmp_path, defect):
    output, dataset, confirmed, models, _, _ = fake_smoke_runtime(monkeypatch, tmp_path, defect=defect)
    report = module.execute(output, "a" * 40, dataset, module.DATA_REPORT_HASH, "smoke", confirmed)
    assert report["status"] == "stopped" and "retry" in report["error"]
    assert report["original_data_unchanged"]
    if defect == "no_mps":
        assert not models and not report["training_completed"]


def test_explicit_fake_smoke_rejects_enabled_mps_cpu_operation_fallback(monkeypatch, tmp_path):
    output, dataset, confirmed, models, _, _ = fake_smoke_runtime(monkeypatch, tmp_path)
    monkeypatch.setenv("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    report = module.execute(output, "a" * 40, dataset, module.DATA_REPORT_HASH, "smoke", confirmed)
    assert report["status"] == "stopped" and not models
