// Invoke the original plugin's registered managed callback and await the real public effects.
import {createHash} from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import {mock} from "node:test";
import {pathToFileURL} from "node:url";
import {snapshot, publicEvents, compressCapturedBlobs} from "./dream-light-runtime.mjs";

const digest = bytes => createHash("sha256").update(bytes).digest("hex");
const stable = value => Array.isArray(value) ? value.map(stable) : value && typeof value === "object"
  ? Object.fromEntries(Object.keys(value).sort().map(k => [k, stable(value[k])])) : value;
const hashes = new Set([
  "b82bb8b4368ffde4193bbf78f910c4b1bfa82e41f5c9b6c89938d0f3845f276a",
  "6f420c44c89f4ab50620a5464412304da26d323606acc5ed91febf29692411ea",
  "7a21355e6efb17e5f66cba6ee9dabe5c6abbce57b8d47431d2513686c178dd31",
  "56252eeaea58df8e590131d1df13ba58c979c18026d7912877897c9f966ef67d",
  "dedb4a8771293d1f0da170a8166d795a61046f7bdbfbaab18f0562ad460c0e50",
  "bac99a659f21fde2606a6aa56c4181cef5289d279ac955475c989f4902f83434",
  "3c95fa951a443ba1911f52e3c31c4dd763c4240f1baa625f2e4e3271cff49e01"
]);
const token = "__openclaw_memory_core_short_term_promotion_dream__";
const recallFile = "memory/.dreams/short-term-recall.json";
const phaseFile = "memory/.dreams/phase-signals.json";
const errorRecord = e => ({name:e.name,message:e.message,stack:e.stack});

