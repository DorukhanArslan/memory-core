// Multi-process fixture orchestration. Every producer, admission decision,
// publication, search, forget and promotion below calls the original owner.
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawn} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {DatabaseSync} from 'node:sqlite';
import {serialize} from 'node:v8';
import {isDeepStrictEqual} from 'node:util';

const hash=value=>crypto.createHash('sha256').update(value).digest('hex');
const plain=value=>JSON.parse(JSON.stringify(value));
const err=error=>({name:error.name,message:error.message,code:error.code??null,stack:error.stack??null,
 cause:error.cause instanceof Error?{name:error.cause.name,message:error.cause.message,code:error.cause.code??null,stack:error.cause.stack??null}:null});
const sealed=value=>{const serializedJSON=JSON.stringify(value);return{serializedJSON,sha256:hash(serializedJSON)};};
const privateValue=value=>{const type=value===undefined?'undefined':value===null?'null':typeof value;
 try{return{type,v8Hex:serialize(value).toString('hex')};}catch(error){return{type,serializationError:{name:error.name,message:error.message}};}};
const controller=()=>globalThis[Symbol.for('memory.eq.forgetIndexFence')];
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const safeName=value=>{if(typeof value!=='string'||!/[A-Za-z]/u.test(value)||!/^[a-zA-Z0-9_-]+$/u.test(value))throw Error('Invalid owned actor/gate name');return value;};
const sqlValue=value=>typeof value==='bigint'?{sqliteInt64:value.toString()}:value instanceof Uint8Array?{sqliteBlobHex:Buffer.from(value).toString('hex')}:value;

// Explicit fixture process stop follows completed original cleanup. An IPC
// disconnect alone does not end an event loop containing other live handles.
export async function finishGracefulActorExit(runtime,settlement){
 if(!runtime.isExiting()||settlement.exiting!==true||settlement.error||settlement.infrastructureError){
  throw Error('A graceful actor exit requires a completed explicit stop');
 }
 runtime.persist();
 await new Promise((resolve,reject)=>process.send(settlement,error=>error?reject(error):resolve()));
 controller()?.event('graceful-stop-ipc-acknowledged',{commandId:settlement.id});
 await Promise.all([process.stdout,process.stderr].map(stream=>new Promise((resolve,reject)=>{
  stream.write('',error=>error?reject(error):resolve());
 })));
 controller()?.event('graceful-stop-output-drained',{commandId:settlement.id});
 controller()?.flush();runtime.persist();
 if(process.connected)process.disconnect();
 process.exit(0);
}

export async function awaitActualProcessClose(closed,timeoutMs){
 let timer;
 try{return await Promise.race([closed,new Promise((_,reject)=>{
  timer=setTimeout(()=>reject(Object.assign(Error('Actual fixture process close exceeded its deadline'),
   {code:'FIF_PROCESS_CLOSE_TIMEOUT',timeoutMs})),timeoutMs);
 })]);}finally{clearTimeout(timer);}
}

// Observation reads use the original export API's explicit read-only lifecycle.
// Retain its whole actual result before selecting events for the frozen facts.
export function captureOriginalTranscriptExportRead({accessor,scope,ref,event,receipts}){
 const method='readTranscriptExportSnapshotReadOnlySync',fn=accessor[method];
 if(typeof fn!=='function')throw Error('Original read-only transcript export callable unavailable');
 const entered=event('original-transcript-export-read-enter',{method,methodRef:ref(fn),ownerRef:ref(accessor)});
 const receipt={method,methodRef:ref(fn),ownerRef:ref(accessor),scope:plain(scope),enterSeq:entered.sequence,
  startedAtNs:entered.atNs,originalStack:new Error('Actual original read-only transcript export').stack};receipts.push(receipt);
 try{const result=fn.call(accessor,scope);receipt.privateReturn=privateValue(result);receipt.returnedUndefined=result===undefined;
  if(result!==undefined)receipt.result=plain(result);return result;
 }catch(error){receipt.error=err(error);receipt.privateError=privateValue(error);throw error;
 }finally{const returned=event('original-transcript-export-read-return',{method,methodRef:receipt.methodRef,
   enteredSeq:receipt.enterSeq,returnedUndefined:receipt.returnedUndefined??null,threw:Object.hasOwn(receipt,'error')});
  receipt.returnSeq=returned.sequence;receipt.finishedAtNs=returned.atNs;}
}

export function childRequest(input,actor,instance,config){
 if(actor!=='observer'&&!Object.hasOwn(input.actors,actor))throw Error('Undeclared original actor');
 return{kind:'forget-index-fence-child',actor,instance,caseId:config.caseId,input,runtimeRoot:config.runtimeRoot,
  fixtureBase:config.stateDirectory,configPath:config.configPath,evidenceDirectory:config.evidenceDirectory};
}

