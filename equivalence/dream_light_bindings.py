"""Pinned source, release and entry-point identities for the original light sweep."""
from pathlib import Path

from equivalence.reference_bindings import _git
from equivalence.session_admission_runtime_bindings import REFERENCE_COMMIT, _owners

SOURCE = {
    "extensions/memory-core/src/dreaming-state.ts": (
        "b115fa0ce1c2757abc282f2822d08dc365c07a3b88c6e90ff7b1e7b87fb64458",
        ('function configureMemoryCoreDreamingState(',)),
    "src/plugin-state/plugin-state-store.ts": (
        "361e7571e9c93efde048462fd967e845c6e68a7a9f7a9c6f9a0823b6cad8b530",
        ('function createPluginStateKeyedStore<T>(',)),
    "extensions/memory-core/src/dreaming-phases.ts": (
        "8e1357d90e083f62ba1afa2b233ebf734270d02c0b2ae460abfa783273a5ce2c",
        ('function runDreamingSweepPhases(', 'function runLightDreaming(', 'function ingestDreamingPhaseSignals(')),
    "src/memory-host-sdk/dreaming.ts": (
        "c4f5299cf96c6701e5217dba3e2f41aeca5b5393e3f0c23e00478a394bbf2daf",
        ('function resolveMemoryLightDreamingConfig(',)),
    "extensions/memory-core/src/short-term-promotion-store.ts": (
        "556c7e10323eb889e857d2cda41a5a6cd78e7e456ee99b2205b491dac547ea84",
        ('function readStore(', 'function readPhaseSignalStore(', 'function writeStore(', 'function writePhaseSignalStore(')),
    "extensions/memory-core/src/dreaming-markdown.ts": (
        "ef2c297222e487ef1e935e7b0d3f723a14c90659ab83d3179084fd29101f3205",
        ('function writeDailyDreamingPhaseBlock(',)),
    "extensions/memory-core/src/dreaming-ingestion-state.ts": (
        "1d4fca365fa88ef871766adccb85bface2aaff04e4ed54ce996f187ae5150905",
        ('function writeDailyIngestionState(',)),
    "extensions/memory-core/src/short-term-promotion-record.ts": (
        "b8d168519af14de5ae793d6738d3a86d51e41cdcc12cbd5b22fb174ba108d8c7",
        ('function recordShortTermRecalls(',)),
    "src/memory-host-sdk/events.ts": (
        "656dbfaad097f0fc90d7f5494fb2f25bb9f353654c649f5c4b9d2e92571960d4",
        ('function readMemoryHostEventRecords(',)),
    "src/memory-host-sdk/event-store.ts": (
        "7f4dd921ae8418488af64c909242180ce81977b9a579323b006c416863ddda71",
        ('function listStoredMemoryHostEvents(',)),
}

