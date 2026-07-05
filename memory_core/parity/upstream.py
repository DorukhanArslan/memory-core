UPSTREAM_REPOSITORY = "https://github.com/openclaw/openclaw"
# Commit the original Python source port was derived from.
UPSTREAM_COMMIT = "7f6798094ce9486a8f463772f4535484aca73fe2"
# Most recent upstream commit audited for behavioral drift (2026-07-05 audit;
# oracle fixtures in tests/integration run against this checkout).
LATEST_INSPECTED_COMMIT = "4c42815348ae336bf18e16ab049b6dbe0e4b8223"

UPSTREAM_SOURCE_PATHS = {
    "extensions/memory-core/src/prompt-section.ts",
    "extensions/memory-core/src/tools.ts",
    "extensions/memory-core/src/tools.citations.ts",
    "extensions/memory-core/src/tools.shared.ts",
    "extensions/memory-core/src/memory/hybrid.ts",
    "extensions/memory-core/src/memory/mmr.ts",
    "extensions/memory-core/src/memory/temporal-decay.ts",
    "extensions/memory-core/src/memory/manager.ts",
    "extensions/memory-core/src/memory/manager-search.ts",
    "extensions/memory-core/src/short-term-promotion.ts",
    "extensions/memory-core/src/dreaming.ts",
    "extensions/memory-core/src/dreaming-phases.ts",
}