export async function runForgetIndexFenceRuntime(input,config){
 if(input.kind!=='forget-index-fence-v3'||!path.isAbsolute(config.runtimeRoot)||!path.isAbsolute(config.stateDirectory))throw Error('Owned original fixture required');
 const base=config.stateDirectory,workspace=path.join(base,'workspace');
 await fsp.mkdir(workspace,{recursive:true});
 const cfg={agents:{ownership:'explicit',defaults:{workspace},entries:{[input.identity.agentId]:{workspace}}},
  logging:{level:'silent',consoleLevel:'silent',file:path.join(base,'native.log')},
  session:{maintenance:{mode:'warn'}},...plain(input.config)};
 await fsp.writeFile(config.configPath,JSON.stringify(cfg)+'\n',{flag:'wx'});
 const raw={schemaVersion:1,kind:'forget-index-fence-native-capture',engine:'native',caseId:config.caseId,
  input:plain(input),fixtureBase:base,pid:process.pid,ppid:process.ppid,config:cfg,children:[],gates:[],snapshots:[],steps:[],completed:false,allChildrenReaped:false};
 const result={provider:null,calls:{},snapshots:{}};
 const live=new Map(),generations=new Map(),pending=new Map();let commandId=0,currentWallClock=input.clock.nowMs,operationFailed=false;
 const persist=()=>fs.writeFileSync(path.join(config.evidenceDirectory,'native-raw.json'),JSON.stringify([raw])+'\n');
 async function start(actor,wallClockNowMs=currentWallClock){
  safeName(actor);if(live.has(actor))throw Error('Actor already owns a live original process');
  const instance=(generations.get(actor)??0)+1;generations.set(actor,instance);
  const request=childRequest(input,actor,instance,config),argv=[fileURLToPath(new URL('./forget-index-fence-entry.mjs',import.meta.url))];
  const child=spawn(process.execPath,argv,{env:{...process.env,MEMORY_EQ_FIF_ACTOR:actor,
   MEMORY_EQ_FIF_INSTANCE:String(instance),MEMORY_EQ_FIF_CLOCK_NOW_MS:String(wallClockNowMs),
   HOME:base,OPENCLAW_HOME:base,OPENCLAW_STATE_DIR:base,OPENCLAW_CONFIG_PATH:config.configPath},
   stdio:['ignore','pipe','pipe','ipc']});
  const record={actor,instance,pid:child.pid,ppid:process.pid,argv:[process.execPath,...argv],request,
   requestSeal:sealed(request),startedAtNs:process.hrtime.bigint().toString(),stdout:'',stderr:'',commands:[]};raw.children.push(record);
  const requests=new Map();let readyResolve,readyReject;
  const ready=new Promise((resolve,reject)=>{readyResolve=resolve;readyReject=reject;});
  child.stdout.setEncoding('utf8');child.stderr.setEncoding('utf8');
  child.stdout.on('data',data=>{record.stdout+=data;});child.stderr.on('data',data=>{record.stderr+=data;});
  child.on('message',message=>{
   if(message?.type==='ready'){record.ready=message;readyResolve();return;}
   if(message?.type==='original-enter'){
    const item=requests.get(message.id);if(!item)throw Error('Unowned original call entry');item.record.originalEntered=message;return;
   }
   if(message?.type==='settled'){
    const item=requests.get(message.id);if(!item)throw Error('Unowned original child reply');
    item.record.settledAtNs=process.hrtime.bigint().toString();item.record.settlement=message;
    requests.delete(message.id);item.resolve(message);return;
   }
   if(message?.type==='fatal'){record.fatal=message;readyReject(Error(message.error.message));return;}
  });
  const exited=new Promise(resolve=>child.once('close',(code,signal)=>{
   record.exit={code,signal};record.finishedAtNs=process.hrtime.bigint().toString();
   for(const item of requests.values())item.reject(Error('Actual original process exited before call settlement'));
   requests.clear();resolve(record.exit);
  }));
  child.once('error',error=>readyReject(error));
  const owned={child,record,requests,exited};live.set(actor,owned);
  child.send({type:'initialize',request});await ready;return owned;
 }
 async function actor(actor){return live.get(actor)??await start(actor);}
 async function dispatch(actorName,operation,label,extra={}){
  const owned=await actor(actorName),id=++commandId;
  const command={id,operation,...(label===undefined?{}:{label}),wallClockNowMs:currentWallClock,...extra};
  const record={id,operation,label:label??null,request:command,requestSeal:sealed(command),startedAtNs:process.hrtime.bigint().toString()};
  owned.record.commands.push(record);
  const promise=new Promise((resolve,reject)=>owned.requests.set(id,{resolve,reject,record}));
  owned.child.send({type:'command',command});return{promise,record};
 }
 function collect(message){
  if(message.infrastructureError)throw Error(message.infrastructureError.message);
  if(message.providerIdentity)result.provider=message.providerIdentity.result.provider;
  if(message.publicCall){const call=message.publicCall;result.calls[`${call.operation}:${call.label}`]=call;}
  if(message.snapshot){raw.snapshots.push(message.snapshot);result.snapshots[message.snapshot.label]=message.snapshot.common;}
  if(message.sourceClockBlocked){(raw.sourceClockFailures??=[]).push({actor:message.actor,pid:message.pid,instance:message.instance,failures:message.sourceClockFailures});
   throw Object.assign(Error('Native source clock control failed; original outcomes retained'),{code:'FIF_SOURCE_CLOCK_CONTROL_FAILED'});}
  if(message.controlBlocked){(raw.controlFailures??=[]).push({actor:message.actor,pid:message.pid,instance:message.instance,failures:message.controlFailures});
   throw Object.assign(Error('Native fixture control failed; original outcomes retained'),{code:'FIF_CONTROL_FAILED'});}
  return message;
 }
 async function run(actorName,operation,label,extra){const call=await dispatch(actorName,operation,label,extra);return collect(await call.promise);}
 async function awaitGate(name){
  const gate=input.gates.find(item=>item.name===name);if(!gate)throw Error('Undeclared gate');
  const filename=path.join(config.gateDirectory,safeName(name)+'.hit.json'),deadline=performance.now()+30_000;
  while(!fs.existsSync(filename)){if(performance.now()>=deadline)throw Error(`Original ${name} boundary not reached`);await sleep(10);}
  const receipt=JSON.parse(fs.readFileSync(filename,'utf8'));
  if(receipt.name!==gate.name||receipt.actor!==gate.actor||receipt.boundary!==gate.boundary)throw Error('Wrong original gate receipt');
  raw.gates.find(item=>item.name===name).receipt=receipt;persist();return receipt;
 }
 try{
  for(const step of input.steps){
   const observed={step:plain(step),startedAtNs:process.hrtime.bigint().toString()};raw.steps.push(observed);
   const name=step.operation;
   if(name==='prepare-real-host-inputs')await run('foreground',name);
   else if(name==='execute-seed-actions'){for(const action of input.seedActions)await run(action.actor,action.operation,action.label);}
   else if(name==='arm-gate'){
    const gate=input.gates.find(item=>item.name===step.gate);if(!gate)throw Error('Undeclared gate');
    fs.writeFileSync(path.join(config.gateDirectory,safeName(gate.name)+'.armed'),JSON.stringify(gate)+'\n',{flag:'wx'});
    raw.gates.push({...gate,armedAtNs:process.hrtime.bigint().toString()});
   }else if(name==='await-gate')await awaitGate(step.gate);
   else if(name==='release-gate'){
    if(step.wallClockNowMs!==undefined)currentWallClock=step.wallClockNowMs;
    fs.writeFileSync(path.join(config.gateDirectory,safeName(step.gate)+'.release'),JSON.stringify(step)+'\n',{flag:'wx'});
    raw.gates.find(item=>item.name===step.gate).releasedAtNs=process.hrtime.bigint().toString();
   }else if(name.startsWith('start-')&&['start-sync','start-forget','start-promotion','start-public-memory-search'].includes(name)){
    const operation={'start-sync':'original-sync','start-forget':'original-forget','start-promotion':'original-promotion','start-public-memory-search':'public-memory-search'}[name];
    const key=`${step.actor}:${operation}:${step.label}`;if(pending.has(key))throw Error('Duplicate pending original call');
    const call=await dispatch(step.actor,operation,step.label);call.promise.catch(()=>{});pending.set(key,call);
   }else if(['await-sync','await-forget','await-promotion','await-public-call'].includes(name)){
    const operation={'await-sync':'original-sync','await-forget':'original-forget','await-promotion':'original-promotion','await-public-call':'public-memory-search'}[name];
    const key=`${step.actor}:${operation}:${step.label}`,call=pending.get(key);if(!call)throw Error('No retained original call frame');
    collect(await call.promise);pending.delete(key);
   }else if(name==='await-original-search-effects'){await run(step.actor,name,step.label);
   }else if(name==='capture-physical-state'){
    // A separate read-only observer process avoids waiting on any held actor.
    const forget=raw.children.flatMap(child=>child.commands.filter(command=>command.operation==='original-forget'&&command.originalEntered)
     .map(command=>({child,command}))).at(-1);
    const builder=raw.children.filter(child=>child.actor==='builder').flatMap(child=>child.commands
     .filter(command=>command.operation==='original-sync'&&command.originalEntered&&input.gates.some(gate=>gate.actor===child.actor&&gate.callLabel===command.label&&
      ['rebuild.revision-captured-before-publication','publication.fence-checked-before-table-writes'].includes(gate.boundary)))
     .map(command=>({child,command}))).at(-1);
    const settled=value=>!value?.command.originalEntered?null:Boolean(value.command.settlement);
    await run('observer',name,step.label,{coordinatedCalls:{
     forget:forget?{pid:forget.child.pid,commandId:forget.command.id,entered:forget.command.originalEntered??null,settlement:forget.command.settlement??null,termination:forget.command.termination??null}:null,
     builder:builder?{pid:builder.child.pid,commandId:builder.command.id,entered:builder.command.originalEntered??null,settlement:builder.command.settlement??null}:null},
     concurrency:{forgetSettled:settled(forget),oldBuildSettled:settled(builder)}});
   }else if(name==='stop-original-process'){
    const owned=live.get(step.actor);if(!owned)throw Error('No original process to stop');
    if(step.mode==='SIGKILL'){
     owned.record.kill={signal:'SIGKILL',atNs:process.hrtime.bigint().toString()};
     for(const gate of raw.gates)if(gate.actor===step.actor&&gate.receipt&&!gate.releasedAtNs)gate.killWhileHeld=true;
     owned.child.kill('SIGKILL');
    }else{await run(step.actor,'process-exit');}
   }else if(name==='reap-original-process'){
    const owned=live.get(step.actor);if(!owned)throw Error('No original process to reap');await owned.exited;
    owned.record.reapedAtNs=process.hrtime.bigint().toString();live.delete(step.actor);
    if(owned.record.kill){
     for(const command of owned.record.commands.filter(item=>!item.settlement&&item.operation==='original-forget')){
      command.termination={...owned.record.exit,reapedAtNs:owned.record.reapedAtNs,pid:owned.record.pid};
      result.calls[`forget:${command.label}`]={operation:'forget',label:command.label,
       outcome:{status:'terminated',signal:owned.record.exit.signal}};
     }
    }
   }else if(name==='start-fresh-original-process'){if(live.has(step.actor))throw Error('Fresh process requires actual prior reap');
    if(step.wallClockNowMs!==undefined)currentWallClock=step.wallClockNowMs;await start(step.actor,currentWallClock);}
   else await run(step.actor??'foreground',name,step.label);
   observed.finishedAtNs=process.hrtime.bigint().toString();persist();
  }
  raw.result=result;raw.completed=true;return result;
 }catch(error){operationFailed=true;raw.failure=err(error);throw error;
 }finally{
  let teardownFailure=null;
  for(const [name,owned]of live){
   let acknowledgementError=null;
   try{
    const draining=(async()=>{
     if(!owned.record.exit){
      try{const call=await dispatch(name,'process-exit'),reply=await call.promise;
       if(reply.infrastructureError||reply.error||reply.sourceClockBlocked||reply.controlBlocked||reply.exiting!==true){
        acknowledgementError=Error(reply.infrastructureError?.message??reply.error?.message??(reply.sourceClockBlocked||reply.controlBlocked?'Native fixture control failed during original close':'Actual child did not acknowledge completed close'));
       }
      }catch(error){acknowledgementError=error;}
     }
     // The real close event follows IPC settlement and output pipe closure.
     return await owned.exited;
    })();
    const exit=await awaitActualProcessClose(draining,10_000);
    if(acknowledgementError)throw acknowledgementError;
    if(exit.code!==0||exit.signal!==null)throw Error('Actual fixture child did not exit gracefully');
   }catch(error){
    teardownFailure??=error;raw.completed=false;
    (raw.teardownFailures??=[]).push({actor:name,pid:owned.record.pid,instance:owned.record.instance,
     error:err(error),atNs:process.hrtime.bigint().toString(),acknowledgementError:acknowledgementError?err(acknowledgementError):null});
    if(error.code==='FIF_PROCESS_CLOSE_TIMEOUT'&&!owned.record.exit){
     owned.record.teardownKill={signal:'SIGKILL',reason:'actual-close-deadline',atNs:process.hrtime.bigint().toString()};
     owned.child.kill('SIGKILL');
    }
    await owned.exited;
   }
   owned.record.reapedAtNs=process.hrtime.bigint().toString();
  }
  raw.allChildrenReaped=raw.children.every(item=>item.exit&&item.reapedAtNs);persist();
  if(teardownFailure&&!operationFailed)throw teardownFailure;
 }
}

