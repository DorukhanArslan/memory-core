"""Reviewed declarations authenticate owners; only actual runtime traces prove flows."""
from copy import deepcopy
import hashlib
import subprocess

import pytest

from equivalence import session_admission_runtime_bindings as bindings


# Labelled non-executing declaration fixtures. This independent frozen edge list
# must be reviewed when a new original runtime linkage is added.
_LINKS = (('extensions/memory-core/src/memory/manager-runtime.ts',
  './manager.js',
  ('getMemoryIndexManagerRegistry', 'MemoryIndexManager'),
  'import'),
 ('extensions/memory-core/src/memory/manager-session-sync-ops.ts',
  './manager-session-sync-state.js',
  ('isMemorySessionIndexable', 'resolveMemorySessionStartupState'),
  'import'),
 ('extensions/memory-core/src/memory/manager-session-sync-ops.ts',
  'openclaw/plugin-sdk/memory-core-host-engine-sessions',
  ('listSessionTranscriptCorpusEntriesForAgent', 'loadArchivedSessions', 'sessionPathForSessionIdentity'),
  'import'),
 ('packages/memory-host-sdk/src/host/session-files.ts',
  './session-transcript-corpus.js',
  ('listSessionTranscriptCorpusEntriesForAgentSync',),
  'import'),
 ('packages/memory-host-sdk/src/host/session-files.ts',
  './session-entry-projection.js',
  ('collectRawSessionText', 'projectSessionEntryRecord'),
  'import'),
 ('packages/memory-host-sdk/src/host/session-files.ts',
  './session-provenance.js',
  ('classifySessionMessageOrigin',),
  'import'),
 ('packages/memory-host-sdk/src/host/session-files.ts',
  './session-reset-recall.js',
  ('resolveSessionResetRecallCutoff',),
  'import'),
 ('packages/memory-host-sdk/src/host/openclaw-runtime-session.ts',
  '../../../../src/config/sessions/session-accessor.js',
  ('listSessionEntriesCore', 'listSessionEntriesReadOnly'),
  'export'),
 ('packages/memory-host-sdk/src/host/openclaw-runtime-session.ts',
  '../../../../src/config/sessions/session-accessor.js',
  ('readTranscriptExportSnapshotReadOnlySync',),
  'import'),
 ('extensions/memory-core/src/memory-search-tool-query.ts',
  './session-search-visibility.js',
  ('filterMemorySearchHitsBySessionVisibility',),
  'import'),
 ('extensions/memory-core/src/session-search-visibility.ts',
  'openclaw/plugin-sdk/session-visibility',
  ('createAgentToAgentPolicy',
   'createSessionVisibilityGuard',
   'resolveEffectiveSessionToolsVisibility',
   'resolveSandboxSessionToolsVisibility'),
  'import'),
 ('extensions/memory-core/src/session-search-visibility.ts',
  'openclaw/plugin-sdk/session-transcript-hit',
  ('extractTranscriptIdentityFromSessionsMemoryHit',
   'loadCombinedSessionStoreForGateway',
   'resolveTranscriptStemToSessionKeys'),
  'import'),
 ('extensions/memory-core/src/session-search-visibility.ts',
  './session-reset-recall-metadata.js',
  ('readSessionArchiveReasonFromHitPath',),
  'import'),
 ('src/plugin-sdk/session-visibility.ts',
  './session-visibility-internal.js',
  ('createSessionVisibilityDecisionChecker', 'listSpawnedSessionKeysWithResult'),
  'import'),
 ('src/agents/tools/in-process-gateway.ts',
  '../../gateway/server-plugin-in-process-dispatch.js',
  ('dispatchGatewayMethodInProcess', 'getInProcessGatewayRequestContext'),
  'import'),
 ('src/gateway/server-plugin-in-process-dispatch.ts',
  './server-in-process-dispatch.js',
  ('dispatchGatewayRequestInProcessRaw', 'unwrapGatewayMethodDispatchResponse'),
  'import'),
 ('src/gateway/server-methods/sessions-read.ts',
  '../session-row-projection-access.js',
  ('getSessionRowProjection',),
  'import'),
 ('src/gateway/server-methods/sessions-read.ts',
  '../../config/sessions/session-accessor.js',
  ('listSessionEntriesReadOnly', 'withSessionEntryReadOnlyScope'),
  'import'),
 ('src/config/sessions/session-accessor.ts',
  './session-accessor.entry.js',
  ('listSessionEntriesCore', 'listSessionEntriesReadOnly', 'upsertSessionEntryCore'),
  'export'),
 ('src/config/sessions/session-accessor.entry.ts',
  './session-accessor.sqlite-entry.js',
  ('upsertSessionEntryCore',),
  'export'),
 ('src/config/sessions/session-accessor.ts',
  './session-accessor.transcript.js',
  ('readTranscriptExportSnapshotReadOnlySync', 'replaceTranscriptEvents', 'replaceTranscriptEventsSync'),
  'export'),
 ('src/config/sessions/session-accessor.ts',
  './session-accessor.lifecycle.js',
  ('resetSessionEntryLifecycle', 'deleteSessionEntryLifecycle'),
  'export'),
 ('src/config/sessions/session-accessor.lifecycle.ts',
  './session-accessor.sqlite-lifecycle.js',
  ('resetSessionEntryLifecycle', 'deleteSessionEntryLifecycle'),
  'export'),
 ('src/plugin-sdk/session-store-runtime.ts',
  '../config/sessions/session-accessor.js',
  ('loadSessionEntryReadOnly', 'updateSessionEntry'),
  'import'),
 ('extensions/memory-core/src/session-ingestion.ts',
  'openclaw/plugin-sdk/memory-core-host-engine-sessions',
  ('loadMemorySessionMetadata',),
  'import'),
 ('extensions/memory-core/src/session-ingestion.ts',
  './memory-entry-origins.js',
  ('listMemorySessionTombstones',),
  'import'),
 ('src/plugin-sdk/memory-core-host-engine-sessions.ts',
  '../config/sessions/session-accessor.js',
  ('listSessionTranscriptInstances',),
  'import'),
 ('src/config/sessions/session-accessor.ts',
  './session-accessor.sqlite-participants.js',
  ('recordSessionParticipant',),
  'export'),
 ('src/config/sessions/session-accessor.ts',
  './session-accessor.sqlite-participant-read.js',
  ('listSessionParticipantsReadOnly',),
  'export'),
 ('src/config/sessions/session-sharing-store.async.ts',
  './session-accessor.sqlite-participants.native.js',
  ('recordSessionParticipant',),
  'import'),
 ('src/config/sessions/session-accessor.sqlite-participants.native.ts',
  './session-participant-identity.js',
  ('participantIdentityNamespace', 'mergeParticipantAggregate'),
  'import'),
 ('src/config/sessions/session-accessor.sqlite-participants.native.ts',
  './session-entry-provenance.js',
  ('MAX_SESSION_PARTICIPANTS',),
  'import'),
 ('src/config/sessions/session-accessor.sqlite-participant-read.ts',
  './session-accessor.sqlite-participant-projection.js',
  ('participantRecordsBySessionKey',),
  'import'),
 ('src/config/sessions/session-accessor.sqlite-participant-projection.ts',
  './session-participant-identity.js',
  ('readParticipantIdentity',),
  'import'),
 ('src/config/sessions/session-participant-identity.ts',
  '../../../packages/gateway-protocol/src/schema/session-participant.js',
  ('SessionParticipantIdentitySchema',),
  'import'),
 ('src/config/sessions/session-entry-provenance.ts',
  '../../../packages/gateway-protocol/src/schema/session-participant.js',
  ('SESSION_EXPANDED_PARTICIPANT_LIMIT',),
  'import'),
 ('src/plugin-sdk/session-key-runtime.ts', '../routing/session-key.js', ('isIncognitoSessionKey',), 'export'),
 ('src/routing/session-key.ts', '../shared/incognito-session-key.js', ('isIncognitoSessionKey',), 'export'),
 ('src/shared/incognito-session-key.ts',
  '../../packages/session-url-contract/src/session-key.js',
  ('isIncognitoSessionKey',),
  'export'),
 ('src/config/sessions/session-accessor.transcript-target.ts',
  './session-accessor.sqlite-scope.js',
  ('resolveSqliteTranscriptScope', 'toDatabaseOptions'),
  'import'),
 ('src/config/sessions/session-accessor.transcript-target.ts',
  '../../state/openclaw-agent-db.js',
  ('resolveOpenClawAgentSqlitePath',),
  'import'),
 ('src/config/sessions/session-accessor.sqlite-scope.ts',
  '../../routing/session-key.js',
  ('isIncognitoSessionKey', 'resolveAgentIdFromSessionKey'),
  'import'),
 ('src/config/sessions/session-accessor.sqlite-scope.ts',
  '../../state/openclaw-agent-db.js',
  ('openOpenClawAgentDatabase', 'resolveIncognitoOpenClawAgentSqlitePath', 'resolveOpenClawAgentSqlitePath'),
  'import'),
 ('src/state/openclaw-agent-db.ts',
  './openclaw-agent-db.paths.js',
  ('isIncognitoOpenClawAgentSqlitePath', 'resolveOpenClawAgentSqlitePath'),
  'import'),
 ('src/state/openclaw-agent-db.ts',
  './openclaw-agent-db.paths.js',
  ('resolveIncognitoOpenClawAgentSqlitePath',),
  'export'),
 ('src/config/sessions/session-accessor.sqlite-entry-store.ts',
  './session-accessor.sqlite-provenance.js',
  ('resolveSessionEntryProvenanceRow',),
  'import'),
 ('src/config/sessions/session-accessor.sqlite-entry.ts',
  './session-accessor.sqlite-entry-store.js',
  ('readLifecycleTargetSnapshot', 'readSessionEntrySelectionSnapshot'),
  'import'),
 ('src/config/sessions/session-accessor.sqlite-archive-store-kernel.ts',
  './session-accessor.sqlite-archive-artifact.js',
  ('resolveRegisteredSqliteTranscriptArchiveName',),
  'import'),
 ('src/config/sessions/session-accessor.sqlite-archive-artifact.ts',
  './archive-compression.js',
  ('encodeSessionArchiveContent', 'readSessionArchiveContentSync', 'SESSION_ARCHIVE_ZSTD_SUFFIX'),
  'import'),
 ('src/config/sessions/archive-compression.ts', '../../infra/zstd-codec.js', ('resolveZstdCodec',), 'import'),
 ('packages/memory-host-sdk/src/host/openclaw-runtime-session.ts',
  '../../../../src/config/sessions/archive-compression.js',
  ('materializeSessionArchiveForRead',),
  'export'),
 ('packages/memory-host-sdk/src/host/session-files.ts',
  './openclaw-runtime-session.js',
  ('materializeSessionArchiveForRead',),
  'import'))
