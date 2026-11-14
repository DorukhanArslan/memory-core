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
import {Worker,isMainThread,threadId} from 'node:worker_threads';
import {serialize,deserialize} from 'node:v8';
import {mock} from 'node:test';
import {createHook} from 'node:async_hooks';

const hash=value=>crypto.createHash('sha256').update(value).digest('hex');
const contextPath=process.env.MEMORY_EQ_RELEASE_CONTEXT;
if(!contextPath||!path.isAbsolute(contextPath)||fs.realpathSync(contextPath)!==contextPath)throw Error('Owned fence context required');
const bytes=fs.readFileSync(contextPath),context=JSON.parse(bytes),profile=context.forgetIndexFenceProfile;
const approved={"forget-index-fence-direct-absent-at-plan-retained-source-other-session-forgotten":"25d61b2395527a2cb7b4d59234ce353b65e91510e6edd8413aa3648c5f336dae","forget-index-fence-keyword-worker-before-forget-enrichment-after":"6f18402d42c354682a18a77d39b7136bb5f4dab0220d3cdbcf4bc6c1d62b8c9b","forget-index-fence-repeat-existing-tombstone-old-full-pending":"32991073589bed868e38493b3b74ff32bd9951c3fddb75de5e12785b61f34de9","forget-index-fence-shared-clean-dryrun-unresolved-promotion-controls":"3c6f2bd032e85accd26cf98c0aac2a645cdb44f51db192b597a54f64fc4f10fc","forget-index-fence-shared-marker-commit-process-kill":"3b8411319dff5a22c171545f1ceafcc6c72ca8856373ca4faf01cf15d471b850","forget-index-fence-shared-old-full-complete-forget":"a50a4ba713d0dcc1dfc61de5bf71dc66a53501c66db8e9c6a6350bfa1bfb0aad","forget-index-fence-shared-postcheck-pending-forget":"15301b52e2c21a39184dca488d1461bb588d37e837361f2fc2239f1467cfd276","forget-index-fence-split-marker-commit-process-kill":"ede638ba25b32ce6285bd2cfe4085c838f2a4dae7bf133ebe8f94b4ee429a7f8","forget-index-fence-split-old-full-complete-forget":"43aa72fd2f30bfcfaf2c773d02f38e2f681cce79b8ab41eaf15d749530291563","forget-index-fence-split-postcheck-pending-forget":"52e6b235cdbcd0304a677de3f69b032be9453470ea8fdb3c7b870ea27c1f48be","forget-index-fence-stored-promotion-model-plan-before-forget":"285755a010826810830b0711678d54522a69beaf30b1f4034e7b2793d8def747","forget-index-fence-unfenced-on-search-marker-commit-process-kill":"d2d79892afd9b7a12fa3d10f2307a9ba215ebaaa42aa796b6addf9507b1b1df5","forget-index-fence-unfenced-on-search-old-full-complete-forget":"0a44f139e39d2e6088475b3a279f3bfc48dbd3744765d7bf5b83f77280e0ba76"};
const keys=['schemaVersion','kind','runtime','providerMode','fetchPolicy','approvedNodeRuntime',
 'forgetIndexFenceProfile','allowedLocal','traceDirectory','evidenceDirectory','stateDirectory',
 'configPath','gateDirectory','approvedReferenceSources','fixtureSourceCaptures'].sort().join();
const profileKeys=['kind','operation','caseId','caseWireSha256','actorClocks','gates','nodeRuntime','acceptancePointsAwarded',
 ...(Object.hasOwn(profile??{},'recoveryNowMs')?['recoveryNowMs']:[])].sort().join();
if(Object.keys(context).sort().join()!==keys||context.schemaVersion!==1||context.kind!=='release-oracle-execution'||
 context.providerMode!=='none'||context.fetchPolicy!=='deny'||profile?.kind!=='forget-index-fence'||
 Object.keys(profile??{}).sort().join()!==profileKeys||
 profile.operation!=='forget-index-fence-runtime'||profile.acceptancePointsAwarded!==0||
 !Object.hasOwn(approved,profile.caseId)||approved[profile.caseId]!==profile.caseWireSha256||!Array.isArray(profile.gates)||
 !profile.actorClocks||Object.keys(profile.actorClocks).length>12||
 JSON.stringify(profile.nodeRuntime)!==JSON.stringify(context.approvedNodeRuntime)||
 context.approvedReferenceSources?.length!==0||context.fixtureSourceCaptures?.length!==0)throw Error('Closed fence capability required');
