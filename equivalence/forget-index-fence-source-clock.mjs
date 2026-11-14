// Functional fixture input, separate from product clocks and original IO.
// Every hook calls the same original function on the same FileHandle object.
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {serialize} from 'node:v8';
import {AsyncLocalStorage} from 'node:async_hooks';
import {threadId,getEnvironmentData,setEnvironmentData} from 'node:worker_threads';
import {deflateRawSync} from 'node:zlib';

const digest=bytes=>createHash('sha256').update(bytes).digest('hex');
const now=()=>process.hrtime.bigint().toString();
const errorValue=error=>({name:error.name,message:error.message,...(error.code===undefined?{}:{code:error.code}),stack:error.stack});
const valueRecord=value=>{try{return{v8Hex:serialize(value).toString('hex')};}catch(error){return{serializationError:errorValue(error)};}};
const statValue=stat=>Object.fromEntries(Object.getOwnPropertyNames(stat).map(key=>[key,typeof stat[key]==='bigint'?stat[key].toString():stat[key]]));
const same=(left,right)=>left.dev===right.dev&&left.ino===right.ino&&left.nlink===1n&&right.nlink===1n;
const stable=(left,right)=>same(left,right)&&left.size===right.size&&left.mtimeNs===right.mtimeNs&&left.ctimeNs===right.ctimeNs;
const PASSIVE_EVENT_CODEC='deflate-raw-native-event-v1',PASSIVE_EVENT_RAW_LIMIT=64*1024*1024;

export function encodePassiveEvent(row){const raw=Buffer.from(JSON.stringify(row),'utf8');
 if(raw.length>PASSIVE_EVENT_RAW_LIMIT)throw Error('Original passive event exceeds its decoded record capacity');
 return Buffer.from(JSON.stringify({codec:PASSIVE_EVENT_CODEC,rawBytes:raw.length,rawSha256:digest(raw),
  dataBase64:deflateRawSync(raw).toString('base64')})+'\n','utf8');
}

