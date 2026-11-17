"""Authenticate genuine history owners without granting helper-only behavioral credit."""
from copy import deepcopy
from pathlib import Path

from equivalence import prompt_runtime_context_bindings as prelude
from equivalence.session_admission_runtime_bindings import _named_link, _owners

REFERENCE_COMMIT = prelude.REFERENCE_COMMIT
OPERATION = "prompt-history-repair-runtime"
FIXTURE_PROVIDER_ID = prelude.FIXTURE_PROVIDER_ID

HISTORY_SOURCE_HASHES = {'src/agents/embedded-agent-runner/history.ts': 'f5e765c8eb914bd79c4910de248deee805c21651e94afc0805148ad4783dbd17',
 'src/agents/embedded-agent-runner/replay-history.ts': 'e35a7ba0a5ff74431b81bbfd775bbebe2267616ab2fbb482206158979cf6d244',
 'src/agents/embedded-agent-runner/run/attempt-history-prepare.ts': '6ad004bb0ddbeb9338224b30a9f0208a5c78ec6479eeb9680e79e8607e8daff4',
 'src/agents/embedded-agent-runner/run/attempt-execution-phase.ts': '8504ff1ff654f2b943fa9660e2bee0e57ce89a4647e701da3fba3516df6df7b8',
 'src/agents/session-transcript-repair.ts': '3e079db308f3d6df90a85ffb51b05a8e4fc567d5fac3928acd4ac7973ac0982b',
 'src/agents/embedded-agent-helpers/openai.ts': '851d3ee9938222da28080daa4971aa5382060b6149decee4402985995fe09f90',
 'src/agents/embedded-agent-helpers/turns.ts': '09758eadf30d707b0b2440ba4156adfa5ddb6a5ff4d0e4806884045a48210a45',
 'packages/agent-core/src/harness/session/tool-result-pairing.ts': '432a3ab386709ea2341f6f336c42eb78eae7ef323ff5f293a69ece53ebb1701b',
 'src/agents/tool-call-shared.ts': 'fdd8b099c66e45bc0cc95ed4e6b7ca4744a06b09564c3a916d23c2e192216c70',
 'src/shared/tool-block-contract.ts': 'c7b38e842e8b0d864ae3f4dcc79ca5f114f341986b27e942022ad26f6367739e',
 'src/agents/cache-trace.ts': '0b20b405586c83e3078ab5e4d98e8d6f815892244269c2f5ec80ad4378c2bc8e',
 'src/agents/queued-file-writer.ts': '9d900bdf67b675de89f1ce9854dfadeaf3e7ad92ef50a8c2f495eba70b1d9332',
 'src/agents/trace-base.ts': 'bf2606d6f9a2171b1e704601daa3648b208148462c29293d0e802718ec315df8',
 'src/agents/embedded-agent-runner/run/pre-persisted-user-turn.ts': '1f2513d3ef3308fc2f7e4d0a626c6e00d773404ace72f0db859125a3350a8a69',
 'packages/agent-core/src/harness/session/session.ts': 'b9da8aab7693741eec60cd43d3e33b36d91e2c2ad2afbc7695320c8bf838350e',
 'src/config/zod-schema.logging.ts': '968108a8264c21de8e5741295bfe8d9c6a6691e44da3776548460342ed951fb8'}
