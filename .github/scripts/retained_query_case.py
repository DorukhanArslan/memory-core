"""Preserve every physical query-sync boundary file and both observed public values."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil

CID = "query-sync-boundaries-warm-failure-natural-retry"
OP = "query-sync-boundaries-runtime"
POINT = "indexing.query-sync.boundaries"
OUT = Path(os.environ["RUNNER_TEMP"])/"query-sync-retained"
OUT.mkdir(exist_ok=True)
MISSING = object()


def save(name, data):
    path = OUT/name
    data = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()+b"\n"
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def physical(package, results, body_hash):
    inventory = []
    prefix = results + "/query-sync-boundaries/"
    for member in package.infolist():
        if member.is_dir() or not member.filename.startswith(prefix):
            continue
        parts = PurePosixPath(member.filename.removeprefix(prefix))
        if parts.is_absolute() or ".." in parts.parts:
            raise ValueError("Unsafe measured query evidence path")
        path = OUT/"original-files"/parts
        path.parent.mkdir(parents=True, exist_ok=True)
        with package.open(member) as original, path.open("xb") as dest:
            shutil.copyfileobj(original,dest,1024*1024)
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream,"sha256").hexdigest()
        if path.stat().st_size != member.file_size:
            raise ValueError("Short original query evidence file")
        inventory.append({"member":member.filename,"sha256":digest,"bytes":member.file_size})
    if not inventory:
        raise ValueError("Original query case files missing")
    save("physical-inventory.json", {"sourceRun":44927413199,"sourceReportSha256":body_hash,"members":inventory})


def external(v):
    return {"present":False} if v is MISSING else {"present":True,"value":v}


def leaf_changes(a,b,path=(),parents=None):
    same = type(a) is type(b)
    if same and isinstance(a,dict):
        for key in sorted(a.keys() | b.keys()):
            yield from leaf_changes(a.get(key,MISSING),b.get(key,MISSING),(*path,key),(a,b))
    elif same and isinstance(a,list):
        for i in range(max(len(a),len(b))):
            yield from leaf_changes(a[i] if i<len(a) else MISSING,b[i] if i<len(b) else MISSING,(*path,i),(a,b))
    elif not same or a != b:
        yield {"path":path,"openclaw":external(a),"python":external(b),
               "openclawRecord":parents[0] if parents else None,"pythonRecord":parents[1] if parents else None}


def capture(key,value,array):
    if key.lower().startswith("querysyncboundar") and array in (True,False):
        save(key+".json", value)
    if array is not True or not isinstance(value,dict) or CID not in (value.get("id"),value.get("caseId")):
        return
    if key not in ("cases","releaseTraces","sourcePolicyDiagnostics","runtimeDiagnostics"):
        return
    ordinal = len(list(OUT.glob(key+"-*.json")))
    save(f"{key}-{ordinal:02}.json", value)
    if key == "cases":
        if value["status"] != "mismatched" or value["operation"] != OP:
            raise ValueError("Mismatching original query case not found")
        records = list(leaf_changes(value["openclaw"],value["python"]))
        digest = save("public-differences.json",{"id":CID,"changes":records})
        print("QUERY_EXPORT",len(records),digest,flush=True)
        for diff in records:
            detail = {k:diff[k] for k in ("path","openclaw","python")}
            print("QUERY_DIFF", json.dumps(detail,ensure_ascii=True,separators=(",",":")), flush=True)


def validate():
    rows = [json.loads(p.read_bytes()) for p in OUT.glob("runtimeDiagnostics-*.json")]
    if (len(list(OUT.glob("cases-*.json")))!=1 or len(list(OUT.glob("releaseTraces-*.json")))!=1 or
            {r["side"] for r in rows}!={"native","python"} or len(rows)!=2):
        raise ValueError("Incomplete original query evidence")
    roots = {r["sha256"] for r in rows}
    inventory = json.loads((OUT/"physical-inventory.json").read_bytes())["members"]
    if not roots <= {r["sha256"] for r in inventory}:
        raise ValueError("Physical query files disagree with original raw snapshot hashes")
