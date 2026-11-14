"""Builtin-only planning holds and concurrent command custody; no release engine."""
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
    code = f"""
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {{MessageChannel,Worker,isMainThread,threadId}} from 'node:worker_threads';
import {{serialize}} from 'node:v8';
import * as clockModule from {json.dumps(HELPER.as_uri())};
import {{createOriginalCommandScope,awaitOriginalPlanningGateRelease,publishControlFile}} from {json.dumps(HELPER.as_uri())};
const directory={json.dumps(str(tmp_path))};
const preloadPath={json.dumps(str(ROOT / 'equivalence/forget-index-fence-preload.mjs'))};
{body}
console.log(JSON.stringify({{builtinOnly:true,originalReleaseModulesImported:false}}));
"""
    result = subprocess.run([str(node), "--input-type=module", "--eval", code],
        cwd=tmp_path, capture_output=True, text=True, timeout=10,
        env={"PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC"}, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "builtinOnly": True, "originalReleaseModulesImported": False,
    }


def test_pending_model_completion_keeps_ipc_live_and_original_command_scope(node, tmp_path):
    _run(node, tmp_path, r"""
const scopes=createOriginalCommandScope(),filename=path.join(directory,'planning.release');
const originalResponse={text:'exact declared model response'},request={candidates:['actual original request']};
let probesResolve,continued=false,calls=0;
const probesDone=new Promise(resolve=>probesResolve=resolve),probes=[];
const complete=async actualRequest=>{
 calls++;assert.equal(actualRequest,request);
 const enteredAtNs=process.hrtime.bigint().toString();
 const release=await awaitOriginalPlanningGateRelease(filename,{enteredAtNs,onProgress:kind=>{
  probes.push({kind,scope:scopes.current()});if(probes.length===2)probesResolve();
 }});
 assert.equal(release.gateDeadlineNs,(BigInt(enteredAtNs)+30_000_000_000n).toString());
 assert(BigInt(release.consumedAtNs)<BigInt(release.gateDeadlineNs));
 assert.deepEqual(release.releaseStep,{operation:'release-gate',gate:'promotionPlan'});
 assert.equal(scopes.current().label,'stored');assert.equal(scopes.current().commandId,12);
 continued=true;return originalResponse;
};
const promotion=scopes.run({id:12,operation:'original-promotion',label:'stored'},()=>complete(request));
await probesDone;assert.equal(continued,false);assert.equal(calls,1);
assert.deepEqual(new Set(probes.map(row=>row.kind)),new Set(['setImmediate','setTimeout']));
assert(probes.every(row=>row.scope.commandId===12&&row.scope.label==='stored'));
const {port1,port2}=new MessageChannel();
const watchControl=new Promise((resolve,reject)=>port1.once('message',()=>{
 scopes.run({id:18,operation:'await-original-watch-effects',label:'selectedWatch'},async()=>{
  assert.equal(scopes.current().label,'selectedWatch');await Promise.resolve();
  assert.equal(scopes.current().commandId,18);assert.equal(continued,false);
  publishControlFile(filename,JSON.stringify({operation:'release-gate',gate:'promotionPlan'})+'\n');
 }).then(resolve,reject);
}));
port2.postMessage('actual IPC control while original model callback remains pending');
await watchControl;assert.equal(await promotion,originalResponse);assert.equal(continued,true);
assert.equal(scopes.current(),null);port1.close();port2.close();
""")


def test_pending_realpath_return_retains_original_result_and_scope_after_control(node, tmp_path):
    _run(node, tmp_path, r"""
const scopes=createOriginalCommandScope(),filename=path.join(directory,'direct.release');
const originalRealpath=fs.promises.realpath,actualResult=await originalRealpath(directory);
let ready,finished=false;const pending=new Promise(resolve=>ready=resolve);
const originalContinuation=scopes.run({id:25,operation:'original-promotion',label:'direct'},async()=>{
 const result=await originalRealpath(directory);assert.equal(result,actualResult);
 const enteredAtNs=process.hrtime.bigint().toString();
 await awaitOriginalPlanningGateRelease(filename,{enteredAtNs,onProgress:kind=>{if(kind==='setImmediate')ready();}});
 assert.equal(scopes.current().label,'direct');finished=true;return result;
});
await pending;const retained=scopes.current();assert.equal(retained,null);assert.equal(finished,false);
await scopes.run({id:26,operation:'await-original-watch-effects',label:'selectedWatch'},async()=>{
 await new Promise(resolve=>setImmediate(resolve));assert.equal(scopes.current().label,'selectedWatch');
 publishControlFile(filename,'{"operation":"release-gate","gate":"directPlan"}\n');
});
assert.equal(await originalContinuation,actualResult);assert.equal(fs.promises.realpath,originalRealpath);
assert.equal(scopes.current(),null);
""")


def test_expired_entry_cannot_gain_a_fresh_deadline_even_when_release_exists(node, tmp_path):
    _run(node, tmp_path, r"""
const filename=path.join(directory,'late.release');publishControlFile(filename,'{"original":"late release"}\n');
let progress=0;
await assert.rejects(awaitOriginalPlanningGateRelease(filename,{
 enteredAtNs:(process.hrtime.bigint()-30_000_000_001n).toString(),onProgress:()=>progress++,
}),/exceeded its real monotonic bound/);
assert.equal(progress,0);assert.equal(JSON.parse(fs.readFileSync(filename,'utf8')).original,'late release');
""")


