from memory_core.parity.upstream import (
    LATEST_INSPECTED_COMMIT,
    LATEST_INSPECTED_TAG,
    PREVIOUS_INSPECTED_COMMITS,
    UPSTREAM_COMMIT,
    UPSTREAM_SOURCE_PATHS,
)


def test_upstream_commit_is_pinned():
    assert UPSTREAM_COMMIT == "7f6798094ce9486a8f463772f4535484aca73fe2"
    assert LATEST_INSPECTED_COMMIT == "eb377ac59e6c9fd6c7705028034812becf00271b"
    assert LATEST_INSPECTED_TAG == "v2026.9.6"


def test_previous_pins_keep_their_history():
    commits = [commit for commit, _date, _role in PREVIOUS_INSPECTED_COMMITS]
    assert commits == [
        "8c7f226401131164a450ee14e13c581eaf489993",
        "b008989bef0747c49b9beecc7221f643d60e7e24",
        "4c42815348ae336bf18e16ab049b6dbe0e4b8223",
    ]
    dates = [date for _commit, date, _role in PREVIOUS_INSPECTED_COMMITS]
    assert dates == sorted(dates)
    assert LATEST_INSPECTED_COMMIT not in commits
    assert UPSTREAM_COMMIT not in commits


def test_referenced_upstream_sources_are_recorded():
    assert "extensions/memory-core/src/prompt-section.ts" in UPSTREAM_SOURCE_PATHS
    assert "extensions/memory-core/src/memory/hybrid.ts" in UPSTREAM_SOURCE_PATHS
    assert "extensions/memory-core/src/memory/mmr.ts" in UPSTREAM_SOURCE_PATHS
    assert "extensions/memory-core/src/memory/temporal-decay.ts" in UPSTREAM_SOURCE_PATHS
    assert "extensions/memory-core/src/short-term-promotion.ts" in UPSTREAM_SOURCE_PATHS
    assert "extensions/memory-core/src/dreaming-phases.ts" in UPSTREAM_SOURCE_PATHS
