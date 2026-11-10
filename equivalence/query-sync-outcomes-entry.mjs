import fs from 'node:fs';
import {createHash} from 'node:crypto';
const context=JSON.parse(fs.readFileSync(process.env.MEMORY_EQ_RELEASE_CONTEXT,'utf8'));
const profile=context.querySyncOutcomesProfile;
let stdin='';for await(const part of process.stdin){stdin+=part;if(Buffer.byteLength(stdin)>1024*1024)throw Error('Excessive query-sync literal');}
let returned;
try{
  if(createHash('sha256').update(stdin).digest('hex')!==profile.caseWireSha256)throw Error('The frozen query-sync literal changed');
  const testCase=JSON.parse(stdin);
  if(Object.keys(testCase).sort().join()!=='id,input,operation'||testCase.id!==profile.caseId||
    testCase.operation!==profile.operation||testCase.input.nowMs!==profile.clockNowMs)throw Error('Wrong protected query-sync input');
  const {runQuerySyncOutcomesRuntime}=await import('./query-sync-outcomes-runtime.mjs');
  const result=await runQuerySyncOutcomesRuntime(testCase.input,{caseId:testCase.id,
    runtimeRoot:context.runtime.runtimeRoot,evidenceDirectory:context.evidenceDirectory,
    stateDirectory:context.stateDirectory,configPath:context.configPath});
  returned={id:testCase.id,ok:true,result};
}catch(error){returned={id:profile.caseId,ok:false,error:{name:error.name,message:error.message,stack:error.stack}};process.exitCode=2;}
await new Promise((resolve,reject)=>process.stdout.write(JSON.stringify(returned)+'\n',error=>error?reject(error):resolve()));
