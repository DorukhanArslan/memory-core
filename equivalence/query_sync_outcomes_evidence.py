"""Independent custody and semantic checks for actual query-sync outcomes.

The first public search may read an older or a newer coherent generation.
Original close, not an extra query or private wait, bounds admitted publication.
Full public details are compared; engine-specific state remains evidence.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
from pathlib import Path

from equivalence.host_turn_barrier_evidence import _same, require
from equivalence.query_sync_outcomes import validate_case

ROOT = Path(__file__).resolve().parents[1]
STAGES = ("initial", "afterMutation", "afterFirstClose", "afterFinalClose")
PRIVATE_MISSING = {"$sdkPrivate": "HYBRID_METADATA_MISSING"}
NATIVE_METHODS = {"status", "search", "sync", "syncAdmitted", "syncPublishedIndexInBackground", "runSync", "syncMemoryFiles", "markMemoryWatchDirty", "prepareKeywordSearch", "close", "awaitManagerIdle", "takeReindexRetryStateForMaintenance", "adoptReindexRetryState"}
PRIVATE_FIELDS = {"importance", "triggers", "project_key", "provenance", "source_mtime", "_vector_id"}


def _one(rows, predicate, message):
    found = [row for row in rows if predicate(row)]
    require(len(found) == 1, "query-sync " + message)
    return found[0]


def _finite(value):
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_finite(item) for item in value.values())
    if isinstance(value, list):
        return all(_finite(item) for item in value)
    return True


def _expected_sources(case):
    value = case["input"]
    before = {path: (text, value["initialSourceMtimeMs"])
              for path, text in value["initialFiles"].items()}
    after = dict(before)
    mutation = value["sourceMutation"] or {"kind": "none"}
    kind = mutation["kind"]
    if kind in {"create", "replace"}:
        after[mutation["path"]] = (mutation["text"], mutation["mtimeMs"])
    elif kind == "delete":
        after.pop(mutation["path"])
    elif kind == "rename":
        after[mutation["to"]] = after.pop(mutation["from"])
    elif kind == "touch-same-bytes":
        after[mutation["path"]] = (after[mutation["path"]][0], mutation["mtimeMs"])
    paths = sorted(set(before) | set(after))
    return paths, before, after


def _source_entries(entries, paths, expected):
    require(isinstance(entries, list) and [row.get("path") for row in entries] == paths,
            "query-sync source observation omitted, duplicated or reordered an owned path")
    for row in entries:
        path = row["path"]
        require(not Path(path).is_absolute() and ".." not in Path(path).parts,
                "query-sync source escaped its owned workspace")
        if path not in expected:
            require(_same(row, {"path": path, "kind": "missing"}),
                    "query-sync removed source was replaced with fabricated bytes")
            continue
        text, mtime = expected[path]
        data = text.encode("utf8")
        require(set(row) == {"path", "kind", "text", "hex", "sha256", "size", "mtimeMs"}
                and row["kind"] == "file" and row["text"] == text and row["hex"] == data.hex()
                and row["sha256"] == hashlib.sha256(data).hexdigest()
                and type(row["size"]) is int and row["size"] == len(data)
                and _same(row["mtimeMs"], mtime),
                "query-sync actual source bytes/hash/stat disagree with the frozen real mutation")


def _search_details(output, sources, *, query):
    require(isinstance(output, dict) and _finite(output) and isinstance(output.get("results"), list)
            and output.get("provider") == "none" and output.get("citations") == "off"
            and not output.get("disabled") and not output.get("unavailable"),
            "query-sync complete public details is missing, unavailable or nonfinite")
    require(len(output["results"]) <= 5, "query-sync public result ignored its actual limit")
    for hit in output["results"]:
        require(isinstance(hit, dict) and hit.get("path") in sources
                and hit.get("source") == hit.get("corpus") == "memory"
                and type(hit.get("startLine")) is int and type(hit.get("endLine")) is int
                and 0 < hit["startLine"] <= hit["endLine"]
                and isinstance(hit.get("snippet"), str) and hit["snippet"]
                and isinstance(hit.get("score"), (float, int)) and type(hit["score"]) is not bool,
                "query-sync public hit lost its actual source/range/score")
        text = sources[hit["path"]][0]
        require(hit["snippet"].strip() in text and query.casefold() in text.casefold(),
                "query-sync public hit is detached from its actual observed source generation")
    debug = output.get("debug")
    require(isinstance(debug, dict) and _same(debug.get("hits"), len(output["results"]))
            and _same(debug.get("withheldHits"), 0),
            "query-sync complete public debug lost actual hit accounting")


def _validate_result(case, result):
    validate_case(case)
    require(isinstance(result, dict) and set(result) == {"provider", "searches", "sources"}
            and result["provider"] == "none"
            and isinstance(result["searches"], dict)
            and set(result["searches"]) == {"seed", "first", "reopened"}
            and isinstance(result["sources"], dict) and set(result["sources"]) == set(STAGES),
            "query-sync public result changed its frozen complete common interface")
    paths, before, after = _expected_sources(case)
    for stage in STAGES:
        _source_entries(result["sources"][stage], paths, before if stage == "initial" else after)
    searches, queries = result["searches"], case["input"]["queries"]
    require((searches["seed"] is None) is (queries["seed"] is None),
            "query-sync seed query presence differs from its frozen input")
    memory_before = dict(before)
    memory_after = dict(after)
    if queries["seed"] is not None:
        _search_details(searches["seed"], memory_before, query=queries["seed"]["query"])
    # The actual first generation is independently authenticated below. Either
    # full source generation is permitted here, never a mixture of hit fields.
    first_sources = dict(memory_before)
    first_sources.update(memory_after)
    for path in memory_before.keys() & memory_after.keys():
        if memory_before[path] != memory_after[path]:
            first_sources[path] = (memory_before[path][0] + memory_after[path][0], 0)
    _search_details(searches["first"], first_sources, query=queries["first"]["query"])
    _search_details(searches["reopened"], memory_after, query=queries["reopened"]["query"])
    require(bool(searches["reopened"]["results"]) is any(queries["reopened"]["query"].casefold() in text.casefold() for text, _ in memory_after.values()),
            "query-sync reopened public query did not expose the completed source generation")
    return True


def _chronology(raw):
    rows = raw["events"]
    require(isinstance(rows, list) and rows
            and [row["sequence"] for row in rows] == list(range(1, len(rows) + 1))
            and all(type(row["sequence"]) is int and isinstance(row["event"], str)
                    and isinstance(row["atNs"], str) and row["atNs"].isdigit() for row in rows),
            "query-sync real lifecycle sequence is absent, duplicated or relabelled")
    times = [int(row["atNs"]) for row in rows]
    require(times == sorted(times) and times[0] > 0,
            "query-sync real monotonic lifecycle observations were reordered")
    allowed = {"source-read-enter", "source-read-return", "source-fixture-finished", "physical-sql-read-enter", "physical-sql-read-return",
        "source-mutation-enter", "source-mutation-return", "original-open-enter", "original-open-return", "original-get-enter", "original-get-return",
        "original-facade-enter", "original-facade-return", "actual-tool-enter", "actual-tool-return", "actual-tool-binding",
        "original-status-enter", "original-status-return", "original-search-enter", "original-search-return", "original-close-enter", "original-close-return",
        "original-method-enter", "original-method-return", "pinned-sql-read-enter", "pinned-sql-read-return", "original-coordination-enter", "original-coordination-return",
        "original-pool-run-enter", "original-pool-run-return", "actual-worker-dispatch-enter", "actual-worker-dispatch-return", "actual-worker-message", "actual-worker-exit",
        "declared-dirty-notification-enter", "declared-dirty-notification-return", "runtime-close-all-enter", "runtime-close-all-return"}
    allowed |= {f"original-{method}-{suffix}" for method in NATIVE_METHODS for suffix in ("enter", "return")}
    require(all(row["event"] in allowed for row in rows), "query-sync lifecycle added an unreviewed operation")
    return {row["sequence"]: row for row in rows}


def _interval(row, events, entered, returned, message):
    start, end = row["enterSeq"], row["returnSeq"]
    require(type(start) is type(end) is int and start < end
            and events[start]["event"] == entered and events[end]["event"] == returned,
            "query-sync " + message)
    if "startedAtNs" in row:
        require(row["startedAtNs"] == events[start]["atNs"]
                and row["finishedAtNs"] == events[end]["atNs"], "query-sync " + message)
    return start, end


def _sql_payload(row):
    return {key: row[key] for key in ("dbPath", "schema", "tables")}


def _physical_sql(row, *, native, allow_missing=False):
    require(isinstance(row, dict) and isinstance(row["dbPath"], str)
            and Path(row["dbPath"]).is_absolute(), "query-sync physical DB path is absent")
    absent = row.get("exists") is False if native else row.get("absent") is True
    decoded = json.loads(row["serializedJSON"])
    require(isinstance(decoded, dict) and all(key in row and _same(value, row[key])
            for key, value in decoded.items())
            and hashlib.sha256(row["serializedJSON"].encode()).hexdigest() == row["sha256"],
            "query-sync physical SQL bytes/hash were detached from observed rows")
    if absent:
        require(allow_missing and not row.get("schema") and not row.get("tables")
                and "error" in decoded and decoded["dbPath"] == row["dbPath"],
                "query-sync noninitial physical database is missing")
        return
    require({"dbPath", "schema", "tables"} <= set(decoded)
            and isinstance(row["schema"], list) and row["schema"]
            and isinstance(row["tables"], dict) and row["tables"],
            "query-sync complete physical SQL schema/tables are absent")
    tables = {item["name"] for item in row["schema"] if item["type"] == "table"}
    require(set(row["tables"]) == tables and all(isinstance(values, list)
            and all(isinstance(item, dict) for item in values) for values in row["tables"].values()),
            "query-sync SQL capture omitted complete actual schema tables or row fields")
    chunk = "memory_index_chunks" if native else "chunks"
    source = "memory_index_sources" if native else "memory_core_index_sources"
    state = "memory_index_state" if native else "memory_core_index_sync"
    body, paths = ("memory_index_chunks_fts", "memory_index_paths_fts") if native else ("chunks_fts", "paths_fts")
    required = {chunk, source, state, "memory_index_meta", "memory_index_chunk_provenance",
                "memory_index_chunk_recall_metadata"}
    if not native:
        required |= {"memory_index_chunk_details", "memory_embedding_cache"}
    for prefix in (body, paths):
        required |= {prefix + suffix for suffix in ("", "_config", "_content", "_data", "_docsize", "_idx")}
    require(required <= tables,
            "query-sync SQL capture omitted required publication/provenance/state/FTS tables")


def _published_sources(row, sources, *, native, initial_sources=None):
    """Authenticate dataflow from independently observed source bytes, not hashes alone."""
    tables = row["tables"]
    chunk_table = "memory_index_chunks" if native else "chunks"
    source_table = "memory_index_sources" if native else "memory_core_index_sources"
    state_table = "memory_index_state" if native else "memory_core_index_sync"
    body_table = "memory_index_chunks_fts" if native else "chunks_fts"
    path_table = "memory_index_paths_fts" if native else "paths_fts"
    expected = dict(sources)
    source_rows, chunks = tables[source_table], tables[chunk_table]
    require(len(source_rows) == len(expected) and {item["path"] for item in source_rows} == set(expected)
            and all(item["source"] == "memory" for item in source_rows),
            "query-sync completed SQL publication differs from actual eligible source paths")
    for source in source_rows:
        text, mtime = expected[source["path"]]
        data = text.encode()
        valid_mtimes = {mtime}
        if initial_sources and source["path"] in initial_sources:
            initial_text, initial_mtime = initial_sources[source["path"]]
            if initial_text == text:
                valid_mtimes.add(initial_mtime)
        own = [item for item in chunks if item["path"] == source["path"]]
        require(source["hash"] == hashlib.sha256(data).hexdigest()
                and _same(source["size"], len(data)) and source["mtime"] in valid_mtimes
                and len(own) == 1 and (native or _same(source["chunk_count"], len(own))),
                "query-sync completed source SQL fingerprint/count is detached from actual bytes")
        for chunk in own:
            require(chunk["source"] == "memory" and isinstance(chunk["text"], str)
                    and chunk["text"] == text
                    and type(chunk["start_line"]) is int and type(chunk["end_line"]) is int
                    and chunk["start_line"] == 1 and chunk["end_line"] == len(text.split("\n")),
                    "query-sync completed SQL chunk text/range lost its source")
            detail = chunk if native else _one(tables["memory_index_chunk_details"],
                        lambda item: item["chunk_id"] == chunk["id"], "chunk lost its real details")
            require(detail["hash"] == hashlib.sha256(chunk["text"].encode()).hexdigest()
                    and detail["model"] == "fts-only", "query-sync chunk hash/model was reassigned")
            provenance = _one(tables["memory_index_chunk_provenance"],
                              lambda item: item["chunk_id"] == chunk["id"],
                              "published chunk lost complete source provenance")
            recall = _one(tables["memory_index_chunk_recall_metadata"],
                          lambda item: item["chunk_id"] == chunk["id"],
                          "published chunk lost complete recall metadata")
            require(_same(provenance, {"chunk_id": chunk["id"], "origin_class": "agent",
                        "session_kind": "unknown", "observed_at": source["mtime"], "supersedes_key": None})
                    and _same(recall, {"chunk_id": chunk["id"], "importance": None,
                                      "triggers": None, "project_key": None}),
                    "query-sync published source provenance/recall values changed independently of actual source")
    require(all(item["path"] in expected for item in chunks)
            and len({item["id"] for item in chunks}) == len(chunks),
            "query-sync completed SQL retains removed/duplicate chunks")
    ids = {item["id"] for item in chunks}
    body = tables[body_table]
    require(len(body) == len(chunks) and {item["id"] for item in body} == ids
            and all(_one(chunks, lambda chunk: chunk["id"] == item["id"],
                         "FTS body lost its chunk")["text"] == item["text"] for item in body),
            "query-sync body FTS rows are detached from the complete chunk set")
    paths = tables[path_table]
    require(len(paths) == len(expected) and {(item["source"], item["path"]) for item in paths}
            == {("memory", path) for path in expected}, "query-sync path FTS rows lost actual source paths")
    owned_tables = ["memory_index_chunk_provenance", "memory_index_chunk_recall_metadata"]
    if not native:
        owned_tables.append("memory_index_chunk_details")
    for name in owned_tables:
        require(len(tables[name]) == len(chunks)
                and {item["chunk_id"] for item in tables[name]} == ids,
                "query-sync published provenance/recall/details contains removed or missing chunks")
    state = tables[state_table]
    require(len(state) == 1 and _same(state[0]["id"], 1)
            and type(state[0]["revision"]) is int and state[0]["revision"] >= 0,
            "query-sync original publication state/revision is absent")
    metadata = _one(tables["memory_index_meta"], lambda item: item["key"] == "memory_index_meta_v1",
                    "original published metadata is missing")
    meta = json.loads(metadata["value"])
    require(meta["provider"] == "none" and meta["model"] == "fts-only"
            and meta["sources"] == (["memory"] if native else ["memory", "sessions"])
            and meta["chunkTokens"] == 400 and meta["chunkOverlap"] == 80
            and meta["chunkingVersion"] == 5 and meta["provenanceVersion"] == 1
            and meta["ftsTokenizer"] == "unicode61",
            "query-sync original metadata changed provider/model/source ownership")


def _private_markers(value, path=()):
    if isinstance(value, dict):
        if "$sdkPrivate" in value:
            require(_same(value, PRIVATE_MISSING) and len(path) == 5
                    and path[0] == "originalSearchCalls" and type(path[1]) is int
                    and path[2] == "result" and type(path[3]) is int and path[4] in PRIVATE_FIELDS,
                    "query-sync SDK private missing marker escaped its exact existing typed field")
        else:
            for key, item in value.items():
                _private_markers(item, (*path, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _private_markers(item, (*path, index))


def _returned_hits(search, output, *, native):
    rows = search["result"]
    require(isinstance(rows, list) and len(rows) == len(output["results"]),
            "query-sync actual public tool lost an original search hit")
    for hit, public in zip(rows, output["results"], strict=True):
        if native:
            require(_same(hit, {key: value for key, value in public.items() if key != "corpus"}),
                    "query-sync Native public tool changed original search fields or order")
            continue
        require(set(hit) == {"path", "start_line", "end_line", "score", "vector_score", "text_score",
                "snippet", "source", "importance", "triggers", "project_key", "provenance",
                "source_mtime", "_vector_id", "_retrieval_mode"},
                "query-sync SDK original typed search return dropped private fields")
        for raw_key, public_key in (("path", "path"), ("start_line", "startLine"),
                ("end_line", "endLine"), ("score", "score"), ("snippet", "snippet"), ("source", "source")):
            require(_same(hit[raw_key], public[public_key]),
                    "query-sync SDK public hit differs from actual original search return")
        for raw_key, public_key in (("importance", "importance"), ("triggers", "triggers"),
                ("project_key", "projectKey"), ("provenance", "provenance"), ("_vector_id", "id")):
            missing = _same(hit[raw_key], PRIVATE_MISSING)
            require((public_key not in public) if missing else
                    public_key in public and _same(public[public_key], hit[raw_key]),
                    "query-sync SDK private missing/null public presence was rewritten")
        for raw_key, public_key in (("vector_score", "vectorScore"), ("text_score", "textScore")):
            present = hit["_retrieval_mode"] == "hybrid" if raw_key == "vector_score" else hit["_retrieval_mode"] != "vector"
            require((public_key in public and _same(public[public_key], hit[raw_key])) if present else public_key not in public,
                    "query-sync SDK original retrieval component presence was rewritten")


def _source_custody(case, raw, result, events, *, native):
    require(set(raw["sourceStages"]) == set(STAGES), "query-sync raw source stage was omitted")
    for label in STAGES:
        stage = raw["sourceStages"][label]
        start, end = _interval(stage, events, "source-read-enter", "source-read-return", "source read was reassigned")
        require(events[start]["label"] == events[end]["label"] == label
                and _same(stage["common"], result["sources"][label]),
                "query-sync complete source stage differs from actual returned observation")
        records = stage["records" if native else "entries"]
        require(len(records) == len(stage["common"]), "query-sync source raw records were dropped")
        for record, common in zip(records, stage["common"], strict=True):
            path = Path(raw["fixtureBase"]) / "workspace" / common["path"]
            require(record["absolutePath"] == str(path) and record["kind"] == common["kind"]
                    and record["path"] == common["path"], "query-sync source bytes borrowed another path")
            if common["kind"] == "missing":
                error = record["error"]
                require((error.get("code") == "ENOENT") if native else
                        error.get("errno") == 2 and error.get("name") == "FileNotFoundError"
                        and error.get("filename") == str(path),
                        "query-sync missing source lacks its actual OS ENOENT receipt")
                continue
            require(all(_same(record[key], common[key]) for key in ("hex", "sha256", "text")),
                    "query-sync raw source bytes/hash were replaced with fixture text")
            if native:
                info = record["stat"]
                require(info["size"]["privateType"] == "bigint"
                        and info["size"]["value"] == str(common["size"])
                        and int(info["mtimeNs"]["value"]) / 1_000_000 == common["mtimeMs"]
                        and info["nlink"]["value"] == "1", "query-sync Native full source stat was reassigned")
            else:
                before, after = record["statBefore"], record["statAfter"]
                require(all(before[key] == after[key] for key in ("st_dev", "st_ino", "st_size", "st_mtime_ns"))
                        and after["st_size"] == common["size"]
                        and after["st_mtime_ns"] / 1_000_000 == common["mtimeMs"]
                        and after["st_nlink"] == 1 and (after["st_mode"] & 0o170000) == 0o100000,
                        "query-sync SDK full source stat changed during original read")
                require(Path(record["byteFile"]).is_relative_to(Path(raw["fixtureBase"]))
                        and Path(record["byteFile"]).read_bytes().hex() == common["hex"],
                        "query-sync SDK retained actual source blob differs from raw bytes")


def _snapshot_map(case, raw, events, *, native):
    rows = raw["snapshots"]
    labels = ["before-first-open", "after-first-open"]
    if case["input"]["queries"]["seed"] is not None:
        labels.append("after-seed")
    labels += ["after-mutation", "after-first-close", "before-reopened-open", "after-reopened-open", "after-final-close"]
    selected = [row for row in rows if row["label"] in labels]
    require([row["label"] for row in selected] == labels,
            "query-sync physical SQL snapshots were omitted, duplicated or reordered")
    snapshots = {}
    previous = 0
    for row in selected:
        start, end = _interval(row, events, "physical-sql-read-enter", "physical-sql-read-return", "SQL interval was reassigned")
        require(start > previous and events[start]["label"] == events[end]["label"] == row["label"]
                and Path(row["dbPath"]).is_relative_to(Path(raw["fixtureBase"])),
                "query-sync physical SQL snapshot belongs to another path or lifecycle")
        previous = end
        _physical_sql(row, native=native, allow_missing=row["label"] == "before-first-open")
        snapshots[row["label"]] = row
    require(len({row["dbPath"] for row in selected}) == 1,
            "query-sync SQL stages borrowed a different owner database")
    initial = snapshots["before-first-open"]
    require((initial.get("exists") is False) if native else initial.get("absent") is True,
            "query-sync cold case fabricated an existing empty index instead of actual absence")
    require((initial["error"].get("code") == "ENOENT") if native else
            initial["error"].get("errno") == 2 and initial["error"].get("name") == "FileNotFoundError",
            "query-sync initial absence lost actual OS ENOENT")
    _, before, after = _expected_sources(case)
    for label in ("after-first-close", "before-reopened-open", "after-reopened-open", "after-final-close"):
        _published_sources(snapshots[label], after, native=native, initial_sources=before)
    require(_same(_sql_payload(snapshots["after-first-close"]), _sql_payload(snapshots["before-reopened-open"]))
            and _same(_sql_payload(snapshots["before-reopened-open"]), _sql_payload(snapshots["after-reopened-open"])),
            "query-sync fresh owner acquisition changed its already completed publication")
    if "after-seed" in snapshots:
        _published_sources(snapshots["after-seed"], before, native=native)
    if native:
        reads = [call for call in raw["methodCalls"] if call["method"] == "prepareKeywordSearch"
                 and call["activeTool"] == "reopened"]
        reopened = _one(raw["snapshots"], lambda row: reads and row.get("methodCallId") == reads[-1]["id"],
                        "final SQL lost original reopened reader")
    else:
        reopened = _one(raw["readAdmissions"], lambda row: row["activeTool"] == "reopened",
                        "final SQL lost actual reopened pinned transaction")["pinnedSnapshot"]
    semantic_tables = (["memory_index_chunks", "memory_index_sources"] if native else
                       ["chunks", "memory_core_index_sources", "memory_index_chunk_details"])
    semantic_tables += ["memory_index_meta", "memory_index_chunk_provenance", "memory_index_chunk_recall_metadata"]
    require(all(_same(snapshots["after-final-close"]["tables"][name], reopened["tables"][name])
                for name in semantic_tables),
            "query-sync final closed publication differs from actual reopened source/chunk/metadata generation")
    if not native:
        catalogs = [row for row in rows if row["label"] in {"catalog-before", "catalog-after"}]
        require(len(catalogs) == 2 and _same(catalogs[0]["tables"], catalogs[1]["tables"])
                and all(not catalogs[0]["tables"][name] for name in
                        ("memory_session_events", "memory_session_nodes", "memory_session_archives")),
                "query-sync actual disabled session corpus was modified")
    return snapshots


def _tool_calls(case, raw, result, events, first_owner, reopened_owner, *, native):
    labels = [label for label in ("seed", "first", "reopened") if case["input"]["queries"][label] is not None]
    require(set(raw["toolCalls"]) == set(labels)
            and len(raw["originalSearchCalls"]) == len(labels), "query-sync added or omitted a real query")
    intervals = {}
    for label in labels:
        call = raw["toolCalls"][label]
        start, end = _interval(call, events, "actual-tool-enter", "actual-tool-return", "actual public tool interval was reassigned")
        args, output = case["input"]["queries"][label], result["searches"][label]
        require(call["label"] == events[start]["label"] == events[end]["label"] == label
                and _same(call["args"], args) and _same(events[start]["args"], args) and "error" not in call,
                "query-sync actual public request differs from frozen input")
        envelope = call["envelope"]
        require(isinstance(envelope, dict) and isinstance(envelope.get("content"), list)
                and len(envelope["content"]) == 1 and envelope["content"][0].get("type") == "text"
                and _same(json.loads(envelope["content"][0]["text"]), envelope["details"])
                and _same(envelope["details"], output), "query-sync whole public envelope/details was projected or replaced")
        if native:
            require(_same(json.loads(call["nativeEnvelopeSerializedJSON"]), envelope)
                    and set(call["nativeDetailsOwnKeys"]) == set(output) | set(call["nativeDetailsUndefinedOwnKeys"])
                    and set(call["nativeDetailsUndefinedOwnKeys"]).isdisjoint(output),
                    "query-sync Native public own-key/undefined custody was changed")
        else:
            encoded = (json.dumps(envelope, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode()
            file = call["envelopeFile"]
            require(file["bytes"] == len(encoded) and file["sha256"] == hashlib.sha256(encoded).hexdigest()
                    and file["path"] == str(Path(raw["fixtureBase"]) / f"tool-{label}-envelope.json")
                    and call["ownKeys"] == list(envelope) and call["detailsOwnKeys"] == list(output)
                    and call["resultOwnKeys"] == [list(hit) for hit in output["results"]],
                    "query-sync SDK early public envelope file/own-key receipt was rewritten")
        search = _one(raw["originalSearchCalls"], lambda row: row["activeTool"] == label,
                      "public tool lost unique actual original search")
        entered, returned = _interval(search, events, "original-search-enter", "original-search-return", "original search interval was reassigned")
        owner_id = reopened_owner if label == "reopened" else first_owner
        require(start < entered < returned < end and search["ownerId"] == owner_id
                and search["receiverIsExactObservedOwner"] is True and search["query"] == args["query"]
                and events[entered]["ownerId"] == events[returned]["ownerId"] == owner_id and "error" not in search,
                "query-sync public tool changed actual owner/query/receiver")
        _returned_hits(search, output, native=native)
        if not native:
            require(search["returnType"] == {"module": "memory_core.host.managed_index", "qualname": "_ManagedSearchResults"}
                    and set(search["returnAttributes"]) == {"_memory_search_status"}
                    and search["returnAttributes"]["_memory_search_status"]["custom"]["indexIdentity"] == {"status": "valid"},
                    "query-sync SDK actual managed return lost its pinned complete status")
        options = search["options"]
        for name, sdk_name in (("maxResults", "max_results"), ("minScore", "min_score")):
            require(_same(options[name if native else sdk_name], args[name]),
                    "query-sync actual original search options changed after public parsing")
        require(_same(options["sources"], ["memory"] if native else {"setValues": ["memory"]})
                and set(options) == {("[symbol:" + key[7:-1] + "]") if key.startswith("Symbol(") and key.endswith(")") else key for key in search["optionKeys"]},
                "query-sync original search options lost source/own-key values")
        statuses = [row for row in raw["statusCalls"] if row.get("activeTool") == label and (not native or row["ownerId"] == owner_id)]
        require(statuses and all(row["ownerId"] == owner_id and row["receiverIsExactObservedOwner"] is True
                    and start < row["enterSeq"] < row["returnSeq"] < end for row in statuses),
                "query-sync tool lost its full actual same-owner status consumption")
        if not native:
            binding = _one(raw["toolBindings"], lambda row: row["label"] == label, "SDK factory binding missing")
            require(binding["ownerId"] == owner_id and binding["storeIsExactObservedOwner"] is True
                    and binding["configIsExactOwnerConfig"] is True and binding["contextStatusIsNone"] is True
                    and binding["runtimeIdentityIsExactOwner"] is True
                    and events[binding["sequence"]]["event"] == "actual-tool-binding"
                    and binding["sequence"] < start,
                    "query-sync SDK public factory substituted its original owner/context/status")
        intervals[label] = (start, end, search)
    require(sum(row["event"] == "original-search-enter" for row in events.values()) == len(labels)
            == sum(row["event"] == "original-search-return" for row in events.values()),
            "query-sync owner executed an undeclared or hidden query")
    return intervals


def _read_generation(case, row, output, *, native, label):
    _physical_sql(row, native=native)
    _, before, after = _expected_sources(case)
    candidates = [before] if label == "seed" else [after] if label == "reopened" else [before, after]
    coherent = False
    for sources in candidates:
        try:
            _published_sources(row, sources, native=native, initial_sources=before)
        except ValueError:
            continue
        coherent = True
        break
    require(coherent, "query-sync actual reader contains a mixed or unrelated source generation")
    chunks = row["tables"]["memory_index_chunks" if native else "chunks"]
    query = case["input"]["queries"][label]["query"]
    expected_hits = [chunk for chunk in chunks if query.casefold() in chunk["text"].casefold()]
    require(bool(output["results"]) is bool(expected_hits),
            "query-sync public hit absence differs from its actual pinned generation")
    for hit in output["results"]:
        chunk = _one(chunks, lambda chunk: chunk["path"] == hit["path"]
                     and chunk["source"] == hit["source"] and _same(chunk["start_line"], hit["startLine"])
                     and _same(chunk["end_line"], hit["endLine"]), "public hit lost its actual read-generation chunk")
        require(hit["snippet"].strip() in chunk["text"],
                "query-sync actual hit text came from a different published generation")
        provenance = _one(row["tables"]["memory_index_chunk_provenance"],
                         lambda item: item["chunk_id"] == chunk["id"], "read-generation hit provenance missing")
        expected_provenance = {"originClass": provenance["origin_class"],
                "sessionKind": provenance["session_kind"], "observedAt": provenance["observed_at"]}
        if provenance["supersedes_key"] is not None:
            expected_provenance["supersedesKey"] = provenance["supersedes_key"]
        require(_same(hit.get("provenance"), expected_provenance),
                "query-sync public provenance lost its actual pinned generation metadata")


def _sdk_owners(case, raw, events, snapshots):
    owners = raw["owners"]
    require(set(owners) == {"first", "reopened"} and len(raw["ownerAcquisitions"]) == 2
            and owners["first"]["ownerId"] != owners["reopened"]["ownerId"],
            "query-sync SDK fresh owner missing or reused closed foreground owner")
    for role in ("first", "reopened"):
        owner = owners[role]
        require(owner["constructorName"] == "ManagedSQLiteMemoryStore"
                and owner["providerInitializedAtAcquisition"] is False,
                "query-sync SDK original query-free owner was substituted or initialized")
        acquisition = _one(raw["ownerAcquisitions"], lambda row: row["role"] == role,
                           "SDK original constructor receipt missing")
        start, end = _interval(acquisition, events, "original-open-enter", "original-open-return", "SDK constructor interval reassigned")
        require(acquisition["ownerId"] == owner["ownerId"] and acquisition["api"] == "ManagedSQLiteMemoryStore"
                and events[end]["returnedIsActualConstructedOwner"] is True
                and acquisition["workspaceIsExactOwner"] is True and acquisition["catalogIsExactOwner"] is True
                and _same(acquisition["config"], owner["config"]),
                "query-sync SDK actual acquisition substituted owner/config/workspace/catalog")
        prefix = "first" if role == "first" else "reopened"
        require(snapshots[f"before-{prefix}-open"]["returnSeq"] < start < end
                < snapshots[f"after-{prefix}-open"]["enterSeq"],
                "query-sync SDK constructor crossed its actual physical snapshots")
        config = owner["config"]
        require(config["workspace_dir"] == str(Path(raw["fixtureBase"]) / "workspace")
                and config["store_path"] == snapshots["after-first-open"]["dbPath"]
                and config["agent_id"] == case["input"]["identity"]["agentId"]
                and config["citation_mode"] == "off" and config["session_search"] is False
                and config["flags"]["vector_search"] is False and config["flags"]["mmr"] is True
                and config["flags"]["temporal_decay"] is True
                and config["search_max_results"] == 5 and config["search_min_score"] == 0,
                "query-sync SDK real config differs from supported memory-only provider-none profile")
        close = owner["close"]
        entered, returned = _interval(close, events, "original-close-enter", "original-close-return", "SDK actual close interval reassigned")
        lifecycle = close["lifecycle"]
        require(close["closed"] is True and close["returnedNone"] is True
                and lifecycle["closed"] is True and lifecycle["activeOperations"] == 0
                and lifecycle["lastSyncError"] is None
                and not any(lifecycle[key] for key in ("operationJournalTruncated", "repairJournalTruncated", "sessionReadJournalTruncated"))
                and all(row["state"] == "completed" and "error" not in row for row in lifecycle["operations"])
                and lifecycle["memoryPublication"]["active"] is False
                and lifecycle["memoryPublication"]["lastError"] is None
                and lifecycle["memoryPublication"]["jobsTruncated"] is False
                and all(row["state"] == "completed" and "error" not in row for row in lifecycle["memoryPublication"]["jobs"]),
                "query-sync SDK original close returned with active, failed or omitted admitted work")
    return owners["first"]["ownerId"], owners["reopened"]["ownerId"]


def _sdk_reads(case, raw, result, events, tools):
    require(len(raw["readAdmissions"]) == len(tools), "query-sync SDK omitted actual pinned reader admission")
    for label, (_, _, search) in tools.items():
        read = _one(raw["readAdmissions"], lambda row: row["activeTool"] == label,
                    "SDK actual reader hook missing")
        start, end = _interval(read, events, "original-method-enter", "original-method-return", "SDK original reader hook reassigned")
        pinned = read["pinnedSnapshot"]
        before, after = _interval(pinned, events, "pinned-sql-read-enter", "pinned-sql-read-return", "SDK pinned SQL receipt reassigned")
        require(search["enterSeq"] < start < before < after < end < search["returnSeq"]
                and read["method"] == "_on_search_snapshot" and read["receiverIsExactObservedOwner"] is True
                and read["ownerId"] == pinned["ownerId"] == search["ownerId"]
                and pinned["activeTool"] == label and pinned["threadId"] == read["threadId"]
                and pinned["inTransactionBefore"] is pinned["inTransactionAfter"] is True
                and pinned["sameActualConnectionPassedToOriginal"] is True
                and pinned["connectionId"] == events[before]["connectionId"] == events[after]["connectionId"]
                and pinned["readRevision"] == read["readRevision"]
                and [item for item in pinned["databases"] if item[1] == "main"] == [[0, "main", pinned["dbPath"]]],
                "query-sync SDK read generation was borrowed from a different connection/owner/transaction")
        _read_generation(case, pinned, result["searches"][label], native=False, label=label)
        state = pinned["tables"]["memory_core_index_sync"]
        require(state[0]["revision"] == read["readRevision"],
                "query-sync SDK pinned revision differs from actual physical state")
        lifecycle = read["lifecycleAfter"]
        admitted = _one(lifecycle["sessionReadAdmissions"], lambda row: row["operationId"] == pinned["operationId"],
                        "SDK actual read operation lacks original lifecycle admission")
        operation = _one(lifecycle["operations"], lambda row: row["id"] == pinned["operationId"],
                         "SDK actual read operation lost original search lifecycle")
        require(admitted["revision"] == read["readRevision"] and admitted["threadId"] == read["threadId"]
                and operation["name"] == "search" and operation["query"] == search["query"]
                and operation["threadId"] == read["threadId"],
                "query-sync SDK actual pinned reader admission lost its operation/thread/query")
        submit = _one(raw["backgroundCalls"], lambda row: row["method"] == "_submit_memory_publication"
                      and row["activeTool"] == label, "SDK reader lost actual publication admission call")
        require(start < after < submit["enterSeq"] < submit["returnSeq"] < end
                and submit["ownerId"] == read["ownerId"] and submit["readRevision"] == read["readRevision"]
                and submit["receiverIsExactObservedOwner"] is True and "error" not in submit,
                "query-sync SDK publication admission preceded actual pinned generation")
    require(sum(row["event"] == "original-method-enter" for row in events.values())
            == sum(row["event"] == "original-method-return" for row in events.values())
            == len(raw["methodCalls"]) + len(raw["backgroundCalls"]) + len(raw["readAdmissions"]),
            "query-sync SDK original method receipts were omitted or added")
    for owner in raw["owners"].values():
        require(owner["close"]["lifecycle"]["memoryPublication"]["jobCount"]
                == sum(call["method"] == "_run_memory_publication" and call["ownerId"] == owner["ownerId"] for call in raw["backgroundCalls"]),
                "query-sync SDK close job journal differs from actual worker invocations")
    for call in raw["methodCalls"] + raw["backgroundCalls"]:
        start, end = _interval(call, events, "original-method-enter", "original-method-return", "SDK actual worker/publication interval reassigned")
        require(events[start]["method"] == events[end]["method"] == call["method"]
                and events[start]["ownerId"] == events[end]["ownerId"] == call["ownerId"]
                and call["receiverIsExactObservedOwner"] is True and "error" not in call,
                "query-sync SDK original publication returned an error or changed receiver")
        close = _one(raw["owners"].values(), lambda owner: owner["ownerId"] == call["ownerId"],
                     "SDK worker belongs to unknown owner")["close"]
        require(end < close["returnSeq"], "query-sync SDK worker completed after original close return")
        if call["method"] == "reindex":
            search = tools[call["activeTool"]][2]
            lifecycle = _one(raw["owners"].values(), lambda owner: owner["ownerId"] == call["ownerId"],
                             "SDK bootstrap owner missing")["close"]["lifecycle"]
            repair = _one(lifecycle["repairs"], lambda repair: repair["searchOperationId"] in {
                operation["id"] for operation in lifecycle["operations"] if operation["name"] == "search"
                and operation.get("query") == search["query"]} and repair["force"] == call["request"]["force"],
                "SDK actual query bootstrap repair lifecycle missing")
            require(search["enterSeq"] < start < end < search["returnSeq"]
                    and repair["reason"] == "search-bootstrap" and repair["state"] == "completed"
                    and call.get("workspaceIsExactOwner") is True,
                    "query-sync SDK bootstrap was manually forced outside actual cold/empty query")
        elif call["method"] == "reindex_sources":
            run = _one(raw["backgroundCalls"], lambda row: row["method"] == "_run_memory_publication"
                       and row["ownerId"] == call["ownerId"] and row["enterSeq"] < start < end < row["returnSeq"],
                       "SDK scoped worker lacks original admitted publisher")
            require(call["request"] == {"sources": ["memory"], "paths": None, "forceSources": False}
                    and call["threadId"] == run["threadId"],
                    "query-sync SDK publication scope/worker thread was rewritten")
        elif call["method"] == "_run_memory_publication":
            lifecycle = call["lifecycleAfter"]
            own = _one(lifecycle["memoryPublication"]["jobs"], lambda row: row.get("id") == call["jobId"],
                       "SDK worker lacks actual completed job")
            require(own["state"] == "completed" and "error" not in own
                    and own["threadId"] == call["threadId"]
                    and call["actualWorkerTokenMatches"] is True and bool(call["workerTokenId"])
                    and call["jobAtEntry"]["id"] == call["jobId"]
                    and _same(call["jobAtReturn"], own),
                    "query-sync SDK caught background failure was presented as success")
            submit = _one(raw["backgroundCalls"], lambda row: row["method"] == "_submit_memory_publication"
                          and row["ownerId"] == call["ownerId"] and row["enterSeq"] < start
                          and call["jobId"] not in {job["id"] for job in row["before"]["jobs"]}
                          and call["jobId"] in {job["id"] for job in row["lifecycleAfter"]["memoryPublication"]["jobs"]},
                          "SDK actual worker lost its unique original job admission")
            require(call["jobAtEntry"] == {"id": call["jobId"], "readRevision": submit["readRevision"], "state": "queued"}
                    and own["readRevision"] == submit["readRevision"],
                    "query-sync SDK actual publication job detached from its admitted pinned revision")
        else:
            require(call["method"] == "_submit_memory_publication",
                    "query-sync SDK added unreviewed manual publication method")


def _native_owners(case, raw, events, snapshots):
    names, owners = raw["ownerNames"], raw["owners"]
    require(set(names) == {"foreground", "reopened"} and names["foreground"] != names["reopened"]
            and len(raw["facadeCalls"]) == 2, "query-sync Native fresh original owner was omitted or reused")
    for role in ("foreground", "reopened"):
        owner = owners[names[role]]
        require(owner["ownerId"] == names[role] and owner["purpose"] == "default"
                and owner["constructorName"] == "MemoryIndexManager"
                and owner["providerInitializedAtAcquisition"] is False,
                "query-sync Native query-free default owner was substituted")
        facade = _one(raw["facadeCalls"], lambda row: row["label"] == role, "Native actual facade missing")
        start, end = _interval(facade, events, "original-facade-enter", "original-facade-return", "Native original facade interval reassigned")
        require(facade["ownerId"] == owner["ownerId"] and facade["error"] is None
                and facade["debug"]["backend"] == "builtin" and facade["debug"]["purpose"] == "default",
                "query-sync Native public facade returned a different engine/purpose")
        prefix = "first" if role == "foreground" else "reopened"
        require(snapshots[f"before-{prefix}-open"]["returnSeq"] < start < end
                < snapshots[f"after-{prefix}-open"]["enterSeq"],
                "query-sync Native public acquisition crossed actual physical snapshots")
    for owner_id, owner in owners.items():
        settings = owner["settings"]
        require(owner["ownerId"] == owner_id and owner["purpose"] in {"default", "maintenance"}
                and settings["provider"] == settings["fallback"] == "none"
                and settings["sources"] == settings["searchSources"] == ["memory"]
                and settings["experimental"]["sessionMemory"] is False
                and settings["rememberAcrossConversations"] is False and settings["extraPaths"] == []
                and settings["store"]["vector"]["enabled"] is False
                and settings["store"]["databasePath"] == snapshots["after-first-open"]["dbPath"]
                and settings["sync"]["onSearch"] is True and settings["sync"]["watch"] is True
                and settings["sync"]["watchDebounceMs"] == 1500
                and settings["chunking"] == {"tokens": 400, "overlap": 80}
                and settings["query"]["hybrid"]["mmr"]["enabled"] is True
                and settings["query"]["hybrid"]["temporalDecay"]["enabled"] is True,
                "query-sync Native resolved original config changed actual source/watch/search defaults")
    require(_same(raw["requestedConfig"]["memory"], case["input"]["config"]["memory"])
            and raw["requestedConfig"]["agents"]["defaults"]["workspace"] == str(Path(raw["fixtureBase"]) / "workspace"),
            "query-sync Native requested config differs from frozen memory workspace")
    for row in raw["originalGetCalls"]:
        start, end = _interval(row, events, "original-get-enter", "original-get-return", "Native original getter interval reassigned")
        require(row["requestedPurpose"] in {"default", "maintenance"}
                and row["actualPurpose"] == row["requestedPurpose"]
                and owners[row["ownerId"]]["purpose"] == row["actualPurpose"]
                and row["receiverIsOriginalClass"] is True and row["agentId"] == "main"
                and _same(row["config"], raw["requestedConfig"]) and "error" not in row,
                "query-sync Native actual getter receiver/config/purpose was reassigned")
        if row["requestedPurpose"] == "maintenance":
            require(row["maintenanceSourceOwnerId"] in names.values()
                    and row["ownerId"] != row["maintenanceSourceOwnerId"]
                    and owners[row["maintenanceSourceOwnerId"]]["acquiredSeq"] < start,
                    "query-sync Native maintenance borrowed a foreign/default source owner")
    require({row["ownerId"] for row in raw["originalGetCalls"]} == set(owners),
            "query-sync Native returned original owner objects lost acquisition custody")
    return names["foreground"], names["reopened"]


def _native_reads(case, raw, result, events, tools):
    require(all(row["method"] in NATIVE_METHODS for row in raw["methodCalls"])
            and all(sum(row["event"] == f"original-{method}-{suffix}" for row in events.values())
                    == sum(row["method"] == method for row in raw["methodCalls"])
                    for method in NATIVE_METHODS for suffix in ("enter", "return")),
            "query-sync Native actual method receipts were removed or added")
    for bucket in ("statusCalls", "originalSearchCalls", "backgroundCalls"):
        method = {"statusCalls": "status", "originalSearchCalls": "search", "backgroundCalls": "syncPublishedIndexInBackground"}[bucket]
        require(_same(raw[bucket], [row for row in raw["methodCalls"] if row["method"] == method]),
                "query-sync Native specialized original receipts differ from complete original calls")
    for call in raw["methodCalls"]:
        start, end = _interval(call, events, f'original-{call["method"]}-enter',
                               f'original-{call["method"]}-return', "Native original method interval reassigned")
        require(call["receiverIsExactObservedOwner"] is True and "error" not in call
                and call["ownerId"] in raw["owners"]
                and events[start]["ownerId"] == events[end]["ownerId"] == call["ownerId"],
                "query-sync Native original method changed receiver or caught failed work")
    for label, (start, end, search) in tools.items():
        getter = _one(raw["originalGetCalls"], lambda row: row["activeTool"] == label
                      and row["requestedPurpose"] == "default", "Native tool original default getter missing")
        require(start < getter["enterSeq"] < getter["returnSeq"] < search["enterSeq"]
                and getter["ownerId"] == search["ownerId"] and getter["returnedIsExactSampledOwner"] is True,
                "query-sync Native public getter substituted the sampled original owner")
        preparations = [call for call in raw["methodCalls"] if call["method"] == "prepareKeywordSearch"
                        and call["activeTool"] == label and call["ownerId"] == search["ownerId"]]
        require(preparations, "query-sync Native actual search omitted original keyword preparation")
        for preparation in preparations:
            require(search["enterSeq"] < preparation["enterSeq"] < preparation["returnSeq"] < search["returnSeq"],
                    "query-sync Native original preparation lies outside its actual search")
            snapshot = _one(raw["snapshots"], lambda row: row.get("methodCallId") == preparation["id"],
                            "Native original preparation lost held-generation physical SQL")
            _physical_sql(snapshot, native=True)
            require(preparation["returnSeq"] < snapshot["enterSeq"] < snapshot["returnSeq"] < search["returnSeq"]
                    and snapshot["ownerId"] == preparation["ownerId"],
                    "query-sync Native physical reader capture moved after generation release")
            leases = [lease for lease in snapshot["coordinationLeases"] if lease["open"] is True
                      and lease["transactionActive"] is True and lease["location"] == snapshot["dbPath"] + ".generation-lock.sqlite"]
            require(len(leases) == 1, "query-sync Native keyword snapshot lacks actual held generation lock")
            lease = leases[0]
            begin = _one(raw["leaseCalls"], lambda row: row["databaseRef"] == lease["databaseRef"]
                         and row["method"] == "exec" and row["args"] == ["BEGIN"],
                         "Native actual shared generation transaction missing")
            pinned = _one(raw["leaseCalls"], lambda row: row["databaseRef"] == lease["databaseRef"]
                          and row["method"] == "statement.get", "Native actual generation transaction was not pinned")
            rollback = _one(raw["leaseCalls"], lambda row: row["databaseRef"] == lease["databaseRef"]
                            and row["method"] == "exec" and row["args"] == ["ROLLBACK"],
                            "Native original generation release missing")
            close = _one(raw["leaseCalls"], lambda row: row["databaseRef"] == lease["databaseRef"]
                         and row["method"] == "close", "Native generation DB original close missing")
            require(begin["returnSeq"] < pinned["enterSeq"] < pinned["returnSeq"] < preparation["enterSeq"]
                    < snapshot["returnSeq"] < rollback["enterSeq"] < rollback["returnSeq"] < close["enterSeq"]
                    and begin["transactionBefore"] is False and begin["transactionAfter"] is True
                    and pinned["transactionBefore"] is pinned["transactionAfter"] is True
                    and "acquireMemoryIndexReadGeneration" in begin["originalCallerStack"]
                    and close["openAfter"] is False,
                    "query-sync Native physical query lost its actual original held-lock interval")
            pool = _one(raw["poolCalls"], lambda row: row["activeTool"] == label
                        and row["args"][0].get("kind") == "keyword"
                        and preparation["enterSeq"] < row["enterSeq"] < row["returnSeq"] < preparation["returnSeq"],
                        "Native actual preparation lacks original keyword pool dispatch")
            job = pool["args"][0]
            require(job["databasePath"] == snapshot["dbPath"] and job["agentId"] == "main"
                    and job["includeIndexState"] is True and job["query"]["body"]["query"] == search["query"]
                    and job["query"]["body"]["sourceFilter"]["params"] == ["memory"]
                    and job["query"]["path"]["sourceFilter"]["params"] == ["memory"],
                    "query-sync Native actual keyword worker consumed another path/query/source")
            dispatch = _one(raw["workerDispatches"], lambda row: pool["enterSeq"] < row["enterSeq"]
                            < row["returnSeq"] < pool["returnSeq"] and _same(row["message"].get("input"), job),
                            "Native keyword pool lacked genuine worker postMessage")
            reply = _one(raw["workerMessages"], lambda row: row["workerId"] == dispatch["workerId"]
                         and row["message"].get("taskId") == dispatch["message"]["taskId"],
                         "Native keyword worker lost original reply")
            require(dispatch["returnSeq"] < reply["sequence"] < pool["returnSeq"]
                    and reply["threadId"] == dispatch["threadId"] > 0
                    and reply["message"]["status"] == "ok"
                    and _same(reply["message"]["value"], pool["result"])
                    and _same(pool["result"]["body"], preparation["result"]["keyword"]["body"])
                    and _same(pool["result"]["path"], preparation["result"]["keyword"]["path"])
                    and _same(pool["result"]["indexState"], preparation["result"]["indexState"]),
                    "query-sync Native original worker reply/result/index state was substituted")
        last = preparations[-1]
        snapshot = _one(raw["snapshots"], lambda row: row.get("methodCallId") == last["id"], "Native final read generation missing")
        _read_generation(case, snapshot, result["searches"][label], native=True, label=label)
        worker_hits = last["result"]["keyword"]["body"]["rows"]
        for hit in result["searches"][label]["results"]:
            worker_hit = _one(worker_hits, lambda row: row["path"] == hit["path"]
                              and row["startLine"] == hit["startLine"] and row["endLine"] == hit["endLine"],
                              "Native public hit was not returned by its real keyword worker")
            require(all(_same(worker_hit[key], hit[key]) for key in ("path", "startLine", "endLine", "score", "snippet", "source", "textScore")),
                    "query-sync Native original worker hit fields changed before public return")
    for lease in raw["leaseCalls"]:
        _interval(lease, events, "original-coordination-enter", "original-coordination-return", "Native coordination call was reassigned")
        require("error" not in lease and isinstance(lease["originalCallerStack"], str)
                and lease["location"].startswith(raw["owners"][raw["ownerNames"]["foreground"]]["settings"]["store"]["databasePath"] + ".generation-"),
                "query-sync Native actual generation coordination failed or borrowed another DB")
    for call in raw["poolCalls"]:
        _interval(call, events, "original-pool-run-enter", "original-pool-run-return", "Native actual pool interval reassigned")
        require("error" not in call and "result" in call, "query-sync Native actual worker failed before publication")
    for call in raw["workerDispatches"]:
        _interval(call, events, "actual-worker-dispatch-enter", "actual-worker-dispatch-return", "Native actual worker dispatch reassigned")
        require("error" not in call and call["returnedUndefined"] is True,
                "query-sync Native actual worker postMessage failed")


def _schedule(case, raw, events, snapshots, tools, first_owner, reopened_owner, *, native):
    mutation = raw["sourceMutation"]
    start, end = _interval(mutation, events, "source-mutation-enter", "source-mutation-return", "real source mutation interval reassigned")
    require(_same(mutation["specification"], case["input"]["sourceMutation"])
            and _same(events[start]["specification"], mutation["specification"])
            and (tools["seed"][1] < start if "seed" in tools else snapshots["after-first-open"]["returnSeq"] < start)
            and end < raw["sourceStages"]["afterMutation"]["enterSeq"]
            < raw["sourceStages"]["afterMutation"]["returnSeq"] < snapshots["after-mutation"]["enterSeq"]
            < snapshots["after-mutation"]["returnSeq"] < tools["first"][0],
            "query-sync actual filesystem mutation crossed its prepared source/first-query boundary")
    if native:
        closed = {}
        for role, owner_id in (("first", first_owner), ("reopened", reopened_owner)):
            row = _one(raw["methodCalls"], lambda row: row["method"] == "close" and row["ownerId"] == owner_id,
                       "Native original public owner close missing")
            require(row["stateAfter"]["closed"] is True and row["stateAfter"]["closing"] is True
                    and row["stateAfter"]["activeManagerOperations"] == 0
                    and row["stateAfter"]["activeBackgroundSearchSyncs"] == 0,
                    "query-sync Native original close left admitted work active")
            closed[role] = row
        spec = case["input"]["sourceMutation"]
        if spec and spec["kind"] != "none":
            entered, returned = mutation["notificationEnterSeq"], mutation["notificationReturnSeq"]
            dirty = _one(raw["methodCalls"], lambda row: row["method"] == "markMemoryWatchDirty"
                         and entered < row["enterSeq"] < row["returnSeq"] < returned,
                         "Native declared real mutation lost original dirty notification")
            require(start < entered < returned < end and dirty["ownerId"] == first_owner
                    and dirty["stateAfter"]["dirty"] is True,
                    "query-sync Native declared dirty notification changed owner or forced publication")
        for background in raw["backgroundCalls"]:
            role = "reopened" if background["ownerId"] == reopened_owner else "first"
            require(background["ownerId"] in {first_owner, reopened_owner}
                    and tools[role][2]["enterSeq"] < background["enterSeq"] < tools[role][2]["returnSeq"]
                    and background["returnSeq"] < closed[role]["returnSeq"]
                    and background.get("returnedPromiseRef") and "error" not in background,
                    "query-sync Native admitted original publication escaped original close settlement")
        for idle in (row for row in raw["methodCalls"] if row["method"] == "awaitManagerIdle"):
            require(any(row["method"] == "close" and row["ownerId"] == idle["ownerId"]
                        and row["enterSeq"] < idle["enterSeq"] < idle["returnSeq"] < row["returnSeq"]
                        for row in raw["methodCalls"]),
                    "query-sync Native adapter inserted private wait outside original close")
    else:
        closed = {role: raw["owners"][role]["close"] for role in ("first", "reopened")}
    require(tools["first"][1] < closed["first"]["enterSeq"] < closed["first"]["returnSeq"]
            < snapshots["after-first-close"]["enterSeq"] < snapshots["after-first-close"]["returnSeq"]
            < raw["sourceStages"]["afterFirstClose"]["enterSeq"]
            < raw["sourceStages"]["afterFirstClose"]["returnSeq"]
            < snapshots["before-reopened-open"]["enterSeq"]
            and snapshots["after-reopened-open"]["returnSeq"] < tools["reopened"][0]
            < tools["reopened"][1] < closed["reopened"]["enterSeq"] < closed["reopened"]["returnSeq"]
            < snapshots["after-final-close"]["enterSeq"] < snapshots["after-final-close"]["returnSeq"]
            < raw["sourceStages"]["afterFinalClose"]["enterSeq"],
            "query-sync first/close/physical/reopen/final-close lifecycle order was reassigned")
    allowed_between = {"actual-worker-message", "actual-worker-exit", "original-coordination-enter", "original-coordination-return",
                       "original-method-return", "original-method-enter", "original-pool-run-return"}
    gap = [row for row in events.values() if tools["first"][1] < row["sequence"] < closed["first"]["enterSeq"]]
    require(all(row["event"] in allowed_between and row.get("ownerId", first_owner) != reopened_owner for row in gap),
            "query-sync adapter inserted an operation between actual first tool and original close")
    if native:
        entered = _one(events.values(), lambda row: row["event"] == "runtime-close-all-enter", "Native original close-all enter missing")
        returned = _one(events.values(), lambda row: row["event"] == "runtime-close-all-return", "Native original close-all return missing")
        rows, gets = raw["finalManagerStates"], raw["originalGetCalls"]
        ids = {row["ownerId"] for row in gets}
        require(raw["runtimeCloseAllInvoked"] is raw["runtimeCloseAllReturned"] is True
                and raw["sourceStages"]["afterFinalClose"]["returnSeq"] < entered["sequence"] < returned["sequence"] == len(events)
                and returned["returnedNormally"] is True and {row["ownerId"] for row in rows} == ids
                and len(rows) == len(ids) and set(entered["returnedManagerIds"]) == ids
                and _same(returned["finalManagerStates"], rows)
                and all(row["closed"] is row["closing"] is True and row["purpose"] in {"default", "maintenance"}
                        and all(get["actualPurpose"] == row["purpose"] for get in gets if get["ownerId"] == row["ownerId"])
                        for row in rows) and returned["allManagersClosed"] is True,
                "query-sync Native close-all success was inferred without every actual owner closed")


def _implementation_bindings(raw):
    bindings = raw["implementationBindings"]
    required = {"memory_core.host.managed_index", "memory_core.index.sqlite_store",
                "memory_core.index.publication", "memory_core.tools.search_factory", "memory_core.tools.memory_search"}
    require(isinstance(bindings, list) and required <= {row["module"] for row in bindings}
            and len({row["module"] for row in bindings}) == len(bindings),
            "query-sync SDK omitted actual loaded implementation modules")
    implementation = Path(raw["implementationRoot"])
    for row in bindings:
        path = Path(row["path"])
        require(path.is_relative_to(implementation) and path.is_file()
                and hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"],
                "query-sync SDK actual imported implementation bytes changed")
        relative = path.relative_to(implementation)
        current = ROOT / relative
        require(current.is_file() and hashlib.sha256(current.read_bytes()).hexdigest() == row["sha256"],
                "query-sync SDK capture belongs to different current production bytes")


def _raw(case, raw, result, *, native, approved_node=None):
    require(isinstance(raw, dict) and raw.get("kind") == "query-sync-outcomes"
            and raw.get("engine") == ("native" if native else "sdk") and raw.get("caseId") == case["id"]
            and _same(raw.get("input"), case["input"])
            and type(raw.get("pid")) is int and type(raw.get("ppid")) is int
            and raw["pid"] > 0 and raw["ppid"] > 0 and raw["pid"] != raw["ppid"]
            and Path(raw["fixtureBase"]).is_absolute() and raw.get("completed") is True
            and raw.get("allManagersClosed") is True and "error" not in raw
            and "teardownError" not in raw and not raw.get("teardownErrors") and _same(raw["result"], result),
            "query-sync protected engine capture is incomplete or belongs to another actual attempt")
    if not native:
        _private_markers(raw)
        require(_same(raw["clock"], {"owner": "public-tool-clock", "nowMs": case["input"]["nowMs"], "monotonicAndTimers": "unmodified"})
                and _same(raw["requestedConfig"], case["input"]["config"])
                and raw["sourcePolicy"]["sources"] == raw["sourcePolicy"]["searchSources"] == ["memory"]
                and raw["sdkProfile"]["memoryPublication"] == "on-search"
                and raw["sdkProfile"]["contextStatus"] is None,
                "query-sync SDK actual source/publication/clock profile was substituted")
        _implementation_bindings(raw)
    events = _chronology(raw)
    _source_custody(case, raw, result, events, native=native)
    snapshots = _snapshot_map(case, raw, events, native=native)
    first_owner, reopened_owner = (_native_owners if native else _sdk_owners)(case, raw, events, snapshots)
    for status in raw["statusCalls"]:
        _interval(status, events, "original-status-enter", "original-status-return", "actual status call reassigned")
        require(isinstance(status["result"], dict) and _finite(status["result"])
                and status["receiverIsExactObservedOwner"] is True,
                "query-sync complete original status return was dropped")
    tools = _tool_calls(case, raw, result, events, first_owner, reopened_owner, native=native)
    (_native_reads if native else _sdk_reads)(case, raw, result, events, tools)
    if native:
        authority = _native_process(case, raw, approved_node=approved_node)
        _native_publication(case, raw, authority)
    _schedule(case, raw, events, snapshots, tools, first_owner, reopened_owner, native=native)
    return True


def _sdk(case, dispatch, result):
    require(isinstance(dispatch, dict) and dispatch.get("kind") == "query-sync-outcomes-sdk-dispatch"
            and _same(dispatch.get("input"), case["input"]) and _same(dispatch.get("exit"), {"code": 0})
            and type(dispatch["pid"]) is type(dispatch["coordinatorPid"]) is int
            and dispatch["pid"] != dispatch["coordinatorPid"]
            and all(isinstance(dispatch[key], str) and dispatch[key].isdigit() for key in ("startedAtNs", "finishedAtNs"))
            and int(dispatch["startedAtNs"]) < int(dispatch["finishedAtNs"]),
            "query-sync SDK protected process dispatch failed or was reassigned")
    wire = dispatch["requestJson"]
    request = json.loads(wire)
    require(_same(request, dispatch["request"]) and set(request) == {"input", "directory"}
            and _same(request["input"], case["input"])
            and hashlib.sha256(wire.encode()).hexdigest() == dispatch["requestSha256"]
            and dispatch["argv"][1:] == ["-m", "equivalence.query_sync_outcomes_sdk_cli"]
            and dispatch["environmentKeys"] == ["LANG", "OPENCLAW_HOME", "OPENCLAW_STATE_DIR", "PATH", "PYTHONPATH", "TZ"],
            "query-sync SDK actual process request/argv/environment carrier changed")
    observed = json.loads(dispatch["stdout"])
    require(_same(observed, dispatch["observation"]) and set(observed) == {"result", "raw"}
            and _same(observed["result"], result), "query-sync SDK stdout lost complete actual public/raw output")
    raw = observed["raw"]
    require(raw["pid"] == dispatch["pid"] and raw["ppid"] == dispatch["coordinatorPid"]
            and raw["fixtureBase"] == request["directory"]
            and raw["process"]["executable"] == dispatch["argv"][0]
            and raw["process"]["cwd"] == raw["implementationRoot"]
            and set(raw["process"]["environmentKeys"]) in (set(dispatch["environmentKeys"]), set(dispatch["environmentKeys"]) | {"LC_CTYPE"})
            and int(dispatch["startedAtNs"]) < int(raw["events"][0]["atNs"])
            <= int(raw["events"][-1]["atNs"]) < int(dispatch["finishedAtNs"]),
            "query-sync SDK actual child PID/directory/environment/chronology was reassigned")
    return _raw(case, raw, result, native=False)


def validate_result(case, result):
    try:
        return _validate_result(case, result)
    except (KeyError, IndexError, TypeError, AttributeError, StopIteration, json.JSONDecodeError, OSError) as error:
        raise ValueError("query-sync public result is structurally incomplete") from error


def validate_capture(case, capture, result, *, native, approved_node=None):
    validate_result(case, result)
    try:
        return _raw(case, capture, result, native=True, approved_node=approved_node) if native else _sdk(case, capture, result)
    except (KeyError, IndexError, TypeError, AttributeError, StopIteration, json.JSONDecodeError, OSError) as error:
        raise ValueError(("Native" if native else "SDK") + " query-sync evidence is structurally incomplete") from error


def validate_pair(case, native_raw, sdk_raw, native_result, sdk_result, *, approved_node=None):
    validate_capture(case, native_raw, native_result, native=True, approved_node=approved_node)
    validate_capture(case, sdk_raw, sdk_result, native=False)
    require(_same(native_result, sdk_result), "query-sync complete actual public result differs across engines")
    return True


def replay_case(case, directory, *, approved_node=None):
    directory = Path(directory)
    native = json.loads((directory / "stdout.json").read_text())["result"]
    sdk = json.loads((directory / "sdk-output.json").read_text())
    originals = json.loads((directory / "evidence/native-raw.json").read_text())
    copies = json.loads((directory / "evidence/python-raw.json").read_text())
    require(len(originals) == len(copies) == 1, "query-sync replay requires one actual capture per engine")
    validate_pair(case, originals[0], copies[0], native, sdk, approved_node=approved_node)
    return {"validated": True, "nativeSnapshots": 1, "sdkSnapshots": 1}


# This program only decodes the original Node V8 transport. It imports no engine,
# evaluates no captured code, opens no fixture, and makes no network calls.
V8_DECODER = r'''
import {deserialize} from 'node:v8';
import fs from 'node:fs';
function carrier(value, seen=new WeakSet()) {
  if(value===undefined)return {privateType:'undefined'};
  if(typeof value==='bigint')return {privateType:'bigint',value:value.toString()};
  if(typeof value==='number'&&!Number.isFinite(value))return {privateType:'number',value:String(value)};
  if(value===null||typeof value!=='object')return value;
  if(ArrayBuffer.isView(value))return {privateType:value.constructor.name,byteLength:value.byteLength,hex:Buffer.from(value.buffer,value.byteOffset,value.byteLength).toString('hex')};
  if(value instanceof ArrayBuffer)return {privateType:'ArrayBuffer',byteLength:value.byteLength,hex:Buffer.from(value).toString('hex')};
  if(seen.has(value))throw Error('Unreviewed repeated/cyclic V8 value');
  seen.add(value);
  if(value instanceof Map)return {privateType:'Map',entries:[...value].map(([k,v])=>[carrier(k,seen),carrier(v,seen)])};
  if(value instanceof Set)return {privateType:'Set',values:[...value].map(v=>carrier(v,seen))};
  if(Array.isArray(value))return value.map(v=>carrier(v,seen));
  return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,carrier(v,seen)]));
}
const input=JSON.parse(fs.readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify(input.map(hex=>carrier(deserialize(Buffer.from(hex,'hex'))))));
'''
_V8_CACHE = {}


def _decode_v8(authority, wires):
    binary = Path(authority["execPath"])
    binary_hash = hashlib.sha256(binary.read_bytes()).hexdigest()
    require(binary_hash == authority["sha256"], "query-sync approved V8 decoder binary bytes changed")
    decoder_hash = hashlib.sha256(V8_DECODER.encode()).hexdigest()
    missing = list(dict.fromkeys(wire for wire in wires if (binary_hash, decoder_hash, wire) not in _V8_CACHE))
    if missing:
        finished = subprocess.run([str(binary), "--input-type=module", "-e", V8_DECODER],
            input=json.dumps(missing), capture_output=True, text=True, timeout=30,
            cwd="/tmp", env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "TZ": "UTC"}, check=False)
        require(finished.returncode == 0 and not finished.stderr,
                "query-sync actual V8 transport failed independent approved decoding")
        values = json.loads(finished.stdout)
        require(isinstance(values, list) and len(values) == len(missing),
                "query-sync actual V8 decoder lost a complete original wire value")
        for wire, value in zip(missing, values, strict=True):
            _V8_CACHE[binary_hash, decoder_hash, wire] = value
    return [_V8_CACHE[binary_hash, decoder_hash, wire] for wire in wires]


def _native_process(case, raw, *, approved_node=None):
    directory = Path(raw["fixtureBase"]).parent
    context_path, process_path = directory / "context.json", directory / "process.json"
    context, process = json.loads(context_path.read_text()), json.loads(process_path.read_text())
    require(process["pid"] == raw["pid"] and process["parentPid"] == raw["ppid"]
            and process["returncode"] == 0 and process["contextPath"] == str(context_path)
            and process["contextSha256"] == hashlib.sha256(context_path.read_bytes()).hexdigest()
            and process["requestSha256"] == hashlib.sha256(Path(process["requestPath"]).read_bytes()).hexdigest()
            and _same(json.loads(Path(process["requestPath"]).read_text()), {key: case[key] for key in ("id", "operation", "input")})
            and int(process["startedAtNs"]) < int(raw["events"][0]["atNs"])
            <= int(raw["events"][-1]["atNs"]) < int(process["finishedAtNs"]),
            "query-sync Native actual PID/request/context/process interval changed")
    require(context["stateDirectory"] == raw["fixtureBase"] and context["fetchPolicy"] == "deny"
            and context["providerMode"] == "none" and process["argv"][0] == context["approvedNodeRuntime"]["execPath"]
            and process["environment"]["OPENCLAW_STATE_DIR"] == raw["fixtureBase"]
            and process["environment"]["MEMORY_EQ_RELEASE_CONTEXT"] == str(context_path)
            and set(process["environment"]) == {"PATH", "LANG", "TZ", "NODE_OPTIONS", "MEMORY_EQ_RELEASE_CONTEXT", "OPENCLAW_STATE_DIR", "OPENCLAW_CONFIG_PATH"},
            "query-sync Native actual executable/environment/source fixture was substituted")
    returned = json.loads(Path(process["stdoutPath"]).read_text())
    require(returned["id"] == case["id"] and returned["ok"] is True and _same(returned["result"], raw["result"]),
            "query-sync Native actual stdout dropped complete public results")
    local = {row["path"]: row["sha256"] for row in context["allowedLocal"]}
    for filename, digest in local.items():
        require(Path(filename).is_file() and hashlib.sha256(Path(filename).read_bytes()).hexdigest() == digest,
                "query-sync Native protected actor bytes changed after actual execution")
    expected = {(package["location"], file["path"]): file["sha256"]
                for package in context["runtime"]["packages"] for file in package["files"]}
    threads, main, worker, oracle = set(), set(), set(), set()
    for path in sorted(Path(context["traceDirectory"]).glob("*.jsonl")):
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        require(rows and rows[0]["event"] == "bootstrap", "query-sync Native actual import trace lacks bootstrap")
        first = rows[0]
        require(first["pid"] == raw["pid"] and first["ppid"] == raw["ppid"]
                and first["runtime"] == context["approvedNodeRuntime"] and first["fetchDenied"] is True
                and first["contextSha256"] == process["contextSha256"]
                and first["isMainThread"] is (first["threadId"] == 0)
                and path.name == f'{raw["pid"]}-{first["threadId"]}.jsonl',
                "query-sync Native imported worker belongs to another actual process/binary")
        require(first["threadId"] not in threads, "query-sync Native duplicated actual worker import trace")
        threads.add(first["threadId"])
        own = [row for row in rows if row["event"] == "query-sync-outcomes-bootstrap"]
        require(len(own) == 1 and own[0]["clock"]["apis"] == ["Date"]
                and own[0]["clock"]["nowMs"] == case["input"]["nowMs"]
                and own[0]["clock"]["setTimeoutUnchanged"] is True
                and own[0]["clock"]["performanceNowUnchanged"] is True,
                "query-sync Native actual workers changed timer or Date-only profile")
        for row in rows[1:]:
            require(row["pid"] == raw["pid"] and row["threadId"] == first["threadId"],
                    "query-sync Native actual import trace changed worker identity")
            if row["event"] == "query-sync-outcomes-bootstrap":
                continue
            require(row["event"] in {"load", "resolve-native"}, "query-sync Native actual import trace added unknown operation")
            if row.get("kind") == "oracle":
                require(local.get(row["path"]) == row["sha256"], "query-sync Native unapproved actor executed")
                oracle.add(row["path"])
            else:
                require(row.get("kind") == "release" and expected.get((row["package"], row["path"])) == row["sha256"],
                        "query-sync Native actual imported engine source bytes changed")
                (main if first["isMainThread"] else worker).add(row["path"])
    require(0 in threads and len(threads) > 1 and set(local) - {str(Path(process["cwd"]) / "equivalence/query-sync-outcomes-preload.mjs")} <= oracle
            and {"dist/extensions/memory-core/manager-runtime.js", "dist/tools-DotaQGXh.mjs"} <= main
            and "dist/sqlite-worker-store-D6Kl0iv0.mjs" in worker,
            "query-sync Native actual public manager/tool/read/publication workers did not execute")
    authority = context["approvedNodeRuntime"]
    configured = approved_node or os.environ.get("MEMORY_EQ_NODE")
    local = ROOT / "work/node-v24.16.0-linux-x64/bin/node"
    selected = configured or (str(local) if local.is_file() else shutil.which("node"))
    require(selected is not None, "query-sync independent trusted Node decoder is unavailable")
    trusted = Path(selected).resolve(strict=True)
    require(trusted == Path(authority["execPath"]) and trusted.is_file()
            and hashlib.sha256(trusted.read_bytes()).hexdigest() == authority["sha256"],
            "query-sync captured Node authority differs from independently trusted decoder")
    return {**authority, "execPath": str(trusted)}


def _native_publication(case, raw, authority):
    encoded = []
    for direction, rows in (("request", raw["workerDispatches"]), ("reply", raw["workerMessages"])):
        for row in rows:
            message = row["message"]
            keys = ["input", "preparation"] if direction == "request" and message.get("type") in {"open", "execute", "execute-frame"} else ["value"] if direction == "reply" and type(message.get("id")) is int and message.get("ok") is True else []
            selected = {key for key in keys if isinstance(message.get(key), dict) and message[key].get("privateType") in {"Uint8Array", "Buffer"}}
            require(set(row["decodedSerialized"]) == selected,
                    "query-sync Native opaque SQL transport lacks complete actual decoded byte custody")
            for key in selected:
                wire = message[key]
                receipt = row["decodedSerialized"][key]
                require(wire["byteLength"] == len(bytes.fromhex(wire["hex"]))
                        and receipt["bytesSha256"] == hashlib.sha256(bytes.fromhex(wire["hex"])).hexdigest()
                        and "error" not in receipt, "query-sync Native original serialized SQL bytes changed or failed decoding")
                encoded.append((wire["hex"], receipt["value"]))
    decoded = _decode_v8(authority, [wire for wire, _ in encoded])
    require(all(_same(value, claimed) for value, (_, claimed) in zip(decoded, encoded, strict=True)),
            "query-sync Native serialized SQL parameters/replies differ from actual V8 wire bytes")
    commands = []
    for dispatch in raw["workerDispatches"]:
        message = dispatch["message"]
        if not dispatch["decodedSerialized"]:
            continue
        data = dispatch["decodedSerialized"].get("input", {}).get("value")
        if not isinstance(data, dict) or "type" not in data:
            require(message.get("type") == "open", "query-sync Native actual execute command type was removed")
            continue
        require(data["type"] in {"database.domain.bind", "database.domain.close", "database.domain.execute",
                "database.prepareWrite", "database.publish", "pluginState.appendJournal", "pluginState.compareDelete",
                "pluginState.compareUpdate", "pluginState.lookup", "pluginState.observe", "source.delete", "source.replace",
                "stage.append", "stage.start"}, "query-sync Native decoded original command type is unreviewed")
        replies = [row for row in raw["workerMessages"] if row["workerId"] == dispatch["workerId"]
                   and row["message"].get("id") == message.get("id")]
        if not replies:
            # The actual recall-event journal is fire-and-forget, outside the
            # original manager's index publication ownership. Its full bytes
            # remain custody; it supplies no publication-completion credit.
            require(data["type"] == "pluginState.appendJournal",
                    "query-sync Native serialized publication request lost original reply")
            continue
        require(len(replies) == 1 and dispatch["returnSeq"] < replies[0]["sequence"]
                and replies[0]["message"].get("ok") is True,
                "query-sync Native actual SQL worker rejected or lost a dispatched operation")
        reply = replies[0]
        command = data["input"]["command"] if data["type"] == "database.domain.execute" else data
        require(command["type"] in {"database.domain.bind", "database.domain.close", "database.prepareWrite", "database.publish",
                "pluginState.appendJournal", "pluginState.compareDelete", "pluginState.compareUpdate", "pluginState.lookup",
                "pluginState.observe", "source.delete", "source.replace", "stage.append", "stage.start"},
                "query-sync Native actual publication command type bypassed reviewed dataflow")
        commands.append((dispatch, command, reply))
    stages = {}
    _, before, after = _expected_sources(case)
    for dispatch, command, reply in commands:
        typ, value = command["type"], command.get("input")
        if typ == "stage.start":
            header, entry = value["header"], value["header"]["entry"]
            sources = before if dispatch["activeTool"] == "seed" else after
            require(entry["path"] in sources and entry["hash"] == hashlib.sha256(sources[entry["path"]][0].encode()).hexdigest()
                    and entry["size"] == len(sources[entry["path"]][0].encode())
                    and entry["mtimeMs"] == sources[entry["path"]][1] and header["source"] == "memory"
                    and header["model"] == "fts-only" and value["rows"] == 1,
                    "query-sync Native actual publication source parameters differ from real observed source")
            require(value["operation"] not in stages, "query-sync Native duplicated staged original publication operation")
            stages[value["operation"]] = {"start": dispatch, "header": header, "fragments": [], "replace": None}
        elif typ == "stage.append":
            stage = stages[value["operation"]]
            require(stage["start"]["returnSeq"] < dispatch["enterSeq"]
                    and len(value["fragments"]) == 1 and value["fragments"][0]["row"] == 0
                    and value["fragments"][0]["part"] == 0 and value["fragments"][0]["last"] is True,
                    "query-sync Native actual staged chunk fragments were removed or reordered")
            fragment = json.loads(value["fragments"][0]["json"])
            chunk, entry = fragment["chunk"], stage["header"]["entry"]
            require(fragment["embedding"] == [] and chunk["hash"] == entry["hash"]
                    and chunk["hash"] == hashlib.sha256(chunk["text"].encode()).hexdigest()
                    and len(chunk["text"].encode()) == entry["size"]
                    and chunk["provenance"] == {"originClass": "agent", "sessionKind": "unknown", "observedAt": entry["mtimeMs"]},
                    "query-sync Native actual publication chunk parameters lost source bytes/provenance")
            stage["fragments"].append((dispatch, fragment))
        elif typ == "source.replace":
            stage = stages[value["operation"]]
            require(len(stage["fragments"]) == 1 and stage["fragments"][0][0]["returnSeq"] < dispatch["enterSeq"]
                    and stage["replace"] is None, "query-sync Native original replace omitted its actual staged bytes")
            stage["replace"] = dispatch
        elif typ == "database.publish":
            index_path = raw["owners"][raw["ownerNames"]["foreground"]]["settings"]["store"]["databasePath"]
            require(value["sourcePath"].startswith(index_path + ".memory-reindex-")
                    and value["metaKey"] == "memory_index_meta_v1"
                    and type(value["expectedRevision"]) is int and value["expectedRevision"] >= 0
                    and value["sourceHasVectors"] is False and value["vectorIndexComplete"] is True
                    and value["sourceIdentity"]["device"].isdigit() and value["sourceIdentity"]["inode"].isdigit(),
                    "query-sync Native original full publication parameters changed staged identity/profile")
        elif typ == "source.delete":
            require(value["source"] == "memory" and value["path"] in before
                    and (value["path"] not in after or before[value["path"]] != after[value["path"]])
                    and value["expectedHash"] == hashlib.sha256(before[value["path"]][0].encode()).hexdigest(),
                    "query-sync Native actual delete parameters targeted a different source/hash")
    require(all(stage["replace"] is not None for stage in stages.values()),
            "query-sync Native actual prepared source never reached original publication replace")
