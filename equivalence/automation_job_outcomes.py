"""The fixed-clock schedule, run recording, and both memory migration owners."""
from copy import deepcopy
from hashlib import sha256

from equivalence.automation_job_state import wire
from equivalence.automation_job_outcomes_inputs import scheduling_input, migration_input
from equivalence.automation_job_dreaming_inputs import dreaming_input

OPERATION = "automation-job-outcomes-runtime"
POINT = "automation.job-state.outcomes"
HASHES = {'automation-job-outcomes-scheduling': '10c960bdf64d66488ecfe068ae6854a6220c43ffa7850bb866a573ac4c27fbc1',
 'automation-job-outcomes-migration': 'c15ae26838e1aee36e688dd1010a4fd273210a0293b647daf9505caf94b6d345',
 'automation-job-outcomes-dreaming': 'c729f43896fec52f46d0031a559714cae471919189634b655e72d0c200d25b46'}


def _definitions():
    return [{"id": "automation-job-outcomes-" + value["kind"], "operation": OPERATION,
             "requirement": "automation.job-state", "covers": [POINT], "input": value,
             "driverScope": "Fixed-clock explicit schedule admission/settlement, Doctor heartbeat-task migration "
                            "and managed memory dreaming enrollment and repair. The host owns OS timers.",
             "normalizationPolicy": "Compare complete portable job rows, schedule errors and decisions, receipts, "
                                    "migration diagnostics and durable state. Preserve actual original and SDK "
                                    "command and producer labels, physical store/backup locations and minted UUIDs "
                                    "in raw evidence. Allocate generated UUIDs by their verified declaration. Compare "
                                    "only explicitly approved product-name spellings for generated attribution."}
            for value in (scheduling_input(), migration_input(), dreaming_input())]


def build_cases():
    cases = _definitions()
    if {row["id"]: sha256(wire(row)).hexdigest() for row in cases} != HASHES:
        raise ValueError("Fixed-clock automation outcomes definitions changed")
    return cases


def validate_case(case):
    if not any(wire(case) == wire(row) for row in build_cases()):
        raise ValueError("Unregistered automation outcomes definition")


def _family(rows):
    return [r for r in rows if r.get("operation") == OPERATION or str(r.get("id", "")).startswith("automation-job-outcomes-")
            or POINT in r.get("covers", ())]


def validate_registration(cases):
    selected = _family(cases)
    if selected and wire(selected) != wire(build_cases()):
        raise ValueError("The automation outcomes point requires schedule, migration, and dreaming owners together")


def family_complete(rows):
    family = _family(rows)
    if len(family) != len(HASHES):
        return False
    try:
        validate_registration([{key: row[key] for key in definition}
                               for row, definition in zip(family, build_cases(), strict=True)])
        return all(row.get("status") == "matched" and row.get("runtimeEvidenceValidated") is True for row in family)
    except (KeyError, ValueError, TypeError):
        return False


def comparable(case, actual, producer):
    if case["input"]["kind"] != "migration":
        return actual
    from memory_core._heartbeat_constants import HEARTBEAT_TASK_DESCRIPTION
    from memory_core.heartbeat_migration import MIGRATE_HEARTBEAT_TASKS_COMMAND

    description = {"native": HEARTBEAT_TASK_DESCRIPTION,
                   "sdk": HEARTBEAT_TASK_DESCRIPTION.replace("openclaw doctor", MIGRATE_HEARTBEAT_TASKS_COMMAND)}[producer]
    output = deepcopy(actual)
    for scenario in output["scenarios"]:
        for phase in scenario["phases"]:
            for job in phase["after"]["jobs"]:
                if isinstance(job["id"], dict):
                    if job.get("description") != description:
                        raise ValueError("Unexpected source-specific description on newly migrated job")
                    job["description"] = {"producerRole": "legacy-heartbeat-migration",
                                          "template": HEARTBEAT_TASK_DESCRIPTION.replace("openclaw doctor", "{producer}")}
    return output


def run_original(case, node, checkout, runtime, directory):
    """Retain original physical observations before the independent pair replay."""
    validate_case(case)
    if case["input"]["kind"] == "dreaming":
        from equivalence.automation_job_dreaming import run_native
    else:
        from equivalence.automation_job_outcomes_native import run_native
    from pathlib import Path
    observed = run_native(case, node=node, checkout=checkout, runtime=runtime,
                          runtime_root=Path(runtime["runtimeRoot"]), evidence_directory=directory)
    (directory / "native-raw.json").write_bytes(wire([observed["raw"]]))
    (directory / "public.json").write_bytes(wire(observed["actual"]))
    (directory / "trace.json").write_bytes(wire(observed["releaseTrace"]))
    return {"kind": "official-release-runtime-comparison", "sources": [],
            "results": [{"id": case["id"], "ok": True, "result": observed["actual"]}],
            "releaseSources": observed["releaseSources"], "releaseTrace": observed["releaseTrace"],
            "runtimeDiagnostics": [{"id": case["id"], "rawSnapshots": [observed["raw"]],
                                    "sha256": sha256(wire([observed["raw"]])).hexdigest(),
                                    "validationStatus": "verified", "evidenceDirectory": str(directory)}]}


def run_python(case, directory):
    validate_case(case)
    if case["input"]["kind"] == "dreaming":
        from equivalence.automation_job_dreaming import run_sdk
    else:
        from equivalence.automation_job_outcomes_sdk import run_sdk
    return run_sdk(case, directory)


def review_pair(case, original, sdk, diagnostic, sdk_hash, directory, implementation):
    from pathlib import Path
    from equivalence.automation_job_outcomes_replay import replay, equal

    validate_case(case)
    native_dir = Path(diagnostic["evidenceDirectory"])
    (directory / "public.json").write_bytes(wire(sdk))
    packet = {"id": case["id"], "nativeDirectory": str(native_dir), "sdkDirectory": str(directory),
              "nativeRawSha256": diagnostic["sha256"], "sdkRawSha256": sdk_hash,
              "nativePublicSha256": sha256(wire(original)).hexdigest(), "sdkPublicSha256": sha256(wire(sdk)).hexdigest(),
              "traceSha256": sha256((native_dir / "trace.json").read_bytes()).hexdigest(),
              "implementation": implementation}
    (directory / "review.json").write_bytes(wire(packet))
    n, s = replay(packet, directory.parent)
    equal(n, comparable(case, original, "native"), "full return differs from retained original")
    equal(s, comparable(case, sdk, "sdk"), "full SDK return differs from its retained file")
    return n, s
