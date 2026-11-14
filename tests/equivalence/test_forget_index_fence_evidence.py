"""Replay only explicitly selected, genuine forget/index-fence packets.

Legacy SDK, V2, V3, and V4 packets have separate explicit selectors.
A failed Native transport cannot become a positive paired baseline. No test
launches an original engine or modifies a retained capture file.
"""
import base64
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import threading
import zlib

import pytest

from equivalence import forget_index_fence_evidence as guard
from equivalence.forget_index_fence import build_cases
from equivalence.forget_index_fence_v2 import build_cases as build_v2_cases
from equivalence.forget_index_fence_v3 import build_cases as build_v3_cases, validate_registration as validate_v3_registration
from equivalence.forget_index_fence_v4 import build_cases as build_v4_cases, validate_registration as validate_v4_registration
from equivalence.forget_index_fence_v5 import build_cases as build_v5_cases


ROOT = Path(__file__).resolve().parents[2]
CAPTURE_ROOT = os.environ.get("MEMORY_FORGET_INDEX_FENCE_CAPTURE_ROOT")
V3_CAPTURE_ROOT = os.environ.get("MEMORY_FORGET_INDEX_FENCE_V3_CAPTURE_ROOT")
V4_CAPTURE_ROOT = os.environ.get("MEMORY_FORGET_INDEX_FENCE_V4_CAPTURE_ROOT")
V3_REJECTED_NATIVE_RELEASE_ROOT = os.environ.get("MEMORY_FORGET_INDEX_FENCE_V3_REJECTED_NATIVE_RELEASE_ROOT")
ADAPTER_ROOT = os.environ.get("MEMORY_FORGET_INDEX_FENCE_ADAPTER_ROOT")
SDK_CAPTURE_ROOT = os.environ.get("MEMORY_FORGET_INDEX_FENCE_SDK_CAPTURE_ROOT")
REJECTED_NATIVE_CAPTURE_ROOT = os.environ.get("MEMORY_FORGET_INDEX_FENCE_REJECTED_NATIVE_ROOT")
REJECTED_RELEASE_CAPTURE_ROOT = os.environ.get("MEMORY_FORGET_INDEX_FENCE_REJECTED_RELEASE_ROOT")
SDK_SOURCE_ROOT = Path(os.environ.get("MEMORY_FORGET_INDEX_FENCE_SDK_SOURCE_ROOT", ROOT)).resolve()
REFERENCE_ROOT = Path(os.environ.get("MEMORY_FORGET_INDEX_FENCE_REFERENCE_ROOT", ROOT / "work/openclaw-v2026.9.9")).resolve()
CASES = build_cases()
V2_CASES = build_v2_cases()
V3_CASES = build_v3_cases()
V4_CASES = build_v4_cases()


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


@pytest.mark.parametrize("attack", ["offset", "coherent-earlier-offset", "coherent-later-offset", "sha", "boundary-receipt-omission", "late-write"])
def test_actual_native_killed_snapshot_requires_exact_ram_prefix_and_read_only_tail(v2_clock_actual, attack):
    case, raw, *_ = v2_clock_actual
    if not any(child["exit"] == {"code": None, "signal": "SIGKILL"} for child in raw["children"]):
        pytest.skip("The actual selected original was not killed; no crash-prefix boundary credit")
    _, original_actors, execution, authority, imports, original_passive = _native_clock_context(case["id"])
    pid, (child, original) = next((pid, values) for pid, values in original_actors.items()
                                if values[0]["exit"] == {"code": None, "signal": "SIGKILL"})
    channels = deepcopy(original["passiveChannels"])
    channel = next(row for row in channels if row["pid"] == pid and row["threadId"] == 0)
    passive = {key: list(rows) for key, rows in original_passive.items()}
    if attack == "offset":
        channel["publishedBytes"] += 1
    elif attack in {"coherent-earlier-offset", "coherent-later-offset"}:
        path = Path(raw["fixtureBase"]).parent / "evidence" / f"{pid}-0-events.jsonl"
        wire = path.read_bytes()
        boundary = channel["publishedBytes"]
        if attack == "coherent-earlier-offset":
            changed = wire.rfind(b"\n", 0, boundary - 1) + 1
            assert 0 < changed < boundary
        else:
            changed = wire.find(b"\n", boundary) + 1
            assert boundary < changed <= len(wire)
        channel["publishedBytes"] = changed
        channel["sha256"] = hashlib.sha256(wire[:changed]).hexdigest()
    elif attack == "sha":
        channel["sha256"] = "0" * 64
    elif attack == "boundary-receipt-omission":
        channels.remove(channel)
    else:
        path = Path(raw["fixtureBase"]).parent / "evidence" / f"{pid}-0-events.jsonl"
        prefix = path.read_bytes()[:channel["publishedBytes"]]
        last = guard._decode_native_event_line(prefix[:-1].rsplit(b"\n", 1)[-1])
        selected = next(((number, row) for number, row in enumerate(passive[pid, 0])
                         if row["event"] == "source-clock-read" and row["sequence"] > last["sequence"]), None)
        if selected is None:
            pytest.skip("The actual killed original has no late read to mutate; no late-read boundary credit")
        number, row = selected
        passive[pid, 0][number] = {**row, "event": "source-clock-deletion"}
    actor = {**original, "passiveChannels": channels}
    actors = {**original_actors, pid: (child, actor)}
    with pytest.raises(ValueError, match="post-marker mutations" if attack == "late-write" else None):
        guard._native_source_clock_v2(case, raw, actors, imports, passive, execution, authority, _trusted_node())


def _sdk_unscoped_read_context(actual, version):
    case, _, sdk, *_ = actual
    for process in sdk["observation"]["processes"]:
        observation = process["observation"]
        if not any(row["scope"] is None for row in observation["sourceClockReads"]):
            continue
        recorded, trusted, events, returns = guard._sdk_observation(observation, process, case["input"], SDK_SOURCE_ROOT)
        context = case, sdk, process, observation, recorded, trusted, events, returns
        proof = _validate_sdk_clock(context, observation)
        for number, row in enumerate(observation["sourceClockReads"]):
            if row["scope"] is not None:
                continue
            returned = row["returned"]
            raw = row["arguments"]["raw"]["bytesHex"]
            initial = case["input"]["initialFiles"].get(returned["path"])
            initial_match = isinstance(initial, str) and initial.encode("utf8").hex() == raw and returned["mtime"] == case["input"]["clock"]["initialSourceMtimeMs"]
            committed = any(item["path"] == row["arguments"]["file"]["abs_path"] and item["bytes"] == raw
                            and item["mtimeNs"] == returned["mtime"] * 1_000_000
                            and int(item["atNs"]) < int(row["atNs"]) for item in proof["commits"])
            if (version == "initial" and initial_match) or (version == "commit" and committed):
                return context, number, proof
    pytest.skip("The actual selected SDK original did not perform this unscoped source-version read; no version boundary credit")


@pytest.mark.parametrize("version", ["initial", "commit"])
def test_actual_sdk_unscoped_read_preserves_absent_public_call_lineage(v2_clock_actual, version):
    context, number, proof = _sdk_unscoped_read_context(v2_clock_actual, version)
    row = context[3]["sourceClockReads"][number]
    summary = next(item for item in proof["reads"] if item["atNs"] == row["atNs"])
    assert row["scope"] is None and summary["callKey"] is None and summary["enteredAtNs"] is None
    assert summary["finishedAtNs"] == row["atNs"]


@pytest.mark.parametrize("version", ["initial", "commit"])
@pytest.mark.parametrize("attack", ["source", "hash", "mtime", "path", "version-bytes", "stat-size", "source-kind"])
def test_actual_sdk_unscoped_read_requires_verified_source_bytes_and_version(v2_clock_actual, version, attack):
    context, number, _ = _sdk_unscoped_read_context(v2_clock_actual, version)
    original = context[3]
    rows = list(original["sourceClockReads"])
    row = deepcopy(rows[number])
    rows[number] = row
    if attack == "source":
        row["sourceCode"]["sourceSha256"] = "0" * 64
    elif attack == "hash":
        row["returned"]["hash"] = "0" * 64
    elif attack == "mtime":
        row["returned"]["mtime"] += 1000
    elif attack == "path":
        row["arguments"]["file"]["abs_path"] = str(Path(context[1]["request"]["directory"]) / "labelled-unowned.md")
    elif attack == "version-bytes":
        raw = row["arguments"]["raw"]
        payload = bytes.fromhex(raw["bytesHex"])
        assert payload and payload[0] < 128
        changed = bytes([payload[0] ^ 1]) + payload[1:]
        raw["bytesHex"] = changed.hex()
        row["arguments"]["text"] = row["returned"]["text"] = changed.decode("utf8")
        row["returned"]["hash"] = hashlib.sha256(changed).hexdigest()
    elif attack == "stat-size":
        row["arguments"]["info"][6] += 1
    else:
        row["arguments"]["file"]["source"] = "sessions"
    with pytest.raises(ValueError):
        _validate_sdk_clock(context, {**original, "sourceClockReads": rows})


