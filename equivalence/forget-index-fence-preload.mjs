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
const bytes=fs.readFileSync(contextPath),context=JSON.parse(bytes),profile=context.forgetIndexFenceV2Profile;
const approved={"forget-index-fence-v2-direct-absent-at-plan-retained-source-other-session-forgotten":"4a44ef7d5325e52f2a37c5e306d8d1e3aeb3f88dd0dc3b42d50c70fce5714a9b","forget-index-fence-v2-keyword-worker-before-forget-enrichment-after":"b11017ccae3ba4124c67f8f1c5c8a5819c82fb0d4e61ee42b468d013e1e290e3","forget-index-fence-v2-repeat-existing-tombstone-old-full-pending":"6b099a8cf96a2bf407b19f4452c63e0e5b64c509c0f902f952eb68abb1b3336f","forget-index-fence-v2-shared-clean-dryrun-unresolved-promotion-controls":"1b9acfda1c62857b998cdcd0ecda553d454eab908fa21113eb47bdce9862a35f","forget-index-fence-v2-shared-marker-commit-process-kill":"0c9860ab427b19a7b9bff71dacd969d57277a99fc5243ca21d1b37dada4992d2","forget-index-fence-v2-shared-old-full-complete-forget":"df0166e9b6206c3c9358fae34b74a62ceacffe89767b193067329f6773638180","forget-index-fence-v2-shared-postcheck-pending-forget":"b28624082be718f339fc1c49c25371c0a5824bd9d0f27680d134feefea0e7133","forget-index-fence-v2-split-marker-commit-process-kill":"fbf87d499b7dcc11b034db752c96a88818504062fbe45540496e33bdc8297a72","forget-index-fence-v2-split-old-full-complete-forget":"5f8ae8105407367ada19c9f426c28c4dec584b8c30e8cc55282f828e5d6fb84d","forget-index-fence-v2-split-postcheck-pending-forget":"3ab64950bbabaac2f6da2535e6ab1a72f98cf90869dd935f2e29d5709ac75acd","forget-index-fence-v2-stored-promotion-model-plan-before-forget":"2d04f44d937ae8a33ca14775e620d9ecc998eec455a970f7d3558aa1a16085e1","forget-index-fence-v2-unfenced-on-search-marker-commit-process-kill":"54bcd55182af74d9d40adbc1785b61a1948c89261f10eae3df9aa3a6c77e64e2","forget-index-fence-v2-unfenced-on-search-old-full-complete-forget":"bdbe5dade86046563655d13645f8f7513f624e5cbc8c6fb81146ad456421103d"};
const keys=['schemaVersion','kind','runtime','providerMode','fetchPolicy','approvedNodeRuntime',
 'forgetIndexFenceV2Profile','allowedLocal','traceDirectory','evidenceDirectory','stateDirectory',
 'configPath','gateDirectory','approvedReferenceSources','fixtureSourceCaptures'].sort().join();
const profileKeys=['kind','operation','caseId','caseWireSha256','actorClocks','gates','nodeRuntime','acceptancePointsAwarded','sourceWriteClock',
 ...(Object.hasOwn(profile??{},'recoveryNowMs')?['recoveryNowMs']:[])].sort().join();
if(Object.keys(context).sort().join()!==keys||context.schemaVersion!==1||context.kind!=='release-oracle-execution'||
 context.providerMode!=='none'||context.fetchPolicy!=='deny'||profile?.kind!=='forget-index-fence-v2'||
 Object.keys(profile??{}).sort().join()!==profileKeys||
 profile.operation!=='forget-index-fence-v2-runtime'||profile.acceptancePointsAwarded!==0||
 !Object.hasOwn(approved,profile.caseId)||approved[profile.caseId]!==profile.caseWireSha256||!Array.isArray(profile.gates)||
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
const originalDate=Date,originalTimeout=setTimeout,originalPerformance=performance.now;
const actorClock=Number(process.env.MEMORY_EQ_FIF_CLOCK_NOW_MS??profile.actorClocks[actor]);
const permittedClocks=new Set([profile.actorClocks[actor],...(profile.recoveryNowMs===undefined?[]:[profile.recoveryNowMs])]);
if(!permittedClocks.has(actorClock))throw Error('Undeclared wall clock phase');
mock.timers.enable({apis:['Date'],now:actorClock});
trace({event:'bootstrap',isMainThread,runtime:actualNode,contextSha256:hash(bytes),preloadSha256:ownRecord.sha256,fetchDenied:true,providerMode:'none'});
trace({event:'forget-index-fence-v2-bootstrap',profile,clock:{owner:'node:test',apis:['Date'],nowMs:Date.now(),
 dateConstructorReplaced:Date!==originalDate,setTimeoutUnchanged:setTimeout===originalTimeout,performanceNowUnchanged:performance.now===originalPerformance}});

const sleepCell=new Int32Array(new SharedArrayBuffer(4)),fired=new Set(),passive=[];
let callLabel=null,sequence=0,lastReindexRevisionRead=null,sourceClock=null;
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
 get sourceClock(){return sourceClock;},
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

const clockModule=await import('./forget-index-fence-source-clock.mjs');
sourceClock=clockModule.installSourceClock({workspaceDir:path.join(context.stateDirectory,'workspace'),actor,
 ticksByCall:profile.sourceWriteClock.ticksByCall,event:(name,fields)=>event(name,fields),
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
