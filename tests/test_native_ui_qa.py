"""Offline receipt/CLI boundaries; browser and actual model calls are forbidden."""

import asyncio
import copy
import importlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from world_engine.atif import export_episode
from world_engine.models import RunConfig, canonical_json
from world_engine.native_ledger import reconstruct
from world_engine.ollama_tools import LEDGER_PROTOCOL, PROTOCOL, OllamaToolsProvider
from world_engine.providers import ScriptedProvider
from world_engine.rollout import rollout

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/native-ui-qa.mjs"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for receipt QA preflight")


def node(code):
    return subprocess.run([NODE, "--input-type=module"], input=code, cwd=ROOT,
                          capture_output=True, text=True, timeout=30)


def test_node_helper_accepts_large_receipt_code_via_stdin():
    code = "/*" + "x" * (128 * 1024) + "*/\nconsole.log('stdin-ok');"
    result = node(code)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "stdin-ok"


class RawBody(httpx.AsyncByteStream):
    def __init__(self, data):
        self.body = canonical_json(data).encode()

    async def __aiter__(self):
        yield self.body


@pytest.fixture(scope="module", params=[PROTOCOL, LEDGER_PROTOCOL])
def recorded(request):
    selected = request.param

    async def fixture():
        oracle = ScriptedProvider()
        chat_count = 0

        async def respond(req):
            nonlocal chat_count
            if req.url.path == "/api/tags":
                data = {"models": [{"name": "qwen3:8b", "digest": "a" * 64}]}
            elif req.url.path == "/api/show":
                data = {"capabilities": ["tools", "completion"]}
            elif req.url.path == "/api/version":
                data = {"version": "offline-fixture"}
            else:
                assert req.url.path == "/api/chat"
                body = json.loads(req.content)
                public = reconstruct(body) if selected == LEDGER_PROTOCOL else json.loads(body["messages"][1]["content"])
                action = (await oracle.decide(public["observation"], public["history"])).action
                data = {"model": "qwen3:8b", "done": True, "done_reason": "stop", "eval_count": 16,
                        "message": {"role": "assistant", "content": "", "tool_calls": [
                            {"function": {"name": action.tool, "arguments": action.args}}]}}
                if selected == LEDGER_PROTOCOL or chat_count == 0:
                    data["prompt_eval_count"] = 27
                chat_count += 1
            return httpx.Response(200, stream=RawBody(data))

        config = RunConfig(environment_id="crm-merge", provider_id="local", model="qwen3:8b",
                           seed=0, max_steps=20, timeout_seconds=35, concurrency=1, evaluation_only=True)
        provider = OllamaToolsProvider(config, protocol=selected)
        provider.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        module = importlib.import_module("world_engine.rollout")
        try:
            await provider.prepare()
            with patch.object(module, "collection_revision", return_value={"git_revision": "a" * 40,
                              "git_dirty": False, "implementation_dirty": False}):
                episode = await rollout(config, 0, provider)
        finally:
            await provider.close()
        assert episode["passed"] and episode["steps"] > 1
        return {"schema": "world-engine.evaluation-trace.v1", "episode": episode,
                "slot": {"index": 1 if selected == LEDGER_PROTOCOL else 0, "seed": 0, "protocol": selected},
                "evaluation_only": True, "training_eligible": False, "exact_envelope_preserved": True}

    return asyncio.run(fixture())


def write_receipt(tmp_path, recorded):
    file = tmp_path / "receipt.jsonl"
    file.write_text(canonical_json(recorded)+"\n")
    return file


@pytest.mark.parametrize("args", [[], ["--run-id", "x"], ["--run-id", "../unsafe", "--receipt", "x", "--output", "y"],
                                 ["--run-id", "x", "--receipt", "x", "--output", ""],
                                 ["--run-id", "x", "--receipt", "x", "--output", "y", "--local-cancel"],
                                 ["--run-id", "x", "--receipt", "x", "--output", "y", "--access"]])
def test_invalid_cli_no_browser_git_or_output(tmp_path, args):
    guard = tmp_path / "guard.cjs"
    guard.write_text("const M=require('node:module');const old=M._load;M._load=function(name,...args){"
                     "if(name==='playwright')throw Error('FORBIDDEN_BROWSER');return old.call(this,name,...args)};")
    result = subprocess.run([NODE, str(SCRIPT), *args], cwd=tmp_path, capture_output=True, text=True,
                            timeout=10, env={**os.environ, "NODE_OPTIONS": f"--require={guard}"})
    assert result.returncode != 0 and "FORBIDDEN_BROWSER" not in result.stderr
    assert not (tmp_path / "y").exists()


