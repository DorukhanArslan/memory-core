"""Pure observer forwarding controls; no original memory engine is executed.

The approved Node imports only the local observer module and creates fake classes.
These unit checks do not provide Native host evidence or acceptance credit.
"""
import json
import os
from pathlib import Path
import subprocess

import pytest

from equivalence.model_runtime_authority import prepare_model_node_authority

ROOT = Path(__file__).resolve().parents[2]
ACTOR = ROOT / "equivalence/host-turn-barrier-runtime.mjs"


@pytest.fixture(scope="module")
def approved_node():
    selected = os.environ.get("MEMORY_EQ_NODE")
    if not selected:
        pytest.skip("Explicit approved Node required; observer units award no acceptance credit")
    return prepare_model_node_authority(Path(selected).resolve())["execPath"]


PRELUDE = r"""
import assert from 'node:assert/strict';
const {createNativeNoticeObserver}=await import(ACTOR_URL);
assert.equal(typeof createNativeNoticeObserver,'function');
const observations={};
let sequence=0,stampFails=false,getterReads=0;
const header={version:1,purpose:'fake-class-forwarding-only',acceptancePointsAwarded:0};
const stamp=()=>{
  if(stampFails)throw new Error('Deliberate observer stamp failure');
  return{sequence:sequence++,atNs:String(1000+sequence),turn:'fake'};
};
const invocations=[];
const payload={value:'the identical original result'};
let getCalls=0,statusCalls=0;
let getReturn,searchReturn,syncReturn,runReturn,publishReturn;
let originalFailure=null;
class FakePublishedDatabase{
  publishShadow(...args){
    invocations.push({method:'publishShadow',receiver:this,args});
    if(originalFailure)throw originalFailure;
    return publishReturn;
  }
}
class MemoryManagerSyncOps{
  recordAutomaticRebuild(...args){
    invocations.push({method:'recordAutomaticRebuild',receiver:this,args});
    if(originalFailure)throw originalFailure;
    this.automaticRebuildNotice.sequence+=1;
    this.automaticRebuildNotice.warning='Original fake writer notice';
    return payload;
  }
  takeSearchMaintenanceRequest(...args){
    invocations.push({method:'takeSearchMaintenanceRequest',receiver:this,args});
    return payload;
  }
  syncAdmitted(...args){
    invocations.push({method:'syncAdmitted',receiver:this,args});
    if(originalFailure)throw originalFailure;
    return syncReturn;
  }
  runSync(...args){
    invocations.push({method:'runSync',receiver:this,args});
    if(originalFailure)throw originalFailure;
    return runReturn;
  }
}
class MemorySearchOrchestration extends MemoryManagerSyncOps{
  search(...args){
    invocations.push({method:'search',receiver:this,args});
    if(originalFailure)throw originalFailure;
    return searchReturn;
  }
}
class MemoryIndexManager extends MemorySearchOrchestration{
  constructor(notice={sequence:0,warning:''}){
    super();
    this.automaticRebuildNotice=notice;
    this.purpose='default';this.agentId='fake-agent';this.workspaceDir='/fake/workspace';
    this.settings={store:{databasePath:'/fake/index.sqlite'}};
    this.publishedDatabase=new FakePublishedDatabase();
  }
  status(...args){
    statusCalls+=1;
    invocations.push({method:'status',receiver:this,args});
    if(originalFailure)throw originalFailure;
    return payload;
  }
  static get(...args){
    getCalls+=1;
    invocations.push({method:'get',receiver:this,args});
    if(originalFailure)throw originalFailure;
    return getReturn;
  }
}
const watched=[
  [MemoryManagerSyncOps.prototype,'recordAutomaticRebuild'],
  [MemoryManagerSyncOps.prototype,'takeSearchMaintenanceRequest'],
  [MemoryManagerSyncOps.prototype,'syncAdmitted'],
  [MemoryManagerSyncOps.prototype,'runSync'],
  [MemorySearchOrchestration.prototype,'search'],
  [MemoryIndexManager.prototype,'status'],
  [MemoryIndexManager,'get'],
  [FakePublishedDatabase.prototype,'publishShadow'],
];
const descriptors=watched.map(([owner,name])=>Object.getOwnPropertyDescriptor(owner,name));
const observer=createNativeNoticeObserver(MemoryIndexManager,{observations,stamp,header});
assert.equal(getCalls,0,'Observer installation must not acquire a manager');
assert.equal(statusCalls,0,'Observer installation must not ask for status');
const owner=new MemoryIndexManager();
const argument={reason:'fake caller input'},otherArgument={nested:{identity:'unchanged'}};
const lastInvocation=method=>invocations.filter(row=>row.method===method).at(-1);
const assertInvocation=(method,receiver,args)=>{
  const actual=lastInvocation(method);assert.ok(actual);
  assert.equal(actual.receiver,receiver);
  assert.equal(actual.args.length,args.length);
  args.forEach((value,index)=>assert.equal(actual.args[index],value));
};
"""


