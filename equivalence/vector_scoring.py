"""Portable CPU vector candidates compared with the original native owners.

The reference's actual ``searchVector`` selects its CPU fallback capability,
then executes ``searchChunksByEmbedding`` over SQLite. Optional sqlite-vec KNN
acceleration and the surrounding managed-query snapshot policy are not claimed.
Finite scores and complete ordered candidate rows are compared without rounding.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import tempfile
from typing import Any


_CANCEL_REASON = "fixture vector search cancelled"
_PROFILE = (
    "Portable CPU capability: actual native searchVector with ensureVectorReady=false, "
    "then original searchChunksByEmbedding over real SQLite; actual Python store candidate "
    "method before hybrid ranking. sqlite-vec KNN remains unverified. Mutable caller-owned "
    "connections exercise batch boundaries; managed-query snapshot policy is separate."
)


def _row(index: int, embedding: list[Any] | None = None, **fields: Any) -> dict[str, Any]:
    return {
        "rowid": str(index + 1), "id": f"chunk-{index}",
        "path": f"memory/note-{index}.md", "source": "memory",
        "startLine": index + 1, "endLine": index + 2,
        "text": f"candidate {index}", "model": "target-model",
        "embedding": [1, 0] if embedding is None else embedding, **fields,
    }


def build_vector_scoring_cases() -> list[dict[str, Any]]:
    """Substantive numeric, filtering, ordering and bounded-scan comparisons."""
    cases: list[dict[str, Any]] = []

    def add(name: str, kind: str, **arguments: Any) -> None:
        cases.append({
            "id": f"vector-{name}", "requirement": "retrieval.vector-scoring",
            "operation": "vector-scoring", "covers": [],
            "input": {"kind": kind, **deepcopy(arguments)}, "driverScope": _PROFILE,
            "normalizationPolicy": (
                "Finite scores and complete ordered id/path/source/range/snippet fields remain "
                "exact. Nonfinite scalar outputs use explicit tagged JSON carriers. Rowids "
                "remain decimal strings. Logical numeric coordinates are IEEE-754 binary64; "
                "native BLOB64 and Python JSON/BLOB64 are private storage representations. "
                "Only the declared cancellation reason is canonicalized."
            ),
        })

    for name, a, b in (
        ("empty", [], []), ("one-empty", [1], []),
        ("same", [1, 2, 3], [1, 2, 3]),
        ("orthogonal", [1, 0], [0, 1]),
        ("opposite", [1, 0], [-1, 0]),
        ("zero-norm", [0, 0], [1, 0]),
        ("short-left-prefix", [1], [1, 0, 99]),
        ("short-right-prefix", [1, 0, 99], [1, 0]),
        ("binary64-fractions", [0.1, 0.2, 0.3], [0.7, -0.1, 0.9]),
        ("underflow-norm", [1e-180], [1e-180]),
        ("overflow-norm", [1e308], [1e308]),
        ("nonfinite-query", [{"special": "nan"}, 1], [1, 1]),
    ):
        add(f"cosine-{name}", "cosine", a=a, b=b)

    def search(name: str, rows: list[dict[str, Any]], **arguments: Any) -> None:
        add(name, "search", **{
            "backend": "scan", "rows": rows, "queryVec": [1, 0],
            "limit": 3, "providerModel": "target-model", "snippetMaxChars": 200,
            **arguments,
        })

    basic = [_row(0, [0, 1]), _row(1, [1, 0]), _row(2, [0.8, 0.6])]
    search("empty-table", [])
    for name, query, limit in (("empty-query", [], 2), ("zero-limit", [1, 0], 0),
                                ("negative-limit", [1, 0], -1)):
        arguments = {"backend": "scan", "rows": basic, "queryVec": query,
                     "limit": limit, "providerModel": "target-model", "snippetMaxChars": 200}
        add(name, "search", **arguments)
    search("ordered-top-one", basic, **{"limit": 1})
    search("limit-beyond-corpus", basic, **{"limit": 10})
    search("zero-query-retains-candidates", basic, **{"queryVec": [0, 0]})
    search("prefix-dimensions", [_row(0, [1]), _row(1, [0, 1, 99]), _row(2, [])])
    search("negative-zero-and-positive", [
        _row(0, [-1, 0]), _row(1, [0, 0]), _row(2, [0.8, 0.6]),
    ])
    search("finite-score-filter", [
        _row(0, [1e308, 1e308]), _row(1, [0, 0]), _row(2, [1, 0]),
    ], **{"queryVec": [1e308, 1e308]})
    search("malformed-derived-blobs", [
        _row(0, embeddingBytesHex="010203"),
        _row(1, embeddingBytesHex="000000000000f07f"),
        _row(2, [1, 0]),
    ])
    tied = [
        _row(0, rowid="8", path="memory/a.md", startLine=1, endLine=1),
        _row(1, rowid="-1", path="sessions/z.md", source="sessions", startLine=9, endLine=12),
        _row(2, rowid="0", path="memory/z.md", startLine=5, endLine=8),
    ]
    search("tie-order-is-rowid-not-path", tied, **{"limit": 2})
    search("full-source-and-range-identities", [
        _row(0, path="same.md", startLine=20, endLine=25),
        _row(1, path="same.md", source="sessions", startLine=1, endLine=2),
        _row(2, path="same.md", startLine=1, endLine=3),
    ])
    mixed = [
        _row(0, model="unrelated", source="memory"),
        _row(1, [0.8, 0.6], model="alias-model", source="sessions"),
        _row(2, [0.6, 0.8], model="target-model", source="memory"),
        _row(3, model="/not-declared/model", source="sessions"),
    ]
    search("model-aliases-filter-before-limit", mixed, **{
        "providerModelAliases": ["alias-model", "alias-model", ""], "limit": 2,
    })
    search("source-memory-only", mixed, **{
        "providerModelAliases": ["alias-model"], "sources": ["memory"],
    })
    search("source-sessions-only", mixed, **{
        "providerModelAliases": ["alias-model"], "sources": ["sessions"],
    })
    search("empty-sources-is-host-no-filter", mixed, **{
        "providerModelAliases": ["alias-model"], "sources": [],
    })
    search("empty-primary-model", [_row(0, model=""), _row(1)], **{"providerModel": ""})
    for limit in (0, 4, 5):
        search(f"utf16-nul-snippet-{limit}", [_row(0, text="a😀\x00tail café")],
               **{"snippetMaxChars": limit})
    search("utf16-database-snippet", [_row(0, text="A\x00😀続き")], **{
        "encoding": "UTF-16le", "snippetMaxChars": 4,
    })

    rowids = [-(2**63), -(2**53) - 1, -1, 0]
    high = [2**53 + 1 + i * 2 for i in range(252)]
    rowids += high + [high[-1] + 1, high[-1] + 2, 2**63 - 1]
    sparse = [_row(i, [1, 0] if i == 256 else [0, 1], rowid=str(rowid))
              for i, rowid in enumerate(rowids)]
    search("signed-rowid-batch-boundary", sparse, **{"limit": 2, "observe": True})
    search("abort-before-scan", basic, **{"preAborted": True})
    many = [_row(i, [0, 1]) for i in range(257)]
    search("abort-after-full-batch", many, **{"abortAfterBatch": True})
    search("insert-after-full-batch", many, **{"observe": True, "limit": 2,
        "mutateAfterBatch": {"replaceRows": [_row(257), _row(258, [0.8, 0.6])]},
    })
    payload_rows = [_row(i, [1, 0] if i in {0, 1, 256} else [0, 1],
                         text="old 😀 text" if i == 0 else f"candidate {i}")
                    for i in range(257)]
    search("hydrate-before-batch-mutation", payload_rows, **{
        "observe": True, "limit": 2, "snippetMaxChars": 5,
        "mutateAfterBatch": {"replaceRows": [_row(0, [0, 1], text="replacement")]},
    })
    search("external-wal-payload-snapshot", [_row(0, text="original payload")], **{
        "observe": True, "limit": 1,
        "externalDuringScan": {"replaceRows": [_row(0, [0, 1], text="replacement payload")]},
    })
    outcome_searches = {
        "empty-table", "empty-query", "zero-limit", "negative-limit", "ordered-top-one",
        "limit-beyond-corpus", "zero-query-retains-candidates", "prefix-dimensions",
        "negative-zero-and-positive", "finite-score-filter", "malformed-derived-blobs",
        "signed-rowid-batch-boundary",
    }
    identity_searches = {
        "ordered-top-one", "limit-beyond-corpus", "tie-order-is-rowid-not-path",
        "full-source-and-range-identities", "model-aliases-filter-before-limit",
        "source-memory-only", "source-sessions-only", "empty-sources-is-host-no-filter",
        "empty-primary-model", "utf16-nul-snippet-0", "utf16-nul-snippet-4",
        "utf16-nul-snippet-5", "utf16-database-snippet", "signed-rowid-batch-boundary",
        "insert-after-full-batch", "hydrate-before-batch-mutation", "external-wal-payload-snapshot",
    }
    for case in cases:
        name = case["id"].removeprefix("vector-")
        if case["input"]["kind"] == "cosine" or name in outcome_searches:
            case["covers"].append("retrieval.vector-scoring.outcomes")
        if name in identity_searches:
            case["covers"].append("retrieval.vector-scoring.boundaries")
    return cases


def _number(value: Any) -> float:
    if isinstance(value, dict):
        return {"nan": math.nan, "infinity": math.inf, "-infinity": -math.inf}[value["special"]]
    return float(value)


def _vector(values: list[Any]) -> list[float]:
    return [_number(value) for value in values]


def _scalar(value: float) -> dict[str, Any]:
    if math.isfinite(value):
        return {"value": value}
    return {"nonfinite": "nan" if math.isnan(value) else "infinity" if value > 0 else "-infinity"}


def run_vector_scoring(arguments: dict[str, Any]) -> dict[str, Any]:
    """Call actual production cosine/candidate owners over fixture-owned SQLite."""
    from memory_core.cancellation import CancellationSignal, OperationAbortedError
    from memory_core.config import MemoryConfig
    from memory_core.flags import FeatureFlags
    from memory_core.index.sqlite_store import SQLiteMemoryStore
    from memory_core.index.vector import cosine_similarity

    value = deepcopy(arguments)
    if value["kind"] == "cosine":
        return _scalar(cosine_similarity(_vector(value["a"]), _vector(value["b"])))
    if value["kind"] != "search":
        raise ValueError(f"Unsupported vector scoring operation: {value['kind']}")
    if value.get("backend", "scan") != "scan":
        raise ValueError("Only the portable CPU vector capability is verified")
    with tempfile.TemporaryDirectory(prefix="memory-vector-scoring-") as temporary:
        root = Path(temporary)
        store_path = root / "index.sqlite"
        encoding = value.get("encoding", "UTF-8")
        if encoding not in {"UTF-8", "UTF-16le", "UTF-16be"}:
            raise ValueError("Unsupported vector fixture database encoding")
        if encoding != "UTF-8":
            with sqlite3.connect(store_path) as encoding_db:
                encoding_db.execute(f"PRAGMA encoding='{encoding}'")
                encoding_db.execute("CREATE TABLE fixture_encoding(anchor INTEGER)")
        store = SQLiteMemoryStore(MemoryConfig(
            workspace_dir=root, store_path=store_path, flags=FeatureFlags(vector_search=False),
        ), None)
        db = store.connect()
        writer = None
        try:
            table = "chunks"

            def arrange(rows: list[dict[str, Any]], connection: sqlite3.Connection | None = None) -> None:
                destination = db if connection is None else connection
                for row in rows:
                    embedding = (bytes.fromhex(row["embeddingBytesHex"])
                                 if "embeddingBytesHex" in row else
                                 json.dumps(_vector(row["embedding"]), allow_nan=False))
                    destination.execute(
                        f"INSERT OR REPLACE INTO {table} "
                        "(rowid,id,path,start_line,end_line,source,text,embedding) VALUES (?,?,?,?,?,?,?,?)",
                        (int(row["rowid"]), row["id"], row["path"], row["startLine"],
                         row["endLine"], row["source"], row["text"], embedding),
                    )
                    destination.execute("INSERT OR REPLACE INTO memory_index_chunk_details "
                               "(chunk_id,hash,model,updated_at) VALUES (?,?,?,?)",
                               (row["id"], hashlib.sha256(row["text"].encode()).hexdigest(), row["model"], 1))

            arrange(value["rows"])
            db.commit()
            observed = any(value.get(key) for key in (
                "observe", "preAborted", "abortAfterBatch", "mutateAfterBatch", "externalDuringScan",
            ))
            scanned: list[str] = []
            external_applied = False
            if value.get("externalDuringScan"):
                db.execute("PRAGMA journal_mode = WAL")
                writer = sqlite3.connect(store_path)
                writer.execute("PRAGMA foreign_keys = ON")
            if observed:
                db.execute("ALTER TABLE chunks RENAME TO fixture_chunks")
                table = "fixture_chunks"

                def observe(rowid: int, embedding: Any) -> Any:
                    nonlocal external_applied
                    scanned.append(str(rowid))
                    if value.get("externalDuringScan") and not external_applied:
                        external_applied = True
                        arrange(value["externalDuringScan"]["replaceRows"], writer)
                        writer.commit()
                    return embedding

                db.create_function("observe_vector", 2, observe)
                db.execute("CREATE VIEW chunks AS SELECT rowid AS rowid,id,path,start_line,end_line,"
                           "source,text,observe_vector(rowid,embedding) AS embedding FROM fixture_chunks")
                db.commit()

            class FixtureSignal(CancellationSignal):
                changed = False

                def throw_if_aborted(self) -> None:
                    if len(scanned) >= 256 and not self.changed:
                        self.changed = True
                        mutation = value.get("mutateAfterBatch")
                        if mutation:
                            for identifier in mutation.get("deleteIds", []):
                                db.execute(f"DELETE FROM {table} WHERE id=?", (identifier,))
                            arrange(mutation.get("replaceRows", []))
                            db.commit()
                        if value.get("abortAfterBatch"):
                            self.abort(_CANCEL_REASON)
                    super().throw_if_aborted()

            signal = FixtureSignal() if observed else None
            if signal is not None and value.get("preAborted"):
                signal.abort(_CANCEL_REASON)
            try:
                rows = store.search_vector_candidates(
                    _vector(value["queryVec"]), limit=value["limit"],
                    provider_model=value["providerModel"],
                    provider_model_aliases=value.get("providerModelAliases"),
                    sources=set(value["sources"]) if value.get("sources") is not None else None,
                    snippet_max_chars=value["snippetMaxChars"], signal=signal, db=db,
                )
                result: dict[str, Any] = {"rows": [{
                    "id": row.id, "path": row.path, "startLine": row.start_line,
                    "endLine": row.end_line, "score": row.vector_score,
                    "snippet": row.snippet, "source": row.source,
                } for row in rows]}
            except OperationAbortedError as error:
                if str(error) != _CANCEL_REASON:
                    raise
                result = {"rows": None, "aborted": True}
            if observed:
                result["observations"] = {"scannedRowids": scanned}
                if value.get("externalDuringScan"):
                    result["observations"]["externalRows"] = [
                        {"id": row["id"], "text": writer.execute(
                            f"SELECT text FROM {table} WHERE id=?", (row["id"],),
                        ).fetchone()[0]}
                        for row in value["externalDuringScan"]["replaceRows"]
                    ]
            return result
        finally:
            if writer is not None:
                writer.close()
            db.close()
