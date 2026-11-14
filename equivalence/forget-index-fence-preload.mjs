// Closed call-through authority. Controls pause actual source-owned boundaries;
// neither SQL, module source, worker payloads nor public results are replaced.
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {Console} from 'node:console';
import {registerHooks,syncBuiltinESMExports} from 'node:module';
import childProcess from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {DatabaseSync} from 'node:sqlite';
import {Worker,isMainThread,threadId,parentPort,MessagePort} from 'node:worker_threads';
import {serialize,deserialize} from 'node:v8';
import {mock} from 'node:test';
import {createHook} from 'node:async_hooks';

const hash=value=>crypto.createHash('sha256').update(value).digest('hex');
const contextPath=process.env.MEMORY_EQ_RELEASE_CONTEXT;
if(!contextPath||!path.isAbsolute(contextPath)||fs.realpathSync(contextPath)!==contextPath)throw Error('Owned fence context required');
const bytes=fs.readFileSync(contextPath),context=JSON.parse(bytes),profile=context.forgetIndexFenceV3Profile;
const approved={"forget-index-fence-v3-direct-absent-at-plan-retained-source-other-session-forgotten":"a28d02cc268762203bc31d13f00ce592ff1a296f9a516694c640ee9a05806115","forget-index-fence-v3-keyword-worker-before-forget-enrichment-after":"7f2b2fbd4a7cee358f095a58732f89633147a171c036b218912f13c520a95c50","forget-index-fence-v3-repeat-existing-tombstone-old-full-pending":"b0ab0dd957a78a530f22951261f5e8755204d576d914b4a425237247c6e58287","forget-index-fence-v3-shared-clean-dryrun-unresolved-promotion-controls":"e80853d8cdc780eb06a577715d34c93e3fd51a536e73d33221122a7b3f33f9b7","forget-index-fence-v3-shared-marker-commit-process-kill":"b6aa0ac7f16c1648955ab197b924b6eab41494362c02c3732e508850e48e04a3","forget-index-fence-v3-shared-old-full-complete-forget":"8484e6cb552a05d4550d19c250d63b6983bc4fcae8e882da4ecf089c94a86678","forget-index-fence-v3-shared-postcheck-pending-forget":"959a7677379f513b3271b6d886258dc26429c7479532597634907bb0d0abcb15","forget-index-fence-v3-split-marker-commit-process-kill":"4ff9d176c30b2390020f715d1280b776010662e70f0b16ff47482d2e77eba114","forget-index-fence-v3-split-old-full-complete-forget":"cae43cd5ffbbaf2514abe76258c4a4b4866bcc9b0ef15a84b6dcca4ba063ba4d","forget-index-fence-v3-split-postcheck-pending-forget":"3c07dedecf3f7faddaff2148d5c9afbe0e836a554d024eb4120f919830eafae2","forget-index-fence-v3-stored-promotion-model-plan-before-forget":"22978effc4196cf8c4202387e4ea15188c31d89703635849216d1f09e493ac7d","forget-index-fence-v3-unfenced-on-search-marker-commit-process-kill":"b47372d03e8216b49e59e3e8d443b38d71d2df836d2013db4a02448de5e962e5","forget-index-fence-v3-unfenced-on-search-old-full-complete-forget":"fb798a36b2309c8ceb421f397e07e67a5d4d367102bc3bbf16bce0410519e0d0","forget-index-fence-v4-direct-absent-at-plan-retained-source-other-session-forgotten":"fae07da335b69936216316b8bd4b90fd82faf7bd00bc366cb4e526e7282260cd","forget-index-fence-v4-keyword-worker-before-forget-enrichment-after":"a6b380b07213696094f0cfcb88e74eccb50ae0bfb2328dd6fb157543d74c8001","forget-index-fence-v4-repeat-existing-tombstone-old-full-pending":"4ca62c88948ceacf778a3bd5f03829e6a0c1a88e3991570f856b6ba9a0535c70","forget-index-fence-v4-shared-clean-dryrun-unresolved-promotion-controls":"7771c6d04b4eb6fb3203aecb7edc733f2b9ee507d2b434c4fc4d4d1a2ab9c5ad","forget-index-fence-v4-shared-marker-commit-process-kill":"92794024ce1fd1de0e33b6a245107a959d615c08fe5cf317b913ddbc5427a39e","forget-index-fence-v4-shared-old-full-complete-forget":"c471fe4367a6efa908e2f364d8aea307215fb29a672b50c022df352e211494f2","forget-index-fence-v4-shared-postcheck-pending-forget":"22288ca76a30e9beb3be5e60b5071217b9fd4e09e6cbe02ff06343adfb67d8a6","forget-index-fence-v4-split-marker-commit-process-kill":"ab685413990ac529b50e258914655418bad859c6f60383b64a529467d550be68","forget-index-fence-v4-split-old-full-complete-forget":"8606fa125a9ff1ea3f0ddabdc4791ca5f29a5d61ff3a5c4cf3ca1b3c3268289f","forget-index-fence-v4-split-postcheck-pending-forget":"537d3e16b35f056683a917f08e03423f2cdaaa6f8600919bef4e9e0de74bdc65","forget-index-fence-v4-stored-promotion-model-plan-before-forget":"ff99601c5fdd375690291f1ad52f9e56b5244fa048518cf711c93d76ad657a3b","forget-index-fence-v4-unfenced-on-search-marker-commit-process-kill":"a02bae1e9a35c25d271de47f2f31275c830e006bed65db8f986b2aa71e3cb278","forget-index-fence-v4-unfenced-on-search-old-full-complete-forget":"cdb385a63e1210907e955d8336fc25011b55882656c6ce5d8c42653489018310","forget-index-fence-v5-direct-absent-at-plan-retained-source-other-session-forgotten":"6d90512bef66e38214078a0f3f125fd63548888cc160c02faa2e5b8cf0e9623d","forget-index-fence-v5-keyword-worker-before-forget-enrichment-after":"73d22414857d1eac5b526604d7e7ec0c73d5ddc6d36b16fef4038802e04b2f22","forget-index-fence-v5-repeat-existing-tombstone-old-full-pending":"986401f4bd6df92976bb28c217500d5a2e7502f815a238dfd0f6f1bcac8c2b88","forget-index-fence-v5-shared-clean-dryrun-unresolved-promotion-controls":"501eafdb98cd3a43723b90797edd7cd94913c38266fe257f66a9b8c84ae346c5","forget-index-fence-v5-shared-marker-commit-process-kill":"b209de1acd2ed0784c6155157535d2dfc566a374b3dc38e1a4f52af30e9aae83","forget-index-fence-v5-shared-old-full-complete-forget":"a82f2179e67bbfc8049fd9474afc55426abc16ff5565d12c08dec27fa53ef294","forget-index-fence-v5-shared-postcheck-pending-forget":"3680808de2cb65507b836f2b3b9f6d6bf6068725c7a6f4b50091c94fb4c68690","forget-index-fence-v5-split-marker-commit-process-kill":"9b73bee08dfdc62ee37f6e94ae3a8b48c0ca7ad429f40dfedf5b4f2b49872e1b","forget-index-fence-v5-split-old-full-complete-forget":"5c6774d2d629e408dc5475882f6f99538c443ae3f8bac98fdc40d9db85903eea","forget-index-fence-v5-split-postcheck-pending-forget":"8d407798781efdc21a8bf720796423107ffdabd109ea56d6e328ba42a200192f","forget-index-fence-v5-stored-promotion-model-plan-before-forget":"1b4968b19b84fa74faa31301b6c14f9a8cb37e182e68633fb94bbdf05377036c","forget-index-fence-v5-unfenced-on-search-marker-commit-process-kill":"132fd64957494daaf82d87a27862e9c1595252c49e30f03b5ee24e777c7fe329","forget-index-fence-v5-unfenced-on-search-old-full-complete-forget":"d8ed3c7c235b1ea487ca347782cf35eae3e5ac671e8abe6b127a6bdf96504117"};
const keys=['schemaVersion','kind','runtime','providerMode','fetchPolicy','approvedNodeRuntime',
 'forgetIndexFenceV3Profile','allowedLocal','traceDirectory','evidenceDirectory','stateDirectory',
 'configPath','gateDirectory','approvedReferenceSources','fixtureSourceCaptures'].sort().join();
