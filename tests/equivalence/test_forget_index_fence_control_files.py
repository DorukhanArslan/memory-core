"""Real builtin-only atomic gate handoffs; no original engine is imported."""
import json
import os
from pathlib import Path
import subprocess

import pytest

from equivalence.model_runtime_authority import prepare_model_node_authority

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "equivalence/forget-index-fence-source-clock.mjs"


@pytest.fixture(scope="module")
def node():
    selected = os.environ.get("MEMORY_EQ_NODE")
    path = Path(selected) if selected else ROOT / "work/node-v24.16.0-linux-x64/bin/node"
    if not path.is_file():
        pytest.skip("Exact Node unavailable; builtin mechanism only, no parity credit")
    prepare_model_node_authority(path)
    return path


def _run(node, tmp_path, body):
    code = f'''
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {{Worker}} from 'node:worker_threads';
import {{publishControlFile}} from {json.dumps(HELPER.as_uri())};
const helper={json.dumps(HELPER.as_uri())},directory={json.dumps(str(tmp_path))};
{body}
console.log(JSON.stringify({{builtinOnly:true}}));
'''
    result = subprocess.run([str(node), "--input-type=module", "--eval", code],
        cwd=tmp_path, capture_output=True, text=True, timeout=20,
        env={"PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC"}, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"builtinOnly": True}


def test_partial_real_worker_stage_is_invisible_and_atomic_target_has_complete_bytes(node, tmp_path):
    _run(node, tmp_path, r'''
const filename=path.join(directory,'actual.release'),content=JSON.stringify({gate:'pure-gate',padding:'x'.repeat(65536)})+'\n';
const state=new Int32Array(new SharedArrayBuffer(4));
const worker=new Worker(`
 const fs=require('node:fs');const {parentPort,workerData}=require('node:worker_threads');
 const state=new Int32Array(workerData.state),originalWrite=fs.writeSync;let first=true;
 fs.writeSync=function(fd,bytes,offset,length,...rest){
  if(first){first=false;const actual=originalWrite.call(this,fd,bytes,offset,3,...rest);
   parentPort.postMessage({kind:'actual-partial-stage',written:actual});Atomics.wait(state,0,0);return actual;}
  return originalWrite.call(this,fd,bytes,offset,length,...rest);
 };
 import(workerData.helper).then(({publishControlFile})=>{
  const receipt=publishControlFile(workerData.filename,workerData.content);
  parentPort.postMessage({kind:'published',receipt});
 }).catch(error=>{parentPort.postMessage({kind:'failed',message:error.message});process.exitCode=2;});
`,{eval:true,execArgv:[],workerData:{helper,filename,content,state:state.buffer}});
let partialResolve,publishedResolve;
const partial=new Promise(resolve=>partialResolve=resolve),published=new Promise(resolve=>publishedResolve=resolve);
const exited=new Promise((resolve,reject)=>{worker.once('exit',resolve);worker.once('error',reject);});
worker.on('message',message=>{if(message.kind==='actual-partial-stage')partialResolve(message);else publishedResolve(message);});
try{
 const first=await partial;assert.equal(first.written,3);
 assert.equal(fs.existsSync(filename),false);
 assert.equal(fs.readFileSync(path.join(filename+'.publishing','body')).length,3);
 assert.throws(()=>publishControlFile(filename,content),error=>error.code==='EEXIST');
 assert.equal(fs.existsSync(filename),false);
}finally{Atomics.store(state,0,1);Atomics.notify(state,0);}
const outcome=await published;assert.equal(outcome.kind,'published');assert.equal(await exited,0);
assert.equal(fs.readFileSync(filename,'utf8'),content);assert.equal(JSON.parse(fs.readFileSync(filename,'utf8')).gate,'pure-gate');
const actual=fs.lstatSync(filename,{bigint:true});assert.equal(actual.nlink,1n);
assert.equal(actual.ino.toString(),outcome.receipt.stageStat.ino);assert.equal(actual.dev.toString(),outcome.receipt.stageStat.dev);
assert.equal(outcome.receipt.bytes,Buffer.from(content).toString('hex'));
assert.equal(fs.existsSync(filename+'.publishing'),false);
''')


def test_duplicate_complete_publication_cannot_replace_original_control_or_leave_stage(node, tmp_path):
    _run(node, tmp_path, r'''
const filename=path.join(directory,'actual.hit.json'),content='{"original":"complete control body"}\n';
publishControlFile(filename,content);const before=fs.lstatSync(filename,{bigint:true});
assert.throws(()=>publishControlFile(filename,'{"replacement":"forbidden"}\n'),/already published/);
assert.equal(fs.readFileSync(filename,'utf8'),content);
const after=fs.lstatSync(filename,{bigint:true});assert.equal(after.ino,before.ino);assert.equal(after.nlink,1n);
assert.equal(fs.existsSync(filename+'.publishing'),false);
''')


def test_real_stage_failure_is_returned_and_owned_stage_is_cleaned_before_retry(node, tmp_path):
    _run(node, tmp_path, r'''
const filename=path.join(directory,'actual.armed'),originalWrite=fs.writeSync,originalError=new Error('pure actual stage writer failure');
fs.writeSync=function(){throw originalError;};
try{assert.throws(()=>publishControlFile(filename,'{"control":"whole"}\n'),error=>error===originalError);}
finally{fs.writeSync=originalWrite;}
assert.equal(fs.existsSync(filename),false);assert.equal(fs.existsSync(filename+'.publishing'),false);
publishControlFile(filename,'{"control":"whole"}\n');assert.deepEqual(JSON.parse(fs.readFileSync(filename,'utf8')),{control:'whole'});
assert.equal(fs.lstatSync(filename).nlink,1);
''')
