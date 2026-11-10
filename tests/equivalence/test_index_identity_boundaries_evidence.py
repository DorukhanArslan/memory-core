"""Semantic attacks on genuine retained identity-boundary engine captures.

No successful capture is hand-built. Every baseline first validates its complete
custody. Missing retained captures skip without credit; the newest selected
current capture that is invalid fails rather than falling back to a success.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import stat

import pytest

from equivalence.index_identity_boundaries import build_cases

ROOT = Path(__file__).resolve().parents[2]
CASES = build_cases()
RETAINED = (
    ROOT / ".equivalence-results/index-identity-boundaries",
    ROOT / "work/index-identity-boundaries/native",
    ROOT / "work/index-identity-boundaries/sdk",
)


def _guard():
    from equivalence import index_identity_boundaries_evidence
    return index_identity_boundaries_evidence


def _read(path):
    info = path.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and not path.is_symlink(), path
    return json.loads(path.read_text(encoding="utf8"))


def _paths(name):
    return sorted({path for root in RETAINED if root.is_dir() for path in root.rglob(name)},
                  key=lambda path: path.stat().st_mtime_ns, reverse=True)


def _load(case, native):
    for path in _paths("native-raw.json" if native else "python-raw.json"):
        values = _read(path)
        if not isinstance(values, list) or len(values) != 1:
            continue
        capture = values[0]
        if capture.get("input") != case["input"]:
            continue
        if native:
            context_path, stdout_path = path.parents[1] / "context.json", path.parents[1] / "stdout.json"
            if not context_path.is_file() or not stdout_path.is_file():
                continue
            context = _read(context_path)
            actor = ROOT / "equivalence/index-identity-boundaries-runtime.mjs"
            approved = [row for row in context.get("allowedLocal", []) if row.get("path") == str(actor)]
            if len(approved) != 1 or approved[0]["sha256"] != hashlib.sha256(actor.read_bytes()).hexdigest():
                continue  # Another actor generation remains historical, not current replay credit.
            returned = _read(stdout_path)
            assert returned.get("ok") is True and returned["id"] == case["id"], stdout_path
            result = returned["result"]
        else:
            if capture.get("kind") != "index-identity-boundaries-sdk-dispatch":
                continue
            assert capture["exit"]["code"] == 0, path
            assert capture["observation"]["raw"]["implementationRoot"] == str(ROOT), path
            result = capture["observation"]["result"]
        assert _guard().validate_capture(case, capture, result, native=native) is True
        return case, capture, result
    pytest.skip("No retained current genuine identity-boundary capture; no acceptance credit")


@pytest.fixture(scope="module", params=[True, False], ids=["native", "sdk"])
def engine(request):
    return request.param


@pytest.fixture(scope="module", params=CASES, ids=lambda value: value["id"])
def actual(request, engine):
    return engine, _load(request.param, engine)


@pytest.fixture(scope="module")
def matching(engine):
    return engine, _load(CASES[0], engine)


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
    with pytest.raises(ValueError, match="(?i)identity"):
        _guard().validate_capture(*capture, native=native)


def _resnapshot(row):
    value = {key: row[key] for key in ("dbPath", "schema", "tables")}
    row["serializedJSON"] = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    row["sha256"] = hashlib.sha256(row["serializedJSON"].encode()).hexdigest()


def _move_block(raw, first, last, before):
    """Preserve valid chronology slots and all dependent receipt references."""
    rows = raw["events"]
    slots = [(row["sequence"], row["atNs"]) for row in rows]
    selected = [row for row in rows if first <= row["sequence"] <= last]
    others = [row for row in rows if row not in selected]
    offset = next(index for index, row in enumerate(others) if row["sequence"] == before)
    reordered = others[:offset] + selected + others[offset:]
    mapping = {row["sequence"]: sequence for row, (sequence, _) in zip(reordered, slots, strict=True)}
    times = {sequence: instant for sequence, instant in slots}
    for row, (sequence, instant) in zip(reordered, slots, strict=True):
        row["sequence"], row["atNs"] = sequence, instant
    raw["events"] = reordered

    def fix(value):
        if isinstance(value, dict):
            for key, item in list(value.items()):
                if key in {"enterSeq", "returnSeq", "sequence"} and type(item) is int and item in mapping:
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


def test_genuine_complete_capture_validates(actual):
    native, capture = actual
    assert _guard().validate_capture(*capture, native=native) is True


@pytest.mark.parametrize("attack", ["missing-status", "duplicate-status-selector", "after-as-before",
                                  "eager-knowledge", "different-status-owner"])
def test_two_actual_pre_query_statuses_are_not_borrowed(actual, attack):
    native, original = actual
    capture = deepcopy(original)
    raw = _raw(capture, native)
    selected = raw["diagnosticStatusCalls"]["searchOwner"]
    row = next(item for item in raw["statusCalls"] if item["id"] == selected[0])
    if attack == "missing-status":
        raw["statusCalls"].remove(row)
    elif attack == "duplicate-status-selector":
        selected[1] = selected[0]
    elif attack == "after-as-before":
        selected[0] = raw["diagnosticStatusCalls"]["afterQuery"]
    elif attack == "eager-knowledge":
        raw["events"][row["enterSeq"] - 1]["providerInitialized"] = True
    else:
        row["ownerId"] = raw["owners"]["producer"]["ownerId"]
    _reject(capture, native)


@pytest.mark.parametrize("attack", ["missing-snapshot", "duplicate-snapshot", "publication-rewrite",
                                  "metadata-row-removed", "wrong-database"])
def test_independent_physical_sql_is_required_and_not_only_a_hash(actual, attack):
    native, original = actual
    capture = deepcopy(original)
    raw = _raw(capture, native)
    row = next(item for item in raw["snapshots"] if item["label"] == "search-owner-after-read-2")
    if attack == "missing-snapshot":
        raw["snapshots"].remove(row)
    elif attack == "duplicate-snapshot":
        raw["snapshots"].append(deepcopy(row))
    elif attack == "publication-rewrite":
        name = next(name for name, rows in row["tables"].items()
                    if name != "memory_index_meta" and rows)
        row["tables"][name][0][next(iter(row["tables"][name][0]))] = "changed-after-status"
        _resnapshot(row)
    elif attack == "metadata-row-removed":
        row["tables"].pop("memory_index_meta")
        row["schema"] = [item for item in row["schema"] if item["name"] != "memory_index_meta"]
        _resnapshot(row)
    else:
        row["dbPath"] += ".foreign"
        _resnapshot(row)
    _reject(capture, native)


@pytest.mark.parametrize("attack", ["coedited-table-omission", "empty-published-chunks"])
def test_all_snapshot_sql_projection_cannot_invent_a_real_published_seed(actual, attack):
    native, original = actual
    capture = deepcopy(original)
    chunk_table = "memory_index_chunks" if native else "chunks"
    for row in _raw(capture, native)["snapshots"]:
        if attack == "coedited-table-omission":
            removed = {name for name in row["tables"] if "chunk" in name}
            row["tables"] = {name: rows for name, rows in row["tables"].items() if name not in removed}
            row["schema"] = [item for item in row["schema"] if item["name"] not in removed
                             and item["tbl_name"] not in removed]
        else:
            row["tables"][chunk_table] = []
        _resnapshot(row)
    _reject(capture, native)


@pytest.mark.parametrize("attack", ["uncommitted", "wrong-fixture", "wrong-row", "wrong-change-count",
                                  "wrong-sql-arguments"])
def test_actual_declared_metadata_transaction_remains_bound(actual, attack):
    native, original = actual
    capture = deepcopy(original)
    mutation = _raw(capture, native)["fixtureMutation"]
    if attack == "uncommitted":
        mutation["committed"] = False
    elif attack == "wrong-fixture":
        mutation["specification"] = {"kind": "none", "injected": True}
    elif attack == "wrong-row":
        mutation["after"] = '{"fabricated":true}'
    elif attack == "wrong-change-count":
        mutation["sqliteChanges"] = bool(mutation["sqliteChanges"])
    else:
        mutation["parameters"] = ["another metadata key"]
    _reject(capture, native)


@pytest.mark.parametrize("attack", ["missing-search", "foreign-search-owner", "wrong-options",
                                  "lost-real-hits", "receiver-substitution"])
def test_actual_public_tool_consumes_its_original_same_owner_search(actual, attack):
    native, original = actual
    capture = deepcopy(original)
    raw = _raw(capture, native)
    search = next(item for item in raw["originalSearchCalls"] if item["activeTool"] == "seed")
    if attack == "missing-search":
        raw["originalSearchCalls"].remove(search)
    elif attack == "foreign-search-owner":
        search["ownerId"] = raw["owners"]["searchOwner"]["ownerId"]
    elif attack == "wrong-options":
        search["options"]["maxResults" if native else "max_results"] = 200
    elif attack == "lost-real-hits":
        search["result"] = []
    else:
        search["receiverIsExactObservedOwner"] = False
    _reject(capture, native)


def test_query_cannot_move_before_its_last_status_even_with_resealed_receipts(matching):
    native, original = matching
    capture = deepcopy(original)
    raw = _raw(capture, native)
    query = raw["toolCalls"]["query"]
    second = raw["diagnosticStatusCalls"]["searchOwner"][1]
    observed = next(item for item in raw["statusCalls"] if item["id"] == second)
    _move_block(raw, query["enterSeq"], query["returnSeq"], observed["enterSeq"])
    _reject(capture, native)


@pytest.mark.parametrize("attack", ["missing-owner", "reused-owner", "unclosed-owner", "hidden-manual-publication"])
def test_setup_inspector_and_query_owners_keep_actual_lifetimes(actual, attack):
    native, original = actual
    capture = deepcopy(original)
    raw = _raw(capture, native)
    if attack == "missing-owner":
        raw["owners"].pop("inspection")
    elif attack == "reused-owner":
        raw["owners"]["searchOwner"]["ownerId"] = raw["owners"]["producer"]["ownerId"]
    elif attack == "unclosed-owner":
        raw["owners"]["inspection"]["close"]["closed"] = False
    else:
        event = deepcopy(next(row for row in raw["events"] if row["event"] in {"original-sync-enter", "original-publication-enter"}))
        event.update(sequence=len(raw["events"]) + 1, atNs=str(int(raw["events"][-1]["atNs"]) + 1))
        raw["events"].append(event)
    _reject(capture, native)


@pytest.mark.parametrize("attack", ["source-change", "public-projection", "tool-carrier-change"])
def test_complete_source_public_and_original_carriers_remain_linked(actual, attack):
    native, original = actual
    capture = deepcopy(original)
    raw = _raw(capture, native)
    if attack == "source-change":
        raw["sourceAfter"]["text"] += "changed"
    elif attack == "public-projection":
        capture[2]["seedSearch"].pop("debug")
    else:
        raw["toolCalls"]["seed"]["envelope"]["content"][0]["text"] = '{}'
    _reject(capture, native)


def test_native_intrinsic_maintenance_keeps_source_owner_without_becoming_public_owner():
    original = _load(CASES[0], True)
    raw = _raw(original, True)
    maintenance = [row for row in raw["originalGetCalls"] if row["requestedPurpose"] == "maintenance"]
    if not maintenance:
        pytest.skip("This genuine matching scheduling outcome has no intrinsic maintenance receipt; no credit")
    capture = deepcopy(original)
    row = next(item for item in _raw(capture, True)["originalGetCalls"] if item["requestedPurpose"] == "maintenance")
    row["maintenanceSourceOwnerId"] = _raw(capture, True)["owners"]["inspection"]["ownerId"]
    _reject(capture, True)


@pytest.mark.parametrize("attack", ["scalar-success", "coedited-rows", "missing-owner", "wrong-purpose"])
def test_native_close_all_return_requires_actual_every_returned_owner_closed(attack):
    capture = deepcopy(_load(CASES[0], True))
    raw = _raw(capture, True)
    returned = next(row for row in raw["events"] if row["event"] == "runtime-close-all-return")
    if attack == "scalar-success":
        raw["finalManagerStates"][-1]["closed"] = False
    elif attack == "coedited-rows":
        raw["finalManagerStates"][-1]["closed"] = False
        returned["finalManagerStates"] = deepcopy(raw["finalManagerStates"])
    elif attack == "missing-owner":
        raw["finalManagerStates"].pop()
        returned["finalManagerStates"] = deepcopy(raw["finalManagerStates"])
    else:
        raw["finalManagerStates"][-1]["purpose"] = "unreviewed-purpose"
        returned["finalManagerStates"] = deepcopy(raw["finalManagerStates"])
    assert raw["allManagersClosed"] is True
    _reject(capture, True)


@pytest.mark.parametrize("attack", ["maintenance-before-source-acquisition", "close-all-before-final-sql"])
def test_native_lifecycle_cannot_move_before_its_actual_dependencies_with_resealed_receipts(attack):
    capture = deepcopy(_load(CASES[0], True))
    raw = _raw(capture, True)
    if attack == "maintenance-before-source-acquisition":
        children = [row for row in raw["originalGetCalls"] if row["requestedPurpose"] == "maintenance"]
        if not children:
            pytest.skip("This genuine scheduling outcome has no maintenance getter; no acceptance credit")
        child = children[0]
        parent = next(row for row in raw["originalGetCalls"]
                      if row["ownerId"] == child["maintenanceSourceOwnerId"]
                      and row["phase"] in {"producer-acquisition", "search-owner-acquisition"})
        _move_block(raw, child["enterSeq"], child["returnSeq"], parent["enterSeq"])
    else:
        entered = next(row for row in raw["events"] if row["event"] == "runtime-close-all-enter")
        snapshot = next(row for row in raw["snapshots"] if row["label"] == "search-owner-after-close")
        _move_block(raw, entered["sequence"], entered["sequence"], snapshot["enterSeq"])
    _reject(capture, True)


@pytest.mark.parametrize("attack", ["null-for-missing", "private-in-public", "unknown-private-type", "lost-private-field"])
def test_sdk_private_missing_enum_cannot_rewrite_null_or_public_results(attack):
    capture = deepcopy(_load(CASES[0], False))
    raw = _raw(capture, False)
    hit = raw["originalSearchCalls"][0]["result"][0]
    if attack == "null-for-missing":
        assert hit["importance"] == {"$sdkPrivate": "HYBRID_METADATA_MISSING"}
        hit["importance"] = None
    elif attack == "private-in-public":
        capture[2]["seedSearch"]["debug"]["injected"] = {"$sdkPrivate": "HYBRID_METADATA_MISSING"}
    elif attack == "unknown-private-type":
        hit["importance"] = {"$sdkPrivate": "UNKNOWN_ENUM"}
    else:
        hit.pop("_vector_id")
    _reject(capture, False)


@pytest.mark.parametrize("attack", ["missing-get", "foreign-default", "getter-receiver", "getter-config"])
def test_native_public_default_getter_uses_exact_sampled_owner(attack):
    capture = deepcopy(_load(CASES[0], True))
    raw = _raw(capture, True)
    row = next(item for item in raw["originalGetCalls"]
               if item["activeTool"] == "query" and item["requestedPurpose"] == "default")
    if attack == "missing-get":
        raw["originalGetCalls"].remove(row)
    elif attack == "foreign-default":
        row["ownerId"] = raw["owners"]["producer"]["ownerId"]
    elif attack == "getter-receiver":
        row["receiverIsOriginalClass"] = False
    else:
        row["config"]["memory"]["backend"] = "unreviewed-backend"
    _reject(capture, True)


def test_native_getter_cannot_hide_maintenance_behind_an_undeclared_purpose():
    capture = deepcopy(_load(CASES[0], True))
    raw = _raw(capture, True)
    rows = [row for row in raw["originalGetCalls"] if row["requestedPurpose"] == "maintenance"]
    if not rows:
        pytest.skip("This genuine scheduling outcome has no maintenance getter; no acceptance credit")
    rows[0]["requestedPurpose"] = "unreviewed-purpose"
    _reject(capture, True)


@pytest.mark.parametrize("attack", ["binding-owner", "binding-status", "binding-runtime"])
def test_sdk_public_factory_binding_is_actual(attack):
    capture = deepcopy(_load(CASES[0], False))
    raw = _raw(capture, False)
    row = next(item for item in raw["toolBindings"] if item["label"] == "query")
    if attack == "binding-owner":
        row["ownerId"] = raw["owners"]["producer"]["ownerId"]
    elif attack == "binding-status":
        row["statusIsObservedOwnerStatus"] = False
    else:
        row["runtimeIdentityIsExactOwner"] = False
    _reject(capture, False)