const profileKeys=['kind','operation','caseId','caseWireSha256','actorClocks','gates','nodeRuntime','acceptancePointsAwarded','sourceWriteClock','searchEffects',
 ...(profile?.kind==='forget-index-fence-v5'?['watchEffects']:[]),
 ...(Object.hasOwn(profile??{},'recoveryNowMs')?['recoveryNowMs']:[])].sort().join();
const literalKind={'forget-index-fence-v3-runtime':'forget-index-fence-v3','forget-index-fence-v4-runtime':'forget-index-fence-v4',
 'forget-index-fence-v5-runtime':'forget-index-fence-v5'}[profile?.operation];
if(Object.keys(context).sort().join()!==keys||context.schemaVersion!==1||context.kind!=='release-oracle-execution'||
 context.providerMode!=='none'||context.fetchPolicy!=='deny'||!literalKind||profile?.kind!==literalKind||!profile.caseId.startsWith(literalKind+'-')||
 Object.keys(profile??{}).sort().join()!==profileKeys||
 profile.acceptancePointsAwarded!==0||
 !Object.hasOwn(approved,profile.caseId)||approved[profile.caseId]!==profile.caseWireSha256||!Array.isArray(profile.gates)||
 profile.searchEffects?.protocol!=='original-search-effects-v3'||
 profile.kind==='forget-index-fence-v5'&&profile.watchEffects?.protocol!=='original-watch-effects-v5'||
 profile.sourceWriteClock?.protocol!=='owned-source-write-clock-v2'||!profile.sourceWriteClock.ticksByCall||
 !profile.actorClocks||Object.keys(profile.actorClocks).length>12||
 JSON.stringify(profile.nodeRuntime)!==JSON.stringify(context.approvedNodeRuntime)||
 context.approvedReferenceSources?.length!==0||context.fixtureSourceCaptures?.length!==0)throw Error('Closed fence capability required');
const own=fs.realpathSync(fileURLToPath(import.meta.url)),folder=path.dirname(own);
const localNames=['forget-index-fence-preload.mjs','forget-index-fence-entry.mjs','forget-index-fence-runtime.mjs','forget-index-fence-source-clock.mjs'];
const permitted=new Map();
function regular(filename){const info=fs.lstatSync(filename);return info.isFile()&&!info.isSymbolicLink()&&info.nlink===1&&fs.realpathSync(filename)===filename;}
if(!Array.isArray(context.allowedLocal)||context.allowedLocal.length!==localNames.length)throw Error('Closed local fence authority required');
for(const item of context.allowedLocal){
 if(!localNames.some(name=>item.path===path.join(folder,name))||permitted.has(item.path)||!regular(item.path)||
  hash(fs.readFileSync(item.path))!==item.sha256)throw Error('Changed or aliased local fence actor');
 permitted.set(item.path,{kind:'oracle',...item});
}
for(const pkg of context.runtime.packages){
 if(fs.realpathSync(pkg.directory)!==pkg.directory)throw Error('Aliased release package');
 for(const file of pkg.files){const filename=path.resolve(pkg.directory,file.path);
  if(!filename.startsWith(pkg.directory+path.sep)||permitted.has(filename)||!/^[0-9a-f]{64}$/.test(file.sha256))throw Error('Invalid release authority');
  permitted.set(filename,{kind:'release',package:pkg.location,path:file.path,sha256:file.sha256});
 }
}
const ownRecord=permitted.get(own);
const actualNode={execPath:fs.realpathSync(process.execPath),nodeVersion:process.version,icuVersion:process.versions.icu,
 unicodeVersion:process.versions.unicode,sha256:hash(fs.readFileSync(process.execPath))};
if(!ownRecord||Object.keys(actualNode).some(key=>actualNode[key]!==context.approvedNodeRuntime?.[key])||
 actualNode.nodeVersion!=='v24.16.0'||actualNode.icuVersion!=='78.3'||actualNode.unicodeVersion!=='17.0'||
 actualNode.sha256!=='b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd')throw Error('Unapproved exact Node authority');
for(const [key,relative]of[['traceDirectory','traces'],['evidenceDirectory','evidence'],['stateDirectory','state'],['gateDirectory','gates']]){
 if(context[key]!==path.join(path.dirname(contextPath),relative)||fs.realpathSync(context[key])!==context[key])throw Error('Unowned fence directory');
}
const actor=process.env.MEMORY_EQ_FIF_ACTOR??'coordinator';
if(!Object.hasOwn(profile.actorClocks,actor))throw Error('Undeclared actual fence actor');
const traceFile=path.join(context.traceDirectory,`${process.pid}-${threadId}.jsonl`);
function trace(row){fs.appendFileSync(traceFile,JSON.stringify({...row,pid:process.pid,ppid:process.ppid,threadId,actor,
 instance:Number(process.env.MEMORY_EQ_FIF_INSTANCE??0)})+'\n',{mode:0o600});}
