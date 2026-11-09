// Uncredited exact worker reply observer. Original parent retry and worker remain intact.
import fs from 'node:fs/promises';
import fsSync from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {createRequire,syncBuiltinESMExports} from 'node:module';
import {mock} from 'node:test';
const require=createRequire(import.meta.url), threads=require('node:worker_threads');
const OriginalWorker=threads.Worker, originalPost=OriginalWorker.prototype.postMessage;
const request=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
const {input,runtimeRoot:root,fixtureDirectory:directory}=request;
if (![root,directory].every(value=>typeof value==='string' && path.isAbsolute(value))) throw Error('Absolute authenticated runtime and fixture paths required');
const declaredSecrets=new Set(['worker-fixture-credential','unrelated-worker-credential-2']);
if(input.secret!=='worker-fixture-credential')throw Error('Only declared synthetic worker credentials are admitted');
const assertSynthetic=(values)=>{if(!Array.isArray(values)||values.some(value=>!declaredSecrets.has(value)))throw Error('Undeclared registry member; sensitive snapshot was not recorded');};
await fs.mkdir(directory,{recursive:true});
process.env.OPENCLAW_STATE_DIR=path.join(directory,'state');
process.env.OPENCLAW_CONFIG_PATH=path.join(directory,'openclaw.json');
process.env.OPENCLAW_HOME=directory;
const cfg={agents:{defaults:{workspace:directory}},logging:{level:'silent',consoleLevel:'silent',file:path.join(directory,'native.log')},session:{maintenance:{mode:'warn'}}};
await fs.writeFile(process.env.OPENCLAW_CONFIG_PATH,JSON.stringify(cfg));
const originalDate=Date,originalTimeout=setTimeout;
mock.timers.enable({apis:['Date'],now:1000});
const clock={owner:'node:test',apis:['Date'],nowMs:Date.now(),dateConstructorReplaced:Date!==originalDate,setTimeoutUnchanged:setTimeout===originalTimeout};
const imp=(file)=>import(pathToFileURL(path.join(root,file)).href);
const workers=new WeakMap(),observations=[],mutations=[];
const callbackObservations=[];
let register,revision,attempt=0;
const expected=pathToFileURL(path.join(root,'dist/config/sessions/session-transcript.worker.js')).href;
threads.Worker=new Proxy(OriginalWorker,{construct(target,args,newTarget){
 const worker=Reflect.construct(target,args,newTarget);
 workers.set(worker,String(args[0]));
 observations.push({event:'worker-created',url:String(args[0]),threadId:worker.threadId});
 return worker;
}});
OriginalWorker.prototype.postMessage=function(message,...rest){
 const url=workers.get(this);
 if(url===expected && message?.input?.kind==='session-entry'){
  assertSynthetic(message.input.redaction?.registeredSecretValues);
  const ordinal=++attempt, taskId=message.taskId;
  observations.push({event:'preparation-dispatch',ordinal,url,threadId:this.threadId,message:JSON.parse(JSON.stringify(message,(_k,v)=>v instanceof SharedArrayBuffer?{$type:'SharedArrayBuffer',byteLength:v.byteLength}:v))});
  const listener=(reply)=>{
   if(reply?.taskId!==taskId || !['ok','failed'].includes(reply?.status))return;
   this.removeListener('message',listener);
   observations.push({event:'actual-preparation-reply',ordinal,url,threadId:this.threadId,reply});
   if(reply.status==='ok' && reply.value?.ok===true && ordinal<=input.mutations){
    const value=ordinal===1?input.secret:`unrelated-worker-credential-${ordinal}`;
    const before=revision();register(value);const after=revision();
    mutations.push({ordinal,value,before,after});
   }
  };
  this.prependListener('message',listener);
 }
 return Reflect.apply(originalPost,this,[message,...rest]);
};
syncBuiltinESMExports();
const registry=await imp('dist/secret-redaction-registry-b2B9lcfy.mjs');register=registry.s;revision=registry.r;
assertSynthetic(registry.t().values);
const config=await imp('dist/plugin-sdk/config-runtime.js');config.setRuntimeConfigSnapshot(cfg);
const sessions=await imp('dist/plugin-sdk/session-store-runtime.js');
const accessor=await imp('dist/session-accessor-CiKKTlbe.mjs');
const engine=await imp('dist/plugin-sdk/memory-core-host-engine-sessions.js');
const {s:closeDatabases}=await imp('dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs');
const scope={agentId:'main',sessionId:'worker-fixture',sessionKey:'agent:main:dm:worker-fixture',storePath:sessions.resolveStorePath(undefined,{agentId:'main'})};
try{
 await sessions.upsertSessionEntry({...scope,entry:{sessionId:scope.sessionId,updatedAt:1000}});
 await accessor.appendTranscriptMessage(scope,{eventId:'user-1',message:{role:'user',content:`Remember ${input.secret}`,timestamp:1000},now:1000,cwd:'/fixture/work'});
 const before=accessor.loadTranscriptEventsSync(scope);
 if(input.initiallyRegistered)register(input.secret);
 const enumerated=await engine.listSessionTranscriptCorpusEntriesForAgent(scope.agentId,{includeContentRevision:false,includeRetainedSqlite:true});
 const source=enumerated.find(value=>value.sessionId===scope.sessionId && value.sessionKey===scope.sessionKey);
 if(!source)throw Error('Actual corpus enumeration did not retain the registered source identity');
 const filename=source.sessionFile;
 let result,error;
 const options={...scope,updatedAtMs:source.updatedAtMs,sessionKind:source.sessionKind,
  ...(source.generatedByDreamingNarrative?{generatedByDreamingNarrative:true}:{}),...(source.generatedByCronRun?{generatedByCronRun:true}:{})};
 if(input.observer)options.onTranscriptMessage=(message,observedAt)=>{
  const ordinal=callbackObservations.length+1;callbackObservations.push({ordinal,message,observedAt});
  if(ordinal<=input.mutations){const before=revision();register(input.secret);mutations.push({ordinal,value:input.secret,before,after:revision(),cut:'transcript-callback'});}
 };
 try{result=await engine.buildSessionEntry(filename,options);}catch(value){error={name:value.name,message:value.message};}
 const after=accessor.loadTranscriptEventsSync(scope);
 fsSync.writeFileSync(1,JSON.stringify({scope,filename,source,enumerated,clock,before,after,expected,observations,mutations,callbackObservations,result,error,attempts:attempt})+'\n');
}finally{
 threads.Worker=OriginalWorker;OriginalWorker.prototype.postMessage=originalPost;syncBuiltinESMExports();
 await closeDatabases();config.clearRuntimeConfigSnapshot();
 mock.timers.reset();
}
