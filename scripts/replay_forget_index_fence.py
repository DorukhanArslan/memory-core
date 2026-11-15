"""Independently replay an explicitly selected frozen family from retained roots.

This diagnostic starts no original engine, repairs no capture and awards no
acceptance credit. All source roots and the decoder executable are explicit.
V5/V6 may instead stream an actual complete registered-suite report and its
independently selected Native/SDK capture roots, without collector substitutes.
"""
from __future__ import annotations

import argparse
import hashlib
from importlib import import_module
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from equivalence.harness import _validate_reference  # noqa: E402
from equivalence.model_runtime_authority import prepare_model_node_authority  # noqa: E402
from equivalence.promotion_apply_family import differences  # noqa: E402
from memory_core.project_name import PACKAGE_NAME  # noqa: E402

SHA256 = re.compile(r"[0-9a-f]{64}\Z")
# Full catalog reports are streamed; collector and engine packet limits stay separate.
SUITE_REPORT_LIMIT = 2 * 1024 * 1024 * 1024
CALL_RESULT_KEYS = {"validated", "publicMatch", "nativeSnapshots", "sdkSnapshots",
                    "acceptancePointsAwarded", "nativeResult", "sdkResult"}
FILES = {
    "nativeRaw": ("native/evidence/native-raw.json", 128 * 1024 * 1024),
    "sdkRaw": ("sdk/evidence/python-raw.json", 512 * 1024 * 1024),
    "nativeStdout": ("native/stdout.json", 64 * 1024 * 1024),
    "sdkOutput": ("sdk-output.json", 64 * 1024 * 1024),
}


def _json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key in a selected replay input")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("Non-finite JSON constant in a selected replay input")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def _directory(value):
    path = Path(value).absolute()
    if ".." in path.parts or path.resolve(strict=True) != path or not path.is_dir():
        raise ValueError("A selected source directory is missing or aliased")
    return path


def _file(value, *, root=None, limit=None):
    path = Path(value).absolute()
    if ".." in path.parts or path.resolve(strict=True) != path:
        raise ValueError("A selected replay file is missing or aliased")
    if root is not None and not path.is_relative_to(root):
        raise ValueError("A selected replay file escaped its explicit capture root")
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or limit is not None and info.st_size > limit):
        raise ValueError("A selected replay file is not a bounded, singly owned regular file")
    return path, info


def _fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _seal(value, *, root=None, limit=None):
    path, before = _file(value, root=root, limit=limit)
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as stream:
        if _fingerprint(os.fstat(stream.fileno())) != _fingerprint(before):
            raise ValueError("A replay input changed before hashing")
        while block := stream.read(1024 * 1024):
            digest.update(block)
            size += len(block)
            if size > before.st_size:
                raise ValueError("A replay input grew while hashing")
        after = os.fstat(stream.fileno())
    _, current = _file(path, root=root, limit=limit)
    if size != before.st_size or not _fingerprint(before) == _fingerprint(after) == _fingerprint(current):
        raise ValueError("A replay input changed while hashing")
    return {"path": str(path), "bytes": size, "sha256": digest.hexdigest()}


def _read_json(value, *, root=None, limit=1024 * 1024 * 1024):
    path, before = _file(value, root=root, limit=limit)
    with path.open("rb") as stream:
        if _fingerprint(os.fstat(stream.fileno())) != _fingerprint(before):
            raise ValueError("A replay input changed before parsing")
        data = stream.read(before.st_size + 1)
        after = os.fstat(stream.fileno())
    _, current = _file(path, root=root, limit=limit)
    if len(data) != before.st_size or not _fingerprint(before) == _fingerprint(after) == _fingerprint(current):
        raise ValueError("A replay input changed while parsing")
    return _json(data.decode("utf-8")), {
        "path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
    }


def _sdk_identity(root):
    root = _directory(root)
    package = _directory(root / PACKAGE_NAME)
    paths = sorted(package.rglob("*.py"))
    if not paths:
        raise ValueError("The independently selected SDK source inventory is empty")
    digest, files = hashlib.sha256(), []
    for path in paths:
        observed = _seal(path, root=root)
        content = path.read_bytes()
        if len(content) != observed["bytes"] or hashlib.sha256(content).hexdigest() != observed["sha256"]:
            raise ValueError("An SDK source file changed during inventory")
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode() + b"\0" + content + b"\0")
        files.append({"path": relative, "bytes": len(content), "sha256": observed["sha256"]})
    return {"root": str(root), "sourceFiles": len(files), "sourceSha256": digest.hexdigest(), "files": files}


