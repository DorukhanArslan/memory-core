"""Authenticate original memory-search owners and separate official release exports.

Loaded declarations are provenance, not proof that every visibility/deadline or
host integration path executed. Each comparison retains its genuine envelope.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from equivalence.reference_bindings import ReferenceBindingError, _git
from equivalence.reuse_bindings import ReuseBindingError, _named

REFERENCE_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"
SOURCE_HASHES = {'extensions/memory-core/src/tools.ts': 'bc3fc7cbfa743fcfe57200a0c66ee6ca53191e928a20f4195c29ca0122980e66',
 'extensions/memory-core/src/memory-tool-contract.ts': '6d1649776d4a73729b36facd8ef5cdc6d77e443b719c736ecedd9c9ea6f48191',
 'extensions/memory-core/src/tools.shared.ts': 'f111a96bd8f19e2e7b295133531a1ac240ae9938ef2c0c4cd477a8b914b0d9be',
 'extensions/memory-core/src/tools.citations.ts': '10ac036c279a1d18ea20e0731b3aee126aebd89f3d3a4fff09b965db5ef80669',
 'extensions/memory-core/src/memory-search-tool-query.ts': '48168070d098e7540f82e83a2ab5e12cda338af8bded9d1a0b65e22514c93bdb',
 'extensions/memory-core/src/memory-corpus.ts': 'f37d07ba508c47256dfa5b60f71caad06569ca8e3e195bbfc2363c7cc098bca3',
 'extensions/memory-core/src/session-search-visibility.ts': '81027cda9baa0a97809f4ecaa1f39425c1e9029d048830d2c0f1ed5960e98e41',
 'src/agents/tools/tool-results.ts': '36a3500e0cc46b1615daf70636c651f7f35ff6c6ed5273a2c63a3e9182bc14f7',
 'src/agents/tools/common.ts': '3140b2be2998afbd24d2ab68e1d206e86c7dd8ed8147a2b4ff77304419f7c7dc',
 'extensions/memory-core/src/memory/manager-runtime.ts': '0aa26fecd02844613b2e671b00e417ade5f0354df30e36afb9dcc2b559178c6b',
 'extensions/memory-core/src/memory/manager.ts': 'c4995b1e83db3e9aa4fbc6bdcffe4ddb36d9a5769396a0b1fd4ee2934c5c8173',
 'src/plugins/memory-state.ts': 'b334c9eed9bbb43c54560515a62511b6ff5ea77a044c584d0ea029670ad37229'}
SOURCE_ANCHORS = {'extensions/memory-core/src/tools.ts': ('export function createMemorySearchTool(options: '
                                       'MemoryToolOptions) {',
                                         'function readCorpusParam<T extends string>('),
 'extensions/memory-core/src/memory-tool-contract.ts': ('export const MEMORY_SEARCH_TOOL_CONTRACT = {',
                                                        'export function resolveMemoryToolContext(options: '
                                                        'MemoryToolOptions) {'),
 'extensions/memory-core/src/tools.shared.ts': ('export function buildMemorySearchUnavailableResult(',
                                                'export function createMemoryTool(params: {'),
 'extensions/memory-core/src/tools.citations.ts': ('export function buildMemorySearchPresentation(',
                                                   'export function shouldIncludeCitations(params: {'),
 'extensions/memory-core/src/memory-search-tool-query.ts': ('export async function '
                                                            'executeMemorySearchToolQuery(params: {',),
 'extensions/memory-core/src/memory-corpus.ts': ('export function composeMemoryCorpusMetadata(',
                                                 'export async function '
                                                 'searchMemoryCorpusSupplements(params: {'),
 'extensions/memory-core/src/session-search-visibility.ts': ('export async function '
                                                             'filterMemorySearchHitsBySessionVisibility(params: '
                                                             '{',),
 'src/agents/tools/tool-results.ts': ('export function jsonResult<TDetails>(payload: TDetails): '
                                      'AgentToolResult<TDetails> {',),
 'src/agents/tools/common.ts': ('export function readPositiveIntegerParam(',
                                'export function readFiniteNumberParam('),
 'extensions/memory-core/src/memory/manager-runtime.ts': ('export { MemoryIndexManager };',),
 'extensions/memory-core/src/memory/manager.ts': ('export class MemoryIndexManager extends '
                                                  'MemorySearchOrchestration implements MemorySearchManager '
                                                  '{',),
 'src/plugins/memory-state.ts': ('export function registerMemoryCorpusSupplement(',)}
COMPILED_HASHES = {'dist/tools-DotaQGXh.mjs': 'c31b10a5ed25a1e02e5e7ac5be034b78906558c39350fd72be3f4c9edecc766e',
 'dist/memory-tool-contract-DOz26L8b.mjs': 'caa1cf11748ff19c561d94a321ffff564fdfbd357bc8954e09f50ed6844bb063',
 'dist/common-CnSoEQyp.mjs': '7528a47a2ba0ad07e678c6efdd308b858bc2587abf85bfc3f1a6c20e2a50cf57',
 'dist/tool-results-BCM3fdVS.mjs': 'ac69dc5bf2dac8d90d319e1fa58ee8684101987f8522ae80a5b0ba5de49239a1',
 'dist/types-DTVBdCzw.mjs': '14598f9947a85bf691d345dc54c32899c8931afc580e45f143918afe8b54db50',
 'dist/session-search-visibility-BSOBplEm.mjs': 'd7ab86815684e09c631ddc06062dbf62a6063be42c08d595b9f2050d24f63675',
 'dist/memory-state-BmtUbXjH.mjs': 'ed71931d904089353576180357a71c99a6a976b6e300b381b0be943298c9bc4f',
 'dist/extensions/memory-core/manager-runtime.js': '6ae8f02e229a5422d88dde59a6c070cce03e1ac9ffe5fa87172db8512f0eea0e'}
COMPILED_ANCHORS = {'dist/tools-DotaQGXh.mjs': ('function createMemorySearchTool(options) {',
                             'function executeMemorySearchToolQuery(params) {',
                             'function composeMemoryCorpusMetadata(attempts, extraWarnings = []) {',
                             'export { createMemoryGetTool, createMemorySearchTool, testing };'),
 'dist/memory-tool-contract-DOz26L8b.mjs': ('const MEMORY_SEARCH_TOOL_CONTRACT = {',
                                            'function resolveMemoryToolContext(options) {',
                                            'export { resolveMemoryToolContext as i, '
                                            'MEMORY_SEARCH_TOOL_CONTRACT as n, buildMemoryPromptSection as '
                                            'r, MEMORY_GET_TOOL_CONTRACT as t };'),
 'dist/common-CnSoEQyp.mjs': ('function readPositiveIntegerParam(params, key, options = {}) {',
                              'function readFiniteNumberParam(params, key, options = {}) {'),
 'dist/tool-results-BCM3fdVS.mjs': ('function jsonResult(payload) {',),
 'dist/types-DTVBdCzw.mjs': ('function resolveMemorySearchStaleness(status, agentId) {',),
 'dist/session-search-visibility-BSOBplEm.mjs': ('async function '
                                                 'filterMemorySearchHitsBySessionVisibility(params) {',),
 'dist/memory-state-BmtUbXjH.mjs': ('function registerMemoryCorpusSupplement(requestedPluginId, supplement) '
                                    '{',
                                    'function listMemoryCorpusSupplements() {'),
 'dist/extensions/memory-core/manager-runtime.js': ('var MemoryIndexManager = class MemoryIndexManager '
                                                    'extends MemorySearchOrchestration {',
                                                    'export { MemoryIndexManager, '
                                                    'closeAllMemoryIndexManagers, '
                                                    'closeMemoryIndexManagersForAgent };')}

HELPER_ARTIFACTS = (
    "dist/tools-DotaQGXh.mjs", "dist/memory-tool-contract-DOz26L8b.mjs",
    "dist/common-CnSoEQyp.mjs", "dist/tool-results-BCM3fdVS.mjs",
)
TOOL_ARTIFACTS = tuple(COMPILED_HASHES)
REQUIRED_LOADED_ARTIFACTS_BY_PROFILE = {
    "search-contract-helper-runtime": list(HELPER_ARTIFACTS),
    "search-contract-runtime": list(TOOL_ARTIFACTS),
}


class SearchContractRuntimeBindingError(ValueError):
    """The reviewed native tool declarations or published artifacts changed."""


def _owners(root: Path, hashes: dict[str, str], anchors: dict[str, tuple[str, ...]],
            *, committed: bool) -> tuple[dict[str, str], list[dict]]:
    sources = {}
    evidence = []
    for relative, digest in hashes.items():
        file = root / relative
        if (any(part.is_symlink() for part in (file, *file.parents) if part != root)
                or not file.resolve().is_relative_to(root)):
            raise SearchContractRuntimeBindingError("A search-tool owner escaped its reviewed tree.")
        raw = file.read_bytes()
        if (hashlib.sha256(raw).hexdigest() != digest or committed
                and hashlib.sha256(_git(root, "show", f"HEAD:{relative}")).hexdigest() != digest):
            raise SearchContractRuntimeBindingError("A search-tool owner differs from its reviewed bytes.")
        source = raw.decode("utf-8")
        sources[relative] = source
        locations = []
        for anchor in anchors[relative]:
            if source.count(anchor) != 1:
                raise SearchContractRuntimeBindingError("A search-tool owner has no unique reviewed linkage.")
            locations.append({"anchor": anchor.rstrip("\n"),
                              "line": source[:source.index(anchor)].count("\n") + 1})
        evidence.append({"path": relative, "sha256": digest, "anchors": locations})
    return sources, evidence


def prepare_search_contract_runtime_bindings(checkout: Path, runtime_root: Path) -> dict:
    """Authenticate unchanged source declarations and separately published exports."""
    checkout = Path(checkout).resolve()
    runtime_root = Path(runtime_root).resolve()
    try:
        if (_git(checkout, "rev-parse", "HEAD").decode().strip() != REFERENCE_COMMIT
                or Path(_git(checkout, "rev-parse", "--show-toplevel").decode().strip()).resolve() != checkout
                or _git(checkout, "status", "--porcelain", "--untracked-files=no").strip()):
            raise SearchContractRuntimeBindingError("Search-tool evidence requires the unchanged pinned checkout.")
        sources, source_evidence = _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
        _, compiled_evidence = _owners(runtime_root, COMPILED_HASHES, COMPILED_ANCHORS, committed=False)
        tool = "extensions/memory-core/src/tools.ts"
        chain = [
            _named(sources, tool, "./memory-tool-contract.js",
                   ("MEMORY_GET_TOOL_CONTRACT", "MEMORY_SEARCH_TOOL_CONTRACT"), kind="import", exact=True),
            _named(sources, tool, "./tools.citations.js",
                   ("buildMemorySearchPresentation", "resolveMemoryCitationsMode", "shouldIncludeCitations"),
                   kind="import", exact=True),
            _named(sources, tool, "./tools.shared.js",
                   ("buildMemorySearchUnavailableResult", "createMemoryTool",
                    "getMemoryManagerContextWithPurpose", "loadMemoryToolRuntime"), kind="import", exact=True),
            _named(sources, "extensions/memory-core/src/memory/manager-runtime.ts", "./manager.js",
                   ("getMemoryIndexManagerRegistry", "MemoryIndexManager"), kind="import", exact=True),
        ]
    except (OSError, UnicodeError, ReferenceBindingError, ReuseBindingError) as error:
        raise SearchContractRuntimeBindingError("Search-tool runtime provenance could not be verified.") from error
    return {
        "kind": "official-release-memory-search-tool-owner", "referenceCommit": REFERENCE_COMMIT,
        "sourceBuildReproduced": False, "constructorSkipped": False,
        "fullManagerExecutionVerified": False, "fullHostOrchestrationVerified": False,
        "sourceBindings": source_evidence, "sourceImportLinks": chain,
        "compiledBindings": compiled_evidence,
        "entrypoints": {
            "tool": {"path": "dist/tools-DotaQGXh.mjs", "export": "createMemorySearchTool"},
            "contract": {"path": "dist/memory-tool-contract-DOz26L8b.mjs", "export": "n",
                         "originalBinding": "MEMORY_SEARCH_TOOL_CONTRACT"},
            "manager": {"path": "dist/extensions/memory-core/manager-runtime.js",
                        "export": "MemoryIndexManager", "methods": ["get", "sync", "search", "close"]},
        },
        "requiredLoadedArtifactsByProfile": REQUIRED_LOADED_ARTIFACTS_BY_PROFILE,
        "workerRequiredByProfile": {"search-contract-helper-runtime": False,
                                    "search-contract-runtime": True},
        "fixtureBoundary": "Whole-tool cases use the actual public factory and execute callback, "
                           "a real provider-none manager and a paired main-thread Date.now input. "
                           "Registered wiki callbacks are provider fixtures. The native full JSON "
                           "envelope, debug fields, warnings and ordered rows are retained. Helper "
                           "cases execute genuine declarations without claiming worker dispatch. "
                           "Deadline expiry and complete session visibility remain separate contracts.",
    }
