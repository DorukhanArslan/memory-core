"""Pinned release writers/readers reached during SQLite index recovery."""
from pathlib import Path

from equivalence import dream_light_bindings as dreaming
from equivalence import embedding_cache_lifecycle_bindings as cache
from equivalence import entry_provenance_bindings as entry
from equivalence import importance_project_runtime_bindings as manager
from equivalence.reference_bindings import _git
from equivalence.session_admission_runtime_bindings import _owners

MANAGER = 'dist/extensions/memory-core/manager-runtime.js'
METHODS = {'get': '36301b41bb14203a43d7d9833eb9947556c55cee40b7b06aebba31df7558f703',
           'markMemoryWatchDirty': '69294031f437532b482c185e4cc0907ed2cc03e5102390c39cb06930fe9c384d',
           'sync': 'a37c73c22b95c1d7d8fda1716ba76443e2977082f4e34f936e4ccf89da5c8ba6',
           'close': 'e1cc04bbdab1cdedc21e8d856698eb61a6e835d3b375c6bbbefc4716b5f564be',
           'status': 'bd478365656d6a3f88ab78f5b7ef36c217bbb356a5566c4c78ffa476d8de5fe7'}
MODULES = {MANAGER: (manager.COMPILED_HASHES[MANAGER], ('\tasync sync(params) {', '\tmarkMemoryWatchDirty() {'))}
for name in ('dist/manager-index-preparation-wXpJtJiU.mjs', 'dist/manager-source-index-kernel-D-njga00.mjs', 'dist/plugin-sdk/memory-core-host-engine-storage.js'):
    MODULES[name] = (entry.COMPILED_HASHES[name], entry.COMPILED_ANCHORS[name])
for name in ('dist/dreaming-state-VYUvbU-n.mjs','dist/plugin-state-store-BPUaLoVD.mjs','dist/plugin-state-worker-client-7ByaGIDy.mjs','dist/infra/sqlite-store.worker.js','dist/state/openclaw-state.worker.js'):
    MODULES[name] = dreaming.COMPILED[name]
SOURCES = {}
for module, names in ((manager, ('manager.ts',)), (cache, ('manager-sync-base.ts','manager-embedding-ops.ts','manager-sync-ops.ts')), (entry, ('manager-index-preparation.ts','manager-chunk-writer.ts','manager-source-index-kernel.ts'))):
    for name in names:
        relative = 'extensions/memory-core/src/memory/' + name
        SOURCES[relative] = (module.SOURCE_HASHES[relative], module.SOURCE_ANCHORS[relative])


def prepare_index_repair_bindings(checkout, runtime_root):
    checkout, runtime_root = Path(checkout).resolve(), Path(runtime_root).resolve()
    if _git(checkout, 'rev-parse', 'HEAD').decode().strip() != manager.REFERENCE_COMMIT:
        raise ValueError('Unexpected original index repair source revision')
    def verify(root, owners, committed):
        return _owners(root, {p: info[0] for p, info in owners.items()}, {p: info[1] for p, info in owners.items()}, committed=committed)[1]
    return {'kind': 'official-index-repair-manager', 'referenceCommit': manager.REFERENCE_COMMIT,
            'sourceBindings': verify(checkout, SOURCES, True), 'compiledBindings': verify(runtime_root, MODULES, False),
            'entryPoint': {'artifact': MANAGER, 'export': 'MemoryIndexManager.get', 'methods': METHODS},
            'sourceBuildReproduced': False, 'sourceFallbackAllowed': False}
