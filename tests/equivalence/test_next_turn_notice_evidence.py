"""Replay the first declared notice-observation packet, without running hosts.

Only the new, explicitly selected observation packet supplies test truth. A
missing packet skips without credit; a selected malformed packet fails loudly.
These tests make no assertion about warning presence, retry policy or equality
between engines. Every tamper starts from a genuine complete capture.
"""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import stat

import pytest

from equivalence.host_turn_barrier import build_cases


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = Path(os.environ.get("MEMORY_NEXT_TURN_NOTICE_EVIDENCE_ROOT", ROOT)).resolve()
CAPTURE_ROOT = os.environ.get("MEMORY_NEXT_TURN_NOTICE_CAPTURE_ROOT")
CONTRACT_SHA = "bceed5c96344270816f676d27fa02117370b714d69c6b1cc492aab7b5cb98585"
CASES = build_cases()


def _guard():
    from equivalence import next_turn_notice_evidence
    return next_turn_notice_evidence


def _trusted_node():
    """The caller chooses decoder authority; raw executable fields never do."""
    return Path(os.environ.get("MEMORY_EQ_NODE", SOURCE_ROOT / "work/node-v24.16.0-linux-x64/bin/node")).resolve()


@lru_cache(maxsize=32)
def _read_cached(path, size, mtime):
    return json.loads(Path(path).read_text(encoding="utf8"))


def _read(path):
    info = path.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and not path.is_symlink(), path
    return _read_cached(str(path), info.st_size, info.st_mtime_ns)


def _load(case, native):
    if CAPTURE_ROOT is None:
        pytest.skip("No explicitly selected notice-observation packet; no acceptance credit")
    directory = Path(CAPTURE_ROOT).resolve() / case["id"]
    path = directory / "evidence" / ("native-raw.json" if native else "python-raw.json")
    assert path.is_file(), f"Explicitly selected notice packet is incomplete: {path}"
    values = _read(path)
    assert isinstance(values, list) and len(values) == 1, path
    capture = values[0]
    if native:
        returned = _read(directory / "stdout.json")
        assert returned["ok"] is True and returned["id"] == case["id"], directory
        result = returned["result"]
    else:
        assert capture["kind"] == "host-turn-barrier-sdk-dispatch", path
        assert capture["exit"] == {"code": 0}, path
        result = capture["observation"]["result"]
    raw = capture if native else capture["observation"]["raw"]
    assert raw["input"] == case["input"], path
    assert raw["noticeObservations"]["contractSha256"] == CONTRACT_SHA, path
    facts = _guard().validate_capture(case, capture, result, native=native,
                                      approved_node=_trusted_node() if native else None)
    assert facts["validated"] is True and facts["acceptancePointsAwarded"] == 0
    return case, capture, result


@pytest.fixture(scope="module", params=[True, False], ids=["native", "sdk"])
def engine(request):
    return request.param


@pytest.fixture(scope="module", params=CASES, ids=lambda case: case["id"])
def actual(request, engine):
    return engine, _load(request.param, engine)


@pytest.fixture(scope="module", params=CASES, ids=lambda case: case["id"])
def native_actual(request):
    return _load(request.param, True)


@pytest.fixture(scope="module", params=CASES, ids=lambda case: case["id"])
def sdk_actual(request):
    return _load(request.param, False)


def _raw(capture, native):
    return capture[1] if native else capture[1]["observation"]["raw"]


def _notice(capture, native):
    return _raw(capture, native)["noticeObservations"]


def _reject_observation(capture, native):
    with pytest.raises(ValueError):
        _guard().validate_observations(capture[0], _raw(capture, native), native=native)


def test_observation_contract_keeps_original_four_inputs_and_zero_credit():
    path = SOURCE_ROOT / "docs/next_turn_notice_observation_contract.json"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == CONTRACT_SHA
    contract = _read(path)
    assert [row["id"] for row in contract["inputs"]["cases"]] == [case["id"] for case in CASES]
    assert contract["acceptance"]["addedByThisMeasurement"] == 0
    assert contract["acceptance"]["scoreCanChangeFromThisPlan"] is False
    assert contract["inputs"]["caseInputChanges"] == []


def test_actual_complete_observation_is_valid_without_predicting_a_warning(actual):
    native, capture = actual
    facts = _guard().validate_capture(*capture, native=native,
                                      approved_node=_trusted_node() if native else None)
    assert facts["validated"] is True and facts["acceptancePointsAwarded"] == 0
    assert capture[0]["covers"] == ["host.turn-barrier.outcomes"]


