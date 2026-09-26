"""Package-level checks of memory_core.consolidation (offline; parity literals live in tests/parity)."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

import memory_core.consolidation as consolidation
import memory_core.consolidation.promotion as promotion_module
from memory_core.config import MemoryConfig
from memory_core.consolidation import (
    DeepDreamingPolicy,
    record_short_term_recalls,
    repair_short_term_promotion_artifacts,
    resolve_deep_dreaming_policy,
    run_dreaming_sweep,
    run_short_term_promotion,
)
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.index.sqlite_store import SQLiteMemoryStore

PACKAGE_DIR = Path(consolidation.__file__).parent


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def test_consolidation_imports_no_demo_web_or_llm_modules():
    banned_roots = {"demo", "fastapi", "starlette", "httpx", "openai"}
    for source in sorted(PACKAGE_DIR.glob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                roots = {(node.module or "").split(".")[0]}
            else:
                continue
            assert not roots & banned_roots, f"{source.name} imports {roots & banned_roots}"


def test_public_names_resolve():
    for name in consolidation.__all__:
        assert hasattr(consolidation, name), name


def test_deep_dreaming_policy_defaults_are_the_pin_deep_defaults():
    # src/memory-host-sdk/dreaming.ts:14,38-44 at 4c42815348.
    assert resolve_deep_dreaming_policy() == DeepDreamingPolicy(
        enabled=False,
        limit=10,
        min_score=0.8,
        min_recall_count=3,
        min_unique_queries=3,
        max_age_days=30,
        recency_half_life_days=14,
        max_promoted_snippet_tokens=160,
    )


def test_deep_dreaming_policy_reads_full_or_plugin_config_and_falls_back():
    deep = {"enabled": True, "limit": 7, "minScore": 1.4, "maxAgeDays": 0, "minRecallCount": "x"}
    plugin_config = {"dreaming": {"enabled": "true", "phases": {"deep": deep}}}
    full_config = {"plugins": {"entries": {"memory-core": {"config": plugin_config}}}}

    for config in (plugin_config, full_config):
        policy = resolve_deep_dreaming_policy(config)
        assert policy.enabled is True
        assert policy.limit == 7
        # dreaming.ts:220-230 normalizeScore: out of range falls back, never clamps.
        assert policy.min_score == 0.8
        assert policy.max_age_days == 30
        assert policy.min_recall_count == 3
    assert resolve_deep_dreaming_policy(full_config).as_dict()["limit"] == 7


def test_deep_dreaming_policy_uses_javascript_number_coercion():
    # Pin values measured with the deepPolicy oracle at 4c42815348 (dreaming.ts:181-230).
    def resolve(**deep):
        return resolve_deep_dreaming_policy({"dreaming": {"phases": {"deep": deep}}})

    assert resolve(minScore=-0.2).min_score == 0.8
    assert resolve(minScore=None).min_score == 0.0
    assert resolve(limit=None).limit == 0
    assert resolve(limit="Infinity").limit == 10
    assert resolve(limit=float("inf")).limit == 10
    assert resolve(limit=" 12 ").limit == 12
    assert resolve(limit=7.9).limit == 7
    assert resolve(maxAgeDays=float("inf")).max_age_days == 30
    assert resolve(maxAgeDays=None).max_age_days == 30
    assert resolve(maxPromotedSnippetTokens="200").max_promoted_snippet_tokens == 200


def test_promotion_append_delegates_budget_compaction_to_memory_budget(
    tmp_path: Path, monkeypatch
):
    calls = []
    real = promotion_module.compact_memory_for_budget

    def spy(**kwargs):
        calls.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(promotion_module, "compact_memory_for_budget", spy)
    config = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    (tmp_path / "MEMORY.md").write_text("# MEMORY.md\n", encoding="utf-8")
    daily = tmp_path / "memory" / "2026-05-08.md"
    daily.parent.mkdir(parents=True)
    daily.write_text("# 2026-05-08\n\n- Move backups to S3 Glacier.\n", encoding="utf-8")
    now = _ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    record_short_term_recalls(
        config=config,
        query="glacier",
        results=[
            {
                "path": "memory/2026-05-08.md",
                "startLine": 3,
                "snippet": "- Move backups to S3 Glacier.",
                "score": 1,
            }
        ],
        now_ms=now,
    )

    run = run_short_term_promotion(
        config=config,
        store=SQLiteMemoryStore(config, FakeEmbeddingProvider(dimensions=8)),
        now_ms=now,
        timezone="UTC",
        min_score=0,
        min_recall_count=0,
        min_unique_queries=0,
        memory_file_max_chars=4_000,
    )

    assert run.parsed.should_write is True
    assert [call["budget_chars"] for call in calls] == [4_000]
    assert calls[0]["existing_memory"] == "# MEMORY.md\n"


def test_typed_results_serialize_with_upstream_keys(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    now = _ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))

    sweep = run_dreaming_sweep(
        config=config,
        store=SQLiteMemoryStore(config, FakeEmbeddingProvider(dimensions=8)),
        phase="light",
        now_ms=now,
        timezone="UTC",
    )
    repair = repair_short_term_promotion_artifacts(config, now)

    assert sweep.as_dict() == {
        "phase": "light",
        "candidateCount": 0,
        "candidateKeys": [],
        "phaseSignalsRecorded": 0,
        "filesChanged": [],
        "promotion": None,
    }
    assert repair.as_dict() == {
        "changed": False,
        "removedInvalidEntries": 0,
        "rewroteStore": False,
        "removedStaleLock": False,
    }
