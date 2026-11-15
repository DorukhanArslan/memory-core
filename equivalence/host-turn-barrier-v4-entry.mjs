// Host v4 changes the explicit physical environment, never the business actor.
import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {isDeepStrictEqual} from 'node:util';

const hash=value=>createHash('sha256').update(value).digest('hex');
const context=JSON.parse(fs.readFileSync(process.env.MEMORY_EQ_RELEASE_CONTEXT,'utf8'));
const profile=context.hostTurnBarrierV4Profile;
const environmentBytes=fs.readFileSync(context.hostV4EnvironmentContext.path);
if(hash(environmentBytes)!==context.hostV4EnvironmentContext.sha256)throw Error('Host v4 environment context changed');
const environment=JSON.parse(environmentBytes),mapping=environment.mapping;
const capture=mapping.captureRoot;
const exclusive=(name,value)=>fs.writeFileSync(path.join(capture,name),JSON.stringify(value)+'\n',{flag:'wx',mode:0o600});
function directory(value,missing=false){
 if(!path.isAbsolute(value)||path.resolve(value)!==value)throw Error('Host v4 directory is not canonical');
 let cursor=value;
 while(true){let info;try{info=fs.lstatSync(cursor);}catch(error){if(!(missing&&cursor===value&&error.code==='ENOENT'))throw error;}
  if(info&&(!info.isDirectory()||info.isSymbolicLink()||fs.realpathSync(cursor)!==cursor))throw Error('Host v4 directory is aliased');
  const parent=path.dirname(cursor);if(parent===cursor)break;cursor=parent;}
 return value;
}
function identity(value){const s=fs.lstatSync(value,{bigint:true});return{device:String(s.dev),inode:BigInt.asUintN(64,s.ino).toString(),mode:Number(s.mode),uid:Number(s.uid)};}
function ancestors(value){
 directory(value,true);const rows=[];let cursor=value;
 while(true){try{fs.lstatSync(path.join(cursor,'.git'));throw Error('Host v4 actual execution path has Git ancestry');}
  catch(error){if(error.code!=='ENOENT')throw error;}
  const exists=fs.existsSync(cursor);rows.push({path:cursor,exists,identity:exists?identity(cursor):null,gitEntryPresent:false});
  const parent=path.dirname(cursor);if(parent===cursor)break;cursor=parent;}
 return rows;
}
function paths(){
 if(mapping.engine!=='native'||mapping.version!==4||path.dirname(mapping.executionRoot)!==environment.temporaryRoot||
  !path.basename(mapping.executionRoot).startsWith('memory-host-v4-')||mapping.cwd!==path.join(mapping.executionRoot,'cwd')||
  mapping.state!==path.join(mapping.executionRoot,'state')||mapping.workspace!==path.join(mapping.state,'workspace')||
  mapping.captureRoot===mapping.executionRoot||mapping.captureRoot.startsWith(mapping.executionRoot+path.sep)||
  mapping.executionRoot.startsWith(mapping.captureRoot+path.sep))throw Error('Host v4 actual path mapping changed');
 directory(mapping.executionRoot);directory(mapping.captureRoot);directory(mapping.cwd);directory(mapping.state);
 const executionIdentity=identity(mapping.executionRoot),captureIdentity=identity(mapping.captureRoot);
 if((executionIdentity.mode&0o777)!==0o700||executionIdentity.uid!==process.getuid()||captureIdentity.uid!==process.getuid())
  throw Error('Host v4 execution/capture ownership changed');
 return{mapping,executionIdentity,captureIdentity,cwdAncestors:ancestors(mapping.cwd),workspaceAncestors:ancestors(mapping.workspace)};
}
function gitProbe(phase){
 const filename=environment.gitContext.path,bytes=fs.readFileSync(filename);
 if(hash(bytes)!==environment.gitContext.sha256)throw Error('Host v4 original Git context changed');
 const probe=JSON.parse(bytes),argv=[probe.probe.path,filename],startedAtNs=process.hrtime.bigint().toString();
 const result=spawnSync(environment.node.execPath,argv,{cwd:process.cwd(),env:probe.expectedEnvironment,
  input:JSON.stringify({cwd:process.cwd(),workspace:mapping.workspace}),encoding:'utf8',timeout:30000,maxBuffer:4*1024*1024});
 exclusive(`git-${phase}.process.json`,{kind:'host-turn-barrier-v4-git-probe-process',argv:[environment.node.execPath,...argv],
  cwd:process.cwd(),environment:probe.expectedEnvironment,pid:result.pid,coordinatorPid:process.pid,
  stdin:JSON.stringify({cwd:process.cwd(),workspace:mapping.workspace}),actualExitObserved:result.status!==null,
  startedAtNs,finishedAtNs:process.hrtime.bigint().toString(),actualReturnCode:result.status,signal:result.signal,
  stdout:result.stdout,stderr:result.stderr,error:result.error?{name:result.error.name,message:result.error.message}:null});
 if(result.error||result.status!==0)throw Error('Host v4 original Git qualification failed; streams retained');
 const proof=JSON.parse(result.stdout);exclusive(`git-${phase}.proof.json`,proof);
 if(proof.results?.cwd!==null||proof.results?.workspace!==null)throw Error('Host v4 original findGitRoot found a repository');
 return proof;
}
function observe(phase,proof){
 const actualEnvironment=Object.fromEntries(Object.entries(process.env));
 const expected={...environment.environment,...(phase==='after-host'?{
  OPENCLAW_HOME:mapping.state,OPENCLAW_STATE_DIR:mapping.state,OPENCLAW_CONFIG_PATH:context.configPath,JITI_FS_CACHE:'false'}:{})};
 if(process.cwd()!==mapping.cwd||!isDeepStrictEqual(actualEnvironment,expected))throw Error('Host v4 actual Native cwd/environment differs from its sealed dispatch');
 const own=fileURLToPath(import.meta.url);
 return{kind:`host-turn-barrier-v4-native-${phase}`,version:4,contractSha256:profile.environmentContractSha256,
  caseWireSha256:profile.caseWireSha256,pid:process.pid,ppid:process.ppid,cwd:process.cwd(),environment:actualEnvironment,
  atNs:process.hrtime.bigint().toString(),
  argv:process.argv,execArgv:process.execArgv,actualExecutable:fs.realpathSync(process.execPath),
  executableSha256:hash(fs.readFileSync(process.execPath)),paths:paths(),originalGitProof:proof,
  source:{path:own,sha256:hash(fs.readFileSync(own))}};
}
let stdin='';for await(const chunk of process.stdin)stdin+=chunk;
let returned;
try{
 if(hash(stdin)!==profile.caseWireSha256)throw Error('Host v4 outer input changed');
 const testCase=JSON.parse(stdin);
 if(Object.keys(testCase).sort().join()!=='id,input,operation'||testCase.id!==profile.caseId||
  testCase.operation!==profile.operation||testCase.input.version!==4)throw Error('Wrong Host v4 input');
 const before=gitProbe('before');exclusive('environment-before-host.json',observe('before-host',before));
 const {runHostTurnBarrierRuntime}=await import('./host-turn-barrier-runtime.mjs');
 const result=await runHostTurnBarrierRuntime(testCase.input.businessCase.input,{runtimeRoot:context.runtime.runtimeRoot,
  evidenceDirectory:context.evidenceDirectory,stateDirectory:context.stateDirectory,configPath:context.configPath});
 const after=gitProbe('after');exclusive('environment-after-host.json',observe('after-host',after));
 returned={id:testCase.id,ok:true,result};
}catch(error){returned={id:profile.caseId,ok:false,error:{name:error.name,message:error.message,stack:error.stack}};process.exitCode=2;}
await new Promise((resolve,reject)=>process.stdout.write(JSON.stringify(returned)+'\n',error=>error?reject(error):resolve()));
process.exit(process.exitCode??0);
