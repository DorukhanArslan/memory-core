// Source-qualified filesystem classification only. This starts no memory host.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {registerHooks} from 'node:module';
import {fileURLToPath,pathToFileURL} from 'node:url';

export const CONTRACT_SHA256='124be0e13fbf71f99092e8a3ebadf5dec0aef8d2d01d6df49366a8c359abf49e';
export const HELPER_PATH='dist/git-root-DRBSRg7z.mjs';
export const HELPER_SHA256='7e7b5a2994f3ca326cb9ccb31393916d1d71fa5262a4e19e386eb920603a10fd';
export const REFERENCE_PATH='src/infra/git-root.ts';
export const REFERENCE_SHA256='84157c2595515ef21f098ab67ef31944cbddc004b9fef456220411870586f87c';
export const FUNCTION_SHA256='940791e2a9454c03e4982ee57f5e73ca4c0378e6aaff7feb92d24f3c8ed8e0fd';
const NODE={nodeVersion:'v24.16.0',icuVersion:'78.3',unicodeVersion:'17.0',
 sha256:'b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd'};
const OWN=fileURLToPath(import.meta.url),SHA=/^[0-9a-f]{64}$/;
const hash=value=>crypto.createHash('sha256').update(value).digest('hex');
const exact=(value,keys)=>{if(value===null||typeof value!=='object'||Array.isArray(value))return false;
 const actual=Object.keys(value).sort(),expected=keys.slice().sort();
 return actual.length===expected.length&&actual.every((key,index)=>key===expected[index]);};

export function strictJSON(text,limit){
 if(Buffer.byteLength(text)>limit)throw Error('Git qualification JSON exceeded its byte bound');
 const value=JSON.parse(text),pending=[value];
 while(pending.length){const item=pending.pop();
  if(typeof item==='number'&&!Number.isFinite(item))throw Error('Git qualification JSON contains a nonfinite number');
  if(item!==null&&typeof item==='object')for(const child of Object.values(item))pending.push(child);
 }
 // JSON.parse establishes syntax; this second pass rejects repeated keys.
 const frames=[];
 for(let index=0;index<text.length;index++){
  const char=text[index];
  if(char==='{'||char==='['){frames.push(char==='{'?new Set():null);continue;}
  if(char==='}'||char===']'){frames.pop();continue;}
  if(char!=='"')continue;
  const start=index++;
  while(index<text.length&&text[index]!=='"'){if(text[index]==='\\')index++;index++;}
  let next=index+1;while(/\s/.test(text[next]??'')&&next<text.length)next++;
  if(text[next]===':'){
   const key=JSON.parse(text.slice(start,index+1)),frame=frames.at(-1);
   if(!(frame instanceof Set)||frame.has(key))throw Error('Git qualification JSON has a duplicate key');
   frame.add(key);
  }
 }
 return value;
}

export function canonicalDirectory(value,{missing=false}={}){
 if(typeof value!=='string'||!path.isAbsolute(value)||path.resolve(value)!==value)
  throw Error('Git qualification needs a canonical absolute directory');
 let cursor=value,first=true;
 while(true){
  try{const stat=fs.lstatSync(cursor);
   if(!stat.isDirectory()||stat.isSymbolicLink()||fs.realpathSync(cursor)!==cursor)
    throw Error('Git qualification rejects an aliased directory');
  }catch(error){if(!(missing&&first&&error.code==='ENOENT'))throw error;}
  first=false;const parent=path.dirname(cursor);if(parent===cursor)break;cursor=parent;
 }
 return value;
}

export function validatePaths(value){
 if(!exact(value,['cwd','workspace']))throw Error('Git qualification has foreign path fields');
 return{cwd:canonicalDirectory(value.cwd),workspace:canonicalDirectory(value.workspace,{missing:true})};
}

export function sealedFile(value,{limit=64*1024*1024}={}){
 if(typeof value!=='string'||!path.isAbsolute(value)||path.resolve(value)!==value||fs.realpathSync(value)!==value)
  throw Error('Git qualification rejects an aliased file');
 const before=fs.lstatSync(value,{bigint:true});
 if(!before.isFile()||before.nlink!==1n||before.size>BigInt(limit))throw Error('Git qualification file is not bounded and singly owned');
 const bytes=fs.readFileSync(value),after=fs.lstatSync(value,{bigint:true});
 const same=['dev','ino','mode','nlink','size','mtimeNs','ctimeNs'].every(key=>before[key]===after[key]);
 if(!same||BigInt(bytes.length)!==before.size)throw Error('Git qualification file changed during observation');
 return{path:value,bytes:bytes.length,sha256:hash(bytes)};
}