@pytest.mark.parametrize("kind", ["directory", "file", "live_symlink", "dangling_symlink"])
def test_existing_output_refused_before_receipt_or_browser(tmp_path, kind):
    output, target = tmp_path / "existing", tmp_path / "target"
    if kind == "directory":
        output.mkdir()
        (output / "historical.json").write_text("old")
    elif kind == "file":
        output.write_text("old")
    else:
        if kind == "live_symlink":
            target.mkdir()
        output.symlink_to(target)
    before = {file: file.read_bytes() for file in tmp_path.rglob("*") if file.is_file()}
    result = node(f"""
      import {{prepare}} from {json.dumps(SCRIPT.as_uri())};
      await prepare({{output:{json.dumps(str(output))},receipt:'/missing-receipt',runId:'imported'}});
    """)
    assert result.returncode != 0 and "QA output already exists" in result.stderr
    assert {file: file.read_bytes() for file in before} == before
    assert output.is_symlink() if "symlink" in kind else output.exists()


def test_import_safe_and_get_only_loopback_guard():
    result = node(f"""
      import assert from 'node:assert/strict';
      import {{parseOptions,localBaseURL,requestAllowed}} from {json.dumps(SCRIPT.as_uri())};
      assert.equal(parseOptions(['--run-id','imported-v2','--receipt','receipt','--output','fresh']).runId,'imported-v2');
      for(const url of ['http://127.0.0.1:5173','http://localhost:5173','http://[::1]:5173'])
        assert.equal(localBaseURL(url),new URL(url).origin);
      for(const url of ['https://remote.example','http://user:pass@127.0.0.1:5173','http://127.0.0.1:5173/?q=x','http://127.0.0.1:5173/#x','file:///tmp'])
        assert.throws(()=>localBaseURL(url));
      assert.equal(requestAllowed('http://127.0.0.1:5173','GET','http://127.0.0.1:5173/api/runs/x'),true);
      for(const method of ['POST','PUT','DELETE','PATCH'])
        assert.equal(requestAllowed('http://127.0.0.1:5173',method,'http://127.0.0.1:5173/api/runs'),false);
      assert.equal(requestAllowed('http://127.0.0.1:5173','GET','http://remote.example/api/runs'),false);
    """)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("url", ["http://user:NATIVE_QA_SECRET_SENTINEL@[::1",
                                 "http://user:NATIVE_QA_SECRET_SENTINEL@127.0.0.1:bad"])
def test_malformed_origin_errors_do_not_disclose_input(url):
    result = node(f"""
      import {{localBaseURL}} from {json.dumps(SCRIPT.as_uri())};
      localBaseURL({json.dumps(url)});
    """)
    assert result.returncode != 0
    assert "loopback browser origin" in result.stderr
    assert "NATIVE_QA_SECRET_SENTINEL" not in result.stderr
    assert "ERR_INVALID_URL" not in result.stderr


def test_direct_api_reads_disable_redirects():
    source = SCRIPT.read_text()
    calls = re.findall(r"context\.request\.get\([^;]+;", source)
    assert len(calls) == 2
    assert all("maxRedirects: 0" in call for call in calls)


def test_actual_mocked_native_receipt_preflight_usage_and_numeric_fidelity(tmp_path, recorded):
    file = write_receipt(tmp_path, recorded)
    result = node(f"""
      import {{preflightReceipt}} from {json.dumps(SCRIPT.as_uri())};
      const receipt=await preflightReceipt({json.dumps(str(file))});
      console.log(JSON.stringify({{protocol:receipt.episode.provenance.provider_protocol,usage:receipt.episode.usage,
        canonical_episode:receipt.canonical_episode,replay_verified:receipt.replay_verified}}));
    """)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["replay_verified"] and data["canonical_episode"] == canonical_json(recorded["episode"])
    assert data["usage"]["input_tokens_complete"] == (data["protocol"] == LEDGER_PROTOCOL)
    assert data["usage"]["output_tokens_complete"]


@pytest.mark.parametrize("mutation", ["not_json", "multi", "flags", "protocol", "slot", "reward", "usage", "nan"])
def test_bad_receipt_fails_redacted_before_browser(tmp_path, recorded, mutation):
    value = copy.deepcopy(recorded)
    if mutation == "flags":
        value["training_eligible"] = True
    elif mutation == "protocol":
        value["episode"]["provenance"]["provider_protocol"] = "unknown"
    elif mutation == "slot":
        value["slot"]["seed"] = False
    elif mutation == "reward":
        value["episode"]["reward"] = 0.1
    elif mutation == "usage":
        value["episode"]["usage"]["input_tokens_known"] = 999
    elif mutation == "nan":
        value["episode"]["reward"] = float("nan")
    text = json.dumps(value)+"\n"
    if mutation == "not_json":
        text = "secret sentinel not JSON"
    elif mutation == "multi":
        text *= 2
    file = tmp_path / "bad.jsonl"
    file.write_text(text)
    result = node(f"""
      import {{prepare}} from {json.dumps(SCRIPT.as_uri())};
      await prepare({{receipt:{json.dumps(str(file))},output:{json.dumps(str(tmp_path/'fresh'))},runId:'imported'}});
    """)
    assert result.returncode != 0
    assert "supplied values and subprocess details redacted" in result.stderr
    assert "secret sentinel" not in result.stderr


