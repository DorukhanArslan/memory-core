"""Bind complete recall observations to actual sources, durable rows and calls.

No recall, dedupe, ranking, retention or event-normalization algorithm is
reimplemented here. Language returns and exceptions remain private raw facts;
the declared portable interface is complete business state and completion.
"""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from equivalence.forget_lineage_evidence import _bytes, physical_snapshot
from equivalence.forget_lineage_outcomes_evidence import (
    ORIGIN_FIELDS, TOMBSTONE_FIELDS, _files, _rows, _sdk_physical, _tables,
)
from equivalence.recall_signals import FAILURE_MARKER, canonical, validate_case
from equivalence.recall_signals_bindings import COMPILED_HASHES, GENUINE_HELPER_EXPORTS
from equivalence.search_contract import _same_json

ROOT = Path(__file__).resolve().parents[1]
TRIGGER = "recall_signal_origin_failure"
TRIGGER_SQL = (
    "CREATE TRIGGER recall_signal_origin_failure BEFORE INSERT ON memory_entry_origins "
    "BEGIN SELECT RAISE(ABORT,'recall-origin-write-blocked'); END"
)
RECALL_FILE = "workspace/memory/.dreams/short-term-recall.json"
GUARD = "workspace/memory/.dreams/short-term-promotion.lock.guard"


def _require(value, message):
    if not value:
        raise ValueError("recall signals: " + message)


def _same(left, right, message):
    _require(canonical(left) == canonical(right), message)


def _state(raw, capture, observed, native):
    _require(set(observed) == {"recall", "origins", "tombstones", "events"},
             "the complete portable state interface changed")
    if native:
        fixture, state = capture["fixture"], capture["state"]
        _same(fixture["root"], raw["fixtureBase"], "Native fixture ownership changed")
        _same(state["root"], raw["stateDirectory"], "Native state ownership changed")
        _same(json.loads(_bytes(capture["config"])), raw["config"], "physical Native configuration changed")
        files, state_files = _files(fixture), _files(state)
        _tables(fixture, files)
        databases = _tables(state, state_files)
        _require("state/openclaw.sqlite" in databases, "the actual plugin state database is missing")
        plugin = databases["state/openclaw.sqlite"]["tables"]
        entries, metadata, events, cursors = {}, [], [], []
        workspace_key = hashlib.sha256(raw["workspace"].encode()).hexdigest()
        for row in plugin["plugin_state_entries"]:
            _require(set(row) == {"plugin_id", "namespace", "entry_key", "value_json", "created_at", "expires_at"}
                     and row["plugin_id"] == "memory-core" and row["expires_at"] is None
                     and type(row["created_at"]) is int and row["created_at"] > 0,
                     "a physical plugin row lost its full original identity")
            value = json.loads(row["value_json"])
            if row["namespace"] in {"short-term-recall", "short-term-meta"}:
                _require(set(value) == {"version", "workspaceKey", "workspaceDir", "key", "value"}
                         and value["version"] == 1 and value["workspaceKey"] == workspace_key
                         and value["workspaceDir"] == raw["workspace"]
                         and row["entry_key"] == workspace_key + ":" + hashlib.sha256(value["key"].encode()).hexdigest(),
                         "a stored signal escaped its actual workspace/key")
                if row["namespace"] == "short-term-recall":
                    _require(value["key"] not in entries, "duplicate physical recall key")
                    entries[value["key"]] = value["value"]
                else:
                    _require(value["key"] == "recall", "unexpected signal metadata")
                    metadata.append(value["value"])
            elif row["namespace"] == "memory-host.event-cursors":
                _require(set(value) == {"kind", "lastSequence"} and value["kind"] == "cursor"
                         and row["entry_key"] == workspace_key[:24] + ":cursor",
                         "the actual host journal cursor changed workspace or shape")
                cursors.append(value["lastSequence"])
            else:
                _require(row["namespace"] == "memory-host.events"
                         and value.get("kind") == "event"
                         and row["entry_key"].startswith(workspace_key[:24] + ":"),
                         "an unrelated plugin namespace or workspace was written")
                events.append(value)
        _require(len(metadata) == 1, "the actual recall metadata is missing or duplicated")
        recall = {"version": 1, "updatedAt": metadata[0]["updatedAt"], "entries": entries}
        _require(len(cursors) == bool(events) and (not events or cursors == [max(row["sequence"] for row in events)]),
                 "the physical host journal cursor disagrees with its complete event sequence")
        events = [row["event"] for row in sorted(events, key=lambda row: row["sequence"])]
        database_path = "agents/main/agent/openclaw-agent.sqlite"
    else:
        _same(capture["root"], raw["fixtureRoot"], "SDK physical fixture ownership changed")
        files = _files(capture)
        databases = _tables(capture, files)
        _require(RECALL_FILE in files, "the full physical SDK recall file is missing")
        recall = json.loads(files[RECALL_FILE])
        events = [json.loads(line) for line in files.get("host-events.jsonl", b"").splitlines()]
        database_path = "agents/main/memory.sqlite"
        if GUARD in files:
            _same(files[GUARD].hex(), "", "the SDK coordination inode contains data")
    _require(not native or database_path in databases, "the actual Native origin ledger is missing")
    database = databases.get(database_path)
    origins = sorted(_rows(database, "memory_entry_origins", ORIGIN_FIELDS, "main") if database else [],
                     key=lambda row: (row["entryKey"], row["sessionId"]))
    tombstones = sorted(_rows(database, "memory_session_tombstones", TOMBSTONE_FIELDS, "main") if database else [],
                        key=lambda row: row["sessionId"])
    # JSON has one numeric type. This is exact value equality, including integer
    # versus floating spelling, with booleans distinct and no numeric tolerance.
    # Original file bytes and the actual canonical reader result remain intact.
    _require(_same_json(observed["recall"], recall), "whole recall read differs from actual persisted state")
    _same(observed["events"], events, "whole ordered event read differs from actual persisted events")
    _same(observed["origins"], {"main": origins}, "whole origin read differs from actual SQL rows")
    _same(observed["tombstones"], {"main": tombstones}, "whole tombstone read differs from actual SQL rows")
    return files, database


