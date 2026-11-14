"""Builtin-only V3 Promise controls; no original release module executes."""
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
    setup = r'''
import assert from 'node:assert/strict';
import {AsyncLocalStorage} from 'node:async_hooks';
import {deserialize} from 'node:v8';
import {setImmediate as turn} from 'node:timers/promises';
const rows=[],failures=[],refs=new WeakMap(),als=new AsyncLocalStorage();let nextRef=0;
const ref=value=>value!==null&&(typeof value==='object'||typeof value==='function')?
 (refs.has(value)?refs.get(value):(refs.set(value,'pure-ref-'+(++nextRef)),refs.get(value))):null;
const scope={key:'search:query',causalFrame:{fixture:'labelled-builtin-only',commandId:3}};
const qualifyPromise=stack=>{
 if(stack.includes('pure-recall-source.mjs')){
  if(stack.includes('at Promise.catch'))return{kind:'recall-catch',source:'pure-recall-source'};
  if(stack.includes('at Promise.then'))return{kind:'recall-then',source:'pure-recall-source'};
 }
 if(stack.includes('syntheticOwnedPublisher')&&stack.includes('at Promise.finally'))
  return{kind:'publisher',source:'pure-publisher-source'};
 return null;
};
const effects=observeOriginalSearchEffects({scope:()=>als.getStore(),qualifyPromise,ref,
 event:(event,fields)=>rows.push({event,...structuredClone(fields)}),onFailure:error=>failures.push(error)});
const owner={purpose:'default',activeBackgroundSearchSyncs:new Set()};
function deferred(){let release,reject;const promise=new Promise((yes,no)=>{release=yes;reject=no;});return{promise,release,reject};}
function syntheticOwnedPublisher(originalJob){
 const actual=originalJob.finally(()=>owner.activeBackgroundSearchSyncs.delete(actual));
 owner.activeBackgroundSearchSyncs.add(actual);return actual;
}
async function importSearch(){
 const target='data:text/javascript,'+encodeURIComponent('export const recordShortTermRecalls=globalThis.pureOriginalRecall;');
 const code=`export function search(){
   import(${JSON.stringify(target)}).then(({recordShortTermRecalls})=>recordShortTermRecalls()).catch(()=>{});
   return globalThis.pureOriginalPublicResult;
 }\n//# sourceURL=file:///tmp/pure-recall-source.mjs`;
 return await import('data:text/javascript,'+encodeURIComponent(code));
}
'''
    script = ("import {observeOriginalSearchEffects} from " + json.dumps(HELPER.as_uri()) + ";\n"
              + setup + body + "\neffects.stop();console.log(JSON.stringify({builtinOnly:true,rows:rows.length}));")
    finished = subprocess.run([str(node), "--input-type=module", "--eval", script],
        cwd=tmp_path, capture_output=True, text=True, timeout=20,
        env={"PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC"}, check=False)
    assert finished.returncode == 0, finished.stderr
    assert json.loads(finished.stdout)["builtinOnly"] is True


def test_real_recall_chain_pending_before_public_return_waits_genuine_completion(node, tmp_path):
    _run(node, tmp_path, r'''
const held=deferred(),originalRecallResult={unchanged:'actual recall return'},publicResult={unchanged:'public result'};
let called=0,completed=false;
globalThis.pureOriginalPublicResult=publicResult;
globalThis.pureOriginalRecall=async()=>{called++;await held.promise;completed=true;return originalRecallResult;};
const search=await importSearch();effects.begin('query');
const returned=als.run(scope,()=>search.search());assert.equal(returned,publicResult);
effects.settled('query',{status:'fulfilled',requiresRecall:true});
let joined=false;const waiting=effects.awaitEffects('query',[owner]).then(value=>{joined=true;return value;});
await turn();assert.equal(called,1);assert.equal(completed,false);assert.equal(joined,false);
held.release();const receipt=await waiting;
assert.equal(completed,true);assert.equal(joined,true);assert.equal(called,1);
assert.equal(receipt.jobs.length,2);assert.equal(receipt.jobs[1].triggerAsyncId,receipt.jobs[0].asyncId);
for(const job of receipt.jobs)assert.deepEqual(deserialize(Buffer.from(job.settlement.value.v8Hex,'hex')),originalRecallResult);
effects.assertDrained();assert.deepEqual(failures,[]);
''')


@pytest.mark.parametrize("kind,admitted", [("forget-index-fence-v3", True), ("forget-index-fence-v2", False)])
def test_real_runtime_entry_admits_only_frozen_v3_before_any_original_import(node, tmp_path, kind, admitted):
    from equivalence.forget_index_fence_v3 import build_cases

    value = build_cases()[0]["input"]
    value["kind"] = kind
    state = tmp_path / "state-is-a-file"
    state.write_bytes(b"A valid admission must reach fixture directory setup, never an original import.")
    module = (ROOT / "equivalence/forget-index-fence-runtime.mjs").as_uri()
    script = ("import {runForgetIndexFenceRuntime} from " + json.dumps(module) + ";\n"
              "const input=" + json.dumps(value) + ";\n"
              "try { await runForgetIndexFenceRuntime(input,"
              + json.dumps({"runtimeRoot": str(tmp_path / "never-imported-original"), "stateDirectory": str(state)})
              + ");throw Error('Expected a pre-import fixture failure');} catch(error){"
              "console.log(JSON.stringify({code:error.code??null,message:error.message}));}")
    finished = subprocess.run([str(node), "--input-type=module", "--eval", script],
        cwd=tmp_path, capture_output=True, text=True, timeout=10,
        env={"PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC"}, check=False)
    assert finished.returncode == 0, finished.stderr
    error = json.loads(finished.stdout)
    if admitted:
        assert error["code"] in {"ENOTDIR", "EEXIST"}
    else:
        assert error == {"code": None, "message": "Owned original fixture required"}


