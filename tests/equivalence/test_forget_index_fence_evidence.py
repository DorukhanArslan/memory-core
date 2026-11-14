"""Replay only explicitly selected, genuine forget/index-fence packets.

Legacy SDK packets and new V2 paired packets have separate explicit selectors.
A failed Native transport cannot become a positive paired baseline. No test
launches an original engine or modifies a retained capture file.
"""
import base64
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import zlib

import pytest

from equivalence import forget_index_fence_evidence as guard
from equivalence.forget_index_fence import build_cases
from equivalence.forget_index_fence_v2 import build_cases as build_v2_cases


ROOT = Path(__file__).resolve().parents[2]
CAPTURE_ROOT = os.environ.get("MEMORY_FORGET_INDEX_FENCE_CAPTURE_ROOT")
SDK_CAPTURE_ROOT = os.environ.get("MEMORY_FORGET_INDEX_FENCE_SDK_CAPTURE_ROOT")
REJECTED_NATIVE_CAPTURE_ROOT = os.environ.get("MEMORY_FORGET_INDEX_FENCE_REJECTED_NATIVE_ROOT")
REJECTED_RELEASE_CAPTURE_ROOT = os.environ.get("MEMORY_FORGET_INDEX_FENCE_REJECTED_RELEASE_ROOT")
SDK_SOURCE_ROOT = Path(os.environ.get("MEMORY_FORGET_INDEX_FENCE_SDK_SOURCE_ROOT", ROOT)).resolve()
REFERENCE_ROOT = Path(os.environ.get("MEMORY_FORGET_INDEX_FENCE_REFERENCE_ROOT", ROOT / "work/openclaw-v2026.9.9")).resolve()
CASES = build_cases()
V2_CASES = build_v2_cases()


def _read(path):
    info = path.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and not path.is_symlink(), path
    return json.loads(path.read_text(encoding="utf8"))


@lru_cache(maxsize=2)
def _sdk(case_id):
    if SDK_CAPTURE_ROOT is None:
        pytest.skip("No explicitly selected new SDK forget/index-fence packet; no acceptance credit")
    case = next(case for case in CASES if case["id"] == case_id)
    directory = Path(SDK_CAPTURE_ROOT).resolve(strict=True) / case_id / "sdk/evidence"
    path = directory / "python-raw.json"
    assert path.is_file(), f"The explicitly selected packet is incomplete: {path}"
    values = _read(path)
    assert isinstance(values, list) and len(values) == 1, path
    capture = values[0]
    result = capture["observation"]["result"]
    assert guard.validate_capture(case, capture, result, native=False,
        approved_sdk_root=SDK_SOURCE_ROOT, directory=directory) is True
    return case, capture, result, directory


@pytest.fixture(scope="module", params=CASES, ids=lambda case: case["id"])
def sdk_actual(request):
    return _sdk(request.param["id"])


def _trusted_node():
    return Path(os.environ.get("MEMORY_EQ_NODE", ROOT / "work/node-v24.16.0-linux-x64/bin/node")).resolve()


@lru_cache(maxsize=1)
def _v2_raw_packet(case_id):
    if CAPTURE_ROOT is None:
        pytest.skip("No explicitly selected new V2 paired packet; no acceptance credit")
    case = next(case for case in V2_CASES if case["id"] == case_id)
    directory = Path(CAPTURE_ROOT).resolve(strict=True) / case_id
    native_directory, sdk_directory = directory / "native", directory / "sdk/evidence"
    native_path = native_directory / "evidence/native-raw.json"
    sdk_path = sdk_directory / "python-raw.json"
    assert native_path.is_file() and sdk_path.is_file(), f"The explicitly selected V2 packet is incomplete: {directory}"
    native_values, sdk_values = _read(native_path), _read(sdk_path)
    assert isinstance(native_values, list) and len(native_values) == 1, native_path
    assert isinstance(sdk_values, list) and len(sdk_values) == 1, sdk_path
    returned = _read(native_directory / "stdout.json")
    assert returned["id"] == case_id and returned["ok"] is True
    native, sdk = native_values[0], sdk_values[0]
    native_result, sdk_result = returned["result"], sdk["observation"]["result"]
    return case, native, sdk, native_result, sdk_result, native_directory, sdk_directory


@lru_cache(maxsize=1)
def _v2_packet(case_id):
    values = _v2_raw_packet(case_id)
    case, native, sdk, native_result, sdk_result, native_directory, sdk_directory = values
    validated = guard.validate_pair(case, native, sdk, native_result, sdk_result,
        approved_node=_trusted_node(), approved_sdk_root=SDK_SOURCE_ROOT,
        approved_reference=REFERENCE_ROOT, native_directory=native_directory,
        sdk_directory=sdk_directory)
    assert validated is True
    return (*values, validated)


@pytest.fixture(scope="module", params=V2_CASES, ids=lambda case: case["id"])
def v2_actual(request):
    return _v2_packet(request.param["id"])


@pytest.fixture(scope="module", params=V2_CASES, ids=lambda case: case["id"])
def v2_clock_actual(request):
    """Actual receipt subchecks alone never award complete-pair custody."""
    return _v2_raw_packet(request.param["id"])


@lru_cache(maxsize=1)
def _v2_sdk_packet(case_id):
    values = _v2_raw_packet(case_id)
    case, _, sdk, _, result, _, directory = values
    validated = guard.validate_capture(case, sdk, result, native=False,
        approved_sdk_root=SDK_SOURCE_ROOT, directory=directory)
    assert validated is True
    return (*values, validated)


@pytest.fixture(scope="module", params=V2_CASES, ids=lambda case: case["id"])
def v2_sdk_actual(request):
    """Independent SDK custody alone supplies no paired acceptance credit."""
    return _v2_sdk_packet(request.param["id"])


def test_actual_v2_pair_authenticates_both_originals_without_predicting_parity(v2_actual):
    assert v2_actual[-1] is True


def test_actual_v2_sdk_capture_authenticates_without_a_native_positive(v2_sdk_actual):
    assert v2_sdk_actual[-1] is True


