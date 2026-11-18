// Exercise the real forget CLI across two committed-data boundaries with separate SQLite readers.
import fs from "node:fs/promises";
import path from "node:path";
import { createHash } from "node:crypto";
import { DatabaseSync, backup } from "node:sqlite";
import { mock } from "node:test";
import { pathToFileURL } from "node:url";
import { gzipSync } from "node:zlib";

const hash = value => createHash("sha256").update(value).digest("hex");
const stable = value => Array.isArray(value) ? value.map(stable) : value !== null && typeof value === "object"
  ? Object.fromEntries(Object.keys(value).sort().map(key => [key, stable(value[key])])) : value;
const allowed = new Set(["973f94897019eb76955263139838a5b6dfe647d9719ffcebddbad9632e22195a",
  "25cb5042d206dc44013c611303fa69d5fe3def208c02e584a965925b822b4781"]);
const trigger = "recovery_literal_cut";
const message = "frozen interrupted forget publication";
const reject = cut => cut === "before-marker" ? "BEFORE INSERT ON memory_session_tombstones"
  : "BEFORE DELETE ON memory_entry_origins";

function fullError(error) {
  return Object.fromEntries(["name", "message", "stack", "code", "errcode", "errstr", "cause"]
    .filter(key => error[key] !== undefined)
    .map(key => [key, key === "cause" ? fullError(error[key]) : error[key]]));
}

