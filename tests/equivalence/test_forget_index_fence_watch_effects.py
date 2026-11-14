"""Builtin-only watcher lifecycle doubles; no original engine or parity credit."""
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
    path = Path(os.environ.get("MEMORY_EQ_NODE", str(ROOT / "work/node-v24.16.0-linux-x64/bin/node")))
    if not path.is_file():
        pytest.skip("Exact Node unavailable; builtin protocol only")
    prepare_model_node_authority(path)
    return path


def run(node, tmp_path, body):
    setup = r'''
import assert from 'node:assert/strict';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import {EventEmitter} from 'node:events';
import {serialize} from 'node:v8';
import {setImmediate as turn} from 'node:timers/promises';
const rows=[],failures=[],refs=new WeakMap();let next=0;
const ref=value=>value!==null&&(typeof value==='object'||typeof value==='function')?
 (refs.has(value)?refs.get(value):(refs.set(value,'builtin-watch-'+(++next)),refs.get(value))):null;
const control=observeOriginalWatchEffects({ref,event:(event,fields)=>rows.push(structuredClone({event,...fields})),
 onFailure:error=>failures.push(error),qualifyTimer:stack=>stack.includes('scheduleWatchSync')?{pure:'timer'}:null,
 qualifySync:stack=>stack.includes('pure-original-watch-sync.mjs:1:')?{pure:'original-sync'}:null,
 qualifyNativeWatch:stack=>stack.includes('pureNativeRegistration')?{pure:'native-watch'}:null,
 qualifyEmitter:stack=>stack.includes('emitOriginalSource')?{pure:'chokidar-emit'}:null});
function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return{promise,resolve,reject};}
const emitter=new EventEmitter(),held=deferred();let syncCalls=0,writeCalls=0;
globalThis.pureWatchSync=()=>{syncCalls++;return held.promise;};
const syncModule=await import('data:text/javascript,'+encodeURIComponent('export async function sync(){\n return await globalThis.pureWatchSync();\n}\n//# sourceURL=file:///tmp/pure-original-watch-sync.mjs'));
const owner={purpose:'default',workspaceDir:process.cwd(),settings:{sync:{watch:true,onSearch:true,onSessionStart:true}},sync:syncModule.sync};
const originalSync=owner.sync;
const watcher={starting:Promise.resolve(),watcher:emitter,nativeMemoryWatchPairs:[],pendingWatchPaths:new Map(),
 pendingReconciliations:new Map(),pendingChange:false,reconcileAll:false,closed:false,reconciling:null,settling:null,
 watchTimer:null,callbacks:{onChange:()=>owner.sync()},
 markMemoryWatchDirty(filename,stats){this.pendingChange=true;this.pendingWatchPaths.set(filename,stats);
  this.scheduleWatchSync();return globalThis.unchangedDirtyReturn;},
 scheduleWatchSync(){if(this.watchTimer)clearTimeout(this.watchTimer);
  this.watchTimer=setTimeout(()=>{this.watchTimer=null;if(this.settling)return;
   const settle=(async()=>{await this.reconciling;
    for(const filename of this.pendingWatchPaths.keys()){
     try{const stats=await fsp.stat(filename);control.observeSourceRead({path:filename,startedAtNs:'1',finishedAtNs:process.hrtime.bigint().toString(),
      sourceOwner:{pure:'stat-owner'},originalStack:'pure snapshotPath',return:{v8Hex:serialize(stats).toString('hex')}});
     }catch(error){control.observeSourceRead({path:filename,startedAtNs:'1',finishedAtNs:process.hrtime.bigint().toString(),
      sourceOwner:{pure:'stat-owner'},originalStack:'pure snapshotPath',error:{name:error.name,message:error.message,code:error.code},
      privateError:{v8Hex:serialize(error).toString('hex')}});}
    }this.pendingWatchPaths.clear();this.pendingChange=false;await this.callbacks.onChange();
   })().catch(()=>{}).finally(()=>{if(this.settling===settle){this.settling=null;if(this.pendingChange)this.scheduleWatchSync();}});
   this.settling=settle;
  },0);},
};owner.fileWatcher=watcher;
emitter.on('change',(...args)=>watcher.markMemoryWatchDirty(...args));
emitter.on('unlink',filename=>watcher.markMemoryWatchDirty(filename,{isDirectory:()=>false}));
function emitOriginalSource(name,...args){return emitter.emit(name,...args);}
const registered=control.register(owner);
emitOriginalSource('ready');await control.ready([owner],'actual-ready');
async function committedVersion(name,text){const filename=process.cwd()+'/'+name;
 await fsp.writeFile(filename,text);writeCalls++;await fsp.utimes(filename,1000,1000);
 const stat=await fsp.stat(filename,{bigint:true});return{kind:'file',path:filename,sha256:'pure-not-an-oracle',versionId:name,
  stat:Object.fromEntries(Object.getOwnPropertyNames(stat).map(key=>[key,typeof stat[key]==='bigint'?stat[key].toString():stat[key]])),
  committedAtNs:process.hrtime.bigint().toString()};}
'''
    script = ("import {observeOriginalWatchEffects} from " + json.dumps(HELPER.as_uri()) + ";\n"
              + setup + body + "\ncontrol.stop();assert.equal(owner.sync,originalSync);"
              "assert.deepEqual(failures,[]);console.log(JSON.stringify({builtinOnly:true,rows:rows.length}));")
    result = subprocess.run([str(node), "--input-type=module", "--eval", script], cwd=tmp_path,
                            capture_output=True, text=True, timeout=20,
                            env={"PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC"}, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["builtinOnly"] is True


def test_waits_for_real_delivery_and_same_original_settling_without_running_sync(node, tmp_path):
    run(node, tmp_path, r'''
const version=await committedVersion('selected.md','actual bytes');let completed=false;
const waiting=control.waitForVersions([owner],'write-completion',[version]).then(value=>{completed=true;return value;});
await turn();assert.equal(completed,false);assert.equal(syncCalls,0);
const originalStats=await fsp.stat(version.path),sameReturn={actual:'dirty-return'};globalThis.unchangedDirtyReturn=sameReturn;
const timer=watcher.watchTimer;emitOriginalSource('change',version.path,originalStats);
emitOriginalSource('change',version.path,originalStats);
assert.ok(rows.some(row=>row.event==='original-watch-fact-return'&&row.returnRef===ref(sameReturn)));
await turn();while(syncCalls===0)await turn();assert.equal(completed,false);assert.equal(syncCalls,1);
held.resolve({actual:'original-sync-result'});const result=await waiting;
assert.equal(writeCalls,1);assert.equal(syncCalls,1);assert.equal(result.owners[0].facts[0].versionId,version.versionId);
assert.ok(result.owners[0].timers.some(row=>row.fired));
assert.ok(rows.some(row=>row.event==='original-watch-timer-replacement'));
assert.equal(timer,null);
''')


def test_original_inner_rejection_is_retained_when_terminal_settle_catches(node, tmp_path):
    run(node, tmp_path, r'''
const version=await committedVersion('selected.md','actual bytes');
const waiting=control.waitForVersions([owner],'rejected-sync',[version]);
emitOriginalSource('change',version.path,await fsp.stat(version.path));
while(syncCalls===0)await turn();held.reject(Object.assign(Error('actual original failure'),{code:'PURE_ORIGINAL_ERROR'}));
const result=await waiting;
assert.ok(result.owners[0].promises.some(row=>row.kind==='watch-sync'&&row.settlement.status==='rejected'&&row.settlement.error.code==='PURE_ORIGINAL_ERROR'));
assert.ok(result.owners[0].promises.some(row=>row.kind!=='watch-sync'&&row.settlement.status==='fulfilled'));
assert.equal(syncCalls,1);
''')


def test_absent_owner_and_no_mutations_are_explicit_absence(node, tmp_path):
    run(node, tmp_path, r'''
const transient={purpose:'cli'},result=await control.waitForVersions([transient,owner],'no-source-mutation',[]);
assert.equal(result.owners[0].absence,'original-transient-owner');
assert.equal(result.owners[1].absence,'no-actual-declared-source-mutations');assert.equal(syncCalls,0);
''')


def test_joins_actual_pending_change_successor_and_canceled_timer(node, tmp_path):
    run(node, tmp_path, r'''
const version=await committedVersion('selected.md','actual bytes');
const waiting=control.waitForVersions([owner],'successor',[version]);
emitOriginalSource('change',version.path,await fsp.stat(version.path));
while(syncCalls===0)await turn();
emitOriginalSource('change',version.path,await fsp.stat(version.path));
while(watcher.watchTimer!==null)await turn();
assert.equal(syncCalls,1);assert.equal(watcher.pendingChange,true);held.resolve('original result');
const result=await waiting;assert.equal(syncCalls,2);
assert.ok(result.owners[0].timers.filter(row=>row.fired).length>=3);
assert.ok(result.owners[0].promises.filter(row=>row.kind==='watch-sync').length>=2);
assert.equal(watcher.pendingChange,false);assert.equal(watcher.watchTimer,null);
''')


def test_real_native_handle_and_callback_registration_are_retained(node, tmp_path):
    run(node, tmp_path, r'''
const delivered=deferred(),actualReturn={actual:'native callback return'};
function pureNativeRegistration(){return fs.watch(process.cwd(),{persistent:false},function actualNativeCallback(...args){
 delivered.resolve(args);return actualReturn;
});}
const handle=pureNativeRegistration();watcher.nativeMemoryWatchPairs.push({main:handle,parent:null});
const ready=await control.ready([owner],'native-ready');
assert.equal(ready.owners[0].nativeHandles[0].handleRef,ref(handle));
await fsp.writeFile(process.cwd()+'/native-event.md','genuine filesystem event');await delivered.promise;
assert.ok(rows.some(row=>row.event==='original-watch-delivery-return'&&row.returnRef===ref(actualReturn)));
handle.close();assert.equal(syncCalls,0);
''')


def test_deleted_version_needs_actual_original_absence_probe(node, tmp_path):
    run(node, tmp_path, r'''
const first=await committedVersion('selected.md','actual bytes');await fsp.unlink(first.path);
const deleted={kind:'deleted',path:first.path,versionId:'actual-deletion',committedAtNs:process.hrtime.bigint().toString()};
const waiting=control.waitForVersions([owner],'actual-delete',[deleted]);let completed=false;waiting.then(()=>{completed=true;});
await turn();assert.equal(completed,false);assert.equal(syncCalls,0);
emitOriginalSource('unlink',deleted.path);while(syncCalls===0)await turn();assert.equal(completed,false);held.resolve();
const result=await waiting;assert.equal(result.owners[0].facts[0].versionId,deleted.versionId);
assert.ok(rows.some(row=>row.event==='original-watch-version-stat-throw'&&row.error.code==='ENOENT'));
''')


def test_watch_target_input_never_becomes_a_completed_business_receipt(node, tmp_path):
    runtime = (ROOT / "equivalence/forget-index-fence-runtime.mjs").as_uri()
    run(node, tmp_path, "const {originalCallEntry,retainCompletedSourceVersions}=await import("
        + json.dumps(runtime) + ");\n" + r'''
const store=new Map(),targets=[{kind:'file',path:'/builtin/actual-path',versionId:'unchanged-target'}];
for(const operation of ['await-original-watch-ready','await-original-watch-effects']){
 const command={id:4,operation,label:'actual-barrier',sourceVersions:targets,sourceVersionReceipts:[{callKey:'promotion:seed'}]};
 const entry=originalCallEntry(command);assert.equal(Object.hasOwn(entry,'sourceVersions'),false);
 assert.deepEqual(entry.arguments,command);assert.deepEqual(command.sourceVersions,targets);
 retainCompletedSourceVersions(store,{id:4,actor:'foreground',pid:100,instance:1});
}
assert.equal(store.size,0);
assert.throws(()=>retainCompletedSourceVersions(store,{sourceVersions:[]}),/Invalid original source call/);
const frame={commandId:3,actor:'foreground',pid:100,instance:1};
const receipt={callKey:'promotion:seed',causalFrame:frame,versions:[{versionId:'actual-version',sha256:'original-private-bytes'}]};
const settled={id:3,actor:'foreground',pid:100,instance:1,sourceVersions:receipt};
retainCompletedSourceVersions(store,settled);assert.equal(store.get('promotion:seed'),receipt);
assert.throws(()=>retainCompletedSourceVersions(store,settled),/Duplicate original source call/);
const distinct={...settled,sourceVersions:{...receipt,versions:[{versionId:'different-version',sha256:'different-bytes'}]}};
assert.throws(()=>retainCompletedSourceVersions(store,distinct),/Duplicate original source call/);
assert.equal(store.get('promotion:seed'),receipt);assert.equal(settled.sourceVersions,receipt);
assert.throws(()=>retainCompletedSourceVersions(new Map(),{...settled,id:999}),/Invalid original source call/);
''')


@pytest.mark.parametrize("member", [6, 7, 8])
def test_crash_reference_is_negative_only_with_pending_marker_and_real_lifecycle_proof(node, tmp_path, member):
    from equivalence.forget_index_fence_v5 import build_cases

    case = build_cases()[member]
    marker = next(gate for gate in case["input"]["gates"]
                  if gate["boundary"] == "forget.marker-committed-before-purge")
    step = next(step for step in case["input"]["steps"] if step.get("label") == "interruptedWatch")
    assert step["afterCalls"] == ["forget:selected"]
    runtime = (ROOT / "equivalence/forget-index-fence-runtime.mjs").as_uri()
    run(node, tmp_path, "const {interruptedSourceCallReceipt,retainCompletedSourceVersions}=await import("
        + json.dumps(runtime) + ");\nconst literalMarker=" + json.dumps(marker) + ";\n" + r'''
// Labelled protocol doubles only; these rows do not claim an original OS run.
const frame={commandId:10,actor:'forgetter',pid:100,instance:1};
const cutoff={kind:'original-source-call-cutoff',callKey:'forget:selected',actor:'forgetter',causalFrame:frame,
 completed:false,cutoffAtNs:'120',before:[],commits:[],deletions:[],handles:[],receipts:[],failures:[]};
const child={actor:'forgetter',pid:100,instance:1,exit:{code:null,signal:'SIGKILL'},kill:{signal:'SIGKILL',atNs:'200'},reapedAtNs:'300'};
const command={id:10,operation:'original-forget',label:'selected',originalEntered:{id:10,actor:'forgetter',pid:100,instance:1,
 apiName:'runMemoryForget',atNs:'100'},termination:{code:null,signal:'SIGKILL',pid:100,reapedAtNs:'300'}};
const gate={...literalMarker,killWhileHeld:true,receipt:{...literalMarker,pid:100,actor:'forgetter',instance:1,
 enteredAtNs:'110',commitReturned:true,wasTransaction:true,sql:'COMMIT',sourceOwner:'forgetWorkspaceMemory.marker-transaction',sourceCallCutoff:cutoff}};
const receipt=interruptedSourceCallReceipt(child,command,gate);
assert.equal(receipt.kind,'original-interrupted-source-call');assert.equal(Object.hasOwn(receipt,'versions'),false);
const emptyStore=new Map();assert.throws(()=>retainCompletedSourceVersions(emptyStore,{sourceVersions:receipt}),/Invalid original source call/);
const joined=await control.waitForVersions([owner],'interruptedWatch',[],[receipt]);
assert.equal(joined.outcome,'interrupted-before-source-publication');
assert.equal(joined.owners[0].absence,'original-call-interrupted-before-source-publication');assert.equal(syncCalls,0);
for(const mutation of [{handles:[{path:'actual-write',writes:[{status:'fulfilled'}]}]},
 {commits:[{committed:true}]},{deletions:['actual-deletion']},{failures:[{reason:'uncertain'}]}]){
 const changed=structuredClone(gate);Object.assign(changed.receipt.sourceCallCutoff,mutation);
 assert.throws(()=>interruptedSourceCallReceipt(child,command,changed),/mutation or uncertainty/);
}
assert.throws(()=>interruptedSourceCallReceipt({...child,exit:{code:0,signal:null}},command,gate),/SIGKILL/);
assert.throws(()=>interruptedSourceCallReceipt(child,{...command,settlement:{actual:'returned'}},gate),/pending original call/);
assert.throws(()=>interruptedSourceCallReceipt(child,command,{...gate,releasedAtNs:'150'}),/held marker/);
assert.throws(()=>interruptedSourceCallReceipt(child,command,{...gate,receipt:{...gate.receipt,sourceCallCutoff:{...cutoff,completed:true}}}),/pending original call/);
''')
