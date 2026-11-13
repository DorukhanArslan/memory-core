"""Independent declarations for natural foreground/maintenance admission.

These pins extend the unchanged restart publication inventory with the genuine
full reply caller, its admission and completion owners, optional maintenance,
and the plugin/provider context used by the controlled model transport. They
prove authenticated bytes and declaration linkage only. Actual execution and
any acceptance credit belong to the separate closed-family evidence guard.
No existing capability or frozen restart/update family is widened here.
"""
from __future__ import annotations

from pathlib import Path

from equivalence.host_restart_bindings import REFERENCE_COMMIT, _owners
from equivalence.host_restart_publication_bindings import prepare_host_restart_publication_bindings

HOST_TURN_BARRIER_OPERATION = "host-turn-barrier-runtime"

SOURCE_HASHES = {'src/auto-reply/reply/agent-runner-run.ts': '789a725743e20fafc2208f45a0a390855057ca4abea07588bfa374951f6e82fa',
 'src/auto-reply/reply/agent-runner-execute.ts': 'd93d021dd55fda038ba1fc222caa007f4c4b39a4e6fe69fe8100b961dafa72cb',
 'src/auto-reply/reply/agent-runner-execution.ts': '6b23faea4f50463cf05d2459f6bd70262591e8baec33a8b6b213689debda4549',
 'src/auto-reply/reply/agent-runner-result.ts': '1ccb8ebd23f1a685140185525d9be3cd684d8e79720428dab96213539286a9dc',
 'src/auto-reply/reply/agent-runner-result-complete.ts': '7b5cc1c9609b1fdb53c4c13d6ce2b316c60ad10290604fa408f383947e4b9ab0',
 'src/auto-reply/reply/agent-runner-maintenance.ts': '261f036fcbf39cafee2dade0cd1255540464a6ee4abef1ec1f54ab8ec8f2da95',
 'src/auto-reply/reply/agent-runner-core.ts': '51e1919ecb77acb0ba29bc63f4f9f27e91ff23c6f6e92cbdf8b11ac4820edc71',
 'src/auto-reply/reply/agent-runner-memory.ts': '283089b92cfd44840aaf5cdea08cec5148015ba93d86668e5e0a2b41fcfe8878',
 'src/auto-reply/reply/reply-turn-admission.ts': '6ddc894e6633f4e33306a6c373abfa049a88a76501f51bd97a9547f5284ed989',
 'src/auto-reply/reply/reply-run-registry.operation.ts': '570ce1e0823b21c41d9953ce2c437b87c3104db0c1c670c61f8b80b773df5e9f',
 'src/auto-reply/reply/reply-tool-authority.ts': 'db11b12c78899397faea5afa7e0121feb4c587515aa9e7f656af59e3f5bde4e5',
 'src/agents/session-maintenance/coordinator.ts': '638588d5a22012f1e892932b08eb6df8cc0cfe0423b63b0139348ebb2a330a44',
 'src/agents/session-maintenance/run.ts': '043485f2d937b849c800f01b19d88ef5f0a5e9a997f42fded38641ee45ff0987',
 'src/agents/embedded-agent-runner/run.ts': 'eb795ca6417c5334803554bf42e74f3586f7327bf47edbe048bb65c7852f59d6',
 'src/agents/embedded-agent-runner/run-orchestrator.ts': '479f398502cd42290c9a7cf48bb2dcf180fdc9866a3edf844566e12c7359b6f7',
 'src/sessions/session-lifecycle-admission.ts': '223d69292217c14381eb5b1acc9214fc97a5f1e7ba5a7daea5877f6bda435d50',
 'src/process/gateway-work-admission.ts': 'b6fd1d1011edf486db8bd8cd96123a9a93648c84c881eb81b4db0f110a329596',
 'src/plugins/loader.ts': '04f30e7b07d329c059290a6a666f0e5b797a956f6b9ba44213cbd3e31b1e831d',
 'src/plugins/loader-runtime-load.ts': 'ea1d0c49308736d8fd75316ed612483c9dfb89ad0966ed32a3e0f0beb46c8409',
 'src/plugins/registry.ts': '4f49793315d848868dfa7c5b517f08f52ff3e7b04ec0ff2186047ed7a30ee4bc',
 'src/plugins/registry-empty.ts': '8512baea357321aa7743f43dfb76c75fe1397ce752f2794d112d23e2baa7ef2e',
 'src/plugins/plugin-metadata-snapshot.ts': 'e7e329a73d5c84fc4a368b58ded7de1a9cfacdb1d23b83e763b6d3188037f957',
 'src/plugins/provider-runtime.ts': 'b209db16ccf0845faa417e8bca7da4c7afbbf1d4b6a66919d246e2c458d62ffd',
 'src/plugins/runtime/gateway-request-scope.ts': '93b37b160965b90be21a0ea82f7257390a376481f97e2f96c0ea9fb89607478e',
 'src/config/runtime-snapshot.ts': '16f1308be97b38b2524026c3367d9653248522ae60861b3ddbc770d127ba0d5d',
 'src/config/sessions/transcript-header.ts': 'df2f0da864f5c642bc2b2f76332525d8dab52feb282fd959247acf99f55bc0b7'}