def _adapter_identity(root, version):
    root = _directory(root)
    folder = _directory(root / "equivalence")
    paths = sorted(folder.glob("*.py")) + sorted(folder.glob("*.mjs"))
    paths.extend(path for path in (folder / "openclaw.plugin.json",
                 root / f"docs/forget_index_fence_{version}_literals.json",
                 root / f"docs/forget_index_fence_{version}_plan.md") if path.is_file())
    if not paths:
        raise ValueError("The independently selected adapter source inventory is empty")
    return {"root": str(root), "files": [
        {"path": path.relative_to(root).as_posix(), **{key: value for key, value in _seal(path, root=root).items()
          if key != "path"}} for path in paths]}


def _node_authority(node):
    return prepare_model_node_authority(node)


def _reference_authority(reference, node):
    target, _ = _read_json(ROOT / "equivalence/reference.json", limit=1024 * 1024)
    return _validate_reference(reference, node, target)


def _authorities(args, guard, frozen):
    expected_guard = ROOT / "equivalence/forget_index_fence_evidence.py"
    guard_path = Path(guard.__file__).resolve(strict=True)
    if guard_path != expected_guard.resolve(strict=True):
        raise ValueError("Replay attempted to use a guard outside the independently selected program")
    node, _ = _file(args.node)
    reference, sdk = _directory(args.reference), _directory(args.sdk_source_root)
    adapter_root = args.adapter_root or (ROOT if args.version != "v2" else None)
    return {
        **({"adapters": _adapter_identity(adapter_root, args.version)} if adapter_root is not None else {}),
        "guard": _seal(guard_path), "script": _seal(Path(__file__).resolve()),
        "literalModule": _seal(Path(frozen.__file__).resolve()), "manifest": _seal(frozen.MANIFEST),
        "node": _node_authority(node), "reference": _reference_authority(reference, node),
        "sdk": _sdk_identity(sdk),
    }