@pytest.mark.parametrize("kind", ["directory", "symlink", "empty", "oversize"])
def test_nonregular_or_oversize_receipts_refused(tmp_path, kind):
    file = tmp_path / "receipt"
    if kind == "directory":
        file.mkdir()
    elif kind == "symlink":
        file.symlink_to(tmp_path / "missing")
    elif kind == "empty":
        file.write_text("")
    else:
        with file.open("wb") as handle:
            handle.truncate(24*1024*1024+1)
    result = node(f"""
      import {{preflightReceipt}} from {json.dumps(SCRIPT.as_uri())};
      await preflightReceipt({json.dumps(str(file))});
    """)
    assert result.returncode != 0 and "bounded regular" in result.stderr


def test_imported_api_detail_is_exact_and_rejects_rewrites(tmp_path, recorded):
    file = write_receipt(tmp_path, recorded)
    episode = recorded["episode"]
    detail = {"id": "imported", "label": "Imported operator receipt / mock fixture", "status": episode["status"],
              "elapsed_seconds": episode["elapsed_seconds"], "config": {"evaluation_only": True, "episodes": 1,
              "environment_id": episode["provenance"]["environment_id"], "seed": episode["seed"],
              "model": episode["provenance"]["model"], "allow_paid": False}, "episodes": [episode]}
    detail_file = tmp_path / "detail.json"
    detail_file.write_text(canonical_json(detail))
    result = node(f"""
      import assert from 'node:assert/strict';
      import {{readFile}} from 'node:fs/promises';
      import {{preflightReceipt,validateApiDetail}} from {json.dumps(SCRIPT.as_uri())};
      const receipt=await preflightReceipt({json.dumps(str(file))});
      const raw=await readFile({json.dumps(str(detail_file))},'utf8');
      validateApiDetail(receipt,raw,'imported');
      for(const field of ['id','index','seed','reward']){{
        const changed=JSON.parse(raw);changed.episodes[0][field]='rewritten';
        assert.throws(()=>validateApiDetail(receipt,JSON.stringify(changed),'imported'));
      }}
      const label=JSON.parse(raw);label.label='Measured native run';
      assert.throws(()=>validateApiDetail(receipt,JSON.stringify(label),'imported'));
      assert.throws(()=>validateApiDetail(receipt,JSON.stringify(JSON.parse(raw)),'imported'));
    """)
    assert result.returncode == 0, result.stderr


def test_native_api_wrapper_and_batch_overhead_are_exact(tmp_path, recorded):
    run_id = "00000000-0000-0000-0000-000000000050"
    episode = recorded["episode"]
    wrapper = {"evaluation_only": True, "training_eligible": False, "run_id": run_id, "episode": episode}
    file = tmp_path / "api-original.jsonl"
    file.write_text(canonical_json(wrapper) + "\n")
    alias = "local-tools" if episode["provenance"]["provider_protocol"] == PROTOCOL else "local-tools-ledger"
    detail = {"id": run_id, "label": "native-api-smoke-v1", "status": episode["status"],
              "elapsed_seconds": episode["elapsed_seconds"] + 0.5, "config": {"evaluation_only": True, "episodes": 1,
              "environment_id": episode["provenance"]["environment_id"], "seed": episode["seed"],
              "model": episode["provenance"]["model"], "allow_paid": False, "provider_id": alias,
              "label": "native-api-smoke-v1", "concurrency": 1, "max_steps": 20,
              "timeout_seconds": 35}, "episodes": [episode]}
    detail_file = tmp_path / "detail.json"
    detail_file.write_text(canonical_json(detail))
    result = node(f"""
      import assert from 'node:assert/strict';
      import {{readFile}} from 'node:fs/promises';
      import {{preflightReceipt,validateApiDetail,prepare}} from {json.dumps(SCRIPT.as_uri())};
      const receipt=await preflightReceipt({json.dumps(str(file))});
      assert.equal(receipt.receipt_kind,'native-api');assert.equal(receipt.slot,null);
      assert.equal(receipt.receipt_run_id,{json.dumps(run_id)});
      assert.equal(receipt.canonical_episode,{json.dumps(canonical_json(episode))});
      assert.deepEqual(receipt.raw,await readFile({json.dumps(str(file))}));
      const raw=await readFile({json.dumps(str(detail_file))},'utf8');
      validateApiDetail(receipt,raw,{json.dumps(run_id)});
      for(const field of ['id','index','seed','reward']){{
        const changed=JSON.parse(raw);changed.episodes[0][field]='rewritten';
        assert.throws(()=>validateApiDetail(receipt,JSON.stringify(changed),{json.dumps(run_id)}));
      }}
      for(const [field,value] of [['provider_id','local'],['label','Imported operator receipt'],['evaluation_only',1],['allow_paid',true],
                                ['concurrency',2],['max_steps',19],['timeout_seconds',36]]){{
        const changed=JSON.parse(raw);changed.config[field]=value;
        assert.throws(()=>validateApiDetail(receipt,JSON.stringify(changed),{json.dumps(run_id)}));
      }}
      const changed=JSON.parse(raw);changed.elapsed_seconds=-1;
      assert.throws(()=>validateApiDetail(receipt,JSON.stringify(changed),{json.dumps(run_id)}));
      await assert.rejects(prepare({{receipt:{json.dumps(str(file))},output:{json.dumps(str(tmp_path/'fresh'))},runId:'other'}}));
    """)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("mutation", ["eval_int", "train_int", "run_id", "extra", "schema", "protocol"])
