// The original manager/facade owns all diagnostics, parsing, repair and retrieval.
// This closed fixture only prepares sources, applies its declared metadata edit,
// calls original APIs and observes their complete returns and physical SQLite.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
import {pathToFileURL} from 'node:url';
import {isDeepStrictEqual} from 'node:util';

const plain=value=>JSON.parse(JSON.stringify(value));
const optionsCarrier=value=>JSON.parse(JSON.stringify(value,(_key,item)=>
  typeof item==='function'?{nativeCallback:true,name:item.name}:
  item instanceof AbortSignal?{nativeAbortSignal:true,aborted:item.aborted}:item));
const sha=value=>crypto.createHash('sha256').update(value).digest('hex');
const sqlValue=value=>typeof value==='bigint'?{sqliteInt64:value.toString()}:
  value instanceof Uint8Array?{sqliteBlobHex:Buffer.from(value).toString('hex')}:value;
const details=envelope=>{
  const transported=plain(envelope);
  if(!transported||!Array.isArray(transported.content)||transported.content[0]?.type!=='text'||
    !isDeepStrictEqual(JSON.parse(transported.content[0].text),transported.details)){
    throw Error('The original complete tool text carrier differs from its details');
  }
  return transported.details;
};

export async function runIndexIdentityBoundariesRuntime(input,config){
  const base=config.stateDirectory,workspace=path.join(base,'workspace');
  const raw={kind:'index-identity-boundaries',engine:'native',input:plain(input),
    caseId:config.caseId,pid:process.pid,ppid:process.ppid,fixtureBase:base,
    events:[],owners:{},statusCalls:[],snapshots:[],toolCalls:{},
    originalGetCalls:[],originalSearchCalls:[],diagnosticStatusCalls:{inspection:[],searchOwner:[]}};
  let sequence=0,phase='setup',requestLabel=null,activeTool=null,dbPath;
  let producer,inspection,searchOwner,OriginalManager,originalGet,closeAll;
  const refs=new WeakMap(),returnedManagers=new Map();let nextRef=0;
  const ref=owner=>{if(!owner)return null;if(!refs.has(owner))refs.set(owner,`owner-${++nextRef}`);return refs.get(owner);};
  const event=(name,fields={})=>{
    const row={event:name,sequence:++sequence,atNs:process.hrtime.bigint().toString(),phase,...fields};
    raw.events.push(row);return row;
  };
  const persist=()=>fs.writeFileSync(path.join(config.evidenceDirectory,'native-raw.json'),JSON.stringify([raw])+'\n');
  function physical(label){
    const entered=event('physical-sql-read-enter',{label});
    const db=new DatabaseSync(dbPath,{readOnly:true});let value;
    try{
      db.exec('BEGIN');
      const schema=db.prepare("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name LIKE 'memory_index_%' ORDER BY type,name").all();
      const tables={};
      for(const table of schema.filter(row=>row.type==='table')){
        tables[table.name]=db.prepare('SELECT * FROM "'+table.name.replaceAll('"','""')+'"').all()
          .map(row=>Object.fromEntries(Object.entries(row).map(([key,item])=>[key,sqlValue(item)])));
      }
      value={dbPath,schema,tables};
    }finally{db.exec('ROLLBACK');db.close();}
    const returned=event('physical-sql-read-return',{label});
    const serializedJSON=JSON.stringify(value);
    const snapshot={label,enterSeq:entered.sequence,returnSeq:returned.sequence,
      startedAtNs:entered.atNs,finishedAtNs:returned.atNs,...value,
      serializedJSON,sha256:sha(serializedJSON)};
    raw.snapshots.push(snapshot);return snapshot;
  }
  function source(){
    const relative='MEMORY.md',filename=path.join(workspace,relative),data=fs.readFileSync(filename);
    const stat=fs.lstatSync(filename);
    if(!stat.isFile()||stat.isSymbolicLink()||stat.nlink!==1)throw Error('The owned source is no longer a regular fixture file');
    return{path:relative,kind:'file',text:data.toString('utf8'),hex:data.toString('hex')};
  }
  function observe(owner,name){
    const ownerId=ref(owner);
    raw.owners[name]={ownerId,purpose:owner.purpose,settings:plain(owner.settings),
      providerInitializedAtAcquisition:owner.providerInitialized,constructorName:owner.constructor.name};
    const originalStatus=owner.status,originalSearch=owner.search;
    owner.status=function(...args){
      const entered=event('original-status-enter',{ownerId,requestLabel,activeTool,
        receiverIsExactObservedOwner:this===owner,providerInitialized:this.providerInitialized});
      const result=originalStatus.apply(this,args),captured=plain(result);
      const returned=event('original-status-return',{ownerId,requestLabel,activeTool,
        receiverIsExactObservedOwner:this===owner,providerInitialized:this.providerInitialized});
      raw.statusCalls.push({id:`status-${raw.statusCalls.length+1}`,ownerId,phase,requestLabel,activeTool,
        enterSeq:entered.sequence,returnSeq:returned.sequence,startedAtNs:entered.atNs,finishedAtNs:returned.atNs,
        receiverIsExactObservedOwner:this===owner,result:captured});
      return result;
    };
    owner.search=async function(...args){
      const entered=event('original-search-enter',{ownerId,activeTool,
        receiverIsExactObservedOwner:this===owner,providerInitialized:this.providerInitialized});
      const call={id:`search-${raw.originalSearchCalls.length+1}`,ownerId,phase,activeTool,
        query:args[0],optionKeys:Object.keys(args[1]??{}),options:optionsCarrier(args[1]??{}),enterSeq:entered.sequence,
        startedAtNs:entered.atNs,receiverIsExactObservedOwner:this===owner};
      raw.originalSearchCalls.push(call);
      try{
        const returned=await originalSearch.apply(this,args);call.result=plain(returned);return returned;
      }catch(error){call.error={name:error.name,message:error.message};throw error;}
      finally{
        const returned=event('original-search-return',{ownerId,activeTool,
          receiverIsExactObservedOwner:this===owner,providerInitialized:this.providerInitialized});
        call.returnSeq=returned.sequence;call.finishedAtNs=returned.atNs;
      }
    };
    return owner;
  }
  function status(owner,label){
    requestLabel=label;
    try{
      const value=plain(owner.status()),call=raw.statusCalls.at(-1);
      if(call.requestLabel!==label||!isDeepStrictEqual(value,call.result))throw Error('Status carrier was detached from its original return');
      return{value,callId:call.id};
    }finally{requestLabel=null;}
  }
  async function close(owner,label){
    const entered=event('original-close-enter',{ownerId:ref(owner),label});
    const returned=await owner.close();
    const finished=event('original-close-return',{ownerId:ref(owner),label,
      returnedUndefined:returned===undefined,closed:owner.closed,closing:owner.closing});
    raw.owners[label].close={enterSeq:entered.sequence,returnSeq:finished.sequence,
      startedAtNs:entered.atNs,finishedAtNs:finished.atNs,returnedUndefined:returned===undefined,
      closed:owner.closed,closing:owner.closing};
  }
  async function toolCall(tool,label,args){
    activeTool=label;
    const entered=event('actual-tool-enter',{label,args:plain(args)});
    const call={label,args:plain(args),enterSeq:entered.sequence,startedAtNs:entered.atNs};
    raw.toolCalls[label]=call;
    try{const envelope=await tool.execute(`identity-${label}`,plain(args));
      call.nativeDetailsOwnKeys=Object.keys(envelope.details??{});
      call.nativeDetailsUndefinedOwnKeys=Object.keys(envelope.details??{}).filter(key=>envelope.details[key]===undefined);
      call.nativeEnvelopeSerializedJSON=JSON.stringify(envelope);call.envelope=plain(envelope);return details(envelope);}
    catch(error){call.error={name:error.name,message:error.message};throw error;}
    finally{const returned=event('actual-tool-return',{label});call.returnSeq=returned.sequence;
      call.finishedAtNs=returned.atNs;activeTool=null;}
  }
  try{
    fs.mkdirSync(workspace,{recursive:true});
    for(const[relative,text]of Object.entries(input.files)){
      if(relative!=='MEMORY.md')throw Error('Only the independently frozen root source is admitted');
      fs.writeFileSync(path.join(workspace,relative),text,{flag:'wx'});
      fs.utimesSync(path.join(workspace,relative),input.sourceMtimeMs/1000,input.sourceMtimeMs/1000);
    }
    raw.sourceBefore=source();event('source-fixture-finished');
    const cfg={...plain(input.config),agents:{defaults:{workspace}}};raw.requestedConfig=plain(cfg);
    const imp=relative=>import(pathToFileURL(path.join(config.runtimeRoot,relative)).href);
    const managerModule=await imp('dist/extensions/memory-core/manager-runtime.js');
    OriginalManager=managerModule.MemoryIndexManager;closeAll=managerModule.closeAllMemoryIndexManagers;
    const api=await imp('dist/extensions/memory-core/runtime-api.js');
    const{createPluginStateKeyedStore}=await imp('dist/plugin-sdk/plugin-state-store-runtime.js');
    api.configureMemoryCoreDreamingState(options=>createPluginStateKeyedStore('memory-core',options));
    const{createMemorySearchTool}=await imp('dist/tools-DotaQGXh.mjs');
    originalGet=OriginalManager.get;
    OriginalManager.get=async function(...args){
      const params=args[0];
      const invokingTool=activeTool,observed=invokingTool==='seed'?producer:invokingTool==='query'?searchOwner:null;
      const entered=event('original-get-enter',{activeTool,agentId:params.agentId,
        requestedPurpose:params.purpose??'default',receiverIsOriginalClass:this===OriginalManager});
      const call={id:`get-${raw.originalGetCalls.length+1}`,phase,activeTool,agentId:params.agentId,
        requestedPurpose:params.purpose??'default',config:plain(params.cfg),enterSeq:entered.sequence,
        startedAtNs:entered.atNs,receiverIsOriginalClass:this===OriginalManager,
        parameterKeys:Object.keys(params),maintenanceSourceOwnerId:ref(params.maintenanceSource),
        maintenanceSourceIsExactSampledOwner:observed?params.maintenanceSource===observed:null};
      raw.originalGetCalls.push(call);
      try{
        const owner=await originalGet.apply(this,args);
        call.ownerId=ref(owner);call.actualPurpose=owner?.purpose??null;
        if(owner)returnedManagers.set(call.ownerId,owner);
        call.returnedIsExactSampledOwner=observed?owner===observed:null;
        return owner;
      }catch(error){call.error={name:error.name,message:error.message};throw error;}
      finally{const returned=event('original-get-return',{activeTool:invokingTool,ownerId:call.ownerId,
        returnedIsExactSampledOwner:call.returnedIsExactSampledOwner});
        call.returnSeq=returned.sequence;call.finishedAtNs=returned.atNs;}
    };
    const acquire=async purpose=>{
      const result=await api.getMemorySearchManager({cfg,agentId:input.identity.agentId,purpose});
      if(!result.manager)throw Error(`Original facade acquisition failed: ${result.error??'no manager'}`);
      return result.manager;
    };
    const makeTool=()=>{
      const tool=createMemorySearchTool({config:cfg,...plain(input.toolOptions)});
      if(!tool)throw Error('The original public memory_search factory returned no tool');return tool;
    };
    phase='producer-acquisition';producer=observe(await acquire('default'),'producer');
    phase='seed-publication';
    const seedEntered=event('original-sync-enter',{ownerId:ref(producer),args:{reason:'cli'}});
    const syncResult=await producer.sync({reason:'cli'});
    raw.seedPublication={ownerId:ref(producer),args:{reason:'cli'},enterSeq:seedEntered.sequence,
      returnSeq:event('original-sync-return',{ownerId:ref(producer),returnedUndefined:syncResult===undefined}).sequence,
      returnedUndefined:syncResult===undefined};
    const published=status(producer,'seed-after-publication');dbPath=published.value.dbPath;
    physical('seed-after-publication');
    phase='seed-search';const seedSearch=await toolCall(makeTool(),'seed',input.seed.baselineSearch);
    if(!Array.isArray(seedSearch.results)||!seedSearch.results.length)throw Error('The actual pre-mutation positive-control search returned no published source');
    physical('seed-after-search');
    phase='seed-close';await close(producer,'producer');physical('seed-after-close');
    phase='metadata-mutation';physical('metadata-fixture-before');
    const mutation=input.metadataMutation,db=new DatabaseSync(dbPath);
    const mutationEntered=event('metadata-fixture-enter',{mutation:plain(mutation)});
    try{
      db.exec('BEGIN IMMEDIATE');
      const before=db.prepare("SELECT value FROM memory_index_meta WHERE key='memory_index_meta_v1'").get();
      if(typeof before?.value!=='string')throw Error('The original producer did not publish real metadata');
      raw.fixtureMutation={specification:plain(mutation),dbPath,before:before.value,
        enterSeq:mutationEntered.sequence,sql:'',parameters:[]};
      let info;
      if(mutation.kind==='delete-metadata-row'){
        raw.fixtureMutation.sql='DELETE FROM memory_index_meta WHERE key=?';raw.fixtureMutation.parameters=[mutation.key];
      }else if(mutation.kind==='replace-metadata-serialized'){
        raw.fixtureMutation.sql='UPDATE memory_index_meta SET value=? WHERE key=?';raw.fixtureMutation.parameters=[mutation.value,mutation.key];
      }
      else if(mutation.kind==='merge-metadata-fields'){
        const value=Object.assign(JSON.parse(before.value),plain(mutation.fields));
        raw.fixtureMutation.sql="UPDATE memory_index_meta SET value=? WHERE key='memory_index_meta_v1'";
        raw.fixtureMutation.parameters=[JSON.stringify(value)];
      }else if(mutation.kind!=='none')throw Error('Unrecognized frozen metadata fixture');
      if(raw.fixtureMutation.sql)info=db.prepare(raw.fixtureMutation.sql).run(...raw.fixtureMutation.parameters);
      raw.fixtureMutation.sqliteChanges=info?.changes??0;
      raw.fixtureMutation.after=db.prepare("SELECT value FROM memory_index_meta WHERE key='memory_index_meta_v1'").get()?.value??null;
      db.exec('COMMIT');raw.fixtureMutation.committed=true;
    }catch(error){if(db.isTransaction)db.exec('ROLLBACK');throw error;}
    finally{db.close();raw.fixtureMutation??={specification:plain(mutation)};
      raw.fixtureMutation.returnSeq=event('metadata-fixture-return').sequence;}
    physical('metadata-fixture-after');
    phase='inspection-acquisition';physical('inspection-before-open');
    inspection=observe(await acquire(input.diagnosticSchedule.nativeReadOnlyStatusPurpose),'inspection');physical('inspection-after-open');
    phase='inspection-read';const inspectionReads=[];
    for(let index=0;index<2;index++){
      const observed=status(inspection,`inspection-${index+1}`);inspectionReads.push(observed.value.custom.indexIdentity);
      raw.diagnosticStatusCalls.inspection.push(observed.callId);physical(`inspection-after-read-${index+1}`);
    }
    phase='inspection-close';await close(inspection,'inspection');physical('inspection-after-close');
    phase='search-owner-acquisition';physical('search-owner-before-open');
    searchOwner=observe(await acquire(input.diagnosticSchedule.searchManagerPurpose),'searchOwner');physical('search-owner-after-open');
    phase='search-owner-read';const searchReads=[];
    for(let index=0;index<2;index++){
      const observed=status(searchOwner,`search-owner-${index+1}`);searchReads.push(observed.value.custom.indexIdentity);
      raw.diagnosticStatusCalls.searchOwner.push(observed.callId);physical(`search-owner-after-read-${index+1}`);
    }
    phase='first-query';const search=await toolCall(makeTool(),'query',input.search);
    phase='after-query-status';const after=status(searchOwner,'after-query');
    raw.diagnosticStatusCalls.afterQuery=after.callId;physical('search-owner-after-query');
    phase='search-owner-close';await close(searchOwner,'searchOwner');physical('search-owner-after-close');
    raw.sourceAfter=source();
    raw.result={provider:'none',seedSearch,diagnostics:{inspection:inspectionReads,searchOwner:searchReads,
      afterQuery:after.value.custom.indexIdentity},search,source:raw.sourceAfter};
    raw.completed=true;return raw.result;
  }catch(error){raw.error={name:error.name,message:error.message,stack:error.stack};throw error;}
  finally{
    phase='teardown';
    event('runtime-close-all-enter',{returnedManagerIds:[...returnedManagers.keys()]});
    raw.runtimeCloseAllInvoked=typeof closeAll==='function';
    try{
      if(raw.runtimeCloseAllInvoked){await closeAll();raw.runtimeCloseAllReturned=true;}
      else raw.runtimeCloseAllReturned=false;
    }catch(error){raw.runtimeCloseAllReturned=false;raw.teardownError={name:error.name,message:error.message};}
    raw.finalManagerStates=[...returnedManagers].map(([ownerId,owner])=>({ownerId,
      purpose:owner.purpose,closed:owner.closed,closing:owner.closing}));
    raw.allManagersClosed=raw.finalManagerStates.length>0&&
      raw.finalManagerStates.every(owner=>owner.closed===true&&owner.closing===true);
    event('runtime-close-all-return',{returnedNormally:raw.runtimeCloseAllReturned,
      finalManagerStates:plain(raw.finalManagerStates),allManagersClosed:raw.allManagersClosed});
    if(OriginalManager&&originalGet)OriginalManager.get=originalGet;
    persist();
  }
}