COMPILED = {
    "dist/dreaming-state-VYUvbU-n.mjs": (
        "8676156b95cc8b73d0cc830e1305bc3460eb90f2bf1114d9e5a6b008269a3e2c",
        ('function configureMemoryCoreDreamingState(',)),
    "dist/plugin-state-store-BPUaLoVD.mjs": (
        "4d010227d5baea72f1dfc1e117efe2cc1eb596eeab579e6c92c047abf75f7efc",
        ('function createPluginStateKeyedStore(', 'function closePluginStateDatabaseAsync(')),
    "dist/plugin-state-worker-client-7ByaGIDy.mjs": (
        "bee1c828bf9a23d3aeafd84e91d3dfd2b2d685b2d560fc5a9e01aabcd0346217",
        ('function lookupPluginStateInWorker(',)),
    "dist/infra/sqlite-store.worker.js": (
        "b6fb8b9d214bd7d35beb77849e1c44926d4963cacd9fc13af40f8c3b43374d69",
        ('SQLite store worker requires its host port', 'async function receive(')),
    "dist/state/openclaw-state.worker.js": (
        "52fdb859d0add218690d0db4358fa5b2f2d2118379163eefb42a35c87f0715d4",
        ('function createSqliteWorkerBackend(',)),
    "dist/plugin-state.worker-Bt1nfP3u.mjs": (
        "d724a51faf2d46e518a733a47528ac9b629e54b1d4f6afa9007d769021bba9f4",
        ('function executePluginStateCommand(',)),
    "dist/dreaming-phases-rmgXNBLP.mjs": (
        "a6cb36f29a58a368fadd5edfe59eb7c4c2ba09f6f72057f5b3601f312159ee3a",
        ('function runDreamingSweepPhases(', 'function runLightDreaming(', 'function ingestDreamingPhaseSignals(')),
    "dist/dreaming-dsmlMxw7.mjs": (
        "d84a68d61fc08db53d0ec7e408017c940151ff10e11a38430c23415a06ffef83",
        ('function resolveMemoryLightDreamingConfig(',)),
    "dist/short-term-promotion-store-B6T388Bo.mjs": (
        "704c9fa0e2a1fe7c4dc805aa23ad541562d66c47fbb853351ef74b0604c348b8",
        ('function readStore(', 'function readPhaseSignalStore(', 'function writeStore(', 'function writePhaseSignalStore(')),
    "dist/dreaming-markdown-B86sCBbW.mjs": (
        "9b318186cdef7190a6831bd92d5e0f308e78b4df3d60e344115b4fbc3f3340d6",
        ('function writeDailyDreamingPhaseBlock(',)),
    "dist/dreaming-ingestion-state-licbtf_y.mjs": (
        "91904fa3331423770d712029fa2863d0e30279a33d8b8b9486ab630281ff31e3",
        ('function writeDailyIngestionState(',)),
    "dist/short-term-promotion-record-DrLa1fiO.mjs": (
        "26a083e3c17cd6512af9785266c7bdffe459cd02591be4127004efe7eb8887c7",
        ('function recordShortTermRecalls(',)),
    "dist/memory-host-events-C8-U38f1.mjs": (
        "8253343c15c8cf22bf861d36108bf707f614f01c78dd53bdf25f93ff0d767862",
        ('function readMemoryHostEventRecords(',)),
    "dist/event-store-BeWtwFJV.mjs": (
        "e48bf5aaecb7287e3f873251880148cf992492194b61103a467e84e648001cb6",
        ('function listStoredMemoryHostEvents(',)),
    "dist/plugin-sdk/memory-host-events.js": (
        "bbc677afa65845b6aace5abaac6c7c61ca8dd8594a05aa6c7d83048f2f2e2d78",
        ('export { appendMemoryHostEvent,',)),
}


REM_SOURCE = {
    "extensions/memory-core/src/dreaming-phases.ts": (
        "8e1357d90e083f62ba1afa2b233ebf734270d02c0b2ae460abfa783273a5ce2c",
        ('function runRemDreaming(', 'function selectRemCandidateTruths(', 'function buildRemReflections(')),
    "extensions/memory-core/src/dreaming-narrative.ts": (
        "1274c328923b0d4d219a0ca5dae16535aca0d9aaf1a4b3b6f8223a05400c9818",
        ('function runDreamNarrative(', 'function generateAndAppendDreamNarrative(', 'function buildNarrativePrompt(', 'function appendFallbackNarrativeEntry(')),
    "extensions/memory-core/src/dreaming-dreams-file.ts": (
        "91ef8ad95b9b16e7975c06572e0b6c4c96bdb15b98679a520efd840cd263a43b",
        ('function appendNarrativeEntry(', 'function assertSafeDreamsPath(')),
    "extensions/memory-core/src/short-term-promotion-stats.ts": (
        "f10c97fcbe12a499c747910425659ca2e00ce49b8c44ed2feb77bc74e38c5372",
        ('function recordRemConsideredPhaseSignals(', 'function readLightStagedKeys(', 'function recordDreamingPhaseSignals(')),
}