function authority(url){
 if(url.startsWith('node:'))return;
 if(!url.startsWith('file:')||new URL(url).search||new URL(url).hash)throw Error('Unowned module import');
 const lexical=path.resolve(fileURLToPath(url)),filename=fs.realpathSync(lexical),record=permitted.get(filename);
 if(filename!==lexical||!record||!regular(filename)||hash(fs.readFileSync(filename))!==record.sha256){
  trace({event:'rejected',basename:path.basename(filename)});throw Error('Unverified original fence module');}
 return record;
}
registerHooks({resolve(specifier,ctx,next){const result=next(specifier,ctx),record=authority(result.url);
 if(record&&result.url.endsWith('.node'))trace({event:'resolve-native',...record});return result;},
 load(url,ctx,next){const record=authority(url);if(record)trace({event:'load',...record});return next(url,ctx);}});
const diagnostics=new Console({stdout:process.stderr,stderr:process.stderr});
for(const name of['log','info','debug'])Object.defineProperty(console,name,{value:diagnostics[name].bind(diagnostics),writable:false,configurable:false});
Object.defineProperty(globalThis,'fetch',{value:async()=>{throw Error('Fence reference network fetch denied');},writable:false,configurable:false});
const originalDate=Date,originalTimeout=setTimeout,originalImmediate=setImmediate,originalPerformance=performance.now;
const actorClock=Number(process.env.MEMORY_EQ_FIF_CLOCK_NOW_MS??profile.actorClocks[actor]);
const permittedClocks=new Set([profile.actorClocks[actor],...(profile.recoveryNowMs===undefined?[]:[profile.recoveryNowMs])]);
if(!permittedClocks.has(actorClock))throw Error('Undeclared wall clock phase');
mock.timers.enable({apis:['Date'],now:actorClock});
trace({event:'bootstrap',isMainThread,runtime:actualNode,contextSha256:hash(bytes),preloadSha256:ownRecord.sha256,fetchDenied:true,providerMode:'none'});
trace({event:'forget-index-fence-v3-bootstrap',profile,clock:{owner:'node:test',apis:['Date'],nowMs:Date.now(),
 dateConstructorReplaced:Date!==originalDate,setTimeoutUnchanged:setTimeout===originalTimeout,performanceNowUnchanged:performance.now===originalPerformance}});

const clockModule=await import('./forget-index-fence-source-clock.mjs');
const passiveStore=clockModule.openThreadEventStore({directory:context.evidenceDirectory,token:hash(bytes)});
const sleepCell=new Int32Array(new SharedArrayBuffer(4)),fired=new Set();
const commandScopes=clockModule.createOriginalCommandScope();
const currentCallLabel=()=>commandScopes.current()?.label??null;
let sequence=0,lastReindexRevisionRead=null,sourceClock=null,searchEffects=null,watchEffects=null;
const controlFailures=[];
let activeBrokerRequest=null,heldPublication=null;
const resourceCloseRequests=new WeakMap(),taskRequests=new Map();
const event=(name,fields={})=>{const row={event:name,sequence:++sequence,callLabel:currentCallLabel(),atNs:process.hrtime.bigint().toString(),...fields,
 pid:process.pid,ppid:process.ppid,threadId,actor,instance:Number(process.env.MEMORY_EQ_FIF_INSTANCE??0)};passiveStore.append(row);return row;};
function flush(){try{return passiveStore.flush();}catch(error){controlFailures.push({event:'fixture-control-failure',reason:'passive-flush-failed',
 pid:process.pid,threadId,error:{name:error.name,message:error.message,stack:error.stack}});return null;}}
event('passive-channel-register',passiveStore.identity);
process.once('exit',flush);
const carrier=value=>{try{return{v8Hex:serialize(value).toString('hex')};}catch(error){return{unserializable:{name:error.name,message:error.message}};}};
function setWallClock(nowMs){if(!permittedClocks.has(nowMs))throw Error('Undeclared original wall clock advance');
 const before=Date.now();mock.timers.setTime(nowMs);process.env.MEMORY_EQ_FIF_CLOCK_NOW_MS=String(nowMs);
 event('declared-wall-clock-phase',{before,nowMs,monotonicUnchanged:true});}
function matching(boundary){return profile.gates.filter(gate=>gate.actor===actor&&gate.boundary===boundary&&
 !fired.has(gate.name)&&(!isMainThread||gate.callLabel===currentCallLabel()));}
function pause(boundary,facts={}){
 try{
 for(const gate of matching(boundary)){
  const prefix=path.join(context.gateDirectory,gate.name);
  if(!fs.existsSync(prefix+'.armed'))continue;
  fired.add(gate.name);
  const receipt={...gate,pid:process.pid,ppid:process.ppid,threadId,actor,sequence:++sequence,
   instance:Number(process.env.MEMORY_EQ_FIF_INSTANCE??0),
   enteredAtNs:process.hrtime.bigint().toString(),originalStack:new Error('Actual original fence control').stack,...facts};
  if(profile.kind==='forget-index-fence-v5'&&boundary==='forget.marker-committed-before-purge'){
   receipt.sourceCallCutoff=sourceClock.capturePendingSourceState();
   event('original-source-call-interrupted-cutoff',{gate:gate.name,gateEnterSequence:receipt.sequence,cutoff:receipt.sourceCallCutoff});
  }
  if(boundary==='publication.fence-checked-before-table-writes'&&!isMainThread){
   heldPublication={gate:gate.name,boundary,callLabel:gate.callLabel,gateEnterSequence:receipt.sequence,
    brokerRequestId:activeBrokerRequest?.id,requestRef:activeBrokerRequest?processRef(activeBrokerRequest):null,
    request:carrier(activeBrokerRequest),requestType:activeBrokerRequest?.type,
    requestInput:activeBrokerRequest?.input instanceof Uint8Array?passiveObservation(()=>carrier(deserialize(activeBrokerRequest.input))):null};
  }
  trace({event:'fence-gate-enter',...receipt});
  if(!flush())return;
  clockModule.publishControlFile(prefix+'.hit.json',JSON.stringify(receipt)+'\n');
  if(gate.pause===false)return;
  const deadline=performance.now()+30_000;
  while(!fs.existsSync(prefix+'.release')){if(performance.now()>=deadline)throw Error('Declared fence gate exceeded its real monotonic bound');Atomics.wait(sleepCell,0,0,10);}
  const released=JSON.parse(fs.readFileSync(prefix+'.release','utf8'));
  if(released.wallClockNowMs!==undefined)setWallClock(released.wallClockNowMs);
  event('fence-gate-release',{gate:gate.name,boundary,callLabel:gate.callLabel,gateEnterSequence:receipt.sequence,releaseStep:released});
  flush(); // A real Worker.terminate need not run this worker's exit listener.
 }
 }catch(error){controlFailure('synchronous-gate-control-failed',error,{boundary});}
}
function controlFailure(reason,error,fields={}){const row=event('fixture-control-failure',{reason,...fields,
 error:{name:error.name,message:error.message,stack:error.stack},privateError:carrier(error)});controlFailures.push(row);flush();}