@pytest.mark.parametrize("kind", ["write", "datetime"])
def test_actual_sdk_unscoped_read_policy_never_extends_to_writes_or_datetime(v2_clock_actual, kind):
    context = _sdk_clock_context(v2_clock_actual, require_receipt=kind == "write", require_datetime=kind == "datetime")
    original = context[3]
    field = "sourceClockOriginalIO" if kind == "write" else "datetimeClockCalls"
    rows = list(original[field])
    selected = next(((number, row) for number, row in enumerate(rows) if isinstance(row.get("scope"), dict)), None)
    assert selected is not None
    number, actual = selected
    row = deepcopy(actual)
    assert isinstance(row["scope"], dict)
    row["scope"] = None
    rows[number] = row
    with pytest.raises(ValueError, match="public-call scope"):
        _validate_sdk_clock(context, {**original, field: rows})


@lru_cache(maxsize=1)
def _v3_raw_packet(case_id):
    if V3_CAPTURE_ROOT is None:
        pytest.skip("No explicitly selected V3 packet; no acceptance credit")
    assert ADAPTER_ROOT is not None, "Selected V3 replay requires an independently selected adapter root"
    assert Path(ADAPTER_ROOT).resolve(strict=True).is_dir()
    case = next(case for case in V3_CASES if case["id"] == case_id)
    directory = Path(V3_CAPTURE_ROOT).resolve(strict=True) / case_id
    native_directory, sdk_directory = directory / "native", directory / "sdk/evidence"
    native_path, sdk_path = native_directory / "evidence/native-raw.json", sdk_directory / "python-raw.json"
    assert native_path.is_file() and sdk_path.is_file(), f"The explicitly selected V3 packet is incomplete: {directory}"
    native_values, sdk_values = _read(native_path), _read(sdk_path)
    assert isinstance(native_values, list) and len(native_values) == 1
    assert isinstance(sdk_values, list) and len(sdk_values) == 1
    returned = _read(native_directory / "stdout.json")
    assert returned["id"] == case_id and returned["ok"] is True
    native, sdk = native_values[0], sdk_values[0]
    return case, native, sdk, returned["result"], sdk["observation"]["result"], native_directory, sdk_directory


@pytest.fixture(scope="module", params=V3_CASES, ids=lambda case: case["id"])
def v3_raw_actual(request):
    """Raw structure alone supplies no engine, barrier, or acceptance credit."""
    return _v3_raw_packet(request.param["id"])


def test_v3_selected_raw_retains_both_independent_original_inputs(v3_raw_actual):
    case, native, sdk, native_result, sdk_result, *_ = v3_raw_actual
    guard._same(native["input"], case["input"], "Native V3 raw must retain the whole frozen independent input")
    guard._same(sdk["input"], case["input"], "SDK V3 raw must retain the whole frozen independent input")
    guard._same(native["result"], native_result, "Native V3 raw must retain its whole original common result")
    guard._same(sdk["observation"]["result"], sdk_result, "SDK V3 raw must retain its whole original common result")


def test_v3_actual_pair_requires_complete_independent_custody(v3_raw_actual):
    """Genuine disagreement is retained; either invalid engine blocks custody."""
    case, native, sdk, native_result, sdk_result, native_directory, sdk_directory = v3_raw_actual
    assert guard.validate_pair(case, native, sdk, native_result, sdk_result,
        approved_node=_trusted_node(), approved_sdk_root=SDK_SOURCE_ROOT,
        approved_reference=REFERENCE_ROOT, approved_adapter_root=Path(ADAPTER_ROOT).resolve(strict=True),
        native_directory=native_directory, sdk_directory=sdk_directory) is True


@lru_cache(maxsize=1)
def _v3_sdk_packet(case_id):
    values = _v3_raw_packet(case_id)
    case, _, sdk, _, result, _, directory = values
    assert guard.validate_capture(case, sdk, result, native=False, approved_sdk_root=SDK_SOURCE_ROOT,
        approved_adapter_root=Path(ADAPTER_ROOT).resolve(strict=True), directory=directory) is True
    return values


@pytest.fixture(scope="module", params=V3_CASES, ids=lambda case: case["id"])
def v3_sdk_actual(request):
    """A genuine SDK proof is independent of a rejected Native transport."""
    return _v3_sdk_packet(request.param["id"])


def test_actual_v3_sdk_public_capture_validates_without_a_native_positive(v3_sdk_actual):
    case, _, sdk, _, result, _, directory = v3_sdk_actual
    assert sdk["observation"]["complete"] is True and directory.name == "evidence"
    assert set(result["calls"]) == set(guard._expected_calls(case["input"]))


def _v3_sdk_observation_context(actual):
    case, _, sdk, *_ = actual
    raw = sdk["observation"]
    roots = guard._adapter_inventory(raw["adapterProvenanceBefore"], Path(ADAPTER_ROOT).resolve(strict=True))
    process = next(process for process in raw["processes"] if process["observation"]["ownerBindings"])
    observation = process["observation"]
    recorded, trusted, events, returns = guard._sdk_observation(observation, process, case["input"],
        SDK_SOURCE_ROOT, adapter_roots=roots)
    return case, process, observation, recorded, trusted, roots, events, returns


@pytest.mark.parametrize("attack", ["frame", "code", "receiver"])
def test_v3_sdk_original_method_return_requires_its_retained_entry(v3_sdk_actual, attack):
    case, process, original, _, _, roots, events, returns = _v3_sdk_observation_context(v3_sdk_actual)
    call = next(row for row in events.values() if row["event"] == "original-call" and row["name"] == "MemorySearchTool.execute")
    row = deepcopy(returns[call["sequence"]])
    lookup = row["returnLookup"]
    if attack == "frame":
        lookup["frameObjectId"] = next(item["frameObjectId"] for item in events.values()
            if item["event"] == "original-call" and item["frameObjectId"] != call["frameObjectId"])
    elif attack == "code":
        lookup["entryCode"]["sourceSha256"] = "0" * 64
    else:
        lookup["entryReceiverObjectId"] = next(item["receiverObjectId"] for item in events.values()
            if item["event"] == "original-call" and item["receiverObjectId"] is not None
            and item["receiverObjectId"] != call["receiverObjectId"])
    observation = {**original, "originalCalls": [row if item["sequence"] == row["sequence"] else item
                                               for item in original["originalCalls"]]}
    with pytest.raises(ValueError):
        guard._sdk_observation(observation, process, case["input"], SDK_SOURCE_ROOT, adapter_roots=roots)


@pytest.mark.parametrize("attack", ["callable-role", "present", "receiver"])
def test_v3_sdk_declared_predicate_must_match_the_actual_effective_callable(v3_sdk_actual, attack):
    case, process, original, _, _, roots, *_ = _v3_sdk_observation_context(v3_sdk_actual)
    owners = list(original["ownerBindings"])
    owner = deepcopy(owners[0])
    owners[0] = owner
    effective = owner["effectiveForgottenCallback"]
    if attack == "callable-role":
        if owner["forgottenCallback"]:
            effective["callable"]["module"] = "memory_core.index.sqlite_store"
            effective["callable"]["qualname"] = "SQLiteMemoryStore.is_session_forgotten"
        else:
            effective["callable"]["module"] = "equivalence.forget_index_fence_sdk"
            effective["callable"]["qualname"] = "_SdkActor.acquire.<locals>.<lambda>"
    elif attack == "present":
        effective["present"] = not effective["present"]
    else:
        effective["boundReceiverObjectId"] = owner["storeObjectId"] if effective["boundReceiverObjectId"] is None else None
    with pytest.raises(ValueError):
        guard._sdk_observation({**original, "ownerBindings": owners}, process, case["input"],
            SDK_SOURCE_ROOT, adapter_roots=roots)