def _source_map(witnesses, items, workspace, physical_files):
    grouped = {}
    for item in items:
        relative = item["path"].replace("\\", "/").removeprefix("./")
        grouped.setdefault(relative, []).append(item)
    _require(isinstance(witnesses, list) and [row["path"] for row in witnesses] == list(grouped),
             "the complete source witness order or paths changed")
    for witness, (relative, selected) in zip(witnesses, grouped.items(), strict=True):
        _require(set(witness) == {"path", "absolutePath", "exists", "bytes", "identity", "ranges"},
                 "a source witness lost bytes, revision, identity or ranges")
        _same(witness["absolutePath"], str(Path(workspace) / relative), "source escaped its owned workspace")
        payload = physical_files.get("workspace/" + relative)
        _require(witness["exists"] is (payload is not None), "source existence differs from physical bytes")
        if payload is None:
            _require(witness["bytes"] is None and witness["identity"] is None,
                     "a missing source acquired invented bytes or identity")
            lines = None
        else:
            _same(_bytes(witness["bytes"]).hex(), payload.hex(), "source revision differs from actual physical bytes")
            identity = witness["identity"]
            _require(set(identity) == {"device", "inode", "size", "mtimeNs", "ctimeNs"}
                     and identity["size"] == len(payload)
                     and all(isinstance(identity[key], str) and identity[key].isdigit()
                             for key in ("device", "inode", "mtimeNs", "ctimeNs")),
                     "source identity lost an actual filesystem fact")
            lines = payload.decode("utf8").replace("\r\n", "\n").split("\n")
        expected = [{"startLine": item["startLine"], "endLine": item["endLine"],
                     "lines": lines[item["startLine"] - 1:item["endLine"]] if lines is not None else None}
                    for item in selected]
        _same(witness["ranges"], expected, "source ranges are not backed by the captured source revision")
        for item, selected_range in zip(selected, expected, strict=True):
            if "snippet" in item:
                _require(selected_range["lines"] is not None
                         and item["snippet"] in "\n".join(selected_range["lines"]),
                         "a supplied snippet is not grounded in its actual visible source range")
    return grouped


