"""Real SDK process-flow checks and adversarial zero-credit evidence replay."""
from copy import deepcopy
import json

import pytest

from equivalence.host_restart import CASE_HASHES, build_cases, validate_case
from equivalence.host_restart_evidence import validate_capture
from equivalence.host_restart_sdk import run_host_restart


@pytest.fixture(scope="module")
def captures(tmp_path_factory):
    root = tmp_path_factory.mktemp("host-restart-real-sdk")
    rows = []
    for case in build_cases():
        directory = root / case["id"]
        result = run_host_restart(case["input"], evidence_directory=directory)
        raw = json.loads((directory / "python-raw.json").read_text())[0]
        rows.append((case, raw, result))
    return rows


def _rewire(raw):
    """An adversarial carrier can be self-consistent without being live evidence."""
    for phase in raw["phases"]:
        phase["stdout"] = json.dumps(phase["observation"], ensure_ascii=False)


@pytest.mark.parametrize("index", range(3))
def test_actual_sdk_host_process_flow(captures, index):
    case, raw, result = captures[index]
    assert validate_capture(case, raw, result, native=False) == {
        "structuralCustodyPassed": True, "acceptancePointsAwarded": 0}


def test_restart_literal_family_is_exact_and_zero_credit():
    cases = build_cases()
    assert len(cases) == len(CASE_HASHES) == 3
    assert all(case["covers"] == [] for case in cases)
    for case in cases:
        claimed = deepcopy(case)
        claimed["covers"] = ["host.restart-recall.outcomes"]
        with pytest.raises(ValueError, match="zero-credit"):
            validate_case(claimed)
        changed = deepcopy(case)
        changed["input"]["phases"][1]["recall"]["prompt"] += " Answer is already known."
        with pytest.raises(ValueError, match="exact"):
            validate_case(changed)


@pytest.mark.parametrize("attack", ["same-process", "overlapping-processes", "full-input", "stdin-digest", "seeded-source",
                                   "initial-answer", "active-producer", "cancelled-read", "invented-answer", "changed-score"])
def test_rejects_adversarial_host_receipts(captures, attack):
    case, original, original_result = captures[0]
    raw, result = deepcopy(original), deepcopy(original_result)
    child = raw["phases"][1]
    phase = child["observation"]["raw"]
    turn = phase["turns"][0]
    if attack == "same-process":
        child["pid"] = raw["phases"][0]["pid"]
    elif attack == "overlapping-processes":
        child["startedAtNs"] = raw["phases"][0]["startedAtNs"]
    elif attack == "full-input":
        child["request"]["oldProducer"] = case["input"]["phases"][0]
    elif attack == "stdin-digest":
        child["requestSha256"] = "0" * 64
    elif attack == "seeded-source":
        raw["phases"][0]["observation"]["raw"]["initialSource"]["kind"] = "file"
    elif attack == "initial-answer":
        turn["modelInput"]["runtimeContext"] = case["input"]["phases"][0]["write"]["text"]
    elif attack == "active-producer":
        phase["settlement"][0]["outstandingBlockingSources"] = 1
    elif attack == "cancelled-read":
        turn["outcome"]["cancelled"] = True
    elif attack == "invented-answer":
        result["phases"][1]["reads"][0]["answer"] = "Invented answer"
        child["observation"]["result"]["reads"][0]["answer"] = "Invented answer"
        turn["assistant"]["content"][0]["text"] = "Invented answer"
    elif attack == "changed-score":
        result["phases"][1]["reads"][0]["search"]["results"][0]["score"] = 1.0
        child["observation"]["result"]["reads"][0]["search"]["results"][0]["score"] = 1.0
    _rewire(raw)
    with pytest.raises(ValueError):
        validate_capture(case, raw, result, native=False)


def test_get_failure_cannot_be_relabelled_as_success(captures):
    case, original, original_result = captures[2]
    raw, result = deepcopy(original), deepcopy(original_result)
    child = raw["phases"][1]
    child["observation"]["raw"]["turns"][0]["outcome"]["failures"] = []
    _rewire(raw)
    with pytest.raises(ValueError, match="suppressed"):
        validate_capture(case, raw, result, native=False)


def test_self_consistent_get_and_answer_must_still_match_real_source_bytes(captures):
    case, original, original_result = captures[0]
    raw, result = deepcopy(original), deepcopy(original_result)
    child = raw["phases"][1]
    turn = child["observation"]["raw"]["turns"][0]
    call = turn["toolCalls"][1]
    payload = deepcopy(call["returned"])
    payload["text"] = "A fabricated answer."
    call["returned"] = payload
    call["observed"]["payload"] = payload
    call["observed"]["message"]["details"] = payload
    call["observed"]["message"]["content"][0]["text"] = json.dumps(payload)
    terminal = next(message for message in turn["terminalInput"]["messages"] if message.get("toolName") == "memory_get")
    terminal["details"] = payload
    terminal["content"][0]["text"] = json.dumps(payload)
    turn["assistant"]["content"][0]["text"] = payload["text"]
    for public in [result["phases"][1]["reads"][0], child["observation"]["result"]["reads"][0]]:
        public["get"] = payload
        public["answer"] = payload["text"]
    _rewire(raw)
    with pytest.raises(ValueError, match="actual saved source range"):
        validate_capture(case, raw, result, native=False)