_DYNAMIC_MODULE = "src/plugin-sdk/session-visibility-internal.ts"
_DYNAMIC_LINK = '(await import("../agents/tools/in-process-gateway.js")).bindAgentToolGatewayRequest'
_COMMENTED_MODULE = "src/config/sessions/session-accessor.entry.ts"


def _edge(module, specifier, names, kind):
    if module in {"src/routing/session-key.ts", "src/shared/incognito-session-key.ts"}:
        return kind + " { " + ", ".join(names) + " } from \"" + specifier + "\";\n"
    comment = "  // Original owner documentation stays inside this export.\n" if module == _COMMENTED_MODULE else ""
    return kind + " {\n" + comment + "".join("  " + name + ",\n" for name in names) + "} from \"" + specifier + "\";\n"


@pytest.fixture
def sources():
    values = {module: "// Labelled original owner; not an implementation or execution.\n"
              for module in bindings.SOURCE_HASHES}
    for module, specifier, names, kind in _LINKS:
        values[module] += _edge(module, specifier, names, kind)
    values[_DYNAMIC_MODULE] += _DYNAMIC_LINK + "\n"
    for module, anchors in bindings.SOURCE_ANCHORS.items():
        for anchor in anchors:
            if anchor not in values[module]:
                values[module] += anchor + "\n"
        assert all(values[module].count(anchor) == 1 for anchor in anchors), module
    return values


