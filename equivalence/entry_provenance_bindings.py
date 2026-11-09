"""Pinned entry preparation/publication owners, without acceptance registration."""
from pathlib import Path

from equivalence.reference_bindings import _git
from equivalence.importance_project_runtime_bindings import prepare_importance_project_runtime_bindings
from equivalence.session_admission_runtime_bindings import (
    _named_link, _owners, prepare_session_admission_runtime_bindings,
)


REFERENCE_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"
SOURCE_HASHES = {'extensions/memory-core/src/memory/manager-index-preparation.ts': '208e5c367e6f5dd79f1837050404fe67a9f05ac8fa5e5ad1860c12f4a259e041',
 'extensions/memory-core/src/memory/manager-source-index-kernel.ts': 'b0bf466a54ee67705f5b7327a31c0013e9ee44a57117181ca5860c5ef90e30b5',
 'extensions/memory-core/src/memory/manager-chunk-writer.ts': '623dc154a82424dbafac73dd1110c5031bb62bde0b54ad275e264fa38a53db9a',
 'extensions/memory-core/src/memory/manager-reset-chunk-boundary.ts': 'e758a1f18bf953d71b914dee0121c067803147ea9fdb3703bde3296a1181102f',
 'extensions/memory-core/src/memory/manager-source-sync-ops.ts': 'bc6a8fba716ffe3bd6cb130b3e415a057982b84a494ded95429acf7d7721e4b1',
 'extensions/memory-core/src/memory/memory-path-provenance.ts': '11e0adfcf2069d535b9fc3b9b625a5b65fd64dda4b97e4fa2ba9bcf5fc24a0af',
 'packages/memory-host-sdk/src/host/markdown-chunks.ts': 'caae77122117210dba507956489f1e20f4015a31113e017e9e0b57f72ad78f1b',
 'packages/memory-host-sdk/src/host/embedding-input-limits.ts': '2f0185b461c16f51146deb9a1e8e0687e8add417793c47d0fe1b9b34c3da9a13',
 'packages/memory-host-sdk/src/host/embedding-model-limits.ts': '8c419d411c64189d9217c2b90d7554d5ff404c03655f8224603f958366edd773',
 'packages/memory-host-sdk/src/host/embedding-chunk-limits.ts': '0a5a95868e75f9855bb85493fa35f4df10154a1ed536a6d1ed49cfec9648d14b',
 'packages/memory-host-sdk/src/host/embedding-inputs.ts': '7e2def96d2b619c5beaf023dbbdfadf91473408410785c73eb65feabdb5b436b',
 'packages/memory-host-sdk/src/host/curated-annotations.ts': 'c4bd75fe3476f54508b42623e1f09190816f49e319703375865b9564fe4e7f5d',
 'packages/memory-host-sdk/src/host/hash.ts': 'face88c71f4d752c24052ab299771ddf55c1c54d76ed2ebac8618a7812818683',
 'packages/normalization-core/src/utf16-slice.ts': '12fd3212b08522a1523263c92f654151ad01605ee48a0ff58a1256889fb7cb5f',
 'src/plugin-sdk/memory-core-host-engine-indexing.ts': 'd539b55f81454443f3b3589e1711c04787941a18782c84c0b3422425be9de472'}
SOURCE_ANCHORS = {'extensions/memory-core/src/memory/manager-index-preparation.ts': ('export function '
                                                                    'prepareMemoryIndexChunks({',
                                                                    'export function '
                                                                    'resolveChunkProvenance('),
 'extensions/memory-core/src/memory/manager-source-index-kernel.ts': ('export class MemorySourceIndexKernel '
                                                                      '{',),
 'extensions/memory-core/src/memory/manager-chunk-writer.ts': ('export function createMemoryChunkWriter(',),
 'extensions/memory-core/src/memory/manager-reset-chunk-boundary.ts': ('export function '
                                                                       'chunkSessionContentAtResetBoundary(',),
 'extensions/memory-core/src/memory/manager-source-sync-ops.ts': ('export abstract class '
                                                                  'MemoryManagerSourceSyncOps extends '
                                                                  'MemoryManagerSessionSyncOps {',),
 'extensions/memory-core/src/memory/memory-path-provenance.ts': ('export async function '
                                                                 'resolveMemoryPathClassification(',),
 'packages/memory-host-sdk/src/host/markdown-chunks.ts': ('export function chunkMarkdown(',),
 'packages/memory-host-sdk/src/host/embedding-input-limits.ts': ('export function '
                                                                 'splitTextToUtf8ByteLimit(',),
 'packages/memory-host-sdk/src/host/embedding-model-limits.ts': ('export function '
                                                                 'resolveEmbeddingMaxInputTokens(',),
 'packages/memory-host-sdk/src/host/embedding-chunk-limits.ts': ('export function '
                                                                 'enforceEmbeddingMaxInputTokens(',),
 'packages/memory-host-sdk/src/host/embedding-inputs.ts': ('export function buildTextEmbeddingInput(',),
 'packages/memory-host-sdk/src/host/curated-annotations.ts': ('export function '
                                                              'extractCuratedEntryRecallMetadata(',),
 'packages/memory-host-sdk/src/host/hash.ts': ('export function hashText(',),
 'packages/normalization-core/src/utf16-slice.ts': ('export function avoidTrailingHighSurrogateBreak(',),
 'src/plugin-sdk/memory-core-host-engine-indexing.ts': ('export { enforceEmbeddingMaxInputTokens }',)}
