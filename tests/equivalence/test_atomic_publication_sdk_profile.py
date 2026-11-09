"""Real SDK fixture transport, complete IO failures and physical snapshots."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import stat

import pytest

from equivalence.atomic_publication_cases import build_atomic_publication_cases
from equivalence.atomic_publication_evidence import validate_atomic_publication_raw
from equivalence.atomic_publication_runtime import run_atomic_publication


_CASES = build_atomic_publication_cases()


def _case(suffix):
    return next(case for case in build_atomic_publication_cases() if case["id"].endswith("." + suffix))


def test_literal_atomic_catalog_keeps_the_original_three_domains_and_no_credit():
    cases = build_atomic_publication_cases()
    assert len(cases) == len({case["id"] for case in cases}) == 41
    assert {case["operation"] for case in cases} == {
        "atomic-commit-runtime", "atomic-append-runtime", "atomic-bootstrap-runtime",
    }
    assert all(case["requirement"] == "storage.atomic-writes" and case["covers"] == [] for case in cases)
    cases[0]["input"]["request"]["content"] = "changed caller fixture"
    assert build_atomic_publication_cases()[0]["input"]["request"]["content"] != "changed caller fixture"


@pytest.mark.parametrize("case", _CASES, ids=lambda case: case["id"])
def test_every_literal_sdk_case_dispatches_real_owners_and_retains_its_complete_physical_tree(tmp_path, case):
    public = run_atomic_publication(case["input"], evidence_directory=tmp_path)
    raw = json.loads((tmp_path / "python-raw.json").read_text())[0]
    validate_atomic_publication_raw(case, public, raw, evidence_directory=tmp_path)
    root = Path(raw["fixtureBase"]) / "subject"
    actual = {str(root), *(str(path) for path in root.rglob("*"))}
    recorded = {entry["path"] for entry in raw["snapshots"]["after"]}
    assert recorded == actual
    for entry in raw["snapshots"]["after"]:
        path = Path(entry["path"])
        current = path.lstat()
        assert entry["mode"] == stat.S_IMODE(current.st_mode)
        assert entry["stat"]["dev"] == str(current.st_dev)
        assert entry["stat"]["ino"] == str(current.st_ino)
        assert entry["stat"]["nlink"] == str(current.st_nlink)
        if entry["kind"] == "file":
            assert entry["bytes"] == list(path.read_bytes())
    assert [request["outcome"] for request in raw["requests"]] == raw["outcomes"]
    assert all(fault["matched"] == 1 and fault["events"] for fault in raw["faults"])
    if case["input"]["kind"] == "commit":
        assert all(request["owner"] == "memory_core.atomic_publication.commit_memory_content" for request in raw["requests"])
    elif case["input"]["kind"] == "append":
        assert raw["requests"][0]["owner"] == "memory_core.atomic_publication.append_memory_content"
    else:
        assert all(request["owner"] == "memory_core.bootstrap.lifecycle._write_file_if_missing" for request in raw["requests"])


def test_literal_partial_append_keeps_real_dispatched_bytes_and_never_invents_a_publication_marker(tmp_path):
    case = _case("append-partial-efbig")
    public = run_atomic_publication(case["input"], evidence_directory=tmp_path)
    raw = json.loads((tmp_path / "python-raw.json").read_text())[0]
    target = Path(raw["fixtureBase"]) / "subject" / case["input"]["path"]
    assert target.read_bytes() == b"before\nn"
    error = public["outcomes"][0]["error"]
    assert error["name"] == "Error" and error["code"] == "EFBIG"
    assert error["message"] == "EFBIG: file too large, write" and "publication" not in error
    write = next(event for event in raw["ioEvents"] if event["operation"] == "write" and event["when"] == "before")
    assert write["arguments"]["requestedArgs"][1]["bytes"] == list(b"new complete append data\n")
    assert write["arguments"]["delegatedArgs"][1]["bytes"] == [ord("n")]


def test_swallowed_secondary_cleanup_error_keeps_its_original_stack_and_literal_facts_in_io_evidence(tmp_path):
    case = _case("bootstrap-prepare-and-cleanup-fail")
    run_atomic_publication(case["input"], evidence_directory=tmp_path)
    raw = json.loads((tmp_path / "python-raw.json").read_text())[0]
    injected = [event for event in raw["ioEvents"] if event["operation"] == "fault"]
    assert len(injected) == 2
    assert [event["rawError"]["message"] for event in injected] == [fault["message"] for fault in case["input"]["faults"]]
    assert all(event["rawError"]["stack"] and event["error"]["code"] == "EIO" for event in injected)
    assert raw["requests"][0]["rawError"]["stack"]


def test_foreign_cleanup_entry_and_original_parked_stage_are_both_preserved_as_distinct_physical_objects(tmp_path):
    case = _case("bootstrap-foreign-stage-before-cleanup")
    public = run_atomic_publication(case["input"], evidence_directory=tmp_path)
    raw = json.loads((tmp_path / "python-raw.json").read_text())[0]
    validate_atomic_publication_raw(case, public, raw, evidence_directory=tmp_path)
    parked = next(entry for entry in raw["snapshots"]["after"] if Path(entry["path"]).name == "parked-stage-0")
    original = raw["stageAllocations"][0]
    foreign = next(entry for entry in raw["snapshots"]["after"] if entry["path"] == original["path"])
    assert parked["stat"]["ino"] == original["stat"]["ino"]
    assert foreign["stat"]["ino"] != original["stat"]["ino"]
    assert foreign["bytes"] == list(b"foreign stage winner\n")
    assert parked["bytes"] == list(b"complete bootstrap\n")


@pytest.mark.parametrize("update", [
    {"path": "../ambient.md"}, {"version": 2}, {"kind": "manager"}, {"parentMode": 0o777},
    {"request": {"content": "incomplete"}},
    {"faults": [{"id": "arbitrary", "operation": "network", "role": "target", "effect": "reject-before",
                 "occurrence": 1, "code": "EIO", "message": "outside the IO profile"}]},
])
def test_unbounded_sdk_profiles_are_rejected_before_fixture_mutation(tmp_path, update):
    value = deepcopy(_CASES[0]["input"])
    value.update(update)
    with pytest.raises(ValueError):
        run_atomic_publication(value, evidence_directory=tmp_path)
    assert list(tmp_path.iterdir()) == []
