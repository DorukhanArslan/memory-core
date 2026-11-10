// Independent closed index-identity capability; no older profile is widened.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {Console} from 'node:console';
import {registerHooks} from 'node:module';
import {fileURLToPath} from 'node:url';
import {threadId,isMainThread} from 'node:worker_threads';
import {mock} from 'node:test';
const hash=data=>crypto.createHash('sha256').update(data).digest('hex');
const contextPath=process.env.MEMORY_EQ_RELEASE_CONTEXT;
if(!contextPath||!path.isAbsolute(contextPath)||fs.realpathSync(contextPath)!==contextPath)throw Error('Query-sync outcomes context required');
const bytes=fs.readFileSync(contextPath);
if(bytes.length>64*1024*1024)throw Error('Excessive query-sync outcomes context');
const context=JSON.parse(bytes),profile=context.querySyncOutcomesProfile;
const approved={
 "query-sync-outcomes-cold-existing-no-index": "2cfbdbda1abf050d61255b3fafe7c577d1d95ba532b6e69e12dd5773277f16c2",
 "query-sync-outcomes-cold-empty-then-add": "1bf92fb4e5c924792d0df44a682912ccc00a36a8712531b65946cbdee8d56eef",
 "query-sync-outcomes-warm-unchanged": "32d6d1acdccb7129db779729182d22bd767b0235787d7c54ad6e7ac56bd4840e",
 "query-sync-outcomes-warm-edit": "5fa326d5745fe5bbdea3826d1b66a539acf02901814a65af2d89934129664b59",
 "query-sync-outcomes-warm-delete": "c28686e39f9739b397a0b3ae3e9879d2a624ef12123c81a6d0b7b5d0b79da7b9",
 "query-sync-outcomes-warm-rename": "df6bd13ac9792f7f5f4aef86d78833a9909e3a36fbdaa412ba57c5301e41cc5e",
 "query-sync-outcomes-warm-touch-same-bytes": "05fd6486cc377ac469b1c08616be55612b9c1330e79d7117f8e625b01ce143de"
};
const keys=['schemaVersion','kind','runtime','providerMode','fetchPolicy','approvedNodeRuntime',
 'querySyncOutcomesProfile','allowedLocal','traceDirectory','evidenceDirectory','stateDirectory',
 'configPath','approvedReferenceSources','fixtureSourceCaptures'].sort().join();
if(Object.keys(context).sort().join()!==keys||context.schemaVersion!==1||context.kind!=='release-oracle-execution'||
 context.providerMode!=='none'||context.fetchPolicy!=='deny'||!profile||
 Object.keys(profile).sort().join()!==['kind','operation','caseId','caseWireSha256','clockNowMs','nodeRuntime','acceptancePointsAwarded'].sort().join()||
 profile.kind!=='query-sync-outcomes'||profile.operation!=='query-sync-outcomes-runtime'||
 profile.acceptancePointsAwarded!==0||profile.clockNowMs!==1794268800000||
 !Object.hasOwn(approved,profile.caseId)||approved[profile.caseId]!==profile.caseWireSha256||
 JSON.stringify(profile.nodeRuntime)!==JSON.stringify(context.approvedNodeRuntime)||
 !Array.isArray(context.approvedReferenceSources)||context.approvedReferenceSources.length!==0||
 !Array.isArray(context.fixtureSourceCaptures)||context.fixtureSourceCaptures.length!==0){
 throw Error('Query-sync outcomes capability rejects other profiles and changed frozen literals');
}
const own=fs.realpathSync(fileURLToPath(import.meta.url)),folder=path.dirname(own);
const expectedLocals=['query-sync-outcomes-preload.mjs','query-sync-outcomes-entry.mjs','query-sync-outcomes-runtime.mjs'].map(name=>path.join(folder,name));
if(!Array.isArray(context.allowedLocal)||context.allowedLocal.length!==expectedLocals.length)throw Error('Closed query-sync outcomes local authority required');
const permitted=new Map();
function regular(filename){const stat=fs.lstatSync(filename);return stat.isFile()&&!stat.isSymbolicLink()&&stat.nlink===1&&fs.realpathSync(filename)===filename;}
for(const item of context.allowedLocal){
 if(!item||Object.keys(item).sort().join()!=='path,sha256'||!expectedLocals.includes(item.path)||
 permitted.has(item.path)||!regular(item.path)||!/^[0-9a-f]{64}$/.test(item.sha256)||hash(fs.readFileSync(item.path))!==item.sha256){
 throw Error('Duplicate, aliased or changed query-sync outcomes local authority');}
 permitted.set(item.path,{kind:'oracle',path:item.path,sha256:item.sha256});
}
for(const pkg of context.runtime.packages){
 const directory=fs.realpathSync(pkg.directory);
 if(directory!==pkg.directory)throw Error('Aliased release package');
 for(const file of pkg.files){
  const absolute=path.resolve(directory,file.path);
  if(!absolute.startsWith(directory+path.sep)||permitted.has(absolute)||!/^[0-9a-f]{64}$/.test(file.sha256))throw Error('Invalid release artifact authority');
  permitted.set(absolute,{kind:'release',package:pkg.location,path:file.path,sha256:file.sha256});
 }
}
const ownRecord=permitted.get(own);
if(!ownRecord||ownRecord.kind!=='oracle'||hash(fs.readFileSync(own))!==ownRecord.sha256)throw Error('Unreviewed query-sync preload');
const approvedNode=context.approvedNodeRuntime;
const actualNode={execPath:fs.realpathSync(process.execPath),nodeVersion:process.version,
 icuVersion:process.versions.icu,unicodeVersion:process.versions.unicode,sha256:hash(fs.readFileSync(process.execPath))};
