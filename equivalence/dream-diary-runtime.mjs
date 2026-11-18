// Workspace fixtures and receipts only. All diary, phase, trust and lease decisions belong to OpenClaw.
import fs from "node:fs/promises";
import path from "node:path";
import {createHash} from "node:crypto";
import {DatabaseSync} from "node:sqlite";
import {pathToFileURL} from "node:url";
import {gzipSync} from "node:zlib";

const hash = value => createHash("sha256").update(value).digest("hex");
const now = 1767268800000;
async function capture(workspace, directory = workspace, files = {}) {
  for (const name of (await fs.readdir(directory)).sort()) {
    const file = path.join(directory, name);
    const meta = await fs.lstat(file, {bigint:true});
    if (meta.isDirectory()) { await capture(workspace, file, files); continue; }
    const item = {mode:Number(meta.mode & 0o7777n),mtimeNs:String(meta.mtimeNs),ino:String(meta.ino)};
    if (meta.isSymbolicLink()) Object.assign(item,{kind:"link",target:await fs.readlink(file)});
    else if (meta.isFile() && meta.nlink === 1n && meta.size < 1024n*1024n) {
      const data = await fs.readFile(file);
      Object.assign(item,{kind:"file",text:data.toString("utf8"),sha256:hash(data)});
    } else throw Error("Unknown diary fixture file");
    files[path.relative(workspace,file)] = item;
  }
  return files;
}
function durable(database) {
  const db = new DatabaseSync(database,{readOnly:true});
  try { return db.prepare("SELECT namespace,entry_key,value_json FROM plugin_state_entries WHERE plugin_id=? ORDER BY namespace,entry_key").all("memory-core"); }
  finally { db.close(); }
}
function eventsAt(events,workspace) {
  return events.map(e=>Object.fromEntries(Object.entries(e).map(([key,value])=>[key,
    ["inlinePath","reportPath"].includes(key) && String(value).startsWith(workspace+"/")
    ? "$WORKSPACE/"+value.slice(workspace.length+1) :value])));
}
function documents(files) {
  return Object.fromEntries(Object.entries(files).filter(([p])=>p.endsWith(".md")).map(([p,item])=>[p,
    item.kind==="link"?{link:item.target}:{text:item.text}]));
}
function errorRecord(e) { return {name:e.name,message:e.message,stack:e.stack,...(e.code?{code:e.code}:{})}; }

