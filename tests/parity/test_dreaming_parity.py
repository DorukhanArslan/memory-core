from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from memory_core.config import MemoryConfig
from memory_core.consolidation import (
    SHORT_TERM_PHASE_SIGNAL_RELATIVE_PATH,
    record_daily_memory_flush,
    record_short_term_recalls,
    run_dreaming_sweep,
)
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.index.sqlite_store import SQLiteMemoryStore


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def fake_store(config: MemoryConfig):
    return SQLiteMemoryStore(config, FakeEmbeddingProvider(dimensions=8))


def seed_candidate(config: MemoryConfig, now_ms: int):
    daily = config.workspace_dir / "memory" / "2026-05-08.md"
    daily.parent.mkdir(parents=True, exist_ok=True)
    daily.write_text("# 2026-05-08\n\n- User prefers lowercase answers.\n", encoding="utf-8")
    result = {
        "path": "memory/2026-05-08.md",
        "startLine": 3,
        "endLine": 3,
        "snippet": "- User prefers lowercase answers.",
        "score": 0.9,
    }
    day_ms = 24 * 60 * 60 * 1000
    queries = ("lowercase", "answer case", "writing style", "response tone", "format preference")
    for offset, query in enumerate(queries):
        record_short_term_recalls(
            config=config,
            query=query,
            results=[result],
            now_ms=now_ms - (len(queries) - 1 - offset) * day_ms,
        )


def seed_weak_candidate(config: MemoryConfig, now_ms: int):
    daily = config.workspace_dir / "memory" / "2026-05-08.md"
    daily.parent.mkdir(parents=True, exist_ok=True)
    daily.write_text("# 2026-05-08\n\n- User mentioned tabs once.\n", encoding="utf-8")
    record_short_term_recalls(
        config=config,
        query="tabs",
        results=[
            {
                "path": "memory/2026-05-08.md",
                "startLine": 3,
                "endLine": 3,
                "snippet": "- User mentioned tabs once.",
                "score": 0.2,
            }
        ],
        now_ms=now_ms,
    )


def test_light_dreaming_records_phase_signal(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    seed_candidate(config, now)

    run = run_dreaming_sweep(
        config=config,
        store=fake_store(config),
        phase="light",
        now_ms=now,
        timezone="Europe/Istanbul",
    )

    assert run.phase == "light"
    assert run.phase_signals_recorded == 1
    assert (tmp_path / SHORT_TERM_PHASE_SIGNAL_RELATIVE_PATH).exists()


def test_rem_dreaming_writes_dreams_md(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    seed_candidate(config, now)

    run = run_dreaming_sweep(
        config=config,
        store=fake_store(config),
        phase="rem",
        now_ms=now,
        timezone="Europe/Istanbul",
    )

    dreams = tmp_path / "DREAMS.md"
    assert run.phase == "rem"
    assert dreams.exists()
    assert "Dreaming sweep" in dreams.read_text(encoding="utf-8")


def test_deep_dreaming_runs_promotion(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    (tmp_path / "MEMORY.md").write_text("# MEMORY.md\n", encoding="utf-8")
    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    seed_candidate(config, now)
    for phase in ("light", "rem"):
        run_dreaming_sweep(
            config=config,
            store=fake_store(config),
            phase=phase,
            now_ms=now,
            timezone="Europe/Istanbul",
        )

    run = run_dreaming_sweep(
        config=config,
        store=fake_store(config),
        phase="deep",
        now_ms=now,
        timezone="Europe/Istanbul",
    )

    assert run.phase == "deep"
    assert run.promotion.outcome.should_write is True
    assert "lowercase answers" in (tmp_path / "MEMORY.md").read_text(encoding="utf-8")


def test_deep_dreaming_keeps_durable_user_preference_behind_openclaw_score_gate(
    tmp_path: Path,
):
    config = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    memory = tmp_path / "MEMORY.md"
    memory.write_text("# MEMORY.md\n", encoding="utf-8")
    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    daily = tmp_path / "memory" / "2026-05-08.md"
    daily.parent.mkdir(parents=True, exist_ok=True)
    daily.write_text(
        "# 2026-05-08\n\n"
        "- User prefers to be addressed as \"Kudret\" in every conversation.\n",
        encoding="utf-8",
    )
    entry = "- User prefers to be addressed as \"Kudret\" in every conversation.\n"
    record_daily_memory_flush(
        config=config,
        target="memory/2026-05-08.md",
        entry=entry,
        now_ms=now,
    )
    record_daily_memory_flush(
        config=config,
        target="memory/2026-05-08.md",
        entry=entry,
        now_ms=now + 1,
    )
    for query in ("call me kudret", "address me kudret", "future sessions kudret"):
        record_short_term_recalls(
            config=config,
            query=query,
            results=[
                {
                    "path": "memory/2026-05-08.md",
                    "startLine": 3,
                    "endLine": 3,
                    "snippet": entry,
                    "score": 0.3,
                }
            ],
            now_ms=now,
        )

    run = run_dreaming_sweep(
        config=config,
        store=fake_store(config),
        phase="deep",
        now_ms=now,
        timezone="Europe/Istanbul",
    )

    assert run.phase == "deep"
    assert run.promotion.outcome.should_write is False
    assert "Kudret" not in memory.read_text(encoding="utf-8")


def test_deep_dreaming_rejects_three_signal_durable_preference_like_openclaw(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    memory = tmp_path / "MEMORY.md"
    memory.write_text("# MEMORY.md\n", encoding="utf-8")
    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    daily = tmp_path / "memory" / "2026-05-08.md"
    daily.parent.mkdir(parents=True, exist_ok=True)
    daily.write_text(
        "# 2026-05-08\n\n"
        "- User prefers to be addressed as \"Kudret\" in every conversation.\n",
        encoding="utf-8",
    )
    entry = "- User prefers to be addressed as \"Kudret\" in every conversation.\n"
    record_daily_memory_flush(
        config=config,
        target="memory/2026-05-08.md",
        entry=entry,
        now_ms=now,
    )
    for query in ("call me kudret", "future sessions kudret"):
        record_short_term_recalls(
            config=config,
            query=query,
            results=[
                {
                    "path": "memory/2026-05-08.md",
                    "startLine": 3,
                    "endLine": 3,
                    "snippet": entry,
                    "score": 0.3,
                }
            ],
            now_ms=now,
        )

    run = run_dreaming_sweep(
        config=config,
        store=fake_store(config),
        phase="deep",
        now_ms=now,
        timezone="Europe/Istanbul",
    )

    assert run.phase == "deep"
    assert run.promotion.outcome.should_write is False
    assert "Kudret" not in memory.read_text(encoding="utf-8")


def test_deep_dreaming_does_not_promote_single_weak_recall(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    memory = tmp_path / "MEMORY.md"
    memory.write_text("# MEMORY.md\n", encoding="utf-8")
    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    seed_weak_candidate(config, now)

    run = run_dreaming_sweep(
        config=config,
        store=fake_store(config),
        phase="deep",
        now_ms=now,
        timezone="Europe/Istanbul",
    )

    assert run.phase == "deep"
    assert run.promotion.outcome.should_write is False
    assert memory.read_text(encoding="utf-8") == "# MEMORY.md\n"
