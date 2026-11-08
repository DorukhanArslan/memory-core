"""Authenticate original deadline/cooldown/corpus owners and release exports.

The search profile injects a controlled manager at its acquisition boundary.
The get profile performs genuine secure file reads without that override.
Neither profile establishes index construction, provider transport, general
ranking, operating-system timing or complete host orchestration.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from equivalence.reference_bindings import ReferenceBindingError, _git
from equivalence.reuse_bindings import ReuseBindingError, _named

REFERENCE_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"
SOURCE_HASHES = {'extensions/memory-core/src/tools.ts': 'bc3fc7cbfa743fcfe57200a0c66ee6ca53191e928a20f4195c29ca0122980e66',
 'extensions/memory-core/src/memory/search-deadline.ts': '8bbbe60f02eb73552adbcf8e7440c2dad84c6d6d857a0bccf948f6a30ad5f693',
 'packages/memory-host-sdk/src/host/search-deadline-control.ts': 'ac3eee0e159c9d949c5367a1e8e40ead6b1c2a5433f9d925dc29184b9dc3208b',
 'extensions/memory-core/src/memory-corpus.ts': 'f37d07ba508c47256dfa5b60f71caad06569ca8e3e195bbfc2363c7cc098bca3',
 'extensions/memory-core/src/memory-search-tool-query.ts': '48168070d098e7540f82e83a2ab5e12cda338af8bded9d1a0b65e22514c93bdb',
 'extensions/memory-core/src/tools.shared.ts': 'f111a96bd8f19e2e7b295133531a1ac240ae9938ef2c0c4cd477a8b914b0d9be',
 'extensions/memory-core/src/tools.runtime.ts': 'db0cca56eef6ad7b7cd6d56429d42529442a541ca0597f87be0603583e730fc5',
 'extensions/memory-core/src/memory/search-manager.ts': 'c416ce10a435f0eaa8b3dbeae9158ea989b33de2aedf9a8816e52472bb2b1c23',
 'extensions/memory-core/src/memory/manager-runtime.ts': '0aa26fecd02844613b2e671b00e417ade5f0354df30e36afb9dcc2b559178c6b',
 'extensions/memory-core/src/memory/manager.ts': 'c4995b1e83db3e9aa4fbc6bdcffe4ddb36d9a5769396a0b1fd4ee2934c5c8173',
 'packages/memory-host-sdk/src/host/types.ts': '737b555fc517671b927bcbab30334ffbd20c3690e02fa72595eeaacbddf06e4a',
 'src/config/runtime-snapshot.ts': '16f1308be97b38b2524026c3367d9653248522ae60861b3ddbc770d127ba0d5d',
 'src/plugins/memory-state.ts': 'b334c9eed9bbb43c54560515a62511b6ff5ea77a044c584d0ea029670ad37229'}
SOURCE_ANCHORS = {'extensions/memory-core/src/tools.ts': ('export function createMemorySearchTool(options: '
                                         'MemoryToolOptions) {',
                                         'function readMemorySearchToolCooldown(',
                                         'function recordMemorySearchToolCooldown('),
 'extensions/memory-core/src/memory/search-deadline.ts': ('export async function '
                                                          'runMemorySearchWithDeadline<T>(params: {',
                                                          'export function '
                                                          'isMemorySearchDeadlineError(error: unknown): '
                                                          'boolean {'),
 'packages/memory-host-sdk/src/host/search-deadline-control.ts': ('export function '
                                                                  'createMemorySearchDeadlineControl(): '
                                                                  'MemorySearchDeadlineControl {',),
 'extensions/memory-core/src/memory-corpus.ts': ('export async function runMemoryCorpusDeadline<T>(params: '
                                                 '{',
                                                 'export async function attemptMemoryCorpus<T>(params: {',
                                                 'export function composeMemoryCorpusMetadata('),
 'extensions/memory-core/src/memory-search-tool-query.ts': ('export async function '
                                                            'executeMemorySearchToolQuery(params: {',),
 'extensions/memory-core/src/tools.shared.ts': ('export async function '
                                                'getMemoryManagerContextWithPurpose(params: {',
                                                'export function buildMemorySearchUnavailableResult('),
 'extensions/memory-core/src/tools.runtime.ts': ('  readAgentMemoryFile,',),
 'extensions/memory-core/src/memory/search-manager.ts': ('export async function getMemorySearchManager(',),
 'extensions/memory-core/src/memory/manager-runtime.ts': ('export { MemoryIndexManager };',),
 'extensions/memory-core/src/memory/manager.ts': ('export class MemoryIndexManager extends '
                                                  'MemorySearchOrchestration implements '
                                                  'MemorySearchManager {',),
 'packages/memory-host-sdk/src/host/types.ts': ('export function resolveMemorySearchStaleness(',),
 'src/config/runtime-snapshot.ts': ('export function resolveRuntimeConfigCacheKey(config: OpenClawConfig): '
                                    'string {',),
 'src/plugins/memory-state.ts': ('export function registerMemoryCorpusSupplement(',)}
COMPILED_HASHES = {'dist/tools-DotaQGXh.mjs': 'c31b10a5ed25a1e02e5e7ac5be034b78906558c39350fd72be3f4c9edecc766e',
 'dist/search-deadline-control-CvwcTLrz.mjs': '863e15928b995cf1180f00f1cffda9eee2f4c164718e33cfa92967e3a4d79f52',
 'dist/extensions/memory-core/manager-runtime.js': '6ae8f02e229a5422d88dde59a6c070cce03e1ac9ffe5fa87172db8512f0eea0e',
 'dist/memory-CO0OCfyl.mjs': '428531446f314cd1d2a5214f78e849a1ae9f7fbd042d66b71505416e7fda9702',
 'dist/tools.runtime.js': '453b5423b3b47e05cf06608162ae184186d332c2042792bde427580cc73d5661',
 'dist/tools.runtime-m4sffzql.mjs': '0e3cca44ae9922d28e02779723a91f99889e6322a77daa4d9700bdcb4f816983',
 'dist/memory-state-BmtUbXjH.mjs': 'ed71931d904089353576180357a71c99a6a976b6e300b381b0be943298c9bc4f',
 'dist/types-DTVBdCzw.mjs': '14598f9947a85bf691d345dc54c32899c8931afc580e45f143918afe8b54db50',
 'dist/session-search-visibility-BSOBplEm.mjs': 'd7ab86815684e09c631ddc06062dbf62a6063be42c08d595b9f2050d24f63675',
 'dist/runtime-snapshot-BFi3jxlO.mjs': '0cb73088d71ff77c47d63931a00d9c771b5fc5c205ad77f3588335c8a908f9cb',
 'dist/tool-results-BCM3fdVS.mjs': 'ac69dc5bf2dac8d90d319e1fa58ee8684101987f8522ae80a5b0ba5de49239a1'}
COMPILED_ANCHORS = {'dist/tools-DotaQGXh.mjs': ('function createMemorySearchTool(options) {',
                             'function readMemorySearchToolCooldown(key, cfg) {',
                             'function recordMemorySearchToolCooldown(key, cfg, failure) {',
                             'async function runMemoryCorpusDeadline(params) {',
                             'async function attemptMemoryCorpus(params) {',
                             'async function executeMemorySearchToolQuery(params) {',
                             'function buildMemorySearchUnavailableResult(error, overrides) {'),
 'dist/search-deadline-control-CvwcTLrz.mjs': ('function createMemorySearchDeadlineControl() {',
                                               'export { createMemorySearchDeadlineControl as n, '
                                               'MEMORY_SEARCH_DEADLINE_CONTROL as t };'),
 'dist/extensions/memory-core/manager-runtime.js': ('var MemoryIndexManager = class MemoryIndexManager '
                                                    'extends MemorySearchOrchestration {',
                                                    '\tstatic async get(params) {'),
 'dist/memory-CO0OCfyl.mjs': ('async function getMemorySearchManager(params) {',),
 'dist/tools.runtime.js': ('export * from "./tools.runtime-m4sffzql.mjs";',),
 'dist/tools.runtime-m4sffzql.mjs': ('export { getMemorySearchManager, readAgentMemoryFile, '
                                     'resolveMemoryBackendConfig };',),
 'dist/memory-state-BmtUbXjH.mjs': ('function registerMemoryCorpusSupplement(requestedPluginId, '
                                    'supplement) {',),
 'dist/types-DTVBdCzw.mjs': ('function resolveMemorySearchStaleness(status, agentId) {',),
 'dist/session-search-visibility-BSOBplEm.mjs': ('async function '
                                                 'filterMemorySearchHitsBySessionVisibility(params) {',),
 'dist/runtime-snapshot-BFi3jxlO.mjs': ('function resolveRuntimeConfigCacheKey(config) {',),
 'dist/tool-results-BCM3fdVS.mjs': ('function jsonResult(payload) {',)}

# Preserve the original controlled-search artifact requirement independently of
# the additional real-file get profile. No other binder is imported or nested.
SEARCH_REQUIRED_LOADED_ARTIFACTS = tuple(COMPILED_HASHES)
GET_SOURCE_HASHES = {
    "extensions/memory-core/src/memory-read-tool.ts": "318bdf62b8503176b55eda4c6431b91e6b330cbeb3178f390f0623e87f621c37",
    "packages/memory-host-sdk/src/host/read-file.ts": "340bb4aff7a88ee80591e5d0bc4f959367e7d2b6d7f06017d599f0342cb29dd2",
    "packages/memory-host-sdk/src/host/read-file-shared.ts": "cc574d3135a6849b6a62ed640a5e502eb23ca066071ce152d704ce861f2f8b5d",
    "packages/memory-host-sdk/src/runtime-files.ts": "1245f01809e91317f28aa6966cbdd7baf34d1d46b858b0dbfd765be29bfb5274",
    "src/plugin-sdk/memory-core-host-runtime-files.ts": "286e82455cd53f203094ed3ef196c622bd98b73f34a8b25a8035e402e5178905",
}
GET_SOURCE_ANCHORS = {
    "extensions/memory-core/src/memory-read-tool.ts": (
        "export async function executeMemoryReadResult(",
        "export async function executeWikiMemoryReadResult(params: MemoryReadRequest) {",
    ),
    "packages/memory-host-sdk/src/host/read-file.ts": (
        "export async function readMemoryFile(params: {",
        "export async function readAgentMemoryFile(params: {",
    ),
    "packages/memory-host-sdk/src/host/read-file-shared.ts": (
        "export function buildMemoryReadResult(params: {",
        "export function buildMemoryReadResultFromSlice(params: {",
    ),
    "packages/memory-host-sdk/src/runtime-files.ts": (
        'export { readAgentMemoryFile } from "./host/read-file.js";',
    ),
    "src/plugin-sdk/memory-core-host-runtime-files.ts": ("  readAgentMemoryFile,",),
}
SOURCE_HASHES.update(GET_SOURCE_HASHES)
SOURCE_ANCHORS.update(GET_SOURCE_ANCHORS)
SOURCE_ANCHORS["extensions/memory-core/src/tools.ts"] += (
    "export function createMemoryGetTool(options: MemoryToolOptions) {",
)
SOURCE_ANCHORS["extensions/memory-core/src/memory-corpus.ts"] += (
    "export async function readMemoryCorpusSupplements(params: {",
)
COMPILED_HASHES["dist/read-file-CH8NQLbp.mjs"] = "eec2ac48d772f0d2303c65bf3ea3a0866c42f864bf8e9c75f7307643044a4687"
COMPILED_ANCHORS["dist/read-file-CH8NQLbp.mjs"] = (
    "async function readMemoryFile(params) {", "async function readAgentMemoryFile(params) {",
    "function buildMemoryReadResult(params) {", "function buildMemoryReadResultFromSlice(params) {",
)
COMPILED_ANCHORS["dist/tools-DotaQGXh.mjs"] += (
    "function createMemoryGetTool(options) {", "async function executeMemoryReadResult(params) {",
    "async function executeWikiMemoryReadResult(params) {",
)
COMPILED_ANCHORS["dist/tools.runtime-m4sffzql.mjs"] += (
    'import { t as readAgentMemoryFile } from "./read-file-CH8NQLbp.mjs";',
)
GET_REQUIRED_LOADED_ARTIFACTS = (
    "dist/tools-DotaQGXh.mjs", "dist/search-deadline-control-CvwcTLrz.mjs",
    "dist/tools.runtime.js", "dist/tools.runtime-m4sffzql.mjs",
    "dist/memory-state-BmtUbXjH.mjs", "dist/types-DTVBdCzw.mjs",
    "dist/tool-results-BCM3fdVS.mjs", "dist/read-file-CH8NQLbp.mjs",
)
REQUIRED_LOADED_ARTIFACTS_BY_PROFILE = {
    "deadline-partial-runtime": list(SEARCH_REQUIRED_LOADED_ARTIFACTS),
    "deadline-partial-get-runtime": list(GET_REQUIRED_LOADED_ARTIFACTS),
}


class DeadlinePartialRuntimeBindingError(ValueError):
    """The reviewed deadline/recovery owners or official artifacts changed."""


def _owners(root: Path, hashes: dict[str, str], anchors: dict[str, tuple[str, ...]],
            *, committed: bool) -> tuple[dict[str, str], list[dict]]:
    sources = {}
    evidence = []
    for relative, digest in hashes.items():
        file = root / relative
        if (any(part.is_symlink() for part in (file, *file.parents) if part != root)
                or not file.resolve().is_relative_to(root)):
            raise DeadlinePartialRuntimeBindingError("A deadline/recovery owner escaped its reviewed tree.")
        raw = file.read_bytes()
        if (hashlib.sha256(raw).hexdigest() != digest or committed
                and hashlib.sha256(_git(root, "show", f"HEAD:{relative}")).hexdigest() != digest):
            raise DeadlinePartialRuntimeBindingError("A deadline/recovery owner differs from its reviewed bytes.")
        source = raw.decode("utf-8")
        sources[relative] = source
        locations = []
        for anchor in anchors[relative]:
            if source.count(anchor) != 1:
                raise DeadlinePartialRuntimeBindingError("A deadline/recovery owner has no unique reviewed linkage.")
            locations.append({"anchor": anchor.rstrip("\n"),
                              "line": source[:source.index(anchor)].count("\n") + 1})
        evidence.append({"path": relative, "sha256": digest, "anchors": locations})
    return sources, evidence


def prepare_deadline_partial_runtime_bindings(checkout: Path, runtime_root: Path) -> dict:
    """Authenticate genuine tool owners with an explicit manager fixture boundary."""
    checkout, runtime_root = Path(checkout).resolve(), Path(runtime_root).resolve()
    try:
        if (_git(checkout, "rev-parse", "HEAD").decode().strip() != REFERENCE_COMMIT
                or Path(_git(checkout, "rev-parse", "--show-toplevel").decode().strip()).resolve() != checkout
                or _git(checkout, "status", "--porcelain", "--untracked-files=no").strip()):
            raise DeadlinePartialRuntimeBindingError("Deadline/recovery evidence requires the unchanged pinned checkout.")
        sources, source_evidence = _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
        _, compiled_evidence = _owners(runtime_root, COMPILED_HASHES, COMPILED_ANCHORS, committed=False)
        tool = "extensions/memory-core/src/tools.ts"
        chain = [
            _named(sources, tool, "./memory-corpus.js",
                   ("attemptMemoryCorpus", "composeMemoryCorpusMetadata", "runMemoryCorpusDeadline",
                    "searchMemoryCorpusSupplements", "unavailableMemoryCorpus"),
                   kind="import", exact=True),
            _named(sources, tool, "./memory-search-tool-query.js",
                   ("buildPausedMemoryIndexUnavailableResult", "executeMemorySearchToolQuery"),
                   kind="import", exact=True),
            _named(sources, tool, "./memory/search-deadline.js",
                   ("DEFAULT_MEMORY_SEARCH_TIMEOUT_MS", "resolveMemorySearchAbortError",
                    "runMemorySearchWithDeadline"), kind="import", exact=True),
            _named(sources, tool, "./tools.shared.js",
                   ("buildMemorySearchUnavailableResult", "createMemoryTool",
                    "getMemoryManagerContextWithPurpose", "loadMemoryToolRuntime"),
                   kind="import", exact=True),
            _named(sources, "extensions/memory-core/src/memory-corpus.ts", "./memory/search-deadline.js",
                   ("createMemorySearchDeadlineError", "DEFAULT_MEMORY_SEARCH_TIMEOUT_MS",
                    "isMemorySearchDeadlineError", "resolveMemorySearchAbortError"),
                   kind="import", exact=True),
            _named(sources, "extensions/memory-core/src/tools.shared.ts", "./memory/search-deadline.js",
                   ("DEFAULT_MEMORY_SEARCH_TIMEOUT_MS",), kind="import", exact=True),
            _named(sources, "extensions/memory-core/src/tools.runtime.ts", "./memory/index.js",
                   ("getMemorySearchManager",), kind="export", exact=True),
            _named(sources, "extensions/memory-core/src/memory/manager-runtime.ts", "./manager.js",
                   ("getMemoryIndexManagerRegistry", "MemoryIndexManager"), kind="import", exact=True),
            _named(sources, tool, "./memory-read-tool.js",
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
    except (OSError, UnicodeError, ReferenceBindingError, ReuseBindingError, ValueError) as error:
        raise DeadlinePartialRuntimeBindingError("Deadline/recovery runtime provenance could not be verified.") from error
    manager_path = "dist/extensions/memory-core/manager-runtime.js"
    return {
        "kind": "official-release-memory-deadline-partial-tool-owner",
        "referenceCommit": REFERENCE_COMMIT, "sourceBuildReproduced": False,
        "defaultProfile": "deadline-partial-runtime",
        "topLevelFlagsApplyToProfile": "deadline-partial-runtime",
        "constructorSkipped": True, "managerFixture": True,
        "fullManagerExecutionVerified": False, "fullHostOrchestrationVerified": False,
        "sourceBindings": source_evidence, "sourceImportLinks": chain,
        "compiledBindings": compiled_evidence,
        "entrypoints": {
            "tool": {"path": "dist/tools-DotaQGXh.mjs", "export": "createMemorySearchTool"},
            "manager": {"path": manager_path, "export": "MemoryIndexManager",
                        "overriddenMethod": "get", "constructorSkipped": True},
            "deadlineControl": {"path": "dist/search-deadline-control-CvwcTLrz.mjs", "export": "n",
                                "originalBinding": "createMemorySearchDeadlineControl"},
            "getTool": {"path": "dist/tools-DotaQGXh.mjs", "export": "createMemoryGetTool"},
            "getRead": {"path": "dist/read-file-CH8NQLbp.mjs", "export": "t",
                        "originalBinding": "readAgentMemoryFile"},
        },
        "overriddenMethods": [{
            "path": manager_path, "export": "MemoryIndexManager", "method": "get",
            "static": True, "controlledFixture": True,
            "behavior": "Returns the declared controlled manager fixture at acquisition; "
                        "the original manager constructor and static get body do not execute.",
        }],
        "requiredLoadedArtifacts": list(SEARCH_REQUIRED_LOADED_ARTIFACTS), "workerRequired": False,
        "requiredLoadedArtifactsByProfile": REQUIRED_LOADED_ARTIFACTS_BY_PROFILE,
        "profiles": {
            "deadline-partial-runtime": {
                "constructorSkipped": True, "managerFixture": True, "workerRequired": False,
                "realFileIO": False, "overriddenMethods": ["MemoryIndexManager.get"],
                "fullManagerExecutionVerified": False,
            },
            "deadline-partial-get-runtime": {
                "constructorSkipped": False, "managerFixture": False, "workerRequired": False,
                "realFileIO": True, "overriddenMethods": [], "indexManagerConstructed": False,
                "managerAcquisition": "not-required",
                "fullManagerExecutionVerified": False,
            },
        },
        "timingProfile": {
            "owner": "node:test", "timers": "mock.timers", "apis": ["Date", "setTimeout"],
            "performanceClock": "mock.method(performance, 'now', () => Date.now())",
            "customTimerImplementation": False,
        },
        "fixtureBoundary": "Top-level fixture flags describe the default controlled-search profile. "
                           "The genuine search factory, execute callback, manager-context acquisition, "
                           "deadline/query/corpus/cooldown owners and result envelope execute unchanged. "
                           "Only static MemoryIndexManager.get is overridden to return a declared controlled "
                           "manager fixture. Built-in Node mock timers control Date/setTimeout and "
                           "mock.method couples performance.now to that clock. The index manager constructor "
                           "is skipped; no provider transport, index construction, worker dispatch, general "
                           "ranking, operating-system timing, or complete host orchestration is established. "
                           "The separate get profile uses createMemoryGetTool, unchanged read/corpus "
                           "wrappers and genuine secure readAgentMemoryFile file IO; it does not override "
                           "manager acquisition, construct an index manager, or require a worker.",
    }