def _producer(raw, actual, request, files, previous_files, native):
    producer = actual["producer"]
    _require(set(producer) == {"owner", "arguments", "returnValue", "sourcesBefore", "sourcesAfter"},
             "the complete source producer carrier changed")
    _same(producer["owner"], "appendSessionCorpusLines" if native else "append_session_corpus_lines",
          "the source producer owner changed")
    returned = producer["returnValue"]
    if native:
        _require(set(returned) == {"type", "value"} and returned["type"] == "object",
                 "the original source appender return was rewritten")
        items = returned["value"]
        arguments = {"workspaceDir": raw["workspace"], **request["append"]}
    else:
        items = returned
        lines = []
        for row in request["append"]["lines"]:
            names = {"contentIndex": "content_index", "lineNumber": "line_number", "stateKey": "state_key",
                     "sessionOrigin": "session_origin"}
            lines.append({names.get(key, key): value for key, value in row.items()})
        arguments = {"workspace_dir": raw["workspace"], "day": request["append"]["day"], "lines": lines}
    _same(producer["arguments"], arguments, "the real appender received different source facts")
    _require(isinstance(items, list) and len(items) == len(request["append"]["lines"]),
             "the full actual appender return is missing")
    _source_map(producer["sourcesAfter"], items, raw["workspace"], files)
    before = producer["sourcesBefore"]
    relative = "memory/.dreams/session-corpus/" + request["append"]["day"] + ".txt"
    _require(len(before) == 1 and before[0]["path"] == relative, "the pre-append source revision is missing")
    _source_map(before, [{"path": relative, "startLine": 1, "endLine": 1}], raw["workspace"], previous_files)
    _same(producer["sourcesAfter"], actual["sourcesBefore"], "the appender revision changed before writer dispatch")
    previous = _bytes(before[0]["bytes"]) if before[0]["exists"] else b""
    appended = "".join(row["rendered"] + "\n" for row in request["append"]["lines"]).encode()
    _same(files["workspace/" + relative].hex(), (previous + appended).hex(),
          "the actual appender changed bytes beyond its complete literal source lines")
    source_lines = files["workspace/" + relative].decode().replace("\r\n", "\n").split("\n")
    for item, source in zip(items, request["append"]["lines"], strict=True):
        _require(item["path"] == relative and item["startLine"] == item["endLine"]
                 and source_lines[item["startLine"] - 1] == source["rendered"],
                 "actual appender ranges do not identify their real visible source lines")
        _same(item["snippet"], source["snippet"], "the actual appender snippet changed its source fact")
        _same(item["provenance"], source["provenance"], "actual source provenance changed")
        _same(item.get("sessionOrigin"), source.get("sessionOrigin"), "actual source lineage changed")
    return items


def _arguments(raw, actual, request, items, native):
    grounded = request["op"] != "recall"
    if native:
        expected = {"workspaceDir": raw["workspace"], "nowMs": request["nowMs"],
                    "timezone": raw["input"]["timezone"], "query": request["query"]}
        for key in ("dedupeByQueryPerDay", "dayBucket", "signalType"):
            if key in request:
                expected[key] = request[key]
    else:
        from memory_core.config import MemoryConfig

        config = json.loads(json.dumps(asdict(MemoryConfig(workspace_dir=Path(raw["workspace"]))), default=str))
        expected = {"config": config, "query": request["query"], "now_ms": request["nowMs"],
                    "timezone": raw["input"]["timezone"], "origins": {"owner": "MemoryEntryOriginLedger",
                    "databasePaths": {"main": str(Path(raw["fixtureRoot"]) / "agents/main/memory.sqlite")}}}
        for camel, snake in (("dedupeByQueryPerDay", "dedupe_by_query_per_day"), ("dayBucket", "day_bucket")):
            if camel in request:
                expected[snake] = request[camel]
        if not grounded:
            expected["signal_type"] = request.get("signalType", "recall")
            expected["on_event"] = {"owner": "_Owners.on_event", "path": str(Path(raw["fixtureRoot"]) / "host-events.jsonl")}
    expected["items" if grounded else "results"] = items
    _same(actual["arguments"], expected, "the complete actual writer arguments changed")


