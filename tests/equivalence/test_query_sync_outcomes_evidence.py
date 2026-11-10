"""Attack genuine current query-sync captures; never manufacture passing raw.

Only reads/JSON decoding are cached. A selected invalid current capture fails
without falling back. Missing actual captures skip and supply no acceptance.
"""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import stat

import pytest

from equivalence.query_sync_outcomes import build_cases
from equivalence import query_sync_outcomes_evidence as evidence

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = Path(os.environ.get("MEMORY_QUERY_SYNC_EVIDENCE_ROOT", ROOT)).resolve()
CASES = build_cases()


@lru_cache(maxsize=128)
def _read_cached(path, size, mtime):
    return json.loads(Path(path).read_text(encoding="utf8"))


def _read(path):
    info = path.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and not path.is_symlink(), path
    return _read_cached(str(path), info.st_size, info.st_mtime_ns)


def _load(case, native):
    roots = (SOURCE_ROOT / ".equivalence-results/query-sync-outcomes",
             SOURCE_ROOT / "work/query-sync" / ("native" if native else "sdk"))
    name = "native-raw.json" if native else "python-raw.json"
    paths = sorted({path for root in roots if root.is_dir() for path in root.rglob(name)},
                   key=lambda path: path.stat().st_mtime_ns, reverse=True)
    for path in paths:
        values = _read(path)
        assert isinstance(values, list) and len(values) == 1, path
        capture = values[0]
        if capture.get("input") != case["input"]:
            continue
        if native:
            context = _read(path.parents[1] / "context.json")
            actor = SOURCE_ROOT / "equivalence/query-sync-outcomes-runtime.mjs"
            approved = [row for row in context["allowedLocal"] if row["path"] == str(actor)]
            if not approved or approved[0]["sha256"] != hashlib.sha256(actor.read_bytes()).hexdigest():
                continue  # Historical actor generation supplies no current credit.
            returned = _read(path.parents[1] / "stdout.json")
            assert returned["ok"] is True and returned["id"] == case["id"], path
            result = returned["result"]
        else:
            assert capture.get("kind") == "query-sync-outcomes-sdk-dispatch", path
            assert capture["exit"] == {"code": 0}, path
            assert capture["observation"]["raw"]["implementationRoot"] == str(SOURCE_ROOT), path
            result = capture["observation"]["result"]
        assert evidence.validate_capture(case, capture, result, native=native) is True
        return case, capture, result
    pytest.skip("No retained current genuine query-sync capture; no acceptance credit")


@pytest.fixture(scope="module", params=[True, False], ids=["native", "sdk"])
def engine(request):
    return request.param


@pytest.fixture(scope="module", params=CASES, ids=lambda case: case["id"])
def actual(request, engine):
    return engine, _load(request.param, engine)


@pytest.fixture(scope="module")
def edit(engine):
    return engine, _load(CASES[3], engine)


def _raw(capture, native):
    return capture[1] if native else capture[1]["observation"]["raw"]


def _seal(capture, native):
    raw = _raw(capture, native)
    raw["result"] = deepcopy(capture[2])
    if not native:
        capture[1]["observation"]["result"] = deepcopy(capture[2])
        capture[1]["stdout"] = json.dumps(capture[1]["observation"], ensure_ascii=False)


def _reject(capture, native):
    _seal(capture, native)
    with pytest.raises(ValueError, match="(?i)query-sync"):
        evidence.validate_capture(*capture, native=native)


def _resnapshot(row):
    original = json.loads(row["serializedJSON"])
    value = {key: row[key] for key in original}
    row["serializedJSON"] = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    row["sha256"] = hashlib.sha256(row["serializedJSON"].encode()).hexdigest()


def _all_sql(raw, native):
    rows = [row for row in raw["snapshots"] if row.get("tables") and "catalog" not in row["label"]]
    if not native:
        rows += [row["pinnedSnapshot"] for row in raw["readAdmissions"]]
    return rows


