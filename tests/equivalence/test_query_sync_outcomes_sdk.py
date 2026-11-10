"""Query-sync evidence keeps actual bytes, public returns, and SQL snapshots."""
from contextlib import closing
from copy import deepcopy
from dataclasses import fields
import hashlib
import json
import os
from pathlib import Path
import sqlite3

import pytest

from equivalence.query_sync_outcomes_sdk import (
    _capture_sources,
    _persist_tool_envelope,
    _search_return_custody,
    _sql_rows,
)
from memory_core.host.managed_index import _ManagedSearchResults
from memory_core.index.hybrid import HYBRID_METADATA_MISSING, HybridResult
from memory_core.tools.search_factory import serialize_search_tool_result


def _directories(tmp_path):
    workspace, evidence = tmp_path / "workspace", tmp_path / "evidence"
    workspace.mkdir()
    evidence.mkdir()
    return workspace, evidence


def _by_path(entries):
    return {entry["path"]: entry for entry in entries}


def test_source_capture_keeps_unexpected_files_declared_absence_and_invalid_utf8_bytes(tmp_path):
    workspace, evidence = _directories(tmp_path)
    source = workspace / "memory" / "unexpected.bin"
    source.parent.mkdir()
    payload = b"actual bytes\x00\xff\xfe\xc3\xa7\n"
    source.write_bytes(payload)
    os.utime(source, ns=(1_700_000_000_123_456_789,) * 2)

    receipt = _capture_sources(workspace, {"declared-missing.md"}, evidence, "actual")

    entries, common = _by_path(receipt["entries"]), _by_path(receipt["common"])
    assert set(entries) == {"declared-missing.md", "memory/unexpected.bin"}
    assert entries["declared-missing.md"]["kind"] == "missing"
    assert entries["declared-missing.md"]["error"]["name"] == "FileNotFoundError"
    assert common["declared-missing.md"] == {"path": "declared-missing.md", "kind": "missing"}
    captured = entries["memory/unexpected.bin"]
    assert Path(captured["byteFile"]).read_bytes() == payload
    assert bytes.fromhex(captured["hex"]) == payload
    assert captured["sha256"] == hashlib.sha256(payload).hexdigest()
    assert captured["text"] == "actual bytes\x00\ufffd\ufffdç\n"
    assert captured["statBefore"]["st_mtime_ns"] == source.stat().st_mtime_ns
    assert captured["statAfter"]["st_size"] == len(payload)
    assert common["memory/unexpected.bin"]["mtimeMs"] == source.stat().st_mtime_ns / 1_000_000
    assert common["memory/unexpected.bin"]["hex"] == captured["hex"]
    assert json.loads((evidence / "sources-actual.json").read_text()) == receipt


def test_source_capture_records_rename_without_rewriting_bytes_or_mtime(tmp_path):
    workspace, evidence = _directories(tmp_path)
    old, renamed = workspace / "old.md", workspace / "renamed.md"
    payload = "Rename preserves the source. ç\n".encode()
    old.write_bytes(payload)
    os.utime(old, ns=(1_700_000_000_123_456_789,) * 2)
    declared = {"old.md", "renamed.md"}
    before = _capture_sources(workspace, declared, evidence, "before-rename")
    old_stat = old.stat()

    old.rename(renamed)
    after = _capture_sources(workspace, declared, evidence, "after-rename")

    previous, current = _by_path(before["entries"]), _by_path(after["entries"])
    assert previous["renamed.md"]["kind"] == "missing"
    assert current["old.md"]["kind"] == "missing"
    assert current["renamed.md"]["statBefore"]["st_ino"] == old_stat.st_ino
    assert current["renamed.md"]["statAfter"]["st_mtime_ns"] == old_stat.st_mtime_ns
    assert current["renamed.md"]["sha256"] == previous["old.md"]["sha256"]
    assert current["renamed.md"]["hex"] == previous["old.md"]["hex"]
    assert Path(current["renamed.md"]["byteFile"]).read_bytes() == payload
    assert _by_path(after["common"])["old.md"] == {"path": "old.md", "kind": "missing"}


def test_source_capture_distinguishes_same_bytes_touch_from_content_change(tmp_path):
    workspace, evidence = _directories(tmp_path)
    source = workspace / "MEMORY.md"
    payload = b"The content stays byte-for-byte identical.\n"
    source.write_bytes(payload)
    os.utime(source, ns=(1_700_000_000_000_000_000,) * 2)
    before = _capture_sources(workspace, {"MEMORY.md"}, evidence, "before-touch")

    os.utime(source, ns=(1_700_000_002_000_000_000,) * 2)
    after = _capture_sources(workspace, {"MEMORY.md"}, evidence, "after-touch")

    previous, current = before["common"][0], after["common"][0]
    assert {key: previous[key] for key in ("hex", "sha256", "text", "size")} == {
        key: current[key] for key in ("hex", "sha256", "text", "size")
    }
    assert current["mtimeMs"] != previous["mtimeMs"]
    assert current["mtimeMs"] == source.stat().st_mtime_ns / 1_000_000
    assert Path(before["entries"][0]["byteFile"]).read_bytes() == payload
    assert Path(after["entries"][0]["byteFile"]).read_bytes() == payload


def _result(**annotations):
    return HybridResult(path="MEMORY.md", start_line=1, end_line=2, score=0.5,
        vector_score=0.0, text_score=0.25, snippet="Actual private result. ç",
        source="memory", **annotations)