if(!approvedNode||Object.keys(approvedNode).sort().join()!=='execPath,icuVersion,nodeVersion,sha256,unicodeVersion'||
 actualNode.nodeVersion!=='v24.16.0'||actualNode.icuVersion!=='78.3'||actualNode.unicodeVersion!=='17.0'||
 actualNode.sha256!=='b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd'||
 Object.keys(actualNode).some(key=>actualNode[key]!==approvedNode[key]))throw Error('Unapproved query-sync outcomes Node/ICU/Unicode executable');
const base=path.dirname(contextPath);
for(const[name,relative]of[['traceDirectory','traces'],['evidenceDirectory','evidence'],['stateDirectory','state']]){
 const directory=context[name];
 if(directory!==path.join(base,relative)||fs.realpathSync(directory)!==directory||!fs.lstatSync(directory).isDirectory()||fs.lstatSync(directory).isSymbolicLink()){
 throw Error('Query-sync outcomes directories must remain in their owned case');}
}
if(context.configPath!==path.join(context.stateDirectory,'openclaw.json'))throw Error('Wrong query-sync outcomes config owner');
const traceFile=path.join(context.traceDirectory,`${process.pid}-${threadId}.jsonl`);
function trace(row){if(fs.existsSync(traceFile)&&fs.statSync(traceFile).size>8*1024*1024)throw Error('Query-sync trace limit exceeded');
 fs.appendFileSync(traceFile,JSON.stringify({...row,pid:process.pid,threadId})+'\n',{mode:0o600});}
const diagnostics=new Console({stdout:process.stderr,stderr:process.stderr});
const methods=Object.fromEntries(['log','info','debug'].map(name=>[name,diagnostics[name].bind(diagnostics)]));
function routeConsole(){for(const[name,implementation]of Object.entries(methods)){if(console[name]!==implementation)Object.defineProperty(console,name,{value:implementation,writable:false,configurable:false});}}
routeConsole();
Object.defineProperty(globalThis,'fetch',{value:async()=>{throw Error('Query-sync outcomes reference network fetch is denied');},writable:false,configurable:false});
function authority(url){
 if(url.startsWith('node:'))return;
 if(!url.startsWith('file:'))throw Error('Identity runtime imports require authenticated files');
 if(new URL(url).search||new URL(url).hash)throw Error('Aliased query-sync import URL');
 const lexical=path.resolve(fileURLToPath(url)),filename=fs.realpathSync(lexical),record=permitted.get(filename);
 if(filename!==lexical||!record||!regular(filename)||hash(fs.readFileSync(filename))!==record.sha256){
  trace({event:'rejected',code:'unverified-module-bytes',basename:path.basename(filename)});throw Error('Unverified query-sync outcomes module');}
 return record;
}
registerHooks({resolve(specifier,ctx,next){
 const value=next(specifier,ctx),record=authority(value.url);
 if(record&&value.url.endsWith('.node'))trace({event:'resolve-native',...record});return value;
},load(url,ctx,next){routeConsole();const record=authority(url);if(record)trace({event:'load',...record});return next(url,ctx);}});
const originalDate=globalThis.Date,timeout=globalThis.setTimeout,performanceNow=globalThis.performance.now;
mock.timers.enable({apis:['Date'],now:profile.clockNowMs});
trace({event:'bootstrap',isMainThread,ppid:process.ppid,runtime:actualNode,contextSha256:hash(bytes),
 preloadSha256:ownRecord.sha256,fetchDenied:true,providerMode:'none'});
trace({event:'query-sync-outcomes-bootstrap',profile,preloadSha256:ownRecord.sha256,clock:{owner:'node:test',apis:['Date'],
 nowMs:Date.now(),dateConstructorReplaced:globalThis.Date!==originalDate,
 setTimeoutUnchanged:globalThis.setTimeout===timeout,performanceNowUnchanged:globalThis.performance.now===performanceNow}});
