"""Real SDK preparation/reindex over common literal entry provenance profiles."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

from equivalence.get_contract import map_get_fixture_paths


def _physical(store, *, catalog=False):
    db = store._connect() if catalog else store.connect()
    try:
        db.execute("PRAGMA query_only = ON")
        db.execute("BEGIN DEFERRED")
        cursor = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name")
        schema = [dict(zip(("type", "name", "tbl_name", "sql"), row, strict=True)) for row in cursor]
        schema_count = db.execute("SELECT COUNT(*) FROM sqlite_schema").fetchone()[0]
        tables = []
        for row in schema:
            if row["type"] != "table":
                continue
            cursor = db.execute('SELECT * FROM "' + row["name"].replace('"', '""') + '"')
            names = [item[0] for item in cursor.description]
            values = cursor.fetchall()
            row_count = db.execute('SELECT COUNT(*) FROM "' + row["name"].replace('"', '""') + '"').fetchone()[0]
            columns_cursor = db.execute('PRAGMA table_info("' + row["name"].replace('"', '""') + '")')
            column_names = [item[0] for item in columns_cursor.description]
            columns = [dict(zip(column_names, item, strict=True)) for item in columns_cursor]
            tables.append({"name": row["name"], "rowCount": row_count, "columns": columns, "rows": [dict(zip(names, (
                {"type": "bytes", "hex": bytes(value).hex()} if isinstance(value, (bytes, bytearray, memoryview)) else value
                for value in item), strict=True)) for item in values]})
        return {"schema": schema, "schemaCount": schema_count, "tables": tables,
                "snapshotTransaction": {"mode": "deferred", "active": db.in_transaction}}
    finally:
        db.rollback()
        db.close()


def _logical(store):
    value = store.read_published_index()
    return {name: value[name] for name in ("sources", "chunks", "provenance", "recall", "details", "fts", "paths")}


def run_entry_provenance(arguments, *, evidence_directory=None):
    import memory_core
    from memory_core.config import MemoryConfig
    from memory_core.flags import FeatureFlags
    from memory_core.index.embedding_limits import enforce_embedding_max_input_tokens
    from memory_core.index.sqlite_store import SQLiteMemoryStore
    from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
    from memory_core.session_catalog import MemorySessionCatalog
    from memory_core.session_corpus import MemoryCoreSessionCorpus
    from memory_core.workspace import MemoryWorkspace

    owner_root = Path(__file__).resolve().parents[1]
    if not Path(memory_core.__file__).resolve().is_relative_to(owner_root):
        raise RuntimeError("Entry provenance imported an SDK outside its owning worktree")
    value = deepcopy(arguments)
    if value["kind"] not in {"published-memory", "prepared-provider", "session-projection"}:
        raise ValueError("An explicit bounded entry-provenance profile is required")
    now = value.get("nowMs", (value.get("steps") or [{}])[0].get("nowMs"))
    with tempfile.TemporaryDirectory(prefix="python-entry-provenance-") as temporary:
        root = Path(temporary)
        workspace, state = root / "workspace", root / "state"
        workspace.mkdir()
        raw = {"kind": value["kind"], "fixtureBase": str(root), "input": value, "pid": os.getpid(),
               "implementationRoot": str(owner_root), "calls": [], "snapshots": [], "preparations": [], "providerCalls": []}
        session_mode = value["kind"] == "session-projection"
        catalog = MemorySessionCatalog(state / "agents/main/sessions/authority.sqlite", agent_id="main",
            store_path=state / "agents/main/sessions/sessions.json", clock_ms=lambda: now) if session_mode else None

        def write(files):
            for relative, text in (files or {}).items():
                filename = workspace / relative
                if Path(relative).is_absolute() or ".." in relative.replace("\\", "/").split("/"):
                    raise ValueError("Source files must remain owned")
                filename.parent.mkdir(parents=True, exist_ok=True)
                filename.write_text(text, encoding="utf-8")
                os.utime(filename, ns=(value["mtimeMs"] * 1_000_000, value["mtimeMs"] * 1_000_000))
                raw["calls"].append({"operation": "write", "relative": relative, "content": text, "mtimeMs": value["mtimeMs"]})

        for item in value.get("sessions", []):
            catalog.upsert_session(item["sessionKey"], item["entry"])
            catalog.replace_events(item["entry"]["sessionId"], item["events"], session_key=item["sessionKey"])
            raw["calls"].append({"operation": "seed", "input": item, "entry": catalog.get_session_entry(item["sessionKey"]),
                                 "events": list(catalog.read_transcript(item["entry"]["sessionId"], session_key=item["sessionKey"]).events)})
        provider = None
        if value["kind"] == "prepared-provider":
            class Provider:
                provider_id = value["provider"]["id"]
                model = value["provider"]["model"]
                max_input_tokens = value["provider"]["maxInputTokens"]

                def embed_documents(self, texts):
                    result = [deepcopy(value["embeddingVector"]) for _ in texts]
                    raw["providerCalls"].append({"inputs": list(texts), "result": deepcopy(result)})
                    return result

                def embed_query(self, text):
                    raise RuntimeError("This preparation profile executes no query/provider loop")

            provider = Provider()
        config = MemoryConfig(workspace_dir=workspace, flags=FeatureFlags(vector_search=provider is not None))
        store = SQLiteMemoryStore(config, provider)
        memory_workspace = MemoryWorkspace(workspace, openclaw_state_dir=state if session_mode else None,
            session_catalog=catalog, index_sources=["sessions"] if session_mode else ["memory"])
        raw["config"] = asdict(config)
        try:
            if value["kind"] == "prepared-provider":
                write({value["path"]: value["content"]})

                def observe(actual_provider, chunks):
                    result = enforce_embedding_max_input_tokens(actual_provider, chunks)
                    raw["preparations"].append({"input": [asdict(chunk) for chunk in chunks],
                                                 "result": [asdict(chunk) for chunk in result]})
                    return result

                with patch("memory_core.index.sqlite_store.enforce_embedding_max_input_tokens", observe), patch(
                        "memory_core.index.sqlite_store.time.time_ns", return_value=now * 1_000_000):
                    store.reindex(memory_workspace)
                state_rows = _logical(store)
                raw["snapshots"].append({"state": state_rows, "physical": _physical(store)})
                fragments = []
                for chunk in raw["preparations"][0]["result"]:
                    matches = [row for row in state_rows["chunks"] if row["path"] == chunk["path"]
                               and row["startLine"] == chunk["start_line"] and row["endLine"] == chunk["end_line"]
                               and row["text"] == chunk["text"]]
                    row, = matches
                    fragments.append({"id": row["id"], "startLine": row["startLine"], "endLine": row["endLine"],
                        **({"entryStartLine": chunk["entry_start_line"], "entryEndLine": chunk["entry_end_line"]}
                           if chunk["entry_start_line"] is not None else {}),
                        "text": row["text"], "hash": row["hash"], "provenance": row["provenance"], "recall": row["recall"]})
                return {"provider": "none", "contentHash": state_rows["sources"][0]["hash"], "fragments": fragments, "state": state_rows}
            write(value.get("files"))
            steps = []
            corpus = MemoryCoreSessionCorpus(state, catalog=catalog, runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY) if session_mode else None
            for step in value["steps"]:
                now = step["nowMs"]
                write(step.get("write"))
                if "events" in step:
                    catalog.replace_events(value["sessionId"], step["events"], session_key=value["sessionKey"])
                    raw["calls"].append({"operation": "replace_events", "events": step["events"]})
                with patch("memory_core.index.sqlite_store.time.time_ns", return_value=now * 1_000_000):
                    returned = store.reindex(memory_workspace, force=step.get("force", False))
                raw["calls"].append({"operation": "reindex", "label": step["label"], "force": step.get("force", False), "result": returned})
                sources = []
                if corpus is not None:
                    admitted = corpus.discover_admitted_entries()
                    files = {(str(file.abs_path), file.session_id, file.artifact_kind): file for file in corpus.discover_files()}
                    for source in admitted:
                        file = files[(source["sessionFile"], source["sessionId"], source["artifactKind"])]
                        sources.append({"source": source, "entry": corpus.read_source_entry(file),
                                        "resetRecallCutoff": corpus.read_index_entry(file).reset_recall_cutoff})
                snapshot = {"label": step["label"], "state": _logical(store), "sources": sources}
                steps.append(snapshot)
                raw["snapshots"].append({**deepcopy(snapshot), "physical": _physical(store),
                    **({"sessionPhysical": _physical(catalog, catalog=True)} if catalog is not None else {})})
            return map_get_fixture_paths({"provider": "none", "steps": steps}, root)
        finally:
            if evidence_directory is not None:
                evidence_directory = Path(evidence_directory)
                evidence_directory.mkdir(parents=True, exist_ok=True)
                (evidence_directory / "python-raw.json").write_text(json.dumps([raw], ensure_ascii=False, default=str, indent=2) + "\n")


if __name__ == "__main__":
    request = json.load(sys.stdin)
    json.dump(run_entry_provenance(request["input"], evidence_directory=Path(request["evidenceDirectory"])),
              sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
