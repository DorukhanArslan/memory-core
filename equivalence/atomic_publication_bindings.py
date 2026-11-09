"""Pin original atomic owners; source and release execution remain separate.

These declarations authenticate exact original bytes and import edges. They do
not execute a publisher, reproduce the source build, or grant acceptance credit.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

from equivalence.reference_bindings import _NAMED_FROM, _git, _runtime_names

REFERENCE_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"
OPENCLAW_PACKAGE = "node_modules/openclaw"
FS_SAFE_PACKAGE = "node_modules/@openclaw/fs-safe"
NATIVE_PACKAGE = "node_modules/@openclaw/fs-safe-linux-x64-gnu"

# Generated once from the unchanged pinned checkout and authenticated release;
# the literal hashes below are never derived from an untrusted runtime input.
SOURCE_ANCHORS = {'extensions/memory-core/src/short-term-promotion-memory-write.ts': ('export async function '
                                                                     'commitMemoryContent(',
                                                                     'async function '
                                                                     'writeExistingMemoryInPlace(',
                                                                     'export class '
                                                                     'MemoryAtomicPublicationError extends '
                                                                     'Error {'),
 'src/plugin-sdk/security-runtime.ts': ('export { movePathWithCopyFallback, replaceFileAtomic } from '
                                        '"@openclaw/fs-safe/atomic";',),
 'src/plugin-sdk/file-access-runtime.ts': ('export { writeFileWindowFully } from '
                                           '"../infra/file-descriptor.js";',),
 'src/infra/file-descriptor.ts': ('export function sameFileMutationFingerprint(',),
 'src/infra/fs-safe.ts': ('export async function root(rootDir: string, defaults?: RootDefaults): '
                          'Promise<Root> {',),
 'src/infra/directory-durability.ts': ('  isHardlinkFallbackError,',),
 'src/agents/workspace-bootstrap-publish.ts': ('export async function publishBootstrapFile(',),
 'src/agents/agent-tools.read.ts': ('async function appendMemoryFlushContent(params: {',)}
SOURCE_HASHES = {'extensions/memory-core/src/short-term-promotion-memory-write.ts': '73efe7aded716c4ad1dce87230ef0cd538737491190168b1769765dd8ad092e5',
 'src/plugin-sdk/security-runtime.ts': 'fe090cbc705b32f357c99d7d64f4f882d00aa8007bf9aba0378f7c7259a34d39',
 'src/plugin-sdk/file-access-runtime.ts': '4815132a128f5ea4da642ef76571345f313f3cfa8161839beb52df15597a96f9',
 'src/infra/file-descriptor.ts': 'ccaf5d9a38f77be1ca5b10d843626b2fdd894fd4299a8165cf78b210af21ab50',
 'src/infra/fs-safe.ts': '4df60b4136ca5f0b117a90e257a41a8b448638c4f46112ca43240f7a23b1fc6a',
 'src/infra/directory-durability.ts': '2870fe5841c6cde1260fa8564f14e187a96a42e44affd67a59e6e4391c2de1ad',
 'src/agents/workspace-bootstrap-publish.ts': 'abad65e904b473f569e4875664fee1d1ff53b6d3d9f8c3cdf428246f079a9659',
 'src/agents/agent-tools.read.ts': '34db04c4719a01d2b173c690498707e42c2dc8d1b8f6b1bca211fce9c08e3a6a'}
COMPILED_ANCHORS = {'dist/short-term-promotion-memory-write-DLJgScco.mjs': ('export { commitMemoryContent, '
                                                         'resolveMemoryWritePath };',),
 'dist/short-term-promotion-memory-write-HTLC95gL.mjs': ('async function commitMemoryContent(params) {',
                                                         'async function writeExistingMemoryInPlace(params) '
                                                         '{',
                                                         'var MemoryAtomicPublicationError = class extends '
                                                         'Error {'),
 'dist/security-runtime-D3RcbWGb.mjs': ('import { movePathWithCopyFallback as movePathWithCopyFallback$1, '
                                        'replaceFileAtomic as replaceFileAtomic$1 } from '
                                        '"@openclaw/fs-safe/atomic";',),
 'dist/file-descriptor-B4yBUiAP.mjs': ('import { copyFileHandle, overwriteFileHandle as '
                                       'overwriteFileHandle$1, writeFileWindowFully } from '
                                       '"@openclaw/fs-safe/advanced";',),
 'dist/error-coercion-1P2One0X.mjs': ('function extractErrorCode(err) {',),
 'dist/workspace-C0LMBmap.mjs': ('async function publishBootstrapFile(filePath, content, '
                                 'beforePersistentApply) {',
                                 'publishBootstrapFile as u'),
 'dist/fs-safe-CHQXnCPk.mjs': ('async function root$1(rootDir, defaults) {', 'root$1 as w,'),
 'dist/directory-durability-fWp4i1Sl.mjs': ('function requireDirectorySync(outcome, label) {',)}
COMPILED_HASHES = {'dist/short-term-promotion-memory-write-DLJgScco.mjs': 'bd78827cf89ebf4fae7384225d95c9150835b8be2d5cceccdecc87dedbdb8aa5',
 'dist/short-term-promotion-memory-write-HTLC95gL.mjs': '0c5107c106706654ac87dba9f499024ff7e7f57fb9e5ffcd7e3e4c01d9732d46',
 'dist/security-runtime-D3RcbWGb.mjs': 'd6c1dae5bce79f6a283619c32707067b74738b15c3e1a1f209e39df2b5cf728a',
 'dist/file-descriptor-B4yBUiAP.mjs': '262ebb537b1560095f05f2599c08d4b9e3810bcc88a0a7a3a8c572c7a4df9a49',
 'dist/error-coercion-1P2One0X.mjs': 'dc084c616cc292128c5ff39fc77cf2a5cf9487bd0e8339bb0a8aa215110646b6',
 'dist/workspace-C0LMBmap.mjs': 'c39922b28d2d5f7893d7b2a19afbcba3392283af318ab3ecc72d57cf0ae765ba',
 'dist/fs-safe-CHQXnCPk.mjs': 'f3c36c1f9de0572825f72f154c5f2e6e969a7e1fb7ab7914933bb40d18c18414',
 'dist/directory-durability-fWp4i1Sl.mjs': '3bcf8705742ed16bdc380faae3e6d557d3c2aa23ce38fb4d3f8c88904e084563'}
EXTERNAL_ANCHORS = {'dist/root.js': ('export { DEFAULT_ROOT_MAX_BYTES, openLocalFileSafely, readLocalFileSafely, '
                  'resolveOpenedFileRealPathForHandle, root, } from "./root-impl.js";',),
 'dist/root-impl.js': ('export class RootHandle {',
                       '    async append(relativePath, data, options = {}) {',
                       'export async function root(rootDir, defaults = {}) {',
                       'async function openWritableFileInRoot(root, params, options) {',
                       'async function appendFileInRoot(root, params) {'),
 'dist/atomic.js': ('export { replaceFileAtomic, replaceFileAtomicSync, } from "./replace-file.js";',),
 'dist/advanced.js': ('export { writeFileWindowFully } from "./write-file-handle.js";',),
 'dist/replace-file.js': ('export async function replaceFileAtomic(options) {',
                          'async function replaceFileAtomicUnserialized(options, filePath, renameIdentity, '
                          'mutation, syncParent) {'),
 'dist/replace-file-descriptor.js': ('export async function writeTempFile(params) {',),
 'dist/replace-file-temp-owner.js': ('export class AsyncAtomicTempOwner extends AtomicTempOwner {',
                                     'function cleanupFailure(originalFailure, cleanupError) {',
                                     'function closeFailure(closeError, params, cleanupFailure) {'),
 'dist/replace-file-mode.js': ('export function inheritedRegularFileMode(stat) {',),
 'dist/file-cleanup.js': ('export async function removeOwnedPath(params) {',),
 'dist/file-sync.js': ('export async function syncFileBestEffort(handle) {',
                       'export function syncFileBestEffortSync(fd, fsModule = fs) {'),
 'dist/write-file-handle.js': ('export async function writeFileWindowFully(handle, bytes, position, options '
                               '= {}) {',
                               'export async function writeAllToFile(target, data, options = {}) {'),
 'dist/write-queue.js': ('export async function serializePathWrite(key, run) {',),
 'dist/strict-file-identity.js': ('export async function inspectFileIdentity(inspect, expected, platform = '
                                  'process.platform) {',
                                  'export function inspectFileIdentitySync(inspect, expected, platform = '
                                  'process.platform, mismatch = fileIdentityMismatchError) {'),
 'dist/directory-durability.js': ('export async function syncDirectoryBestEffort(directoryPath) {',),
 'dist/errors.js': ('export function categorizeFsSafeError(code) {',
                    'export class FsSafeError extends Error {'),
 'dist/root-errors.js': ('export function normalizePinnedWriteError(error) {',),
 'dist/pinned-write.js': ('export async function runPinnedWriteHelper(params) {',
                          'export async function runPinnedWriteWithRenamePolicy(params) {'),
 'dist/native-pinned-write.js': ('export async function runPinnedWriteNative(binding, params) {',),
 'dist/native-parent-admission.js': ('export async function openNativeRootAdmission(binding, params) {',
                                     'export async function openNativeParentAdmission(binding, '
                                     'rootAdmission, relativeParentPath, observation) {'),
 'dist/native-staged-file.js': ('class NativeStagedFile {',
                                'export const createNativeStage = NativeStagedFile.create;',
                                'export const writeNativeStage = NativeStagedFile.write;',
                                '    async publish(basename, options, onPublished) {',
                                '    #finalize() {'),
 'dist/staged-file-settlement.js': ('export function createStagedFileReceipt(directory, temporaryBasename, '
                                    'stat) {',
                                    'export function stagedFileFailure(error, details) {'),
 'dist/staged-directory.js': ('export function describeStagedDirectory(fd, pathname) {',
                              'export function assertStagedDirectoryCurrent(receipt) {'),
 'dist/native-binding.js': ('export function captureNativeFdClose(binding) {',),
 'dist/native-rename-outcome.js': ('export function classifyNativeRenameFailure(error) {',),
 'dist/native.js': ('function loadBundledBinding() {',
                    'export function getNativeBinding() {',
                    '    const loaded = require(nativePackageForTarget(target));'),
 'dist/native-config.js': ('export function getFsSafeNativeConfig() {',)}
EXTERNAL_HASHES = {'dist/root.js': 'c13b886e66b7684d1025acb4993da8a11f07a82dd811241f14a47f84c2ed72dd',
 'dist/root-impl.js': '44038d8acaf1a7f4a5aa675ceb52aed90d8217c9f353835b8f2f390fb23a8f36',
 'dist/atomic.js': 'e2f2c978674bd3b21579cc3a9f351dd19b2a3a2411346ca1a7d8429714bc97e9',
 'dist/advanced.js': 'fe1bce14b7d9676230e77ccd06d3f1a9012c517f5752833b25d1cb6b9a6c6a9c',
 'dist/replace-file.js': 'ee02805fb04856879c7c027b64566ef7b7004926d64d961703cfee70f1e6f4c3',
 'dist/replace-file-descriptor.js': '9ca3c2bca30012a6e70c100ad001368c3b98242b04228da84e7875afc9ed7eb1',
 'dist/replace-file-temp-owner.js': '2c5c28174e0d29ece2ef574c99aa784f6cf1c4b79928cc5a79e2fbc5977322bc',
 'dist/replace-file-mode.js': '0b14605c39e40066ffa2a1e6d67adf3a8f1a5b579ec2f3efdfaafd2a4fc42aae',
 'dist/file-cleanup.js': '7e4339d62609e74988a0fa1c04c6c98ec31bde5be4e4d6f6a8def308bc1aa44a',
 'dist/file-sync.js': '6d7485625782f21d32ec8efa4cfaab5fa897afa1fcea5acbeea9c41c2910c8f4',
 'dist/write-file-handle.js': 'fc39fb43c9a41658c24ac21d80fb3147375f6d82964542b2a6622c485b1af09b',
 'dist/write-queue.js': '87b49d5950578f7e38f6a4cec7bdbb376d0d1914399927dccff3a7b893f23c0c',
 'dist/strict-file-identity.js': '6c6a03ceb1f4045b598a7f8f327a4c1c7049891b252f88bfe03d759b7abc1860',
 'dist/directory-durability.js': '1344b73f9e2fb9fe042b7f78420b41a5c3bc5691acd6ad312a8cf57dc7e9cb5f',
 'dist/errors.js': '3fd6400f3981c280d1f61f67555132ca0af47ed26ce50f85f13b2fcaca8d5b28',
 'dist/root-errors.js': '1c67e26e5b54ee0976248e50810dce41304d0f74310344b7ee9a4dbd3b0dfdfa',
 'dist/pinned-write.js': 'fcf44192e91b724aa9b4f1dfa751e454383b6b341756171be0485a09fa41b2f3',
 'dist/native-pinned-write.js': '14ef84b1ea6ca8322ef1be1d1043cedd773715ab57361d72ee554b8977a01689',
 'dist/native-parent-admission.js': '1afc836ab725e8a45dd2c671a20409218490ef2dbcdf3de1d5dbcec05f02c933',
 'dist/native-staged-file.js': 'dcb5107b3d805c4fef6e08249dc60a2c6ace4421dd93d7f5f4817b4cca974676',
 'dist/staged-file-settlement.js': 'c6718d0867bf66c8434c0eddeb1023bd0a0be36590d7c5e7ef62d41dfdaade5f',
 'dist/staged-directory.js': '12ffc1c9a91c5633172ec8de8929cc8e9dd70145eac50f265e4a5036f8dd013e',
 'dist/native-binding.js': '0e08d01eb6eee9bc2ccd3bcb855393302cd18f0f91f398069f1f63b9c7d8f720',
 'dist/native-rename-outcome.js': 'c7b0d8fc18bcac348b9b2330b03a9ef15e64b229ff2fee680b8cfa515ccf39c4',
 'dist/native.js': '29be2ed4afc31d22dc31d7d08aa113ef4823392d3fe144c576f9d9604b004a73',
 'dist/native-config.js': '50632a01fc464bff05518eca7a5f1e7f59777b2876e92c3660c93067b129d9be'}
PACKAGE_HASHES = {'node_modules/@openclaw/fs-safe': '69241330487f571a0daf239e704dc82876227273bbea27b158cdf6f5e2181430',
 'node_modules/@openclaw/fs-safe-linux-x64-gnu': '51f30bade0676b5400f422626b939d63408b8f3a173f6ecfd4582cee66c5dfeb'}
NATIVE_BINARY_SHA256 = "f1aad2619542e43af6f28606e7514054bd0824814f2a2bb4b72f5e16e9ea2d7c"
EXTERNAL_HASHES.update({
    "dist/durability.js": "2a9c105a960e36d3e4a429020e9bb7f77ffdf72a284e533d4208546e58655583",
    "dist/publish-file.js": "37ac0cc109152e3470b1973be933a4d344cdf892ec85fd999c4fe660da086818",
    "dist/temp-cleanup.js": "62ed4a1a2acb7367857014b67bbd14f32b497673e410667cb54c402ad30009bb",
    "dist/file-identity.js": "7a402c9423810d389dd0c7f9574d076bc9319c60b14fb06247b5ffbef4034973",
})
EXTERNAL_ANCHORS.update({
    "dist/durability.js": ('export { isHardlinkFallbackError, publishFileExclusive, } from "./publish-file.js";',),
    "dist/publish-file.js": ("export function isHardlinkFallbackError(error) {",),
    "dist/temp-cleanup.js": ("function cleanupRegisteredTempPathsSync() {",
                             "export function registerTempPathForExit(tempPath, options) {",
                             'process.once("exit", cleanupRegisteredTempPathsSync);'),
    "dist/file-identity.js": ("export function sameFileIdentityForCleanup(left, right, platform = process.platform) {",),
})

SOURCE_LINKS = (
    ("extensions/memory-core/src/short-term-promotion-memory-write.ts", "openclaw/plugin-sdk/security-runtime",
     (("replaceFileAtomic", "replaceFileAtomic"),), "import"),
    ("extensions/memory-core/src/short-term-promotion-memory-write.ts", "openclaw/plugin-sdk/file-access-runtime",
     (("writeFileWindowFully", "writeFileWindowFully"),), "import"),
    ("src/plugin-sdk/security-runtime.ts", "@openclaw/fs-safe/atomic", (("replaceFileAtomic", "replaceFileAtomic"),), "export"),
    ("src/plugin-sdk/file-access-runtime.ts", "../infra/file-descriptor.js", (("writeFileWindowFully", "writeFileWindowFully"),), "export"),
    ("src/infra/file-descriptor.ts", "@openclaw/fs-safe/advanced", (("writeFileWindowFully", "writeFileWindowFully"),), "export"),
    ("src/infra/fs-safe.ts", "@openclaw/fs-safe/root", (("root", "fsSafeRoot"),), "import"),
    ("src/agents/workspace-bootstrap-publish.ts", "../infra/fs-safe.js", (("FsSafeError", "FsSafeError"), ("root", "fsRoot")), "import"),
    ("src/agents/workspace-bootstrap-publish.ts", "../infra/directory-durability.js", (("isHardlinkFallbackError", "isHardlinkFallbackError"),), "import"),
    ("src/infra/directory-durability.ts", "@openclaw/fs-safe/durability", (("isHardlinkFallbackError", "isHardlinkFallbackError"),), "export"),
)

COMPILED_LINKS = (
    ("dist/short-term-promotion-memory-write-DLJgScco.mjs", "./short-term-promotion-memory-write-HTLC95gL.mjs",
     (("i", "commitMemoryContent"), ("l", "resolveMemoryWritePath")), "import"),
    ("dist/short-term-promotion-memory-write-HTLC95gL.mjs", "./security-runtime-D3RcbWGb.mjs", (("r", "replaceFileAtomic"),), "import"),
    ("dist/short-term-promotion-memory-write-HTLC95gL.mjs", "./file-descriptor-B4yBUiAP.mjs", (("a", "writeFileWindowFully"),), "import"),
    ("dist/short-term-promotion-memory-write-HTLC95gL.mjs", "./error-coercion-1P2One0X.mjs", (("i", "extractErrorCode"),), "import"),
    ("dist/security-runtime-D3RcbWGb.mjs", "@openclaw/fs-safe/atomic", (("replaceFileAtomic", "replaceFileAtomic$1"),), "import"),
    ("dist/file-descriptor-B4yBUiAP.mjs", "@openclaw/fs-safe/advanced", (("writeFileWindowFully", "writeFileWindowFully"),), "import"),
    ("dist/workspace-C0LMBmap.mjs", "./fs-safe-CHQXnCPk.mjs", (("t", "FsSafeError"), ("w", "root")), "import"),
    ("dist/workspace-C0LMBmap.mjs", "./directory-durability-fWp4i1Sl.mjs", (("r", "isHardlinkFallbackError"),), "import"),
    ("dist/fs-safe-CHQXnCPk.mjs", "@openclaw/fs-safe/root", (("root", "root"),), "import"),
    ("dist/directory-durability-fWp4i1Sl.mjs", "@openclaw/fs-safe/durability", (("isHardlinkFallbackError", "isHardlinkFallbackError"),), "import"),
)

EXTERNAL_LINKS = (
    ("dist/replace-file-temp-owner.js", "./temp-cleanup.js", (("registerTempPathForExit", "registerTempPathForExit"),), "import"),
    ("dist/temp-cleanup.js", "./file-identity.js", (("sameFileIdentityForCleanup", "sameFileIdentityForCleanup"),), "import"),
    ("dist/durability.js", "./publish-file.js", (("isHardlinkFallbackError", "isHardlinkFallbackError"),), "export"),
    ("dist/root.js", "./root-impl.js", (("root", "root"),), "export"),
    ("dist/atomic.js", "./replace-file.js", (("replaceFileAtomic", "replaceFileAtomic"),), "export"),
    ("dist/advanced.js", "./write-file-handle.js", (("writeFileWindowFully", "writeFileWindowFully"),), "export"),
    ("dist/replace-file.js", "./replace-file-descriptor.js", (("writeTempFile", "writeTempFile"), ("syncDirectoryBestEffort", "syncDirectoryBestEffort")), "import"),
    ("dist/replace-file.js", "./replace-file-temp-owner.js", (("AsyncAtomicTempOwner", "AsyncAtomicTempOwner"),), "import"),
    ("dist/replace-file.js", "./write-queue.js", (("serializePathWrite", "serializePathWrite"),), "import"),
    ("dist/replace-file-descriptor.js", "./file-sync.js", (("syncFileBestEffort", "syncFileBestEffort"),), "import"),
    ("dist/replace-file-temp-owner.js", "./file-cleanup.js", (("removeOwnedPath", "removeOwnedPath"),), "import"),
    ("dist/root-impl.js", "./write-file-handle.js", (("writeAllToFile", "writeAllToFile"),), "import"),
    ("dist/root-impl.js", "./replace-file-temp-owner.js", (("removePathIfIdentityUnchanged", "removePathIfIdentityUnchanged"),), "import"),
    ("dist/root-impl.js", "./pinned-write.js", (("runPinnedWriteHelper", "runPinnedWriteHelper"), ("runPinnedWriteWithRenamePolicy", "runPinnedWriteWithRenamePolicy")), "import"),
    ("dist/pinned-write.js", "./native-pinned-write.js", (("runPinnedWriteNative", "runPinnedWriteNative"),), "import"),
    ("dist/native-pinned-write.js", "./native-staged-file.js", (("writeNativeStage", "writeNativeStage"),), "import"),
    ("dist/native-pinned-write.js", "./native-parent-admission.js", (("openNativeRootAdmission", "openNativeRootAdmission"), ("openNativeParentAdmission", "openNativeParentAdmission")), "import"),
    ("dist/native-pinned-write.js", "./native-binding.js", (("captureNativeFdClose", "captureNativeFdClose"),), "import"),
    ("dist/native-staged-file.js", "./native-binding.js", (("captureNativeFdClose", "captureNativeFdClose"),), "import"),
    ("dist/native-staged-file.js", "./staged-file-settlement.js", (("createStagedFileReceipt", "createStagedFileReceipt"), ("stagedFileFailure", "failure")), "import"),
    ("dist/native-staged-file.js", "./native-rename-outcome.js", (("classifyNativeRenameFailure", "classifyNativeRenameFailure"),), "import"),
    ("dist/native.js", "./native-config.js", (("getFsSafeNativeConfig", "getFsSafeNativeConfig"),), "import"),
)

COMMIT_COMPILED_ARTIFACTS = tuple(path for path in COMPILED_HASHES if path.startswith((
    "dist/short-term-promotion-memory-write-", "dist/security-runtime-", "dist/file-descriptor-", "dist/error-coercion-",
)))
COMMIT_EXTERNAL_ARTIFACTS = (
    "dist/atomic.js", "dist/advanced.js", "dist/replace-file.js", "dist/replace-file-descriptor.js",
    "dist/replace-file-temp-owner.js", "dist/replace-file-mode.js", "dist/file-cleanup.js", "dist/file-sync.js",
    "dist/write-file-handle.js", "dist/write-queue.js", "dist/strict-file-identity.js", "dist/errors.js",
    "dist/temp-cleanup.js", "dist/file-identity.js",
)
APPEND_EXTERNAL_ARTIFACTS = (
    "dist/root.js", "dist/root-impl.js", "dist/write-file-handle.js", "dist/replace-file-temp-owner.js",
    "dist/file-cleanup.js", "dist/strict-file-identity.js", "dist/directory-durability.js", "dist/errors.js",
)
BOOTSTRAP_COMPILED_ARTIFACTS = (
    "dist/workspace-C0LMBmap.mjs", "dist/fs-safe-CHQXnCPk.mjs", "dist/directory-durability-fWp4i1Sl.mjs",
)
BOOTSTRAP_EXTERNAL_ARTIFACTS = (
    "dist/root.js", "dist/root-impl.js", "dist/pinned-write.js", "dist/native-pinned-write.js",
    "dist/native-parent-admission.js", "dist/native-staged-file.js", "dist/native-binding.js",
    "dist/native-rename-outcome.js", "dist/native.js", "dist/native-config.js", "dist/staged-directory.js",
    "dist/staged-file-settlement.js", "dist/write-file-handle.js", "dist/file-sync.js", "dist/root-errors.js",
    "dist/strict-file-identity.js", "dist/write-queue.js", "dist/errors.js", "dist/durability.js", "dist/publish-file.js",
)
NATIVE_BINDING_OWNER = (NATIVE_PACKAGE, "fs-safe-native.node")
REQUIRED_ARTIFACTS_BY_OPERATION = {
    "atomic-commit-runtime": tuple((OPENCLAW_PACKAGE, path) for path in COMMIT_COMPILED_ARTIFACTS)
        + tuple((FS_SAFE_PACKAGE, path) for path in COMMIT_EXTERNAL_ARTIFACTS),
    "atomic-append-runtime": tuple((FS_SAFE_PACKAGE, path) for path in APPEND_EXTERNAL_ARTIFACTS),
    "atomic-bootstrap-runtime": tuple((OPENCLAW_PACKAGE, path) for path in BOOTSTRAP_COMPILED_ARTIFACTS)
        + tuple((FS_SAFE_PACKAGE, path) for path in BOOTSTRAP_EXTERNAL_ARTIFACTS) + (NATIVE_BINDING_OWNER,),
}
ENTRYPOINTS = {
    "atomic-commit-runtime": {"package": OPENCLAW_PACKAGE, "path": "dist/short-term-promotion-memory-write-DLJgScco.mjs", "export": "commitMemoryContent"},
    "atomic-append-runtime": {"package": FS_SAFE_PACKAGE, "path": "dist/root.js", "export": "root"},
    "atomic-bootstrap-runtime": {"package": OPENCLAW_PACKAGE, "path": "dist/workspace-C0LMBmap.mjs", "export": "u", "originalBinding": "publishBootstrapFile"},
}


class AtomicPublicationBindingError(ValueError):
    """An original atomic owner or its external native dependency changed."""


def _file(root: Path, relative: str) -> Path:
    item = PurePosixPath(relative)
    file = root / relative
    if (not relative or item.is_absolute() or ".." in item.parts or "\\" in relative
            or item.as_posix() != relative or not file.is_file()
            or any(part.is_symlink() for part in (file, *file.parents) if part.is_relative_to(root))
            or not file.resolve().is_relative_to(root)):
        raise AtomicPublicationBindingError("An atomic owner escaped its exact reviewed tree.")
    return file


def _owners(root: Path, hashes: dict, anchors: dict, *, committed: bool = False) -> tuple[dict, list]:
    text, evidence = {}, []
    if set(hashes) != set(anchors):
        raise AtomicPublicationBindingError("Every atomic owner requires its exact declarations.")
    for relative, digest in hashes.items():
        raw = _file(root, relative).read_bytes()
        if (hashlib.sha256(raw).hexdigest() != digest or committed
                and hashlib.sha256(_git(root, "show", f"HEAD:{relative}")).hexdigest() != digest):
            raise AtomicPublicationBindingError("An atomic owner differs from its reviewed bytes.")
        source = raw.decode("utf-8")
        locations = []
        for anchor in anchors[relative]:
            if source.count(anchor) != 1:
                raise AtomicPublicationBindingError("An atomic owner has no unique reviewed declaration.")
            locations.append({"anchor": anchor, "line": source[:source.index(anchor)].count("\n") + 1})
        text[relative] = source
        evidence.append({"path": relative, "sha256": digest, "anchors": locations})
    return text, evidence


def _links(sources: dict, specifications: tuple) -> list:
    result = []
    for module, specifier, expected, kind in specifications:
        matches = [match for match in _NAMED_FROM.finditer(sources[module])
                   if match["kind"] == kind and match["specifier"] == specifier and not match["types"]]
        if len(matches) != 1 or not all(pair in _runtime_names(matches[0]) for pair in expected):
            raise AtomicPublicationBindingError("An atomic owner import alias or target changed.")
        match = matches[0]
        result.append({"path": module, "kind": kind, "specifier": specifier,
            "bindings": [{"sourceBinding": before, "destinationBinding": after} for before, after in expected],
            "line": sources[module][:match.start()].count("\n") + 1,
            "declarationSha256": hashlib.sha256(match[0].encode()).hexdigest()})
    return result


def prepare_atomic_publication_bindings(checkout: Path, runtime_root: Path) -> dict:
    """Authenticate the three bounded operation owners, never execute them."""
    checkout, runtime_root = Path(checkout), Path(runtime_root)
    if checkout.is_symlink() or runtime_root.is_symlink():
        raise AtomicPublicationBindingError("Atomic owner roots cannot borrow a symlink identity.")
    checkout, runtime_root = checkout.resolve(), runtime_root.resolve()
    try:
        if (_git(checkout, "rev-parse", "HEAD").decode().strip() != REFERENCE_COMMIT
                or Path(_git(checkout, "rev-parse", "--show-toplevel").decode().strip()).resolve() != checkout
                or _git(checkout, "status", "--porcelain", "--untracked-files=no").strip()):
            raise AtomicPublicationBindingError("Atomic owners require the unchanged exact pinned checkout.")
        source_text, source = _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
        compiled_text, compiled = _owners(runtime_root, COMPILED_HASHES, COMPILED_ANCHORS)
        external_root, native_root = runtime_root.parent / "@openclaw/fs-safe", runtime_root.parent / "@openclaw/fs-safe-linux-x64-gnu"
        external_text, external = _owners(external_root, EXTERNAL_HASHES, EXTERNAL_ANCHORS)
        packages = []
        for package, root in ((FS_SAFE_PACKAGE, external_root), (NATIVE_PACKAGE, native_root)):
            raw = _file(root, "package.json").read_bytes()
            if hashlib.sha256(raw).hexdigest() != PACKAGE_HASHES[package]:
                raise AtomicPublicationBindingError("An atomic dependency package identity changed.")
            metadata = json.loads(raw)
            if metadata["name"] != package.removeprefix("node_modules/") or metadata["version"] != "0.21.1":
                raise AtomicPublicationBindingError("An atomic dependency is not the reviewed package.")
            if (package == FS_SAFE_PACKAGE and metadata["exports"]["./root"]["default"] != "./dist/root.js"
                    or package == NATIVE_PACKAGE and (metadata["main"] != "fs-safe-native.node"
                        or metadata["os"] != ["linux"] or metadata["cpu"] != ["x64"] or metadata["libc"] != ["glibc"])):
                raise AtomicPublicationBindingError("An atomic package resolution changed.")
            packages.append({"package": package, "path": "package.json", "sha256": PACKAGE_HASHES[package],
                             "name": metadata["name"], "version": metadata["version"]})
        native_bytes = _file(native_root, "fs-safe-native.node").read_bytes()
        if hashlib.sha256(native_bytes).hexdigest() != NATIVE_BINARY_SHA256 or native_bytes[:4] != b"\x7fELF":
            raise AtomicPublicationBindingError("The default Linux x64 native binding changed.")
        source_links, compiled_links = _links(source_text, SOURCE_LINKS), _links(compiled_text, COMPILED_LINKS)
        external_links = _links(external_text, EXTERNAL_LINKS)
    except (OSError, UnicodeError, ValueError, KeyError) as error:
        raise AtomicPublicationBindingError("Atomic publication owner provenance could not be verified.") from error
    return {
        "kind": "official-release-atomic-publication-owners", "referenceCommit": REFERENCE_COMMIT,
        "sourceBuildReproduced": False, "providerTransportVerified": False,
        "managerExecutionVerified": False, "indexExecutionVerified": False, "workerExecutionVerified": False,
        "fullAgentToolExecutionVerified": False, "fullPromotionSchedulerExecutionVerified": False,
        "sourceBindings": source, "compiledBindings": compiled,
        "sourceImportLinks": source_links, "compiledImportLinks": compiled_links,
        "externalRuntimeBindings": [{"package": FS_SAFE_PACKAGE, **row} for row in external],
        "externalImportLinks": [{"package": FS_SAFE_PACKAGE, **row} for row in external_links],
        "packageBindings": packages,
        "nativeBinaryBindings": [{"package": NATIVE_PACKAGE, "path": "fs-safe-native.node",
                                   "sha256": NATIVE_BINARY_SHA256, "format": "ELF", "target": "linux-x64-gnu"}],
        "entrypoints": {operation: dict(entry) for operation, entry in ENTRYPOINTS.items()},
        "requiredLoadedOwnersByOperation": {operation: [{"package": package, "path": path} for package, path in owners]
                                             for operation, owners in REQUIRED_ARTIFACTS_BY_OPERATION.items()},
        "nativeResolution": {"package": FS_SAFE_PACKAGE, "loader": "dist/native.js", "function": "loadBundledBinding",
            "target": "linux-x64-gnu", "resolvedPackage": NATIVE_PACKAGE, "resolvedEntry": "fs-safe-native.node",
            "nativeModeOverridePermitted": False, "testLoaderPermitted": False,
            "actualResolutionAndNapiCallsRequired": True},
        "receiptPhysicalInterchangeabilityClaimed": False,
        "fixtureBoundary": "Three original direct operation owners only. Pins do not establish execution; "
            "the protected collector must separately bind imports, actual native resolution, same owned "
            "stage/descriptor statistics, delegated IO, complete errors and surviving files. Direct commit "
            "does not claim the promotion scheduler, maintenance IPC or an agent memory tool executed.",
    }
