// Functional fixture input, separate from product clocks and original IO.
// Every hook calls the same original function on the same FileHandle object.
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {serialize,deserialize} from 'node:v8';
import {AsyncLocalStorage,createHook,executionAsyncId} from 'node:async_hooks';
import {EventEmitter} from 'node:events';
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

// Concurrent IPC controls must not relabel a still-pending original call or
// its asynchronous descendants. Each command retains its own causal scope.
export function createOriginalCommandScope(){
 const scopes=new AsyncLocalStorage();
 function validate(frame){if(frame!==null&&(frame.protocol!=='async-local-original-command-v1'||
  !Number.isSafeInteger(frame.commandId)||frame.commandId<1||typeof frame.operation!=='string'||!frame.operation||
  typeof frame.label!=='string'||!frame.label))throw Error('An original command scope requires its actual labelled IPC command');}
 return Object.freeze({
  current:()=>scopes.getStore()??null,
  run(command,callback){const frame=Object.freeze({protocol:'async-local-original-command-v1',commandId:command.id,
   operation:command.operation,label:command.label??command.operation});validate(frame);return scopes.run(frame,callback);},
  resume(frame,callback){validate(frame);return scopes.run(frame,callback);},
 });
}

// Hold only an already asynchronous planning continuation. The real 30-second
// deadline begins at the recorded gate entry, including flushes and probes.
export async function awaitOriginalPlanningGateRelease(filename,{enteredAtNs,onProgress=()=>{},
 originalTimeout=setTimeout,originalImmediate=setImmediate}){
 const entered=BigInt(enteredAtNs),deadline=entered+30_000_000_000n;
 if(entered<0n||entered>process.hrtime.bigint())throw Error('A planning gate requires its actual monotonic entry');
 const withinDeadline=()=>{if(process.hrtime.bigint()>=deadline)throw Error('Declared asynchronous fence gate exceeded its real monotonic bound');};
 withinDeadline();
 const progressed=kind=>new Promise((resolve,reject)=>{
  const callback=()=>{try{onProgress(kind);resolve();}catch(error){reject(error);}};
  if(kind==='setImmediate')originalImmediate(callback);else originalTimeout(callback,0);
 });
 await Promise.all([progressed('setImmediate'),progressed('setTimeout')]);
 for(;;){withinDeadline();if(fs.existsSync(filename))break;await new Promise(resolve=>originalTimeout(resolve,10));}
 const releaseStep=JSON.parse(fs.readFileSync(filename,'utf8')),consumedAtNs=now();withinDeadline();
 return{releaseStep,consumedAtNs,gateDeadlineNs:deadline.toString()};
}

// A control consumer must never see a partially written JSON body. The private
// reservation is exclusive across processes; rename publishes one complete,
// closed, single-link inode without overwriting a prior control publication.
export function publishControlFile(filename,content){
 if(!path.isAbsolute(filename)||fs.realpathSync(path.dirname(filename))!==path.dirname(filename))throw Error('A control publication requires its exact owned directory');
 const bytes=Buffer.isBuffer(content)?content:Buffer.from(content,'utf8'),reservation=filename+'.publishing',stage=path.join(reservation,'body');
 fs.mkdirSync(reservation,{mode:0o700});let fd=null;
 try{
  try{fs.lstatSync(filename);throw Error('A control file was already published');}catch(error){if(error.code!=='ENOENT')throw error;}
  fd=fs.openSync(stage,fs.constants.O_CREAT|fs.constants.O_EXCL|fs.constants.O_WRONLY|fs.constants.O_NOFOLLOW,0o600);
  let written=0;while(written<bytes.length){const count=fs.writeSync(fd,bytes,written,bytes.length-written);
   if(count<=0)throw Error('A control body write made no progress');written+=count;}
  fs.closeSync(fd);fd=null;
  const before=fs.lstatSync(stage,{bigint:true}),actual=fs.readFileSync(stage);
  if(!before.isFile()||before.nlink!==1n||before.size!==BigInt(bytes.length)||!actual.equals(bytes))throw Error('A control stage lost its complete original bytes');
  const renameEnteredAtNs=now();fs.renameSync(stage,filename);const renameReturnedAtNs=now();
  return{path:filename,stagePath:stage,bytes:bytes.toString('hex'),sha256:digest(bytes),
   stageStat:statValue(before),renameEnteredAtNs,renameReturnedAtNs};
 }finally{
  if(fd!==null)fs.closeSync(fd);
  try{fs.unlinkSync(stage);}catch(error){if(error.code!=='ENOENT')throw error;}
  fs.rmdirSync(reservation);
 }
}

