"""Prepared index publication comparisons against the real native owner.

Fixtures provide already prepared rows to each production publication owner.
Chunk/annotation derivation, provider orchestration and full manager startup are
separate contracts. Private revision counters are compared by advancement and
conflict outcomes, since native row triggers and Python revision publication use
different internal counters; every stored semantic row remains observable.
"""
from __future__ import annotations

from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
from typing import Any


def _chunk(identifier: str, path: str, text: str, *, source: str = "memory",
           start: int = 1, importance: int | None = None,
           triggers: list[str] | None = None, project: str | None = None,
           origin: str = "owner", session_kind: str = "interactive",
           supersedes: str | None = None) -> dict:
    return {"id": identifier, "path": path, "source": source,
            "startLine": start, "endLine": start + 1, "text": text,
            "embedding": [0.25, 0.75], "hash": f"prepared-hash-{identifier}",
            "model": "fixture-model", "updatedAt": 1000,
            "provenance": {"originClass": origin, "sessionKind": session_kind,
                           "observedAt": 900, "supersedesKey": supersedes},
            "recall": {"importance": importance, "triggers": triggers,
                       "projectKey": project}}


def _revision(label: str, sources: list[dict], chunks: list[dict]) -> dict:
    return {"sources": sources, "chunks": chunks,
            "meta": {"model": "fixture-model", "provider": "fixture-provider",
                     "providerKey": "fixture-provider-key", "sources": ["memory", "sessions"],
                     "scopeHash": "fixture-scope", "chunkTokens": 400, "chunkOverlap": 80,
                     "chunkingVersion": 5, "ftsTokenizer": "unicode61", "provenanceVersion": 1,
                     "vectorDims": 2, "publicationLabel": label}}


def build_index_publication_cases() -> list[dict[str, Any]]:
    old = _revision("old", [
        {"path": "memory/old.md", "source": "memory", "hash": "source-old",
         "mtime": 800, "size": 41},
        {"path": "sessions/old.jsonl", "source": "sessions", "hash": "session-old",
         "mtime": 801, "size": 42},
    ], [
        _chunk("old-memory", "memory/old.md", "alpha old memory", importance=3,
               triggers=["alpha"], project="old-project"),
        _chunk("old-session", "sessions/old.jsonl", "alpha old session", source="sessions",
               origin="agent", session_kind="cron"),
    ])
    new = _revision("new", [
        {"path": "memory/new.md", "source": "memory", "hash": "source-new",
         "mtime": 1100, "size": 67},
        {"path": "sessions/new.jsonl", "source": "sessions", "hash": "session-new",
         "mtime": 1101, "size": 68},
        {"path": "memory/empty.md", "source": "memory", "hash": "source-empty",
         "mtime": 1102, "size": 0},
    ], [
        _chunk("new-memory", "memory/new.md", "beta new memory", importance=9,
               triggers=["beta", "project kickoff"], project="new-project", supersedes="old-memory"),
        _chunk("new-fragment", "memory/new.md", "gamma second fragment", start=3,
               importance=1, triggers=[], origin="untrusted", session_kind="unknown"),
        _chunk("new-session", "sessions/new.jsonl", "beta new session", source="sessions",
               importance=10, origin="system", session_kind="heartbeat"),
    ])
    empty = _revision("empty", [], [])
    definitions: list[tuple[str, dict]] = [
        ("success", {}),
        ("reader-snapshot", {"holdReader": True}),
        ("empty-replacement", {"replacement": empty}),
        ("same-rows", {"replacement": deepcopy(old)}),
        ("stale-revision", {"stale": True}),
        ("stale-reader-snapshot", {"stale": True, "holdReader": True}),
        ("begin-failure", {"failure": "begin"}),
        ("sources-failure", {"failure": "sources"}),
        ("chunks-failure", {"failure": "chunks"}),
        ("details-failure", {"failure": "details"}),
        ("recall-failure", {"failure": "recall"}),
        ("provenance-failure", {"failure": "provenance"}),
        ("commit-failure", {"failure": "commit"}),
        ("commit-failure-reader-snapshot", {"failure": "commit", "holdReader": True}),
        ("post-commit-failure", {"failure": "after-commit", "holdReader": True}),
        ("orphan-metadata-replacement", {"orphans": True}),
        ("orphan-metadata-rollback", {"orphans": True, "failure": "commit"}),
    ]
    return [{"id": f"publication-{name}", "requirement": "indexing.transaction-publication",
             "operation": "index-publication",
             "input": {"initial": deepcopy(old), "replacement": deepcopy(new), **deepcopy(options)},
             "normalizationPolicy": [
                 "Private revision counters retain advancement and stale-owner rejection semantics; "
                 "native row-trigger counts and Python publication counts are separate schema internals.",
                 "A failure after COMMIT is compared by visible failure and independently observed "
                 "durable state, including native handle fencing; it cannot count as rollback.",
             ],
             "covers": ["indexing.transaction-publication.outcomes",
                        "indexing.transaction-publication.boundaries"]}
            for name, options in definitions]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _prepared(value: dict):
    from memory_core.index.publication import (
        ChunkProvenance, ChunkRecallMetadata, PreparedChunk, PreparedIndexRevision, PreparedSource,
    )

    chunks = []
    for chunk in value["chunks"]:
        provenance, recall = chunk["provenance"], chunk["recall"]
        chunks.append(PreparedChunk(
            id=chunk["id"], path=chunk["path"], source=chunk["source"],
            start_line=chunk["startLine"], end_line=chunk["endLine"], text=chunk["text"],
            embedding=tuple(chunk["embedding"]), hash=chunk["hash"], model=chunk["model"],
            updated_at=chunk["updatedAt"],
            provenance=ChunkProvenance(
                origin_class=provenance["originClass"], session_kind=provenance["sessionKind"],
                observed_at=provenance["observedAt"], supersedes_key=provenance["supersedesKey"]),
            recall=ChunkRecallMetadata(
                importance=recall["importance"],
                triggers=None if recall["triggers"] is None else _json(recall["triggers"]),
                project_key=recall["projectKey"]),
        ))
    return PreparedIndexRevision(
        sources=tuple(PreparedSource(
            path=source["path"], source=source["source"], hash=source["hash"],
            mtime=source["mtime"], size=source["size"],
            chunks=tuple(chunk for chunk in chunks
                         if (chunk.source, chunk.path) == (source["source"], source["path"])),
        ) for source in value["sources"]),
        metadata_json=_json(value["meta"]),
    )