HISTORY_SOURCE_ANCHORS = {'src/agents/embedded-agent-runner/history.ts': ('export function '
                                                 'limitHistoryTurns(',
                                                 'export function '
                                                 'getHistoryLimitFromSessionKey(',
                                                 'const maxUserTurns = '
                                                 'Math.ceil(targetUserTurns * '
                                                 '1.5);'),
 'src/agents/embedded-agent-runner/replay-history.ts': ('export async function '
                                                        'sanitizeSessionHistory(params: '
                                                        '{',
                                                        'export async function '
                                                        'validateReplayTurns(params: '
                                                        '{',
                                                        'const '
                                                        'normalizedAssistantReplay '
                                                        '= '
                                                        'normalizeAssistantReplayContent(withInterSessionMarkers);',
                                                        'appendModelSnapshot(params.sessionManager, '
                                                        'currentSnapshot);'),
 'src/agents/embedded-agent-runner/run/attempt-history-prepare.ts': ('export '
                                                                     'async '
                                                                     'function '
                                                                     'prepareEmbeddedAttemptHistory(',
                                                                     'const '
                                                                     'prior = '
                                                                     'await '
                                                                     'sanitizeSessionHistory({',
                                                                     'const '
                                                                     'validated '
                                                                     '= await '
                                                                     'validateReplayTurns({',
                                                                     'getHistoryLimitFromSessionKey(attempt.sessionKey, '
                                                                     'attempt.config, '
                                                                     '{',
                                                                     'activeSession.agent.state.messages '
                                                                     '= '
                                                                     'limited;'),
 'src/agents/embedded-agent-runner/run/attempt-execution-phase.ts': ('export '
                                                                     'async '
                                                                     'function '
                                                                     'runEmbeddedAttemptExecutionPhase(',
                                                                     'preparedHistory '
                                                                     '= await '
                                                                     'prepareEmbeddedAttemptHistory(input);'),
 'src/agents/session-transcript-repair.ts': ('export function '
                                             'sanitizeToolCallInputs(',
                                             'export function '
                                             'sanitizeToolUseResultPairingForModel(',
                                             'export function '
                                             'repairToolUseResultPairing(',
                                             'erroredAssistantResultPolicy: '
                                             '"drop",'),
 'src/agents/embedded-agent-helpers/openai.ts': ('export function '
                                                 'normalizeOpenAIResponsesToolCallIds(',
                                                 'export function '
                                                 'downgradeOpenAIFunctionCallReasoningPairs(',
                                                 'export function '
                                                 'dropStaleOpenAIReasoning('),
 'src/agents/embedded-agent-helpers/turns.ts': ('export function '
                                                'shouldAllowProviderOwnedThinkingReplay(',
                                                'export function '
                                                'validateAnthropicTurns(',
                                                'export function '
                                                'validateGeminiTurns('),
 'packages/agent-core/src/harness/session/tool-result-pairing.ts': ('export '
                                                                    'function '
                                                                    'classifyToolUseResultPairing(',
                                                                    'export '
                                                                    'function '
                                                                    'makeMissingToolResult(',
                                                                    'failed: '
                                                                    'stopReason '
                                                                    '=== '
                                                                    '"error" '
                                                                    '|| '
                                                                    'stopReason '
                                                                    '=== '
                                                                    '"aborted",'),
 'src/agents/tool-call-shared.ts': ('export function '
                                    'createCompletedToolCallPredicate(',
                                    'export function isAllowedToolCallName('),
 'src/shared/tool-block-contract.ts': ('export function collectToolCallIds(',
                                       'export function '
                                       'isContractToolCallBlock('),
 'src/agents/cache-trace.ts': ('export function createCacheTrace(',
                               'const enabled = envEnabled ?? config?.enabled '
                               '?? false;',
                               'recordStage("stream:context", {'),
 'src/agents/queued-file-writer.ts': ('export function getQueuedFileWriter(',
                                      'flush: async () => {'),
 'src/agents/trace-base.ts': ('export function buildAgentTraceBase(',),
 'src/agents/embedded-agent-runner/run/pre-persisted-user-turn.ts': ('export '
                                                                     'async '
                                                                     'function '
                                                                     'preparePersistedCurrentUserTurn(',
                                                                     'export '
                                                                     'function '
                                                                     'reconcilePrePersistedCurrentUserTurn(',
                                                                     'params.activeSession.agent.state.messages '
                                                                     '= '
                                                                     'messages.slice(0, '
                                                                     '-1);'),
 'packages/agent-core/src/harness/session/session.ts': ('export function* '
                                                        'iterateSessionContextMessages<',
                                                        'export function '
                                                        'buildSessionContext(',
                                                        'Object.defineProperty(message, '
                                                        'SESSION_HISTORY_PRELUDE, '
                                                        '{'),
 'src/config/zod-schema.logging.ts': ('    cacheTrace: z',)}
HISTORY_COMPILED_HASHES = {'dist/session-transcript-repair-Dg5NBzYF.mjs': '0fc308b266f5edc6fe4a8cc45301e5a82a47d0ece7ffbf22e5274339ade036b7',
 'dist/tool-result-pairing-Cxh1CJVG.mjs': '15ac445c19df0a718696cd62b243153e5f78652e07492c3ad99b81d01dbdf190',
 'dist/tool-call-shared-DmcFgftS.mjs': '68964569f4b282ef4cde9e271fa1b7087772fe8ea01c918c3f91e64e2723000a',
 'dist/tool-block-contract-D4MRTdgi.mjs': 'cf7724026a5cc5931d8396abddd112d8b70c5b1a83b3a39785955ad60b1af466'}
HISTORY_COMPILED_ANCHORS = {'dist/session-transcript-repair-Dg5NBzYF.mjs': ('function '
                                                 'sanitizeToolCallInputs(',
                                                 'function '
                                                 'sanitizeToolUseResultPairingForModel(',
                                                 'function '
                                                 'repairToolUseResultPairing(',
                                                 'import { c as '
                                                 'extractToolResultIds, d as '
                                                 'normalizeLegacyToolResultId, '
                                                 'o as '
                                                 'extractToolCallsFromAssistant, '
                                                 'r as '
                                                 'classifyToolUseResultPairing, '
                                                 'u as makeMissingToolResult } '
                                                 'from '
                                                 '"./tool-result-pairing-Cxh1CJVG.mjs";'),
 'dist/tool-result-pairing-Cxh1CJVG.mjs': ('function '
                                           'classifyToolUseResultPairing(',
                                           'function makeMissingToolResult(',
                                           'failed: stopReason === "error" || '
                                           'stopReason === "aborted"'),
 'dist/tool-call-shared-DmcFgftS.mjs': ('function '
                                        'createCompletedToolCallPredicate(',
                                        'function isAllowedToolCallName('),
 'dist/tool-block-contract-D4MRTdgi.mjs': ('function collectToolCallIds(',
                                           'function isContractToolCallBlock(')}

