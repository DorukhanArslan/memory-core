"""Builtin-only shared log custody; no original release owner executes."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


HELPER = Path(__file__).resolve().parents[2] / "equivalence/forget-index-fence-source-clock.mjs"


def _run(tmp_path, body):
    node = os.environ.get("MEMORY_EQ_NODE") or shutil.which("node")
    if node is None:
        pytest.skip("A local Node runtime is required for this builtin-only shared log")
    options = {"directory": str(tmp_path), "token": "labelled-builtin-log", "slotCount": 8,
               "initialBytes": 64, "maxBytes": 4096}
    script = f"""
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {{Worker,threadId}} from 'node:worker_threads';
import {{openThreadEventStore}} from {json.dumps(HELPER.as_uri())};
const options={json.dumps(options)},store=openThreadEventStore(options);
{body}
process.stdout.write(JSON.stringify({{kind:'builtin-only-shared-log',originalReleaseModulesImported:false}})+'\\n');
"""
    environment = {key: value for key, value in os.environ.items()
                   if key != "NODE_OPTIONS" and not key.startswith("MEMORY_EQ_")}
    result = subprocess.run([node, "--input-type=module", "--eval", script], env=environment,
                            capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "kind": "builtin-only-shared-log", "originalReleaseModulesImported": False,
    }


def test_parent_retains_actual_worker_ram_prefix_after_immediate_terminate_before_worker_flush(tmp_path):
    _run(tmp_path, f"""
store.append({{event:'main',threadId}});
const code=`import {{parentPort,threadId}} from 'node:worker_threads';
 import {{openThreadEventStore}} from {json.dumps(HELPER.as_uri())};
 const store=openThreadEventStore(${{JSON.stringify(options)}});
 store.append({{event:'worker',threadId,text:'x'.repeat(1000)}});
 parentPort.postMessage({{threadId}});`;
const worker=new Worker(new URL('data:text/javascript,'+encodeURIComponent(code)),{{execArgv:[]}});
const message=await new Promise((resolve,reject)=>{{worker.once('message',resolve);worker.once('error',reject);}});
await worker.terminate();
const filename=path.join(options.directory,`${{process.pid}}-${{message.threadId}}-events.jsonl`);
assert.equal(fs.existsSync(filename),false); // the worker never performed any checkpoint IO
const seal=store.flush(),rows=fs.readFileSync(filename,'utf8').trim().split('\\n').map(JSON.parse);
assert.equal(rows.length,1);assert.equal(rows[0].threadId,message.threadId);assert.equal(rows[0].text.length,1000);
assert.equal(seal.channels.length,2);assert.equal(store.failures().length,0);
assert(seal.channels.find(row=>row.threadId===message.threadId).capacityBytes>options.initialBytes);
""")


def test_append_is_immutable_utf8_and_checkpoint_never_truncates_a_longer_prefix(tmp_path):
    _run(tmp_path, """
const value={event:'first',body:{text:'actual 🦊 source'}};
store.append(value);value.body.text='mutated after append';
store.flush();store.append({event:'second'});const second=store.flush();
store.flush();const filename=path.join(options.directory,`${process.pid}-${threadId}-events.jsonl`);
const rows=fs.readFileSync(filename,'utf8').trim().split('\\n').map(JSON.parse);
assert.equal(rows[0].body.text,'actual 🦊 source');assert.equal(rows[1].event,'second');
assert.equal(fs.statSync(filename).size,second.channels[0].publishedBytes);
assert.equal(second.channels[0].publishedBytes,second.channels[0].persistedBytes);
assert.equal(store.failures().length,0);
""")


def test_capacity_failure_is_independent_bounded_and_preserves_all_preceding_rows(tmp_path):
    _run(tmp_path, """
assert.equal(store.append({event:'retained'}),true);
assert.equal(store.append({event:'oversized',text:'x'.repeat(options.maxBytes)}),false);
assert.equal(store.append({event:'later'}),false);
const failures=store.failures();assert.equal(failures.length,1);assert.equal(failures[0].code,1);
const seal=store.flush(),filename=path.join(options.directory,`${process.pid}-${threadId}-events.jsonl`);
assert.deepEqual(fs.readFileSync(filename,'utf8').trim().split('\\n').map(JSON.parse),[{event:'retained'}]);
assert.equal(seal.failures.length,1);assert.equal(seal.channels[0].failureCode,1);
""")


def test_older_parent_flush_cannot_truncate_a_newer_actual_worker_prefix(tmp_path):
    _run(tmp_path, f"""
store.append({{event:'main'}});const control=new SharedArrayBuffer(4),state=new Int32Array(control);
const code=`import {{parentPort,workerData,threadId}} from 'node:worker_threads';
 import {{openThreadEventStore}} from {json.dumps(HELPER.as_uri())};
 const store=openThreadEventStore(${{JSON.stringify(options)}}),state=new Int32Array(workerData);
 store.append({{event:'first',threadId}});
 parentPort.on('message',()=>{{store.append({{event:'newer',threadId}});store.flush();Atomics.store(state,0,1);Atomics.notify(state,0);}});
 parentPort.postMessage({{threadId}});`;
const worker=new Worker(new URL('data:text/javascript,'+encodeURIComponent(code)),{{execArgv:[],workerData:control}});
const ready=await new Promise((resolve,reject)=>{{worker.once('message',resolve);worker.once('error',reject);}});
const filename=path.join(options.directory,`${{process.pid}}-${{ready.threadId}}-events.jsonl`),open=fs.openSync;let interleaved=false;
fs.openSync=function(...args){{
 if(args[0]===filename&&!interleaved){{interleaved=true;worker.postMessage('publish-newer-prefix');
  while(Atomics.load(state,0)===0)Atomics.wait(state,0,0,1000);
 }}
 return Reflect.apply(open,this,args);
}};
try{{store.flush();}}finally{{fs.openSync=open;}}
const rows=fs.readFileSync(filename,'utf8').trim().split('\\n').map(JSON.parse);
assert.deepEqual(rows.map(row=>row.event),['first','newer']);assert.equal(interleaved,true);
const channel=store.snapshot().find(row=>row.threadId===ready.threadId);
assert.equal(channel.publishedBytes,fs.statSync(filename).size);assert.equal(channel.persistedBytes,channel.publishedBytes);
await worker.terminate();
""")
