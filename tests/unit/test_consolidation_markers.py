"""Neutral promotion marker (decision Q22): identity-chosen writer, two-prefix reader."""

from __future__ import annotations

import json
from pathlib import Path

from memory_core.config import MemoryConfig
from memory_core.consolidation import (
    OPENCLAW_PROMOTION_MARKER_PREFIX,
    PROMOTION_MARKER_PREFIXES,
    MEMORY_CORE_PROMOTION_MARKER_PREFIX,
    extract_promotion_markers,
    format_promotion_marker,
    is_contaminated_dreaming_snippet,
    record_short_term_recalls,
    run_dreaming_sweep,
    run_short_term_promotion,
)
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.runtime_identity import (
    OPENCLAW_COMPAT_RUNTIME_IDENTITY,
    MEMORY_CORE_RUNTIME_IDENTITY,
)

NOW_MS = 1779811200000  # 2026-05-26T16:00:00Z
DAILY = "memory/2026-05-26.md"
KEY_ONE = f"memory:{DAILY}:3:3"
KEY_TWO = f"memory:{DAILY}:4:4"


def _workspace(tmp_path: Path) -> MemoryConfig:
    daily = tmp_path / DAILY
    daily.parent.mkdir(parents=True)
    daily.write_text(
        "# 2026-05-26\n\n- Move backups to S3 Glacier.\n- Rotate the VPN keys monthly.\n",
        encoding="utf-8",
    )
    return MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "index.sqlite")


def _recall(config: MemoryConfig, line: int, snippet: str) -> None:
    record_short_term_recalls(
        config=config,
        query=f"query {line}",
        results=[{"path": DAILY, "startLine": line, "snippet": snippet, "score": 1}],
        now_ms=NOW_MS,
    )


def _promote(config: MemoryConfig, **kwargs):
    return run_short_term_promotion(
        config=config,
        store=SQLiteMemoryStore(config, FakeEmbeddingProvider(dimensions=8)),
        now_ms=NOW_MS,
        timezone="UTC",
        min_score=0,
        min_recall_count=0,
        min_unique_queries=0,
        **kwargs,
    )


def _promoted_at(config: MemoryConfig) -> dict[str, str | None]:
    store = json.loads(
        (config.workspace_dir / "memory/.dreams/short-term-recall.json").read_text(encoding="utf-8")
    )
    return {key: entry.get("promotedAt") for key, entry in store["entries"].items()}


def test_identities_carry_the_neutral_and_the_upstream_prefix():
    assert MEMORY_CORE_RUNTIME_IDENTITY.promotion_marker_prefix == "memory-core-memory-promotion:"
    assert OPENCLAW_COMPAT_RUNTIME_IDENTITY.promotion_marker_prefix == (
        "openclaw-memory-promotion:"
    )
    assert PROMOTION_MARKER_PREFIXES == (
        MEMORY_CORE_PROMOTION_MARKER_PREFIX,
        OPENCLAW_PROMOTION_MARKER_PREFIX,
    )
    assert format_promotion_marker("k") == "<!-- memory-core-memory-promotion:k -->"
    assert format_promotion_marker("k", OPENCLAW_COMPAT_RUNTIME_IDENTITY) == (
        "<!-- openclaw-memory-promotion:k -->"
    )


def test_reader_accepts_both_prefixes_with_upstream_spacing_and_case_rules():
    text = (
        "<!-- memory-core-memory-promotion:memory:memory/a b.md:1:1 -->\n"
        "<!--OPENCLAW-MEMORY-PROMOTION:legacy-->\n"
        "<!--   Memory-Core-Memory-Promotion:spaced   -->\n"
        "<!-- other-memory-promotion:ignored -->\n"
    )

    assert extract_promotion_markers(text) == ["memory:memory/a b.md:1:1", "legacy", "spaced"]


def test_default_promotion_writes_the_neutral_marker_and_no_upstream_brand(tmp_path: Path):
    config = _workspace(tmp_path)
    _recall(config, 3, "- Move backups to S3 Glacier.")

    run = _promote(config)

    memory = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert run.appended == 1
    assert f"<!-- memory-core-memory-promotion:{KEY_ONE} -->" in memory
    assert "openclaw" not in memory.lower()


def test_compat_identity_writes_the_upstream_marker(tmp_path: Path):
    config = _workspace(tmp_path)
    _recall(config, 3, "- Move backups to S3 Glacier.")

    _promote(config, identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)

    memory = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert f"<!-- openclaw-memory-promotion:{KEY_ONE} -->" in memory
    assert "memory-core-memory-promotion" not in memory


