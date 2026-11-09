"""Real canonical same-line fragment collisions retain the native publication owner."""
from dataclasses import replace
import json
import os
from pathlib import Path

from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.index.identity import INDEX_SOURCES_TABLE
from memory_core.index.publication import (
    ChunkProvenance, ChunkRecallMetadata, PreparedChunk, PreparedIndexRevision, PreparedSource,
)
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.workspace import MemoryWorkspace


def _store(tmp_path):
    config = MemoryConfig(workspace_dir=tmp_path, flags=FeatureFlags(vector_search=False))
    return SQLiteMemoryStore(config, None), MemoryWorkspace(tmp_path)


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    os.utime(path, ns=(1700000000000000000, 1700000000000000000))


def test_long_single_line_matches_original_canonical_ids_and_unchanged_input_stays_unchanged(tmp_path, monkeypatch):
    capture = json.loads((Path(__file__).parents[1] / "fixtures/entry-provenance-long-line-native.json").read_text())
    _write(tmp_path / "MEMORY.md", capture["input"]["content"])
    store, workspace = _store(tmp_path)
    monkeypatch.setattr("memory_core.index.sqlite_store.time.time_ns", lambda: 1800000000000000000)
    store.reindex(workspace)
    before = store.read_published_index()
    original = capture["nativeRaw"][0]
    # The full original capture remains available. This regression compares the
    # deterministic identity fields; its uncontrolled publication clock is not
    # a paired acceptance result and is never fed into the SDK.
    fields = ("id", "path", "source", "startLine", "endLine", "text", "hash", "model")
    assert [{key: row[key] for key in fields} for row in before["chunks"]] == sorted(
        ({key: row[key] for key in fields} for row in original["chunks"]), key=lambda row: row["id"])
    assert len(before["chunks"]) == len(before["fts"]) == len(before["provenance"]) == len(before["recall"]) == 2
    assert before["provenance"] == original["provenance"]
    assert before["recall"] == original["recall"]
    with store.connect() as db:
        assert db.execute(f"SELECT chunk_count FROM {INDEX_SOURCES_TABLE}").fetchall() == [(2,)]
    monkeypatch.setattr("memory_core.index.sqlite_store.time.time_ns", lambda: 1800000001000000000)
    store.reindex(workspace)
    assert store.read_published_index() == before


def test_changed_same_size_same_time_and_sibling_path_retain_full_source_identity(tmp_path, monkeypatch):
    _write(tmp_path / "MEMORY.md", "a" * 5000)
    store, workspace = _store(tmp_path)
    monkeypatch.setattr("memory_core.index.sqlite_store.time.time_ns", lambda: 1800000000000000000)
    store.reindex(workspace)
    before = store.read_published_index()
    _write(tmp_path / "MEMORY.md", "a" * 4999 + "b")
    _write(tmp_path / "memory/sibling.md", "a" * 4999 + "b")
    monkeypatch.setattr("memory_core.index.sqlite_store.time.time_ns", lambda: 1800000001000000000)
    store.reindex(workspace)
    after = store.read_published_index()
    root = [row for row in after["chunks"] if row["path"] == "MEMORY.md"]
    sibling = [row for row in after["chunks"] if row["path"] == "memory/sibling.md"]
    assert len(root) == len(sibling) == 2
    assert {row["id"] for row in root}.isdisjoint(row["id"] for row in sibling)
    assert len({row["id"] for row in root} & {row["id"] for row in before["chunks"]}) == 1
    assert {row["hash"] for row in root} == {row["hash"] for row in sibling}
    assert all(row["updatedAt"] == 1800000001000 for row in after["chunks"])
    assert len(after["chunks"]) == len(after["fts"]) == len(after["details"]) == len(after["provenance"]) == len(after["recall"]) == 4
    assert after["sources"][0]["hash"] != before["sources"][0]["hash"]
    with store.connect() as db:
        assert db.execute(f"SELECT path,chunk_count FROM {INDEX_SOURCES_TABLE} ORDER BY path").fetchall() == [
            ("MEMORY.md", 2), ("memory/sibling.md", 2)]


def test_same_canonical_id_updates_complete_metadata_once_instead_of_salted_identity(tmp_path):
    _write(tmp_path / "MEMORY.md", "a" * 1600)
    store, workspace = _store(tmp_path)
    store.reindex(workspace)
    initial = store.read_published_index()
    row, = initial["chunks"]
    first = PreparedChunk(row["id"], row["path"], row["source"], row["startLine"], row["endLine"], row["text"],
                          (), row["hash"], row["model"], 10, ChunkProvenance("agent", "unknown", 10),
                          ChunkRecallMetadata(1, "first", "first"))
    final = replace(first, updated_at=20, provenance=ChunkProvenance("untrusted", "interactive", 20, "earlier"),
                    recall=ChunkRecallMetadata(9, "final", "final"))
    source = initial["sources"][0]
    prepared = PreparedIndexRevision((PreparedSource(source["path"], source["source"], source["hash"],
        source["mtime"], source["size"], (first, final)),), "{}", workspace=str(tmp_path))
    store.publish_prepared_index(prepared, store.index_revision())
    actual = store.read_published_index()
    published, = actual["chunks"]
    assert published["id"] == row["id"] and published["updatedAt"] == 20
    assert published["provenance"] == {"originClass": "untrusted", "sessionKind": "interactive", "observedAt": 20,
                                       "supersedesKey": "earlier"}
    assert published["recall"] == {"importance": 9, "triggers": "final", "projectKey": "final"}
    assert len(actual["fts"]) == len(actual["details"]) == len(actual["provenance"]) == len(actual["recall"]) == 1