def test_api_wrapper_mutations_fail_before_browser_redacted(tmp_path, recorded, mutation):
    wrapper = {"evaluation_only": True, "training_eligible": False,
               "run_id": "00000000-0000-0000-0000-000000000050", "episode": copy.deepcopy(recorded["episode"])}
    if mutation == "eval_int":
        wrapper["evaluation_only"] = 1
    elif mutation == "train_int":
        wrapper["training_eligible"] = 0
    elif mutation == "run_id":
        wrapper["run_id"] = "PRIVATE_SENTINEL"
    elif mutation == "extra":
        wrapper["extra"] = "PRIVATE_SENTINEL"
    elif mutation == "schema":
        wrapper["schema"] = "unknown"
    else:
        wrapper["episode"]["provenance"]["provider_protocol"] = "unknown"
    file = tmp_path / "bad.jsonl"
    file.write_text(canonical_json(wrapper) + "\n")
    result = node(f"import {{preflightReceipt}} from {json.dumps(SCRIPT.as_uri())};"
                  f"await preflightReceipt({json.dumps(str(file))});")
    assert result.returncode != 0 and "PRIVATE_SENTINEL" not in result.stderr
    assert "supplied values and subprocess details redacted" in result.stderr


def test_native_download_boundaries_and_no_invented_usage(tmp_path, recorded):
    episode = recorded["episode"]
    trace = {"schema": "world-engine.trace.v1", "provenance": {**episode["provenance"],
             "episode_id": episode["id"], "run_id": "imported", "split": episode["split"]},
             "provider_events": episode["provider_events"], "provider_recording": episode["provider_recording"],
             "usage": episode["usage"], "trace": episode["trace"], "training_eligible": False,
             "initial_observation": episode["initial_observation"], "final_state_hash": episode["final_state_hash"],
             "passed": episode["passed"], "reward": episode["reward"], "termination": episode["termination"]}
    atif = export_episode(episode, run_id="imported")
    file = write_receipt(tmp_path, recorded)
    exports = tmp_path / "exports.json"
    exports.write_text(canonical_json({"traces": trace, "atif": atif}))
    result = node(f"""
      import assert from 'node:assert/strict';
      import {{readFile}} from 'node:fs/promises';
      import {{preflightReceipt,validateDownload}} from {json.dumps(SCRIPT.as_uri())};
      const receipt=await preflightReceipt({json.dumps(str(file))});
      const exports=JSON.parse(await readFile({json.dumps(str(exports))},'utf8'));
      for(const format of ['traces','atif']){{
        assert.equal(validateDownload(format,JSON.stringify(exports[format]),receipt,'imported').length,1);
        const corrupt=structuredClone(exports[format]);
        if(format==='traces')corrupt.provider_events[0].request_sha256='changed';
        else corrupt.extra.world_engine.recorded_provider_usage={{input_tokens:0}};
        assert.throws(()=>validateDownload(format,JSON.stringify(corrupt),receipt,'imported'));
      }}
      for(const format of ['sft','dpo','grpo']){{
        assert.equal(validateDownload(format,'',receipt,'imported').length,0);
        assert.throws(()=>validateDownload(format,'{{}}',receipt,'imported'));
      }}
    """)
    assert result.returncode == 0, result.stderr