export async function runDreamDeepRuntime(input, runtimeConfig) {
  const inputSha256 = digest(JSON.stringify(stable(input)));
  if (!hashes.has(inputSha256) || !path.isAbsolute(runtimeConfig.evidenceDirectory) ||
      !path.isAbsolute(runtimeConfig.runtimeRoot)) throw Error("Unbound deep dreaming request");
  const directory = runtimeConfig.evidenceDirectory;
  await fs.mkdir(directory,{recursive:true});
  const root = await fs.mkdtemp(path.join(directory,"native-deep-"));
  const workspace = path.join(root,"workspace");
  const env = {OPENCLAW_STATE_DIR:path.join(root,"state"),OPENCLAW_HOME:root,OPENCLAW_CONFIG_PATH:path.join(root,"openclaw.json")};
  const saved = Object.fromEntries(Object.keys(env).map(k => [k,process.env[k]]));
  const options = input.options;
  const dreaming = {enabled:options.enabled,timezone:options.timezone,storage:{mode:options.storageMode},phases:{
    light:{enabled:options.light},rem:{enabled:options.rem},deep:{enabled:options.enabled,limit:options.limit,
      minScore:options.minScore,minRecallCount:options.minRecallCount,minUniqueQueries:options.minUniqueQueries}}};
  const cfg = {agents:{defaults:{workspace,userTimezone:"UTC"},list:[{id:"main",workspace}]},
      plugins:{entries:{"memory-core":{enabled:true,config:{dreaming}}}},
      logging:{level:"silent",consoleLevel:"silent",file:path.join(root,"openclaw.log")}};
  const raw = {kind:"official-managed-deep-dreaming",root,workspace,input,inputSha256,env,cfg,owners:[],registrations:[],
      calls:[],turnReceipts:[],snapshots:[],atReturnSnapshots:[],blobs:{},observations:[],logs:[],factoryCalls:[],provider:[],pid:process.pid,ppid:process.ppid};
  let closeStore,clock=false,releaseNarrative,activeTurn;
  const originalDate=Date, initialTimer=setTimeout, originalPerformance=performance.now;
  async function owner(relative,alias) {
    const artifact=path.join(runtimeConfig.runtimeRoot,relative);
    const fn=(await import(pathToFileURL(artifact).href))[alias];
    if(typeof fn!=="function") throw Error("Invalid original owner "+relative);
    raw.owners.push({relative,alias,name:fn.name,sourceSha256:digest(fn.toString()),artifactSha256:digest(await fs.readFile(artifact))});
    return fn;
  }
  async function call(name,args,fn,invocation=args) {
    const receipt={name,args:structuredClone(args)};
    raw.calls.push(receipt);
    try {
      const value=await fn(...invocation);
      receipt.returned=value === undefined ? {kind:"undefined"} : {kind:"value",value:structuredClone(value)};
      return value;
    } catch(e) { receipt.error=errorRecord(e); throw e; }
  }
  const snapshotTree=()=>snapshot(root,raw.blobs);
  async function diary() {
    try {
      const file=path.join(workspace,"DREAMS.md");
      return (await fs.lstat(file)).isFile() ? await fs.readFile(file,"utf8") : null;
    }
    catch(e) {if(e.code!=="ENOENT")throw e;return null;}
  }
  try {
    Object.assign(process.env,env);
    await fs.mkdir(workspace);await fs.writeFile(env.OPENCLAW_CONFIG_PATH,JSON.stringify(cfg));
    mock.timers.enable({apis:["Date"],now:input.turns[0].nowMs});clock=true;
    for(const [name,body] of Object.entries(input.files)){
      const target=path.resolve(workspace,name);
      if(!target.startsWith(workspace+path.sep))throw Error("Unbound source path");
      await fs.mkdir(path.dirname(target),{recursive:true});await fs.writeFile(target,body,{flag:"wx"});
      await fs.utimes(target,input.turns[0].nowMs/1000,input.turns[0].nowMs/1000);
    }
    const pluginFile="dist/extensions/memory-core/index.js",artifact=path.join(runtimeConfig.runtimeRoot,pluginFile);
    const plugin=(await import(pathToFileURL(artifact).href)).default;
    raw.owners.push({relative:pluginFile,alias:"default.register",name:plugin.register.name,
       sourceSha256:digest(plugin.register.toString()),artifactSha256:digest(await fs.readFile(artifact))});
    const storeFile="dist/plugin-state-store-BPUaLoVD.mjs",stores="dist/short-term-promotion-store-B6T388Bo.mjs";
    const open=await owner(storeFile,"r");closeStore=await owner(storeFile,"u");
    const readers={recall:await owner(stores,"a"),phase:await owner(stores,"r"),carrier:await owner(stores,"i"),
      events:await owner("dist/plugin-sdk/memory-host-events.js","readMemoryHostEventRecords"),
      origins:await owner("dist/memory-entry-origins-BCQSIB3X.mjs","n"),
      preimages:await owner("dist/dreaming-state-VYUvbU-n.mjs","y")};
    const enqueue=await owner("dist/system-events-aMYQfkLb.mjs","o");
    const hooks=[];
    const logger=Object.fromEntries(["info","debug","error","warn"].map(level=>[level,(...args)=>raw.logs.push({level,args})]));
    const runtime={config:{current:()=>cfg},state:{openKeyedStore(opts){
      raw.factoryCalls.push({options:structuredClone(opts),env});
      return open("memory-core",{...opts,env});
    }}};
    if(input.provider!==null)runtime.subagent={async complete(request){
      const receipt={request:structuredClone(request),callerStack:new Error("Original dreaming provider").stack,nowMs:Date.now()};
      const reply=input.provider[raw.provider.length];raw.provider.push(receipt);
      if(!reply)throw Error("Unplanned original model call");
      receipt.reply=structuredClone(reply);
      if(activeTurn.trigger==="cron" && request.extraSystemPrompt.startsWith("You are keeping a dream diary."))
        await new Promise(resolve=>{releaseNarrative=resolve;});
      receipt.returned=structuredClone(reply);
      return structuredClone(reply);
    }};
    const api={config:cfg,runtime,logger,on(name,fn,opts) {
      raw.registrations.push({name,opts,sourceSha256:digest(fn.toString())});
      if(name==="before_agent_reply" && opts?.eligibleTriggers?.includes("cron"))hooks.push(fn);
    }};
    for(const method of ["registerService","registerMemoryCapability","registerGatewayMethod","registerTool","registerCommand","registerCli"])
      api[method]=()=>{};
    await plugin.register(api);
    if(hooks.length!==2)throw Error("Managed hook not registered");
    raw.invokedHookSha256=digest(hooks[0].toString());
    await call("writeStore",[workspace,JSON.parse(input.files[recallFile])],await owner(stores,"l"));
    if(input.files[phaseFile])await call("writePhaseSignalStore",[workspace,JSON.parse(input.files[phaseFile])],await owner(stores,"c"));
    if(input.originSeeds.length)await call("recordMemoryEntryOrigins",[{agentId:"main",origins:input.originSeeds}],
                                            await owner("dist/memory-entry-origins-BCQSIB3X.mjs","a"));
    raw.snapshots.push(await snapshotTree());
    for(const turn of input.turns) {
      activeTurn=turn;mock.timers.setTime(turn.nowMs);
      if(turn.queued)await call("enqueueSystemEvent",[token,{sessionKey:"agent:main:main",agentId:"main",contextKey:"cron:observatory"}],enqueue);
      const ctx={trigger:turn.trigger,agentId:turn.agentId,sessionKey:turn.sessionKey,workspaceDir:workspace};
      const returned=await call("before_agent_reply",[{cleanedBody:turn.cleanedBody},ctx],hooks[0]);
      raw.atReturnSnapshots.push(await snapshotTree());
      const diaryAtReturn=await diary();
      if(releaseNarrative) {
        releaseNarrative();releaseNarrative=undefined;
        const started=performance.now();
        while(!(await diary())?.includes(input.provider.at(-1).text)) {
          if(performance.now()-started>10000)throw Error("Original detached diary did not settle");
          await new Promise(resolve=>setTimeout(resolve,5));
        }
      }
      const iso=new Date(turn.nowMs).toISOString();
      for(const name of ["recall","phase"])await call("readShortTermStore",[workspace,name,iso],readers.carrier);
      const recall=await call("readStore",[workspace,iso],readers.recall),signals=await call("readPhaseSignalStore",[workspace,iso],readers.phase);
      const events=await call("readMemoryHostEventRecords",[{workspaceDir:workspace,env}],readers.events);
      const preimages=await call("readMemoryCoreWorkspaceEntries",[{workspaceDir:workspace,namespace:"dreaming-memory-backups"}],readers.preimages);
      const origins=await call("listMemoryEntryOrigins",[{agentId:"main"}],readers.origins);
      raw.turnReceipts.push({providerCalls:raw.provider.length,logCount:raw.logs.length,eventCount:events.length});
      const tree=await snapshotTree();raw.snapshots.push(tree);
      const documents=Object.fromEntries(Object.entries(tree).filter(([p])=>p.startsWith("workspace/")&&p.endsWith(".md"))
          .map(([p,f])=>[p.slice(10),Buffer.from(raw.blobs[f.sha256],"base64").toString("utf8")]));
      raw.observations.push({turn,returned:returned??null,diaryAtReturn,documents,recall,signals,preimages:preimages.map(e=>e.value),
          origins,events:publicEvents(events,workspace),modelCalls:structuredClone(raw.provider.map(r=>r.request)),
          summaries:raw.logs.map(l=>l.args[0]).filter(v=>typeof v==="string" && v.startsWith("memory-core: dreaming promotion complete"))});
    }
    raw.completed=true;return {observations:raw.observations};
  } catch(e){raw.error=errorRecord(e);throw e;}
  finally{
    if(releaseNarrative)releaseNarrative();
    if(closeStore){await closeStore();raw.storeClosed=true;}
    if(clock)mock.timers.reset();
    raw.clockRestored=Date===originalDate && setTimeout===initialTimer && performance.now===originalPerformance;
    for(const [k,v] of Object.entries(saved)){if(v===undefined)delete process.env[k];else process.env[k]=v;}
    compressCapturedBlobs(raw);
    await fs.writeFile(path.join(directory,"native-raw.json"),JSON.stringify([raw]),{flag:"wx"});
  }
}