@pytest.mark.parametrize("attack", ["source-code", "already-settled"])
def test_v2_sdk_writer_progress_requires_original_source_and_pending_execution(v2_sdk_actual, attack):
    case, _, sdk, *_ = v2_sdk_actual
    raw = sdk["observation"]
    processes, observations = {}, {}
    for process in raw["processes"]:
        observation = process["observation"]
        recorded, trusted, events, returns = guard._sdk_observation(observation, process,
            case["input"], SDK_SOURCE_ROOT)
        processes[process["pid"]] = process
        observations[process["pid"]] = observation, events, returns
    selected = next(((pid, gate) for pid, (observation, _, _) in observations.items()
                     for gate in observation["functionalGates"].values()
                     if gate["armed"] and gate["hits"] and gate["hits"][0].get("progressKind") ==
                     "actual-original-SQLite-writer-attempt"), None)
    if selected is None:
        pytest.skip("The actual selected SDK original did not enter a pending writer attempt; no progress boundary credit")
    pid, gate = selected
    receipt = gate["hits"][0]
    observation, events, returns = observations[pid]
    sequence = receipt["sqlExecutionSequence"]
    execution = deepcopy(events[sequence])
    if attack == "source-code":
        execution["parentCode"]["sourceSha256"] = "0" * 64
        changed = {**observation,
            "originalCalls": [execution if row["sequence"] == sequence else row for row in observation["originalCalls"]],
            "sqlExecutions": [execution if row["sequence"] == sequence else row for row in observation["sqlExecutions"]]}
        with pytest.raises(ValueError):
            guard._sdk_observation(changed, processes[pid], case["input"], SDK_SOURCE_ROOT)
    else:
        stage = next(step for step in raw["steps"] if step["specification"]["operation"] == "await-gate"
                     and step["specification"]["gate"] == gate["specification"]["name"])
        execution["finishedAtNs"] = stage["settledAtNs"]
        observations[pid] = observation, {**events, sequence: execution}, returns
        with pytest.raises(ValueError, match="already settled"):
            guard._sdk_gates(case, raw, processes, observations, recorded, trusted)


@pytest.mark.parametrize("field", ["provider", "calls", "snapshots"])
def test_v2_whole_common_result_cannot_drop_a_field(v2_actual, field):
    case, _, _, native_result, sdk_result, *_ = v2_actual
    for original in (native_result, sdk_result):
        result = deepcopy(original)
        del result[field]
        with pytest.raises(ValueError):
            guard.validate_result(case, result)


def test_v2_public_json_numbers_are_exact_with_distinct_booleans(v2_actual):
    case, *_ = v2_actual
    tick = next(iter(case["input"]["clock"]["sourceWriteClock"]["ticksByCall"].values()))
    value = tick["mtimeMs"]
    guard._same(value, float(value), "Exact JSON numbers must accept their identical float representation")
    with pytest.raises(ValueError):
        guard._same(value, value + 0.001, "Public numbers cannot use an epsilon")
    with pytest.raises(ValueError):
        guard._same(1, True, "JSON booleans must remain distinct from numbers")


def test_rejected_native_transport_never_supplies_a_positive_pair():
    if REJECTED_NATIVE_CAPTURE_ROOT is None:
        pytest.skip("No explicitly selected rejected Native packet; no acceptance credit")
    case = CASES[0]
    directory = Path(REJECTED_NATIVE_CAPTURE_ROOT).resolve(strict=True) / case["id"]
    native_directory, sdk_directory = directory / "native", directory / "sdk/evidence"
    process = _read(native_directory / "process.json")
    assert process.get("timedOut") or process.get("observationFailure") or process.get("returncode") != 0
    with pytest.raises(ValueError):
        guard.replay_case(case, native_directory, sdk_directory,
            approved_node=_trusted_node(), approved_sdk_root=SDK_SOURCE_ROOT,
            approved_reference=REFERENCE_ROOT)


def test_actual_rejected_native_gate_release_is_not_inferred_from_a_release_file():
    if REJECTED_RELEASE_CAPTURE_ROOT is None:
        pytest.skip("No explicitly selected rejected Native release packet; no acceptance credit")
    case = next(case for case in V2_CASES if case["id"] == "forget-index-fence-v2-shared-postcheck-pending-forget")
    directory = Path(REJECTED_RELEASE_CAPTURE_ROOT).resolve(strict=True) / case["id"] / "native"
    values = _read(directory / "evidence/native-raw.json")
    assert isinstance(values, list) and len(values) == 1
    raw = values[0]
    assert raw["caseId"] == case["id"] and raw["completed"] is raw["allChildrenReaped"] is True
    guard._same(raw["input"], case["input"], "The rejected release packet must retain its actual frozen input")
    process, returned = _read(directory / "process.json"), _read(directory / "stdout.json")
    assert process["returncode"] == 0 and returned["id"] == case["id"] and returned["ok"] is True
    gates = [gate for gate in raw["gates"] if gate["name"] == "postcheck"]
    assert len(gates) == 1
    gate = gates[0]
    receipt = gate["receipt"]
    path = directory / "evidence" / f'{receipt["pid"]}-{receipt["threadId"]}-events.jsonl'
    info = path.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and not path.is_symlink()
    events = [json.loads(line) for line in path.read_text(encoding="utf8").splitlines()]
    assert events and all((row["pid"], row["threadId"]) == (receipt["pid"], receipt["threadId"]) for row in events)
    assert not any(row["event"] == "fence-gate-release" and row["gate"] == gate["name"] for row in events)
    # The original coordinator wrote the real file and returned successfully.
    # Neither fact can replace the missing actual worker-consumption receipt.
    assert _read(directory / "gates/postcheck.release") == next(row["step"] for row in raw["steps"]
        if row["step"]["operation"] == "release-gate" and row["step"]["gate"] == gate["name"])
    with pytest.raises(ValueError, match="never consumed its actual release"):
        guard._native_gate_release(gate, raw, events, directory)


