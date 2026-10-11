import importlib.util
import json
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

PATH = Path(__file__).resolve().parents[1] / "scripts/local_sft_pilot.py"
spec = importlib.util.spec_from_file_location("local_sft_pilot_test", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_plan_is_pure_fixed_private_cohort(monkeypatch, tmp_path):
    for name in ("source_identity", "cache_identity", "load_tokenizer", "rollout"):
        monkeypatch.setattr(module, name, lambda *args: pytest.fail("plan performed activity"))
    before = list(tmp_path.iterdir())
    plan = module.plan()
    assert plan["planned_episodes"] == 128
    assert plan["protocol"]["seeds"] == tuple(range(60000, 60064))
    assert plan["protocol"]["model_execution"] is plan["protocol"]["training_execution"] is False
    assert plan["protocol"]["source_rights"]["redistribution_allowed"] is False
    assert plan["protocol_sha256"] == module.digest(module.protocol())
    assert list(tmp_path.iterdir()) == before


@pytest.mark.parametrize("kind", ["directory", "file", "symlink", "dangling"])
async def test_fresh_output_before_all_activity(monkeypatch, tmp_path, kind):
    output = tmp_path / "existing"
    if kind == "directory":
        output.mkdir()
    elif kind == "file":
        output.write_text("preserve")
    else:
        output.symlink_to(tmp_path if kind == "symlink" else tmp_path / "absent")
    monkeypatch.setattr(module, "source_identity", lambda *args: pytest.fail("preflight too late"))
    with pytest.raises(module.PilotStopped, match="fresh"):
        await module.collect(output, "a" * 40)


def mocked_collect(monkeypatch, *, failure=None, oversize=False, source_changed=False):
    calls = []
    source_calls = []
    monkeypatch.setattr(module, "WORLDS", ("refund-ops", "access-provisioning"))
    monkeypatch.setattr(module, "SEEDS", tuple(range(12)))

    def source(revision):
        source_calls.append(revision)
        return {"revision": revision, "hash": "changed" if source_changed and len(source_calls) > 1 else "fixed"}

    monkeypatch.setattr(module, "source_identity", source)
    monkeypatch.setattr(module, "cache_identity", lambda: {"revision": "explicit-fake-cache"})
    monkeypatch.setattr(module, "load_tokenizer", lambda: object())

    async def rollout(config, index):
        calls.append(config)
        if failure and len(calls) == 2:
            raise failure
        return {"id": f"fake-{config.environment_id}-{config.seed}", "split": "train" if config.seed < 8 else "test",
                "steps": 4, "scenario_id": f"scenario-{config.environment_id}-{config.seed}"}

    def selection(episode, rights):
        examples = tuple({"provenance": {"episode_id": episode["id"]}, "step": index} for index in range(4))
        return SimpleNamespace(status="accepted" if episode["split"] == "train" else "excluded",
                               reason=None if episode["split"] == "train" else "heldout_split",
                               examples=examples if episode["split"] == "train" else ())

    def encode(example, tokenizer, **kwargs):
        if oversize:
            raise module.TrainingDataError("oversize_decision")
        return {"explicit_fake_encoded": True, **example}

    monkeypatch.setattr(module, "rollout", rollout)
    monkeypatch.setattr(module, "select_episode", selection)
    monkeypatch.setattr(module, "encode_example", encode)
    return calls


async def test_mocked_cohort_preserves_all_raw_rows_and_heldouts(monkeypatch, tmp_path):
    calls = mocked_collect(monkeypatch)
    output = tmp_path / "new"
    report = await module.collect(output, "a" * 40)
    assert report["status"] == "completed" and report["training_ready"]
    assert report["counts"] == {"planned": 24, "persisted": 24, "tokenized": 64,
                                 "rejected_tokens": 0, "unattempted": 0,
                                 "heldout_instances": 8, "heldout_decisions": 32}
    assert len(report["heldout_live_evaluation"]) == 8
    assert all(config.provider_id == "scripted-oracle" and not config.evaluation_only
               and config.concurrency == 1 and config.max_steps == 20 for config in calls)
    raw = [json.loads(line) for line in (output / "operator-episodes.jsonl").read_text().splitlines()]
    assert len(raw) == 24 and all(row["training_eligible"] is False for row in raw)
    for name, metadata in report["files"].items():
        assert metadata == {"bytes": (output / name).stat().st_size, "sha256": module.sha256(output / name)}
    assert json.loads((output / "report.json").read_text())["counts"] == report["counts"]


async def test_raw_is_durable_before_selection_error(monkeypatch, tmp_path):
    mocked_collect(monkeypatch)
    output = tmp_path / "new"

    def fail(episode, rights):
        persisted = json.loads((output / "operator-episodes.jsonl").read_text())
        assert persisted["episode"] == episode
        raise ValueError("SECRET_SENTINEL")

    monkeypatch.setattr(module, "select_episode", fail)
    report = await module.collect(output, "a" * 40)
    assert report["status"] == "stopped" and report["counts"]["persisted"] == 1
    assert report["counts"]["unattempted"] == 23
    assert "SECRET_SENTINEL" not in (output / "report.json").read_text()


@pytest.mark.parametrize("missing", ["id", "steps", "split", "scenario_id"])
async def test_malformed_returned_raw_is_counted_before_field_extraction(monkeypatch, tmp_path, missing):
    mocked_collect(monkeypatch)
    original = module.rollout

    async def malformed(config, index):
        episode = await original(config, index)
        episode.pop(missing)
        return episode

    monkeypatch.setattr(module, "rollout", malformed)
    output = tmp_path / "new"
    report = await module.collect(output, "a" * 40)
    raw = json.loads((output / "operator-episodes.jsonl").read_text())
    assert missing not in raw["episode"]
    assert report["status"] == "stopped" and report["counts"]["persisted"] == 1
    assert report["rows"][0]["raw_persisted"] is True and report["rows"][0]["status"] == "inconclusive"
    assert report["counts"]["unattempted"] == 23
    assert report["counts"]["tokenized"] == 0 and not report["training_ready"]


@pytest.mark.parametrize(("field", "value"), [("steps", True), ("steps", "4"), ("steps", -1),
                                              ("split", []), ("id", 1), ("scenario_id", None)])
async def test_malformed_header_types_cannot_break_final_receipt(monkeypatch, tmp_path, field, value):
    mocked_collect(monkeypatch)
    original = module.rollout

    async def malformed(config, index):
        episode = await original(config, index)
        episode[field] = value
        return episode

    monkeypatch.setattr(module, "rollout", malformed)
    output = tmp_path / "new"
    report = await module.collect(output, "a" * 40)
    assert json.loads((output / "operator-episodes.jsonl").read_text())["episode"][field] == value
    assert report["counts"]["persisted"] == 1 and report["rows"][0]["status"] == "inconclusive"
    assert json.loads((output / "report.json").read_text())["status"] == "stopped"


async def test_all_token_rejects_retained_no_silent_truncation(monkeypatch, tmp_path):
    mocked_collect(monkeypatch, oversize=True)
    output = tmp_path / "new"
    report = await module.collect(output, "a" * 40)
    assert report["status"] == "insufficient_training_data" and not report["training_ready"]
    assert report["counts"]["rejected_tokens"] == 64 and report["counts"]["tokenized"] == 0
    assert len((output / "public-decisions.jsonl").read_text().splitlines()) == 64
    assert len((output / "token-rejections.jsonl").read_text().splitlines()) == 64
    assert not (output / "masked-decisions.jsonl").exists()


async def test_source_changed_cannot_be_training_ready(monkeypatch, tmp_path):
    mocked_collect(monkeypatch, source_changed=True)
    report = await module.collect(tmp_path / "new", "a" * 40)
    assert report["status"] == "stopped" and not report["training_ready"]
    assert report["counts"]["persisted"] == 24


@pytest.mark.parametrize("failure", [ValueError("SECRET"), __import__("asyncio").CancelledError()])
async def test_stopped_prefix_never_retry_and_retain_unattempted(monkeypatch, tmp_path, failure):
    calls = mocked_collect(monkeypatch, failure=failure)
    report = await module.collect(tmp_path / "new", "a" * 40)
    assert len(calls) == 2 and report["counts"]["persisted"] == 1
    assert report["counts"]["unattempted"] == 22
    assert report["status"] in {"stopped", "cancelled"}
    assert not report["training_ready"]


async def test_admission_quota_stops_before_next_rollout(monkeypatch, tmp_path):
    calls = mocked_collect(monkeypatch)
    monkeypatch.setattr(module, "RESERVE", module.CAP)
    report = await module.collect(tmp_path / "new", "a" * 40)
    assert not calls and report["counts"]["unattempted"] == 24 and report["status"] == "stopped"


def test_offline_socket_guard_restores_exact_state():
    original = socket.socket.connect, socket.create_connection
    with module.offline():
        with pytest.raises(module.PilotStopped, match="network forbidden"):
            socket.create_connection(("example.invalid", 443))
        with pytest.raises(module.PilotStopped):
            socket.socket.connect(None, ("127.0.0.1", 1))
    assert (socket.socket.connect, socket.create_connection) == original


@pytest.mark.parametrize("revision", [None, "main", "a" * 39, "A" * 40, 1])
def test_source_requires_full_reviewed_revision(revision):
    with pytest.raises(module.PilotStopped, match="full source"):
        module.source_identity(revision)


def test_cache_drift_refuses_without_download(monkeypatch, tmp_path):
    monkeypatch.setattr(module, "CACHE_PATH", tmp_path)
    with pytest.raises(module.PilotStopped, match="exact installed"):
        module.cache_identity()


@pytest.mark.parametrize("drift", ["version", "eos", "pad", "template"])
def test_tokenizer_identity_gates(monkeypatch, drift):
    monkeypatch.setattr(module.importlib.metadata, "version", lambda name:
                        "incorrect" if drift == "version" else module.VERSIONS[name])
    import sys

    tokenizer = SimpleNamespace(chat_template="fixed", eos_token_id=151645, pad_token_id=151643)
    monkeypatch.setattr(module, "TEMPLATE_HASH", __import__("hashlib").sha256(b"fixed").hexdigest())
    if drift == "eos":
        tokenizer.eos_token_id = 99
    elif drift == "pad":
        tokenizer.pad_token_id = 99
    elif drift == "template":
        tokenizer.chat_template = "changed"

    def load(path, **kwargs):
        assert kwargs == {"local_files_only": True, "trust_remote_code": False}
        return tokenizer

    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(AutoTokenizer=SimpleNamespace(from_pretrained=load)))
    with pytest.raises(module.PilotStopped):
        module.load_tokenizer()


def test_main_default_does_not_collect(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", [str(PATH)])
    monkeypatch.setattr(module, "collect", lambda *args: pytest.fail("default collected"))
    assert module.main() == 0
    assert json.loads(capsys.readouterr().out)["status"] == "plan-only"


@pytest.mark.parametrize("args", [["--collect"], ["--collect", "--output", "new"]])
def test_collect_requires_explicit_source_and_output(monkeypatch, args):
    monkeypatch.setattr("sys.argv", [str(PATH), *args])
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 2
