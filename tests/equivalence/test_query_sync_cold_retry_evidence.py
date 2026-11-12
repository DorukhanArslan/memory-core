"""Replay only genuine captures of the two zero-credit cold-retry schedules.

This module never launches either engine and never treats an older outcome
capture as this development packet. Missing captures skip without credit; a
selected current capture that does not validate fails without fallback.

The attack plan includes independent trusted-Node authority, actual OS fault
identity/syscalls, same-owner retry, receiver-qualified search/bootstrap counts,
complete error carriers, original worker/V8 bytes and physical read/publication
dataflow. No after-removal success or cross-engine equality is assumed.
"""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import stat

import pytest

from equivalence.query_sync_cold_retry import build_cases


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = Path(os.environ.get("MEMORY_QUERY_SYNC_COLD_RETRY_EVIDENCE_ROOT", ROOT)).resolve()
CASES = build_cases()
CAPTURE_ROOT = os.environ.get("MEMORY_QUERY_SYNC_COLD_RETRY_CAPTURE_ROOT")
RETAINED = ((Path(CAPTURE_ROOT).resolve(),) if CAPTURE_ROOT else
            (SOURCE_ROOT / ".equivalence-results/query-sync-cold-retry",
             SOURCE_ROOT / "work/query-sync-boundaries"))


def _guard():
    from equivalence import query_sync_cold_retry_evidence
    return query_sync_cold_retry_evidence


def _trusted_node():
    """Decoder authority comes from caller configuration, never capture fields."""
    return Path(os.environ.get("MEMORY_EQ_NODE", SOURCE_ROOT / "work/node-v24.16.0-linux-x64/bin/node")).resolve()


@lru_cache(maxsize=32)
def _read_cached(path, size, mtime):
    return json.loads(Path(path).read_text(encoding="utf8"))


def _read(path):
    observed = path.lstat()
    assert stat.S_ISREG(observed.st_mode) and observed.st_nlink == 1 and not path.is_symlink(), path
    return _read_cached(str(path), observed.st_size, observed.st_mtime_ns)


def _current_sdk_generation(raw):
    """Exclude dated source generations without accepting malformed bindings."""
    bindings = raw["implementationBindings"]
    assert isinstance(bindings, list) and bindings
    for binding in bindings:
        module, filename, digest = binding["module"], Path(binding["path"]), binding["sha256"]
        assert isinstance(module, str) and (module == "memory_core" or module.startswith("memory_core."))
        parts = module.split(".")
        assert all(part.isidentifier() for part in parts)
        relative = Path(*parts)
        assert filename in {SOURCE_ROOT / relative.with_suffix(".py"), SOURCE_ROOT / relative / "__init__.py"}
        assert isinstance(digest, str) and len(digest) == 64 and set(digest) <= set("0123456789abcdef")
        if not filename.is_file():
            return False
        assert not filename.is_symlink() and filename.resolve() == filename
        if hashlib.sha256(filename.read_bytes()).hexdigest() != digest:
            return False
    return True


def _load(case, native):
    name = "native-raw.json" if native else "python-raw.json"
    paths = sorted({path for root in RETAINED if root.is_dir() for path in root.rglob(name)},
                   key=lambda path: path.stat().st_mtime_ns, reverse=True)
    for path in paths:
        values = _read(path)
        assert isinstance(values, list) and len(values) == 1, path
        capture = values[0]
        if capture.get("input") != case["input"]:
            continue
        if native:
            context = _read(path.parents[1] / "context.json")
            actor = SOURCE_ROOT / "equivalence/query-sync-cold-retry-runtime.mjs"
            records = [row for row in context["allowedLocal"] if row["path"] == str(actor)]
            if len(records) != 1 or records[0]["sha256"] != hashlib.sha256(actor.read_bytes()).hexdigest():
                continue  # A historical program generation supplies no current truth.
            returned = _read(path.parents[1] / "stdout.json")
            assert returned["ok"] is True and returned["id"] == case["id"], path
            result = returned["result"]
        else:
            assert capture["kind"] == "query-sync-cold-retry-sdk-dispatch", path
            assert capture["exit"] == {"code": 0}, path
            assert capture["observation"]["raw"]["implementationRoot"] == str(SOURCE_ROOT), path
            if not _current_sdk_generation(capture["observation"]["raw"]):
                continue  # An honest historical SDK source generation is not current truth.
            result = capture["observation"]["result"]
        assert _guard().validate_capture(case, capture, result, native=native,
                                         approved_node=_trusted_node() if native else None) is True
        return case, capture, result
    pytest.skip("No retained current genuine cold-retry development capture; no acceptance credit")


