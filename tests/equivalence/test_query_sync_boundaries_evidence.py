"""Adversarial replays of the new, closed eight-case boundary packet.

This module never launches a host and never borrows an older outcome/development
capture. Only an explicit packet root supplies genuine baselines. Custody is
validated independently for each engine; different actual policies remain valid
mismatches. No counter, warning, retry outcome or equality is predicted here.
"""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import stat

import pytest

from equivalence.query_sync_boundaries import MANIFEST_SHA256, build_cases


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = Path(os.environ.get("MEMORY_QUERY_SYNC_BOUNDARIES_EVIDENCE_ROOT", ROOT)).resolve()
CAPTURE_ROOT = os.environ.get("MEMORY_QUERY_SYNC_BOUNDARIES_CAPTURE_ROOT")
CASES = build_cases()
COUNTERS = ("searchRequests", "managerSearches", "syncRequests", "bootstrapRequests",
            "producerAttempts", "committedGenerations")


def _guard():
    from equivalence import query_sync_boundaries_evidence
    return query_sync_boundaries_evidence


def _trusted_node():
    """Never execute a program or executable selected by captured metadata."""
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
        pytest.skip("No explicitly selected new query-sync boundary packet; no acceptance credit")
    directory = Path(CAPTURE_ROOT).resolve() / case["id"]
    path = directory / "evidence" / ("native-raw.json" if native else "python-raw.json")
    assert path.is_file(), f"The explicitly selected boundary packet is incomplete: {path}"
    values = _read(path)
    assert isinstance(values, list) and len(values) == 1, path
    capture = values[0]
    if native:
        returned = _read(directory / "stdout.json")
        assert returned["ok"] is True and returned["id"] == case["id"], directory
        result = returned["result"]
    else:
        assert capture["kind"] == "query-sync-boundaries-sdk-dispatch", path
        assert capture["exit"] == {"code": 0}, path
        result = capture["observation"]["result"]
    raw = capture if native else capture["observation"]["raw"]
    assert raw["kind"] == "query-sync-boundaries" and raw["caseId"] == case["id"], path
    assert raw["input"] == case["input"], path
    assert _guard().validate_capture(case, capture, result, native=native,
                                     approved_node=_trusted_node() if native else None) is True
    return case, capture, result


@pytest.fixture(scope="module", params=[True, False], ids=["native", "sdk"])
def engine(request):
    return request.param


@pytest.fixture(scope="module", params=CASES, ids=lambda case: case["id"])
def actual(request, engine):
    return engine, _load(request.param, engine)


def _raw(capture, native):
    return capture[1] if native else capture[1]["observation"]["raw"]


def _seal(capture, native):
    """Keep wire copies coherent so failures must involve independent custody."""
    _raw(capture, native)["result"] = deepcopy(capture[2])
    if not native:
        capture[1]["observation"]["result"] = deepcopy(capture[2])
        capture[1]["stdout"] = json.dumps(capture[1]["observation"], ensure_ascii=False, allow_nan=False)


def _reject(capture, native):
    _seal(capture, native)
    with pytest.raises(ValueError):
        _guard().validate_capture(*capture, native=native,
                                  approved_node=_trusted_node() if native else None)


def _case(scenario):
    return next(case for case in CASES if case["input"]["scenario"] == scenario)


def test_boundary_manifest_is_the_independently_sealed_eight_case_family():
    path = SOURCE_ROOT / "docs/query_sync_boundaries_literals.json"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == MANIFEST_SHA256
    assert len(CASES) == 8 and _read(path)["acceptancePointsAwarded"] == 0
    assert all(case["covers"] == ["indexing.query-sync.boundaries"] for case in CASES)


def test_actual_full_capture_validates_without_predicting_its_policy(actual):
    native, capture = actual
    assert _guard().validate_capture(*capture, native=native,
                                     approved_node=_trusted_node() if native else None) is True
    assert set(capture[2]["dispatches"]) == set(COUNTERS)


@pytest.mark.parametrize("attack", ["code", "message", "removed-declaration", "encoded-sql"])
def test_absent_native_sql_allows_only_the_declared_deferred_stack_enrichment(attack):
    capture = deepcopy(_load(CASES[0], True))
    raw = _raw(capture, True)
    snapshot = next(row for row in raw["snapshots"] if row.get("exists") is False)
    assert json.loads(snapshot["serializedJSON"])["error"]["stack"] is None
    assert isinstance(snapshot["error"]["stack"], str)
    if attack == "code":
        snapshot["error"]["code"] = "EACCES"
    elif attack == "message":
        snapshot["error"]["message"] += " substituted"
    elif attack == "removed-declaration":
        del snapshot["error"]["stackSerialization"]
    else:
        sealed = json.loads(snapshot["serializedJSON"])
        sealed["dbPath"] += "-other"
        snapshot["serializedJSON"] = json.dumps(sealed)
        snapshot["sha256"] = hashlib.sha256(snapshot["serializedJSON"].encode()).hexdigest()
    _reject(capture, True)