@pytest.mark.parametrize("attack", ["drop", "duplicate"])
def test_v2_native_gate_release_requires_actual_unique_consumption(v2_actual, attack):
    case, raw, _, _, _, directory, *_ = v2_actual
    _, _, _, _, _, passive = _native_clock_context(case["id"])
    selected = next(((gate, passive[gate["receipt"]["pid"], gate["receipt"]["threadId"]])
                     for gate in raw["gates"] if gate.get("releasedAtNs") is not None), None)
    if selected is None:
        pytest.skip("The actual selected original did not release a held gate; no release boundary credit")
    gate, events = selected
    release, _ = guard._native_gate_release(gate, raw, events, directory)
    if attack == "drop":
        changed = [row for row in events if row is not release]
    else:
        changed = [*events, deepcopy(release)]
    with pytest.raises(ValueError, match="never consumed its actual release"):
        guard._native_gate_release(gate, raw, changed, directory)


def _sdk_clock_context(v2_actual, *, require_receipt=False, require_datetime=False):
    case, _, sdk, *_ = v2_actual
    for process in sdk["observation"]["processes"]:
        observation = process["observation"]
        if require_receipt and not observation["sourceClockReceipts"]:
            continue
        if require_datetime and not observation["datetimeClockCalls"]:
            continue
        recorded, trusted, events, returns = guard._sdk_observation(observation, process,
            case["input"], SDK_SOURCE_ROOT)
        context = case, sdk, process, observation, recorded, trusted, events, returns
        proof = _validate_sdk_clock(context, observation)
        assert set(proof) == {"commits", "reads"}
        return context
    pytest.skip("The selected actual original did not enter this clock boundary; no boundary credit")


def _validate_sdk_clock(context, observation):
    from equivalence.forget_index_fence_sdk_clock_evidence import validate_sdk_clock_v2

    case, sdk, process, _, recorded, trusted, events, returns = context
    process = {**process, "observation": observation}
    return validate_sdk_clock_v2(case, observation, process, events, returns,
        recorded_root=recorded, approved_sdk_root=trusted,
        fixture_root=Path(sdk["request"]["directory"]))


@pytest.mark.parametrize("attack", [
    "tick", "utime", "descriptor", "inode", "bytes", "fsync", "writer-source",
    "commit-witness", "post-utime-stat", "duplicate",
])
def test_v2_sdk_clock_requires_actual_source_owned_write_and_commit(v2_clock_actual, attack):
    context = _sdk_clock_context(v2_clock_actual, require_receipt=True)
    original = context[3]
    observation = {**original, "sourceClockReceipts": list(original["sourceClockReceipts"])}
    receipt = deepcopy(observation["sourceClockReceipts"][0])
    observation["sourceClockReceipts"][0] = receipt
    if attack == "tick":
        receipt["tick"]["mtimeMs"] += 1000
    elif attack == "utime":
        receipt["utimeArguments"]["ns"][1] += 1
    elif attack == "descriptor":
        receipt["descriptor"] += 1000
    elif attack == "inode":
        receipt["after"]["identity"]["inode"] += 1
    elif attack == "bytes":
        payload = bytes.fromhex(receipt["after"]["bytes"])
        assert payload, "Select an actual nonempty original write for this replay"
        changed = bytes([payload[0] ^ 1]) + payload[1:]
        receipt["after"]["bytes"] = changed.hex()
        receipt["after"]["sha256"] = hashlib.sha256(changed).hexdigest()
    elif attack == "fsync":
        receipt["originalFsync"] = None
        receipt["originalFsyncPresent"] = False
    elif attack == "writer-source":
        receipt["sourceStack"][0]["code"]["sourceSha256"] = "0" * 64
    elif attack == "commit-witness":
        receipt["originalCommit"]["witness"] = "fixture-inferred-publication"
    elif attack == "post-utime-stat":
        info = receipt["statImmediatelyAfterUtime"]
        info["st_mtime_ns"] = str(int(info["st_mtime_ns"]) + 1)
    else:
        observation["sourceClockReceipts"].append(deepcopy(receipt))
    with pytest.raises(ValueError):
        _validate_sdk_clock(context, observation)


@pytest.mark.parametrize("attack", [
    "wall-clock", "returned-time", "returned-class", "source", "scope", "binding",
    "same-object", "removed-calls",
])
def test_v2_sdk_datetime_clock_is_narrow_and_source_qualified(v2_clock_actual, attack):
    context = _sdk_clock_context(v2_clock_actual, require_datetime=True)
    original = context[3]
    observation = {**original, "datetimeClockCalls": list(original["datetimeClockCalls"]),
                   "clockBindings": deepcopy(original["clockBindings"])}
    receipt = deepcopy(observation["datetimeClockCalls"][0])
    observation["datetimeClockCalls"][0] = receipt
    if attack == "wall-clock":
        receipt["wallClockNowMs"] += 1000
    elif attack == "returned-time":
        receipt["returnedISO"] = receipt["returnedISO"].replace("00:00:00", "00:00:01")
    elif attack == "returned-class":
        receipt["returnedClass"]["name"] = "DatetimeClockProxy"
    elif attack == "source":
        receipt["sourceCode"]["sourceSha256"] = "0" * 64
    elif attack == "scope":
        scope = receipt["scope"]
        scope["label"] = next(call["label"] for call in original["publicCalls"].values()
                              if call["kind"] == scope["kind"] and call["label"] != scope["label"])
    elif attack == "binding":
        observation["clockBindings"]["datetime"]["bindingIsExactProxy"] = False
    elif attack == "same-object":
        binding = observation["clockBindings"]["datetime"]
        binding["proxyObjectId"] = binding["originalClassObjectId"]
    else:
        observation["datetimeClockCalls"] = []
    with pytest.raises(ValueError):
        _validate_sdk_clock(context, observation)


