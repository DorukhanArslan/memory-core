"""Observer/error/input transport tests; no promotion candidate is executed."""
from copy import deepcopy
from dataclasses import dataclass
import errno
import json
from pathlib import Path
import sqlite3

import pytest

from equivalence.promotion_apply_reconcile_fixtures import build_promotion_apply_reconcile_cases
from equivalence.promotion_apply_runtime import (
    _error_record,
    _documents,
    _filesystem_snapshot,
    _json_value,
    _observe_path,
    _safe_path,
    _sqlite_snapshot,
    _validate_input,
    run_promotion_apply_reconcile,
)


def test_observing_an_empty_directory_never_opens_or_reads_it(tmp_path, monkeypatch):
    directory = tmp_path / "MEMORY.md"
    directory.mkdir()

    def forbidden(*args, **kwargs):
        raise AssertionError("A document directory was opened as a regular file")

    monkeypatch.setattr("equivalence.promotion_apply_runtime.os.open", forbidden)
    observed = _observe_path(directory)
    assert observed["kind"] == "directory"
    assert "hex" not in observed and "text" not in observed and "observationError" not in observed
    tree = _filesystem_snapshot(tmp_path)
    assert [entry["kind"] for entry in tree] == ["directory", "directory"]


def test_documents_keep_missing_and_regular_file_bytes_text_and_full_stats(tmp_path):
    missing = _observe_path(tmp_path / "source.md")
    assert missing == {"path": str(tmp_path / "source.md"), "kind": "missing"}
    filename = tmp_path / "DREAMS.md"
    content = "Cedar 🌲\r\n"
    filename.write_bytes(content.encode())
    observed = _observe_path(filename)
    assert observed["kind"] == "file"
    assert observed["text"] == content
    assert observed["hex"] == content.encode().hex()
    assert {"st_mode", "st_ino", "st_dev", "st_size", "st_mtime_ns", "st_ctime_ns"} <= observed["stat"].keys()
    assert observed["openedStat"]["st_ino"] == observed["stat"]["st_ino"]


def test_public_document_codec_matches_typed_order_without_erasing_raw_stats(tmp_path):
    (tmp_path / "MEMORY.md").mkdir()
    (tmp_path / "DREAMS.md").write_bytes(b"Cedar\xff\n")
    public, rich = _documents(tmp_path, ["memory/source.md", "MEMORY.md", "DREAMS.md", "MEMORY.md"])
    assert public == [
        {"path": "memory/source.md", "exists": False, "kind": "missing"},
        {"path": "MEMORY.md", "exists": True, "kind": "directory"},
        {"path": "DREAMS.md", "exists": True, "kind": "file", "bytes": "4365646172ff0a", "text": "Cedar\ufffd\n"},
    ]
    assert rich[1]["stat"] and rich[2]["stat"]
    assert rich[2]["textError"]["name"] == "UnicodeDecodeError"


def test_filesystem_observer_does_not_follow_directory_symlinks(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "note.md").write_text("ordinary")
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    observed = _observe_path(link)
    assert observed["kind"] == "symlink" and observed["link"] == str(real)
    assert "hex" not in observed
    tree = _filesystem_snapshot(tmp_path)
    assert sum(entry["kind"] == "file" for entry in tree) == 1


def test_invalid_utf8_remains_full_bytes_and_an_explicit_observation_codec_error(tmp_path):
    filename = tmp_path / "binary"
    filename.write_bytes(b"\xff\x00")
    observed = _observe_path(filename)
    assert observed["hex"] == "ff00"
    assert observed["textError"]["name"] == "UnicodeDecodeError"
    assert observed["textUtf8SurrogateEscape"].encode("utf-8", errors="surrogateescape") == b"\xff\x00"
    json.dumps(observed, ensure_ascii=True, allow_nan=False)


def test_error_codec_keeps_actual_errno_filename_attributes_traceback_and_chains(tmp_path):
    filename = str(tmp_path / "MEMORY.md")
    try:
        try:
            raise FileNotFoundError(errno.ENOENT, "missing source", "memory/source.md")
        except FileNotFoundError as cause:
            error = IsADirectoryError(errno.EISDIR, "Is a directory", filename)
            error.fixture_field = {"exact": [False, 0, None]}
            error.add_note("An actual error codec test, not an apply invocation")
            raise error from cause
    except IsADirectoryError as actual:
        observed = _error_record(actual)
    assert observed["name"] == "IsADirectoryError"
    assert observed["attributes"]["errno"] == errno.EISDIR
    assert observed["attributes"]["filename"] == filename
    assert observed["attributes"]["fixture_field"] == {"exact": [False, 0, None]}
    assert observed["cause"]["attributes"]["errno"] == errno.ENOENT
    assert observed["context"]["attributes"]["filename"] == "memory/source.md"
    assert "test_error_codec_keeps_actual_errno" in observed["traceback"]
    assert observed["notes"] == ["An actual error codec test, not an apply invocation"]
    assert observed["suppressContext"] is True
    json.dumps(observed, allow_nan=False)