SOURCE_ANCHORS = {'src/auto-reply/reply/agent-runner-run.ts': ('export async function runReplyAgent(',),
 'src/auto-reply/reply/agent-runner-execute.ts': ('export async function executePreparedReplyAgentRun(',),
 'src/auto-reply/reply/agent-runner-execution.ts': ('export async function executeAgentTurn(',),
 'src/auto-reply/reply/agent-runner-result.ts': ('export async function finalizeReplyAgentRun(',),
 'src/auto-reply/reply/agent-runner-result-complete.ts': ('export async function '
                                                          'completeReplyAgentRun(',),
 'src/auto-reply/reply/agent-runner-maintenance.ts': ('export function '
                                                      'scheduleReplySessionMaintenance(',),
 'src/auto-reply/reply/agent-runner-core.ts': ('export async function cleanupReplyAgentRun(',),
 'src/auto-reply/reply/agent-runner-memory.ts': ('export async function runMemoryFlushIfNeeded(',
                                                 'export async function runSessionCompactionIfNeeded('),
 'src/auto-reply/reply/reply-turn-admission.ts': ('export async function admitReplyTurn(',),
 'src/auto-reply/reply/reply-run-registry.operation.ts': ('export function createReplyOperation(',),
 'src/auto-reply/reply/reply-tool-authority.ts': ('export function prepareReplyToolAuthority(',),
 'src/agents/session-maintenance/coordinator.ts': ('export function createSessionMaintenanceOwner(',
                                                   'export async function '
                                                   'beginForegroundSessionMaintenance(',
                                                   'export async function waitForSessionMaintenance('),
 'src/agents/session-maintenance/run.ts': ('export function scheduleSessionMaintenance(',
                                           'export function createSessionMaintenanceFollowup('),
 'src/agents/embedded-agent-runner/run.ts': ('export { runEmbeddedAgent } from '
                                             '"./run-orchestrator.js";',),
 'src/agents/embedded-agent-runner/run-orchestrator.ts': ('export function runEmbeddedAgent(',
                                                          'async function runEmbeddedAgentInternal('),
 'src/sessions/session-lifecycle-admission.ts': ('export async function beginSessionWorkAdmission(',),
 'src/process/gateway-work-admission.ts': ('export function '
                                           'runWithGatewayIndependentRootWorkAdmission<T>(',),
 'src/plugins/loader.ts': ('export function loadAndActivateRootPluginRegistry(',),
 'src/plugins/loader-runtime-load.ts': ('export function loadOpenClawPlugins(',),
 'src/plugins/registry.ts': ('export function createPluginRegistry(',),
 'src/plugins/registry-empty.ts': ('export function createEmptyPluginRegistry(',),
 'src/plugins/plugin-metadata-snapshot.ts': ('export function loadPluginMetadataSnapshot(',),
 'src/plugins/provider-runtime.ts': ('export function resolveProviderStreamFn(',),
 'src/plugins/runtime/gateway-request-scope.ts': ('export function '
                                                  'withPluginRuntimeGatewayRequestScope<T>(',
                                                  'export function withPluginRuntimeRegistryScope<T>('),
 'src/config/runtime-snapshot.ts': ('export function setRuntimeConfigSnapshot(',),
 'src/config/sessions/transcript-header.ts': ('export function createSessionTranscriptHeader(',)}

