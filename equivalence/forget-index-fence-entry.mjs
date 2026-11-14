import fs from 'node:fs';
import {createHash} from 'node:crypto';
import {isDeepStrictEqual} from 'node:util';
const context=JSON.parse(fs.readFileSync(process.env.MEMORY_EQ_RELEASE_CONTEXT,'utf8'));
const profile=context.forgetIndexFenceProfile;
const actor=process.env.MEMORY_EQ_FIF_ACTOR??'coordinator';
if(actor==='coordinator'){
 let stdin='';for await(const part of process.stdin){stdin+=part;if(Buffer.byteLength(stdin)>4*1024*1024)throw Error('Excessive frozen fence input');}
 let output;
 try{
  if(createHash('sha256').update(stdin).digest('hex')!==profile.caseWireSha256)throw Error('Frozen original fence literal changed');
  const testCase=JSON.parse(stdin);
  if(Object.keys(testCase).sort().join()!=='id,input,operation'||testCase.id!==profile.caseId||testCase.operation!==profile.operation)throw Error('Wrong original fence input');
  const expectedClocks=Object.fromEntries(['coordinator','observer',...Object.keys(testCase.input.actors)].map(name=>[name,testCase.input.clock.nowMs]));
  if(!isDeepStrictEqual(testCase.input.gates,profile.gates)||!isDeepStrictEqual(profile.actorClocks,expectedClocks)||
   profile.recoveryNowMs!==testCase.input.clock.recoveryNowMs)throw Error('Fence capability substituted declared controls or wall phases');
  const {runForgetIndexFenceRuntime}=await import('./forget-index-fence-runtime.mjs');
  const result=await runForgetIndexFenceRuntime(testCase.input,{caseId:testCase.id,runtimeRoot:context.runtime.runtimeRoot,
   evidenceDirectory:context.evidenceDirectory,stateDirectory:context.stateDirectory,configPath:context.configPath,gateDirectory:context.gateDirectory});
  output={id:testCase.id,ok:true,result};
 }catch(error){output={id:profile.caseId,ok:false,error:{name:error.name,message:error.message,stack:error.stack}};process.exitCode=2;}
 globalThis[Symbol.for('memory.eq.forgetIndexFence')].flush();
 await new Promise((resolve,reject)=>process.stdout.write(JSON.stringify(output)+'\n',error=>error?reject(error):resolve()));
}else{
 let runtime;
 process.on('message',async message=>{
  try{
   if(message?.type==='initialize'){
    if(runtime||message.request.actor!==actor||message.request.caseId!==profile.caseId)throw Error('Wrong or repeated original actor initialization');
    const {runForgetIndexFenceActor}=await import('./forget-index-fence-runtime.mjs');
    runtime=await runForgetIndexFenceActor(message.request);
    process.send({type:'ready',actor,pid:process.pid,ppid:process.ppid,instance:Number(process.env.MEMORY_EQ_FIF_INSTANCE)});return;
   }
   if(message?.type!=='command'||!runtime)throw Error('Original actor command before initialization');
   const returned=await runtime.execute(message.command);
   process.send(returned,()=>{if(runtime.isExiting()){runtime.persist();process.disconnect();}});
  }catch(error){process.send?.({type:'fatal',actor,pid:process.pid,error:{name:error.name,message:error.message,stack:error.stack}});process.exitCode=2;}
 });
}