def _operations(case, raw, public, captures, native):
    value = case["input"]
    _require(set(public) == {"before", "observations"}, "the complete portable interface changed")
    _same(raw["input"], value, "the actual common input changed")
    _same(raw["initialState"], public["before"], "the complete initial reader result changed")
    _require(_same_json(public["before"]["recall"], value["store"]), "the initial full literal recall facts changed")
    _same(public["before"]["origins"], {"main": []}, "an unprovided initial origin was supplied")
    tombstones = sorted([{"sessionId": session, "agentId": row["agentId"], "reason": "forgotten",
                          "createdAt": value["nowMs"]} for row in value["tombstones"]
                         for session in row["sessionIds"]], key=lambda row: row["sessionId"])
    _same(public["before"]["tombstones"], {"main": tombstones}, "initial tombstones differ from literal facts")
    _same(public["before"]["events"], [], "an initial host event was supplied")
    _require(len(raw["operations"]) == len(public["observations"]) == len(value["operations"])
             and len(captures) == len(value["operations"]) + 1, "a driven call or complete physical state is missing")
    files, _ = _state(raw, captures[0], public["before"], native)
    for name, text in value["files"].items():
        _same(files["workspace/" + name].hex(), text.encode().hex(), "an initial source fact changed")
    for entry in value["store"]["entries"].values():
        lines = files["workspace/" + entry["path"]].decode().split("\n")
        _require(entry["snippet"] in "\n".join(lines[entry["startLine"] - 1:entry["endLine"]]),
                 "a literal seeded recall entry lacks its actual source range")
    previous = public["before"]
    previous_files = files
    for request, actual, observed, capture in zip(value["operations"], raw["operations"],
                                                  public["observations"], captures[1:], strict=True):
        _same(actual["operation"], request, "a raw operation was changed or reordered")
        _same(actual["observed"], observed, "the complete public observation differs from actual raw")
        _require(set(observed) == {"operation", "completed", "state"}, "a public operation field disappeared")
        _same(observed["operation"], request, "the public operation differs from its common input")
        files, database = _state(raw, capture, observed["state"], native)
        appended_path = ("memory/.dreams/session-corpus/" + request["append"]["day"] + ".txt"
                         if request["op"] == "append-grounded" else None)
        for name in value["files"]:
            if name != appended_path:
                _same(files["workspace/" + name].hex(), previous_files["workspace/" + name].hex(),
                      "a recall writer changed an unrelated source file")
        items = (_producer(raw, actual, request, files, previous_files, native) if request["op"] == "append-grounded"
                 else request["results" if request["op"] == "recall" else "items"])
        _arguments(raw, actual, request, items, native)
        _source_map(actual["sourcesBefore"], items, raw["workspace"], files)
        _same(actual["sourcesAfter"], actual["sourcesBefore"], "a writer changed its visible source revision")
        if request.get("failOrigins"):
            _require(observed["completed"] is False and "returnValue" not in actual
                     and FAILURE_MARKER in actual["error"]["message"] and isinstance(actual["error"]["name"], str),
                     "the real origin write did not produce the retained injected failure")
            trigger = actual["trigger"]
            _same(trigger["name"], TRIGGER, "the actual failure trigger changed")
            _same(trigger["statement" if native else "sql"], TRIGGER_SQL, "the actual SQLite failure policy changed")
            active = trigger["schemaBeforeDispatch" if native else "beforeSchema"]
            rows = [row for row in active if row["name"] == TRIGGER]
            _require(len(rows) == 1 and rows[0]["type"] == "trigger" and rows[0]["sql"] == TRIGGER_SQL
                     and rows[0] in database["schema"], "the real abort trigger was absent during dispatch/capture")
            _same(trigger["afterDropSchema"], [row for row in active if row["name"] != TRIGGER],
                  "the actual abort trigger was not removed for the recovery call")
            _same(observed["state"], previous, "failed lineage write published recall, events or partial origins")
        else:
            _require(observed["completed"] is True and "error" not in actual and "trigger" not in actual,
                     "a required actual writer call failed")
            returned = actual["returnValue"]
            _require(returned == {"type": "undefined"} if native else type(returned) is int and returned >= 0,
                     "the original void or SDK integer return was coerced")
        previous = observed["state"]
        previous_files = files
    _call_bindings(raw, native)


def _call_bindings(raw, native):
    key = "operation" if native else "owner"
    names = ({"recordShortTermRecalls", "recordGroundedShortTermCandidates"} if native
             else {"record_short_term_recalls", "record_grounded_short_term_candidates"})
    calls = [row for row in raw["calls"] if row.get(key) in names]
    _require(len(calls) == len(raw["operations"]), "an actual writer call was dropped or added")
    for call, actual in zip(calls, raw["operations"], strict=True):
        owner = ("recordShortTermRecalls" if actual["operation"]["op"] == "recall"
                 else "recordGroundedShortTermCandidates") if native else (
                     "record_short_term_recalls" if actual["operation"]["op"] == "recall"
                     else "record_grounded_short_term_candidates")
        _same(call[key], owner, "a different real owner handled the operation")
        _same(call["arguments"], [actual["arguments"]] if native else actual["arguments"],
              "the original call received different complete arguments")
        field = "returnValue" if actual["observed"]["completed"] else "error"
        _same(call[field], actual[field], "the actual return or exception was changed")
    owner = "appendSessionCorpusLines" if native else "append_session_corpus_lines"
    calls = [row for row in raw["calls"] if row.get(key) == owner]
    producers = [row["producer"] for row in raw["operations"] if "producer" in row]
    _require(len(calls) == len(producers), "an actual source producer call is missing")
    for call, producer in zip(calls, producers, strict=True):
        _same(call["arguments"], [producer["arguments"]] if native else producer["arguments"],
              "the actual source producer received different input facts")
        _same(call["returnValue"], producer["returnValue"], "the actual full source producer return changed")


