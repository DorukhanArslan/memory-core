"""Physical fixture custody; these tests do not invoke a development host."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from equivalence.query_sync_cold_retry import build_cases
from equivalence.query_sync_cold_retry_sdk import (
    _PublicationSidecarFault,
    _capture_sources,
    _literal,
    _original_error,
    _persist_tool_envelope,
    _query_labels,
    _search_return_custody,
)
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.host.managed_index import ManagedSQLiteMemoryStore
from memory_core.tools.search_factory import serialize_search_tool_result
from memory_core.workspace import MemoryWorkspace


def _fault(index, directory):
    return _PublicationSidecarFault(index, directory, build_cases()[1]["input"]["fault"])


@pytest.mark.parametrize("existing", [False, True])
def test_owned_physical_sidecar_fault_restores_exact_original_inode_and_bytes(tmp_path, existing):
    index = tmp_path / "index.sqlite"
    journal = Path(str(index) + "-journal")
    if existing:
        journal.write_bytes(b"actual saved sidecar\x00\xff")
        original = journal.stat()
    fault = _fault(index, tmp_path)

    receipt = fault.arm()

    assert journal.is_symlink() and not journal.exists()
    assert receipt["targetParentBefore"]["kind"] == "missing"
    assert receipt["actualFollowError"]["name"] == "FileNotFoundError"
    assert receipt["armed"]["stat"]["st_ino"] == journal.lstat().st_ino
    fault.remove()

    assert not fault.armed and not fault.saved.exists()
    assert receipt["afterUnlink"]["kind"] == "missing"
    if existing:
        assert journal.stat().st_ino == original.st_ino
        assert journal.read_bytes() == b"actual saved sidecar\x00\xff"
        assert receipt["afterRemoval"]["hex"] == b"actual saved sidecar\x00\xff".hex()
    else:
        assert receipt["afterRemoval"]["kind"] == "missing"


def test_sidecar_fixture_refuses_existing_alias_without_following_it(tmp_path):
    index = tmp_path / "index.sqlite"
    foreign = tmp_path / "foreign"
    foreign.write_bytes(b"untouched")
    journal = Path(str(index) + "-journal")
    journal.symlink_to(foreign)
    before = journal.lstat()

    with pytest.raises(RuntimeError, match="existing sidecar alias"):
        _fault(index, tmp_path).arm()

    assert journal.lstat().st_ino == before.st_ino
    assert foreign.read_bytes() == b"untouched"


def test_fault_is_real_sqlite_refusal_without_replacing_owner_or_changing_sources(tmp_path):
    root, evidence = tmp_path / "workspace", tmp_path / "evidence"
    root.mkdir()
    evidence.mkdir()
    source = root / "MEMORY.md"
    source.write_bytes(b"Actual source remains unchanged.\x00\xff\n")
    config = MemoryConfig(root, store_path=tmp_path / "index.sqlite", session_search=False,
                          flags=FeatureFlags(vector_search=False))
    workspace = MemoryWorkspace(root)
    store = ManagedSQLiteMemoryStore(config, workspace, memory_publication="on-search")
    before = _capture_sources(root, {"MEMORY.md"}, evidence, "before")
    fault = _fault(store.path, tmp_path)
    try:
        fault.arm()
        # The original connection performs a genuine write, without a mocked
        # publisher or a fixture-provided exception.
        with store.connect() as db:
            with pytest.raises(sqlite3.OperationalError, match="unable to open database file") as raised:
                db.execute("CREATE TABLE real_refused_publication(value TEXT)")
        recorded = _original_error(raised.value)
        assert recorded["sqlite_errorcode"] & 255 == sqlite3.SQLITE_CANTOPEN
        fault.remove()
        after = _capture_sources(root, {"MEMORY.md"}, evidence, "after")

        assert after["common"] == before["common"]
        assert store._workspace is workspace and store.config is config and not store.closed
        assert store.lifecycle_snapshot()["operationCount"] == 0
        with store.connect() as db:
            assert db.execute("SELECT name FROM sqlite_master WHERE name='real_refused_publication'").fetchall() == []
    finally:
        if fault.armed:
            fault.remove()
        store.close()


def test_full_public_envelope_is_durable_before_private_codec_failure(tmp_path):
    details = {"results": [], "disabled": True, "unavailable": True, "error": "actual error",
               "warning": "actual warning ç", "action": "actual action", "extension": [None, False, 0]}
    returned = serialize_search_tool_result(deepcopy(details))
    receipt = _persist_tool_envelope(tmp_path, "faulted", returned)
    payload = Path(receipt["path"]).read_bytes()

    class UnknownPrivate:
        def __str__(self):
            raise AssertionError("Never stringify a private return")

        __repr__ = __str__

    with pytest.raises(TypeError, match="not JSON serializable"):
        _search_return_custody([UnknownPrivate()])

    assert Path(receipt["path"]).read_bytes() == payload
    assert json.loads(payload) == returned
    assert json.loads(json.loads(payload)["content"][0]["text"]) == details
    assert receipt["sha256"] == hashlib.sha256(payload).hexdigest()


def test_changed_literal_is_rejected_before_child_acquisition(tmp_path):
    value = deepcopy(build_cases()[1]["input"])
    value["queries"]["afterRemoval"]["query"] = "changed"
    with pytest.raises(ValueError, match="exact frozen"):
        _literal(value)


@pytest.mark.parametrize("case", build_cases(), ids=lambda case: case["id"])
def test_sorted_transport_object_cannot_reorder_frozen_public_search_steps(case):
    original = case["input"]
    transported = json.loads(json.dumps(original, sort_keys=True))
    expected = [step["label"] for step in original["steps"]
                if step["operation"] == "public-memory-search"]

    assert _literal(transported)["id"] == case["id"]
    assert _query_labels(transported) == expected
    if "fault" in transported:
        assert list(transported["queries"]) == ["afterRemoval", "faulted"]
        assert _query_labels(transported) == ["faulted", "afterRemoval"]


@pytest.mark.parametrize("mutation", ["missing", "duplicate"])
def test_query_schedule_requires_each_declared_label_exactly_once(mutation):
    value = deepcopy(build_cases()[0]["input"])
    step = next(row for row in value["steps"] if row["operation"] == "public-memory-search")
    if mutation == "missing":
        value["steps"].remove(step)
    else:
        value["steps"].append(deepcopy(step))
    with pytest.raises(ValueError, match="exactly one ordered"):
        _query_labels(value)
