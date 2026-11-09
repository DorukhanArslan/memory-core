"""Pinned original declarations for the explicit mixed turn-trust runtime.

Only the approved zero-dependency taint state executes from unchanged source.
Other critical owners execute the official compiled release. Declaration links
are provenance, not proof of a full embedded runner or provider execution.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from equivalence.reference_bindings import _git
from equivalence.session_admission_runtime_bindings import _owners, _named_link
from equivalence.transcript_boundary_runtime_bindings import (
    prepare_transcript_boundary_runtime_bindings, REQUIRED_BOUNDARY_ARTIFACTS,
    SQLITE_BOUNDARY_ARTIFACTS, TRANSCRIPT_WORKER_ARTIFACTS, TRANSCRIPT_WORKER_PARENT_ARTIFACTS,
)
from equivalence.turn_trust_source_authority import prepare_turn_taint_source_authority

REFERENCE_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"

SOURCE_HASHES = {'src/agents/embedded-agent-runner/run/turn-taint-state.ts': '7fd28e4064c555256feeaace2dbabb8b08d31ce1e0d7baaf1a1d7b20380723fe',
 'src/agents/embedded-agent-runner/run-loop.ts': '9c0cda106a202e42a1514cf829428767a02f8b39bde1fe70221641a0556b86d9',
 'src/agents/agent-tools.ts': 'bdcad2054268bf84d89439a5473224118c504a3eb36e1961d6454c09f9d4a391',
 'src/agents/core-coding-tools.ts': '64fb003174fb93c22e8de032006cbc67aadee8bbd565f718846c577808d4902b',
 'src/agents/agent-tools.before-tool-call.ts': '6f7f389c3de0a80e3cf8252252e448f5ed46b561fdb81b2463dcd4b0e293b2d4',
 'src/agents/agent-tools.before-tool-call.wrapper.ts': 'e5291b503723ba40ab621f2d079edbe974c987e6a2b9f121ac2db27fc2b0358c',
 'src/agents/agent-tools.before-tool-call.diagnostics.ts': '9e0aa53a994605b3f7c87dccb62dd95524fd830f7e3b180d3445ef5772991cc1',
 'src/agents/agent-tools.before-tool-call.runtime.ts': 'f4d0b4ff0f3ef1cde818d6dc6d07b90af9e09347f554b812453191b62cce98a6',
 'src/agents/tool-loop-detection.ts': 'b917baf4a27decc7fed0ce2d9a34cfd49982e91962f3147d3647169c4ef21066',
 'src/logging/diagnostic-session-state.ts': 'e6d387acd8c72764c9f7cfba699a9e3716a2b4d3ddde230329c89987621054d7',
 'src/agents/memory-write-provenance.ts': '628c004d93b38b06108d426750ca1ef1e8459c108202d0568b18e4c02bfebd13',
 'src/memory/memory-artifact-provenance.ts': '68f4d030c3d6025e390065c296a74f94d46b177497e03655e7820e26215fb373',
 'src/plugin-state/plugin-state-store.ts': '361e7571e9c93efde048462fd967e845c6e68a7a9f7a9c6f9a0823b6cad8b530',
 'src/agents/agent-tools.read.ts': '34db04c4719a01d2b173c690498707e42c2dc8d1b8f6b1bca211fce9c08e3a6a',
 'src/agents/sessions/tools/write.ts': 'e305091da36b3ed8b9af0d358ed3047592721780b569d65ab587f751eaf20b57',
 'src/plugin-sdk/agent-core.ts': '36923c1bfeef3df3271659521acb32f0769666563c589da864e01c35c0335171',
 'packages/agent-core/src/index.ts': 'a1bcf6fbaf46e7bfba3fa04313b8c66f3da1a1226e6f31b0263db695d7028de2',
 'packages/agent-core/src/agent-loop.ts': 'c16d96af6a900d9a8540955336d43fb66c98810a92aa0693127f1bef35a1164e',
 'packages/agent-core/src/agent-stream-response.ts': '51a45aa652f8a7cb6325e2a520c5c7e7668962f9d865ea1ca9404edca6332bea',
 'packages/llm-core/src/utils/event-stream.ts': 'c04b8859e2ffe373cf796d997f964b6dddff637711188d4befc1111282942dbd',
 'src/config/sessions/session-accessor.sqlite-transcript-message-append.ts': '6cbf0606d549cd2fae2e80e63181a0ff81e2eebfe32f8f93f4593d3832947618',
 'src/config/sessions/session-accessor.sqlite-transcript-header.ts': '05c4ad331965633ecf0cd850fa7b3e4e1072b62b2728d14f2175a4a5f8dcf79c',
 'src/config/sessions/transcript-header.ts': 'df2f0da864f5c642bc2b2f76332525d8dab52feb282fd959247acf99f55bc0b7',
 'src/config/sessions/version.ts': '39a17391fd9d6c7e73d6ea619a04c8fc47c674f70ec14e0bb4d1786f1e2fc3d3',
 'src/config/sessions/session-accessor.sqlite-transcript-anchor.ts': 'e2db126148df6df03a8c09cb628f58130ba34d70b5088817f2446699c316ae74',
 'src/config/sessions/session-accessor.sqlite-transcript-store.ts': 'e658ffefb7c1c8cfc6ad4c416d8f2f20657cb59f8412eac951e1d8e564afa50d'}

SOURCE_ANCHORS = {'src/agents/embedded-agent-runner/run/turn-taint-state.ts': ('export function '
                                                              'createAgentTurnTaintState(initiallyTainted = '
                                                              'false) {',),
 'src/agents/embedded-agent-runner/run-loop.ts': ('  const turnTaintState = '
                                                  'createAgentTurnTaintState(params.initialTurnTainted === true);',
                                                  '    turnTaintState.observe(observation);'),
 'src/agents/agent-tools.ts': ('export function createOpenClawCodingTools(',
                               'export function createOpenClawCodingToolsInternal(',
                               '    resolveOriginClass: () =>'),
 'src/agents/core-coding-tools.ts': ('export function createCoreCodingTools(options: CoreCodingToolsOptions): '
                                     'AnyAgentTool[] {',),
 'src/agents/agent-tools.before-tool-call.ts': ('  wrapToolWithBeforeToolCallHook,',),
 'src/agents/agent-tools.before-tool-call.wrapper.ts': ('export function wrapToolWithBeforeToolCallHook(',),
 'src/agents/agent-tools.before-tool-call.diagnostics.ts': ('export async function recordLoopOutcome(args: {',
                                                            '    args.ctx.onToolOutcome?.(recordedOutcome);'),
 'src/agents/agent-tools.before-tool-call.runtime.ts': ('export const beforeToolCallRuntime = {',),
 'src/agents/tool-loop-detection.ts': ('export function recordToolCallOutcome(',),
 'src/logging/diagnostic-session-state.ts': ('export function getDiagnosticSessionState(ref: SessionRef): '
                                             'SessionState {',),
 'src/agents/memory-write-provenance.ts': ('export function createMemoryWriteProvenanceObserver(params: {',
                                           'export function withMemoryWriteProvenance<T extends '
                                           'ProvenanceWriteOperations>('),
 'src/memory/memory-artifact-provenance.ts': ('export async function recordMemoryArtifactWriteProvenance(params: '
                                              '{',
                                              'export async function readMemoryArtifactProvenance(params: {',
                                              'export async function listMemoryArtifactProvenance(params: {'),
 'src/plugin-state/plugin-state-store.ts': ('export function createCorePluginStateKeyedStore<T>(',),
 'src/agents/agent-tools.read.ts': ('export function createHostWorkspaceWriteTool(',),
 'src/agents/sessions/tools/write.ts': ('export function createWriteTool(',),
 'src/plugin-sdk/agent-core.ts': ('export { runAgentLoop } from "../../packages/agent-core/src/index.js";',),
 'packages/agent-core/src/index.ts': ('export * from "./agent-loop.js";',),
 'packages/agent-core/src/agent-loop.ts': ('export async function runAgentLoop(',
                                           'function withAssistantTurnTaint(message: AssistantMessage, tainted: '
                                           'boolean): AssistantMessage {',
                                           'function withToolResultContentSource('),
 'packages/agent-core/src/agent-stream-response.ts': ('export async function streamAgentResponse(',),
 'packages/llm-core/src/utils/event-stream.ts': ('export function createAssistantMessageEventStream(): '
                                                 'AssistantMessageEventStream {',),
 'src/config/sessions/session-accessor.sqlite-transcript-message-append.ts': ('export function '
                                                                              'appendTranscriptMessageInTransaction',
                                                                              'export function '
                                                                              'prepareTranscriptMessageAppend'),
 'src/config/sessions/session-accessor.sqlite-transcript-header.ts': ('export function ensureTranscriptHeader(',),
 'src/config/sessions/transcript-header.ts': ('export function createSessionTranscriptHeader(',),
 'src/config/sessions/version.ts': ('export const CURRENT_SESSION_VERSION = 4;',),
 'src/config/sessions/session-accessor.sqlite-transcript-anchor.ts': ('export function '
                                                                      'createTranscriptEntryAnchor(',),
 'src/config/sessions/session-accessor.sqlite-transcript-store.ts': ('export function '
                                                                     'appendTranscriptEventInTransaction(',)}

COMPILED_HASHES = {'dist/plugin-sdk/agent-core.js': '354eb73c79096ca4761431cb7fd85d9756a352219fdc3f1187a4ae9607e36af1',
 'dist/agent-core-DrCkPXML.mjs': '44500635166e55c16d9a66f9ddc277cd6cee17b764184b82118b445ac82732eb',
 'dist/llm-ASoRyt-k.mjs': '00a1ffd0459c90d077d3f245633d4ac94d145901ed56b62112cb84cb94aab01f',
 'dist/agent-tools-HIqp3eTk.mjs': '9887e5788b6d88cf3c9a7a5581548d52b5f208fccd2694a01df8bb75017cd702',
 'dist/core-coding-tools-DMPT-DjL.mjs': 'de2d807cb25075f8347888fcac51a907efcd971cedd6fce60c042d7d5201c80e',
 'dist/agent-tools.before-tool-call-Cg8vCu9u.mjs': '69abb7861a76913024828b0a7fd1948fc72081f9a8c91b629d0bc06e966f49c5',
 'dist/agent-tools.before-tool-call.runtime.js': '64f74bcc77d386854f7bb46c030dc01caf081073e3220251ba49f18ed3225811',
 'dist/agent-tools.before-tool-call.runtime-DrbwqsOU.mjs': '88be9b0b2e1dcdc921606bc9a829bbd6a28ee4c088a1ea0bfab8d2f4a2f4ec46',
 'dist/tool-loop-detection-mkeiOPtW.mjs': 'd413a8d62300079502cb4d1dd66137b8d8dbde93779179121afc2713a9167b6b',
 'dist/diagnostic-session-state-DpvjzgzY.mjs': 'a26fa1dc18a7e2dd7575aceb976b8d0730031f41235eea762c43c4795c7820e4',
 'dist/agent-tools.read-ZzkirzL1.mjs': 'bec516044e956d92b1297b154a48ef9ee75e83dfdfe79b8dda5668a9995e778c',
 'dist/tools-DLW3vi8k.mjs': '100134d5d22981dcad305e470b30c6e8296e6ef7e034bcc2cabc502552c91b02',
 'dist/memory-artifact-provenance-DhnyWiV1.mjs': 'd9058a906197fbec520df32a63257e4bb24b084223aa35871c64e71d1e8c464c',
 'dist/plugin-state-store-BPUaLoVD.mjs': '4d010227d5baea72f1dfc1e117efe2cc1eb596eeab579e6c92c047abf75f7efc',
 'dist/session-accessor.sqlite-transcript-write-guard-OsMLicSE.mjs': '252ed9e8717da3b64bee74c0948425d77519bf520b1e131e381d985ec4fb73a0',
 'dist/session-accessor.sqlite-transcript-header-BrRgLK61.mjs': '26e983f0f600c413613e54b7c8978db7defc046c8bd4a542e75764209e969a95',
 'dist/transcript-header-CP-ow2Zr.mjs': '4adbb6f0a5d024dd72cff7e77b6ef8ddeec3f7955399980fc421e8c815844608',
 'dist/session-accessor.sqlite-transcript-anchor-BRfT_bMM.mjs': 'dbe095833b6deabf938291cab994d3361534731fa78fbab80e60226727c01393',
 'dist/session-accessor.sqlite-transcript-store-DEXEZWnC.mjs': 'deb4cca4a9d2fc66702e5adc2f3882f620e8d1533fbe7107a7cd95869d54cf5e'}

COMPILED_ANCHORS = {'dist/plugin-sdk/agent-core.js': ('u as runAgentLoop } from "../agent-core-DrCkPXML.mjs";', ' runAgentLoop,'),
 'dist/agent-core-DrCkPXML.mjs': ('async function runAgentLoop(prompts, context, config, emit, signal, streamFn, '
                                  'runtime) {',
                                  'function withAssistantTurnTaint(message, tainted) {',
                                  'runAgentLoop as u'),
 'dist/llm-ASoRyt-k.mjs': ('function createAssistantMessageEventStream() {',
                           'createAssistantMessageEventStream as x'),
 'dist/agent-tools-HIqp3eTk.mjs': ('function createOpenClawCodingTools(options) {',
                                   'createOpenClawCodingTools as t'),
 'dist/core-coding-tools-DMPT-DjL.mjs': ('function createCoreCodingTools(options) {',),
 'dist/agent-tools.before-tool-call-Cg8vCu9u.mjs': ('function wrapToolWithBeforeToolCallHook(tool, ctx, '
                                                    'options = {}) {',
                                                    'async function recordLoopOutcome(args) {',
                                                    'wrapToolWithBeforeToolCallHook as l'),
 'dist/agent-tools.before-tool-call.runtime.js': ('export * from '
                                                  '"./agent-tools.before-tool-call.runtime-DrbwqsOU.mjs";',),
 'dist/agent-tools.before-tool-call.runtime-DrbwqsOU.mjs': ('const beforeToolCallRuntime = {',),
 'dist/tool-loop-detection-mkeiOPtW.mjs': ('function recordToolCallOutcome(state, params) {',),
 'dist/diagnostic-session-state-DpvjzgzY.mjs': ('function getDiagnosticSessionState(ref) {',),
 'dist/agent-tools.read-ZzkirzL1.mjs': ('function createMemoryWriteProvenanceObserver(params) {',
                                        'function withMemoryWriteProvenance(operations, observer) {',
                                        'function createHostWorkspaceWriteTool(root, options) {',
                                        'createMemoryWriteProvenanceObserver as p'),
 'dist/tools-DLW3vi8k.mjs': ('function createWriteTool(cwd, options) {',),
 'dist/memory-artifact-provenance-DhnyWiV1.mjs': ('async function recordMemoryArtifactWriteProvenance(params) {',
                                                  'async function readMemoryArtifactProvenance(params) {',
                                                  'async function listMemoryArtifactProvenance(params) {'),
 'dist/plugin-state-store-BPUaLoVD.mjs': ('function createCorePluginStateKeyedStore(options) {',),
 'dist/session-accessor.sqlite-transcript-write-guard-OsMLicSE.mjs': ('function '
                                                                      'appendTranscriptMessageInTransaction(',
                                                                      'function prepareTranscriptMessageAppend('),
 'dist/session-accessor.sqlite-transcript-header-BrRgLK61.mjs': ('function ensureTranscriptHeader(',),
 'dist/transcript-header-CP-ow2Zr.mjs': ('function createSessionTranscriptHeader(',),
 'dist/session-accessor.sqlite-transcript-anchor-BRfT_bMM.mjs': ('function createTranscriptEntryAnchor(',),
 'dist/session-accessor.sqlite-transcript-store-DEXEZWnC.mjs': ('function appendTranscriptEventInTransaction(',)}

SOURCE_HASHES['src/agents/sessions/tools/index.ts'] = 'c03a89f8258623e2a7df15334be63f92526fd80d404bf3c38debfa4fd8b41e22'
SOURCE_ANCHORS['src/agents/sessions/tools/index.ts'] = ('  createWriteTool,',)

SOURCE_LINKS = (
    ("src/agents/embedded-agent-runner/run-loop.ts", "./run/turn-taint-state.js", ("createAgentTurnTaintState",), "import"),
    ("src/agents/agent-tools.ts", "./memory-write-provenance.js", ("createMemoryWriteProvenanceObserver",), "import"),
    ("src/agents/agent-tools.ts", "./core-coding-tools.js", ("createCoreCodingTools",), "import"),
    ("src/agents/core-coding-tools.ts", "./agent-tools.read.js", ("createHostWorkspaceWriteTool",), "import"),
    ("src/agents/agent-tools.read.ts", "./memory-write-provenance.js", ("withMemoryWriteProvenance",), "import"),
    ("src/agents/agent-tools.read.ts", "./sessions/tools/index.js", ("createWriteTool",), "import"),
    ("src/agents/sessions/tools/index.ts", "./write.js", ("createWriteTool",), "export"),
    ("src/agents/memory-write-provenance.ts", "../memory/memory-artifact-provenance.js",
     ("recordMemoryArtifactWriteProvenance", "normalizeMemoryArtifactRelativePath"), "import"),
    ("src/memory/memory-artifact-provenance.ts", "../plugin-state/plugin-state-store.js", ("createCorePluginStateKeyedStore",), "import"),
    ("src/agents/agent-tools.before-tool-call.ts", "./agent-tools.before-tool-call.wrapper.js", ("wrapToolWithBeforeToolCallHook",), "export"),
    ("src/agents/agent-tools.before-tool-call.wrapper.ts", "./agent-tools.before-tool-call.diagnostics.js", ("recordLoopOutcome",), "import"),
    ("src/agents/agent-tools.before-tool-call.runtime.ts", "./tool-loop-detection.js", ("recordToolCallOutcome",), "import"),
    ("src/agents/agent-tools.before-tool-call.runtime.ts", "../logging/diagnostic-session-state.js", ("getDiagnosticSessionState",), "import"),
    ("src/plugin-sdk/agent-core.ts", "../../packages/agent-core/src/index.js", ("runAgentLoop",), "export"),
    ("packages/agent-core/src/agent-loop.ts", "./agent-stream-response.js", ("streamAgentResponse",), "import"),
    ("src/config/sessions/session-accessor.sqlite-transcript-message-append.ts", "./session-accessor.sqlite-transcript-header.js", ("ensureTranscriptHeader",), "import"),
    ("src/config/sessions/session-accessor.sqlite-transcript-message-append.ts", "./session-accessor.sqlite-transcript-store.js", ("appendTranscriptEventInTransaction",), "import"),
    ("src/config/sessions/session-accessor.sqlite-transcript-header.ts", "./transcript-header.js", ("createSessionTranscriptHeader",), "import"),
    ("src/config/sessions/transcript-header.ts", "./version.js", ("CURRENT_SESSION_VERSION",), "import"),
)
LITERAL_SOURCE_LINKS = (
    ("packages/agent-core/src/index.ts", 'export * from "./agent-loop.js";', "export-all"),
    ("src/agents/agent-tools.before-tool-call.diagnostics.ts", '() => import("./agent-tools.before-tool-call.runtime.js"),', "dynamic-import"),
)

AGENT_LOOP_ARTIFACTS = (
    "dist/plugin-sdk/agent-core.js", "dist/agent-core-DrCkPXML.mjs", "dist/llm-ASoRyt-k.mjs",
)
TURN_TOOL_ARTIFACTS = (
    "dist/agent-tools-HIqp3eTk.mjs", "dist/core-coding-tools-DMPT-DjL.mjs",
    "dist/agent-tools.before-tool-call-Cg8vCu9u.mjs", "dist/agent-tools.before-tool-call.runtime.js",
    "dist/agent-tools.before-tool-call.runtime-DrbwqsOU.mjs", "dist/tool-loop-detection-mkeiOPtW.mjs",
    "dist/diagnostic-session-state-DpvjzgzY.mjs", "dist/agent-tools.read-ZzkirzL1.mjs",
    "dist/tools-DLW3vi8k.mjs", "dist/memory-artifact-provenance-DhnyWiV1.mjs",
    "dist/plugin-state-store-BPUaLoVD.mjs",
)
APPEND_ARTIFACTS = (
    "dist/session-accessor.sqlite-transcript-write-C5YumkFZ.mjs",
    "dist/session-accessor.sqlite-transcript-write-guard-OsMLicSE.mjs",
    "dist/session-accessor.sqlite-transcript-header-BrRgLK61.mjs", "dist/transcript-header-CP-ow2Zr.mjs",
    "dist/session-accessor.sqlite-transcript-anchor-BRfT_bMM.mjs",
    "dist/session-accessor.sqlite-transcript-store-DEXEZWnC.mjs",
)
PERSISTENCE_ARTIFACTS = tuple(dict.fromkeys((*SQLITE_BOUNDARY_ARTIFACTS, *APPEND_ARTIFACTS)))
READ_PROJECTION_ARTIFACTS = tuple(dict.fromkeys((*REQUIRED_BOUNDARY_ARTIFACTS, *SQLITE_BOUNDARY_ARTIFACTS)))
REQUIRED_TURN_TRUST_ARTIFACTS = tuple(dict.fromkeys((
    *AGENT_LOOP_ARTIFACTS, *TURN_TOOL_ARTIFACTS, *PERSISTENCE_ARTIFACTS, *READ_PROJECTION_ARTIFACTS,
)))


class TurnTrustBindingError(ValueError):
    """A reviewed original turn-taint, write-provenance or persistence owner changed."""


def prepare_turn_trust_runtime_bindings(checkout: Path, runtime_root: Path) -> dict:
    checkout, runtime_root = Path(checkout).resolve(), Path(runtime_root).resolve()
    try:
        if (_git(checkout, "rev-parse", "HEAD").decode().strip() != REFERENCE_COMMIT
                or Path(_git(checkout, "rev-parse", "--show-toplevel").decode().strip()).resolve() != checkout
                or _git(checkout, "status", "--porcelain", "--untracked-files=no").strip()):
            raise TurnTrustBindingError("Turn trust requires the unchanged pinned original checkout.")
        source_authority = prepare_turn_taint_source_authority(checkout)
        reused = prepare_transcript_boundary_runtime_bindings(checkout, runtime_root)
        sources, source_evidence = _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
        _, compiled = _owners(runtime_root, COMPILED_HASHES, COMPILED_ANCHORS, committed=False)
        links = [_named_link(sources, module, specifier, names, kind=kind)
                 for module, specifier, names, kind in SOURCE_LINKS]
        for module, declaration, kind in LITERAL_SOURCE_LINKS:
            if sources[module].count(declaration) != 1:
                raise TurnTrustBindingError("An original public barrel or lazy outcome-owner import changed.")
            links.append({"path": module, "kind": kind, "declaration": declaration,
                          "line": sources[module][:sources[module].index(declaration)].count("\n") + 1,
                          "declarationSha256": hashlib.sha256(declaration.encode()).hexdigest()})
    except (OSError, UnicodeError, ValueError) as error:
        raise TurnTrustBindingError("Original turn trust source/release provenance could not be verified.") from error
    return {
        "kind": "mixed-original-source-and-official-release-turn-trust",
        "referenceCommit": REFERENCE_COMMIT, "sourceBuildReproduced": False,
        "wholeRuntimeCompiled": False, "approvedSourceTaintAuthority": source_authority,
        "sourceTaintExecutionRequired": True, "otherRuntimeOwners": "official compiled release",
        "sourceBindings": source_evidence, "sourceImportLinks": links, "compiledBindings": compiled,
        "reusedTranscriptBoundaryBindings": reused,
        "agentLoopArtifacts": list(AGENT_LOOP_ARTIFACTS), "turnToolArtifacts": list(TURN_TOOL_ARTIFACTS),
        "appendArtifacts": list(APPEND_ARTIFACTS), "persistenceArtifacts": list(PERSISTENCE_ARTIFACTS),
        "readProjectionArtifacts": list(READ_PROJECTION_ARTIFACTS),
        "requiredTurnTrustArtifacts": list(REQUIRED_TURN_TRUST_ARTIFACTS),
        "transcriptWorkerArtifacts": list(TRANSCRIPT_WORKER_ARTIFACTS),
        "transcriptWorkerParentArtifacts": list(TRANSCRIPT_WORKER_PARENT_ARTIFACTS),
        "workerRequiredWhen": "Default SQLite source projection without observer or explicit parseYieldEveryLines",
        "declarationContext": {"embeddedRunLoopTaintStateCreatedBeforeAttempts": True,
                               "embeddedRunLoopActuallyExecuted": False,
                               "sourceDeclarationsAreRuntimeExecutionProof": False},
        "modelProviderTransportVerified": False, "fullHostOrchestrationVerified": False,
        "indexManagerConstructed": False, "memoryIndexWorkerRequired": False,
        "privateStampExported": False, "privateStampCaller": "public original runAgentLoop",
        "requiresCompleteOriginalToolResultBeforeAgentLoopProjection": True,
        "toolInvocationBoundary": "Sequential public execute delegation with unchanged arguments and original wrapped-tool receiver",
        "originalToolPrivatePreparerMutated": False, "originalToolBatchAdmissionVerified": False,
    }
