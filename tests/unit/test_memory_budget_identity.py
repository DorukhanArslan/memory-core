"""An explicit writing identity cannot delete another runtime's marked text."""
from dataclasses import replace

import pytest

from memory_core.config import MemoryConfig
from memory_core.consolidation.promotion import run_short_term_promotion
from memory_core.consolidation.recall import record_short_term_recalls
from memory_core.flags import FeatureFlags
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.memory_budget import build_budgeted_memory_append, compact_memory_for_budget, parse_memory_blocks
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY, OPENCLAW_COMPAT_RUNTIME_IDENTITY


def _block(prefix):
    return f"## Promoted From Short-Term Memory (2026-05-01)\n<!-- {prefix}old -->\n- " + "Saved source evidence. " * 30 + "\n"


@pytest.mark.parametrize("identity,prefix,generated", [
    (None, MEMORY_CORE_RUNTIME_IDENTITY.promotion_marker_prefix, True),
    (None, OPENCLAW_COMPAT_RUNTIME_IDENTITY.promotion_marker_prefix, True),
    (MEMORY_CORE_RUNTIME_IDENTITY, MEMORY_CORE_RUNTIME_IDENTITY.promotion_marker_prefix, True),
    (MEMORY_CORE_RUNTIME_IDENTITY, OPENCLAW_COMPAT_RUNTIME_IDENTITY.promotion_marker_prefix, False),
    (OPENCLAW_COMPAT_RUNTIME_IDENTITY, OPENCLAW_COMPAT_RUNTIME_IDENTITY.promotion_marker_prefix, True),
    (OPENCLAW_COMPAT_RUNTIME_IDENTITY, MEMORY_CORE_RUNTIME_IDENTITY.promotion_marker_prefix, False),
])
def test_parser_compaction_and_append_obey_the_same_owned_prefix(identity, prefix, generated):
    existing = _block(prefix)
    assert parse_memory_blocks(existing, identity=identity)[0].kind == ("promotion" if generated else "preserved")
    compacted = compact_memory_for_budget(existing_memory=existing, new_section="", budget_chars=1, identity=identity)
    assert compacted.compacted == ("" if generated else existing)
    assert compacted.dropped_dates == (("2026-05-01",) if generated else ())
    appended, dates = build_budgeted_memory_append(existing_memory=existing, new_section="New content.\n", budget_chars=1,
        identity=identity)
    assert dates == compacted.dropped_dates
    assert (existing in appended) is not generated


def test_custom_identity_prefix_is_literal_and_does_not_expand_regex_syntax():
    custom = replace(MEMORY_CORE_RUNTIME_IDENTITY, promotion_marker_prefix="host.[owned]+:")
    owned = _block(custom.promotion_marker_prefix)
    other = _block("host.o:")
    assert parse_memory_blocks(owned, identity=custom)[0].kind == "promotion"
    assert parse_memory_blocks(other, identity=custom)[0].kind == "preserved"
    assert compact_memory_for_budget(existing_memory=owned, new_section="", budget_chars=1, identity=custom).compacted == ""
    assert compact_memory_for_budget(existing_memory=other, new_section="", budget_chars=1, identity=custom).compacted == other


@pytest.mark.parametrize("identity,drops", [(OPENCLAW_COMPAT_RUNTIME_IDENTITY, False), (MEMORY_CORE_RUNTIME_IDENTITY, True)])
def test_real_promotion_caller_preserves_foreign_prefix_or_compacts_its_own(tmp_path, identity, drops):
    target = tmp_path / "MEMORY.md"
    before = _block(MEMORY_CORE_RUNTIME_IDENTITY.promotion_marker_prefix)
    target.write_text(before)
    relative = "memory/2026-05-08.md"
    daily = tmp_path / relative
    daily.parent.mkdir()
    daily.write_text("# Source\n\n- A saved preference.\n")
    now = 1779811200000
    config = MemoryConfig(tmp_path, flags=FeatureFlags(vector_search=False))
    record_short_term_recalls(config=config, query="preference", results=[{"path": relative, "startLine": 3,
        "endLine": 3, "snippet": "- A saved preference.", "score": 1}], now_ms=now)
    run = run_short_term_promotion(config=config, store=SQLiteMemoryStore(config, None), now_ms=now, timezone="UTC",
        min_score=0, min_recall_count=0, min_unique_queries=0, memory_file_max_chars=400,
        max_prior_entry_loss_fraction=1, identity=identity)
    assert run.appended == (1 if drops else 0)
    assert run.compacted_dates == (("2026-05-01",) if drops else ())
    if drops:
        assert before not in target.read_text() and "A saved preference." in target.read_text()
    else:
        assert target.read_text() == before
        assert run.rejected_candidates[0].category == "memory budget"
