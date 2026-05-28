from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path

import demo.short_term_promotion as promotion_module
from demo.short_term_promotion import (
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
from memory_core.config import MemoryConfig
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.index.sqlite_store import SQLiteMemoryStore


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def fake_store(config: MemoryConfig):
    return SQLiteMemoryStore(config, FakeEmbeddingProvider(dimensions=8))


def test_lock_constants_match_openclaw_paths():
    assert SHORT_TERM_PHASE_SIGNAL_RELATIVE_PATH.as_posix() == "memory/.dreams/phase-signals.json"
    assert SHORT_TERM_LOCK_RELATIVE_PATH.as_posix() == "memory/.dreams/short-term-promotion.lock"
    assert SHORT_TERM_LOCK_STALE_MS == 60_000
    assert not hasattr(promotion_module, "SHORT_TERM_LOCK_GUARD_RELATIVE_PATH")
    assert (
        promotion_module._SHORT_TERM_LOCK_GUARD_RELATIVE_PATH.as_posix()
        == "memory/.dreams/short-term-promotion.lock.guard"
    )


def test_concept_tags_match_openclaw_vocabulary_for_european_languages():
    assert promotion_module._derive_concept_tags(
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
    assert promotion_module._derive_concept_tags(
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
    tags = promotion_module._derive_concept_tags(
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
    assert promotion_module._derive_concept_tags(
        "memory/2026-04-03.md",
        "Move backups to S3 Glacier and sync QMD router notes.",
    ) == ["backup", "backups", "glacier", "qmd", "router", "sync"]


def test_concept_tags_match_openclaw_vocabulary_for_multilingual_short_term_fixture():
    assert promotion_module._derive_concept_tags(
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

    monkeypatch.setattr(promotion_module, "_lock_is_stale", replace_with_fresh_lock)

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

    assert result["removedInvalidEntries"] == 2
    assert result["rewroteStore"] is True
    assert result["removedStaleLock"] is True
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
