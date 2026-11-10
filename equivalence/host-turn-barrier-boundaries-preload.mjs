// Independent whole-caller capability. This does not widen an older profile.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { Console } from 'node:console';
import { execFileSync } from 'node:child_process';
import { registerHooks } from 'node:module';
import { fileURLToPath } from 'node:url';
import { threadId, isMainThread } from 'node:worker_threads';
import { mock } from 'node:test';
const hash = data => crypto.createHash('sha256').update(data).digest('hex');
const filename = process.env.MEMORY_EQ_RELEASE_CONTEXT;
if (!filename || !path.isAbsolute(filename)) throw Error('Turn barrier context required');
const bytes = fs.readFileSync(filename), context = JSON.parse(bytes);
const profile = context.hostTurnBarrierBoundariesProfile;
const approved = {
 "host-turn-barrier-boundaries-pending-ascii": "3fb13d571213c7758e29fb99124863f3c97781281a1120a0aa8d77c07c97961a",
 "host-turn-barrier-boundaries-target-open-unicode": "3b4d4db5499d772a64368c34418d178f3d77c8746c0b019b75881a49c6f3b290",
 "host-turn-barrier-boundaries-committed-ascii": "019816c79b7f5540a6d4894f0b0a6f01135fc9f6c8396827b39213fdf23048ea",
 "host-turn-barrier-boundaries-maintenance-refusal-unicode": "50eccd137544f5b277283e869edb346ccd0ccef1518b571c9d0f55dae3b18dd9",
 "host-turn-barrier-boundaries-foreground-refusal-ascii": "e6917adf98d0937c884d299706fd8a00219c325c2cb2283e3965891e71508378",
 "host-turn-barrier-boundaries-publication-failure-unicode": "2eae19b1881e1e19c4f172bfb8ebc2ce6284928a845494b8344a99e327dd26a5"
};
const keys=['schemaVersion','kind','runtime','providerMode','fetchPolicy','approvedNodeRuntime',
 'hostTurnBarrierBoundariesProfile','allowedLocal','traceDirectory','evidenceDirectory','stateDirectory',
 'configPath','approvedReferenceSources','fixtureSourceCaptures','leaseFixture'].sort().join();
if (bytes.length>64*1024*1024 || Object.keys(context).sort().join()!==keys ||
 context.schemaVersion!==1 || context.kind!=='release-oracle-execution' ||
 context.providerMode!=='none' || context.fetchPolicy!=='deny' || !profile ||
 Object.keys(profile).sort().join()!==['kind','operation','caseId','caseWireSha256','clockNowMs','nodeRuntime','acceptancePointsAwarded'].sort().join() ||
 profile.kind!=='host-turn-barrier-boundaries' || profile.operation!=='host-turn-barrier-boundaries-runtime' ||
 profile.acceptancePointsAwarded!==0 || profile.clockNowMs!==1794268800000 ||
 approved[profile.caseId]!==profile.caseWireSha256 || !Object.hasOwn(approved,profile.caseId) ||
 JSON.stringify(profile.nodeRuntime)!==JSON.stringify(context.approvedNodeRuntime) ||
 !Array.isArray(context.approvedReferenceSources) || context.approvedReferenceSources.length!==0 ||
 !Array.isArray(context.fixtureSourceCaptures) || context.fixtureSourceCaptures.length!==1) {
 throw Error('Turn barrier capability rejects other profiles, source substitutions or changed literals');
}
const leaseCase=profile.caseId==='host-turn-barrier-boundaries-target-open-unicode';
if(leaseCase!==(context.leaseFixture!==null))throw Error('Kernel lease fixture cannot borrow another boundary schedule');
if(leaseCase){
 const fixture=context.leaseFixture;
 if(!fixture||Object.keys(fixture).sort().join()!=='helper,python'||
 Object.keys(fixture.helper??{}).sort().join()!=='path,sha256'||
 Object.keys(fixture.python??{}).sort().join()!=='execPath,sha256,version'||
 fixture.helper.path!==path.join(path.dirname(fileURLToPath(import.meta.url)),'host_turn_barrier_boundaries_lease.py')||
 !path.isAbsolute(fixture.python.execPath)||!/^3\.(?:11|12|13|14|15)\.[0-9]+$/.test(fixture.python.version)||
 [fixture.helper.path,fixture.python.execPath].some(p=>fs.realpathSync(p)!==p)||
 hash(fs.readFileSync(fixture.helper.path))!==fixture.helper.sha256||
 hash(fs.readFileSync(fixture.python.execPath))!==fixture.python.sha256||
 !context.allowedLocal.some(x=>x.path===fixture.helper.path&&x.sha256===fixture.helper.sha256))
 throw Error('The physical kernel fixture requires its exact owned helper and interpreter');
}
const own=fs.realpathSync(fileURLToPath(import.meta.url));
const localNames=['host-turn-barrier-boundaries-entry.mjs','host-turn-barrier-boundaries-preload.mjs',
 'host-turn-barrier-boundaries-runtime.mjs','host-turn-barrier-provider/index.mjs',
 'host-turn-barrier-provider/openclaw.plugin.json'];
