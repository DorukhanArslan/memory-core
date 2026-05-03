from memory_core.parity.upstream import UPSTREAM_COMMIT, UPSTREAM_SOURCE_PATHS


def test_upstream_commit_is_pinned():
    assert UPSTREAM_COMMIT == "7f6798094ce9486a8f463772f4535484aca73fe2"


def test_referenced_upstream_sources_are_recorded():
    assert "extensions/memory-core/src/prompt-section.ts" in UPSTREAM_SOURCE_PATHS
    assert "extensions/memory-core/src/memory/hybrid.ts" in UPSTREAM_SOURCE_PATHS
    assert "extensions/memory-core/src/memory/mmr.ts" in UPSTREAM_SOURCE_PATHS
    assert "extensions/memory-core/src/memory/temporal-decay.ts" in UPSTREAM_SOURCE_PATHS
