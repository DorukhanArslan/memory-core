"""Provider continuation and the matching tool result after restarting both real sessions."""
from hashlib import sha256
import json
from pathlib import Path

from equivalence.automation_job_state import wire
from equivalence import compaction_active_history
from equivalence.compaction_assembly_inputs import inputs

POINT = "compaction.context-assembly.boundaries"
OPERATION = "compaction-assembly-restart-runtime"
FAMILY = "compaction-context-assembly"
DEFINITIONS_SHA256 = "ee5616fbecb08dd4064f90cae9880c211412bdf02a25c332d960e525a69ad4b8"


def _definitions():
    return [{"id": "compaction-assembly-" + key, "operation": OPERATION,
             "requirement": "compaction.context-assembly", "covers": [POINT], "input": value,
             "driverScope": "Restart the published embedded agent and the SDK host on durable sessions. "
                            "Compare the entire OpenAI Responses input, the real memory_get result, "
                            "and the checkpoint and call/result persisted before and after restart.",
             "normalizationPolicy": "Preserve complete provider input and checkpoint values. "
                                    "Compare the complete tool call and result apart from the host timestamp "
                                    "and turn attribution. Retain both original stores and event envelopes."}
            for key, value in inputs().items()]


def build_cases():
    cases = _definitions()
    if sha256(wire(cases)).hexdigest() != DEFINITIONS_SHA256:
        raise ValueError("The registered compaction restart drives changed")
    return cases


def family_rows(rows):
    return [r for r in rows if not compaction_active_history.active_case(r) and (r.get("operation") == OPERATION
            or POINT in r.get("covers", ()) or r["id"].startswith("compaction-assembly-"))]


def validate_registration(cases):
    compaction_active_history.validate_registration(cases)
    selected = family_rows(cases)
    if selected and wire(selected) != wire(build_cases()):
        raise ValueError("Retained, evicted and different-model restarts must be measured together")


def family_complete(rows):
    family = family_rows(rows)
    try:
        return (len(family) == 3 and all(r.get("status") == "matched" and r.get("runtimeEvidenceValidated") is True
                                        for r in family)
                and wire([{key: r[key] for key in d} for r, d in zip(family, build_cases(), strict=True)]) ==
                    wire(build_cases()))
    except (ValueError, KeyError, TypeError):
        return False


def check_case(case):
    if wire(case) not in [wire(row) for row in [*build_cases(), *compaction_active_history.build_cases()]]:
        raise ValueError("Unregistered compaction restart")


def run_original(case, node, checkout, runtime, directory):
    from equivalence.compaction_assembly_native import run_native
    check_case(case)
    result = run_native(case, checkout=checkout, node=node, runtime_root=Path(runtime["runtimeRoot"]),
                        runtime=runtime, evidence_directory=directory)
    data = wire([result["raw"]])
    (directory / "native-raw.json").write_bytes(data)
    (directory / "public.json").write_bytes(wire(result["actual"]))
    (directory / "trace.json").write_bytes(wire(result["releaseTrace"]))
    return {"kind": "official-release-runtime-comparison", "sources": [],
            "results": [{"id": case["id"], "ok": True, "result": result["actual"]}],
            "releaseSources": result["releaseSources"], "releaseTrace": result["releaseTrace"],
            "runtimeDiagnostics": [{"id": case["id"], "rawSnapshots": [result["raw"]],
                "sha256": sha256(data).hexdigest(), "validationStatus": "verified", "evidenceDirectory": str(directory)}]}


def review_pair(case, original, sdk, diagnostic, sdk_hash, directory, implementation):
    check_case(case)
    native_dir = Path(diagnostic["evidenceDirectory"])
    (directory / "public.json").write_bytes(wire(sdk))
    packet = {"id": case["id"], "nativeDirectory": str(native_dir), "sdkDirectory": str(directory),
              "nativeRawSha256": diagnostic["sha256"], "sdkRawSha256": sdk_hash,
              "nativePublicSha256": sha256(wire(original)).hexdigest(), "sdkPublicSha256": sha256(wire(sdk)).hexdigest(),
              "traceSha256": sha256((native_dir / "trace.json").read_bytes()).hexdigest(),
              "implementation": implementation}
    (directory / "review.json").write_bytes(wire(packet))
    return replay(packet, directory.parent)


