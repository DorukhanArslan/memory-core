"""Drive the real SDK forget owner against a persistent, independently readable SQLite ledger."""
import base64
from contextlib import closing
import gzip
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import tempfile
import time
from unittest.mock import patch

from memory_core.config import MemoryConfig
from memory_core.consolidation.forget import forget_memory_entries
from memory_core.consolidation.origins import MemoryEntryOrigin, MemoryEntryOriginLedger

TRIGGER = "recovery_literal_cut"
MESSAGE = "frozen interrupted forget publication"


def run_interrupted_forget(case, directory):
    from equivalence.recovery_failure import validate_case
    validate_case(case)
    value = case["input"]
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(dir=directory, prefix="python-interrupted-forget-"))
    workspace, database = root/"workspace", root/"memory.sqlite"
    workspace.mkdir()
    note = workspace/"MEMORY.md"
    note.write_text(value["memory"], encoding="utf-8")
    sdk_root = Path(__file__).resolve().parents[1]/"memory_core"
    raw = {"root":str(root), "database":str(database), "input":value, "calls":[], "stages":[], "blobs":{},
           "sdkFiles":{f:sha256((sdk_root/f).read_bytes()).hexdigest() for f in
                       ("config.py","consolidation/forget.py","consolidation/origins.py","consolidation/promotion.py")}}
    def save(blob):
        digest = sha256(blob).hexdigest()
        if digest not in raw["blobs"]:
            raw["blobs"][digest] = base64.b64encode(gzip.compress(blob,mtime=0)).decode("ascii")
        return digest

    def owners():
        return MemoryConfig(workspace_dir=workspace), MemoryEntryOriginLedger(lambda _: database)

    config, ledger = owners()
    def forget(session):
        args = {"agent_id":value["agentId"],"session_ids":[session],"now_ms":value["nowMs"]}
        try:
            report = forget_memory_entries(config=config,origins=ledger,**args).to_json()
        except sqlite3.IntegrityError as error:
            raw["calls"].append({"kind":"forget","args":args,"error":{"class":type(error).__name__,
                "message":str(error),"code":error.sqlite_errorcode,"name":error.sqlite_errorname},"report":None})
            if str(error)!=MESSAGE:
                raise
            return {"failure":str(error),"report":None}
        raw["calls"].append({"kind":"forget","args":args,"error":None,"report":report})
        return {"failure":None,"report":report}

    observations = []
    with patch.object(time,"time",return_value=value["nowMs"]/1000):
        for stage in value["stages"]:
            result = None
            if stage == "seed":
                result = forget(value["previous"])
                ledger.record(value["agentId"],[MemoryEntryOrigin(r["entryKey"],r["agentId"],r["sessionId"],
                    r["sessionKey"],r["originClass"],r["observedAt"]) for r in value["origins"]])
                raw["calls"].append({"kind":"record","origins":value["origins"]})
            elif stage in ("arm","disarm"):
                edge = ("BEFORE INSERT ON memory_session_tombstones" if value["cut"]=="before-marker"
                        else "BEFORE DELETE ON memory_entry_origins")
                statement = (f"CREATE TRIGGER {TRIGGER} {edge} BEGIN SELECT RAISE(ABORT, '{MESSAGE}'); END"
                             if stage=="arm" else f"DROP TRIGGER {TRIGGER}")
                with closing(sqlite3.connect(database)) as db:
                    db.execute(statement)
                raw["calls"].append({"kind":"sql","statement":statement})
            elif stage == "reopen":
                config,ledger = owners()
                raw["calls"].append({"kind":"reopenOwners"})
            else:
                result = forget(value["session"])
            with closing(sqlite3.connect(database.as_uri()+"?mode=ro",uri=True)) as db, closing(sqlite3.connect(":memory:")) as snap:
                db.row_factory=sqlite3.Row
                state = {"memory":note.read_text(encoding="utf8"),
                         "origins":[dict(row) for row in db.execute("SELECT * FROM memory_entry_origins ORDER BY entry_key,agent_id,session_id")],
                         "tombstones":[dict(row) for row in db.execute("SELECT * FROM memory_session_tombstones ORDER BY session_id,agent_id")],
                         "armed":bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?",(TRIGGER,)).fetchone())}
                db.backup(snap)
                image=save(snap.serialize())
            raw["stages"].append({"stage":stage,"result":result,"state":state,"image":image,"note":save(note.read_bytes())})
            observations.append({"stage":stage,"result":result,"state":state})
    (directory/"python-raw.json").write_text(json.dumps([raw],ensure_ascii=False,allow_nan=False)+"\n")
    return {"observations":observations}
