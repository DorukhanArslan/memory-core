"""Rebuild each interrupted caller observation from the immutable note and SQLite image."""
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import tempfile

from equivalence import forget_lineage_bindings as owners
from equivalence.dream_light import canonical
from equivalence.recovery_artifact_evidence import _blobs, require, same
from equivalence.recovery_failure import validate_case
from equivalence.recovery_failure_sdk import MESSAGE, TRIGGER

# Function bodies are independently sealed as well as their enclosing published modules.
EXPORTS = (
    ('dist/plugin-sdk/config-runtime.js', 'setRuntimeConfigSnapshot', 'setRuntimeConfigSnapshot', 'ee68b6b8007df7f1a01ca28cf9a384937a9e3d58dbdf224128767af2a461244a'),
    ('dist/plugin-sdk/config-runtime.js', 'clearRuntimeConfigSnapshot', 'clearRuntimeConfigSnapshot', '52791a5f856774e3908fffc901c66b0dc07da073028967a9866c9fabdc9de4cf'),
    ('dist/extensions/memory-core/runtime-api.js', 'configureMemoryCoreDreamingState', 'configureMemoryCoreDreamingState', '7c97cd878aa65b0ee17367683050f50530df0656d54ab52e3e6f0c2d92e279cc'),
    ('dist/plugin-sdk/plugin-state-store-runtime.js', 'createPluginStateKeyedStore', 'createPluginStateKeyedStore', '3c4f0e6163afd4d4f9462fe11b1c18410332764b5ea591361ed6c66034d0c203'),
    ('dist/cli.runtime-CVRN4xUp.mjs', 'runMemoryForget', 'runMemoryForget', 'a46afcd698103b992f817c9116408e14d02a35038f0e37784d96c568d8c57f3a'),
    ('dist/memory-entry-origins-BCQSIB3X.mjs', 'a', 'recordMemoryEntryOrigins', '37f5fef0ba36e38d8e2d08ad059ed6acb7ef5d74e4aa5700bee35a4b8b3bb1cd'),
    ('dist/openclaw-agent-db.paths-Dv3PPTNK.mjs', 'c', 'resolveOpenClawAgentSqlitePath', 'ce90abbe92b20dabbf96287817e95c28c7c6ffd6594dd5766e369cee64e20f08'),
    ('dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs', 's', 'closeOpenClawAgentDatabasesAsync', '129bc877b44a960d9c41bf678f2627f1e3969755b8426e9b34cd3385bddf5260'),
    ('dist/openclaw-state-db-cache-IdIaBoUp.mjs', 'a', 'closeOpenClawStateDatabaseAsync', '8740c6af7f300ffc41378d3509e3bb6f90dd96c8e4cb2bf989c8418a140efa43'),
)


def _state(image, memory):
    require(image.startswith(b"SQLite format 3\x00"), "Expected an actual recoverable SQLite image")
    with tempfile.TemporaryDirectory(prefix="replay-forget-interruption-") as root:
        filename=Path(root)/"image.sqlite"
        filename.write_bytes(image)
        with closing(sqlite3.connect(filename.as_uri()+"?mode=ro&immutable=1",uri=True)) as db:
            db.row_factory=sqlite3.Row
            db.execute("PRAGMA trusted_schema=OFF")
            for table in ("memory_entry_origins","memory_session_tombstones"):
                require(db.execute("SELECT type FROM sqlite_master WHERE name=?",(table,)).fetchone()[0]=="table",
                        "Retained store replaced a durable table")
            origins=[dict(row) for row in db.execute("SELECT * FROM memory_entry_origins ORDER BY entry_key,agent_id,session_id")]
            markers=[dict(row) for row in db.execute("SELECT * FROM memory_session_tombstones ORDER BY session_id,agent_id")]
            trigger=db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",(TRIGGER,)).fetchone()
            return {"memory":memory.decode(),"origins":origins,"tombstones":markers,"armed":bool(trigger)}, trigger[0] if trigger else None


