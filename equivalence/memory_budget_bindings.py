"""Exact original #38 compaction/apply owners; no behavioral credit from pinning."""
from pathlib import Path
import hashlib

from equivalence.get_contract_runtime_bindings import _owners
from equivalence.reference_bindings import _git
from equivalence.session_admission_runtime_bindings import _named_link

REFERENCE_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"
SOURCE_HASHES = {'extensions/memory-core/src/memory-budget.ts': 'feba8e1de3c3391d82fb996bcee882da23f9df296c1d68e9bd6b8d4ecf1c305e',
 'extensions/memory-core/src/memory-budget-append.ts': '7037e68a38bcc4c0a92777b49a7051d7795e67a16c8c7ae6d226efa644a06a9c',
 'extensions/memory-core/src/short-term-promotion-apply.ts': '914fb4c452d358540e138a09681b262d1932e6c5f8c2303ab3de9b0e992f522a',
 'extensions/memory-core/src/short-term-promotion-memory-write.ts': '73efe7aded716c4ad1dce87230ef0cd538737491190168b1769765dd8ad092e5',
 'extensions/memory-core/src/short-term-promotion-metadata.ts': '8ee19a393e6ec8fb6370bf3f04d657ab78f053a715468aa772f0d7499b1da278',
 'extensions/memory-core/src/short-term-promotion-rehydrate.ts': '3525f10252f5dd72c439d45c224751a76334f9ab2b4447fede7b3cc09bd0652b',
 'extensions/memory-core/src/short-term-promotion-store.ts': '556c7e10323eb889e857d2cda41a5a6cd78e7e456ee99b2205b491dac547ea84',
 'extensions/memory-core/src/short-term-promotion-utils.ts': '2c9368be7fcff1581a3e4c706465dc60506fa605cf8db9dba3577fa7cc9274c7',
 'extensions/memory-core/src/short-term-promotion-types.ts': 'c97c17dcc52eea9fc9d320fa77be6f0da901331428d6bfc70d289da9e6764daf',
 'extensions/memory-core/src/memory-workspace-lock.ts': '557bf3bdb03a8139af1c3fe40d106b3fb74e8ad20c30969bd888a7bccf25beb2',
 'extensions/memory-core/src/memory-workspace-files.ts': '1e7864b563fb9efc44b1b69933199886e49ebe8241b46336f83e1186c62f7f56',
 'extensions/memory-core/src/dreaming-state.ts': 'b115fa0ce1c2757abc282f2822d08dc365c07a3b88c6e90ff7b1e7b87fb64458',
 'extensions/memory-core/src/time.ts': '3bdbf0427b95742be8fceae4107a2949ef184df196c75760eee132d06572fdcc',
 'src/plugin-state/plugin-state-store.ts': '361e7571e9c93efde048462fd967e845c6e68a7a9f7a9c6f9a0823b6cad8b530',
 'src/memory-host-sdk/events.ts': '656dbfaad097f0fc90d7f5494fb2f25bb9f353654c649f5c4b9d2e92571960d4',
 'src/memory-host-sdk/event-store.ts': '7f4dd921ae8418488af64c909242180ce81977b9a579323b006c416863ddda71',
 'src/infra/file-lock.ts': '7476abe40ade08deb99502672c52a77e41e7f0fa0881fbf45141185637d52c7c',
 'src/plugin-sdk/file-lock.ts': 'ae7f9dc28c1b544f5fb21a129df8ce8ddc172c8ae1b1ead36af21fc19b0aa7ec',
 'src/plugin-sdk/plugin-state-store-runtime.ts': 'ecf895427ac1c6acf31570294fd6c2418dfc7b09a041b0b8f71d44e4d732c998'}

