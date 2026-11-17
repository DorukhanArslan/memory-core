"""Authenticate the original embedded prompt prelude and its public runtime APIs.

Static ownership supplies no behavioral credit. Original committed source and
official published modules are authenticated independently; no reproduced build,
private prompt DTO, Inspector access or copied prompt kernel is authorized.
"""
import hashlib
from pathlib import Path

from equivalence import embedding_cache_lifecycle_bindings as host
from equivalence import model_runtime_bindings as model
from equivalence import session_reset_boundaries_bindings as reset
from equivalence.reference_bindings import _git
from equivalence.session_admission_runtime_bindings import _named_link, _owners

REFERENCE_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"
OPERATION = "prompt-runtime-context-runtime"
FIXTURE_PROVIDER_ID = "fixture-prompt-runtime-model"


def _select(names, values):
    return {name: values[name] for name in names}


_MODEL_SOURCES = [
    "src/agents/sessions/sdk.ts",
    "src/agents/sessions/agent-session-base.ts",
    "src/agents/sessions/session-manager.ts",
    "src/agents/sessions/session-manager-core.ts",
    "src/agents/sessions/session-manager-persistence.ts",
    "src/agents/sessions/model-registry.ts",
    "src/agents/sessions/auth-storage.ts",
    "src/agents/sessions/resource-loader.ts",
    "src/agents/sessions/settings-manager.ts",
    "packages/agent-core/src/harness/session/session.ts",
    "packages/agent-core/src/harness/messages.ts",
    "src/config/sessions/session-accessor.sqlite-read.ts",
    "src/config/sessions/session-accessor.sqlite-transcript-write.ts",
    "src/config/sessions/session-accessor.sqlite-transcript-header.ts",
    "src/config/sessions/transcript-header.ts",
    "src/config/sessions/version.ts",
    "src/config/runtime-snapshot.ts",
    "src/plugin-sdk/config-runtime.ts",
    "packages/llm-core/src/utils/event-stream.ts"
]
_HOST_SOURCES = [
    "src/plugins/plugin-metadata-snapshot.ts",
    "src/plugins/loader.ts",
    "src/plugins/loader-runtime-load.ts",
    "src/plugins/registry.ts",
    "src/plugins/registry-api.ts",
    "src/plugins/registry-registrars-providers.ts",
    "src/plugins/runtime.ts",
    "src/plugins/registry-empty.ts",
    "src/plugins/plugin-source-capture-path.ts",
    "src/plugins/plugin-source-capture-directory.ts",
    "src/plugins/plugin-package-metadata-capture.ts"
]
_EXTRA_SOURCE_HASHES = {
    "packages/agent-core/src/agent-stream-response.ts": "51a45aa652f8a7cb6325e2a520c5c7e7668962f9d865ea1ca9404edca6332bea",
    "src/agents/tool-call-id.ts": "5cad90a3ff7478c3ae39fe62cdf6f6c01c637989ad115c6990f9f8f461afa3fc",
    "src/agents/transcript-policy.ts": "bf2bb906e44e8e8fc07b093456581021f0dc9baa22d593bbb1ba65e9fb31871c",
    "src/agents/embedded-agent-helpers/images.ts": "a39cf919d7bdc8bbc8ce5dc697c71fec13b1c686f641301882938b48d0f5a24c",
    "src/agents/embedded-agent-runner/run/attempt-stream.ts": "97a8459dbfe30f37767854bde6ce53ce280edbf3ffa8331fb6d31791f0bddd54",
    "src/agents/embedded-agent-runner/run/attempt-tool-call-replay-sanitization.ts": "67c04274eea92dce61cf6986cdd65106a8ab37e2ac767bf344724d7161657109",
    "src/agents/embedded-agent-runner/run/attempt-history.ts": "4f3237d29082e51e0289b2910e9378e861e30d92649754e6e4f1f8b0aa4eec8b",
    "src/agents/harness/builtin-openclaw.ts": "250eacd91f5dd7073cdc1229534f1d638f7579fa8ade8315d7481fe84179ad1e",
    "src/agents/harness/builtin-openclaw-metadata.ts": "420f1c5b200ccd229eac21505a7913321a0f323421d88b83c1cc68ba8b719104",
    "src/agents/admitted-run-context.ts": "3c773ae41741661e2354ce18e47c4fd0f8c31d553d3a92524f5988bbf4aa4a04",
    "src/agents/embedded-agent-runner/run/attempt.ts": "dc29b5a469b2e84a43fedb67fdd690093d2842080a08246179de3d2680ae3781",
    "src/agents/embedded-agent-runner/run/attempt-setup.ts": "f1312aaa50fa3385acb9273c93703e293e95b91d4dafc1e03753f41ca954bafe",
    "src/agents/embedded-agent-runner/run/attempt-session-prepare.ts": "e32977bad2203fb5683cb07b859346c7658ebfd19fd12e17c64e1cb185ce4e3b",
    "src/agents/embedded-agent-runner/run/attempt-session-runtime-prepare.ts": "9d369ff9b8f26fddd93378fe3cc651e318673e51702c912e174b5cb040158d38",
    "src/agents/embedded-agent-runner/run/attempt-system-prompt-prepare.ts": "55221977201bf389589f65fd33bcf9da1575904ec3dc51ed0fe196867c5351de",
    "src/agents/embedded-agent-runner/run/attempt-system-prompt.ts": "d2e40045c8fd76051acfec14b4f27dbe856f8b26cebc097954e8ca5944a5b96b",
    "src/agents/embedded-agent-runner/run/attempt-prompt-build.ts": "b9e42fc2b03715744eda0da3431169cc729ecf3fde144b4dd6e37342e4e7a77a",
    "src/agents/embedded-agent-runner/run/attempt-prompt-submit.ts": "91d72acf733ec2defc9b66841cce3c5670cbe6520c227fdb5b7ebe040cdd0867",
    "src/agents/embedded-agent-runner/run/attempt-llm-boundary.ts": "6da9c2597018b27b496d14d22a70e6cfff91a4a9dd398f781b83748ecbe0f041",
    "src/agents/embedded-agent-runner/run/runtime-context-prompt.ts": "69e82242918c567188a5a8a65f1651c45253e5deb6c50c728599902cc410f6d0",
    "src/agents/internal-runtime-context.ts": "22afc06e907f9216a89e63081636e4696da0a8904bf66ebe21b40f9aca2b9585",
    "src/agents/system-prompt.ts": "951e09f7704838361b236fbe650ea67cff0890d821e91f9bec811694cf724cb1",
    "src/agents/system-prompt-params.ts": "75ae5d5c17409685dcf6758bdbdabe87b29cb60217d972af1a613fa5b387615e",
    "src/agents/memory-prompt-prepare.ts": "28cb57428f44f97bf5eb0c10e2faeb48dd576021f7aa98e7c7ce7de9355ab5d3",
    "src/plugins/memory-state.ts": "b334c9eed9bbb43c54560515a62511b6ff5ea77a044c584d0ea029670ad37229",
    "src/plugins/memory-runtime.ts": "da358078fa03863c13493eab3cc4f2d1010cbb2f93d0f6faaab30c55930a797e",
    "extensions/memory-core/index.ts": "407649ff3005ec692a1c3d15e7e599692e693bf3e6ccbdc7e4aa18755deddd89",
    "extensions/memory-core/src/memory-tool-contract.ts": "6d1649776d4a73729b36facd8ef5cdc6d77e443b719c736ecedd9c9ea6f48191",
    "src/agents/current-time.ts": "189cfac9eced3467df51b8cc683736723c1b7dad60505b95b66fd0db1272978f",
    "src/agents/date-time.ts": "051a17e9166dcafd666930f5975045da8400d31a968fc6b2103ef57bc8675e47",
    "src/agents/embedded-agent-runner/run/attempt-stream-prepare.ts": "52451e6d1dbf1b0e04a3cfe23a3f0b036cc0eb16d40763d3703298055b5e3552",
    "src/agents/sessions/agent-session-prompting.ts": "0198fd57164d9d79fdd5bfb897ebbd6b00b781bd732e96c541ab14da6b07f387",
    "src/plugins/provider-plugin.types.ts": "7f657fd81fae9d950a61b3cf06b4108f14eae9b1b2529f7fa89759a49b2a176b",
    "src/plugins/provider-runtime.ts": "b209db16ccf0845faa417e8bca7da4c7afbbf1d4b6a66919d246e2c458d62ffd"
}
_EXTRA_SOURCE_ANCHORS = {
    "src/agents/tool-call-id.ts": [
        "function sanitizeToolCallId(", "export function sanitizeToolCallIdsForCloudCodeAssist(",
        'return alphanumericOnly.length > 0 ? alphanumericOnly : "sanitizedtoolid";'
    ],
    "src/agents/transcript-policy.ts": [
        "function buildUnownedProviderTransportReplayFallback(", "export function resolveTranscriptPolicy(",
        'const isStrictOpenAiCompatible = params.modelApi === "openai-completions";',
        'toolCallIdMode: "strict" as const,'
    ],
    "src/agents/embedded-agent-helpers/images.ts": [
        "export async function sanitizeSessionMessagesImages(",
        "? sanitizeToolCallIdsForCloudCodeAssist(messages, options.toolCallIdMode, {"
    ],
    "src/agents/embedded-agent-runner/run/attempt-stream.ts": [
        "if (shouldApplyReplayToolCallIdSanitizer(replayToolCallIdSanitizerDecision)) {",
        "sanitizeReplayToolCallIdsForStream({"
    ],
    "src/agents/embedded-agent-runner/run/attempt-tool-call-replay-sanitization.ts": [
        "export function shouldApplyReplayToolCallIdSanitizer(",
        "export function sanitizeReplayToolCallIdsForStream(",
        "return sanitizeToolCallIdsForCloudCodeAssist(paired, params.mode, {"
    ],
    "src/agents/embedded-agent-runner/run/attempt-history.ts": [
        "export function resolveAttemptTranscriptPolicy(",
        "params.runtimePlan?.transcript.resolvePolicy(params.runtimePlanModelContext) ??"
    ],
    "packages/agent-core/src/agent-stream-response.ts": [
        "function ensureToolTurnIdentity(",
        "if (!executable || message.responseId?.trim() || message.turnId?.trim()) {",
        "const finalMessage = prepareAssistantMessage(\n            ensureToolTurnIdentity("
    ],
    "src/agents/harness/builtin-openclaw.ts": [
        "export function createOpenClawAgentHarness("
    ],
    "src/agents/harness/builtin-openclaw-metadata.ts": [
        "export const BUILTIN_AGENT_HARNESS_METADATA"
    ],
    "src/agents/admitted-run-context.ts": [
        "export function prepareSystemAgentRunAdmission("
    ],
    "src/agents/embedded-agent-runner/run/attempt.ts": [
        "export async function runEmbeddedAttempt("
    ],
    "src/agents/embedded-agent-runner/run/attempt-setup.ts": [
        "export async function prepareEmbeddedAttemptSetup("
    ],
    "src/agents/embedded-agent-runner/run/attempt-session-prepare.ts": [
        "export async function prepareEmbeddedAttemptAgentSession(",
        "export async function prepareEmbeddedAttemptSessionManager("
    ],
    "src/agents/embedded-agent-runner/run/attempt-session-runtime-prepare.ts": [
        "export async function prepareEmbeddedAttemptSessionRuntime("
    ],
    "src/agents/embedded-agent-runner/run/attempt-system-prompt-prepare.ts": [
        "export async function prepareEmbeddedAttemptSystemPrompt("
    ],
    "src/agents/embedded-agent-runner/run/attempt-system-prompt.ts": [
        "export function buildAttemptSystemPrompt("
    ],
    "src/agents/embedded-agent-runner/run/attempt-prompt-build.ts": [
        "export async function prepareEmbeddedAttemptPromptAssembly(",
        "export async function prepareEmbeddedAttemptPromptContext("
    ],
    "src/agents/embedded-agent-runner/run/attempt-prompt-submit.ts": [
        "export async function submitEmbeddedAttemptPrompt("
    ],
    "src/agents/embedded-agent-runner/run/attempt-llm-boundary.ts": [
        "export function normalizeMessagesForLlmBoundary(",
        "export function installRuntimeContextMessageForPrompt("
    ],
    "src/agents/embedded-agent-runner/run/runtime-context-prompt.ts": [
        "export function resolveRuntimeContextPromptParts(",
        "export function prependRuntimeContextForModel(",
        "export function buildRuntimeContextCustomMessage("
    ],
    "src/agents/internal-runtime-context.ts": [
        "export const OPENCLAW_RUNTIME_CONTEXT_CUSTOM_TYPE = \"openclaw.runtime-context\";",
        "export function stripHistoricalRuntimeContextCustomMessages<T>("
    ],
    "src/agents/system-prompt.ts": [
        "export function buildAgentSystemPrompt("
    ],
    "src/agents/system-prompt-params.ts": [
        "export function buildSystemPromptParams("
    ],
    "src/agents/memory-prompt-prepare.ts": [
        "export async function prepareAgentMemoryPrompt("
    ],
    "src/plugins/memory-state.ts": [
        "export async function prepareMemoryPromptSection(",
        "export function buildMemoryPromptSection(",
        "function buildSynchronousMemoryPromptSection("
    ],
    "src/plugins/memory-runtime.ts": [
        "export async function closeActiveMemorySearchManagersCore(",
        "function listCurrentMemoryRuntimes(",
        "runPluginCleanup(runtime, () => runtime.closeAllMemorySearchManagers?.())"
    ],
    "extensions/memory-core/index.ts": [
        "    api.registerMemoryCapability({"
    ],
    "extensions/memory-core/src/memory-tool-contract.ts": [
        "export function buildMemoryPromptSection({"
    ],
    "src/agents/current-time.ts": [
        "export function resolveCronStyleNow(",
        "export function appendCronStyleCurrentTimeLine("
    ],
    "src/agents/date-time.ts": [
        "export function resolveUserTimezone(",
        "export function buildTemporalContextText("
    ],
    "src/agents/embedded-agent-runner/run/attempt-stream-prepare.ts": [
        "export function prepareEmbeddedAttemptStream("
    ],
    "src/agents/sessions/agent-session-prompting.ts": [
        "export const agentSessionQueuePromptContext:"
    ],
    "src/plugins/provider-plugin.types.ts": [
        "  createStreamFn?:"
    ],
    "src/plugins/provider-runtime.ts": [
        "export function resolveProviderStreamFn("
    ]
}
_SETUP_SOURCES = (
    "extensions/memory-core/src/memory/manager-runtime.ts",
    "extensions/memory-core/src/memory/manager.ts",
    "src/config/sessions/session-accessor.ts",
    "src/config/sessions/session-accessor.entry.ts",
    "src/config/sessions/session-accessor.sqlite-entry.ts",
    "src/config/sessions/session-accessor.transcript-target.ts",
    "src/state/openclaw-state-db.ts",
    "src/state/openclaw-agent-db-lifecycle.ts",
    "src/plugin-state/plugin-state-store.ts",
    "src/plugin-state/plugin-state-store.sqlite.ts",
    "src/logging/logger.ts",
    "src/infra/fs-safe.ts",
    "extensions/memory-core/src/memory-workspace-lock.ts",
    "extensions/memory-core/src/short-term-promotion-record.ts",
)
_EXTRA_SOURCE_HASHES.update({
    "src/infra/gateway-scheduler.ts": "53c5a46e4cbe447b6b58daefe30f977dae8d06cd2f44b359fca0962617fc120d",
    "src/agents/agent-bundle-mcp-manager-api.ts": "9ba61b7b03f548a451e1688434c9885d3f429ef930784f5090c498876162b2de",
    "src/plugins/registry-registrars-tools-hooks.ts": "d29cd0106955926ed8aca1757a73e5a7b19f9b9ed3aa032aec2b4f15ea1e1b4c",
})
_EXTRA_SOURCE_ANCHORS.update({
    "src/infra/gateway-scheduler.ts": ("export class GatewayScheduler {",),
    "src/agents/agent-bundle-mcp-manager-api.ts": (
        "export function setSessionMcpRuntimeScheduler(",
        "export async function disposeAllSessionMcpRuntimes(",
    ),
    "src/plugins/registry-registrars-tools-hooks.ts": (
        "export function createToolHookRegistrars(", "  const registerTypedHook = ",
    ),
})
_EXTRA_SOURCE_HASHES.update({
    "src/sessions/user-turn-transcript.ts": "7bc3d9eed2c6b994158dec7b4fd2eaaac746b2e314df79abe38a60f37a2203b5",
    "src/sessions/user-turn-transcript.message.ts": "1170716e5498aa455963adbf76bbf010339f33e582544d449b1280290415bd57",
    "src/sessions/user-turn-transcript.metadata.ts": "d008f43b68b6696bf27c3804f7a547b817a9fd3738960259e943271d5560681b",
    "src/sessions/user-turn-transcript.types.ts": "4ef301d73448712876a7c6f8a7de34813e70da6065cfff4e258f95f3bb082362",
    "src/sessions/transcript-events.ts": "d30ec2f89cd11b8df52adf3bb4078ddd38ce322deea3fd2cdfabb0344b497373",
    "src/agents/session-tool-result-guard.ts": "174aa005b10c2b55dcbe36152843e8da31cdcc9d8bfe4e4e38efbc34a3b74e90",
    "src/plugins/plugin-api.types.ts": "c6515e735827ea2f0b8a69d9eb9073a5e45ce819c09bf0a99d89e6b5aed3de6d",
    "src/plugins/hook-types.ts": "ab35f763d4258089fb055e8fa1ff5f30aa9592bb63b6d2a31aee854c7679732d",
    "src/plugins/hooks.ts": "3ce3f5ca3810be4a48d6934c38b1a34bfdec9cb5d36ccbdec1dab12406494b86"
})
_EXTRA_SOURCE_ANCHORS.update({
    "src/sessions/user-turn-transcript.ts": [
        "export function createUserTurnTranscriptRecorder("
    ],
    "src/sessions/user-turn-transcript.message.ts": [
        "export function buildPersistedUserTurnMessage(",
        "export function resolvePersistedUserTurnMessage("
    ],
    "src/sessions/user-turn-transcript.metadata.ts": [
        "export function buildRunUserTurnIdempotencyKey(",
        "export function preparePersistedUserTurnMessageForTranscriptWrite("
    ],
    "src/sessions/user-turn-transcript.types.ts": [
        "export type CreateUserTurnTranscriptRecorderParams = {",
        "export type UserTurnTranscriptRecorder = {"
    ],
    "src/sessions/transcript-events.ts": [
        "export function attachSessionTranscriptRunId<T>("
    ],
    "src/agents/session-tool-result-guard.ts": [
        "    const runOwnedMessage = attachSessionTranscriptRunId(message, transcriptRunId);"
    ],
    "src/plugins/plugin-api.types.ts": [
        "export type OpenClawPluginApi = {",
        "  on: <K extends PluginHookName>("
    ],
    "src/plugins/hook-types.ts": [
        "export type PluginHookBeforeToolCallEvent = {",
        "export type PluginHookAfterToolCallEvent = {",
        "export type PluginHookHandlerMap = {"
    ],
    "src/plugins/hooks.ts": [
        "export function createHookRunner(",
        "  async function runBeforeToolCall(",
        "  async function runAfterToolCall("
    ]
})
SOURCE_HASHES = {
    **_select(_MODEL_SOURCES, model.SOURCE_HASHES),
    **_select(_HOST_SOURCES, host.SOURCE_HASHES),
    **_select(_SETUP_SOURCES, reset.SOURCE_HASHES),
    **_EXTRA_SOURCE_HASHES,
}
SOURCE_ANCHORS = {
    **_select(_MODEL_SOURCES, model.SOURCE_ANCHORS),
    **_select(_HOST_SOURCES, host.SOURCE_ANCHORS),
    **_select(_SETUP_SOURCES, reset.SOURCE_ANCHORS),
    **_EXTRA_SOURCE_ANCHORS,
}