PROBES = {
    "sync-values-receiver-and-arguments": r"""
assert.equal(Reflect.apply(owner.recordAutomaticRebuild,owner,[argument,otherArgument]),payload);
assertInvocation('recordAutomaticRebuild',owner,[argument,otherArgument]);
assert.equal(Reflect.apply(owner.status,owner,[argument]),payload);
assertInvocation('status',owner,[argument]);
assert.equal(owner.takeSearchMaintenanceRequest(argument),payload);
assertInvocation('takeSearchMaintenanceRequest',owner,[argument]);
const call=observations.calls.find(row=>row.method==='recordAutomaticRebuild');
assert.ok(call);assert.equal(typeof call.originalFunctionRef,'string');
assert.equal(typeof call.originalReturnRef,'string');assert.equal(typeof call.argsRef,'string');
assert.ok(Number.isInteger(call.enterSeq));assert.ok(Number.isInteger(call.returnSeq));
assert.equal(getCalls,0);assert.equal(statusCalls,1);
""",
    "original-promises-and-settlement": r"""
let release;
const promised=new Promise(resolve=>{release=resolve;});
searchReturn=promised;syncReturn=promised;runReturn=promised;
assert.equal(owner.search(argument,otherArgument),promised);
assert.equal(owner.syncAdmitted(argument,otherArgument),promised);
assert.equal(owner.runSync(argument,otherArgument),promised);
for(const method of ['search','syncAdmitted','runSync']){
  assertInvocation(method,owner,[argument,otherArgument]);
  const call=observations.calls.find(row=>row.method===method);
  assert.ok(call);assert.equal(call.returnKind,'promise');
  assert.equal(typeof call.originalReturnRef,'string');
}
release(payload);assert.equal(await promised,payload);
for(const method of ['search','syncAdmitted','runSync']){
  const call=observations.calls.find(row=>row.method===method);
  assert.ok(Number.isInteger(call.settleSeq));
}
assert.equal(getCalls,0);assert.equal(statusCalls,0);
""",
    "original-thrown-and-rejected-errors": r"""
const failure=new Error('The exact original operation error');originalFailure=failure;
for(const method of ['recordAutomaticRebuild','status','search','syncAdmitted','runSync']){
  assert.throws(()=>owner[method](argument),error=>error===failure);
  assertInvocation(method,owner,[argument]);
}
originalFailure=null;
const rejected=Promise.reject(failure);searchReturn=rejected;
assert.equal(owner.search(argument),rejected);
await assert.rejects(rejected,error=>error===failure);
""",
    "declaring-parent-descriptor-and-restore": r"""
assert.notEqual(Object.getOwnPropertyDescriptor(MemoryManagerSyncOps.prototype,'recordAutomaticRebuild').value,
  descriptors[0].value,'The actual declaring parent is observed');
assert.equal(Object.hasOwn(MemoryIndexManager.prototype,'recordAutomaticRebuild'),false);
assert.equal(Object.hasOwn(MemorySearchOrchestration.prototype,'recordAutomaticRebuild'),false);
observer.checkpoint('fake-before-restore',{label:'no extra call'});
assert.equal(getCalls,0);assert.equal(statusCalls,0);
observer.restore();observer.restore();
watched.forEach(([target,name],index)=>assert.deepEqual(
  Object.getOwnPropertyDescriptor(target,name),descriptors[index]));
assert.equal(Object.hasOwn(MemoryIndexManager.prototype,'recordAutomaticRebuild'),false);
assert.equal(owner.recordAutomaticRebuild(argument),payload);
""",
    "shared-notice-distinct-managers": r"""
const shared={sequence:0,warning:''};
const first=new MemoryIndexManager(shared),second=new MemoryIndexManager(shared);
assert.equal(first.recordAutomaticRebuild(argument),payload);
assert.equal(second.recordAutomaticRebuild(otherArgument),payload);
observer.checkpoint('fake-shared-notice',{label:'after both original calls'});
const calls=observations.calls.filter(row=>row.method==='recordAutomaticRebuild');
assert.equal(calls.length,2);assert.notEqual(calls[0].managerRef,calls[1].managerRef);
assert.equal(calls[0].noticeRef,calls[1].noticeRef);
assert.equal(observations.notices.filter(row=>row.noticeRef===calls[0].noticeRef).length,1);
assert.equal(shared.sequence,2);
assert.equal(getCalls,0);assert.equal(statusCalls,0);
""",
    "initial-nonzero-notice-origin-is-unobserved": r"""
const shared={sequence:9,warning:'Pre-existing actual fake notice'};
const late=new MemoryIndexManager(shared);
late.recordAutomaticRebuild(argument);
observer.checkpoint('fake-late-observation',{label:'nonzero initial notice'});
const call=observations.calls.find(row=>row.method==='recordAutomaticRebuild');
const notice=observations.notices.find(row=>row.noticeRef===call.noticeRef);
assert.ok(notice);assert.equal(notice.firstSeenOrigin,'unobserved');
assert.equal(notice.firstSeenSequence,9);assert.equal(shared.sequence,10);
""",
    "snapshots-do-not-invoke-own-getters": r"""
const poisoned=new MemoryIndexManager();
const poison={enumerable:true,configurable:true,get(){getterReads+=1;throw new Error('Getter must stay untouched');}};
Object.defineProperty(poisoned,'unrelatedGetter',poison);
Object.defineProperty(poisoned,'purpose',poison);
Object.defineProperty(poisoned.settings.store,'databasePath',poison);
Object.defineProperty(poisoned.automaticRebuildNotice,'unrelatedGetter',poison);
assert.equal(poisoned.recordAutomaticRebuild(argument),payload);
observer.checkpoint('fake-own-getters',{label:'must inspect data descriptors only'});
assert.equal(getterReads,0);assert.equal(getCalls,0);assert.equal(statusCalls,0);
""",
    "static-get-forwards-the-original-promise": r"""
const promised=Promise.resolve(owner);getReturn=promised;
assert.equal(MemoryIndexManager.get(argument,otherArgument),promised);
assertInvocation('get',MemoryIndexManager,[argument,otherArgument]);
assert.equal(await promised,owner);assert.equal(getCalls,1);assert.equal(statusCalls,0);
observer.checkpoint('fake-after-get',{label:'caller-owned acquisition only'});
assert.equal(getCalls,1);assert.equal(statusCalls,0);
""",
    "actual-publish-shadow-forwarding": r"""
owner.status();
const database=owner.publishedDatabase;
let release;const promised=new Promise(resolve=>{release=resolve;});publishReturn=promised;
assert.equal(database.publishShadow(argument,otherArgument),promised);
assertInvocation('publishShadow',database,[argument,otherArgument]);
release(payload);assert.equal(await promised,payload);
const call=observations.calls.find(row=>row.method==='publishShadow');
assert.ok(call);assert.equal(call.returnKind,'promise');assert.ok(Number.isInteger(call.settleSeq));
const failure=new Error('Original publish error');originalFailure=failure;
assert.throws(()=>database.publishShadow(argument),error=>error===failure);
assertInvocation('publishShadow',database,[argument]);originalFailure=null;
observer.restore();
assert.deepEqual(Object.getOwnPropertyDescriptor(FakePublishedDatabase.prototype,'publishShadow'),descriptors.at(-1));
assert.equal(getCalls,0);assert.equal(statusCalls,1);
""",
    "observer-failure-never-changes-original-behavior": r"""
stampFails=true;
assert.equal(owner.recordAutomaticRebuild(argument),payload);
assertInvocation('recordAutomaticRebuild',owner,[argument]);
assert.doesNotThrow(()=>observer.checkpoint('fake-broken-observer',{label:'passive failure'}));
const failure=new Error('Original failure wins over observer failure');originalFailure=failure;
assert.throws(()=>owner.recordAutomaticRebuild(otherArgument),error=>error===failure);
originalFailure=null;
const promised=Promise.resolve(payload);searchReturn=promised;
assert.equal(owner.search(argument),promised);assert.equal(await promised,payload);
assert.ok(observations.observerFailures.length>0,'Observer failures must remain visible');
assert.equal(getCalls,0);assert.equal(statusCalls,0);
""",
}


@pytest.mark.parametrize("probe", PROBES)
def test_native_notice_observer_preserves_the_original_fake_operation(approved_node, probe):
    script = PRELUDE.replace("ACTOR_URL", json.dumps(ACTOR.as_uri())) + PROBES[probe] + r"""
observer.restore();
process.stdout.write(JSON.stringify({ok:true,probe:PROBE_NAME,acceptancePointsAwarded:0}));
""".replace("PROBE_NAME", json.dumps(probe))
    result = subprocess.run(
        [approved_node, "--input-type=module", "--eval", script], cwd=ROOT,
        capture_output=True, text=True, timeout=15,
        env={"PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC"},
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"ok": True, "probe": probe, "acceptancePointsAwarded": 0}