export async function runDreamDiaryRuntime(input, runtimeConfig) {
  const evidence = runtimeConfig.evidenceDirectory;
  await fs.mkdir(evidence,{recursive:true});
  const root = await fs.mkdtemp(path.join(evidence,"native-diary-"));
  const workspace = path.join(root,"workspace");
  await fs.mkdir(workspace);
  const env={OPENCLAW_STATE_DIR:path.join(root,"state"),OPENCLAW_CONFIG_PATH:path.join(root,"openclaw.json")};
  const original=Object.fromEntries(Object.keys(env).map(k=>[k,process.env[k]]));
  const database=path.join(env.OPENCLAW_STATE_DIR,"state/openclaw.sqlite");
  const raw={kind:"official-diary-publication",input,workspace,root,database,pid:process.pid,ppid:process.ppid,
    owners:[],calls:[],rows:[],race:[],factory:[],leaseCalls:[],dbBlobs:{}};
  const observations=[];
  async function captureDb() {
    const snapshot={};
    for(const suffix of ["","-wal"]) {
      let bytes;
      try {bytes=await fs.readFile(database+suffix);}
      catch(error) {if(error.code==="ENOENT" && suffix) continue;throw error;}
      if(bytes.length>4*1024*1024)throw Error("Diary database snapshot exceeds the fixture bound");
      const sha256=hash(bytes);
      raw.dbBlobs[sha256]??=gzipSync(bytes).toString("base64");
      snapshot[suffix]={sha256,size:bytes.length};
    }
    return snapshot;
  }
  async function owner(relative,alias) {
    const file=path.join(runtimeConfig.runtimeRoot,relative);
    const fn=(await import(pathToFileURL(file).href))[alias];
    if(typeof fn!=="function") throw Error("Missing original diary owner: "+relative);
    raw.owners.push({relative,alias,name:fn.name,artifactSha256:hash(await fs.readFile(file)),sourceSha256:hash(String(fn))});
    return fn;
  }
  async function call(fn,args) {
    const receipt={name:fn.name,args:structuredClone(args)}; raw.calls.push(receipt);
    try { const value=await fn(...args); receipt.returned=value===undefined?{undefined:true}:{value}; return value; }
    catch(e) { receipt.error=errorRecord(e); throw e; }
  }
  let close;
  try {
    Object.assign(process.env,env);
    await fs.writeFile(env.OPENCLAW_CONFIG_PATH,JSON.stringify({logging:{level:"silent",consoleLevel:"silent",file:path.join(root,"native.log")}}));
    for(const [rel,text] of Object.entries(input.files)) {
      const file=path.join(workspace,rel);await fs.mkdir(path.dirname(file),{recursive:true});
      await fs.writeFile(file,text);await fs.utimes(file,now/1000,now/1000);
    }
    const configure=await owner("dist/dreaming-state-VYUvbU-n.mjs","p");
    const open=await owner("dist/plugin-sdk/plugin-state-store-runtime.js","createPluginStateKeyedStore");
    close=await owner("dist/plugin-state-store-BPUaLoVD.mjs","u");
    configure(options=>{
      const store=open("memory-core",{...options,env});
      raw.factory.push({options,methods:Object.keys(store)});
      if (options.namespace==="short-term-locks") {
        const observed={...store};
        for(const method of ["observe","compareAndApply"]) {
          observed[method]=async(...args)=>{
            const receipt={method,args:structuredClone(args),pid:process.pid};
            raw.leaseCalls.push(receipt);
            const returned=await store[method](...args);
            receipt.returned=structuredClone(returned);
            return returned;
          };
        }
        return observed;
      }
      return store;
    });
    const dreams="dist/dreaming-dreams-file-BJzlZFlf.mjs";
    const append=await owner(dreams,"n"),recent=await owner(dreams,"o"),update=await owner(dreams,"u"),lease=await owner(dreams,"g");
    const phase=await owner("dist/dreaming-markdown-B86sCBbW.mjs","n");
    const classify=await owner("dist/memory-path-provenance-C84vBRrO.mjs","t");
    const read=await owner("dist/short-term-promotion-store-B6T388Bo.mjs","a"),write=await owner("dist/short-term-promotion-store-B6T388Bo.mjs","l");
    const events=await owner("dist/plugin-sdk/memory-host-events.js","readMemoryHostEventRecords");
    const s=input.source;
    await call(write,[workspace,{version:1,updatedAt:new Date(now).toISOString(),entries:{[s.key]:s}}]);
    raw.initial={files:await capture(workspace),database:durable(database),dbFiles:await captureDb()};
    const publish=params=>call(append,[{workspaceDir:workspace,narrative:params.narrative,nowMs:params.nowMs,
      timezone:params.timezone,sourceEntryKeys:params.keys,recentDiaryEntries:params.recent}]);
    for(const op of input.operations) {
      const row={operation:op};
      let outcome;
      if(op.op==="phase") {
        const args={workspaceDir:workspace,phase:op.phase,bodyLines:op.lines,hasContent:true,nowMs:op.nowMs,
          timezone:op.timezone,storage:{mode:op.storageMode,separateReports:false}};
        const paths=await lease(workspace,()=>call(phase,[args]));
        outcome={status:"published",paths:[paths.inlinePath,paths.reportPath].filter(Boolean).map(f=>path.relative(workspace,f))};
      } else if(op.op==="append") {
        try {const filename=await publish(op);row.returnPath=filename??null;
          outcome=filename?{status:"published",path:path.basename(filename)}:{status:"skipped"};}
        catch(error){row.error=errorRecord(error);outcome={status:"failed",message:error.message};}
      } else if(op.op==="race") {
        const entered=Promise.withResolvers(),release=Promise.withResolvers();
        const holder=lease(workspace,async()=>{
          const filename=await publish({narrative:op.first,nowMs:op.nowMs,timezone:"UTC",keys:[],recent:[]});
          raw.race.push({event:"first-published",path:filename});
          entered.resolve();await release.promise;
        });
        holder.catch(entered.reject);
        await entered.promise;
        let returned=false;
        raw.race.push({event:"second-attempted"});
        const waiter=publish(op.second).finally(()=>{returned=true;});
        try {
          await new Promise(resolve=>setImmediate(resolve));
          const mid=await fs.readFile(path.join(workspace,"DREAMS.md"),"utf8");
          raw.race.push({event:"contention",database:durable(database),dbFiles:await captureDb(),pending:!returned,text:mid});
          outcome={status:"raced",pending:!returned,intermediate:mid};
        } finally {release.resolve();}
        const [,filename]=await Promise.all([holder,waiter]);
        raw.race.push({event:"second-published",path:filename});
      } else {
        if(op.op==="forget-source") {
          await lease(workspace,async()=>{
            const current=await call(read,[workspace,new Date(op.nowMs).toISOString()]);
            const next=structuredClone(current);delete next.entries[op.key];await call(write,[workspace,next]);
          });
        } else if(op.op==="change-diary") {
          await update({workspaceDir:workspace,updater:()=>({content:op.text,result:undefined})});
        } else if(op.op==="make-symlink") {
          const file=path.join(workspace,op.path);await fs.unlink(file);await fs.symlink(op.target,file);
        } else if(op.op==="restore-file") {
          const file=path.join(workspace,op.path);await fs.unlink(file);await fs.writeFile(file,op.text);
        } else throw Error("Unknown diary operation");
        outcome={status:"fixture"};
      }
      const files=await capture(workspace),docs=documents(files);
      const trust=[];
      for(const relativePath of Object.keys(docs).sort()){
        const fact=await call(classify,[{workspaceDir:workspace,absolutePath:path.join(workspace,relativePath),source:"memory"}]);
        trust.push({relativePath,originClass:fact.originClass});
      }
      const receipts=await call(events,[{workspaceDir:workspace,env}]);
      const current=await call(read,[workspace,new Date(now).toISOString()]);
      const observation={operation:op,outcome,documents:docs,recent:await call(recent,[{workspaceDir:workspace}]),
        trust,events:eventsAt(receipts,workspace),sourceKeys:Object.keys(current.entries).sort()};
      Object.assign(row,{files,database:durable(database),dbFiles:await captureDb(),events:receipts,observation});
      raw.rows.push(row);observations.push(observation);
    }
    raw.complete=true;
    return {observations};
  } catch(e){raw.error=errorRecord(e);throw e;}
  finally {
    try {if(close){await close();raw.closed=true;}} finally {
      for(const [k,v] of Object.entries(original)){if(v===undefined)delete process.env[k];else process.env[k]=v;}
      await fs.writeFile(path.join(evidence,"native-raw.json"),JSON.stringify([raw]),{flag:"wx"});
    }
  }
}