def _move_block(raw, first, last, before):
    """Move genuine operations and reseal EVERY receipt sequence and time."""
    rows = raw["events"]
    slots = [(row["sequence"], row["atNs"]) for row in rows]
    selected = [row for row in rows if first <= row["sequence"] <= last]
    others = [row for row in rows if row not in selected]
    offset = next(index for index, row in enumerate(others) if row["sequence"] == before)
    reordered = others[:offset] + selected + others[offset:]
    mapping = {row["sequence"]: slot[0] for row, slot in zip(reordered, slots, strict=True)}
    times = dict(slots)
    for row, (sequence, instant) in zip(reordered, slots, strict=True):
        row["sequence"], row["atNs"] = sequence, instant
    raw["events"] = reordered

    def fix(value):
        if isinstance(value, dict):
            for key, item in list(value.items()):
                if (key.endswith("Seq") or key in {"sequence", "acquiredSeq"}) and type(item) is int and item in mapping:
                    value[key] = mapping[item]
                else:
                    fix(item)
            if "startedAtNs" in value and "enterSeq" in value:
                value["startedAtNs"] = times[value["enterSeq"]]
            if "finishedAtNs" in value and "returnSeq" in value:
                value["finishedAtNs"] = times[value["returnSeq"]]
        elif isinstance(value, list):
            for item in value:
                fix(item)
    for key, value in raw.items():
        if key != "events":
            fix(value)


def test_genuine_current_complete_capture_validates(actual):
    native, capture = actual
    assert evidence.validate_capture(*capture, native=native) is True


@pytest.mark.parametrize("attack", ["drop-stage", "source-bytes", "full-stat", "missing-error"])
def test_actual_source_bytes_stats_and_missing_os_receipts_are_required(actual, attack):
    native, baseline = actual
    capture = deepcopy(baseline)
    raw = _raw(capture, native)
    stage = raw["sourceStages"]["afterMutation"]
    records = stage["records" if native else "entries"]
    if attack == "drop-stage":
        raw["sourceStages"].pop("afterFirstClose")
    elif attack == "source-bytes":
        records[0]["hex"] = "00"
    elif attack == "full-stat":
        record = next((row for row in records if row["kind"] == "file"), None)
        if record is None:
            pytest.skip("Actual empty source stage has no stat to mutate")
        record["stat" if native else "statAfter"].pop("size" if native else "st_size")
    else:
        record = next((row for row in records if row["kind"] == "missing"), None)
        if record is None:
            pytest.skip("This genuine source stage has no missing path")
        record["error"]["code" if native else "errno"] = "EPERM" if native else 13
    _reject(capture, native)


@pytest.mark.parametrize("attack", ["drop-table-and-schema", "drop-fts", "wrong-source", "wrong-provenance", "wrong-count"])
def test_all_resealed_sql_copies_must_retain_real_publication_dataflow(edit, attack):
    native, baseline = edit
    capture = deepcopy(baseline)
    raw = _raw(capture, native)
    for row in _all_sql(raw, native):
        tables = row["tables"]
        chunk_table = "memory_index_chunks" if native else "chunks"
        if attack == "drop-table-and-schema":
            table = "memory_index_chunk_provenance"
            tables.pop(table)
            row["schema"] = [entry for entry in row["schema"] if entry["name"] != table]
        elif attack == "drop-fts":
            tables["memory_index_chunks_fts" if native else "chunks_fts"] = []
        elif attack == "wrong-source":
            for chunk in tables[chunk_table]:
                chunk["source"] = "sessions"
        elif attack == "wrong-provenance":
            for provenance in tables["memory_index_chunk_provenance"]:
                provenance["observed_at"] = 1
        else:
            for source in tables["memory_index_sources" if native else "memory_core_index_sources"]:
                source["size"] += 1
        _resnapshot(row)
    _reject(capture, native)


@pytest.mark.parametrize("attack", ["lost-search", "foreign-owner", "changed-options", "lost-envelope-field", "changed-hit-order"])
def test_full_actual_public_tool_and_original_search_are_bound(edit, attack):
    native, baseline = edit
    capture = deepcopy(baseline)
    raw = _raw(capture, native)
    search = next(row for row in raw["originalSearchCalls"] if row["activeTool"] == "first")
    if attack == "lost-search":
        raw["originalSearchCalls"].remove(search)
    elif attack == "foreign-owner":
        search["ownerId"] = "foreign-owner"
    elif attack == "changed-options":
        search["options"]["minScore" if native else "min_score"] = 0.3
    elif attack == "lost-envelope-field":
        raw["toolCalls"]["first"]["envelope"]["details"]["debug"].pop("effectiveMode")
    else:
        search["result"][0]["snippet"] += " forged"
    _reject(capture, native)


