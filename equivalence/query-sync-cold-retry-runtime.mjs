// Observe two frozen cold public searches and one real owned publication refusal.
// No synchronization, retrieval, publication or timer algorithm is supplied here.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
import {Worker,MessagePort} from 'node:worker_threads';
import {pathToFileURL} from 'node:url';
import {isDeepStrictEqual} from 'node:util';
import {deserialize} from 'node:v8';

const plain=value=>JSON.parse(JSON.stringify(value));
const sha=value=>crypto.createHash('sha256').update(value).digest('hex');
const errorValue=error=>({name:error.name,message:error.message,code:error.code??null,stack:error.stack??null});
const sqlValue=value=>typeof value==='bigint'?{sqliteInt64:value.toString()}:
  value instanceof Uint8Array?{sqliteBlobHex:Buffer.from(value).toString('hex')}:value;

export function orderedPublicQueryLabels(input){
  const labels=input.steps.filter(step=>step.operation==='public-memory-search').map(step=>step.label);
  if(labels.length!==2||new Set(labels).size!==2||Object.keys(input.queries).length!==2||
    labels.some(label=>!Object.hasOwn(input.queries,label)))throw Error('Cold retry requires two exact ordered public query steps');
  return labels;
}

export async function runQuerySyncColdRetryRuntime(input,config){
  const base=config.stateDirectory,workspace=path.join(base,'workspace');
  const raw={kind:'query-sync-cold-retry',engine:'native',caseId:config.caseId,input:plain(input),
    pid:process.pid,ppid:process.ppid,fixtureBase:base,events:[],owners:{},ownerNames:{},
    facadeCalls:[],originalGetCalls:[],statusCalls:[],originalSearchCalls:[],methodCalls:[],
    backgroundCalls:[],poolCalls:[],workerDispatches:[],workerMessages:[],workerStates:[],leaseCalls:[],
    snapshots:[],sourceStages:{},toolCalls:{},fault:null,faultSyscalls:[]};
  let sequence=0,phase='setup',activeTool=null,requestLabel=null,dbPath;
  let OriginalManager,originalGet,closeAll,Pool,originalPoolRun;
  let foreground;
  let armedFault=null;
  const owners=new Map(),refs=new WeakMap(),restorations=[],workers=new Map(),leaseDatabases=new Map();
  let refCount=0,workerCount=0;
  const ref=value=>{if(!value)return null;if(!refs.has(value))refs.set(value,`ref-${++refCount}`);return refs.get(value);};
  const event=(name,fields={})=>{const row={event:name,sequence:++sequence,phase,activeTool,atNs:process.hrtime.bigint().toString(),...fields};raw.events.push(row);return row;};
  function carrier(value,seen=new WeakMap()){
    if(value===undefined)return{privateType:'undefined'};
    if(typeof value==='bigint')return{privateType:'bigint',value:value.toString()};
    if(typeof value==='number'&&!Number.isFinite(value))return{privateType:'number',value:String(value)};
    if(typeof value==='function')return{privateType:'nativeCallback',name:value.name,ref:ref(value)};
    if(typeof value==='symbol')return{privateType:'symbol',description:value.description};
    if(value===null||typeof value!=='object')return value;
    if(value instanceof Error)return{privateType:'error',...errorValue(value)};
    if(value instanceof AbortSignal)return{privateType:'AbortSignal',aborted:value.aborted,reason:carrier(value.reason,seen)};
    if(value instanceof MessagePort)return{privateType:'MessagePort',ref:ref(value)};
    if(value instanceof ArrayBuffer||value instanceof SharedArrayBuffer)return{privateType:value.constructor.name,byteLength:value.byteLength,hex:Buffer.from(value).toString('hex')};
    if(ArrayBuffer.isView(value))return{privateType:value.constructor.name,byteLength:value.byteLength,hex:Buffer.from(value.buffer,value.byteOffset,value.byteLength).toString('hex')};
    if(seen.has(value))return{privateType:'reference',ref:seen.get(value)};
    seen.set(value,ref(value));
    if(value instanceof Map)return{privateType:'Map',entries:[...value].map(([key,item])=>[carrier(key,seen),carrier(item,seen)])};
    if(value instanceof Set)return{privateType:'Set',values:[...value].map(item=>carrier(item,seen))};
    if(Array.isArray(value))return value.map(item=>carrier(item,seen));
    const result={};for(const key of Reflect.ownKeys(value)){
      const descriptor=Object.getOwnPropertyDescriptor(value,key);
      if(!descriptor||!Object.hasOwn(descriptor,'value'))continue;
      const name=typeof key==='symbol'?`[symbol:${key.description}]`:key;
      result[name]=carrier(descriptor.value,seen);
    }return result;
  }
  const state=owner=>({closed:owner.closed,closing:owner.closing,dirty:owner.dirty,
    memoryWatchGeneration:owner.memoryWatchGeneration,activeManagerOperations:owner.activeManagerOperations,
    activeBackgroundSearchSyncs:owner.activeBackgroundSearchSyncs?.size??null,
    syncing:owner.syncing!==null,providerInitialized:owner.providerInitialized,
    memoryFullRetryDirty:owner.memoryFullRetryDirty,sessionsDirty:owner.sessionsDirty});
  function decodedSerialized(message,direction){
    const decoded={};
    // The original SQLite broker protocol uses V8 bytes in these named fields.
    // Keep those bytes intact and independently decode only their known carriers.
    const keys=direction==='request'&&['open','execute','execute-frame'].includes(message?.type)
      ? ['input','preparation']:direction==='reply'&&Number.isSafeInteger(message?.id)&&message?.ok===true
        ? ['value']:[];
    for(const key of keys){if(message[key] instanceof Uint8Array){
      try{decoded[key]={value:carrier(deserialize(message[key])),bytesSha256:sha(message[key])};}
      catch(error){decoded[key]={error:errorValue(error),bytesSha256:sha(message[key])};}
    }}return decoded;
  }
  const originalExec=DatabaseSync.prototype.exec,originalPrepare=DatabaseSync.prototype.prepare,
    originalDbClose=DatabaseSync.prototype.close,originalLocation=DatabaseSync.prototype.location;
  function coordination(database){
    if(!dbPath||!database.isOpen)return null;
    const location=originalLocation.call(database,'main');
    if(location!==`${dbPath}.generation-lock.sqlite`&&location!==`${dbPath}.generation-writer.sqlite`&&
      location!==`${dbPath}.reindex-lock.sqlite`)return null;
    leaseDatabases.set(database,{databaseRef:ref(database),location});return location;
  }
  function leaseCall(database,method,args,run){
    const location=coordination(database);if(!location)return run();
    const entered=event('original-coordination-enter',{method,databaseRef:ref(database),location});
    const call={id:`lease-${raw.leaseCalls.length+1}`,method,args:carrier(args),databaseRef:ref(database),location,
      phase,activeTool,enterSeq:entered.sequence,startedAtNs:entered.atNs,transactionBefore:database.isTransaction,
      originalCallerStack:new Error('Original coordination call-through').stack};raw.leaseCalls.push(call);
    try{const result=run();call.result=carrier(result);return result;}
    catch(error){call.error=errorValue(error);throw error;}
    finally{call.openAfter=database.isOpen;call.transactionAfter=database.isOpen?database.isTransaction:null;
      const returned=event('original-coordination-return',{method,databaseRef:ref(database),location});call.returnSeq=returned.sequence;call.finishedAtNs=returned.atNs;}
  }
  DatabaseSync.prototype.exec=function(...args){return leaseCall(this,'exec',args,()=>originalExec.apply(this,args));};
  DatabaseSync.prototype.prepare=function(...args){
    const location=coordination(this),statement=originalPrepare.apply(this,args);
    if(location){const database=this,originalStatementGet=statement.get;
      statement.get=function(...getArgs){return leaseCall(database,'statement.get',[args[0],...getArgs],()=>originalStatementGet.apply(this,getArgs));};}
    return statement;
  };
  DatabaseSync.prototype.close=function(...args){return leaseCall(this,'close',args,()=>originalDbClose.apply(this,args));};
  const persist=()=>fs.writeFileSync(path.join(config.evidenceDirectory,'native-raw.json'),JSON.stringify([raw])+'\n');
  function physical(label,extra={}){
    const entered=event('physical-sql-read-enter',{label,...extra});
    let value;
    try{
      const stat=fs.lstatSync(dbPath);
      if(!stat.isFile()||stat.isSymbolicLink()||stat.nlink!==1)throw Error('Aliased physical index');
      const db=new DatabaseSync(dbPath,{readOnly:true});
      try{
        db.exec('BEGIN');
        const schema=db.prepare("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name LIKE 'memory_index_%' ORDER BY type,name").all();
        const tables={};
        for(const table of schema.filter(row=>row.type==='table')){
          tables[table.name]=db.prepare('SELECT * FROM "'+table.name.replaceAll('"','""')+'"').all()
            .map(row=>Object.fromEntries(Object.entries(row).map(([key,item])=>[key,sqlValue(item)])));
        }
        value={exists:true,dbPath,schema,tables};
      }finally{if(db.isTransaction)db.exec('ROLLBACK');db.close();}
    }catch(error){if(error.code!=='ENOENT')throw error;value={exists:false,dbPath,error:errorValue(error)};}
    const returned=event('physical-sql-read-return',{label,...extra});
    const coordinationLeases=[...leaseDatabases].map(([database,record])=>({...record,open:database.isOpen,
      transactionActive:database.isOpen?database.isTransaction:false}));
    const serializedJSON=JSON.stringify(value),row={label,enterSeq:entered.sequence,returnSeq:returned.sequence,
      startedAtNs:entered.atNs,finishedAtNs:returned.atNs,...extra,...value,serializedJSON,sha256:sha(serializedJSON)};
    row.coordinationLeases=coordinationLeases;
    raw.snapshots.push(row);return row;
  }
  const declaredPaths=new Set(Object.keys(input.initialFiles));
  function sourceStage(label){
    const entered=event('source-read-enter',{label});
    const paths=new Set(declaredPaths);
    function walk(folder){for(const entry of fs.readdirSync(folder,{withFileTypes:true})){
      const filename=path.join(folder,entry.name),relative=path.relative(workspace,filename).replaceAll(path.sep,'/');
      if(entry.isSymbolicLink())throw Error('Aliased source path');
      if(entry.isDirectory())walk(filename);else if(entry.isFile())paths.add(relative);else throw Error('Nonregular source path');
    }}
    walk(workspace);
    const common=[],records=[];
    for(const relative of [...paths].sort()){
      const filename=path.join(workspace,relative);
      try{
        const stat=fs.lstatSync(filename,{bigint:true});
        if(!stat.isFile()||stat.isSymbolicLink()||stat.nlink!==1n)throw Error('The owned source is no longer an independent file');
        const bytes=fs.readFileSync(filename),mtimeMs=Number(stat.mtimeNs)/1e6;
        if(BigInt(bytes.length)!==stat.size)throw Error('Source size changed during observation');
        const row={path:relative,kind:'file',text:bytes.toString('utf8'),hex:bytes.toString('hex'),sha256:sha(bytes),size:bytes.length,mtimeMs};
        common.push(row);records.push({...row,absolutePath:filename,stat:carrier(stat)});
      }catch(error){if(error.code!=='ENOENT')throw error;const row={path:relative,kind:'missing'};common.push(row);records.push({...row,absolutePath:filename,error:errorValue(error)});}
    }
    const returned=event('source-read-return',{label});
    raw.sourceStages[label]={enterSeq:entered.sequence,returnSeq:returned.sequence,records,common};return common;
  }
  function observe(owner){
    if(!owner)return owner;
    const ownerId=ref(owner);if(owners.has(ownerId))return owner;
    owners.set(ownerId,owner);
    raw.owners[ownerId]={ownerId,purpose:owner.purpose,settings:plain(owner.settings),constructorName:owner.constructor.name,
      acquiredSeq:sequence,providerInitializedAtAcquisition:owner.providerInitialized,stateAtAcquisition:state(owner)};
    for(const name of ['status','search','sync','syncAdmitted','syncPublishedIndexInBackground','runSync','syncMemoryFiles',
      'markMemoryWatchDirty','prepareKeywordSearch','close','awaitManagerIdle','takeReindexRetryStateForMaintenance','adoptReindexRetryState']){
      const original=owner[name];if(typeof original!=='function')throw Error(`Missing original manager method ${name}`);
      owner[name]=function(...args){
        const entered=event(`original-${name}-enter`,{ownerId,requestLabel,receiverIsExactObservedOwner:this===owner});
        const call={id:`method-${raw.methodCalls.length+1}`,method:name,ownerId,phase,activeTool,requestLabel,
          args:carrier(args),enterSeq:entered.sequence,startedAtNs:entered.atNs,receiverIsExactObservedOwner:this===owner,stateBefore:state(owner)};
        raw.methodCalls.push(call);
        if(name==='status')raw.statusCalls.push(call);
        if(name==='search'){call.query=args[0];call.options=carrier(args[1]);call.optionKeys=Reflect.ownKeys(args[1]??{}).map(String);raw.originalSearchCalls.push(call);}
        if(name==='syncPublishedIndexInBackground')raw.backgroundCalls.push(call);
        const finish=(value,error)=>{
          if(error)call.error=errorValue(error);else {call.result=carrier(value);call.nativeSerializedJSON=JSON.stringify(value);}
          call.stateAfter=state(owner);
          const returned=event(`original-${name}-return`,{ownerId,requestLabel:call.requestLabel,error:!!error,receiverIsExactObservedOwner:this===owner});
          call.returnSeq=returned.sequence;call.finishedAtNs=returned.atNs;
          if(name==='prepareKeywordSearch'&&!error)physical(`read-generation-${call.id}`,{ownerId,methodCallId:call.id});
        };
        try{
          const returned=original.apply(this,args);
          if(returned&&typeof returned.then==='function'){
            call.returnedPromiseRef=ref(returned);
            returned.then(value=>finish(value),error=>finish(undefined,error));
          }else finish(returned);
          return returned;
        }catch(error){finish(undefined,error);throw error;}
      };
      restorations.push(()=>{owner[name]=original;});
    }
    return owner;
  }
  const originalPost=Worker.prototype.postMessage;
  Worker.prototype.postMessage=function(...args){
    let workerId=workers.get(this);
    if(!workerId){workerId=`worker-${++workerCount}`;workers.set(this,workerId);
      raw.workerStates.push({workerId,threadId:this.threadId,firstObservedSeq:sequence});
      this.on('message',message=>{const row=event('actual-worker-message',{workerId,threadId:this.threadId});raw.workerMessages.push({workerId,threadId:this.threadId,sequence:row.sequence,message:carrier(message),decodedSerialized:decodedSerialized(message,'reply')});});
      this.on('exit',exitCode=>{const row=event('actual-worker-exit',{workerId,exitCode});raw.workerStates.find(item=>item.workerId===workerId).exit={sequence:row.sequence,exitCode};});
    }
    const entered=event('actual-worker-dispatch-enter',{workerId,threadId:this.threadId});
    const call={workerId,threadId:this.threadId,phase,activeTool,enterSeq:entered.sequence,startedAtNs:entered.atNs,
      message:carrier(args[0]),decodedSerialized:decodedSerialized(args[0],'request'),transferList:carrier(args[1])};raw.workerDispatches.push(call);
    try{const result=originalPost.apply(this,args);call.returnedUndefined=result===undefined;return result;}
    catch(error){call.error=errorValue(error);throw error;}
    finally{const returned=event('actual-worker-dispatch-return',{workerId});call.returnSeq=returned.sequence;call.finishedAtNs=returned.atNs;}
  };
  async function toolCall(tool,label,args){
    activeTool=label;const entered=event('actual-tool-enter',{label,args:plain(args)});
    const call={label,args:plain(args),enterSeq:entered.sequence,startedAtNs:entered.atNs};raw.toolCalls[label]=call;
    try{
      const envelope=await tool.execute(`query-sync-${label}`,plain(args));
      call.nativeDetailsOwnKeys=Object.keys(envelope.details??{});
      call.nativeDetailsUndefinedOwnKeys=Object.keys(envelope.details??{}).filter(key=>envelope.details[key]===undefined);
      call.nativeEnvelopeSerializedJSON=JSON.stringify(envelope);call.envelope=plain(envelope);
      if(!Array.isArray(call.envelope.content)||call.envelope.content[0]?.type!=='text'||
        !isDeepStrictEqual(JSON.parse(call.envelope.content[0].text),call.envelope.details))throw Error('Original whole tool carrier differs from its details');
      return call.envelope.details;
    }catch(error){call.error=errorValue(error);throw error;}
    finally{const returned=event('actual-tool-return',{label});call.returnSeq=returned.sequence;call.finishedAtNs=returned.atNs;activeTool=null;}
  }
  function faultSyscall(method,args,run){
    const entered=event('fault-syscall-enter',{method,args:carrier(args)});
    const call={id:`fault-syscall-${raw.faultSyscalls.length+1}`,method,args:carrier(args),
      enterSeq:entered.sequence,startedAtNs:entered.atNs};raw.faultSyscalls.push(call);
    try{const value=run();call.result=carrier(value);return value;}
    catch(error){call.error=errorValue(error);throw error;}
    finally{const returned=event('fault-syscall-return',{method,error:!!call.error});
      call.returnSeq=returned.sequence;call.finishedAtNs=returned.atNs;}
  }
  function faultPath(filename){
    let stat;
    try{stat=faultSyscall('lstatSync',[filename],()=>fs.lstatSync(filename,{bigint:true}));}
    catch(error){if(error.code==='ENOENT')return{path:filename,kind:'missing',error:errorValue(error)};throw error;}
    const identity={device:stat.dev.toString(),inode:stat.ino.toString(),nlink:Number(stat.nlink),
      mode:Number(stat.mode),uid:Number(stat.uid),size:Number(stat.size)};
    const result={path:filename,identity,stat:carrier(stat)};
    if(stat.isSymbolicLink())return{...result,kind:'symlink',
      target:faultSyscall('readlinkSync',[filename],()=>fs.readlinkSync(filename))};
    if(!stat.isFile())return{...result,kind:stat.isDirectory()?'directory':'other'};
    if(stat.nlink!==1n||Number(stat.uid)!==process.getuid()||stat.size>1024n*1024n||
      faultSyscall('realpathSync',[filename],()=>fs.realpathSync(filename))!==filename)throw Error('Unowned or excessive refusal sidecar');
    const bytes=faultSyscall('readFileSync',[filename],()=>fs.readFileSync(filename));
    return{...result,kind:'file',sha256:sha(bytes),hex:bytes.toString('hex')};
  }
  const sameFaultIdentity=(left,right)=>left?.device===right?.device&&left?.inode===right?.inode&&
    left?.nlink===right?.nlink&&left?.uid===right?.uid;
  function armFault(){
    if(armedFault||!input.fault||input.fault.kind!=='actual-owned-publication-sidecar-dangling-symlink')throw Error('Invalid cold retry refusal schedule');
    const entered=event('fault-arm-enter',{ownerId:ref(foreground)});
    const sidecar=`${dbPath}.reindex-lock.sqlite`,target=path.resolve(base,input.fault.target),
      backup=`${sidecar}.cold-retry-owned-backup`;
    if(!path.isAbsolute(dbPath)||!dbPath.startsWith(base+path.sep)||
      !target.startsWith(base+path.sep)||target===sidecar||
      fs.realpathSync(path.dirname(sidecar))!==path.dirname(sidecar))throw Error('Fault escaped the actual acquired index owner');
    const receipt={kind:input.fault.kind,ownerId:ref(foreground),dbPath,sidecar,target,backup,
      armEnterSeq:entered.sequence,initial:faultPath(sidecar),targetBefore:faultPath(target),
      targetParentBefore:faultPath(path.dirname(target)),backupBefore:faultPath(backup),removed:false};
    raw.fault=receipt;
    if(receipt.targetBefore.kind!=='missing'||receipt.targetParentBefore.kind!=='missing'||
      receipt.backupBefore.kind!=='missing'||!['file','missing'].includes(receipt.initial.kind))throw Error('Refusal must use an owned missing target and independent sidecar');
    // Record ownership before mutation so emergency cleanup retains any real partial arm.
    armedFault=receipt;
    if(receipt.initial.kind==='file'){
      faultSyscall('renameSync',[sidecar,backup],()=>fs.renameSync(sidecar,backup));
      receipt.backupAfterRename=faultPath(backup);
      if(!sameFaultIdentity(receipt.initial.identity,receipt.backupAfterRename.identity)||
        receipt.initial.sha256!==receipt.backupAfterRename.sha256)throw Error('Renamed refusal sidecar identity changed');
    }
    faultSyscall('symlinkSync',[target,sidecar],()=>fs.symlinkSync(target,sidecar));
    receipt.armed=faultPath(sidecar);receipt.targetAfterArm=faultPath(target);
    if(receipt.armed.kind!=='symlink'||receipt.armed.target!==target||receipt.targetAfterArm.kind!=='missing')throw Error('Actual dangling refusal was not armed');
    receipt.armReturnSeq=event('fault-arm-return',{ownerId:ref(foreground),sidecar,target}).sequence;
  }
  function removeFault({emergency=false}={}){
    if(!armedFault)throw Error('No owned cold retry fault to remove');
    const receipt=armedFault,entered=event('fault-remove-enter',{ownerId:ref(foreground),emergency});
    receipt.removeEnterSeq=entered.sequence;receipt.emergencyRemoval=emergency;
    receipt.beforeRemoval=faultPath(receipt.sidecar);receipt.targetBeforeRemoval=faultPath(receipt.target);
    if(!receipt.armed||receipt.beforeRemoval.kind!=='symlink'||
      receipt.beforeRemoval.target!==receipt.target||
      !sameFaultIdentity(receipt.beforeRemoval.identity,receipt.armed.identity)||
      receipt.targetBeforeRemoval.kind!=='missing')throw Error('Refusal sidecar ownership changed before removal');
    faultSyscall('unlinkSync',[receipt.sidecar],()=>fs.unlinkSync(receipt.sidecar));
    receipt.afterUnlink=faultPath(receipt.sidecar);
    if(receipt.afterUnlink.kind!=='missing')throw Error('Owned refusal unlink did not remove its symlink');
    if(receipt.initial.kind==='file'){
      receipt.backupBeforeRestore=faultPath(receipt.backup);
      if(!sameFaultIdentity(receipt.initial.identity,receipt.backupBeforeRestore.identity)||
        receipt.initial.sha256!==receipt.backupBeforeRestore.sha256)throw Error('Refusal backup changed before restoration');
      faultSyscall('renameSync',[receipt.backup,receipt.sidecar],()=>fs.renameSync(receipt.backup,receipt.sidecar));
    }
    receipt.restored=faultPath(receipt.sidecar);receipt.backupAfterRestore=faultPath(receipt.backup);
    if(receipt.restored.kind!==receipt.initial.kind||receipt.backupAfterRestore.kind!=='missing'||
      (receipt.initial.kind==='file'&&(!sameFaultIdentity(receipt.initial.identity,receipt.restored.identity)||
       receipt.initial.sha256!==receipt.restored.sha256)))throw Error('Actual refusal restoration differs from its owned initial state');
    receipt.removed=true;armedFault=null;
    receipt.removeReturnSeq=event('fault-remove-return',{ownerId:ref(foreground),emergency}).sequence;
  }
  try{
    fs.mkdirSync(workspace,{recursive:true});
    for(const[relative,text]of Object.entries(input.initialFiles)){
      if(path.isAbsolute(relative)||relative.split('/').includes('..'))throw Error('Invalid owned source path');
      const filename=path.join(workspace,relative);fs.mkdirSync(path.dirname(filename),{recursive:true});
      fs.writeFileSync(filename,text,{flag:'wx'});fs.utimesSync(filename,input.initialSourceMtimeMs/1000,input.initialSourceMtimeMs/1000);
    }
    const sources={initial:sourceStage('initial')};event('source-fixture-finished');
    const cfg={...plain(input.config),agents:{defaults:{workspace}}};raw.requestedConfig=plain(cfg);
    const imp=relative=>import(pathToFileURL(path.join(config.runtimeRoot,relative)).href);
    ({WorkerTaskPool:Pool}=await imp('dist/plugin-sdk/process-runtime.js'));
    originalPoolRun=Pool.prototype.run;
    Pool.prototype.run=function(...args){
      const entered=event('original-pool-run-enter',{poolId:ref(this)});
      const call={poolId:ref(this),phase,activeTool,args:carrier(args),enterSeq:entered.sequence,startedAtNs:entered.atNs};raw.poolCalls.push(call);
      try{const result=originalPoolRun.apply(this,args);result.then(value=>{call.result=carrier(value);const returned=event('original-pool-run-return',{poolId:call.poolId});call.returnSeq=returned.sequence;call.finishedAtNs=returned.atNs;},error=>{call.error=errorValue(error);const returned=event('original-pool-run-return',{poolId:call.poolId,error:true});call.returnSeq=returned.sequence;call.finishedAtNs=returned.atNs;});return result;}
      catch(error){call.error=errorValue(error);call.returnSeq=event('original-pool-run-return',{poolId:call.poolId,error:true}).sequence;throw error;}
    };
    const managerModule=await imp('dist/extensions/memory-core/manager-runtime.js');
    OriginalManager=managerModule.MemoryIndexManager;closeAll=managerModule.closeAllMemoryIndexManagers;
    const api=await imp('dist/extensions/memory-core/runtime-api.js');
    const{createPluginStateKeyedStore}=await imp('dist/plugin-sdk/plugin-state-store-runtime.js');
    api.configureMemoryCoreDreamingState(options=>createPluginStateKeyedStore('memory-core',options));
    const{createMemorySearchTool}=await imp('dist/tools-DotaQGXh.mjs');
    originalGet=OriginalManager.get;
    OriginalManager.get=function(...args){
      const params=args[0],entered=event('original-get-enter',{agentId:params.agentId,requestedPurpose:params.purpose??'default'});
      const sampled=foreground;
      const call={id:`get-${raw.originalGetCalls.length+1}`,phase,activeTool,agentId:params.agentId,
        requestedPurpose:params.purpose??'default',config:plain(params.cfg),parameterKeys:Object.keys(params),
        maintenanceSourceOwnerId:ref(params.maintenanceSource),receiverIsOriginalClass:this===OriginalManager,
        enterSeq:entered.sequence,startedAtNs:entered.atNs};raw.originalGetCalls.push(call);
      const result=originalGet.apply(this,args);
      return result.then(owner=>{
        observe(owner);call.ownerId=ref(owner);call.actualPurpose=owner?.purpose??null;
        call.returnedIsExactSampledOwner=sampled?owner===sampled:null;
        const returned=event('original-get-return',{ownerId:ref(owner)});call.returnSeq=returned.sequence;call.finishedAtNs=returned.atNs;return owner;
      },error=>{call.error=errorValue(error);call.returnSeq=event('original-get-return',{error:true}).sequence;throw error;});
    };
    const acquire=async label=>{
      const entered=event('original-facade-enter',{label});
      const returned=await api.getMemorySearchManager({cfg,agentId:input.identity.agentId,purpose:'default'});
      const call={label,ownerId:ref(returned.manager),debug:carrier(returned.debug),error:returned.error??null,
        enterSeq:entered.sequence,returnSeq:event('original-facade-return',{label,ownerId:ref(returned.manager)}).sequence};raw.facadeCalls.push(call);
      if(!returned.manager)throw Error(`Original facade failed: ${returned.error??'no manager'}`);raw.ownerNames[label]=ref(returned.manager);return returned.manager;
    };
    const makeTool=()=>{const tool=createMemorySearchTool({config:cfg,...plain(input.toolOptions)});if(!tool)throw Error('Original public memory_search factory returned no tool');return tool;};
    const{t:resolveMemorySearchConfig}=await imp('dist/memory-search-CIhUURbE.mjs');
    const resolved=resolveMemorySearchConfig(cfg,input.identity.agentId);
    if(!resolved)throw Error('Original source/search settings are disabled');
    dbPath=resolved.store.databasePath;raw.resolvedConfigBeforeOpen=plain(resolved);
    phase='owner-acquisition';physical('before-owner-open');
    foreground=await acquire('foreground');
    requestLabel='after-owner-open';const initialStatus=foreground.status();requestLabel=null;
    if(initialStatus.dbPath!==dbPath||foreground.purpose!=='default')throw Error('Unexpected original default database owner');
    raw.initialStatus=carrier(initialStatus);raw.foregroundOwnerId=ref(foreground);
    physical('after-owner-open');
    if(input.fault){phase='fault-arm';armFault();}
    const tool=makeTool(),searches={},dispatches={},labels=orderedPublicQueryLabels(input);
    for(let index=0;index<labels.length;index++){
      const label=labels[index];phase=label;
      searches[label]=await toolCall(tool,label,input.queries[label]);
      if(index===0&&input.fault){phase='fault-remove';removeFault();}
      // The next loop iteration immediately enters the second original tool.
      // No snapshots, status calls, explicit sync, reopen or private wait occur here.
    }
    phase='after-two-queries';
    for(const label of labels){
      const call=raw.toolCalls[label];
      const during=raw.methodCalls.filter(row=>row.ownerId===ref(foreground)&&row.activeTool===label&&
        call.enterSeq<row.enterSeq&&row.enterSeq<call.returnSeq);
      dispatches[label]={managerSearches:during.filter(row=>row.method==='search').length,
        bootstrapAttempts:during.filter(row=>row.method==='syncAdmitted'&&row.args[0]?.reason==='search-bootstrap').length};
      const actualGets=raw.originalGetCalls.filter(row=>row.activeTool===label&&row.requestedPurpose==='default');
      if(!actualGets.length||actualGets.some(row=>row.ownerId!==ref(foreground)))throw Error('Public query replaced the exact original foreground owner');
    }
    if(input.fault){
      const first=raw.toolCalls[labels[0]];
      raw.fault.actualBootstrapFailures=raw.methodCalls.filter(row=>row.ownerId===ref(foreground)&&
        row.method==='syncAdmitted'&&row.args[0]?.reason==='search-bootstrap'&&row.error&&
        first.enterSeq<row.enterSeq&&row.returnSeq<first.returnSeq).map(row=>row.id);
      if(!raw.fault.actualBootstrapFailures.length)throw Error('The actual owned sidecar refusal did not affect first-query bootstrap');
    }
    physical('after-two-queries');
    phase='owner-close';await foreground.close();
    physical('after-close');sources.afterClose=sourceStage('afterClose');
    raw.result={provider:'none',searches,dispatches,sources};
    raw.completed=true;return raw.result;
  }catch(error){raw.error=errorValue(error);throw error;}
  finally{
    phase='teardown';
    if(armedFault){try{removeFault({emergency:true});}catch(error){raw.faultCleanupError=errorValue(error);}}
    event('runtime-close-all-enter',{returnedManagerIds:[...owners.keys()]});
    raw.runtimeCloseAllInvoked=typeof closeAll==='function';
    try{if(raw.runtimeCloseAllInvoked){await closeAll();raw.runtimeCloseAllReturned=true;}else raw.runtimeCloseAllReturned=false;}
    catch(error){raw.runtimeCloseAllReturned=false;raw.teardownError=errorValue(error);}
    raw.finalManagerStates=[...owners].map(([ownerId,owner])=>({ownerId,purpose:owner.purpose,closed:owner.closed,closing:owner.closing}));
    raw.allManagersClosed=raw.finalManagerStates.length>0&&raw.finalManagerStates.every(row=>row.closed===true&&row.closing===true);
    event('runtime-close-all-return',{returnedNormally:raw.runtimeCloseAllReturned,allManagersClosed:raw.allManagersClosed,finalManagerStates:plain(raw.finalManagerStates)});
    if(OriginalManager&&originalGet)OriginalManager.get=originalGet;
    if(Pool&&originalPoolRun)Pool.prototype.run=originalPoolRun;
    Worker.prototype.postMessage=originalPost;
    DatabaseSync.prototype.exec=originalExec;DatabaseSync.prototype.prepare=originalPrepare;DatabaseSync.prototype.close=originalDbClose;
    for(const restore of restorations.reverse())restore();
    raw.counts={managers:owners.size,managerSearches:raw.originalSearchCalls.length,backgroundAdmissions:raw.backgroundCalls.length,
      syncs:raw.methodCalls.filter(call=>call.method==='sync').length,syncAdmitted:raw.methodCalls.filter(call=>call.method==='syncAdmitted').length,
      readPreparations:raw.methodCalls.filter(call=>call.method==='prepareKeywordSearch').length,poolRuns:raw.poolCalls.length,workerDispatches:raw.workerDispatches.length};
    persist();
  }
}