// V3's explicit observer joins actual work already scheduled by the original
// search. The hook never invokes a producer or replaces an original Promise.
export function observeOriginalSearchEffects({scope,qualifyPromise,ref,event=()=>{},onFailure=()=>{},maxJobs=256}){
 if(!Number.isSafeInteger(maxJobs)||maxJobs<1||maxJobs>256)throw Error('A search-effects observer requires a bounded declared reference capacity');
 const originalThen=Promise.prototype.then,metadata=new WeakMap(),recalls=new Map(),searches=new Map();
 let observing=false,nextJob=0;
 const emit=(name,fields)=>{try{event(name,fields);}catch(error){onFailure(error);}};
 const fail=message=>{const error=Error(message);onFailure(error);throw error;};
 const hook=createHook({init(asyncId,type,triggerAsyncId,resource){
  if(type!=='PROMISE'||observing)return;
  try{
   const causal=scope();if(!causal?.key?.startsWith('search:'))return;
   const originalStack=new Error('Actual original search-effect Promise creation').stack;
   const owner=qualifyPromise(originalStack);if(!owner)return;
   const record={jobId:`search-effect-${++nextJob}`,asyncId,triggerAsyncId,promiseRef:ref(resource),
    promiseConstructorRef:ref(resource.constructor),promisePrototypeRef:ref(Object.getPrototypeOf(resource)),
    callKey:causal.key,causalFrame:causal.causalFrame,sourceOwner:owner,originalStack,resource};
   metadata.set(resource,record);
   if(owner.kind==='recall-then'||owner.kind==='recall-catch'){
    const rows=recalls.get(causal.key)??[];rows.push(record);recalls.set(causal.key,rows);
   }
   emit('original-search-effect-promise-created',Object.fromEntries(Object.entries(record).filter(([key])=>key!=='resource')));
  }catch(error){onFailure(error);}
 }}).enable();
 emit('original-search-effects-observer-installed',{protocol:'original-search-effects-v3',originalThenRef:ref(originalThen),
  originalThenSource:Function.prototype.toString.call(originalThen),hookRef:ref(hook),maxJobs,
  promiseClassRef:ref(Promise),promisePrototypeRef:ref(Promise.prototype),setClassRef:ref(Set),setPrototypeRef:ref(Set.prototype),
  sourceKinds:['recall-then','recall-catch','publisher']});
 function observe(record){
  if(record.observed)return record.observed;
  observing=true;
  try{record.observed=Reflect.apply(originalThen,record.resource,[value=>{
    record.settlement={status:'fulfilled',value:valueRecord(value),valueRef:ref(value),valueType:typeof value};
    emit('original-search-effect-promise-settled',{jobId:record.jobId,promiseRef:record.promiseRef,...record.settlement});
   },error=>{
    const object=error!==null&&(typeof error==='object'||typeof error==='function');
    record.settlement={status:'rejected',error:valueRecord(error),errorRef:ref(error),errorType:typeof error,
     ...(object?{errorFields:errorValue(error),errorConstructorRef:ref(error.constructor),errorPrototypeRef:ref(Object.getPrototypeOf(error)),
     errorOwnProperties:Reflect.ownKeys(error).map(key=>{const descriptor=Object.getOwnPropertyDescriptor(error,key);
      return{key:typeof key==='symbol'?{symbolDescription:key.description}:key,enumerable:descriptor.enumerable,
       configurable:descriptor.configurable,...(Object.hasOwn(descriptor,'value')?{value:valueRecord(descriptor.value)}:{accessor:true})};})}:{})};
    emit('original-search-effect-promise-settled',{jobId:record.jobId,promiseRef:record.promiseRef,...record.settlement});
   }]);}finally{observing=false;}
  return record.observed;
 }
 function queued(key,owners,stage){const records=[],reads=[];
  for(const owner of owners){if(owner.purpose!=='default')continue;
   const actualSet=owner.activeBackgroundSearchSyncs;
   if(!(actualSet instanceof Set))fail('The actual default owner has no original background Promise Set');
   const members=Array.from(actualSet),read={callKey:key,stage,ownerRef:ref(owner),setRef:ref(actualSet),
    setConstructorRef:ref(actualSet.constructor),setPrototypeRef:ref(Object.getPrototypeOf(actualSet)),
    promiseRefs:members.map(ref),atNs:now()};reads.push(read);emit('original-search-effects-queue-read',read);
   for(const promise of members){const record=metadata.get(promise);
    if(!record||record.callKey!==key||record.sourceOwner.kind!=='publisher')fail('An actual queued publisher lost its labelled original Promise source');
    records.push(record);
   }
  }
  return{records,reads};
 }
 return{
  reference:ref,
  begin(label){const key=`search:${label}`;if(searches.has(key))fail('A V3 search label was entered twice');
   searches.set(key,{settled:false,awaited:false});},
  settled(label,{status,requiresRecall},owners=[]){const key=`search:${label}`,entry=searches.get(key);
   if(!entry||entry.settled)fail('A V3 search lost its actual original settlement');
   const originalQueue=queued(key,owners,'public-settlement');
   Object.assign(entry,{settled:true,status,requiresRecall,publishers:originalQueue.records,queueReads:originalQueue.reads});
   const receipt={callKey:key,status,requiresRecall,queueReads:originalQueue.reads,
    recallPromiseRefs:(recalls.get(key)??[]).map(row=>row.promiseRef),atNs:now()};
   emit('original-search-effects-public-settlement',receipt);return receipt;},
  async awaitEffects(label,owners){const key=`search:${label}`,entry=searches.get(key);
   if(!entry?.settled||entry.awaited)fail('V3 effects require one already settled original search');
   const recorded=recalls.get(key)??[],then=recorded.filter(row=>row.sourceOwner.kind==='recall-then'),
    caught=recorded.filter(row=>row.sourceOwner.kind==='recall-catch');
   if(then.length!==caught.length||then.length>1||entry.requiresRecall&&then.length!==1||
    caught.length&&caught[0].triggerAsyncId!==then[0].asyncId)fail('Original recall Promise source/trigger custody is missing or ambiguous');
   const jobs=new Map([...recorded,...entry.publishers].map(row=>[row.promiseRef,row]));
   const receipt={protocol:'original-search-effects-v3',callKey:key,searchStatus:entry.status,
    recallPromiseRefs:recorded.map(row=>row.promiseRef),queueReads:[...entry.queueReads],startedAtNs:now()};
   emit('original-search-effects-await-enter',receipt);
   function readQueued(){const added=[],observed=queued(key,owners,'explicit-await');receipt.queueReads.push(...observed.reads);
    for(const record of observed.records)if(!jobs.has(record.promiseRef)){jobs.set(record.promiseRef,record);added.push(record);}
    if(jobs.size>maxJobs)fail('Already queued search effects exceed the declared control capacity');
    return added;
   }
   readQueued();let pending=Array.from(jobs.values());
   while(pending.length){await Promise.all(pending.map(observe));pending=readQueued();}
   receipt.jobs=Array.from(jobs.values(),record=>({jobId:record.jobId,promiseRef:record.promiseRef,
    promiseConstructorRef:record.promiseConstructorRef,promisePrototypeRef:record.promisePrototypeRef,
    asyncId:record.asyncId,triggerAsyncId:record.triggerAsyncId,sourceOwner:record.sourceOwner,
    originalStack:record.originalStack,settlement:record.settlement}));
   receipt.finishedAtNs=now();entry.awaited=true;emit('original-search-effects-await-return',receipt);return receipt;
  },
  assertDrained(){if(Array.from(searches.values()).some(row=>row.settled&&!row.awaited))fail('An original search has not reached its declared V3 effects boundary');},
  stop(){hook.disable();},
 };
}