const own=fs.realpathSync(fileURLToPath(import.meta.url)),folder=path.dirname(own);
const localNames=['forget-index-fence-preload.mjs','forget-index-fence-entry.mjs','forget-index-fence-runtime.mjs'];
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
const originalDate=Date,originalTimeout=setTimeout,originalPerformance=performance.now;
const actorClock=Number(process.env.MEMORY_EQ_FIF_CLOCK_NOW_MS??profile.actorClocks[actor]);
const permittedClocks=new Set([profile.actorClocks[actor],...(profile.recoveryNowMs===undefined?[]:[profile.recoveryNowMs])]);
if(!permittedClocks.has(actorClock))throw Error('Undeclared wall clock phase');
mock.timers.enable({apis:['Date'],now:actorClock});
trace({event:'bootstrap',isMainThread,runtime:actualNode,contextSha256:hash(bytes),preloadSha256:ownRecord.sha256,fetchDenied:true,providerMode:'none'});
trace({event:'forget-index-fence-bootstrap',profile,clock:{owner:'node:test',apis:['Date'],nowMs:Date.now(),
 dateConstructorReplaced:Date!==originalDate,setTimeoutUnchanged:setTimeout===originalTimeout,performanceNowUnchanged:performance.now===originalPerformance}});

const sleepCell=new Int32Array(new SharedArrayBuffer(4)),fired=new Set(),passive=[];
let callLabel=null,sequence=0,lastReindexRevisionRead=null;
const event=(name,fields={})=>{const row={event:name,sequence:++sequence,callLabel,atNs:process.hrtime.bigint().toString(),...fields};passive.push(row);return row;};
function flush(){if(passive.length)fs.appendFileSync(path.join(context.evidenceDirectory,`${process.pid}-${threadId}-events.jsonl`),
 passive.splice(0).map(row=>JSON.stringify({...row,pid:process.pid,ppid:process.ppid,threadId,actor,
  instance:Number(process.env.MEMORY_EQ_FIF_INSTANCE??0)})).join('\n')+'\n',{mode:0o600});}
process.once('exit',flush);
const carrier=value=>{try{return{v8Hex:serialize(value).toString('hex')};}catch(error){return{unserializable:{name:error.name,message:error.message}};}};
function setWallClock(nowMs){if(!permittedClocks.has(nowMs))throw Error('Undeclared original wall clock advance');
 const before=Date.now();mock.timers.setTime(nowMs);process.env.MEMORY_EQ_FIF_CLOCK_NOW_MS=String(nowMs);
 event('declared-wall-clock-phase',{before,nowMs,monotonicUnchanged:true});}
function matching(boundary){return profile.gates.filter(gate=>gate.actor===actor&&gate.boundary===boundary&&
 !fired.has(gate.name)&&(!isMainThread||gate.callLabel===callLabel));}
