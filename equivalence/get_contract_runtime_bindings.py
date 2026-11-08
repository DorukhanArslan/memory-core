"""Pin genuine memory_get owners and separately authenticated release exports.

The read boundary executes secure file IO without constructing an index manager.
Declaration authentication does not imply unrelated storage/deadline equivalence.
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
 'extensions/memory-core/src/tools.runtime.ts': 'db0cca56eef6ad7b7cd6d56429d42529442a541ca0597f87be0603583e730fc5',
 'extensions/memory-core/src/memory-read-tool.ts': '318bdf62b8503176b55eda4c6431b91e6b330cbeb3178f390f0623e87f621c37',
 'extensions/memory-core/src/memory-corpus.ts': 'f37d07ba508c47256dfa5b60f71caad06569ca8e3e195bbfc2363c7cc098bca3',
 'packages/memory-host-sdk/src/host/read-file.ts': '340bb4aff7a88ee80591e5d0bc4f959367e7d2b6d7f06017d599f0342cb29dd2',
 'packages/memory-host-sdk/src/host/read-file-shared.ts': 'cc574d3135a6849b6a62ed640a5e502eb23ca066071ce152d704ce861f2f8b5d',
 'packages/memory-host-sdk/src/runtime-files.ts': '1245f01809e91317f28aa6966cbdd7baf34d1d46b858b0dbfd765be29bfb5274',
 'src/plugin-sdk/memory-core-host-runtime-files.ts': '286e82455cd53f203094ed3ef196c622bd98b73f34a8b25a8035e402e5178905',
 'src/agents/tools/tool-results.ts': '36a3500e0cc46b1615daf70636c651f7f35ff6c6ed5273a2c63a3e9182bc14f7',
 'src/agents/tools/common.ts': '3140b2be2998afbd24d2ab68e1d206e86c7dd8ed8147a2b4ff77304419f7c7dc',
 'src/plugins/memory-state.ts': 'b334c9eed9bbb43c54560515a62511b6ff5ea77a044c584d0ea029670ad37229'}
SOURCE_ANCHORS = {'extensions/memory-core/src/tools.ts': ('export function createMemoryGetTool(options: MemoryToolOptions) '
                                         '{',),
 'extensions/memory-core/src/memory-tool-contract.ts': ('export const MEMORY_GET_TOOL_CONTRACT = {',
                                                        'export function resolveMemoryToolContext(options: '
                                                        'MemoryToolOptions) {'),
 'extensions/memory-core/src/tools.shared.ts': ('export function createMemoryTool(params: {',),
 'extensions/memory-core/src/tools.runtime.ts': ('  readAgentMemoryFile,',),
 'extensions/memory-core/src/memory-read-tool.ts': ('export async function executeMemoryReadResult(',
                                                    'export async function '
                                                    'executeWikiMemoryReadResult(params: '
                                                    'MemoryReadRequest) {'),
 'extensions/memory-core/src/memory-corpus.ts': ('export function composeMemoryCorpusMetadata(',
                                                 'export async function '
                                                 'readMemoryCorpusSupplements(params: {'),
 'packages/memory-host-sdk/src/host/read-file.ts': ('export async function readMemoryFile(params: {',
                                                    'export async function readAgentMemoryFile(params: {'),
 'packages/memory-host-sdk/src/host/read-file-shared.ts': ('export function buildMemoryReadResult(params: '
                                                           '{',
                                                           'export function '
                                                           'buildMemoryReadResultFromSlice(params: {'),
 'packages/memory-host-sdk/src/runtime-files.ts': ('export { readAgentMemoryFile } from '
                                                   '"./host/read-file.js";',),
 'src/plugin-sdk/memory-core-host-runtime-files.ts': ('  readAgentMemoryFile,',),
 'src/agents/tools/tool-results.ts': ('export function jsonResult<TDetails>(payload: TDetails): '
                                      'AgentToolResult<TDetails> {',),
 'src/agents/tools/common.ts': ('export function readPositiveIntegerParam(',),
 'src/plugins/memory-state.ts': ('export function registerMemoryCorpusSupplement(',)}
COMPILED_HASHES = {'dist/tools-DotaQGXh.mjs': 'c31b10a5ed25a1e02e5e7ac5be034b78906558c39350fd72be3f4c9edecc766e',
 'dist/memory-tool-contract-DOz26L8b.mjs': 'caa1cf11748ff19c561d94a321ffff564fdfbd357bc8954e09f50ed6844bb063',
 'dist/common-CnSoEQyp.mjs': '7528a47a2ba0ad07e678c6efdd308b858bc2587abf85bfc3f1a6c20e2a50cf57',
 'dist/tool-results-BCM3fdVS.mjs': 'ac69dc5bf2dac8d90d319e1fa58ee8684101987f8522ae80a5b0ba5de49239a1',
 'dist/read-file-CH8NQLbp.mjs': 'eec2ac48d772f0d2303c65bf3ea3a0866c42f864bf8e9c75f7307643044a4687',
 'dist/memory-state-BmtUbXjH.mjs': 'ed71931d904089353576180357a71c99a6a976b6e300b381b0be943298c9bc4f',
 'dist/tools.runtime.js': '453b5423b3b47e05cf06608162ae184186d332c2042792bde427580cc73d5661',
 'dist/tools.runtime-m4sffzql.mjs': '0e3cca44ae9922d28e02779723a91f99889e6322a77daa4d9700bdcb4f816983'}
COMPILED_ANCHORS = {'dist/tools-DotaQGXh.mjs': ('function createMemoryGetTool(options) {',
                             'async function executeMemoryReadResult(params) {',
                             'async function executeWikiMemoryReadResult(params) {',
                             'export { createMemoryGetTool, createMemorySearchTool, testing };'),
 'dist/memory-tool-contract-DOz26L8b.mjs': ('const MEMORY_GET_TOOL_CONTRACT = {',
                                            'function resolveMemoryToolContext(options) {'),
 'dist/common-CnSoEQyp.mjs': ('function readPositiveIntegerParam(params, key, options = {}) {',),
 'dist/tool-results-BCM3fdVS.mjs': ('function jsonResult(payload) {',),
 'dist/read-file-CH8NQLbp.mjs': ('async function readMemoryFile(params) {',
                                 'async function readAgentMemoryFile(params) {',
                                 'function buildMemoryReadResult(params) {',
                                 'function buildMemoryReadResultFromSlice(params) {'),
 'dist/memory-state-BmtUbXjH.mjs': ('function registerMemoryCorpusSupplement(requestedPluginId, '
                                    'supplement) {',
                                    'function listMemoryCorpusSupplements() {'),
 'dist/tools.runtime.js': ('export * from "./tools.runtime-m4sffzql.mjs";',),
 'dist/tools.runtime-m4sffzql.mjs': ('import { t as readAgentMemoryFile } from "./read-file-CH8NQLbp.mjs";',
                                     'export { getMemorySearchManager, readAgentMemoryFile, '
                                     'resolveMemoryBackendConfig };')}

DEFINITION_ARTIFACTS = tuple(list(COMPILED_HASHES)[:4])
TOOL_ARTIFACTS = tuple(list(COMPILED_HASHES)[:6])
READ_RUNTIME_ARTIFACTS = ("dist/tools.runtime.js", "dist/tools.runtime-m4sffzql.mjs")
REQUIRED_LOADED_ARTIFACTS_BY_KIND = {
    "definition": list(DEFINITION_ARTIFACTS), "tool": list(TOOL_ARTIFACTS),
}
REQUIRED_LOADED_ARTIFACTS_BY_PROFILE = {
    "get-contract-helper-runtime": list(DEFINITION_ARTIFACTS),
    "get-contract-runtime": list(TOOL_ARTIFACTS),
}


class GetContractRuntimeBindingError(ValueError):
    """The reviewed read tool owners or separate official artifact changed."""


def _owners(root: Path, hashes: dict[str, str], anchors: dict[str, tuple[str, ...]],
            *, committed: bool) -> tuple[dict[str, str], list[dict]]:
    sources = {}
    evidence = []
    for relative, digest in hashes.items():
        file = root / relative
        if (any(part.is_symlink() for part in (file, *file.parents) if part != root)
                or not file.resolve().is_relative_to(root)):
            raise GetContractRuntimeBindingError("A get-tool owner escaped its reviewed tree.")
        raw = file.read_bytes()
        if (hashlib.sha256(raw).hexdigest() != digest or committed
                and hashlib.sha256(_git(root, "show", f"HEAD:{relative}")).hexdigest() != digest):
            raise GetContractRuntimeBindingError("A get-tool owner differs from its reviewed bytes.")
        source = raw.decode("utf-8")
        sources[relative] = source
        locations = []
        for anchor in anchors[relative]:
            if source.count(anchor) != 1:
                raise GetContractRuntimeBindingError("A get-tool owner has no unique reviewed linkage.")
            locations.append({"anchor": anchor.rstrip("\n"),
                              "line": source[:source.index(anchor)].count("\n") + 1})
        evidence.append({"path": relative, "sha256": digest, "anchors": locations})
    return sources, evidence


def prepare_get_contract_runtime_bindings(checkout: Path, runtime_root: Path) -> dict:
    """Authenticate source owners and independent official release module exports."""
    checkout, runtime_root = Path(checkout).resolve(), Path(runtime_root).resolve()
    try:
        if (_git(checkout, "rev-parse", "HEAD").decode().strip() != REFERENCE_COMMIT
                or Path(_git(checkout, "rev-parse", "--show-toplevel").decode().strip()).resolve() != checkout
                or _git(checkout, "status", "--porcelain", "--untracked-files=no").strip()):
            raise GetContractRuntimeBindingError("Get-tool evidence requires the unchanged pinned checkout.")
        sources, source_evidence = _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
        _, compiled_evidence = _owners(runtime_root, COMPILED_HASHES, COMPILED_ANCHORS, committed=False)
        chain = [
            _named(sources, "extensions/memory-core/src/tools.ts", "./memory-read-tool.js",
                   ("executeMemoryReadResult", "executeWikiMemoryReadResult"), kind="import", exact=True),
            _named(sources, "extensions/memory-core/src/tools.runtime.ts",
                   "openclaw/plugin-sdk/memory-core-host-runtime-files",
                   ("readAgentMemoryFile", "resolveMemoryBackendConfig"), kind="export", exact=True),
            _named(sources, "src/plugin-sdk/memory-core-host-runtime-files.ts",
                   "../../packages/memory-host-sdk/src/runtime-files.js",
                   ("listMemoryFiles", "normalizeExtraMemoryPaths", "readAgentMemoryFile",
                    "resolveMemoryBackendConfig"), kind="export", exact=True),
            _named(sources, "packages/memory-host-sdk/src/runtime-files.ts", "./host/read-file.js",
                   ("readAgentMemoryFile",), kind="export", exact=True),
            _named(sources, "packages/memory-host-sdk/src/host/read-file.ts", "./read-file-shared.js",
                   ("buildMemoryReadResult", "DEFAULT_MEMORY_READ_LINES"), kind="import", exact=True),
        ]
    except (OSError, UnicodeError, ReferenceBindingError, ReuseBindingError) as error:
        raise GetContractRuntimeBindingError("Get-tool runtime provenance could not be verified.") from error
    return {
        "kind": "official-release-memory-get-tool-owner", "referenceCommit": REFERENCE_COMMIT,
        "sourceBuildReproduced": False, "constructorSkipped": False,
        "indexManagerConstructed": False, "fullManagerExecutionVerified": False,
        "fullHostOrchestrationVerified": False,
        "sourceBindings": source_evidence, "sourceImportLinks": chain,
        "compiledBindings": compiled_evidence,
        "entrypoints": {
            "tool": {"path": "dist/tools-DotaQGXh.mjs", "export": "createMemoryGetTool"},
            "read": {"path": "dist/read-file-CH8NQLbp.mjs", "export": "t",
                     "originalBinding": "readAgentMemoryFile"},
        },
        "requiredLoadedArtifactsByKind": REQUIRED_LOADED_ARTIFACTS_BY_KIND,
        "requiredLoadedArtifactsByProfile": REQUIRED_LOADED_ARTIFACTS_BY_PROFILE,
        "additionalReadRuntimeArtifactsForReturnedEnvelope": list(READ_RUNTIME_ARTIFACTS),
        "workerRequired": False,
        "fixtureBoundary": "Whole-tool cases use the genuine public factory/execute callback, "
                           "native secure file reads and registered wiki provider fixtures. All "
                           "wire envelope fields and raw originals are retained through the declared "
                           "JSON carrier codec. Explicitly flagged filesystem fixtures may alias "
                           "only their exact owned case fixture base, preserving every path suffix "
                           "and OS diagnostic word; the untouched raw payload remains attested. "
                           "This read path needs no index manager or worker. "
                           "Unrelated storage, deadline and general UTF-engine contracts remain open.",
    }