// A watcher barrier joins facts already admitted by the original watcher. It
// does not manufacture an event, run a timer, or claim an OS delivery watermark.
export function observeOriginalWatchEffects({ref,event=()=>{},onFailure=()=>{},qualifyTimer,
 qualifySync,qualifyNativeWatch,qualifyEmitter,maxReferences=1024}){
 const originalThen=Promise.prototype.then,originalWatch=fs.watch,originalEmit=EventEmitter.prototype.emit;
 const owners=new Map(),timers=new Map(),resources=new WeakMap(),promises=new WeakMap(),parents=new Map(),
  nativeHandles=new WeakMap(),readyEvents=new WeakMap(),waiters=new Set(),sourceReads=[],deliveries=new AsyncLocalStorage();
 const records=[],restorations=[];let observing=false,nextFact=0,nextDelivery=0;
 const emit=(name,fields)=>{try{event(name,fields);}catch(error){onFailure(error);}};
 const fail=message=>{const error=Error(message);onFailure(error);throw error;};
 function notify(){for(const resolve of waiters)resolve();waiters.clear();}
 const changed=()=>new Promise(resolve=>waiters.add(resolve));
 function pass(callback){try{return callback();}catch(error){onFailure(error);return undefined;}}
 function snapshot(record,stage){const watcher=record.watcher;
  const row={ownerRef:record.ownerRef,watcherRef:record.watcherRef,stage,atNs:now(),
   closed:watcher.closed,pendingChange:watcher.pendingChange,
   startingRef:ref(watcher.starting),reconcilingRef:ref(watcher.reconciling),settlingRef:ref(watcher.settling),
   timerRef:ref(watcher.watchTimer),pendingPaths:valueRecord(watcher.pendingWatchPaths),
   pendingReconciliations:valueRecord(watcher.pendingReconciliations),reconcileAll:watcher.reconcileAll};
  emit('original-watch-state-read',row);return row;
 }
 function promiseRecord(promise,kind,record){if(!(promise instanceof Promise))return null;
  let item=promises.get(promise);if(!item){item={promise,promiseRef:ref(promise),kind,
   source:'actual-watcher-property',ownerRef:record?.ownerRef??null,createdAtNs:now()};promises.set(promise,item);}
  if(record){item.ownerRef??=record.ownerRef;item.watcherRef??=record.watcherRef;}return item;
 }
 function observePromise(item){if(item.observed)return item.observed;
  observing=true;try{item.observed=Reflect.apply(originalThen,item.promise,[value=>{
   item.settlement={status:'fulfilled',value:valueRecord(value),valueRef:ref(value),atNs:now()};
   emit('original-watch-promise-settlement',{...publicPromise(item),settlement:item.settlement});notify();return item.settlement;
  },error=>{item.settlement={status:'rejected',error:errorValue(error),privateError:valueRecord(error),errorRef:ref(error),atNs:now()};
   emit('original-watch-promise-settlement',{...publicPromise(item),settlement:item.settlement});notify();return item.settlement;
  }]);}finally{observing=false;}return item.observed;
 }
 function publicPromise(item){return{promiseRef:item.promiseRef,kind:item.kind,ownerRef:item.ownerRef??null,
  watcherRef:item.watcherRef??null,asyncId:item.asyncId??null,triggerAsyncId:item.triggerAsyncId??null,
  sourceOwner:item.sourceOwner??null,originalStack:item.originalStack??null,asyncAncestry:item.asyncAncestry??null,
  onChangeRef:item.onChangeRef??null,syncMethodRef:item.syncMethodRef??null,
  promiseConstructorRef:ref(item.promise.constructor),promisePrototypeRef:ref(Object.getPrototypeOf(item.promise))};}
 function attachTimer(record,timer,stage){if(!timer)return null;const item=resources.get(timer);
  if(!item||item.kind!=='watch-timer')fail('Actual watcher timer lacks its original source-qualified Timeout resource');
  if(item.watcherRef&&item.watcherRef!==record.watcherRef)fail('Original Timeout was borrowed by another watcher');
  item.ownerRef=record.ownerRef;item.watcherRef=record.watcherRef;
  emit('original-watch-timer-binding',{stage,...item,resource:undefined});return item;
 }
 const hook=createHook({init(asyncId,type,triggerAsyncId,resource){parents.set(asyncId,triggerAsyncId);
  if(observing||type!=='Timeout'&&type!=='PROMISE')return;
  pass(()=>{const originalStack=new Error('Actual original watcher resource').stack;
   if(type==='Timeout'){const sourceOwner=qualifyTimer(originalStack);if(!sourceOwner)return;
    const item={kind:'watch-timer',asyncId,triggerAsyncId,resource,resourceRef:ref(resource),
     resourceConstructorRef:ref(resource.constructor),resourcePrototypeRef:ref(Object.getPrototypeOf(resource)),
     callbackRef:ref(resource._onTimeout),callbackSource:Function.prototype.toString.call(resource._onTimeout),
     sourceOwner,originalStack,createdAtNs:now(),fired:false,destroyed:false,
     delivery:deliveries.getStore()??null};resources.set(resource,item);timers.set(asyncId,item);
    emit('original-watch-timer-created',{...item,resource:undefined});notify();
   }else{const sourceOwner=qualifySync(originalStack);if(!sourceOwner)return;
    const ancestry=[];let ancestor=triggerAsyncId,owningTimer=null;
    while(ancestor&&!ancestry.includes(ancestor)&&ancestry.length<maxReferences){ancestry.push(ancestor);
     if(timers.get(ancestor)?.watcherRef){owningTimer=timers.get(ancestor);break;}ancestor=parents.get(ancestor);}
    const owner=owningTimer?Array.from(owners.values()).find(record=>record.watcherRef===owningTimer.watcherRef):null;
    const item={kind:'watch-sync',asyncId,triggerAsyncId,promise:resource,promiseRef:ref(resource),sourceOwner,
     originalStack,createdAtNs:now(),delivery:deliveries.getStore()??null,asyncAncestry:ancestry,
     ownerRef:owner?.ownerRef??null,watcherRef:owner?.watcherRef??null,
     onChangeRef:owner?ref(owner.watcher.callbacks.onChange):null,syncMethodRef:owner?ref(owner.owner.sync):null};promises.set(resource,item);
    records.push(item);emit('original-watch-promise-created',publicPromise(item));}
  });
 },before(asyncId){const item=timers.get(asyncId);if(!item)return;pass(()=>{
  for(const record of owners.values())if(record.watcher.watchTimer===item.resource)attachTimer(record,item.resource,'actual-timer-before');
  item.fired=true;item.enteredAtNs=now();emit('original-watch-timer-fire',{...item,resource:undefined});notify();
 });},after(asyncId){const item=timers.get(asyncId);if(!item)return;pass(()=>{
  const record=Array.from(owners.values()).find(value=>value.watcherRef===item.watcherRef);
  if(record){const pending=promiseRecord(record.watcher.settling,'watch-settling',record);
   if(pending){item.settlingRef=pending.promiseRef;observePromise(pending);}snapshot(record,'actual-timer-after');}
  item.returnedAtNs=now();emit('original-watch-timer-return',{...item,resource:undefined});notify();
 });},destroy(asyncId){const item=timers.get(asyncId);if(!item)return;pass(()=>{
  item.destroyed=true;item.destroyedAtNs=now();emit('original-watch-timer-destroy',{...item,resource:undefined});notify();
 });}});hook.enable();
 fs.watch=function(...args){const originalStack=new Error('Actual original fs.watch registration').stack,
  sourceOwner=pass(()=>qualifyNativeWatch(originalStack));if(!sourceOwner)return Reflect.apply(originalWatch,this,args);
  const index=args.length-1,listener=args[index];if(typeof listener!=='function')return Reflect.apply(originalWatch,this,args);
  const registration={sourceOwner,originalStack,originalMethodRef:ref(originalWatch),listenerRef:ref(listener),
   listenerSource:Function.prototype.toString.call(listener),directory:String(args[0]),
   arguments:valueRecord(args.slice(0,-1)),registeredAtNs:now()};
  const wrapped=function(...values){const delivery={deliveryId:`${process.pid}:${threadId}:watch-delivery-${++nextDelivery}`,
    kind:'native',handleRef:registration.handleRef,registration,arguments:valueRecord(values),atNs:now()};
   emit('original-watch-delivery-enter',delivery);
   return deliveries.run(delivery,()=>{try{const result=Reflect.apply(listener,this,values);
    emit('original-watch-delivery-return',{deliveryId:delivery.deliveryId,return:valueRecord(result),returnRef:ref(result),atNs:now()});return result;
   }catch(error){emit('original-watch-delivery-throw',{deliveryId:delivery.deliveryId,error:errorValue(error),privateError:valueRecord(error),atNs:now()});throw error;}});
  };
  const received=args.slice();received[index]=wrapped;const result=Reflect.apply(originalWatch,this,received);
  registration.handleRef=ref(result);registration.wrapperRef=ref(wrapped);nativeHandles.set(result,registration);
  emit('original-watch-handle-created',registration);return result;
 };
 EventEmitter.prototype.emit=function(name,...args){
  if(!['ready','add','change','unlink','unlinkDir'].includes(name))return Reflect.apply(originalEmit,this,[name,...args]);
  const originalStack=new Error('Actual original watcher emit').stack,sourceOwner=pass(()=>qualifyEmitter(originalStack,this,name));
  if(!sourceOwner)return Reflect.apply(originalEmit,this,[name,...args]);
  const delivery={deliveryId:`${process.pid}:${threadId}:watch-delivery-${++nextDelivery}`,kind:'chokidar',
   emitterRef:ref(this),emitterConstructorRef:ref(this.constructor),emitterPrototypeRef:ref(Object.getPrototypeOf(this)),
   eventName:name,arguments:valueRecord(args),originalMethodRef:ref(originalEmit),
   originalStack,sourceOwner,atNs:now()};emit('original-watch-delivery-enter',delivery);
  let result;try{result=deliveries.run(delivery,()=>Reflect.apply(originalEmit,this,[name,...args]));}
  catch(error){emit('original-watch-delivery-throw',{deliveryId:delivery.deliveryId,error:errorValue(error),privateError:valueRecord(error),atNs:now()});throw error;}
  if(name==='ready')readyEvents.set(this,delivery);
  emit('original-watch-delivery-return',{deliveryId:delivery.deliveryId,return:valueRecord(result),returnRef:ref(result),atNs:now()});notify();return result;
 };
 function register(owner){if(owner.purpose!=='default')return{ownerRef:ref(owner),purpose:owner.purpose,absence:'original-transient-owner',closed:owner.closed??false};
  const watcher=owner.fileWatcher;if(!watcher)return{ownerRef:ref(owner),purpose:owner.purpose,absence:'original-no-local-file-watcher',closed:owner.closed??false};
  let record=owners.get(watcher);if(record)return record;
  record={owner,watcher,ownerRef:ref(owner),watcherRef:ref(watcher),facts:[]};owners.set(watcher,record);
  const original=watcher.markMemoryWatchDirty,body=Function.prototype.toString.call(original);
  const wrapped=function(...args){const before=this.watchTimer,delivery=deliveries.getStore()??null,
    fact={factId:`${process.pid}:${threadId}:watch-fact-${++nextFact}`,ownerRef:record.ownerRef,watcherRef:record.watcherRef,
     path:typeof args[0]==='string'?path.resolve(args[0]):null,arguments:valueRecord(args),argumentValues:args.map(valueRecord),argumentRefs:args.map(ref),delivery,
     originalMethodRef:ref(original),originalStack:new Error('Actual original watcher dirty fact').stack,enteredAtNs:now()};
   emit('original-watch-fact-enter',fact);const result=Reflect.apply(original,this,args);
   pass(()=>{fact.return=valueRecord(result);fact.returnRef=ref(result);fact.returnedAtNs=now();fact.pendingPaths=valueRecord(this.pendingWatchPaths);
    fact.timerRef=ref(this.watchTimer);record.facts.push(fact);attachTimer(record,this.watchTimer,'actual-fact-return');
    emit('original-watch-fact-return',fact);
    if(before&&before!==this.watchTimer)emit('original-watch-timer-replacement',{ownerRef:record.ownerRef,watcherRef:record.watcherRef,
     previousTimerRef:ref(before),nextTimerRef:ref(this.watchTimer),factId:fact.factId,atNs:now()});notify();});return result;
  };watcher.markMemoryWatchDirty=wrapped;restorations.push(()=>{watcher.markMemoryWatchDirty=original;});
  emit('original-watch-owner-binding',{ownerRef:record.ownerRef,watcherRef:record.watcherRef,sourceModule:'dist/file-watcher-DSOr6bb7.mjs',
   ownerConstructorRef:ref(owner.constructor),watcherConstructorRef:ref(watcher.constructor),watcherPrototypeRef:ref(Object.getPrototypeOf(watcher)),
   originalDirtyMethodRef:ref(original),observerDirtyMethodRef:ref(wrapped),originalDirtySource:body,originalDirtySha256:digest(Buffer.from(body)),
   onChangeRef:ref(watcher.callbacks.onChange),onChangeSource:Function.prototype.toString.call(watcher.callbacks.onChange),
   callbacksRef:ref(watcher.callbacks),syncMethodRef:ref(owner.sync),syncSource:Function.prototype.toString.call(owner.sync),
   syncSha256:digest(Buffer.from(Function.prototype.toString.call(owner.sync))),settings:valueRecord(owner.settings)});
  if(watcher.watchTimer)attachTimer(record,watcher.watchTimer,'owner-acquisition');return record;
 }
 async function ready(actualOwners,label){const receipt={protocol:'original-watch-effects-v5',label,kind:'ready',startedAtNs:now(),owners:[]};
  if(!actualOwners.size&&Array.from(actualOwners).length===0)receipt.absence='actual-no-acquired-original-owners';
  emit('original-watch-ready-enter',{...receipt});
  for(const owner of actualOwners){const record=register(owner);if(record.absence){receipt.owners.push(record);continue;}
   const watcher=record.watcher,starting=promiseRecord(watcher.starting,'watch-starting',record);if(!starting)fail('Original watcher startup Promise missing');
   await observePromise(starting);
   if(starting.settlement.status==='rejected')fail('Original watcher startup rejected');
   let ready=null;if(watcher.watcher){while(!(ready=readyEvents.get(watcher.watcher)))await changed();}
   const handles=watcher.nativeMemoryWatchPairs.flatMap(pair=>[pair.main,pair.parent,...(pair.treeWatchers?.values()??[])].map(value=>value?.watcher??value).filter(Boolean));
   const native=handles.map(handle=>{const registration=nativeHandles.get(handle);if(!registration)fail('Original native watch handle lacks source registration');return registration;});
   const row={ownerRef:record.ownerRef,watcherRef:record.watcherRef,starting:publicPromise(starting),
    chokidarRef:ref(watcher.watcher),ready,nativeHandles:native,capacityDegraded:watcher.capacityDegraded,atNs:now()};
   if(!ready&&!native.length)fail('No actual original ready watcher coverage');receipt.owners.push(row);record.ready=row;
  }receipt.finishedAtNs=now();emit('original-watch-ready-return',receipt);return receipt;
 }
 function factMatches(record,version){return record.facts.find(fact=>fact.path===version.path&&fact.delivery&&
  BigInt(fact.returnedAtNs)>=BigInt(version.committedAtNs)&&(
   version.kind==='deleted'?sourceReads.some(read=>read.path===version.path&&read.error?.code==='ENOENT'&&
    BigInt(read.finishedAtNs)>=BigInt(fact.enteredAtNs)):
   sourceReads.some(read=>read.path===version.path&&BigInt(read.finishedAtNs)>=BigInt(fact.enteredAtNs)&&
    read.size===String(version.stat.size)&&read.ino===String(version.stat.ino)&&read.dev===String(version.stat.dev)&&
    BigInt(version.stat.mtimeNs)%1_000_000n===0n&&read.mtimeMs===Number(BigInt(version.stat.mtimeNs)/1_000_000n))));}
 emit('original-watch-observer-installed',{protocol:'original-watch-effects-v5',fsWatchOriginalRef:ref(originalWatch),
  fsWatchObserverRef:ref(fs.watch),emitOriginalRef:ref(originalEmit),emitObserverRef:ref(EventEmitter.prototype.emit),
  originalThenRef:ref(originalThen),promiseClassRef:ref(Promise),promisePrototypeRef:ref(Promise.prototype),
  resourceTypes:['Timeout','PROMISE'],timersInvoked:false,syncMethodsWrapped:false,storage:'shared-per-thread-immutable-jsonl'});
 return{
  register,reference:ref,
  observeSourceRead(row){if(!row.sourceOwner||!row.originalStack.includes('snapshotPath'))return;
   pass(()=>{if(row.error){const read={...row,asyncId:executionAsyncId()};sourceReads.push(read);
     emit('original-watch-version-stat-throw',read);notify();return;}
    const actual=deserialize(Buffer.from(row.return.v8Hex,'hex'));
    const read={path:row.path,startedAtNs:row.startedAtNs,finishedAtNs:row.finishedAtNs,sourceOwner:row.sourceOwner,
     originalStack:row.originalStack,return:row.return,size:String(actual.size),ino:String(actual.ino),dev:String(actual.dev),
     mtimeMs:actual.mtimeMs,ctimeMs:actual.ctimeMs,asyncId:executionAsyncId()};
    sourceReads.push(read);emit('original-watch-version-stat-return',read);notify();});
  },
  ready,
  async waitForVersions(actualOwners,label,versions,interruptedSourceCalls=[]){
   if(!Array.isArray(interruptedSourceCalls)||interruptedSourceCalls.some(value=>value.kind!=='original-interrupted-source-call'||
     Object.hasOwn(value,'versions')||value.sourceMutationState!=='no-original-source-write-before-held-marker'))
    fail('An interrupted watcher reference is not a proved negative source-call receipt');
   const receipt={protocol:'original-watch-effects-v5',kind:'effects',label,versions:structuredClone(versions),
    interruptedSourceCalls:structuredClone(interruptedSourceCalls),
    ...(interruptedSourceCalls.length&&!versions.length?{outcome:'interrupted-before-source-publication'}:{}),startedAtNs:now(),owners:[]};
   emit('original-watch-effects-enter',receipt);
   if(!actualOwners.size&&Array.from(actualOwners).length===0)receipt.absence='actual-no-acquired-original-owners';
   for(const owner of actualOwners){const record=register(owner);if(record.absence){receipt.owners.push(record);continue;}
    if(!record.ready)fail('An actual watcher has not reached its declared readiness barrier');
    const selected=versions.filter(version=>version.path===owner.workspaceDir||version.path.startsWith(owner.workspaceDir+path.sep));
    const row={ownerRef:record.ownerRef,watcherRef:record.watcherRef,versions:selected,facts:[],states:[],promises:[],timers:[]};
    if(!selected.length){row.absence=interruptedSourceCalls.length?'original-call-interrupted-before-source-publication':'no-actual-declared-source-mutations';
     receipt.owners.push(row);continue;}
    for(const version of selected){let fact;while(!(fact=factMatches(record,version)))await changed();
     row.facts.push({versionId:version.versionId,factId:fact.factId,deliveryId:fact.delivery.deliveryId});}
    const seen=new Set();
    for(;;){const state=snapshot(record,'explicit-effects-await');row.states.push(state);
     const timer=attachTimer(record,record.watcher.watchTimer,'explicit-effects-await');
     if(timer&&!timer.fired&&!timer.destroyed){const pending=changed();if(!timer.fired&&!timer.destroyed)await pending;continue;}
     const pending=[record.watcher.reconciling,record.watcher.settling].filter(Boolean);
     for(const promise of pending){const item=promiseRecord(promise,'watch-owner-pending',record);seen.add(item);}
     const inner=records.filter(item=>item.kind==='watch-sync'&&item.delivery&&record.facts.some(fact=>fact.delivery?.deliveryId===item.delivery.deliveryId));
     for(const item of inner){if(item.ownerRef!==record.ownerRef||item.watcherRef!==record.watcherRef||
       item.onChangeRef!==ref(record.watcher.callbacks.onChange)||item.syncMethodRef!==ref(record.owner.sync))
       fail('Original watcher sync Promise lacks its actual owner/callback/timer lineage');seen.add(item);}
     if(seen.size>maxReferences||row.states.length>maxReferences)fail('Actual watcher effects exceed declared reference capacity');
     const unsettled=Array.from(seen).filter(item=>!item.settlement);if(unsettled.length){await Promise.all(unsettled.map(observePromise));continue;}
     if(record.watcher.watchTimer||record.watcher.reconciling||record.watcher.settling)continue;
     if(record.watcher.pendingChange||record.watcher.pendingWatchPaths.size||record.watcher.pendingReconciliations.size||record.watcher.reconcileAll)
      fail('Original watcher retains admitted work without its original queued timer or Promise');
     row.promises=Array.from(seen,item=>({...publicPromise(item),settlement:item.settlement}));
     if(!row.promises.some(item=>item.kind==='watch-sync'))fail('An applicable delivered source version lacks its actual original watch sync Promise');
     row.timers=Array.from(timers.values()).filter(item=>item.watcherRef===record.watcherRef).map(({resource,...item})=>({...item}));break;
    }row.finishedAtNs=now();receipt.owners.push(row);
   }receipt.finishedAtNs=now();emit('original-watch-effects-return',receipt);return receipt;
  },
  stop(){hook.disable();fs.watch=originalWatch;EventEmitter.prototype.emit=originalEmit;for(const restore of restorations.reverse())restore();},
 };
}

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

