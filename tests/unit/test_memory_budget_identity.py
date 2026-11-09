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


@pytest.mark.parametrize("identity", [None, OPENCLAW_COMPAT_RUNTIME_IDENTITY])
@pytest.mark.parametrize("change", ["dotted-i", "dotless-i", "key-cr", "key-ls", "key-ps", "project-cr", "project-ls", "project-ps"])
def test_lookalike_prefixes_and_js_dot_line_boundaries_preserve_all_user_bytes(identity, change):
    existing = _block(OPENCLAW_COMPAT_RUNTIME_IDENTITY.promotion_marker_prefix)
    if change in {"dotted-i", "dotless-i"}:
        existing = existing.replace("promotion:", "promot" + ("\u0130" if change == "dotted-i" else "\u0131") + "on:")
    else:
        separator = {"cr": "\r", "ls": "\u2028", "ps": "\u2029"}[change.split("-")[1]]
        existing = (existing.replace("promotion:old", "promotion:old" + separator + "user") if change.startswith("key-") else
            existing.replace("\n<!--", "\n### Project: owner" + separator + "user\n<!--"))
    result = compact_memory_for_budget(existing_memory=existing, new_section="", budget_chars=1, identity=identity)
    assert result.compacted == existing and result.dropped_dates == ()


def test_ascii_case_still_folds_and_non_ascii_custom_prefix_remains_literal():
    own = OPENCLAW_COMPAT_RUNTIME_IDENTITY.promotion_marker_prefix
    existing = _block(own).replace(own, own.upper())
    assert compact_memory_for_budget(existing_memory=existing, new_section="", budget_chars=1,
        identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY).compacted == ""
    custom = replace(MEMORY_CORE_RUNTIME_IDENTITY, promotion_marker_prefix="host.\u03a3+:")
    assert compact_memory_for_budget(existing_memory=_block(custom.promotion_marker_prefix), new_section="", budget_chars=1,
        identity=custom).compacted == ""
    lookalike = _block("host.\u03c3+:")
    assert compact_memory_for_budget(existing_memory=lookalike, new_section="", budget_chars=1,
        identity=custom).compacted == lookalike


@pytest.mark.parametrize("identity,prefix,drops", [
    (OPENCLAW_COMPAT_RUNTIME_IDENTITY, MEMORY_CORE_RUNTIME_IDENTITY.promotion_marker_prefix, False),
    (MEMORY_CORE_RUNTIME_IDENTITY, MEMORY_CORE_RUNTIME_IDENTITY.promotion_marker_prefix, True),
    (MEMORY_CORE_RUNTIME_IDENTITY, OPENCLAW_COMPAT_RUNTIME_IDENTITY.promotion_marker_prefix, True),
])
def test_real_promotion_caller_keeps_core_legacy_dual_and_compatibility_strict(tmp_path, identity, prefix, drops):
    target = tmp_path / "MEMORY.md"
    before = _block(prefix)
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


@pytest.mark.parametrize("before", [
    "# Personal notes\r\nKeep this exact user text.\rA separate literal CR and 😀.\r\n",
    "# Personal notes\rOnly bare CR separates these user lines.\r",
])
def test_real_promotion_preserves_original_line_endings_and_publication_preimage(tmp_path, monkeypatch, before):
    import memory_core.atomic_publication as publication
    from memory_core.consolidation._util import read_text_if_exists

    target = tmp_path / "MEMORY.md"
    encoded = before.encode("utf-8")
    target.write_bytes(encoded)
    # The shared helper's existing default stays unchanged for other readers.
    assert read_text_if_exists(target) == before.replace("\r\n", "\n").replace("\r", "\n")
    assert read_text_if_exists(target, preserve_newlines=True) == before
    daily = tmp_path / "memory" / "2026-05-08.md"
    daily.parent.mkdir()
    daily.write_text("# Source\n\n- A saved preference.\n")
    config = MemoryConfig(tmp_path, flags=FeatureFlags(vector_search=False))
    now = 1779811200000
    record_short_term_recalls(config=config, query="preference", results=[{"path": "memory/2026-05-08.md",
        "startLine": 3, "endLine": 3, "snippet": "- A saved preference.", "score": 1}], now_ms=now)
    original = publication.commit_memory_content
    requests = []

    def commit(path, **kwargs):
        requests.append((path, kwargs.copy()))
        return original(path, **kwargs)

    monkeypatch.setattr(publication, "commit_memory_content", commit)
    run = run_short_term_promotion(config=config, store=SQLiteMemoryStore(config, None), now_ms=now,
        timezone="UTC", min_score=0, min_recall_count=0, min_unique_queries=0,
        identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)
    assert run.appended == 1 and run.reconciled_existing == 0
    request_path, request = requests[0]
    assert len(requests) == 1 and request_path == target
    assert request["expected_content"] == before
    assert request["expected_hash"] == publication.hash_memory_content(before)
    assert target.read_bytes() == request["content"].encode("utf-8")
    assert target.read_bytes().startswith(encoded)


def test_optional_preserving_reader_keeps_missing_and_strict_utf8_policy(tmp_path):
    from memory_core.consolidation._util import read_text_if_exists

    target = tmp_path / "MEMORY.md"
    assert read_text_if_exists(target) == read_text_if_exists(target, preserve_newlines=True) == ""
    target.write_bytes(b"invalid UTF8 \xff\r\n")
    for preserve in (False, True):
        with pytest.raises(UnicodeDecodeError):
            read_text_if_exists(target, preserve_newlines=preserve)