def _validate(case,public,snapshots,directory,native,archived):
    validate_case(case)
    raw,=snapshots
    inp=case["input"]
    same(raw["input"],inp,"Wrong original interrupted publisher input")
    name="native-raw.json" if native else "python-raw.json"
    directory=Path(directory).resolve(strict=True)
    wire=directory/name
    require(wire.is_file() and not wire.is_symlink() and wire.stat().st_size<1024**2, "Missing bounded failure capture")
    same(json.loads(wire.read_bytes()),snapshots,"Interruption capture changed")
    root=Path(raw["root"])
    require(root.is_absolute() and (archived or root.parent==directory),"Unbound interrupted workspace")
    relative="state/agents/main/agent/openclaw-agent.sqlite" if native else "memory.sqlite"
    require(Path(raw["database"])==root/relative, "Wrong independently reopened database")
    if native:
        same(raw["env"],{"OPENCLAW_CONFIG_PATH":str(root/"openclaw.json"),"OPENCLAW_HOME":str(root),
             "OPENCLAW_STATE_DIR":str(root/"state")},"Unbound native runtime state")
        require(sha256(canonical(inp)).hexdigest()==raw["inputSha256"],"Native input identity changed")
    else:
        sdk=Path(__file__).resolve().parents[1]/"memory_core"
        names=("config.py","consolidation/forget.py","consolidation/origins.py","consolidation/promotion.py")
        same(raw["sdkFiles"],{p:sha256((sdk/p).read_bytes()).hexdigest() for p in names},"SDK owner changed")
    calls=list(raw["calls"])
    wanted=["forget","recordMemoryEntryOrigins" if native else "record","sql","forget",
            "closeOwners" if native else "reopenOwners","sql","forget","closeOwners" if native else "reopenOwners","forget"]
    same([c["kind"] for c in calls],wanted,"Original forget or restart missing")
    same(calls[1]["origins"],inp["origins"],"Original origins seed differs")
    edge="BEFORE INSERT ON memory_session_tombstones" if inp["cut"]=="before-marker" else "BEFORE DELETE ON memory_entry_origins"
    armed="CREATE TRIGGER "+TRIGGER+" "+edge+" BEGIN SELECT RAISE(ABORT, '"+MESSAGE+"'); END"
    same([calls[i]["statement"] for i in (2,5)],[armed,"DROP TRIGGER "+TRIGGER],"Fault injection changed")
    results={}
    for stage,index,session in (("seed",0,inp["previous"]),("forget",3,inp["session"]),
                                ("retry",6,inp["session"]),("repeat",8,inp["session"])):
        call=calls[index]
        same(call["args"],{"agent":inp["agentId"],"session":[session],"json":True} if native else
             {"agent_id":inp["agentId"],"session_ids":[session],"now_ms":inp["nowMs"]},"Wrong public caller")
        error=call["error"]
        if stage=="forget":
            if native:
                require(error["message"]=="Memory forget failed: "+MESSAGE and "runMemoryForget" in error["stack"] and
                        error["cause"]["message"]==MESSAGE and error["cause"]["errcode"]==1811 and
                        call["stdout"]=="","Original refusal was not the injected SQLite trigger")
            else:
                same(error,{"class":"IntegrityError","message":MESSAGE,"code":1811,"name":"SQLITE_CONSTRAINT_TRIGGER"},
                     "SDK refusal did not come from the fixture SQLite trigger")
                require(call["report"] is None,"Failed SDK reported success")
            results[stage]={"failure":MESSAGE,"report":None}
        else:
            require(error is None,"Unexpected forget failure")
            report=json.loads(call["stdout"]) if native else call["report"]
            require(report["agentId"]=="main" and report["sessionIds"]==[session] and report["dryRun"] is False,
                    "Original forget did not report the selected session")
            results[stage]={"failure":None,"report":report}
    same([r["stage"] for r in raw["stages"]],inp["stages"],"Missing interrupted operation stages")
    blobs=_blobs(raw)
    used=set()
    notes,opened=[],0
    for index,record in enumerate(raw["stages"]):
        stage=record["stage"]
        used.update((record["image"],record["note"]))
        state,actual_trigger=_state(blobs[record["image"]],blobs[record["note"]])
        opened+=1
        same(state,record["state"],"Independent SQLite or note differs from intercepted state")
        same(actual_trigger,armed if 1<=index<=3 else None,"A different trigger caused the refusal")
        same(record["result"],results.get(stage),"Original command output changed")
        notes.append({"stage":stage,"result":results.get(stage),"state":state})
    require(used==set(blobs),"Unreferenced physical artifacts")
    same(public,{"observations":notes},"Cannot reconstruct interrupted states")
    target_state=notes[2]["state"]
    keep_only="# Notes\n\n<!-- openclaw-memory-promotion:key-b -->\n- B owns the workshop.\n"
    same(notes[0]["state"]["memory"],inp["memory"],"Notes did not start intact")
    same(target_state["memory"],inp["memory"] if inp["cut"]=="before-marker" else keep_only,"Unexpected partial write")
    same([r["session_id"] for r in target_state["origins"]],["A","B"],"Origin cleanup failure removed a retry witness")
    same([r["session_id"] for r in target_state["tombstones"]],
         [inp["previous"]] if inp["cut"]=="before-marker" else ["A",inp["previous"]],"Wrong durable boundary")
    same(notes[3]["state"],target_state,"Cold owner changed interrupted state")
    same(notes[5]["state"],notes[6]["state"],"Reopening changed the completed retry")
    same(notes[6]["state"],notes[7]["state"],"The repeated forget changed durable state")
    require(notes[7]["state"]["memory"]==keep_only and [o["session_id"] for o in notes[7]["state"]["origins"]]==["B"]
            and [o["session_id"] for o in notes[7]["state"]["tombstones"]]==["A",inp["previous"]],
            "Retry did not finish the selected purge while preserving the independent note")
    return {"stages":len(notes),"sqliteImagesReopened":opened}


def validate_native(case,public,snapshots,directory,loaded,*,archived=False):
    raw,=snapshots
    for module, *_ in EXPORTS:
        require(("node_modules/openclaw",module) in loaded, "Missing actual original forget export")
    same(raw["owners"],[{"module":module,"alias":alias,"name":name,"sourceSha256":digest,
         "artifactSha256":owners.COMPILED_HASHES[module]} for module,alias,name,digest in EXPORTS],
         "Original forget export function or module bytes changed")
    return _validate(case,public,snapshots,directory,True,archived)


def validate_sdk(case,public,snapshots,directory,*,archived=False):
    return _validate(case,public,snapshots,directory,False,archived)
