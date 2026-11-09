"""Independent protected process/worker execution for whole promotion apply."""
from pathlib import Path
import hashlib
import json
import os
import signal
import re
import stat
import subprocess
from equivalence.model_runtime_authority import prepare_model_node_authority
from equivalence.promotion_apply_bindings import PROMOTION_WORKER_ROUTE
from equivalence.promotion_apply_family import CASE_HASHES, validate_execution_case
from equivalence.release_runtime import validate_release_sources
ROOT = Path(__file__).resolve().parents[1]

LOCAL = ("promotion-apply-family-entry.mjs", "promotion-apply-family-preload.mjs",
         "promotion-apply-family-runtime.mjs", "promotion-apply-family-observers.mjs",
         "release-preload.mjs", "model-runtime-observation.mjs")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False) + "\n", encoding="utf8")


def validate_traces(directory, context, runtime, authority, *, process_pid=None, coordinator_pid=None):
    """Authenticate actual thread/import receipts; no behavioral expected output."""
    seen, bootstraps, workers = {}, [], {}
    packages = {(p["location"], f["path"]): f["sha256"] for p in runtime["packages"] for f in p["files"]}
    locals_ = {entry["path"]: entry["sha256"] for entry in context["allowedLocal"]}
    traces = sorted(directory.iterdir())
    if not traces or len(traces) > 512:
        raise ValueError("Missing or excessive family process traces")
    total = 0
    for trace in traces:
        info = trace.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or not re.fullmatch(r"[1-9][0-9]*-[0-9]+\.jsonl", trace.name)):
            raise ValueError("An unowned or unknown trace file was supplied")
        content = trace.read_bytes()
        total += len(content)
        if total > 64 * 1024 * 1024:
            raise ValueError("Excessive aggregate family worker traces")
        if len(content) > 8 * 1024 * 1024 or not content.endswith(b"\n"):
            raise ValueError("Incomplete or excessive worker trace")
        rows = [json.loads(line) for line in content.splitlines()]
        first = rows[0]
        if (first.get("event") != "bootstrap" or first.get("runtime") != authority
                or first.get("fetchDenied") is not True or first.get("providerMode") != "none"
                or first.get("contextSha256") != context["_sha256"]
                or first.get("preloadSha256") != locals_[str(ROOT / "equivalence/release-preload.mjs")]
                or first.get("isMainThread") is not (first.get("threadId") == 0)
                or trace.name != f'{first["pid"]}-{first["threadId"]}.jsonl'):
            raise ValueError("Missing exact process/worker authority")
        bootstraps.append(first)
        family_bootstraps = [row for row in rows if row.get("event") == "promotion-family-bootstrap"]
        if (len(family_bootstraps) != 1 or family_bootstraps[0].get("profile") != context["promotionApplyFamilyProfile"]
                or family_bootstraps[0].get("preloadSha256") != locals_[str(ROOT / "equivalence/promotion-apply-family-preload.mjs")]):
            raise ValueError("Missing independent family capability attestation")
        for row in rows[1:]:
            if row.get("event") not in {"load", "resolve-native", "promotion-family-bootstrap"}:
                raise ValueError("Unknown or rejected family trace event")
            if row.get("pid") != first["pid"] or row.get("threadId") != first["threadId"]:
                raise ValueError("Trace changed producer identity")
            if row["event"] in {"rejected", "network-denied"}:
                raise ValueError("Rejected import or runtime network attempt")
            if row["event"] in {"load", "resolve-native"}:
                if row["kind"] == "release":
                    key = row["package"], row["path"]
                    if packages.get(key) != row["sha256"]:
                        raise ValueError("Unverified original import")
                    seen[key] = {"package": key[0], "path": key[1], "sha256": row["sha256"]}
                    if first["threadId"] != 0:
                        workers.setdefault(first["threadId"], set()).add(row["path"])
                elif row["kind"] == "oracle":
                    if locals_.get(row["path"]) != row["sha256"]:
                        raise ValueError("Unverified adapter import")
                else:
                    raise ValueError("The family cannot import source substitutions")
    mains = [first for first in bootstraps if first["isMainThread"]]
    if (len(bootstraps) < 2 or len(mains) != 1 or mains[0].get("ppid") != (os.getpid() if coordinator_pid is None else coordinator_pid)
            or process_pid is not None and mains[0]["pid"] != process_pid
            or any(first["pid"] != mains[0]["pid"] for first in bootstraps)):
        raise ValueError("Missing main process or protected original worker")
    if not any(set(PROMOTION_WORKER_ROUTE) <= loaded for loaded in workers.values()):
        raise ValueError("The actual three-part plugin-state worker route did not execute")
    validate_release_sources(runtime, list(seen.values()), required_entry="dist/short-term-promotion-MX1vHJuE.mjs")
    return {"bootstraps": bootstraps, "loaded": list(seen.values()),
            "traces": [{"path": str(p), "sha256": digest(p)} for p in sorted(directory.glob("*.jsonl"))]}



