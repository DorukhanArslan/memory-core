"""Independent post-run assessment of the explicit scheduled memory task."""
import hashlib
import json
from pathlib import Path


def replay_jobs(data, cases, args, runtime):
    from equivalence.automation_job_state import build_cases, wire
    from equivalence.automation_job_state_evidence import validate_native
    from equivalence.automation_job_state_native import DRIVER, PRELOAD, _source_bindings
    from equivalence.automation_job_state_replay import make_packet, replay
    from equivalence.heartbeat_dependency import CRONER

    if wire(cases) != wire(build_cases()):
        raise ValueError("Missing or altered frozen scheduled-task definition")
    [definition] = cases
    cid = definition["id"]
    captured = data["followupRows"][cid]
    row, native, sdk, trace = (captured[k] for k in ("case", "native", "python", "trace"))
    if (row.get("runtimeEvidenceValidated") is not True or row["status"] != "matched"
            or native.get("validationStatus") != "verified" or wire(row["openclaw"]) != wire(row["python"])):
        raise ValueError("Scheduled memory task lacks a validated public match")
    [raw] = native["rawSnapshots"]
    validate_native(definition, raw, row["openclaw"])
    if (raw["sourceBindings"]["owners"] != _source_bindings(args.reference)
            or raw["dependency"]["integrity"] != CRONER["integrity"]
            or raw["release"] != {k: runtime[k] for k in ("buildAttestation", "lockfileSha256", "manifestSha256")}
            or raw["driverSha256"] != hashlib.sha256(DRIVER.read_bytes()).hexdigest()
            or raw["preloadSha256"] != hashlib.sha256(PRELOAD.read_bytes()).hexdigest()):
        raise ValueError("Scheduled memory task source, release or adapter identity changed")
    files = {(p["location"], entry["path"]): entry["sha256"]
             for p in runtime["packages"] for entry in p["files"]}
    if not trace["loaded"] or any(files.get((item["package"], item["path"])) != item["sha256"]
                                  for item in trace["loaded"]):
        raise ValueError("Unverified module in the original scheduled memory task")
    expected = make_packet(row, native, trace, sdk["sha256"], data["implementation"])
    root = args.report.resolve().parent / "automation-job-state"
    sdk_dir = root / Path(expected["sdkDirectory"]).name
    packet = json.loads((sdk_dir / "review.json").read_bytes())
    if wire(packet) != wire(expected):
        raise ValueError("The compact scheduler packet differs from the full report")
    proofs = replay(packet, root)
    sdk_raw = json.loads((sdk_dir / "python-raw.json").read_bytes())
    if wire(sdk_raw) != wire(sdk["rawSnapshots"]):
        raise ValueError("The SDK raw evidence differs from the full report")
    return [{"id": cid, "publicMatch": True, "nativeRawSha256": packet["stdoutSha256"],
             "sdkRawSha256": packet["sdkSha256"], "durableReceipts": proofs["callbacks"],
             "drives": proofs["drives"], "releaseModules": len(trace["loaded"])}]
