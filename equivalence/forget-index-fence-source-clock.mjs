// Functional fixture input, separate from product clocks and original IO.
// Every hook calls the same original function on the same FileHandle object.
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {serialize} from 'node:v8';
import {AsyncLocalStorage} from 'node:async_hooks';
import {threadId} from 'node:worker_threads';

const digest=bytes=>createHash('sha256').update(bytes).digest('hex');
const now=()=>process.hrtime.bigint().toString();
const errorValue=error=>({name:error.name,message:error.message,...(error.code===undefined?{}:{code:error.code}),stack:error.stack});
const valueRecord=value=>{try{return{v8Hex:serialize(value).toString('hex')};}catch(error){return{serializationError:errorValue(error)};}};
const statValue=stat=>Object.fromEntries(Object.getOwnPropertyNames(stat).map(key=>[key,typeof stat[key]==='bigint'?stat[key].toString():stat[key]]));
const same=(left,right)=>left.dev===right.dev&&left.ino===right.ino&&left.nlink===1n&&right.nlink===1n;
const stable=(left,right)=>same(left,right)&&left.size===right.size&&left.mtimeNs===right.mtimeNs&&left.ctimeNs===right.ctimeNs;

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