SOURCE_ANCHORS = {'extensions/memory-core/src/memory-budget.ts': ('export function compactMemoryForBudget(',
                                                 'const WRITE_OVERHEAD_RESERVE = 21;'),
 'extensions/memory-core/src/memory-budget-append.ts': ('export function buildBudgetedMemoryAppend(',),
 'extensions/memory-core/src/short-term-promotion-apply.ts': ('export async function applyShortTermPromotions(',),
 'extensions/memory-core/src/short-term-promotion-memory-write.ts': ('export async function commitMemoryContent(',
                                                                     'export function buildPromotionMarker('),
 'extensions/memory-core/src/short-term-promotion-metadata.ts': ('export function '
                                                                 'buildPromotionRecallAnnotations(',),
 'extensions/memory-core/src/short-term-promotion-rehydrate.ts': ('export async function '
                                                                  'rehydratePromotionCandidate(',),
 'extensions/memory-core/src/short-term-promotion-store.ts': ('export async function readStore(',
                                                              'export async function writeStore('),
 'extensions/memory-core/src/short-term-promotion-utils.ts': ('export function formatPromotedSnippetForMemory(',
                                                              'export function normalizeShortTermRecallStore('),
 'extensions/memory-core/src/short-term-promotion-types.ts': ('export type ApplyShortTermPromotionsResult = {',),
 'extensions/memory-core/src/memory-workspace-lock.ts': ('export async function withMemoryWorkspaceLock<T>(',),
 'extensions/memory-core/src/memory-workspace-files.ts': ('export async function readWorkspaceFile(',),
 'extensions/memory-core/src/dreaming-state.ts': ('export function configureMemoryCoreDreamingState(',
                                                  'export async function writeMemoryCoreWorkspaceEntries('),
 'extensions/memory-core/src/time.ts': ('export function resolveMemoryCoreNowMs(',),
 'src/plugin-state/plugin-state-store.ts': ('export function createPluginStateKeyedStore<T>(',),
 'src/memory-host-sdk/events.ts': ('export async function appendMemoryHostEvent(',
                                   'export async function readMemoryHostEventRecords('),
 'src/memory-host-sdk/event-store.ts': ('export function normalizeMemoryHostEventRecordForStorage(',
                                        'export async function registerMemoryHostEvent('),
 'src/infra/file-lock.ts': ('  withFileLock,',),
 'src/plugin-sdk/file-lock.ts': ('export async function withFileLock<T>(',),
 'src/plugin-sdk/plugin-state-store-runtime.ts': ('  createPluginStateKeyedStore,',)}

COMPILED_HASHES = {'dist/memory-budget-BodJnew-.mjs': 'c2debded932e73622e81e4d695f7804ac7dd3947a77725e3512e35de22d9d005',
 'dist/short-term-promotion-MX1vHJuE.mjs': 'be3114e9aa8c448bdeedbd750b41b25ac06bc00ad8a728edb70db376aa3bc1da',
 'dist/short-term-promotion-memory-write-HTLC95gL.mjs': '0c5107c106706654ac87dba9f499024ff7e7f57fb9e5ffcd7e3e4c01d9732d46',
 'dist/short-term-promotion-store-B6T388Bo.mjs': '704c9fa0e2a1fe7c4dc805aa23ad541562d66c47fbb853351ef74b0604c348b8',
 'dist/memory-workspace-files-CC0bKS3d.mjs': '7d884a6a33d19ec06d9db6b99b136815548b75841ba3c7029499ab356a631c7e',
 'dist/dreaming-dreams-file-BJzlZFlf.mjs': 'fbc57813554fc29a6b7c5bcbada4baa21d5f774c33edd54297a3976741fa4492',
 'dist/dreaming-state-VYUvbU-n.mjs': '8676156b95cc8b73d0cc830e1305bc3460eb90f2bf1114d9e5a6b008269a3e2c',
 'dist/time-BhFVUM0b.mjs': '2eed429a02ba038dbaf5c16e83acfcae6baa0293dc46370475cb00b1d267ae02',
 'dist/plugin-sdk/plugin-state-store-runtime.js': '6e34e2530c913403a15ce4f93a3c8fdfbbb7caaa9ea191faa5993c6b469f1e61',
 'dist/plugin-state-store-BPUaLoVD.mjs': '4d010227d5baea72f1dfc1e117efe2cc1eb596eeab579e6c92c047abf75f7efc',
 'dist/memory-host-events-C8-U38f1.mjs': '8253343c15c8cf22bf861d36108bf707f614f01c78dd53bdf25f93ff0d767862',
 'dist/event-store-BeWtwFJV.mjs': 'e48bf5aaecb7287e3f873251880148cf992492194b61103a467e84e648001cb6',
 'dist/file-lock-bsl71RWY.mjs': '2c9ba26b97c5f6edbcea933422db39e9bfdc3b3a428b6da37d27dc9e32bbcc94'}