def test_error_codec_handles_recursive_exception_attributes_without_faking_an_error():
    actual = RuntimeError("actual message")
    actual.loop = actual
    observed = _error_record(actual)
    assert observed["message"] == "actual message"
    assert observed["attributes"]["loop"] == {"$type": "exception-reference", "name": "RuntimeError"}


def test_full_dataclass_extension_fields_are_not_projected_away():
    @dataclass
    class ActualReceipt:
        path: Path
        content: bytes
        index_extension: dict

    observed = _json_value(ActualReceipt(Path("index.sqlite"), b"\x00\xff", {"indexed_files": 0, "chunks": 0}))
    assert observed["fields"] == {"path": "index.sqlite", "content": {"type": "blob", "hex": "00ff"},
                                  "index_extension": {"indexed_files": 0, "chunks": 0}}


def test_independent_readonly_sql_snapshot_keeps_complete_schema_rows_and_blob_bytes(tmp_path):
    filename = tmp_path / "index.sqlite"
    with sqlite3.connect(filename) as db:
        db.execute("CREATE TABLE ordinary (id TEXT PRIMARY KEY, value BLOB)")
        db.execute("CREATE TABLE compact (id TEXT PRIMARY KEY, value INTEGER) WITHOUT ROWID")
        db.execute("CREATE VIEW ordinary_view AS SELECT * FROM ordinary")
        db.execute("INSERT INTO ordinary VALUES ('a',X'00FF')")
        db.execute("INSERT INTO compact VALUES ('b',2)")
    before = filename.read_bytes()
    observed = _sqlite_snapshot(filename)
    assert "observationError" not in observed
    assert observed["schemaCount"] == len(observed["schema"])
    assert observed["snapshotTransaction"] == {"mode": "deferred", "active": True, "queryOnly": 1}
    tables = {table["name"]: table for table in observed["tables"]}
    assert {entry["name"] for entry in observed["schema"] if entry["type"] == "table"} == tables.keys()
    assert any(entry["name"] == "ordinary_view" for entry in observed["schema"])
    assert tables["ordinary"]["rows"] == [{"__rowid__": 1, "id": "a", "value": {"type": "blob", "hex": "00ff"}}]
    assert tables["compact"]["rows"] == [{"id": "b", "value": 2}]
    assert tables["ordinary"]["rowCount"] == tables["compact"]["rowCount"] == 1
    assert {"cid", "name", "type", "notnull", "dflt_value", "pk", "hidden"} == tables["ordinary"]["columns"][0].keys()
    assert filename.read_bytes() == before


def test_approved_literal_validates_without_executing_or_mutating_the_candidate():
    arguments = build_promotion_apply_reconcile_cases()[0]["input"]
    original = deepcopy(arguments)
    assert _validate_input(arguments) == original
    assert arguments == original
    assert arguments["directories"] == ["MEMORY.md"]
    assert arguments["files"] == {}
    assert arguments["candidates"][0]["path"] not in arguments["files"]


def test_actual_runner_rejects_a_broader_input_before_any_apply_invocation():
    value = build_promotion_apply_reconcile_cases()[0]["input"]
    value["options"]["limit"] += 1
    with pytest.raises(ValueError, match="only its reviewed literal"):
        run_promotion_apply_reconcile(value)


@pytest.mark.parametrize("relative", ["/absolute", "../escape", "memory/../escape", "memory\\windows", ".", "memory//note"])
def test_fixture_paths_are_owned_before_setup_or_any_owner_call(tmp_path, relative):
    with pytest.raises(ValueError, match="relative fixture path"):
        _safe_path(tmp_path, relative)


@pytest.mark.parametrize("fault", ["kind", "unknown-option", "unknown-field", "boolean-time", "nontext-file"])
def test_invalid_literal_requests_fail_before_any_apply_invocation(fault):
    value = build_promotion_apply_reconcile_cases()[0]["input"]
    if fault == "kind":
        value["kind"] = "not-apply"
    elif fault == "unknown-option":
        value["options"]["model"] = "unapproved"
    elif fault == "unknown-field":
        value["expectedResult"] = {}
    elif fault == "boolean-time":
        value["nowMs"] = True
    else:
        value["files"]["memory/source.md"] = b"not literal text"
    with pytest.raises(ValueError):
        _validate_input(value)
