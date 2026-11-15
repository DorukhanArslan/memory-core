"""Builtin-only asynchronous reply controls; no original release code executes."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


HELPER = Path(__file__).resolve().parents[2] / "equivalence/forget-index-fence-source-clock.mjs"


def _run(body):
    node = os.environ.get("MEMORY_EQ_NODE") or shutil.which("node")
    if node is None:
        pytest.skip("A local Node runtime is required for this builtin-only reply control")
    script = f"""
import assert from 'node:assert/strict';
import {{Worker,MessageChannel}} from 'node:worker_threads';
import {{EventEmitter}} from 'node:events';
import {{deserialize}} from 'node:v8';
import {{deferOriginalEventDelivery}} from {json.dumps(HELPER.as_uri())};
const rows=[],failures=[];
const onReceipt=(name,row)=>rows.push({{name,...row}});
const onControlFailure=error=>failures.push(error);
{body}
process.stdout.write(JSON.stringify({{kind:'builtin-only-async-reply',originalReleaseModulesImported:false}})+'\\n');
"""
    environment = {key: value for key, value in os.environ.items()
                   if key != "NODE_OPTIONS" and not key.startswith("MEMORY_EQ_")}
    result = subprocess.run([node, "--input-type=module", "--eval", script], env=environment,
                            capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "kind": "builtin-only-async-reply", "originalReleaseModulesImported": False,
    }


def test_real_worker_reply_hold_keeps_timer_messageport_and_mainloop_live_then_delivers_same_once():
    _run("""
const nativeEmit=Worker.prototype.emit;
let release,heldResolve;const releasePromise=new Promise(resolve=>release=resolve);
const heldPromise=new Promise(resolve=>heldResolve=resolve);
const worker=new Worker(`const {parentPort}=require('node:worker_threads');
 parentPort.on('message',()=>{}); // retain the genuine local worker until explicit teardown
 parentPort.postMessage({status:'ok',taskId:73,value:{kind:'keyword',body:{rows:[{text:'actual local reply'}]}}});`,{eval:true,execArgv:[]});
let calls=0,received=0,heldMessage,control;
const actualEmit=function(...args){calls++;assert.equal(this,worker);assert.equal(args[1],heldMessage);
 assert.equal(args[1].taskId,73);return Reflect.apply(nativeEmit,this,args);};
worker.emit=function(name,message,...args){
 if(name!=='message')return Reflect.apply(nativeEmit,this,[name,message,...args]);
 heldMessage=message;
 control=deferOriginalEventDelivery({receiver:this,originalEmit:actualEmit,eventName:name,message,args,
  awaitRelease:()=>releasePromise,onReceipt,onControlFailure});
 heldResolve();
 // No actual original emit has run; this interceptor claims no original return.
};
worker.on('message',message=>{received++;assert.equal(message,heldMessage);});
await heldPromise;
assert.equal(calls,0);assert.equal(received,0);
const {port1,port2}=new MessageChannel();let timer=false,immediate=false,broker=false;
const brokerDone=new Promise(resolve=>port1.once('message',value=>{assert.equal(value,'actual-port-callback');broker=true;resolve();}));
port2.postMessage('actual-port-callback');
await Promise.all([brokerDone,new Promise(resolve=>setTimeout(()=>{timer=true;resolve();},0)),
 new Promise(resolve=>setImmediate(()=>{immediate=true;resolve();}))]);
assert.equal(timer&&immediate&&broker,true);assert.equal(calls,0);assert.equal(received,0);
release();assert.equal(await control.completion,true);
await new Promise(resolve=>setImmediate(resolve));
assert.equal(calls,1);assert.equal(received,1);assert.equal(failures.length,0);
assert.deepEqual(rows.map(row=>row.name),['delivery-enter','delivery-return']);
assert.equal(deserialize(Buffer.from(rows[0].message.v8Hex,'hex')).taskId,73);
assert.equal(deserialize(Buffer.from(rows[1].actualReturn.v8Hex,'hex')),true);
port1.close();port2.close();await worker.terminate();
""")


def test_deferred_original_false_return_is_retained_without_fabricating_listener_success():
    _run("""
const receiver=new EventEmitter(),message={taskId:1,value:{kind:'keyword'}};
let calls=0,release;const pending=new Promise(resolve=>release=resolve);
const originalEmit=function(...args){calls++;assert.equal(this,receiver);assert.equal(args[1],message);
 return EventEmitter.prototype.emit.apply(this,args);};
const control=deferOriginalEventDelivery({receiver,originalEmit,eventName:'message',message,args:[],
 awaitRelease:()=>pending,onReceipt,onControlFailure});
assert.equal(calls,0);release();assert.equal(await control.completion,false);assert.equal(calls,1);
assert.equal(deserialize(Buffer.from(rows[1].actualReturn.v8Hex,'hex')),false);assert.equal(failures.length,0);
""")


def test_actual_original_delivery_error_object_is_retained_and_not_replaced():
    _run("""
const receiver=new EventEmitter(),message={taskId:1},actual=new Error('Labelled original listener failure');
receiver.on('message',()=>{throw actual;});
const control=deferOriginalEventDelivery({receiver,originalEmit:EventEmitter.prototype.emit,eventName:'message',message,args:[],
 awaitRelease:async()=>{},onReceipt,onControlFailure});
let caught;try{await control.completion;}catch(error){caught=error;}
assert.equal(caught,actual);assert.deepEqual(rows.map(row=>row.name),['delivery-enter','delivery-throw']);
assert.equal(deserialize(Buffer.from(rows[1].privateError.v8Hex,'hex')).message,actual.message);
assert.equal(failures.length,0);
""")


def test_failed_control_never_invents_release_delivery_or_public_return():
    _run("""
const receiver=new EventEmitter(),actual=new Error('Labelled control failure');let calls=0;
const control=deferOriginalEventDelivery({receiver,originalEmit(){calls++;return true;},eventName:'message',message:{taskId:1},args:[],
 awaitRelease:async()=>{throw actual;},onReceipt,onControlFailure});
let caught;try{await control.completion;}catch(error){caught=error;}
assert.equal(caught,actual);assert.equal(failures[0],actual);assert.equal(calls,0);assert.equal(rows.length,0);
""")