COMPILED_ANCHORS = {'dist/memory-budget-BodJnew-.mjs': ('function compactMemoryForBudget(', 'compactMemoryForBudget as n'),
 'dist/short-term-promotion-MX1vHJuE.mjs': ('async function applyShortTermPromotions(',
                                            'function buildBudgetedMemoryAppend(',
                                            'applyShortTermPromotions as a'),
 'dist/short-term-promotion-memory-write-HTLC95gL.mjs': ('async function commitMemoryContent(',),
 'dist/short-term-promotion-store-B6T388Bo.mjs': ('async function writeStore(', 'async function readStore('),
 'dist/memory-workspace-files-CC0bKS3d.mjs': ('async function readWorkspaceFile(',),
 'dist/dreaming-dreams-file-BJzlZFlf.mjs': ('async function withMemoryWorkspaceLock(',),
 'dist/dreaming-state-VYUvbU-n.mjs': ('function configureMemoryCoreDreamingState(',),
 'dist/time-BhFVUM0b.mjs': ('function resolveMemoryCoreNowMs(',),
 'dist/plugin-sdk/plugin-state-store-runtime.js': ('export { createPluginStateKeyedStore, '
                                                   'createPluginStateSyncKeyedStore };',),
 'dist/plugin-state-store-BPUaLoVD.mjs': ('function createPluginStateKeyedStore(',),
 'dist/memory-host-events-C8-U38f1.mjs': ('async function readMemoryHostEventRecords(',),
 'dist/event-store-BeWtwFJV.mjs': ('async function registerMemoryHostEvent(',),
 'dist/file-lock-bsl71RWY.mjs': ('async function withFileLock(',)}

REQUIRED_ARTIFACTS = {"memory-budget-runtime": ("dist/memory-budget-BodJnew-.mjs",),
    "memory-budget-apply-runtime": tuple(COMPILED_HASHES)}
NATIVE_ARTIFACTS = {("node_modules/@openclaw/fs-safe-linux-x64-gnu", "fs-safe-native.node"):
    "f1aad2619542e43af6f28606e7514054bd0824814f2a2bb4b72f5e16e9ea2d7c"}


def prepare_memory_budget_bindings(checkout: Path, runtime_root: Path):
    if _git(checkout, "rev-parse", "HEAD").decode().strip() != REFERENCE_COMMIT:
        raise ValueError("Memory budget requires the exact pinned original source commit")
    sources, source_evidence = _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
    _, compiled_evidence = _owners(runtime_root, COMPILED_HASHES, COMPILED_ANCHORS, committed=False)
    native_evidence = []
    for (package, relative), digest in NATIVE_ARTIFACTS.items():
        filename = runtime_root.parent.parent / package / relative
        if (not filename.is_file() or filename.is_symlink()
                or not filename.resolve().is_relative_to(runtime_root.parent.resolve())
                or hashlib.sha256(filename.read_bytes()).hexdigest() != digest):
            raise ValueError("The exact original fs-safe published native artifact changed")
        native_evidence.append({"package": package, "path": relative, "sha256": digest, "nativeBuildReproduced": False})
    links = [
        ("extensions/memory-core/src/memory-budget-append.ts", "./memory-budget.js", ("compactMemoryForBudget",)),
        ("extensions/memory-core/src/short-term-promotion-apply.ts", "./memory-budget-append.js", ("buildBudgetedMemoryAppend",)),
        ("extensions/memory-core/src/short-term-promotion-apply.ts", "./short-term-promotion-memory-write.js", ("commitMemoryContent", "buildPromotionMarker")),
        ("extensions/memory-core/src/short-term-promotion-apply.ts", "./short-term-promotion-store.js", ("readStore", "writeStore")),
        ("extensions/memory-core/src/short-term-promotion-apply.ts", "./short-term-promotion-rehydrate.js", ("rehydratePromotionCandidate",)),
        ("extensions/memory-core/src/short-term-promotion-apply.ts", "./memory-workspace-lock.js", ("withMemoryWorkspaceLock",)),
        ("extensions/memory-core/src/short-term-promotion-store.ts", "./dreaming-state.js", ("readMemoryCoreWorkspaceEntries", "writeMemoryCoreWorkspaceEntries", "writeMemoryCoreWorkspaceEntry")),
        ("src/memory-host-sdk/events.ts", "./event-store.js", ("registerMemoryHostEvent", "listStoredMemoryHostEvents")),
    ]
    return {"kind": "official-release-memory-budget-owners", "referenceCommit": REFERENCE_COMMIT,
        "sourceBuildReproduced": False, "sourceFallbackAllowed": False, "covers": [],
        "sourceBindings": source_evidence, "compiledBindings": compiled_evidence,
        "nativeArtifactBindings": native_evidence,
        "sourceImportLinks": [_named_link(sources, module, specifier, names, kind="import")
            for module, specifier, names in links],
        "helperEntrypoint": {"path": "dist/memory-budget-BodJnew-.mjs", "export": "n"},
        "applyEntrypoint": {"path": "dist/short-term-promotion-MX1vHJuE.mjs", "export": "a"},
        "configurationResolverCompared": False, "providerLoopCompared": False, "lockEquivalenceClaimed": False}
