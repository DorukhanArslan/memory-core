"""Subject promotion (decision Q16): scored consolidation on a live subject workspace."""

from __future__ import annotations

from pathlib import Path

import pytest

from memory_core import (
    FeatureFlags,
    MemoryConfig,
    SubjectConsolidation,
    SubjectPromotionDisabledError,
)
from memory_core.live import SubjectMemory

DAY_MS = 86_400_000
NOW_MS = 1779811200000  # 2026-05-26T16:00:00Z
DAILY = "memory/2026-05-26.md"
FACT = "- Alice prefers morning appointments before 10am."
QUERIES = (
    "morning appointments",
    "prefers morning",
    "appointments before",
    "alice morning",
    "morning 10am",
)


def _open(root: Path, subject_id: str, **kwargs) -> SubjectMemory:
    subject = SubjectMemory.open(workspace_dir=root, subject_id=subject_id, **kwargs)
    daily = subject.memory.config.workspace_dir / DAILY
    daily.write_text(f"# 2026-05-26\n\n{FACT}\n", encoding="utf-8")
    subject.memory.store.reindex(subject.memory.workspace)
    return subject


def _enabled(root: Path, subject_id: str) -> SubjectMemory:
    return _open(
        root, subject_id, flags=FeatureFlags(vector_search=False, subject_promotion=True)
    )


def _record_five_days(consolidation: SubjectConsolidation) -> None:
    for day, query in enumerate(QUERIES):
        results = consolidation.subject.memory.search(query)["results"]
        assert results, query
        consolidation.record_recalls(query, results, now_ms=NOW_MS + day * DAY_MS)


def test_subject_promotion_is_off_by_default_and_fails_closed(tmp_path: Path):
    subject = _open(tmp_path, "alice")
    consolidation = SubjectConsolidation(subject)
    workspace = subject.memory.config.workspace_dir
    memory_before = (workspace / "MEMORY.md").read_text(encoding="utf-8")
    results = subject.memory.search("morning appointments")["results"]

    assert consolidation.enabled is False
    for call in (
        lambda: consolidation.record_recalls("morning", results, now_ms=NOW_MS),
        lambda: consolidation.promote(now_ms=NOW_MS),
        lambda: consolidation.dream("light", now_ms=NOW_MS),
        lambda: consolidation.audit(now_ms=NOW_MS),
        lambda: consolidation.repair(now_ms=NOW_MS),
    ):
        with pytest.raises(SubjectPromotionDisabledError):
            call()
    assert not (workspace / "memory" / ".dreams").exists()
    assert (workspace / "MEMORY.md").read_text(encoding="utf-8") == memory_before


def test_subject_promotion_writes_only_the_subject_workspace(tmp_path: Path):
    alice = _enabled(tmp_path, "alice")
    bob = _open(tmp_path, "bob")
    bob_memory = (bob.memory.config.workspace_dir / "MEMORY.md").read_text(encoding="utf-8")
    consolidation = SubjectConsolidation(alice)
    _record_five_days(consolidation)

    run = consolidation.promote(now_ms=NOW_MS + 4 * DAY_MS, min_score=0)

    alice_dir = tmp_path / "subjects" / "alice"
    memory = (alice_dir / "MEMORY.md").read_text(encoding="utf-8")
    key = f"memory:{DAILY}:3:3"
    assert run.appended == 1
    assert [candidate.key for candidate in run.applied_candidates] == [key]
    assert f"<!-- memory-core-memory-promotion:{key} -->" in memory
    assert "Alice prefers morning appointments before 10am." in memory
    # Recorded hits are the raw ones: memory_search's "Source:" citation is not an entry.
    assert [evaluation.key for evaluation in run.evaluated_candidates] == [key]
    assert (alice_dir / "memory" / ".dreams" / "short-term-recall.json").exists()
    assert not (tmp_path / "MEMORY.md").exists()
    assert not (tmp_path / "memory").exists()
    assert (bob.memory.config.workspace_dir / "MEMORY.md").read_text(encoding="utf-8") == bob_memory
    assert not (bob.memory.config.workspace_dir / "memory" / ".dreams").exists()
    # The promotion reindexed the subject's own store.
    hits = alice.memory.search("morning appointments")["results"]
    assert "MEMORY.md" in {hit["path"] for hit in hits}


def test_subject_dreaming_sweeps_run_in_the_subject_workspace(tmp_path: Path):
    alice = _enabled(tmp_path, "alice")
    consolidation = SubjectConsolidation(alice)
    _record_five_days(consolidation)
    alice_dir = tmp_path / "subjects" / "alice"
    later = NOW_MS + 4 * DAY_MS

    light = consolidation.dream("light", now_ms=later)
    rem = consolidation.dream("rem", now_ms=later)
    audit = consolidation.audit(now_ms=later)

    assert light.phase_signals_recorded == 1
    assert rem.files_changed == ("memory/.dreams/phase-signals.json", "DREAMS.md")
    assert "Alice prefers morning appointments" in (alice_dir / "DREAMS.md").read_text(
        encoding="utf-8"
    )
    assert not (tmp_path / "DREAMS.md").exists()
    assert (audit.entry_count, audit.promoted_entry_count) == (1, 0)
    assert consolidation.repair(now_ms=later).changed is False


def test_flags_and_a_shared_config_cannot_be_combined(tmp_path: Path):
    with pytest.raises(ValueError, match="flags"):
        SubjectMemory.open(
            workspace_dir=tmp_path,
            subject_id="alice",
            config=MemoryConfig(workspace_dir=tmp_path),
            flags=FeatureFlags(vector_search=False, subject_promotion=True),
        )