@pytest.mark.parametrize("field", ["contractSha256", "caseWireSha256", "instrumentedActorSha256", "pid", "ppid"])
def test_observation_header_is_bound_to_this_case_and_real_process(actual, field):
    native, baseline = actual
    capture = deepcopy(baseline)
    notice = _notice(capture, native)
    notice[field] = ("0" * 64 if field.endswith("Sha256") else -1)
    _reject_observation(capture, native)


@pytest.mark.parametrize("attack", ["source-bytes", "source-path", "original-function", "restoration"])
def test_observation_is_source_bound_and_restores_original_descriptors(actual, attack):
    native, baseline = actual
    capture = deepcopy(baseline)
    notice = _notice(capture, native)
    if attack == "source-bytes":
        notice["originalSourceBindings"][0]["sha256"] = "0" * 64
    elif attack == "source-path":
        notice["originalSourceBindings"][0]["path"] = "/tmp/borrowed-original-source.py"
    elif attack == "original-function":
        notice["hookDescriptors"][0]["originalFunctionRef"] = "replacement-original-function"
    elif native:
        notice["restoreReceipts"][0]["restoredExactDescriptor"] = False
    else:
        notice["restoration"][0]["restoredExactOwnDescriptor"] = False
    _reject_observation(capture, native)


@pytest.mark.parametrize("field", ["warmup", "followup", "source", "provider"])
def test_original_whole_public_result_cannot_drop_fields(actual, field):
    native, baseline = actual
    capture = deepcopy(baseline)
    assert field in capture[2]
    del capture[2][field]
    if not native:
        capture[1]["observation"]["result"] = deepcopy(capture[2])
        capture[1]["stdout"] = json.dumps(capture[1]["observation"], ensure_ascii=False)
    with pytest.raises(ValueError):
        _guard().validate_capture(*capture, native=native,
                                  approved_node=_trusted_node() if native else None)


@pytest.mark.parametrize("attack", ["status-call", "search-call", "notice-identity", "captured-sequence", "direct-reader"])
def test_native_capture_is_the_actual_status_to_search_source_edge(native_actual, attack):
    capture = deepcopy(native_actual)
    edge = _notice(capture, True)["captureEdges"][0]
    if attack == "status-call":
        edge["statusCallId"] = edge["searchCallId"]
    elif attack == "search-call":
        edge["searchCallId"] = edge["statusCallId"]
    elif attack == "notice-identity":
        edge["noticeRef"] = "borrowed-notice-reference"
    elif attack == "captured-sequence":
        edge["capturedSequence"] += 1
    else:
        edge["noDirectReaderClaim"] = False
    _reject_observation(capture, True)


@pytest.mark.parametrize("attack", ["receiver", "function", "phase", "promise", "forwarding"])
def test_native_observer_retains_original_receiver_function_and_promise(native_actual, attack):
    capture = deepcopy(native_actual)
    calls = _notice(capture, True)["calls"]
    call = next(row for row in calls if row.get("returnKind") == "promise")
    if attack == "receiver":
        call["receiverRef"] = "different-original-receiver"
    elif attack == "function":
        call["originalFunctionRef"] = "different-original-function"
    elif attack == "phase":
        call["returnSeq"] = call["returnSequence"] = call["enterSequence"]
    elif attack == "promise":
        call["originalReturnRef"] = "replacement-promise"
    else:
        call["returnedExactOriginalPromise"] = False
    _reject_observation(capture, True)


@pytest.mark.parametrize("attack", ["returned-notice", "status-scalar", "status-return-sequence"])
def test_native_status_keeps_actual_notice_identity_and_return_snapshot(native_actual, attack):
    capture = deepcopy(native_actual)
    notice = _notice(capture, True)
    edge = notice["captureEdges"][0]
    status = next(row for row in notice["statuses"] if row["callId"] == edge["statusCallId"])
    if attack == "returned-notice":
        status["noticeRef"] = "equal-value-copy-is-not-original"
    elif attack == "status-scalar":
        status["notice"]["sequence"] += 1
    else:
        status["returnSeq"] = edge["searchEnterSeq"]
    _reject_observation(capture, True)


@pytest.mark.parametrize("attack", ["missing-result", "wrong-turn", "wrong-model-call", "wrong-tool", "wrong-carrier", "different-public-result"])
def test_native_tool_checkpoint_is_the_actual_model_consumed_full_carrier(native_actual, attack):
    capture = deepcopy(native_actual)
    notice = _notice(capture, True)
    checkpoint = next(row for row in notice["checkpoints"] if row["event"] == "actual-memory-search-result")
    if attack == "missing-result":
        notice["checkpoints"].remove(checkpoint)
    elif attack == "wrong-turn":
        checkpoint["turn"] = "save"
    elif attack == "wrong-model-call":
        checkpoint["modelCall"] = 0
    elif attack == "wrong-tool":
        checkpoint["actualToolResult"]["toolName"] = "write"
    elif attack == "wrong-carrier":
        checkpoint["actualToolResult"]["content"][0]["text"] = "{}"
    else:
        del checkpoint["publicSearch"]["provider"]
    _reject_observation(capture, True)