def run_native_case(case, node, runtime, directory, *, timeout=120):
    validate_execution_case(case)
    node = Path(node).resolve()
    authority = prepare_model_node_authority(node)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    traces, evidence = directory / "traces", directory / "evidence"
    traces.mkdir()
    evidence.mkdir()
    case_path = directory / "case.json"
    write_json(case_path, case)
    profile = {"kind": "promotion-apply-family-development", "operation": case["operation"],
               "casePath": str(case_path), "caseFileSha256": digest(case_path),
               "caseWireSha256": CASE_HASHES[case["id"]], "nodeRuntime": authority, "acceptancePointsAwarded": 0}
    context = {"schemaVersion": 1, "kind": "release-oracle-execution", "runtime": runtime,
               "providerMode": "none", "fetchPolicy": "deny", "approvedNodeRuntime": authority,
               "promotionApplyFamilyProfile": profile,
               "allowedLocal": [{"path": str(ROOT / "equivalence" / name), "sha256": digest(ROOT / "equivalence" / name)} for name in LOCAL],
               "traceDirectory": str(traces), "evidenceDirectory": str(evidence),
               "stateDirectory": str(directory / "state"), "configPath": str(directory / "openclaw.json"),
               "approvedReferenceSources": [], "fixtureSourceCaptures": []}
    context_path = directory / "context.json"
    write_json(context_path, context)
    env = {"PATH": str(node.parent) + os.pathsep + os.defpath, "LANG": "C.UTF-8", "TZ": "UTC",
           "NODE_OPTIONS": f'--import={ROOT / "equivalence/promotion-apply-family-preload.mjs"}',
           "MEMORY_EQ_RELEASE_CONTEXT": str(context_path)}

    original_hashes = {entry["path"]: entry["sha256"] for entry in context["allowedLocal"]}
    with (directory / "stdout.json").open("wb") as stdout, (directory / "stderr.log").open("wb") as stderr:
        process = subprocess.Popen([str(node), str(ROOT / "equivalence/promotion-apply-family-entry.mjs")],
                                   env=env, cwd=ROOT, stdout=stdout, stderr=stderr,
                                   start_new_session=os.name == "posix")
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait()
            raise ValueError("Promotion reference timed out; original streams retained without retry") from None
    if (directory / "stdout.json").stat().st_size > 4 * 1024 * 1024:
        raise ValueError("Family stdout exceeded the complete result bound")
    returned = json.loads((directory / "stdout.json").read_text())
    if (process.returncode or set(returned) != {"id", "ok", "result"}
            or returned.get("id") != case["id"] or returned.get("ok") is not True):
        raise ValueError("Promotion original observation failed; complete streams retained without retry")
    trace = validate_traces(traces, {**context, "_sha256": digest(context_path)}, runtime, authority,
                            process_pid=process.pid, coordinator_pid=os.getpid())
    for filename, expected in original_hashes.items():
        if digest(Path(filename)) != expected:
            raise ValueError("Family process/worker adapter changed during execution")
    if prepare_model_node_authority(node) != authority:
        raise ValueError("Family executable changed during execution")
    if digest(case_path) != profile["caseFileSha256"]:
        raise ValueError("Family literal carrier changed during execution")
    raw = json.loads((evidence / "native-raw.json").read_text())
    if (not isinstance(raw, list) or len(raw) != 1
            or Path(raw[0]["fixtureBase"]).parent != evidence):
        raise ValueError("The original fixture borrowed another case's evidence directory")
    from equivalence.promotion_apply_family_evidence import validate_native_capture
    validate_native_capture(case, raw[0], returned["result"], authority=authority, pid=process.pid)
    return {"kind": "official-release-runtime-comparison", "sources": [],
            "results": [returned], "releaseSources": trace["loaded"],
            "releaseTrace": {"kind": "authenticated-promotion-family-process-thread-trace",
                "threads": trace["bootstraps"], "networkFetchDenied": True, "provider": "none",
                "protectedWorkerThreads": len(trace["bootstraps"]) - 1,
                "familyProfile": profile,
                "rawProcessWorkerTraces": [{"name": p.name, "text": p.read_text(), "sha256": digest(p)}
                                           for p in sorted(traces.glob("*.jsonl"))]},
            "runtimeDiagnostics": [{"id": case["id"], "sha256": digest(evidence / "native-raw.json"),
                                    "rawSnapshots": raw}],
            "evidenceDirectory": str(directory)}