// One actual Node thread owns each append channel. Shared prefixes survive a
// Worker.terminate and are persisted only at the caller's explicit checkpoints.
export function openThreadEventStore({directory,token,environmentKey='memory.eq.fif.shared-passive-events',slotCount=128,
 initialBytes=64*1024,maxBytes=64*1024*1024}){
 const protocol='shared-original-event-jsonl-v2',codec=PASSIVE_EVENT_CODEC;let pool=getEnvironmentData(environmentKey);
 if(pool===undefined){pool={protocol,codec,token,pid:process.pid,slotCount,initialBytes,maxBytes,
   slots:Array.from({length:slotCount},()=>({data:new SharedArrayBuffer(initialBytes,{maxByteLength:maxBytes}),state:new SharedArrayBuffer(5*4)}))};
  setEnvironmentData(environmentKey,pool);
 }
 if(pool.protocol!==protocol||pool.codec!==codec||pool.token!==token||pool.pid!==process.pid||pool.slotCount!==slotCount||
  pool.initialBytes!==initialBytes||pool.maxBytes!==maxBytes||pool.slots.length!==slotCount)throw Error('Unqualified shared passive event owner');
 if(threadId>=slotCount)throw Error('Actual worker thread exceeds passive channel capacity');
 const channel=pool.slots[threadId],state=new Int32Array(channel.state);
 if(Atomics.load(state,3)!==0)throw Error('Passive channel already has a thread writer');
 Atomics.store(state,3,threadId+1);
 function block(code,requested){Atomics.store(state,2,Math.min(requested,0x7fffffff));Atomics.store(state,1,code);return false;}
 function append(row){if(Atomics.load(state,1))return false;try{const bytes=encodePassiveEvent(row),length=Atomics.load(state,0),required=length+bytes.length;
   if(required>maxBytes)return block(1,required);
   if(required>channel.data.byteLength)channel.data.grow(Math.min(maxBytes,Math.max(required,channel.data.byteLength*2)));
   new Uint8Array(channel.data).set(bytes,length);Atomics.store(state,0,required);return true;
  }catch{return block(2,Atomics.load(state,0));}
 }
 function failures(){return pool.slots.flatMap((slot,index)=>{const info=new Int32Array(slot.state),code=Atomics.load(info,1);
  return code?[{protocol,codec,pid:process.pid,threadId:index,code,publishedBytes:Atomics.load(info,0),requestedBytes:Atomics.load(info,2),maxBytes}]:[];});}
 function snapshot(){return pool.slots.flatMap((slot,index)=>{const info=new Int32Array(slot.state),owner=Atomics.load(info,3);
  if(!owner)return[];const length=Atomics.load(info,0),bytes=Buffer.from(new Uint8Array(slot.data,0,length));
  return[{protocol,codec,token,pid:process.pid,threadId:owner-1,channelIndex:index,publishedBytes:length,persistedBytes:Atomics.load(info,4),
   capacityBytes:slot.data.byteLength,maxBytes,failureCode:Atomics.load(info,1),sha256:digest(bytes)}];});}
 function flush(){const seals=[];
  for(let index=0;index<pool.slots.length;index++){const slot=pool.slots[index],info=new Int32Array(slot.state),owner=Atomics.load(info,3);
   if(!owner)continue;const length=Atomics.load(info,0);if(!length)continue;
   const bytes=Buffer.from(new Uint8Array(slot.data,0,length)),filename=path.join(directory,`${process.pid}-${owner-1}-events.jsonl`);
   const fd=fs.openSync(filename,fs.constants.O_CREAT|fs.constants.O_RDWR|fs.constants.O_NOFOLLOW,0o600);
   try{const stat=fs.fstatSync(fd,{bigint:true});if(!stat.isFile()||stat.nlink!==1n)throw Error('Unowned passive event file');
    let offset=0;while(offset<bytes.length){const written=fs.writeSync(fd,bytes,offset,bytes.length-offset,offset);if(!written)throw Error('Passive prefix write did not advance');offset+=written;}
   }finally{fs.closeSync(fd);}
   let previous=Atomics.load(info,4);while(previous<length){const found=Atomics.compareExchange(info,4,previous,length);if(found===previous)break;previous=found;}
   seals.push({protocol,codec,token,pid:process.pid,threadId:owner-1,channelIndex:index,publishedBytes:length,persistedBytes:Atomics.load(info,4),
    capacityBytes:slot.data.byteLength,maxBytes,failureCode:Atomics.load(info,1),sha256:digest(bytes)});
  }
  const seal={protocol,codec,token,pid:process.pid,flushingThreadId:threadId,atNs:now(),channels:seals,failures:failures()};
  fs.writeFileSync(path.join(directory,`${process.pid}-${threadId}-passive-seal.json`),JSON.stringify(seal)+'\n',{mode:0o600});return seal;
 }
 return{append,flush,failures,snapshot,identity:{protocol,codec,token,pid:process.pid,threadId,channelIndex:threadId,initialBytes,maxBytes,slotCount}};
}

// A reply hold postpones only its original delivery; no thread waits on Atomics.
// The intercepted notification has no original return until the real emit runs.
export function deferOriginalEventDelivery({receiver,originalEmit,eventName,message,args,awaitRelease,onReceipt,onControlFailure}){
 const receipt=(name,fields)=>{try{onReceipt(name,fields);}catch(error){onControlFailure(error);}};
 const completion=(async()=>{
  try{await awaitRelease();}catch(error){onControlFailure(error);throw error;}
  receipt('delivery-enter',{enteredAtNs:now(),message:valueRecord(message),arguments:valueRecord(args)});
  try{const result=Reflect.apply(originalEmit,receiver,[eventName,message,...args]);
   receipt('delivery-return',{returnedAtNs:now(),actualReturn:valueRecord(result),actualReturnType:typeof result});return result;
  }catch(error){receipt('delivery-throw',{threwAtNs:now(),error:errorValue(error),privateError:valueRecord(error)});throw error;}
 })();
 return{completion};
}

export function callOriginalAtCheckpoint({receiver,original,args,before,settled,onControlFailure}){
 const observe=callback=>{try{callback();}catch(error){onControlFailure(error);}};
 observe(before);
 let result;
 try{result=Reflect.apply(original,receiver,args);}catch(error){observe(()=>settled(undefined,error));throw error;}
 observe(()=>settled(result));return result;
}