@pytest.fixture
def compiled_sources():
    return {module: "// Labelled publisher artifact, never executed.\n" + "\n".join(anchors) + "\n"
            for module, anchors in bindings.COMPILED_ANCHORS.items()}


def _trees(root, monkeypatch, sources, compiled):
    checkout = root / "reference"
    checkout.mkdir()

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=checkout).decode().strip()

    git("init", "-q")
    for relative, content in sources.items():
        path = checkout / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    git("add", ".")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "commit", "-qm", "Labelled session authority declarations, no behavioral evidence")
    runtime = root / "runtime"
    for relative, content in compiled.items():
        path = runtime / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    monkeypatch.setattr(bindings, "REFERENCE_COMMIT", git("rev-parse", "HEAD"))
    monkeypatch.setattr(bindings, "SOURCE_HASHES", {
        name: hashlib.sha256(content.encode()).hexdigest() for name, content in sources.items()
    })
    monkeypatch.setattr(bindings, "COMPILED_HASHES", {
        name: hashlib.sha256(content.encode()).hexdigest() for name, content in compiled.items()
    })
    return checkout, runtime


@pytest.fixture
def trees(tmp_path, monkeypatch, sources, compiled_sources):
    return _trees(tmp_path, monkeypatch, sources, compiled_sources)


