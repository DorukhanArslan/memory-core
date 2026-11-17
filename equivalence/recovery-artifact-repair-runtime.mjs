// Persist damaged carrier rows, invoke the original audit and repair, retain each actual boundary.
import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { DatabaseSync, backup } from "node:sqlite";
import { mock } from "node:test";
import { pathToFileURL } from "node:url";
import { gzipSync } from "node:zlib";
import { snapshot } from "./dream-light-runtime.mjs";
const hash = bytes => createHash("sha256").update(bytes).digest("hex");
const stable = v => Array.isArray(v) ? v.map(stable) : v && typeof v === "object"
  ? Object.fromEntries(Object.keys(v).sort().map(k => [k,stable(v[k])])) : v;
const approved = new Set([
  "0a55fc2befaea963e593e7cd37fd52a2f835622720c364170e6d68350fa9c5c6",
  "ed7ba8cd137b16e3239337413cdd786194b08c033cb2f02cb3ed79532ff71cde",
  "3dba1dc6af84d2a809eec922acb8cc7cba8a46d7de974f005997254568aa428e",
  "3fa7764bd540ffbfe36cb07aca063135fd428edeedc1713676b2f61df3c3f96f",
  "1a31c9cbf4cb44e27b7d354e012d5b807739bfac9b479eccbc884c9f0341c0e7",
  "363cfb95145bcd128f9cbc9d443623499fc9b77b2c42e19142ad70396bd6201c",
  "450c333e38ad7e0082e2f293cdbb153540b35c4547377ed8cddc2eba3265f5ad"
]);
const stateMod = "dist/dreaming-state-VYUvbU-n.mjs", keyedMod = "dist/plugin-state-store-BPUaLoVD.mjs",
      promotionMod = "dist/short-term-promotion-MX1vHJuE.mjs", corpusMod = "dist/dreaming-repair-IHhh4uIq.mjs",
      storeMod = "dist/short-term-promotion-store-B6T388Bo.mjs";

