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
if(!contextPath||!path.isAbsolute(contextPath)||fs.realpathSync(contextPath)!==contextPath)throw Error('Index identity context required');
const bytes=fs.readFileSync(contextPath);
if(bytes.length>64*1024*1024)throw Error('Excessive index identity context');
const context=JSON.parse(bytes),profile=context.indexIdentityBoundariesProfile;
const approved={
 "index-identity-boundaries-matching": "05498bb4b7f614baaa8c26aa6ee41ee5d168f847fd1e05d852d19911baeaf8fd",
 "index-identity-boundaries-missing-metadata": "f3a4e74f0d1a72fd89fd697a02bdef50222ab9c30a2209773829b8e7033938f2",
 "index-identity-boundaries-malformed-metadata": "603fff54ff3d6eac7a728f0f604bb39817a980207e7c44d92d2c844d5aacf94a",
 "index-identity-boundaries-older-provenance": "7c67bdd74ff31a22d01c03e5620b4dd91a29500b5b8525b4aae87cfb9a3dc04c",
 "index-identity-boundaries-older-chunker-only": "73ddd55444e799b016e5dde588685964a551de57d3297c86257f9ec9259078ec",
 "index-identity-boundaries-newer-provenance-older-chunker": "ff614f006a7befc1f01c912d5c83eb31d3660106252e9a0d5505c4a77185a1a7",
 "index-identity-boundaries-newer-chunker-older-provenance": "f4f67768ee188f9ab0936ac525dc8ef139e0b442992fcba1914e842a010df1ce",
 "index-identity-boundaries-provider-key-only": "f850dc2426885f6b2c3977eb3da50e243af3dd6123d1b829fe2749e29cee9753",
 "index-identity-boundaries-model-only": "48723ca0cdcb8de719288f792a3833486bd253d51f277afc8198762d2ac7bb17",
 "index-identity-boundaries-provider-only": "8c12fc66a405085de36a7729be46d88a7378771beaee2732d95ab461926eaa83",
 "index-identity-boundaries-sources-only": "c8f3acec301946d34ae2534fb48aa9c7c649aee7198711dfea160897b7327377",
 "index-identity-boundaries-scope-only": "7dd0d5dd9329b26d7550cdedf46a76fcf4530fa14732499fe7dd757a14428321",
 "index-identity-boundaries-chunk-tokens-only": "32cc40a04bd3f7cba6267df6c916eb517bcf0c42662f795e812bc1b0c3640101",
 "index-identity-boundaries-chunk-overlap-only": "5a31baccf4c598658ae03a41330344ea394aeb8121dc82f1b7d1abd193baa788",
 "index-identity-boundaries-tokenizer-only": "399f8c4d532bbae72982c9ac982af7bbfe41be1fca256e34781a9c94f161a3a2",
 "index-identity-boundaries-older-chunker-scope-incompatible": "b92cf95556dcd40a9f49382690dcdd5904527dffa6b272cba22fcfec436d701a"
};
const keys=['schemaVersion','kind','runtime','providerMode','fetchPolicy','approvedNodeRuntime',
 'indexIdentityBoundariesProfile','allowedLocal','traceDirectory','evidenceDirectory','stateDirectory',
 'configPath','approvedReferenceSources','fixtureSourceCaptures'].sort().join();
