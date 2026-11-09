"""Actual SDK policy flows, metadata custody and rejection of altered evidence."""
from copy import deepcopy
import json

import pytest

from equivalence.host_restart import build_cases as original_cases, validate_case as validate_original
from equivalence.host_restart_policy import build_cases, validate_case
from equivalence.host_restart_policy_evidence import validate_capture
from equivalence.host_restart_sdk import run_host_restart


@pytest.fixture(scope="module")
def captures(tmp_path_factory):
    root = tmp_path_factory.mktemp("real-host-policy")
    captures = []
    for case in build_cases():
        directory = root / case["id"]
        result = run_host_restart(case["input"], evidence_directory=directory)
        raw = json.loads((directory / "python-raw.json").read_text())[0]
        captures.append((case, raw, result))
    return captures


@pytest.mark.parametrize("index", range(4))
def test_actual_sdk_policy_metadata_and_process_custody(captures, index):
    case, raw, result = captures[index]
    observed = validate_capture(case, raw, result, native=False)
    assert observed["policyResolutionPassed"] and observed["metadataSyscallCustodyPassed"]
    assert observed["acceptancePointsAwarded"] == 0
    assert observed["observedCorpusTimeline"]
    for phase in result["phases"]:
        for read in phase["reads"]:
            assert {key: read["search"]["debug"][key] for key in ("searchMs", "toolMs", "outsideSearchMs")} == {
                "searchMs": 0, "toolMs": 0, "outsideSearchMs": 0}


def test_both_frozen_families_refuse_each_others_inputs_and_coverage_claims():
    for case in build_cases():
        assert validate_case(case) == case
        with pytest.raises(ValueError):
            validate_original(case)
        claimed = deepcopy(case)
        claimed["covers"] = ["host.restart-recall.outcomes"]
        with pytest.raises(ValueError):
            validate_case(claimed)
    for case in original_cases():
        assert validate_original(case) == case
        with pytest.raises(ValueError):
            validate_case(case)


@pytest.mark.parametrize("attack", ["changed-inode", "changed-mtime", "changed-bytes", "index-rewrite", "reader-retime", "wrong-ack", "missing-writer-session"])
def test_rejects_self_consistent_policy_custody_substitutions(captures, attack):
    # The sessions-enabled case must prove actual session indexing, rather than
    # merely report that a resolver returned the word "sessions".
    case, original, result = captures[2]
    raw = deepcopy(original)
    produce = raw["phases"][0]["observation"]["raw"]
    restart = raw["phases"][1]["observation"]["raw"]
    writer = produce["turns"][0]
    metadata = writer["sourceMetadata"]
    if attack == "changed-inode":
        metadata["after"]["stat"]["ino"] += 1
    elif attack == "changed-mtime":
        metadata["after"]["stat"]["mtimeNs"] = "0"
    elif attack == "changed-bytes":
        metadata["after"]["source"]["hex"] = "00"
    elif attack == "index-rewrite":
        metadata["publishedAfterMetadataChange"]["revision"] += 1
    elif attack == "reader-retime":
        restart["turns"][0]["sourceMetadata"] = metadata
    elif attack == "wrong-ack":
        writer["assistant"]["content"][0]["text"] = "A different acknowledgement."
    elif attack == "missing-writer-session":
        produce["snapshots"][0]["published"]["chunks"] = [chunk for chunk in produce["snapshots"][0]["published"]["chunks"] if chunk["source"] != "sessions"]
    for phase in raw["phases"]:
        phase["stdout"] = json.dumps(phase["observation"], ensure_ascii=False)
    with pytest.raises(ValueError):
        validate_capture(case, raw, result, native=False)