COMPILED_HASHES = {'dist/agent-runner.runtime-BinSrYfK.mjs': 'cb6eab57cd73619064ffee88347841ed747893abf17236c779590e99f3eb6e7a',
 'dist/session-entry-handle-BTUM17M1.mjs': 'c1ae9c69420966502a196015bac7f42594c0aad5501ee3a3ea7d068f8f4ee52d',
 'dist/reply-run-registry.registry-BB8ktna9.mjs': '890d55089fda8b1ac676bcb57b131c9300dc46f9a7ded380111916d62fc71f99',
 'dist/reply-tool-authority-DHzSfn5D.mjs': 'fe1483f49ac6e195c3393d7b04539b330adb596af5c6bf6d113c7f7d29f57f9d',
 'dist/coordinator-BinYGTDh.mjs': '6a93078f7b08d9058693add622a13f19c104efbd0d888e22ba5c15a24696382b',
 'dist/run-C6ggOzT5.mjs': 'c4c28c955bfd70ea25c57bd9fed4d2bf04564a45837f8767a2bb27dbdc8edf4b',
 'dist/agent-runner-memory-Cc4lCZcs.mjs': '9a87aeee70d84d41eb6bf764a70c0334fb679a2f1e21d817c44c5eb306d5620e',
 'dist/embedded-agent-gxn-c3nS.mjs': '5241e89998d2798f0621418c04438adb07b798a0b92537e91718bf116246d808',
 'dist/session-lifecycle-admission-Bavp6-Yk.mjs': '22cd73046f93f5c54aaeb0eb27296b541e0b19dd5fd74012186dab5cf0fd8c71',
 'dist/gateway-work-admission-CpqGU6O4.mjs': 'ebf3a18ed30b070baa619905f17f20b5000a6ad65632c6d2d9b3cda0d430133d',
 'dist/loader-DpAS3szV.mjs': '8f7973dc6048dff4a775f32b21fdc78d3a38dd73639a478404ed2bc078356106',
 'dist/loader-runtime-load-DpgEqnzx.mjs': '3c30c5d43fb3cd19525853bb6b756cf45cfd05f5da32a732dc129b85cb309787',
 'dist/registry-empty-BTjzcMW2.mjs': '11afb0f560f5b31d2785a5b4381d05639862e748a1220370364657d8b4333698',
 'dist/plugin-metadata-snapshot-DT_pRp6g.mjs': '4236d6b46e5044178b8f938eedd2edbd129f1bfd42e9467d49f1cc49dbcb82b9',
 'dist/provider-runtime-BHqCdO9o.mjs': 'c546dc4f068c84a318fb13fff99a15f0b0871065ded276ca7d81c3efd11d751c',
 'dist/gateway-request-scope-Btza1qbw.mjs': 'd6dcdd77a938c1d4fc8ca2fb1435efdd3bbd4d8ef59663df60ebffa9ab353f5f',
 'dist/runtime-snapshot-BFi3jxlO.mjs': '0cb73088d71ff77c47d63931a00d9c771b5fc5c205ad77f3588335c8a908f9cb',
 'dist/transcript-header-CP-ow2Zr.mjs': '4adbb6f0a5d024dd72cff7e77b6ef8ddeec3f7955399980fc421e8c815844608'}

