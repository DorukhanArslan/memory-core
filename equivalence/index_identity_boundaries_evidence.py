"""Actual pre-query diagnostics and first-query custody for frozen identities.

This validator compares the declared complete indexIdentity/result interface.
Whole engine statuses, original factory/tool returns and physical SQL remain
custody. It does not claim full status API or binary database interchange,
semantic provider initialization, or absence of internal speculative SQL reads.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from equivalence.host_turn_barrier_evidence import _same, require
from equivalence.index_identity_boundaries import validate_case

ROOT = Path(__file__).resolve().parents[1]
META_KEY = "memory_index_meta_v1"
SNAPSHOT_LABELS = (
    "seed-after-publication", "seed-after-search", "seed-after-close",
    "metadata-fixture-before", "metadata-fixture-after",
    "inspection-before-open", "inspection-after-open", "inspection-after-read-1",
    "inspection-after-read-2", "inspection-after-close", "search-owner-before-open",
    "search-owner-after-open", "search-owner-after-read-1", "search-owner-after-read-2",
    "search-owner-after-query", "search-owner-after-close",
)
REPAIRED = {
    "index-identity-boundaries-missing-metadata", "index-identity-boundaries-malformed-metadata",
    "index-identity-boundaries-older-provenance", "index-identity-boundaries-older-chunker-only",
    "index-identity-boundaries-older-chunker-scope-incompatible",
}
VALID_QUERY = REPAIRED | {"index-identity-boundaries-matching"}
NEWER = {
    "index-identity-boundaries-newer-provenance-older-chunker",
    "index-identity-boundaries-newer-chunker-older-provenance",
}


def _one(rows, predicate, message):
    found = [row for row in rows if predicate(row)]
    require(len(found) == 1, message)
    return found[0]


def _finite(value):
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_finite(item) for item in value.values())
    if isinstance(value, list):
        return all(_finite(item) for item in value)
    return True


def _source(value):
    text = value["files"]["MEMORY.md"]
    return {"path": "MEMORY.md", "kind": "file", "text": text, "hex": text.encode().hex()}


def _diagnostic(value):
    require(isinstance(value, dict) and value.get("status") in {"valid", "missing", "mismatched"}
            and _finite(value), "identity complete diagnostic is missing or malformed")
    if value["status"] == "valid":
        require(set(value) == {"status"}, "identity valid diagnostic has reassigned fields")
    else:
        require(isinstance(value.get("reason"), str) and bool(value["reason"])
                and value.get("owner") in {"openclaw", "configuration"}
                and isinstance(value.get("code"), str) and bool(value["code"]),
                "identity diagnostic lost its actual reason, owner or code")


def _search_result(value, source, *, positive):
    require(isinstance(value, dict) and isinstance(value.get("results"), list) and _finite(value),
            "identity complete actual search result is missing or nonfinite")
    if positive:
        require(value["results"] and value.get("provider") == "none" and value.get("citations") == "off"
                and not value.get("unavailable") and not value.get("disabled"),
                "identity real positive query control did not return an available source")
        for hit in value["results"]:
            require(isinstance(hit, dict) and hit.get("path") == source["path"]
                    and hit.get("source") == "memory" and hit.get("corpus") == "memory"
                    and type(hit.get("startLine")) is int and type(hit.get("endLine")) is int
                    and 0 < hit["startLine"] <= hit["endLine"]
                    and isinstance(hit.get("snippet"), str) and hit["snippet"]
                    and isinstance(hit.get("score"), (int, float)) and not isinstance(hit["score"], bool),
                    "identity actual positive result is detached from its source/range")
            require(hit["snippet"].strip() in source["text"],
                    "identity query snippet was not derived from actual unchanged source bytes")
        debug = value.get("debug")
        require(isinstance(debug, dict) and _same(debug.get("hits"), len(value["results"]))
                and _same(debug.get("withheldHits"), 0),
                "identity actual search debug carrier lost hit accounting")
    else:
        require(value["results"] == [] and value.get("disabled") is True
                and value.get("unavailable") is True
                and all(isinstance(value.get(key), str) and value[key]
                        for key in ("error", "warning", "action"))
                and isinstance(value.get("debug"), dict),
                "identity actual refusal lost its complete error/warning/action carrier")


def _validate_result(case, result):
    validate_case(case)
    require(isinstance(result, dict)
            and set(result) == {"provider", "seedSearch", "diagnostics", "search", "source"}
            and result["provider"] == "none" and _same(result["source"], _source(case["input"])),
            "identity public result is incomplete or reassigned to another source/profile")
    diag = result["diagnostics"]
    require(isinstance(diag, dict) and set(diag) == {"inspection", "searchOwner", "afterQuery"}
            and all(isinstance(diag[key], list) and len(diag[key]) == 2
                    for key in ("inspection", "searchOwner")),
            "identity public diagnostics omit an actual pre-query observation")
    for item in diag["inspection"] + diag["searchOwner"] + [diag["afterQuery"]]:
        _diagnostic(item)
    require(_same(diag["inspection"][0], diag["inspection"][1])
            and _same(diag["searchOwner"][0], diag["searchOwner"][1]),
            "identity two query-free diagnostic calls changed their actual result")
    require(_same(diag["inspection"][0], diag["searchOwner"][0]),
            "identity same metadata/unknown phase produced reassigned owner diagnostics")
    _search_result(result["seedSearch"], result["source"], positive=True)
    _search_result(result["search"], result["source"], positive=case["id"] in VALID_QUERY)
    _case_diagnostics(case, diag)
    return True


def _case_diagnostics(case, diag):
    """Falsifiable declared controls; complete outputs still come from originals."""
    before = diag["inspection"] + diag["searchOwner"]
    name = case["id"].removeprefix("index-identity-boundaries-")
    if name in {"matching", "provider-key-only"}:
        require(all(_same(item, {"status": "valid"}) for item in before),
                "identity query-free provider knowledge was borrowed from an initialized owner")
    elif name in {"missing-metadata", "malformed-metadata"}:
        require(all(item.get("status") == "missing" and item.get("code") == "metadata_missing"
                    and item.get("owner") == "openclaw" for item in before),
                "identity missing/malformed metadata bypassed its actual parse diagnostic")
    elif case["id"] in NEWER:
        code = "provenance_version" if name.startswith("newer-provenance") else "chunking_version"
        require(all(item.get("status") == "mismatched" and item.get("owner") == "openclaw"
                    and item.get("code") == code and item.get("versionOrder") == "newer" for item in before),
                "identity newer-format priority was replaced by an older/configuration decision")
    elif case["id"] in REPAIRED:
        code = "provenance_version" if name == "older-provenance" else "chunking_version"
        require(all(item.get("status") == "mismatched" and item.get("owner") == "openclaw"
                    and item.get("code") == code and item.get("versionOrder") == "older" for item in before),
                "identity old-format diagnostic lost its true owner/version priority")
        require(all((item.get("chunkingVersionOnly") is True) == (name == "older-chunker-only") for item in before),
                "identity old-chunker compatibility flag hid an incompatible scope")
    else:
        codes = {"model-only": "model", "provider-only": "provider", "sources-only": "sources",
                 "scope-only": "scope", "chunk-tokens-only": "chunking",
                 "chunk-overlap-only": "chunking", "tokenizer-only": "fts_tokenizer"}
        require(all(item.get("status") == "mismatched" and item.get("owner") == "configuration"
                    and item.get("code") == codes[name] for item in before),
                "identity actual configuration diagnostic was dropped or reassigned")
    after = diag["afterQuery"]
    if case["id"] in VALID_QUERY:
        require(_same(after, {"status": "valid"}), "identity actual successful query did not establish valid metadata")
    elif name == "provider-key-only":
        require(after.get("status") == "mismatched" and after.get("owner") == "configuration"
                and after.get("code") == "provider_settings",
                "identity actual first-query provider-key gate was bypassed")
    else:
        require(all(_same(after, item) for item in before),
                "identity actual refused first query changed its unsupported diagnostic")


def _chronology(raw):
    rows = raw["events"]
    require(isinstance(rows, list) and rows, "identity lifecycle chronology is absent")
    require([row["sequence"] for row in rows] == list(range(1, len(rows) + 1))
            and all(type(row["sequence"]) is int and isinstance(row["event"], str)
                    and isinstance(row["atNs"], str) and row["atNs"].isdigit() for row in rows),
            "identity lifecycle sequence was removed, duplicated or relabelled")
    instants = [int(row["atNs"]) for row in rows]
    require(instants == sorted(instants) and instants[0] > 0,
            "identity lifecycle monotonic observations were reordered")
    allowed = {"source-fixture-finished", "original-get-enter", "original-get-return",
               "original-status-enter", "original-status-return", "original-search-enter",
               "original-search-return", "original-close-enter", "original-close-return",
               "original-sync-enter", "original-sync-return", "actual-tool-enter", "actual-tool-return",
               "physical-sql-read-enter", "physical-sql-read-return", "metadata-fixture-enter",
               "metadata-fixture-return", "original-open-enter", "original-open-return",
               "original-publication-enter", "original-publication-return", "actual-tool-binding",
               "runtime-close-all-enter", "runtime-close-all-return"}
    require(all(row["event"] in allowed for row in rows), "identity lifecycle added an unreviewed operation")
    return {row["sequence"]: row for row in rows}


def _interval(row, events, entered, returned, message):
    start, end = row["enterSeq"], row["returnSeq"]
    require(type(start) is type(end) is int and start < end
            and events[start]["event"] == entered and events[end]["event"] == returned,
            message)
    if "startedAtNs" in row:
        require(row["startedAtNs"] == events[start]["atNs"]
                and row["finishedAtNs"] == events[end]["atNs"], message)
    return start, end


def _event(events, name, predicate=lambda row: True):
    return _one(list(events.values()), lambda row: row["event"] == name and predicate(row),
                f"identity lifecycle lacks unique actual {name} receipt")


def _snapshot_map(raw, events):
    rows = raw["snapshots"]
    require(isinstance(rows, list) and [row["label"] for row in rows] == list(SNAPSHOT_LABELS),
            "identity actual independent SQL snapshots are missing, duplicated or reordered")
    snapshots = {}
    previous = 0
    for row in rows:
        start, end = _interval(row, events, "physical-sql-read-enter", "physical-sql-read-return",
                               "identity physical SQL snapshot interval was reassigned")
        require(start > previous and events[start]["label"] == row["label"]
                and events[end]["label"] == row["label"],
                "identity physical SQL snapshot does not belong to its actual capture")
        previous = end
        require(isinstance(row["dbPath"], str) and Path(row["dbPath"]).is_absolute()
                and Path(row["dbPath"]).is_relative_to(Path(raw["fixtureBase"]))
                and isinstance(row["schema"], list) and row["schema"]
                and isinstance(row["tables"], dict) and row["tables"],
                "identity physical SQL snapshot is absent or outside its actual owned database")
        decoded = json.loads(row["serializedJSON"])
        require(_same(decoded, {key: row[key] for key in ("dbPath", "schema", "tables")})
                and hashlib.sha256(row["serializedJSON"].encode()).hexdigest() == row["sha256"],
                "identity complete SQL snapshot bytes/hash were detached from its actual rows")
        table_names = {entry["name"] for entry in row["schema"] if entry["type"] == "table"}
        require(set(row["tables"]) == table_names and "memory_index_meta" in table_names
                and all(isinstance(items, list) and all(isinstance(item, dict) for item in items)
                        for items in row["tables"].values()),
                "identity SQL snapshot omitted actual schema tables or their complete rows")
        snapshots[row["label"]] = row
    require(len({row["dbPath"] for row in rows}) == 1,
            "identity SQL snapshots borrowed another database")
    return snapshots


def _sql_state(row):
    return {key: row[key] for key in ("schema", "tables")}


def _published_sql(case, result, snapshots, *, native):
    """Bind real publication rows, independently of snapshot self-consistency.

    Table names come from Native memory-schema and SDK sqlite_store/publication.
    These sixteen inputs publish one small file. We authenticate that actual
    source/chunk and its seed-hit range; we do not recreate either chunker.
    """
    chunk_table = "memory_index_chunks" if native else "chunks"
    source_table = "memory_index_sources" if native else "memory_core_index_sources"
    state_table = "memory_index_state" if native else "memory_core_index_sync"
    chunk_fts = "memory_index_chunks_fts" if native else "chunks_fts"
    path_fts = "memory_index_paths_fts" if native else "paths_fts"
    required = {chunk_table, source_table, state_table, "memory_index_meta",
                "memory_index_chunk_provenance", "memory_index_chunk_recall_metadata"}
    if not native:
        required |= {"memory_index_chunk_details", "memory_embedding_cache"}
    for prefix in (chunk_fts, path_fts):
        required |= {prefix + suffix for suffix in ("", "_config", "_content", "_data", "_docsize", "_idx")}
    source = result["source"]
    digest = hashlib.sha256(bytes.fromhex(source["hex"])).hexdigest()
    for snapshot in snapshots.values():
        tables = snapshot["tables"]
        require(required <= set(tables),
                "identity physical capture omitted known engine publication/state/provenance/FTS tables")
        require(len(tables[chunk_table]) == len(tables[source_table]) == 1,
                "identity actual one-source publication lost its physical source or chunk row")
        chunk, published_source = tables[chunk_table][0], tables[source_table][0]
        require(chunk["path"] == published_source["path"] == source["path"]
                and chunk["source"] == published_source["source"] == "memory"
                and chunk["text"] == source["text"]
                and published_source["hash"] == digest
                and _same(published_source["size"], len(bytes.fromhex(source["hex"])))
                and _same(published_source["mtime"], case["input"]["sourceMtimeMs"]),
                "identity physical source/chunk bytes are detached from the unchanged real source")
        for hit in result["seedSearch"]["results"]:
            require(chunk["path"] == hit["path"] and _same(chunk["start_line"], hit["startLine"])
                    and _same(chunk["end_line"], hit["endLine"])
                    and hit["snippet"].strip() in chunk["text"],
                    "identity actual positive seed hit has no corresponding published SQL chunk/range")
        require(len(tables[chunk_fts]) == len(tables[path_fts]) == 1
                and tables[chunk_fts][0]["id"] == chunk["id"]
                and tables[chunk_fts][0]["text"] == chunk["text"]
                and _same(tables[path_fts][0], {"path": source["path"], "source": "memory"}),
                "identity original published body/path FTS rows were removed or changed")
        for name in ("memory_index_chunk_provenance", "memory_index_chunk_recall_metadata"):
            require(len(tables[name]) == 1 and tables[name][0]["chunk_id"] == chunk["id"],
                    "identity original chunk provenance/recall SQL rows were removed or reassigned")
        require(len(tables[state_table]) == 1 and _same(tables[state_table][0]["id"], 1)
                and type(tables[state_table][0]["revision"]) is int,
                "identity actual publication revision state row was removed or malformed")
        if native:
            require(chunk["hash"] == digest and chunk["model"] == "fts-only",
                    "native identity actual published chunk hash/model was replaced")
        else:
            details = tables["memory_index_chunk_details"]
            require(len(details) == 1 and details[0]["chunk_id"] == chunk["id"]
                    and details[0]["hash"] == digest and details[0]["model"] == "fts-only"
                    and _same(published_source["chunk_count"], 1),
                    "SDK identity actual published chunk details/hash/model were removed or changed")


def _meta_row(snapshot):
    found = [row["value"] for row in snapshot["tables"]["memory_index_meta"] if row.get("key") == META_KEY]
    require(len(found) <= 1, "identity physical metadata row was duplicated")
    return found[0] if found else None


def _mutation(case, raw, events, snapshots):
    mutation = raw["fixtureMutation"]
    expected = case["input"]["metadataMutation"]
    require(_same(mutation["specification"], expected) and mutation["committed"] is True
            and mutation["dbPath"] == snapshots["metadata-fixture-before"]["dbPath"],
            "identity metadata fixture differs from its independent frozen transaction")
    start, end = _interval(mutation, events, "metadata-fixture-enter", "metadata-fixture-return",
                           "identity metadata fixture transaction interval was reassigned")
    before, after = snapshots["metadata-fixture-before"], snapshots["metadata-fixture-after"]
    require(before["returnSeq"] < start < end < after["enterSeq"]
            and _same(_meta_row(before), mutation["before"])
            and _same(_meta_row(after), mutation["after"]),
            "identity fixture transaction does not match actual before/after SQL rows")
    baseline = json.loads(mutation["before"])
    require(isinstance(baseline, dict) and _same(baseline.get("provenanceVersion"), 1)
            and _same(baseline.get("chunkingVersion"), 5) and baseline.get("provider") == "none"
            and baseline.get("model") == "fts-only",
            "identity fixture did not start from the genuine current producer metadata")
    native = raw["engine"] == "native"
    require((isinstance(mutation["sql"], str) if native else isinstance(mutation["sql"], list))
            and isinstance(mutation["parameters"], list), "identity fixture DML carrier schema was reassigned")
    sqls = ([mutation["sql"]] if mutation["sql"] else []) if native else mutation["sql"]
    bindings = ([mutation["parameters"]] if mutation["sql"] else []) if native else mutation["parameters"]
    kind = expected["kind"]
    if kind == "none":
        require(mutation["before"] == mutation["after"] and type(mutation["sqliteChanges"]) is int
                and mutation["sqliteChanges"] == 0 and sqls == [] and bindings == []
                and mutation["parameters"] == [],
                "identity matching control performed a hidden metadata write")
    else:
        require(type(mutation["sqliteChanges"]) is int and mutation["sqliteChanges"] == 1
                and len(sqls) == len(bindings) == 1,
                "identity declared metadata fixture lost its actual DML/change receipt")
        sql, params = sqls[0], bindings[0]
        if kind == "delete-metadata-row":
            require(mutation["after"] is None and sql == "DELETE FROM memory_index_meta WHERE key=?"
                    and _same(params, [expected["key"]]), "identity missing metadata was fabricated")
        elif kind == "replace-metadata-serialized":
            require(mutation["after"] == expected["value"]
                    and sql == "UPDATE memory_index_meta SET value=? WHERE key=?"
                    and _same(params, [expected["value"], expected["key"]]),
                    "identity malformed metadata did not pass through actual SQL serialization")
        else:
            require(kind == "merge-metadata-fields", "identity fixture used an undeclared mutation")
            patched = {**baseline, **expected["fields"]}
            require(_same(json.loads(mutation["after"]), patched)
                    and sql == ("UPDATE memory_index_meta SET value=? WHERE key='memory_index_meta_v1'" if native
                                else "UPDATE memory_index_meta SET value=? WHERE key=?")
                    and _same(params, [mutation["after"]] if native else [mutation["after"], META_KEY]),
                    "identity fixture changed an undeclared metadata field or DML binding")
    require(_same([row for row in before["tables"]["memory_index_meta"] if row.get("key") != META_KEY],
                  [row for row in after["tables"]["memory_index_meta"] if row.get("key") != META_KEY]),
            "identity fixture changed an undeclared metadata row")
    for name in before["tables"]:
        if name != "memory_index_meta":
            require(_same(before["tables"][name], after["tables"][name]),
                    "identity fixture rewrote physical publication/source/chunk rows")
    require(_same(before["schema"], after["schema"]), "identity fixture changed the physical SQL schema")
    return start, end


def _owners(raw, events, *, native):
    owners = raw["owners"]
    require(isinstance(owners, dict) and set(owners) == {"producer", "inspection", "searchOwner"},
            "identity real owner set was changed or borrowed")
    ids = [owner["ownerId"] for owner in owners.values()]
    require(all(isinstance(item, str) and item for item in ids) and len(set(ids)) == 3,
            "identity producer, inspector and search owner are not separate real objects")
    for role, owner in owners.items():
        require(type(owner["providerInitializedAtAcquisition"]) is bool
                and (role == "producer" or owner["providerInitializedAtAcquisition"] is False)
                and owner["constructorName"] == ("MemoryIndexManager" if native else "ManagedSQLiteMemoryStore")
                and owner["purpose"] == (("status" if role == "inspection" else "default") if native else None),
                "identity owner purpose, constructor or initial knowledge was fabricated")
        close = owner["close"]
        start, end = _interval(close, events, "original-close-enter", "original-close-return",
                               "identity original close settlement is missing")
        require(events[start]["ownerId"] == events[end]["ownerId"] == owner["ownerId"]
                and events[start]["label"] == events[end]["label"] == role
                and close["closed"] is True and events[end]["closed"] is True
                and _same(close["closing"], events[end]["closing"])
                and close["returnedUndefined" if native else "returnedNone"] is True
                and events[end]["returnedUndefined" if native else "returnedNone"] is True,
                "identity original close did not settle the actual owner")
        if not native:
            require(close["lifecycle"]["closed"] is True and close["lifecycle"]["activeOperations"] == 0,
                    "SDK identity close left an admitted operation active")
    return owners



def _acquisitions(case, raw, events, owners, snapshots, *, native):
    rows = raw["originalGetCalls"] if native else raw["ownerAcquisitions"]
    require(isinstance(rows, list), "identity real owner acquisitions were removed")
    for role, phase, prefix in (("producer", "producer-acquisition", None),
                                ("inspection", "inspection-acquisition", "inspection"),
                                ("searchOwner", "search-owner-acquisition", "search-owner")):
        row = _one(rows, lambda item: (item.get("phase") == phase and item.get("activeTool") is None
                    and item.get("requestedPurpose") == owners[role]["purpose"])
                   if native else item.get("role") == role,
                   "identity actual owner acquisition is missing, duplicated or reassigned")
        start, end = _interval(row, events,
            "original-get-enter" if native else "original-open-enter",
            "original-get-return" if native else "original-open-return",
            "identity original owner acquisition interval was changed")
        require(row["ownerId"] == owners[role]["ownerId"],
                "identity acquisition returned a different actual owner")
        if native:
            require(row["receiverIsOriginalClass"] is True
                    and row["actualPurpose"] == owners[role]["purpose"]
                    and row["requestedPurpose"] == owners[role]["purpose"]
                    and row["agentId"] == case["input"]["identity"]["agentId"]
                    and _same(row["config"], raw["requestedConfig"])
                    and events[start]["receiverIsOriginalClass"] is True
                    and events[end]["ownerId"] == row["ownerId"],
                    "native identity constructor bypassed its original configured facade")
        else:
            require(row["api"] == "ManagedSQLiteMemoryStore"
                    and row["actualClass"] == owners[role]["constructorName"]
                    and row["workspaceIsExactOwner"] is True
                    and _same(row["config"], owners[role]["settings"])
                    and row["indexPath"] == snapshots["seed-after-publication"]["dbPath"]
                    and events[end]["returnedIsActualConstructedOwner"] is True,
                    "SDK identity constructor borrowed another class, workspace or database")
        if prefix is not None:
            require(snapshots[prefix + "-before-open"]["returnSeq"] < start < end
                    < snapshots[prefix + "-after-open"]["enterSeq"],
                    "identity constructor effects were not independently captured")
        else:
            require(_event(events, "source-fixture-finished")["sequence"] < start < end
                    < raw["seedPublication"]["enterSeq"],
                    "identity seed publisher preceded its declared source/acquisition")
    enter_name = "original-get-enter" if native else "original-open-enter"
    return_name = "original-get-return" if native else "original-open-return"
    require(len(rows) == sum(item["event"] == enter_name for item in events.values())
            == sum(item["event"] == return_name for item in events.values()),
            "identity actual owner acquisition receipts were discarded")
    if native:
        for row in rows:
            start, end = _interval(row, events, "original-get-enter", "original-get-return",
                                   "native identity original acquisition was detached from its actual call")
            classification = (row["phase"], row["activeTool"], row["requestedPurpose"])
            require((row["requestedPurpose"] == "maintenance" or classification in {
                        ("producer-acquisition", None, "default"), ("inspection-acquisition", None, "status"),
                        ("search-owner-acquisition", None, "default"), ("seed-search", "seed", "default"),
                        ("first-query", "query", "default")})
                    and row["actualPurpose"] == row["requestedPurpose"]
                    and row["agentId"] == case["input"]["identity"]["agentId"]
                    and _same(row["config"], raw["requestedConfig"])
                    and row["receiverIsOriginalClass"] is True
                    and all(_same(row[key], events[start][key]) for key in
                            ("phase", "activeTool", "agentId", "requestedPurpose", "receiverIsOriginalClass"))
                    and all(_same(row[key], events[end][key]) for key in
                            ("activeTool", "ownerId", "returnedIsExactSampledOwner"))
                    and "error" not in row,
                    "native identity original getter used an undeclared purpose, owner, config or call carrier")
            if row["requestedPurpose"] != "maintenance":
                continue
            source_id = row["maintenanceSourceOwnerId"]
            parent = _one(list(owners.values()), lambda item: item["ownerId"] == source_id,
                          "native identity intrinsic maintenance lost its actual foreground source owner")
            parent_phase = "producer-acquisition" if parent is owners["producer"] else "search-owner-acquisition"
            parent_acquisition = _one(rows, lambda item: item["ownerId"] == source_id
                                      and item["activeTool"] is None and item["phase"] == parent_phase,
                                      "native identity intrinsic maintenance lost its source acquisition")
            require(parent is not owners["inspection"] and row["actualPurpose"] == "maintenance"
                    and row["ownerId"] not in {owner["ownerId"] for owner in owners.values()}
                    and row["receiverIsOriginalClass"] is True
                    and _same(row["config"], raw["requestedConfig"])
                    and "maintenanceSource" in row["parameterKeys"]
                    and events[start]["requestedPurpose"] == "maintenance"
                    and events[end]["ownerId"] == row["ownerId"]
                    and parent_acquisition["enterSeq"] < start
                    and end < parent["close"]["returnSeq"],
                    "native identity intrinsic maintenance borrowed an unrelated source or bypassed original ownership")
            if row["activeTool"] is not None:
                expected_parent = owners["producer"] if row["activeTool"] == "seed" else owners["searchOwner"]
                require(source_id == expected_parent["ownerId"]
                        and row["maintenanceSourceIsExactSampledOwner"] is True
                        and row["returnedIsExactSampledOwner"] is False,
                        "native identity intrinsic maintenance was relabelled as the public default owner")
    else:
        require(len(rows) == 3, "SDK identity added an undeclared managed owner")


def _statuses(raw, events, owners):
    calls = raw["statusCalls"]
    require(isinstance(calls, list) and calls, "identity actual full status returns were removed")
    require([row["id"] for row in calls] == [f"status-{index}" for index in range(1, len(calls) + 1)],
            "identity status receipts were duplicated or relabelled")
    for row in calls:
        start, end = _interval(row, events, "original-status-enter", "original-status-return",
                               "identity status return interval was changed")
        require(row["ownerId"] in {owner["ownerId"] for owner in owners.values()}
                and row["receiverIsExactObservedOwner"] is True
                and all(events[seq]["ownerId"] == row["ownerId"]
                        and events[seq]["receiverIsExactObservedOwner"] is True
                        and events[seq]["requestLabel"] == row["requestLabel"]
                        and events[seq]["activeTool"] == row["activeTool"] for seq in (start, end))
                and isinstance(row["result"], dict),
                "identity status original receiver or complete return was detached")
        _diagnostic(row["result"]["custom"]["indexIdentity"])
    require(sum(row["event"] == "original-status-enter" for row in events.values()) == len(calls)
            == sum(row["event"] == "original-status-return" for row in events.values()),
            "identity actual status call/return receipts were discarded")
    indexed = {row["id"]: row for row in calls}
    selected = raw["diagnosticStatusCalls"]
    require(set(selected) == {"inspection", "searchOwner", "afterQuery"},
            "identity actual diagnostic selector is incomplete")
    for role, prefix in (("inspection", "inspection"), ("searchOwner", "search-owner")):
        require(isinstance(selected[role], list) and len(selected[role]) == 2,
                "identity actual two pre-query status calls were removed")
        for index, receipt in enumerate(selected[role], start=1):
            row = indexed[receipt]
            require(row["ownerId"] == owners[role]["ownerId"]
                    and row["requestLabel"] == f"{prefix}-{index}" and row["activeTool"] is None,
                    "identity pre-query status borrowed another owner or actual tool status")
    after = indexed[selected["afterQuery"]]
    require(after["ownerId"] == owners["searchOwner"]["ownerId"]
            and after["requestLabel"] == "after-query" and after["activeTool"] is None,
            "identity post-query diagnostic borrowed a pre-query observation")
    return indexed


def _tool_carrier(call):
    envelope = call["envelope"]
    require(isinstance(envelope, dict) and isinstance(envelope.get("content"), list)
            and envelope["content"] and envelope["content"][0].get("type") == "text"
            and isinstance(envelope["content"][0].get("text"), str)
            and _same(json.loads(envelope["content"][0]["text"]), envelope["details"]),
            "identity actual original complete tool carrier was changed")
    return envelope["details"]



_PRIVATE_MISSING = {"$sdkPrivate": "HYBRID_METADATA_MISSING"}
_PRIVATE_FIELDS = {"importance", "triggers", "project_key", "provenance", "source_mtime", "_vector_id"}


def _private_markers(value, path=()):
    if isinstance(value, dict):
        if "$sdkPrivate" in value:
            require(_same(value, _PRIVATE_MISSING) and len(path) == 5
                    and path[0] == "originalSearchCalls" and type(path[1]) is int
                    and path[2] == "result" and type(path[3]) is int and path[4] in _PRIVATE_FIELDS,
                    "SDK identity private metadata marker escaped its exact typed search-return field")
        else:
            for key, item in value.items():
                _private_markers(item, (*path, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _private_markers(item, (*path, index))


def _returned_hits(search, output, *, native):
    rows = search["result"]
    for public in output["results"]:
        start_key, end_key = ("startLine", "endLine") if native else ("start_line", "end_line")
        hit = _one(rows, lambda row: row.get("path") == public["path"]
                   and _same(row.get(start_key), public["startLine"])
                   and _same(row.get(end_key), public["endLine"]),
                   "identity public hit was not returned by its actual original search")
        if native:
            require(_same(hit, {key: item for key, item in public.items() if key != "corpus"}),
                    "native identity public tool changed or invented an actual original search field")
        else:
            required = {"path", "start_line", "end_line", "score", "vector_score", "text_score", "snippet", "source",
                        "importance", "triggers", "project_key", "provenance", "source_mtime", "_vector_id", "_retrieval_mode"}
            require(set(hit) == required, "SDK identity raw HybridResult dropped actual dataclass fields")
            for raw_key, public_key in (("path", "path"), ("start_line", "startLine"), ("end_line", "endLine"),
                                        ("score", "score"), ("snippet", "snippet"), ("source", "source")):
                require(_same(hit[raw_key], public[public_key]),
                        "SDK identity public hit differs from its actual original search return")
            for raw_key, public_key in (("importance", "importance"), ("triggers", "triggers"),
                                        ("project_key", "projectKey"), ("provenance", "provenance"), ("_vector_id", "id")):
                missing = _same(hit[raw_key], _PRIVATE_MISSING)
                require((public_key not in public) if missing else
                        public_key in public and _same(public[public_key], hit[raw_key]),
                        "SDK identity private missing/null annotation presence was silently rewritten")
            for raw_key, public_key in (("vector_score", "vectorScore"), ("text_score", "textScore")):
                present = (hit["_retrieval_mode"] == "hybrid" if raw_key == "vector_score"
                           else hit["_retrieval_mode"] != "vector")
                require((public_key in public and _same(public[public_key], hit[raw_key])) if present
                        else public_key not in public,
                        "SDK identity retrieval component field presence was altered")


def _tools(case, raw, result, events, owners, statuses, *, native):
    calls = raw["toolCalls"]
    require(isinstance(calls, dict) and set(calls) == {"seed", "query"},
            "identity actual original public tool calls were added or removed")
    intervals = {}
    for label, role, params, output in (
        ("seed", "producer", case["input"]["seed"]["baselineSearch"], result["seedSearch"]),
        ("query", "searchOwner", case["input"]["search"], result["search"]),
    ):
        call = calls[label]
        start, end = _interval(call, events, "actual-tool-enter", "actual-tool-return",
                               "identity actual public tool interval was reordered")
        require(call["label"] == events[start]["label"] == events[end]["label"] == label
                and _same(call["args"], params) and _same(events[start]["args"], params)
                and _same(_tool_carrier(call), output) and "error" not in call,
                "identity actual first public tool request/result was replaced or projected")
        if not native:
            encoded = json.dumps(call["envelope"], ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
            file = call["envelopeFile"]
            require(file["path"] == str(Path(raw["fixtureBase"]) / f"tool-{label}-envelope.json")
                    and type(file["bytes"]) is int and file["bytes"] == len(encoded.encode())
                    and file["sha256"] == hashlib.sha256(encoded.encode()).hexdigest(),
                    "SDK identity early actual tool-envelope file receipt was rewritten")
        owner_id = owners[role]["ownerId"]
        searches = [row for row in raw["originalSearchCalls"] if row["activeTool"] == label]
        require(len(searches) == 1, "identity valid public tool lacks its unique actual search dispatch")
        search = searches[0]
        entered, returned = _interval(search, events, "original-search-enter", "original-search-return",
                                     "identity original manager search interval was replaced")
        require(start < entered < returned < end and search["ownerId"] == owner_id
                and search["query"] == params["query"] and search["receiverIsExactObservedOwner"] is True
                and events[entered]["ownerId"] == events[returned]["ownerId"] == owner_id
                and events[entered]["activeTool"] == events[returned]["activeTool"] == label
                and events[entered]["receiverIsExactObservedOwner"] is True
                and events[returned]["receiverIsExactObservedOwner"] is True
                and isinstance(search["result"], list) and "error" not in search,
                "identity public tool did not consume the same sampled original search owner")
        _returned_hits(search, output, native=native)
        options = search["options"]
        expected_names = {"maxResults": "max_results", "minScore": "min_score"}
        for name in ("maxResults", "minScore"):
            require(_same(options[name if native else expected_names[name]], params[name]),
                    "identity original search options were changed after actual public parsing")
        absent = set(search["optionKeys"]) - set(options)
        require(set(options) <= set(search["optionKeys"])
                and (absent <= {"sessionKey", "activeProjectKeys"} if native else not absent),
                "identity original search option values were discarded")
        require(_same(options["sources"], ["memory"] if native else {"setValues": ["memory"]}),
                "identity public corpus selection did not reach its actual search owner")
        tool_statuses = [row for row in statuses.values() if row["activeTool"] == label]
        require(tool_statuses and all(row["ownerId"] == owner_id and start < row["enterSeq"]
                                     < row["returnSeq"] < end for row in tool_statuses)
                and any(row["returnSeq"] < entered for row in tool_statuses)
                and any(row["enterSeq"] > returned for row in tool_statuses),
                "identity public query lost its actual pre/post original status consumption")
        if native:
            acquisitions = [row for row in raw["originalGetCalls"] if row["activeTool"] == label
                            and row["requestedPurpose"] == "default"]
            require(len(acquisitions) == 1 and all(row["ownerId"] == owner_id
                    and row["returnedIsExactSampledOwner"] is True
                    and row["receiverIsOriginalClass"] is True and row["actualPurpose"] == "default"
                    and row["requestedPurpose"] == "default" and row["agentId"] == case["input"]["identity"]["agentId"]
                    for row in acquisitions), "native identity original tool getter returned another owner")
            for acquisition in acquisitions:
                acquired, got = _interval(acquisition, events, "original-get-enter", "original-get-return",
                                          "native identity original acquisition receipt was reordered")
                require(start < acquired < got < entered
                        and events[got]["ownerId"] == owner_id
                        and events[got]["returnedIsExactSampledOwner"] is True,
                        "native identity original public getter did not precede its actual search")
        else:
            binding = _one(raw["toolBindings"], lambda row: row["label"] == label,
                           "SDK identity public factory lost its exact real-store binding")
            require(binding["ownerId"] == owner_id and binding["storeIsExactObservedOwner"] is True
                    and binding["configIsExactOwnerConfig"] is True
                    and binding["statusIsObservedOwnerStatus"] is True
                    and binding["runtimeIdentityIsExactOwner"] is True
                    and binding["api"] == "memory_core.tools.search_factory.create_memory_search_tool(...).execute"
                    and events[binding["sequence"]]["event"] == "actual-tool-binding"
                    and events[binding["sequence"]]["ownerId"] == owner_id
                    and binding["sequence"] < start,
                    "SDK identity public tool substituted another store, config or status callback")
        intervals[label] = (start, end)
    require(len(raw["originalSearchCalls"]) == 2
            == sum(row["event"] == "original-search-enter" for row in events.values())
            == sum(row["event"] == "original-search-return" for row in events.values()),
            "identity owner executed an unobserved query before its declared first public call")
    return intervals


def _schedule(case, raw, result, events, owners, statuses, snapshots, tools, mutation):
    publication = raw["seedPublication"]
    require(sum(row["event"] in {"original-sync-enter", "original-publication-enter"} for row in events.values()) == 1
            == sum(row["event"] in {"original-sync-return", "original-publication-return"} for row in events.values()),
            "identity actor executed an undeclared manual publication after the fixture")
    published, publication_end = _interval(publication, events,
        "original-sync-enter" if raw["engine"] == "native" else "original-publication-enter",
        "original-sync-return" if raw["engine"] == "native" else "original-publication-return",
        "identity seed index was not published by its real original owner")
    require(publication["ownerId"] == owners["producer"]["ownerId"]
            and publication_end < snapshots["seed-after-publication"]["enterSeq"]
            < snapshots["seed-after-publication"]["returnSeq"] < tools["seed"][0]
            < tools["seed"][1] < snapshots["seed-after-search"]["enterSeq"]
            < snapshots["seed-after-search"]["returnSeq"] < owners["producer"]["close"]["enterSeq"]
            < owners["producer"]["close"]["returnSeq"] < snapshots["seed-after-close"]["enterSeq"]
            < snapshots["metadata-fixture-before"]["enterSeq"] < mutation[0] < mutation[1]
            < snapshots["metadata-fixture-after"]["enterSeq"],
            "identity original producer/positive-query/close/fixture chronology was broken")
    for role, prefix in (("inspection", "inspection"), ("searchOwner", "search-owner")):
        selected = [statuses[key] for key in raw["diagnosticStatusCalls"][role]]
        require(snapshots[prefix + "-before-open"]["returnSeq"]
                < snapshots[prefix + "-after-open"]["enterSeq"]
                < snapshots[prefix + "-after-open"]["returnSeq"]
                < selected[0]["enterSeq"] < selected[0]["returnSeq"]
                < snapshots[prefix + "-after-read-1"]["enterSeq"]
                < snapshots[prefix + "-after-read-1"]["returnSeq"]
                < selected[1]["enterSeq"] < selected[1]["returnSeq"]
                < snapshots[prefix + "-after-read-2"]["enterSeq"]
                < snapshots[prefix + "-after-read-2"]["returnSeq"],
                "identity two genuine pre-query diagnostics were reordered or borrowed")
        expected = [row["result"]["custom"]["indexIdentity"] for row in selected]
        require(_same(result["diagnostics"][role], expected),
                "identity common diagnostic dropped or rewrote original full status fields")
    require(snapshots["metadata-fixture-after"]["returnSeq"]
            < snapshots["inspection-before-open"]["enterSeq"]
            < snapshots["inspection-after-read-2"]["returnSeq"]
            < owners["inspection"]["close"]["enterSeq"]
            < owners["inspection"]["close"]["returnSeq"]
            < snapshots["inspection-after-close"]["enterSeq"]
            < snapshots["search-owner-before-open"]["enterSeq"]
            < snapshots["search-owner-after-read-2"]["returnSeq"] < tools["query"][0]
            < tools["query"][1], "identity first actual query preceded its full reopened diagnostic boundary")
    after = statuses[raw["diagnosticStatusCalls"]["afterQuery"]]
    require(tools["query"][1] < after["enterSeq"] < after["returnSeq"]
            < snapshots["search-owner-after-query"]["enterSeq"]
            < snapshots["search-owner-after-query"]["returnSeq"]
            < owners["searchOwner"]["close"]["enterSeq"]
            < owners["searchOwner"]["close"]["returnSeq"]
            < snapshots["search-owner-after-close"]["enterSeq"]
            and _same(result["diagnostics"]["afterQuery"], after["result"]["custom"]["indexIdentity"]),
            "identity actual post-query diagnostic/close boundary was reassigned")
    original = _sql_state(snapshots["metadata-fixture-after"])
    for label in SNAPSHOT_LABELS[5:14]:
        require(_same(_sql_state(snapshots[label]), original),
                "identity pre-query constructor/status silently rewrote physical publication")
    if case["id"] not in VALID_QUERY:
        require(_same(_sql_state(snapshots["search-owner-after-query"]), original)
                and _same(_sql_state(snapshots["search-owner-after-close"]), original),
                "identity refused/newer metadata query overwrote its actual publication")
    if case["id"] in REPAIRED:
        repaired = json.loads(_meta_row(snapshots["search-owner-after-query"]))
        require(repaired.get("provenanceVersion") == 1 and repaired.get("chunkingVersion") == 5
                and result["diagnostics"]["afterQuery"] == {"status": "valid"},
                "identity actual first search did not naturally publish current metadata")
    for role in ("inspection", "searchOwner"):
        for key in raw["diagnosticStatusCalls"][role]:
            row = statuses[key]
            require(events[row["enterSeq"]]["providerInitialized"] is False
                    and events[row["returnSeq"]]["providerInitialized"] is False,
                    "identity query-free diagnostic eagerly initialized provider knowledge")
    require(_same(raw["sourceBefore"], raw["sourceAfter"]) and _same(raw["sourceAfter"], result["source"]),
            "identity diagnostics or query changed the declared source bytes")



def _final_closed(raw, events, owners, snapshots, *, native):
    if not native:
        require(raw["allManagersClosed"] is all(owner["close"]["closed"] is True for owner in owners.values()),
                "SDK identity all-owner closure scalar contradicts actual owner returns")
        return
    entered = _event(events, "runtime-close-all-enter")
    returned = _event(events, "runtime-close-all-return")
    require(snapshots["search-owner-after-close"]["returnSeq"]
            < entered["sequence"] < returned["sequence"] == len(events)
            and raw["runtimeCloseAllInvoked"] is True and raw["runtimeCloseAllReturned"] is True
            and returned["returnedNormally"] is True,
            "native identity original close-all did not actually return normally")
    rows = raw["finalManagerStates"]
    actual_gets = raw["originalGetCalls"]
    require(isinstance(rows, list) and rows
            and len({row["ownerId"] for row in rows}) == len(rows)
            and {row["ownerId"] for row in rows} == {row["ownerId"] for row in actual_gets}
            and set(entered["returnedManagerIds"]) == {row["ownerId"] for row in actual_gets
                                                       if row["returnSeq"] < entered["sequence"]}
            and _same(returned["finalManagerStates"], rows),
            "native identity final actual manager states lost returned original owner objects")
    for row in rows:
        getters = [item for item in actual_gets if item["ownerId"] == row["ownerId"]]
        require(all(item["returnSeq"] < returned["sequence"] and item["actualPurpose"] == row["purpose"]
                    for item in getters) and row["closed"] is True and row["closing"] is True,
                "native identity claimed close-all success with an actual returned manager still open")
    computed = all(row["closed"] is True and row["closing"] is True for row in rows)
    require(raw["allManagersClosed"] is computed and returned["allManagersClosed"] is computed,
            "native identity all-manager closure was fabricated from normal return alone")


def _sdk_config(case, raw, owners):
    expected_source = str(Path(raw["fixtureBase"]) / "workspace")
    require(_same(raw["requestedConfig"], case["input"]["config"]),
            "SDK identity requested configuration differs from its frozen fixture")
    for owner in owners.values():
        config = owner["settings"]
        require(config["workspace_dir"] == expected_source
                and config["agent_id"] == case["input"]["identity"]["agentId"]
                and config["citation_mode"] == "off"
                and config["flags"]["vector_search"] is False
                and config["flags"]["mmr"] is True and config["flags"]["temporal_decay"] is True,
                "SDK identity actual owner config changed its provider/source/query profile")
    require(_same(raw["catalogBefore"], raw["catalogAfter"])
            and all(not raw["catalogBefore"]["tables"][name] for name in
                    ("memory_session_events", "memory_session_nodes", "memory_session_archives")),
            "SDK identity declared empty real session corpus was replaced or mutated")


def _native_config(case, raw, owners):
    value = case["input"]
    expected = value["nativeResolvedPolicyContract"]
    for owner in owners.values():
        settings = owner["settings"]
        require(_same(settings["sync"], expected["sync"])
                and _same(settings["chunking"], expected["chunking"])
                and settings["cache"]["maxEntries"] == expected["cacheMaxEntries"]
                and _same(settings["query"]["hybrid"], expected["query"]["hybrid"])
                and settings["provider"] == "none" and settings["fallback"] == "none"
                and settings["sources"] == ["memory", "sessions"]
                and settings["store"]["vector"]["enabled"] is False
                and settings["store"]["fts"]["tokenizer"] == "unicode61"
                and settings["cache"]["enabled"] is False,
                "native identity actual resolved configuration differs from its declared supported profile")
    require(_same(raw["requestedConfig"]["memory"], value["config"]["memory"])
            and raw["requestedConfig"]["agents"]["defaults"]["workspace"] == str(Path(raw["fixtureBase"]) / "workspace"),
            "native identity actual configuration borrowed another workspace or unsupported fixture")


def _raw(case, raw, result, *, native):
    require(isinstance(raw, dict) and raw.get("kind") == "index-identity-boundaries"
            and raw.get("engine") == ("native" if native else "sdk")
            and raw.get("caseId") == case["id"] and _same(raw.get("input"), case["input"])
            and type(raw.get("pid")) is int and raw["pid"] > 0
            and type(raw.get("ppid")) is int and raw["ppid"] > 0
            and raw["pid"] != raw["ppid"] and Path(raw["fixtureBase"]).is_absolute()
            and raw.get("completed") is True and raw.get("allManagersClosed") is True
            and "error" not in raw and "teardownError" not in raw
            and _same(raw["result"], result),
            "identity protected engine capture is incomplete or belongs to another actual attempt")
    if not native:
        require(raw["implementationRoot"] == str(ROOT)
                and _same(raw["clock"], {"owner": "public-tool-clock", "nowMs": case["input"]["nowMs"],
                    "monotonicAndTimers": "unmodified"}),
                "SDK identity capture imported another implementation or replaced real timers")
    if not native:
        _private_markers(raw)
    events = _chronology(raw)
    snapshots = _snapshot_map(raw, events)
    _published_sql(case, result, snapshots, native=native)
    owners = _owners(raw, events, native=native)
    _acquisitions(case, raw, events, owners, snapshots, native=native)
    statuses = _statuses(raw, events, owners)
    mutation = _mutation(case, raw, events, snapshots)
    tools = _tools(case, raw, result, events, owners, statuses, native=native)
    _schedule(case, raw, result, events, owners, statuses, snapshots, tools, mutation)
    if native:
        _native_config(case, raw, owners)
    else:
        _sdk_config(case, raw, owners)
    _final_closed(raw, events, owners, snapshots, native=native)
    return True


def _sdk(case, dispatch, result):
    require(dispatch.get("kind") == "index-identity-boundaries-sdk-dispatch"
            and _same(dispatch["input"], case["input"])
            and _same(dispatch["exit"], {"code": 0})
            and type(dispatch["pid"]) is int and type(dispatch["coordinatorPid"]) is int
            and dispatch["pid"] != dispatch["coordinatorPid"]
            and int(dispatch["startedAtNs"]) < int(dispatch["finishedAtNs"]),
            "SDK identity process dispatch failed or belongs to another case")
    require(all(isinstance(dispatch[key], str) and dispatch[key].isdigit()
                for key in ("startedAtNs", "finishedAtNs")),
            "SDK identity dispatch lost its actual monotonic process timestamps")
    wire = dispatch["requestJson"]
    request = json.loads(wire)
    require(hashlib.sha256(wire.encode()).hexdigest() == dispatch["requestSha256"]
            and _same(request, dispatch["request"]) and _same(request["input"], case["input"])
            and set(request) == {"input", "directory"}
            and dispatch["argv"][1:] == ["-m", "equivalence.index_identity_boundaries_sdk_cli"]
            and dispatch["environmentKeys"] == ["LANG", "OPENCLAW_HOME", "OPENCLAW_STATE_DIR", "PATH", "PYTHONPATH", "TZ"],
            "SDK identity protected request/process carrier was modified")
    observed = json.loads(dispatch["stdout"])
    require(_same(observed, dispatch["observation"]) and set(observed) == {"result", "raw"}
            and _same(observed["result"], result),
            "SDK identity stdout lost its complete actual public result/raw capture")
    raw = observed["raw"]
    require(raw["pid"] == dispatch["pid"] and raw["ppid"] == dispatch["coordinatorPid"]
            and raw["fixtureBase"] == request["directory"],
            "SDK identity child process/directory was reassigned")
    require(int(dispatch["startedAtNs"]) < int(raw["events"][0]["atNs"])
            <= int(raw["events"][-1]["atNs"]) < int(dispatch["finishedAtNs"]),
            "SDK identity actual child observations escaped their original process interval")
    return _raw(case, raw, result, native=False)


def validate_result(case, result):
    try:
        return _validate_result(case, result)
    except (KeyError, IndexError, TypeError, AttributeError, StopIteration, json.JSONDecodeError) as error:
        raise ValueError("identity public result is structurally incomplete") from error


def validate_capture(case, capture, result, *, native):
    validate_result(case, result)
    try:
        return _raw(case, capture, result, native=True) if native else _sdk(case, capture, result)
    except (KeyError, IndexError, TypeError, AttributeError, StopIteration, json.JSONDecodeError) as error:
        raise ValueError(("native" if native else "SDK") + " identity evidence is structurally incomplete") from error


def validate_pair(case, native_raw, sdk_raw, native_result, sdk_result):
    validate_capture(case, native_raw, native_result, native=True)
    validate_capture(case, sdk_raw, sdk_result, native=False)
    return True


def replay_case(case, directory):
    directory = Path(directory)
    native = json.loads((directory / "stdout.json").read_text())["result"]
    sdk = json.loads((directory / "sdk-output.json").read_text())
    originals = json.loads((directory / "evidence/native-raw.json").read_text())
    copies = json.loads((directory / "evidence/python-raw.json").read_text())
    require(len(originals) == len(copies) == 1, "identity replay needs exactly one actual capture per engine")
    validate_pair(case, originals[0], copies[0], native, sdk)
    return {"validated": True, "nativeSnapshots": 1, "sdkSnapshots": 1}
