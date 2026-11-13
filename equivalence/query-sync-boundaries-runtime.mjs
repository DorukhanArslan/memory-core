// Observe the complete independently frozen query-sync boundary family.
// No synchronization, retrieval, publication or timer algorithm is supplied here.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
import {Worker,MessagePort} from 'node:worker_threads';
import {pathToFileURL} from 'node:url';
import {isDeepStrictEqual,getCallSites} from 'node:util';
import {AsyncLocalStorage} from 'node:async_hooks';
import {deserialize} from 'node:v8';

const plain=value=>JSON.parse(JSON.stringify(value));
const sha=value=>crypto.createHash('sha256').update(value).digest('hex');
const errorScalars=error=>{const result={};for(const key of ['name','message','code','errcode','errstr','entered','committed']){
  let target=error,descriptor;while(target&&(typeof target==='object'||typeof target==='function')&&
    !(descriptor=Object.getOwnPropertyDescriptor(target,key)))target=Object.getPrototypeOf(target);
  result[key]=descriptor&&Object.hasOwn(descriptor,'value')?descriptor.value:null;
}return result;};
const sqlValue=value=>typeof value==='bigint'?{sqliteInt64:value.toString()}:
  value instanceof Uint8Array?{sqliteBlobHex:Buffer.from(value).toString('hex')}:value;

// Match the original agent-owned SQLite domain envelope. This only selects an
// observed publication; the caller still queues the original generation reader.
export function matchOriginalTypedPublicationReply(round,receipt,message,workerDispatches,publicationCalls){
  if(message?.ok!==true||!Number.isSafeInteger(message.id))return null;
  const returned=receipt.decodedSerialized?.value?.value;
  if(returned?.ok!==false||returned.error?.name!=='MemoryIndexRevisionConflictError')return null;
  const request=[...workerDispatches].reverse().find(row=>row.workerId===receipt.workerId&&row.message?.id===message.id);
  const domain=request?.decodedSerialized?.input?.value;
  if(domain?.type!=='database.domain.execute')return null;
  const command=domain.input?.command;
  if(command?.type!=='database.publish'||command.input?.expectedRevision!==round.expectedRevision)return null;
  // A shared broker's ambient async scope can belong to an older caller. Use
  // the exact original publisher entry and real command identity instead.
  const publication=publicationCalls.find(call=>call.method==='publishShadow'&&
    call.ownerId===round.actualOwnerId&&call.operationContext?.runSyncCallId===round.runSyncCallId&&
    call.args[0]?.sourcePath===command.input.sourcePath&&call.args[0]?.expectedRevision===round.expectedRevision&&
    call.enterSeq<request.enterSeq&&!call.returnSeq);
  return publication?{request,publication,command,domainId:domain.input.id}:null;
}