def validate_native(case, public, snapshots, evidence):
    validate_case(case)
    _require(isinstance(snapshots, list) and len(snapshots) == 1, "one complete original capture is required")
    raw = snapshots[0]
    base = Path(raw["fixtureBase"])
    _require(base.is_absolute() and base.parent == Path(evidence)
             and base.name.startswith("native-recall-signals-") and raw["closed"] is True,
             "the original fixture lost its exact owned identity or completion")
    _same(raw["workspace"], str(base / "workspace"), "Native workspace changed")
    _same(raw["config"], {
        "agents": {"defaults": {"workspace": raw["workspace"]},
                   "list": [{"id": "main", "workspace": raw["workspace"]}]},
        "logging": {"level": "silent", "consoleLevel": "silent", "file": str(base / "native.log")}},
        "the original writer-only fixture configuration changed")
    _same(raw["environment"], {"OPENCLAW_STATE_DIR": raw["stateDirectory"],
          "OPENCLAW_CONFIG_PATH": raw["configPath"], "OPENCLAW_HOME": str(base)},
          "the original durable owners escaped the owned fixture environment")
    _same(raw["clock"], {"owner": "node:test", "apis": ["Date"], "nowMs": case["input"]["nowMs"],
          "dateConstructorReplaced": True, "setTimeoutUnchanged": True, "performanceNowUnchanged": True},
          "the original clock changed scheduler ownership")
    expected = {(module, export) for module, exports in GENUINE_HELPER_EXPORTS.items() for export in exports}
    owners = raw["codeOwners"]
    _require({(row["modulePath"], row["exportName"]) for row in owners} == expected and len(owners) == len(expected),
             "an original function owner is missing or duplicated")
    for row in owners:
        _same(row["compiledSha256"], COMPILED_HASHES[row["modulePath"]], "an original compiled owner changed")
        _same(row["functionSourceSha256"], hashlib.sha256(row["functionSource"].encode()).hexdigest(),
              "a complete original function source observation changed")
    _same(raw["output"], public, "the whole original producer output changed")
    _operations(case, raw, public, [physical_snapshot(item) for item in raw["physical"]], True)


def validate_pair(case, native_raw, sdk_raw, native_public, sdk_public, sdk_directory):
    validate_native(case, native_public, [native_raw], Path(native_raw["fixtureBase"]).parent)
    directory = Path(sdk_directory).resolve()
    raw_path = directory / "python-raw.json"
    _require(not raw_path.is_symlink(), "the SDK raw capture is a symlink")
    _same(json.loads(raw_path.read_text()), [sdk_raw], "the complete SDK raw file differs from its supplied record")
    _require(sdk_raw["fixtureRoot"] == str(directory / "sdk-fixture")
             and sdk_raw["workspace"] == str(directory / "sdk-fixture/workspace") and sdk_raw["closed"] is True,
             "the SDK fixture escaped its actual owned attempt")
    _require({owner["name"] for owner in sdk_raw["owners"]} == {
        "record_short_term_recalls", "record_grounded_short_term_candidates", "append_session_corpus_lines",
        "read_canonical_recall_store", "write_recall_store", "MemoryEntryOriginLedger.record",
        "MemoryEntryOriginLedger.list", "MemoryEntryOriginLedger.list_session_tombstones"}
        and len(sdk_raw["owners"]) == 8, "an actual SDK owner is missing or duplicated")
    for owner in sdk_raw["owners"]:
        path = Path(owner["path"])
        _require(path.is_relative_to(ROOT / "memory_core") and not path.is_symlink(), "an SDK owner escaped its source")
        _same(hashlib.sha256(path.read_bytes()).hexdigest(), owner["sha256"], "an actual SDK owner source changed")
    _operations(case, sdk_raw, sdk_public, _sdk_physical(sdk_raw, directory), False)
    return native_public, sdk_public
