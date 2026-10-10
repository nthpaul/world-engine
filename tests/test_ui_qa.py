import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ui-qa.mjs"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for console QA preflight")


def node_module(code):
    return subprocess.run([NODE, "--input-type=module", "-e", code], cwd=ROOT,
                          capture_output=True, text=True, timeout=10)


def test_inspector_throughput_explicitly_labels_steps_per_second():
    source = (ROOT / "web/src/App.tsx").read_text()
    metric = re.search(r'<Metric\s+label="Step throughput"\s+value=\{`([^`]+)`\}', source)
    assert metric is not None
    assert metric.group(1) == "${number(run.steps_per_second)} steps/s"


@pytest.mark.parametrize("args", [[], ["--access"], ["--output", ""], ["--unknown"],
                                 ["--output", "x", "--access", "--atif"],
                                 ["--output", "x", "--access", "--local-cancel"],
                                 ["--output", "x", "--atif", "--local-cancel"]])
def test_cli_invalid_options_never_load_browser_or_create_default_artifacts(tmp_path, args):
    guard = tmp_path / "guard.cjs"
    guard.write_text("const Module=require('node:module');const load=Module._load;"
                     "Module._load=function(name,...args){if(name==='playwright')"
                     "throw Error('FORBIDDEN_BROWSER_ACTIVITY');return load.call(this,name,...args)};")
    env = {**os.environ, "NODE_OPTIONS": f"--require={guard}", "WORLD_ENGINE_UI_URL": "http://127.0.0.1:1"}
    before = {path: path.stat().st_mtime_ns for path in (ROOT / "artifacts/qa").rglob("*") if path.is_file()}
    result = subprocess.run([NODE, str(SCRIPT), *args], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "FORBIDDEN_BROWSER_ACTIVITY" not in result.stderr
    assert not (tmp_path / "x").exists()
    assert {path: path.stat().st_mtime_ns for path in before} == before


@pytest.mark.parametrize("kind", ["directory", "file", "symlink", "dangling-symlink"])
def test_existing_output_refused_before_browser_or_api(tmp_path, kind):
    output, target = tmp_path / "output", tmp_path / "target"
    if kind == "directory":
        output.mkdir()
        (output / "ui-report.json").write_text("historical QA receipt")
    elif kind == "file":
        output.write_text("historical QA receipt")
    else:
        if kind == "symlink":
            target.mkdir()
            (target / "ui-report.json").write_text("historical QA receipt")
        output.symlink_to(target, target_is_directory=True)
    guard = tmp_path / "guard.cjs"
    guard.write_text("const Module=require('node:module');const load=Module._load;"
                     "Module._load=function(name,...args){if(name==='playwright')"
                     "throw Error('FORBIDDEN_BROWSER_ACTIVITY');return load.call(this,name,...args)};")
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    result = subprocess.run([NODE, str(SCRIPT), "--access", "--output", str(output)], cwd=tmp_path,
                            env={**os.environ, "NODE_OPTIONS": f"--require={guard}",
                                 "WORLD_ENGINE_UI_URL": "http://127.0.0.1:1"},
                            capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "QA output already exists" in result.stderr
    assert "FORBIDDEN_BROWSER_ACTIVITY" not in result.stderr
    assert {path: path.read_bytes() for path in before} == before
    assert output.is_symlink() == ("symlink" in kind)
    if kind == "dangling-symlink":
        assert not target.exists()


def test_import_safe_options_make_inference_opt_in():
    result = node_module(f"""
      import assert from 'node:assert/strict';
      import {{parseOptions}} from {json.dumps(SCRIPT.as_uri())};
      assert.equal(parseOptions(['--output','fresh']).localCancel, false);
      assert.equal(parseOptions(['--output','fresh','--local-cancel']).localCancel, true);
      assert.equal(parseOptions(['--output','fresh','--access']).phase, 'access');
      assert.equal(parseOptions(['--output','fresh','--atif']).phase, 'atif');
      console.log('import-safe opt-in boundary verified');
    """)
    assert result.returncode == 0, result.stderr
    assert "import-safe opt-in boundary verified" in result.stdout


def test_fresh_directory_reserved_once_without_pruning(tmp_path):
    output = tmp_path / "nested/fresh"
    unrelated = tmp_path / "historical"
    unrelated.mkdir()
    (unrelated / "earlier.jsonl").write_text("prior download")
    (unrelated / "earlier.webm").write_bytes(b"prior video")
    result = node_module(f"""
      import assert from 'node:assert/strict';
      import {{writeFile,readFile}} from 'node:fs/promises';
      import {{reserveFreshOutput}} from {json.dumps(SCRIPT.as_uri())};
      const output={json.dumps(str(output))};
      const results=await Promise.allSettled([reserveFreshOutput(output),reserveFreshOutput(output)]);
      assert.equal(results.filter(result=>result.status==='fulfilled').length,1);
      assert.equal(results.filter(result=>result.status==='rejected').length,1);
      await writeFile(output+'/receipt.json','first receipt');
      await assert.rejects(reserveFreshOutput(output));
      assert.equal(await readFile(output+'/receipt.json','utf8'),'first receipt');
    """)
    assert result.returncode == 0, result.stderr
    assert (unrelated / "earlier.jsonl").read_text() == "prior download"
    assert (unrelated / "earlier.webm").read_bytes() == b"prior video"


def test_operator_episode_serialization_preserves_wire_numeric_types():
    raw = '{"episodes":[{"id":9007199254740993,"reward":1.0,"zero":0.0,"nested":{"flag":true,"id":1}}]}'
    result = node_module(f"""
      import {{operatorEpisodeJsonl}} from {json.dumps(SCRIPT.as_uri())};
      process.stdout.write(operatorEpisodeJsonl([{json.dumps(raw)}]));
    """)
    assert result.returncode == 0, result.stderr
    episode = json.loads(result.stdout)
    assert episode["id"] == 9007199254740993
    assert type(episode["reward"]) is float and episode["reward"] == 1.0
    assert type(episode["zero"]) is float and episode["zero"] == 0.0
    assert episode["nested"] == {"flag": True, "id": 1}
    assert type(episode["nested"]["id"]) is int


@pytest.mark.parametrize("raw", ["{not-json}", '{"episodes":[{"reward":NaN}]}', '{}'])
def test_operator_episode_serialization_refuses_invalid_wire_records(raw):
    result = node_module(f"""
      import assert from 'node:assert/strict';
      import {{operatorEpisodeJsonl}} from {json.dumps(SCRIPT.as_uri())};
      assert.throws(()=>operatorEpisodeJsonl([{json.dumps(raw)}]));
    """)
    assert result.returncode == 0, result.stderr


def test_operator_episode_serialization_requires_bounded_raw_response_strings():
    result = node_module(f"""
      import assert from 'node:assert/strict';
      import {{operatorEpisodeJsonl}} from {json.dumps(SCRIPT.as_uri())};
      for (const value of [null, [], [{{episodes:[]}}], ['x'.repeat(16*1024*1024+1)]])
        assert.throws(()=>operatorEpisodeJsonl(value));
    """)
    assert result.returncode == 0, result.stderr