@pytest.mark.parametrize("attack", ["outside-root", "other-approved-module"])
def test_v3_sdk_main_import_alias_is_limited_to_the_actual_cli(v3_sdk_actual, attack):
    case, process, original, _, _, roots, *_ = _v3_sdk_observation_context(v3_sdk_actual)
    modules = list(original["loadedFixtureModules"])
    number, actual = next((number, row) for number, row in enumerate(modules) if row["module"] == "__main__")
    row = dict(actual)
    modules[number] = row
    if attack == "outside-root":
        row["path"] = str(roots[0].parent / "labelled-other-tree/equivalence/forget_index_fence_sdk_cli.py")
    else:
        target = next(item for item in modules if item["module"] == "equivalence.forget_index_fence_sdk")
        row["path"], row["sha256"] = target["path"], target["sha256"]
    with pytest.raises(ValueError):
        guard._sdk_observation({**original, "loadedFixtureModules": modules}, process, case["input"],
            SDK_SOURCE_ROOT, adapter_roots=roots)


def test_actual_v3_rejected_native_release_never_becomes_a_positive_capture():
    if V3_REJECTED_NATIVE_RELEASE_ROOT is None:
        pytest.skip("No explicitly selected rejected V3 Native release packet; no acceptance credit")
    assert ADAPTER_ROOT is not None, "Rejected V3 replay requires an independently selected adapter root"
    case = V3_CASES[0]
    directory = Path(V3_REJECTED_NATIVE_RELEASE_ROOT).resolve(strict=True) / case["id"] / "native"
    values, returned = _read(directory / "evidence/native-raw.json"), _read(directory / "stdout.json")
    assert isinstance(values, list) and len(values) == 1
    assert returned["id"] == case["id"] and returned["ok"] is True
    with pytest.raises(ValueError, match="release"):
        guard.validate_capture(case, values[0], returned["result"], native=True, approved_node=_trusted_node(),
            approved_reference=REFERENCE_ROOT, approved_adapter_root=Path(ADAPTER_ROOT).resolve(strict=True),
            directory=directory)


def test_v3_capture_selector_never_borrows_a_v2_packet(tmp_path, monkeypatch):
    monkeypatch.setitem(globals(), "V3_CAPTURE_ROOT", None)
    monkeypatch.setitem(globals(), "CAPTURE_ROOT", str(tmp_path / "labelled-v2-only"))
    with pytest.raises(pytest.skip.Exception, match="No explicitly selected V3 packet"):
        _v3_raw_packet.__wrapped__(V3_CASES[0]["id"])


@pytest.mark.parametrize("case", V3_CASES, ids=lambda case: case["id"])
def test_v3_literal_barriers_bind_search_settlement_and_declared_dependencies(case):
    value = case["input"]
    policy = value["observationPolicy"]["searchEffects"]
    assert policy["protocol"] == "original-search-effects-v3"
    assert policy["placement"]["captureAndCloseRequiresSettledPriorSearchEffects"] is True
    deferred = {(row["actor"], row["label"]): row["after"] for row in policy["placement"]["deferredSearches"]}
    settled, pending, joined = {}, set(), set()
    for number, step in enumerate(value["steps"]):
        operation = step["operation"]
        key = step.get("actor", "foreground"), step.get("label")
        if operation == "start-public-memory-search":
            assert key not in pending and key not in settled
            pending.add(key)
        elif operation in {"public-memory-search", "await-public-call"}:
            assert key[1] in value["queries"] and key not in settled
            if operation == "await-public-call":
                assert key in pending
                pending.remove(key)
            settled[key] = number
        elif operation == "await-original-search-effects":
            assert set(step) == {"operation", "actor", "label"}
            assert key in settled and key not in joined
            after = deferred.get(key)
            if after is None:
                assert number == settled[key] + 1
            else:
                prior = value["steps"][number - 1]
                assert all(prior.get(name) == expected for name, expected in after.items())
                assert number - 1 > settled[key]
            joined.add(key)
        elif operation == "capture-physical-state":
            # A search still held before its actual await settlement is pending.
            assert set(settled) <= joined
        elif operation == "original-owner-close":
            assert all(item in joined for item in settled if item[0] == key[0])
    assert not pending and set(settled) == joined and set(deferred) <= joined


def test_v3_closed_family_never_credits_legacy_v2_cases():
    with pytest.raises(ValueError):
        validate_v3_registration(V2_CASES)


def _v3_schema_only_counterexample(case):
    """Deliberately non-evidence: no engine return, state, or job count is claimed."""
    calls = {}
    for key, (kind, label, _) in guard._expected_calls(case["input"]).items():
        outcome = ({"status": "rejected", "isTypedConflict": False} if kind == "sync" else
                   {"status": "rejected", "error": {"message": "Labelled schema-only negative; never original output"}})
        calls[key] = {"operation": kind, "label": label, "outcome": outcome}
    stages = {}
    for step in case["input"]["steps"]:
        if step["operation"] == "capture-physical-state":
            stages[step["label"]] = {"documents": [], "origins": [], "tombstones": [], "recall": None,
                "phaseSignals": None, "ingestion": None, "preimages": None, "sessions": {"facts": [], "admission": []},
                "index": [], "events": [], "concurrency": {"markerVisible": None, "forgetSettled": None, "oldBuildSettled": None}}
    return {"provider": "none", "calls": calls, "snapshots": stages}


@pytest.mark.parametrize("case", V3_CASES, ids=lambda case: case["id"])
@pytest.mark.parametrize("native", [False, True])
def test_v3_schema_only_counterexample_never_supplies_capture_custody(case, native):
    result = _v3_schema_only_counterexample(case)
    assert guard.validate_result(case, result) is True  # Schema validation is not custody.
    with pytest.raises(ValueError):
        guard.validate_capture(case, {}, result, native=native)


ADAPTER_SOURCE_FILES = (
    "equivalence/forget_index_fence_sdk.py", "equivalence/forget_index_fence_sdk_cli.py",
    "equivalence/forget_index_fence_sdk_clock.py", "equivalence/forget_index_fence_v3.py",
    "docs/forget_index_fence_v3_literals.json", "docs/forget_index_fence_v3_plan.md",
)


def _source_only_adapter_identity(root):
    digest, rows = hashlib.sha256(), []
    for name in ADAPTER_SOURCE_FILES:
        data = (root / name).read_bytes()
        digest.update(name.encode() + b"\0" + data + b"\0")
        rows.append({"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    return {"root": str(root), "files": rows, "sourceSha256": digest.hexdigest()}


@pytest.fixture
def approved_adapter_source_copy(tmp_path):
    """Actual source bytes only; this fixture contains no execution evidence."""
    approved, recorded = tmp_path / "approved-adapter", tmp_path / "recorded-checkout"
    for name in ADAPTER_SOURCE_FILES:
        destination = approved / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / name).read_bytes())
    identity = _source_only_adapter_identity(approved)
    identity["root"] = str(recorded)
    return approved, recorded, identity


def test_v3_adapter_inventory_uses_independently_approved_canonical_bytes(approved_adapter_source_copy):
    approved, recorded, identity = approved_adapter_source_copy
    assert guard._adapter_inventory(identity, approved) == (recorded, approved)
    for name in ADAPTER_SOURCE_FILES:
        assert guard._adapter_path(recorded / name, recorded, approved) == approved / name


@pytest.mark.parametrize("attack", ["bytes", "missing", "duplicate", "order", "seal", "relative-root"])
def test_v3_adapter_inventory_rejects_tampered_bytes_or_complete_inventory(approved_adapter_source_copy, attack):
    approved, _, original = approved_adapter_source_copy
    identity = deepcopy(original)
    if attack == "bytes":
        target = approved / ADAPTER_SOURCE_FILES[0]
        target.write_bytes(target.read_bytes() + b"\n# labelled source-only substitution\n")
    elif attack == "missing":
        del identity["files"][0]
    elif attack == "duplicate":
        identity["files"].append(deepcopy(identity["files"][0]))
    elif attack == "order":
        identity["files"].reverse()
    elif attack == "seal":
        identity["sourceSha256"] = "0" * 64
    else:
        identity["root"] = "labelled-relative-root"
    with pytest.raises(ValueError):
        guard._adapter_inventory(identity, approved)


