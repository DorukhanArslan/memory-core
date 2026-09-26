from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path

import memory_core.consolidation.concepts as concepts_module
import memory_core.consolidation.store as store_module
from memory_core.config import MemoryConfig
from memory_core.consolidation import (
    SHORT_TERM_LOCK_RELATIVE_PATH,
    SHORT_TERM_LOCK_STALE_MS,
    SHORT_TERM_PHASE_SIGNAL_RELATIVE_PATH,
    acquire_short_term_promotion_lock,
    audit_short_term_promotion_artifacts,
    rank_short_term_promotion_candidates,
    record_short_term_phase_signals,
    record_short_term_recalls,
    repair_short_term_promotion_artifacts,
    run_short_term_promotion,
)
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
from memory_core.index.sqlite_store import SQLiteMemoryStore


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def fake_store(config: MemoryConfig):
    return SQLiteMemoryStore(config, FakeEmbeddingProvider(dimensions=8))


def test_lock_constants_match_openclaw_paths():
    assert SHORT_TERM_PHASE_SIGNAL_RELATIVE_PATH.as_posix() == "memory/.dreams/phase-signals.json"
    assert SHORT_TERM_LOCK_RELATIVE_PATH.as_posix() == "memory/.dreams/short-term-promotion.lock"
    assert SHORT_TERM_LOCK_STALE_MS == 60_000
    assert not hasattr(store_module, "SHORT_TERM_LOCK_GUARD_RELATIVE_PATH")
    assert (
        store_module._SHORT_TERM_LOCK_GUARD_RELATIVE_PATH.as_posix()
        == "memory/.dreams/short-term-promotion.lock.guard"
    )


def test_concept_tags_match_openclaw_vocabulary_for_european_languages():
    assert concepts_module.derive_concept_tags(
        "memory/2026-04-04.md",
        "Configuración de gateway, configuration du routeur, Sicherung und Überwachung Glacier.",
    ) == [
        "gateway",
        "glacier",
        "routeur",
        "sicherung",
        "überwachung",
        "configuración",
        "configuration",
    ]


def test_concept_tags_match_openclaw_vocabulary_for_cjk_protected_terms():
    assert concepts_module.derive_concept_tags(
        "memory/2026-04-04.md",
        "障害対応ルーター設定とバックアップ確認。路由器备份与网关同步。라우터 백업 페일오버 점검.",
    ) == [
        "バックアップ",
        "ルーター",
        "障害対応",
        "路由器",
        "备份",
        "网关",
        "라우터",
        "백업",
    ]


def test_concept_tags_match_openclaw_vocabulary_for_chat_scaffolding_stop_words():
    tags = concepts_module.derive_concept_tags(
        "memory/.dreams/session-corpus/2026-04-16.txt",
        "Assistant: the system should remind you about the Ollama provider setup in your workspace.",
    )

    assert "ollama" in tags
    assert "provider" in tags
    assert "assistant" not in tags
    assert "system" not in tags
    assert "the" not in tags
    assert "you" not in tags
    assert "your" not in tags


def test_concept_tags_match_openclaw_vocabulary_for_stable_snippets_and_paths():
    assert concepts_module.derive_concept_tags(
        "memory/2026-04-03.md",
        "Move backups to S3 Glacier and sync QMD router notes.",
    ) == ["backup", "backups", "glacier", "qmd", "router", "s3", "sync"]


def test_concept_tags_match_openclaw_vocabulary_for_multilingual_short_term_fixture():
    assert concepts_module.derive_concept_tags(
        "memory/2026-04-03.md",
        "Configuración du routeur et sauvegarde Glacier.",
    ) == ["glacier", "sauvegarde", "routeur", "configuración"]


def test_active_short_term_lock_blocks_second_owner(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path)
    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))

    with acquire_short_term_promotion_lock(config, now) as first:
        assert first.acquired is True
        second = acquire_short_term_promotion_lock(config, now)
        with second as blocked:
            assert blocked.acquired is False
            assert blocked.reason == "locked"


def test_stale_short_term_lock_is_repaired(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path)
    lock_path = tmp_path / SHORT_TERM_LOCK_RELATIVE_PATH
    lock_path.parent.mkdir(parents=True)
    stale_time = datetime(2026, 5, 8, 12, 0, tzinfo=UTC) - timedelta(minutes=5)
    lock_path.write_text('{"pid": 999999, "createdAt": "old"}\n', encoding="utf-8")
    old_seconds = stale_time.timestamp()
    os.utime(lock_path, times=(old_seconds, old_seconds))

    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    with acquire_short_term_promotion_lock(config=config, now_ms=now) as lock:
        assert lock.acquired is True
        assert lock.stole_stale is True


def test_stale_owner_release_does_not_delete_new_owner_lock(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path)
    first_now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    second_now = first_now + SHORT_TERM_LOCK_STALE_MS + 1
    lock_path = tmp_path / SHORT_TERM_LOCK_RELATIVE_PATH

    first_manager = acquire_short_term_promotion_lock(config, first_now)
    first = first_manager.__enter__()
    first_released = False
    try:
        assert first.acquired is True
        second_manager = acquire_short_term_promotion_lock(config, second_now)
        second = second_manager.__enter__()
        try:
            assert second.acquired is True
            assert second.stole_stale is True

            first_manager.__exit__(None, None, None)
            first_released = True

            assert lock_path.exists() is True
        finally:
            second_manager.__exit__(None, None, None)
    finally:
        if not first_released:
            first_manager.__exit__(None, None, None)