@pytest.mark.parametrize("attack", ["close-before-publication", "capture-before-close", "reopen-before-closed-capture"])
def test_coedited_receipts_cannot_move_real_boundaries(edit, attack):
    native, baseline = edit
    capture = deepcopy(baseline)
    raw = _raw(capture, native)
    snapshot = next(row for row in raw["snapshots"] if row["label"] == "after-first-close")
    if native:
        first = raw["ownerNames"]["foreground"]
        close = next(row for row in raw["methodCalls"] if row["method"] == "close" and row["ownerId"] == first)
        acquire = next(row for row in raw["facadeCalls"] if row["label"] == "reopened")
        background = raw["backgroundCalls"][0]
    else:
        close = raw["owners"]["first"]["close"]
        acquire = next(row for row in raw["ownerAcquisitions"] if row["role"] == "reopened")
        background = next(row for row in raw["backgroundCalls"] if row["method"] == "_run_memory_publication")
    if attack == "close-before-publication":
        _move_block(raw, close["returnSeq"], close["returnSeq"], background["returnSeq"])
    elif attack == "capture-before-close":
        _move_block(raw, snapshot["enterSeq"], snapshot["returnSeq"], close["enterSeq"])
    else:
        _move_block(raw, acquire["enterSeq"], acquire["returnSeq"], snapshot["enterSeq"])
    _reject(capture, native)


@pytest.mark.parametrize("attack", ["same-owner", "not-closed", "failed-publication", "fake-empty-db"])
def test_original_lifetime_and_actual_initial_enoent_cannot_be_forged(edit, attack):
    native, baseline = edit
    capture = deepcopy(baseline)
    raw = _raw(capture, native)
    if attack == "same-owner":
        if native:
            raw["ownerNames"]["reopened"] = raw["ownerNames"]["foreground"]
        else:
            raw["owners"]["reopened"]["ownerId"] = raw["owners"]["first"]["ownerId"]
    elif attack == "not-closed":
        if native:
            raw["finalManagerStates"][-1]["closed"] = False
            raw["events"][-1]["finalManagerStates"] = deepcopy(raw["finalManagerStates"])
        else:
            raw["owners"]["first"]["close"]["lifecycle"]["activeOperations"] = 1
    elif attack == "failed-publication":
        if native:
            row = raw["backgroundCalls"][0]
            row["error"] = {"name": "Error", "message": "caught original publisher failure"}
            next(item for item in raw["methodCalls"] if item["id"] == row["id"]).update(error=deepcopy(row["error"]))
        else:
            raw["owners"]["first"]["close"]["lifecycle"]["memoryPublication"]["jobs"][0]["state"] = "failed"
    else:
        row = next(row for row in raw["snapshots"] if row["label"] == "before-first-open")
        row["exists" if native else "absent"] = True if native else False
        row["schema"], row["tables"] = [], {}
        _resnapshot(row)
    _reject(capture, native)


@pytest.mark.parametrize("attack", ["wrong-connection", "no-transaction", "wrong-revision", "wrong-operation", "borrow-final-sql", "worker-token"])
def test_sdk_pinned_actual_reader_and_worker_identity_are_required(attack):
    capture = deepcopy(_load(CASES[3], False))
    raw = _raw(capture, False)
    read = next(row for row in raw["readAdmissions"] if row["activeTool"] == "first")
    pinned = read["pinnedSnapshot"]
    if attack == "wrong-connection":
        pinned["connectionId"] = "foreign-connection"
    elif attack == "no-transaction":
        pinned["inTransactionBefore"] = False
    elif attack == "wrong-revision":
        read["readRevision"] += 1
        pinned["readRevision"] = read["readRevision"]
    elif attack == "wrong-operation":
        pinned["operationId"] = 1
    elif attack == "borrow-final-sql":
        final = next(row for row in raw["snapshots"] if row["label"] == "after-first-close")
        pinned["schema"], pinned["tables"] = deepcopy(final["schema"]), deepcopy(final["tables"])
        pinned["readRevision"] = pinned["tables"]["memory_core_index_sync"][0]["revision"]
        read["readRevision"] = pinned["readRevision"]
    else:
        run = next(row for row in raw["backgroundCalls"] if row["method"] == "_run_memory_publication")
        run["actualWorkerTokenMatches"] = False
    _resnapshot(pinned)
    _reject(capture, False)


@pytest.mark.parametrize("attack", ["missing-enum-as-null", "public-enum", "unknown-enum", "lost-field"])
def test_sdk_private_enum_codec_never_rewrites_public_null_or_missing(attack):
    capture = deepcopy(_load(CASES[3], False))
    raw = _raw(capture, False)
    hit = raw["originalSearchCalls"][0]["result"][0]
    if attack == "missing-enum-as-null":
        assert hit["importance"] == evidence.PRIVATE_MISSING
        hit["importance"] = None
    elif attack == "public-enum":
        capture[2]["searches"]["first"]["debug"]["injected"] = deepcopy(evidence.PRIVATE_MISSING)
    elif attack == "unknown-enum":
        hit["importance"] = {"$sdkPrivate": "UNKNOWN"}
    else:
        hit.pop("_vector_id")
    _reject(capture, False)


