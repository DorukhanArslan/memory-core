"""Additional whole-apply source/compiled owners, separate from the old literal lane."""
from pathlib import Path
from equivalence.promotion_apply_bindings import prepare_promotion_apply_bindings, _regular_owners
from equivalence.session_admission_runtime_bindings import _owners, _named_link

SOURCE_HASHES = {'extensions/memory-core/src/dreaming-consolidation.ts': 'fd6639fac416d17d0dc96464bb4abdfd023e81d65a861a2264fbfdc41b107a8b',
 'extensions/memory-core/src/dreaming-consolidation-artifacts.ts': '3ab27880336927e05100efe3e320d7909c5cc42cb3b5abae147fc9755a4ef2d0',
 'extensions/memory-core/src/memory-entry-origins.ts': 'd84877d05b1621d554260c23b3d4678eb184ffce9ad7fd0255abee67ac3ad0d7',
 'src/plugin-sdk/memory-core-host-engine-storage.ts': '77459d8b9de13ebc1aa1974313807e9575f35300663e6f6a392a131a794c478a',
 'src/state/openclaw-agent-db.ts': 'f28a4f20493b63d9d3ce88e5811e82733b4989068b400d9219736ddce84b5781',
 'src/state/openclaw-agent-db-readonly.ts': '9346ab682eb7585e20feb7defa2a75ae2f62db2514206d6276ecfc7c64261890'}

COMPILED_HASHES = {'dist/memory-entry-origins-BCQSIB3X.mjs': '35506e30b05eb6ebc688b90688b449d06c2a01ffabb0348c1eaa1b1f9d0fd37d',
 'dist/memory-core-host-engine-storage-Dn-n8hud.mjs': '9d62579b77fd6dd89cfa6047d355ab1d9d8b2ec38bcfe6b2528b7b00c3881186',
 'dist/openclaw-agent-db-DRy3ui_B.mjs': 'f851c6fa5b6a766e6afff83684ad02883c45589532bd8ac1e790f20bbb3b0d93',
 'dist/openclaw-agent-db-readonly-WugFtIYV.mjs': '905c12dfe4ab5732d2ec46884422b03433587ddd6e859cee0e51da01a4e87480'}

SOURCE_ANCHORS = {
    "extensions/memory-core/src/dreaming-consolidation.ts": ("export async function consolidateMemory(",),
    "extensions/memory-core/src/dreaming-consolidation-artifacts.ts": ("export async function storeMemoryPreimage(",),
    "extensions/memory-core/src/memory-entry-origins.ts": ("export function reserveMemoryEntryOrigins(",),
    "src/plugin-sdk/memory-core-host-engine-storage.ts": ("  ensureMemoryEntryOriginsSchema,",),
    "src/state/openclaw-agent-db.ts": ("export function openOpenClawAgentDatabase(",),
    "src/state/openclaw-agent-db-readonly.ts": ("export function withOpenClawAgentDatabaseReadOnly<T>(",),
}
COMPILED_ANCHORS = {
    "dist/memory-entry-origins-BCQSIB3X.mjs": ("function reserveMemoryEntryOrigins(",),
    "dist/memory-core-host-engine-storage-Dn-n8hud.mjs": ("function ensureMemoryEntryOriginsSchema(",),
    "dist/openclaw-agent-db-DRy3ui_B.mjs": ("function openOpenClawAgentDatabase(",),
    "dist/openclaw-agent-db-readonly-WugFtIYV.mjs": ("function withOpenClawAgentDatabaseReadOnly(",),
}


def prepare_family_bindings(checkout: Path, runtime_root: Path):
    original = prepare_promotion_apply_bindings(checkout, runtime_root)
    _regular_owners(checkout, SOURCE_HASHES)
    _regular_owners(runtime_root, COMPILED_HASHES)
    sources, source_evidence = _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
    _, compiled_evidence = _owners(runtime_root, COMPILED_HASHES, COMPILED_ANCHORS, committed=False)
    prefix = "extensions/memory-core/src/"
    links = [
        _named_link(sources, prefix + "memory-entry-origins.ts", "openclaw/plugin-sdk/sqlite-runtime",
                    ("openOpenClawAgentDatabase", "withOpenClawAgentDatabaseReadOnly", "runSqliteImmediateTransactionSync"), kind="import"),
        _named_link(sources, prefix + "dreaming-consolidation-artifacts.ts", "./dreaming-state.js",
                    ("readMemoryCoreWorkspaceEntries", "writeMemoryCoreWorkspaceEntries", "DREAMING_MEMORY_BACKUP_NAMESPACE"), kind="import"),
    ]
    store = (runtime_root / "dist/short-term-promotion-store-B6T388Bo.mjs").read_text()
    for alias in ("normalizeShortTermRecallStore as k", "readShortTermStore as i", "enforceShortTermRecallStoreRetention as _"):
        if store.count(alias) != 1:
            raise ValueError("The original physical/read/normalization aliases changed")
    writer = (runtime_root / "dist/memory-artifact-provenance-DhnyWiV1.mjs").read_text()
    if writer.count("recordMemoryArtifactWriteProvenance as a") != 1:
        raise ValueError("The original provenance writer alias changed")
    return {"kind": "official-release-promotion-apply-family-owners", "operation": "promotion-apply-family-runtime",
            "referenceCommit": original["referenceCommit"], "sourceBuildReproduced": False,
            "originalOwnerBindings": original, "additionalSourceBindings": source_evidence,
            "additionalCompiledBindings": compiled_evidence, "additionalSourceImportLinks": links,
            "normalizationAliases": {"readPhysical": "i", "normalize": "k", "retain": "_", "read": "a"},
            "provenanceWriteAlias": "a", "covers": []}