async function pauseAsync(boundary,facts={}){
 try{
 for(const gate of matching(boundary)){
  const prefix=path.join(context.gateDirectory,gate.name);
  if(!fs.existsSync(prefix+'.armed'))continue;
  fired.add(gate.name);
  const mode={'promotion.model-planning-before-final-lock':'deferred-original-model-completion',
   'promotion.source-planned-before-final-lock':'deferred-original-realpath-return'}[boundary]??'deferred-original-worker-reply';
  const planning=mode!=='deferred-original-worker-reply',enteredAtNs=process.hrtime.bigint().toString();
  const planningFields=planning?{commandScope:commandScopes.current(),gateTimeoutMs:30_000,
   gateDeadlineNs:(BigInt(enteredAtNs)+30_000_000_000n).toString()}:{};
  if(planning&&(profile.kind!=='forget-index-fence-v5'||planningFields.commandScope?.operation!=='original-promotion'))
   throw Error('An asynchronous planning gate requires its actual V5 promotion command');
  const receipt={...gate,pid:process.pid,ppid:process.ppid,threadId,actor,sequence:++sequence,
   instance:Number(process.env.MEMORY_EQ_FIF_INSTANCE??0),mode,enteredAtNs,...planningFields,
   originalStack:new Error('Actual original asynchronous fence control').stack,...facts};
  trace({event:'fence-gate-enter',...receipt});if(!flush())return;
  clockModule.publishControlFile(prefix+'.hit.json',JSON.stringify(receipt)+'\n');
  if(gate.pause===false)return;
  if(planning){
   const released=await clockModule.awaitOriginalPlanningGateRelease(prefix+'.release',{enteredAtNs,originalTimeout,originalImmediate,
    onProgress:kind=>event('async-gate-mainloop-progress',{gate:gate.name,boundary,callLabel:gate.callLabel,
     kind,gateEnterAtNs:enteredAtNs,mode,...planningFields})});
   if(released.releaseStep.wallClockNowMs!==undefined)setWallClock(released.releaseStep.wallClockNowMs);
   event('fence-gate-release',{gate:gate.name,boundary,callLabel:gate.callLabel,mode,...planningFields,
    gateEnterSequence:receipt.sequence,releaseStep:released.releaseStep,consumedAtNs:released.consumedAtNs});flush();continue;
  }
  // These real callbacks demonstrate that the held notification does not own
  // unrelated IPC, SQLite admission ports, timers or main-loop completions.
  await Promise.all([new Promise(resolve=>originalImmediate(()=>{event('async-gate-mainloop-progress',{
   gate:gate.name,boundary,callLabel:gate.callLabel,kind:'setImmediate',gateEnterAtNs:receipt.enteredAtNs});resolve();})),
   new Promise(resolve=>originalTimeout(()=>{event('async-gate-mainloop-progress',{
    gate:gate.name,boundary,callLabel:gate.callLabel,kind:'setTimeout',gateEnterAtNs:receipt.enteredAtNs});resolve();},0))]);flush();
  const deadline=performance.now()+30_000;
  while(!fs.existsSync(prefix+'.release')){if(performance.now()>=deadline)throw Error('Declared asynchronous fence gate exceeded its real monotonic bound');
   await new Promise(resolve=>originalTimeout(resolve,10));}
  const released=JSON.parse(fs.readFileSync(prefix+'.release','utf8'));
  if(released.wallClockNowMs!==undefined)setWallClock(released.wallClockNowMs);
  event('fence-gate-release',{gate:gate.name,boundary,callLabel:gate.callLabel,mode:'deferred-original-worker-reply'});flush();
 }
 }catch(error){controlFailure('asynchronous-gate-control-failed',error,{boundary});}
}
globalThis[Symbol.for('memory.eq.forgetIndexFence')]=Object.freeze({
 withCommandScope:(command,callback)=>commandScopes.run(command,callback),event,pause,pauseAsync,carrier,flush,setWallClock,
 blockControl:controlFailure,
 getReindexRevisionRead(){return lastReindexRevisionRead;},
 get sourceClock(){return sourceClock;},
 get searchEffects(){return searchEffects;},
 get watchEffects(){return watchEffects;},
 get controlFailures(){return[...controlFailures,...passiveStore.failures().map(failure=>({event:'fixture-control-failure',reason:'shared-passive-buffer-blocked',...failure}))];},
 get passiveChannels(){return passiveStore.snapshot();},
});
// Observe the original sleep resource after its held-lock decision. Timers
// remain unchanged; this is a pending proof, never a timeout-selected outcome.
createHook({init(asyncId,type,triggerAsyncId,resource){
 if(type!=='Timeout'||!matching('forget.marker-commit-or-original-workspace-or-writer-wait').length)return;
 const originalStack=new Error('Actual original workspace wait timer').stack;
 if(originalStack.includes('acquireMemoryWorkspaceLock')&&resource._idleTimeout===40){
  pause('forget.marker-commit-or-original-workspace-or-writer-wait',{observation:'actual-original-workspace-lock-wait',
   sourceOwner:'acquireMemoryWorkspaceLock.actual-sleep',asyncId,triggerAsyncId,delayMs:resource._idleTimeout,originalStack});
 }
}}).enable();

// Observe revision reads and original SQL transactions on their actual connection.
const sqlObservation=clockModule.installOriginalSqlObservation({DatabaseSync,qualifyStack:releaseCaller,event,
 ref:value=>objectRef(value),onControlFailure:error=>controlFailure('original-sql-observer-failed',error)});