// Passive SQL custody observes actual method calls and iterator consumption.
// No query is replayed, iterator advanced, row changed, or filesystem written.
export function installOriginalSqlObservation({DatabaseSync,qualifyStack,event,ref,onControlFailure}){
 const prepare=DatabaseSync.prototype.prepare,exec=DatabaseSync.prototype.exec,location=DatabaseSync.prototype.location;
 const restorations=[],iterators=new WeakSet(),boundMethods=new WeakSet();let nextCall=0;
 const facts=db=>{let dbPath=null,locationError,transactionActive=null,transactionError;
  try{dbPath=location.call(db,'main');}catch(error){locationError=errorValue(error);}
  try{transactionActive=db.isTransaction;}catch(error){transactionError=errorValue(error);}
  return{databaseRef:ref(db),dbPath,transactionActive,...(locationError?{locationError}:{}),...(transactionError?{transactionError}:{})};};
 const authority=stack=>{try{return qualifyStack(stack);}catch(error){onControlFailure(error);return null;}};
 const observe=callback=>{try{return callback();}catch(error){onControlFailure(error);return undefined;}};
 const failure=error=>({errorRef:ref(error),errorPrototypeRef:error&&Object.getPrototypeOf(error)?ref(Object.getPrototypeOf(error)):null,
  errorConstructorRef:error&&typeof Object.getPrototypeOf(error)?.constructor==='function'?ref(Object.getPrototypeOf(error).constructor):null,
  name:error?.name,message:error?.message,stack:error?.stack,
  privateError:valueRecord(error),ownProperties:Reflect.ownKeys(Object(error)).map(key=>{const descriptor=Object.getOwnPropertyDescriptor(error,key);
   return{key:typeof key==='symbol'?{symbolDescription:key.description}:key,enumerable:descriptor.enumerable,configurable:descriptor.configurable,
    ...(Object.hasOwn(descriptor,'value')?{value:valueRecord(descriptor.value)}:{accessor:true})};})});
 function invoke({db,statement,sql,operation,original,receiver,args,sourceCaller,originalStack}){
  const callId=`${process.pid}:${threadId}:sql-${++nextCall}`;
  const common={callId,operation,statementRef:statement?ref(statement):null,sql,sourceCaller,originalStack,
   originalMethodRef:ref(original),originalMethodName:original.name};
  observe(()=>{if(!boundMethods.has(original)){boundMethods.add(original);const body=Function.prototype.toString.call(original),prototype=Object.getPrototypeOf(receiver);
    event('original-sql-method-binding',{functionRef:ref(original),functionName:original.name,functionSource:body,functionSourceSha256:digest(Buffer.from(body)),
     databaseClassRef:ref(DatabaseSync),databasePrototypeRef:ref(DatabaseSync.prototype),receiverPrototypeRef:prototype?ref(prototype):null,
     receiverConstructorRef:prototype&&typeof prototype.constructor==='function'?ref(prototype.constructor):null});}});
  observe(()=>event('original-selected-sql-call',{...common,...facts(db),arguments:valueRecord(args)}));
  try{const result=Reflect.apply(original,receiver,args);
   observe(()=>event('original-selected-sql-return',{...common,...facts(db),result:valueRecord(result),resultType:typeof result,
    resultRef:result&&(typeof result==='object'||typeof result==='function')?ref(result):null,
    ...(result&&(typeof result==='object'||typeof result==='function')?{resultPrototypeIsNull:Object.getPrototypeOf(result)===null,
     resultPrototypeRef:Object.getPrototypeOf(result)===null?null:ref(Object.getPrototypeOf(result))}:{})}));return result;
  }catch(error){observe(()=>event('original-selected-sql-throw',{...common,...facts(db),...failure(error)}));throw error;}
 }
 function instrumentIterator(iterator,context){if(!iterator||iterators.has(iterator))return;iterators.add(iterator);
  for(const name of['next','return','throw']){const original=iterator[name];if(typeof original!=='function')continue;
   iterator[name]=function(...args){return invoke({...context,operation:'iterate.'+name,original,receiver:this,args,
    originalStack:new Error('Actual original SQLite iterator consumption').stack});};
   restorations.push(()=>{iterator[name]=original;});
  }
 }
 DatabaseSync.prototype.prepare=function(...args){const originalStack=new Error('Actual original SQLite prepare custody').stack,sourceCaller=authority(originalStack);
  if(!sourceCaller)return Reflect.apply(prepare,this,args);
  const statement=invoke({db:this,sql:args[0],operation:'prepare',original:prepare,receiver:this,args,sourceCaller,originalStack}),db=this,sql=args[0];
  observe(()=>{for(const name of['get','all','run','iterate','columns','setAllowBareNamedParameters','setAllowUnknownNamedParameters','setReadBigInts','setReturnArrays']){const original=statement[name];if(typeof original!=='function')continue;
   statement[name]=function(...values){const context={db,statement,sql,operation:name,original,receiver:this,args:values,
     sourceCaller,originalStack:new Error('Actual original SQLite statement custody').stack};
    const result=invoke(context);if(name==='iterate')observe(()=>instrumentIterator(result,context));return result;};
   restorations.push(()=>{statement[name]=original;});
  }});return statement;
 };
 DatabaseSync.prototype.exec=function(...args){const originalStack=new Error('Actual original SQLite exec custody').stack,sourceCaller=authority(originalStack);
  return sourceCaller?invoke({db:this,sql:args[0],operation:'exec',original:exec,receiver:this,args,sourceCaller,originalStack}):Reflect.apply(exec,this,args);
 };
 return{declareInstalled(){event('original-sql-observer-installed',{databaseClassRef:ref(DatabaseSync),databasePrototypeRef:ref(DatabaseSync.prototype),
   prepareOriginalRef:ref(prepare),execOriginalRef:ref(exec),statementMethods:['get','all','run','iterate','columns','setAllowBareNamedParameters',
    'setAllowUnknownNamedParameters','setReadBigInts','setReturnArrays'],iteratorMethods:['next','return','throw'],storage:'shared-per-thread-immutable-jsonl'});},
  restore(){DatabaseSync.prototype.prepare=prepare;DatabaseSync.prototype.exec=exec;for(const restore of restorations.reverse())restore();}};
}

