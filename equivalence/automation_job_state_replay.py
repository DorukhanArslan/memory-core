"""Replay the scheduled-task evidence from a retained CI artifact without rerunning the catalog."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from equivalence.automation_job_state import CASE_ID, DIGEST, build_cases, wire
from equivalence.automation_job_state_evidence import validate_native, validate_sdk
from equivalence.automation_job_state_native import MAIN_OWNERS, READ_ENTRY, WRITE_ENTRY, WRITE_OWNER


def _equal(left, right, message):
    if wire(left) != wire(right):
        raise ValueError(message)


def _bytes(path, expected_hash):
    data = path.read_bytes()
    if sha256(data).hexdigest() != expected_hash:
        raise ValueError(f"Changed scheduled-task evidence: {path}")
    return data


def packet_from_report(report):
    [row] = [row for row in report["cases"] if row["id"] == CASE_ID]
    [native] = [d for d in report["runtimeDiagnostics"] if d["id"] == CASE_ID and d["side"] == "native"]
    [sdk] = [d for d in report["runtimeDiagnostics"] if d["id"] == CASE_ID and d["side"] == "python"]
    [trace] = [t for t in report["releaseTraces"] if t["id"] == CASE_ID]
    return make_packet(row, native, trace, sdk["sha256"], report["implementation"])


def make_packet(row, native, trace, sdk_hash, implementation):
    [raw] = native["rawSnapshots"]
    return {"case": row["id"], "caseSha256": raw["caseSha256"], "implementation": implementation,
            "nativeDirectory": native["evidenceDirectory"], "sdkDirectory": row["sdkEvidenceDirectory"],
            "stdoutSha256": native["sha256"], "sdkSha256": sdk_hash, "nativeStore": raw["store"],
            "trace": {k: trace[k] for k in ("bootstraps", "traces", "moduleTableSha256")}}


def replay(packet, root):
    [case] = build_cases()
    _equal([packet["case"], packet["caseSha256"]], [CASE_ID, DIGEST], "Different registered job case")
    native = root / Path(packet["nativeDirectory"]).name / "scheduled-task-original"
    sdk = root / Path(packet["sdkDirectory"]).name
    _equal(json.loads((native / "request.json").read_bytes()), case, "Different original request")
    original = json.loads(_bytes(native / "stdout.json", packet["stdoutSha256"]))
    [python] = json.loads(_bytes(sdk / "python-raw.json", packet["sdkSha256"]))
    sdk_output = {"steps": [step["observation"] for step in python["steps"]]}
    validate_native(case, original["raw"], original["actual"])
    validate_sdk(case, python, sdk_output, sdk, recorded_directory=packet["sdkDirectory"])
    _equal(original["actual"], sdk_output, "Original and SDK scheduled task observations differ")

    trace = packet["trace"]
    table = json.loads(_bytes(native / "loaded-modules.json", trace["moduleTableSha256"]))
    roles = set()
    for identity, saved in zip(trace["bootstraps"], trace["traces"], strict=True):
        filename = f"trace-{identity['pid']}-{identity['threadId']}.jsonl"
        _equal(filename, saved["name"], "Trace does not match its actual process/thread identity")
        entries = [json.loads(line) for line in _bytes(native / filename, saved["sha256"]).splitlines()]
        _equal(entries[0], {k: v for k, v in identity.items() if k != "role"}, "Changed original trace bootstrap")
        _equal(len(entries) - 1, saved["loads"], "Incomplete original module imports")
        role = identity["role"]
        roles.add(role)
        loaded = [table[str(row["load"])] for row in entries[1:]]
        owners = {row["path"] for row in loaded if row["package"] == "node_modules/openclaw"}
        required = {"scheduler": MAIN_OWNERS, "store-worker": [WRITE_ENTRY, WRITE_OWNER],
                    "read-location": [READ_ENTRY]}[role]
        if not set(required) <= owners:
            raise ValueError("Missing original scheduler/reader/SQLite runtime owner")
    if roles != {"scheduler", "store-worker", "read-location"}:
        raise ValueError("Missing original scheduler, SQLite worker or read-only subprocess")
    expected = original["raw"]["steps"][-1]["afterStore"]["jobs"]
    filename = native / "state/state/openclaw.sqlite"
    with sqlite3.connect(filename.resolve().as_uri() + "?mode=ro&immutable=1", uri=True) as db:
        rows = list(db.execute("SELECT store_key, job_id, job_json, state_json, updated_at "
                               "FROM cron_jobs ORDER BY sort_order"))
        jobs = []
        for key, job_id, job_json, state, updated in rows:
            _equal(key, packet["nativeStore"], "Foreign SQLite job")
            job = json.loads(job_json)
            _equal(job_id, job["id"], "Different stored SQLite job identity")
            jobs.append({**job, "state": json.loads(state), "updatedAtMs": updated})
        _equal(jobs, expected, "Actual SQLite data differs from the last original job snapshot")
        receipts = db.execute("SELECT job_id, status FROM cron_run_receipts ORDER BY rowid").fetchall()
    expected_ids = [s["jobId"] for s in original["actual"]["steps"] if s["callbacks"]]
    _equal([rid for rid, _ in receipts], expected_ids, "Missing durable receipt for an explicitly driven job")
    return {"condition": case["covers"][0], "drives": len(sdk_output["steps"]), "callbacks": len(receipts),
            "caseSha256": DIGEST, "producer": packet["implementation"]["gitCommit"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--packet", type=Path)
    source.add_argument("--report", type=Path, help="Focused report, or use the compact CI packet")
    parser.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args()
    packet = json.loads((args.packet or args.report).read_bytes())
    if args.report:
        packet = packet_from_report(packet)
    print(json.dumps(replay(packet, args.evidence_root)))


if __name__ == "__main__":
    main()