REM_COMPILED = {
    "dist/dreaming-phases-rmgXNBLP.mjs": (
        "a6cb36f29a58a368fadd5edfe59eb7c4c2ba09f6f72057f5b3601f312159ee3a",
        ('function runRemDreaming(', 'function selectRemCandidateTruths(', 'function buildRemReflections(')),
    "dist/dreaming-narrative-B8Hp3Mc_.mjs": (
        "db2106633d04a70616bb0b9596d9c35f506d984312325f57e6a32fbfbf46ed79",
        ('function runDreamNarrative(', 'function generateAndAppendDreamNarrative(', 'function buildNarrativePrompt(', 'function appendFallbackNarrativeEntry(')),
    "dist/dreaming-dreams-file-BJzlZFlf.mjs": (
        "fbc57813554fc29a6b7c5bcbada4baa21d5f774c33edd54297a3976741fa4492",
        ('function appendNarrativeEntry(', 'function assertSafeDreamsPath(')),
    "dist/short-term-promotion-MX1vHJuE.mjs": (
        "be3114e9aa8c448bdeedbd750b41b25ac06bc00ad8a728edb70db376aa3bc1da",
        ('function recordRemConsideredPhaseSignals(', 'function readLightStagedKeys(', 'function recordDreamingPhaseSignals(')),
}

REQUIRED_RUNTIME_ARTIFACTS = tuple(COMPILED)
FUNCTION_HASHES = {"readShortTermStore": "4c9ea7bd8a2d4bb40f607296fce8c0332eb6b0f255b1f578fa2c56bf39285c84",
'createPluginStateKeyedStore': '3c4f0e6163afd4d4f9462fe11b1c18410332764b5ea591361ed6c66034d0c203',
'closePluginStateDatabaseAsync': 'c648b6b2311377ff1d43593a21ce37b67b4d8b9bce744aae495049043b99da92',
'configureMemoryCoreDreamingState': '7c97cd878aa65b0ee17367683050f50530df0656d54ab52e3e6f0c2d92e279cc',
'runDreamingSweepPhases': '149a1a2cc7fe80eb5159b27066f7a6495fb0713cd8394ce5aad147ec5765dae4',
 'readStore': '263f66124da587c26023e24360703445ae5cf3ed9d1dca87d91df5591f0f4ae9',
 'readPhaseSignalStore': '5f389e8532f7870d6e511e502f09d72a2c6723e3f1dba1f23366552157edbfb2',
 'writeStore': 'e1ebaa231556530f68fdf65c1cc227ba1140aef0b875be10c621ea3dbfecdb0e',
 'writePhaseSignalStore': 'b8a8e4c14df57c38af559a55767cc37843184927a8df5d9d8c8acd502ad46135',
 'readMemoryHostEventRecords': '60d1b7c8011d88df7ab3d057a30c2983a4614e9a327dbc91fb1ddcb748b7c4d9'}


def prepare_dream_light_bindings(checkout: Path, runtime_root: Path, phase="light"):
    checkout, runtime_root = Path(checkout).resolve(), Path(runtime_root).resolve()
    if _git(checkout, "rev-parse", "HEAD").decode().strip() != REFERENCE_COMMIT:
        raise ValueError("The light sweep requires the pinned OpenClaw source commit")

    if phase not in ("light", "rem", "diary"):
        raise ValueError("Unknown dreaming phase")
    source = {**SOURCE, **REM_SOURCE} if phase == "rem" else SOURCE
    compiled = {**COMPILED, **REM_COMPILED} if phase == "rem" else COMPILED
    entry = {"artifact": "dist/dreaming-phases-rmgXNBLP.mjs", "export": "r", "name": "runDreamingSweepPhases"}
    if phase == "diary":
        from equivalence.dream_diary_bindings import SOURCE as source, COMPILED as compiled
        entry = {"artifact": "dist/dreaming-dreams-file-BJzlZFlf.mjs", "export": "n", "name": "appendNarrativeEntry"}

    def verify(root, table, committed):
        hashes = {name: row[0] for name, row in table.items()}
        anchors = {name: row[1] for name, row in table.items()}
        return _owners(root, hashes, anchors, committed=committed)[1]

    return {"kind": f"official-release-{phase}-dreaming-owners", "referenceCommit": REFERENCE_COMMIT,
            "sourceBindings": verify(checkout, source, True),
            "compiledBindings": verify(runtime_root, compiled, False),
            "requiredLoadedArtifacts": list(compiled),
            "sourceBuildReproduced": False, "sourceFallbackAllowed": False,
            "entryPoint": entry}
