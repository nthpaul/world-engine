"""Pure Node guards and fake browser controls; no actual browser/API/model calls."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/qa-native-controls.mjs"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js required")


def node(code):
    return subprocess.run([NODE, "--input-type=module", "-e", code], cwd=ROOT,
                          capture_output=True, text=True, timeout=15)


def imported(code):
    result = node(f"import * as q from {json.dumps(SCRIPT.as_uri())};"
                  "import assert from 'node:assert/strict';" + code)
    assert result.returncode == 0, result.stderr
    return result


@pytest.mark.parametrize("args", [[], ["--plan"]])
def test_plan_has_no_source_browser_or_output_activity(tmp_path, args):
    guard = tmp_path / "guard.cjs"
    guard.write_text("const cp=require('node:child_process'),M=require('node:module');"
                     "cp.execFileSync=()=>{throw Error('FORBIDDEN_SOURCE')};M.syncBuiltinESMExports();"
                     "const old=M._load;M._load=function(n,...a){if(n==='playwright')"
                     "throw Error('FORBIDDEN_BROWSER');return old.call(this,n,...a)};")
    result = subprocess.run([NODE, str(SCRIPT), *args], cwd=tmp_path, capture_output=True,
                            text=True, timeout=15, env={**os.environ, "NODE_OPTIONS": f"--require={guard}"})
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan["protocol"]["inference_requests"] == 0
    assert plan["protocol"]["new_rollouts"] == 0
    assert len(plan["protocol"]["viewports"]) == 3
    assert list(tmp_path.iterdir()) == [guard]


@pytest.mark.parametrize("args", [["--collect"], ["--plan", "--collect"], ["--plan", "--output", "x"],
                                 ["--local-cancel"], ["--collect", "--output", "x", "--source-revision", "short"],
                                 ["--collect", "--output", "", "--source-revision", "a" * 40]])
def test_invalid_options_redacted(args):
    imported(f"assert.throws(()=>q.parseOptions({json.dumps(args)}),/supplied values redacted/);")


@pytest.mark.parametrize("kind", ["directory", "file", "live_symlink", "dangling_symlink"])
def test_existing_output_fails_before_source_or_browser(tmp_path, kind):
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
    imported(f"await assert.rejects(q.collect({{output:{json.dumps(str(output))},revision:'invalid'}}),"
             "/QA output already exists/);")
    assert output.is_symlink() if "symlink" in kind else output.exists()
    if kind == "directory":
        assert (output / "old.json").read_text() == "historical"
    elif kind == "file":
        assert output.read_text() == "historical"


@pytest.mark.parametrize("url", ["http://user:SECRET_SENTINEL@[::1", "http://user:SECRET_SENTINEL@127.0.0.1:bad"])
def test_malformed_origin_does_not_leak_url(url):
    result = node(f"import {{localOrigin}} from {json.dumps(SCRIPT.as_uri())};localOrigin({json.dumps(url)});")
    assert result.returncode != 0 and "loopback origin" in result.stderr
    assert "SECRET_SENTINEL" not in result.stderr and "ERR_INVALID_URL" not in result.stderr


def test_origin_and_request_guards():
    imported("""
      const base='http://127.0.0.1:5173';
      for(const url of [base,'http://localhost:5173','http://[::1]:5173']) assert.equal(q.localOrigin(url),new URL(url).origin);
      for(const url of ['https://external.test','http://u:p@127.0.0.1:5173',base+'/?q=x',base+'/#x','file:///tmp'])
        assert.throws(()=>q.localOrigin(url));
      for(const p of ['/api/health','/api/providers','/api/environments','/api/runs','/src/App.tsx'])
        assert.equal(q.requestAllowed(base,'GET',base+p),true);
      for(const m of ['POST','PUT','PATCH','DELETE','HEAD','OPTIONS']) assert.equal(q.requestAllowed(base,m,base+'/api/runs'),false);
      for(const p of ['/api/chat','/api/show','/api/runs/id','/api/runs/id/export']) assert.equal(q.requestAllowed(base,'GET',base+p),false);
      assert.equal(q.requestAllowed(base,'GET','http://external.test/x'),false);
      assert.equal(q.requestAllowed(base,'GET',base,true),false);
      assert.equal(q.requestAllowed(base,'GET','bad'),false);
    """)


@pytest.mark.parametrize("mode", ["okay", "mutation", "external", "redirected", "redirect_response", "wrong_origin", "fetch_error"])
def test_route_gate_never_forwards_mutation_or_redirect(mode):
    imported(f"""
      const mode={json.dumps(mode)},base='http://127.0.0.1:5173';
      const report={{blocked_requests:[],browser_errors:[],requests:{{GET:0}},get_paths:{{}}}};
      let fetches=0,aborts=0,fulfills=0;
      const route={{request:()=>({{method:()=>mode==='mutation'?'POST':'GET',
        url:()=>mode==='external'?'http://external.test/x':base+'/api/health',
        redirectedFrom:()=>mode==='redirected'?{{}}:null}}),
        abort:async()=>aborts++,fetch:async(options)=>{{fetches++;assert.equal(options.maxRedirects,0);
          if(mode==='fetch_error')throw Error('PRIVATE_NETWORK_BODY');
          return {{status:()=>mode==='redirect_response'?302:200,url:()=>mode==='wrong_origin'?'http://external.test/x':base+'/api/health'}};
        }},fulfill:async()=>fulfills++}};
      await q.readOnlyRoute(base,report)(route);
      assert.equal(fulfills,mode==='okay'?1:0);assert.equal(aborts,mode==='okay'?0:1);
      if(['mutation','external','redirected'].includes(mode))assert.equal(fetches,0);
      assert.ok(!JSON.stringify(report).includes('PRIVATE_NETWORK_BODY'));
      assert.ok(Object.keys(report.get_paths).every(p=>p==='/api/health'));
    """)


def test_metadata_saved_projection_excludes_private_catalog():
    imported("""
      const health={status:'ok',version:'0.1.0',paid_calls_enabled:false,active_runs:0,max_global_concurrency:8,private:'SECRET'};
      const providers=['local-tools','local-tools-ledger'].map(id=>({id,kind:'local',configured:true,requires_opt_in:false,
        name:'PRIVATE_NAME',models:['PRIVATE_MODEL','qwen3:8b']}));
      providers.push({id:'remote',configured:true,models:['PRIVATE_OTHER']});
      const saved=q.checkMetadata(health,{providers});
      assert.deepEqual(saved.map(r=>Object.keys(r)),[0,1].map(()=>['id','configured','kind','requires_opt_in','has_exact_public_qwen3_8b']));
      assert.ok(!JSON.stringify(saved).includes('PRIVATE'));
      for(const change of [{version:'wrong'},{paid_calls_enabled:true},{active_runs:1}])
        assert.throws(()=>q.checkMetadata({...health,...change},{providers}));
      assert.throws(()=>q.checkMetadata(health,{providers:providers.map(r=>({...r,models:[]}))}));
      assert.throws(()=>q.checkMetadata(health,{providers:providers.map(r=>({...r,configured:false}))}));
    """)


def test_source_and_cooperative_deadline_guards():
    imported("""
      const source={revision:'a'.repeat(40),source_dirty:false,files:{'one':'sha'}};
      assert.equal(q.verifySourceIdentity(source.revision,source),source);
      for(const change of [{revision:'b'.repeat(40)},{source_dirty:true},{files:{}}])
        assert.throws(()=>q.verifySourceIdentity(source.revision,{...source,...change}));
      assert.equal(q.workTimeLeft(0,104999),1);assert.throws(()=>q.workTimeLeft(0,105000));
    """)


def test_browser_has_no_direct_api_bypass_and_blocks_websockets():
    source = SCRIPT.read_text()
    assert 'context.route("**/*", readOnlyRoute(baseURL, report))' in source
    assert 'context.routeWebSocket("**/*"' in source and "socket.close()" in source
    assert 'serviceWorkers: "block"' in source
    assert "context.request" not in source and "route.continue" not in source
    assert 'git(["status", "--porcelain", "--untracked-files=all"])' in source


def test_exclusive_artifact_cap_and_video_postclose_check(tmp_path):
    output = tmp_path / "out"
    output.mkdir()
    imported(f"""
      import {{writeFile,open,readFile,symlink,unlink}} from 'node:fs/promises';
      const out={json.dumps(str(output))},video={json.dumps(str(tmp_path / 'video.webm'))};
      await q.writeBounded(out,'one.png',Buffer.from('first'));
      await assert.rejects(q.writeBounded(out,'one.png',Buffer.from('replacement')));
      assert.equal(await readFile(out+'/one.png','utf8'),'first');
      await assert.rejects(q.writeBounded(out,'../escape',Buffer.from('x')));
      const handle=await open(video,'w');await handle.truncate(q.ARTIFACT_CAP);await handle.close();
      await assert.rejects(q.publishVideo(out,video),/cap/);
      await writeFile(video,'video');await q.publishVideo(out,video);
      assert.equal(await readFile(out+'/controls.webm','utf8'),'video');
      await symlink(video,out+'/link');await assert.rejects(q.artifactBytes(out),/symlink/);await unlink(out+'/link');
      await assert.rejects(q.writeBounded(out,'limit',Buffer.from('x'),q.ARTIFACT_CAP),/cap/);
    """)


def test_mock_dialog_transitions_never_start_or_open_model_dropdown():
    imported("""
      let visible=false,provider='scripted-oracle',workers='4',evaluation=false,opened=0,cancelled=0;
      const native=()=>provider==='local-tools'||provider==='local-tools-ledger';
      const worker={inputValue:async()=>workers,isEnabled:async()=>true,fill:async(v)=>workers=v};
      const checkbox={isEnabled:async()=>!native(),isDisabled:async()=>native(),isChecked:async()=>evaluation,
        uncheck:async()=>{assert.ok(!native());evaluation=false}};
      const dialog={getByLabel:(name)=>{
        if(name==='Concurrency')return worker;
        if(name==='Model')return {inputValue:async()=> 'qwen3:8b'};
        assert.equal(name,'Provider');return {selectOption:async(v)=>{const prior=native();provider=v;if(native()){evaluation=true;if(!prior)workers='1'}}};
      },getByRole:(role,{name})=>{
        if(role==='checkbox')return checkbox;
        assert.equal(name,'Cancel');return {click:async()=>{visible=false;cancelled++}};
      },locator:(selector)=>{assert.equal(selector,'.paid-consent');return {count:async()=>0}},isVisible:async()=>visible};
      const page={getByRole:(role,{name})=>{
        if(role==='dialog')return dialog;
        assert.equal(name,'New rollout');return {click:async()=>{visible=true;provider='scripted-oracle';workers='4';evaluation=false;opened++}};
      }};
      const shots=[],checks=[];
      for(const width of [1440,390,360]) await q.inspectControls(page,async(name)=>shots.push(name),(s)=>checks.push(s),width);
      assert.equal(opened,9);assert.equal(cancelled,9);assert.equal(shots.length,12);assert.equal(checks.length,12);
      assert.equal(new Set(shots).size,12);assert.ok(!visible);
    """)


@pytest.mark.parametrize("mode", ["completed", "mutation", "close_failure", "source_drift", "modal_overlap", "button_overlap"])
def test_fake_collector_report_cleanup_and_privacy(tmp_path, mode):
    guard, output = tmp_path / "fake.cjs", tmp_path / "out"
    guard.write_text("""
      const cp=require('node:child_process'),M=require('node:module'),fs=require('node:fs'),path=require('node:path');
      let sourceCalls=0;
      cp.execFileSync=(command,args)=>{
        if(command!=='git')throw Error('UNEXPECTED_PROCESS');
        if(args.includes('rev-parse')){sourceCalls++;return 'a'.repeat(40)+'\\n'}
        return process.env.MODE==='source_drift'&&sourceCalls>1?' M source\\n':'';
      };M.syncBuiltinESMExports();
      const health={status:'ok',version:'0.1.0',active_runs:0,paid_calls_enabled:false,max_global_concurrency:8};
      const catalog={providers:['local-tools','local-tools-ledger'].map(id=>({id,kind:'local',configured:true,
        requires_opt_in:false,models:['PRIVATE_MODEL_SENTINEL','qwen3:8b']}))};
      let routeHandler,visible=false,provider='scripted-oracle',workers='4',evaluation=false,viewport;
      const native=()=>['local-tools','local-tools-ledger'].includes(provider);
      const worker={inputValue:async()=>workers,isEnabled:async()=>true,fill:async(v)=>workers=v};
      const checkbox={isEnabled:async()=>!native(),isDisabled:async()=>native(),isChecked:async()=>evaluation,
        uncheck:async()=>evaluation=false};
      const dialog={getByLabel:(name)=>name==='Concurrency'?worker:name==='Model'?{inputValue:async()=> 'qwen3:8b'}:
        {selectOption:async(v)=>{const prior=native();provider=v;if(native()){evaluation=true;if(!prior)workers='1'}}},
        getByRole:(role,{name})=>{if(role==='checkbox')return checkbox;
          return {click:async()=>{if(name!=='Cancel')throw Error('START_FORBIDDEN');visible=false},
            boundingBox:async()=>({x:20,y:process.env.MODE==='button_overlap'?190:150,width:100,height:40})}},
        locator:()=>({count:async()=>0}),isVisible:async()=>visible,
        boundingBox:async()=>({x:0,y:0,width:viewport.width,
          height:process.env.MODE==='modal_overlap'?viewport.height+2:200})};
      let videoPath;
      const page={getByRole:(role)=>role==='dialog'?dialog:{click:async()=>{visible=true;provider='scripted-oracle';
        workers='4';evaluation=false}},on:()=>{},waitForResponse:async(predicate)=>{
          const responses=['health','providers'].map(name=>({url:()=> 'http://127.0.0.1:5173/api/'+name,
            status:()=>200,json:async()=>name==='health'?health:catalog}));return responses.find(predicate);
        },goto:async()=>{
          for(const method of ['GET',...(process.env.MODE==='mutation'?['POST']:[])]){
            await routeHandler({request:()=>({method:()=>method,url:()=> 'http://127.0.0.1:5173/api/health',redirectedFrom:()=>null}),
              abort:async()=>{},fetch:async()=>({status:()=>200,url:()=> 'http://127.0.0.1:5173/api/health'}),fulfill:async()=>{}});
          }
        },setViewportSize:async(v)=>viewport=v,viewportSize:()=>viewport,evaluate:async()=>true,
        screenshot:async()=>Buffer.from('fake screenshot'),video:()=>({path:async()=>videoPath})};
      const context={setDefaultTimeout:()=>{},route:async(_,handler)=>routeHandler=handler,routeWebSocket:async()=>{},
        newPage:async()=>page,close:async()=>{fs.appendFileSync(process.env.CLEANUP,'context\\n');
          if(process.env.MODE==='close_failure')throw Error('PRIVATE_CLOSE_SENTINEL')}};
      const browser={newContext:async(options)=>{viewport=options.viewport;videoPath=path.join(options.recordVideo.dir,'fake.webm');
        fs.writeFileSync(videoPath,'fake video');return context},close:async()=>fs.appendFileSync(process.env.CLEANUP,'browser\\n')};
      const old=M._load;M._load=function(name,...args){if(name==='playwright')return {chromium:{launch:async()=>browser}};
        return old.call(this,name,...args)};
    """)
    cleanup = tmp_path / "cleanup.txt"
    result = subprocess.run([NODE, str(SCRIPT), "--collect", "--source-revision", "a" * 40,
                             "--api-startup-revision", "b" * 40, "--output", str(output)],
                            cwd=ROOT, capture_output=True, text=True, timeout=15,
                            env={**os.environ, "NODE_OPTIONS": f"--require={guard}", "MODE": mode,
                                 "CLEANUP": str(cleanup), "WORLD_ENGINE_UI_URL": "http://127.0.0.1:5173"})
    assert result.returncode == (0 if mode == "completed" else 1), result.stderr
    report = json.loads((output / "report.json").read_text())
    assert report["status"] == ("completed" if mode == "completed" else "stopped")
    assert cleanup.read_text() == "context\nbrowser\n"
    assert report["api_startup_revision_declared"] == "b" * 40
    assert report["new_rollouts"] == report["inference_requests"] == report["api_mutations"] == 0
    assert len(list(output.glob("*.png"))) == (0 if mode in ("modal_overlap", "button_overlap") else 12)
    assert report["artifact_total_bytes"] == sum(file.stat().st_size for file in output.iterdir())
    assert report["report_bytes"] == (output / "report.json").stat().st_size
    assert report["artifact_total_bytes"] < 64 * 1024 ** 2
    assert "PRIVATE_MODEL_SENTINEL" not in (output / "report.json").read_text()
    assert "PRIVATE_CLOSE_SENTINEL" not in result.stdout + result.stderr + (output / "report.json").read_text()
    for relative in ["web/vite.config.ts", "web/index.html"]:
        assert relative in report["source"]["scope"]
        assert report["source"]["files"][relative] == hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        if mode != "source_drift":
            assert report["source_post"]["files"][relative] == report["source"]["files"][relative]
    if mode == "mutation":
        assert report["blocked_requests"] == [{"method": "POST", "redirected": False}]
    elif mode == "source_drift":
        assert "source_post" not in report
    elif mode == "close_failure":
        assert report["browser_cleanup"] == "unconfirmed" and "video" not in report
    else:
        assert report["browser_cleanup"] == "completed" and report["video"] == "controls.webm"
