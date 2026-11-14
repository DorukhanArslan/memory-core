"""Independently replay the exact frozen V2 family from retained collector roots.

This diagnostic starts no original engine, repairs no capture and awards no
acceptance credit. All source roots and the decoder executable are explicit.
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

from equivalence.forget_index_fence_v2 import (  # noqa: E402
    CASE_HASHES, MANIFEST, MANIFEST_SHA256, POINTS, build_cases,
)
from equivalence.harness import _validate_reference  # noqa: E402
from equivalence.model_runtime_authority import prepare_model_node_authority  # noqa: E402
from equivalence.promotion_apply_family import differences  # noqa: E402

SHA256 = re.compile(r"[0-9a-f]{64}\Z")
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
    package = _directory(root / "memory_core")
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


def _node_authority(node):
    return prepare_model_node_authority(node)


def _reference_authority(reference, node):
    target, _ = _read_json(ROOT / "equivalence/reference.json", limit=1024 * 1024)
    return _validate_reference(reference, node, target)


def _authorities(args, guard):
    expected_guard = ROOT / "equivalence/forget_index_fence_evidence.py"
    guard_path = Path(guard.__file__).resolve(strict=True)
    if guard_path != expected_guard.resolve(strict=True):
        raise ValueError("Replay attempted to use a guard outside the independently selected program")
    node, _ = _file(args.node)
    reference, sdk = _directory(args.reference), _directory(args.sdk_source_root)
    module = import_module("equivalence.forget_index_fence_v2")
    return {
        "guard": _seal(guard_path), "script": _seal(Path(__file__).resolve()),
        "literalModule": _seal(Path(module.__file__).resolve()), "manifest": _seal(MANIFEST),
        "node": _node_authority(node), "reference": _reference_authority(reference, node),
        "sdk": _sdk_identity(sdk),
    }


def _admit_reports(roots, authority, report):
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
        if (not isinstance(source, dict) or source.get("kind") != "forget-index-fence-v2-comparison"
                or source.get("finalAuthenticationPassed") is not True
                or source.get("errors") != [] or not isinstance(source.get("errors"), list)
                or type(source.get("acceptancePointsAwarded")) is not int
                or source["acceptancePointsAwarded"] != 0 or source.get("covers") != []
                or source.get("fullScopePassed") is not False
                or source.get("candidateCoverage") != list(POINTS)
                or source.get("literalManifestSha256") != MANIFEST_SHA256):
            raise ValueError("A source collector report lacks complete final authentication or frozen V2 scope")
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
    parser.add_argument("--capture-root", type=Path, action="append", required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--sdk-source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = {"schemaVersion": 1, "kind": "forget-index-fence-v2-independent-replay",
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
        cases = build_cases()
        guard = import_module("equivalence.forget_index_fence_evidence")
        authority = _authorities(args, guard)
        if authority["manifest"]["sha256"] != MANIFEST_SHA256:
            raise ValueError("The independently frozen V2 manifest changed")
        report["authority"] = authority
        selected, final_seals = _admit_reports(args.capture_root, authority, report)
        output.write(report)
        for case in cases:
            selection = selected[case["id"]]
            root = selection["root"]
            native_directory = root / case["id"] / "native"
            sdk_directory = root / case["id"] / "sdk/evidence"
            row = {"id": case["id"], "operation": case["operation"], "covers": [],
                   "status": "blocked", "sourceReport": selection["report"],
                   "originalCollectorRow": selection["originalRow"],
                   "directories": {"native": str(native_directory), "sdk": str(sdk_directory)}}
            report["cases"].append(row)
            replay = native_result = sdk_result = sdk_output = None
            try:
                files = _case_files(selection, case["id"])
                row["files"] = files
                final_seals.extend(files.values())
                replay = guard.replay_case(
                    case, native_directory, sdk_directory, approved_node=Path(authority["node"]["execPath"]),
                    approved_reference=_directory(args.reference),
                    approved_sdk_root=Path(authority["sdk"]["root"]), include_results=True)
                if (not isinstance(replay, dict) or set(replay) != CALL_RESULT_KEYS
                        or replay["validated"] is not True or type(replay["publicMatch"]) is not bool
                        or type(replay["acceptancePointsAwarded"]) is not int
                        or replay["acceptancePointsAwarded"] != 0):
                    raise ValueError("The independent guard did not affirmatively validate both complete engines")
                native_result, sdk_result = replay["nativeResult"], replay["sdkResult"]
                row["structuralReplay"] = {key: value for key, value in replay.items()
                                           if key not in {"nativeResult", "sdkResult"}}
                sdk_output, sdk_seal = _read_json(files["sdkOutput"]["path"], root=root,
                                                limit=FILES["sdkOutput"][1])
                if sdk_seal != files["sdkOutput"] or differences(sdk_output, sdk_result):
                    raise ValueError("The small SDK output differs from its actual authenticated raw result")
                row["differences"] = differences(native_result, sdk_result)
                matched = not row["differences"]
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
        if _authorities(args, guard) != authority:
            raise ValueError("The independent guard, source inputs or approved authorities changed during replay")
        build_cases()
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
