"""Deep-phase LLM consolidation wiring, DREAMS.md history, preimages and JS case folding (offline)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from memory_core.config import MemoryConfig
from memory_core.consolidation import (
    DeepConsolidation,
    LlmConsolidationOptions,
    append_consolidation_skipped_summary,
    append_consolidation_summary,
    is_contaminated_dreaming_snippet,
    read_memory_preimages,
    record_short_term_recalls,
    run_dreaming_sweep,
)
from memory_core.consolidation.policy import DeepDreamingPolicy
from memory_core.consolidation.llm_consolidation import (
    ConsolidationRequest,
    _normalize_comparable_fact,
)
from memory_core.consolidation.markers import (
    MEMORY_CORE_PROMOTION_MARKER_PREFIX,
    OPENCLAW_PROMOTION_MARKER_PREFIX,
    extract_promotion_markers,
)
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.consolidation.curated_annotations import extract_project_keys_from_curated_entry

NOW_MS = 1779811200000
KEY = "memory:memory/2026-05-08.md:3:3"
DAILY = "# 2026-05-08\n\n- Move backups to S3 Glacier.\n"
MEMORY = "# Memory\n\n- Existing global fact.\n"


def _workspace(tmp_path: Path, *, memory: str | None = MEMORY) -> tuple[MemoryConfig, SQLiteMemoryStore]:
    workspace = tmp_path / "ws"
    (workspace / "memory").mkdir(parents=True)
    (workspace / "memory" / "2026-05-08.md").write_text(DAILY, encoding="utf-8")
    if memory is not None:
        (workspace / "MEMORY.md").write_text(memory, encoding="utf-8")
    config = MemoryConfig(workspace_dir=workspace, store_path=tmp_path / "idx.sqlite")
    record_short_term_recalls(
        config=config,
        query="backups",
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
        now_ms=NOW_MS,
    )
    return config, SQLiteMemoryStore(config, FakeEmbeddingProvider(dimensions=8))


def _deep(config, store, *, consolidation=None, **extra):
    return run_dreaming_sweep(
        config=config,
        store=store,
        phase="deep",
        now_ms=NOW_MS,
        timezone="UTC",
        consolidation=consolidation,
        policy=DeepDreamingPolicy(
            enabled=True, limit=10, min_score=0, min_recall_count=0, min_unique_queries=0
        ),
        **extra,
    )


def _consolidation(model, *, enabled=True) -> DeepConsolidation:
    return DeepConsolidation(
        model=model,
        options=LlmConsolidationOptions(enabled=enabled),
        logger=logging.getLogger("unit-deep-consolidation"),
    )


def _added(_request: ConsolidationRequest) -> str:
    return json.dumps(
        {"operations": [{"candidateKey": KEY, "action": "added", "priorEntries": []}]}
    )


def _gates() -> dict[str, Any]:
    return {}


def test_default_is_deterministic_and_never_calls_the_model(tmp_path: Path) -> None:
    config, store = _workspace(tmp_path)
    calls: list[Any] = []

    def model(request: ConsolidationRequest) -> str:
        calls.append(request)
        return _added(request)

    off = _deep(config, store, consolidation=_consolidation(model, enabled=False))
    assert calls == []
    assert off.promotion is not None
    assert off.promotion.outcome.reason == "short-term promotion"
    assert not (config.workspace_dir / "DREAMS.md").exists()
    assert not (config.workspace_dir / "memory" / ".dreams" / "consolidation-preimages.json").exists()


def test_enabled_consolidation_rewrites_memory_with_preimage_and_history(tmp_path: Path) -> None:
    config, store = _workspace(tmp_path)
    result = _deep(config, store, consolidation=_consolidation(_added))
    promotion = result.promotion
    assert promotion is not None
    assert promotion.outcome.reason == "short-term promotion consolidated"
    assert promotion.consolidation is not None and promotion.consolidation.added == 1
    memory = (config.workspace_dir / "MEMORY.md").read_text(encoding="utf-8")
    assert "## Consolidated Memory (2026-05-26)" in memory
    assert "- Move backups to S3 Glacier. Source: memory/2026-05-08.md#L3-L3" in memory
    assert extract_promotion_markers(memory) == [KEY]
    preimages = read_memory_preimages(config.workspace_dir)
    assert [item["content"] for item in preimages] == [MEMORY]
    dreams = (config.workspace_dir / "DREAMS.md").read_text(encoding="utf-8")
    assert dreams.startswith("## Memory Consolidation History\n\n### 2026-05-26T16:00:00.000Z\n\n")
    assert "- Added: 1\n- Merged: 0\n- Superseded: 0\n" in dreams
    assert "DREAMS.md" in result.files_changed and "MEMORY.md" in result.files_changed
    recall = json.loads(
        (config.workspace_dir / "memory" / ".dreams" / "short-term-recall.json").read_text("utf-8")
    )
    assert recall["entries"][KEY]["promotedAt"]


def test_rejected_plan_falls_back_to_the_deterministic_section(tmp_path: Path) -> None:
    config, store = _workspace(tmp_path)
    result = _deep(config, store, consolidation=_consolidation(lambda _r: "not json"))
    assert result.promotion is not None
    assert result.promotion.outcome.reason == "short-term promotion"
    memory = (config.workspace_dir / "MEMORY.md").read_text(encoding="utf-8")
    assert "## Promoted From Short-Term Memory (2026-05-26)" in memory
    assert not (config.workspace_dir / "DREAMS.md").exists()
    assert read_memory_preimages(config.workspace_dir) == []


def test_memory_changed_during_planning_skips_with_a_history_note(tmp_path: Path) -> None:
    config, store = _workspace(tmp_path)

    def model(request: ConsolidationRequest) -> str:
        with (config.workspace_dir / "MEMORY.md").open("a", encoding="utf-8") as handle:
            handle.write("- Added concurrently.\n")
        return _added(request)

    result = _deep(config, store, consolidation=_consolidation(model))
    assert result.promotion is not None
    assert result.promotion.consolidation_skipped_reason == (
        "MEMORY.md changed while consolidation was running"
    )
    memory = (config.workspace_dir / "MEMORY.md").read_text(encoding="utf-8")
    assert "- Added concurrently." in memory and "## Promoted From Short-Term Memory" in memory
    dreams = (config.workspace_dir / "DREAMS.md").read_text(encoding="utf-8")
    assert dreams.endswith(
        "### 2026-05-26T16:00:00.000Z\n\n- Rewrite skipped: MEMORY.md changed while "
        "consolidation was running.\n- Fallback: append-only promotion.\n"
    )


def test_untrusted_origin_is_filtered_when_consolidation_is_active(tmp_path: Path) -> None:
    config, store = _workspace(tmp_path)
    path = config.workspace_dir / "memory" / ".dreams" / "short-term-recall.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["entries"][KEY]["provenance"] = {"originClass": "system", "sessionKind": "unknown"}
    path.write_text(json.dumps(data), encoding="utf-8")
    calls: list[Any] = []
    result = _deep(
        config, store, consolidation=_consolidation(lambda r: calls.append(r) or _added(r))
    )
    assert calls == []
    assert result.promotion is not None and result.promotion.applied_candidates == ()


def test_history_writers_use_the_upstream_text(tmp_path: Path) -> None:
    append_consolidation_summary(
        tmp_path, added=1, merged=2, superseded=3, highlights=["<!-- m -->\n- `+ x`"], now_ms=NOW_MS
    )
    append_consolidation_skipped_summary(tmp_path, now_ms=NOW_MS + 1000, reason="why")
    assert (tmp_path / "DREAMS.md").read_text(encoding="utf-8") == (
        "## Memory Consolidation History\n\n"
        "### 2026-05-26T16:00:00.000Z\n\n- Added: 1\n- Merged: 2\n- Superseded: 3\n"
        "<!-- m -->\n- `+ x`\n\n"
        "### 2026-05-26T16:00:01.000Z\n\n- Rewrite skipped: why.\n"
        "- Fallback: append-only promotion.\n"
    )


def test_history_goes_to_an_existing_lowercase_dreams_file(tmp_path: Path) -> None:
    (tmp_path / "dreams.md").write_text("kept\n", encoding="utf-8")
    append_consolidation_skipped_summary(tmp_path, now_ms=NOW_MS, reason="r")
    assert not (tmp_path / "DREAMS.md").exists()
    assert (tmp_path / "dreams.md").read_text(encoding="utf-8").startswith(
        "kept\n\n## Memory Consolidation History\n\n### "
    )


def test_history_refuses_a_symlinked_dreams_file(tmp_path: Path) -> None:
    target = tmp_path / "elsewhere.md"
    target.write_text("x", encoding="utf-8")
    (tmp_path / "DREAMS.md").symlink_to(target)
    try:
        append_consolidation_skipped_summary(tmp_path, now_ms=NOW_MS, reason="r")
    except OSError as error:
        assert "symlinked DREAMS.md" in str(error)
    else:
        raise AssertionError("expected a refusal")
    assert target.read_text(encoding="utf-8") == "x"


# --- JavaScript case folding in the consolidation regexes ---------------------------------


def test_normalize_comparable_fact_folds_like_js_iu() -> None:
    # /iu: U+212A (Kelvin) folds onto k, U+017F (long s) onto s; U+0130 folds onto nothing.
    assert _normalize_comparable_fact("- Fact <!-- triɡger: x -->") != "fact"
    assert _normalize_comparable_fact("- Fact <!-- trigger: x -->") == "fact"
    assert _normalize_comparable_fact("- Fact <!-- TRIGGER: x -->") == "fact"
    assert _normalize_comparable_fact("- Fact Source: memory/a.md#L1-L2") == "fact"
    assert _normalize_comparable_fact("- Fact ſource: memory/a.md#L1-L2") == "fact"
    assert _normalize_comparable_fact("- Fact <!-- project: a -->") == "fact"
    assert _normalize_comparable_fact("- Fact <!-- <!--  İmportance: 3 -->") != "fact"
    assert _normalize_comparable_fact("- Fact <!-- İmportance: 3 -->") == (
        "fact <!-- İmportance: 3 -->".lower()
    )
    assert _normalize_comparable_fact("- Fact <!-- importance: 3 -->") == "fact"


def test_non_unicode_ignore_case_does_not_fold_non_ascii() -> None:
    # /i without u: only ASCII letters fold, so U+017F never reads as an "s".
    assert is_contaminated_dreaming_snippet("Session Key abc Session ID def")
    assert is_contaminated_dreaming_snippet("SESSION KEY abc session id def")
    assert not is_contaminated_dreaming_snippet("ſession Key abc Session ID def")
    assert is_contaminated_dreaming_snippet("Conversation Summary: x")
    assert not is_contaminated_dreaming_snippet("Converſation Summary: x")
    # \b and \d are ASCII-only like JavaScript's: Arabic-Indic digits are not digits.
    snippet = (
        "Candidate: x confidence: ٣ evidence: memory/a.md status: staged recalls: 2 "
        "note: reflection"
    )
    assert not is_contaminated_dreaming_snippet(snippet)
    assert is_contaminated_dreaming_snippet(snippet.replace("٣", "3"))


def test_curated_project_annotation_and_markers_fold_like_js() -> None:
    keys = extract_project_keys_from_curated_entry("- fact <!-- PROJECT: alpha -->")
    assert keys.keys == ("alpha",)
    assert extract_promotion_markers(f"<!-- {MEMORY_CORE_PROMOTION_MARKER_PREFIX}abc -->") == ["abc"]
    assert extract_promotion_markers(f"<!-- {OPENCLAW_PROMOTION_MARKER_PREFIX.upper()}abc -->") == [
        "abc"
    ]
    assert extract_promotion_markers(f"<!-- {OPENCLAW_PROMOTION_MARKER_PREFIX[:-1]}\u212a:abc -->") == []