@pytest.mark.parametrize("attack", ["different-owner", "not-original-class", "different-purpose"])
def test_native_public_tool_ownership_is_bound_to_its_actual_original_get(attack):
    capture = deepcopy(_load(CASES[0], True))
    raw = _raw(capture, True)
    tool = next(iter(raw["toolCalls"].values()))
    get = next(row for row in raw["originalGetCalls"]
               if tool["enterSeq"] < row["enterSeq"] < row["returnSeq"] < tool["returnSeq"])
    if attack == "different-owner":
        get["ownerId"] = "borrowed-owner"
    elif attack == "not-original-class":
        get["receiverIsOriginalClass"] = False
    else:
        get["requestedPurpose"] = "maintenance"
    _reject(capture, True)


@pytest.mark.parametrize("field", ["provider", "searches", "syncs", "dispatches", "producerOutcomes", "sources"])
def test_whole_public_boundary_result_cannot_drop_a_field(actual, field):
    _, baseline = actual
    case, _, result = deepcopy(baseline)
    del result[field]
    with pytest.raises(ValueError):
        _guard().validate_result(case, result)


@pytest.mark.parametrize("counter", COUNTERS)
@pytest.mark.parametrize("replacement", [True, -1, 1.5])
def test_public_counts_are_actual_nonnegative_integers(actual, counter, replacement):
    _, baseline = actual
    case, _, result = deepcopy(baseline)
    result["dispatches"][counter] = replacement
    with pytest.raises(ValueError):
        _guard().validate_result(case, result)


@pytest.mark.parametrize("counter", COUNTERS)
def test_resealed_count_requires_original_receiver_qualified_lifetime_receipts(actual, counter):
    native, baseline = actual
    capture = deepcopy(baseline)
    capture[2]["dispatches"][counter] += 1
    _reject(capture, native)


@pytest.mark.parametrize("attack", ["wrong-owner", "wrong-query", "early-return", "different-receiver"])
def test_manager_search_is_an_actual_original_call_of_the_selected_owner(actual, attack):
    native, baseline = actual
    capture = deepcopy(baseline)
    call = _raw(capture, native)["originalSearchCalls"][0]
    if attack == "wrong-owner":
        call["ownerId"] = "borrowed-owner"
    elif attack == "wrong-query":
        if native:
            call["query"] = "another-query"
        else:
            call["arguments"]["0"] = "another-query"
    elif attack == "early-return":
        call["returnSeq"] = call["enterSeq"]
    else:
        call["receiverIsExactObservedOwner"] = False
    _reject(capture, native)


@pytest.mark.parametrize("attack", ["tool-details", "tool-text", "tool-arguments", "tool-order"])
def test_complete_public_payload_retains_the_actual_producing_tool(actual, attack):
    native, baseline = actual
    capture = deepcopy(baseline)
    raw = _raw(capture, native)
    label = next(iter(capture[2]["searches"]))
    call = raw["toolCalls"][label]
    if attack == "tool-details":
        call["envelope"]["details"] = {"provider": "none", "results": []}
    elif attack == "tool-text":
        call["envelope"]["content"][0]["text"] = "{}"
    elif attack == "tool-arguments":
        call["args"]["query"] += " other-input"
    else:
        call["returnSeq"] = call["enterSeq"]
    _reject(capture, native)


@pytest.mark.parametrize("attack", ["status", "typed-flag", "missing-outcome"])
def test_producer_outcomes_are_actual_settlements_of_the_selected_attempts(actual, attack):
    native, baseline = actual
    capture = deepcopy(baseline)
    outcomes = capture[2]["producerOutcomes"]
    assert outcomes, "The selected actual packet must retain its initial producer attempt"
    if attack == "status":
        outcomes[0]["status"] = "rejected" if outcomes[0]["status"] == "fulfilled" else "fulfilled"
    elif attack == "typed-flag":
        outcomes[0]["isTypedConflict"] = not outcomes[0]["isTypedConflict"]
    else:
        outcomes.pop()
    _reject(capture, native)


@pytest.mark.parametrize("scenario", ["joined-force-and-query", "joined-failure-persistent-cold-recovery"])
@pytest.mark.parametrize("attack", ["no-real-transaction", "released-before-pending", "different-index"])
def test_concurrent_requests_require_the_actual_held_owned_sqlite_gate(engine, scenario, attack):
    capture = deepcopy(_load(_case(scenario), engine))
    raw = _raw(capture, engine)
    gate = raw["gates"][0] if engine else raw["sqlGates"][0]
    if attack == "no-real-transaction":
        gate["transactionActiveAtArm" if engine else "inTransaction"] = False
    elif attack == "released-before-pending":
        gate["releaseEnterSeq"] = gate["armReturnSeq"]
    else:
        gate["path"] = str(Path(raw["fixtureBase"]) / "another-index.sqlite")
    _reject(capture, engine)


