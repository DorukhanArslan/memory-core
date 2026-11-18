"""Reproduce the schedule, migration and Doctor outcomes from retained disk evidence."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from equivalence.automation_job_outcomes import build_cases, comparable, validate_case, wire
from equivalence.automation_job_outcomes_native import _migration, portable_findings, portable_jobs
from memory_core.heartbeat_migration import MIGRATE_HEARTBEAT_TASKS_COMMAND


def equal(left, right, message):
    if wire(left) != wire(right):
        raise ValueError("Automation outcomes: " + message)


def read_checked(path, digest):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Missing retained evidence file: " + str(path))
    data = path.read_bytes()
    equal(sha256(data).hexdigest(), digest, "evidence digest changed for " + path.name)
    return data


def stored_jobs(database, store_key):
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro&immutable=1", uri=True) as db:
        rows = db.execute("SELECT job_json,state_json,runtime_updated_at_ms FROM cron_jobs "
                          "WHERE store_key=? ORDER BY sort_order", (str(store_key),))
        jobs = []
        for definition, state, updated in rows:
            job = json.loads(definition)
            job["state"] = json.loads(state)
            if updated is not None:
                job["updatedAtMs"] = updated
            jobs.append(job)
        return jobs


def sdk_scheduling(case, raw, actual, stage):
    equal(raw["probes"], actual["probes"], "SDK schedule decisions changed")
    equal(len(case["input"]["probes"]), len(actual["probes"]), "incomplete SDK schedule decisions")
    previous = None
    for drive, row, capture in zip(case["input"]["runs"], actual["runs"], raw["runs"], strict=True):
        before, after = (json.loads(capture[key])["jobs"] for key in ("beforeStore", "afterStore"))
        if previous is not None:
            equal(before, previous, "SDK run was not reopened")
        equal(row, capture["observation"], "SDK run receipt differs")
        equal(after, row["jobs"], "SDK return omitted durable job fields")
        if row["receipt"]["ran"]:
            [callback] = row["callbacks"]
            equal(callback["reply"], drive["reply"], "wrong callback settlement")
            equal(callback["wake"]["tasks"][0]["jobId"], drive["jobId"], "wrong scheduled task ran")
        else:
            equal(row["callbacks"], [], "SDK ran a task on an early drive")
            equal(after, before, "SDK early drive wrote a different job")
        previous = after
    equal(json.loads((stage / ".memory-core/automation.json").read_bytes())["jobs"], previous, "SDK final store changed")


def sdk_migration(case, raw, actual, stage):
    for spec, scenario, proof in zip(case["input"]["scenarios"], actual["scenarios"], raw["scenarios"], strict=True):
        equal(scenario["name"], spec["name"], "wrong migration scenario")
        minted, previous = {}, None
        for phase, capture, expected_phase in zip(scenario["phases"], proof["phases"], spec["phases"], strict=True):
            equal(phase["phase"], expected_phase, "wrong migration phase")
            equal(capture["observed"], phase, "SDK lost its migration receipt")
            after = capture["after"]
            jobs = json.loads(after["store"])["jobs"]
            equal(jobs, after["jobs"], "SDK migration capture differs from actual store")
            if previous is not None:
                equal(capture["before"]["store"], previous["store"], "SDK migration did not reopen prior store")
                equal(capture["before"]["session"], previous["session"], "SDK migration did not reopen prior session")
            previous = after
            state = after["session"].get("heartbeatTaskState")
            equal(phase["receipt"], {k: capture["receipt"][k] for k in ("changes", "warnings")},
                  "SDK migration changed its public result")
            equal(phase["after"], {"scratch": after["monitor"], "legacyTaskState": state,
                  "jobs": portable_jobs(jobs, {job["id"] for job in spec["jobs"]}, minted),
                  "findings": portable_findings(after["findings"], proof["storePath"], MIGRATE_HEARTBEAT_TASKS_COMMAND)},
                  "SDK migration changed a returned job, finding or legacy state")
        folder = stage / spec["name"]
        equal((folder / ".memory-core/automation.json").read_bytes().decode(), previous["store"], "SDK final job store")
        with sqlite3.connect((folder / "sessions.sqlite").resolve().as_uri() + "?mode=ro&immutable=1", uri=True) as db:
            [(payload,)] = list(db.execute("SELECT entry_json FROM memory_session_nodes WHERE agent='main'"))
        equal(json.loads(payload).get("heartbeatTaskState"), previous["session"].get("heartbeatTaskState"),
              "SDK legacy timestamps differ from persisted session")


def validate_trace(trace, fixture_root, recorded_attempt):
    index = json.loads(read_checked(fixture_root / "modules.json", trace["moduleTableSha256"]))
    traces = {}
    for invocation in trace["traces"]:
        rel = Path(invocation["directory"]).relative_to(recorded_attempt)
        if rel.parts[0] != fixture_root.name or ".." in rel.parts:
            raise ValueError("Invalid original stage location")
        stage = fixture_root.joinpath(*rel.parts[1:])
        request = stage / "request.json"
        if not request.exists():
            request = stage.parent / "request.json"
        data = json.loads(read_checked(request, invocation["requestSha256"]))
        result = json.loads(read_checked(stage / "result.json", invocation["resultSha256"]))
        read_checked(stage / "stdout.log", invocation["stdoutSha256"])
        read_checked(stage / "stderr.log", invocation["stderrSha256"])
        for actor in invocation["actors"]:
            identity = actor["bootstrap"]
            name = f"load-{identity['pid']}-{identity['threadId']}.jsonl"
            equal(actor["file"], name, "unexpected original actor trace name")
            head, *records = [json.loads(line) for line in read_checked(stage / name, actor["sha256"]).splitlines()]
            equal(head, identity, "unexpected original actor identity")
            equal(actor["loads"], len(records), "missing original imports")
            if any(str(r["load"]) not in index for r in records):
                raise ValueError("Unknown original module")
        traces[str(rel)] = (data, result)
    return traces


def native_evidence(case, raw, output, trace, recorded, local):
    kind = case["input"]["kind"]
    subdir = "managed-dreaming" if kind == "dreaming" else "task-outcomes-" + kind
    invocations = validate_trace(trace, local / subdir, recorded)
    if kind == "dreaming":
        from equivalence.automation_job_dreaming import validate_raw
        validate_raw(case, raw, output, original=True, recorded_directory=recorded, retained_directory=local)
        for spec, source in zip(case["input"]["scenarios"], raw["scenarios"], strict=True):
            request, received = invocations.pop(f"{subdir}/{spec['name']}")
            equal(request, {"scenario": spec, "nowMs": case["input"]["nowMs"]}, "changed dreaming input")
            equal(received, source["data"], "original dreaming raw result differs from the retained stream")
    else:
        scenarios = case["input"].get("scenarios", [case["input"]])
        for spec, evidence in zip(scenarios, raw["stages"], strict=True):
            name = spec.get("name", "scheduling")
            rel = f"{subdir}/{name}"
            folder = local / rel
            steps = ["seed", *spec["phases"]] if kind == "migration" else ["scheduling"]
            for step, capture in zip(steps, evidence["observations"], strict=True):
                request, received = invocations.pop(f"{rel}/{step}")
                equal(received, capture, "original stage capture differs from its stream")
                equal(request, spec, "original received a different literal schedule or migration input")
            batch = evidence["observations"][-1]
            if kind == "migration":
                projected = _migration(spec, recorded / rel, evidence["observations"])
                expected = next(s for s in output["scenarios"] if s["name"] == name)
                equal(projected, expected, "original migration rows differ from the original receipt")
                final_jobs = batch["after"]["store"]["jobs"]
            else:
                equal(output["probes"], batch["probes"], "original schedule decisions changed")
                equal(len(output["probes"]), len(spec["probes"]), "missing original decisions")
                final_jobs = batch["initialStore"]["jobs"]
                for drive, run, row in zip(spec["runs"], batch["runs"], output["runs"], strict=True):
                    equal([run["jobId"], run["atMs"], run["mode"]], [drive[k] for k in ("jobId","atMs","mode")],
                          "wrong original fixed-clock drive")
                    equal(run["beforeStore"]["jobs"], final_jobs, "original store changed across reopen")
                    final_jobs = run["afterStore"]["jobs"]
                    equal(row, {"receipt": run["receipt"], "callbacks": run["callbacks"], "jobs": final_jobs},
                          "wrong original durable run outcome")
            equal(stored_jobs(folder / "state/state/openclaw.sqlite", recorded / rel / "state/cron/jobs.json"),
                  final_jobs, "original final SQL rows differ")
    equal(invocations, {}, "unexpected original invocations")


def replay(packet, root):
    [case] = [row for row in build_cases() if row["id"] == packet["id"]]
    validate_case(case)
    native_dir, sdk_dir = (Path(root) / Path(packet[key]).name for key in ("nativeDirectory", "sdkDirectory"))
    [native] = json.loads(read_checked(native_dir / "native-raw.json", packet["nativeRawSha256"]))
    [sdk] = json.loads(read_checked(sdk_dir / "python-raw.json", packet["sdkRawSha256"]))
    trace = json.loads(read_checked(native_dir / "trace.json", packet["traceSha256"]))
    n, s = (json.loads(read_checked(path / "public.json", checksum))
            for path, checksum in ((native_dir, packet["nativePublicSha256"]), (sdk_dir, packet["sdkPublicSha256"])))
    equal(native["caseSha256"], sha256(wire(case)).hexdigest(), "different original case definition")
    native_evidence(case, native, n, trace, Path(packet["nativeDirectory"]), native_dir)
    kind = case["input"]["kind"]
    if kind == "dreaming":
        from equivalence.automation_job_dreaming import validate_raw
        validate_raw(case, sdk, s, original=False, recorded_directory=Path(packet["sdkDirectory"]), retained_directory=sdk_dir)
    else:
        {"scheduling": sdk_scheduling, "migration": sdk_migration}[kind](case, sdk, s, sdk_dir)
    return comparable(case, n, "native"), comparable(case, s, "sdk")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--evidence-root", required=True, type=Path)
    args = parser.parse_args()
    packet = json.loads(args.packet.read_bytes())
    n, s = replay(packet, args.evidence_root)
    equal(n, s, "native and SDK outcomes differ")
    print(json.dumps({"case": packet["id"], "matched": True, "nativeRawSha256": packet["nativeRawSha256"],
                      "sdkRawSha256": packet["sdkRawSha256"]}))


if __name__ == "__main__":
    main()
