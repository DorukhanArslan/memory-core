// One real Native host owner and session, using the pristine runReplyAgent caller.
// The only controlled execution seam is the declared offline provider transport.
import fs from 'node:fs/promises';
import fsSync from 'node:fs';
import path from 'node:path';
import {pathToFileURL,fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
import {isDeepStrictEqual} from 'node:util';
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
 if(message.toolName!=='tool_call'||message.isError===true)throw Error('The actual deferred memory dispatch failed');
 const carrier=message.content?.find(x=>x.type==='text');if(!carrier)throw Error('Missing actual deferred tool carrier');
 const value=JSON.parse(carrier.text);if(value.tool?.name!==expected||!value.result?.details)throw Error('Wrong actual memory tool result');
 const nested=JSON.parse(value.result.content[0].text);
 if(!isDeepStrictEqual(nested,value.result.details))throw Error('The actual memory carrier and details differ');
 return transported(value.result.details);
}
export async function runHostTurnBarrierRuntime(input,runtimeConfig){
 if(!input||input.source!=='MEMORY.md'||input.nowMs!==1794268800000||Date.now()!==input.nowMs||
 !['cold','warm'].includes(input.initialState)||![runtimeConfig?.runtimeRoot,runtimeConfig?.evidenceDirectory,runtimeConfig?.stateDirectory].every(x=>typeof x==='string'&&path.isAbsolute(x)))
 throw Error('The natural host profile requires its exact owned input and inherited Date clock');
 const directory=runtimeConfig.stateDirectory,workspace=path.join(directory,'workspace'),agentDir=path.join(directory,'agent');
 await fs.mkdir(workspace,{recursive:true});await fs.mkdir(agentDir,{recursive:true});
 process.env.OPENCLAW_STATE_DIR=directory;process.env.OPENCLAW_HOME=directory;process.env.OPENCLAW_CONFIG_PATH=runtimeConfig.configPath;
 process.env.JITI_FS_CACHE='false';
 const pluginPath=fileURLToPath(new URL('./host-turn-barrier-provider/index.mjs',import.meta.url));
 const cfg={
 logging:{level:'silent',consoleLevel:'silent',file:path.join(directory,'native.log')},
 plugins:{allow:[PROVIDER,'memory-core'],load:{paths:[pluginPath]},entries:{[PROVIDER]:{enabled:true},'memory-core':{enabled:true}},slots:{memory:'memory-core'}},
 agents:{list:[{id:input.identity.agentId,default:true,workspace,agentDir}],defaults:{workspace,model:{primary:`${PROVIDER}/${MODEL}`},
 compaction:{enabled:input.policy.compactionEnabled,reserveTokens:input.policy.reserveTokens,memoryFlush:{enabled:input.policy.memoryFlushEnabled,softThresholdTokens:input.policy.softThresholdTokens}}}},
 session:{maintenance:{mode:'warn'}},tools:{profile:'coding',loopDetection:{enabled:false},fs:{workspaceOnly:true}},
 memory:{citations:'off',search:{enabled:true,provider:'none',fallback:'none',sources:input.policy.memorySources,
 rememberAcrossConversations:false,experimental:{sessionMemory:input.policy.sessionMemory},store:{vector:{enabled:false}},query:{maxResults:5,minScore:0}}},
 models:{providers:{[PROVIDER]:{api:'openai-completions',baseUrl:'http://127.0.0.1:1/v1',apiKey:'fixture-not-a-credential',models:[{id:MODEL,name:'Offline turn barrier model',api:'openai-completions',reasoning:false,input:['text'],contextWindow:input.policy.contextWindowTokens,maxTokens:4096,cost:{input:0,output:0,cacheRead:0,cacheWrite:0}}]}}},
 };
 await fs.writeFile(runtimeConfig.configPath,JSON.stringify(cfg));
 const raw={kind:'host-turn-barrier-native',input:transported(input),request:transported(input),fixtureBase:directory,pid:process.pid,ppid:process.ppid,
 executable:process.execPath,execArgv:process.execArgv,config:cfg,turns:[],events:[],metadataOperations:[],snapshots:[],closeReceipts:[]};
 let activeTurn,sequence=0,scheduler,unsubscribe,closeManagers,closeAgentDatabases,disposeMcp,clearConfig,waitMaintenance;
 const watchedOwners=new WeakSet();
 const record=(event,extra={})=>{const value={sequence:sequence++,event,atMs:Date.now(),atNs:process.hrtime.bigint().toString(),turn:activeTurn?.label??null,owners:ownerSnapshot(),...extra};raw.events.push(value);return value;};
 function observeOwners(){const state=globalThis[Symbol.for('openclaw.sessionMaintenance')];for(const [,s]of state?.sessions??[])for(const owner of s.owners){
 if(watchedOwners.has(owner))continue;watchedOwners.add(owner);const ownerId=owner.sequence;
 owner.controller.signal.addEventListener('abort',()=>record('actual-maintenance-abort',{ownerId,reason:errorRecord(owner.controller.signal.reason)}),{once:true});
 owner.done.then(()=>record('actual-maintenance-done',{ownerId}));}}
 const progress=phase=>{observeOwners();record('provider-transport-progress',{phase});};
 const imp=relative=>import(pathToFileURL(path.join(runtimeConfig.runtimeRoot,relative)).href);
 try{
  const {x:createStream}=await imp('dist/llm-ASoRyt-k.mjs');
  const stream=(model,context)=>{
   if(!activeTurn)throw Error('An unowned maintenance inference reached the low-usage outcomes fixture');
   observeOwners();record('actual-model-invocation',{index:activeTurn.modelCalls.length});
   const turn=activeTurn,index=turn.modelCalls.length,call={index,model:transported(model),context:transported(context)};turn.modelCalls.push(call);
   let content,stopReason='stop';
   const toolCall=(name,args)=>{const value={type:'toolCall',id:`tb${turn.label.replaceAll('-','')}${index}`,name,arguments:args};turn.toolCalls.push({modelCall:index,...transported(value)});return[value];};
   if(index===0){content=turn.kind==='save'?toolCall('write',{path:input.source,content:turn.instruction.content}):toolCall('tool_call',{id:'memory_search',args:turn.instruction.search});stopReason='toolUse';}
   else if(turn.kind==='save'){
    const receipt=actualToolResult(context);turn.producingToolResult=transported(receipt);
    if(receipt.toolName!=='write')throw Error('The save model did not consume its actual write receipt');
    if(receipt.isError===true)content=[{type:'text',text:receipt.content.filter(x=>x.type==='text').map(x=>x.text).join('\n')}];
    else{
     const before=sourceMetadata(workspace,input.source),source=sourceObservation(workspace,input.source);
     if(source.text!==turn.instruction.content)throw Error('The genuine producer bytes differ from the declared corpus');
     const fixture=input.sourceMetadataFixture,args=[before.absolutePath,fixture.atimeMs/1000,fixture.mtimeMs/1000];
     const startedAtNs=process.hrtime.bigint().toString();
     const returned=fsSync.utimesSync(...args),after=sourceMetadata(workspace,input.source);
     const finishedAtNs=process.hrtime.bigint().toString();
     if(before.sha256!==after.sha256)throw Error('The declared metadata fixture changed source bytes');
     raw.metadataOperations.push({turn:turn.label,operation:'utimesSync',placement:fixture.placement,before,arguments:args,returnedUndefined:returned===undefined,after,startedAtNs,finishedAtNs});
     record('source-metadata',{label:turn.label});
     content=[{type:'text',text:'Saved.'}];
    }
   }else if(index===1){
    const receipt=actualToolResult(context);turn.searchCarrier=transported(receipt);turn.search=unwrapMemoryResult(receipt,'memory_search');
    const hit=turn.search.results?.[0];if(hit){const args={path:hit.path,from:hit.startLine,lines:hit.endLine-hit.startLine+1};turn.selectedGetArguments=args;content=toolCall('tool_call',{id:'memory_get',args});stopReason='toolUse';}
    else{turn.get=null;content=[{type:'text',text:'No source-backed memory found.'}];}
   }else if(index===2){const receipt=actualToolResult(context);turn.getCarrier=transported(receipt);turn.get=unwrapMemoryResult(receipt,'memory_get');
    if(typeof turn.get.text!=='string')throw Error('The actual source getter returned no text');content=[{type:'text',text:turn.get.text}];
   }else throw Error('The declared actual-tool-derived model script exhausted');
   const usage=input.firstTurnUsage,message={role:'assistant',content,api:model.api,provider:model.provider,model:model.id,stopReason,timestamp:Date.now(),usage:{input:usage.input,output:usage.output,cacheRead:0,cacheWrite:0,totalTokens:usage.total,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}}};
   call.reply=transported(message);const result=createStream();queueMicrotask(()=>{result.push({type:'done',reason:stopReason,message});result.end(message);});return result;
  };
  globalThis[BRIDGE]={stream,progress};
  const configRuntime=await imp('dist/plugin-sdk/config-runtime.js');configRuntime.setRuntimeConfigSnapshot(cfg);clearConfig=configRuntime.clearRuntimeConfigSnapshot;
  const {w:setRegistry}=await imp('dist/runtime-9cxii0oQ.mjs');const {t:emptyRegistry}=await imp('dist/registry-empty-BTjzcMW2.mjs');setRegistry(emptyRegistry(),'startup-registry','gateway-bindable',workspace);
  const {t:GatewayScheduler}=await imp('dist/gateway-scheduler-TywODsdc.mjs');scheduler=new GatewayScheduler();
  const mcp=await imp('dist/agent-bundle-mcp-manager-api--Y4zt2wo.mjs');await mcp.p(scheduler);disposeMcp=mcp.i;
  const {o:metadataSnapshot}=await imp('dist/plugin-metadata-snapshot-DT_pRp6g.mjs');const {t:loadRegistry}=await imp('dist/loader-DpAS3szV.mjs');
  const metadata=metadataSnapshot({config:cfg,workspaceDir:workspace}),registry=loadRegistry({config:cfg,workspaceDir:workspace,manifestRegistry:metadata.manifestRegistry,discovery:metadata.discovery,onlyPluginIds:[PROVIDER,'memory-core'],runtimeOptions:{allowGatewaySubagentBinding:true},cache:false,throwOnLoadError:true});
  raw.pluginRegistry={providers:registry.providers.map(p=>({pluginId:p.pluginId,id:p.provider.id})),plugins:registry.plugins.map(p=>({id:p.id,status:p.status,source:p.source})),diagnostics:transported(registry.diagnostics)};
  const {t:resolveMemorySearch}=await imp('dist/memory-search-CIhUURbE.mjs');raw.resolvedMemorySearch=transported(resolveMemorySearch(cfg,input.identity.agentId));
  const sessions=await imp('dist/session-accessor-CiKKTlbe.mjs');const {t:createHeader}=await imp('dist/transcript-header-CP-ow2Zr.mjs');
  const {runReplyAgent}=await imp('dist/agent-runner.runtime-BinSrYfK.mjs');
  const lifecycle=await imp('dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs');closeAgentDatabases=lifecycle.s;
  const memoryRuntime=await imp('dist/extensions/memory-core/manager-runtime.js');closeManagers=memoryRuntime.closeAllMemoryIndexManagers;
  const coordinator=await imp('dist/coordinator-BinYGTDh.mjs');waitMaintenance=coordinator.r;
  const events=await imp('dist/agent-events-CwU5G442.mjs');unsubscribe=events.f(event=>{const row=transported(event);activeTurn?.toolEvents.push(row);record('actual-agent-event',{observation:row});});
  const {agentId,sessionKey,sessionId}=input.identity,storePath=path.join(directory,'sessions.json'),scope={agentId,sessionKey,storePath};
  raw.scope={...scope,sessionId};await sessions.replaceSessionEntry(scope,{sessionId,updatedAt:input.nowMs,compactionCount:0});
  await sessions.replaceTranscriptEvents({...scope,sessionId},[createHeader({sessionId,cwd:workspace})]);
  const snapshot=label=>{const value={label,sequence:sequence++,atNs:process.hrtime.bigint().toString(),source:sourceObservation(workspace,input.source),sourceMetadata:sourceMetadata(workspace,input.source),entry:sessions.loadSessionEntry(scope),transcript:sessions.loadTranscriptEventsSync({...scope,sessionId}),owners:ownerSnapshot(),sqlite:readSqliteFiles(directory)};raw.snapshots.push(transported(value));return value;};
  async function turn(label,kind,instruction){
   const entry=sessions.loadSessionEntry(scope),row={label,kind,instruction:transported(instruction),toolCalls:[],modelCalls:[],toolEvents:[]};raw.turns.push(row);activeTurn=row;
   row.before=snapshot(`before:${label}`);record('host-submission-attempt',{label});
   const followupRun={prompt:instruction.prompt,enqueuedAt:input.nowMs,summaryLine:'',run:{agentId,agentDir,sessionId,sessionKey,sessionFile:`sqlite:${agentId}:${sessionId}:${storePath}`,workspaceDir:workspace,config:cfg,skillsSnapshot:{prompt:'',skills:[]},provider:PROVIDER,model:MODEL,thinkingCatalog:[{provider:PROVIDER,id:MODEL,input:['text']}],thinkLevel:'off',verboseLevel:'off',elevatedLevel:'off',senderIsOwner:true,bashElevated:{enabled:false,allowed:false,defaultLevel:'off'},timeoutMs:30000,blockReplyBreak:'message_end',skipProviderRuntimeHints:true}};
   row.followupRun=transported(followupRun);
   const typing={onReplyStart:async()=>{},startTypingLoop:async()=>{},startTypingOnText:async()=>{},refreshTypingTtl(){},isActive:()=>false,markRunComplete(){},markDispatchIdle(){},cleanup(){}};
   const callInput={commandBody:instruction.prompt,followupRun,queueKey:sessionKey,resolvedQueue:{mode:'interrupt'},shouldSteer:false,shouldFollowup:false,isActive:false,typing,sessionEntry:entry,sessionStore:{[sessionKey]:entry},sessionKey,storePath,defaultModel:`${PROVIDER}/${MODEL}`,resolvedVerboseLevel:'off',isNewSession:raw.turns.length===1,blockStreamingEnabled:false,resolvedBlockStreamingBreak:'message_end',sessionCtx:{Provider:'webchat',Surface:'webchat',To:sessionKey,ChatType:'direct'},shouldInjectGroupIntro:false,typingMode:'never'};
   row.callInput=transported(callInput);
   row.reply=transported(await runReplyAgent(callInput));
   observeOwners();record('actual-host-return',{label,reply:row.reply});row.after=snapshot(`after:${label}`);return row;
  }
  const publicRecall=row=>({search:row.search,get:row.get??null,reply:row.reply});
  let warmup=null;
  if(input.initialState==='warm'){await turn('warmup-save','save',input.warmup.save);const recalled=await turn('warmup-recall','recall',input.warmup.recall);warmup=publicRecall(recalled);if(!recalled.search?.results?.length||!recalled.get)throw Error('The genuine warm positive control was not searchable');}
  const saved=await turn('save','save',input.save),source=transported(saved.after.source);
  const followup=await turn('followup','recall',input.followup);
  raw.result={provider:'none',warmup,source,followup:publicRecall(followup)};
  record('public-outcome-fixed');activeTurn=undefined;
  record('teardown-maintenance-join-start');await waitMaintenance(sessionKey);record('teardown-maintenance-join-done');
  snapshot('after-teardown-maintenance');return raw.result;
 }catch(error){raw.error=errorRecord(error);throw error;}
 finally{
  for(const [label,close]of [['memory-managers',closeManagers],['mcp-runtime',disposeMcp],['scheduler',scheduler?()=>scheduler.stop():undefined],['agent-databases',closeAgentDatabases]]){
   if(!close)continue;try{await close();raw.closeReceipts.push({label,ok:true});}catch(error){raw.closeReceipts.push({label,ok:false,error:errorRecord(error)});}}
  raw.closeOwners=ownerSnapshot();raw.closedSource=sourceObservation(workspace,input.source);
  raw.closedSqlite=readSqliteFiles(directory);
  unsubscribe?.();clearConfig?.();delete globalThis[BRIDGE];await fs.writeFile(path.join(runtimeConfig.evidenceDirectory,'native-raw.json'),JSON.stringify([raw]));
 }
}