export async function runRecoveryArtifactRepairRuntime(input, runtimeConfig) {
  const inputSha256 = hash(JSON.stringify(stable(input)));
  const directory = runtimeConfig.evidenceDirectory;
  if (!approved.has(inputSha256) || !path.isAbsolute(directory)) throw Error("Unknown recovery artifact fixture");
  await fs.mkdir(directory, {recursive:true});
  const root = await fs.mkdtemp(path.join(directory, "native-recovery-"));
  const workspace = path.join(root, "workspace");
  const env = {OPENCLAW_STATE_DIR:path.join(root,"state"), OPENCLAW_HOME:root,
               OPENCLAW_CONFIG_PATH:path.join(root,"openclaw.json")};
  const saved = Object.fromEntries(Object.keys(env).map(k=>[k,process.env[k]]));
  const raw = {input,inputSha256,root,workspace,env,owners:[],calls:[],stages:[],blobs:{},observations:[]};
  const storeKey = hash(workspace), now = new Date(input.nowMs).toISOString();
  const normalizeName = name => name.replace(/(\.openclaw-repair\/dreaming\/[^/]+\/(?:session-corpus|session-ingestion\.json|dreams\.md|DREAMS\.md))\.[a-f0-9-]{36}(?=\/|$)/g, "$1.$UUID");
  function paths(v) {
    if (typeof v === "string") {
      if (v === "plugin-state:memory-core/short-term-recall/"+storeKey) return "$RECALL";
      if (v === "plugin-state:memory-core/short-term-locks/"+storeKey) return "$LOCK";
      return v.startsWith(workspace+"/") ? "$WORKSPACE/"+normalizeName(v.slice(workspace.length+1)) : v;
    }
    return Array.isArray(v) ? v.map(paths) : v && typeof v === "object"
      ? Object.fromEntries(Object.entries(v).map(([k,value])=>[k,paths(value)])) : v;
  }
  async function owner(module, alias) {
    const file = path.join(runtimeConfig.runtimeRoot,module);
    const fn = (await import(pathToFileURL(file).href))[alias];
    if (typeof fn !== "function") throw Error("Missing official recovery owner "+module);
    raw.owners.push({module,alias,name:fn.name,sourceSha256:hash(fn.toString()),artifactSha256:hash(await fs.readFile(file))});
    return fn;
  }
  async function call(fn, ...args) {
    const returned = await fn(...args);
    raw.calls.push({name:fn.name,args,returned:returned===undefined?{kind:"undefined"}:{kind:"value",value:structuredClone(returned)}});
    return returned;
  }
  let close;
  try {
    Object.assign(process.env,env);
    mock.timers.enable({apis:["Date"],now:input.nowMs});
    await fs.mkdir(workspace);
    for (const [relative,body] of Object.entries(input.files)) {
      const target = path.resolve(workspace,relative);
      if (!target.startsWith(workspace+"/")) throw Error("Unowned workspace source");
      await fs.mkdir(path.dirname(target),{recursive:true}); await fs.writeFile(target,body,{flag:"wx"});
    }
    const configure = await owner(stateMod,"p"), open = await owner(keyedMod,"r");
    close=await owner(keyedMod,"u");
    configure(options=>open("memory-core",{...options,env}));
    const seed = await owner(stateMod,"b"), read = await owner(storeMod,"i");
    const audit = input.kind==="corpus" ? await owner(corpusMod,"t") : await owner(promotionMod,"n");
    const repair = input.kind==="corpus" ? await owner(corpusMod,"n") : await owner(promotionMod,"i");
    const recall={...input.recall};
    if (input.repeat) for (let i=0;i<input.repeat.count;i++) {
      const key="repeat-"+String(i).padStart(4,"0"); recall[key]={...input.repeat.entry,key};
    }
    for (const [namespace,data] of [["short-term-recall",recall],["short-term-phase-signals",input.signals],
      ["short-term-meta",{recall:{updatedAt:input.updatedAt},phase:{updatedAt:input.updatedAt}}]]) {
      await call(seed,{workspaceDir:workspace,namespace,entries:Object.entries(data).map(([key,value])=>({key,value}))});
    }
    const lock = open("memory-core",{env,namespace:"short-term-locks",maxEntries:4096});
    if (input.lock) await lock.register(storeKey,input.lock);
    async function stage(operation,returned) {
      const workBlobs={}, tree=await snapshot(workspace,workBlobs);
      for (const [digest,body] of Object.entries(workBlobs)) raw.blobs[digest]??=gzipSync(Buffer.from(body,"base64")).toString("base64");
      const database = path.join(env.OPENCLAW_STATE_DIR,"state/openclaw.sqlite");
      const db = new DatabaseSync(database,{readOnly:true});
      const copy = path.join(root,"captured.sqlite");
      try { await backup(db,copy); } finally {db.close();}
      const data=await fs.readFile(copy); await fs.unlink(copy);
      const databaseSha256=hash(data); raw.blobs[databaseSha256]??=gzipSync(data).toString("base64");
      const recall=await call(read,workspace,"recall",now), signals=await call(read,workspace,"phase",now);
      const observedLock=(await lock.lookup(storeKey))??null;
      const documents=Object.fromEntries(Object.entries(tree).map(([name,f])=>[normalizeName(name),Buffer.from(workBlobs[f.sha256],"base64").toString("utf8")]));
      raw.stages.push({operation,returned:structuredClone(returned),databaseSha256,tree,lock:observedLock,recall,signals});
      raw.observations.push({operation,returned:paths(returned),documents,lock:observedLock,recall,signals});
    }
    const args={workspaceDir:workspace};
    await stage("audit",await call(audit,args));
    if (input.repair) for (let i=0;i<2;i++) {
      const params = input.kind==="corpus" ? {...args,archiveDiary:input.archiveDiary,now:new Date(input.nowMs)} : args;
      await stage("repair",await call(repair,params)); await stage("audit",await call(audit,args));
    }
    return {observations:raw.observations};
  } finally {
    if (close) await close();
    mock.timers.reset();
    await fs.writeFile(path.join(directory,"native-raw.json"),JSON.stringify([raw]));
    for(const [name,value] of Object.entries(saved)) { if(value===undefined) delete process.env[name]; else process.env[name]=value; }
  }
}