COMPILED_ANCHORS = {'dist/agent-runner.runtime-BinSrYfK.mjs': ('async function runReplyAgent(input) {',
                                            'async function executePreparedReplyAgentRun(input) {',
                                            'async function executeAgentTurn(params) {',
                                            'async function completeReplyAgentRun(input) {',
                                            'function scheduleReplySessionMaintenance(params) {',
                                            'export { runReplyAgent };'),
 'dist/session-entry-handle-BTUM17M1.mjs': ('async function admitReplyTurn(params) {',
                                            'export { admitReplyTurn as a,'),
 'dist/reply-run-registry.registry-BB8ktna9.mjs': ('function createReplyOperation(params) {',
                                                   'createReplyOperation as w,'),
 'dist/reply-tool-authority-DHzSfn5D.mjs': ('function prepareReplyToolAuthority(run, narrow) {',
                                            'prepareReplyToolAuthority as t'),
 'dist/coordinator-BinYGTDh.mjs': ('function createSessionMaintenanceOwner(params) {',
                                   'async function beginForegroundSessionMaintenance(sessionKey) {',
                                   'async function waitForSessionMaintenance(sessionKey) {',
                                   'export { createSessionMaintenanceOwner as n, '
                                   'waitForSessionMaintenance as r, beginForegroundSessionMaintenance as '
                                   't };'),
 'dist/run-C6ggOzT5.mjs': ('function scheduleSessionMaintenance(request, afterOwnerSettles) {',
                           'function createSessionMaintenanceFollowup(params) {',
                           'scheduleSessionMaintenance as n,'),
 'dist/agent-runner-memory-Cc4lCZcs.mjs': ('async function runMemoryFlushIfNeeded(params) {',
                                           'async function runSessionCompactionIfNeeded(params) {'),
 'dist/embedded-agent-gxn-c3nS.mjs': ('function runEmbeddedAgent(internalParamsInput) {',
                                      'async function runEmbeddedAgentInternal(paramsInput) {',
                                      'runEmbeddedAgent as t'),
 'dist/session-lifecycle-admission-Bavp6-Yk.mjs': ('async function beginSessionWorkAdmission(params) {',),
 'dist/gateway-work-admission-CpqGU6O4.mjs': ('function runWithGatewayIndependentRootWorkAdmission(run, '
                                              'origin, signal) {',),
 'dist/loader-DpAS3szV.mjs': ('function loadAndActivateRootPluginRegistry(options = {}) {',
                              'loadAndActivateRootPluginRegistry as t'),
 'dist/loader-runtime-load-DpgEqnzx.mjs': ('function loadOpenClawPlugins(options = {}) {',
                                           'function createPluginRegistry(registryParams) {'),
 'dist/registry-empty-BTjzcMW2.mjs': ('function createEmptyPluginRegistry() {',),
 'dist/plugin-metadata-snapshot-DT_pRp6g.mjs': ('function loadPluginMetadataSnapshot(params) {',
                                                'loadPluginMetadataSnapshot as o,'),
 'dist/provider-runtime-BHqCdO9o.mjs': ('function resolveProviderStreamFn(params) {',
                                        'const streamFn = plugin?.createStreamFn?.(params.context);'),
 'dist/gateway-request-scope-Btza1qbw.mjs': ('function withPluginRuntimeGatewayRequestScope(scope, run) '
                                             '{',
                                             'function withPluginRuntimeRegistryScope(registry, run, '
                                             'declaredProviderOwners) {',
                                             'withPluginRuntimeGatewayRequestScope as c,'),
 'dist/runtime-snapshot-BFi3jxlO.mjs': ('function setRuntimeConfigSnapshot(config, sourceConfig) {',),
 'dist/transcript-header-CP-ow2Zr.mjs': ('function createSessionTranscriptHeader(params = {}) {',)}