def test_changed_stale_lock_is_not_unlinked_during_steal(tmp_path: Path, monkeypatch):
    config = MemoryConfig(workspace_dir=tmp_path)
    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    lock_path = tmp_path / SHORT_TERM_LOCK_RELATIVE_PATH
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(
        '{"pid": 999999, "createdAt": "2026-05-08T11:58:00Z", "ownerToken": "stale"}\n',
        encoding="utf-8",
    )

    def replace_with_fresh_lock(path: Path, checked_now: int) -> bool:
        assert path == lock_path
        assert checked_now == now
        lock_path.write_text(
            '{"pid": 123, "createdAt": "2026-05-08T12:00:00Z", "ownerToken": "fresh"}\n',
            encoding="utf-8",
        )
        return True

    monkeypatch.setattr(store_module, "_lock_is_stale", replace_with_fresh_lock)

    with acquire_short_term_promotion_lock(config, now) as lock:
        assert lock.acquired is False
        assert lock.reason == "locked"

    assert json.loads(lock_path.read_text(encoding="utf-8"))["ownerToken"] == "fresh"


def test_promotion_run_returns_locked_result_when_lock_is_active(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    (tmp_path / "MEMORY.md").write_text("# MEMORY.md\n", encoding="utf-8")
    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))

    with acquire_short_term_promotion_lock(config=config, now_ms=now):
        run = run_short_term_promotion(
            config=config,
            store=fake_store(config),
            now_ms=now,
            timezone="Europe/Istanbul",
        )

    assert run.parsed.should_write is False
    assert run.parsed.reason == "promotion locked"


def test_audit_reports_unreadable_recall_store(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path)
    store_path = tmp_path / "memory" / ".dreams" / "short-term-recall.json"
    store_path.parent.mkdir(parents=True)
    store_path.write_bytes(b"\xff\xfe{not-json")

    audit = audit_short_term_promotion_artifacts(config, ms(datetime(2026, 5, 8, tzinfo=UTC)))

    assert audit.exists is True
    assert audit.invalid_entry_count == 0
    assert audit.issues[0].code == "recall-store-unreadable"


def test_audit_counts_readable_recall_store_entries(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path)
    store_path = tmp_path / "memory" / ".dreams" / "short-term-recall.json"
    store_path.parent.mkdir(parents=True)
    store_path.write_text(
        json.dumps(
            {
                "entries": {
                    "promoted": {
                        "key": "promoted",
                        "path": "memory/topic.md",
                        "snippet": "Promoted claim",
                        "promotedAt": "2026-05-08T12:00:00Z",
                        "recallDays": ["2026-05-07"],
                        "conceptTags": ["topic"],
                    },
                    "spaced": {
                        "key": "spaced",
                        "path": "memory/topic.md",
                        "snippet": "Spaced claim",
                        "recallDays": ["2026-05-07", "2026-05-08"],
                        "conceptTags": [],
                    },
                    "invalid": {
                        "key": "invalid",
                        "path": "memory/topic.md",
                        "recallDays": [],
                    },
                    "not-dict": "invalid",
                }
            }
        ),
        encoding="utf-8",
    )

    audit = audit_short_term_promotion_artifacts(config, ms(datetime(2026, 5, 8, tzinfo=UTC)))

    assert audit.exists is True
    assert audit.entry_count == 2
    assert audit.promoted_entry_count == 1
    assert audit.spaced_entry_count == 1
    assert audit.concept_tagged_entry_count == 1
    assert audit.invalid_entry_count == 2
    assert audit.issues == ()