export function installSourceClock({workspaceDir,actor,ticksByCall,event=()=>{},qualifyStack,captureVersions=false}){
 if(!path.isAbsolute(workspaceDir)||!ticksByCall||typeof qualifyStack!=='function')throw Error('A source clock requires explicit owned inputs and source authority');
 const original=Object.fromEntries(['open','writeFile','rename','unlink','stat','lstat','readFile'].map(name=>[name,fsp[name]]));
 const handles=new WeakMap(),handleRecords=[],stages=new Map(),restorations=[],rows=[],failures=[],versions=new Map(),completedVersions=new Map();
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
  handles.set(handle,record);handleRecords.push(record);if(record.stage)stages.set(filename,record);
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
   path:filename,method:name,sourceOwner,originalStack:stack,startedAtNs:entered,finishedAtNs:now(),return:valueRecord(value)};rows.push(row);emit(row.event,row);},error=>{
    if(!captureVersions)return;const row={event:'source-clock-read-throw',actor,callKey,path:filename,method:name,sourceOwner,
     originalStack:stack,startedAtNs:entered,finishedAtNs:now(),error:errorValue(error),privateError:valueRecord(error),
     errorOwnProperties:Reflect.ownKeys(error).map(key=>{const descriptor=Object.getOwnPropertyDescriptor(error,key);return{
      key:typeof key==='symbol'?{symbolDescription:key.description}:key,enumerable:descriptor.enumerable,configurable:descriptor.configurable,
      ...(Object.hasOwn(descriptor,'value')?{value:valueRecord(descriptor.value)}:{accessor:true})};})};rows.push(row);emit(row.event,row);
   });return result;
 };
 return{
  currentCall:()=>currentScope(),
  capturePendingSourceState(){const active=currentScope();if(!captureVersions||!active||active.completed)
    throw Error('An interrupted source cutoff requires the actual pending V5 business call');
   return{kind:'original-source-call-cutoff',callKey:active.key,actor,causalFrame:structuredClone(active.causalFrame),
    completed:false,cutoffAtNs:now(),before:Array.from(active.before,([path,value])=>({path,...structuredClone(value)})),
    commits:Array.from(active.commits.values(),value=>structuredClone(value)),
    deletions:Array.from(active.deletions),handles:handleRecords.filter(record=>record.scope===active.key).map(record=>({
     handleRef:record.handleRef,path:record.path,stage:record.stage,scope:record.scope,open:structuredClone(record.open),
     writes:structuredClone(record.writes),syncs:structuredClone(record.syncs),close:record.close?structuredClone(record.close):null})),
    receipts:structuredClone(rows.filter(row=>row.callKey===active.key)),
    failures:structuredClone(failures.filter(row=>row.callKey===active.key))};
  },
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
    if(captureVersions){const captured=[];
    for(const[filename,control]of active.commits){if(active.deletions.has(filename))continue;const actual=after.get(filename);
     if(!actual||actual.sha256!==control.after.sha256)throw Error('A completed original source version was superseded before its call boundary');
     const value={kind:'file',path:filename,sha256:actual.sha256,stat:actual.stat,controlId:control.controlId,
      committedAtNs:control.rename?.returnedAtNs??control.close?.finishedAtNs??control.finishedAtNs,
      actor,callKey:active.key,causalFrame:active.causalFrame};value.versionId=digest(Buffer.from(JSON.stringify(value)));captured.push(value);
    }
    for(const filename of active.deletions){if(after.has(filename))throw Error('A completed original deletion was replaced before its call boundary');
     const deletion=rows.findLast(item=>item.event==='source-clock-deletion'&&item.callKey===active.key&&item.path===filename);
     const value={kind:'deleted',path:filename,committedAtNs:deletion.atNs,actor,callKey:active.key,causalFrame:active.causalFrame};
     value.versionId=digest(Buffer.from(JSON.stringify(value)));captured.push(value);
    }
    completedVersions.set(active.key,{callKey:active.key,actor,causalFrame:active.causalFrame,
     capturedAtNs:row.atNs,versions:captured,boundary:row});}
   }catch(error){failure('source-clock-exit-read-failed',{error:errorValue(error)});}finally{active.completed=true;scopes.enterWith(null);}
  },
  blocked:()=>failures.length>0,receipts:()=>rows,failures:()=>failures,
  captureCompletedVersions(key){const actual=completedVersions.get(key);if(!actual)throw Error('Original source call has not reached its actual completion boundary');
   return structuredClone(actual);},
  restore(){for(const name of Object.keys(original))fsp[name]=original[name];for(const restore of restorations.reverse())restore();},
 };
}
