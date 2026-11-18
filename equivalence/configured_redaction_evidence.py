"""Keep the original configured policy process and the actual reopened model-session databases."""
from __future__ import annotations

import base64
from contextlib import closing
from hashlib import sha256
from importlib import metadata
import os
from pathlib import Path
import sqlite3
import tempfile

from equivalence.configured_redaction import IDS


def engine_identity():
    import _quickjs
    import quickjs
    dist=metadata.distribution("quickjs-ng")
    files={Path(dist.locate_file(row)).resolve():row for row in dist.files or () if row.hash}
    result={}
    for name,module in (("wrapper",quickjs),("engine",_quickjs)):
        path=Path(module.__file__).resolve()
        record=files[path].hash
        digest=sha256(path.read_bytes())
        if record.mode!="sha256" or record.value!=base64.urlsafe_b64encode(digest.digest()).decode().rstrip("="):
            raise ValueError("The loaded ECMAScript engine differs from the installed wheel record")
        result[name]={"file":path.name,"sha256":digest.hexdigest()}
    return {"distribution":"quickjs-ng","version":dist.version,"files":result}


def save_sqlite_image(source, target):
    target=Path(target)
    target.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(Path(source).as_uri()+"?mode=ro",uri=True)) as original, closing(sqlite3.connect(target)) as image:
        original.backup(image)


def retain_capture(ident,side,wire,*,image_root=None):
    from equivalence.runtime_oracle import ROOT, MAX_DIAGNOSTIC_BYTES, _owned_regular
    if ident not in IDS or side not in ("source","native","python") or not isinstance(wire,bytes):
        raise ValueError("Unbound configured-redaction capture")
    root=ROOT/".equivalence-results"/"configured-redaction"
    root.mkdir(parents=True,exist_ok=True)
    if root.resolve(strict=True)!=root or root.is_symlink():
        raise ValueError("Invalid configured-redaction evidence root")
    directory=Path(tempfile.mkdtemp(prefix=side+"-attempt-",dir=root))
    def save(name,body):
        path=directory/name
        if len(body)>MAX_DIAGNOSTIC_BYTES:
            raise ValueError("Configured capture exceeds the bounded evidence size")
        with os.fdopen(os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),"wb") as out:
            out.write(body)
        if _owned_regular(ROOT,path,MAX_DIAGNOSTIC_BYTES)!=body:
            raise ValueError("Configured capture changed during retention")
        return {"path":str(path),"bytes":len(body),"sha256":sha256(body).hexdigest()}
    result={"id":ident,"side":side,"wire":save(side+"-raw.json",wire),"databases":[]}
    if image_root is not None:
        for label in ("write","continue","verify"):
            name="configured-"+label+".sqlite"
            body=_owned_regular(image_root,image_root/name,8*1024**2)
            result["databases"].append({"phase":label,**save(name,body)})
    return result
