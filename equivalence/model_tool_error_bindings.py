"""Pinned whole-tool supplemental failures and genuine redacting formatter owners."""
from __future__ import annotations
import hashlib
from pathlib import Path
from equivalence.reference_bindings import _git
from equivalence.session_admission_runtime_bindings import _owners, _named_link
REFERENCE_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"

SOURCE_HASHES = {'src/infra/errors.ts': 'a195735ec6b4f2426dce5eada6f033f40faca93c3dd2777f41ba88bb4b83e1f0',
 'packages/normalization-core/src/error-coercion.ts': '699730a7140507cc86c884116d01b3820cc0a3fe9a4c1ed38db58f77c673ab88',
 'src/logging/redact.ts': 'ecdfdb1e0f4b0f2aa3eb54aad574bb5375ae8da78539ad937b34ba02dd170e7b',
 'src/logging/secret-redaction-registry.ts': '217d789ec4e6b3896dc7c647d33a8a2eed2df4b754fa0abf93a577296863f689',
 'src/plugins/memory-state.ts': 'b334c9eed9bbb43c54560515a62511b6ff5ea77a044c584d0ea029670ad37229',
 'extensions/memory-core/src/tools.ts': 'bc3fc7cbfa743fcfe57200a0c66ee6ca53191e928a20f4195c29ca0122980e66',
 'extensions/memory-core/src/tools.shared.ts': 'f111a96bd8f19e2e7b295133531a1ac240ae9938ef2c0c4cd477a8b914b0d9be',
 'extensions/memory-core/src/memory-corpus.ts': 'f37d07ba508c47256dfa5b60f71caad06569ca8e3e195bbfc2363c7cc098bca3',
 'extensions/memory-core/src/memory-read-tool.ts': '318bdf62b8503176b55eda4c6431b91e6b330cbeb3178f390f0623e87f621c37',
 'extensions/memory-core/src/memory-tool-contract.ts': '6d1649776d4a73729b36facd8ef5cdc6d77e443b719c736ecedd9c9ea6f48191',
 'extensions/memory-core/src/tools.runtime.ts': 'db0cca56eef6ad7b7cd6d56429d42529442a541ca0597f87be0603583e730fc5',
 'src/agents/tools/tool-results.ts': '36a3500e0cc46b1615daf70636c651f7f35ff6c6ed5273a2c63a3e9182bc14f7',
 'src/plugin-sdk/error-runtime.ts': '91e7eae29418c9659235b1a0cbc96c955c20fac9655db067d83f29c8900bd7c8'}

SOURCE_ANCHORS = {'src/infra/errors.ts': ('export function formatErrorMessage(err: unknown): string {',),
 'packages/normalization-core/src/error-coercion.ts': ('export function formatErrorMessage(value: unknown, '
                                                       'options: FormatErrorMessageOptions): string {',),
 'src/logging/redact.ts': ('export function redactSensitiveText(',),
 'src/logging/secret-redaction-registry.ts': ('export function registerSecretValueForRedaction(value: '
                                              'string): void {',
                                              'export function captureSecretRedactionRegistrySnapshot():'),
 'src/plugins/memory-state.ts': ('export function registerMemoryCorpusSupplement(',),
 'extensions/memory-core/src/tools.ts': ('export function createMemorySearchTool(options: MemoryToolOptions) '
                                         '{',
                                         'export function createMemoryGetTool(options: MemoryToolOptions) {'),
 'extensions/memory-core/src/tools.shared.ts': ('export function createMemoryTool(params: {',),
 'extensions/memory-core/src/memory-corpus.ts': ('export async function '
                                                 'searchMemoryCorpusSupplements(params: {',
                                                 'export async function readMemoryCorpusSupplements(params: '
                                                 '{'),
 'extensions/memory-core/src/memory-read-tool.ts': ('function readWiki(',),
 'extensions/memory-core/src/memory-tool-contract.ts': ('export function resolveMemoryToolContext(options: '
                                                        'MemoryToolOptions) {',),
 'extensions/memory-core/src/tools.runtime.ts': ('export { getMemorySearchManager }',),
 'src/agents/tools/tool-results.ts': ('export function jsonResult<TDetails>(payload: TDetails): '
                                      'AgentToolResult<TDetails> {',),
 'src/plugin-sdk/error-runtime.ts': ('  formatErrorMessage,',)}