export function actualNode(){
 const execPath=fs.realpathSync(process.execPath);
 return{execPath,nodeVersion:process.version,icuVersion:process.versions.icu,
  unicodeVersion:process.versions.unicode,sha256:hash(fs.readFileSync(execPath))};
}

export function buildImportAuthority(runtime){
 if(runtime===null||typeof runtime!=='object'||!Array.isArray(runtime.packages)||
  runtime.packages.length===0||runtime.packages.length>512)
  throw Error('Git qualification lacks explicit release package authority');
 const runtimeRoot=canonicalDirectory(runtime.runtimeRoot),permitted=new Map();
 let mainPackage=null;
 for(const pkg of runtime.packages){
  if(typeof pkg.location!=='string'||!pkg.location||!Array.isArray(pkg.files))
   throw Error('Git qualification has invalid release package metadata');
  const directory=canonicalDirectory(pkg.directory);
  if(directory===runtimeRoot){if(mainPackage)throw Error('Git qualification duplicated its main package');mainPackage=pkg;}
  for(const file of pkg.files){
   if(typeof file.path!=='string'||!file.path||file.path.includes('\\')||path.isAbsolute(file.path)||
    file.path.split('/').some(part=>!part||part==='.'||part==='..')||!SHA.test(file.sha256))
    throw Error('Git qualification rejects an escaped release file');
   const absolute=path.resolve(directory,file.path);
   if(!absolute.startsWith(directory+path.sep)||permitted.has(absolute)||permitted.size>=200000)
    throw Error('Git qualification duplicated or exceeded its release authority');
   permitted.set(absolute,{package:pkg.location,path:file.path,absolutePath:absolute,sha256:file.sha256});
  }
 }
 if(!mainPackage)throw Error('Git qualification omitted its approved main runtime');
 const helper=permitted.get(path.join(runtimeRoot,HELPER_PATH));
 if(!helper||helper.sha256!==HELPER_SHA256)throw Error('Git qualification changed its pinned original helper');
 return{permitted,helper};
}

export function validateContext(context,contextPath){
 if(!exact(context,['schemaVersion','kind','contractSha256','paths','expectedEnvironment',
  'approvedNodeRuntime','runtime','referenceRoot','probe'])||context.schemaVersion!==1||
  context.kind!=='host-turn-barrier-v4-git-probe-context'||context.contractSha256!==CONTRACT_SHA256)
  throw Error('Git qualification rejects another context/profile');
 validatePaths(context.paths);
 if(!exact(context.expectedEnvironment,['LANG','PATH','TZ'])||context.expectedEnvironment.LANG!=='C.UTF-8'||
  context.expectedEnvironment.TZ!=='UTC'||typeof context.expectedEnvironment.PATH!=='string')
  throw Error('Git qualification rejects an inherited or changed environment');
 if(!exact(context.probe,['path','sha256'])||context.probe.path!==OWN||!SHA.test(context.probe.sha256))
  throw Error('Git qualification has another probe source');
 const own=sealedFile(OWN),sealedContext=sealedFile(contextPath);
 if(own.sha256!==context.probe.sha256)throw Error('Git qualification probe source changed');
 const reference=path.join(canonicalDirectory(context.referenceRoot),REFERENCE_PATH),source=sealedFile(reference);
 if(source.sha256!==REFERENCE_SHA256)throw Error('Git qualification changed its pinned original source');
 const authority=buildImportAuthority(context.runtime);
 const node=actualNode();
 if(!exact(context.approvedNodeRuntime,['execPath','nodeVersion','icuVersion','unicodeVersion','sha256'])||
  Object.entries(node).some(([key,value])=>context.approvedNodeRuntime[key]!==value)||
  Object.entries(NODE).some(([key,value])=>node[key]!==value))
  throw Error('Git qualification requires the exact approved Node authority');
 if(process.execArgv.length||process.cwd()!==context.paths.cwd||
  !exact(process.env,['LANG','PATH','TZ'])||
  Object.entries(context.expectedEnvironment).some(([key,value])=>process.env[key]!==value))
  throw Error('Git qualification actual process cwd/environment/arguments changed');
 const helper=sealedFile(authority.helper.absolutePath);
 if(helper.sha256!==HELPER_SHA256)throw Error('Git qualification original helper bytes changed');
 return{...authority,node,sourceAuthority:{probe:{path:own.path,sha256:own.sha256},context:sealedContext,
  reference:{path:source.path,sha256:source.sha256},helper:{...authority.helper,
   exportName:'t',functionName:'findGitRoot',functionSourceSha256:FUNCTION_SHA256}}};
}