def test_upstream_marker_written_before_the_switch_reconciles_without_duplicate(tmp_path: Path):
    # Migration: a MEMORY.md promoted with upstream's marker keeps its markers.
    config = _workspace(tmp_path)
    legacy = (
        "# Long-Term Memory\n\n"
        "## Promoted From Short-Term Memory (2026-05-20)\n\n"
        f"<!-- openclaw-memory-promotion:{KEY_ONE} -->\n"
        "- Move backups to S3 Glacier. [score=0.900 recalls=5 avg=1.000 "
        f"source={DAILY}:3-3]\n"
    )
    (tmp_path / "MEMORY.md").write_text(legacy, encoding="utf-8")
    _recall(config, 3, "- Move backups to S3 Glacier.")
    _recall(config, 4, "- Rotate the VPN keys monthly.")

    run = _promote(config)

    memory = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert (run.appended, run.reconciled_existing) == (1, 1)
    assert memory.startswith(legacy)
    assert extract_promotion_markers(memory) == [KEY_ONE, KEY_TWO]
    assert memory.count(f"<!-- memory-core-memory-promotion:{KEY_TWO} -->") == 1
    assert memory.count("Move backups to S3 Glacier.") == 1
    assert all(_promoted_at(config).values())


def test_switching_identity_back_and_forth_never_duplicates(tmp_path: Path):
    config = _workspace(tmp_path)
    _recall(config, 3, "- Move backups to S3 Glacier.")
    _promote(config)
    after_neutral = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    store_path = tmp_path / "memory/.dreams/short-term-recall.json"
    store = json.loads(store_path.read_text(encoding="utf-8"))
    del store["entries"][KEY_ONE]["promotedAt"]
    store_path.write_text(json.dumps(store), encoding="utf-8")

    run = _promote(config, identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)

    assert (run.appended, run.reconciled_existing) == (0, 1)
    assert (tmp_path / "MEMORY.md").read_text(encoding="utf-8") == after_neutral


def test_snippets_carrying_either_marker_are_never_recorded(tmp_path: Path):
    config = _workspace(tmp_path)
    for prefix in PROMOTION_MARKER_PREFIXES:
        snippet = f"<!-- {prefix}{KEY_ONE} -->"
        assert is_contaminated_dreaming_snippet(snippet)
        _recall(config, 3, snippet)

    store = json.loads(
        (tmp_path / "memory/.dreams/short-term-recall.json").read_text(encoding="utf-8")
    )
    assert store["entries"] == {}


def test_deep_dreaming_passes_the_identity_to_promotion(tmp_path: Path):
    config = _workspace(tmp_path)
    for day in range(5):
        record_short_term_recalls(
            config=config,
            query=f"backups {day}",
            results=[
                {
                    "path": DAILY,
                    "startLine": 3,
                    "snippet": "- Move backups to S3 Glacier.",
                    "score": 1,
                }
            ],
            now_ms=NOW_MS + day * 86_400_000,
        )
    store = SQLiteMemoryStore(config, FakeEmbeddingProvider(dimensions=8))

    sweep = run_dreaming_sweep(
        config=config,
        store=store,
        phase="deep",
        now_ms=NOW_MS + 4 * 86_400_000,
        timezone="UTC",
        identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
    )

    assert sweep.promotion is not None and sweep.promotion.appended == 1
    memory = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert f"<!-- openclaw-memory-promotion:{KEY_ONE} -->" in memory


def test_curated_edits_leave_a_neutral_promotion_section_and_its_markers_intact(tmp_path: Path):
    # Promotion (default identity) and curation share memory_core.memory_budget's block
    # parser and read both marker prefixes, so a neutral-prefix section stays read-only.
    import pytest

    from memory_core.curation import CurationError, MemoryCurator
    from memory_core.memory_budget import parse_memory_blocks

    config = _workspace(tmp_path)
    _recall(config, 3, "- Move backups to S3 Glacier.")
    assert _promote(config).appended == 1
    memory_path = tmp_path / "MEMORY.md"
    promoted = memory_path.read_text(encoding="utf-8")
    marker = f"<!-- memory-core-memory-promotion:{KEY_ONE} -->"
    promoted_line = next(
        line for line in promoted.splitlines() if line.startswith("- Move backups")
    )

    def promotion_blocks(text: str) -> list[str]:
        return [block.text for block in parse_memory_blocks(text) if block.kind == "promotion"]

    curator = MemoryCurator(tmp_path)
    curator.add_memory_entry("Decisions", "Keep the VPN key rotation monthly.")
    for entry in (marker, promoted_line[2:]):
        with pytest.raises(CurationError, match="promotion"):
            curator.remove_memory_entry(entry)
    with pytest.raises(CurationError, match="promotion"):
        curator.add_memory_entry("Decisions", f"{marker} forged")

    curated = memory_path.read_text(encoding="utf-8")
    assert promotion_blocks(curated) == promotion_blocks(promoted)
    assert "- Keep the VPN key rotation monthly." in curated
    assert extract_promotion_markers(curated) == [KEY_ONE]