export function installSourceClock({workspaceDir,actor,ticksByCall,event=()=>{},qualifyStack}){
 if(!path.isAbsolute(workspaceDir)||!ticksByCall||typeof qualifyStack!=='function')throw Error('A source clock requires explicit owned inputs and source authority');
 const original=Object.fromEntries(['open','writeFile','rename','unlink','stat','lstat','readFile'].map(name=>[name,fsp[name]]));
 const handles=new WeakMap(),stages=new Map(),restorations=[],rows=[],failures=[],versions=new Map();
 const scopes=new AsyncLocalStorage();let nextHandle=0,nextControl=0;
 const currentScope=()=>scopes.getStore();
 function emit(name,row){try{event(name,row);}catch(error){const blocked={event:'source-clock-failure',reason:'receipt-sink-error',actor,callKey:currentScope()?.key??null,atNs:now(),error:errorValue(error)};failures.push(blocked);rows.push(blocked);}}
 function failure(reason,fields={}){const row={event:'source-clock-failure',reason,actor,callKey:currentScope()?.key??null,atNs:now(),...fields};
  failures.push(row);rows.push(row);emit(row.event,row);return row;}
 function authority(stack,kind,details){try{return qualifyStack(stack,kind,details);}catch(error){failure('source-authority-error',{error:errorValue(error)});return null;}}
 function absolute(value){if(value instanceof URL)value=value.pathname;if(typeof value!=='string')return null;return path.resolve(value);}
 function inside(filename){return filename===workspaceDir||filename.startsWith(workspaceDir+path.sep);}
 function owned(value){const filename=absolute(value);return filename&&inside(filename)&&/\.(?:md|txt)$/iu.test(filename)?filename:null;}
 function sourceFiles(){const result=new Map();
  function walk(directory){for(const name of fs.readdirSync(directory)){const filename=path.join(directory,name),stat=fs.lstatSync(filename,{bigint:true});
   if(stat.isSymbolicLink())throw Error('A source clock refuses aliased workspace entries');
   if(stat.isDirectory())walk(filename);else if(stat.isFile()&&owned(filename)){
    if(typeof fs.constants.O_NOATIME!=='number')throw Error('Source clock boundary requires the pinned Linux no-atime read ABI');
    const fd=fs.openSync(filename,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW|fs.constants.O_NOATIME);
    try{const before=fs.fstatSync(fd,{bigint:true});if(!stable(stat,before))throw Error('Source clock boundary source changed before reading');
     const bytes=fs.readFileSync(fd),after=fs.fstatSync(fd,{bigint:true});if(!stable(before,after))throw Error('Source clock boundary source changed during reading');
     result.set(filename,{sha256:digest(bytes),stat:statValue(after)});
    }finally{fs.closeSync(fd);}
   }
  }}walk(workspaceDir);return result;
 }
 function frame(){const active=currentScope();if(!active){failure('missing-declared-call');return null;}return active;}
 function readBound(record,filename){
  const fdStat=fs.fstatSync(record.handle.fd,{bigint:true}),pathStat=fs.lstatSync(filename,{bigint:true});
  if(!fdStat.isFile()||!pathStat.isFile()||pathStat.isSymbolicLink()||!stable(fdStat,pathStat))throw Error('Source clock inode ownership changed');
  if(typeof fs.constants.O_NOATIME!=='number')throw Error('Source clock byte verification requires the pinned Linux no-atime read ABI');
  const fd=fs.openSync(filename,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW|fs.constants.O_NOATIME);
  try{const readStat=fs.fstatSync(fd,{bigint:true});if(!stable(fdStat,readStat))throw Error('Source clock reader opened another inode');
   const bytes=fs.readFileSync(fd),after=fs.fstatSync(record.handle.fd,{bigint:true});
   if(!stable(fdStat,after)||after.size!==BigInt(bytes.length))throw Error('Source clock bytes changed during read');
   return{fdStat:statValue(fdStat),pathStat:statValue(pathStat),readerStat:statValue(readStat),afterReadStat:statValue(after),
    bytesHex:bytes.toString('hex'),sha256:digest(bytes)};
  }finally{fs.closeSync(fd);}
 }
 async function clock(record,filename,finalPath,operation,stack,sourceOwner){
  const current=frame();if(!current)return null;
  const control={event:'source-clock-control',controlId:`${process.pid}:${threadId}:${++nextControl}`,actor,callKey:current.key,causalFrame:current.causalFrame,
   ordinal:current.tick.ordinal,tick:{...current.tick},operation,path:finalPath,stagePath:operation==='atomic'?filename:null,
   handleRef:record.handleRef,fd:record.handle.fd,sourceOwner,originalStack:stack,open:record.open,
   writes:record.writes.map(row=>({...row})),syncs:record.syncs.map(row=>({...row})),startedAtNs:now(),status:'pending'};
  rows.push(control);
  try{
   if(!record.writes.length||record.writes.some(row=>row.status!=='fulfilled'))throw Error('Source clock requires completed successful original writes');
   if(record.scope!==current.key)throw Error('Source clock handle belongs to another declared call');
   control.before=readBound(record,filename);
   const key=current.key+'\0'+finalPath,previous=versions.get(key);
   if(previous&&previous.sha256!==control.before.sha256)throw Error('One declared call committed different source byte revisions');
   const args=[current.tick.atimeMs/1000,current.tick.mtimeMs/1000];
   control.utimes={arguments:args,startedAtNs:now()};
   try{const result=await record.original.utimes.apply(record.handle,args);control.utimes.return=valueRecord(result);}
   catch(error){control.utimes.error=errorValue(error);control.utimes.privateError=valueRecord(error);throw error;}
   finally{control.utimes.finishedAtNs=now();}
   control.after=readBound(record,filename);
   if(control.after.sha256!==control.before.sha256||BigInt(control.after.fdStat.mtimeNs)!==BigInt(current.tick.mtimeMs)*1_000_000n)throw Error('Source clock changed bytes or missed its literal timestamp');
   control.status='clocked';
   if(operation==='inPlace'){versions.set(key,{sha256:control.after.sha256,controlId:control.controlId});current.commits.set(finalPath,control);control.committed=true;}
  }catch(error){control.status='blocked';control.controlError=errorValue(error);failure('source-clock-control-failed',{controlId:control.controlId,error:errorValue(error)});}
  control.finishedAtNs=now();emit(control.event,control);return control;
 }
 function track(handle,filename,flags,stack,sourceOwner){
  if(handles.has(handle))return;
  const exclusive=typeof flags==='number'?Boolean(flags&fs.constants.O_EXCL):String(flags).includes('x');
  const record={handle,handleRef:`${process.pid}:${threadId}:source-handle-${++nextHandle}`,path:filename,
   stage:sourceOwner.publicationRole?sourceOwner.publicationRole==='stage':exclusive,scope:currentScope()?.key??null,writes:[],syncs:[],open:{path:filename,flags:valueRecord(flags),
    originalStack:stack,sourceOwner,atNs:now()},original:{}};
  for(const name of['write','writeFile','truncate','sync','close','utimes'])record.original[name]=handle[name];
  if(typeof record.original.utimes!=='function'){failure('missing-original-handle-utimes',{path:filename});return;}
  handles.set(handle,record);if(record.stage)stages.set(filename,record);
  for(const name of['write','writeFile','truncate','sync']){
   if(typeof record.original[name]!=='function')continue;
   handle[name]=function(...args){
    const row={method:name,arguments:valueRecord(args),startedAtNs:now(),originalStack:new Error('Original source handle operation').stack};
    if(name==='sync')record.syncs.push(row);else if(name!=='truncate')record.writes.push(row);
    const settle=(result,error)=>{row.finishedAtNs=now();row.status=error?'rejected':'fulfilled';
     if(error){row.error=errorValue(error);row.privateError=valueRecord(error);}else row.return=valueRecord(result);};
    try{const result=record.original[name].apply(this,args);if(result&&typeof result.then==='function')result.then(value=>settle(value),error=>settle(undefined,error));else settle(result);return result;}
    catch(error){settle(undefined,error);throw error;}
   };
   restorations.push(()=>{handle[name]=record.original[name];});
  }
  handle.close=async function(...args){const stack=new Error('Original source handle close').stack;let control=null;
   if(!record.stage&&record.writes.length&&owned(record.path))control=await clock(record,record.path,record.path,'inPlace',stack,sourceOwner);
   const call={method:'close',arguments:valueRecord(args),startedAtNs:now(),originalStack:stack};record.close=call;
   try{const result=await record.original.close.apply(this,args);call.return=valueRecord(result);return result;}
   catch(error){call.error=errorValue(error);call.privateError=valueRecord(error);throw error;}
   finally{call.finishedAtNs=now();if(control){control.close=call;emit('source-clock-continuation',{controlId:control.controlId,callKey:control.callKey,close:call});}
    if(record.stage)stages.delete(record.path);}
  };
  restorations.push(()=>{handle.close=record.original.close;});
 }
 fsp.open=async function(...args){const stack=new Error('Original source open').stack,result=await original.open.apply(this,args),filename=absolute(args[0]);
  const flags=args[1],writing=typeof flags==='number'?Boolean(flags&(fs.constants.O_WRONLY|fs.constants.O_RDWR)):/[wa+]/u.test(String(flags));
  const exclusive=typeof flags==='number'?Boolean(flags&fs.constants.O_EXCL):String(flags).includes('x');
  if(filename&&inside(filename)&&writing&&(owned(filename)||exclusive)){try{const sourceOwner=authority(stack,'open',{path:filename,flags});if(sourceOwner)track(result,filename,flags,stack,sourceOwner);}
   catch(error){failure('source-handle-observer-install-failed',{path:filename,error:errorValue(error)});}}
  return result;
 };
 fsp.writeFile=function(...args){const record=handles.get(args[0]);if(!record){const filename=owned(args[0]),stack=new Error('Original direct source write').stack;
   if(filename&&authority(stack,'write'))failure('unsupported-direct-owned-source-write',{path:filename,originalStack:stack});
   return original.writeFile.apply(this,args);
  }
  const row={method:'fs.promises.writeFile',arguments:valueRecord(args.slice(1)),startedAtNs:now(),originalStack:new Error('Original staged write completion').stack};record.writes.push(row);
  const settle=(result,error)=>{row.finishedAtNs=now();row.status=error?'rejected':'fulfilled';if(error){row.error=errorValue(error);row.privateError=valueRecord(error);}else row.return=valueRecord(result);};
  try{const result=original.writeFile.apply(this,args);result.then(value=>settle(value),error=>settle(undefined,error));return result;}
  catch(error){settle(undefined,error);throw error;}
 };
 fsp.rename=async function(...args){const finalPath=owned(args[1]),stack=new Error('Original source atomic rename').stack;
  const sourceOwner=finalPath?authority(stack,'rename'):null,record=stages.get(absolute(args[0]));let control=null;
  if(finalPath&&sourceOwner){if(record)control=await clock(record,record.path,finalPath,'atomic',stack,sourceOwner);
   else failure('missing-original-stage-association',{path:finalPath,originalStack:stack});}
  try{const result=await original.rename.apply(this,args);
   if(control){control.rename={arguments:valueRecord(args),return:valueRecord(result),returnedAtNs:now()};
    try{control.published=readBound(record,finalPath);control.committed=true;
     if(control.status==='clocked'){const key=control.callKey+'\0'+finalPath;versions.set(key,{sha256:control.published.sha256,controlId:control.controlId});currentScope()?.commits.set(finalPath,control);}
    }catch(error){control.status='blocked';control.controlError=errorValue(error);failure('source-clock-publication-identity-failed',{controlId:control.controlId,error:errorValue(error)});}
   }return result;
  }catch(error){if(control)control.rename={arguments:valueRecord(args),error:errorValue(error),privateError:valueRecord(error),returnedAtNs:now()};throw error;}
  finally{if(control)emit('source-clock-continuation',{controlId:control.controlId,callKey:control.callKey,rename:control.rename,published:control.published??null,committed:control.committed===true});}
 };
 fsp.unlink=async function(...args){const filename=owned(args[0]),stack=new Error('Original source unlink').stack,sourceOwner=filename?authority(stack,'unlink'):null;
  try{const result=await original.unlink.apply(this,args);if(filename&&sourceOwner){const current=frame();
    const row={event:'source-clock-deletion',actor,callKey:current?.key??null,path:filename,sourceOwner,originalStack:stack,
     arguments:valueRecord(args),return:valueRecord(result),atNs:now()};rows.push(row);emit(row.event,row);current?.deletions.add(filename);}
   return result;
  }catch(error){throw error;}
 };
 for(const name of['stat','lstat','readFile'])fsp[name]=function(...args){const filename=owned(args[0]),stack=new Error('Original source read').stack,
  sourceOwner=filename?authority(stack,'read'):null;if(!sourceOwner)return original[name].apply(this,args);
  const entered=now(),callKey=currentScope()?.key??null,result=original[name].apply(this,args);result.then(value=>{const row={event:'source-clock-read',actor,callKey,
   path:filename,method:name,sourceOwner,originalStack:stack,startedAtNs:entered,finishedAtNs:now(),return:valueRecord(value)};rows.push(row);emit(row.event,row);},()=>{});return result;
 };
 return{
  beginCall(key,causalFrame=null){if(currentScope()&&!currentScope().completed){failure('ambiguous-concurrent-call',{requestedCall:key});return;}
   const tick=ticksByCall[key];if(!tick||tick.actor!==actor||!Number.isInteger(tick.ordinal)||(causalFrame&&causalFrame.wallClockNowMs!==tick.wallClockNowMs)||
    ![tick.atimeMs,tick.mtimeMs].every(value=>Number.isSafeInteger(value)&&value%1000===0)){
    failure('missing-or-invalid-literal-call-tick',{requestedCall:key});return;
   }
   const active={key,tick:{...tick},causalFrame,commits:new Map(),deletions:new Set(),before:new Map(),completed:false};scopes.enterWith(active);
   try{active.before=sourceFiles();}catch(error){failure('source-clock-entry-read-failed',{error:errorValue(error)});}
  },
  endCall(){const active=currentScope();if(!active)return;try{const after=sourceFiles(),row={event:'source-clock-call-boundary',actor,callKey:active.key,
    tick:{...active.tick},before:[...active.before].map(([path,value])=>({path,...value})),
    after:[...after].map(([path,value])=>({path,...value})),atNs:now()};
    rows.push(row);emit(row.event,row);
   }catch(error){failure('source-clock-exit-read-failed',{error:errorValue(error)});}finally{active.completed=true;scopes.enterWith(null);}
  },
  blocked:()=>failures.length>0,receipts:()=>rows,failures:()=>failures,
  restore(){for(const name of Object.keys(original))fsp[name]=original[name];for(const restore of restorations.reverse())restore();},
 };
}
