from copy import deepcopy
from uuid import uuid4

from equivalence.heartbeat_scratch_outcomes import compare_doctor_outcomes


def _case():
    phase = {"agents": [{"id": "main"}], "ops": [{"op": "repair"}]}
    return {"id": "guard", "phases": [phase, phase]}


def _phases(root, suffix, ino):
    job = str(uuid4())
    absent = [{"path": ".", "kind": "absent"}]
    physical = {"dev": 1, "ino": ino, "size": 3, "nlink": 1, "mtimeMs": 0, "ctimeMs": 0}
    directory = {"path": ".", "kind": "directory", "mode": 0o700, "physical": dict(physical, ino=1)}
    file = {"path": "HEARTBEAT.md", "kind": "file", "mode": 0o600, "physical": physical,
            "bytes": {"type": "bytes", "base64": "YWJj"}}
    stem = "main-" + "a" * 64 + ".md"
    name = stem + "." + suffix
    archive = [directory, dict(file, path=stem, physical=dict(physical, ino=ino + 1)),
               dict(directory, path=name), dict(file, path=name + "/HEARTBEAT.md")]
    before = {"sourceTree": [directory, file], "archiveTree": absent, "monitors": {"main": {"type": "undefined"}}}
    after = {"sourceTree": [directory], "archiveTree": archive, "monitors": {
        "main": {"jobId": job, "state": {"currentRevision": 1, "scratch": {"content": "abc"}}}}}
    response = {"changes": [f"Migrated {root}/workspace/HEARTBEAT.md"], "warnings": []}
    call = {"operation": {"op": "repair"}, "result": response}
    tree = [{**row, "path": "state/backups/heartbeat-migration" +
             ("/" + row["path"] if row["path"] != "." else "")} for row in archive]
    result = []
    for number, snapshots in enumerate(([before, after], [after, after])):
        result.append({"kind": "heartbeat-doctor-observation", "covers": [],
                       "result": {"operations": [response], "snapshots": snapshots},
                       "raw": {"pid": 100 + number, "fixtureDirectory": root, "calls": [call],
                               "snapshots": snapshots, "fixtureTreeAfterClose": tree}})
    return result


def test_generated_values_match_only_if_relationships_and_public_results_survive():
    native = _phases("/fixture/native", "bZMf47", 101)
    sdk = _phases("/fixture/sdk", "a9_w4cdb", 22)
    assert compare_doctor_outcomes(_case(), native, sdk)["matches"]
    native_style = _phases("/fixture/sdk", "aZl780", 22)
    assert compare_doctor_outcomes(_case(), native, native_style)["matches"]
    wrong_suffix = _phases("/fixture/sdk", "aZl7807", 22)
    assert not compare_doctor_outcomes(_case(), native, wrong_suffix)["matches"]

    changed = [sdk[0], deepcopy(sdk[1])]
    # A close/reopen regenerated an owner, while the note stayed the same.
    new_id = str(uuid4())
    for snap in changed[1]["raw"]["snapshots"]:
        snap["monitors"]["main"] = {**snap["monitors"]["main"], "jobId": new_id}
    assert not compare_doctor_outcomes(_case(), native, changed)["matches"]

    changed = deepcopy(sdk)
    changed[0]["raw"]["calls"][0]["result"]["warnings"].append("operator action required")
    assert not compare_doctor_outcomes(_case(), native, changed)["matches"]


def test_copy_instead_of_archiving_original_and_observing_wrong_directory_fail():
    native = _phases("/fixture/native", "bZMf47", 101)
    sdk = _phases("/fixture/sdk", "a9_w4cdb", 22)
    changed = deepcopy(sdk)
    final = changed[0]["raw"]["snapshots"][-1]["archiveTree"][-1]
    final["physical"] = dict(final["physical"], ino=90)
    changed[0]["raw"]["fixtureTreeAfterClose"][-1]["physical"] = final["physical"]
    assert not compare_doctor_outcomes(_case(), native, changed)["matches"]

    changed = deepcopy(sdk)
    changed[0]["raw"]["fixtureTreeAfterClose"] = []
    assert not compare_doctor_outcomes(_case(), native, changed)["matches"]

    changed = deepcopy(sdk)
    source = changed[0]["raw"]["snapshots"][-1]["sourceTree"]
    source.append(dict(source[0], path=".memory-core"))
    assert not compare_doctor_outcomes(_case(), native, changed)["matches"]