COMPILED_HASHES = {'dist/manager-index-preparation-wXpJtJiU.mjs': '6f9e0930cb49dfe7ba14ea851dde17a56ebebe66e3dabdab525854f90f179867',
 'dist/manager-source-index-kernel-D-njga00.mjs': '762c8cecb4b1eae8ea90d96eb6ed2759f07fd970c9ef4b12344f5e14ef0745fc',
 'dist/embedding-chunk-limits-BDAmib6Y.mjs': 'f3029933eb5b4f969615e8ad85b1815c8ac1ece29d6a8ce137c72fdf5b29dd1d',
 'dist/embedding-inputs-pKTJXw8f.mjs': 'f307200dbdf7c16cfd07cf07d603247189a7031ccbb681a8dd2d2c4e3aa377b4',
 'dist/markdown-chunks-vUp6Qqqw.mjs': '5e5e5486f8b3dd4eccbed0232c92783ca01324a84318c73ec36d1d733190ace3',
 'dist/curated-annotations-DM9mz8Th.mjs': '8c65d576ee392eba56ef6ce89a1b49ac5f9b407b7caf731e40480a1f259b7da0',
 'dist/hash-CAMhNIP1.mjs': '579f6261976a154cace3a4aa3b3aa638fccb1c0d73f2a42a96dec3694e781dc8'}
COMPILED_ANCHORS = {'dist/manager-index-preparation-wXpJtJiU.mjs': ('function prepareMemoryIndexChunks(',
                                                 'export { resolveChunkProvenance as n, '
                                                 'prepareMemoryIndexChunks as t };'),
 'dist/manager-source-index-kernel-D-njga00.mjs': ('function createMemoryChunkWriter(',
                                                   'export { readMemorySourceHash as n, '
                                                   'MemorySourceIndexKernel as t };'),
 'dist/embedding-chunk-limits-BDAmib6Y.mjs': ('function enforceEmbeddingMaxInputTokens(',),
 'dist/embedding-inputs-pKTJXw8f.mjs': ('function splitTextToUtf8ByteLimit(',),
 'dist/markdown-chunks-vUp6Qqqw.mjs': ('function chunkMarkdown(',),
 'dist/curated-annotations-DM9mz8Th.mjs': ('function extractCuratedEntryRecallMetadata(',),
 'dist/hash-CAMhNIP1.mjs': ('function hashText(',)}


def prepare_entry_provenance_bindings(checkout: Path, runtime_root: Path) -> dict:
    if _git(checkout, "rev-parse", "HEAD").decode().strip() != REFERENCE_COMMIT:
        raise ValueError("Entry provenance requires the exact unchanged pinned source commit")
    sources, source_evidence = _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
    _, compiled_evidence = _owners(runtime_root, COMPILED_HASHES, COMPILED_ANCHORS, committed=False)
    links = [
        ("extensions/memory-core/src/memory/manager-index-preparation.ts", "openclaw/plugin-sdk/memory-core-host-engine-indexing",
         ("chunkMarkdown", "extractCuratedEntryRecallMetadata", "enforceEmbeddingMaxInputTokens", "hashText", "remapChunkLines", "stripMemoryAnnotationCarriers"), "import"),
        ("extensions/memory-core/src/memory/manager-index-preparation.ts", "./manager-reset-chunk-boundary.js", ("chunkSessionContentAtResetBoundary",), "import"),
        ("extensions/memory-core/src/memory/manager-source-index-kernel.ts", "./manager-chunk-writer.js", ("createMemoryChunkWriter",), "import"),
        ("src/plugin-sdk/memory-core-host-engine-indexing.ts", "../../packages/memory-host-sdk/src/host/markdown-chunks.js", ("chunkMarkdown", "remapChunkLines"), "export"),
        ("src/plugin-sdk/memory-core-host-engine-indexing.ts", "../../packages/memory-host-sdk/src/host/embedding-chunk-limits.js", ("enforceEmbeddingMaxInputTokens",), "export"),
        ("src/plugin-sdk/memory-core-host-engine-indexing.ts", "../../packages/memory-host-sdk/src/host/curated-annotations.js", ("extractCuratedEntryRecallMetadata", "stripMemoryAnnotationCarriers"), "export"),
        ("packages/memory-host-sdk/src/host/embedding-chunk-limits.ts", "./embedding-input-limits.js", ("estimateUtf8Bytes", "splitTextToUtf8ByteLimit"), "import"),
        ("packages/memory-host-sdk/src/host/embedding-chunk-limits.ts", "./embedding-model-limits.js", ("resolveEmbeddingMaxInputTokens",), "import"),
        ("packages/memory-host-sdk/src/host/embedding-input-limits.ts", "@openclaw/normalization-core/utf16-slice", ("avoidTrailingHighSurrogateBreak",), "import"),
    ]
    return {"kind": "official-release-entry-provenance-owners", "referenceCommit": REFERENCE_COMMIT,
            "sourceBuildReproduced": False, "sourceFallbackAllowed": False, "covers": [],
            "sourceBindings": source_evidence, "compiledBindings": compiled_evidence,
            "sourceImportLinks": [_named_link(sources, module, specifier, names, kind=kind)
                                  for module, specifier, names, kind in links],
            "preparedEntrypoint": {"path": "dist/manager-index-preparation-wXpJtJiU.mjs", "export": "t"},
            "publicationEntrypoint": {"path": "dist/manager-source-index-kernel-D-njga00.mjs", "export": "t"},
            "runtimeAuthorities": {
                "publicManager": prepare_importance_project_runtime_bindings(checkout, runtime_root),
                "persistedSessions": prepare_session_admission_runtime_bindings(checkout, runtime_root),
            },
            "fullManagerOrHostEquivalenceClaimed": False}