def test_real_flow_and_pure_helper_authority_claims_remain_explicitly_separate(trees, sources):
    original = deepcopy(sources)
    result = bindings.prepare_session_admission_runtime_bindings(*trees)
    assert sources == original
    assert result["kind"] == "official-release-session-admission-visibility-owners"
    assert result["referenceCommit"] == bindings.REFERENCE_COMMIT
    assert result["sourceBuildReproduced"] is False
    assert result["constructorSkipped"] is result["managerFixture"] is False
    assert result["defaultProfile"] == result["topLevelFlagsApplyToProfile"] == "session-contract-runtime"
    for flag in ("fullManagerExecutionVerified", "fullHostOrchestrationVerified",
                 "fullGatewayHTTPVerified", "providerTransportVerified"):
        assert result[flag] is False
    assert result["workerRequiredByProfile"] == {
        "session-contract-runtime": True, "session-contract-helper-runtime": False,
    }
    assert result["requiredMemoryIndexWorkerArtifacts"] == [
        "dist/extensions/memory-core/memory-index.worker.js", "dist/manager-index.worker-CinEDBkE.mjs",
    ]
    assert result["additionalHostedGatewayArtifacts"] == list(bindings.HOSTED_GATEWAY_ARTIFACTS)
    assert result["additionalArchiveArtifacts"] == list(bindings.ARCHIVE_ARTIFACTS)
    assert result["archiveReadArtifacts"] == list(bindings.ARCHIVE_READ_ARTIFACTS)
    assert result["archivePersistArtifacts"] == list(bindings.ARCHIVE_PERSIST_ARTIFACTS)
    assert result["additionalParticipantArtifacts"] == list(bindings.PARTICIPANT_ARTIFACTS)
    assert result["additionalIncognitoArtifacts"] == list(bindings.INCOGNITO_ARTIFACTS)
    assert len(result["additionalIncognitoArtifacts"]) == 6
    assert result["incognitoAuthority"]["sqliteTarget"] == ":memory:"
    for claim in ("privateStatePersisted", "fullDurableSessionContractVerified", "restartRecallVerified"):
        assert result["incognitoAuthority"][claim] is False
    assert result["participantAuthority"]["retainedIdentityLimit"] == 32
    assert result["participantAuthority"]["participantMetadataGrantsVisibility"] is False
    assert result["participantAuthority"]["publicWrite"] == {
        "path": "dist/session-accessor-CiKKTlbe.mjs", "export": "recordSessionParticipant",
    }
    assert result["sessionWriteProvenanceAuthority"] == {
        "originalOwner": "src/config/sessions/session-accessor.sqlite-provenance.ts",
        "originalBinding": "resolveSessionEntryProvenanceRow",
        "sourceCaller": "src/config/sessions/session-accessor.sqlite-entry-store.ts",
        "callerBinding": "writeSessionEntry",
        "compiledOwner": "dist/session-accessor.sqlite-entry-store-akBDqu6n.mjs",
        "monotonicSessionWindowFacts": [
            "session_entry_provenance", "acp_owned", "plugin_owner_id", "hook_external_content_source",
        ],
        "callerLifecycleProofRequired": True,
    }
    archive = result["archiveFixtureAuthority"]
    assert archive["fullArchivePublisherLifecycleVerified"] is False
    assert archive["recordedArchiveInsertion"] == {
        "path": "dist/session-accessor.sqlite-archive-store-kernel-C1WROmlG.mjs",
        "export": "persistSessionTranscriptArchive",
        "implementationPath": "dist/session-accessor.sqlite-archive-store-kernel-DNnMhRk6.mjs",
        "originalOwner": "src/config/sessions/session-accessor.sqlite-archive-store-kernel.ts",
    }
    assert archive["decompression"]["codec"] == "node:zlib.zstdDecompressSync"
    assert archive["sourceRead"]["bindings"] == [
        "materializeSessionArchiveForRead", "readSessionArchiveContentSync", "decodeSessionArchiveBytes",
    ]
    assert set(result["requiredLoadedArtifactsByProfile"]["session-contract-helper-runtime"]) == {
        "dist/session-ingestion-Dy5uAq-_.mjs", "dist/record-coerce-TIsquoVR.mjs",
        "dist/string-normalization-YMwDjufr.mjs",
    }
    flow = result["profiles"]["session-contract-runtime"]
    assert flow["constructorSkipped"] is flow["managerFixture"] is False
    assert flow["managerOverrides"] == []
    assert flow["workerRequired"] is flow["realFileIO"] is flow["realSqliteIO"] is True
    assert flow["requiresMemoryIndexWorkerProof"] is True
    assert flow["incidentalSqlWorkersSatisfyIndexProof"] is False
    assert flow["hostedGatewayHTTPServerStarted"] is False
    assert flow["rawFlowObservationsRequired"] == [
        "sessionWrites", "catalog", "admitted", "sourceEntries", "chunks", "provenance",
        "candidateHits", "nativeEnvelopes",
    ]
    helper = result["profiles"]["session-contract-helper-runtime"]
    assert helper["helperOnly"] is True
    for flag in ("workerRequired", "helperToWholeFlowCredit", "realSqliteIO",
                 "indexPublicationVerified", "sessionVisibilityVerified"):
        assert helper[flag] is False
    assert helper["executedBinding"] == "resolveAdmissionPolicy"
    assert {row["path"] for row in result["sourceBindings"]} == set(bindings.SOURCE_HASHES)
    assert {row["path"] for row in result["compiledBindings"]} == set(bindings.COMPILED_HASHES)
    assert len(result["sourceImportLinks"]) == len(_LINKS) + 2
    assert result["sourceImportLinks"][-2]["originalBinding"] == "recordSessionParticipantInWorker"
    assert result["sourceImportLinks"][-2]["exportedBinding"] == "recordSessionParticipant"
    assert result["sourceImportLinks"][-1]["specifier"] == "../agents/tools/in-process-gateway.js"
    assert result["sourceImportLinks"][-1]["binding"] == "bindAgentToolGatewayRequest"
    assert any(row.get("originalDeclarationCommentsPreserved") is True
               for row in result["sourceImportLinks"])
    for row in result["sourceBindings"] + result["compiledBindings"]:
        assert len(row["sha256"]) == 64
        assert all(item["line"] > 0 and item["anchor"] for item in row["anchors"])