# Raw-only notice observations bind the original writer, live-object consumer
# and publication method. These declarations add no operation or result policy.
SOURCE_HASHES.update({
    "extensions/memory-core/src/memory/manager-sync-ops.ts":
        "5e2732c67f5e07cbb545ec9aad4f7e40ac391561b0c645f68f5ce6e865dcbf18",
    "extensions/memory-core/src/memory/manager.ts":
        "c4995b1e83db3e9aa4fbc6bdcffe4ddb36d9a5769396a0b1fd4ee2934c5c8173",
    "extensions/memory-core/src/memory/manager-search-orchestration.ts":
        "04f4189be68e7cf1118348dd2f22c9cbdfe4a80496a783922d095283c3986c55",
    "extensions/memory-core/src/memory/manager-database-context.ts":
        "bf2006808241b2ed7c07636b49f447e44d1d2fcf1141a4c9d60744738d194bf8",
    "extensions/memory-core/src/memory-rebuild-notice.ts":
        "0abad588fa8a1aad9040d85a16249780592202e651f287446eb55ad3821fe519",
    "extensions/memory-core/src/memory-search-tool-query.ts":
        "48168070d098e7540f82e83a2ab5e12cda338af8bded9d1a0b65e22514c93bdb",
    "extensions/memory-core/src/tools.ts":
        "bc3fc7cbfa743fcfe57200a0c66ee6ca53191e928a20f4195c29ca0122980e66",
})
SOURCE_ANCHORS.update({
    "extensions/memory-core/src/memory/manager-sync-ops.ts": (
        "export abstract class MemoryManagerSyncOps extends MemoryManagerSourceSyncOps {",
        '    this.automaticRebuildNotice = notice ?? { sequence: 0, warning: "" };',
        "  protected recordAutomaticRebuild(): void {",
        "    this.automaticRebuildNotice.sequence += 1;",
        "  protected async runSync(params?: MemorySyncParams) {",
    ),
    "extensions/memory-core/src/memory/manager.ts": (
        "  status(): MemoryProviderStatus {",
        "  protected async syncAdmitted(",
        "    super(params.maintenanceSource?.automaticRebuildNotice);",
        "        automaticRebuildNotice: this.automaticRebuildNotice,",
    ),
    "extensions/memory-core/src/memory/manager-search-orchestration.ts": (
        "export abstract class MemorySearchOrchestration extends MemoryKeywordRetrieval {",
        "  async search(query: string, opts?: MemoryIndexSearchOptions): Promise<MemorySearchResult[]> {",
        "        this.recordAutomaticRebuild();",
    ),
    "extensions/memory-core/src/memory/manager-database-context.ts": (
        "export class MemoryIndexDatabase {",
        "  async publishShadow(",
        '            type: "database.publish",',
    ),
    "extensions/memory-core/src/memory-rebuild-notice.ts": (
        "export function captureMemoryRebuildNotice(status: MemoryProviderStatus): () => string | undefined {",
        "  const sequence = notice?.sequence;",
        '    notice?.sequence !== sequence && typeof notice?.warning === "string"',
    ),
    "extensions/memory-core/src/memory-search-tool-query.ts": (
        "    params.onRebuildNotice?.(captureMemoryRebuildNotice(active.manager.status()));",
        "    const candidates = await active.manager.search(query.text, {",
    ),
    "extensions/memory-core/src/tools.ts": (
        "                onRebuildNotice: (read) => rebuildNotices.push(read),",
        "              automaticRebuildWarning: readRebuildWarning(),",
    ),
})
COMPILED_HASHES.update({
    "dist/extensions/memory-core/manager-runtime.js":
        "6ae8f02e229a5422d88dde59a6c070cce03e1ac9ffe5fa87172db8512f0eea0e",
    "dist/memory-rebuild-notice-9mxFMQoD.mjs":
        "cbbccbfb7f15644ca228606b8683e7ffe15fc0444d5bf422c164d326f4237e8f",
    "dist/tools-DotaQGXh.mjs":
        "c31b10a5ed25a1e02e5e7ac5be034b78906558c39350fd72be3f4c9edecc766e",
})
COMPILED_ANCHORS.update({
    "dist/extensions/memory-core/manager-runtime.js": (
        "var MemoryManagerSyncOps = class extends MemoryManagerSourceSyncOps {",
        "\trecordAutomaticRebuild() {",
        "\t\tthis.automaticRebuildNotice.sequence += 1;",
        "\tasync runSync(params) {",
        "var MemorySearchOrchestration = class extends MemoryKeywordRetrieval {",
        "var MemoryIndexManager = class MemoryIndexManager extends MemorySearchOrchestration {",
        "\t\tsuper(params.maintenanceSource?.automaticRebuildNotice);",
        "\tasync syncAdmitted(params, options) {",
        "\tasync publishShadow(input, assertCurrent) {",
        "export { MemoryIndexManager, closeAllMemoryIndexManagers, closeMemoryIndexManagersForAgent };",
    ),
    "dist/memory-rebuild-notice-9mxFMQoD.mjs": (
        "function captureMemoryRebuildNotice(status) {",
        "\tconst sequence = notice?.sequence;",
        '\treturn () => notice?.sequence !== sequence && typeof notice?.warning === "string" ? notice.warning : void 0;',
        "export { captureMemoryRebuildNotice as t };",
    ),
    "dist/tools-DotaQGXh.mjs": (
        'import { t as captureMemoryRebuildNotice } from "./memory-rebuild-notice-9mxFMQoD.mjs";',
        "\t\tparams.onRebuildNotice?.(captureMemoryRebuildNotice(active.manager.status()));",
        "\t\t\t\tcandidates: await active.manager.search(query.text, {",
    ),
})