def _renumber_sdk_clock(observation):
    rows = sorted((row for key in ("sourceClockReceipts", "sourceClockOriginalIO", "sourceClockReads")
                   for row in observation[key]), key=lambda row: row["sequence"])
    mapping = {row["sequence"]: number for number, row in enumerate(rows, 1)}
    for row in rows:
        row["sequence"] = mapping[row["sequence"]]
    for receipt in observation["sourceClockReceipts"]:
        embedded = [receipt.get("originalOpen"), receipt.get("originalFullWrite"), receipt.get("originalFsync"),
                    *receipt.get("originalWrites", []), *receipt.get("originalTextIO", [])]
        for part in embedded:
            if part is not None:
                part["sequence"] = mapping[part["sequence"]]


@pytest.mark.parametrize("attack", ["source-read", "original-close"])
def test_v2_sdk_clock_cannot_hide_original_receipts_by_renumbering(v2_clock_actual, attack):
    context = _sdk_clock_context(v2_clock_actual, require_receipt=True)
    original = context[3]
    observation = {**original, **{key: deepcopy(original[key]) for key in
        ("sourceClockReceipts", "sourceClockOriginalIO", "sourceClockReads")}}
    if attack == "source-read":
        if not observation["sourceClockReads"]:
            pytest.skip("The actual selected writer did not perform an eligible source read")
        del observation["sourceClockReads"][0]
    else:
        selected = next((row for row in observation["sourceClockOriginalIO"]
                         if row["event"] == "original-source-io-return" and row["syscall"] == "close"), None)
        if selected is None:
            pytest.skip("The actual selected writer has no original close receipt")
        observation["sourceClockOriginalIO"].remove(selected)
    _renumber_sdk_clock(observation)
    with pytest.raises(ValueError):
        _validate_sdk_clock(context, observation)


@lru_cache(maxsize=1)
def _native_clock_context(case_id):
    case, raw, _, _, _, directory, _ = _v2_raw_packet(case_id)
    context, _, authority, imports, passive = guard._native_authority(
        case, raw, directory, _trusted_node(), None, REFERENCE_ROOT)
    actors = {}
    for child in raw["children"]:
        actor = _read(directory / "evidence" / f'{child["actor"]}-{child["instance"]}-raw.json')
        assert actor["pid"] == child["pid"]
        actors[child["pid"]] = child, actor
    proof = guard._native_source_clock_v2(case, raw, actors, imports, passive, context,
        authority, _trusted_node())
    assert set(proof) == {"commits", "reads", "boundaries"}
    return case, actors, context, authority, imports, passive


def _native_control(context):
    _, actors, *_ = context
    for child, actor in actors.values():
        for control in actor["sourceClock"]["receipts"]:
            if control["event"] == "source-clock-control":
                return child, actor, control
    pytest.skip("The selected actual original did not write an eligible source; no write boundary credit")


@pytest.mark.parametrize("attack", [
    "tick", "utime", "causal-frame", "write-order", "writer-source", "open-source",
    "descriptor", "handle", "inode", "bytes", "utime-return", "published-inode",
    "rename-arguments", "commit", "published-bytes", "write-return", "sync-return",
])
def test_v2_native_clock_authenticates_the_real_control_and_publication(v2_clock_actual, attack):
    case, *_ = v2_clock_actual
    context = _native_clock_context(case["id"])
    _, _, execution, authority, imports, original_passive = context
    child, actor, original = _native_control(context)
    if original["operation"] != "atomic":
        pytest.skip("This test requires an actually entered atomic publication boundary")
    control = deepcopy(original)
    if attack == "tick":
        control["tick"]["mtimeMs"] += 1000
    elif attack == "utime":
        control["utimes"]["arguments"][1] += 1
    elif attack == "causal-frame":
        control["causalFrame"]["wallClockNowMs"] += 1000
    elif attack == "write-order":
        control["writes"][-1]["finishedAtNs"] = str(int(control["startedAtNs"]) + 1)
    elif attack in {"writer-source", "open-source"}:
        owner = control["sourceOwner"] if attack == "writer-source" else control["open"]["sourceOwner"]
        owner["sha256"] = "0" * 64
    elif attack == "descriptor":
        control["fd"] = -1
    elif attack == "handle":
        control["handleRef"] = ""
    elif attack == "inode":
        control["after"]["pathStat"]["ino"] = str(int(control["after"]["pathStat"]["ino"]) + 1)
    elif attack in {"bytes", "published-bytes"}:
        state = control["after"] if attack == "bytes" else control["published"]
        payload = bytes.fromhex(state["bytesHex"])
        assert payload, "Select an actual nonempty original write for this replay"
        changed = bytes([payload[0] ^ 1]) + payload[1:]
        state["bytesHex"], state["sha256"] = changed.hex(), hashlib.sha256(changed).hexdigest()
    elif attack == "utime-return":
        control["utimes"]["return"]["v8Hex"] = "ff0f54"
    elif attack == "write-return":
        write = next((row for row in control["writes"] if row["method"] == "fs.promises.writeFile"), None)
        if write is None:
            pytest.skip("The actual selected write did not use the original void writeFile API")
        write["return"]["v8Hex"] = "ff0f54"
    elif attack == "sync-return":
        sync = next((row for row in control["syncs"] if row["status"] == "fulfilled"), None)
        if sync is None:
            pytest.skip("The actual selected write did not perform a successful original fsync")
        sync["return"]["v8Hex"] = "ff0f54"
    elif attack == "published-inode":
        for name in ("fdStat", "pathStat", "readerStat", "afterReadStat"):
            control["published"][name]["ino"] = str(int(control["published"][name]["ino"]) + 1)
    elif attack == "rename-arguments":
        control["rename"]["arguments"] = deepcopy(control["writes"][0]["arguments"])
    else:
        control["committed"] = False

    # Keep the duplicate passive carrier coherent so semantic authentication,
    # rather than a comparison between two copies, must reject the mutation.
    passive = {key: list(rows) for key, rows in original_passive.items()}
    for key, rows in passive.items():
        for number, row in enumerate(rows):
            if row.get("controlId") != control["controlId"]:
                continue
            if row["event"] == "source-clock-control":
                metadata = {"sequence", "pid", "ppid", "threadId", "instance", "atNs", "callLabel"}
                rows[number] = {name: deepcopy(control[name]) if name not in metadata else value
                                for name, value in row.items()}
            elif row["event"] == "source-clock-continuation":
                rows[number] = {**row, "rename": deepcopy(control["rename"]),
                                "published": deepcopy(control["published"]), "committed": control["committed"]}
    with pytest.raises(ValueError):
        guard._native_clock_control_v2(case, control, actor=actor, child=child,
            context=execution, imports=imports, passive=passive, authority=authority,
            approved_node=_trusted_node())