if(leaseCase)localNames.push('host_turn_barrier_boundaries_lease.py');
const expectedLocals=new Set(localNames.map(name=>path.join(path.dirname(own),name)));
if(!Array.isArray(context.allowedLocal)||context.allowedLocal.length!==expectedLocals.size)
 throw Error('Boundary capability cannot expand its closed local authority');
const permitted=new Map();
for (const item of context.allowedLocal) {
 const absolute=fs.realpathSync(item.path);
 const info=fs.lstatSync(item.path);
 if (absolute!==item.path || permitted.has(absolute)||!expectedLocals.has(absolute)||
 !info.isFile()||info.isSymbolicLink()||info.nlink!==1||hash(fs.readFileSync(absolute))!==item.sha256)
 throw Error('Duplicate, foreign, changed or aliased local boundary authority');
 permitted.set(absolute,{kind:'oracle',path:absolute,sha256:item.sha256});
}
for (const pkg of context.runtime.packages) for(const file of pkg.files) {
 const absolute=path.resolve(pkg.directory,file.path);
 if (!absolute.startsWith(fs.realpathSync(pkg.directory)+path.sep) || permitted.has(absolute)) throw Error('Invalid release authority');
 permitted.set(absolute,{kind:'release',package:pkg.location,path:file.path,sha256:file.sha256});
}
const ownRecord=permitted.get(own);
if (!ownRecord || ownRecord.kind!=='oracle' || hash(fs.readFileSync(own))!==ownRecord.sha256) throw Error('Unreviewed whole-caller preload');
const actual={execPath:fs.realpathSync(process.execPath),nodeVersion:process.version,icuVersion:process.versions.icu,
 unicodeVersion:process.versions.unicode,sha256:hash(fs.readFileSync(process.execPath))};
const required={nodeVersion:'v24.16.0',icuVersion:'78.3',unicodeVersion:'17.0',sha256:'b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd'};
if (JSON.stringify(actual)!==JSON.stringify(context.approvedNodeRuntime) ||
 Object.entries(required).some(([key,value])=>actual[key]!==value)) throw Error('Unapproved actual Node/ICU/Unicode executable');