const dbStates=new WeakMap();let nextDb=0;
const originalPrepare=DatabaseSync.prototype.prepare,originalExec=DatabaseSync.prototype.exec,originalLocation=DatabaseSync.prototype.location;
function dbState(db){if(!dbStates.has(db))dbStates.set(db,{id:`${process.pid}:${threadId}:db-${++nextDb}`,marker:false,lastRevision:null});return dbStates.get(db);}
function dbFacts(db,state){return{databaseRef:state.id,dbPath:originalLocation.call(db,'main'),transactionActive:db.isTransaction};}
DatabaseSync.prototype.prepare=function(sql,...args){
 const state=dbState(this),stack=new Error('Actual native SQLite prepare').stack;
 if(/^DELETE FROM main\.memory_index_meta WHERE key = \?$/u.test(sql)&&stack.includes('publishMemoryDatabaseTables')){
  pause('publication.fence-checked-before-table-writes',{...dbFacts(this,state),sql,lastRevisionRead:state.lastRevision,sourceOwner:'publishMemoryDatabaseTables'});
 }
 const statement=originalPrepare.call(this,sql,...args),db=this;
 for(const name of['get','run']){const original=statement[name];
  statement[name]=function(...bindings){const result=original.apply(this,bindings);
   if(name==='get'&&/^SELECT revision FROM memory_index_state WHERE id = \?$/u.test(sql)){
    state.lastRevision={sql,bindings:carrier(bindings),result:carrier(result),value:result?.revision,
     originalStack:stack,...dbFacts(db,state)};
    if(stack.includes('runInPlaceReindex'))lastReindexRevisionRead=state.lastRevision;
    event('original-revision-read',state.lastRevision);
   }
   if(name==='run'&&/insert into ["`]?memory_session_tombstones["`]?/iu.test(sql)&&stack.includes('recordMemorySessionTombstonesInDatabase')){
    state.marker=true;event('original-tombstone-write',{...dbFacts(db,state),sql,bindings:carrier(bindings),result:carrier(result),originalStack:stack});
   }
   return result;
  };
 }
 return statement;
};
DatabaseSync.prototype.exec=function(sql,...args){
 const state=dbState(this),wasTransaction=this.isTransaction,stack=new Error('Actual native SQLite exec').stack;
 const result=originalExec.call(this,sql,...args);
 if(/^COMMIT(?:\s+TRANSACTION)?\s*;?$/iu.test(sql.trim())&&state.marker){
  state.marker=false;const facts={...dbFacts(this,state),sql,wasTransaction,returned:carrier(result),originalStack:stack,
   commitReturned:true,sourceOwner:'forgetWorkspaceMemory.marker-transaction'};
  event('original-forget-marker-commit',facts);
  pause('forget.marker-commit-or-original-workspace-or-writer-wait',{...facts,observation:'actual-marker-COMMIT-returned'});
  pause('forget.marker-committed-before-purge',facts);
 }
 return result;
};

// The worker task pool receives the exact original keyword reply; gate only its
// delivery to existing listeners, retaining the original task id/object/bytes.
const tasks=new WeakMap(),observedWorkers=new WeakSet(),sourceWorkers=new WeakMap(),post=Worker.prototype.postMessage,emit=Worker.prototype.emit;
const transportMethods=new WeakSet();
let nextWorkerCall=0;
function workerPayload(value){return{value:carrier(value),privateJSON:processJSON(value),valueRef:objectRef(value)};}
function passiveObservation(operation){try{return operation();}catch(error){controlFailure('original-transport-observer-failed',error);return null;}}
function bindTransportMethod(fn,sourceClass){if(transportMethods.has(fn))return;transportMethods.add(fn);const body=Function.prototype.toString.call(fn);
 event('original-transport-method-binding',{functionRef:processRef(fn),functionName:fn.name,functionSource:body,functionSourceSha256:hash(body),
  sourceClassRef:processRef(sourceClass),sourcePrototypeRef:processRef(sourceClass.prototype)});}
function transportError(error){return{name:error.name,message:error.message,stack:error.stack,errorRef:objectRef(error),
 ownProperties:Reflect.ownKeys(error).map(key=>{const descriptor=Object.getOwnPropertyDescriptor(error,key);
  return{key:typeof key==='symbol'?{symbolDescription:key.description}:key,enumerable:descriptor.enumerable,configurable:descriptor.configurable,
   ...(Object.hasOwn(descriptor,'value')?{value:carrier(descriptor.value)}:{accessor:true})};})};}
Worker.prototype.postMessage=function(message,...args){
 const postStack=new Error('Actual original worker command custody').stack,postCaller=releaseCaller(postStack);
 const commandFacts=postCaller?passiveObservation(()=>{const facts={callId:`${process.pid}:${threadId}:worker-command-${++nextWorkerCall}`,
   workerRef:processRef(this),workerThreadId:this.threadId,originalPostRef:processRef(post),sourceCaller:postCaller,originalStack:postStack,
   message:workerPayload(message),arguments:workerPayload([message,...args]),requestId:message?.id??null,taskId:message?.taskId??null};
  bindTransportMethod(post,Worker);sourceWorkers.set(this,{workerRef:facts.workerRef,sourceCaller:postCaller,originalStack:postStack});return facts;}):null;
 if(!observedWorkers.has(this)){observedWorkers.add(this);event('original-worker-first-dispatch',{
  workerThreadId:this.threadId,wallClockNowMs:Date.now(),request:carrier(message),originalStack:new Error('Original worker dispatch').stack});}
 if(message?.input?.kind==='keyword'&&Number.isSafeInteger(message.taskId)){
  const originalStack=new Error('Original keyword task dispatch').stack,sourceCaller=releaseCaller(originalStack);
  if(sourceCaller?.package!=='node_modules/openclaw'||sourceCaller.path!=='dist/worker-task-pool-BQlnRNqZ.mjs'){
   controlFailure('keyword-request-source-unqualified',Error('Unqualified original keyword worker dispatch'),{originalStack,sourceCaller});
   return post.call(this,message,...args);
  }
  let map=tasks.get(this);if(!map){map=new Map();tasks.set(this,map);}map.set(message.taskId,{request:carrier(message),requestObject:message,
   requestRef:processRef(message),requestInput:carrier(message.input),nativeSectionsRef:processRef(message.nativeSections),originalStack,sourceCaller,
   callLabel:currentCallLabel(),commandScope:commandScopes.current()});
 }
 if(message?.input instanceof Uint8Array&&message.type==='execute'){
  const command=deserialize(message.input);
  if(command?.type==='database.publish')event('original-database-publication-command',{brokerRequestId:message.id,command:carrier(command),
   expectedRevision:command.input.expectedRevision,sourcePath:command.input.sourcePath,sourceIdentity:command.input.sourceIdentity});
 }
 return clockModule.callOriginalAtCheckpoint({receiver:this,original:post,args:[message,...args],
  before:()=>{if(commandFacts)event('original-worker-command-call',commandFacts);},
  settled:(result,error)=>{if(commandFacts)event(error?'original-worker-command-throw':'original-worker-command-return',{
   ...commandFacts,...(error?{error:transportError(error),privateError:carrier(error)}:{actualReturn:carrier(result)})});},
  onControlFailure:error=>controlFailure('original-worker-command-observer-failed',error)});
};
Worker.prototype.emit=function(name,message,...args){
 const receiver=this;
 if(['exit','error','messageerror','online'].includes(name)&&sourceWorkers.has(this))passiveObservation(()=>{
  event('original-worker-lifecycle-event',{...sourceWorkers.get(this),workerThreadId:this.threadId,eventName:name,arguments:workerPayload([message,...args])});});
 const workerSource=sourceWorkers.get(this),incoming=name==='message'&&workerSource?passiveObservation(()=>{
  bindTransportMethod(emit,Worker);
  const facts={...workerSource,callId:`${process.pid}:${threadId}:worker-reply-${++nextWorkerCall}`,workerThreadId:this.threadId,
   originalEmitRef:processRef(emit),message:workerPayload(message),arguments:workerPayload([name,message,...args]),
   requestId:message?.id??null,taskId:message?.taskId??null};event('original-worker-reply-received',facts);return facts;}):null;
 if(name==='message'&&message?.status==='ok'&&message.value?.kind==='keyword'){
  const task=tasks.get(this)?.get(message.taskId);
  if(task)return commandScopes.resume(task.commandScope,()=>{
   const boundary='search.keyword-result-before-enrichment',armed=isMainThread&&matching(boundary).some(gate=>fs.existsSync(path.join(context.gateDirectory,gate.name)+'.armed'));
   if(armed){const facts={sourceOwner:'WorkerTaskPool.original-keyword-reply',taskId:message.taskId,workerThreadId:this.threadId,
     workerRef:processRef(this),emitRef:processRef(emit),messageRef:processRef(message),requestRef:task.requestRef,
     request:task.request,requestInput:task.requestInput,nativeSectionsRef:task.nativeSectionsRef,requestSourceCaller:task.sourceCaller,
     requestOriginalStack:task.originalStack,reply:carrier(message),replyV8Sha256:hash(serialize(message)),eventName:name,
     eventArguments:carrier(args),eventArgumentRefs:args.map(value=>value&&typeof value==='object'?processRef(value):null)};
    facts.replyCallId=incoming?.callId??null;
    facts.callLabel=task.callLabel;
    facts.requestHeader={taskId:task.requestObject.taskId,interactive:task.requestObject.interactive,sampleMemory:task.requestObject.sampleMemory,
     nativeSections:{constructorName:task.requestObject.nativeSections.constructor.name,byteLength:task.requestObject.nativeSections.byteLength,
      bytesHex:Buffer.from(task.requestObject.nativeSections).toString('hex')}};
    event('keyword-reply-held',facts);
    const held=clockModule.deferOriginalEventDelivery({receiver:this,originalEmit:emit,eventName:name,message,args,
     awaitRelease:()=>pauseAsync(boundary,facts),
     onReceipt:(stage,fields)=>{if(stage==='delivery-enter'&&hash(serialize(message))!==facts.replyV8Sha256)
       controlFailure('held-keyword-message-mutated',Error('Actual held keyword reply changed before original delivery'),facts);
      event('keyword-reply-'+stage,{...facts,...fields});
      if(incoming)event(stage==='delivery-enter'?'original-worker-reply-call':stage==='delivery-return'?'original-worker-reply-return':'original-worker-reply-throw',{
       ...incoming,...fields,message:incoming.message,arguments:incoming.arguments});if(stage!=='delivery-enter'){tasks.get(this).delete(message.taskId);flush();}},
     onControlFailure:error=>controlFailure('keyword-reply-control-failed',error,facts)});
    held.completion.catch(error=>controlFailure('keyword-reply-deferred-completion-rejected',error,facts));
    return; // The original emit has deliberately not run yet.
   }
   tasks.get(this).delete(message.taskId);return deliver();
  });
 }
 return deliver();
 function deliver(){
 if(!incoming)return emit.call(receiver,name,message,...args);
 return clockModule.callOriginalAtCheckpoint({receiver,original:emit,args:[name,message,...args],
  before:()=>event('original-worker-reply-call',incoming),
  settled:(result,error)=>event(error?'original-worker-reply-throw':'original-worker-reply-return',{
   ...incoming,...(error?{error:transportError(error),privateError:carrier(error)}:{actualReturn:carrier(result)})}),
  onControlFailure:error=>controlFailure('original-worker-reply-observer-failed',error)});
 }
};
const realpath=fsp.realpath;
fsp.realpath=async function(...args){const stack=new Error('Original promotion lock target resolution').stack;
 const result=await realpath.apply(this,args);
 if(stack.includes('resolveMemoryPromotionLockTarget')){
  const facts={sourceOwner:'resolveMemoryPromotionLockTarget.actual-realpath-return',arguments:carrier(args),result:carrier(result),originalStack:stack};
  if(profile.kind==='forget-index-fence-v5')await pauseAsync('promotion.source-planned-before-final-lock',facts);
  else pause('promotion.source-planned-before-final-lock',facts);
 }
 return result;
};

// Original integrity inspection owns additional OS children. Observe its
// actual launch object, request/reply objects and native close, independently
// of the fixture coordinator's already authenticated actor processes.
const originalFork=childProcess.fork,originalSpawn=childProcess.spawn;
const observedChildren=new WeakSet(),processRefs=new WeakMap();let nextProcessRef=0,nextLaunch=0,forkDepth=0;
const processRef=value=>{if(!processRefs.has(value))processRefs.set(value,`${process.pid}:${threadId}:process-ref-${++nextProcessRef}`);return processRefs.get(value);};
function objectRef(value){return value&&(typeof value==='object'||typeof value==='function')?processRef(value):null;}
function processJSON(value,seen=new WeakSet()){
 if(value===undefined)return{privateType:'undefined'};
 if(typeof value==='bigint')return{privateType:'bigint',value:value.toString()};
 if(typeof value==='function')return{privateType:'function',name:value.name,ref:processRef(value)};
 if(value===null||typeof value!=='object')return value;
 if(value instanceof Error||value instanceof DOMException){if(seen.has(value))return{privateType:'reference',ref:processRef(value)};seen.add(value);
  return{privateType:'Error',constructorName:value.constructor.name,ref:processRef(value),name:value.name,message:value.message,stack:value.stack,
   ownProperties:Reflect.ownKeys(value).map(key=>{const descriptor=Object.getOwnPropertyDescriptor(value,key);
    return{key:typeof key==='symbol'?{symbolDescription:key.description}:key,enumerable:descriptor.enumerable,configurable:descriptor.configurable,
     ...(Object.hasOwn(descriptor,'value')?{value:processJSON(descriptor.value,seen)}:{accessor:true})};})};}
 if(value instanceof URL)return{privateType:'URL',href:value.href};
 if(value instanceof AbortSignal)return{privateType:'AbortSignal',aborted:value.aborted,reason:processJSON(value.reason,seen),ref:processRef(value)};
 if(value instanceof MessagePort)return{privateType:'MessagePort',ref:processRef(value)};
 if(value instanceof ArrayBuffer||value instanceof SharedArrayBuffer)return{privateType:value.constructor.name,
  byteLength:value.byteLength,hex:Buffer.from(value).toString('hex'),ref:processRef(value)};
 if(ArrayBuffer.isView(value))return{privateType:value.constructor.name,byteLength:value.byteLength,
  hex:Buffer.from(value.buffer,value.byteOffset,value.byteLength).toString('hex')};
 if(seen.has(value))return{privateType:'reference',ref:processRef(value)};
 seen.add(value);
 if(Array.isArray(value))return value.map(item=>processJSON(item,seen));
 return Object.fromEntries(Object.keys(value).map(key=>[key,processJSON(value[key],seen)]));
}
function releaseCaller(stack){
 for(const match of stack.matchAll(/(file:\/\/[^\s)]+?):\d+:\d+/gu)){
  const filename=fileURLToPath(match[1]),record=permitted.get(filename);
  if(record?.kind==='release')return{...record,absolutePath:filename};
 }
 return null;
}
function observeOriginalChild(child,method,args,originalStack){
 const sourceCaller=releaseCaller(originalStack);
 if(!sourceCaller||observedChildren.has(child))return child;
 observedChildren.add(child);
 const launchId=`${process.pid}:${threadId}:original-child-${++nextLaunch}`;
 const modulePath=method==='fork'?(args[0] instanceof URL?fileURLToPath(args[0]):path.resolve(args[0])):child.spawnargs?.[1];
 const entryRecord=typeof modulePath==='string'?permitted.get(modulePath):null;
 const options=method==='fork'?(Array.isArray(args[1])?args[2]:args[1]):args[2];
 const selectedOptions=options??{},environment=selectedOptions.env??process.env;
 const environmentKeys=['MEMORY_EQ_RELEASE_CONTEXT','MEMORY_EQ_FIF_ACTOR','MEMORY_EQ_FIF_INSTANCE',
  'MEMORY_EQ_FIF_CLOCK_NOW_MS','NODE_OPTIONS','OPENCLAW_STATE_DIR','OPENCLAW_CONFIG_PATH','HOME','OPENCLAW_HOME'];
 const spawned=event('original-child-spawn',{launchId,method,childPid:child.pid??null,
  executable:child.spawnfile,argv:[...(child.spawnargs??[])],modulePath,
  execArgv:processJSON(selectedOptions.execArgv),cwd:selectedOptions.cwd??process.cwd(),wallClockNowMs:Date.now(),
  originalStack,sourceCaller,sourceEntrypoint:entryRecord?{...entryRecord,absolutePath:modulePath}:null,
  environment:Object.fromEntries(environmentKeys.map(key=>[key,processJSON(environment[key])])),
  request:{originalArgs:carrier(args),argumentsJSON:processJSON(args),options:carrier(selectedOptions),optionsJSON:processJSON(selectedOptions)},
  returnedChildRef:processRef(child)});
 if(typeof child.send==='function'){
  const originalSend=child.send;
  child.send=function(...values){event('original-child-message',{launchId,childPid:child.pid??null,
   direction:'parent-to-child',message:carrier(values[0]),messageJSON:processJSON(values[0]),originalStack:new Error('Original child request').stack});
   return originalSend.apply(this,values);
  };
 }
 child.on('message',message=>event('original-child-message',{launchId,childPid:child.pid??null,
  direction:'child-to-parent',message:carrier(message),messageJSON:processJSON(message)}));
 child.once('error',error=>event('original-child-error',{launchId,childPid:child.pid??null,error:carrier(error),message:error.message}));
 child.once('exit',(code,signal)=>event('original-child-os-exit',{launchId,childPid:child.pid??null,code,signal,spawnSequence:spawned.sequence}));
 child.once('close',(code,signal)=>{
  event('original-child-exit',{launchId,childPid:child.pid??null,code,signal,spawnSequence:spawned.sequence});
  flush(); // Actual source-owned process close is a settlement boundary.
 });
 return child;
}
childProcess.fork=function(...args){const originalStack=new Error('Original child_process.fork call-through').stack;
 let child;forkDepth++;try{child=originalFork.apply(this,args);}finally{forkDepth--;}
 return observeOriginalChild(child,'fork',args,originalStack);
};
childProcess.spawn=function(...args){const originalStack=new Error('Original child_process.spawn call-through').stack;
 const child=originalSpawn.apply(this,args);
 return forkDepth?child:observeOriginalChild(child,'spawn',args,originalStack);
};
syncBuiltinESMExports();

if(parentPort){
 // The original broker sends one request at a time. This earlier listener only
 // retains that same request object; the original receive callback still owns it.
 parentPort.on('message',request=>{activeBrokerRequest=request;
  if(request?.closeResource===true&&request.resourcePort instanceof MessagePort)resourceCloseRequests.set(request.resourcePort,request);
  if(Number.isSafeInteger(request?.taskId)&&request.responseId===undefined&&request.nativeSections instanceof SharedArrayBuffer)taskRequests.set(request.taskId,request);
 });
}
const originalPortPost=MessagePort.prototype.postMessage;
MessagePort.prototype.postMessage=function(...args){const reply=args[0],originalStack=new Error('Actual original MessagePort custody').stack,
 sourceCaller=releaseCaller(originalStack);
 if(!sourceCaller)return originalPortPost.apply(this,args);
 const facts=passiveObservation(()=>({callId:`${process.pid}:${threadId}:port-${++nextWorkerCall}`,sourceCaller,originalStack,
  portRef:processRef(this),parentPortRef:parentPort?processRef(parentPort):null,originalPostRef:processRef(originalPortPost),
  message:workerPayload(reply),arguments:workerPayload(args)}));
 passiveObservation(()=>bindTransportMethod(originalPortPost,MessagePort));
 let sqliteTerminal=false;
 if(this===parentPort&&sourceCaller.package==='node_modules/openclaw'&&sourceCaller.path==='dist/infra/sqlite-store.worker.js'&&
  reply?.id===activeBrokerRequest?.id&&typeof reply.ok==='boolean'&&reply.input!=='next'){
  sqliteTerminal=!reply.transfer||reply.transfer==='frame'&&passiveObservation(()=>deserialize(reply.value).done===true)===true;
 }
 const taskTerminal=this===parentPort&&sourceCaller.package==='node_modules/openclaw'&&sourceCaller.path==='dist/worker-task-server-CF3aSh39.mjs'&&
  ['ok','failed'].includes(reply?.status)&&Number.isSafeInteger(reply.taskId);
 const resourceRequest=resourceCloseRequests.get(this),resourceTerminal=sourceCaller.package==='node_modules/openclaw'&&sourceCaller.path==='dist/worker-task-server-CF3aSh39.mjs'&&
  resourceRequest?.closeResource===true&&resourceRequest.resourcePort===this&&typeof reply?.ok==='boolean';
 const terminal=sqliteTerminal||taskTerminal||resourceTerminal,held=sqliteTerminal&&heldPublication&&reply.id===heldPublication.brokerRequestId?heldPublication:null;
 const terminalRequest=resourceTerminal?resourceRequest:taskTerminal?taskRequests.get(reply.taskId):activeBrokerRequest;
 if(held)heldPublication=null;
 const heldFacts=held?{...held,sourceOwner:'SqliteStoreWorker.receive.original-terminal-reply',sourceCaller,originalStack,
  parentPortRef:processRef(parentPort),originalPostRef:processRef(originalPortPost),replyRef:processRef(reply),
  reply:carrier(reply),postArguments:carrier(args),transferListRef:objectRef(args[1])}:null;
 return clockModule.callOriginalAtCheckpoint({receiver:this,original:originalPortPost,args,
  before:()=>{if(facts)event('original-message-port-call',facts);
   if(heldFacts)event('held-publication-worker-terminal-reply',heldFacts);
   if(terminal){event('original-worker-terminal-reply-checkpoint',{sourceCaller,originalStack,
    request:workerPayload(terminalRequest),requestRef:objectRef(terminalRequest),reply:carrier(reply),replyRef:objectRef(reply),
    portCallId:facts?.callId??null,terminalKind:sqliteTerminal?'sqlite-command':resourceTerminal?'worker-resource-close':'worker-task'});
    if(heldFacts||resourceTerminal||sqliteTerminal&&activeBrokerRequest?.type==='close')flush();}},
  settled:(result,error)=>{const outcome=error?{error:transportError(error),privateError:carrier(error)}:{actualReturn:carrier(result)};
   if(facts)event(error?'original-message-port-throw':'original-message-port-return',{...facts,...outcome});
   if(heldFacts)event('held-publication-worker-terminal-post-settled',{...heldFacts,...outcome});
   if(taskTerminal)taskRequests.delete(reply.taskId);if(resourceTerminal)resourceCloseRequests.delete(this);
   if(heldFacts||resourceTerminal||sqliteTerminal&&activeBrokerRequest?.type==='close')flush();},
  onControlFailure:error=>controlFailure('original-message-port-observer-failed',error,heldFacts??{})});
};
sqlObservation.declareInstalled();
event('original-transport-observer-installed',{workerClassRef:processRef(Worker),workerPrototypeRef:processRef(Worker.prototype),
 workerPostOriginalRef:processRef(post),workerEmitOriginalRef:processRef(emit),portClassRef:processRef(MessagePort),
 portPrototypeRef:processRef(MessagePort.prototype),portPostOriginalRef:processRef(originalPortPost),storage:'shared-per-thread-immutable-jsonl'});
sourceClock=clockModule.installSourceClock({workspaceDir:path.join(context.stateDirectory,'workspace'),actor,
 ticksByCall:profile.sourceWriteClock.ticksByCall,captureVersions:profile.kind==='forget-index-fence-v5',
 event:(name,fields)=>{const returned=event(name,fields);if(['source-clock-read','source-clock-read-throw'].includes(name))watchEffects?.observeSourceRead(fields);return returned;},
 qualifyStack(stack,kind,details){const caller=releaseCaller(stack);if(!caller)return null;
  if(kind==='read'||kind==='write')return caller;
  const fsSafe=caller.package==='node_modules/@openclaw/fs-safe';
  if(kind==='open'){
   if(fsSafe&&caller.path==='dist/replace-file-descriptor.js'&&stack.includes('writeTempFile'))return{...caller,publicationRole:'stage'};
   if(caller.package==='node_modules/openclaw'&&caller.path==='dist/short-term-promotion-memory-write-HTLC95gL.mjs'&&stack.includes('writeExistingMemoryInPlace'))return{...caller,publicationRole:'inPlace'};
   if(fsSafe&&(caller.path==='dist/root-impl.js'||caller.path==='dist/regular-file.js'&&stack.includes('appendRegularFile')))return{...caller,publicationRole:'inPlace'};
   if(!/\.(?:md|txt)$/iu.test(details.path))return null;
  }
  if(kind==='rename'&&((fsSafe&&caller.path==='dist/replace-file.js')||
   caller.package==='node_modules/openclaw'&&caller.path==='dist/short-term-promotion-memory-write-HTLC95gL.mjs'))return caller;
  if(kind==='unlink'&&caller.package==='node_modules/openclaw'&&caller.path==='dist/short-term-promotion-memory-write-HTLC95gL.mjs')return caller;
  throw Error(`Unsupported original source clock ${kind} owner ${caller.package}/${caller.path}`);
 }});

if(isMainThread&&profile.kind==='forget-index-fence-v5'){
 watchEffects=clockModule.observeOriginalWatchEffects({ref:objectRef,event,
  maxReferences:profile.watchEffects.maxReferencesPerBarrier,
  onFailure:error=>controlFailure('original-watch-effects-observer-failed',error),
  qualifyTimer(stack){const caller=releaseCaller(stack);return caller?.package==='node_modules/openclaw'&&
   caller.path==='dist/file-watcher-DSOr6bb7.mjs'&&stack.includes('scheduleWatchSync')&&stack.includes('file-watcher-DSOr6bb7.mjs:234:')?caller:null;},
  qualifySync(stack){const caller=releaseCaller(stack);return caller?.package==='node_modules/openclaw'&&
   caller.path==='dist/extensions/memory-core/manager-runtime.js'&&stack.includes('manager-runtime.js:5508:')&&
   stack.includes('manager-runtime.js:1541:')?caller:null;},
  qualifyNativeWatch(stack){const caller=releaseCaller(stack);return caller?.package==='node_modules/openclaw'&&
   caller.path==='dist/file-watcher-DSOr6bb7.mjs'?caller:null;},
  qualifyEmitter(stack){const caller=releaseCaller(stack);return caller?.package==='node_modules/chokidar'&&caller.path==='index.js'?caller:null;},
 });syncBuiltinESMExports();
}

searchEffects=clockModule.observeOriginalSearchEffects({scope:()=>sourceClock.currentCall(),ref:objectRef,event,
 maxJobs:profile.searchEffects.maxReferencesPerBarrier,
 onFailure:error=>controlFailure('original-search-effects-observer-failed',error),
 qualifyPromise(originalStack){const sourceCaller=releaseCaller(originalStack);if(!sourceCaller)return null;
  if(sourceCaller.package!=='node_modules/openclaw')return null;
  if(sourceCaller.path==='dist/tools-DotaQGXh.mjs'&&originalStack.includes('tools-DotaQGXh.mjs:904:')){
   if(originalStack.includes('at Promise.catch'))return{kind:'recall-catch',sourceCaller,line:904};
   if(originalStack.includes('at Promise.then'))return{kind:'recall-then',sourceCaller,line:904};
  }
  if(sourceCaller.path==='dist/extensions/memory-core/manager-runtime.js'&&
   originalStack.includes('manager-runtime.js:5068:')&&originalStack.includes('at Promise.finally'))
   return{kind:'publisher',sourceCaller,line:5068};
  return null;
 }});