@pytest.fixture(scope="module", params=[True, False], ids=["native", "sdk"])
def engine(request):
    return request.param


@pytest.fixture(scope="module", params=CASES, ids=lambda case: case["id"])
def actual(request, engine):
    return engine, _load(request.param, engine)


@pytest.fixture(scope="module")
def recovery(engine):
    return engine, _load(CASES[1], engine)


def _raw(capture, native):
    return capture[1] if native else capture[1]["observation"]["raw"]


def _seal(capture, native):
    _raw(capture, native)["result"] = deepcopy(capture[2])
    if not native:
        capture[1]["observation"]["result"] = deepcopy(capture[2])
        capture[1]["stdout"] = json.dumps(capture[1]["observation"], ensure_ascii=False, allow_nan=False)


def _reject(capture, native, message="(?i)cold-retry|query-sync"):
    _seal(capture, native)
    with pytest.raises(ValueError, match=message):
        _guard().validate_capture(*capture, native=native,
                                  approved_node=_trusted_node() if native else None)


def _replace(value, old, new):
    if isinstance(value, dict):
        for key, item in list(value.items()):
            if item == old:
                value[key] = deepcopy(new)
            else:
                _replace(item, old, new)
    elif isinstance(value, list):
        for number, item in enumerate(value):
            if item == old:
                value[number] = deepcopy(new)
            else:
                _replace(item, old, new)


def _fault(raw, native):
    return raw["fault"] if native else raw["faults"][0]


def _labels(case):
    """Execution order is the frozen step array, not JSON object insertion order."""
    return [step["label"] for step in case["input"]["steps"]
            if step["operation"] == "public-memory-search"]


def test_actual_complete_capture_validates_without_predicting_recovery(actual):
    native, capture = actual
    assert capture[0]["covers"] == []
    assert _guard().validate_capture(*capture, native=native,
                                     approved_node=_trusted_node() if native else None) is True
    assert set(capture[2]["searches"]) == set(_labels(capture[0]))


@pytest.mark.parametrize("field", ["searches", "dispatches", "sources"])
def test_complete_development_wire_cannot_drop_a_stage(actual, field):
    _, capture = actual
    case, _, result = deepcopy(capture)
    target = result[field]
    target.pop(next(iter(target)))
    with pytest.raises(ValueError, match="(?i)cold-retry"):
        _guard().validate_result(case, result)


@pytest.mark.parametrize("field", ["managerSearches", "bootstrapAttempts"])
@pytest.mark.parametrize("replacement", [None, False, -1])
def test_public_dispatch_counts_are_complete_actual_integer_counts(actual, field, replacement):
    _, capture = actual
    case, _, result = deepcopy(capture)
    result["dispatches"][next(iter(result["dispatches"]))][field] = replacement
    with pytest.raises(ValueError, match="(?i)cold-retry"):
        _guard().validate_result(case, result)


@pytest.mark.parametrize("field", ["managerSearches", "bootstrapAttempts"])
def test_resealed_public_counts_cannot_replace_actual_receiver_admissions(actual, field):
    native, baseline = actual
    capture = deepcopy(baseline)
    label = next(iter(capture[2]["dispatches"]))
    capture[2]["dispatches"][label][field] += 1
    _reject(capture, native)