_MODEL_COMPILED = [
    "dist/resource-loader-DhipPm1N.mjs",
    "dist/resource-loader-N7_h4_No.mjs",
    "dist/session-manager-a8MFS1Kk.mjs",
    "dist/session-BA9qunLx.mjs",
    "dist/model-registry-CyECwbEb.mjs",
    "dist/session-accessor-CiKKTlbe.mjs",
    "dist/session-accessor.sqlite-read-BsSfe2AE.mjs",
    "dist/session-accessor.sqlite-transcript-write-C5YumkFZ.mjs",
    "dist/session-accessor.sqlite-transcript-header-BrRgLK61.mjs",
    "dist/transcript-header-CP-ow2Zr.mjs",
    "dist/runtime-snapshot-BFi3jxlO.mjs",
    "dist/plugin-sdk/config-runtime.js",
    "dist/plugin-sdk/llm.js",
    "dist/llm-ASoRyt-k.mjs"
]
_HOST_COMPILED = [
    "dist/plugin-metadata-snapshot-DT_pRp6g.mjs",
    "dist/loader-DpAS3szV.mjs",
    "dist/loader-runtime-load-DpgEqnzx.mjs",
    "dist/runtime-9cxii0oQ.mjs",
    "dist/registry-empty-BTjzcMW2.mjs"
]
_EXTRA_COMPILED_HASHES = {
    "dist/agent-core-DrCkPXML.mjs": "44500635166e55c16d9a66f9ddc277cd6cee17b764184b82118b445ac82732eb",
    "dist/tool-call-id-D6Bs5Pq7.mjs": "afb563a6b904e335b48c13849c01413e6de105f0b39697045dcc7c00ac02edd9",
    "dist/helpers-DnieXpdv.mjs": "991682b731606542b7dbbac43b45f080b5e52e889b1e2a41bc0c29f9f721cacc",
    "dist/embedded-agent-helpers-CNzM9z5K.mjs": "73d0194fa72a0d8b072130585a8e78f40a57fa92777d9371930d15dd3f8b6e59",
    "dist/history-image-prune-VTygPOF7.mjs": "b81ffd42c4b3a0e6be199aa36260bd3833f2521f95190dd681a8efb77d98b0aa",
    "dist/builtin-openclaw-D1Xfnzzr.mjs": "cde1b380d227ffe432d5597e0a7422df5241b459df7150a9564bb0b7cec84953",
    "dist/admitted-run-context-hIkojwNE.mjs": "83fd79543af64e8e69570f8c4891420e9e6e7f0d420820db65d6467f09593cb7",
    "dist/runtime-context-prompt-K3ClPtvW.mjs": "b84d2d7f2fa322e98e6178f4ca28b2361d236dc4334957f1fd9fcac16980c814",
    "dist/internal-runtime-context-CLIwiurx.mjs": "a6e7da42e62adc06a94df4b27ae8365a358502faa32c4d649d1e288b0c42cc29",
    "dist/system-prompt-params-BxQn8CFS.mjs": "a2b7636601bddbacc9056a027c67a978a3773c1444c43cdc0a5c16906b457b41",
    "dist/memory-state-BmtUbXjH.mjs": "ed71931d904089353576180357a71c99a6a976b6e300b381b0be943298c9bc4f",
    "dist/memory-runtime-BzdCLKPx.mjs": "bcfdf870307c0ea827682a6bef89e5c3170d09a2b818c9cbae7f3ce17920fd18",
    "dist/extensions/memory-core/index.js": "ead9aeb06b76504ba8ab9cb50a03c1425d18cbb936285c47f5ae7cf25e2877f8",
    "dist/memory-tool-contract-DOz26L8b.mjs": "caa1cf11748ff19c561d94a321ffff564fdfbd357bc8954e09f50ed6844bb063",
    "dist/current-time-CgCswWtv.mjs": "a393fe167a107166d4add3868bc8f90dc44d1859364bf99f9115d7b42fa2fdca",
    "dist/date-time-B8B56dzx.mjs": "594dc7447a252288c396ff30006af4d143aa2ec8de2ba55a457e097fcca6811e",
    "dist/provider-runtime-BHqCdO9o.mjs": "c546dc4f068c84a318fb13fff99a15f0b0871065ded276ca7d81c3efd11d751c"
}
_EXTRA_COMPILED_ANCHORS = {
    "dist/tool-call-id-D6Bs5Pq7.mjs": [
        "function sanitizeToolCallId(", "function sanitizeToolCallIdsForCloudCodeAssist(",
        'return alphanumericOnly.length > 0 ? alphanumericOnly : "sanitizedtoolid";',
        "sanitizeToolCallIdsForCloudCodeAssist as r"
    ],
    "dist/helpers-DnieXpdv.mjs": [
        "function buildUnownedProviderTransportReplayFallback(", "function resolveTranscriptPolicy(",
        'const isStrictOpenAiCompatible = params.modelApi === "openai-completions";',
        'toolCallIdMode: "strict"', "resolveTranscriptPolicy as m"
    ],
    "dist/embedded-agent-helpers-CNzM9z5K.mjs": [
        "async function sanitizeSessionMessagesImages(",
        "const sanitizedIds = options?.sanitizeToolCallIds === true ? sanitizeToolCallIdsForCloudCodeAssist(",
        "sanitizeSessionMessagesImages as c"
    ],
    "dist/history-image-prune-VTygPOF7.mjs": [
        "function resolveAttemptTranscriptPolicy(", "resolveAttemptTranscriptPolicy as c",
        'import { m as resolveTranscriptPolicy } from "./helpers-DnieXpdv.mjs";'
    ],
    "dist/agent-core-DrCkPXML.mjs": [
        "function ensureToolTurnIdentity(",
        "message.responseId?.trim() || message.turnId?.trim()) return message;",
        "const finalMessage = prepareAssistantMessage(ensureToolTurnIdentity(removeNonExecutableToolCalls({"
    ],
    "dist/builtin-openclaw-D1Xfnzzr.mjs": [
        "function createOpenClawAgentHarness(",
        "async function runEmbeddedAttempt(",
        "async function prepareEmbeddedAttemptSetup(",
        "async function prepareEmbeddedAttemptPromptContext(",
        "async function submitEmbeddedAttemptPrompt(",
        "function normalizeMessagesForLlmBoundary(",
        "function sanitizeReplayToolCallIdsForStream(",
        "if (shouldApplyReplayToolCallIdSanitizer(replayToolCallIdSanitizerDecision)) {",
        "session.agent.streamFn = wrapStreamFnWithMessageTransform(session.agent.streamFn, (messages, model) => sanitizeReplayToolCallIdsForStream({"
    ],
    "dist/admitted-run-context-hIkojwNE.mjs": [
        "function prepareSystemAgentRunAdmission(",
        "prepareSystemAgentRunAdmission as d"
    ],
    "dist/runtime-context-prompt-K3ClPtvW.mjs": [
        "function resolveRuntimeContextPromptParts(",
        "function buildRuntimeContextCustomMessage(",
        "function prependRuntimeContextForModel("
    ],
    "dist/internal-runtime-context-CLIwiurx.mjs": [
        "function stripHistoricalRuntimeContextCustomMessages(",
        "function escapeInternalRuntimeContextDelimiters("
    ],
    "dist/system-prompt-params-BxQn8CFS.mjs": [
        "function buildSystemPromptParams(",
        "function buildAgentSystemPrompt("
    ],
    "dist/memory-state-BmtUbXjH.mjs": [
        "async function prepareMemoryPromptSection(",
        "function buildMemoryPromptSection(",
        "function buildSynchronousMemoryPromptSection("
    ],
    "dist/memory-runtime-BzdCLKPx.mjs": [
        "async function closeActiveMemorySearchManagersCore(",
        "closeActiveMemorySearchManagersCore as i",
        "runPluginCleanup(runtime, () => runtime.closeAllMemorySearchManagers?.())"
    ],
    "dist/extensions/memory-core/index.js": [
        "api.registerMemoryCapability({",
        "export { memory_core_default as default };"
    ],
    "dist/memory-tool-contract-DOz26L8b.mjs": [
        "function buildMemoryPromptSection(",
        "buildMemoryPromptSection as r"
    ],
    "dist/current-time-CgCswWtv.mjs": [
        "function resolveCronStyleNow(",
        "function appendCronStyleCurrentTimeLine("
    ],
    "dist/date-time-B8B56dzx.mjs": [
        "function resolveUserTimezone(",
        "function buildTemporalContextText("
    ],
    "dist/provider-runtime-BHqCdO9o.mjs": [
        "function resolveProviderStreamFn(",
        "resolveProviderStreamFn as O"
    ]
}
_SETUP_COMPILED = (
    "dist/extensions/memory-core/manager-runtime.js",
    "dist/session-accessor.sqlite-entry-BrsmAX-T.mjs",
    "dist/session-accessor.transcript-target-vG-nGtYV.mjs",
    "dist/openclaw-state-db-Dh2awMJ8.mjs",
    "dist/plugin-state-store-BPUaLoVD.mjs",
    "dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs",
    "dist/logger-Cn5hoa7J.mjs",
    "dist/fs-safe-CHQXnCPk.mjs",
    "dist/short-term-promotion-record-CEpBdgKW.mjs",
    "dist/short-term-promotion-record-DrLa1fiO.mjs",
    "dist/dreaming-dreams-file-BJzlZFlf.mjs",
)
_EXTRA_COMPILED_HASHES.update({
    "dist/gateway-scheduler-TywODsdc.mjs": "92a674af56f14b9340a1c80b9f3ac0ffe8b454d97a1fa4af9a2186a4eac9fc6e",
    "dist/agent-bundle-mcp-manager-api--Y4zt2wo.mjs": "e4ac019e8a97a7468ce59cd8a8764b2fa24123cb2b30b7f72f14a5533653c9fd",
})
_EXTRA_COMPILED_ANCHORS.update({
    "dist/gateway-scheduler-TywODsdc.mjs": (
        "var GatewayScheduler = class {", "export { GatewayScheduler as t };",
    ),
    "dist/agent-bundle-mcp-manager-api--Y4zt2wo.mjs": (
        "function setSessionMcpRuntimeScheduler(", "async function disposeAllSessionMcpRuntimes(",
    ),
})
_EXTRA_COMPILED_HASHES.update({
    "dist/user-turn-transcript-Dig8rv9R.mjs": "652a1b122293b705b6548f015e8abc3383dba5b307d9129a696c390b42a2ce63",
    "dist/user-turn-transcript.message-Bb1TX1Le.mjs": "fedb377ec1e751125ef784dc0c20ab1e7350e85d2f8157e714315a212fc4cd20",
    "dist/user-turn-transcript.metadata-C4MejEIQ.mjs": "33b3ac629c74aa598f590c33d0eebccecb74c447ffcdb8dc1fac7bf71bc1b791",
    "dist/transcript-events-Ce9wKss8.mjs": "3c002577a318257953fa5b1ba10cd16b83c99fca869e4058469a4f274a897c51",
    "dist/hooks-3uEO1KNL.mjs": "90606030c454dba75918959c8717f99ca29fb91ce0430d9765ac515fd8b6e045"
})
_EXTRA_COMPILED_ANCHORS.update({
    "dist/user-turn-transcript-Dig8rv9R.mjs": [
        "function createUserTurnTranscriptRecorder(",
        "export { createUserTurnTranscriptRecorder as t };"
    ],
    "dist/user-turn-transcript.message-Bb1TX1Le.mjs": [
        "function buildPersistedUserTurnMessage(",
        "function resolvePersistedUserTurnMessage("
    ],
    "dist/user-turn-transcript.metadata-C4MejEIQ.mjs": [
        "function buildRunUserTurnIdempotencyKey(",
        "function preparePersistedUserTurnMessageForTranscriptWrite("
    ],
    "dist/transcript-events-Ce9wKss8.mjs": [
        "function attachSessionTranscriptRunId(", "attachSessionTranscriptRunId as t"
    ],
    "dist/hooks-3uEO1KNL.mjs": [
        "function createHookRunner(",
        "async function runBeforeToolCall(",
        "async function runAfterToolCall("
    ]
})
COMPILED_HASHES = {
    **_select(_MODEL_COMPILED, model.COMPILED_HASHES),
    **_select(_HOST_COMPILED, host.COMPILED_HASHES),
    **_select(_SETUP_COMPILED, reset.COMPILED_HASHES),
    **_EXTRA_COMPILED_HASHES,
}
COMPILED_ANCHORS = {
    **_select(_MODEL_COMPILED, model.COMPILED_ANCHORS),
    **_select(_HOST_COMPILED, host.COMPILED_ANCHORS),
    **_select(_SETUP_COMPILED, reset.COMPILED_ANCHORS),
    **_EXTRA_COMPILED_ANCHORS,
}
COMPILED_ANCHORS["dist/resource-loader-DhipPm1N.mjs"] = (
    *COMPILED_ANCHORS["dist/resource-loader-DhipPm1N.mjs"],
    'import { t as Agent } from "./agent-core-DrCkPXML.mjs";',
    'import { c as resolveTerminalAssistantTranscriptRunId, t as attachSessionTranscriptRunId } from "./transcript-events-Ce9wKss8.mjs";',
    "const runOwnedMessage = attachSessionTranscriptRunId(message, transcriptRunId);",
)

