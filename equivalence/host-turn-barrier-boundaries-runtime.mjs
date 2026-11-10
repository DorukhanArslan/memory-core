// One real Native host owner and session, using the pristine runReplyAgent caller.
// The only controlled execution seam is the declared offline provider transport.
import fs from 'node:fs/promises';
import fsSync from 'node:fs';
import path from 'node:path';
import {pathToFileURL,fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
import {isDeepStrictEqual} from 'node:util';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
const BRIDGE=Symbol.for('memory-core.equivalence.host-turn-barrier-provider');
const PROVIDER='fixture-turn-barrier-model', MODEL='scripted-turn-barrier-model';
const transported=value=>JSON.parse(JSON.stringify(value));
const errorRecord=error=>({name:error.name,message:error.message,code:error.code,stack:error.stack});
const hash=bytes=>createHash('sha256').update(bytes).digest('hex');
function sourceObservation(workspace,relative){
 const absolute=path.join(workspace,relative);
 try{const stat=fsSync.lstatSync(absolute);if(!stat.isFile())return{path:relative,kind:stat.isSymbolicLink()?'symlink':'other'};
 const bytes=fsSync.readFileSync(absolute);return{path:relative,kind:'file',text:bytes.toString('utf8'),hex:bytes.toString('hex')};}
 catch(error){if(error.code==='ENOENT')return{path:relative,kind:'missing'};throw error;}
}
function sourceMetadata(workspace,relative){
 const absolute=path.join(workspace,relative);try{const stat=fsSync.lstatSync(absolute);const bytes=fsSync.readFileSync(absolute);
 return{absolutePath:absolute,nlink:stat.nlink,ino:stat.ino,size:stat.size,mtimeMs:stat.mtimeMs,atimeMs:stat.atimeMs,sha256:hash(bytes)};}
 catch(error){if(error.code==='ENOENT')return{absolutePath:absolute,kind:'missing'};throw error;}
}
function ownerSnapshot(){
 const state=globalThis[Symbol.for('openclaw.sessionMaintenance')];
 return [...(state?.sessions??[])].map(([sessionKey,s])=>({sessionKey,foreground:s.foreground,owners:[...s.owners].map(o=>({
 id:o.sequence,lifecycleGeneration:o.lifecycleGeneration,preemptible:o.preemptible,running:o.running,
 writesReleased:o.writesReleased,aborted:o.controller.signal.aborted,predecessors:o.predecessors.map(p=>p.sequence)}))}));
}
function readSqliteFiles(directory){
 const files=[];
 function visit(base){for(const item of fsSync.readdirSync(base,{withFileTypes:true})){const filename=path.join(base,item.name);
  if(item.isDirectory())visit(filename);else if(item.isFile()&&filename.endsWith('.sqlite'))files.push(filename);}}
 visit(directory);
 return files.map(filename=>{let db;try{db=new DatabaseSync(filename,{readOnly:true});
 const tables=db.prepare("SELECT name FROM sqlite_schema WHERE type='table' AND (name LIKE 'memory_index_%' OR name LIKE 'session_%' OR name LIKE 'transcript_%') ORDER BY name").all()
 .map(x=>x.name).filter(name=>!/_fts_(config|content|data|docsize|idx)$/.test(name));
 return{path:path.relative(directory,filename).replaceAll(path.sep,'/'),tables:tables.map(name=>({name,rows:db.prepare('SELECT * FROM "'+name.replaceAll('"','""')+'"').all()
 .map(row=>Object.fromEntries(Object.entries(row).map(([key,value])=>[key,value instanceof Uint8Array?{type:'bytes',hex:Buffer.from(value).toString('hex')}:value])))}))};
 }catch(error){return{path:path.relative(directory,filename),error:errorRecord(error)};}finally{db?.close();}});
}
function actualToolResult(context){const message=[...context.messages].reverse().find(m=>m.role==='toolResult');
 if(!message)throw Error('The actual model context contains no tool result');return message;}
function unwrapMemoryResult(message,expected){
 if(message.toolName!=='tool_call')throw Error('The actual deferred memory dispatch used another tool');
 const carrier=message.content?.find(x=>x.type==='text');if(!carrier)throw Error('Missing actual deferred tool carrier');
 const value=JSON.parse(carrier.text);if(value.tool?.name!==expected||!value.result?.details)throw Error('Wrong actual memory tool result');
 const nested=JSON.parse(value.result.content[0].text);
 if(!isDeepStrictEqual(nested,value.result.details))throw Error('The actual memory carrier and details differ');
 return transported(value.result.details);
}
export async function runHostTurnBarrierBoundariesRuntime(input,runtimeConfig){
 const scenarios=['pending-optional-preemption','target-open-preparation','committed-maintenance','refused-maintenance','refused-foreground','cold-publication-failure'];
 if(!input||input.source!=='MEMORY.md'||!scenarios.includes(input.scenario)||Date.now()!==input.nowMs||
 ![runtimeConfig?.runtimeRoot,runtimeConfig?.evidenceDirectory,runtimeConfig?.stateDirectory].every(x=>typeof x==='string'&&path.isAbsolute(x)))throw Error('The independent boundary actor requires its owned exact input and clock');
 const directory=runtimeConfig.stateDirectory,workspace=path.join(directory,'workspace'),agentDir=path.join(directory,'agent');
 await fs.mkdir(workspace,{recursive:true});await fs.mkdir(agentDir,{recursive:true});
 process.env.OPENCLAW_STATE_DIR=directory;process.env.OPENCLAW_HOME=directory;process.env.OPENCLAW_CONFIG_PATH=runtimeConfig.configPath;process.env.JITI_FS_CACHE='false';
 const pluginPath=fileURLToPath(new URL('./host-turn-barrier-provider/index.mjs',import.meta.url));
 const cfg={logging:{level:'silent',consoleLevel:'silent',file:path.join(directory,'native.log')},
 plugins:{allow:[PROVIDER,'memory-core'],load:{paths:[pluginPath]},entries:{[PROVIDER]:{enabled:true},'memory-core':{enabled:true}},slots:{memory:'memory-core'}},
 agents:{list:[{id:input.identity.agentId,default:true,workspace,agentDir}],defaults:{workspace,skipBootstrap:input.policy.nativeSkipBootstrap,model:{primary:`${PROVIDER}/${MODEL}`},
 compaction:{enabled:input.policy.compactionEnabled,reserveTokens:input.policy.reserveTokens,memoryFlush:{enabled:input.policy.memoryFlushEnabled,softThresholdTokens:input.policy.softThresholdTokens}}}},
 session:{store:path.join(directory,'sessions.json'),maintenance:{mode:'warn'}},tools:{profile:'coding',loopDetection:{enabled:false},fs:{workspaceOnly:true}},
 memory:{citations:'off',search:{enabled:true,provider:'none',fallback:'none',sources:input.policy.memorySources,rememberAcrossConversations:false,
 experimental:{sessionMemory:input.policy.sessionMemory},store:{vector:{enabled:false}},query:{maxResults:5,minScore:0}}},
 models:{providers:{[PROVIDER]:{api:'openai-completions',baseUrl:'http://127.0.0.1:1/v1',apiKey:'fixture-not-a-credential',models:[{id:MODEL,name:'Offline boundary model',api:'openai-completions',reasoning:false,input:['text'],contextWindow:input.policy.contextWindowTokens,maxTokens:4096,cost:{input:0,output:0,cacheRead:0,cacheWrite:0}}]}}}};
 await fs.writeFile(runtimeConfig.configPath,JSON.stringify(cfg));
 const raw={kind:'host-turn-barrier-boundaries-native',input:transported(input),request:transported(input),fixtureBase:directory,pid:process.pid,ppid:process.ppid,
 executable:process.execPath,execArgv:process.execArgv,config:cfg,turns:[],maintenanceCalls:[],events:[],metadataOperations:[],faultOperations:[],fixtureOperations:[],snapshots:[],closeReceipts:[],lease:null};
 let activeTurn,sequence=0,scheduler,unsubscribe,closeManagers,closeAgentDatabases,disposeMcp,clearConfig,waitMaintenance,lease,pendingFollowup;
 let maintenanceReadyResolve;const maintenanceReady=new Promise(resolve=>{maintenanceReadyResolve=resolve;});
 let maintenanceCheckpoint=()=>null;
 const watchedOwners=new WeakSet();
 const record=(event,extra={})=>{const value={sequence:sequence++,event,atMs:Date.now(),atNs:process.hrtime.bigint().toString(),turn:activeTurn?.label??null,owners:ownerSnapshot(),...extra};raw.events.push(value);return value;};
 const owners=()=>[...(globalThis[Symbol.for('openclaw.sessionMaintenance')]?.sessions.get(input.identity.sessionKey)?.owners??[])];
 function observeOwners(){for(const owner of owners()){
  if(watchedOwners.has(owner))continue;watchedOwners.add(owner);const ownerId=owner.sequence;
  owner.controller.signal.addEventListener('abort',()=>record('actual-maintenance-abort',{ownerId,reason:errorRecord(owner.controller.signal.reason),checkpoint:maintenanceCheckpoint()}),{once:true});
  owner.done.then(()=>record('actual-maintenance-done',{ownerId,checkpoint:maintenanceCheckpoint()}));}}
 const progress=phase=>{observeOwners();record('provider-transport-progress',{phase});};
 const imp=relative=>import(pathToFileURL(path.join(runtimeConfig.runtimeRoot,relative)).href);
 function sourceFixture(relative,label){
  const before=sourceMetadata(workspace,relative),fixture=input.sourceMetadataFixture,args=[before.absolutePath,fixture.atimeMs/1000,fixture.mtimeMs/1000];
  const startedAtNs=process.hrtime.bigint().toString(),returned=fsSync.utimesSync(...args),after=sourceMetadata(workspace,relative),finishedAtNs=process.hrtime.bigint().toString();
  if(before.sha256!==after.sha256)throw Error('The metadata fixture changed actual producer bytes');
  raw.metadataOperations.push({turn:label,operation:'utimesSync',placement:fixture.placement,target:relative,before,arguments:args,returnedUndefined:returned===undefined,after,startedAtNs,finishedAtNs});record('source-metadata',{label,target:relative});
 }
 const linkAlias=path.join(directory,'fault-hard-link');
 function armHardlink(relative,label){const before=sourceMetadata(workspace,relative);fsSync.linkSync(before.absolutePath,linkAlias);
  const operation={kind:'hard-link',operation:'arm',label,target:relative,alias:linkAlias,before,after:sourceMetadata(workspace,relative),aliasStat:transported(fsSync.statSync(linkAlias))};raw.faultOperations.push(operation);record('actual-hard-link-armed',operation);}
 function removeHardlink(relative,label){const before=sourceMetadata(workspace,relative);fsSync.unlinkSync(linkAlias);
  const operation={kind:'hard-link',operation:'remove',label,target:relative,alias:linkAlias,before,after:sourceMetadata(workspace,relative)};raw.faultOperations.push(operation);record('actual-hard-link-removed',operation);}
 function armPublication(){const database=raw.resolvedMemorySearch.store.databasePath,sidecar=database+'.reindex-lock.sqlite',target=path.join(directory,'missing-sidecar-directory','journal');
  fsSync.mkdirSync(path.dirname(sidecar),{recursive:true});fsSync.symlinkSync(target,sidecar);
  const operation={kind:'publication-sidecar-symlink',operation:'arm',database,sidecar,target,isSymbolicLink:fsSync.lstatSync(sidecar).isSymbolicLink(),readlink:fsSync.readlinkSync(sidecar)};raw.faultOperations.push(operation);record('actual-publication-fault-armed',operation);}
 function warningText(payload){return [payload.warning,payload.action].filter(value=>typeof value==='string'&&value.length).join('\n');}
 async function startLease(){
  const helper=runtimeConfig.leaseHelper,python=runtimeConfig.leasePython;
  if(!helper||!python||fsSync.realpathSync(helper.path)!==helper.path||hash(fsSync.readFileSync(helper.path))!==helper.sha256||fsSync.realpathSync(python.execPath)!==python.execPath||hash(fsSync.readFileSync(python.execPath))!==python.sha256)throw Error('Unapproved target preparation lease executable or helper');
  const args=['-I','-B',helper.path,'--workspace',workspace,'--relative-path',input.maintenance.relativePath,'--owner-pid',String(process.pid)];
  const child=spawn(python.execPath,args,{env:{PATH:path.dirname(python.execPath)+':/usr/bin:/bin',LANG:'C.UTF-8',TZ:'UTC'},stdio:['pipe','pipe','pipe']});
  const state={pid:child.pid,ppid:process.pid,executable:python,helper,arguments:args,events:[],commands:[],stderr:'',exit:null};raw.lease=state;
  let count=0,failure;const waiters=[];
  const check=()=>{for(let i=waiters.length-1;i>=0;i--){const w=waiters[i],row=state.events.find(x=>x.event===w.event&&(w.id===undefined||x.id===w.id));if(row){waiters.splice(i,1);w.resolve(row);}else if(failure){waiters.splice(i,1);w.reject(failure);}}};
  const lines=createInterface({input:child.stdout});lines.on('line',wire=>{try{
   const row=JSON.parse(wire);if(row.kind!=='host-turn-barrier-boundaries-lease'||row.pid!==child.pid||row.ppid!==process.pid||row.sequence!==state.events.length)throw Error('Detached target lease receipt');
   state.events.push(row);record('actual-lease-'+row.event.toLowerCase(),{receipt:transported(row)});if(row.event==='ERROR')failure=Error(row.error.message);check();
  }catch(error){failure=error;check();}});
  child.stderr.on('data',bytes=>{state.stderr+=bytes.toString();if(state.stderr.length>65536){failure=Error('Excessive target lease stderr');check();}});
  const exited=new Promise((resolve,reject)=>{child.on('error',error=>{failure=error;check();reject(error);});child.on('exit',(code,signal)=>{state.exit={code,signal};record('actual-lease-process-exit',{code,signal});if(code!==0)failure=Error('The target lease helper failed');check();resolve(state.exit);});});
  const wait=(event,id)=>new Promise((resolve,reject)=>{waiters.push({event,id,resolve,reject});check();});
  const command=async(name,event)=>{const id='lease'+count++,value={command:name,id};state.commands.push({sequence:sequence,atNs:process.hrtime.bigint().toString(),...value});record('actual-lease-command',{command:value});child.stdin.write(JSON.stringify(value)+'\n');return await wait(event,id);};
  const armed=await wait('ARMED');if(!isDeepStrictEqual(armed.executable,{path:python.execPath,sha256:python.sha256,version:python.version})||!isDeepStrictEqual(armed.script,{path:helper.path,sha256:helper.sha256})||armed.target.path!==path.join(workspace,input.maintenance.relativePath)||armed.target.size!==0||armed.target.nlink!==1)throw Error('The lease helper admitted another target or executable');
  return{wait,command,exited,state,async finish(){if(state.exit)return;if(state.events.at(-1)?.held)await command('RELEASE','RELEASED');await command('STOP','CLOSED');await exited;}};
 }
 for(const fixture of input.fixtureFiles??[]){const filename=path.join(workspace,fixture.path);fsSync.mkdirSync(path.dirname(filename),{recursive:true});fsSync.writeFileSync(filename,fixture.content,{flag:'wx'});fsSync.utimesSync(filename,fixture.atimeMs/1000,fixture.mtimeMs/1000);const operation={...fixture,observation:sourceObservation(workspace,fixture.path),metadata:sourceMetadata(workspace,fixture.path)};raw.fixtureOperations.push(operation);record('actual-empty-target-fixture',operation);}
 try{
  const {x:createStream}=await imp('dist/llm-ASoRyt-k.mjs');
  const stream=(model,context,options)=>{
   const lastUser=[...context.messages].reverse().find(m=>m.role==='user'),userText=typeof lastUser?.content==='string'?lastUser.content:JSON.stringify(lastUser?.content);
   const emit=(content,stopReason,usage)=>({role:'assistant',content,api:model.api,provider:model.provider,model:model.id,stopReason,timestamp:Date.now(),usage:{input:usage.input,output:usage.output,cacheRead:0,cacheWrite:0,totalTokens:usage.total,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}}});
   const complete=(message,call)=>{call.reply=transported(message);const result=createStream();queueMicrotask(()=>{result.push({type:'done',reason:message.stopReason,message});result.end(message);});return result;};
   if(userText?.startsWith('Pre-compaction memory flush.')){
    observeOwners();const index=raw.maintenanceCalls.length,call={index,model:transported(model),context:transported(context),signal:{present:Boolean(options?.signal),aborted:options?.signal?.aborted}};raw.maintenanceCalls.push(call);record('actual-maintenance-model',{index,signal:call.signal});
    const usage={input:128,output:8,total:136},relative=input.maintenance.relativePath;
    if(index===0){if(input.scenario==='refused-maintenance')armHardlink(relative,'maintenance');return complete(emit([{type:'toolCall',id:'tbboundarymaintenance0',name:'write',arguments:{path:relative,content:input.maintenance.body}}],'toolUse',usage),call);}
    if(index!==1)throw Error('The maintenance corpus producer exceeded its actual-tool script');
    const receipt=actualToolResult(context);call.producingToolResult=transported(receipt);call.actualSource=sourceObservation(workspace,relative);call.actualMetadata=sourceMetadata(workspace,relative);
    if(receipt.toolName!=='write')throw Error('Maintenance did not consume its genuine write result');
    if(receipt.isError!==true){sourceFixture(relative,'maintenance');call.afterMetadata=sourceMetadata(workspace,relative);}
    else if(input.scenario==='refused-maintenance')removeHardlink(relative,'maintenance');
    if(!options?.signal)throw Error('The actual maintenance transport has no abort signal');
    record('actual-maintenance-write-result-consumed',{index,failed:receipt.isError===true,receipt:call.producingToolResult,source:call.actualSource});maintenanceReadyResolve();
    const result=createStream();const abort=()=>{call.abortReason=errorRecord(options.signal.reason);record('actual-maintenance-provider-abort',{reason:call.abortReason,signalAborted:options.signal.aborted});setImmediate(()=>{const message=emit([],'aborted',usage);message.errorMessage=String(options.signal.reason?.message??options.signal.reason);call.reply=transported(message);record('actual-maintenance-provider-abort-cleanup',{source:sourceObservation(workspace,relative)});result.push({type:'error',error:message});result.end(message);});};
    if(options.signal.aborted)abort();else options.signal.addEventListener('abort',abort,{once:true});return result;
   }
   if(!activeTurn)throw Error('An unowned foreground inference reached the boundary fixture');
   observeOwners();record('actual-model-invocation',{index:activeTurn.modelCalls.length});const turn=activeTurn,index=turn.modelCalls.length,call={index,model:transported(model),context:transported(context)};turn.modelCalls.push(call);
   const tool=(name,args)=>{const value={type:'toolCall',id:`tbb${turn.label.replaceAll('-','')}${index}`,name,arguments:args};turn.toolCalls.push({modelCall:index,...transported(value)});return[value];};
   let content,stopReason='stop';
   if(index===0){if(turn.kind==='save'){if(turn.label==='save'&&input.scenario==='refused-foreground')armHardlink(input.source,'foreground');content=tool('write',{path:input.source,content:turn.instruction.content});}else content=tool('tool_call',{id:'memory_search',args:turn.instruction.search});stopReason='toolUse';}
   else if(turn.kind==='save'&&index===1){const receipt=actualToolResult(context);turn.producingToolResult=transported(receipt);if(receipt.toolName!=='write')throw Error('The save model did not consume its actual write receipt');
    if(receipt.isError===true){if(turn.label==='save'&&input.scenario==='refused-foreground')removeHardlink(input.source,'foreground');content=[{type:'text',text:'The memory write failed.'}];}
    else{sourceFixture(input.source,turn.label);if(turn.instruction.verificationSearch){armPublication();content=tool('tool_call',{id:'memory_search',args:turn.instruction.verificationSearch});stopReason='toolUse';}else content=[{type:'text',text:'Saved.'}];}}
   else{const receipt=actualToolResult(context),searchIndex=turn.kind==='save'?2:1;
    if(index===searchIndex){turn.searchCarrier=transported(receipt);turn.search=unwrapMemoryResult(receipt,'memory_search');const hit=turn.search.results?.[0],warning=warningText(turn.search);
     if(hit){const args={path:hit.path,from:hit.startLine,lines:hit.endLine-hit.startLine+1};turn.selectedGetArguments=args;content=tool('tool_call',{id:'memory_get',args});stopReason='toolUse';}else{turn.get=null;content=[{type:'text',text:warning||'No source-backed memory found.'}];}}
    else if(index===searchIndex+1){turn.getCarrier=transported(receipt);turn.get=unwrapMemoryResult(receipt,'memory_get');if(typeof turn.get.text!=='string')throw Error('The genuine source getter returned no text');content=[{type:'text',text:[turn.get.text,warningText(turn.search)].filter(Boolean).join('\n')}];}
    else throw Error('The actual foreground model script exhausted');
   }
   const usage=turn.label==='save'?input.firstTurnUsage:turn.label==='warmup-save'?input.warmup.usage:input.followupUsage;return complete(emit(content,stopReason,usage),call);
  };
  globalThis[BRIDGE]={stream,progress};
  const configRuntime=await imp('dist/plugin-sdk/config-runtime.js');configRuntime.setRuntimeConfigSnapshot(cfg);clearConfig=configRuntime.clearRuntimeConfigSnapshot;
  const {w:setRegistry}=await imp('dist/runtime-9cxii0oQ.mjs');const {t:emptyRegistry}=await imp('dist/registry-empty-BTjzcMW2.mjs');setRegistry(emptyRegistry(),'startup-registry','gateway-bindable',workspace);
  const {t:GatewayScheduler}=await imp('dist/gateway-scheduler-TywODsdc.mjs');scheduler=new GatewayScheduler();const mcp=await imp('dist/agent-bundle-mcp-manager-api--Y4zt2wo.mjs');await mcp.p(scheduler);disposeMcp=mcp.i;
  const {o:metadataSnapshot}=await imp('dist/plugin-metadata-snapshot-DT_pRp6g.mjs');const {t:loadRegistry}=await imp('dist/loader-DpAS3szV.mjs');const metadata=metadataSnapshot({config:cfg,workspaceDir:workspace}),registry=loadRegistry({config:cfg,workspaceDir:workspace,manifestRegistry:metadata.manifestRegistry,discovery:metadata.discovery,onlyPluginIds:[PROVIDER,'memory-core'],runtimeOptions:{allowGatewaySubagentBinding:true},cache:false,throwOnLoadError:true});
  raw.pluginRegistry={providers:registry.providers.map(p=>({pluginId:p.pluginId,id:p.provider.id})),plugins:registry.plugins.map(p=>({id:p.id,status:p.status,source:p.source})),diagnostics:transported(registry.diagnostics)};
  const {t:resolveMemorySearch}=await imp('dist/memory-search-CIhUURbE.mjs');raw.resolvedMemorySearch=transported(resolveMemorySearch(cfg,input.identity.agentId));const {v:resolveMemoryFlushPlan}=await imp('dist/memory-state-BmtUbXjH.mjs');raw.resolvedFlushPlan=transported(resolveMemoryFlushPlan({cfg,contextWindowTokens:input.policy.contextWindowTokens}));
  const sessions=await imp('dist/session-accessor-CiKKTlbe.mjs');const {t:createHeader}=await imp('dist/transcript-header-CP-ow2Zr.mjs');
  const {n:dispatchReplyFromConfig}=await imp('dist/dispatch-from-config-BG9rT_X3.mjs');const {i:createReplyDispatcher}=await imp('dist/reply-dispatcher-XbSXLzuk.mjs');
  const lifecycle=await imp('dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs');closeAgentDatabases=lifecycle.s;const memoryRuntime=await imp('dist/extensions/memory-core/manager-runtime.js');closeManagers=memoryRuntime.closeAllMemoryIndexManagers;const coordinator=await imp('dist/coordinator-BinYGTDh.mjs');waitMaintenance=coordinator.r;
  const events=await imp('dist/agent-events-CwU5G442.mjs');unsubscribe=events.f(event=>{const row=transported(event);activeTurn?.toolEvents.push(row);record('actual-agent-event',{observation:row});});
  const {agentId,sessionKey,sessionId}=input.identity,storePath=path.join(directory,'sessions.json'),scope={agentId,sessionKey,storePath};raw.scope={...scope,sessionId};maintenanceCheckpoint=()=>({entry:sessions.loadSessionEntry(scope),transcript:sessions.loadTranscriptEventsSync({...scope,sessionId}),sqlite:readSqliteFiles(directory)});await sessions.replaceSessionEntry(scope,{sessionId,updatedAt:input.nowMs,compactionCount:0});await sessions.replaceTranscriptEvents({...scope,sessionId},[createHeader({sessionId,cwd:workspace})]);
  const snapshot=label=>{const value={label,sequence:sequence++,atNs:process.hrtime.bigint().toString(),source:sourceObservation(workspace,input.source),maintenanceSource:input.maintenance?sourceObservation(workspace,input.maintenance.relativePath):null,sourceMetadata:sourceMetadata(workspace,input.source),entry:sessions.loadSessionEntry(scope),transcript:sessions.loadTranscriptEventsSync({...scope,sessionId}),owners:ownerSnapshot(),sqlite:readSqliteFiles(directory)};raw.snapshots.push(transported(value));return value;};
  async function turn(label,kind,instruction){const row={label,kind,instruction:transported(instruction),toolCalls:[],modelCalls:[],toolEvents:[],deliveries:[],agentRunStarts:[]};raw.turns.push(row);activeTurn=row;row.before=snapshot('before:'+label);record('host-submission-attempt',{label});
   const dispatcher=createReplyDispatcher({deliver:async(payload,info)=>{observeOwners();record('actual-terminal-delivery',{label,payload:transported(payload),info:transported(info)});row.deliveries.push(transported(payload));
    if(label==='save'&&input.scenario==='pending-optional-preemption'){const owner=owners().find(o=>o.preemptible);if(!owner||owner.running)throw Error('No genuine scheduler-created pending owner at actual delivery');const aborted=new Promise(resolve=>owner.controller.signal.addEventListener('abort',resolve,{once:true}));record('actual-delivery-ack-held',{label,ownerId:owner.sequence});pendingFollowup=turn('followup','recall',input.followup);await aborted;record('actual-delivery-ack-released',{label,ownerId:owner.sequence});}
    return true;}});
   const ctx={Body:instruction.prompt,RawBody:instruction.prompt,BodyForAgent:instruction.prompt,BodyForCommands:instruction.prompt,SessionKey:sessionKey,From:'fixture-user',To:sessionKey,Provider:'webchat',Surface:'webchat',ChatType:'direct',SenderId:'fixture-user',CommandAuthorized:true,MessageSid:'fixture-'+label};row.dispatchContext=transported(ctx);
   const replyOptions={onAgentRunStart(runId,_identity,offered){const observation={runId,completionSource:offered?.completionSource??null,entry:sessions.loadSessionEntry(scope),transcript:sessions.loadTranscriptEventsSync({...scope,sessionId}),sqlite:readSqliteFiles(directory)};row.agentRunStarts.push(transported(observation));record('actual-agent-run-start',{label,observation:transported(observation)});}};
   try{row.dispatchResult=transported(await dispatchReplyFromConfig({ctx,cfg,dispatcher,replyOptions}));}finally{dispatcher.markComplete();row.deliveryReceipt=transported(await dispatcher.waitForIdle());}
   observeOwners();record('actual-host-return',{label,dispatchReturn:row.dispatchResult,deliveries:row.deliveries});row.after=snapshot('after:'+label);return row;}
  const stage=row=>({deliveries:row.deliveries,dispatchReturn:row.dispatchResult,search:row.search??null,get:row.get??null});
  if(input.scenario==='target-open-preparation')lease=await startLease();
  const warmup=input.warmup?await turn('warmup-save','save',input.warmup.save):null;
  const saved=await turn('save','save',input.save);let followup;
  if(input.scenario==='pending-optional-preemption')followup=await pendingFollowup;
  else if(input.scenario==='committed-maintenance'||input.scenario==='refused-maintenance'){record('awaiting-actual-maintenance-result');await maintenanceReady;observeOwners();record('running-maintenance-next-submission-boundary');followup=await turn('followup','recall',input.followup);}
  else if(input.scenario==='target-open-preparation'){await lease.wait('BREAK');observeOwners();const owner=owners().find(o=>o.preemptible&&o.running);if(!owner)throw Error('No actual running maintenance owner at blocked target open');const aborted=new Promise(resolve=>owner.controller.signal.addEventListener('abort',resolve,{once:true}));const next=turn('followup','recall',input.followup);await aborted;await new Promise(resolve=>setImmediate(resolve));record('actual-node-event-loop-live-after-abort',{ownerId:owner.sequence,nextModelCalls:raw.turns.find(t=>t.label==='followup').modelCalls.length});await lease.command('RELEASE','RELEASED');followup=await next;await owner.done;await lease.command('VERIFY','VERIFIED');await lease.command('RELEASE','RELEASED');await lease.finish();}
  else followup=await turn('followup','recall',input.followup);
  raw.result={provider:'none',scenario:input.scenario,source:sourceObservation(workspace,input.source),maintenanceSource:input.maintenance?sourceObservation(workspace,input.maintenance.relativePath):null,warmup:warmup?stage(warmup):null,save:stage(saved),followup:stage(followup)};
  record('public-outcome-fixed');activeTurn=undefined;record('teardown-maintenance-join-start');await waitMaintenance(sessionKey);record('teardown-maintenance-join-done');snapshot('after-teardown-maintenance');return raw.result;
 }catch(error){raw.error=errorRecord(error);throw error;}
 finally{
  if(lease){try{await lease.finish();}catch(error){raw.closeReceipts.push({label:'lease-helper',ok:false,error:errorRecord(error)});}}
  for(const [label,close]of [['memory-managers',closeManagers],['mcp-runtime',disposeMcp],['scheduler',scheduler?()=>scheduler.stop():undefined],['agent-databases',closeAgentDatabases]]){if(!close)continue;try{await close();raw.closeReceipts.push({label,ok:true});}catch(error){raw.closeReceipts.push({label,ok:false,error:errorRecord(error)});}}
  raw.closeOwners=ownerSnapshot();raw.closedSource=sourceObservation(workspace,input.source);raw.closedMaintenanceSource=input.maintenance?sourceObservation(workspace,input.maintenance.relativePath):null;raw.closedSqlite=readSqliteFiles(directory);unsubscribe?.();clearConfig?.();delete globalThis[BRIDGE];await fs.writeFile(path.join(runtimeConfig.evidenceDirectory,'native-raw.json'),JSON.stringify([raw]));
 }
}
