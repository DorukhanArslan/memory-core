"""Builtin-only checkpoint controls, including real immediate Worker termination."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


HELPER = Path(__file__).resolve().parents[2] / "equivalence/forget-index-fence-source-clock.mjs"


def _run(script):
    node = os.environ.get("MEMORY_EQ_NODE") or shutil.which("node")
    if node is None:
        pytest.skip("A local Node runtime is required for this builtin-only checkpoint")
    environment = {key: value for key, value in os.environ.items()
                   if key != "NODE_OPTIONS" and not key.startswith("MEMORY_EQ_")}
    result = subprocess.run([node, "--input-type=module", "--eval", script], env=environment,
                            capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_real_worker_terminal_prepost_checkpoint_survives_immediate_original_terminate(tmp_path):
    output = tmp_path / "labelled-passive-buffer.json"
    child = tmp_path / "labelled-checkpoint-worker.mjs"
    child.write_text(f"""
import fs from 'node:fs';
import {{parentPort}} from 'node:worker_threads';
import {{callOriginalAtCheckpoint}} from {json.dumps(HELPER.as_uri())};
const rows=[];let writes=0;
const flush=()=>fs.writeFileSync({json.dumps(str(output))},JSON.stringify({{rows,writes:++writes}}));
process.once('exit',()=>rows.push({{event:'exit-not-relied-upon'}}));
parentPort.on('message',message=>{{
 if(message!=='run')throw Error('Unqualified labelled request');
 rows.push({{event:'actual-controlled-release',releaseStep:{{operation:'release-gate',gate:'labelled'}}}});flush();
 rows.push({{event:'labelled-passive-postrelease-row'}}); // memory only, no per-row filesystem IO
 const reply={{id:73,ok:true,value:new Uint8Array([12,34,56])}},transfers=[reply.value.buffer];
 callOriginalAtCheckpoint({{receiver:parentPort,original:parentPort.postMessage,args:[reply,transfers],
  before:()=>{{rows.push({{event:'terminal-reply-checkpoint',id:reply.id}});flush();}},
  settled:(result,error)=>{{rows.push({{event:'actual-post-settled',returnedUndefined:result===undefined,threw:Boolean(error)}});flush();}},
  onControlFailure:error=>{{throw error;}}
 }});
}});
parentPort.postMessage({{kind:'ready'}});
""", encoding="utf8")
    result = _run(f"""
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {{Worker}} from 'node:worker_threads';
const worker=new Worker(new URL({json.dumps(child.as_uri())}),{{execArgv:[]}});
let terminating;
const reply=await new Promise((resolve,reject)=>{{
 worker.on('error',reject);
 worker.on('message',message=>{{
  if(message.kind==='ready'){{worker.postMessage('run');return;}}
  terminating=worker.terminate(); // the real parent ends the worker as soon as its reply arrives
  resolve(message);
 }});
}});
await terminating;
assert.equal(reply.id,73);assert.equal(reply.ok,true);assert.deepEqual([...reply.value],[12,34,56]);
const observed=JSON.parse(fs.readFileSync({json.dumps(str(output))},'utf8'));
assert.equal(observed.rows[0].event,'actual-controlled-release');
assert.equal(observed.rows[1].event,'labelled-passive-postrelease-row');
assert.equal(observed.rows[2].event,'terminal-reply-checkpoint');
assert.equal(observed.rows.some(row=>row.event==='exit-not-relied-upon'),false);
assert(observed.writes>=2);
process.stdout.write(JSON.stringify({{kind:'builtin-only-worker-checkpoint',originalReleaseModulesImported:false}})+'\\n');
""")
    assert result == {"kind": "builtin-only-worker-checkpoint", "originalReleaseModulesImported": False}


def test_checkpoint_keeps_actual_receiver_arguments_return_and_error_identity():
    result = _run(f"""
import assert from 'node:assert/strict';
import {{callOriginalAtCheckpoint}} from {json.dumps(HELPER.as_uri())};
const receiver={{}},argument={{}},actualResult={{}},actualError=new Error('Labelled actual original failure');
const order=[];let calls=0;
const actual=callOriginalAtCheckpoint({{receiver,original(value){{assert.equal(this,receiver);assert.equal(value,argument);calls++;order.push('original');return actualResult;}},
 args:[argument],before:()=>order.push('before'),settled:(value,error)=>{{assert.equal(value,actualResult);assert.equal(error,undefined);order.push('return');}},
 onControlFailure:error=>{{throw error;}}}});
assert.equal(actual,actualResult);assert.equal(calls,1);assert.deepEqual(order,['before','original','return']);
let caught;
try{{callOriginalAtCheckpoint({{receiver,original(){{throw actualError;}},args:[],before(){{}},
 settled:(value,error)=>{{assert.equal(value,undefined);assert.equal(error,actualError);}},onControlFailure:error=>{{throw error;}}}});}}catch(error){{caught=error;}}
assert.equal(caught,actualError);
process.stdout.write(JSON.stringify({{identityPreserved:true}})+'\\n');
""")
    assert result == {"identityPreserved": True}


@pytest.mark.parametrize("phase", ["before", "settled"])
def test_checkpoint_observer_failure_does_not_replace_actual_original_return(phase):
    result = _run(f"""
import assert from 'node:assert/strict';
import {{callOriginalAtCheckpoint}} from {json.dumps(HELPER.as_uri())};
const actual={{}},control=new Error('Labelled checkpoint failure'),failures=[];let calls=0;
const returned=callOriginalAtCheckpoint({{receiver:{{}},original(){{calls++;return actual;}},args:[],
 before(){{if({json.dumps(phase)}==='before')throw control;}},settled(){{if({json.dumps(phase)}==='settled')throw control;}},
 onControlFailure:error=>failures.push(error)}});
assert.equal(returned,actual);assert.equal(calls,1);assert.deepEqual(failures,[control]);
process.stdout.write(JSON.stringify({{originalReturnUnchanged:true}})+'\\n');
""")
    assert result == {"originalReturnUnchanged": True}
