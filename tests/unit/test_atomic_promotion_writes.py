"""Publication failures pass through the actual promotion callers and origins ledger."""
from __future__ import annotations

import errno
import logging
import os
from pathlib import Path

import pytest

from memory_core.atomic_publication import MemoryAtomicPublicationError, hash_memory_content
from memory_core.consolidation.llm_consolidation import (
    ConsolidationOperation,
    DeepConsolidation,
    MemoryConsolidationPlan,
    commit_deep_consolidation,
    consolidation_candidate_fingerprint,
)
from memory_core.consolidation.origins import MemoryEntryOrigin, MemoryEntryOriginLedger
from memory_core.consolidation.promotion import PromotionCandidate, _append_to_memory


def _refuse_staging(monkeypatch, path):
    original = os.open

    def checked(file, flags, *args, **kwargs):
        if Path(file).parent == path.parent and flags & os.O_EXCL:
            raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), str(file))
        return original(file, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", checked)


def test_real_promotion_caller_opts_into_readonly_directory_in_place_fallback(tmp_path, monkeypatch):
    path = tmp_path / "MEMORY.md"
    path.write_text("# Memory\n\n- Prior fact.\n")
    path.chmod(0o640)
    _refuse_staging(monkeypatch, path)
    dates, reason = _append_to_memory(path, "## New section\n\n- New fact.\n")
    assert dates == () and reason is None
    assert path.read_text() == "# Memory\n\n- Prior fact.\n## New section\n\n- New fact.\n"
    assert path.stat().st_mode & 0o777 == 0o640
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("fault", ["partial-write", "sync"])
def test_real_promotion_fallback_restores_preimage_before_rethrowing(tmp_path, monkeypatch, fault):
    path = tmp_path / "MEMORY.md"
    before = "# Memory\n\n- Prior fact.\n"
    path.write_text(before)
    _refuse_staging(monkeypatch, path)
    inode = path.stat().st_ino
    original_write, original_sync = os.write, os.fsync
    triggered = False
    failure = OSError("literal fallback fault")

    def write(descriptor, data):
        nonlocal triggered
        if fault == "partial-write" and not triggered and os.fstat(descriptor).st_ino == inode:
            triggered = True
            original_write(descriptor, data[:2])
            raise failure
        return original_write(descriptor, data)

    def sync(descriptor):
        nonlocal triggered
        if fault == "sync" and not triggered and os.fstat(descriptor).st_ino == inode:
            triggered = True
            raise failure
        return original_sync(descriptor)

    monkeypatch.setattr(os, "write", write)
    monkeypatch.setattr(os, "fsync", sync)
    with pytest.raises(OSError) as raised:
        _append_to_memory(path, "## New section\n\n- New fact.\n")
    assert triggered and raised.value is failure
    assert path.read_text() == before
    assert not hasattr(raised.value, "publication")
    assert list(tmp_path.iterdir()) == [path]


def _candidate():
    return PromotionCandidate(
        key="child", path="memory/2026-07-01.md", start_line=1, end_line=1, snippet="New fact.",
        recall_count=3, daily_count=0, grounded_count=0, signal_count=3,
        avg_score=0.9, max_score=0.9, unique_queries=2, score=0.9,
        first_recalled_at="2026-07-01T10:00:00.000Z", last_recalled_at="2026-07-01T10:00:00.000Z",
    )


@pytest.mark.parametrize("fault", ["refused", "uncertain", "committed"])
def test_actual_consolidation_keeps_reserved_origins_after_dispatched_publication(tmp_path, monkeypatch, fault):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    path = workspace / "MEMORY.md"
    before = "# Memory\n\n<!-- memory-core-memory-promotion:parent -->\n- Prior fact.\n"
    path.write_text(before)
    ledger = MemoryEntryOriginLedger(lambda agent: tmp_path / f"{agent}.sqlite")
    ledger.record("main", [MemoryEntryOrigin("parent", "main", "session-a", "agent:main:session-a", "owner", 1000)])
    plan = MemoryConsolidationPlan([
        ConsolidationOperation("child", "merged", "- New fact.", ["- Prior fact."]),
    ])
    candidate = _candidate()
    replace = os.replace

    def publish(source, target):
        if Path(target) != path:
            return replace(source, target)
        if fault == "refused":
            raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), str(source))
        replace(source, target)
        if fault == "uncertain":
            raise OSError(errno.EIO, os.strerror(errno.EIO))
        external = workspace / "external-replacement"
        external.write_text("external replacement\n")
        replace(external, target)

    monkeypatch.setattr(os, "replace", publish)

    def commit():
        return commit_deep_consolidation(
            DeepConsolidation(logger=logging.getLogger("atomic-origin-test")),
            memory_path=path, workspace=workspace, plan=plan,
            base_hash=hash_memory_content(before), to_append=[candidate],
            planned_fingerprints={"child": consolidation_candidate_fingerprint(candidate)},
            max_prior_entry_loss_fraction=1, memory_file_max_chars=10000,
            timezone="UTC", now_ms=1782986400000, origins=ledger, origin_agent_ids=["main"],
        )

    if fault == "refused":
        result = commit()
        assert result.result is None and result.skipped_reason == "the MEMORY.md directory blocked atomic replacement"
        assert path.read_text() == before
        assert ledger.list("main", entry_keys=["child"]) == []
    else:
        with pytest.raises(MemoryAtomicPublicationError) as raised:
            commit()
        assert raised.value.publication == fault
        assert [row.session_id for row in ledger.list("main", entry_keys=["child"])] == ["session-a"]
        if fault == "uncertain":
            assert "- New fact." in path.read_text() and "- Prior fact." not in path.read_text()
        else:
            assert path.read_text() == "external replacement\n"
    assert [row.session_id for row in ledger.list("main", entry_keys=["parent"])] == ["session-a"]