def _admit_reports(roots, authority, report, frozen, version):
    CASE_HASHES, MANIFEST_SHA256, POINTS = frozen.CASE_HASHES, frozen.MANIFEST_SHA256, frozen.POINTS
    selected, seals, seen_roots = {}, [], set()
    for value in roots:
        root = _directory(value)
        if root in seen_roots:
            raise ValueError("A capture root was selected more than once")
        seen_roots.add(root)
        source, sealed = _read_json(root / "report.json", root=root)
        compact = {"directory": str(root), "report": sealed}
        report["sourceReports"].append(compact)
        seals.append(sealed)
        if (not isinstance(source, dict) or source.get("kind") != f"forget-index-fence-{version}-comparison"
                or source.get("finalAuthenticationPassed") is not True
                or source.get("errors") != [] or not isinstance(source.get("errors"), list)
                or type(source.get("acceptancePointsAwarded")) is not int
                or source["acceptancePointsAwarded"] != 0 or source.get("covers") != []
                or source.get("fullScopePassed") is not False
                or source.get("candidateCoverage") != list(POINTS)
                or source.get("literalManifestSha256") != MANIFEST_SHA256):
            raise ValueError("A source collector report lacks complete final authentication or selected frozen scope")
        execution = source.get("execution")
        if (not isinstance(execution, dict)
                or version in {"v3", "v4", "v5", "v6"} and execution.get("inputVersion") != version
                or "inputVersion" in execution and execution["inputVersion"] != version):
            raise ValueError("A collector report does not belong to the explicitly selected input version")
        identity, node = source.get("implementationIdentity"), source.get("node")
        if (not isinstance(identity, dict) or identity.get("trackedWorkingTreeDirty") is not False
                or identity.get("sourceSha256") != authority["sdk"]["sourceSha256"]
                or type(identity.get("sourceFiles")) is not int
                or identity["sourceFiles"] != authority["sdk"]["sourceFiles"]):
            raise ValueError("A collector report does not match the independently chosen SDK source")
        if not isinstance(node, dict) or any(
                node.get(key) != authority["node"].get(key)
                for key in ("sha256", "nodeVersion", "icuVersion", "unicodeVersion")):
            raise ValueError("A collector report names another approved Node authority")
        expected_reference = {key: authority["reference"][key] for key in ("tag", "commit")}
        if source.get("reference") != expected_reference:
            raise ValueError("A collector report names another independently chosen reference")
        adapters = source.get("adapterHashes")
        if (not isinstance(adapters, dict) or not adapters
                or any(not isinstance(k, str) or not isinstance(v, str) or not SHA256.fullmatch(v)
                       for k, v in adapters.items())
                or not isinstance(source.get("collectorSha256"), str)
                or not SHA256.fullmatch(source["collectorSha256"])):
            raise ValueError("A collector report omitted its source/adapter authentication")
        rows = source.get("cases")
        if not isinstance(rows, list) or not rows:
            raise ValueError("A collector report contains no actual executed cases")
        compact.update(collectorSha256=source["collectorSha256"], implementationIdentity=identity,
                       node=node, reference=source["reference"], adapterHashes=adapters,
                       actualCaseIds=[row.get("id") for row in rows if isinstance(row, dict)])
        for row in rows:
            if not isinstance(row, dict) or row.get("id") not in CASE_HASHES:
                raise ValueError("A collector report contains an unknown or foreign case")
            identifier = row["id"]
            if identifier in selected:
                raise ValueError("Duplicate actual case across selected collector reports: " + identifier)
            if row.get("covers") != [] or row.get("candidateCoverage") != list(POINTS):
                raise ValueError("A collector row has foreign acceptance coverage")
            if "nativeError" in row or "sdkError" in row:
                raise ValueError("A collector row contains an original engine failure: " + identifier)
            if row.get("status") not in {"match", "mismatch", "blocked"}:
                raise ValueError("A collector row has no recognized original diagnostic status")
            artifacts = {}
            if not isinstance(row.get("artifacts"), list):
                raise ValueError("A collector row omitted its original artifact seals")
            for item in row["artifacts"]:
                if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                    raise ValueError("A collector artifact record is malformed")
                name = item["path"]
                pure = PurePosixPath(name)
                if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != name or "\\" in name:
                    raise ValueError("A collector artifact path is not canonical")
                if name in artifacts:
                    raise ValueError("A collector artifact was duplicated")
                artifacts[name] = item
            selected[identifier] = {
                "root": root, "report": sealed, "artifacts": artifacts,
                "originalRow": {key: row[key] for key in ("status", "custodyPending", "custodyError") if key in row},
            }
    if set(selected) != set(CASE_HASHES):
        raise ValueError("Independent baseline replay requires all thirteen exact cases without omissions")
    return selected, seals


def _case_files(selection, identifier):
    root, result = selection["root"], {}
    for role, (relative, limit) in FILES.items():
        name = identifier + "/" + relative
        expected = selection["artifacts"].get(name)
        actual = _seal(root / name, root=root, limit=limit)
        if (not isinstance(expected, dict) or expected.get("kind") != "file"
                or type(expected.get("bytes")) is not int or expected["bytes"] != actual["bytes"]
                or expected.get("sha256") != actual["sha256"]):
            raise ValueError("An actual engine file differs from its collector artifact seal: " + name)
        result[role] = actual
    return result


OLD_DEFINITIONS_SHA256 = "0fa31b6393c65303f4fa2e1663671e4ef60eb15edc563f05aba218c8c408349c"
FIXED_SCOPE_SHA256 = "a8e066e63970dd0be734485d62a5932640894b8c0a42f47ac3eb67f784cbc7b9"


def _registered_cases():
    from equivalence.cases import build_cases
    return build_cases()


def _suite_adapter_hashes():
    from equivalence.harness import _adapter_identity as current_adapter_identity
    return current_adapter_identity()


