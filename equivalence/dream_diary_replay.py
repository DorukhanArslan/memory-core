"""Archive and replay the seven diary cases from a focused or full comparison report.

Run python -m equivalence.dream_diary_replay REPORT --archive DIRECTORY once beside
the original SDK fixtures, or --captures DIRECTORY to reopen the resulting portable proof.
The checkout used for replay must contain the captured SDK implementation.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil

from equivalence import dream_diary as family
from equivalence.dream_diary_bindings import COMPILED
from equivalence.dream_diary_evidence import validate_native, validate_sdk
from equivalence.dream_diary_sdk import capture
from equivalence.dream_light_evidence import require, same
from equivalence.promotion_ranking_bindings import PROMOTION_WORKER_ROUTE


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _trace(case, transport, sources, authority, raw):
    profile = family.validate_profile(transport["profile"])
    require(profile["caseId"] == case["id"] and profile["nodeRuntime"] == authority, "Wrong diary trace authority")
    workers, main, loaded = [], 0, set()
    for stream in transport["traceFiles"]:
        content = stream["text"].encode()
        require(len(content) == stream["bytes"] and _sha(content) == stream["sha256"], "Diary worker trace changed")
        rows = [json.loads(line) for line in content.splitlines()]
        first = rows[0]
        require(first["event"] == "bootstrap" and first["runtime"] == authority and first["dreamPhaseProfile"] == profile
                and first["pid"] == raw["pid"] and first["ppid"] == raw["ppid"] and first["fetchDenied"] is True
                and first["providerMode"] == "none" and first["isMainThread"] == (first["threadId"] == 0)
                and stream["name"] == f'{first["pid"]}-{first["threadId"]}.jsonl', "Misbound diary worker trace")
        seen = set()
        for row in rows[1:]:
            require(row["event"] in {"load", "resolve-native"} and row["pid"] == first["pid"] and
                    row["threadId"] == first["threadId"], "Unknown or rejected diary import")
            if row["kind"] == "release":
                key = row["package"], row["path"]
                require(sources.get(key) == row["sha256"], "Unknown diary release import")
                if key[0] == "node_modules/openclaw" and key[1] in COMPILED:
                    require(COMPILED[key[1]][0] == row["sha256"], "Wrong pinned diary owner")
                loaded.add(key)
                seen.add(key)
        if first["isMainThread"]:
            main += 1
        else:
            workers.append(seen)
    require(main == 1 and any(all(("node_modules/openclaw", item) in seen for item in PROMOTION_WORKER_ROUTE)
                              for seen in workers), "Original diary SQLite worker missing")
    return loaded


def replay(report_path, *, archive=None, captures=None):
    data = Path(report_path).read_bytes()
    report = json.loads(gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data)
    require(not (archive and captures), "Choose either archive or replay")
    require(report["dreamDiaryFamilyComplete"] is True and report["implementation"]["trackedWorkingTreeDirty"] is False,
            "Diary source or family result is incomplete")
    sources = {(row["package"], row["path"]): row["sha256"] for row in report["releaseSources"]}
    traces = {row["id"]: row for row in report["releaseTraces"]}
    diagnostics = {(r["id"], r["side"]): r for r in report["runtimeDiagnostics"]}
    passed = []
    rows = [r for r in report["cases"] if r["operation"] == family.OPERATION]
    require(family.family_complete(rows), "Incomplete seven-case diary family")
    if archive:
        Path(archive).mkdir(exist_ok=False, parents=True)
    for case, row in zip(family.build_cases(), rows, strict=True):
        identifier = case["id"]
        native, sdk = (diagnostics[identifier, s] for s in ("native", "python"))
        require(native["validationStatus"] == sdk["validationStatus"] == "verified", "Unverified diary pair")
        same(row["openclaw"], row["python"], "Diary pair differs")
        directory = Path(captures) / identifier if captures else Path(sdk["evidenceDirectory"])
        wire = (directory / "native-raw.json" if captures else Path(native["retainedNativeRawPath"])).read_bytes()
        python_wire = (directory / "python-raw.json").read_bytes()
        require(_sha(wire) == native["sha256"] and _sha(python_wire) == sdk["sha256"], "Diary sidecar digest mismatch")
        original, actual = json.loads(wire), json.loads(python_wire)
        same(original, native["rawSnapshots"], "Native diary report differs from disk")
        same(actual, sdk["rawSnapshots"], "SDK diary report differs from disk")
        loaded = _trace(case, traces[identifier]["dreamDiaryTransport"], sources, report["dreamDiaryNode"], original[0])
        validate_native(case, row["openclaw"], original, Path(original[0]["root"]).parent, loaded, archived=True)
        validate_sdk(case, row["python"], actual, directory, archived_workspace=actual[0]["workspace"] if captures else None)
        if captures:
            # A copy has new filesystem identities. Check every archived literal file and
            # link against the original content, mode and time; the wire retains original inodes.
            public_files = capture(directory / "sdk-diary")
            def without_inode(files):
                return {k: {x: y for x, y in v.items() if x != "ino"} for k, v in files.items()}
            same(without_inode(public_files), without_inode(actual[0]["rows"][-1]["files"]), "Archived SDK files changed")
        if archive:
            target = Path(archive) / identifier
            target.mkdir()
            (target / "native-raw.json").write_bytes(wire)
            shutil.copy2(directory / "python-raw.json", target)
            shutil.copy2(directory / "sdk-callbacks.jsonl", target)
            shutil.copytree(directory / "sdk-diary", target / "sdk-diary", symlinks=True)
        passed.append({"id": identifier, "nativeSha256": _sha(wire), "sdkSha256": _sha(python_wire),
                       "reopenedSqliteSnapshots": len(original[0]["rows"]) + 1 + bool(original[0]["race"]),
                       "sdkWorkspaceReopened": True})
    return {"passed": True, "gitCommit": report["implementation"]["gitCommit"], "reportSha256": _sha(data),
            "globalCredit": 0, "cases": passed}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--archive", type=Path)
    group.add_argument("--captures", type=Path)
    args = parser.parse_args()
    print(json.dumps(replay(args.report, archive=args.archive, captures=args.captures), indent=2))