def test_v3_captured_adapter_root_cannot_select_its_own_authority(approved_adapter_source_copy, tmp_path):
    approved, _, _ = approved_adapter_source_copy
    attacker = tmp_path / "captured-arbitrary-root"
    for name in ADAPTER_SOURCE_FILES:
        target = attacker / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((approved / name).read_bytes())
    target = attacker / ADAPTER_SOURCE_FILES[0]
    target.write_bytes(target.read_bytes() + b"\n# labelled coherently sealed attacker tree\n")
    identity = _source_only_adapter_identity(attacker)
    for authority in (approved, None):
        with pytest.raises(ValueError):
            guard._adapter_inventory(identity, authority)


@pytest.mark.parametrize("path_kind", ["outside", "traversal", "production"])
def test_v3_adapter_owner_path_cannot_escape_the_declared_fixture_surface(approved_adapter_source_copy, path_kind):
    approved, recorded, _ = approved_adapter_source_copy
    paths = {"outside": recorded.parent / "other-checkout/equivalence/forget_index_fence_sdk.py",
             "traversal": recorded / "equivalence/../docs/forget_index_fence_v3_literals.json",
             "production": recorded / "memory_core/index/sqlite_store.py"}
    with pytest.raises(ValueError):
        guard._adapter_path(paths[path_kind], recorded, approved)


@pytest.mark.parametrize("kind", ["symbolic", "hardlink"])
def test_v3_adapter_source_must_be_an_independent_regular_file(approved_adapter_source_copy, tmp_path, kind):
    approved, _, identity = approved_adapter_source_copy
    path = approved / ADAPTER_SOURCE_FILES[0]
    backing = tmp_path / "labelled-temporary-backing.py"
    backing.write_bytes(path.read_bytes())
    path.unlink()
    if kind == "symbolic":
        path.symlink_to(backing)
    else:
        os.link(backing, path)
    with pytest.raises(ValueError):
        guard._adapter_inventory(identity, approved)


INSTALLED_WAIT_ROLES = {"ThreadPoolExecutor.submit": ThreadPoolExecutor.submit,
                        "Future.result": Future.result, "Condition.wait": threading.Condition.wait}


