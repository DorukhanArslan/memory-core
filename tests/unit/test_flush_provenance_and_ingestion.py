"""Offline tests of the flush's trust records, the dreaming ingestion wiring and the recall events.

The real TS code is compared in tests/integration/test_memory_write_provenance_oracle.py (the observer),
test_daily_ingestion_oracle.py and test_session_ingestion_oracle.py (the ingestion), and
test_recall_events_oracle.py (the events). This file holds the composition the oracle cannot reach: the
host kit's flush wiring, ``run_dreaming_sweep(ingestion=)`` and the host kit's event callback.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
from memory_core.consolidation.daily_ingestion import ingest_daily_memory_signals
from memory_core.consolidation.dreaming import DreamingIngestion, run_dreaming_sweep
from memory_core.consolidation.origins import MemoryEntryOriginLedger
from memory_core.consolidation.session_ingestion import SessionCorpusEntry
from memory_core.consolidation.store import recall_store_path
from memory_core.consolidation._util import iso_ms
from memory_core.flags import FeatureFlags
from memory_core.host import HostKit, SessionState, TurnUsage

NOW_MS = 1_790_375_400_000  # 2026-09-25 22:30 UTC
TARGET = "memory/2026-09-25.md"
DUE = TurnUsage(176_000, 10)
TRANSCRIPT = ({"role": "user", "content": "We picked velvetkiwi."}, {"role": "assistant", "content": "Noted."})
SESSION = SessionState(session_key="agent:main:main", session_id="s1", entry={"sessionId": "s1", "compactionCount": 0})


def _kit(root: Path, **options: Any) -> HostKit:
    config = MemoryConfig(workspace_dir=root, store_path=root.parent / f"{root.name}.sqlite", flags=FeatureFlags(vector_search=False))
    memory = Memory.from_workspace(root, config=config, initialize=False)
    return HostKit(memory, now_ms=lambda: NOW_MS, **options)


def _records(store: MemoryArtifactProvenanceStore, root: Path) -> dict[str, Any]:
    return {path: record for path, record in store.list(root)}


def _flush(kit: HostKit, **kwargs: Any):
    record = kit.after_turn(SESSION, transcript=TRANSCRIPT, usage=DUE, **kwargs)
    assert record.flush is not None
    return record.flush


# --- the flush's trust records -----------------------------------------------------------------


def test_the_flush_records_the_daily_notes_trust(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    store = MemoryArtifactProvenanceStore(tmp_path / "prov.sqlite")
    flush = _flush(_kit(root, artifact_provenance=store))
    flush.dispatch("write", {"path": TARGET, "content": "- First fact about the codename velvetkiwi."})
    flush.dispatch("write", {"path": TARGET, "content": "- Second fact."})
    record = _records(store, root)[TARGET]
    # Native maintenance clears sender ownership even for a trusted source turn.
    assert record.origin_class == "untrusted"
    assert record.session_id == flush.execution_session_id != "s1"
    assert record.session_key == flush.execution_session_key != "agent:main:main"
    import hashlib

    assert record.file_hash == hashlib.sha256((root / TARGET).read_bytes()).hexdigest()


def test_an_untrusted_turn_quarantines_the_note_and_it_stays_untrusted(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    store = MemoryArtifactProvenanceStore(tmp_path / "prov.sqlite")
    kit = _kit(root, artifact_provenance=store)
    tainted = {"value": True}
    flush = _flush(kit, untrusted_turn=lambda: tainted["value"])
    flush.dispatch("write", {"path": TARGET, "content": "- A fact written during a tainted turn."})
    assert _records(store, root)[TARGET].origin_class == "untrusted"
    tainted["value"] = False
    flush.dispatch("write", {"path": TARGET, "content": "- A later trusted write."})
    assert _records(store, root)[TARGET].origin_class == "untrusted"  # sticky


def test_without_a_store_the_flush_writes_untracked(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    flush = _flush(_kit(root))
    result = flush.dispatch("write", {"path": TARGET, "content": "- Plain fact about the codename."})
    assert result["action"] == "appended" and (root / TARGET).read_text().endswith("codename.")


def test_a_failed_append_rolls_the_record_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    store = MemoryArtifactProvenanceStore(tmp_path / "prov.sqlite")
    flush = _flush(_kit(root, artifact_provenance=store))
    from memory_core import workspace as workspace_module

    def failing_write(_descriptor: int, _data: bytes):
        raise OSError("disk full")

    monkeypatch.setattr(workspace_module.os, "write", failing_write)
    result = flush.dispatch("write", {"path": TARGET, "content": "- A fact that cannot be written."})
    assert result["status"] == "error"
    assert TARGET not in _records(store, root)


def test_the_ingestion_reads_the_flushs_quarantine(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    store = MemoryArtifactProvenanceStore(tmp_path / "prov.sqlite")
    flush = _flush(_kit(root, artifact_provenance=store), untrusted_turn=True)
    flush.dispatch("write", {"path": TARGET, "content": "- An untrusted fact the dreaming must not trust."})
    config = MemoryConfig(workspace_dir=root, store_path=tmp_path / "i.sqlite", flags=FeatureFlags(vector_search=False))
    ingest_daily_memory_signals(
        config=config, now_ms=NOW_MS, lookback_days=14, limit=5, timezone="UTC", provenance=store
    )
    entries = json.loads(recall_store_path(root).read_text("utf-8"))["entries"]
    assert [e["provenance"]["originClass"] for e in entries.values()] == ["untrusted"]


# --- the sweep ---------------------------------------------------------------------------------


def _sweep_config(tmp_path: Path) -> tuple[MemoryConfig, Memory]:
    root = tmp_path / "ws"
    (root / "memory").mkdir(parents=True)
    (root / "memory" / "2026-09-25.md").write_text("# 2026-09-25\n\n- The deploy runs through the staging cluster first.\n", "utf-8")
    config = MemoryConfig(workspace_dir=root, store_path=tmp_path / "i.sqlite", flags=FeatureFlags(vector_search=False))
    return config, Memory.from_workspace(root, config=config, initialize=False)


@pytest.mark.parametrize("phase", ["light", "rem"])
def test_a_sweep_stages_daily_only_notes_after_ingestion(tmp_path: Path, phase: str) -> None:
    config, memory = _sweep_config(tmp_path)
    events: list[dict[str, Any]] = []
    result = run_dreaming_sweep(
        config=config,
        store=memory.store,
        phase=phase,
        now_ms=NOW_MS,
        timezone="UTC",
        ingestion=DreamingIngestion(),
        on_event=events.append,
    )
    assert result.daily_ingestion is not None and result.daily_ingestion.batches
    assert result.session_ingestion is None  # no corpus given
    entries = json.loads(recall_store_path(config.workspace_dir).read_text("utf-8"))["entries"]
    assert [(e["dailyCount"], e["recallCount"]) for e in entries.values()] == [(1, 0)]
    # dreaming-phases.ts stages daily-only signals without interactive-query diversity gates.
    assert len(result.candidates) == result.phase_signals_recorded == 1
    assert result.candidates[0].daily_count == 1
    assert result.candidates[0].recall_count == result.candidates[0].unique_queries == 0
    # A daily signal is recorded like a recall (only the grounded signal emits nothing): one event.
    assert [(e["type"], e["query"], e["resultCount"]) for e in events] == [
        ("memory.recall.recorded", "__dreaming_daily__:2026-09-25", 1)
    ]


def test_sweeps_without_ingestion_and_the_deep_phase_ingest_nothing(tmp_path: Path) -> None:
    config, memory = _sweep_config(tmp_path)
    for phase, ingestion in (("light", None), ("deep", DreamingIngestion())):
        result = run_dreaming_sweep(config=config, store=memory.store, phase=phase, now_ms=NOW_MS, timezone="UTC", ingestion=ingestion)
        assert result.daily_ingestion is None and result.session_ingestion is None
    assert not recall_store_path(config.workspace_dir).exists()


@pytest.mark.parametrize("phase", ["light", "rem"])
def test_historical_daily_only_ingestion_does_not_stage_stale_evidence(tmp_path: Path, phase):
    config, memory = _sweep_config(tmp_path)
    root = config.workspace_dir
    (root / TARGET).rename(root / "memory" / "2026-09-15.md")
    result = run_dreaming_sweep(
        config=config, store=memory.store, phase=phase, now_ms=NOW_MS,
        timezone="UTC", ingestion=DreamingIngestion(),
    )
    assert result.daily_ingestion is not None and result.daily_ingestion.batches
    assert result.candidates == () and result.phase_signals_recorded == 0


@pytest.mark.parametrize("phase", ["light", "rem"])
def test_untrusted_daily_only_note_is_not_staged(tmp_path: Path, phase):
    config, memory = _sweep_config(tmp_path)
    root = config.workspace_dir
    trust = MemoryArtifactProvenanceStore(tmp_path / "trust.sqlite")
    trust.record_write(
        workspace_dir=root, relative_path=TARGET, content_before="",
        content_after=(root / TARGET).read_text("utf-8"), origin_class="untrusted", observed_at=NOW_MS,
    )
    result = run_dreaming_sweep(
        config=config, store=memory.store, phase=phase, now_ms=NOW_MS,
        timezone="UTC", ingestion=DreamingIngestion(provenance=trust),
    )
    assert result.daily_ingestion is not None and result.daily_ingestion.batches
    assert result.candidates == () and result.phase_signals_recorded == 0


@pytest.mark.parametrize("phase", ["light", "rem"])
def test_phase_filters_before_limit_and_includes_promoted_daily_evidence(tmp_path, phase):
    config, memory = _sweep_config(tmp_path)
    ingest_daily_memory_signals(
        config=config, now_ms=NOW_MS, lookback_days=14, limit=5, timezone="UTC",
    )
    path = recall_store_path(config.workspace_dir)
    data = json.loads(path.read_text("utf-8"))
    fresh = next(iter(data["entries"].values()))
    fresh["promotedAt"] = iso_ms(NOW_MS)
    data["entries"]["older"] = {
        **fresh, "key": "older", "dailyCount": 10, "totalScore": 10,
        "recallDays": ["2026-09-15"],
    }
    # The existing tolerant rank reader ignores dict rows without a key.
    data["entries"]["malformed"] = {"lastRecalledAt": iso_ms(NOW_MS), "recallDays": ["2026-09-25"]}
    path.write_text(json.dumps(data), "utf-8")
    result = run_dreaming_sweep(
        config=config, store=memory.store, phase=phase, now_ms=NOW_MS, timezone="UTC", limit=1,
    )
    assert [candidate.key for candidate in result.candidates] == [fresh["key"]]
    assert result.candidates[0].promoted_at == fresh["promotedAt"]


def test_light_and_rem_use_their_own_default_lookback_windows(tmp_path):
    config, memory = _sweep_config(tmp_path)
    (config.workspace_dir / TARGET).rename(config.workspace_dir / "memory" / "2026-09-22.md")
    for phase, expected in [("light", 0), ("rem", 1)]:
        result = run_dreaming_sweep(
            config=config, store=memory.store, phase=phase, now_ms=NOW_MS,
            timezone="UTC", ingestion=DreamingIngestion(),
        )
        assert len(result.candidates) == expected


def test_a_rem_sweep_ingests_sessions_and_skips_forgotten_ones(tmp_path: Path) -> None:
    config, memory = _sweep_config(tmp_path)
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    entries = []
    for session in ("keep", "gone"):
        path = sessions / f"{session}.jsonl"
        message = {"role": "user", "content": f"A message of session {session} that is long enough.", "timestamp": NOW_MS - 1000}
        path.write_text(json.dumps({"type": "session"}) + "\n" + json.dumps({"type": "message", "message": message}) + "\n", "utf-8")
        entries.append(SessionCorpusEntry("main", session, str(path), session_key=f"agent:main:{session}", transcript_source="sqlite"))
    ledger = MemoryEntryOriginLedger(lambda agent: tmp_path / f"{agent}.sqlite")
    ledger.record_session_tombstones("main", ["gone"])
    result = run_dreaming_sweep(
        config=config,
        store=memory.store,
        phase="rem",
        now_ms=NOW_MS,
        timezone="UTC",
        origins=ledger,
        ingestion=DreamingIngestion(agent_ids=["main"], corpus_entries=lambda agent: entries),
    )
    assert result.session_ingestion is not None
    corpus = (config.workspace_dir / "memory/.dreams/session-corpus/2026-09-25.txt").read_text("utf-8")
    assert "session keep" in corpus and "session gone" not in corpus
    assert {o.session_id for o in ledger.list("main")} == {"keep"}


# --- the host kit's recall events --------------------------------------------------------------


def test_the_host_kit_passes_recall_events_to_the_host(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    (root / "memory").mkdir(parents=True)
    (root / "memory" / "2026-09-25.md").write_text("- The quokkabyte importer runs at night.\n", "utf-8")
    (root / "MEMORY.md").write_text("- The quokkabyte importer is documented here.\n", "utf-8")
    events: list[dict[str, Any]] = []
    kit = _kit(root, dreaming_enabled=True, on_event=events.append)
    # Exercise both recall-event paths independently of dated-hit decay and
    # the native 0.35 default relevance threshold.
    result = kit.dispatch(
        "memory_search", {"query": "quokkabyte importer", "minScore": 0}, session=SESSION,
    )
    assert result["results"]
    types = [event["type"] for event in events]
    assert types[0] == "memory.recall.recorded"
    assert set(types) <= {"memory.recall.recorded", "memory.recall.skipped"}
    assert events[0]["resultCount"] >= 1 and events[0]["results"][0]["path"] == "memory/2026-09-25.md"
    recalls = json.loads(recall_store_path(root).read_text("utf-8"))["entries"]
    assert [entry["snippet"] for entry in recalls.values()] == [
        "- The quokkabyte importer runs at night.",
    ]