def test_public_envelope_is_durable_before_unknown_private_return_fails(tmp_path):
    details = {"results": [{"path": "MEMORY.md", "snippet": "Exact public source. ç",
                            "score": 0, "importance": None, "source": "memory"}],
               "provider": "none", "citations": "off", "partial": False,
               "warning": "Retain the complete public warning.",
               "action": "Retain the complete public action.",
               "debug": {"hits": 1, "searchMs": 0, "extension": [None, False, 0]}}
    envelope = serialize_search_tool_result(details)
    original = deepcopy(envelope)

    persisted = _persist_tool_envelope(tmp_path, "query", envelope)
    payload = Path(persisted["path"]).read_bytes()

    class UnknownPrivate:
        def __str__(self):
            raise AssertionError("Private returns must never be coerced to text")

        __repr__ = __str__

    with pytest.raises(TypeError, match="not JSON serializable"):
        _search_return_custody([_result(provenance=UnknownPrivate())])

    assert json.loads(payload) == original
    assert json.loads(json.loads(payload)["content"][0]["text"]) == details
    assert "ç".encode() in payload
    assert persisted["bytes"] == len(payload)
    assert persisted["sha256"] == hashlib.sha256(payload).hexdigest()
    assert Path(persisted["path"]).read_bytes() == payload
    assert envelope == original


def test_managed_return_custody_keeps_every_private_field_and_pinned_status_attribute():
    row = _result(importance=None, triggers=0)
    pinned = {"provider": "none", "custom": {"indexIdentity": {"status": "valid"},
               "automaticRebuildNotice": {"sequence": 1, "warning": "Actual repair notice."}},
              "lastSyncError": "Actual pinned generation error."}
    returned = _ManagedSearchResults([row], pinned)
    public_before = deepcopy(row.to_payload())

    custody = _search_return_custody(returned)

    assert json.loads(json.dumps(custody, allow_nan=False)) == custody
    assert custody["returnType"] == {"module": type(returned).__module__,
                                      "qualname": type(returned).__qualname__}
    assert set(custody["result"][0]) == {field.name for field in fields(row)}
    assert custody["result"][0]["importance"] is None
    assert custody["result"][0]["triggers"] == 0
    for name in ("project_key", "provenance", "source_mtime", "_vector_id"):
        assert getattr(row, name) is HYBRID_METADATA_MISSING
        assert custody["result"][0][name] == {"$sdkPrivate": "HYBRID_METADATA_MISSING"}
    assert custody["result"][0]["_retrieval_mode"] == row._retrieval_mode
    assert custody["returnAttributes"] == {"_memory_search_status": pinned}
    custody["returnAttributes"]["_memory_search_status"]["custom"]["indexIdentity"]["status"] = "copy"
    assert returned._memory_search_status is pinned
    assert pinned["custom"]["indexIdentity"] == {"status": "valid"}
    assert returned[0] is row and row.to_payload() == public_before


@pytest.mark.parametrize("row_factory", [None, sqlite3.Row], ids=["tuple", "sqlite-row"])
def test_sql_capture_keeps_existing_pinned_reader_during_real_wal_publication(tmp_path, row_factory):
    path = tmp_path / "index.sqlite"
    with closing(sqlite3.connect(path)) as writer, closing(sqlite3.connect(path)) as reader:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.executescript('''
            CREATE TABLE documents(id INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT, raw BLOB);
            CREATE TABLE "quoted ""table"(label TEXT, optional INTEGER);
            CREATE INDEX document_body ON documents(body);
            CREATE VIEW document_view AS SELECT id, body FROM documents;
            CREATE TRIGGER document_guard BEFORE DELETE ON documents BEGIN SELECT 1; END;
        ''')
        writer.execute("INSERT INTO documents(body,raw) VALUES (?,?)", ("pinned ç", b"\x00\xff"))
        writer.execute('INSERT INTO "quoted ""table" VALUES (?,?)', ("all columns", None))
        writer.commit()
        reader.row_factory = row_factory
        reader.execute("BEGIN")
        assert tuple(reader.execute("SELECT body FROM documents").fetchone()) == ("pinned ç",)
        schema_before = [dict(zip(("type", "name", "tbl_name", "sql"), row, strict=True))
                         for row in reader.execute(
                             "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")]

        writer.execute("UPDATE documents SET body=?,raw=?", ("published later", b"new bytes"))
        writer.execute("CREATE TABLE later_publication(value TEXT)")
        writer.execute("INSERT INTO later_publication VALUES ('new schema')")
        writer.commit()
        assert writer.execute("SELECT body FROM documents").fetchone() == ("published later",)

        receipt = _sql_rows(reader)

        assert reader.in_transaction
        assert reader.row_factory is row_factory
        assert receipt["schema"] == schema_before
        assert set(receipt["tables"]) == {"documents", "quoted \"table", "sqlite_sequence"}
        assert receipt["tables"]["documents"] == [
            {"id": 1, "body": "pinned ç", "raw": {"blobHex": "00ff"}}]
        assert receipt["tables"]["quoted \"table"] == [{"label": "all columns", "optional": None}]
        assert receipt["tables"]["sqlite_sequence"] == [{"name": "documents", "seq": 1}]
        assert tuple(reader.execute("SELECT body FROM documents").fetchone()) == ("pinned ç",)
        reader.rollback()
        assert tuple(reader.execute("SELECT body FROM documents").fetchone()) == ("published later",)
        assert reader.execute("SELECT value FROM later_publication").fetchone()[0] == "new schema"