function pause(boundary,facts={}){
 for(const gate of matching(boundary)){
  const prefix=path.join(context.gateDirectory,gate.name);
  if(!fs.existsSync(prefix+'.armed'))continue;
  fired.add(gate.name);
  const receipt={...gate,pid:process.pid,ppid:process.ppid,threadId,actor,sequence:++sequence,
   instance:Number(process.env.MEMORY_EQ_FIF_INSTANCE??0),
   enteredAtNs:process.hrtime.bigint().toString(),originalStack:new Error('Actual original fence control').stack,...facts};
  fs.writeFileSync(prefix+'.hit.json',JSON.stringify(receipt)+'\n',{flag:'wx',mode:0o600});
  flush();
  trace({event:'fence-gate-enter',...receipt});
  if(gate.pause===false)return;
  const deadline=performance.now()+30_000;
  while(!fs.existsSync(prefix+'.release')){if(performance.now()>=deadline)throw Error('Declared fence gate exceeded its real monotonic bound');Atomics.wait(sleepCell,0,0,10);}
  const released=JSON.parse(fs.readFileSync(prefix+'.release','utf8'));
  if(released.wallClockNowMs!==undefined)setWallClock(released.wallClockNowMs);
  event('fence-gate-release',{gate:gate.name,boundary});
 }
}
globalThis[Symbol.for('memory.eq.forgetIndexFence')]=Object.freeze({
 setCallLabel(label){callLabel=label;},event,pause,carrier,flush,setWallClock,
 getReindexRevisionRead(){return lastReindexRevisionRead;},
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
const tasks=new WeakMap(),observedWorkers=new WeakSet(),post=Worker.prototype.postMessage,emit=Worker.prototype.emit;
Worker.prototype.postMessage=function(message,...args){
 if(!observedWorkers.has(this)){observedWorkers.add(this);event('original-worker-first-dispatch',{
  workerThreadId:this.threadId,wallClockNowMs:Date.now(),request:carrier(message),originalStack:new Error('Original worker dispatch').stack});}
 if(message?.input?.kind==='keyword'&&Number.isSafeInteger(message.taskId)){
  let map=tasks.get(this);if(!map){map=new Map();tasks.set(this,map);}map.set(message.taskId,{request:carrier(message),callLabel});
 }
 if(message?.input instanceof Uint8Array&&message.type==='execute'){
  const command=deserialize(message.input);
  if(command?.type==='database.publish')event('original-database-publication-command',{brokerRequestId:message.id,command:carrier(command),
   expectedRevision:command.input.expectedRevision,sourcePath:command.input.sourcePath,sourceIdentity:command.input.sourceIdentity});
 }
 return post.call(this,message,...args);
};
Worker.prototype.emit=function(name,message,...args){
 if(name==='message'&&message?.status==='ok'&&message.value?.kind==='keyword'){
  const task=tasks.get(this)?.get(message.taskId);
  if(task){const previous=callLabel;callLabel=task.callLabel;
   try{pause('search.keyword-result-before-enrichment',{sourceOwner:'WorkerTaskPool.original-keyword-reply',taskId:message.taskId,
    workerThreadId:this.threadId,request:task.request,reply:carrier(message),replyV8Sha256:hash(serialize(message))});}
   finally{callLabel=previous;tasks.get(this).delete(message.taskId);}
  }
 }
 return emit.call(this,name,message,...args);
};
const realpath=fsp.realpath;
fsp.realpath=async function(...args){const stack=new Error('Original promotion lock target resolution').stack;
 const result=await realpath.apply(this,args);
 if(stack.includes('resolveMemoryPromotionLockTarget'))pause('promotion.source-planned-before-final-lock',{
  sourceOwner:'resolveMemoryPromotionLockTarget.actual-realpath-return',arguments:carrier(args),result:carrier(result),originalStack:stack});
 return result;
};

// Original integrity inspection owns additional OS children. Observe its
// actual launch object, request/reply objects and native close, independently
// of the fixture coordinator's already authenticated actor processes.
const originalFork=childProcess.fork,originalSpawn=childProcess.spawn;
const observedChildren=new WeakSet(),processRefs=new WeakMap();let nextProcessRef=0,nextLaunch=0,forkDepth=0;
const processRef=value=>{if(!processRefs.has(value))processRefs.set(value,`${process.pid}:${threadId}:process-ref-${++nextProcessRef}`);return processRefs.get(value);};
function processJSON(value,seen=new WeakSet()){
 if(value===undefined)return{privateType:'undefined'};
 if(typeof value==='bigint')return{privateType:'bigint',value:value.toString()};
 if(typeof value==='function')return{privateType:'function',name:value.name,ref:processRef(value)};
 if(value===null||typeof value!=='object')return value;
 if(value instanceof URL)return{privateType:'URL',href:value.href};
 if(value instanceof AbortSignal)return{privateType:'AbortSignal',aborted:value.aborted,reason:processJSON(value.reason,seen),ref:processRef(value)};
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
