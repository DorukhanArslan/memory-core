"""Synthetic local Node process controls; no original release owner is loaded."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
ACTOR = ROOT / "equivalence" / "forget-index-fence-runtime.mjs"


def _node():
    node = shutil.which("node")
    if node is None:
        pytest.skip("A local Node runtime is required for this synthetic process test")
    return node


def _environment():
    # A pure local fixture must never inherit the protected release preload.
    return {key: value for key, value in os.environ.items()
            if key != "NODE_OPTIONS" and not key.startswith("MEMORY_EQ_")}


def test_explicit_stop_exits_with_live_handle_after_actual_ipc_and_output_drain(tmp_path):
    child = tmp_path / "synthetic-stop-child.mjs"
    receipt = tmp_path / "synthetic-persist-count.txt"
    child.write_text("\n".join([
        "import fs from 'node:fs';",
        f"import {{finishGracefulActorExit}} from {json.dumps(ACTOR.as_uri())};",
        "setInterval(()=>{}, 10000); // deliberately referenced synthetic handle",
        "process.stdout.write('out-'.repeat(131072));",
        "process.stderr.write('err-'.repeat(65536));",
        "let persisted=0;",
        "const runtime={isExiting:()=>true,persist:()=>{",
        f" fs.writeFileSync({json.dumps(str(receipt))}, String(++persisted));",
        "}};",
        "await finishGracefulActorExit(runtime,{type:'settled',id:7,exiting:true,error:null});",
    ]), encoding="utf8")
    parent = "\n".join([
        "import {spawn} from 'node:child_process';",
        "import {createHash} from 'node:crypto';",
        f"const child=spawn(process.execPath,[{json.dumps(str(child))}],{{stdio:['ignore','pipe','pipe','ipc']}});",
        "const messages=[],out=[],err=[];",
        "child.on('message',message=>messages.push(message));",
        "child.stdout.on('data',chunk=>out.push(chunk));",
        "child.stderr.on('data',chunk=>err.push(chunk));",
        "child.on('close',(code,signal)=>{",
        " const bytes=Buffer.concat(out),errors=Buffer.concat(err);",
        " console.log(JSON.stringify({code,signal,messages,stdoutBytes:bytes.length,",
        "  stdoutSha256:createHash('sha256').update(bytes).digest('hex'),",
        "  stderrContainsBody:errors.includes(Buffer.from('err-'.repeat(65536)))}));",
        "});",
    ])
    result = subprocess.run([_node(), "--input-type=module", "-e", parent],
                            env=_environment(), text=True, capture_output=True, timeout=10, check=True)
    observed = json.loads(result.stdout)
    assert observed == {
        "code": 0, "signal": None,
        "messages": [{"type": "settled", "id": 7, "exiting": True, "error": None}],
        "stdoutBytes": len(b"out-" * 131072),
        "stdoutSha256": hashlib.sha256(b"out-" * 131072).hexdigest(),
        "stderrContainsBody": True,
    }
    assert receipt.read_text() == "2"


@pytest.mark.parametrize("exiting,settlement", [
    (False, {"exiting": True}),
    (True, {"exiting": False}),
    (True, {"exiting": True, "infrastructureError": {"message": "synthetic close failed"}}),
])
def test_explicit_exit_refuses_unclosed_or_failed_actor(exiting, settlement):
    script = "\n".join([
        f"import {{finishGracefulActorExit}} from {json.dumps(ACTOR.as_uri())};",
        f"const runtime={{isExiting:()=>{json.dumps(exiting)},persist:()=>{{throw Error('Unexpected persist');}}}};",
        "try {",
        f" await finishGracefulActorExit(runtime,{json.dumps(settlement)});",
        "} catch(error) { console.log(JSON.stringify({message:error.message})); }",
    ])
    result = subprocess.run([_node(), "--input-type=module", "-e", script],
                            env=_environment(), text=True, capture_output=True, timeout=10, check=True)
    assert json.loads(result.stdout) == {"message": "A graceful actor exit requires a completed explicit stop"}


@pytest.mark.parametrize("finish_after_ack,expected_code,expected_signal,deadline", [
    (True, 0, None, False),
    (False, None, "SIGKILL", True),
])
def test_observer_teardown_waits_actual_close_and_kills_only_after_real_deadline(
        tmp_path, finish_after_ack, expected_code, expected_signal, deadline):
    child = tmp_path / "synthetic-delayed-close-child.mjs"
    child.write_text("\n".join([
        "setInterval(()=>{}, 10000);",
        "process.send({type:'synthetic-close-ack'},()=>{",
        *([" setTimeout(()=>process.exit(0),30);"] if finish_after_ack else []),
        "});",
    ]), encoding="utf8")
    parent = "\n".join([
        "import {spawn} from 'node:child_process';",
        f"import {{awaitActualProcessClose}} from {json.dumps(ACTOR.as_uri())};",
        f"const child=spawn(process.execPath,[{json.dumps(str(child))}],{{stdio:['ignore','ignore','ignore','ipc']}});",
        "const closed=new Promise(resolve=>child.once('close',(code,signal)=>resolve({code,signal})));",
        "await new Promise(resolve=>child.once('message',resolve));",
        "let deadline=false;const started=performance.now();let exit;",
        f"try{{exit=await awaitActualProcessClose(closed,{1000 if finish_after_ack else 100});}}",
        "catch(error){",
        " if(error.code!=='FIF_PROCESS_CLOSE_TIMEOUT')throw error;",
        " deadline=true;child.kill('SIGKILL');exit=await closed;",
        "}",
        "console.log(JSON.stringify({...exit,deadline,elapsedMs:performance.now()-started}));",
    ])
    result = subprocess.run([_node(), "--input-type=module", "-e", parent],
                            env=_environment(), text=True, capture_output=True, timeout=10, check=True)
    observed = json.loads(result.stdout)
    assert {key: observed[key] for key in ("code", "signal", "deadline")} == {
        "code": expected_code, "signal": expected_signal, "deadline": deadline,
    }
    assert observed["elapsedMs"] >= (90 if deadline else 20)