if(Object.keys(context).sort().join()!==keys||context.schemaVersion!==1||context.kind!=='release-oracle-execution'||
 context.providerMode!=='none'||context.fetchPolicy!=='deny'||!profile||
 Object.keys(profile).sort().join()!==['kind','operation','caseId','caseWireSha256','clockNowMs','nodeRuntime','acceptancePointsAwarded'].sort().join()||
 profile.kind!=='index-identity-boundaries'||profile.operation!=='index-identity-boundaries-runtime'||
 profile.acceptancePointsAwarded!==0||profile.clockNowMs!==1794268800000||
 !Object.hasOwn(approved,profile.caseId)||approved[profile.caseId]!==profile.caseWireSha256||
 JSON.stringify(profile.nodeRuntime)!==JSON.stringify(context.approvedNodeRuntime)||
 !Array.isArray(context.approvedReferenceSources)||context.approvedReferenceSources.length!==0||
 !Array.isArray(context.fixtureSourceCaptures)||context.fixtureSourceCaptures.length!==0){
 throw Error('Index identity capability rejects other profiles and changed frozen literals');
}
const own=fs.realpathSync(fileURLToPath(import.meta.url)),folder=path.dirname(own);
const expectedLocals=['index-identity-boundaries-preload.mjs','index-identity-boundaries-entry.mjs','index-identity-boundaries-runtime.mjs'].map(name=>path.join(folder,name));
if(!Array.isArray(context.allowedLocal)||context.allowedLocal.length!==expectedLocals.length)throw Error('Closed index identity local authority required');
const permitted=new Map();
function regular(filename){const stat=fs.lstatSync(filename);return stat.isFile()&&!stat.isSymbolicLink()&&stat.nlink===1&&fs.realpathSync(filename)===filename;}
for(const item of context.allowedLocal){
 if(!item||Object.keys(item).sort().join()!=='path,sha256'||!expectedLocals.includes(item.path)||
 permitted.has(item.path)||!regular(item.path)||!/^[0-9a-f]{64}$/.test(item.sha256)||hash(fs.readFileSync(item.path))!==item.sha256){
 throw Error('Duplicate, aliased or changed index identity local authority');}
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
if(!ownRecord||ownRecord.kind!=='oracle'||hash(fs.readFileSync(own))!==ownRecord.sha256)throw Error('Unreviewed identity preload');
const approvedNode=context.approvedNodeRuntime;
const actualNode={execPath:fs.realpathSync(process.execPath),nodeVersion:process.version,
 icuVersion:process.versions.icu,unicodeVersion:process.versions.unicode,sha256:hash(fs.readFileSync(process.execPath))};
if(!approvedNode||Object.keys(approvedNode).sort().join()!=='execPath,icuVersion,nodeVersion,sha256,unicodeVersion'||
 actualNode.nodeVersion!=='v24.16.0'||actualNode.icuVersion!=='78.3'||actualNode.unicodeVersion!=='17.0'||
 actualNode.sha256!=='b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd'||
 Object.keys(actualNode).some(key=>actualNode[key]!==approvedNode[key]))throw Error('Unapproved index identity Node/ICU/Unicode executable');
const base=path.dirname(contextPath);
for(const[name,relative]of[['traceDirectory','traces'],['evidenceDirectory','evidence'],['stateDirectory','state']]){
 const directory=context[name];
 if(directory!==path.join(base,relative)||fs.realpathSync(directory)!==directory||!fs.lstatSync(directory).isDirectory()||fs.lstatSync(directory).isSymbolicLink()){
 throw Error('Index identity directories must remain in their owned case');}
}
if(context.configPath!==path.join(context.stateDirectory,'openclaw.json'))throw Error('Wrong index identity config owner');
const traceFile=path.join(context.traceDirectory,`${process.pid}-${threadId}.jsonl`);
function trace(row){if(fs.existsSync(traceFile)&&fs.statSync(traceFile).size>8*1024*1024)throw Error('Identity trace limit exceeded');
 fs.appendFileSync(traceFile,JSON.stringify({...row,pid:process.pid,threadId})+'\n',{mode:0o600});}
const diagnostics=new Console({stdout:process.stderr,stderr:process.stderr});
const methods=Object.fromEntries(['log','info','debug'].map(name=>[name,diagnostics[name].bind(diagnostics)]));
function routeConsole(){for(const[name,implementation]of Object.entries(methods)){if(console[name]!==implementation)Object.defineProperty(console,name,{value:implementation,writable:false,configurable:false});}}
routeConsole();
Object.defineProperty(globalThis,'fetch',{value:async()=>{throw Error('Index identity reference network fetch is denied');},writable:false,configurable:false});
function authority(url){
 if(url.startsWith('node:'))return;
 if(!url.startsWith('file:'))throw Error('Identity runtime imports require authenticated files');
 const lexical=path.resolve(fileURLToPath(url)),filename=fs.realpathSync(lexical),record=permitted.get(filename);
 if(filename!==lexical||!record||!regular(filename)||hash(fs.readFileSync(filename))!==record.sha256){
  trace({event:'rejected',code:'unverified-module-bytes',basename:path.basename(filename)});throw Error('Unverified index identity module');}
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
trace({event:'index-identity-boundaries-bootstrap',profile,preloadSha256:ownRecord.sha256,clock:{owner:'node:test',apis:['Date'],
 nowMs:Date.now(),dateConstructorReplaced:globalThis.Date!==originalDate,
 setTimeoutUnchanged:globalThis.setTimeout===timeout,performanceNowUnchanged:globalThis.performance.now===performanceNow}});