@pytest.mark.parametrize("attack", ["other-receiver", "other-query", "other-owner", "other-query-label"])
def test_original_search_dispatch_belongs_to_this_same_owner_query(actual, attack):
    native, baseline = actual
    capture = deepcopy(baseline)
    raw = _raw(capture, native)
    row = raw["originalSearchCalls"][0]
    old = deepcopy(row)
    if attack == "other-receiver":
        row["receiverIsExactObservedOwner"] = False
    elif attack == "other-query":
        row["query"] = "another cold recovery marker"
    elif attack == "other-owner":
        row["ownerId"] = "borrowed-owner"
    else:
        row["activeTool"] = _labels(capture[0])[1]
    _replace(raw, old, row)
    _reject(capture, native)


@pytest.mark.parametrize("attack", ["missing-open", "extra-owner", "early-close"])
def test_same_owner_retry_cannot_be_an_implicit_reopen(actual, attack):
    native, baseline = actual
    capture = deepcopy(baseline)
    raw = _raw(capture, native)
    if attack == "missing-open":
        raw["facadeCalls" if native else "ownerAcquisitions"] = []
    elif attack == "extra-owner":
        owner_id = next(iter(raw["owners"]))
        raw["owners"]["another-owner"] = deepcopy(raw["owners"][owner_id])
    else:
        close = (next(row for row in raw["methodCalls"] if row["method"] == "close")
                 if native else next(iter(raw["owners"].values()))["close"])
        close["returnSeq"] = raw["toolCalls"][_labels(capture[0])[0]]["returnSeq"]
    _reject(capture, native)


@pytest.mark.parametrize("attack", ["wrong-sidecar", "target-exists", "not-symlink", "wrong-removal-inode", "no-follow-error"])
def test_real_owned_refusal_and_its_removal_are_not_just_claims(recovery, attack):
    native, baseline = recovery
    capture = deepcopy(baseline)
    fault = _fault(_raw(capture, native), native)
    if attack == "wrong-sidecar":
        key = "sidecar" if native else "path"
        fault[key] = str(Path(fault[key]).with_name("another-index-journal"))
    elif attack == "target-exists":
        fault["targetParentBefore"]["kind"] = "directory"
    elif attack == "not-symlink":
        fault["armed"]["kind"] = "file"
    elif attack == "wrong-removal-inode":
        key = "identity" if native else "stat"
        inode = "inode" if native else "st_ino"
        observed = fault["beforeRemoval"][key][inode]
        fault["beforeRemoval"][key][inode] = str(int(observed) + 1) if native else observed + 1
    else:
        if native:
            fault["actualBootstrapFailures"] = []
        else:
            fault.pop("actualFollowError")
    _reject(capture, native)


@pytest.mark.parametrize("attack", ["missing-unlink", "wrong-unlink", "wrong-symlink", "lost-restoration"])
def test_native_physical_fault_requires_actual_owned_os_calls(attack):
    capture = deepcopy(_load(CASES[1], True))
    raw = capture[1]
    calls = raw["faultSyscalls"]
    if attack == "missing-unlink":
        raw["faultSyscalls"] = [row for row in calls if row["method"] != "unlinkSync"]
    elif attack == "wrong-unlink":
        next(row for row in calls if row["method"] == "unlinkSync")["args"] = ["/tmp/not-the-owned-refusal"]
    elif attack == "wrong-symlink":
        next(row for row in calls if row["method"] == "symlinkSync")["args"][0] = "/tmp/not-the-owned-target"
    else:
        fault = raw["fault"]
        fault["restored"]["kind"] = "symlink"
    _reject(capture, True)


@pytest.mark.parametrize("attack", ["carrier-text", "details", "missing-call"])
def test_complete_original_tool_error_carrier_cannot_be_detached(recovery, attack):
    native, baseline = recovery
    capture = deepcopy(baseline)
    raw = _raw(capture, native)
    first = _labels(capture[0])[0]
    call = raw["toolCalls"][first]
    if attack == "carrier-text":
        call["envelope"]["content"][0]["text"] = "{}"
    elif attack == "details":
        call["envelope"]["details"].pop("warning")
    else:
        raw["toolCalls"].pop(first)
    _reject(capture, native)