def verify_public(case, public):
    """These controls distinguish a usable checkpoint, a stale checkpoint and a real trailing result."""
    if compaction_active_history.active_case(case):
        return compaction_active_history.verify_public(case, public)
    v = case["input"]
    before, after = public["retainedBefore"], public["retainedAfter"]
    if (before != after or before["result"]["details"] != public["tool"]
            or before["result"]["toolCallId"] != before["call"]["id"]
            or before["checkpoint"]["data"] != v["checkpointItem"]["encrypted_content"]
            or json.loads(before["result"]["content"][0]["text"]) != public["tool"]
            or public["tool"]["text"] != v["file"]["text"].rstrip("\n")):
        raise ValueError("Missing durable checkpoint or matched original memory_get result")
    body = public["input"]
    checkpoints = [r for r in body if r.get("type") == "compaction"]
    expected = [v["checkpointItem"]] if (v["checkpointAfterUser"] == len(v["users"]) - 1
                                           and v["attemptModelId"] == v["model"]["id"]) else []
    if checkpoints != expected:
        raise ValueError("Provider received a misplaced or missing checkpoint")
    [call] = [r for r in body if r.get("type") == "function_call"]
    [result] = [r for r in body if r.get("type") == "function_call_output"]
    if (call["name"] != before["call"]["name"] or json.loads(call["arguments"]) != before["call"]["arguments"]
            or call["call_id"] != v["callItem"]["call_id"] or result["call_id"] != call["call_id"]
            or result["output"] != before["result"]["content"][0]["text"] or body.index(call) >= body.index(result)
            or body[-1]["role"] != "user" or not body[-1]["content"][0]["text"].endswith(v["prompt"])):
        raise ValueError("The reopened request did not send the saved tool call and its result")


def replay(packet, root):
    from equivalence.compaction_assembly_native import read_native
    from equivalence.compaction_assembly_sdk import read_sdk
    from equivalence.automation_job_outcomes_replay import read_checked

    [case] = [r for r in [*build_cases(), *compaction_active_history.build_cases()] if r["id"] == packet["id"]]
    actuals = []
    for side, prefix, folder, reader in (("native", "native-attempt-", "native-raw.json", read_native),
                                         ("sdk", "sdk-attempt-", "python-raw.json", read_sdk)):
        recorded = Path(packet[side + "Directory"])
        retained = root / recorded.name
        if (not recorded.is_absolute() or recorded.parent.name != FAMILY or not recorded.name.startswith(prefix)
                or retained.resolve(strict=True) != retained or any(item.is_symlink() for item in retained.rglob("*"))):
            raise ValueError("Unexpected compaction evidence directory")
        [raw] = json.loads(read_checked(retained / folder, packet[side + "RawSha256"]))
        captured = json.loads(read_checked(retained / "public.json", packet[side + "PublicSha256"]))
        if side == "native":
            trace = json.loads(read_checked(retained / "trace.json", packet["traceSha256"]))
            actual = reader(case, raw, recorded, retained, trace)
        else:
            actual = reader(case, raw, recorded, retained)
        if wire(actual) != wire(captured):
            raise ValueError("Retained compaction evidence differs from the public result")
        verify_public(case, actual)
        actuals.append(actual)
    return tuple(actuals)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--evidence-root", required=True, type=Path)
    args = parser.parse_args()
    packet = json.loads(args.packet.read_bytes())
    native, sdk = replay(packet, args.evidence_root.resolve())
    if wire(native) != wire(sdk):
        raise ValueError("Original and SDK differ")
    print(json.dumps({"id": packet["id"], "publicMatch": True, "providerInputItems": len(sdk["input"])}))