@pytest.mark.parametrize("tree,module", [
    *(("source", module) for module in bindings.SOURCE_HASHES),
    *(("compiled", module) for module in bindings.COMPILED_HASHES),
])
@pytest.mark.parametrize("mutation", ["missing", "ambiguous"])
def test_every_reviewed_owner_requires_its_unique_original_declaration(
    tmp_path, monkeypatch, sources, compiled_sources, tree, module, mutation,
):
    values, anchors = ((sources, bindings.SOURCE_ANCHORS) if tree == "source"
                       else (compiled_sources, bindings.COMPILED_ANCHORS))
    anchor = anchors[module][0]
    if mutation == "missing":
        values[module] = values[module].replace(anchor, "// missing original owner")
    else:
        values[module] += "\n" + anchor
    with pytest.raises(bindings.SessionAdmissionRuntimeBindingError):
        bindings.prepare_session_admission_runtime_bindings(
            *_trees(tmp_path, monkeypatch, sources, compiled_sources),
        )


@pytest.mark.parametrize("module,specifier,names,kind", _LINKS)
@pytest.mark.parametrize("mutation", ["alias", "type", "module"])
def test_reviewed_bytes_cannot_substitute_a_catalog_visibility_history_or_gateway_import(
    tmp_path, monkeypatch, sources, compiled_sources, module, specifier, names, kind, mutation,
):
    old = _edge(module, specifier, names, kind)
    if mutation == "alias":
        new = old.replace(names[0], "Other as " + names[0], 1)
    elif mutation == "type":
        new = old.replace(kind + " {", kind + " type {", 1)
    else:
        new = old.replace(specifier, "./unreviewed-owner.js")
    assert old in sources[module] and new != old
    sources[module] = sources[module].replace(old, new, 1)
    with pytest.raises(bindings.SessionAdmissionRuntimeBindingError):
        bindings.prepare_session_admission_runtime_bindings(
            *_trees(tmp_path, monkeypatch, sources, compiled_sources),
        )