@pytest.mark.parametrize("attack", ["missing-bytes", "wrong-hash", "forged-decoded-value"])
def test_native_v8_projection_still_requires_original_broker_bytes(attack):
    capture = deepcopy(_load(CASES[0], True))
    raw = capture[1]
    rows = raw["workerDispatches"] + raw["workerMessages"]
    row = next(row for row in rows if row["decodedSerialized"])
    key = next(iter(row["decodedSerialized"]))
    wire, decoded = row["message"][key], row["decodedSerialized"][key]
    if attack == "missing-bytes":
        wire.pop("hex")
    elif attack == "wrong-hash":
        decoded["bytesSha256"] = "0" * 64
    else:
        decoded["value"] = {"manufactured": "projection without original V8 data"}
    _reject(capture, True)


def test_native_v8_decoder_uses_only_independently_approved_node(monkeypatch):
    capture = _load(CASES[0], True)
    evidence = _guard()
    decode = evidence._decode_v8
    approved = _trusted_node()
    observed = []

    def trusted_only(authority, wires):
        assert Path(authority["execPath"]).resolve() == approved
        observed.append(authority["sha256"])
        return decode(authority, wires)

    monkeypatch.setattr(evidence, "_decode_v8", trusted_only)
    assert evidence.validate_capture(*capture, native=True, approved_node=approved) is True
    assert observed


@pytest.mark.parametrize("mapping", ["input-queries", "public-results", "raw-tool-calls"])
def test_json_object_key_order_does_not_redefine_the_actual_frozen_schedule(actual, mapping):
    native, baseline = actual
    capture = deepcopy(baseline)
    if mapping == "input-queries":
        queries = capture[0]["input"]["queries"]
        capture[0]["input"]["queries"] = dict(reversed(list(queries.items())))
    elif mapping == "public-results":
        for field in ("searches", "dispatches", "sources"):
            capture[2][field] = dict(reversed(list(capture[2][field].items())))
    else:
        raw = _raw(capture, native)
        raw["toolCalls"] = dict(reversed(list(raw["toolCalls"].items())))
    _seal(capture, native)
    assert _guard().validate_capture(*capture, native=native,
                                     approved_node=_trusted_node() if native else None) is True


def test_frozen_step_array_order_cannot_be_replaced_by_a_reordered_recipe(actual):
    native, baseline = actual
    capture = deepcopy(baseline)
    steps = capture[0]["input"]["steps"]
    positions = [number for number, step in enumerate(steps) if step["operation"] == "public-memory-search"]
    left, right = positions
    steps[left], steps[right] = steps[right], steps[left]
    with pytest.raises(ValueError, match="(?i)cold.retry|exact frozen"):
        _guard().validate_capture(*capture, native=native,
                                  approved_node=_trusted_node() if native else None)


def test_real_wrong_order_first_attempt_is_rejected_without_relabelling_it():
    case = CASES[1]
    directory = SOURCE_ROOT / "work/query-sync-boundaries/cold-retry-baseline-001" / case["id"]
    path = directory / "evidence/native-raw.json"
    if not path.is_file():
        pytest.skip("The genuine rejected first cold-retry attempt is not retained here; no credit")
    raw, returned = _read(path)[0], _read(directory / "stdout.json")
    assert raw["input"] == case["input"] and returned["id"] == case["id"]
    first, second = _labels(case)
    assert raw["toolCalls"][second]["returnSeq"] < raw["toolCalls"][first]["enterSeq"]
    with pytest.raises(ValueError, match="(?i)cold-retry.*(second query|order|fault|before)"):
        _guard().validate_capture(case, raw, returned["result"], native=True, approved_node=_trusted_node())


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_real_pair_custody_does_not_require_the_two_observed_results_to_match(case):
    native, sdk = _load(case, True), _load(case, False)
    assert _guard().validate_pair(case, native[1], sdk[1], native[2], sdk[2],
                                  approved_node=_trusted_node()) is True
