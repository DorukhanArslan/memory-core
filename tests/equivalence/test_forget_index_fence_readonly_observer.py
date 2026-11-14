"""Builtin-only observer protocol tests; no original release owner executes."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ACTOR = Path(__file__).resolve().parents[2] / "equivalence/forget-index-fence-runtime.mjs"


def _run(body):
    node = shutil.which("node")
    if node is None:
        pytest.skip("A local Node runtime is required for this builtin-only protocol test")
    script = f"""
import assert from 'node:assert/strict';
import {{deserialize}} from 'node:v8';
import {{captureOriginalTranscriptExportRead}} from {json.dumps(ACTOR.as_uri())};
const receipts=[],events=[],refs=new WeakMap();let nextRef=0;
const ref=value=>{{if(!refs.has(value))refs.set(value,++nextRef);return refs.get(value);}};
const event=(name,fields)=>{{const row={{name,...fields,sequence:events.length+1,atNs:process.hrtime.bigint().toString()}};events.push(row);return row;}};
const scope={{agentId:'labelled-agent',sessionId:'labelled-session',sessionKey:'labelled-key',storePath:'/labelled/store'}};
{body}
process.stdout.write(JSON.stringify({{kind:'builtin-only-observer-protocol',originalReleaseModulesImported:false}})+'\\n');
"""
    environment = {key: value for key, value in os.environ.items()
                   if key != "NODE_OPTIONS" and not key.startswith("MEMORY_EQ_")}
    result = subprocess.run([node, "--input-type=module", "--eval", script], env=environment,
                            capture_output=True, text=True, timeout=10, check=True)
    assert json.loads(result.stdout) == {
        "kind": "builtin-only-observer-protocol", "originalReleaseModulesImported": False,
    }


def test_observer_uses_actual_readonly_export_and_preserves_whole_result_and_events_identity():
    _run("""
const actual={events:[{type:'message',id:'labelled-event',message:{content:'literal local event'}}],
 stats:{eventCount:1,byteSize:77},sessionKey:'actual-key'};
let calls=0;
const accessor={
 loadTranscriptEventsSync(){throw Error('Writable readback must never enter this observer');},
 readTranscriptExportSnapshotReadOnlySync(received){
  assert.equal(this,accessor);assert.equal(received,scope);calls++;return actual;
 }
};
const result=captureOriginalTranscriptExportRead({accessor,scope,ref,event,receipts});
assert.equal(result,actual);assert.equal(result.events,actual.events);assert.equal(calls,1);
assert.equal(receipts.length,1);const receipt=receipts[0];
assert.equal(receipt.method,'readTranscriptExportSnapshotReadOnlySync');
assert.equal(receipt.methodRef,ref(accessor.readTranscriptExportSnapshotReadOnlySync));
assert.equal(receipt.ownerRef,ref(accessor));assert.deepEqual(receipt.scope,scope);
assert.deepEqual(receipt.result,actual);assert.notEqual(receipt.result,actual);
assert.deepEqual(deserialize(Buffer.from(receipt.privateReturn.v8Hex,'hex')),actual);
assert.equal(receipt.returnedUndefined,false);assert.equal(receipt.enterSeq,1);assert.equal(receipt.returnSeq,2);
assert(BigInt(receipt.finishedAtNs)>=BigInt(receipt.startedAtNs));
assert.deepEqual(events.map(row=>row.name),['original-transcript-export-read-enter','original-transcript-export-read-return']);
""")


def test_actual_absent_export_is_retained_without_fabricating_empty_events():
    _run("""
const accessor={readTranscriptExportSnapshotReadOnlySync(){return undefined;}};
assert.equal(captureOriginalTranscriptExportRead({accessor,scope,ref,event,receipts}),undefined);
assert.equal(receipts[0].returnedUndefined,true);assert.equal(Object.hasOwn(receipts[0],'result'),false);
assert.equal(receipts[0].privateReturn.type,'undefined');
assert.equal(deserialize(Buffer.from(receipts[0].privateReturn.v8Hex,'hex')),undefined);
assert.equal(events[1].threw,false);
""")


def test_actual_read_error_object_and_full_private_error_are_preserved():
    _run("""
const actual=Object.assign(new Error('Labelled genuine getter failure'),{code:'LABELLED_READ_FAILURE'});
const accessor={readTranscriptExportSnapshotReadOnlySync(){throw actual;}};
let caught;try{captureOriginalTranscriptExportRead({accessor,scope,ref,event,receipts});}catch(error){caught=error;}
assert.equal(caught,actual);assert.equal(receipts.length,1);assert.equal(receipts[0].error.code,actual.code);
assert.equal(receipts[0].error.message,actual.message);
assert.equal(deserialize(Buffer.from(receipts[0].privateError.v8Hex,'hex')).message,actual.message);
assert.equal(events[1].threw,true);assert.equal(receipts[0].returnSeq,2);
""")


def test_absent_readonly_callable_fails_before_another_read_route_or_fake_result():
    _run("""
const accessor={loadTranscriptEventsSync(){throw Error('Never enter writable fallback');}};
assert.throws(()=>captureOriginalTranscriptExportRead({accessor,scope,ref,event,receipts}),/read-only transcript export callable unavailable/);
assert.equal(receipts.length,0);assert.equal(events.length,0);
""")