@pytest.mark.parametrize("mutation", ["missing", "different-module", "different-binding", "duplicate"])
def test_genuine_hosted_gateway_dynamic_owner_cannot_be_changed(
    tmp_path, monkeypatch, sources, compiled_sources, mutation,
):
    source = sources[_DYNAMIC_MODULE]
    if mutation == "missing":
        source = source.replace(_DYNAMIC_LINK, "// absent hosted authority")
    elif mutation == "different-module":
        source = source.replace("../agents/tools/in-process-gateway.js", "./fabricated-visible-keys.js")
    elif mutation == "different-binding":
        source = source.replace(".bindAgentToolGatewayRequest", ".fabricatedGatewayResponse")
    else:
        source += _DYNAMIC_LINK
    sources[_DYNAMIC_MODULE] = source
    with pytest.raises(bindings.SessionAdmissionRuntimeBindingError):
        bindings.prepare_session_admission_runtime_bindings(
            *_trees(tmp_path, monkeypatch, sources, compiled_sources),
        )


@pytest.mark.parametrize("mutation", [
    "source-dirty", "source-digest", "source-missing", "commit", "nested-root", "committed-bytes",
    "source-symlink", "source-ancestor-symlink", "compiled-digest", "compiled-missing",
    "compiled-symlink", "compiled-ancestor-symlink",
])
def test_unowned_or_uncommitted_owner_bytes_cannot_authenticate_real_session_flows(trees, monkeypatch, mutation):
    checkout, runtime = trees
    module = "extensions/memory-core/src/session-search-visibility.ts"
    artifact = "dist/tools-DotaQGXh.mjs"
    if mutation == "source-dirty":
        (checkout / module).write_text("// uncommitted replacement\n")
    elif mutation == "source-digest":
        monkeypatch.setattr(bindings, "SOURCE_HASHES", {**bindings.SOURCE_HASHES, module: "0" * 64})
    elif mutation == "source-missing":
        (checkout / module).unlink()
    elif mutation == "commit":
        monkeypatch.setattr(bindings, "REFERENCE_COMMIT", "0" * 40)
    elif mutation == "nested-root":
        checkout = checkout / "extensions"
    elif mutation == "committed-bytes":
        git = bindings._git
        def forged_git(root, *args):
            return b"fabricated committed owner" if args[0] == "show" else git(root, *args)
        monkeypatch.setattr(bindings, "_git", forged_git)
    elif "symlink" in mutation:
        path = checkout / module if mutation.startswith("source") else runtime / artifact
        target = path.parent if "ancestor" in mutation else path
        saved = target.with_name("original-owner")
        target.rename(saved)
        target.symlink_to(saved, target_is_directory="ancestor" in mutation)
    elif mutation == "compiled-digest":
        monkeypatch.setattr(bindings, "COMPILED_HASHES", {**bindings.COMPILED_HASHES, artifact: "0" * 64})
    else:
        (runtime / artifact).unlink()
    with pytest.raises(bindings.SessionAdmissionRuntimeBindingError):
        bindings.prepare_session_admission_runtime_bindings(checkout, runtime)