def test_repair_removes_invalid_entries_and_stale_lock(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path)
    dreams = tmp_path / "memory" / ".dreams"
    dreams.mkdir(parents=True)
    (dreams / "short-term-recall.json").write_text(
        json.dumps(
            {
                "version": 1,
                "updatedAt": "2026-05-08T00:00:00Z",
                "entries": {
                    "bad": None,
                    "missing-fields": {
                        "key": "missing-fields",
                        "path": "memory/topic.md",
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    lock = dreams / "short-term-promotion.lock"
    lock.write_text('{"pid": 999999}\n', encoding="utf-8")
    old = datetime(2026, 5, 8, 11, 55, tzinfo=UTC).timestamp()
    os.utime(lock, times=(old, old))

    result = repair_short_term_promotion_artifacts(
        config=config,
        now_ms=ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC)),
    )

    assert result.removed_invalid_entries == 2
    assert result.rewrote_store is True
    assert result.removed_stale_lock is True
    payload = json.loads((dreams / "short-term-recall.json").read_text(encoding="utf-8"))
    assert payload["updatedAt"] == "2026-05-08T12:00:00.000Z"
    assert isinstance(payload["entries"], dict)
    assert "bad" not in payload["entries"]
    assert "missing-fields" not in payload["entries"]
    assert not lock.exists()


def test_phase_signals_are_recorded_and_decay_old_keys(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path)
    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    phase_path = tmp_path / SHORT_TERM_PHASE_SIGNAL_RELATIVE_PATH
    phase_path.parent.mkdir(parents=True)
    phase_path.write_text(
        json.dumps(
            {
                "version": 1,
                "updatedAt": "2026-03-01T12:00:00Z",
                "entries": {
                    "memory:memory/2026-03-01.md:2:2:old": {
                        "key": "memory:memory/2026-03-01.md:2:2:old",
                        "lightHits": 1,
                        "remHits": 1,
                        "lastLightAt": "2026-03-01T12:00:00Z",
                        "lastRemAt": "2026-03-01T12:00:00Z",
                        "updatedAt": "2026-03-01T12:00:00Z",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    changed = record_short_term_phase_signals(
        config=config,
        keys=["memory:memory/2026-05-08.md:2:2:abc"],
        phase="light",
        now_ms=now,
    )

    raw = phase_path.read_text(encoding="utf-8")
    payload = json.loads(raw)
    entry = payload["entries"]["memory:memory/2026-05-08.md:2:2:abc"]

    assert changed == 1
    assert "memory:memory/2026-03-01.md:2:2:old" not in payload["entries"]
    assert '"lightHits": 1' in raw
    assert '"remHits": 0' in raw
    assert entry["lastLightAt"] == "2026-05-08T12:00:00.000Z"
    assert entry["lastRemAt"] is None


def test_new_rem_phase_signal_entry_includes_last_light_at(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path)
    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    changed = record_short_term_phase_signals(
        config=config,
        keys=["memory:memory/2026-05-08.md:2:2:def"],
        phase="rem",
        now_ms=now,
    )

    phase_path = tmp_path / SHORT_TERM_PHASE_SIGNAL_RELATIVE_PATH
    payload = json.loads(phase_path.read_text(encoding="utf-8"))
    entry = payload["entries"]["memory:memory/2026-05-08.md:2:2:def"]

    assert changed == 1
    assert entry["lightHits"] == 0
    assert entry["remHits"] == 1
    assert entry["lastLightAt"] is None
    assert entry["lastRemAt"] == "2026-05-08T12:00:00.000Z"


def test_candidate_output_includes_score_components_and_phase_boost(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path)
    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    daily = tmp_path / "memory" / "2026-05-08.md"
    daily.parent.mkdir(parents=True)
    daily.write_text("# 2026-05-08\n\n- User prefers lowercase answers.\n", encoding="utf-8")
    result = {
        "path": "memory/2026-05-08.md",
        "startLine": 3,
        "endLine": 3,
        "snippet": "- User prefers lowercase answers.",
        "score": 0.9,
    }
    for query in ("lowercase", "answer case", "writing style"):
        record_short_term_recalls(config=config, query=query, results=[result], now_ms=now)

    candidates = rank_short_term_promotion_candidates(
        config=config,
        now_ms=now,
        limit=5,
        min_score=0,
        min_recall_count=1,
        min_unique_queries=1,
    )
    for phase in ("light", "light", "light", "rem", "rem", "rem"):
        record_short_term_phase_signals(
            config=config,
            keys=[candidates[0].key],
            phase=phase,
            now_ms=now,
        )
    boosted = rank_short_term_promotion_candidates(
        config=config,
        now_ms=now,
        limit=5,
        min_score=0,
        min_recall_count=1,
        min_unique_queries=1,
    )

    assert boosted[0].components["frequency"] > 0
    assert boosted[0].components["phaseBoost"] > 0
    assert boosted[0].components["phaseBoost"] <= 0.09
    assert boosted[0].score >= candidates[0].score


def test_ranking_keeps_existing_promotion_marker_candidate_like_openclaw(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path)
    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    daily = tmp_path / "memory" / "2026-05-08.md"
    daily.parent.mkdir(parents=True)
    daily.write_text("# 2026-05-08\n\n- Move backups to S3 Glacier.\n", encoding="utf-8")
    result = {
        "path": "memory/2026-05-08.md",
        "startLine": 3,
        "endLine": 3,
        "snippet": "- Move backups to S3 Glacier.",
        "score": 1,
    }
    for query in ("backup policy", "glacier backup", "s3 retention", "cold storage", "backup notes"):
        record_short_term_recalls(config=config, query=query, results=[result], now_ms=now)
    key = "memory:memory/2026-05-08.md:3:3"
    (tmp_path / "MEMORY.md").write_text(
        "# Long-Term Memory\n\n"
        "## Promoted From Short-Term Memory (2026-05-08)\n\n"
        f"<!-- openclaw-memory-promotion:{key} -->\n"
        "- Move backups to S3 Glacier. [score=0.900 recalls=5 avg=1.000 "
        "source=memory/2026-05-08.md:3-3]\n",
        encoding="utf-8",
    )

    candidates = rank_short_term_promotion_candidates(
        config=config,
        now_ms=now,
        limit=5,
        min_score=0,
        min_recall_count=1,
        min_unique_queries=1,
    )

    assert [candidate.key for candidate in candidates] == [key]


def test_ranking_skips_promoted_at_entry_like_openclaw(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path)
    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    daily = tmp_path / "memory" / "2026-05-08.md"
    daily.parent.mkdir(parents=True)
    daily.write_text("# 2026-05-08\n\n- Move backups to S3 Glacier.\n", encoding="utf-8")
    result = {
        "path": "memory/2026-05-08.md",
        "startLine": 3,
        "endLine": 3,
        "snippet": "- Move backups to S3 Glacier.",
        "score": 1,
    }
    for query in ("backup policy", "glacier backup", "s3 retention", "cold storage", "backup notes"):
        record_short_term_recalls(config=config, query=query, results=[result], now_ms=now)
    recall_path = tmp_path / "memory" / ".dreams" / "short-term-recall.json"
    store_payload = json.loads(recall_path.read_text(encoding="utf-8"))
    key = "memory:memory/2026-05-08.md:3:3"
    store_payload["entries"][key]["promotedAt"] = "2026-05-08T12:00:00.000Z"
    recall_path.write_text(json.dumps(store_payload), encoding="utf-8")

    candidates = rank_short_term_promotion_candidates(
        config=config,
        now_ms=now,
        limit=5,
        min_score=0,
        min_recall_count=1,
        min_unique_queries=1,
    )

    assert candidates == []


def test_record_short_term_recalls_ignores_contaminated_dreaming_snippet_like_openclaw(
    tmp_path: Path,
):
    config = MemoryConfig(workspace_dir=tmp_path)
    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))

    changed = record_short_term_recalls(
        config=config,
        query="action preference",
        results=[
            {
                "path": "memory/2026-04-03.md",
                "source": "memory",
                "startLine": 1,
                "endLine": 1,
                "score": 0.92,
                "snippet": (
                    "Candidate: Default to action. confidence: 0.76 evidence: "
                    "memory/.dreams/session-corpus/2026-04-08.txt:1-1 recalls: 3 "
                    "status: staged"
                ),
            }
        ],
        now_ms=now,
    )

    assert changed == 0
    store_payload = json.loads(
        (tmp_path / "memory" / ".dreams" / "short-term-recall.json").read_text(
            encoding="utf-8"
        )
    )
    assert store_payload["entries"] == {}


def test_ranking_skips_contaminated_dreaming_snippet_like_openclaw(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path)
    store_path = tmp_path / "memory" / ".dreams" / "short-term-recall.json"
    store_path.parent.mkdir(parents=True)
    store_path.write_text(
        json.dumps(
            {
                "version": 1,
                "updatedAt": "2026-04-04T00:00:00.000Z",
                "entries": {
                    "contaminated": {
                        "key": "contaminated",
                        "path": "memory/2026-04-03.md",
                        "startLine": 1,
                        "endLine": 1,
                        "source": "memory",
                        "snippet": (
                            "Reflections: Theme: assistant. confidence: 1.00 evidence: "
                            "memory/.dreams/session-corpus/2026-04-08.txt:2-2 recalls: "
                            "4 status: staged"
                        ),
                        "recallCount": 4,
                        "dailyCount": 0,
                        "groundedCount": 0,
                        "totalScore": 3.6,
                        "maxScore": 0.95,
                        "firstRecalledAt": "2026-04-03T00:00:00.000Z",
                        "lastRecalledAt": "2026-04-04T00:00:00.000Z",
                        "queryHashes": ["a", "b"],
                        "recallDays": ["2026-04-03", "2026-04-04"],
                        "conceptTags": ["assistant"],
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    candidates = rank_short_term_promotion_candidates(
        config=config,
        now_ms=ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC)),
        limit=5,
        min_score=0,
        min_recall_count=0,
        min_unique_queries=0,
    )

    assert candidates == []


def test_candidate_like_daily_memory_evidence_is_not_contaminated_like_openclaw(
    tmp_path: Path,
):
    config = MemoryConfig(workspace_dir=tmp_path)
    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    snippet = "Candidate: move backups weekly. confidence: 0.76 evidence: memory/2026-04-08.md:1-1"
    result = {
        "path": "memory/2026-04-08.md",
        "source": "memory",
        "startLine": 1,
        "endLine": 1,
        "snippet": snippet,
        "score": 1,
    }

    for query in ("backup candidate", "weekly backups", "backup evidence"):
        record_short_term_recalls(config=config, query=query, results=[result], now_ms=now)
    candidates = rank_short_term_promotion_candidates(
        config=config,
        now_ms=now,
        limit=5,
        min_score=0,
        min_recall_count=1,
        min_unique_queries=1,
    )

    assert len(candidates) == 1
    assert candidates[0].snippet == snippet
    assert candidates[0].key == "memory:memory/2026-04-08.md:1:1"


def test_promotion_run_reconciles_existing_marker_without_duplicate_append(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    daily = tmp_path / "memory" / "2026-05-08.md"
    daily.parent.mkdir(parents=True)
    daily.write_text("# 2026-05-08\n\n- Move backups to S3 Glacier.\n", encoding="utf-8")
    result = {
        "path": "memory/2026-05-08.md",
        "startLine": 3,
        "endLine": 3,
        "snippet": "- Move backups to S3 Glacier.",
        "score": 1,
    }
    for query in ("backup policy", "glacier backup", "s3 retention", "cold storage", "backup notes"):
        record_short_term_recalls(config=config, query=query, results=[result], now_ms=now)
    key = "memory:memory/2026-05-08.md:3:3"
    existing_memory = (
        "# Long-Term Memory\n\n"
        "## Promoted From Short-Term Memory (2026-05-08)\n\n"
        f"<!-- openclaw-memory-promotion:{key} -->\n"
        "- Move backups to S3 Glacier. [score=0.900 recalls=5 avg=1.000 "
        "source=memory/2026-05-08.md:3-3]\n"
    )
    (tmp_path / "MEMORY.md").write_text(existing_memory, encoding="utf-8")

    run = run_short_term_promotion(
        config=config,
        store=fake_store(config),
        now_ms=now,
        timezone="Europe/Istanbul",
        limit=5,
        min_score=0,
        min_recall_count=1,
        min_unique_queries=1,
    )

    assert run.parsed.should_write is False
    assert (tmp_path / "MEMORY.md").read_text(encoding="utf-8") == existing_memory
    recall_store = json.loads(
        (tmp_path / "memory" / ".dreams" / "short-term-recall.json").read_text(encoding="utf-8")
    )
    assert recall_store["entries"][key]["promotedAt"] == "2026-05-08T12:00:00.000Z"


def test_promotion_run_parses_spaced_case_insensitive_marker_like_openclaw(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    daily = tmp_path / "memory" / "2026-05-08.md"
    daily.parent.mkdir(parents=True)
    daily.write_text("# 2026-05-08\n\n- Move backups to S3 Glacier.\n", encoding="utf-8")
    result = {
        "path": "memory/2026-05-08.md",
        "source": "memory",
        "startLine": 3,
        "endLine": 3,
        "snippet": "- Move backups to S3 Glacier.",
        "score": 1,
    }
    record_short_term_recalls(config=config, query="glacier", results=[result], now_ms=now)
    key = "memory:memory/2026-05-08.md:3:3"
    existing_memory = (
        "# Long-Term Memory\n\n"
        "## Promoted From Short-Term Memory (2026-05-08)\n\n"
        f"<!--   OPENCLAW-MEMORY-PROMOTION:{key}-->\n"
        "- Move backups to S3 Glacier. [score=0.900 recalls=1 avg=1.000 "
        "source=memory/2026-05-08.md:3-3]\n"
    )
    (tmp_path / "MEMORY.md").write_text(existing_memory, encoding="utf-8")

    run = run_short_term_promotion(
        config=config,
        store=fake_store(config),
        now_ms=now,
        timezone="Europe/Istanbul",
        limit=5,
        min_score=0,
        min_recall_count=0,
        min_unique_queries=0,
    )

    assert run.parsed.should_write is False
    assert (tmp_path / "MEMORY.md").read_text(encoding="utf-8") == existing_memory
    recall_store = json.loads(
        (tmp_path / "memory" / ".dreams" / "short-term-recall.json").read_text(encoding="utf-8")
    )
    assert recall_store["entries"][key]["promotedAt"] == "2026-05-08T12:00:00.000Z"


def test_promotion_run_compacts_oldest_promotion_section_when_memory_budget_exceeded(
    tmp_path: Path,
):
    config = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    now = ms(datetime(2026, 4, 29, 10, 0, tzinfo=UTC))
    daily = tmp_path / "memory" / "2026-04-29.md"
    daily.parent.mkdir(parents=True)
    daily.write_text(
        "# 2026-04-29\n\nRotate the staging Postgres credentials before next deploy.\n",
        encoding="utf-8",
    )
    filler = "x" * 600
    seeded_memory = "\n".join(
        [
            "# Long-Term Memory",
            "",
            "User-authored note that must stay.",
            "",
            "## Promoted From Short-Term Memory (2026-04-10)",
            "<!-- openclaw-memory-promotion:legacy-old -->",
            f"- {filler}",
            "",
            "## Promoted From Short-Term Memory (2026-04-20)",
            "<!-- openclaw-memory-promotion:legacy-newer -->",
            f"- {filler}",
            "",
        ]
    )
    (tmp_path / "MEMORY.md").write_text(seeded_memory, encoding="utf-8")
    record_short_term_recalls(
        config=config,
        query="rotate creds",
        results=[
            {
                "path": "memory/2026-04-29.md",
                "source": "memory",
                "startLine": 3,
                "endLine": 3,
                "snippet": "Rotate the staging Postgres credentials before next deploy.",
                "score": 0.96,
            }
        ],
        now_ms=now,
    )

    run = run_short_term_promotion(
        config=config,
        store=fake_store(config),
        now_ms=now,
        timezone="Europe/Istanbul",
        limit=5,
        min_score=0,
        min_recall_count=0,
        min_unique_queries=0,
        memory_file_max_chars=1_400,
    )
    memory_text = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")

    assert run.parsed.should_write is True
    assert "User-authored note that must stay." in memory_text
    assert "(2026-04-10)" not in memory_text
    assert "legacy-old" not in memory_text
    assert "(2026-04-20)" in memory_text
    assert "legacy-newer" in memory_text
    assert "Rotate the staging Postgres credentials" in memory_text


def test_promotion_run_leaves_memory_unchanged_before_append_when_budget_fits(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    now = ms(datetime(2026, 4, 29, 10, 0, tzinfo=UTC))
    daily = tmp_path / "memory" / "2026-04-29.md"
    daily.parent.mkdir(parents=True)
    daily.write_text("# 2026-04-29\n\nA short snippet that fits comfortably.\n", encoding="utf-8")
    seeded_memory = "# Long-Term Memory\n\nSome small existing content.\n"
    (tmp_path / "MEMORY.md").write_text(seeded_memory, encoding="utf-8")
    record_short_term_recalls(
        config=config,
        query="tiny note",
        results=[
            {
                "path": "memory/2026-04-29.md",
                "source": "memory",
                "startLine": 3,
                "endLine": 3,
                "snippet": "A short snippet that fits comfortably.",
                "score": 0.92,
            }
        ],
        now_ms=now,
    )

    run = run_short_term_promotion(
        config=config,
        store=fake_store(config),
        now_ms=now,
        timezone="Europe/Istanbul",
        limit=5,
        min_score=0,
        min_recall_count=0,
        min_unique_queries=0,
        memory_file_max_chars=10_000,
    )
    memory_text = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")

    assert run.parsed.should_write is True
    assert memory_text.startswith(seeded_memory)
    assert "Some small existing content." in memory_text
    assert "A short snippet that fits comfortably." in memory_text


def test_promotion_run_drops_all_old_promotion_sections_when_budget_cannot_fit_otherwise(
    tmp_path: Path,
):
    config = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    now = ms(datetime(2026, 4, 29, 10, 0, tzinfo=UTC))
    daily = tmp_path / "memory" / "2026-04-29.md"
    daily.parent.mkdir(parents=True)
    daily.write_text("# 2026-04-29\n\nFresh material still gets written.\n", encoding="utf-8")
    filler = "x" * 600
    seeded_memory = "\n".join(
        [
            "## Promoted From Short-Term Memory (2026-04-10)",
            "<!-- openclaw-memory-promotion:legacy-old -->",
            f"- {filler}",
            "## Promoted From Short-Term Memory (2026-04-15)",
            "<!-- openclaw-memory-promotion:legacy-middle -->",
            f"- {filler}",
            "## Promoted From Short-Term Memory (2026-04-20)",
            "<!-- openclaw-memory-promotion:legacy-newer -->",
            f"- {filler}",
        ]
    )
    (tmp_path / "MEMORY.md").write_text(seeded_memory, encoding="utf-8")
    record_short_term_recalls(
        config=config,
        query="fresh material",
        results=[
            {
                "path": "memory/2026-04-29.md",
                "source": "memory",
                "startLine": 3,
                "endLine": 3,
                "snippet": "Fresh material still gets written.",
                "score": 0.92,
            }
        ],
        now_ms=now,
    )

    run = run_short_term_promotion(
        config=config,
        store=fake_store(config),
        now_ms=now,
        timezone="Europe/Istanbul",
        limit=5,
        min_score=0,
        min_recall_count=0,
        min_unique_queries=0,
        memory_file_max_chars=700,
    )
    memory_text = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")

    assert run.parsed.should_write is True
    assert "(2026-04-10)" not in memory_text
    assert "(2026-04-15)" not in memory_text
    assert "(2026-04-20)" not in memory_text
    assert "legacy-old" not in memory_text
    assert "legacy-middle" not in memory_text
    assert "legacy-newer" not in memory_text
    assert "Fresh material still gets written." in memory_text


def test_first_promotion_write_bootstraps_long_term_memory_header_like_openclaw(
    tmp_path: Path,
):
    config = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    daily = tmp_path / "memory" / "2026-05-08.md"
    daily.parent.mkdir(parents=True)
    daily.write_text("# 2026-05-08\n\n- Move backups to S3 Glacier.\n", encoding="utf-8")
    result = {
        "path": "memory/2026-05-08.md",
        "source": "memory",
        "startLine": 3,
        "endLine": 3,
        "snippet": "- Move backups to S3 Glacier.",
        "score": 1,
    }
    record_short_term_recalls(config=config, query="glacier", results=[result], now_ms=now)

    run = run_short_term_promotion(
        config=config,
        store=fake_store(config),
        now_ms=now,
        timezone="Europe/Istanbul",
        limit=5,
        min_score=0,
        min_recall_count=0,
        min_unique_queries=0,
    )

    assert run.parsed.should_write is True
    assert (tmp_path / "MEMORY.md").read_text(encoding="utf-8").startswith(
        "# Long-Term Memory\n\n\n## Promoted From Short-Term Memory (2026-05-08)"
    )


def test_second_promotion_apply_reconciles_existing_marker_without_duplicate_like_openclaw(
    tmp_path: Path,
):
    config = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    daily = tmp_path / "memory" / "2026-05-08.md"
    daily.parent.mkdir(parents=True)
    daily.write_text("# 2026-05-08\n\n- Move backups to S3 Glacier.\n", encoding="utf-8")
    result = {
        "path": "memory/2026-05-08.md",
        "source": "memory",
        "startLine": 3,
        "endLine": 3,
        "snippet": "- Move backups to S3 Glacier.",
        "score": 1,
    }
    record_short_term_recalls(config=config, query="glacier", results=[result], now_ms=now)

    first = run_short_term_promotion(
        config=config,
        store=fake_store(config),
        now_ms=now,
        timezone="Europe/Istanbul",
        limit=5,
        min_score=0,
        min_recall_count=0,
        min_unique_queries=0,
        identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
    )
    memory_after_first = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    recall_path = tmp_path / "memory" / ".dreams" / "short-term-recall.json"
    recall_store = json.loads(recall_path.read_text(encoding="utf-8"))
    key = "memory:memory/2026-05-08.md:3:3"
    del recall_store["entries"][key]["promotedAt"]
    recall_path.write_text(json.dumps(recall_store, indent=2) + "\n", encoding="utf-8")

    second = run_short_term_promotion(
        config=config,
        store=fake_store(config),
        now_ms=now,
        timezone="Europe/Istanbul",
        limit=5,
        min_score=0,
        min_recall_count=0,
        min_unique_queries=0,
        identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
    )

    assert first.parsed.should_write is True
    assert second.parsed.should_write is False
    assert "appending 0; reconciled 1" in second.raw_text
    assert (tmp_path / "MEMORY.md").read_text(encoding="utf-8") == memory_after_first
    assert memory_after_first.count("openclaw-memory-promotion:") == 1
    assert memory_after_first.count("Move backups to S3 Glacier.") == 1
    recall_store = json.loads(recall_path.read_text(encoding="utf-8"))
    assert recall_store["entries"][key]["promotedAt"] == "2026-05-08T12:00:00.000Z"


def test_ranking_applies_max_age_gate_like_openclaw(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path)
    recalled_at = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    ranked_at = recalled_at + 3 * 86_400_000
    daily = tmp_path / "memory" / "2026-05-08.md"
    daily.parent.mkdir(parents=True)
    daily.write_text("# 2026-05-08\n\n- Move backups to S3 Glacier.\n", encoding="utf-8")
    result = {
        "path": "memory/2026-05-08.md",
        "source": "memory",
        "startLine": 3,
        "endLine": 3,
        "snippet": "- Move backups to S3 Glacier.",
        "score": 1,
    }
    record_short_term_recalls(
        config=config,
        query="glacier",
        results=[result],
        now_ms=recalled_at,
    )

    candidates = rank_short_term_promotion_candidates(
        config=config,
        now_ms=ranked_at,
        limit=5,
        min_score=0,
        min_recall_count=0,
        min_unique_queries=0,
        max_age_days=2,
    )

    assert candidates == []


def test_ranking_uses_recency_half_life_days_like_openclaw(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path)
    recalled_at = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    ranked_at = recalled_at + 7 * 86_400_000
    daily = tmp_path / "memory" / "2026-05-08.md"
    daily.parent.mkdir(parents=True)
    daily.write_text("# 2026-05-08\n\n- Move backups to S3 Glacier.\n", encoding="utf-8")
    result = {
        "path": "memory/2026-05-08.md",
        "source": "memory",
        "startLine": 3,
        "endLine": 3,
        "snippet": "- Move backups to S3 Glacier.",
        "score": 1,
    }
    record_short_term_recalls(
        config=config,
        query="glacier",
        results=[result],
        now_ms=recalled_at,
    )

    candidates = rank_short_term_promotion_candidates(
        config=config,
        now_ms=ranked_at,
        limit=5,
        min_score=0,
        min_recall_count=0,
        min_unique_queries=0,
        recency_half_life_days=7,
    )

    assert len(candidates) == 1
    assert candidates[0].age_days == 7
    assert candidates[0].components["recency"] == 0.5


def test_ranking_applies_score_recall_unique_query_and_limit_gates_like_openclaw(
    tmp_path: Path,
):
    config = MemoryConfig(workspace_dir=tmp_path)
    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    daily = tmp_path / "memory" / "2026-05-08.md"
    daily.parent.mkdir(parents=True)
    daily.write_text(
        "# 2026-05-08\n\n"
        "- Strong promotion candidate for backups.\n"
        "- Medium promotion candidate for routing.\n"
        "- Weak promotion candidate for notes.\n",
        encoding="utf-8",
    )
    strong = {
        "path": "memory/2026-05-08.md",
        "source": "memory",
        "startLine": 3,
        "endLine": 3,
        "snippet": "- Strong promotion candidate for backups.",
        "score": 1,
    }
    medium = {
        "path": "memory/2026-05-08.md",
        "source": "memory",
        "startLine": 4,
        "endLine": 4,
        "snippet": "- Medium promotion candidate for routing.",
        "score": 0.9,
    }
    weak = {
        "path": "memory/2026-05-08.md",
        "source": "memory",
        "startLine": 5,
        "endLine": 5,
        "snippet": "- Weak promotion candidate for notes.",
        "score": 0.8,
    }
    for query, results in (
        ("backup policy", [strong, medium, weak]),
        ("backup retention", [strong, medium]),
        ("backup restore", [strong]),
    ):
        record_short_term_recalls(config=config, query=query, results=results, now_ms=now)

    baseline = rank_short_term_promotion_candidates(
        config=config,
        now_ms=now,
        limit=10,
        min_score=0,
        min_recall_count=0,
        min_unique_queries=0,
    )
    min_recall_candidates = rank_short_term_promotion_candidates(
        config=config,
        now_ms=now,
        limit=10,
        min_score=0,
        min_recall_count=2,
        min_unique_queries=0,
    )
    unique_query_candidates = rank_short_term_promotion_candidates(
        config=config,
        now_ms=now,
        limit=10,
        min_score=0,
        min_recall_count=0,
        min_unique_queries=3,
    )
    limited = rank_short_term_promotion_candidates(
        config=config,
        now_ms=now,
        limit=1,
        min_score=0,
        min_recall_count=0,
        min_unique_queries=0,
    )
    above_top_score = rank_short_term_promotion_candidates(
        config=config,
        now_ms=now,
        limit=10,
        min_score=baseline[0].score + 0.001,
        min_recall_count=0,
        min_unique_queries=0,
    )

    assert [candidate.key for candidate in baseline] == [
        "memory:memory/2026-05-08.md:3:3",
        "memory:memory/2026-05-08.md:4:4",
        "memory:memory/2026-05-08.md:5:5",
    ]
    assert [candidate.recall_count for candidate in baseline] == [3, 2, 1]
    assert [candidate.key for candidate in min_recall_candidates] == [
        "memory:memory/2026-05-08.md:3:3",
        "memory:memory/2026-05-08.md:4:4",
    ]
    assert [candidate.key for candidate in unique_query_candidates] == [
        "memory:memory/2026-05-08.md:3:3"
    ]
    assert [candidate.key for candidate in limited] == ["memory:memory/2026-05-08.md:3:3"]
    assert above_top_score == []


def test_promotion_run_skips_candidate_when_live_daily_note_no_longer_contains_snippet(
    tmp_path: Path,
):
    config = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    daily = tmp_path / "memory" / "2026-05-08.md"
    daily.parent.mkdir(parents=True)
    daily.write_text("# 2026-05-08\n\n- Different note content now.\n", encoding="utf-8")
    result = {
        "path": "memory/2026-05-08.md",
        "source": "memory",
        "startLine": 3,
        "endLine": 3,
        "snippet": "- Move backups to S3 Glacier.",
        "score": 1,
    }
    record_short_term_recalls(config=config, query="glacier", results=[result], now_ms=now)

    candidates = rank_short_term_promotion_candidates(
        config=config,
        now_ms=now,
        limit=5,
        min_score=0,
        min_recall_count=0,
        min_unique_queries=0,
    )
    run = run_short_term_promotion(
        config=config,
        store=fake_store(config),
        now_ms=now,
        timezone="Europe/Istanbul",
        limit=5,
        min_score=0,
        min_recall_count=0,
        min_unique_queries=0,
    )

    assert len(candidates) == 1
    assert run.parsed.should_write is False
    assert not (tmp_path / "MEMORY.md").exists()
    recall_store = json.loads(
        (tmp_path / "memory" / ".dreams" / "short-term-recall.json").read_text(encoding="utf-8")
    )
    assert "promotedAt" not in recall_store["entries"]["memory:memory/2026-05-08.md:3:3"]


def test_promotion_header_uses_dreaming_timezone_like_openclaw(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    record_now = ms(datetime(2026, 4, 1, 23, 30, tzinfo=UTC))
    apply_now = ms(datetime(2026, 4, 2, 6, 30, tzinfo=UTC))
    daily = tmp_path / "memory" / "2026-04-01.md"
    daily.parent.mkdir(parents=True)
    daily.write_text(
        "# 2026-04-01\n\n- Cross-midnight router maintenance window.\n",
        encoding="utf-8",
    )
    record_short_term_recalls(
        config=config,
        query="router window",
        results=[
            {
                "path": "memory/2026-04-01.md",
                "source": "memory",
                "startLine": 3,
                "endLine": 3,
                "snippet": "- Cross-midnight router maintenance window.",
                "score": 0.9,
            }
        ],
        now_ms=record_now,
    )

    run = run_short_term_promotion(
        config=config,
        store=fake_store(config),
        now_ms=apply_now,
        timezone="America/Los_Angeles",
        limit=5,
        min_score=0,
        min_recall_count=0,
        min_unique_queries=0,
    )

    assert run.parsed.should_write is True
    assert "Promoted From Short-Term Memory (2026-04-01)" in (
        tmp_path / "MEMORY.md"
    ).read_text(encoding="utf-8")


# Literals below are the pin 4c42815348 outputs of the same inputs (applyShortTermPromotions,
# deriveConceptTags), recorded from the oracle on 2026-09-26.


def _record_glacier(config: MemoryConfig, now_ms: int) -> None:
    daily = config.workspace_dir / "memory" / "2026-05-08.md"
    daily.parent.mkdir(parents=True, exist_ok=True)
    daily.write_text("# 2026-05-08\n\n- Move backups to S3 Glacier.\n", encoding="utf-8")
    record_short_term_recalls(
        config=config,
        query="glacier",
        results=[
            {
                "source": "memory",
                "path": "memory/2026-05-08.md",
                "startLine": 3,
                "endLine": 3,
                "snippet": "- Move backups to S3 Glacier.",
                "score": 1,
            }
        ],
        now_ms=now_ms,
    )


def _promote_ungated(config: MemoryConfig, now_ms: int, **kwargs):
    return run_short_term_promotion(
        config=config,
        store=fake_store(config),
        now_ms=now_ms,
        timezone="Europe/Istanbul",
        min_score=0,
        min_recall_count=0,
        min_unique_queries=0,
        identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
        **kwargs,
    )


_GLACIER_SECTION = (
    "\n## Promoted From Short-Term Memory (2026-05-26)\n\n"
    "<!-- openclaw-memory-promotion:memory:memory/2026-05-08.md:3:3 -->\n"
    "- Move backups to S3 Glacier. [score=0.609 recalls=1 avg=1.000 "
    "source=memory/2026-05-08.md:3-3]\n"
)


def test_first_promotion_write_matches_openclaw_bytes(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    now = 1779811200000
    _record_glacier(config, now)

    _promote_ungated(config, now)

    assert (tmp_path / "MEMORY.md").read_text(encoding="utf-8") == (
        "# Long-Term Memory\n\n" + _GLACIER_SECTION
    )


def test_promotion_section_follows_existing_memory_after_a_blank_line_like_openclaw(
    tmp_path: Path,
):
    config = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    now = 1779811200000
    (tmp_path / "MEMORY.md").write_text("# Long-Term Memory\n\nKeep this.", encoding="utf-8")
    _record_glacier(config, now)

    _promote_ungated(config, now)

    assert (tmp_path / "MEMORY.md").read_text(encoding="utf-8") == (
        "# Long-Term Memory\n\nKeep this.\n" + _GLACIER_SECTION
    )


def test_promotion_restores_header_when_budget_drops_every_old_section_like_openclaw(
    tmp_path: Path,
):
    config = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    now = 1779811200000
    (tmp_path / "MEMORY.md").write_text(
        "## Promoted From Short-Term Memory (2026-04-10)\n"
        "<!-- openclaw-memory-promotion:legacy-old -->\n"
        f"- {'x' * 600}",
        encoding="utf-8",
    )
    _record_glacier(config, now)

    run = _promote_ungated(config, now, memory_file_max_chars=400)

    assert run.compacted_dates == ("2026-04-10",)
    assert (tmp_path / "MEMORY.md").read_text(encoding="utf-8") == (
        "# Long-Term Memory\n\n" + _GLACIER_SECTION
    )


def test_concept_tags_keep_decimal_tokens_and_split_dated_file_names_like_openclaw():
    assert concepts_module.derive_concept_tags(
        "memory/2026-04-08.md",
        "Candidate: move backups weekly. confidence: 0.76 evidence: memory/2026-04-08.md:1-1",
    ) == [
        "backup",
        "backups",
        "0.76",
        "memory/2026-04-08.md",
        "1-1",
        "candidate",
        "weekly",
        "confidence",
    ]
    assert concepts_module.derive_concept_tags(
        "memory/2026-05-26.md", "- User prefers to be addressed as dodo."
    ) == ["prefers", "addressed", "dodo"]


def test_promotion_metadata_rounds_ties_up_like_openclaw_to_fixed(tmp_path: Path):
    # buildPromotionSection formats score/avg with toFixed(3) (short-term-promotion.ts:2326),
    # which rounds an exact tie up: avg (1 + 0.125) / 2 = 0.5625 is written as 0.563.
    # Literal taken from the pin (test_real_openclaw_oracle_promotion_metadata_rounds_ties...).
    config = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    daily = tmp_path / "memory" / "2026-05-08.md"
    daily.parent.mkdir(parents=True)
    daily.write_text("# 2026-05-08\n\n- Move backups to S3 Glacier.\n", encoding="utf-8")
    hit = {
        "path": "memory/2026-05-08.md",
        "source": "memory",
        "startLine": 3,
        "endLine": 3,
        "snippet": "- Move backups to S3 Glacier.",
    }
    for query, score in (("glacier", 1), ("backups", 0.125)):
        record_short_term_recalls(
            config=config, query=query, results=[{**hit, "score": score}], now_ms=now
        )

    run_short_term_promotion(
        config=config,
        store=fake_store(config),
        now_ms=now,
        timezone="UTC",
        min_score=0,
        min_recall_count=0,
        min_unique_queries=0,
        identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
    )

    assert (tmp_path / "MEMORY.md").read_text(encoding="utf-8") == (
        "# Long-Term Memory\n\n\n## Promoted From Short-Term Memory (2026-05-08)\n\n"
        "<!-- openclaw-memory-promotion:memory:memory/2026-05-08.md:3:3 -->\n"
        "- Move backups to S3 Glacier. [score=0.549 recalls=2 avg=0.563 "
        "source=memory/2026-05-08.md:3-3]\n"
    )
