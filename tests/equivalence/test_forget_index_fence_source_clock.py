"""Builtin-only source-clock controls; no original release owner is imported.

The local adapter runs against real temporary files and real FileHandles. These
checks authenticate the fixture mechanism and grant no parity or product credit.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

from equivalence.model_runtime_authority import prepare_model_node_authority

ROOT = Path(__file__).resolve().parents[2]
CLOCK = ROOT / "equivalence/forget-index-fence-source-clock.mjs"


@pytest.fixture(scope="module")
def node():
    selected = os.environ.get("MEMORY_EQ_NODE")
    path = Path(selected).resolve() if selected else ROOT / "work/node-v24.16.0-linux-x64/bin/node"
    if not path.is_file():
        pytest.skip("No explicitly approved Node for builtin-only filesystem controls; no parity credit")
    prepare_model_node_authority(path)
    return path


def _run(node, tmp_path, body):
    workspace = tmp_path / "local fixture workspace"
    workspace.mkdir()
    code = f'''
import assert from 'node:assert/strict';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {{installSourceClock}} from {json.dumps(CLOCK.as_uri())};
const workspaceDir={json.dumps(str(workspace))};
const tick=1794614411;
const ns=seconds=>BigInt(seconds)*1_000_000_000n;
const blockList=clock=>{{const value=clock.blocked();return Array.isArray(value)?value:(value?[value]:[]);}};
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const rows=[];
const originalDateNow=Date.now,originalTimeout=setTimeout,originalPerformance=performance.now;
{body}
assert.equal(Date.now,originalDateNow);
assert.equal(setTimeout,originalTimeout);
assert.equal(performance.now,originalPerformance);
process.stdout.write(JSON.stringify({{fixtureKind:'builtin-only-source-clock',originalReleaseModulesImported:false,rows}})+'\\n');
'''
    result = subprocess.run(
        [str(node), "--input-type=module", "--eval", code],
        cwd=tmp_path, capture_output=True, text=True, timeout=20,
        env={"PATH": str(node.parent) + os.pathsep + os.defpath, "LANG": "C.UTF-8", "TZ": "UTC"},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    returned = json.loads(result.stdout)
    assert returned["fixtureKind"] == "builtin-only-source-clock"
    assert returned["originalReleaseModulesImported"] is False
    return returned


_SETUP = r'''
const actor='labelled-builtin-actor';
const ticksByCall={
 'promotion:seed':{ordinal:91,actor,wallClockNowMs:Date.now(),atimeMs:tick*1000,mtimeMs:tick*1000},
 'promotion:other':{ordinal:4,actor,wallClockNowMs:Date.now(),atimeMs:(tick+7)*1000,mtimeMs:(tick+7)*1000}
};
const qualifyStack=(stack,kind)=>stack.includes('syntheticOwned')?{kind,fixture:'labelled-builtin-only'}:null;
const clock=installSourceClock({workspaceDir,actor,ticksByCall,event:(name,row)=>rows.push({name,row}),qualifyStack});
'''


def test_v5_completed_version_is_captured_before_later_writer_without_rereading(node, tmp_path):
    setup = _SETUP.replace("qualifyStack});", "qualifyStack,captureVersions:true});")
    _run(node, tmp_path, setup + r'''
const target=path.join(workspaceDir,'MEMORY.md');
async function syntheticOwnedWrite(text){const handle=await fsp.open(target,'w');try{await handle.writeFile(text);}finally{await handle.close();}}
clock.beginCall('promotion:seed');await syntheticOwnedWrite('first committed source');clock.endCall();
const captured=clock.captureCompletedVersions('promotion:seed');
assert.equal(captured.versions.length,1);assert.equal(captured.versions[0].sha256,hash(Buffer.from('first committed source')));
const first=structuredClone(captured);
clock.beginCall('promotion:other');await syntheticOwnedWrite('later actual source');clock.endCall();
assert.deepEqual(clock.captureCompletedVersions('promotion:seed'),first);
assert.equal(clock.captureCompletedVersions('promotion:other').versions[0].sha256,hash(Buffer.from('later actual source')));
assert.equal(captured.versions[0].stat.mtimeNs,ns(tick).toString());assert.equal(clock.blocked(),false);clock.restore();
''')


def test_v5_real_deletion_and_zero_mutations_are_distinct_completion_facts(node, tmp_path):
    setup = _SETUP.replace("qualifyStack});", "qualifyStack,captureVersions:true});")
    _run(node, tmp_path, r'''
const target=path.join(workspaceDir,'selected.md');await fsp.writeFile(target,'actual original input');
''' + setup + r'''
clock.beginCall('promotion:seed');clock.endCall();
assert.deepEqual(clock.captureCompletedVersions('promotion:seed').versions,[]);
async function syntheticOwnedDeletion(){return await fsp.unlink(target);}
clock.beginCall('promotion:other');const originalReturn=await syntheticOwnedDeletion();clock.endCall();
assert.equal(originalReturn,undefined);const captured=clock.captureCompletedVersions('promotion:other');
assert.equal(captured.versions.length,1);assert.equal(captured.versions[0].kind,'deleted');
assert.equal(captured.versions[0].path,target);assert.equal(fs.existsSync(target),false);
assert.ok(clock.receipts().some(row=>row.event==='source-clock-deletion'&&row.atNs===captured.versions[0].committedAtNs));
assert.equal(clock.blocked(),false);clock.restore();
''')


def test_atomic_stage_is_dated_after_real_full_write_and_sync_before_original_rename(node, tmp_path):
    _run(node, tmp_path, r'''
const target=path.join(workspaceDir,'MEMORY.md'),stage=path.join(workspaceDir,'.memory-stage.tmp');
await fsp.writeFile(target,'old source\n');
const originalRename=fsp.rename;
let held,atRename,realSyncs=0;
fsp.rename=async function syntheticOriginalRename(from,to){
 atRename=await held.stat({bigint:true});
 const named=await fsp.lstat(from,{bigint:true});
 assert.equal(named.ino,atRename.ino);
 assert.equal(atRename.atimeNs,ns(tick));
 assert.equal(atRename.mtimeNs,ns(tick));
 assert.equal(realSyncs,1);
 assert.equal(await fsp.readFile(target,'utf8'),'old source\n');
 return originalRename.call(this,from,to);
};
''' + _SETUP + r'''
async function syntheticOwnedAtomic(){
 held=await fsp.open(stage,'wx',0o600);
 const nativeSync=held.sync;
 held.sync=function(...args){realSyncs++;return nativeSync.apply(this,args);};
 try{
  // This is the actual fs-safe portable writer API; it bypasses FileHandle.writeFile.
  await fsp.writeFile(held,'new exact source bytes\n');
  await held.sync();
  return await fsp.rename(stage,target);
 }finally{await held.close();}
}
try{
 clock.beginCall('promotion:seed');
 assert.equal(await syntheticOwnedAtomic(),undefined);
 clock.endCall();
 assert.equal(blockList(clock).length,0);
 const final=await fsp.stat(target,{bigint:true});
 assert.equal(final.ino,atRename.ino);
 assert.equal(final.mtimeNs,ns(tick));
 assert.equal(await fsp.readFile(target,'utf8'),'new exact source bytes\n');
 const controls=clock.receipts().filter(row=>row.event==='source-clock-control');
 assert.equal(controls.length,1);
 assert.equal(controls[0].status,'clocked');
 assert.equal(controls[0].operation,'atomic');
 assert.equal(controls[0].before.sha256,hash(Buffer.from('new exact source bytes\n')));
 assert.equal(controls[0].tick.mtimeMs,tick*1000);
 assert.equal(controls[0].writes.some(write=>write.method==='fs.promises.writeFile'&&write.status==='fulfilled'),true);
 assert.equal(controls[0].syncs.length,1);
 assert.equal(controls[0].utimes.return.v8Hex.length>0,true);
 assert.equal(typeof controls[0].before.fdStat.ctimeNs,'string');
 assert.equal(typeof controls[0].after.fdStat.ctimeNs,'string');
}finally{clock.restore();fsp.rename=originalRename;}
''')


@pytest.mark.parametrize("writer", ["write", "writeFile", "fs.promises.writeFile"])
def test_in_place_exact_handle_is_dated_after_original_sync_and_before_original_close(node, tmp_path, writer):
    body = r'''
const target=path.join(workspaceDir,'notes.txt');
await fsp.writeFile(target,'base:');
const originalOpen=fsp.open;
let closeCut,selectedHandle,realSyncs=0;
fsp.open=async function syntheticOriginalOpen(...args){
 const handle=await originalOpen.apply(this,args);
 if(args[0]===target){
  selectedHandle=handle;
  const nativeClose=handle.close,nativeSync=handle.sync;
  handle.sync=function(...values){realSyncs++;return nativeSync.apply(this,values);};
  handle.close=async function(...values){
   closeCut=await this.stat({bigint:true});
   assert.equal(this,selectedHandle);
   assert.equal(closeCut.atimeNs,ns(tick));
   assert.equal(closeCut.mtimeNs,ns(tick));
   assert.equal(realSyncs,1);
   return nativeClose.apply(this,values);
  };
 }
 return handle;
};
''' + _SETUP + r'''
async function syntheticOwnedAppend(){
 const handle=await fsp.open(target,'a+');
 try{
  const payload=Buffer.from('appended\n');
  __WRITE__
  await handle.sync();
 }finally{await handle.close();}
}
try{
 clock.beginCall('promotion:seed');
 await syntheticOwnedAppend();
 clock.endCall();
 assert.equal(blockList(clock).length,0);
 const final=await fsp.stat(target,{bigint:true});
 assert.equal(final.ino,closeCut.ino);
 assert.equal(final.mtimeNs,ns(tick));
 assert.equal(await fsp.readFile(target,'utf8'),'base:appended\n');
 const control=clock.receipts().find(row=>row.event==='source-clock-control');
 assert.equal(control.operation,'inPlace');
 assert.equal(control.status,'clocked');
 assert.equal(control.syncs.length,1);
 assert.equal(control.committed,true);
}finally{clock.restore();fsp.open=originalOpen;}
'''
    write = {"write": "await handle.write(payload,0,payload.length,null);",
             "writeFile": "await handle.writeFile(payload);",
             "fs.promises.writeFile": "await fsp.writeFile(handle,payload);"}[writer]
    _run(node, tmp_path, body.replace("__WRITE__", write))


def test_clock_retains_original_rename_error_object_and_fields(node, tmp_path):
    _run(node, tmp_path, r'''
const stage=path.join(workspaceDir,'.stage.tmp'),target=path.join(workspaceDir,'missing','MEMORY.md');
const originalRename=fsp.rename;
let originalError;
fsp.rename=async function syntheticOriginalRename(...args){
 try{return await originalRename.apply(this,args);}catch(error){originalError=error;throw error;}
};
''' + _SETUP + r'''
async function syntheticOwnedRejectedRename(){
 const handle=await fsp.open(stage,'wx',0o600);
 try{await fsp.writeFile(handle,'complete stage');await handle.sync();return await fsp.rename(stage,target);}
 finally{await handle.close();}
}
try{
 clock.beginCall('promotion:seed');
 let caught;
 try{await syntheticOwnedRejectedRename();}catch(error){caught=error;}
 clock.endCall();
 assert.equal(caught,originalError);
 assert.equal(caught.code,'ENOENT');
 assert.equal(caught.syscall,'rename');
 assert.equal(caught.path,stage);
 assert.equal(caught.dest,target);
 const receipt=clock.receipts().find(row=>row.event==='source-clock-control');
 assert.equal(receipt.rename.error.code,'ENOENT');
 assert.equal(receipt.committed,undefined);
 assert.equal(blockList(clock).length,0);
}finally{clock.restore();fsp.rename=originalRename;}
''')


def test_clock_control_failure_blocks_custody_without_replacing_original_public_error(node, tmp_path):
    _run(node, tmp_path, r'''
const stage=path.join(workspaceDir,'.stage.tmp'),target=path.join(workspaceDir,'MEMORY.md');
const originalOpen=fsp.open;
let timestampError;
fsp.open=async function syntheticOriginalOpen(...args){
 const handle=await originalOpen.apply(this,args);
 if(args[0]===stage){const nativeUtimes=handle.utimes;
  handle.utimes=async function(...ignored){
   // A builtin-only control fault; this invokes the real FileHandle API.
   try{return await nativeUtimes.call(this,Number.NaN,Number.NaN);}catch(error){timestampError=error;throw error;}
  };
 }
 return handle;
};
''' + _SETUP + r'''
const originalPublicError=Object.assign(new Error('Labelled local owner failure after its real write'),{code:'LOCAL_OWNER_FAILURE'});
async function syntheticOwnedPublicCaller(){
 const handle=await fsp.open(stage,'wx',0o600);
 try{await fsp.writeFile(handle,'actual completed source');await handle.sync();await fsp.rename(stage,target);}
 finally{await handle.close();}
 throw originalPublicError;
}
try{
 clock.beginCall('promotion:seed');
 let caught;
 try{await syntheticOwnedPublicCaller();}catch(error){caught=error;}
 clock.endCall();
 assert.equal(caught,originalPublicError);
 assert.equal(caught.code,'LOCAL_OWNER_FAILURE');
 assert.equal(await fsp.readFile(target,'utf8'),'actual completed source');
 assert.equal(timestampError instanceof Error,true);
 assert.equal(blockList(clock).length>0,true);
 const control=clock.receipts().find(row=>row.event==='source-clock-control');
 assert.equal(control.status,'blocked');
 assert.equal(control.utimes.error.message,timestampError.message);
 assert.equal(control.rename.error,undefined);
}finally{clock.restore();fsp.open=originalOpen;}
''')


def test_literal_call_tick_is_independent_of_private_writes_and_input_ordinal(node, tmp_path):
    _run(node, tmp_path, _SETUP + r'''
async function syntheticOwnedAtomic(name,parts){
 const stage=path.join(workspaceDir,'.'+name+'.tmp'),target=path.join(workspaceDir,name);
 const handle=await fsp.open(stage,'wx',0o600);
 try{
  for(const part of parts){const bytes=Buffer.from(part);await handle.write(bytes,0,bytes.length,null);}
  await handle.sync();await fsp.rename(stage,target);
 }finally{await handle.close();}
 return (await fsp.stat(target,{bigint:true})).mtimeNs;
}
try{
 clock.beginCall('promotion:seed');
 const one=await syntheticOwnedAtomic('one.md',['a single write']);
 const many=await syntheticOwnedAtomic('many.txt',['m','u','l','t','i','p','l','e',' writes']);
 clock.endCall();
 assert.equal(one,ns(tick));assert.equal(many,ns(tick));
 clock.beginCall('promotion:other');
 const other=await syntheticOwnedAtomic('other.md',['different public call']);
 clock.endCall();
 assert.equal(other,ns(tick+7));
 assert.equal(blockList(clock).length,0);
 const controls=clock.receipts().filter(row=>row.event==='source-clock-control');
 assert.equal(controls.length,3);
 assert.deepEqual(controls.map(row=>row.ordinal),[91,91,4]);
 assert.equal(controls[0].writes.length,1);
 assert.equal(controls[1].writes.length>controls[0].writes.length,true);
 assert.deepEqual(controls.map(row=>row.utimes.arguments),[[tick,tick],[tick,tick],[tick+7,tick+7]]);
}finally{clock.restore();}
''')


def test_different_committed_versions_same_call_path_fail_closed_after_original_io(node, tmp_path):
    _run(node, tmp_path, _SETUP + r'''
const target=path.join(workspaceDir,'MEMORY.md');
async function syntheticOwnedPublish(bytes,name){
 const stage=path.join(workspaceDir,name),handle=await fsp.open(stage,'wx',0o600);
 try{await fsp.writeFile(handle,bytes);await handle.sync();return await fsp.rename(stage,target);}
 finally{await handle.close();}
}
try{
 clock.beginCall('promotion:seed');
 assert.equal(await syntheticOwnedPublish('first committed bytes','.first.tmp'),undefined);
 assert.equal(await syntheticOwnedPublish('second committed bytes','.second.tmp'),undefined);
 clock.endCall();
 assert.equal(await fsp.readFile(target,'utf8'),'second committed bytes');
 assert.equal(blockList(clock).length>0,true);
 const controls=clock.receipts().filter(row=>row.event==='source-clock-control');
 assert.equal(controls.length,2);
 assert.equal(controls[0].status,'clocked');
 assert.equal(controls[1].status,'blocked');
 assert.equal(controls[1].controlError.message.includes('different source byte revisions'),true);
 assert.equal(controls[1].rename.error,undefined);
}finally{clock.restore();}
''')


def test_same_bytes_may_publish_twice_without_a_private_write_ordinal(node, tmp_path):
    _run(node, tmp_path, _SETUP + r'''
const target=path.join(workspaceDir,'MEMORY.md');
async function syntheticOwnedPublish(name){
 const stage=path.join(workspaceDir,name),handle=await fsp.open(stage,'wx',0o600);
 try{await fsp.writeFile(handle,'same final bytes');await handle.sync();await fsp.rename(stage,target);}
 finally{await handle.close();}
}
try{
 clock.beginCall('promotion:seed');
 await syntheticOwnedPublish('.first.tmp');await syntheticOwnedPublish('.second.tmp');
 clock.endCall();
 assert.equal(blockList(clock).length,0);
 const controls=clock.receipts().filter(row=>row.event==='source-clock-control');
 assert.equal(controls.length,2);
 assert.equal(controls[0].before.sha256,controls[1].before.sha256);
 assert.equal(controls[0].handleRef===controls[1].handleRef,false);
 assert.deepEqual(controls.map(row=>row.utimes.arguments),[[tick,tick],[tick,tick]]);
}finally{clock.restore();}
''')


def test_only_owned_markdown_text_sources_are_clocked_and_restore_unpatches_builtins(node, tmp_path):
    _run(node, tmp_path, r'''
const beforeOpen=fsp.open,beforeWrite=fsp.writeFile,beforeRename=fsp.rename,beforeUnlink=fsp.unlink;
''' + _SETUP + r'''
async function syntheticOwnedNonSources(){
 for(const relative of ['agent.sqlite','state.json','gate.receipt']){
  const filename=path.join(workspaceDir,relative),handle=await fsp.open(filename,'w');
  try{await handle.writeFile('untouched by the functional source clock');await handle.sync();}
  finally{await handle.close();}
 }
 const outside=path.join(path.dirname(workspaceDir),'outside.md'),handle=await fsp.open(outside,'w');
 try{await handle.writeFile('outside the authorized source root');await handle.sync();}finally{await handle.close();}
}
try{
 clock.beginCall('promotion:seed');await syntheticOwnedNonSources();clock.endCall();
 assert.equal(clock.receipts().some(row=>row.event==='source-clock-control'),false);
 assert.equal(blockList(clock).length,0);
}finally{clock.restore();}
assert.equal(fsp.open,beforeOpen);assert.equal(fsp.writeFile,beforeWrite);
assert.equal(fsp.rename,beforeRename);assert.equal(fsp.unlink,beforeUnlink);
''')


def test_replaced_stage_name_is_not_authority_to_date_a_different_inode(node, tmp_path):
    _run(node, tmp_path, r'''
const primitiveRename=fsp.rename,primitiveWrite=fsp.writeFile;
''' + _SETUP + r'''
const stage=path.join(workspaceDir,'.stage.tmp'),displaced=path.join(workspaceDir,'.displaced.tmp'),target=path.join(workspaceDir,'MEMORY.md');
let originalStage,originalMtime;
async function syntheticOwnedStageSwap(){
 const handle=await fsp.open(stage,'wx',0o600);
 try{
  await fsp.writeFile(handle,'the retained original stage');await handle.sync();
  originalStage=await handle.stat({bigint:true});originalMtime=originalStage.mtimeNs;
  // An independent local fixture replaces only the name, without changing the held fd.
  await primitiveRename(stage,displaced);await primitiveWrite(stage,'another inode at the old name');
  const returned=await fsp.rename(stage,target);
  assert.equal(returned,undefined);
  assert.equal((await handle.stat({bigint:true})).mtimeNs,originalMtime);
 }finally{await handle.close();}
}
try{
 clock.beginCall('promotion:seed');await syntheticOwnedStageSwap();clock.endCall();
 assert.equal(blockList(clock).length>0,true);
 assert.equal(await fsp.readFile(target,'utf8'),'another inode at the old name');
 assert.equal((await fsp.stat(target,{bigint:true})).ino===originalStage.ino,false);
 const control=clock.receipts().find(row=>row.event==='source-clock-control');
 assert.equal(control.status,'blocked');assert.equal(control.utimes,undefined);
}finally{clock.restore();}
''')


def test_absent_original_fsync_stays_absent_and_distinct_atime_mtime_are_literal(node, tmp_path):
    _run(node, tmp_path, r'''
const target=path.join(workspaceDir,'DREAMS.md'),stage=path.join(workspaceDir,'.dreams-stage.tmp');
const originalRename=fsp.rename;
let held,realSyncs=0;
fsp.rename=async function syntheticOriginalRename(...args){
 const observed=await held.stat({bigint:true});
 assert.equal(observed.atimeNs,ns(tick-5));assert.equal(observed.mtimeNs,ns(tick+7));
 assert.equal(realSyncs,0);
 return originalRename.apply(this,args);
};
''' + _SETUP + r'''
ticksByCall['promotion:seed'].atimeMs=(tick-5)*1000;
ticksByCall['promotion:seed'].mtimeMs=(tick+7)*1000;
async function syntheticOwnedUnsyncedAtomic(){
 held=await fsp.open(stage,'wx',0o600);
 const originalSync=held.sync;
 held.sync=function(...args){realSyncs++;return originalSync.apply(this,args);};
 try{await fsp.writeFile(held,'actual complete unsynced bytes');await fsp.rename(stage,target);}
 finally{await held.close();}
}
try{
 clock.beginCall('promotion:seed');await syntheticOwnedUnsyncedAtomic();clock.endCall();
 assert.equal(blockList(clock).length,0);
 const control=clock.receipts().find(row=>row.event==='source-clock-control');
 assert.deepEqual(control.syncs,[]);
 assert.deepEqual(control.utimes.arguments,[tick-5,tick+7]);
 assert.equal(await fsp.readFile(target,'utf8'),'actual complete unsynced bytes');
}finally{clock.restore();fsp.rename=originalRename;}
''')


def test_original_deletion_keeps_absence_and_is_not_replaced_with_a_timestamp_write(node, tmp_path):
    _run(node, tmp_path, r'''
const target=path.join(workspaceDir,'MEMORY.md');await fsp.writeFile(target,'the actual source to remove');
''' + _SETUP + r'''
async function syntheticOwnedDeletion(){return await fsp.unlink(target);}
try{
 clock.beginCall('promotion:seed');assert.equal(await syntheticOwnedDeletion(),undefined);clock.endCall();
 assert.equal(blockList(clock).length,0);
 await assert.rejects(()=>fsp.stat(target),error=>error.code==='ENOENT');
 const receipt=clock.receipts().find(row=>row.event==='source-clock-deletion');
 assert.equal(receipt.path,target);assert.equal(receipt.callKey,'promotion:seed');
 assert.equal(clock.receipts().some(row=>row.event==='source-clock-control'),false);
}finally{clock.restore();}
''')


def test_unqualified_direct_path_write_is_blocked_without_replacing_its_actual_return(node, tmp_path):
    _run(node, tmp_path, _SETUP + r'''
const target=path.join(workspaceDir,'MEMORY.md');
async function syntheticOwnedUnsupportedDirectWrite(){return await fsp.writeFile(target,'the actual direct-path bytes');}
try{
 clock.beginCall('promotion:seed');
 assert.equal(await syntheticOwnedUnsupportedDirectWrite(),undefined);
 clock.endCall();
 assert.equal(await fsp.readFile(target,'utf8'),'the actual direct-path bytes');
 assert.equal(blockList(clock).length>0,true);
 assert.equal(clock.receipts().some(row=>row.event==='source-clock-control'&&row.status==='clocked'),false);
}finally{clock.restore();}
''')


def test_reused_numeric_fd_does_not_transfer_the_previous_filehandle_clock_authority(node, tmp_path):
    _run(node, tmp_path, _SETUP + r'''
const target=path.join(workspaceDir,'MEMORY.md'),stage=path.join(workspaceDir,'.stage.tmp'),json=path.join(workspaceDir,'private.json');
let releasedFd,reusedFd,jsonBeforeClose;
async function syntheticOwnedPublishThenReuse(){
 const stageHandle=await fsp.open(stage,'wx',0o600);releasedFd=stageHandle.fd;
 try{await fsp.writeFile(stageHandle,'owned source');await stageHandle.sync();await fsp.rename(stage,target);}
 finally{await stageHandle.close();}
 const unrelated=await fsp.open(json,'wx',0o600);reusedFd=unrelated.fd;
 try{await fsp.writeFile(unrelated,'unrelated private state');await unrelated.sync();jsonBeforeClose=await unrelated.stat({bigint:true});}
 finally{await unrelated.close();}
}
try{
 clock.beginCall('promotion:seed');await syntheticOwnedPublishThenReuse();clock.endCall();
 assert.equal(releasedFd,reusedFd,'The local denial control must actually reuse the numeric fd');
 assert.equal((await fsp.stat(json,{bigint:true})).mtimeNs,jsonBeforeClose.mtimeNs);
 assert.equal(await fsp.readFile(json,'utf8'),'unrelated private state');
 assert.equal(blockList(clock).length,0);
 const controls=clock.receipts().filter(row=>row.event==='source-clock-control');
 assert.equal(controls.length,1);assert.equal(controls[0].path,target);
}finally{clock.restore();}
''')


@pytest.mark.parametrize("route", ["atomic", "inPlace"])
def test_throwing_receipt_sink_blocks_control_without_preventing_actual_original_io(node, tmp_path, route):
    setup = _SETUP.replace(
        "event:(name,row)=>rows.push({name,row})",
        "event:(name,row)=>{rows.push({name,row});throw sinkFailure;}",
    )
    _run(node, tmp_path, r'''
const sinkFailure=new Error('Labelled synthetic receipt sink failed');
const target=path.join(workspaceDir,'MEMORY.md'),stage=path.join(workspaceDir,'.stage.tmp');
await fsp.writeFile(target,'before source');
''' + setup + f"\nconst route={json.dumps(route)};\n" + r'''
async function syntheticOwnedWriteDespiteReceiptFailure(){
 const handle=await fsp.open(route==='atomic'?stage:target,route==='atomic'?'wx':'r+',0o600);
 try{
  await fsp.writeFile(handle,'actual source after sink failure');
  await handle.sync();
  if(route==='atomic')assert.equal(await fsp.rename(stage,target),undefined);
 }finally{assert.equal(await handle.close(),undefined);}
}
try{
 clock.beginCall('promotion:seed');
 assert.equal(await syntheticOwnedWriteDespiteReceiptFailure(),undefined);
 clock.endCall();
 assert.equal(await fsp.readFile(target,'utf8'),'actual source after sink failure');
 assert.equal(clock.blocked(),true);
 assert.equal(clock.failures().some(row=>row.reason==='receipt-sink-error'),true);
}finally{clock.restore();}
''')


def test_throwing_receipt_sink_does_not_replace_the_actual_original_rename_error(node, tmp_path):
    setup = _SETUP.replace(
        "event:(name,row)=>rows.push({name,row})",
        "event:(name,row)=>{rows.push({name,row});throw sinkFailure;}",
    )
    _run(node, tmp_path, r'''
const sinkFailure=new Error('Labelled synthetic receipt sink failed');
const originalRename=fsp.rename;let actualOriginalError;
fsp.rename=async function syntheticNativeRename(...args){
 try{return await originalRename.apply(this,args);}
 catch(error){actualOriginalError=error;throw error;}
};
''' + setup + r'''
async function syntheticOwnedMissingStage(){
 return await fsp.rename(path.join(workspaceDir,'absent-stage.tmp'),path.join(workspaceDir,'MEMORY.md'));
}
try{
 clock.beginCall('promotion:seed');
 await assert.rejects(syntheticOwnedMissingStage,error=>{
  assert.equal(error,actualOriginalError);assert.equal(error.code,'ENOENT');assert.notEqual(error,sinkFailure);return true;
 });
 clock.endCall();
 assert.equal(clock.blocked(),true);
 assert.equal(clock.failures().some(row=>row.reason==='receipt-sink-error'),true);
}finally{clock.restore();fsp.rename=originalRename;}
''')