# These are semantic owners loaded by the genuine embedded prelude. The official
# release manifest independently authenticates every other transitive module.
REQUIRED_RUNTIME_ARTIFACTS = tuple(COMPILED_HASHES)
GENUINE_HELPER_EXPORTS = {
    "dist/tool-call-id-D6Bs5Pq7.mjs": ("r",),
    "dist/helpers-DnieXpdv.mjs": ("m",),
    "dist/embedded-agent-helpers-CNzM9z5K.mjs": ("c",),
    "dist/history-image-prune-VTygPOF7.mjs": ("c",),
    "dist/builtin-openclaw-D1Xfnzzr.mjs": ("t",),
    "dist/admitted-run-context-hIkojwNE.mjs": ("d",),
    "dist/runtime-context-prompt-K3ClPtvW.mjs": ("c", "i", "o", "s"),
    "dist/internal-runtime-context-CLIwiurx.mjs": ("a", "f", "r", "t", "n"),
    "dist/memory-tool-contract-DOz26L8b.mjs": ("r",),
    "dist/memory-state-BmtUbXjH.mjs": ("f", "n"),
    "dist/memory-runtime-BzdCLKPx.mjs": ("i",),
    "dist/current-time-CgCswWtv.mjs": ("n", "t"),
    "dist/date-time-B8B56dzx.mjs": ("a", "n", "o", "r", "t"),
    "dist/system-prompt-params-BxQn8CFS.mjs": ("t",),
    "dist/provider-runtime-BHqCdO9o.mjs": ("O",),
    "dist/model-registry-CyECwbEb.mjs": ("i", "t"),
    "dist/session-manager-a8MFS1Kk.mjs": ("t",),
    "dist/session-BA9qunLx.mjs": ("t", "u"),
    "dist/session-accessor-CiKKTlbe.mjs": (
        "replaceSessionEntry", "replaceTranscriptEvents", "loadTranscriptEventsSync",
        "resolveSessionTranscriptDatabasePath",),
    "dist/transcript-header-CP-ow2Zr.mjs": ("t",),
    "dist/extensions/memory-core/index.js": ("default",),
    "dist/plugin-metadata-snapshot-DT_pRp6g.mjs": ("o",),
    "dist/loader-DpAS3szV.mjs": ("t",),
    "dist/runtime-9cxii0oQ.mjs": ("w",),
    "dist/registry-empty-BTjzcMW2.mjs": ("t",),
    "dist/plugin-sdk/config-runtime.js": ("setRuntimeConfigSnapshot", "clearRuntimeConfigSnapshot"),
    "dist/plugin-sdk/llm.js": ("createAssistantMessageEventStream",),
    "dist/extensions/memory-core/manager-runtime.js": ("MemoryIndexManager", "closeAllMemoryIndexManagers"),
    "dist/openclaw-state-db-Dh2awMJ8.mjs": ("r",),
    "dist/plugin-state-store-BPUaLoVD.mjs": ("u",),
    "dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs": ("s",),
    "dist/logger-Cn5hoa7J.mjs": ("n",),
    "dist/gateway-scheduler-TywODsdc.mjs": ("t",),
    "dist/agent-bundle-mcp-manager-api--Y4zt2wo.mjs": ("p", "i"),
    "dist/user-turn-transcript-Dig8rv9R.mjs": ("t",),
    "dist/transcript-events-Ce9wKss8.mjs": ("t",),
    "dist/dreaming-dreams-file-BJzlZFlf.mjs": ("_",),
}
# Distinct driver observations: returned methods share their genuine factory
# owner, while available exports supply no evidence of actual calls on their own.
REQUIRED_OBSERVED_OWNERS = (
    ("dist/builtin-openclaw-D1Xfnzzr.mjs", "t", "createOpenClawAgentHarness"),
    ("dist/builtin-openclaw-D1Xfnzzr.mjs", "t", "OpenClawAgentHarness.runAttempt"),
    ("dist/admitted-run-context-hIkojwNE.mjs", "d", "prepareSystemAgentRunAdmission"),
    ("dist/current-time-CgCswWtv.mjs", "n", "resolveCronStyleNow"),
    ("dist/date-time-B8B56dzx.mjs", "a", "resolveUserTimeFormat"),
    ("dist/transcript-header-CP-ow2Zr.mjs", "t", "createSessionTranscriptHeader"),
    ("dist/session-accessor-CiKKTlbe.mjs", "replaceSessionEntry", "replaceSessionEntry"),
    ("dist/session-accessor-CiKKTlbe.mjs", "replaceTranscriptEvents", "replaceTranscriptEvents"),
    ("dist/session-accessor-CiKKTlbe.mjs", "loadTranscriptEventsSync", "loadTranscriptEventsSync"),
    ("dist/session-accessor-CiKKTlbe.mjs", "resolveSessionTranscriptDatabasePath", "resolveSessionTranscriptDatabasePath"),
    ("dist/model-registry-CyECwbEb.mjs", "i", "AuthStorage.inMemory"),
    ("dist/model-registry-CyECwbEb.mjs", "t", "ModelRegistry.inMemory"),
    ("dist/model-registry-CyECwbEb.mjs", "t", "ModelRegistry.registerProvider"),
    ("dist/openclaw-state-db-Dh2awMJ8.mjs", "r", "openOpenClawStateDatabase"),
    ("dist/memory-runtime-BzdCLKPx.mjs", "i", "closeActiveMemorySearchManagersCore"),
    ("dist/extensions/memory-core/manager-runtime.js", "closeAllMemoryIndexManagers", "closeAllMemoryIndexManagers"),
    ("dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs", "s", "closeOpenClawAgentDatabasesAsync"),
    ("dist/plugin-state-store-BPUaLoVD.mjs", "u", "closePluginStateDatabaseAsync"),
    ("dist/logger-Cn5hoa7J.mjs", "n", "flushLogger"),
    ("dist/user-turn-transcript-Dig8rv9R.mjs", "t", "createUserTurnTranscriptRecorder"),
    ("dist/dreaming-dreams-file-BJzlZFlf.mjs", "_", "withMemoryWorkspacePreparation"),
)
NATIVE_ARTIFACTS = dict(reset.NATIVE_ARTIFACTS)