async function main(){
 if(process.argv.length!==3)throw Error('Git qualification needs exactly one explicit context');
 const contextPath=process.argv[2],contextSeal=sealedFile(contextPath),
  context=strictJSON(fs.readFileSync(contextPath,'utf8'),64*1024*1024);
 const authority=validateContext(context,contextPath);
 if(JSON.stringify(contextSeal)!==JSON.stringify(authority.sourceAuthority.context))
  throw Error('Git qualification context changed before admission');
 let text='';for await(const chunk of process.stdin){text+=chunk;if(Buffer.byteLength(text)>32768)throw Error('Git qualification request exceeded its bound');}
 const paths=validatePaths(strictJSON(text,32768));
 if(paths.cwd!==context.paths.cwd||paths.workspace!==context.paths.workspace)
  throw Error('Git qualification request differs from its sealed context');
 const loads=[],loadedSeals=new Map(),functionToString=Function.prototype.toString;
 function imported(url){
  if(url.startsWith('node:'))return null;
  if(!url.startsWith('file:'))throw Error('Git qualification imported a non-file module');
  const parsed=new URL(url);if(parsed.search||parsed.hash)throw Error('Git qualification imported an aliased module URL');
  const absolute=fileURLToPath(parsed),record=authority.permitted.get(absolute);
  if(!record)throw Error('Git qualification imported an unapproved module');
  const sealed=sealedFile(absolute);
  if(sealed.sha256!==record.sha256)throw Error('Git qualification imported changed original bytes');
  loadedSeals.set(absolute,sealed);return record;
 }
 function retain(event,url,record){
  if(loads.length>=512)throw Error('Git qualification import receipts exceeded their bound');
  loads.push({event,url,...record});
 }
 const hooks=registerHooks({resolve(specifier,context,next){const value=next(specifier,context),record=imported(value.url);
  if(record&&value.url.endsWith('.node'))retain('resolve-native',value.url,record);return value;},
  load(url,context,next){const record=imported(url);if(record)retain('load',url,record);return next(url,context);}});
 let calls;
 try{
  const module=await import(pathToFileURL(authority.helper.absolutePath).href),findGitRoot=module.t;
  if(typeof findGitRoot!=='function'||findGitRoot.name!=='findGitRoot'||findGitRoot.length!==1||
   hash(functionToString.call(findGitRoot))!==FUNCTION_SHA256)
   throw Error('Git qualification lost its actual original function export');
  calls=[];
  for(const role of ['cwd','workspace']){
   const startedAtNs=process.hrtime.bigint().toString(),result=findGitRoot(paths[role]),finishedAtNs=process.hrtime.bigint().toString();
   if(result!==null&&typeof result!=='string')throw Error('Original findGitRoot returned an unsupported value');
   calls.push({role,arguments:[paths[role]],result,startedAtNs,finishedAtNs,
    functionRef:'original-findGitRoot-export-t'});
  }
 }finally{hooks.deregister();}
 if(!loads.some(item=>item.event==='load'&&item.absolutePath===authority.helper.absolutePath))
  throw Error('Git qualification omitted actual original helper loading');
 for(const [filename,seal]of loadedSeals)if(JSON.stringify(sealedFile(filename))!==JSON.stringify(seal))
  throw Error('Original Git qualification source changed during its actual calls');
 for(const item of [authority.sourceAuthority.context,authority.sourceAuthority.probe,authority.sourceAuthority.reference])
  if(sealedFile(item.path).sha256!==item.sha256)throw Error('Git qualification authority changed during execution');
 if(JSON.stringify(actualNode())!==JSON.stringify(authority.node)||process.cwd()!==paths.cwd||
  !exact(process.env,['LANG','PATH','TZ'])||Object.entries(context.expectedEnvironment).some(([key,value])=>process.env[key]!==value))
  throw Error('Git qualification process authority changed during actual calls');
 const report={kind:'host-turn-barrier-v4-original-git-probe',node:authority.node,
  sourceAuthority:authority.sourceAuthority,paths,results:Object.fromEntries(calls.map(call=>[call.role,call.result])),
  pid:process.pid,ppid:process.ppid,cwd:process.cwd(),environment:{...process.env},
  argv:[...process.argv],execArgv:[...process.execArgv],calls,loads,acceptancePointsAwarded:0};
 const output=JSON.stringify(report)+'\n';if(Buffer.byteLength(output)>8*1024*1024)throw Error('Git qualification output exceeded its bound');
 process.stdout.write(output);
}

if(process.argv[1]&&path.resolve(process.argv[1])===OWN){
 try{await main();}catch(error){process.stderr.write(JSON.stringify({kind:'host-turn-barrier-v4-git-probe-failure',
  error:{name:error.name,message:error.message,stack:error.stack},pid:process.pid,ppid:process.ppid})+'\n');process.exitCode=2;}
}
