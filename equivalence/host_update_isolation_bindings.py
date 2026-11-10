"""Original owners added by the update/isolation capability.

The reviewed host-restart publication owners stay separate and unchanged. These
pins authenticate declarations only: the genuine `edit` producer, the per-agent
workspace resolver and the stale-index report. Real execution, refusal and
publication failure must be established by the family's evidence guard.
`consolidateMemory` needs a model completion and is authenticated only.
"""
from __future__ import annotations

from pathlib import Path

from equivalence.host_restart_bindings import REFERENCE_COMMIT, _owners
from equivalence.host_restart_publication_bindings import prepare_host_restart_publication_bindings

UPDATE_OPERATION = "host-update-isolation-runtime"

SOURCE_HASHES = {
    "src/agents/agent-tools.read.ts": "34db04c4719a01d2b173c690498707e42c2dc8d1b8f6b1bca211fce9c08e3a6a",
    "src/agents/sessions/tools/edit.ts": "7d2a36bc4866720d0df6c4af073f34d18a3a2c0024e22355ee89cf701848eb67",
    "packages/memory-host-sdk/src/host/types.ts": "737b555fc517671b927bcbab30334ffbd20c3690e02fa72595eeaacbddf06e4a",
    "src/agents/agent-scope-config.ts": "97afbaa31c3014db8ac76550907e25b60b449052aee03a7591917391c768b245",
}
SOURCE_ANCHORS = {
    "src/agents/agent-tools.read.ts": ("export function createHostWorkspaceEditTool(",),
    "src/agents/sessions/tools/edit.ts": ("export function createEditTool(",),
    "packages/memory-host-sdk/src/host/types.ts": (
        "    warning: `Memory index is stale: ${reason}. Search results may be incomplete.`,",),
    "src/agents/agent-scope-config.ts": ("export function resolveAgentWorkspaceDir(",),
}
COMPILED_HASHES = {
    "dist/agent-tools.read-ZzkirzL1.mjs": "bec516044e956d92b1297b154a48ef9ee75e83dfdfe79b8dda5668a9995e778c",
    "dist/tools-DLW3vi8k.mjs": "100134d5d22981dcad305e470b30c6e8296e6ef7e034bcc2cabc502552c91b02",
    "dist/types-DTVBdCzw.mjs": "14598f9947a85bf691d345dc54c32899c8931afc580e45f143918afe8b54db50",
    "dist/agent-scope-config-Dm6T00l4.mjs": "046526ee2ad580faaa1a3a3d7bf21b2f29acac5ed58863ab8e4035d91b39088a",
}
COMPILED_ANCHORS = {
    "dist/agent-tools.read-ZzkirzL1.mjs": ("function createHostWorkspaceEditTool(",),
    "dist/tools-DLW3vi8k.mjs": ("function createEditTool(",),
    "dist/types-DTVBdCzw.mjs": ("Memory index is stale: ${reason}. Search results may be incomplete.",),
    "dist/agent-scope-config-Dm6T00l4.mjs": ("function resolveAgentWorkspaceDir(",),
}
ADDITIONAL_REQUIRED_HOST_ARTIFACTS = tuple(COMPILED_HASHES)

# Named by the fixed source map for this contract, but reachable only through a
# model completion in deep dreaming. It is authenticated, never executed here.
AUTHENTICATED_ONLY_HASHES = {
    "extensions/memory-core/src/dreaming-consolidation.ts":
        "fd6639fac416d17d0dc96464bb4abdfd023e81d65a861a2264fbfdc41b107a8b",
}
AUTHENTICATED_ONLY_ANCHORS = {
    "extensions/memory-core/src/dreaming-consolidation.ts": ("export async function consolidateMemory(",),
}


def prepare_host_update_isolation_bindings(checkout: Path, runtime_root: Path) -> dict:
    """Authenticate the exact update owners without executing any of them."""
    checkout, runtime_root = Path(checkout).absolute(), Path(runtime_root).absolute()
    return {
        "kind": "official-release-host-update-isolation-owners",
        "operation": UPDATE_OPERATION, "referenceCommit": REFERENCE_COMMIT,
        "publicationHostOwners": prepare_host_restart_publication_bindings(checkout, runtime_root),
        "additionalSourceBindings": _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True),
        "additionalCompiledBindings": _owners(runtime_root, COMPILED_HASHES, COMPILED_ANCHORS, committed=False),
        "authenticatedOnlyDeclarations": _owners(checkout, AUTHENTICATED_ONLY_HASHES,
                                                 AUTHENTICATED_ONLY_ANCHORS, committed=True),
        "sourceBuildReproduced": False, "sourceFallbackAllowed": False,
        "sourceExecutionPermitted": False, "covers": [], "acceptancePointsAwarded": 0,
        "requiredLoadedArtifacts": list(ADDITIONAL_REQUIRED_HOST_ARTIFACTS),
        "producerEntrypoints": [{"path": "dist/agent-tools-HIqp3eTk.mjs", "export": "t", "tool": "write"},
                                {"path": "dist/agent-tools-HIqp3eTk.mjs", "export": "t", "tool": "edit"}],
        "writeToolEquivalenceClaimed": False,
        "writeToolNote": "The original coding write/edit tools and the SDK curated-memory tools are declared "
                         "corpus producers. Only resulting source bytes, explicit publication outcomes and later "
                         "memory_search/memory_get results are compared.",
        "faultRealization": {
            "source-hard-link-during-update": "A second hard link to the saved source exists only while the genuine "
                "update tool runs; both engines' real write guards observe the same filesystem state.",
            "index-publication-sidecar-symlink": "Before the update, the path the engine's index publication must "
                "open is a dangling symbolic link (original: <agent db>.reindex-lock.sqlite; SDK: <index>-journal). "
                "It is removed after the first read that follows the failed publication.",
        },
        "consolidateMemoryExecuted": False,
    }