@pytest.mark.parametrize('module,token,replacement', [
    ('src/config/sessions/session-accessor.sqlite-participants.ts',
     'recordSessionParticipantInWorker as recordSessionParticipant', 'Other as recordSessionParticipant'),
    ('src/config/sessions/session-accessor.sqlite-participants.ts',
     './session-sharing-store.async.js', './unreviewed-writer.js'),
])
def test_public_participant_alias_cannot_hide_a_different_recording_owner(
    tmp_path, monkeypatch, sources, compiled_sources, module, token, replacement,
):
    sources[module] = sources[module].replace(token, replacement)
    with pytest.raises(bindings.SessionAdmissionRuntimeBindingError):
        bindings.prepare_session_admission_runtime_bindings(
            *_trees(tmp_path, monkeypatch, sources, compiled_sources),
        )


@pytest.mark.parametrize('module,token', [
    ('dist/session-accessor.sqlite-archive-store-kernel-C1WROmlG.mjs', 'export {'),
    ('dist/session-accessor.sqlite-archive-store-kernel-DNnMhRk6.mjs', 'persistSessionTranscriptArchive as r,'),
    ('dist/zstd-codec-C-vEb3Qf.mjs', 'export { resolveZstdCodec as t };'),
    ('dist/session-accessor-WMUIp1Kx.mjs', 'recordSessionParticipantInWorker as V,'),
    ('dist/session-sharing-store.native-BimL-D2p.mjs', 'export { recordSessionParticipant as i,'),
    ('dist/session-accessor.sqlite-entry-store-akBDqu6n.mjs', 'writeSessionEntry as f,'),
])
def test_reviewed_compiled_writer_declarations_also_require_the_actual_export_link(
    tmp_path, monkeypatch, sources, compiled_sources, module, token,
):
    assert token in compiled_sources[module]
    compiled_sources[module] = compiled_sources[module].replace(token, '// removed actual export')
    with pytest.raises(bindings.SessionAdmissionRuntimeBindingError):
        bindings.prepare_session_admission_runtime_bindings(
            *_trees(tmp_path, monkeypatch, sources, compiled_sources),
        )
