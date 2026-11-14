"""Replay only explicitly selected, genuine forget/index-fence packets.

Legacy SDK packets and new V2 paired packets have separate explicit selectors.
A failed Native transport cannot become a positive paired baseline. No test
launches an original engine or modifies a retained capture file.
"""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import stat

import pytest

from equivalence import forget_index_fence_evidence as guard
from equivalence.forget_index_fence import build_cases
from equivalence.forget_index_fence_v2 import build_cases as build_v2_cases


ROOT = Path(__file__).resolve().parents[2]
CAPTURE_ROOT = os.environ.get("MEMORY_FORGET_INDEX_FENCE_CAPTURE_ROOT")
SDK_CAPTURE_ROOT = os.environ.get("MEMORY_FORGET_INDEX_FENCE_SDK_CAPTURE_ROOT")
REJECTED_NATIVE_CAPTURE_ROOT = os.environ.get("MEMORY_FORGET_INDEX_FENCE_REJECTED_NATIVE_ROOT")
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


def test_actual_v2_pair_authenticates_both_originals_without_predicting_parity(v2_actual):
    assert v2_actual[-1] is True


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