@pytest.mark.parametrize("attack", ["missing-live-object", "same-value-copy", "changed-counter", "changed-warning", "before-capture"])
def test_native_delivery_sample_is_the_same_live_notice_after_the_real_capture(native_actual, attack):
    capture = deepcopy(native_actual)
    notice = _notice(capture, True)
    edge = notice["captureEdges"][0]
    checkpoint = next(row for row in notice["checkpoints"] if row["event"] == "actual-memory-search-result")
    sample = next(row for row in checkpoint["notices"] if row["noticeRef"] == edge["noticeRef"])
    if attack == "missing-live-object":
        checkpoint["notices"].remove(sample)
    elif attack == "same-value-copy":
        sample["noticeRef"] = "equal-value-copy-is-not-original"
    elif attack == "changed-counter":
        sample["sequence"] += 1
    elif attack == "changed-warning":
        sample["warning"] += " invented-warning"
    else:
        checkpoint["sequence"] = edge["statusReturnSeq"] - 1
    _reject_observation(capture, True)


@pytest.mark.parametrize("attack", ["skipped-counter", "different-notice", "invented-run-owner"])
def test_native_counter_transition_belongs_to_the_actual_original_writer(native_actual, attack):
    capture = deepcopy(native_actual)
    notice = _notice(capture, True)
    writer = next(row for row in notice["calls"] if row["method"] == "recordAutomaticRebuild")
    if attack == "skipped-counter":
        writer["afterNotice"]["sequence"] += 1
        writer["after"]["notice"]["sequence"] = writer["afterNotice"]["sequence"]
    elif attack == "different-notice":
        writer["noticeRef"] = "borrowed-writer-notice"
    else:
        writer["openRunSyncCallIds"] = [writer["callId"]]
    _reject_observation(capture, True)


@pytest.mark.parametrize("attack", ["reader-identity", "original-reader", "notice-cell", "sequence-cell", "cell-primitive", "freevars", "captured-sequence"])
def test_sdk_opaque_original_reader_keeps_its_actual_distinct_closure(sdk_actual, attack):
    capture = deepcopy(sdk_actual)
    notice = _notice(capture, False)
    row = notice["captures"][0]
    if attack == "reader-identity":
        row["observedReaderRef"] = row["originalReaderRef"]
    elif attack == "original-reader":
        row["originalReaderRef"] = row["observedReaderRef"]
    elif attack == "notice-cell":
        row["closureCellRefs"]["notice"] = row["closureCellRefs"]["sequence"]
    elif attack == "sequence-cell":
        row["closureCellRefs"]["sequence"] = row["closureCellRefs"]["notice"]
    elif attack == "cell-primitive":
        cell = next(ref for ref in notice["references"] if ref["ref"] == row["closureCellRefs"]["sequence"])
        cell["primitiveValue"] = row["capturedSequence"] + 1
    elif attack == "freevars":
        row["closureFreevars"] = list(reversed(row["closureFreevars"]))
    else:
        row["capturedSequence"] += 1
    _reject_observation(capture, False)


@pytest.mark.parametrize("attack", ["zero-delegation", "double-delegation", "different-original", "different-exposed", "different-capture", "changed-return", "reader-before-capture"])
def test_sdk_reader_exception_delegates_once_and_preserves_the_real_return(sdk_actual, attack):
    capture = deepcopy(sdk_actual)
    calls = _notice(capture, False)["calls"]
    reader = next(row for row in calls if row["method"] == "notice-reader")
    if attack == "zero-delegation":
        reader["originalInvocations"] = 0
    elif attack == "double-delegation":
        reader["originalInvocations"] = 2
    elif attack == "different-original":
        reader["originalReaderRef"] = reader["observedReaderRef"]
    elif attack == "different-exposed":
        reader["observedReaderRef"] = reader["originalReaderRef"]
    elif attack == "different-capture":
        reader["captureCallId"] = reader["callId"]
    elif attack == "changed-return":
        reader["returnPrimitive"] = "invented-reader-warning"
    else:
        captured = next(row for row in calls if row["callId"] == reader["captureCallId"])
        reader["enterSequence"] = captured["enterSequence"]
    _reject_observation(capture, False)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_real_pair_custody_does_not_require_matching_warning_outcomes(case):
    native = _load(case, True)
    sdk = _load(case, False)
    facts = _guard().validate_pair(case, native[1], sdk[1], native[2], sdk[2], approved_node=_trusted_node())
    assert facts["validated"] is True and facts["acceptancePointsAwarded"] == 0
