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


def test_deep_dreaming_policy_defaults_are_the_tag_deep_defaults():
    # src/memory-host-sdk/dreaming.ts:22,42-51 at v2026.9.6: dreaming on, minScore 0.75.
    assert resolve_deep_dreaming_policy() == DeepDreamingPolicy(
        enabled=True,
        limit=10,
        min_score=0.75,
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
        assert policy.min_score == 0.75
        assert policy.max_age_days == 30
        assert policy.min_recall_count == 3
    assert resolve_deep_dreaming_policy(full_config).as_dict()["limit"] == 7


def test_deep_dreaming_policy_parses_integers_strictly_and_scores_like_number():
    # Measured with the deepPolicy oracle at v2026.9.6 (dreaming.ts:480-490): integers go through
    # parseStrictNonNegativeInteger / parseStrictPositiveInteger, scores keep normalizeScore.
    def resolve(**deep):
        return resolve_deep_dreaming_policy({"dreaming": {"phases": {"deep": deep}}})

    assert resolve(minScore=-0.2).min_score == 0.75
    assert resolve(minScore=None).min_score == 0.0
    assert resolve(limit=None).limit == 10
    assert resolve(limit="Infinity").limit == 10
    assert resolve(limit=float("inf")).limit == 10
    assert resolve(limit=" 12 ").limit == 12
    assert resolve(limit=7.9).limit == 10
    assert resolve(limit="0x10").limit == 10
    assert resolve(limit=0).limit == 0
    assert resolve(maxAgeDays=float("inf")).max_age_days == 30
    assert resolve(maxAgeDays=None).max_age_days == 30
    assert resolve(maxAgeDays=0).max_age_days == 30
    assert resolve(maxPromotedSnippetTokens="200").max_promoted_snippet_tokens == 200


def test_promotion_append_delegates_budget_compaction_to_memory_budget(
    tmp_path: Path, monkeypatch
):
    calls = []
    real = promotion_module.build_budgeted_memory_append

    def spy(**kwargs):
        calls.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(promotion_module, "build_budgeted_memory_append", spy)
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

    assert run.outcome.should_write is True
    assert [call["budget_chars"] for call in calls] == [4_000]
    assert calls[0]["existing_memory"] == "# MEMORY.md\n"


def test_repair_result_serializes_with_upstream_keys(tmp_path: Path):
    # RepairShortTermPromotionArtifactsResult field names (short-term-promotion.ts).
    config = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    now = _ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))

    repair = repair_short_term_promotion_artifacts(config, now)

    assert repair.as_dict() == {
        "changed": False,
        "removedInvalidEntries": 0,
        "rewroteStore": False,
        "removedStaleLock": False,
    }


def test_snippet_caps_count_utf16_code_units(tmp_path: Path):
    # truncateShortTermSnippet / truncatePromotedSnippet use UTF-16 .length and .slice;
    # oracle: test_real_openclaw_oracle_snippet_caps_count_utf16_units.
    from memory_core.consolidation.promotion import _format_promoted_snippet_for_memory
    from memory_core.consolidation.store import truncate_short_term_snippet

    brain = "\U0001f9e0"
    assert truncate_short_term_snippet(brain * 10 + "a" * 800) == brain * 10 + "a" * 780
    # truncateUtf16Safe (v2026.9.6): a cut inside a surrogate pair drops the pair.
    assert truncate_short_term_snippet("a" * 799 + brain) == "a" * 799
    assert _format_promoted_snippet_for_memory("x" * 639 + brain + "y", 160) == "x" * 639 + "..."

    config = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    hit = {"path": "memory/2026-05-08.md", "startLine": 3, "snippet": "a" * 799 + brain}
    record_short_term_recalls(config=config, query="a", results=[hit], now_ms=0)
    stored = (tmp_path / "memory" / ".dreams" / "short-term-recall.json").read_text("utf-8")
    assert '"snippet": "' + "a" * 799 + '"' in stored


def _seed_recalled_daily(tmp_path: Path, now: int) -> MemoryConfig:
    config = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    daily = tmp_path / "memory" / "2026-05-08.md"
    daily.parent.mkdir(parents=True)
    daily.write_text("# 2026-05-08\n\n- Move backups to S3 Glacier.\n", encoding="utf-8")
    hit = {
        "path": "memory/2026-05-08.md",
        "startLine": 3,
        "snippet": "- Move backups to S3 Glacier.",
        "score": 1,
    }
    record_short_term_recalls(config=config, query="glacier", results=[hit], now_ms=now)
    return config


def test_deep_sweep_applies_a_resolved_policy(tmp_path: Path):
    # dreaming.ts runShortTermDreamingPromotion: a disabled config promotes nothing;
    # an enabled one ranks and applies with its own limit, gates and age window.
    now = _ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    config = _seed_recalled_daily(tmp_path, now)
    store = SQLiteMemoryStore(config, FakeEmbeddingProvider(dimensions=8))
    deep = {"minScore": 0, "minRecallCount": 0, "minUniqueQueries": 0}

    def sweep(dreaming: dict) -> consolidation.DreamingSweepResult:
        policy = resolve_deep_dreaming_policy({"dreaming": {**dreaming, "phases": {"deep": deep}}})
        return run_dreaming_sweep(
            config=config, store=store, phase="deep", now_ms=now, timezone="UTC", policy=policy
        )

    disabled = sweep({"enabled": False})
    assert (disabled.skip_reason, disabled.promotion, disabled.files_changed) == (
        "disabled",
        None,
        (),
    )
    assert not (tmp_path / "MEMORY.md").exists()

    enabled = sweep({})  # dreaming is on by default at v2026.9.6
    assert enabled.skip_reason is None
    assert enabled.files_changed == ("MEMORY.md",)
    assert "Move backups to S3 Glacier." in (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
