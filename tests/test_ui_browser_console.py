"""Browser-console QA preflight and network guards; no backend or model calls."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/browser-console-qa.mjs"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js required")


def node(code):
    return subprocess.run([NODE, "--input-type=module"], input=code, cwd=ROOT,
                          capture_output=True, text=True, timeout=15)


def imported(code):
    result = node(f"import * as q from {json.dumps(SCRIPT.as_uri())};"
                  "import assert from 'node:assert/strict';" + code)
    assert result.returncode == 0, result.stderr
    return result


@pytest.mark.parametrize("args", [[], ["--plan"]])
def test_plan_no_source_browser_output_or_network(tmp_path, args):
    guard = tmp_path / "guard.cjs"
    guard.write_text("const cp=require('node:child_process'),M=require('node:module');"
                     "cp.execFileSync=()=>{throw Error('FORBIDDEN_SOURCE')};M.syncBuiltinESMExports();"
                     "const old=M._load;M._load=function(n,...a){if(n==='playwright')"
                     "throw Error('FORBIDDEN_BROWSER');return old.call(this,n,...a)};"
                     "global.fetch=()=>{throw Error('FORBIDDEN_NETWORK')};")
    result = subprocess.run([NODE, str(SCRIPT), *args], cwd=tmp_path, capture_output=True,
                            text=True, timeout=15, env={**os.environ, "NODE_OPTIONS": f"--require={guard}"})
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan["new_attempts"] == plan["inference_calls"] == 0
    assert plan["allowed_methods"] == ["GET"]
    assert plan["viewports"] == [1440, 390, 360]
    assert list(tmp_path.iterdir()) == [guard]


@pytest.mark.parametrize("args", [
    ["--collect"], ["--collect", "--plan"], ["--plan", "--output", "x"],
    ["--local-cancel"], ["--collect", "--attempt-id", "SECRET_SENTINEL", "--output", "x"],
    ["--collect", "--attempt-id", "11111111-1111-4111-8111-111111111111", "--source-revision", "short", "--output", "x"],
])
def test_invalid_options_redacted(args):
    imported(f"assert.throws(()=>q.parseOptions({json.dumps(args)}),/values redacted/);")


@pytest.mark.parametrize("kind", ["directory", "file", "live_symlink", "dangling_symlink"])
def test_existing_output_refused_before_source_browser_network(tmp_path, kind):
    output, target = tmp_path / "existing", tmp_path / "target"
    if kind == "directory":
        output.mkdir()
        (output / "old.json").write_text("historical")
    elif kind == "file":
        output.write_text("historical")
    else:
        if kind == "live_symlink":
            target.mkdir()
        output.symlink_to(target)
    imported(f"await assert.rejects(q.collect({{output:{json.dumps(str(output))},revision:'invalid'}}),/QA output already exists/);")
    if kind == "directory":
        assert (output / "old.json").read_text() == "historical"
    elif kind == "file":
        assert output.read_text() == "historical"
    else:
        assert output.is_symlink()


def test_request_guard_only_public_loopback_get():
    imported("""
      const base='http://127.0.0.1:5173';
      for(const p of ['/api/browser/tasks','/api/browser/status','/api/browser/attempts','/api/health','/src/App.tsx'])
        assert.equal(q.allowedRequest(base,'GET',base+p),true);
      for(const m of ['POST','PUT','PATCH','DELETE','HEAD','OPTIONS']) assert.equal(q.allowedRequest(base,m,base+'/api/browser/attempts'),false);
      for(const p of ['/api/chat','/api/show','/api/private']) assert.equal(q.allowedRequest(base,'GET',base+p),false);
      assert.equal(q.allowedRequest(base,'GET','https://external.test/x'),false);
      assert.equal(q.allowedRequest(base,'GET','http://user:secret@127.0.0.1:5173/x'),false);
      assert.equal(q.allowedRequest(base,'GET',base,true),false);
      assert.equal(q.allowedRequest(base,'GET','bad'),false);
    """)


@pytest.mark.parametrize("mode", ["okay", "mutation", "external", "redirected", "redirect_response", "wrong_origin", "fetch_error"])
def test_route_guard_never_forwards_mutations_or_redirects(mode):
    imported(f"""
      const mode={json.dumps(mode)},base='http://127.0.0.1:5173';
      const report={{blocked_requests:[],browser_errors:[],get_requests:0}};
      let fetched=0,aborted=0,fulfilled=0;
      const route={{request:()=>({{method:()=>mode==='mutation'?'POST':'GET',url:()=>mode==='external'?'http://external.test/x':base+'/api/browser/status',redirectedFrom:()=>mode==='redirected'?{{}}:null}}),
        abort:async()=>{{aborted++}},fulfill:async()=>{{fulfilled++}},fetch:async(options)=>{{fetched++;assert.equal(options.maxRedirects,0);if(mode==='fetch_error')throw Error('SECRET_SENTINEL');return{{status:()=>mode==='redirect_response'?302:200,url:()=>mode==='wrong_origin'?'http://external.test/x':base+'/api/browser/status'}}}}}};
      await q.readOnlyRoute(base,report)(route);
      if(mode==='okay'){{assert.equal(fetched,1);assert.equal(fulfilled,1);assert.equal(aborted,0)}}
      else{{assert.equal(fulfilled,0);assert.equal(aborted,1);if(['mutation','external','redirected'].includes(mode))assert.equal(fetched,0)}}
      assert.equal(JSON.stringify(report).includes('SECRET_SENTINEL'),false);
    """)


def test_bounded_writes_do_not_overwrite_or_escape(tmp_path):
    imported(f"""
      const output={json.dumps(str(tmp_path))};
      await q.writeBounded(output,'receipt.json',Buffer.from('original'));
      await assert.rejects(q.writeBounded(output,'receipt.json',Buffer.from('replacement')));
      await assert.rejects(q.writeBounded(output,'../outside',Buffer.from('bad')));
      await assert.rejects(q.writeBounded(output,'large',Buffer.alloc(q.ARTIFACT_CAP)));
    """)
    assert (tmp_path / "receipt.json").read_text() == "original"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["receipt.json"]


def test_production_browser_schema_offline():
    if not (ROOT / "web/node_modules/vite").exists():
        pytest.skip("Console dependencies are installed in the separate console CI job")
    result = subprocess.run([NODE, "scripts/ui-browser-check.mjs", "--schema-only"], cwd=ROOT,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "boundaries passed" in result.stdout