COMPILED_HASHES = {'dist/errors-DlCDP-e5.mjs': '02648f360e8e7c71abb28611ad4d6abc5f7b37201091c43cd8222e59355f9b48',
 'dist/error-coercion-1P2One0X.mjs': 'dc084c616cc292128c5ff39fc77cf2a5cf9487bd0e8339bb0a8aa215110646b6',
 'dist/redact-BCoakatc.mjs': '17028994a6670b397e171921efdcd01f00c1b8d4058db5216d62f976e74a65d6',
 'dist/secret-redaction-registry-b2B9lcfy.mjs': '432fe8ecb1999ef09de6a40878fcedf717eb570ec024a75d77f9e5667cd62f24',
 'dist/memory-state-BmtUbXjH.mjs': 'ed71931d904089353576180357a71c99a6a976b6e300b381b0be943298c9bc4f',
 'dist/tools-DotaQGXh.mjs': 'c31b10a5ed25a1e02e5e7ac5be034b78906558c39350fd72be3f4c9edecc766e',
 'dist/tools.runtime.js': '453b5423b3b47e05cf06608162ae184186d332c2042792bde427580cc73d5661',
 'dist/tools.runtime-m4sffzql.mjs': '0e3cca44ae9922d28e02779723a91f99889e6322a77daa4d9700bdcb4f816983',
 'dist/memory-tool-contract-DOz26L8b.mjs': 'caa1cf11748ff19c561d94a321ffff564fdfbd357bc8954e09f50ed6844bb063',
 'dist/tool-results-BCM3fdVS.mjs': 'ac69dc5bf2dac8d90d319e1fa58ee8684101987f8522ae80a5b0ba5de49239a1',
 'dist/common-CnSoEQyp.mjs': '7528a47a2ba0ad07e678c6efdd308b858bc2587abf85bfc3f1a6c20e2a50cf57'}

COMPILED_ANCHORS = {'dist/errors-DlCDP-e5.mjs': ('function formatErrorMessage(err) {', 'formatErrorMessage as t'),
 'dist/error-coercion-1P2One0X.mjs': ('function formatErrorMessage(value, options) {',),
 'dist/redact-BCoakatc.mjs': ('function redactSensitiveText(text, options) {',),
 'dist/secret-redaction-registry-b2B9lcfy.mjs': ('function captureSecretRedactionRegistrySnapshot() {',
                                                 'registerSecretValueForRedaction as s'),
 'dist/memory-state-BmtUbXjH.mjs': ('function registerMemoryCorpusSupplement(requestedPluginId, supplement) '
                                    '{',
                                    'registerMemoryCorpusSupplement as m'),
 'dist/tools-DotaQGXh.mjs': ('function createMemorySearchTool(options) {',
                             'function createMemoryGetTool(options) {',
                             'async function searchMemoryCorpusSupplements(params) {',
                             'async function readMemoryCorpusSupplements(params) {'),
 'dist/tools.runtime.js': ('export * from "./tools.runtime-m4sffzql.mjs";',),
 'dist/tools.runtime-m4sffzql.mjs': ('export { getMemorySearchManager, readAgentMemoryFile, '
                                     'resolveMemoryBackendConfig };',),
 'dist/memory-tool-contract-DOz26L8b.mjs': ('function resolveMemoryToolContext(options) {',),
 'dist/tool-results-BCM3fdVS.mjs': ('function jsonResult(payload) {',),
 'dist/common-CnSoEQyp.mjs': ('function readPositiveIntegerParam(params, key, options = {}) {',)}