def test_actual_background_set_preserves_member_identity_and_waits_outer_cleanup(node, tmp_path):
    _run(node, tmp_path, r'''
const held=deferred(),originalResult={original:'publisher result'};let syncCalls=0,cleanup=false;
effects.begin('query');
const queued=als.run(scope,()=>syntheticOwnedPublisher((async()=>{syncCalls++;await held.promise;cleanup=true;return originalResult;})()));
assert.equal(owner.activeBackgroundSearchSyncs.has(queued),true);
effects.settled('query',{status:'fulfilled',requiresRecall:false});
let joined=false;const waiting=effects.awaitEffects('query',[owner]).then(value=>{joined=true;return value;});
await turn();assert.equal(joined,false);assert.equal(cleanup,false);assert.equal(syncCalls,1);
held.release();const receipt=await waiting;
assert.equal(cleanup,true);assert.equal(syncCalls,1);assert.equal(receipt.jobs.length,1);
assert.equal(receipt.queueReads[0].promiseRefs[0],ref(queued));assert.equal(receipt.queueReads[0].setRef,ref(owner.activeBackgroundSearchSyncs));
assert.deepEqual(deserialize(Buffer.from(receipt.jobs[0].settlement.value.v8Hex,'hex')),originalResult);
assert.equal(owner.activeBackgroundSearchSyncs.size,0);effects.assertDrained();assert.deepEqual(failures,[]);
''')


def test_original_recall_rejection_is_retained_while_original_catch_still_swallows_it(node, tmp_path):
    _run(node, tmp_path, r'''
const originalError=Object.assign(new Error('genuine labelled recall failure'),{code:'PURE_ACTUAL'});
globalThis.pureOriginalPublicResult={unchanged:true};globalThis.pureOriginalRecall=async()=>{throw originalError;};
const search=await importSearch();effects.begin('query');const result=als.run(scope,()=>search.search());
effects.settled('query',{status:'fulfilled',requiresRecall:true});const receipt=await effects.awaitEffects('query',[owner]);
assert.deepEqual(result,{unchanged:true});assert.equal(receipt.jobs[0].settlement.status,'rejected');
assert.equal(receipt.jobs[0].settlement.errorRef,ref(originalError));
assert.equal(deserialize(Buffer.from(receipt.jobs[0].settlement.error.v8Hex,'hex')).message,originalError.message);
assert.equal(receipt.jobs[1].settlement.status,'fulfilled');
assert.equal(deserialize(Buffer.from(receipt.jobs[1].settlement.value.v8Hex,'hex')),undefined);
assert.deepEqual(failures,[]);
''')


def test_unknown_actual_queue_member_and_missing_recall_hook_fail_closed(node, tmp_path):
    _run(node, tmp_path, r'''
effects.begin('query');effects.settled('query',{status:'fulfilled',requiresRecall:false});
const held=deferred();owner.activeBackgroundSearchSyncs.add(held.promise);
await assert.rejects(effects.awaitEffects('query',[owner]),/lost its labelled original Promise source/);
held.release();owner.activeBackgroundSearchSyncs.clear();
effects.begin('missing');effects.settled('missing',{status:'fulfilled',requiresRecall:true});
await assert.rejects(effects.awaitEffects('missing',[owner]),/missing or ambiguous/);
assert.equal(failures.length,2);
''')


def test_genuine_causal_job_added_during_await_is_joined_without_creating_work(node, tmp_path):
    _run(node, tmp_path, r'''
const first=deferred(),second=deferred();let secondStarted=0;
effects.begin('query');
als.run(scope,()=>syntheticOwnedPublisher((async()=>{await first.promise;secondStarted++;
 syntheticOwnedPublisher(second.promise);})()));
effects.settled('query',{status:'fulfilled',requiresRecall:false});
let joined=false;const waiting=effects.awaitEffects('query',[owner]).then(value=>{joined=true;return value;});
first.release();await turn();assert.equal(secondStarted,1);assert.equal(joined,false);
second.release();const receipt=await waiting;assert.equal(receipt.jobs.length,2);
assert.equal(owner.activeBackgroundSearchSyncs.size,0);effects.assertDrained();assert.deepEqual(failures,[]);
''')


def test_deferred_boundary_keeps_actual_public_settlement_members_after_original_removal(node, tmp_path):
    _run(node, tmp_path, r'''
const held=deferred();effects.begin('query');
const actual=als.run(scope,()=>syntheticOwnedPublisher(held.promise));
const publicReceipt=effects.settled('query',{status:'fulfilled',requiresRecall:false},[owner]);
assert.equal(publicReceipt.queueReads[0].stage,'public-settlement');
assert.deepEqual(publicReceipt.queueReads[0].promiseRefs,[ref(actual)]);
held.release('original returned value');await actual;assert.equal(owner.activeBackgroundSearchSyncs.size,0);
const receipt=await effects.awaitEffects('query',[owner]);
assert.equal(receipt.jobs.length,1);assert.equal(receipt.jobs[0].promiseRef,ref(actual));
assert.equal(deserialize(Buffer.from(receipt.jobs[0].settlement.value.v8Hex,'hex')),'original returned value');
effects.assertDrained();assert.deepEqual(failures,[]);
''')