@pytest.mark.parametrize("scenario", ["joined-failure-persistent-cold-recovery", "warm-failure-natural-retry"])
@pytest.mark.parametrize("attack", ["different-target", "unremoved-fault", "early-removal"])
def test_real_publication_failure_requires_its_owned_physical_fault_receipts(engine, scenario, attack):
    capture = deepcopy(_load(_case(scenario), engine))
    raw = _raw(capture, engine)
    fault = raw["fault"] if engine else raw["faults"][0]
    if attack == "different-target":
        fault["target"] = str(Path(raw["fixtureBase"]) / "another-owned-target")
    elif attack == "unremoved-fault":
        fault["removed"] = False
    else:
        fault["removeEnterSeq"] = fault["armReturnSeq"]
    _reject(capture, engine)


@pytest.mark.parametrize("attack", ["bytes", "hash", "physical-path", "metadata"])
def test_source_bytes_and_metadata_are_the_actual_declared_fixture(actual, attack):
    native, baseline = actual
    capture = deepcopy(baseline)
    raw = _raw(capture, native)
    stages = raw["sourceStages"]
    stage = next(stage for stage in stages.values() if any(row["kind"] == "file" for row in stage["common"]))
    row = next(row for row in stage["common"] if row["kind"] == "file")
    if attack == "bytes":
        row["hex"] = "00"
    elif attack == "hash":
        row["sha256"] = "0" * 64
    elif attack == "metadata":
        row["mtimeMs"] += 1000
    else:
        records = stage["records"] if native else stage["entries"]
        record = next(record for record in records if record["path"] == row["path"])
        record["absolutePath"] = str(Path(raw["fixtureBase"]) / "another-source.md")
    _reject(capture, native)


@pytest.mark.parametrize("scenario", ["typed-conflict-once-retry", "typed-conflict-twice-exhaustion"])
@pytest.mark.parametrize("attack", ["different-revision", "uncommitted-rival", "different-marker"])
def test_typed_conflict_preparation_is_a_real_original_rival_publication(engine, scenario, attack):
    capture = deepcopy(_load(_case(scenario), engine))
    raw = _raw(capture, engine)
    if engine:
        rival = next(row for row in raw["revisionControl"]["rounds"] if row["role"] == "preparation")
        assert rival["reached"] is True
        if attack == "different-revision":
            rival["expectedRevision"] += 1
        elif attack == "uncommitted-rival":
            rival["rivalResult"] = False
        else:
            rival["markerPath"] = "memory/borrowed-marker.md"
    else:
        rival = next(row for row in raw["functionalInterleavings"] if row["role"] == "preparation")
        if attack == "different-revision":
            rival["trigger"]["expectedRevision"] += 1
        elif attack == "uncommitted-rival":
            rival["returned"] = False
        else:
            rival["markerPath"] = "memory/borrowed-marker.md"
    _reject(capture, engine)


@pytest.mark.parametrize("scenario", ["typed-conflict-once-retry", "typed-conflict-twice-exhaustion"])
def test_native_revision_control_cannot_skip_an_actual_eligible_maintenance_publisher(scenario):
    capture = deepcopy(_load(_case(scenario), True))
    raw = _raw(capture, True)
    selected = [row for row in raw["revisionControl"]["rounds"] if row["role"] == "maintenance"]
    assert all(row["reached"] for row in selected), "A selected positive capture must reach every declared Native rival"
    selected[-1]["reached"] = False
    _reject(capture, True)


@pytest.mark.parametrize("attack", ["before-empty-seed", "different-specification", "missing-fixture"])
def test_newer_empty_generation_is_the_actual_owned_metadata_fixture(engine, attack):
    capture = deepcopy(_load(_case("newer-empty-public-refusal-cli-override"), engine))
    raw = _raw(capture, engine)
    fixture = raw["newerFormatFixture"] if engine else raw["metadataFixtures"][0]
    if attack == "before-empty-seed":
        fixture["enterSeq"] = 0
    elif attack == "different-specification":
        fixture["specification"]["version"] += 1
    elif engine:
        del raw["newerFormatFixture"]
    else:
        raw["metadataFixtures"] = []
    _reject(capture, engine)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_actual_pair_custody_does_not_require_matching_engine_policies(case):
    native, sdk = _load(case, True), _load(case, False)
    assert _guard().validate_pair(case, native[1], sdk[1], native[2], sdk[2], approved_node=_trusted_node()) is True