export async function runQuerySyncBoundariesRuntime(input,config){
  const base=config.stateDirectory,workspace=path.join(base,'workspace');
  const deferredErrorStacks=[];
  const errorValue=error=>{const value={...errorScalars(error),stack:null,stackSerialization:'original-teardown'};
    deferredErrorStacks.push({value,error});return value;};
  const raw={kind:'query-sync-boundaries',engine:'native',caseId:config.caseId,input:plain(input),
    pid:process.pid,ppid:process.ppid,fixtureBase:base,events:[],owners:{},ownerNames:{},
    facadeCalls:[],originalGetCalls:[],statusCalls:[],originalSearchCalls:[],methodCalls:[],
    backgroundCalls:[],poolCalls:[],workerDispatches:[],workerMessages:[],workerStates:[],leaseCalls:[],
    snapshots:[],sourceStages:{},toolCalls:{},fault:null,faultSyscalls:[],syncCalls:{},wholeJobs:[],
    publicationCalls:[],gates:[],executedSteps:[],originalErrors:[],revisionReads:[],revisionErrors:[]};
  let sequence=0,phase='setup',activeTool=null,requestLabel=null,dbPath;
  let OriginalManager,originalGet,closeAll,Pool,originalPoolRun;
  let foreground,primaryOwnerId,TypedRevisionConflict,acquireOriginalReadGeneration,revisionControl;
  let armedFault=null,gate=null;
  const operationScope=new AsyncLocalStorage(),pendingSyncs=new Map(),pendingSearches=new Map(),
    observedLedgers=new WeakSet(),observedDatabases=new WeakSet(),fixtureDatabases=new WeakSet(),openJobs=new Map(),backgroundPromises=new Map();
  const faultSpecification=input.publicationFault??input.fault;
  const owners=new Map(),refs=new WeakMap(),restorations=[],workers=new Map(),leaseDatabases=new Map();
  const errorWitnesses=new WeakMap();
  let refCount=0,workerCount=0;
  const ref=value=>{if(!value)return null;if(!refs.has(value))refs.set(value,`ref-${++refCount}`);return refs.get(value);};
  function originalErrorRef(error){
    if(!error||(typeof error!=='object'&&typeof error!=='function'))return null;
    if(!errorWitnesses.has(error)){
      const prototypeChainRefs=[];let prototype=Object.getPrototypeOf(error),constructor;
      while(prototype){prototypeChainRefs.push(ref(prototype));constructor??=Object.getOwnPropertyDescriptor(prototype,'constructor')?.value;prototype=Object.getPrototypeOf(prototype);}
      const row={errorRef:ref(error),constructorRef:ref(constructor),prototypeChainRefs,
        originalTypedClassRef:ref(TypedRevisionConflict),isTypedConflict:!!TypedRevisionConflict&&error instanceof TypedRevisionConflict,
        payload:errorValue(error)};errorWitnesses.set(error,row);raw.originalErrors.push(row);
    }return errorWitnesses.get(error).errorRef;
  }
  const context=()=>operationScope.getStore()??null;
  const stack=()=>getCallSites(64,{sourceMap:false}).map(frame=>`at ${frame.functionName||'<anonymous>'} (${frame.scriptName}:${frame.lineNumber}:${frame.columnNumber})`).join('\n');
  const event=(name,fields={})=>{const row={event:name,sequence:++sequence,phase,activeTool,operationContext:plain(context()),atNs:process.hrtime.bigint().toString(),...fields};raw.events.push(row);return row;};
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
    syncing:owner.syncing!==null,syncingRef:ref(owner.syncing),syncOutcomesRef:ref(owner.syncOutcomes),providerInitialized:owner.providerInitialized,
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
    if(!dbPath||!database.isOpen||fixtureDatabases.has(database))return null;
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
      originalCallerStack:stack()};raw.leaseCalls.push(call);
    try{const result=run();call.result=carrier(result);return result;}
    catch(error){call.error=errorValue(error);call.errorRef=originalErrorRef(error);
      if(gate&&location===gate.path&&!gate.released&&(/locked|SQLITE_BUSY|SQLITE_LOCKED/i.test(error.message)||[5,6].includes((error.errcode??0)&255))){
        gate.busyCallIds.push(call.id);gate.busy.resolve(call.id);}
      throw error;}
    finally{call.openAfter=database.isOpen;call.transactionAfter=database.isOpen?database.isTransaction:null;
      const returned=event('original-coordination-return',{method,databaseRef:ref(database),location});call.returnSeq=returned.sequence;call.finishedAtNs=returned.atNs;}
  }
  DatabaseSync.prototype.exec=function(...args){return leaseCall(this,'exec',args,()=>originalExec.apply(this,args));};
  DatabaseSync.prototype.prepare=function(...args){
    const location=coordination(this),statement=originalPrepare.apply(this,args);
    if(location){const database=this,originalStatementGet=statement.get;
      statement.get=function(...getArgs){return leaseCall(database,'statement.get',[args[0],...getArgs],()=>originalStatementGet.apply(this,getArgs));};}
    else if(dbPath&&this.isOpen&&originalLocation.call(this,'main')===dbPath&&
      args[0]==='SELECT revision FROM memory_index_state WHERE id = ?'){
      const database=this,originalStatementGet=statement.get;
      statement.get=function(...getArgs){
        const entered=event('original-live-revision-read-enter',{databaseRef:ref(database),sql:args[0],args:carrier(getArgs)});
        const value=originalStatementGet.apply(this,getArgs);
        const row={id:`revision-read-${raw.revisionReads.length+1}`,databaseRef:ref(database),sql:args[0],args:carrier(getArgs),
          result:carrier(value),operationContext:plain(context()),callerStack:stack(),enterSeq:entered.sequence,
          returnSeq:event('original-live-revision-read-return').sequence};raw.revisionReads.push(row);
        onOriginalRevisionRead(row,value);return value;
      };
    }
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
  for(const specification of [input.sourceMutation,...input.steps.filter(step=>step.operation==='mutate-source').map(step=>step.specification)]){
    for(const key of ['path','from','to'])if(typeof specification?.[key]==='string'){
      const relative=specification[key];
      if(path.isAbsolute(relative)||relative.split('/').includes('..'))throw Error('Invalid declared source mutation path');
      declaredPaths.add(relative);
    }
  }
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
    const ledger=owner.syncOutcomes;
    if(ledger&&!observedLedgers.has(ledger)){
      observedLedgers.add(ledger);const originalTrack=ledger.track,originalDescriptor=Object.getOwnPropertyDescriptor(ledger,'track');
      ledger.track=function(...args){
        const entered=event('original-sync-ledger-enter',{ownerId,active:args[1]===true});
        const job={id:`whole-job-${raw.wholeJobs.length+1}`,ownerId,ledgerRef:ref(this),originalOperationRef:ref(args[0]),
          active:args[1]===true,args:carrier(args),operationContext:plain(context()),enterSeq:entered.sequence,
          originalCallerStack:stack(),stateBefore:state(owner)};
        raw.wholeJobs.push(job);
        if(job.active){if(!openJobs.has(ownerId))openJobs.set(ownerId,new Set());openJobs.get(ownerId).add(job.id);}
        try{const returned=originalTrack.apply(this,args);job.returnedPromiseRef=ref(returned);
          job.originalReturnPromisePreserved=true;
          returned.then(value=>{job.result=carrier(value);job.state='fulfilled';job.isTypedConflict=false;job.stateAfter=state(owner);job.returnSeq=event('original-sync-ledger-settled',{ownerId,jobId:job.id,state:job.state}).sequence;openJobs.get(ownerId)?.delete(job.id);},
            error=>{job.error=errorValue(error);job.errorRef=originalErrorRef(error);job.state='rejected';job.isTypedConflict=!!TypedRevisionConflict&&error instanceof TypedRevisionConflict;
              job.stateAfter=state(owner);job.returnSeq=event('original-sync-ledger-settled',{ownerId,jobId:job.id,state:job.state}).sequence;openJobs.get(ownerId)?.delete(job.id);});
          return returned;
        }catch(error){job.error=errorValue(error);job.errorRef=originalErrorRef(error);job.state='rejected';
          job.isTypedConflict=!!TypedRevisionConflict&&error instanceof TypedRevisionConflict;
          job.returnSeq=event('original-sync-ledger-threw',{ownerId,jobId:job.id}).sequence;openJobs.get(ownerId)?.delete(job.id);throw error;}
      };restorations.push(()=>{if(originalDescriptor)Object.defineProperty(ledger,'track',originalDescriptor);else delete ledger.track;});
    }
    const database=owner.publishedDatabase;
    if(database&&!observedDatabases.has(database)){
      observedDatabases.add(database);
      for(const method of ['publishShadow','replaceSource','deleteSource']){
        const original=database[method],originalDescriptor=Object.getOwnPropertyDescriptor(database,method);
        if(typeof original!=='function')throw Error(`Missing original publication ${method}`);
        database[method]=function(...args){
          const call={id:`publication-${raw.publicationCalls.length+1}`,method,ownerId,databaseRef:ref(this),args:carrier(args),
            operationContext:plain(context()),enterSeq:event('original-publication-enter',{ownerId,method}).sequence};raw.publicationCalls.push(call);
          const candidates=[...(openJobs.get(ownerId)??[])];
          call.wholeJobId=context()?.kind!=='revision-rival'&&candidates.length===1?candidates[0]:null;
          try{const returned=original.apply(this,args);call.returnedPromiseRef=ref(returned);
            returned.then(value=>{call.result=carrier(value);call.returnSeq=event('original-publication-settled',{ownerId,method,state:'fulfilled'}).sequence;
              const committed=method==='publishShadow'||(method==='replaceSource'&&value&&value.databaseRevision>value.beforeRevision)||
                (method==='deleteSource'&&value===true);
              if(call.wholeJobId&&committed){const job=raw.wholeJobs.find(row=>row.id===call.wholeJobId);job.committedGeneration=true;
                (job.publicationCommitCallIds??=[]).push(call.id);}
            },
              error=>{call.error=errorValue(error);call.errorRef=originalErrorRef(error);call.returnSeq=event('original-publication-settled',{ownerId,method,state:'rejected'}).sequence;});return returned;
          }catch(error){call.error=errorValue(error);call.errorRef=originalErrorRef(error);call.returnSeq=event('original-publication-threw',{ownerId,method}).sequence;throw error;}
        };restorations.push(()=>{if(originalDescriptor)Object.defineProperty(database,method,originalDescriptor);else delete database[method];});
      }
    }
    for(const name of ['status','search','sync','syncAdmitted','syncPublishedIndexInBackground','runSync','syncMemoryFiles',
      'markMemoryWatchDirty','prepareKeywordSearch','close','awaitManagerIdle','takeReindexRetryStateForMaintenance','adoptReindexRetryState']){
      const original=owner[name],originalDescriptor=Object.getOwnPropertyDescriptor(owner,name);
      if(typeof original!=='function')throw Error(`Missing original manager method ${name}`);
      owner[name]=function(...args){
        const entered=event(`original-${name}-enter`,{ownerId,requestLabel,receiverIsExactObservedOwner:this===owner});
        const call={id:`method-${raw.methodCalls.length+1}`,method:name,ownerId,phase,activeTool,requestLabel,
          args:carrier(args),operationContext:plain(context()),enterSeq:entered.sequence,startedAtNs:entered.atNs,receiverIsExactObservedOwner:this===owner,stateBefore:state(owner)};
        raw.methodCalls.push(call);
        if(gate&&!gate.released&&owner===foreground){
          if(name==='syncAdmitted'&&owner.syncing&&ref(owner.syncing)===gate.originalSyncSlotRef){
            if(args[0]?.reason==='search-bootstrap')gate.queryJoin.resolve(call.id);
            if(args[0]?.reason==='cli')gate.forceJoin.resolve(call.id);
          }
        }
        if(name==='status')raw.statusCalls.push(call);
        if(name==='search'){call.query=args[0];call.options=carrier(args[1]);call.optionKeys=Reflect.ownKeys(args[1]??{}).map(String);raw.originalSearchCalls.push(call);}
        if(name==='syncPublishedIndexInBackground')raw.backgroundCalls.push(call);
        const finish=(value,error)=>{
          if(error){call.error=errorValue(error);call.errorRef=originalErrorRef(error);}else {call.result=carrier(value);call.nativeSerializedJSON=JSON.stringify(value);}
          call.stateAfter=state(owner);
          const returned=event(`original-${name}-return`,{ownerId,requestLabel:call.requestLabel,error:!!error,receiverIsExactObservedOwner:this===owner});
          call.returnSeq=returned.sequence;call.finishedAtNs=returned.atNs;
        };
        try{
          const returned=name==='runSync'?operationScope.run({...context(),runSyncCallId:call.id,runSyncOwnerId:ownerId},()=>original.apply(this,args)):original.apply(this,args);
          if(name==='syncPublishedIndexInBackground')backgroundPromises.set(call.id,returned);
          call.immediateReturnState=state(owner);
          if(gate&&!gate.released&&owner===foreground&&name==='syncAdmitted'&&!call.stateBefore.syncing&&owner.syncing)
            gate.originalSyncSlotRef??=ref(owner.syncing);
          if(returned&&typeof returned.then==='function'){
            call.returnedPromiseRef=ref(returned);
            returned.then(value=>finish(value),error=>finish(undefined,error));
          }else finish(returned);
          return returned;
        }catch(error){finish(undefined,error);throw error;}
      };
      restorations.push(()=>{if(originalDescriptor)Object.defineProperty(owner,name,originalDescriptor);else delete owner[name];});
    }
    return owner;
  }
  const originalPost=Worker.prototype.postMessage;
  Worker.prototype.postMessage=function(...args){
    let workerId=workers.get(this);
    if(!workerId){workerId=`worker-${++workerCount}`;workers.set(this,workerId);
      raw.workerStates.push({workerId,threadId:this.threadId,firstObservedSeq:sequence});
      this.on('message',message=>{const row=event('actual-worker-message',{workerId,threadId:this.threadId});
        const receipt={workerId,threadId:this.threadId,sequence:row.sequence,message:carrier(message),decodedSerialized:decodedSerialized(message,'reply')};
        raw.workerMessages.push(receipt);onOriginalTypedWorkerReply(receipt,message);});
      this.on('exit',exitCode=>{const row=event('actual-worker-exit',{workerId,exitCode});raw.workerStates.find(item=>item.workerId===workerId).exit={sequence:row.sequence,exitCode};});
    }
    const entered=event('actual-worker-dispatch-enter',{workerId,threadId:this.threadId});
    const call={workerId,threadId:this.threadId,phase,activeTool,enterSeq:entered.sequence,startedAtNs:entered.atNs,
      operationContext:plain(context()),message:carrier(args[0]),decodedSerialized:decodedSerialized(args[0],'request'),transferList:carrier(args[1])};raw.workerDispatches.push(call);
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
    if(armedFault||!faultSpecification||faultSpecification.kind!=='actual-owned-publication-sidecar-dangling-symlink')throw Error('Invalid query-sync boundaries refusal schedule');
    const entered=event('fault-arm-enter',{ownerId:ref(foreground)});
    const sidecar=`${dbPath}.reindex-lock.sqlite`,target=path.resolve(base,faultSpecification.target),
      backup=`${sidecar}.query-sync-boundaries-owned-backup`;
    if(!path.isAbsolute(dbPath)||!dbPath.startsWith(base+path.sep)||
      !target.startsWith(base+path.sep)||target===sidecar||
      fs.realpathSync(path.dirname(sidecar))!==path.dirname(sidecar))throw Error('Fault escaped the actual acquired index owner');
    const receipt={kind:faultSpecification.kind,ownerId:ref(foreground),dbPath,sidecar,target,backup,
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
    if(!armedFault)throw Error('No owned query-sync boundaries fault to remove');
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
  function deferred(){let resolve;const promise=new Promise(done=>{resolve=done;});return{promise,resolve};}
  async function bounded(promise,label){
    let watchdog;try{return await Promise.race([promise,new Promise((_,reject)=>{
      watchdog=setTimeout(()=>reject(Error(`Bounded original lifecycle observation timed out: ${label}`)),5000);
    })]);}finally{clearTimeout(watchdog);}
  }
  function gateSql(method,args,run){
    const entered=event('fixture-gate-sql-enter',{method,args:carrier(args)});
    const call={method,args:carrier(args),enterSeq:entered.sequence};gate.sql.push(call);
    try{const value=run();call.result=carrier(value);return value;}
    catch(error){call.error=errorValue(error);throw error;}
    finally{call.returnSeq=event('fixture-gate-sql-return',{method}).sequence;}
  }
  function armGate(){
    if(gate&&!gate.released)throw Error('An owned query-sync gate is already held');
    const target=`${dbPath}.reindex-lock.sqlite`;
    if(!foreground||!path.isAbsolute(dbPath)||!target.startsWith(base+path.sep))throw Error('Gate requires the acquired owned index');
    gate={id:`gate-${raw.gates.length+1}`,path:target,ownerId:ref(foreground),initial:faultPath(target),sql:[],
      busyCallIds:[],busy:deferred(),queryJoin:deferred(),forceJoin:deferred(),released:false};
    if(!['missing','file'].includes(gate.initial.kind))throw Error('Gate sidecar is not an independent owned file');
    for(const name of ['busy','queryJoin','forceJoin'])Object.defineProperty(gate,name,{value:gate[name],enumerable:false});
    raw.gates.push(gate);gate.armEnterSeq=event('fixture-gate-arm-enter',{path:target}).sequence;
    Object.defineProperty(gate,'database',{value:new DatabaseSync(target),enumerable:false});fixtureDatabases.add(gate.database);
    gate.databaseRef=ref(gate.database);
    gateSql('exec',['PRAGMA busy_timeout = 0'],()=>gate.database.exec('PRAGMA busy_timeout = 0'));
    gateSql('exec',['PRAGMA journal_mode = DELETE'],()=>gate.database.exec('PRAGMA journal_mode = DELETE'));
    gateSql('exec',['BEGIN EXCLUSIVE'],()=>gate.database.exec('BEGIN EXCLUSIVE'));
    gateSql('get',['SELECT name FROM sqlite_schema LIMIT 1'],()=>gate.database.prepare('SELECT name FROM sqlite_schema LIMIT 1').get());
    gate.held=faultPath(target);gate.transactionActiveAtArm=gate.database.isTransaction;
    gate.armReturnSeq=event('fixture-gate-arm-return',{path:target,transactionActive:gate.database.isTransaction}).sequence;
  }
  function releaseGate({emergency=false}={}){
    if(!gate||gate.released)return;
    gate.releaseEnterSeq=event('fixture-gate-release-enter',{gateId:gate.id,emergency}).sequence;
    try{if(gate.database?.isOpen&&gate.database.isTransaction)gateSql('exec',['ROLLBACK'],()=>gate.database.exec('ROLLBACK'));}
    finally{if(gate.database?.isOpen)gateSql('close',[],()=>gate.database.close());gate.released=true;
      gate.releaseReturnSeq=event('fixture-gate-release-return',{gateId:gate.id,emergency}).sequence;}
  }
  function startSync(label,params){
    if(pendingSyncs.has(label)||raw.syncCalls[label])throw Error('Duplicate original sync request label');
    const call={label,ownerId:ref(foreground),params:carrier(params),settled:false,
      enterSeq:event('actual-sync-request-enter',{label,ownerId:ref(foreground),params:carrier(params)}).sequence};raw.syncCalls[label]=call;
    const returned=operationScope.run({kind:'sync',label},()=>foreground.sync(params));call.returnedPromiseRef=ref(returned);
    const observation=returned.then(value=>{call.settled=true;call.state='fulfilled';call.result=carrier(value);
      call.returnSeq=event('actual-sync-request-return',{label,state:call.state}).sequence;return{state:'fulfilled'};},
      error=>{call.settled=true;call.state='rejected';call.error=errorValue(error);call.errorRef=originalErrorRef(error);call.isTypedConflict=!!TypedRevisionConflict&&error instanceof TypedRevisionConflict;
        call.returnSeq=event('actual-sync-request-return',{label,state:call.state}).sequence;return{state:'rejected'};});
    pendingSyncs.set(label,{original:returned,observation,call});return call;
  }
  async function awaitSync(label){
    const pending=pendingSyncs.get(label);if(!pending)throw Error('Missing original sync request');
    await pending.observation;return{status:pending.call.state,isTypedConflict:pending.call.isTypedConflict??false};
  }
  function startSearch(tool,label,args){
    if(pendingSearches.has(label))throw Error('Duplicate public query request label');
    const promise=operationScope.run({kind:'search',label},()=>toolCall(tool,label,args));
    const pending={original:promise,settled:false};
    pending.observation=promise.then(value=>{pending.settled=true;pending.result=value;return value;},error=>{
      pending.settled=true;pending.error=error;throw error;});
    // A fixture-owned observer must not introduce an unhandled rejection while
    // the original ordered schedule is still holding a real kernel lease.
    pending.observation.catch(()=>undefined);pendingSearches.set(label,pending);return pending;
  }
  function mutateSource(spec){
    if(!spec||!['replace','create','delete','touch-same-bytes'].includes(spec.kind))throw Error('Unsupported frozen source mutation');
    const filename=path.resolve(workspace,spec.path);if(!filename.startsWith(workspace+path.sep)||path.isAbsolute(spec.path))throw Error('Source mutation escaped owned workspace');
    declaredPaths.add(spec.path);const entered=event('actual-source-mutation-enter',{specification:plain(spec)});
    if(spec.kind==='delete')fs.unlinkSync(filename);
    else if(spec.kind!=='touch-same-bytes'){fs.mkdirSync(path.dirname(filename),{recursive:true});fs.writeFileSync(filename,spec.text,{flag:spec.kind==='create'?'wx':'w'});}
    if(spec.kind!=='delete')fs.utimesSync(filename,spec.mtimeMs/1000,spec.mtimeMs/1000);
    const receipt={specification:plain(spec),enterSeq:entered.sequence,source:sourceStage(`mutation-${raw.executedSteps.length}`)};
    if(spec.notify!==false){foreground.markMemoryWatchDirty();receipt.notificationReturnSeq=event('declared-dirty-notification-return',{ownerId:ref(foreground)}).sequence;}
    receipt.returnSeq=event('actual-source-mutation-return').sequence;(raw.sourceMutations??=[]).push(receipt);
  }
  function setNewerEmptyFormat(){
    const specification=input.newerFormat;if(!specification||specification.field!=='chunkingVersion')throw Error('Unsupported original metadata fixture');
    const before=physical('before-newer-empty-format'),db=new DatabaseSync(dbPath);
    const row={specification:plain(specification),enterSeq:event('owned-newer-format-fixture-enter').sequence,
      dbPath,beforeSnapshotLabel:before.label};raw.newerFormatFixture=row;
    try{
      db.exec('BEGIN IMMEDIATE');
      row.actualChunkCount=db.prepare('SELECT COUNT(*) AS count FROM memory_index_chunks').get().count;
      row.actualSourceCount=db.prepare('SELECT COUNT(*) AS count FROM memory_index_sources').get().count;
      if(row.actualChunkCount!==0||row.actualSourceCount!==0)throw Error('Newer-empty fixture requires genuinely empty original SQL');
      const prior=db.prepare("SELECT value FROM memory_index_meta WHERE key='memory_index_meta_v1'").get();
      if(typeof prior?.value!=='string')throw Error('Actual public empty seed did not produce original metadata');
      row.beforeSerialized=prior.value;row.beforeMetadata=JSON.parse(prior.value);
      row.afterMetadata={...row.beforeMetadata,[specification.field]:specification.version};row.afterSerialized=JSON.stringify(row.afterMetadata);
      row.sql='UPDATE memory_index_meta SET value=? WHERE key=? AND value=?';
      row.params=[row.afterSerialized,'memory_index_meta_v1',row.beforeSerialized];
      row.sqliteResult=carrier(db.prepare(row.sql).run(...row.params));
      db.exec('COMMIT');row.committed=true;
    }catch(error){row.error=errorValue(error);if(db.isTransaction)db.exec('ROLLBACK');throw error;}
    finally{db.close();row.returnSeq=event('owned-newer-format-fixture-return').sequence;}
    physical('after-newer-empty-format');
  }
  function revisionFailure(round,error){
    round.error=errorValue(error);round.state='fixture-error';raw.revisionErrors.push({round:round.index,error:errorValue(error)});
  }
  async function acquireRevisionRound(index,trigger){
    const round=revisionControl.rounds[index];if(!round||round.acquireEnterSeq)throw Error('Duplicate or undeclared real revision reader');
    revisionControl.current=round;round.trigger=carrier(trigger);round.state='reader-pending';
    round.acquireEnterSeq=event('fixture-original-reader-enter',{round:index,role:round.role}).sequence;
    const promise=operationScope.run({kind:'revision-reader',round:index},()=>acquireOriginalReadGeneration(dbPath));
    round.acquirePromiseRef=ref(promise);
    const release=await promise;Object.defineProperty(round,'release',{value:release,enumerable:false});
    round.releaseFunctionRef=ref(release);round.state='reader-held';round.readerHeld=true;
    round.acquireReturnSeq=event('fixture-original-reader-return',{round:index,role:round.role}).sequence;return round;
  }
  async function releaseRevisionRound(round,reason){
    if(!round?.release||round.released)return;
    round.releaseEnterSeq=event('fixture-original-reader-release-enter',{round:round.index,reason}).sequence;
    try{await round.release();round.released=true;round.readerHeld=false;}
    finally{round.releaseReturnSeq=event('fixture-original-reader-release-return',{round:round.index,reason}).sequence;}
  }
  async function armRevisionConflict(role){
    const specification=input.revisionConflict;
    if(!specification||specification.kind!=='genuine-competing-original-index-publication')throw Error('Missing independently declared revision recipe');
    if(!revisionControl){revisionControl={specification:plain(specification),current:null,rounds:specification.paths.map((markerPath,index)=>({index,markerPath,
      role:index===0?'preparation':'maintenance',state:'not-reached',reached:false}))};
      raw.revisionControl={specification:plain(specification),rounds:revisionControl.rounds};}
    if(!['preparation','maintenance'].includes(role))throw Error('Revision control requires its frozen role');
    await acquireRevisionRound(role==='preparation'?0:1,{kind:'declared-role-arm',role});
  }
  function onOriginalRevisionRead(receipt,value){
    const round=revisionControl?.current,scope=receipt.operationContext;
    if(!round||round.reached||!round.readerHeld||!scope?.runSyncCallId||!Number.isSafeInteger(value?.revision))return;
    const owner=raw.owners[scope.runSyncOwnerId],spec=revisionControl.specification;
    const selected=round.role==='preparation'
      ?scope.kind==='sync'&&scope.label===spec.preparationSyncLabel&&scope.runSyncOwnerId===primaryOwnerId
      :scope.kind==='search'&&scope.label===spec.maintenanceQueryLabel&&owner?.purpose==='maintenance'&&owner.maintenanceSourceOwnerId===primaryOwnerId;
    if(!selected)return;
    round.reached=true;round.state='actual-shadow-revision-captured';round.revisionReadId=receipt.id;
    round.runSyncCallId=scope.runSyncCallId;round.actualOwnerId=scope.runSyncOwnerId;round.expectedRevision=value.revision;
    round.reachedSeq=event('fixture-revision-round-reached',{round:round.index,revisionReadId:receipt.id}).sequence;
    const task=performOriginalRival(round).catch(async error=>{revisionFailure(round,error);
      try{await releaseRevisionRound(round,'rival-fixture-error');}catch(releaseError){revisionFailure(round,releaseError);}});
    Object.defineProperty(round,'rivalTask',{value:task,enumerable:false});
  }
  async function performOriginalRival(round){
    const before=physical(`rival-before:${round.index}`),sources=before.tables?.memory_index_sources??[];
    const actual=sources.find(row=>row.path===round.markerPath&&row.source==='memory');
    if(typeof actual?.hash!=='string')throw Error('Reached original revision attempt has no actual indexed rival marker');
    const owner=foreground,database=owner.publishedDatabase;
    const args={path:round.markerPath,source:'memory',expectedHash:actual.hash};round.rivalArguments=carrier(args);
    round.rivalOwnerId=ref(owner);round.rivalDatabaseRef=ref(database);round.beforeSnapshot=before.label;
    round.rivalEnterSeq=event('fixture-original-rival-delete-enter',{round:round.index,args:carrier(args)}).sequence;
    try{
      const returned=operationScope.run({kind:'revision-rival',round:round.index},()=>database.deleteSource(args,()=>{
        if(owner.closed||owner.publishedDatabase!==database||!database.db.isOpen)throw Error('Original rival lost its actual live owner');
      }));round.rivalPromiseRef=ref(returned);round.rivalResult=carrier(await returned);
      const after=physical(`rival-after:${round.index}`);round.afterSnapshot=after.label;
      round.actualRevisionAfter=after.tables?.memory_index_state?.find(row=>row.id===1)?.revision;
      if(round.rivalResult!==true||!(round.actualRevisionAfter>round.expectedRevision))throw Error('Original rival did not commit a newer live revision');
      round.state='rival-committed';round.rivalReturnSeq=event('fixture-original-rival-delete-return',{round:round.index}).sequence;
    }finally{await releaseRevisionRound(round,'after-original-rival');}
  }
  function onOriginalTypedWorkerReply(receipt,message){
    const round=revisionControl?.current,next=round?revisionControl.rounds[round.index+1]:null;
    if(!round||round.role!=='maintenance'||!round.reached||!round.released||!next||next.acquireEnterSeq)return;
    const matched=matchOriginalTypedPublicationReply(round,receipt,message,raw.workerDispatches,raw.publicationCalls);
    if(!matched)return;
    const{request,publication,command,domainId}=matched;
    round.typedPublicationDomainId=domainId;
    round.typedPublicationCallId=publication.id;round.typedPublicationSourcePath=command.input.sourcePath;
    round.typedWorkerReceiptSeq=receipt.sequence;round.typedWorkerRequestEnterSeq=request.enterSeq;
    // This invocation enqueues the real next reader synchronously inside the
    // genuine Worker message callback, before original Promise continuations.
    const queued=acquireRevisionRound(next.index,{kind:'actual-typed-worker-reply',round:round.index,sequence:receipt.sequence});
    Object.defineProperty(next,'queuedTask',{value:queued.catch(error=>revisionFailure(next,error)),enumerable:false});
  }
  async function releaseUnusedRevisionReaders(reason){
    if(!revisionControl)return;
    for(const round of revisionControl.rounds){
      if(round.queuedTask)await round.queuedTask;
      if(!round.reached&&round.readerHeld){round.state='not-reached';await releaseRevisionRound(round,reason);}
    }
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
    ({t:TypedRevisionConflict}=await imp('dist/manager-db-kernel-DyJADqYu.mjs'));
    raw.typedConflictClass={classRef:ref(TypedRevisionConflict),prototypeRef:ref(TypedRevisionConflict.prototype),
      module:'dist/manager-db-kernel-DyJADqYu.mjs',export:'t',sourceSha256:'4973db0580dc6dd7ac032a983efffa79ccb14fc4206f046b94c4250c7b5597ca',
      compiledSha256:'b2af8c64d1450a503cecb97a96d37b3597340c6a68cc7c0231f98befc964bd99'};
    ({p:acquireOriginalReadGeneration}=await imp('dist/manager-vector-warning-DcyxxT5h.mjs'));
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
      call.returnedPromiseRef=ref(result);call.originalReturnPromisePreserved=true;
      result.then(owner=>{
        try{
          observe(owner);call.ownerId=ref(owner);call.actualPurpose=owner?.purpose??null;
          if(owner&&params.maintenanceSource)raw.owners[ref(owner)].maintenanceSourceOwnerId=ref(params.maintenanceSource);
          call.returnedIsExactSampledOwner=sampled?owner===sampled:null;
          const returned=event('original-get-return',{ownerId:ref(owner)});call.returnSeq=returned.sequence;call.finishedAtNs=returned.atNs;
        }catch(error){(raw.observationErrors??=[]).push({stage:'original-get-observer',error:errorValue(error)});}
      },error=>{call.error=errorValue(error);call.errorRef=originalErrorRef(error);call.returnSeq=event('original-get-return',{error:true}).sequence;});
      return result;
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
    const tool=makeTool(),searches={},syncs={},dispatches={};
    const acquireForeground=async label=>{
      phase='owner-acquisition';physical(`before-owner-open:${label}`);
      const previous=foreground;foreground=await acquire(label);
      primaryOwnerId??=ref(foreground);
      const initialStatus=foreground.status();
      if(initialStatus.dbPath!==dbPath||foreground.purpose!=='default')throw Error('Unexpected original default database owner');
      raw.initialStatus??=carrier(initialStatus);raw.foregroundOwnerId=ref(foreground);
      if(previous&&previous===foreground)throw Error('Explicit reopen reused the closed owner');
      physical(`after-owner-open:${label}`);
    };
    if(!input.steps.some(step=>step.operation==='acquire-original-default-owner'))await acquireForeground('foreground');
    for(let index=0;index<input.steps.length;index++){
      const step=input.steps[index],operation=step.operation;
      phase=`step-${index}:${operation}`;
      const receipt={index,step:plain(step),enterSeq:event('declared-step-enter',{index,operation,label:step.label??null}).sequence};raw.executedSteps.push(receipt);
      if(operation==='prepare-real-source-files')receipt.preparedSourceStage='initial';
      else if(operation==='acquire-original-default-owner')await acquireForeground(step.label??'foreground');
      else if(operation==='public-memory-search'||operation==='start-public-memory-search'){
        const pending=startSearch(tool,step.label,step.args??input.queries[step.label]);
        if(operation==='public-memory-search')searches[step.label]=await pending.observation;
      }else if(operation==='await-public-memory-search'){
        const pending=pendingSearches.get(step.label);if(!pending)throw Error('Missing original public query');searches[step.label]=await pending.observation;
      }else if(operation==='original-sync'||operation==='start-sync'){
        startSync(step.label,step.params??{reason:'cli',force:true});
        if(operation==='original-sync')syncs[step.label]=await awaitSync(step.label);
      }else if(operation==='await-sync')syncs[step.label]=await awaitSync(step.label);
      else if(operation==='arm-sql-gate')armGate();
      else if(operation==='await-real-publication-pending'){
        if(!gate)throw Error('No real SQL gate');receipt.busyCallId=await bounded(gate.busy.promise,'first actual SQL busy');
        gate.pendingSnapshot=physical(`gate-pending:${gate.id}`);receipt.ownerState=state(foreground);
      }else if(operation==='await-joined-requests'){
        if(!gate)throw Error('No real SQL gate');
        receipt.joinCallIds=await bounded(Promise.all([gate.forceJoin.promise,gate.queryJoin.promise]),'actual joined force and query');
        receipt.syncStates=[...pendingSyncs.values()].map(value=>({label:value.call.label,settled:value.call.settled}));
        receipt.searchStates=[...pendingSearches].map(([label,value])=>({label,settled:value.settled}));
        receipt.ownerState=state(foreground);gate.joinedRequests=plain(receipt);
        if(receipt.syncStates.some(value=>value.settled)||receipt.searchStates.some(value=>value.settled))throw Error('Real joined requests settled before gate release');
      }else if(operation==='release-sql-gate')releaseGate();
      else if(operation==='arm-publication-fault')armFault();
      else if(operation==='remove-publication-fault')removeFault();
      else if(operation==='mutate-source')mutateSource(step.specification??input.sourceMutation);
      else if(operation==='set-newer-empty-format')setNewerEmptyFormat();
      else if(operation==='arm-revision-conflict')await armRevisionConflict(step.role);
      else if(operation==='await-observed-background-settlement'){
        const calls=raw.backgroundCalls.filter(call=>call.operationContext?.kind==='search'&&call.operationContext.label===step.searchLabel);
        receipt.backgroundCallIds=calls.map(call=>call.id);receipt.admissionState=calls.length?'admitted':'not-admitted';
        if(calls.length)receipt.actualSettlements=carrier(await Promise.allSettled(calls.map(call=>backgroundPromises.get(call.id))));
      }
      else if(operation==='original-owner-close'){
        await foreground.close();await releaseUnusedRevisionReaders('after-original-owner-close');physical(`after-explicit-close:${index}`);
      }
      else if(operation==='reopen-owner')await acquireForeground(step.label??`reopened-${index}`);
      else if(operation==='read-physical-sql-and-source-state'){
        physical(step.label??`declared-sql-${index}`);sources[step.label??`declared-source-${index}`]=sourceStage(step.label??`declared-source-${index}`);
      }else throw Error(`Unsupported independently frozen query-sync operation: ${operation}`);
      receipt.returnSeq=event('declared-step-return',{index,operation,label:step.label??null}).sequence;
    }
    if(gate&&!gate.released)throw Error('Frozen schedule left its real SQL gate held');
    if(armedFault)throw Error('Frozen schedule left its refusal armed');
    if(raw.revisionErrors.length)throw Error('A reached real revision control failed; original diagnostics retained');
    for(const[label,pending]of pendingSearches){if(!pending.settled)throw Error('Unjoined prescribed public query');searches[label]=pending.result;}
    for(const[label,pending]of pendingSyncs){if(!pending.call.settled)throw Error('Unjoined prescribed original sync');syncs[label]={status:pending.call.state,isTypedConflict:pending.call.isTypedConflict??false};}
    phase='owner-close';if(foreground&&!foreground.closed)await foreground.close();
    physical('after-close');sourceStage('after-runtime-close');
    const firstClose=raw.methodCalls.find(row=>row.ownerId===primaryOwnerId&&row.method==='close'&&row.returnSeq);
    if(!firstClose)throw Error('Primary foreground lifetime has no actual close settlement');
    const ownerIds=new Set([primaryOwnerId]);
    for(let changed=true;changed;){changed=false;for(const[ownerId,owner]of Object.entries(raw.owners))
      if(ownerIds.has(owner.maintenanceSourceOwnerId)&&!ownerIds.has(ownerId)){ownerIds.add(ownerId);changed=true;}}
    const inWindow=row=>row.enterSeq<firstClose.returnSeq;
    const methods=raw.methodCalls.filter(row=>ownerIds.has(row.ownerId)&&inWindow(row));
    const jobs=raw.wholeJobs.filter(row=>row.active&&ownerIds.has(row.ownerId)&&inWindow(row));
    if(jobs.some(row=>!row.returnSeq||!row.state))throw Error('Primary admitted producer lacks original settlement');
    Object.assign(dispatches,{searchRequests:Object.values(raw.toolCalls).filter(inWindow).length,
      managerSearches:methods.filter(row=>row.method==='search').length,
      syncRequests:methods.filter(row=>row.method==='syncAdmitted').length,
      bootstrapRequests:methods.filter(row=>row.method==='syncAdmitted'&&row.args[0]?.reason==='search-bootstrap').length,
      producerAttempts:jobs.length,committedGenerations:jobs.filter(row=>row.committedGeneration===true).length});
    const producerOutcomes=jobs.map(row=>({status:row.state,isTypedConflict:row.isTypedConflict??false}));
    raw.comparableWindow={primaryOwnerId,ownerIds:[...ownerIds],endSeq:firstClose.returnSeq,closeCallId:firstClose.id,wholeJobIds:jobs.map(row=>row.id)};
    raw.result={provider:'none',searches,syncs,dispatches,producerOutcomes,sources};
    raw.completed=true;return raw.result;
  }catch(error){raw.error=errorValue(error);throw error;}
  finally{
    phase='teardown';
    if(revisionControl){
      for(const round of revisionControl.rounds){
        try{if(round.queuedTask)await round.queuedTask;if(round.readerHeld)await releaseRevisionRound(round,'emergency-teardown');}
        catch(error){raw.revisionErrors.push({round:round.index,error:errorValue(error)});}
      }
    }
    if(gate&&!gate.released){try{releaseGate({emergency:true});}catch(error){raw.gateCleanupError=errorValue(error);}}
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
    for(const {value,error}of deferredErrorStacks){try{value.stack=error?.stack??null;}catch(formatError){
      (raw.observationErrors??=[]).push({stage:'teardown-stack-serialization',message:String(formatError)});}}
    persist();
  }
}