@pytest.mark.parametrize("attack", ["lost-get", "unknown-purpose", "wrong-maintenance-parent", "lost-lease", "released-lease", "foreign-worker-db", "forged-close-all"])
def test_native_actual_facade_generation_worker_and_closure_identity(attack):
    capture = deepcopy(_load(CASES[3], True))
    raw = _raw(capture, True)
    if attack == "lost-get":
        raw["originalGetCalls"] = [row for row in raw["originalGetCalls"] if row["activeTool"] != "first"]
    elif attack in {"unknown-purpose", "wrong-maintenance-parent"}:
        getter = next(row for row in raw["originalGetCalls"] if row["requestedPurpose"] == "maintenance")
        getter["requestedPurpose" if attack == "unknown-purpose" else "maintenanceSourceOwnerId"] = "unreviewed"
    elif attack in {"lost-lease", "released-lease"}:
        row = next(row for row in raw["snapshots"] if row.get("methodCallId") and raw["events"][row["enterSeq"] - 1]["activeTool"] == "first")
        active = next(lease for lease in row["coordinationLeases"] if lease["open"] and lease["transactionActive"])
        if attack == "lost-lease":
            row["coordinationLeases"].remove(active)
        else:
            active["transactionActive"] = False
    elif attack == "foreign-worker-db":
        row = next(row for row in raw["workerDispatches"] if row["activeTool"] == "first" and row["message"].get("input", {}).get("kind") == "keyword")
        row["message"]["input"]["databasePath"] += ".foreign"
    else:
        raw["finalManagerStates"][-1]["purpose"] = "unknown"
        raw["events"][-1]["finalManagerStates"] = deepcopy(raw["finalManagerStates"])
    _reject(capture, True)


@pytest.mark.parametrize("attack", ["decoded-only", "wire-and-decoded-wrong-hash", "wire-and-decoded-noop-operation"])
def test_native_actual_v8_bytes_and_publication_parameters_are_semantic(attack):
    capture = deepcopy(_load(CASES[3], True))
    raw = _raw(capture, True)
    row = next(row for row in raw["workerDispatches"] if row.get("decodedSerialized", {}).get("input", {}).get("value", {}).get("type") == "stage.start")
    value = row["decodedSerialized"]["input"]["value"]
    original = value["input"]["header"]["entry"]["hash"]
    changed = "0" * len(original)
    value["input"]["header"]["entry"]["hash"] = changed
    if attack == "wire-and-decoded-noop-operation":
        value["input"]["header"]["entry"]["hash"] = original
        original = value["input"]["operation"]
        changed = "0" * len(original)
        value["input"]["operation"] = changed
    if attack != "decoded-only":
        wire = row["message"]["input"]
        data = bytes.fromhex(wire["hex"])
        assert data.count(original.encode()) == 1
        wire["hex"] = data.replace(original.encode(), changed.encode()).hex()
        row["decodedSerialized"]["input"]["bytesSha256"] = hashlib.sha256(bytes.fromhex(wire["hex"])).hexdigest()
    _reject(capture, True)


def test_no_invented_fresh_first_result_or_samehash_mtime_requirement():
    for native in (True, False):
        case, raw, result = _load(CASES[3], native)
        assert "old amber" in result["searches"]["first"]["results"][0]["snippet"]
        assert "new violet" in result["searches"]["reopened"]["results"][0]["snippet"]
        assert evidence.validate_capture(case, raw, result, native=native)
        case, capture, result = _load(CASES[6], native)
        observed = capture if native else capture["observation"]["raw"]
        sql = next(row for row in observed["snapshots"] if row["label"] == "after-first-close")
        sources = sql["tables"]["memory_index_sources" if native else "memory_core_index_sources"]
        stored = next(row for row in sources if row["path"].endswith("touched.md"))
        real = next(row for row in result["sources"]["afterFirstClose"] if row["path"].endswith("touched.md"))
        assert stored["mtime"] == case["input"]["initialSourceMtimeMs"]
        assert real["mtimeMs"] == case["input"]["sourceMutation"]["mtimeMs"]
        assert evidence.validate_capture(case, capture, result, native=native)