def _suite_authority(frozen):
    cases = _registered_cases()
    prior = json.dumps(cases[:1452], sort_keys=True, ensure_ascii=True,
                       separators=(",", ":"), allow_nan=False).encode()
    if (len(cases) != 1465 or cases[1452:] != frozen.build_cases()
            or hashlib.sha256(prior).hexdigest() != OLD_DEFINITIONS_SHA256
            or sum("fixtureSource" in case for case in cases) != 79
            or sum("diagnosticOnly" in case for case in cases) != 1):
        raise ValueError("Suite replay requires the unchanged 1452 definitions plus exact selected frozen thirteen")
    frozen.validate_registration(cases)
    scope, scope_seal = _read_json(ROOT / "equivalence/scope.json", limit=1024 * 1024)
    reference = _seal(ROOT / "equivalence/reference.json", limit=1024 * 1024)
    if (scope_seal["sha256"] != FIXED_SCOPE_SHA256 or len(scope["requirements"]) != 64
            or sum(len(row["acceptance"]) for row in scope["requirements"]) != 128):
        raise ValueError("Suite replay requires the unchanged 64-contract/128-condition scope")
    return cases, scope, {"scope": scope_seal, "reference": reference,
                         "casesModule": _seal(ROOT / "equivalence/cases.py"),
                         "adapters": _suite_adapter_hashes(),
                         "registeredCases": 1465, "priorDefinitionsSha256": OLD_DEFINITIONS_SHA256}


def _suite_reference(item, side, root):
    expected_file = "evidence/native-raw.json" if side == "native" else "python-raw.json"
    if (not isinstance(item, dict) or set(item) != {
            "id", "side", "sha256", "rawSnapshotReference", "validationStatus", "evidenceDirectory"}
            or item["side"] != side or item["validationStatus"] != "verified"):
        raise ValueError("A V5 suite capture lacks affirmative original file custody")
    ref = item["rawSnapshotReference"]
    if (not isinstance(ref, dict) or set(ref) != {"directory", "file", "bytes", "sha256"}
            or not isinstance(ref["directory"], str) or str(Path(ref["directory"])) != ref["directory"]
            or ref["file"] != expected_file or type(ref["bytes"]) is not int or ref["bytes"] <= 0
            or not isinstance(ref["sha256"], str) or not SHA256.fullmatch(ref["sha256"])
            or item["sha256"] != ref["sha256"] or item["evidenceDirectory"] != ref["directory"]):
        raise ValueError("A suite rawSnapshotReference is incomplete or changed")
    directory = _directory(ref["directory"])
    if not directory.is_relative_to(root):
        raise ValueError("A suite capture escaped its independently selected physical root")
    role = "nativeRaw" if side == "native" else "sdkRaw"
    sealed = _seal(directory / expected_file, root=root, limit=FILES[role][1])
    if sealed["bytes"] != ref["bytes"] or sealed["sha256"] != ref["sha256"]:
        raise ValueError("A suite capture differs from its actual original raw file seal")
    return directory, sealed