export async function runForgetIndexFenceActor(request){
 const{input,actor,instance,fixtureBase:base,runtimeRoot,configPath,evidenceDirectory}=request;
 const workspace=path.join(base,'workspace'),cfg=JSON.parse(await fsp.readFile(configPath,'utf8'));
 const raw={schemaVersion:1,kind:'forget-index-fence-actor',actor,instance,pid:process.pid,ppid:process.ppid,request,
  config:cfg,calls:[],snapshots:[],producerReceipts:[],sessionTranscriptExportReads:[],codeOwners:[],owners:[],ownerBindings:[],getCalls:[],closed:false};
 const imp=name=>import(pathToFileURL(path.join(runtimeRoot,name)).href);
 const configRuntime=await imp('dist/plugin-sdk/config-runtime.js');configRuntime.setRuntimeConfigSnapshot(cfg);
 const runtime=await imp('dist/extensions/memory-core/manager-runtime.js');
 const api=await imp('dist/extensions/memory-core/runtime-api.js');
 const keyed=await imp('dist/plugin-sdk/plugin-state-store-runtime.js');
 api.configureMemoryCoreDreamingState(options=>keyed.createPluginStateKeyedStore('memory-core',options));
 const session=await imp('dist/plugin-sdk/session-store-runtime.js');
 const transcript=await imp('dist/plugin-sdk/session-transcript-runtime.js');
 const accessor=await imp('dist/session-accessor-CiKKTlbe.mjs');
 const promo=await imp('dist/short-term-promotion-Cy0NJmOU.mjs');
 const origins=await imp('dist/memory-entry-origins-BCQSIB3X.mjs');
 const paths=await imp('dist/openclaw-agent-db.paths-Dv3PPTNK.mjs');
 const dbPath=paths.c({agentId:input.identity.agentId,env:process.env});
 const statePaths=await imp('dist/openclaw-state-db.paths-rJI64Ab5.mjs');
 const pluginStateDbPath=statePaths.s(process.env);
 const originalCli=await imp('dist/cli.runtime-CVRN4xUp.mjs');
 const conflictType=(await imp('dist/manager-db-kernel-DyJADqYu.mjs')).t;
 const runtimeIO=(await imp('dist/runtime-BC29JSZp.mjs')).r;
 const tools=await imp('dist/tools-DotaQGXh.mjs');
 const refs=new WeakMap();let nextRef=0;
 function ref(value){if((typeof value!=='object'||value===null)&&typeof value!=='function')return null;
  if(!refs.has(value))refs.set(value,`${process.pid}:ref-${++nextRef}`);return refs.get(value);}
 function codeOwner(name,modulePath,exportName,fn){if(typeof fn!=='function')throw Error(`Missing original callable ${name}`);
  const existing=raw.codeOwners.find(owner=>owner.name===name&&owner.modulePath===modulePath&&owner.exportName===exportName);
  if(existing){if(existing.functionRef!==ref(fn))throw Error('Original callable identity changed');return;}
  raw.codeOwners.push({name,modulePath,exportName,functionRef:ref(fn),functionName:fn.name,functionLength:fn.length,
   functionSource:Function.prototype.toString.call(fn),functionSourceSha256:hash(Function.prototype.toString.call(fn))});}
 codeOwner('MemoryIndexManager.get','dist/extensions/memory-core/manager-runtime.js','MemoryIndexManager.get',runtime.MemoryIndexManager.get);
 codeOwner('runMemoryForget','dist/cli.runtime-CVRN4xUp.mjs','runMemoryForget',originalCli.runMemoryForget);
 codeOwner('defaultRuntime.writeJson','dist/runtime-BC29JSZp.mjs','r.writeJson',runtimeIO.writeJson);
 codeOwner('recordShortTermRecalls','dist/short-term-promotion-Cy0NJmOU.mjs','recordShortTermRecalls',promo.recordShortTermRecalls);
 codeOwner('rankShortTermPromotionCandidates','dist/short-term-promotion-Cy0NJmOU.mjs','rankShortTermPromotionCandidates',promo.rankShortTermPromotionCandidates);
 codeOwner('applyShortTermPromotions','dist/short-term-promotion-Cy0NJmOU.mjs','applyShortTermPromotions',promo.applyShortTermPromotions);
 codeOwner('appendSessionTranscriptMessageByIdentityStrict','dist/plugin-sdk/session-transcript-runtime.js','appendSessionTranscriptMessageByIdentityStrict',transcript.appendSessionTranscriptMessageByIdentityStrict);
 codeOwner('createMemorySearchTool','dist/tools-DotaQGXh.mjs','createMemorySearchTool',tools.createMemorySearchTool);
 codeOwner('getSessionEntry','dist/plugin-sdk/session-store-runtime.js','getSessionEntry',session.getSessionEntry);
 codeOwner('upsertSessionEntry','dist/plugin-sdk/session-store-runtime.js','upsertSessionEntry',session.upsertSessionEntry);
 codeOwner('loadTranscriptEventsSync','dist/session-accessor-CiKKTlbe.mjs','loadTranscriptEventsSync',accessor.loadTranscriptEventsSync);
 codeOwner('readTranscriptExportSnapshotReadOnlySync','dist/session-accessor-CiKKTlbe.mjs','readTranscriptExportSnapshotReadOnlySync',accessor.readTranscriptExportSnapshotReadOnlySync);
 codeOwner('replaceTranscriptEventsSync','dist/session-accessor-CiKKTlbe.mjs','replaceTranscriptEventsSync',accessor.replaceTranscriptEventsSync);
 codeOwner('listMemoryEntryOrigins','dist/memory-entry-origins-BCQSIB3X.mjs','n',origins.n);
 codeOwner('listMemorySessionTombstones','dist/memory-entry-origins-BCQSIB3X.mjs','r',origins.r);
 codeOwner('readShortTermRecallEntries','dist/short-term-promotion-Cy0NJmOU.mjs','readShortTermRecallEntries',promo.readShortTermRecallEntries);
 codeOwner('resolveOpenClawStateSqlitePath','dist/openclaw-state-db.paths-rJI64Ab5.mjs','s',statePaths.s);
 raw.pluginStatePathBinding={module:'dist/openclaw-state-db.paths-rJI64Ab5.mjs',export:'s',functionRef:ref(statePaths.s),
  arguments:{env:plain(process.env)},result:pluginStateDbPath,privateReturn:privateValue(pluginStateDbPath)};
 raw.typedConflictClass={classRef:ref(conflictType),prototypeRef:ref(conflictType.prototype),
  module:'dist/manager-db-kernel-DyJADqYu.mjs',export:'t',compiledSha256:hash(fs.readFileSync(path.join(runtimeRoot,'dist/manager-db-kernel-DyJADqYu.mjs')))};
 const originalGet=runtime.MemoryIndexManager.get,observedOwners=new WeakSet(),actualOwners=new Set();
 runtime.MemoryIndexManager.get=function(...args){const received=originalGet.apply(this,args),call={
  callLabel:controller().event('original-manager-get-enter').callLabel,receiverRef:ref(this),originalFunctionRef:ref(originalGet),
  args:args.map(params=>({paramsRef:ref(params),cfg:plain(params.cfg),agentId:params.agentId,purpose:params.purpose??'default',
   inspectSources:params.inspectSources??null,memoryFilesRef:ref(params.memoryFiles),maintenanceSourceRef:ref(params.maintenanceSource),
   acquireLocalServiceRef:ref(params.acquireLocalService)})),returnedPromiseRef:ref(received)};raw.getCalls.push(call);
  received.then(owner=>{call.ownerRef=ref(owner);if(!owner||observedOwners.has(owner))return;observedOwners.add(owner);actualOwners.add(owner);
   for(const name of['sync','search','status','close','listSessionCorpusEntries'])codeOwner(`MemoryIndexManager.${name}`,
    'dist/extensions/memory-core/manager-runtime.js',`MemoryIndexManager.prototype.${name}`,owner[name]);
   const actualStatus=owner.status();
   raw.ownerBindings.push({ownerRef:ref(owner),searchEffectsOwnerRef:controller().searchEffects.reference(owner),
    classRef:ref(runtime.MemoryIndexManager),prototypeRef:ref(Object.getPrototypeOf(owner)),
    databaseRef:ref(owner.publishedDatabase),nativeConnectionRef:ref(owner.publishedDatabase.db),
    dbPath:owner.publishedDatabase.db.location('main'),purpose:owner.purpose,
    providerIdentity:{method:'status',methodRef:ref(owner.status),result:plain(actualStatus),privateReturn:privateValue(actualStatus)},
    methods:['sync','search','status','close','listSessionCorpusEntries'].map(name=>({name,functionRef:ref(owner[name]),functionSourceSha256:hash(Function.prototype.toString.call(owner[name]))}))});
  },error=>{call.errorRef=ref(error);});return received;
 };
 let manager=null,exiting=false;
 const persist=()=>{raw.passiveChannels=controller().passiveChannels;
  fs.writeFileSync(path.join(evidenceDirectory,`${safeName(actor)}-${instance}-raw.json`),JSON.stringify(raw)+'\n');};
 async function getManager(){if(!manager){manager=await runtime.MemoryIndexManager.get({cfg,agentId:input.identity.agentId,purpose:'cli'});
  if(!manager)throw Error('Original manager unavailable');
  const owner={ownerId:`${actor}:${instance}:manager-${raw.owners.length+1}`,purpose:manager.purpose,
   databasePath:manager.publishedDatabase.db.location('main'),settings:plain(manager.settings)};raw.owners.push(owner);
  codeOwner('MemoryIndexManager.sync','dist/extensions/memory-core/manager-runtime.js','MemoryIndexManager.prototype.sync',manager.sync);
  codeOwner('MemoryIndexManager.status','dist/extensions/memory-core/manager-runtime.js','MemoryIndexManager.prototype.status',manager.status);
 }return manager;}
 async function close(){controller().searchEffects.assertDrained();
  if(manager){const owned=manager;await owned.close();manager=null;}
  await runtime.closeAllMemoryIndexManagers();
  await(await imp('dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs')).s(base);
  await(await imp('dist/plugin-state-store-BPUaLoVD.mjs')).u();raw.closed=true;}
 async function sourceDocuments(){const names=new Set([...Object.keys(input.initialFiles),'MEMORY.md','DREAMS.md']);
  async function visit(folder){for(const entry of await fsp.readdir(folder,{withFileTypes:true})){
   const filename=path.join(folder,entry.name);if(entry.isDirectory())await visit(filename);else names.add(path.relative(workspace,filename).replaceAll(path.sep,'/'));
  }}await visit(workspace);const result=[];
  for(const relative of [...names].sort()){
   const filename=path.join(workspace,relative);try{const stat=await fsp.lstat(filename,{bigint:true});
    if(!stat.isFile()||stat.isSymbolicLink())throw Error('Unowned source during capture');const bytes=await fsp.readFile(filename);
    result.push({path:relative,absolutePath:filename,kind:'file',text:bytes.toString('utf8'),hex:bytes.toString('hex'),sha256:hash(bytes),mtimeNs:stat.mtimeNs.toString(),
     rawStat:Object.fromEntries(Object.getOwnPropertyNames(stat).map(key=>[key,typeof stat[key]==='bigint'?stat[key].toString():stat[key]]))});
   }catch(error){if(error.code!=='ENOENT')throw error;result.push({path:relative,absolutePath:filename,kind:'missing',error:err(error)});}
  }return result;
 }
 async function snapshot(label,command){
  controller().searchEffects.assertDrained();
  const entered=controller().event('physical-snapshot-enter',{label,dbPath});
  const db=new DatabaseSync(dbPath,{readOnly:true});let schema,tables;
  try{db.exec('PRAGMA query_only=ON; BEGIN DEFERRED');schema=db.prepare("SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name").all();tables={};
   for(const row of schema.filter(item=>item.type==='table'&&/^(memory_|session_)/u.test(item.name))){
    const name='"'+row.name.replaceAll('"','""')+'"',columns=db.prepare(`PRAGMA table_info(${name})`).all(),
     rows=db.prepare(`SELECT * FROM ${name}`).all().map(row=>Object.fromEntries(Object.entries(row).map(([key,value])=>[key,sqlValue(value)])));
    tables[row.name]={columns:columns.map(column=>column.name),columnInfo:columns,rows,rowCount:rows.length};
   }
  }finally{if(db.isTransaction)db.exec('ROLLBACK');db.close();}
  const documents=await sourceDocuments();
  const publicState={origins:origins.n({agentId:input.identity.agentId}),tombstones:origins.r({agentId:input.identity.agentId}),
   recallEntries:await promo.readShortTermRecallEntries({workspaceDir:workspace,nowMs:Date.now()})};
  const transcriptReadStart=raw.sessionTranscriptExportReads.length;
  const sessions=input.sessionFacts.sessions.map(fact=>{const scope={agentId:fact.agentId,sessionKey:fact.sessionKey,sessionId:fact.sessionId,
   storePath:session.resolveStorePath(undefined,{agentId:fact.agentId})};
   const entry=session.getSessionEntry(scope),exportSnapshot=captureOriginalTranscriptExportRead({accessor,scope,ref,
    event:controller().event,receipts:raw.sessionTranscriptExportReads});
   if(!exportSnapshot||!Array.isArray(exportSnapshot.events))throw Error('Original read-only transcript export unavailable during observation');
   return{agentId:fact.agentId,sessionKey:fact.sessionKey,sessionId:fact.sessionId,entry,events:exportSnapshot.events};});
  const sessionTranscriptExportReads=raw.sessionTranscriptExportReads.slice(transcriptReadStart);
  const diagnostic=await runtime.MemoryIndexManager.get({cfg,agentId:input.identity.agentId,purpose:'status'});
  if(!diagnostic)throw Error('Original read-only producer membership owner unavailable');
  const corpusEntries=await diagnostic.listSessionCorpusEntries();
  codeOwner('listSessionCorpusEntries','dist/extensions/memory-core/manager-runtime.js','MemoryIndexManager.prototype.listSessionCorpusEntries',diagnostic.listSessionCorpusEntries);
  const admission=input.sessionFacts.sessions.map(fact=>({agentId:fact.agentId,sessionId:fact.sessionId,
   admitted:corpusEntries.some(entry=>entry.agentId===fact.agentId&&entry.sessionId===fact.sessionId)}));
  const storeModule=await imp('dist/short-term-promotion-store-B6T388Bo.mjs');
  const eventModule=await imp('dist/memory-host-events-C8-U38f1.mjs');
  const ingestionModule=await imp('dist/dreaming-ingestion-state-licbtf_y.mjs');
  const consolidationModule=await imp('dist/short-term-promotion-MX1vHJuE.mjs');
  codeOwner('readStore','dist/short-term-promotion-store-B6T388Bo.mjs','a',storeModule.a);
  codeOwner('readPhaseSignalStore','dist/short-term-promotion-store-B6T388Bo.mjs','r',storeModule.r);
  codeOwner('readSessionIngestionState','dist/dreaming-ingestion-state-licbtf_y.mjs','l',ingestionModule.l);
  codeOwner('readMemoryPreimages','dist/short-term-promotion-MX1vHJuE.mjs','o',consolidationModule.o);
  codeOwner('readMemoryHostEventRecords','dist/memory-host-events-C8-U38f1.mjs','n',eventModule.n);
  const stores={recall:await storeModule.a(workspace,new Date().toISOString()),phase:await storeModule.r(workspace,new Date().toISOString()),
   ingestion:await ingestionModule.l(workspace),preimages:await consolidationModule.o(workspace),
   events:await eventModule.n({workspaceDir:workspace,env:process.env})};
  // The original keyed stores and host journals persist in the separate shared
  // state database. Retain every physical table without joining its writable
  // lifecycle; logical reader results above remain the original public values.
  const stateEntered=controller().event('physical-plugin-state-read-enter',{label,dbPath:pluginStateDbPath});
  let stateSchema=[],stateTables={},stateExists=true,stateMissingError=null,stateFileIdentity=null;
  try{
   const info=await fsp.lstat(pluginStateDbPath,{bigint:true});
   if(!info.isFile()||info.isSymbolicLink()||info.nlink!==1n)throw Error('Unowned physical plugin-state database');
   stateFileIdentity=Object.fromEntries(Object.getOwnPropertyNames(info).map(key=>[key,typeof info[key]==='bigint'?info[key].toString():info[key]]));
   const stateDb=new DatabaseSync(pluginStateDbPath,{readOnly:true});
   try{
    stateDb.exec('PRAGMA query_only=ON; BEGIN DEFERRED');
    stateSchema=stateDb.prepare('SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name').all();
    for(const table of stateSchema.filter(row=>row.type==='table')){
     const quoted='"'+table.name.replaceAll('"','""')+'"',columns=stateDb.prepare(`PRAGMA table_info(${quoted})`).all();
     const rows=stateDb.prepare(`SELECT * FROM ${quoted}`).all().map(row=>Object.fromEntries(Object.entries(row).map(([key,value])=>[key,sqlValue(value)])));
     stateTables[table.name]={columns:columns.map(column=>column.name),columnInfo:columns,rows,rowCount:rows.length};
    }
   }finally{if(stateDb.isTransaction)stateDb.exec('ROLLBACK');stateDb.close();}
  }catch(error){if(error.code!=='ENOENT')throw error;stateExists=false;stateMissingError=err(error);}
  const stateReturned=controller().event('physical-plugin-state-read-return',{label,dbPath:pluginStateDbPath});
  const statePhysical={dbPath:pluginStateDbPath,readOnly:true,exists:stateExists,schema:stateSchema,
   selectedTables:Object.keys(stateTables),tables:stateTables,...(stateMissingError?{missingError:stateMissingError}:{})};
  const pluginStatePhysical={...statePhysical,...sealed(statePhysical)};
  const returned=controller().event('physical-snapshot-return',{label,dbPath});
  const physical={dbPath,readOnly:true,schema,selectedTables:Object.keys(tables),tables},common={
   documents:documents.filter(item=>/\.(md|txt)$/iu.test(item.path)&&(item.kind==='file'||Object.hasOwn(input.initialFiles,item.path))).map(item=>({path:item.path,exists:item.kind==='file',
    bytes:item.kind==='file'?item.hex:null,sha256:item.kind==='file'?item.sha256:null})),
   origins:publicState.origins,tombstones:publicState.tombstones,recall:stores.recall,phaseSignals:stores.phase,
   ingestion:stores.ingestion,preimages:stores.preimages,sessions:{facts:sessions,admission},
   events:stores.events.filter(event=>event.type?.startsWith('memory.recall.')||event.type==='memory.promotion.applied').map(event=>{
    const value=plain(event);if(value.type==='memory.promotion.applied'&&Object.hasOwn(value,'memoryPath')){
     const relative=path.relative(workspace,value.memoryPath).replaceAll(path.sep,'/');
     if(relative.startsWith('../')||path.isAbsolute(relative))throw Error('Original public promotion event target escaped owned root');
     value.memoryPath=`$WORKSPACE/${relative}`;
    }return value;
   }),
   index:(tables.memory_index_chunks?.rows??[]).map(row=>({path:row.path,source:row.source,startLine:row.start_line,endLine:row.end_line,text:row.text}))
    .sort((left,right)=>left.path.localeCompare(right.path)||left.source.localeCompare(right.source)||left.startLine-right.startLine||left.endLine-right.endLine||left.text.localeCompare(right.text)),
   concurrency:{markerVisible:publicState.tombstones.some(row=>row.sessionId===input.forgetCalls.selected.sessionIds[0]),
    forgetSettled:command.concurrency.forgetSettled,oldBuildSettled:command.concurrency.oldBuildSettled}};
  const capture={label,pid:process.pid,actor,instance,documents,publicState,stores,sessions,sessionTranscriptExportReads,
   pluginStatePhysical,pluginStateCapture:{enterSeq:stateEntered.sequence,returnSeq:stateReturned.sequence,
    startedAtNs:stateEntered.atNs,finishedAtNs:stateReturned.atNs,pathBindingRef:raw.pluginStatePathBinding.functionRef,
    fileIdentity:stateFileIdentity},
   originalCorpusMembership:{ownerRef:ref(diagnostic),methodRef:ref(diagnostic.listSessionCorpusEntries),entries:corpusEntries,...sealed(corpusEntries)},
   coordinatedCalls:command.coordinatedCalls,
   publicReadReturns:{origins:privateValue(publicState.origins),tombstones:privateValue(publicState.tombstones),
    recallEntries:privateValue(publicState.recallEntries),stores:privateValue(stores),sessions:privateValue(sessions)},
   enterSeq:entered.sequence,returnSeq:returned.sequence,
   startedAtNs:entered.atNs,finishedAtNs:returned.atNs,physical:{...physical,...sealed(physical)},common,commonSeal:sealed(common)};
  raw.snapshots.push(capture);return capture;
 }
 async function execute(command){
  const{operation,label}=command;
  if(command.wallClockNowMs!==undefined&&command.wallClockNowMs!==Date.now())controller().setWallClock(command.wallClockNowMs);
  controller().setCallLabel(label??operation);
  const entry={...command,startedAtNs:process.hrtime.bigint().toString(),arguments:plain(command)};raw.calls.push(entry);
  const sourceKind={'original-sync':'sync','original-forget':'forget','original-promotion':'promotion','public-memory-search':'search','original-record-short-term-recalls':'recall'}[operation];
  const sourceClock=controller().sourceClock;
  if(sourceKind)sourceClock.beginCall(`${sourceKind}:${label}`,{commandId:command.id,actor,instance,pid:process.pid,
   wallClockNowMs:Date.now(),enteredAtNs:entry.startedAtNs});
  let actual,publicCall,snapshotValue;
  function searchSettled(status,requiresRecall){try{
   entry.searchEffectsPublicSettlement=controller().searchEffects.settled(label,{status,requiresRecall},actualOwners);
  }catch(error){entry.searchEffectsControlError=err(error);}}
  function entering(apiName,args){const observed=controller().event('original-public-owner-enter',{apiName,args:plain(args)});
   const record={type:'original-enter',id:command.id,actor,pid:process.pid,instance,apiName,sequence:observed.sequence,
    atNs:observed.atNs,originalStack:new Error('Actual original public owner invocation').stack};entry.originalEntered=record;
   persist();process.send?.(record);}
  try{
   if(operation==='prepare-real-host-inputs'){
    raw.initialSourceDocuments=await sourceDocuments();raw.inputFileReceipts=[];
    for(const[relative,text]of Object.entries(input.initialFiles)){const filename=path.join(workspace,relative);
     await fsp.mkdir(path.dirname(filename),{recursive:true});const written=await fsp.writeFile(filename,text,{flag:'wx'});
     const dated=await fsp.utimes(filename,input.clock.initialSourceMtimeMs/1000,input.clock.initialSourceMtimeMs/1000);
     raw.inputFileReceipts.push({path:relative,absolutePath:filename,bytes:Buffer.from(text).toString('hex'),flags:'wx',
      writeReturn:privateValue(written),utimesArguments:[filename,input.clock.initialSourceMtimeMs/1000,input.clock.initialSourceMtimeMs/1000],utimesReturn:privateValue(dated)});
    }
    raw.preparedSourceDocuments=await sourceDocuments();
    for(const fact of input.sessionFacts.sessions){
     const scope={agentId:fact.agentId,sessionKey:fact.sessionKey,sessionId:fact.sessionId,
      storePath:session.resolveStorePath(undefined,{agentId:fact.agentId})};
     const upsertRequest={...scope,entry:plain(fact.entry)},upsert=await session.upsertSessionEntry(upsertRequest);
     const receipt={scope,upsertRequest,upsertReturn:privateValue(upsert)};raw.producerReceipts.push(receipt);
     const events=plain(fact.events),replacement={method:'replaceTranscriptEventsSync',
      request:{scope:plain(scope),events:plain(events)},beforeEvents:accessor.loadTranscriptEventsSync(scope)};
     receipt.transcriptReplacement=replacement;
     const replaced=accessor.replaceTranscriptEventsSync(scope,events);
     replacement.result=replaced;replacement.privateReturn=privateValue(replaced);replacement.eventsArgumentAfter=plain(events);
     receipt.events=accessor.loadTranscriptEventsSync(scope);
    }
   }else if(operation==='acquire-original-owner'){await getManager();}
   else if(operation==='original-sync'){
    const owner=await getManager(),params=plain(input.syncs[label]);
    const progress=update=>{entry.progress??=[];entry.progress.push(plain(update));
     const lastSource=input.config.memory.search.sources.includes('sessions')?'session':'memory';
     if(update.total>0&&update.completed===update.total&&update.label?.startsWith(`Indexing ${lastSource} files`)){
      controller().pause('rebuild.revision-captured-before-publication',{sourceOwner:'MemoryIndexManager.sync.original-progress-return',
       update:plain(update),originalStack:new Error('Original final source progress callback').stack,
       publishedDbPath:owner.publishedDatabase.db.location('main'),shadowDbPath:owner.database?.db?.location('main')??null,
       originalCapturedRevisionRead:controller().getReindexRevisionRead()});
     }
    };
    entry.originalArguments={...params,progress:'source-bound-functional-fixture-checkpoint'};
    entering('MemoryIndexManager.sync',params);
    actual=await owner.sync({...params,progress});publicCall={operation:'sync',label,outcome:{status:'fulfilled',isTypedConflict:false}};
   }else if(operation==='public-memory-search'){
    const opts={config:cfg,getConfig:()=>cfg,agentId:input.identity.agentId,agentSessionKey:input.identity.requesterSessionKey};
    controller().searchEffects.begin(label);
    const tool=tools.createMemorySearchTool(opts);if(!tool)throw Error('Original public memory search tool unavailable');
    const args=plain(input.queries[label]);entry.originalArguments=args;entering('memory_search.execute',args);
    actual=await tool.execute(`forget-index-fence:${label}`,args);
    const envelope=plain(actual),text=envelope.content?.[0]?.text;
    if(typeof text!=='string'||!isDeepStrictEqual(JSON.parse(text),envelope.details))throw Error('Original public envelope/details carrier diverged');
    entry.publicTool={envelope,details:envelope.details,carrierJSON:text,...sealed(envelope)};
    searchSettled('fulfilled',envelope.details.unavailable!==true);
    publicCall={operation:'search',label,outcome:{status:'fulfilled',result:envelope.details}};
   }else if(operation==='original-forget'){
    const params=plain(input.forgetCalls[label]),opts={agent:input.identity.agentId,session:params.sessionIds,
     hookSource:params.hookSources,participant:params.participants,since:params.since,dryRun:params.dryRun,json:true};
    entry.originalArguments=plain(opts);const original=runtimeIO.writeJson,stdoutWrite=process.stdout.write,stdout=[];
    process.stdout.write=function(chunk,...args){const encoding=typeof args[0]==='string'?args[0]:undefined;
     stdout.push(typeof chunk==='string'?Buffer.from(chunk,encoding):Buffer.from(chunk));return stdoutWrite.call(this,chunk,...args);};
    runtimeIO.writeJson=function(value,...args){entry.actualWriteJson={value:plain(value),privateReturnValue:privateValue(value),serializedJSON:JSON.stringify(value)};
     const returned=original.call(this,value,...args);entry.actualWriteJson.privateWriterReturn=privateValue(returned);return returned;};
    entering('runMemoryForget',opts);
    try{actual=await originalCli.runMemoryForget(opts);}finally{runtimeIO.writeJson=original;process.stdout.write=stdoutWrite;
     const bytes=Buffer.concat(stdout);entry.actualCliStdout={hex:bytes.toString('hex'),text:bytes.toString('utf8'),sha256:hash(bytes)};}
    if(!entry.actualWriteJson)throw Error('Original whole CLI forget emitted no report');
    publicCall={operation:'forget',label,outcome:{status:'fulfilled',result:entry.actualWriteJson.value}};
   }else if(operation==='original-record-short-term-recalls'){
    const params={workspaceDir:workspace,nowMs:Date.now(),...plain(input.recallCalls[label])};entry.originalArguments=params;
    entering('recordShortTermRecalls',params);actual=await promo.recordShortTermRecalls(params);
    publicCall={operation:'recall',label,outcome:{status:'fulfilled'}};
   }else if(operation==='original-promotion'){
    const declared=input.promotions[label],selection=declared.candidateSelection;let candidates;
    if(selection.mode==='literal-direct-candidates')candidates=plain(selection.candidates);
    else{const options={workspaceDir:workspace,nowMs:Date.now(),...plain(declared.options)};
     const ranked=await promo.rankShortTermPromotionCandidates(options);entry.ranking={request:options,result:plain(ranked),privateReturn:privateValue(ranked)};
     candidates=ranked.filter(candidate=>selection.keys.includes(candidate.key));
    }
    const params={workspaceDir:workspace,nowMs:Date.now(),candidates,...plain(declared.options)};
    if(declared.consolidation){params.consolidation={logger:{info:(...args)=>(entry.logs??=[]).push({level:'info',args}),warn:(...args)=>(entry.logs??=[]).push({level:'warn',args})},
     subagent:{complete:async request=>{const completion={request:plain(request)};(entry.completions??=[]).push(completion);
      controller().pause('promotion.model-planning-before-final-lock',{sourceOwner:'consolidateMemory.actual-subagent-complete-await',request:plain(request),
       originalStack:new Error('Original consolidation completion callback').stack});
      const returned={text:declared.consolidation.completion.text};completion.returned=returned;return returned;
     }}};}
    entry.originalArguments=plain({...params,consolidation:declared.consolidation});entering('applyShortTermPromotions',entry.originalArguments);
    actual=await promo.applyShortTermPromotions(params);
    const result=plain(actual),relative=path.relative(workspace,result.memoryPath).replaceAll(path.sep,'/');
    if(relative.startsWith('../')||path.isAbsolute(relative))throw Error('Original promotion target escaped owned workspace');
    entry.publicPromotionResult=plain(actual);result.memoryPath=`$WORKSPACE/${relative}`;
    publicCall={operation:'promotion',label,outcome:{status:'fulfilled',result}};
   }else if(operation==='await-original-search-effects'){
    entry.searchEffectsControlEnter=controller().event('original-search-effects-control-enter',{label,commandId:command.id});
    controller().flush();persist();
    entry.searchEffects=await controller().searchEffects.awaitEffects(label,actualOwners);
   }else if(operation==='capture-physical-state'){snapshotValue=await snapshot(label,command);}
   else if(operation==='original-owner-close'){await close();}
   else if(operation==='process-exit'){await close();exiting=true;}
   else throw Error(`Unknown frozen native fixture operation ${operation}`);
   entry.privateReturn=privateValue(actual);entry.returnedUndefined=actual===undefined;
  }catch(error){if(operation==='public-memory-search')searchSettled('rejected',false);
   entry.error=err(error);entry.privateError=privateValue(error);
   entry.errorType={errorRef:ref(error),originalTypedClassRef:ref(conflictType),originalTypedPrototypeRef:ref(conflictType.prototype),
    constructorName:Object.getPrototypeOf(error)?.constructor?.name??null,
    isError:error instanceof Error,isTypedConflict:error instanceof conflictType,
    originalConflictConstructorName:conflictType.name,prototypeChain:[],prototypeChainRefs:[]};
   for(let proto=Object.getPrototypeOf(error);proto;proto=Object.getPrototypeOf(proto)){
    entry.errorType.prototypeChain.push(proto.constructor?.name??null);entry.errorType.prototypeChainRefs.push(ref(proto));}
   entry.errorOwnProperties=Reflect.ownKeys(error).map(key=>{const descriptor=Object.getOwnPropertyDescriptor(error,key);
    return{key:typeof key==='symbol'?{symbolDescription:key.description}:key,
     enumerable:descriptor.enumerable,configurable:descriptor.configurable,...(Object.hasOwn(descriptor,'value')?{value:privateValue(descriptor.value)}:{accessor:true})};});
   const publicKind={'original-sync':'sync','original-forget':'forget','original-promotion':'promotion','public-memory-search':'search','original-record-short-term-recalls':'recall'}[operation];
   if(publicKind)publicCall={operation:publicKind,label,outcome:operation==='original-sync'?{status:'rejected',isTypedConflict:error instanceof conflictType}:
    {status:'rejected',error:{message:error.message,...(error.code===undefined?{}:{code:error.code})}}};
   else entry.infrastructureError=err(error);
  }finally{entry.settledAtNs=process.hrtime.bigint().toString();if(sourceKind)sourceClock.endCall();
   raw.sourceClock={protocol:input.clock.sourceWriteClock.protocol,receipts:sourceClock.receipts(),failures:sourceClock.failures(),blocked:sourceClock.blocked()};
   raw.controlFailures=controller().controlFailures;
   controller().setCallLabel(null);controller().flush();persist();}
  return{type:'settled',id:command.id,...(publicCall?{publicCall}:{}),...(snapshotValue?{snapshot:snapshotValue}:{}),
   privateReturn:entry.privateReturn??null,error:entry.error??null,...(entry.infrastructureError?{infrastructureError:entry.infrastructureError}:{}),
   providerIdentity:raw.ownerBindings.at(-1)?.providerIdentity??null,sourceClockBlocked:sourceClock.blocked(),sourceClockFailures:sourceClock.failures(),
   controlBlocked:controller().controlFailures.length>0,controlFailures:controller().controlFailures,actor,pid:process.pid,instance,exiting};
 }
 return{execute,isExiting:()=>exiting,persist};
}
