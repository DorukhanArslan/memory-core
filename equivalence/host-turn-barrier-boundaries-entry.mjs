import fs from 'node:fs/promises';
import {createHash} from 'node:crypto';
const context=JSON.parse(await fs.readFile(process.env.MEMORY_EQ_RELEASE_CONTEXT,'utf8'));
let stdin='';for await(const chunk of process.stdin)stdin+=chunk;
const profile=context.hostTurnBarrierBoundariesProfile;
let returned;
try{
 if(createHash('sha256').update(stdin).digest('hex')!==profile.caseWireSha256)throw Error('The whole turn-barrier literal changed');
 const testCase=JSON.parse(stdin);
 if(Object.keys(testCase).sort().join()!=='id,input,operation'||testCase.id!==profile.caseId||testCase.operation!==profile.operation||testCase.input.nowMs!==profile.clockNowMs)throw Error('Wrong protected turn-barrier input');
 const {runHostTurnBarrierBoundariesRuntime}=await import('./host-turn-barrier-boundaries-runtime.mjs');
 const result=await runHostTurnBarrierBoundariesRuntime(testCase.input,{runtimeRoot:context.runtime.runtimeRoot,evidenceDirectory:context.evidenceDirectory,stateDirectory:context.stateDirectory,configPath:context.configPath,leaseHelper:context.leaseFixture?.helper??null,leasePython:context.leaseFixture?.python??null});
 returned={id:testCase.id,ok:true,result};
}catch(error){returned={id:profile.caseId,ok:false,error:{name:error.name,message:error.message,stack:error.stack}};process.exitCode=2;}
await new Promise((resolve,reject)=>process.stdout.write(JSON.stringify(returned)+'\n',error=>error?reject(error):resolve()));
// The CLI has completed actual teardown and flushed its single output carrier.
// Original background host handles do not own this offline process lifetime.
process.exit(process.exitCode ?? 0);
