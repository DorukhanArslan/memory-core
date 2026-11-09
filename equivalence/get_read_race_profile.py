"""Exact official read-hook authority for one owned pre-open replacement.

This capability controls real filesystem fixture mutations at the original
owner's test seam. It supplies no file bytes, descriptor result, memory policy,
backend override, or replacement read implementation.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import stat
from typing import Any


GET_READ_RACE_INPUT = {"kind": "owned-leaf-to-symlink", "hook": "afterPreOpenLstat"}
GET_READ_RACE_PROFILE = {
    "kind": "approved-get-read-race-profile",
    "operation": "get-contract-runtime",
    "inputKind": "tool",
    "hook": "afterPreOpenLstat",
    "mutation": "owned-leaf-to-symlink",
    "module": "node_modules/@openclaw/fs-safe/dist/test-hooks.js",
    "sha256": "207753c214f21d77c7cc82b947f24705c937009a73057ddb08a8ef058334e273",
}

_ROOT = "node_modules/@openclaw/fs-safe/dist/"
OWNER_HASHES = {
    _ROOT + "test-hooks.js": GET_READ_RACE_PROFILE["sha256"],
    _ROOT + "local-file-descriptor.js": "b18731ab7703540e2f399af90838d5c33e366792cf784a6be8c41554c5a29f43",
    _ROOT + "root-impl.js": "44038d8acaf1a7f4a5aa675ceb52aed90d8217c9f353835b8f2f390fb23a8f36",
}
OWNER_ANCHORS = {
    _ROOT + "test-hooks.js": (
        'return process.env.NODE_ENV === "test" || process.env.VITEST === "true";',
        "export function __setFsSafeTestHooksForTest(hooks) {",
        "fsSafeTestHooks = hooks;",
    ),
    _ROOT + "local-file-descriptor.js": (
        'import { getFsSafeTestHooks } from "./test-hooks.js";',
        "export async function openLocalFileDescriptor(filePath, options) {",
        "const stat = fsSync.lstatSync(filePath, { bigint: true });",
        "await fsSafeTestHooks?.afterPreOpenLstat?.(filePath);",
        "handle = await fs.open(filePath, openFlags)",
    ),
    _ROOT + "root-impl.js": (
        'import { openLocalFileDescriptor } from "./local-file-descriptor.js";',
        'import { getFsSafeTestHooks } from "./test-hooks.js";',
        "async function openFileInRoot(root, params) {",
        "const { handle, stat, identity } = await openLocalFileDescriptor(resolved, {",
        "const admitted = await admitRootReadHandle({",
        "async function readFileInRoot(root, params) {",
    ),
}


def validate_get_read_race_profile(value: Any) -> dict[str, str]:
    """Reject any additional operation, hook, mutation, module, or authority."""
    if not isinstance(value, dict) or value != GET_READ_RACE_PROFILE:
        raise ValueError("Read races require the exact reviewed whole-get pre-open capability")
    return deepcopy(value)


def validate_get_read_race_case(case: Any) -> None:
    """Bind the seam to its literal owned fixture and single genuine tool call."""
    if not isinstance(case, dict) or case.get("operation") != "get-contract-runtime":
        raise ValueError("An unrelated operation cannot borrow the get read-race capability")
    expected = build_storage_path_read_race_cases()[0]["input"]
    if (not isinstance(case.get("input"), dict) or case["input"] != expected
            or case["input"].get("observeFilesystem") is not True
            or case["input"].get("normalizeFixturePaths") is not True):
        raise ValueError("Read races require the exact owned leaf-replacement fixture")


def prepare_get_read_race_bindings(runtime_root: Path) -> dict[str, Any]:
    """Authenticate the official hook, pre-open caller and real root reader."""
    runtime_root = Path(runtime_root).absolute()
    if (runtime_root.name != "openclaw" or runtime_root.parent.name != "node_modules"
            or runtime_root.resolve() != runtime_root or not runtime_root.is_dir()):
        raise ValueError("Read-race bindings require the authenticated installed OpenClaw root")
    installation = runtime_root.parent.parent
    owners = []
    for relative, digest in OWNER_HASHES.items():
        filename = installation / relative
        if (any(part.is_symlink() for part in (filename, *filename.parents) if part != installation)
                or not filename.resolve().is_relative_to(installation)):
            raise ValueError("A read-race owner escaped its authenticated installation")
        info = filename.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 2 * 1024 * 1024:
            raise ValueError("Read-race owners require independent bounded regular artifacts")
        raw = filename.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("An official read-race owner differs from its reviewed bytes")
        source = raw.decode("utf-8")
        anchors = []
        positions = []
        for anchor in OWNER_ANCHORS[relative]:
            if source.count(anchor) != 1:
                raise ValueError("A read-race owner lacks its unique original caller linkage")
            position = source.index(anchor)
            positions.append(position)
            anchors.append({"anchor": anchor, "line": source[:position].count("\n") + 1})
        if positions != sorted(positions):
            raise ValueError("The genuine read-race hook no longer has its reviewed call order")
        owners.append({"path": relative, "sha256": digest, "anchors": anchors})
    return {
        "kind": "official-release-get-read-race-seam",
        "operation": "get-contract-runtime",
        "hook": "afterPreOpenLstat",
        "setterExport": "__setFsSafeTestHooksForTest",
        "compiledBindings": owners,
        "callerEdges": [
            {"owner": _ROOT + "root-impl.js", "caller": "openFileInRoot",
             "calleeOwner": _ROOT + "local-file-descriptor.js", "callee": "openLocalFileDescriptor"},
            {"owner": _ROOT + "local-file-descriptor.js", "before": "fsSync.lstatSync",
             "hook": "afterPreOpenLstat", "after": "fs.open"},
        ],
        "backendOverrides": False,
        "readResultSubstitution": False,
        "workerRequired": False,
    }


def prepare_get_read_race_profile(case: dict[str, Any], runtime_root: Path) -> dict[str, str]:
    """Grant only the literal reviewed case after all original owners authenticate."""
    validate_get_read_race_case(case)
    prepare_get_read_race_bindings(runtime_root)
    return validate_get_read_race_profile(GET_READ_RACE_PROFILE)


def build_storage_path_read_race_cases() -> list[dict[str, Any]]:
    """One predeclared real OS mutation; no acceptance credit is assigned."""
    return [{
        "id": "storage-path-read-race-owned-leaf-to-symlink",
        "requirement": "storage.path-safety",
        "covers": [],
        "operation": "get-contract-runtime",
        "driverScope": (
            "The genuine provider-none memory_get factory/execute and original secure read owners "
            "run with one official afterPreOpenLstat test seam. The callback is armed once for "
            "the exact owned workspace/memory/race.md path, renames that actual file to "
            "workspace/memory/race.before.md, and creates a real symlink to sibling owned "
            "outside/secret.md. Original open, descriptor identity, root fences and byte reads "
            "remain intact. NODE_ENV=test exists synchronously during the official setter only "
            "and is restored before execute; VITEST and native backend configuration stay unchanged. "
            "No arbitrary hook, callback, target, provider, backend fallback or read result is supplied."
        ),
        "normalizationPolicy": (
            "Complete ordered public envelopes and original raw JSON carriers are retained. "
            "Every text carrier must parse exactly to details before comparison. Only the exact "
            "private fixture-base prefix maps to $FIXTURE; errors, causes, codes and all fields "
            "remain unchanged. Complete nofollow before/after snapshots retain all actual stat "
            "properties and file bytes. The observed intentional fixture rename/symlink changes "
            "make contentUnchanged and writeStatsUnchanged false; this is declared external OS "
            "input, not a product write, and is never repaired or omitted. Hook arming, dispatch, "
            "disarm, exact mutation ownership and environment before/during/after stay attested."
        ),
        "input": {
            "kind": "tool",
            "normalizeFixturePaths": True,
            "observeFilesystem": True,
            "readRace": deepcopy(GET_READ_RACE_INPUT),
            "files": {"memory/race.md": "Original admitted bytes.\n"},
            "outsideFiles": {"secret.md": "Owned outside sentinel must not be read.\n"},
            "steps": [{"params": {"path": "memory/race.md"}}],
        },
    }]