def _admit_suite_report(args, authority, report, frozen):
    """Stream the actual full report, retaining only fixed metadata and V5 rows."""
    from equivalence.harness import _same_json
    from equivalence.strict_report_reader import Reader

    definitions, scope, suite = _suite_authority(frozen)
    registered_ids = {case["id"] for case in definitions}
    native_root, sdk_root = _directory(args.native_capture_root), _directory(args.sdk_capture_root)
    path, before = _file(args.suite_report, limit=SUITE_REPORT_LIMIT)
    sealed = _seal(path, limit=SUITE_REPORT_LIMIT)
    selected, diagnostics, metadata = {}, {}, {}
    case_index = 0
    requirements_index = 0
    counts = {"matched": 0, "mismatched": 0, "blocked": 0}
    arrays = set()
    uncovered = []
    points = {point["id"]: [] for requirement in scope["requirements"] for point in requirement["acceptance"]}
    for case in definitions:
        for point in case["covers"]:
            points[point].append(case["id"])
    selected_requirement = None
    keep = {"schemaVersion", "kind", "mode", "status", "reference", "manifestSha256", "implementation",
            "adapterSha256", "casesSha256", "forgetIndexFenceNode", "forgetIndexFenceBindings",
            "summary", "fullScopePassed", "startedAt", "finishedAt", "durationSeconds", "referenceExecution"}

    def accept(key, value, array):
        nonlocal case_index, requirements_index, selected_requirement
        if array == "array-done":
            arrays.add(key)
            return
        if key in {"cases", "runtimeDiagnostics", "requirements", "errors", "uncoveredAcceptance"} and array is not True:
            raise ValueError("A full suite array has an invalid type")
        if key == "cases":
            if case_index >= len(definitions):
                raise ValueError("The full suite contains extra registered rows")
            expected = definitions[case_index]
            if (not isinstance(value, dict)
                    or any(not _same_json(value.get(field), expected[field])
                           for field in ("id", "operation", "input", "requirement", "covers"))
                    or any((field in value) != (field in expected)
                           or field in expected and not _same_json(value[field], expected[field])
                           for field in ("normalizationPolicy", "driverScope", "declaredDeviation"))
                    or value.get("status") not in counts):
                raise ValueError("The full suite omitted, reordered or changed a registered definition")
            counts[value["status"]] += 1
            case_index += 1
            if expected["id"] in frozen.CASE_HASHES:
                if (value.get("runtimeEvidenceValidated") is not True
                        or value["status"] not in {"matched", "mismatched"}
                        or not isinstance(value.get("python"), dict) or not isinstance(value.get("openclaw"), dict)
                        or "evidenceError" in value or "code" in value):
                    raise ValueError("A V5 suite row lost its frozen metadata, whole public results or paired custody")
                selected[value["id"]] = value
        elif key == "runtimeDiagnostics":
            if not isinstance(value, dict) or value.get("id") not in registered_ids:
                raise ValueError("The full suite contains foreign runtime evidence")
            if value["id"] in frozen.CASE_HASHES:
                identity = value["id"], value.get("side")
                if identity in diagnostics:
                    raise ValueError("A V5 suite capture side was duplicated")
                diagnostics[identity] = value
        elif key == "requirements":
            if requirements_index >= len(scope["requirements"]):
                raise ValueError("The suite added a foreign scope requirement")
            expected = scope["requirements"][requirements_index]
            if (not isinstance(value, dict) or value.get("id") != expected["id"]
                    or value.get("required") is not expected["required"]
                    or type(value.get("registeredCases")) is not int
                    or value.get("registeredCases") != sum(case["requirement"] == expected["id"] for case in definitions)
                    or not isinstance(value.get("acceptance"), list)
                    or len(value["acceptance"]) != len(expected["acceptance"])):
                raise ValueError("The suite changed the fixed acceptance denominator")
            for actual, point in zip(value["acceptance"], expected["acceptance"], strict=True):
                if (actual.get("id") != point["id"] or actual.get("caseIds") != points[point["id"]]
                        or not isinstance(actual.get("matchedCaseIds"), list)
                        or len(set(actual["matchedCaseIds"])) != len(actual["matchedCaseIds"])
                        or any(identifier not in actual["caseIds"] for identifier in actual["matchedCaseIds"])):
                    raise ValueError("The suite changed fixed point membership")
            requirements_index += 1
            if expected["id"] == "forget.index-fence":
                selected_requirement = value
        elif key == "errors":
            raise ValueError("The original full suite contains a failed final check")
        elif key == "uncoveredAcceptance":
            if value not in points or points[value]:
                raise ValueError("The suite changed the fixed uncovered point set")
            uncovered.append(value)
        elif key in keep:
            if array is not False:
                raise ValueError("A suite authentication field has an invalid type")
            metadata[key] = value

    reader = Reader(path)
    if _fingerprint(os.fstat(reader.stream.fileno())) != _fingerprint(before):
        reader.close()
        raise ValueError("The suite changed before streaming admission")
    reader.top(accept)
    _, after = _file(path, limit=SUITE_REPORT_LIMIT)
    if (_fingerprint(before) != _fingerprint(after) or _seal(path) != sealed):
        raise ValueError("The full suite changed during streaming admission")
    del reader  # Release the last decoded wire buffer before opening raw captures.
    if (not {"cases", "runtimeDiagnostics", "requirements", "errors", "uncoveredAcceptance"} <= arrays
            or case_index != 1465 or requirements_index != 64 or len(selected) != 13
            or set(diagnostics) != {(identifier, side) for identifier in frozen.CASE_HASHES for side in ("native", "python")}):
        raise ValueError("The full suite is incomplete or omits a V5 physical engine capture")
    manifest = metadata.get("manifestSha256", {})
    implementation = metadata.get("implementation", {})
    if (type(metadata.get("schemaVersion")) is not int or metadata["schemaVersion"] != 1
            or metadata.get("kind") != "pinned-differential-acceptance" or metadata.get("mode") != "full"
            or metadata.get("status") not in {"passed", "mismatched", "incomplete"} or counts["blocked"]
            or type(metadata.get("fullScopePassed")) is not bool
            or metadata["fullScopePassed"] is not (metadata["status"] == "passed")
            or not isinstance(metadata.get("finishedAt"), str) or not metadata["finishedAt"]
            or not isinstance(metadata.get("startedAt"), str) or not metadata["startedAt"]
            or type(metadata.get("durationSeconds")) not in (int, float) or metadata["durationSeconds"] < 0
            or manifest.get("scope") != suite["scope"]["sha256"]
            or manifest.get("reference") != suite["reference"]["sha256"]
            or metadata.get("casesSha256") != suite["casesModule"]["sha256"]
            or not _same_json(metadata.get("adapterSha256"), suite["adapters"])
            or not _same_json(metadata.get("reference"), authority["reference"])
            or implementation.get("trackedWorkingTreeDirty") is not False
            or implementation.get("sourceSha256") != authority["sdk"]["sourceSha256"]
            or type(implementation.get("sourceFiles")) is not int
            or implementation["sourceFiles"] != authority["sdk"]["sourceFiles"]):
        raise ValueError("The full suite lacks unchanged complete source/scope/registered authority")
    if any(metadata.get("forgetIndexFenceNode", {}).get(key) != authority["node"].get(key)
           for key in ("sha256", "nodeVersion", "icuVersion", "unicodeVersion")):
        raise ValueError("The full suite names another approved Node authority")
    summary = metadata.get("summary", {})
    expected_uncovered = [point for point, members in points.items() if not members]
    expected_status = "mismatched" if counts["mismatched"] else "incomplete" if expected_uncovered else "passed"
    if (any(type(summary.get(key)) is not int or summary[key] != count for key, count in counts.items())
            or uncovered != expected_uncovered or type(summary.get("uncoveredAcceptance")) is not int
            or summary["uncoveredAcceptance"] != len(expected_uncovered) or metadata["status"] != expected_status):
        raise ValueError("The full suite summary differs from its complete actual registered rows")
    owner_bindings = metadata.get("forgetIndexFenceBindings")
    if (not isinstance(owner_bindings, dict) or owner_bindings.get("sourceBuildReproduced") is not False
            or owner_bindings.get("sourceFallbackAllowed") is not False):
        raise ValueError("The suite omitted its honest independently qualified release authority")
    execution = metadata.get("referenceExecution", {})
    groups = [execution.get("trackedTypeScriptCaseIds"), execution.get("compiledReleaseCaseIds")]
    if (any(not isinstance(group, list) for group in groups)
            or len(groups[0] + groups[1]) != 1465
            or set(groups[0] + groups[1]) != {case["id"] for case in definitions}
            or not set(frozen.CASE_HASHES) <= set(groups[1])):
        raise ValueError("The suite lost the complete source/release dispatch identities")
    all_match = all(row["status"] == "matched" for row in selected.values())
    if (selected_requirement is None or any(point["matchedCaseIds"] != (list(frozen.CASE_HASHES) if all_match else [])
                                           for point in selected_requirement["acceptance"])):
        raise ValueError("The original full suite did not preserve the atomic two-point family gate")
    report["sourceReports"].append({"mode": "registered-suite", "report": sealed, "registeredCases": 1465,
                                    "fixedAcceptancePoints": 128, "sourceStatus": metadata["status"]})
    report["suiteAuthority"] = suite
    result = {}
    seals = [sealed, suite["scope"], suite["reference"], suite["casesModule"]]
    for identifier in frozen.CASE_HASHES:
        native_dir, native_seal = _suite_reference(diagnostics[identifier, "native"], "native", native_root)
        sdk_dir, sdk_seal = _suite_reference(diagnostics[identifier, "python"], "python", sdk_root)
        stdout = _seal(native_dir / "stdout.json", root=native_root, limit=FILES["nativeStdout"][1])
        if native_dir == sdk_dir:
            raise ValueError("A suite reused one physical directory for both engines")
        result[identifier] = {"mode": "registered-suite", "report": sealed,
            "directories": {"native": native_dir, "sdk": sdk_dir},
            "files": {"nativeRaw": native_seal, "sdkRaw": sdk_seal, "nativeStdout": stdout},
            "nativeResult": selected[identifier]["openclaw"], "sdkResult": selected[identifier]["python"],
            "originalRow": {"status": selected[identifier]["status"], "runtimeEvidenceValidated": True}}
    return result, seals, suite