def test_deadline_includes_real_mainloop_probes_before_release_consumption(node, tmp_path):
    _run(node, tmp_path, r"""
const filename=path.join(directory,'probe.release');publishControlFile(filename,'{"original":"held release"}\n');
const enteredAtNs=(process.hrtime.bigint()-29_900_000_000n).toString();
await assert.rejects(awaitOriginalPlanningGateRelease(filename,{enteredAtNs,
 originalImmediate:callback=>setTimeout(callback,150),
}),/exceeded its real monotonic bound/);
""")


def test_command_scope_cannot_be_mutated_and_survives_rejection_and_deferred_task_reply(node, tmp_path):
    _run(node, tmp_path, r"""
const scopes=createOriginalCommandScope(),actualError=new Error('actual control rejection');let retained;
await assert.rejects(scopes.run({id:4,operation:'original-promotion',label:'stored'},async()=>{
 retained=scopes.current();assert(Object.isFrozen(retained));
 assert.throws(()=>{retained.label='rewritten';},TypeError);
 await new Promise(resolve=>setImmediate(resolve));assert.equal(scopes.current(),retained);throw actualError;
}),error=>error===actualError);
assert.equal(scopes.current(),null);
await scopes.run({id:5,operation:'await-original-watch-effects',label:'selectedWatch'},async()=>{
 await scopes.resume(retained,async()=>{await Promise.resolve();assert.equal(scopes.current(),retained);});
 assert.equal(scopes.current().label,'selectedWatch');
});
assert.equal(scopes.current(),null);
assert.throws(()=>scopes.run({id:0,operation:'original-promotion',label:'stored'},()=>{}),/actual labelled IPC command/);
""")


def test_actual_preload_reply_wrapper_retains_real_worker_receiver_message_and_task_scope(node, tmp_path):
    _run(node, tmp_path, r"""
const source=fs.readFileSync(preloadPath,'utf8'),start=source.indexOf('Worker.prototype.emit=function(name,message,...args){'),
 end=source.indexOf('\nconst realpath=fsp.realpath;',start);
assert(start>=0&&end>start);
const emit=Worker.prototype.emit,commandScopes=createOriginalCommandScope(),sourceWorkers=new WeakMap(),tasks=new WeakMap();
const passiveObservation=callback=>callback(),event=()=>{},matching=()=>[];
const workerSource={sourceCaller:{path:'builtin-only-worker'}},refs=new WeakMap();let nextRef=0,nextWorkerCall=0;
const processRef=value=>{if(!refs.has(value))refs.set(value,`builtin-ref-${++nextRef}`);return refs.get(value);};
const bindTransportMethod=()=>{},workerPayload=value=>value;
const carrier=value=>({v8Hex:serialize(value).toString('hex')}),controlFailure=(reason,error)=>{throw error;};
eval(source.slice(start,end)); // Exercise the actual production wrapper body.
const worker=new Worker(`const {parentPort}=require('node:worker_threads');
 parentPort.postMessage({status:'ok',taskId:73,value:{kind:'keyword',body:{rows:['whole original payload']}}});`,
 {eval:true,execArgv:[]});
let taskScope;commandScopes.run({id:44,operation:'public-memory-search',label:'selected'},()=>{taskScope=commandScopes.current();});
tasks.set(worker,new Map([[73,{callLabel:'selected',commandScope:taskScope}]]));sourceWorkers.set(worker,workerSource);
const received=new Promise((resolve,reject)=>{
 worker.once('message',function(message){try{
  assert.equal(this,worker);assert.deepEqual(message.value.body.rows,['whole original payload']);
  assert.equal(commandScopes.current(),taskScope);resolve(message);
 }catch(error){reject(error);}});worker.once('error',reject);
});
const exit=new Promise(resolve=>worker.once('exit',resolve));
assert.equal((await received).taskId,73);assert.equal(await exit,0);assert.equal(tasks.get(worker).size,0);
assert.equal(commandScopes.current(),null);Worker.prototype.emit=emit;
""")


def test_both_v5_planning_boundaries_await_async_control_and_keep_legacy_sync_modes():
    preload = (ROOT / "equivalence/forget-index-fence-preload.mjs").read_text()
    runtime = (ROOT / "equivalence/forget-index-fence-runtime.mjs").read_text()
    assert "'promotion.model-planning-before-final-lock':'deferred-original-model-completion'" in preload
    assert "'promotion.source-planned-before-final-lock':'deferred-original-realpath-return'" in preload
    assert "if(input.kind==='forget-index-fence-v5')await controller().pauseAsync('promotion.model-planning-before-final-lock',facts)" in runtime
    assert "else controller().pause('promotion.model-planning-before-final-lock',facts)" in runtime
    assert "if(profile.kind==='forget-index-fence-v5')await pauseAsync('promotion.source-planned-before-final-lock',facts)" in preload
    assert "else pause('promotion.source-planned-before-final-lock',facts)" in preload
    assert "withCommandScope(command,()=>executeScoped(command))" in runtime
    assert "setCallLabel" not in runtime + preload