def _error(error: Exception | None, *, phase: str, failure: str | None) -> dict | None:
    if error is None:
        return None
    if failure == "after-commit" and phase == "after-commit":
        # Native handle fencing can replace the injected marker with a closed
        # connection error. Both implementations must still expose failure and
        # the independently observed durable new revision.
        return {"kind": "post-commit-failure"}
    if type(error).__name__ in {"MemoryIndexSourceChangedError", "MemoryIndexRevisionConflictError"}:
        return {"kind": "revision-conflict"}
    marker = "injected publication failure:"
    if marker in str(error):
        return {"kind": "injected-failure", "stage": str(error).split(marker, 1)[1]}
    return {"kind": "unexpected", "type": type(error).__name__, "message": str(error)}


def run_index_publication(arguments: dict[str, Any]) -> dict:
    from memory_core.config import MemoryConfig
    from memory_core.flags import FeatureFlags
    from memory_core.index.identity import INDEX_SOURCES_TABLE, INDEX_SYNC_TABLE
    from memory_core.index.publication import (
        CHUNK_DETAILS_TABLE, CHUNK_PROVENANCE_TABLE, CHUNK_RECALL_TABLE,
    )
    from memory_core.index.sqlite_store import SQLiteMemoryStore

    with tempfile.TemporaryDirectory(prefix="memory-core-publication-") as directory:
        root = Path(directory)
        filename = root / "index.sqlite"
        store = SQLiteMemoryStore(MemoryConfig(workspace_dir=root, store_path=filename,
                                               flags=FeatureFlags(vector_search=False)), None)
        with store.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
        store.publish_prepared_index(_prepared(arguments["initial"]), store.index_revision())
        with store.connect() as db:
            db.execute("INSERT INTO memory_index_meta(key,value) VALUES ('unrelated-key','target-retained')")
            db.execute("INSERT INTO memory_embedding_cache VALUES "
                       "('fixture-provider','fixture-model','fixture-key','retained',X'000000000000D03F',1,1)")
        if arguments.get("orphans"):
            # Deliberate corruption fixture: enumerate unmatched owner rows,
            # rather than hiding them through chunk joins in the snapshots.
            with sqlite3.connect(filename) as db:
                db.execute(f"INSERT INTO {CHUNK_PROVENANCE_TABLE} VALUES "
                           "('orphan','untrusted','unknown',77,NULL)")
                db.execute(f"INSERT INTO {CHUNK_RECALL_TABLE} VALUES ('orphan',2,'[]','orphan-project')")
        reader = sqlite3.connect(filename)
        held = sqlite3.connect(filename)
        if arguments.get("holdReader"):
            held.execute("BEGIN")
            held.execute("SELECT COUNT(*) FROM chunks").fetchone()
        failure = arguments.get("failure")
        tables = {"sources": INDEX_SOURCES_TABLE, "chunks": "chunks", "details": CHUNK_DETAILS_TABLE,
                  "recall": CHUNK_RECALL_TABLE, "provenance": CHUNK_PROVENANCE_TABLE}
        if failure in tables:
            with store.connect() as db:
                db.execute(f"CREATE TRIGGER fixture_failure BEFORE INSERT ON {tables[failure]} "
                           f"BEGIN SELECT RAISE(ABORT, 'injected publication failure:{failure}'); END")
        expected = store.index_revision()
        if arguments.get("stale"):
            with store.connect() as db:
                db.execute(f"UPDATE {INDEX_SYNC_TABLE} SET revision=revision+1 WHERE id=1")
        base_revision = store.index_revision()
        events = []
        phase = "start"

        def state(db=None):
            # The public snapshot enumerates all metadata rows independently
            # of chunk joins, so orphan rows remain visible as well.
            if db is None:
                with closing(store.connect()) as connection:
                    return state(connection)
            result = _strip_revision(store.read_published_index(db=db))
            result["bodyMatches"] = {
                query: [row[0] for row in db.execute(
                    "SELECT id FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY id", (query,))]
                for query in ("alpha", "beta", "gamma")
            }
            result["pathMatches"] = {
                query: [list(row) for row in db.execute(
                    "SELECT path,source FROM paths_fts WHERE paths_fts MATCH ? ORDER BY source,path", (query,))]
                for query in ("old", "new", "empty")
            }
            return result

        before = state()

        def observe(label: str, writer):
            events.append({"phase": label, "writer": state(writer), "reader": state(reader),
                           "heldReader": state(held) if arguments.get("holdReader") else None})

        def begin(db):
            nonlocal phase
            phase = "begin"
            observe("begin", db)
            if failure == "begin":
                raise RuntimeError("injected publication failure:begin")

        writer = None

        def observed_begin(db):
            nonlocal writer
            writer = db
            begin(db)

        def commit(commit_fn):
            nonlocal phase
            phase = "commit"
            observe("commit", writer)
            if failure == "commit":
                raise RuntimeError("injected publication failure:commit")
            commit_fn()
            if failure == "after-commit":
                phase = "after-commit"
                raise RuntimeError("injected publication failure:after-commit")

        error = None
        try:
            store.publish_prepared_index(_prepared(arguments["replacement"]), expected,
                                         on_begin=observed_begin, with_commit=commit)
        except Exception as exc:
            error = exc
        after = state()
        held_after = state(held) if arguments.get("holdReader") else None
        if arguments.get("holdReader"):
            held.rollback()
        reopened = SQLiteMemoryStore(store.config, None)
        with closing(reopened.connect()) as connection:
            reopened_state = state(connection)
        with store.connect() as db:
            cache = [list(row) for row in db.execute(
                "SELECT provider,model,provider_key,hash,hex(embedding),dims,updated_at "
                "FROM memory_embedding_cache ORDER BY provider,model,provider_key,hash")]
            attachments = [row[1] for row in db.execute("PRAGMA database_list")]
        reader.close()
        held.close()
        attachment_released = True
        if writer is not None:
            try:
                attachment_released = all(row[1] != "memory_reindex"
                                          for row in writer.execute("PRAGMA database_list"))
            except sqlite3.ProgrammingError:
                # This production publisher owns and closes its connection.
                attachment_released = True
        return {"before": before, "events": events, "after": after, "heldAfter": held_after,
                "reopened": reopened_state, "error": _error(error, phase=phase, failure=failure),
                "revisionAdvanced": store.index_revision() != base_revision,
                "cache": cache, "attachments": attachments, "attachmentReleased": attachment_released}


def _strip_revision(value: dict) -> dict:
    return {key: val for key, val in value.items() if key != "revision"}