export async function runRecoveryForgetInterruption(input, context) {
  const inputSha256 = hash(JSON.stringify(stable(input)));
  if (!allowed.has(inputSha256) || !path.isAbsolute(context.evidenceDirectory)) throw Error("Unbound interrupted forget");
  await fs.mkdir(context.evidenceDirectory, { recursive: true });
  const root = await fs.mkdtemp(path.join(context.evidenceDirectory, "native-interrupted-forget-"));
  const workspace = path.join(root, "workspace");
  await fs.mkdir(workspace);
  const env = { OPENCLAW_STATE_DIR: path.join(root, "state"), OPENCLAW_CONFIG_PATH: path.join(root, "openclaw.json"),
    OPENCLAW_HOME: root };
  const old = Object.fromEntries(Object.keys(env).map(key => [key, process.env[key]]));
  Object.assign(process.env, env);
  const cfg = { agents: { defaults: { workspace }, list: [{ id:input.agentId, workspace }] },
    logging: { level:"silent", consoleLevel:"silent", file:path.join(root,"native.log") },
    memory: { search: { enabled:true, provider:"none", fallback:"none", sources:["memory"], store:{vector:{enabled:false}} } } };
  await fs.writeFile(env.OPENCLAW_CONFIG_PATH, JSON.stringify(cfg));
  const file = path.join(workspace,"MEMORY.md");
  await fs.writeFile(file,input.memory,{flag:"wx"});
  const raw = {input,inputSha256,root,env,pid:process.pid,ppid:process.ppid,owners:[],calls:[],stages:[],blobs:{}};
  const load = async (relative, alias) => {
    const location = path.join(context.runtimeRoot, relative);
    const fn = (await import(pathToFileURL(location).href))[alias];
    if (typeof fn !== "function") throw Error("Absent original "+relative);
    raw.owners.push({module:relative,alias,name:fn.name,sourceSha256:hash(fn.toString()),
      artifactSha256:hash(await fs.readFile(location))});
    return fn;
  };
  const blob = bytes => {
    const key = hash(bytes);
    if (!Object.hasOwn(raw.blobs,key)) raw.blobs[key]=gzipSync(bytes).toString("base64");
    return key;
  };
  let clear,closeAgents,closeState;
  mock.timers.enable({apis:["Date"],now:input.nowMs});
  try {
    const config = await load("dist/plugin-sdk/config-runtime.js","setRuntimeConfigSnapshot");
    clear = await load("dist/plugin-sdk/config-runtime.js","clearRuntimeConfigSnapshot");
    config(cfg);
    const configure = await load("dist/extensions/memory-core/runtime-api.js","configureMemoryCoreDreamingState");
    const createStore = await load("dist/plugin-sdk/plugin-state-store-runtime.js","createPluginStateKeyedStore");
    configure(options=>createStore("memory-core",options));
    const cli = await load("dist/cli.runtime-CVRN4xUp.mjs","runMemoryForget");
    const origins = await load("dist/memory-entry-origins-BCQSIB3X.mjs","a");
    const dbPath = await load("dist/openclaw-agent-db.paths-Dv3PPTNK.mjs","c");
    closeAgents = await load("dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs","s");
    closeState = await load("dist/openclaw-state-db-cache-IdIaBoUp.mjs","a");
    const dbFile = dbPath({agentId:input.agentId,env:process.env});
    raw.database = dbFile;
    const sql = statement => {
      const separate = new DatabaseSync(dbFile);
      try { separate.exec(statement); } finally { separate.close(); }
    };
    const forget = async session => {
      const args={agent:input.agentId,session:[session],json:true};
      const chunks=[], orig=process.stdout.write;
      let actualError=null, ret;
      process.stdout.write=function(chunk, ...args) {
        chunks.push(typeof chunk === "string" ? Buffer.from(chunk,typeof args[0]==="string"?args[0]:undefined) : Buffer.from(chunk));
        return true;
      };
      try { ret=await cli(args); }
      catch(error) { actualError=fullError(error); }
      finally { process.stdout.write=orig; }
      const stdout=Buffer.concat(chunks).toString("utf8");
      raw.calls.push({kind:"forget",args,error:actualError,stdout,returned:ret===undefined?"undefined":ret});
      if(actualError) {
        if(stdout!=="" || actualError.cause?.message!==message) throw Error("Unexplained original failure: "+actualError.message);
        return {failure:message,report:null};
      }
      return {failure:null,report:JSON.parse(stdout)};
    };
    const observations=[];
    for(const stage of input.stages) {
      let result=null;
      if(stage==="seed") {
        result=await forget(input.previous);
        origins({agentId:input.agentId,origins:input.origins});
        raw.calls.push({kind:"recordMemoryEntryOrigins",origins:input.origins});
      } else if(stage==="arm") {
        const statement="CREATE TRIGGER "+trigger+" "+reject(input.cut)+" BEGIN SELECT RAISE(ABORT, '"+message+"'); END";
        sql(statement); raw.calls.push({kind:"sql",statement});
      } else if(stage==="disarm") {
        const statement="DROP TRIGGER "+trigger;
        sql(statement); raw.calls.push({kind:"sql",statement});
      } else if(stage==="reopen") {
        await closeAgents();await closeState();raw.calls.push({kind:"closeOwners"});
      } else {
        result=await forget(input.session);
      }
      const independent = new DatabaseSync(dbFile,{readOnly:true});
      const image=path.join(root,"snapshot-"+raw.stages.length+".sqlite");
      let state;
      try {
        state={memory:await fs.readFile(file,"utf8"),
          origins:independent.prepare("SELECT * FROM memory_entry_origins ORDER BY entry_key,agent_id,session_id").all(),
          tombstones:independent.prepare("SELECT * FROM memory_session_tombstones ORDER BY session_id,agent_id").all(),
          armed:Boolean(independent.prepare("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?").get(trigger))};
        await backup(independent,image);
      } finally { independent.close(); }
      raw.stages.push({stage,result,state,image:blob(await fs.readFile(image)),note:blob(await fs.readFile(file))});
      await fs.unlink(image);
      observations.push({stage,result,state});
    }
    await fs.writeFile(path.join(context.evidenceDirectory,"native-raw.json"),JSON.stringify([raw])+"\n");
    return {observations};
  } finally {
    try {if(closeAgents) await closeAgents();if(closeState) await closeState();}
    finally {clear?.();mock.timers.reset();for(const [k,v] of Object.entries(old)) if(v===undefined) delete process.env[k]; else process.env[k]=v;}
  }
}