def prepare_prompt_runtime_context_bindings(checkout: Path, runtime_root: Path) -> dict:
    """Verify source/artifact bytes without importing an original runtime owner."""
    checkout, runtime_root = Path(checkout).resolve(), Path(runtime_root).resolve()
    if _git(checkout, "rev-parse", "HEAD").decode().strip() != REFERENCE_COMMIT:
        raise ValueError("Prompt runtime context requires the exact original source commit")
    sources, source_evidence = _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
    _, compiled_evidence = _owners(runtime_root, COMPILED_HASHES, COMPILED_ANCHORS, committed=False)
    native_evidence = []
    for (package, relative), expected in NATIVE_ARTIFACTS.items():
        filename = runtime_root.parent.parent / package / relative
        if (not filename.is_file() or filename.is_symlink()
                or not filename.resolve().is_relative_to(runtime_root.parent.resolve())
                or hashlib.sha256(filename.read_bytes()).hexdigest() != expected):
            raise ValueError("The original prompt prelude fs-safe native artifact changed")
        native_evidence.append({"package": package, "path": relative, "sha256": expected,
                                "nativeBuildReproduced": False})
    prefix = "src/agents/embedded-agent-runner/run/"
    links = (
        ("src/agents/harness/builtin-openclaw.ts", "../embedded-agent-runner/run/attempt.js",
         ("runEmbeddedAttempt",)),
        (prefix + "attempt.ts", "./attempt-setup.js", ("prepareEmbeddedAttemptSetup",)),
        (prefix + "attempt.ts", "./attempt-session-runtime-prepare.js",
         ("prepareEmbeddedAttemptSessionRuntime",)),
        (prefix + "attempt-session-prepare.ts", "./attempt-history.js", ("resolveAttemptTranscriptPolicy",)),
        (prefix + "attempt-history.ts", "../../transcript-policy.js", ("resolveTranscriptPolicy",)),
        (prefix + "attempt-stream.ts", "./attempt-tool-call-replay-sanitization.js",
         ("sanitizeReplayToolCallIdsForStream", "shouldApplyReplayToolCallIdSanitizer")),
        (prefix + "attempt-tool-call-replay-sanitization.ts", "../../tool-call-id.js",
         ("sanitizeToolCallIdsForCloudCodeAssist",)),
        ("src/agents/embedded-agent-helpers/images.ts", "../tool-call-id.js",
         ("sanitizeToolCallIdsForCloudCodeAssist",)),
        (prefix + "attempt-session-runtime-prepare.ts", "./attempt-session-prepare.js",
         ("prepareEmbeddedAttemptAgentSession", "prepareEmbeddedAttemptSessionManager")),
        (prefix + "attempt-prompt-build.ts", "./runtime-context-prompt.js",
         ("resolveRuntimeContextPromptParts", "buildRuntimeContextCustomMessage")),
        (prefix + "attempt-llm-boundary.ts", "./runtime-context-prompt.js",
         ("projectRuntimeContextFragments",)),
        ("src/agents/memory-prompt-prepare.ts", "../plugins/memory-state.js",
         ("prepareMemoryPromptSection",)),
        ("src/agents/system-prompt.ts", "../plugins/memory-state.js", ("buildMemoryPromptSection",)),
        ("src/plugins/memory-runtime.ts", "./memory-state.js",
         ("getMemoryRuntime", "resolveMemoryCapabilityRegistration", "setStandaloneMemoryManagerActive")),
        ("extensions/memory-core/index.ts", "./src/memory-tool-contract.js",
         ("resolveMemoryToolContext", "buildMemoryPromptSection")),
        ("src/agents/sessions/sdk.ts", "./model-registry.js", ("ModelRegistry",)),
        ("src/agents/sessions/sdk.ts", "./session-manager.js", ("SessionManager",)),
        ("src/plugins/registry.ts", "./registry-api.js", ("createPluginApiFactory",)),
        ("src/sessions/user-turn-transcript.ts", "./user-turn-transcript.message.js",
         ("buildLateResolvedMediaMessage", "isUserMessage", "resolvePersistedUserTurnMessage")),
        ("src/sessions/user-turn-transcript.ts", "./user-turn-transcript.metadata.js",
         ("buildRunUserTurnIdempotencyKey", "preparePersistedUserTurnMessageForTranscriptWrite")),
        ("src/agents/session-tool-result-guard.ts", "../sessions/transcript-events.js",
         ("attachSessionTranscriptRunId",)),
    )
    return {
        "kind": "official-release-prompt-runtime-context-owners", "operation": OPERATION,
        "referenceCommit": REFERENCE_COMMIT, "sourceBuildReproduced": False, "sourceFallbackAllowed": False,
        "sourceBindings": source_evidence, "compiledBindings": compiled_evidence,
        "nativeArtifacts": native_evidence,
        "sourceImportLinks": [_named_link(sources, module, specifier, names, kind="import")
                              for module, specifier, names in links],
        "requiredLoadedArtifacts": list(REQUIRED_RUNTIME_ARTIFACTS),
        "genuineHelperExports": {name: list(exports) for name, exports in GENUINE_HELPER_EXPORTS.items()},
        "genuineReturnedMethods": {
            "dist/builtin-openclaw-D1Xfnzzr.mjs": {"export": "t", "methods": ["runAttempt"]}},
        "requiredObservedOwners": [list(owner) for owner in REQUIRED_OBSERVED_OWNERS],
        "observedOwnerManifestFinalized": bool(REQUIRED_OBSERVED_OWNERS),
        "fixtureProviderId": FIXTURE_PROVIDER_ID, "harnessConstructed": True, "realEmbeddedPrelude": True,
        "providerTransport": "Original plugin registration and createStreamFn callback transport",
        "publicBoundary": (
            "Complete effective memory guidance lines, all five tool-availability booleans, "
            "the whole Cron clock DTO or null, and whole actual provider messages"),
        "rawBoundary": (
            "Entire original system prompt, tools, requests and replies; harness/admission/loader "
            "returns, genuine tool hooks, recorder returns and transcript persistence evidence"),
        "physicalHostLinkScope": "Only the original plugin source capture's authenticated host-package symlink",
        "clockFixture": {"owner": "node:test", "apis": ["Date"], "schedulerReplaced": False},
        "acceptancePointsAwarded": 0, "covers": [],
    }
