"""Drive the SDK index writer and retain each persisted SQLite repair stage."""
import base64
from contextlib import closing
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

from equivalence.entry_provenance_runtime import _logical
from equivalence.recovery_index_fixtures import recovery_index_cases
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.workspace import MemoryWorkspace


SEARCH = ("SELECT f.id,c.path,f.text FROM chunks_fts AS f JOIN chunks AS c ON c.id=f.id "
          "WHERE chunks_fts MATCH ? ORDER BY f.id,f.text")
DAMAGE_SQL = {
    "derived-text": "UPDATE chunks_fts SET text = ? WHERE id IN (SELECT id FROM chunks WHERE path = ?)",
    "provenance-row": "UPDATE memory_index_chunk_provenance SET supersedes_key = ? WHERE chunk_id IN "
                      "(SELECT id FROM chunks WHERE path = ?)",
}


def run_recovery_index_repair(value, *, evidence_directory):
    directory = Path(evidence_directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    base = Path(tempfile.mkdtemp(prefix="sdk-index-repair-", dir=directory))
    workspace = base / "workspace"
    workspace.mkdir()
    for relative, content in value["files"].items():
        filename = workspace / relative
        if not filename.resolve().is_relative_to(workspace):
            raise ValueError("Invalid note path")
        filename.parent.mkdir(parents=True, exist_ok=True)
        filename.write_text(content)
        os.utime(filename, ns=(value["mtimeMs"] * 1_000_000,) * 2)
    config = MemoryConfig(workspace_dir=workspace, store_path=base / "main.sqlite", flags=FeatureFlags(vector_search=False))
    store = SQLiteMemoryStore(config, None)
    source = MemoryWorkspace(workspace, index_sources=["memory"])
    raw = {"input": value, "fixtureBase": str(base), "pid": os.getpid(), "implementationRoot": str(Path(__file__).resolve().parents[1]),
           "calls": [], "snapshots": [], "blobs": {}}
    with patch("memory_core.index.sqlite_store.time.time_ns", return_value=value["nowMs"] * 1_000_000):
        for stage in value["stages"]:
            if stage == "damaged":
                with closing(store.connect()) as db, db:
                    statement = DAMAGE_SQL[value["kind"]]
                    result = db.execute(statement, value["damage"]["args"])
                    raw["calls"].append({"operation": "inject", "stage": stage, "sql": statement, "args": value["damage"]["args"], "rowcount": result.rowcount})
            else:
                result = store.reindex(source, force=True)
                raw["calls"].append({"operation": "reindex", "stage": stage, "force": True, "result": result})
            state = _logical(store)
            with closing(store.connect()) as db:
                searches = [{"query": query, "rows": [dict(zip(("id", "path", "text"), row, strict=True))
                             for row in db.execute(SEARCH, (query,))]} for query in value["searches"]]
                integrity = [row[0] for row in db.execute("PRAGMA integrity_check")]
                image = base / (stage + ".sqlite")
                db.execute("VACUUM INTO ?", (str(image),))
                database_list = [dict(zip(("seq", "name", "file"), row, strict=True)) for row in db.execute("PRAGMA database_list")]
            documents = {relative: (workspace / relative).read_text() for relative in value["files"]}
            observation = {"stage": stage, "documents": documents, "state": state, "searches": searches, "integrity": integrity,
                           "indexIdentity": store.index_identity()}
            data = image.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            raw["blobs"].setdefault(digest, {"size": len(data), "gzip": base64.b64encode(gzip.compress(data, mtime=0)).decode()})
            raw["snapshots"].append({"observation": observation, "sha256": digest, "databaseList": database_list,
                                     "indexRevision": store.index_revision()})
    (directory / "python-raw.json").write_text(json.dumps([raw], separators=(",", ":")) + "\n")
    return {"observations": [row["observation"] for row in raw["snapshots"]]}


if __name__ == "__main__":
    request = json.load(sys.stdin)
    json.dump(run_recovery_index_repair(request["input"], evidence_directory=request["evidenceDirectory"]), sys.stdout)
    sys.stdout.write("\n")