ADDITIONAL_REQUIRED_HOST_ARTIFACTS = tuple(COMPILED_HASHES)


def authenticate_host_turn_barrier_owners(checkout: Path, runtime_root: Path) -> dict:
    """Authenticate the pinned full-caller inventory without executing its owners."""
    checkout, runtime_root = Path(checkout).absolute(), Path(runtime_root).absolute()
    base = prepare_host_restart_publication_bindings(checkout, runtime_root)
    sources = _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
    compiled = _owners(runtime_root, COMPILED_HASHES, COMPILED_ANCHORS, committed=False)
    return {
        "kind": "official-release-host-turn-barrier-owners",
        "operation": HOST_TURN_BARRIER_OPERATION,
        "referenceCommit": REFERENCE_COMMIT,
        "publicationHostOwners": base,
        "additionalSourceBindings": sources,
        "additionalCompiledBindings": compiled,
        "sourceBuildReproduced": False,
        "sourceFallbackAllowed": False,
        "sourceExecutionPermitted": False,
        "covers": [],
        "acceptancePointsAwarded": 0,
        "requiredLoadedArtifacts": list(ADDITIONAL_REQUIRED_HOST_ARTIFACTS),
        "requiredLoadedArtifactsMeaning": (
            "Import presence authenticates declarations, not execution. Actual full-caller "
            "admission, tool dispatch, source commit, natural publication and next-turn "
            "retrieval require independently validated runtime custody."
        ),
        "hostEntrypoint": {
            "path": "dist/agent-runner.runtime-BinSrYfK.mjs", "export": "runReplyAgent",
        },
        "admissionEntrypoint": {
            "path": "dist/session-entry-handle-BTUM17M1.mjs", "export": "a", "owner": "admitReplyTurn",
        },
        "coordinatorEntrypoints": {
            "path": "dist/coordinator-BinYGTDh.mjs",
            "exports": {
                "n": "createSessionMaintenanceOwner",
                "r": "waitForSessionMaintenance",
                "t": "beginForegroundSessionMaintenance",
            },
        },
        "maintenanceEntrypoint": {
            "path": "dist/run-C6ggOzT5.mjs", "export": "n", "owner": "scheduleSessionMaintenance",
        },
        "providerTransport": (
            "A declared scripted provider supplies model messages through the original "
            "provider registration and resolveProviderStreamFn. Original admission, "
            "embedded execution, tool implementations and maintenance owners remain unchanged."
        ),
        "automaticTurnBarrierVerified": False,
        "fullEmbeddedRunnerVerified": False,
        "producerApiParityClaimed": False,
        "forbiddenFixtureBarriers": [
            "manager.sync before follow-up", "manager.markMemoryWatchDirty before follow-up",
            "owner.reindex before follow-up", "forced maintenance drain before follow-up",
        ],
        "declarationLimits": [
            "This inventory is not runtime evidence and awards zero points.",
            "A supplied replyOperation bypasses runReplyAgent admission and cannot prove the natural chain.",
            "Manually invoking coordinator or scheduler helpers is not proof of actual caller execution.",
            "Pending optional maintenance, an already-running writer and delivery settlement are separate states.",
            "No independent build from the original source is claimed.",
        ],
    }


prepare_host_turn_barrier_bindings = authenticate_host_turn_barrier_owners