class AtomicOutput:
    """Exclusive first publication; every later progress update replaces only our file."""

    def __init__(self, value):
        requested = Path(value).absolute()
        requested.parent.mkdir(parents=True, exist_ok=True)
        self.path = _directory(requested.parent) / requested.name
        self.identity = None

    def write(self, report):
        payload = (json.dumps(report, ensure_ascii=True, allow_nan=False, indent=2) + "\n").encode()
        descriptor, temporary = tempfile.mkstemp(prefix="." + self.path.name + ".", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            if self.identity is None:
                os.link(temporary, self.path)
                os.unlink(temporary)
            else:
                _, current = _file(self.path)
                if (current.st_dev, current.st_ino) != self.identity:
                    raise ValueError("The exclusively owned replay output was replaced")
                os.replace(temporary, self.path)
            _, current = _file(self.path)
            self.identity = current.st_dev, current.st_ino
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def _error(error):
    return {"name": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", choices=("v2", "v3", "v4", "v5", "v6"), default="v2")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--capture-root", type=Path, action="append")
    selection.add_argument("--suite-report", type=Path)
    parser.add_argument("--native-capture-root", type=Path)
    parser.add_argument("--sdk-capture-root", type=Path)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--sdk-source-root", type=Path, required=True)
    parser.add_argument("--adapter-root", type=Path,
                        help="Independent actor source tree; V3/V4/V5 default to this replay program tree, V2 preserves legacy custody when omitted")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.suite_report and (args.version not in {"v5", "v6"} or not args.native_capture_root or not args.sdk_capture_root):
        parser.error("Registered-suite replay requires explicit --version v5/v6 and both independently selected capture roots")
    if not args.suite_report and (args.native_capture_root or args.sdk_capture_root):
        parser.error("Physical engine root options apply only to --suite-report")
    frozen = import_module(f"equivalence.forget_index_fence_{args.version}")
    CASE_HASHES, MANIFEST_SHA256, POINTS = frozen.CASE_HASHES, frozen.MANIFEST_SHA256, frozen.POINTS
    report = {"schemaVersion": 1, "kind": f"forget-index-fence-{args.version}-independent-replay",
              "acceptancePointsAwarded": 0, "covers": [], "candidateCoverage": list(POINTS),
              "fullScopePassed": False, "validCompleteBaseline": False,
              "sourceReports": [], "cases": [], "errors": []}
    try:
        output = AtomicOutput(args.output)
        output.write(report)
    except (OSError, ValueError) as error:
        print("Cannot exclusively create replay output: " + str(error), file=sys.stderr)
        return 2
    try:
        cases = frozen.build_cases()
        guard = import_module("equivalence.forget_index_fence_evidence")
        authority = _authorities(args, guard, frozen)
        if authority["manifest"]["sha256"] != MANIFEST_SHA256:
            raise ValueError("The independently selected frozen manifest changed")
        report["authority"] = authority
        suite_authority = None
        if args.suite_report:
            selected, final_seals, suite_authority = _admit_suite_report(args, authority, report, frozen)
        else:
            selected, final_seals = _admit_reports(args.capture_root, authority, report, frozen, args.version)
        output.write(report)
        for case in cases:
            selection = selected[case["id"]]
            suite_mode = selection.get("mode") == "registered-suite"
            root = None if suite_mode else selection["root"]
            native_directory = (selection["directories"]["native"] if suite_mode else root / case["id"] / "native")
            sdk_directory = (selection["directories"]["sdk"] if suite_mode else root / case["id"] / "sdk/evidence")
            row = {"id": case["id"], "operation": case["operation"], "covers": [],
                   "status": "blocked", "sourceReport": selection["report"],
                   **{("originalSuiteRow" if suite_mode else "originalCollectorRow"): selection["originalRow"]},
                   "directories": {"native": str(native_directory), "sdk": str(sdk_directory)}}
            report["cases"].append(row)
            replay = native_result = sdk_result = sdk_output = None
            try:
                files = selection["files"] if suite_mode else _case_files(selection, case["id"])
                if suite_mode and any(_seal(item["path"]) != item for item in files.values()):
                    raise ValueError("A selected suite capture changed before its independent replay")
                row["files"] = files
                final_seals.extend(files.values())
                replay = guard.replay_case(
                    case, native_directory, sdk_directory, approved_node=Path(authority["node"]["execPath"]),
                    approved_reference=_directory(args.reference),
                    approved_sdk_root=Path(authority["sdk"]["root"]), include_results=True,
                    **({"approved_adapter_root": Path(authority["adapters"]["root"])}
                       if "adapters" in authority else {}))
                if (not isinstance(replay, dict) or set(replay) != CALL_RESULT_KEYS
                        or replay["validated"] is not True or type(replay["publicMatch"]) is not bool
                        or type(replay["acceptancePointsAwarded"]) is not int
                        or replay["acceptancePointsAwarded"] != 0):
                    raise ValueError("The independent guard did not affirmatively validate both complete engines")
                native_result, sdk_result = replay["nativeResult"], replay["sdkResult"]
                row["structuralReplay"] = {key: value for key, value in replay.items()
                                           if key not in {"nativeResult", "sdkResult"}}
                if suite_mode:
                    if (differences(selection["sdkResult"], sdk_result)
                            or differences(selection["nativeResult"], native_result)):
                        raise ValueError("Whole V5 suite payloads differ from the independently replayed actual results")
                else:
                    sdk_output, sdk_seal = _read_json(files["sdkOutput"]["path"], root=root,
                                                    limit=FILES["sdkOutput"][1])
                    if sdk_seal != files["sdkOutput"] or differences(sdk_output, sdk_result):
                        raise ValueError("The small SDK output differs from its actual authenticated raw result")
                row["differences"] = differences(native_result, sdk_result)
                matched = not row["differences"]
                if suite_mode and selection["originalRow"]["status"] != ("matched" if matched else "mismatched"):
                    raise ValueError("The original suite row status differs from its whole actual results")
                if replay["publicMatch"] is not matched:
                    raise ValueError("Guard public parity disagrees with the established whole-result comparator")
                row["status"] = "match" if matched else "mismatch"
            except Exception as error:
                row["error"] = _error(error)
                report["errors"].append({"id": case["id"], **row["error"]})
            finally:
                replay = native_result = sdk_result = sdk_output = None
            output.write(report)
            print(json.dumps({"id": case["id"], "status": row["status"],
                              "differences": len(row.get("differences", []))}), flush=True)
        for sealed in final_seals:
            if _seal(sealed["path"]) != sealed:
                raise ValueError("An original collector report or engine file changed during independent replay")
        if _authorities(args, guard, frozen) != authority:
            raise ValueError("The independent guard, source inputs or approved authorities changed during replay")
        if suite_authority is not None and _suite_authority(frozen)[2] != suite_authority:
            raise ValueError("The registered catalog/scope/source authority changed during replay")
        frozen.build_cases()
        report["finalAuthenticationPassed"] = True
    except Exception as error:
        report["errors"].append(_error(error))
    report["summary"] = {status: sum(row["status"] == status for row in report["cases"])
                         for status in ("match", "mismatch", "blocked")}
    report["validCompleteBaseline"] = (
        report.get("finalAuthenticationPassed") is True and not report["errors"]
        and len(report["cases"]) == len(CASE_HASHES)
        and [row["id"] for row in report["cases"]] == list(CASE_HASHES)
        and all(row.get("structuralReplay", {}).get("validated") is True
                and row["status"] in {"match", "mismatch"} for row in report["cases"]))
    report["candidateFamilyMatched"] = (report["validCompleteBaseline"]
                                         and report["summary"]["match"] == len(CASE_HASHES))
    try:
        output.write(report)
    except (OSError, ValueError) as error:
        print("Replay output could not retain its final diagnostic: " + str(error), file=sys.stderr)
        return 2
    sealed_output = _seal(output.path)
    print(json.dumps({"summary": report["summary"], "validCompleteBaseline": report["validCompleteBaseline"],
                      "acceptancePointsAwarded": 0, "fullScopePassed": False,
                      "reportSha256": sealed_output["sha256"]}), flush=True)
    return 2 if not report["validCompleteBaseline"] else 1 if report["summary"]["mismatch"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