SOURCE_HASHES = {**prelude.SOURCE_HASHES, **HISTORY_SOURCE_HASHES}
SOURCE_ANCHORS = {**prelude.SOURCE_ANCHORS, **HISTORY_SOURCE_ANCHORS}
COMPILED_HASHES = {**prelude.COMPILED_HASHES, **HISTORY_COMPILED_HASHES}
COMPILED_ANCHORS = {**prelude.COMPILED_ANCHORS, **HISTORY_COMPILED_ANCHORS}
COMPILED_ANCHORS["dist/builtin-openclaw-D1Xfnzzr.mjs"] = (
    *COMPILED_ANCHORS["dist/builtin-openclaw-D1Xfnzzr.mjs"],
    "async function prepareEmbeddedAttemptHistory(",
    "async function sanitizeSessionHistory(", "async function validateReplayTurns(",
    "function limitHistoryTurns(", "function getHistoryLimitFromSessionKey(",
    "function createCacheTrace(",
    'cacheTrace?.recordStage("session:sanitized", { messages: prior });',
    'cacheTrace?.recordStage("session:limited", { messages: limited });',
    'import { i as sanitizeToolUseResultPairingForModel, n as sanitizeToolCallInputs, r as sanitizeToolUseResultPairing, t as repairToolUseResultPairing } from "./session-transcript-repair-Dg5NBzYF.mjs";',
)
COMPILED_ANCHORS["dist/embedded-agent-helpers-CNzM9z5K.mjs"] = (
    *COMPILED_ANCHORS["dist/embedded-agent-helpers-CNzM9z5K.mjs"],
    "function normalizeOpenAIResponsesToolCallIds(",
    "function downgradeOpenAIFunctionCallReasoningPairs(",
    "function dropStaleOpenAIReasoning(",
)
REQUIRED_RUNTIME_ARTIFACTS = tuple(COMPILED_HASHES)
GENUINE_HELPER_EXPORTS = {
    "dist/helpers-DnieXpdv.mjs": ("m",),
    "dist/builtin-openclaw-D1Xfnzzr.mjs": ("t", "Y"),
    "dist/admitted-run-context-hIkojwNE.mjs": ("d",),
    "dist/date-time-B8B56dzx.mjs": ("a",),
    "dist/model-registry-CyECwbEb.mjs": ("i", "t"),
    "dist/session-accessor-CiKKTlbe.mjs": (
        "replaceSessionEntry", "replaceTranscriptEvents", "loadTranscriptEventsSync",
        "resolveSessionTranscriptDatabasePath", "loadSessionEntry"),
    "dist/transcript-header-CP-ow2Zr.mjs": ("t",),
    "dist/plugin-metadata-snapshot-DT_pRp6g.mjs": ("o",),
    "dist/loader-DpAS3szV.mjs": ("t",),
    "dist/runtime-9cxii0oQ.mjs": ("w",),
    "dist/registry-empty-BTjzcMW2.mjs": ("t",),
    "dist/plugin-sdk/config-runtime.js": ("setRuntimeConfigSnapshot", "clearRuntimeConfigSnapshot"),
    "dist/plugin-sdk/llm.js": ("createAssistantMessageEventStream",),
    "dist/extensions/memory-core/manager-runtime.js": ("closeAllMemoryIndexManagers",),
    "dist/openclaw-state-db-Dh2awMJ8.mjs": ("r",),
    "dist/plugin-state-store-BPUaLoVD.mjs": ("u",),
    "dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs": ("s",),
    "dist/memory-runtime-BzdCLKPx.mjs": ("i",),
    "dist/logger-Cn5hoa7J.mjs": ("n",),
    "dist/gateway-scheduler-TywODsdc.mjs": ("t",),
    "dist/agent-bundle-mcp-manager-api--Y4zt2wo.mjs": ("p", "i"),
    "dist/user-turn-transcript-Dig8rv9R.mjs": ("t",),
}
# Every required observation has a corresponding actual driver invocation.
# Transitive helpers are authenticated source/compiled owners, never direct scoring calls.
REQUIRED_OBSERVED_OWNERS = tuple(
    item for item in prelude.REQUIRED_OBSERVED_OWNERS
    if item[2] not in {"resolveCronStyleNow", "withMemoryWorkspacePreparation"}
) + (
    ("dist/plugin-sdk/config-runtime.js", "setRuntimeConfigSnapshot", "setRuntimeConfigSnapshot"),
    ("dist/plugin-sdk/config-runtime.js", "clearRuntimeConfigSnapshot", "clearRuntimeConfigSnapshot"),
)
NATIVE_ARTIFACTS = dict(prelude.NATIVE_ARTIFACTS)