let leasePythonIdentity=null;
if(leaseCase){
 const fixture=context.leaseFixture;
 const script='import hashlib,json,os,platform,sys; p=os.path.realpath(sys.executable); print(json.dumps({"execPath":p,"sha256":hashlib.sha256(open(p,"rb").read()).hexdigest(),"version":platform.python_version(),"implementation":sys.implementation.name}))';
 try{
  leasePythonIdentity=JSON.parse(execFileSync(fixture.python.execPath,['-I','-B','-c',script],
   {encoding:'utf8',env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8',TZ:'UTC'},timeout:5000,maxBuffer:8192}));
 }catch{throw Error('Boundary kernel fixture requires an actual isolated Python interpreter');}
 if(['execPath','sha256','version'].some(key=>leasePythonIdentity[key]!==fixture.python[key]))
  throw Error('Boundary kernel fixture interpreter identity differs from actual execution');
}
const traceFile=path.join(context.traceDirectory,`${process.pid}-${threadId}.jsonl`);
function trace(record){
 if(fs.existsSync(traceFile)&&fs.statSync(traceFile).size>8*1024*1024)throw Error('Whole-caller trace too large');
 fs.appendFileSync(traceFile,JSON.stringify({...record,pid:process.pid,threadId})+'\n',{mode:0o600});
}
trace({event:'bootstrap',isMainThread,ppid:process.ppid,contextSha256:hash(bytes),preloadSha256:ownRecord.sha256,
 fetchDenied:true,providerMode:'none',runtime:actual,leasePythonIdentity});
const beforeDate=Date,beforeTimeout=setTimeout,beforePerformance=performance.now;
mock.timers.enable({apis:['Date'],now:profile.clockNowMs});
trace({event:'host-turn-barrier-boundaries-bootstrap',profile,preloadSha256:ownRecord.sha256,clock:{owner:'node:test',apis:['Date'],
 nowMs:Date.now(),dateConstructorReplaced:Date!==beforeDate,setTimeoutUnchanged:setTimeout===beforeTimeout,
 performanceNowUnchanged:performance.now===beforePerformance}});
const diagnostics=new Console({stdout:process.stderr,stderr:process.stderr});
const methods=Object.fromEntries(['log','info','debug'].map(name=>[name,diagnostics[name].bind(diagnostics)]));
function routeConsole(){for(const [name,value]of Object.entries(methods))if(console[name]!==value)Object.defineProperty(console,name,{value,configurable:false,writable:false});}
routeConsole();
Object.defineProperty(globalThis,'fetch',{configurable:false,writable:false,value:async function deniedTurnBarrierFetch(){trace({event:'network-denied'});throw Error('Network disabled in whole-caller comparisons');}});
const capture=context.fixtureSourceCaptures[0];
const source=permitted.get(capture.sourcePath);
if (capture.basename!=='index.mjs' || capture.capturePackage!=='host-turn-barrier-provider' ||
 !capture.sourcePath.endsWith('/host-turn-barrier-provider/index.mjs') || source?.kind!=='oracle' ||
 source.sha256!==capture.sha256) throw Error('Only the separately reviewed provider transport can be captured');
const captureRoot=path.join(context.stateDirectory,'tmp','plugin-captures');
function sourceCapture(absolute){
 const relative=path.relative(context.stateDirectory,absolute).replaceAll(path.sep,'/');
 if(!/^tmp\/plugin-captures\/[0-9a-f-]{36}\/captures\/openclaw-plugin-build-[A-Za-z0-9]{6}\/package-0\/node_modules\/host-turn-barrier-provider\/index\.mjs$/.test(relative))throw Error('Unknown provider capture path');
 let cursor=context.stateDirectory;
 for(const component of relative.split('/').slice(0,-1)){cursor=path.join(cursor,component);const s=fs.lstatSync(cursor);if(!s.isDirectory()||s.isSymbolicLink())throw Error('Aliased provider capture parent');}
 const stat=fs.lstatSync(absolute),raw=fs.readFileSync(absolute);
 if(!stat.isFile()||stat.isSymbolicLink()||stat.nlink!==1||fs.realpathSync(absolute)!==absolute||hash(raw)!==capture.sha256)throw Error('Changed provider source capture');
 const proofPath=`fixture-source-captures/${hash(Buffer.from(relative+'\0'+capture.sha256))}.mjs`;
 const proof=path.join(context.evidenceDirectory,proofPath);
 fs.mkdirSync(path.dirname(proof),{recursive:true,mode:0o700});
 if(!fs.existsSync(proof))fs.writeFileSync(proof,raw,{flag:'wx',mode:0o600});
 const proofStat=fs.lstatSync(proof);
 if(!proofStat.isFile()||proofStat.isSymbolicLink()||proofStat.nlink!==1||hash(fs.readFileSync(proof))!==capture.sha256)throw Error('Changed retained provider capture');
 return {kind:'fixture-capture',path:capture.sourcePath,sourcePath:capture.sourcePath,capturePath:relative,proofPath,sha256:capture.sha256};
}
function authority(url){
 if(url.startsWith('node:'))return;
 if(!url.startsWith('file:'))throw Error('Whole-caller imports require authenticated files');
 const lexical=path.resolve(fileURLToPath(url));
 if(lexical.startsWith(captureRoot+path.sep))return sourceCapture(lexical);
 const absolute=fs.realpathSync(lexical),record=permitted.get(absolute);
 if(!record||hash(fs.readFileSync(absolute))!==record.sha256){trace({event:'rejected',code:'unverified-module-bytes',basename:path.basename(absolute)});throw Error('Unverified whole-caller module');}
 return record;
}
registerHooks({
 resolve(specifier,ctx,next){
  let lexical;if(specifier.startsWith('file:'))lexical=path.resolve(fileURLToPath(specifier));else if(path.isAbsolute(specifier))lexical=path.resolve(specifier);
  else if(specifier.startsWith('.')&&ctx.parentURL?.startsWith('file:'))lexical=path.resolve(path.dirname(fileURLToPath(ctx.parentURL)),specifier);
  if(lexical?.startsWith(captureRoot+path.sep))sourceCapture(lexical);
  const value=next(specifier,ctx),record=authority(value.url);
  if(record&&value.url.endsWith('.node'))trace({event:'resolve-native',...record});return value;
 },
 load(url,ctx,next){routeConsole();const record=authority(url);if(record)trace({event:'load',...record});return next(url,ctx);},
});
