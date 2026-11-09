"""Actual curated commits consume the dispatch's live trusted write observer."""
from concurrent.futures import ThreadPoolExecutor
import errno
import threading

import pytest

import memory_core.curation as curation_module
from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
from memory_core.flags import FeatureFlags
from memory_core.host import HostKit, SessionState
from memory_core.memory_write_provenance import MemoryWriteProvenanceObserver


NOW = 1_794_182_400_000
SESSION = SessionState.new(session_key="agent:main:main", session_id="curation-turn")


def _setup(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    ledger = MemoryArtifactProvenanceStore(tmp_path / "provenance.sqlite")
    config = MemoryConfig(workspace_dir=root, store_path=tmp_path / "index.sqlite",
                          flags=FeatureFlags(vector_search=False, temporal_decay=False))
    memory = Memory.from_workspace(root, config=config, initialize=False)
    kit = HostKit(memory, artifact_provenance=ledger, now_ms=lambda: NOW)
    return root, ledger, kit


def _observer(root, ledger, origin):
    return MemoryWriteProvenanceObserver(store=ledger, mutation_root=root, workspace_dir=root,
        resolve_origin_class=origin, now=lambda: NOW, session_id=SESSION.session_id,
        session_key=SESSION.session_key)


def test_bound_dispatch_reads_live_trust_for_both_atomic_edit_and_daily_append(tmp_path):
    root, ledger, kit = _setup(tmp_path)
    taint = {"value": False}
    observer = _observer(root, ledger, lambda: "untrusted" if taint["value"] else "agent")
    dispatch = kit.dispatcher(SESSION, write_provenance=observer)
    assert dispatch("add_memory_entry", {"section": "Facts", "text": "Calibration is cedar."})["status"] == "ok"
    taint["value"] = True
    assert dispatch("append_daily_note", {"text": "External calibration is pine.", "date": "2026-11-09"})["status"] == "ok"
    records = dict(ledger.list(root))
    assert records["MEMORY.md"].origin_class == "agent"
    assert records["memory/2026-11-09.md"].origin_class == "untrusted"
    assert all(record.session_id == SESSION.session_id for record in records.values())
    assert "Calibration is cedar." in (root / "MEMORY.md").read_text()
    assert "External calibration is pine." in (root / "memory/2026-11-09.md").read_text()


def test_two_thread_dispatches_on_one_kit_keep_distinct_observers(tmp_path, monkeypatch):
    root, ledger, kit = _setup(tmp_path)
    a_reading, b_dispatched = threading.Event(), threading.Event()
    curator = kit._curator
    read_target, dispatch_call = curator._read_target, curator._dispatch_call
    first_read = {"pending": True}

    def read(name):
        if name == "MEMORY.md" and first_read["pending"]:
            first_read["pending"] = False
            a_reading.set()
            assert b_dispatched.wait(5)
        return read_target(name)

    def dispatch(name, arguments, **options):
        if name == "upsert_user_directive":
            b_dispatched.set()
        return dispatch_call(name, arguments, **options)

    monkeypatch.setattr(curator, "_read_target", read)
    monkeypatch.setattr(curator, "_dispatch_call", dispatch)
    a = _observer(root, ledger, lambda: "agent")
    b = _observer(root, ledger, lambda: "untrusted")
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(kit.dispatch, "add_memory_entry", {"section": "Facts", "text": "Owner fact."},
                            session=SESSION, write_provenance=a)
        assert a_reading.wait(5)
        second = pool.submit(kit.dispatch, "upsert_user_directive", {"text": "External directive."},
                             session=SESSION, write_provenance=b)
        assert first.result(timeout=10)["status"] == "ok"
        assert second.result(timeout=10)["status"] == "ok"
    records = dict(ledger.list(root))
    assert records["MEMORY.md"].origin_class == "agent"
    assert records["USER.md"].origin_class == "untrusted"


@pytest.mark.parametrize("code,uncertain", [(errno.EIO, True), (errno.EACCES, False)])
def test_failed_atomic_commit_retains_owner_classification_and_restores_dispatch_context(tmp_path, monkeypatch, code, uncertain):
    root, ledger, kit = _setup(tmp_path)
    replace = curation_module.os.replace

    def fail(source, target):
        if target == root / "MEMORY.md":
            raise OSError(code, "Owned commit failed")
        return replace(source, target)

    monkeypatch.setattr(curation_module.os, "replace", fail)
    observer = _observer(root, ledger, lambda: "untrusted")
    result = kit.dispatch("add_memory_entry", {"section": "Facts", "text": "Never committed."},
                          session=SESSION, write_provenance=observer)
    assert result["status"] == "error"
    assert not (root / "MEMORY.md").exists()
    records = ledger.list(root)
    if uncertain:
        # The stub knows it did not replace, but the real publisher dispatched
        # an EIO rename and cannot turn that private knowledge into a guarantee.
        assert result["publication"] == "uncertain"
        assert len(records) == 1 and records[0][1].origin_class == "untrusted"
    else:
        assert "publication" not in result and records == []
    assert list(root.glob(".*.tmp")) == []
    assert kit.dispatch("append_daily_note", {"text": "Default untracked call.", "date": "2026-11-10"},
                        session=SESSION)["status"] == "ok"
    assert ledger.list(root) == records


def test_file_is_rechecked_after_provenance_reservation_before_atomic_replace(tmp_path):
    root, ledger, kit = _setup(tmp_path)
    target = root / "MEMORY.md"
    target.write_text("# MEMORY.md\n")

    def concurrent_change():
        target.write_text("# MEMORY.md\n\nConcurrent owner edit.\n")
        return "agent"

    result = kit.dispatch("add_memory_entry", {"section": "Facts", "text": "Must not overwrite."},
                          session=SESSION, write_provenance=_observer(root, ledger, concurrent_change))
    assert result["status"] == "error"
    assert target.read_text() == "# MEMORY.md\n\nConcurrent owner edit.\n"
    assert ledger.list(root) == [] and list(root.glob(".*.tmp")) == []