def _installed_wait_code(role):
    code = INSTALLED_WAIT_ROLES[role].__code__
    source = Path(code.co_filename).resolve(strict=True)
    return {"file": str(source), "qualname": code.co_qualname, "firstLine": code.co_firstlineno,
            "sourceSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "bytecodeSha256": hashlib.sha256(code.co_code).hexdigest()}


@pytest.mark.parametrize("role", INSTALLED_WAIT_ROLES)
def test_v3_wait_callable_owner_matches_the_actual_installed_standard_library(role):
    row = _installed_wait_code(role)
    assert guard._sdk_callable_owner(row, ROOT, ROOT, role=role) == Path(row["file"])


@pytest.mark.parametrize("role", INSTALLED_WAIT_ROLES)
@pytest.mark.parametrize("attack", ["role", "source", "source-sha", "bytecode"])
def test_v3_wait_callable_owner_rejects_source_role_and_bytecode_substitution(role, attack):
    row = _installed_wait_code(role)
    other = next(item for item in INSTALLED_WAIT_ROLES if item != role)
    if attack == "role":
        role = other
    elif attack == "source":
        row = _installed_wait_code(other)
    elif attack == "source-sha":
        row["sourceSha256"] = "0" * 64
    else:
        alternate = _installed_wait_code(other)["bytecodeSha256"]
        assert alternate != row["bytecodeSha256"]
        row["bytecodeSha256"] = alternate
    with pytest.raises(ValueError):
        guard._sdk_callable_owner(row, ROOT, ROOT, role=role)


def _v3_private_database_context(actual):
    context = _v3_sdk_observation_context(actual)
    _, _, observation, recorded, trusted, _, events, returns = context
    lookups = [row for row in events.values() if row["event"] == "original-call" and row["name"] == "_lease_for"]
    if not lookups:
        pytest.skip("The actual selected SDK has no producer lease acquisition; no lease boundary credit")
    assert guard._sdk_private_database_owners(observation, events, returns, recorded, trusted) is None
    return context, lookups


def _private_database_variants(context, changes):
    _, _, original, _, _, _, events, returns = context
    changed_events = {number: changes.get(number, row) for number, row in events.items()}
    changed_returns = {number: changes.get(row["sequence"], row) for number, row in returns.items()}
    observation = {**original, **{name: [changes.get(row["sequence"], row) for row in original[name]]
                                  for name in ("originalCalls", "sqlExecutions", "sqlStatements")}}
    return observation, changed_events, changed_returns


def test_actual_v3_sdk_private_databases_keep_their_original_lease_and_store_owners(v3_sdk_actual):
    _v3_private_database_context(v3_sdk_actual)


@pytest.mark.parametrize("attack", ["returned-owner", "returned-type", "returned-path", "index-argument", "later-receiver", "cached-owner"])
def test_v3_sdk_lease_lookup_and_later_calls_cannot_change_the_actual_owner(v3_sdk_actual, attack):
    context, lookups = _v3_private_database_context(v3_sdk_actual)
    _, _, original, recorded, trusted, _, events, returns = context
    store = original["ownerBindings"][0]
    changes = {}
    if attack in {"returned-owner", "returned-type", "returned-path", "cached-owner"}:
        if attack == "cached-owner" and len(lookups) < 2:
            pytest.skip("The actual selected original did not reuse its lease lookup; no cache-reuse credit")
        call = lookups[-1] if attack == "cached-owner" else lookups[0]
        row = deepcopy(returns[call["sequence"]])
        if attack in {"returned-owner", "cached-owner"}:
            row["returnedOwnerObjectId"] = store["storeObjectId"]
        elif attack == "returned-type":
            row["returnedOwnerType"]["name"] = "ManagedSQLiteMemoryStore"
        else:
            row["returned"]["path"] = store["storage"]["index"]
    elif attack == "index-argument":
        row = deepcopy(lookups[0])
        assert store["storage"]["catalog"] != row["arguments"]["index_path"]
        row["arguments"]["index_path"] = store["storage"]["catalog"]
    else:
        row = deepcopy(next(item for item in events.values() if item["event"] == "original-call"
                            and item["name"] == "_ReindexLease.try_acquire"))
        row["receiverObjectId"] = row["selfObjectId"] = store["storeObjectId"]
    changes[row["sequence"]] = row
    observation, changed_events, changed_returns = _private_database_variants(context, changes)
    with pytest.raises(ValueError):
        guard._sdk_private_database_owners(observation, changed_events, changed_returns, recorded, trusted)


@pytest.mark.parametrize("attack", ["database-path", "database-owner", "connection", "current-scope", "opening-scope"])
def test_v3_sdk_private_sql_cannot_borrow_another_owner_connection_or_scope(v3_sdk_actual, attack):
    context, _ = _v3_private_database_context(v3_sdk_actual)
    _, _, original, recorded, trusted, _, _, _ = context
    execution = next(row for row in original["sqlExecutions"] if row["source"] == "_ReindexLease._open_database")
    if attack in {"database-path", "database-owner", "connection"}:
        row = deepcopy(execution)
        store = original["ownerBindings"][0]
        if attack == "database-path":
            row["ownerDatabasePath"] = store["storage"]["index"]
        elif attack == "database-owner":
            row["databaseOwnerObjectId"] = store["storeObjectId"]
        else:
            row["connectionId"] = next(item["connectionId"] for item in original["sqlExecutions"]
                                        if item["connectionId"] != execution["connectionId"])
    else:
        statement = next(item for item in original["sqlStatements"]
                         if item.get("executionSequence") == execution["sequence"])
        row = deepcopy(statement)
        name = "callScope" if attack == "current-scope" else "connectionOpenedByScope"
        alternate = next((item["callScope"] for item in original["sqlExecutions"]
                          if item.get("callScope") != row[name]), None)
        if alternate is None:
            pytest.skip("The actual selected original exposed no different scope; no scope-substitution credit")
        row[name] = deepcopy(alternate)
    observation, changed_events, changed_returns = _private_database_variants(context, {row["sequence"]: row})
    with pytest.raises(ValueError):
        guard._sdk_private_database_owners(observation, changed_events, changed_returns, recorded, trusted)


def test_actual_v3_sdk_private_connection_can_keep_distinct_opening_and_current_scopes(v3_sdk_actual):
    context, _ = _v3_private_database_context(v3_sdk_actual)
    _, _, original, recorded, trusted, _, _, _ = context
    statements = [row for row in original["sqlStatements"] if row.get("source") in {
        "_ReindexLease._open_database", "SQLiteMemoryStore.is_session_forgotten"}
        and row.get("connectionOpenedByScope") != row.get("callScope")]
    if not statements:
        pytest.skip("The actual selected original did not expose an opening/current-scope handoff; no handoff credit")
    assert guard._sdk_private_database_owners(original, context[6], context[7], recorded, trusted) is None


@lru_cache(maxsize=1)
def _v4_raw_packet(case_id):
    if V4_CAPTURE_ROOT is None:
        pytest.skip("No explicitly selected V4 packet; no acceptance credit")
    assert ADAPTER_ROOT is not None, "Selected V4 replay requires an independently selected adapter root"
    directory = Path(V4_CAPTURE_ROOT).resolve(strict=True) / case_id
    native_directory, sdk_directory = directory / "native", directory / "sdk/evidence"
    native = _read(native_directory / "evidence/native-raw.json")
    sdk = _read(sdk_directory / "python-raw.json")
    returned = _read(native_directory / "stdout.json")
    assert len(native) == len(sdk) == 1 and returned["id"] == case_id and returned["ok"] is True
    case = next(case for case in V4_CASES if case["id"] == case_id)
    return case, native[0], sdk[0], returned["result"], sdk[0]["observation"]["result"], native_directory, sdk_directory


@pytest.fixture(scope="module", params=V4_CASES, ids=lambda case: case["id"])
def v4_raw_actual(request):
    return _v4_raw_packet(request.param["id"])


def test_actual_v4_pair_requires_complete_independent_custody(v4_raw_actual):
    case, native, sdk, native_result, sdk_result, native_directory, sdk_directory = v4_raw_actual
    assert guard.validate_pair(case, native, sdk, native_result, sdk_result,
        approved_node=_trusted_node(), approved_sdk_root=SDK_SOURCE_ROOT, approved_reference=REFERENCE_ROOT,
        approved_adapter_root=Path(ADAPTER_ROOT).resolve(strict=True),
        native_directory=native_directory, sdk_directory=sdk_directory) is True


@pytest.mark.parametrize("case", V4_CASES, ids=lambda case: case["id"])
def test_v4_changes_only_closed_identity_and_the_explicit_sync_profile(case):
    assert guard._case(case) == case["input"] and guard._version(case) == 4
    assert case["input"]["config"]["memory"]["search"]["sync"] == {
        "onSearch": True, "onSessionStart": False, "watch": False}
    assert guard._native_profile_key(case) == "forgetIndexFenceV3Profile"
    assert guard._native_bootstrap_prefix(case) == "forget-index-fence-v3"
    assert guard._capture_prefix(case) == "forget-index-fence-v4"
    prior = next(row for row in V3_CASES if row["id"] == case["id"].replace("-v4-", "-v3-", 1))
    comparable = deepcopy(case)
    comparable["id"], comparable["operation"] = prior["id"], prior["operation"]
    comparable["input"]["kind"], comparable["input"]["profile"] = prior["input"]["kind"], prior["input"]["profile"]
    del comparable["input"]["config"]["memory"]["search"]["sync"]
    guard._same(comparable, prior, "V4 must preserve all V3 business steps, clocks, barriers and comparison policies")


def test_v4_selector_and_closed_family_never_borrow_a_v3_packet(tmp_path, monkeypatch):
    monkeypatch.setitem(globals(), "V4_CAPTURE_ROOT", None)
    monkeypatch.setitem(globals(), "V3_CAPTURE_ROOT", str(tmp_path / "labelled-v3-only"))
    with pytest.raises(pytest.skip.Exception, match="No explicitly selected V4 packet"):
        _v4_raw_packet.__wrapped__(V4_CASES[0]["id"])
    with pytest.raises(ValueError):
        validate_v4_registration(V3_CASES)
    mixed = {**V4_CASES[0], "operation": "forget-index-fence-v3-runtime"}
    with pytest.raises(ValueError):
        guard._case(mixed)


V5_CAPTURE_ROOT = os.environ.get('MEMORY_FORGET_INDEX_FENCE_V5_CAPTURE_ROOT')
V5_SUITE_REPORT = os.environ.get('MEMORY_FORGET_INDEX_FENCE_V5_SUITE_REPORT')
V5_NATIVE_CAPTURE_ROOT = os.environ.get('MEMORY_FORGET_INDEX_FENCE_V5_NATIVE_CAPTURE_ROOT')
V5_SDK_CAPTURE_ROOT = os.environ.get('MEMORY_FORGET_INDEX_FENCE_V5_SDK_CAPTURE_ROOT')
V5_NATIVE_CAPTURE = os.environ.get('MEMORY_FORGET_INDEX_FENCE_V5_NATIVE_CAPTURE')
V5_CASES = build_v5_cases()


@lru_cache(maxsize=1)
def _v5_replay_cli():
    from importlib.util import module_from_spec, spec_from_file_location
    spec = spec_from_file_location("v5_guard_suite_admission", ROOT / "scripts/replay_forget_index_fence.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def _v5_suite_admission():
    from types import SimpleNamespace
    from equivalence import forget_index_fence_v5
    assert V5_SUITE_REPORT is not None and V5_CAPTURE_ROOT is None, "V5 suite and collector selectors are exclusive"
    assert V5_NATIVE_CAPTURE_ROOT is not None and V5_SDK_CAPTURE_ROOT is not None, "V5 suite replay requires both independently selected physical roots"
    assert ADAPTER_ROOT is not None, "V5 replay requires an independently selected adapter root"
    cli = _v5_replay_cli()
    args = SimpleNamespace(version="v5", suite_report=Path(V5_SUITE_REPORT),
        native_capture_root=Path(V5_NATIVE_CAPTURE_ROOT), sdk_capture_root=Path(V5_SDK_CAPTURE_ROOT),
        node=_trusted_node(), reference=REFERENCE_ROOT, sdk_source_root=SDK_SOURCE_ROOT,
        adapter_root=Path(ADAPTER_ROOT))
    authority = cli._authorities(args, guard, forget_index_fence_v5)
    selected, _, _ = cli._admit_suite_report(args, authority, {"sourceReports": []}, forget_index_fence_v5)
    return selected


@lru_cache(maxsize=1)
def _v5_raw_packet(case_id):
    assert not (V5_SUITE_REPORT is not None and V5_CAPTURE_ROOT is not None), "V5 suite and collector selectors are exclusive"
    if V5_SUITE_REPORT is None and V5_CAPTURE_ROOT is None:
        pytest.skip('No explicitly selected V5 packet; no acceptance credit')
    assert ADAPTER_ROOT is not None, 'V5 replay requires an independently selected adapter root'
    case = next(row for row in V5_CASES if row['id'] == case_id)
    selected = None
    if V5_SUITE_REPORT is not None:
        selected = _v5_suite_admission()[case_id]
        native_directory, sdk_directory = selected['directories']['native'], selected['directories']['sdk']
        assert all(_v5_replay_cli()._seal(item['path']) == item for item in selected['files'].values())
    else:
        assert V5_NATIVE_CAPTURE_ROOT is None and V5_SDK_CAPTURE_ROOT is None, "V5 physical suite roots require an explicit suite report"
        directory = Path(V5_CAPTURE_ROOT).resolve(strict=True) / case_id
        native_directory, sdk_directory = directory / 'native', directory / 'sdk/evidence'
    native, sdk = _read(native_directory / 'evidence/native-raw.json'), _read(sdk_directory / 'python-raw.json')
    returned = _read(native_directory / 'stdout.json')
    assert len(native) == len(sdk) == 1 and returned['id'] == case_id and returned['ok'] is True
    sdk_result = guard.materialize_sdk_dispatch(sdk[0])['observation']['result']
    if selected is not None:
        guard._same(returned['result'], selected['nativeResult'], "Whole suite Native payload differs from its actual stdout")
        guard._same(sdk_result, selected['sdkResult'], "Whole suite SDK payload differs from its actual original dispatch")
        assert all(_v5_replay_cli()._seal(item['path']) == item for item in selected['files'].values())
    return case, native[0], sdk[0], returned['result'], sdk_result, native_directory, sdk_directory


@pytest.mark.parametrize('case', V5_CASES, ids=lambda case: case['id'])
def test_actual_v5_pair_requires_complete_independent_custody(case):
    case, native, sdk, native_result, sdk_result, native_directory, sdk_directory = _v5_raw_packet(case['id'])
    assert guard.validate_pair(case, native, sdk, native_result, sdk_result,
        approved_node=_trusted_node(), approved_sdk_root=SDK_SOURCE_ROOT, approved_reference=REFERENCE_ROOT,
        approved_adapter_root=Path(ADAPTER_ROOT).resolve(strict=True),
        native_directory=native_directory, sdk_directory=sdk_directory) is True


@pytest.mark.parametrize('case', V5_CASES, ids=lambda case: case['id'])
def test_v5_closed_business_family_preserves_original_control_protocols(case):
    assert guard._case(case) == case['input'] and guard._version(case) == 5
    assert guard._native_profile_key(case) == 'forgetIndexFenceV3Profile'
    assert guard._native_bootstrap_prefix(case) == 'forget-index-fence-v3'
    assert guard._capture_prefix(case) == 'forget-index-fence-v5'
    assert 'sync' not in case['input']['config']['memory']['search']
    assert case['input']['observationPolicy']['watchEffects']['protocol'] == 'original-watch-effects-v5'
    assert case['input']['observationPolicy']['searchEffects']['protocol'] == 'original-search-effects-v3'
    mixed = {**case, 'operation': 'forget-index-fence-v4-runtime'}
    with pytest.raises(ValueError):
        guard._case(mixed)


def test_v5_selector_never_borrows_a_v4_packet(tmp_path, monkeypatch):
    monkeypatch.setitem(globals(), 'V5_CAPTURE_ROOT', None)
    monkeypatch.setitem(globals(), 'V5_SUITE_REPORT', None)
    monkeypatch.setitem(globals(), 'V4_CAPTURE_ROOT', str(tmp_path / 'labelled-v4-only'))
    with pytest.raises(pytest.skip.Exception, match='No explicitly selected V5 packet'):
        _v5_raw_packet.__wrapped__(V5_CASES[0]['id'])


@pytest.mark.parametrize('missing', ['V5_NATIVE_CAPTURE_ROOT', 'V5_SDK_CAPTURE_ROOT'])
def test_v5_suite_selector_requires_independent_roots_without_fallback(monkeypatch, missing):
    monkeypatch.setitem(globals(), 'V5_SUITE_REPORT', 'UNIT_FULL_REPORT')
    monkeypatch.setitem(globals(), 'V5_CAPTURE_ROOT', None)
    monkeypatch.setitem(globals(), 'V5_NATIVE_CAPTURE_ROOT', 'UNIT_NATIVE_ROOT')
    monkeypatch.setitem(globals(), 'V5_SDK_CAPTURE_ROOT', 'UNIT_SDK_ROOT')
    monkeypatch.setitem(globals(), missing, None)
    with pytest.raises(AssertionError, match='both independently selected physical roots'):
        _v5_suite_admission.__wrapped__()


def test_v5_suite_and_collector_selectors_are_mutually_exclusive(monkeypatch):
    monkeypatch.setitem(globals(), 'V5_SUITE_REPORT', 'UNIT_FULL_REPORT')
    monkeypatch.setitem(globals(), 'V5_CAPTURE_ROOT', 'UNIT_COLLECTOR_ROOT')
    with pytest.raises(AssertionError, match='exclusive'):
        _v5_raw_packet.__wrapped__(V5_CASES[0]['id'])


@pytest.mark.parametrize('changed_payload', [False, True])
def test_v5_suite_route_uses_sealed_original_refs_and_whole_results(tmp_path, monkeypatch, changed_payload):
    # Labelled files/CLI admission double only; real pair validation is unchanged.
    from types import SimpleNamespace
    import importlib.util
    spec = importlib.util.spec_from_file_location('unit_suite_route_cli', ROOT / 'scripts/replay_forget_index_fence.py')
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    case = V5_CASES[0]
    native_dir, sdk_dir = tmp_path / 'native', tmp_path / 'sdk'
    (native_dir / 'evidence').mkdir(parents=True)
    sdk_dir.mkdir()
    native_result, sdk_result = {'UNIT_WHOLE': [False, 0, None]}, {'UNIT_WHOLE': {'retained': True}}
    (native_dir / 'evidence/native-raw.json').write_text('[{"UNIT_NATIVE":true}]')
    (native_dir / 'stdout.json').write_text(json.dumps({'id': case['id'], 'ok': True, 'result': native_result}))
    (sdk_dir / 'python-raw.json').write_text(json.dumps([{'observation': {'result': sdk_result}}]))
    files = {name: cli._seal(path) for name, path in {
        'nativeRaw': native_dir / 'evidence/native-raw.json', 'nativeStdout': native_dir / 'stdout.json',
        'sdkRaw': sdk_dir / 'python-raw.json'}.items()}
    selected = {case['id']: {'directories': {'native': native_dir, 'sdk': sdk_dir}, 'files': files,
                            'nativeResult': native_result, 'sdkResult': {'UNIT_CHANGED': True} if changed_payload else sdk_result}}
    observed = []
    def authority(args, actual_guard, frozen):
        assert actual_guard is guard and frozen.build_cases() == V5_CASES
        observed.append(('authority', args))
        return {'UNIT_AUTHORITY': True}
    def admit(args, actual_authority, report, frozen):
        assert actual_authority == {'UNIT_AUTHORITY': True} and report == {'sourceReports': []}
        observed.append(('admit', args))
        return selected, [], {'UNIT_SUITE_AUTHORITY': True}
    fake = SimpleNamespace(_authorities=authority, _admit_suite_report=admit, _seal=cli._seal)
    monkeypatch.setitem(globals(), 'V5_SUITE_REPORT', str(tmp_path / 'actual-full.json'))
    monkeypatch.setitem(globals(), 'V5_CAPTURE_ROOT', None)
    monkeypatch.setitem(globals(), 'V5_NATIVE_CAPTURE_ROOT', str(native_dir))
    monkeypatch.setitem(globals(), 'V5_SDK_CAPTURE_ROOT', str(sdk_dir))
    monkeypatch.setitem(globals(), 'ADAPTER_ROOT', str(tmp_path))
    monkeypatch.setitem(globals(), '_v5_replay_cli', lambda: fake)
    admission = _v5_suite_admission.__wrapped__()
    monkeypatch.setitem(globals(), '_v5_suite_admission', lambda: admission)
    if changed_payload:
        with pytest.raises(ValueError, match='Whole suite SDK payload'):
            _v5_raw_packet.__wrapped__(case['id'])
    else:
        result = _v5_raw_packet.__wrapped__(case['id'])
        assert len(result) == 7 and result[0] == case and result[3:5] == (native_result, sdk_result)
        assert result[5:] == (native_dir, sdk_dir)
    assert [row[0] for row in observed] == ['authority', 'admit']
    args = observed[0][1]
    assert args.version == 'v5' and args.native_capture_root == native_dir and args.sdk_capture_root == sdk_dir
    assert args.adapter_root == tmp_path and args.sdk_source_root == SDK_SOURCE_ROOT and args.reference == REFERENCE_ROOT


@pytest.fixture(scope='module')
def v5_native_watcher_actual():
    suite_selected = os.environ.get('MEMORY_FORGET_INDEX_FENCE_V5_SUITE_REPORT') is not None
    if V5_NATIVE_CAPTURE is None and V5_CAPTURE_ROOT is None and not suite_selected:
        pytest.skip('No explicitly selected genuine V5 Native watcher packet; no acceptance credit')
    assert ADAPTER_ROOT is not None
    from unittest.mock import patch
    from equivalence import forget_index_fence_native_watch_evidence as watcher
    if V5_NATIVE_CAPTURE is not None:
        selected = Path(V5_NATIVE_CAPTURE)
    elif suite_selected:
        selected = _v5_raw_packet('forget-index-fence-v5-shared-marker-commit-process-kill')[5]
    else:
        selected = Path(V5_CAPTURE_ROOT) / 'forget-index-fence-v5-shared-marker-commit-process-kill' / 'native'
    directory = selected.resolve(strict=True)
    values, returned = _read(directory / 'evidence/native-raw.json'), _read(directory / 'stdout.json')
    assert len(values) == 1 and returned['ok'] is True
    case = next(row for row in V5_CASES if row['id'] == returned['id'])
    with patch.object(watcher, 'validate_native_watch_v5', wraps=watcher.validate_native_watch_v5) as observed:
        assert guard.validate_capture(case, values[0], returned['result'], native=True,
            approved_node=_trusted_node(), approved_reference=REFERENCE_ROOT,
            approved_adapter_root=Path(ADAPTER_ROOT).resolve(strict=True), directory=directory) is True
        assert observed.call_count == 1
        return observed.call_args.args


def test_actual_v5_native_watcher_positive_is_independently_authenticated(v5_native_watcher_actual):
    assert v5_native_watcher_actual[0]['input']['kind'] == 'forget-index-fence-v5'


@pytest.mark.parametrize('attack', ['sync-wrapper', 'missing-delivery', 'wrong-stat', 'timer-fire', 'sync-owner', 'version-sha'])
def test_v5_native_watcher_rejects_changed_actual_delivery_proof(v5_native_watcher_actual, attack):
    from equivalence.forget_index_fence_native_watch_evidence import validate_native_watch_v5
    args = list(v5_native_watcher_actual)
    passive = {key: list(rows) for key, rows in args[4].items()}
    target_name = {'sync-wrapper': 'original-watch-observer-installed', 'missing-delivery': 'original-watch-delivery-enter',
                   'wrong-stat': 'original-watch-version-stat-return', 'timer-fire': 'original-watch-timer-fire',
                   'sync-owner': 'original-watch-promise-created'}
    if attack == 'version-sha':
        commands = dict(args[3])
        key, original = next((key, row) for key, row in commands.items() if row[3].get('sourceVersions', {}).get('versions'))
        row = list(original)
        row[3] = deepcopy(row[3])
        row[3]['sourceVersions']['versions'][0]['sha256'] = '0' * 64
        commands[key] = tuple(row)
        args[3] = commands
    else:
        key, number, original = next((key, i, row) for key, rows in passive.items() for i, row in enumerate(rows)
                                    if key[0] in args[2] and key[1] == 0 and row['event'] == target_name[attack])
        row = deepcopy(original)
        if attack == 'sync-wrapper':
            row['syncMethodsWrapped'] = True
        elif attack == 'wrong-stat':
            row['mtimeMs'] += 1
        elif attack == 'sync-owner':
            row['syncMethodRef'] += '-other'
        else:
            del passive[key][number]
        if attack not in {'missing-delivery', 'timer-fire'}:
            passive[key][number] = row
        args[4] = passive
    cache = {'sourceIndexes': {}, 'verifiedFiles': {}, 'terminated': {}, 'decoderAuthorities': {}, 'v8': {}}
    token = guard._VALIDATION_CACHE.set(cache)
    try:
        with pytest.raises((ValueError, KeyError)):
            validate_native_watch_v5(*args)
    finally:
        guard._VALIDATION_CACHE.reset(token)


def _v5_stdout_codec_example(text=None):
    """Codec-only data; deliberately lacks all engine/process custody fields."""
    value = V5_CASES[0]['input']
    observation = {'kind': 'forget-index-fence-v5-sdk-host', 'input': value,
                   'codecExample': ['Türkçe\nexact', 1, 1.0, True, False, None, {'timestamp': 1794614400000}]}
    stdout = text if text is not None else json.dumps(observation, ensure_ascii=False, separators=(',', ':')) + '\n'
    wire = stdout.encode('utf8')
    return {'kind': 'forget-index-fence-v5-sdk-dispatch', 'input': value, 'stdout': stdout,
            'observationEncoding': {'kind': 'stdout-json-v1', 'field': 'stdout', 'utf8Bytes': len(wire),
                                    'sha256': hashlib.sha256(wire).hexdigest()}}, observation


def test_v5_stdout_codec_preserves_whole_json_and_original_utf8_bytes():
    dispatch, observation = _v5_stdout_codec_example()
    original = deepcopy(dispatch)
    decoded = guard.materialize_sdk_dispatch(dispatch)
    assert decoded is not dispatch and 'observation' not in dispatch
    assert dispatch == original and decoded['stdout'].encode('utf8') == original['stdout'].encode('utf8')
    guard._same(decoded['observation'], observation, 'The codec must preserve every actual JSON field/value')
    assert type(decoded['observation']['codecExample'][1]) is int
    assert type(decoded['observation']['codecExample'][2]) is float
    assert type(decoded['observation']['codecExample'][3]) is bool
    assert decoded['observationEncoding'] == original['observationEncoding']
    # Parsing a transport cannot manufacture genuine original process proof.
    with pytest.raises(ValueError):
        guard.validate_capture(V5_CASES[0], dispatch, {}, native=False)


@pytest.mark.parametrize('version', [1, 2, 3, 4, 5])
def test_v5_stdout_codec_preserves_historical_inline_wire_without_rewriting(version):
    dispatch = {'kind': f'forget-index-fence-v{version}-sdk-dispatch', 'stdout': 'unchanged', 'observation': {'retained': True}}
    assert guard.materialize_sdk_dispatch(dispatch) is dispatch


@pytest.mark.parametrize('attack', ['dual', 'wrong-version', 'mixed-input', 'marker-extra', 'marker-missing',
    'codec', 'field', 'bool-length', 'negative-length', 'over-limit', 'wrong-length', 'wrong-sha',
    'uppercase-sha', 'stdout-type', 'stdout-tamper', 'invalid-utf8', 'decode-failure', 'stderr-decode-failure',
    'stderr-bytes-duplicate', 'retention-failure', 'bytes-duplicate'])
def test_v5_stdout_codec_rejects_ambiguous_or_changed_bytes(attack):
    dispatch, observation = _v5_stdout_codec_example()
    marker = dispatch['observationEncoding']
    if attack == 'dual':
        dispatch['observation'] = observation
    elif attack == 'wrong-version':
        dispatch['kind'] = 'forget-index-fence-v4-sdk-dispatch'
    elif attack == 'mixed-input':
        dispatch['input'] = V4_CASES[0]['input']
    elif attack == 'marker-extra':
        marker['observed'] = True
    elif attack == 'marker-missing':
        del marker['sha256']
    elif attack == 'codec':
        marker['kind'] = 'stdout-json-v2'
    elif attack == 'field':
        marker['field'] = 'stderr'
    elif attack == 'bool-length':
        marker['utf8Bytes'] = True
    elif attack == 'negative-length':
        marker['utf8Bytes'] = -1
    elif attack == 'over-limit':
        marker['utf8Bytes'] = 512 * 1024 * 1024 + 1
    elif attack == 'wrong-length':
        marker['utf8Bytes'] += 1
    elif attack == 'wrong-sha':
        marker['sha256'] = '0' * 64
    elif attack == 'uppercase-sha':
        marker['sha256'] = marker['sha256'].upper()
    elif attack == 'stdout-type':
        dispatch['stdout'] = ['not original bytes']
    elif attack == 'stdout-tamper':
        dispatch['stdout'] = dispatch['stdout'].replace('exact', 'other')
    elif attack == 'invalid-utf8':
        dispatch['stdout'] = '\ud800\n'
    elif attack == 'decode-failure':
        dispatch['stdoutDecodeError'] = {'message': 'actual invalid UTF8'}
    elif attack == 'stderr-decode-failure':
        dispatch['stderrDecodeError'] = {'message': 'actual invalid UTF8'}
    elif attack == 'stderr-bytes-duplicate':
        dispatch['stderrBytesHex'] = 'ff'
    elif attack == 'retention-failure':
        dispatch['observationEncodingError'] = {'message': 'actual retention failed'}
    else:
        dispatch['stdoutBytesHex'] = dispatch['stdout'].encode('utf8').hex()
    with pytest.raises(ValueError):
        guard.materialize_sdk_dispatch(dispatch)


@pytest.mark.parametrize('attack', ['no-lf', 'two-lines', 'crlf', 'extra-json', 'duplicate', 'nonfinite', 'overflow-float', 'wrong-host', 'wrong-input'])
def test_v5_stdout_codec_rejects_resealed_noncanonical_json_records(attack):
    dispatch, _ = _v5_stdout_codec_example()
    text = dispatch['stdout']
    if attack == 'no-lf':
        text = text[:-1]
    elif attack == 'two-lines':
        text += '\n'
    elif attack == 'crlf':
        text = text[:-1] + '\r\n'
    elif attack == 'extra-json':
        text = text[:-1] + '{}\n'
    elif attack == 'duplicate':
        text = text.replace('{', '{"codecExample":null,', 1)
    elif attack == 'nonfinite':
        text = text.replace('1794614400000', 'NaN', 1)
    elif attack == 'overflow-float':
        text = text.replace('1794614400000', '1e999', 1)
    elif attack == 'wrong-host':
        text = text.replace('forget-index-fence-v5-sdk-host', 'forget-index-fence-v4-sdk-host')
    else:
        text = text.replace('"kind":"forget-index-fence-v5"', '"kind":"forget-index-fence-v4"', 1)
    changed, _ = _v5_stdout_codec_example(text)
    with pytest.raises(ValueError):
        guard.materialize_sdk_dispatch(changed)


@pytest.mark.parametrize('field', ['stdoutDecodeError', 'stderrDecodeError', 'observationEncodingError'])
def test_v5_stdout_codec_diagnostic_inline_data_never_becomes_successful_custody(field):
    dispatch, observation = _v5_stdout_codec_example()
    del dispatch['observationEncoding']
    dispatch['observation'] = observation
    dispatch[field] = {'message': 'failed original stream retention'}
    with pytest.raises(ValueError, match='stream decode or retention failed'):
        guard._sdk_capture(V5_CASES[0], dispatch, {}, None, None)


@pytest.fixture(scope='module')
def v5_actual_opaque_reconciliation_return(v5_native_watcher_actual):
    args = v5_native_watcher_actual
    for (pid, thread), rows in args[4].items():
        if pid not in args[2] or thread != 0:
            continue
        entered = {row['deliveryId']: row for row in rows if row['event'] == 'original-watch-delivery-enter'}
        for row in rows:
            if row['event'] == 'original-watch-delivery-return' and 'serializationError' in row['return']:
                return row, entered[row['deliveryId']], args[5], pid
    pytest.skip('Selected genuine Native packet did not exercise an opaque original reconciliation Promise')


def test_v5_native_original_callback_promise_remains_opaque(v5_actual_opaque_reconciliation_return):
    from equivalence.forget_index_fence_native_watch_evidence import _opaque_native_reconciliation_return
    returned, delivery, context, pid = v5_actual_opaque_reconciliation_return
    before = deepcopy(returned)
    _opaque_native_reconciliation_return(returned, delivery, context, pid)
    assert returned == before and set(returned['return']) == {'serializationError'}
    assert returned['return']['serializationError']['message'] == '#<Promise> could not be cloned.'
    assert 'settlement' not in returned


@pytest.mark.parametrize('attack', ['message', 'return-ref', 'stack', 'listener', 'emitter', 'source-owner', 'dual', 'observer-source'])
def test_v5_native_opaque_callback_requires_original_promise_source(v5_actual_opaque_reconciliation_return, attack):
    from equivalence.forget_index_fence_native_watch_evidence import _opaque_native_reconciliation_return
    returned, delivery, context, pid = deepcopy(v5_actual_opaque_reconciliation_return)
    if attack == 'message':
        returned['return']['serializationError']['message'] = '#<Function> could not be cloned.'
    elif attack == 'return-ref':
        returned['returnRef'] = str(pid + 1) + ':0:process-ref-8088'
    elif attack == 'stack':
        returned['return']['serializationError']['stack'] = 'Error: guessed Promise'
    elif attack == 'listener':
        delivery['registration']['listenerSource'] = '(eventType, filename) => Promise.resolve()'
    elif attack == 'emitter':
        delivery['kind'] = 'chokidar'
    elif attack == 'source-owner':
        delivery['registration']['sourceOwner']['path'] = 'dist/another-watcher.js'
    elif attack == 'dual':
        returned['return']['v8Hex'] = 'ff0f5f'
    else:
        context['allowedLocal'] = [row for row in context['allowedLocal']
                                   if not row['path'].endswith('forget-index-fence-source-clock.mjs')]
    with pytest.raises(ValueError):
        _opaque_native_reconciliation_return(returned, delivery, context, pid)


@pytest.fixture(scope='module')
def v5_native_interrupted_actual(v5_native_watcher_actual):
    args = v5_native_watcher_actual
    stopped = args[1].get('interruptedSourceCalls', [])
    if not stopped:
        pytest.skip('Selected genuine Native packet did not exercise a marker-held process kill')
    assert len(stopped) == 1
    return args, stopped[0]


def test_v5_native_interrupted_source_remains_a_negative_proof(v5_native_interrupted_actual):
    args, stopped = v5_native_interrupted_actual
    assert stopped['kind'] == 'original-interrupted-source-call' and 'versions' not in stopped
    assert stopped['sourceCallCutoff']['completed'] is False
    assert stopped['sourceCallCutoff']['handles'] == stopped['sourceCallCutoff']['commits'] == []
    child, _, command, entry = args[3][stopped['commandId']]
    assert child['exit'] == {'code': None, 'signal': 'SIGKILL'}
    assert 'settlement' not in command and 'sourceVersions' not in entry
    assert int(child['reapedAtNs']) < int(stopped['markerGate']['receipt']['enteredAtNs']) + 30_000_000_000


@pytest.mark.parametrize('attack', ['completed', 'released', 'foreign-frame', 'unreaped', 'not-pending',
                                  'coherent-write-admission', 'coherent-late-reap', 'coherent-io-omission'])
def test_v5_native_interrupted_source_rejects_false_absence(v5_native_interrupted_actual, attack):
    from equivalence.forget_index_fence_native_watch_evidence import validate_native_watch_v5
    actual, original = v5_native_interrupted_actual
    args = list(actual)
    stopped = deepcopy(original)
    raw = dict(args[1])
    raw['interruptedSourceCalls'] = [stopped]
    args[1] = raw
    if attack == 'completed':
        stopped['versions'] = []
    elif attack == 'released':
        stopped['markerGate']['releasedAtNs'] = stopped['kill']['atNs']
    elif attack == 'unreaped':
        stopped['exit'] = {'code': 0, 'signal': None}
    elif attack == 'not-pending':
        commands = dict(args[3])
        row = list(commands[stopped['commandId']])
        row[2] = {**row[2], 'settlement': {'type': 'settled'}}
        commands[stopped['commandId']] = tuple(row)
        args[3] = commands
    elif attack == 'coherent-late-reap':
        commands = dict(args[3])
        row = list(commands[stopped['commandId']])
        child = deepcopy(row[0])
        late = str(int(stopped['markerGate']['receipt']['enteredAtNs']) + 30_000_000_001)
        child['reapedAtNs'] = late
        row[0] = child
        row[2] = {**row[2], 'termination': {**row[2]['termination'], 'reapedAtNs': late}}
        stopped['termination'] = deepcopy(row[2]['termination'])
        stopped['reapedAtNs'] = late
        stopped['capturedAtNs'] = str(int(late) + 1)
        commands[stopped['commandId']] = tuple(row)
        args[3] = commands
    else:
        cutoff = stopped['sourceCallCutoff']
        if attack == 'foreign-frame':
            cutoff['causalFrame']['pid'] += 1
        elif attack == 'coherent-write-admission':
            control = next(row for rows in args[4].values() for row in rows if row['event'] == 'source-clock-control')
            cutoff['handles'] = [deepcopy(control['open'])]
        else:
            assert cutoff['receipts']
            cutoff['receipts'].pop()
        # Keep the copied carrier/seal/gate/passive-cutoff views coherent. The
        # independent original IO stream and negative source policy still reject.
        text = json.dumps(cutoff, ensure_ascii=False, separators=(',', ':'))
        stopped['sourceCallCutoffSeal'] = {'serializedJSON': text, 'sha256': hashlib.sha256(text.encode()).hexdigest()}
        stopped['markerGate']['receipt']['sourceCallCutoff'] = deepcopy(cutoff)
        raw['gates'] = [stopped['markerGate'] if row['name'] == stopped['markerGate']['name'] else row for row in raw['gates']]
        passive = {key: list(rows) for key, rows in args[4].items()}
        key = stopped['pid'], 0
        passive[key] = [{**row, 'cutoff': deepcopy(cutoff)} if row['event'] == 'original-source-call-interrupted-cutoff'
                        and row['gate'] == stopped['markerGate']['name'] else row for row in passive[key]]
        args[4] = passive
    cache = {'sourceIndexes': {}, 'verifiedFiles': {}, 'terminated': {}, 'decoderAuthorities': {}, 'v8': {}}
    token = guard._VALIDATION_CACHE.set(cache)
    try:
        with pytest.raises((ValueError, KeyError)):
            validate_native_watch_v5(*args)
    finally:
        guard._VALIDATION_CACHE.reset(token)