SOURCE_LINKS = (('src/infra/errors.ts', '../logging/redact.js', ('redactSensitiveText',), 'import'),
 ('extensions/memory-core/src/memory-corpus.ts',
  'openclaw/plugin-sdk/error-runtime',
  ('extractErrorCode', 'formatErrorMessage'),
  'import'),
 ('extensions/memory-core/src/memory-corpus.ts',
  'openclaw/plugin-sdk/memory-core-host-runtime-core',
  ('listMemoryCorpusSupplements',),
  'import'),
 ('extensions/memory-core/src/tools.ts',
  './tools.shared.js',
  ('createMemoryTool', 'loadMemoryToolRuntime'),
  'import'),
 ('extensions/memory-core/src/tools.ts', './memory-corpus.js', ('searchMemoryCorpusSupplements',), 'import'))

COMPILED_LINKS = (('dist/errors-DlCDP-e5.mjs',
  'import { i as extractErrorCode, o as formatErrorMessage$1 } from "./error-coercion-1P2One0X.mjs";'),
 ('dist/errors-DlCDP-e5.mjs', 'import { _ as redactSensitiveText } from "./redact-BCoakatc.mjs";'),
 ('dist/tools-DotaQGXh.mjs', 'import { t as formatErrorMessage } from "./errors-DlCDP-e5.mjs";'),
 ('dist/tools-DotaQGXh.mjs',
  'import { l as listMemoryCorpusSupplements } from "./memory-state-BmtUbXjH.mjs";'),
 ('dist/tools-DotaQGXh.mjs', 'import { t as jsonResult } from "./tool-results-BCM3fdVS.mjs";'))

REQUIRED_ERROR_ARTIFACTS = tuple(COMPILED_HASHES)

class ModelToolErrorBindingError(ValueError):
    """The reviewed complete formatter/tool error owner changed."""


def prepare_model_tool_error_runtime_bindings(checkout: Path, runtime_root: Path) -> dict:
    checkout, runtime_root = Path(checkout).resolve(), Path(runtime_root).resolve()
    try:
        if (_git(checkout, "rev-parse", "HEAD").decode().strip() != REFERENCE_COMMIT
                or Path(_git(checkout, "rev-parse", "--show-toplevel").decode().strip()).resolve() != checkout
                or _git(checkout, "status", "--porcelain", "--untracked-files=no").strip()):
            raise ModelToolErrorBindingError("Error boundaries require the unchanged pinned source checkout")
        sources, source_evidence = _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
        compiled, artifact_evidence = _owners(runtime_root, COMPILED_HASHES, COMPILED_ANCHORS, committed=False)
        source_links = [_named_link(sources, p, s, n, kind=k) for p, s, n, k in SOURCE_LINKS]
        compiled_links = []
        for module, declaration in COMPILED_LINKS:
            if compiled[module].count(declaration) != 1:
                raise ModelToolErrorBindingError("An original compiled error-owner import changed")
            compiled_links.append({"path": module, "declaration": declaration, "kind": "import",
                "line": compiled[module][:compiled[module].index(declaration)].count("\n") + 1,
                "declarationSha256": hashlib.sha256(declaration.encode()).hexdigest()})
    except (OSError, UnicodeError, ValueError) as error:
        raise ModelToolErrorBindingError("Complete error-owner authority could not be authenticated") from error
    return {"kind": "official-release-model-tool-error", "referenceCommit": REFERENCE_COMMIT,
        "sourceBuildReproduced": False, "sourceExecutionPermitted": False,
        "sourceBindings": source_evidence, "sourceImportLinks": source_links,
        "compiledBindings": artifact_evidence, "compiledImportLinks": compiled_links,
        "requiredArtifacts": list(REQUIRED_ERROR_ARTIFACTS),
        "indexManagerConstructed": False, "memoryIndexSearchClaimed": False,
        "fullHostOrchestrationVerified": False, "modelProviderNetworkVerified": False,
        "errorBoundary": "Real original memory_get/search factories execute registered synthetic supplemental callbacks",
        "publicBoundary": "Complete formatter string, original JSON envelopes and verified complete decoded transport",
        "registryIsolation": "One fresh protected OS child per case, actual initial revision zero and empty values",
        "errorOwnPropertiesAndCausesRetained": True, "registryRevisionOffsetsPermitted": False,
        "sameThrownErrorReceiptsRequired": True, "testEnvironmentSwitchPermitted": False}
