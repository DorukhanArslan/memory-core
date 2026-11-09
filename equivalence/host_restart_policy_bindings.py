"""Additional exact policy resolver owners for the independent policy capability."""
from pathlib import Path

from equivalence.host_restart_bindings import _owners, prepare_host_restart_runtime_bindings

SOURCE_HASHES = {
    "src/agents/memory-search-source-policy.ts": "b95b8ebf49144924307e153162b1302ba5fd48658e647618aec1ff0d54b0b80f",
    "packages/memory-host-sdk/src/host/config-utils.ts": "670063dd2236bd0340950d19accb55b022efcaee7be1275491777c5a1f65fa53",
}
SOURCE_ANCHORS = {
    "src/agents/memory-search-source-policy.ts": ("export function resolveMemorySearchSourcePolicy(params:",),
    "packages/memory-host-sdk/src/host/config-utils.ts": ("export function resolveRememberAcrossConversations(",),
}
COMPILED_HASHES = {
    "dist/memory-search-source-policy-B3S1qyBP.mjs": "6067ccdc77a747e519980c5d0ed2202afe42c3402f2f0f657038664bedc03434",
    "dist/config-utils-DioOBKyj.mjs": "7b740e863ffb8357ca58d856977d938d14415fb59747a909d87003be04ee1543",
}
COMPILED_ANCHORS = {
    "dist/memory-search-source-policy-B3S1qyBP.mjs": ("function resolveMemorySearchSourcePolicy(params)",),
    "dist/config-utils-DioOBKyj.mjs": ("function resolveRememberAcrossConversations(cfg, agentId)",),
}
ADDITIONAL_REQUIRED_HOST_ARTIFACTS = tuple(COMPILED_HASHES)


def prepare_host_restart_policy_bindings(checkout: Path, runtime_root: Path):
    original = prepare_host_restart_runtime_bindings(checkout, runtime_root)
    sources = _owners(Path(checkout).absolute(), SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
    compiled = _owners(Path(runtime_root).absolute(), COMPILED_HASHES, COMPILED_ANCHORS, committed=False)
    return {"kind": "official-release-host-restart-policy-owners", "operation": "host-restart-policy-runtime",
            "originalHostOwners": original, "additionalSourceBindings": sources,
            "additionalCompiledBindings": compiled, "sourceBuildReproduced": False,
            "sourceFallbackAllowed": False, "covers": [], "acceptancePointsAwarded": 0}