def prepare_prompt_history_repair_bindings(checkout: Path, runtime_root: Path) -> dict:
    """Read-only source/artifact preflight; never import original runtime code."""
    checkout, runtime_root = Path(checkout).resolve(), Path(runtime_root).resolve()
    prior = prelude.prepare_prompt_runtime_context_bindings(checkout, runtime_root)
    sources, source_evidence = _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
    _, compiled_evidence = _owners(runtime_root, COMPILED_HASHES, COMPILED_ANCHORS, committed=False)
    prefix = "src/agents/embedded-agent-runner/run/"
    links = (
        (prefix + "attempt.ts", "./attempt-execution-phase.js", ("runEmbeddedAttemptExecutionPhase",)),
        (prefix + "attempt-execution-phase.ts", "./attempt-history-prepare.js", ("prepareEmbeddedAttemptHistory",)),
        (prefix + "attempt-history-prepare.ts", "../history.js", ("getHistoryLimitFromSessionKey", "limitHistoryTurns")),
        (prefix + "attempt-history-prepare.ts", "../replay-history.js", ("sanitizeSessionHistory", "validateReplayTurns")),
        (prefix + "attempt-history-prepare.ts", "../../session-transcript-repair.js", ("sanitizeToolUseResultPairingForModel",)),
        ("src/agents/embedded-agent-runner/replay-history.ts", "../session-transcript-repair.js", ("sanitizeToolCallInputs", "sanitizeToolUseResultPairingForModel", "stripToolResultDetails")),
        ("src/agents/embedded-agent-runner/replay-history.ts", "../embedded-agent-helpers.js", ("normalizeOpenAIResponsesToolCallIds", "downgradeOpenAIFunctionCallReasoningPairs", "dropStaleOpenAIReasoning")),
        ("src/agents/session-transcript-repair.ts", "../../packages/agent-core/src/harness/session/tool-result-pairing.js", ("classifyToolUseResultPairing", "makeMissingToolResult", "normalizeLegacyToolResultId")),
        (prefix + "attempt-session-runtime-prepare.ts", "../../cache-trace.js", ("createCacheTrace",)),
        ("src/agents/cache-trace.ts", "./queued-file-writer.js", ("getQueuedFileWriter",)),
    )
    result = deepcopy(prior)
    result.update({
        "kind": "official-release-prompt-history-repair-owners", "operation": OPERATION,
        "sourceBindings": source_evidence, "compiledBindings": compiled_evidence,
        "sourceImportLinks": [*prior["sourceImportLinks"], *[
            _named_link(sources, module, specifier, names, kind="import")
            for module, specifier, names in links]],
        "requiredLoadedArtifacts": list(REQUIRED_RUNTIME_ARTIFACTS),
        "genuineHelperExports": {name: list(exports) for name, exports in GENUINE_HELPER_EXPORTS.items()},
        "requiredObservedOwners": [list(item) for item in REQUIRED_OBSERVED_OWNERS],
        "diagnosticObservedOwners": [
            ["dist/helpers-DnieXpdv.mjs", "m", "resolveTranscriptPolicy.diagnostic"],
            ["dist/builtin-openclaw-D1Xfnzzr.mjs", "Y", "getHistoryLimitFromSessionKey.diagnostic"]],
        "diagnosticPolicyResolution": "After the admitted attempt only; never evidence of invocation inside that attempt and never independent integration proof",
        "providerTransport": "Original unchanged fixture provider createStreamFn; genuine unowned transport replay policies",
        "publicBoundary": "Every complete ordered message from every actual provider callback",
        "rawBoundary": "Whole provider requests/replies, real API outcomes and admission/loader returns; actual source cache-trace stages; original and subsequent durable events, SQL and lossless physical evidence",
        "historyProjectionOwner": "Original admitted embedded attempt sanitation, validation, public-config windowing, post-window repair and per-stream replay guards",
        "preludeOwner": "Canonical compaction events projected by original SessionManager; no authored prelude flags or compaction-lifecycle claim",
        "cacheTrace": {"config": "diagnostics.cacheTrace.enabled", "source": "src/agents/cache-trace.ts", "stages": ["session:loaded", "session:sanitized", "session:limited", "stream:context", "session:after"]},
        "standaloneHistoryHelpersCalledForCredit": False,
        "acceptancePointsAwarded": 0, "covers": [],
    })
    return result
