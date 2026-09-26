UPSTREAM_REPOSITORY = "https://github.com/openclaw/openclaw"
# Commit the original Python source port was derived from.
UPSTREAM_COMMIT = "7f6798094ce9486a8f463772f4535484aca73fe2"
# Current oracle target: OpenClaw release tag v2026.9.6 (tag commit dated 2026-09-22), adopted
# on 2026-09-27. Oracle fixtures in tests/integration run against a checkout at this commit.
# The tag sits on a release branch and is not an ancestor of upstream main.
LATEST_INSPECTED_COMMIT = "eb377ac59e6c9fd6c7705028034812becf00271b"
LATEST_INSPECTED_TAG = "v2026.9.6"
# Earlier LATEST_INSPECTED_COMMIT values and oracle baselines, oldest first:
# (commit, date, role). Python behaviour not yet re-ported to the tag was ported at one of these.
PREVIOUS_INSPECTED_COMMITS = (
    (
        "8c7f226401131164a450ee14e13c581eaf489993",
        "2026-05-26",
        "latest inspected commit (drift audit base), never an oracle baseline",
    ),
    (
        "b008989bef0747c49b9beecc7221f643d60e7e24",
        "2026-05-28",
        "oracle baseline 2026-05-28..2026-07-05",
    ),
    (
        "4c42815348ae336bf18e16ab049b6dbe0e4b8223",
        "2026-07-05",
        "HEAD audit; latest inspected commit and oracle target 2026-07-05..2026-09-26",
    ),
)

# Upstream files the source port referenced, as named at the port base. At v2026.9.6
# prompt-section.ts no longer exists (deleted in 16bec3c7272, #126552); its `## Memory Recall`
# builder lives in extensions/memory-core/src/memory-tool-contract.ts.
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