@pytest.mark.parametrize("event", ["source-clock-read", "source-clock-call-boundary"])
@pytest.mark.parametrize("attack", ["omit", "duplicate"])
def test_v2_native_clock_requires_complete_unique_actual_receipts(v2_clock_actual, event, attack):
    case, *_ = v2_clock_actual
    context = _native_clock_context(case["id"])
    _, original_actors, execution, authority, imports, passive = context
    selected = next(((pid, child, actor, receipt) for pid, (child, actor) in original_actors.items()
                     for receipt in actor["sourceClock"]["receipts"] if receipt["event"] == event), None)
    if selected is None:
        pytest.skip("The actual selected original did not enter this receipt boundary")
    pid, child, original, receipt = selected
    receipts = list(original["sourceClock"]["receipts"])
    if attack == "omit":
        receipts.remove(receipt)
    else:
        receipts.append(deepcopy(receipt))
    actor = {**original, "sourceClock": {**original["sourceClock"], "receipts": receipts}}
    actors = {**original_actors, pid: (child, actor)}
    with pytest.raises(ValueError):
        guard._native_source_clock_v2(case, v2_clock_actual[1], actors, imports, passive,
            execution, authority, _trusted_node())


def test_actual_sdk_whole_capture_validates_without_a_native_positive(sdk_actual):
    case, capture, result, directory = sdk_actual
    assert guard.validate_capture(case, capture, result, native=False,
        approved_sdk_root=SDK_SOURCE_ROOT, directory=directory) is True


@pytest.mark.parametrize("field", ["provider", "calls", "snapshots"])
def test_sdk_whole_common_result_cannot_drop_a_field(sdk_actual, field):
    case, _, original, _ = sdk_actual
    result = deepcopy(original)
    del result[field]
    with pytest.raises(ValueError):
        guard.validate_result(case, result)


@pytest.mark.parametrize("field", sorted(guard.FORGET_FIELDS))
def test_sdk_whole_original_forget_report_cannot_drop_a_field(sdk_actual, field):
    case, _, original, _ = sdk_actual
    result = deepcopy(original)
    report = next(call["outcome"]["result"] for call in result["calls"].values()
                  if call["operation"] == "forget" and call["outcome"]["status"] == "fulfilled")
    del report[field]
    with pytest.raises(ValueError):
        guard.validate_result(case, result)


def test_sdk_actual_callable_identity_includes_original_code_location(sdk_actual):
    _, capture, _, _ = sdk_actual
    for process in capture["observation"]["processes"]:
        owners = process["observation"]["codeOwners"]
        identities = [(row["name"], row["code"]["file"], row["code"]["qualname"],
                       row["code"]["firstLine"], row["code"]["bytecodeSha256"]) for row in owners]
        assert len(identities) == len(set(identities))


def _labelled_codec_event():
    """Pure codec data, never an original-engine fixture or acceptance packet."""
    return {"event": "labelled-codec-test", "sequence": 1, "pid": 11, "threadId": 0,
        "numbers": {"integer": 1, "float": 1.0, "boolean": True, "false": False,
                    "negativeZero": -0.0, "largeInteger": 9007199254740993, "fraction": 0.125},
        "whole": {"bytesHex": "00017f80ff" * 40, "v8Hex": "ff0f5f", "timestamp": 1794614400000,
                  "text": "Unicode: 雪 \u2028 \u2029; escaped newline:\n", "warnings": [404, 0, False],
                  "ordered": [3, 1, 2, {"z": "last-key-first", "a": "first-key-last"}]}}


def _codec_raw(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf8")


def _codec_frame(raw, compressed=None):
    if compressed is None:
        compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        compressed = compressor.compress(raw) + compressor.flush()
    return {"codec": "deflate-raw-native-event-v1", "rawBytes": len(raw),
            "rawSha256": hashlib.sha256(raw).hexdigest(),
            "dataBase64": base64.b64encode(compressed).decode("ascii")}


def _codec_line(frame):
    return json.dumps(frame, separators=(",", ":"))


def test_native_event_codec_preserves_whole_nested_json_types_bytes_and_order():
    original = _labelled_codec_event()
    raw = _codec_raw(original)
    assert b"\n" not in raw and b"\r" not in raw
    decoded = guard._decode_native_event_line(_codec_line(_codec_frame(raw)))
    assert guard._decode_native_event_line(_codec_line(_codec_frame(raw)), maximum_raw_bytes=len(raw)) == original
    assert decoded == original and list(decoded) == list(original)
    assert list(decoded["whole"]["ordered"][-1]) == ["z", "a"]
    assert type(decoded["numbers"]["integer"]) is int
    assert type(decoded["numbers"]["float"]) is float
    assert type(decoded["numbers"]["boolean"]) is bool
    assert type(decoded["numbers"]["false"]) is bool
    assert decoded["whole"]["bytesHex"] == original["whole"]["bytesHex"]
    assert decoded["numbers"]["largeInteger"] == 9007199254740993
    assert math.copysign(1.0, decoded["numbers"]["negativeZero"]) == -1.0
    assert decoded["whole"]["text"] == original["whole"]["text"]


@pytest.mark.parametrize("attack", [
    "codec", "extra-field", "missing-field", "length-short", "length-long", "length-bool",
    "length-float", "length-negative", "length-nonfinite", "sha", "uppercase-sha", "base64-invalid",
    "base64-whitespace", "base64-extra-padding",
])
def test_native_event_codec_requires_exact_frame_fields_and_byte_seals(attack):
    frame = _codec_frame(_codec_raw(_labelled_codec_event()))
    if attack == "codec":
        frame["codec"] = "labelled-unapproved-codec"
    elif attack == "extra-field":
        frame["normalized"] = True
    elif attack == "missing-field":
        del frame["dataBase64"]
    elif attack == "length-short":
        frame["rawBytes"] -= 1
    elif attack == "length-long":
        frame["rawBytes"] += 1
    elif attack == "length-bool":
        frame["rawBytes"] = True
    elif attack == "length-float":
        frame["rawBytes"] = float(frame["rawBytes"])
    elif attack == "length-negative":
        frame["rawBytes"] = -1
    elif attack == "length-nonfinite":
        frame["rawBytes"] = float("nan")
    elif attack == "sha":
        frame["rawSha256"] = "0" * 64
    elif attack == "uppercase-sha":
        frame["rawSha256"] = frame["rawSha256"].upper()
    elif attack == "base64-invalid":
        frame["dataBase64"] = "!" + frame["dataBase64"][1:]
    elif attack == "base64-whitespace":
        frame["dataBase64"] += " "
    else:
        frame["dataBase64"] += "===="
    with pytest.raises(ValueError):
        guard._decode_native_event_line(_codec_line(frame))


def test_native_event_codec_rejects_noncanonical_base64_with_identical_decoded_bytes():
    for ordinal in range(10):
        frame = _codec_frame(_codec_raw({"event": "labelled-codec-test", "padding": "x" * ordinal}))
        if frame["dataBase64"].endswith("="):
            break
    encoded = frame["dataBase64"]
    assert encoded.endswith("=")
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    position = len(encoded.rstrip("=")) - 1
    index = alphabet.index(encoded[position])
    changed = encoded[:position] + alphabet[index | 1] + encoded[position + 1:]
    assert changed != encoded
    assert base64.b64decode(changed, validate=True) == base64.b64decode(encoded, validate=True)
    frame["dataBase64"] = changed
    with pytest.raises(ValueError):
        guard._decode_native_event_line(_codec_line(frame))


@pytest.mark.parametrize("attack", ["truncated", "unfinished", "trailing-bytes", "second-member", "zlib-wrapper"])
def test_native_event_codec_requires_exactly_one_complete_raw_deflate_stream(attack):
    raw = _codec_raw(_labelled_codec_event())
    frame = _codec_frame(raw)
    compressed = base64.b64decode(frame["dataBase64"])
    if attack == "truncated":
        compressed = compressed[:-1]
    elif attack == "unfinished":
        compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        compressed = compressor.compress(raw) + compressor.flush(zlib.Z_SYNC_FLUSH)
    elif attack == "trailing-bytes":
        compressed += b"labelled-trailing-bytes"
    elif attack == "second-member":
        compressed += compressed
    else:
        compressed = zlib.compress(raw)
    frame["dataBase64"] = base64.b64encode(compressed).decode("ascii")
    with pytest.raises(ValueError):
        guard._decode_native_event_line(_codec_line(frame))


@pytest.mark.parametrize("raw", [
    b'{"event":"labelled-codec-test","same":1,"same":2}',
    b'{"event":"labelled-codec-test","nested":{"same":1,"same":2}}',
    b'{"event":"labelled-codec-test","number":NaN}',
    b'{"event":"labelled-codec-test","number":Infinity}',
    b'{"event":"labelled-codec-test","number":-Infinity}',
    b'{"event":"labelled-codec-test","number":1e999}',
    b'{"event":"labelled-codec-test","utf8":"\xff"}',
    b'{"event":"labelled-codec-test"}\n', b'{\n"event":"labelled-codec-test"}',
    b'{"event":"labelled-codec-test"}\r', b'{"event":"labelled-codec-test"} {}',
    b'[]', b'null', b'true', b'1', b'"labelled-codec-test"', b'',
])
def test_native_event_codec_rejects_invalid_or_lossy_original_json(raw):
    with pytest.raises(ValueError):
        guard._decode_native_event_line(_codec_line(_codec_frame(raw)))


def test_native_event_codec_rejects_duplicate_frame_members_and_literal_wire_newlines():
    frame = _codec_frame(_codec_raw(_labelled_codec_event()))
    line = _codec_line(frame)
    changed = line[:-1] + ',"rawBytes":' + str(frame["rawBytes"]) + "}"
    for wire in (changed, line + "\n", line + "\r"):
        with pytest.raises(ValueError):
            guard._decode_native_event_line(wire)


@pytest.mark.parametrize("forged_length", [False, True])
def test_native_event_codec_bounds_decompression_even_with_a_forged_small_length(forged_length):
    raw = _codec_raw({"event": "labelled-codec-test", "compressedBytes": "x" * (1024 * 1024)})
    frame = _codec_frame(raw)
    if forged_length:
        frame["rawBytes"] = 32
    with pytest.raises(ValueError):
        guard._decode_native_event_line(_codec_line(frame), maximum_raw_bytes=1024)


def test_native_event_codec_legacy_plain_json_requires_explicit_opt_in():
    original = _labelled_codec_event()
    line = _codec_raw(original).decode("utf8")
    with pytest.raises(ValueError):
        guard._decode_native_event_line(line)
    assert guard._decode_native_event_line(line, allow_plain=True) == original
    for value in ({}, {"event": None}, {"event": 1}, []):
        with pytest.raises(ValueError):
            guard._decode_native_event_line(_codec_raw(value).decode("utf8"), allow_plain=True)


def test_native_event_files_keep_wire_bytes_and_bound_total_decoded_bytes(tmp_path):
    directory = tmp_path / "native"
    evidence = directory / "evidence"
    evidence.mkdir(parents=True)
    originals = [_labelled_codec_event(), {"event": "labelled-codec-test", "pid": 12, "threadId": 1,
                 "sequence": 1, "payload": "x" * 200}]
    raws = [_codec_raw(event) for event in originals]
    paths = [evidence / "11-0-events.jsonl", evidence / "12-1-events.jsonl"]
    wires = [(_codec_line(_codec_frame(raw)) + "\n").encode("utf8") for raw in raws]
    for path, wire in zip(paths, wires, strict=True):
        path.write_bytes(wire)
    decoded = guard._read_native_event_files(directory)
    assert [row["path"] for row in decoded] == paths
    for row, original, raw, wire in zip(decoded, originals, raws, wires, strict=True):
        assert set(row) == {"path", "events", "wireBytes", "decodedBytes"}
        assert row["events"] == [original] and row["wireBytes"] == len(wire) and row["decodedBytes"] == len(raw)
    assert all(len(raw) < sum(map(len, raws)) - 1 for raw in raws)
    assert guard._read_native_event_files(directory, maximum_decoded_bytes=sum(map(len, raws))) == decoded
    with pytest.raises(ValueError):
        guard._read_native_event_files(directory, maximum_decoded_bytes=sum(map(len, raws)) - 1)


@pytest.mark.parametrize("ending", [b"", b"\r\n", b"\n\n"])
def test_native_event_files_reject_partial_or_ambiguous_jsonl_records(tmp_path, ending):
    evidence = tmp_path / "native/evidence"
    evidence.mkdir(parents=True)
    line = _codec_line(_codec_frame(_codec_raw(_labelled_codec_event()))).encode("utf8")
    (evidence / "11-0-events.jsonl").write_bytes(line + ending)
    with pytest.raises(ValueError):
        guard._read_native_event_files(evidence.parent)


def test_native_event_files_legacy_plain_payloads_never_fall_back_implicitly(tmp_path):
    evidence = tmp_path / "native/evidence"
    evidence.mkdir(parents=True)
    raw = _codec_raw(_labelled_codec_event())
    (evidence / "11-0-events.jsonl").write_bytes(raw + b"\n")
    with pytest.raises(ValueError):
        guard._read_native_event_files(evidence.parent)
    decoded = guard._read_native_event_files(evidence.parent, allow_plain=True)
    assert decoded[0]["events"] == [_labelled_codec_event()]
    assert decoded[0]["decodedBytes"] == len(raw)


def test_native_event_files_reject_an_oversized_wire_before_decoding(tmp_path, monkeypatch):
    evidence = tmp_path / "native/evidence"
    evidence.mkdir(parents=True)
    with (evidence / "11-0-events.jsonl").open("wb") as handle:
        handle.truncate(64 * 1024 * 1024 + 1)
    monkeypatch.setattr(guard, "_decode_native_event_record", lambda *_args, **_kwargs: pytest.fail("Oversized wire entered decoding"))
    with pytest.raises(ValueError):
        guard._read_native_event_files(evidence.parent)


@lru_cache(maxsize=1)
def _native_map_context(case_id):
    """Read only genuine selected carriers; this subcheck awards no pair credit."""
    if CAPTURE_ROOT is None:
        pytest.skip("No explicitly selected Native Map packet; no acceptance credit")
    case = next(case for case in V2_CASES if case["id"] == case_id)
    directory = Path(CAPTURE_ROOT).resolve(strict=True) / case_id / "native"
    context, process = _read(directory / "context.json"), _read(directory / "process.json")
    request_path = Path(process["requestPath"])
    assert request_path.is_relative_to(directory) and process["requestSha256"] == guard._digest(request_path)
    guard._same(_read(request_path), {key: case[key] for key in ("id", "operation", "input")},
        "The selected Native Map carrier belongs to another frozen input")
    assert process["returncode"] == 0 and process["contextSha256"] == guard._digest(directory / "context.json")
    root, inventories = guard._release_inventory(context["runtime"])
    imports, selected, workers = {}, {}, {}

    def load_trace(pid, thread):
        if (pid, thread) in imports:
            return
        path = directory / "traces" / f"{pid}-{thread}.jsonl"
        guard._owned(path, directory)
        rows = [guard._json(line) for line in path.read_text(encoding="utf8").splitlines()]
        assert rows[0]["pid"] == pid and rows[0]["threadId"] == thread
        assert rows[0]["contextSha256"] == process["contextSha256"]
        release = [row for row in rows if row.get("kind") == "release"]
        for row in release:
            path = root / guard._relative(row["package"]) / guard._relative(row["path"])
            assert inventories[row["package"]][row["path"]] == row["sha256"] == guard._digest(path)
        imports[pid, thread] = {"loaded": {row["path"] for row in release if row["package"] == "node_modules/openclaw"},
                               "releaseImports": release}

    families = {"original-worker-reply-call": "original-worker-reply",
                "original-message-port-call": "original-message-port"}
    for path in sorted((directory / "evidence").glob("*-events.jsonl")):
        guard._owned(path, directory)
        with path.open("rb") as stream:
            for wire in stream:
                assert wire.endswith(b"\n")
                row = guard._decode_native_event_line(wire[:-1])
                if row["event"] == "original-worker-command-call" and row["workerThreadId"] > 0:
                    workers[row["pid"], row["workerRef"]] = row["workerThreadId"]
                family = families.get(row["event"])
                if family is None or family in selected:
                    continue
                message = row["message"]["privateJSON"]
                if not isinstance(message, dict) or not isinstance(message.get("value"), dict) or message["value"].get("kind") != "recall-metadata":
                    continue
                thread = row.get("workerThreadId", row["threadId"])
                if thread <= 0:
                    thread = workers.get((row["pid"], row.get("workerRef")), thread)
                for actual_thread in {row["threadId"], thread}:
                    load_trace(row["pid"], actual_thread)
                guard._native_clock_owner(row["sourceCaller"], row["originalStack"], context, imports, row["pid"])
                selected[family] = row, thread
                if len(selected) == len(families):
                    break
        if len(selected) == len(families):
            break
    assert selected, "The explicitly selected packet contains no genuine recall-metadata Map carrier"
    return case, directory, context, context["approvedNodeRuntime"], imports, selected


@pytest.fixture(scope="module", params=V2_CASES, ids=lambda case: case["id"])
def v2_native_maps_actual(request):
    return _native_map_context(request.param["id"])


def _actual_map_row(context, family):
    _, _, _, authority, imports, selected = context
    if family not in selected:
        pytest.skip("The actual selected source did not enter this Map transport family; no boundary credit")
    row, thread = selected[family]
    message_paths, argument_paths = guard._native_recall_map_paths(row, family, imports, thread)
    assert len(message_paths) == len(argument_paths) == 3
    for field, paths in (("message", message_paths), ("arguments", argument_paths)):
        guard._native_transport_value(row[field], authority, _trusted_node(), pid=row["pid"],
            thread=row["threadId"], map_paths=paths)
    message = guard._native_value(row["message"]["value"], authority, _trusted_node())
    arguments = guard._native_value(row["arguments"]["value"], authority, _trusted_node())
    guard._same(arguments[1 if family == "original-worker-reply" else 0], message,
        "The actual independent argument carrier must retain all three original Map entries")
    for path in message_paths:
        value = message
        for name in path:
            value = value[name]
        assert value["privateType"] == "Map" and isinstance(value["entries"], list)
    return row, thread, message_paths, argument_paths


@pytest.mark.parametrize("family", ["original-worker-reply", "original-message-port"])
def test_actual_native_recall_metadata_keeps_all_three_typed_maps(v2_native_maps_actual, family):
    _actual_map_row(v2_native_maps_actual, family)


@pytest.mark.parametrize("family", ["original-worker-reply", "original-message-port"])
@pytest.mark.parametrize("attack", ["source", "producer-module", "producer-thread", "default-map", "map-slot", "message-side", "argument-side"])
def test_actual_native_recall_maps_reject_unqualified_sources_slots_and_sideviews(v2_native_maps_actual, family, attack):
    _, _, _, authority, imports, _ = v2_native_maps_actual
    original, thread, message_paths, argument_paths = _actual_map_row(v2_native_maps_actual, family)
    row = deepcopy(original)
    changed_imports = dict(imports)
    if attack == "source":
        row["sourceCaller"]["path"] = "dist/labelled-unapproved-producer.mjs"
    elif attack == "producer-module":
        producer_thread = thread if family == "original-worker-reply" else row["threadId"]
        key = row["pid"], producer_thread
        changed_imports[key] = {**imports[key], "loaded": imports[key]["loaded"] - {"dist/manager-search-DgMs3pkc.mjs"}}
    elif attack == "producer-thread":
        if family == "original-worker-reply":
            thread += 100000
        else:
            row["threadId"] += 100000
    if attack in {"source", "producer-module", "producer-thread"}:
        with pytest.raises(ValueError):
            guard._native_recall_map_paths(row, family, changed_imports, thread)
        return
    field, paths = "message", message_paths
    if attack == "default-map":
        paths = ()
    elif attack == "map-slot":
        paths = (("value",),)
    elif attack == "message-side":
        row["message"]["privateJSON"]["value"]["rows"] = {"labelledTamper": True}
    else:
        field, paths = "arguments", argument_paths
        slot = 1 if family == "original-worker-reply" else 0
        row[field]["privateJSON"][slot]["value"]["sourceMtimes"]["memory"] = {"labelledTamper": True}
    with pytest.raises(ValueError):
        guard._native_transport_value(row[field], authority, _trusted_node(), pid=row["pid"],
            thread=row["threadId"], map_paths=paths)


def test_custody_cache_is_fresh_and_restores_outer_scope_after_structural_rejection(monkeypatch):
    """Cache protocol only; every attempted malformed capture is rejected."""
    original = guard.validate_result
    seen, global_keys = [], set(guard._V8_CACHE)
    outer = {"labelledProtocolOnly": "outer-context"}
    token = guard._VALIDATION_CACHE.set(outer)

    def observe_then_validate(*args):
        cache = guard._VALIDATION_CACHE.get()
        assert cache is not outer and set(cache) == {"sourceIndexes", "verifiedFiles", "terminated", "decoderAuthorities", "v8"}
        assert all(not values for values in cache.values())
        seen.append(cache)
        cache["v8"]["labelled-unused-cache-marker"] = "protocol-only"
        return original(*args)

    monkeypatch.setattr(guard, "validate_result", observe_then_validate)
    try:
        for native in (True, False):
            with pytest.raises(ValueError):
                guard.validate_capture(V2_CASES[0], {}, {}, native=native)
            assert guard._VALIDATION_CACHE.get() is outer
        assert len(seen) == 2 and seen[0] is not seen[1]
        assert set(guard._V8_CACHE) == global_keys
    finally:
        guard._VALIDATION_CACHE.reset(token)


@pytest.mark.parametrize("changed", [False, True])
def test_v2_cache_rechecks_labelled_temporary_source_before_return(v2_clock_actual, tmp_path, monkeypatch, changed):
    """A false protocol callback cannot award original-engine or pair credit."""
    case, raw, _, result, *_ = v2_clock_actual
    path = tmp_path / "labelled-cache-source.mjs"
    path.write_bytes(b"// labelled temporary source version one\n")
    previous = guard._VALIDATION_CACHE.get()
    seen = []

    def false_verification_callback(*_args):
        cache = guard._VALIDATION_CACHE.get()
        seen.append(cache)
        cache["verifiedFiles"][str(path)] = guard._digest(path)
        if changed:
            path.write_bytes(b"// labelled temporary source version two\n")
        return False

    monkeypatch.setattr(guard, "_native_capture", false_verification_callback)
    if changed:
        with pytest.raises(ValueError, match="changed during custody validation"):
            guard.validate_capture(case, raw, result, native=True)
    else:
        assert guard.validate_capture(case, raw, result, native=True) is False
    assert len(seen) == 1 and guard._VALIDATION_CACHE.get() is previous


@pytest.mark.parametrize("value", [None, 0, 1, "true", {}, []])
def test_replay_result_inclusion_requires_a_boolean_before_reading_any_packet(tmp_path, value):
    with pytest.raises(ValueError, match="explicit boolean opt-in"):
        guard.replay_case(V2_CASES[0], tmp_path / "unselected-native", tmp_path / "unselected-sdk", include_results=value)
