"""Custody for the six independently frozen host-maintenance boundary schedules.

The public channel operation includes complete delivered payloads and accounting.
Native's dispatch return is its actual upstream API return; SDK accounting is its
actual delivery adapter's return. Whole SDK HostTurnOutcome and distinct producer
APIs remain engine-specific custody. Provider transport cleanup is not claimed
owned by Native owner.done. The target-open case separately checks a real kernel
lease and descriptor release. Neither standalone comparison nor replay awards credit.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from equivalence.host_turn_barrier_boundaries import validate_case
from equivalence.host_turn_barrier_evidence import _contains, _events, _same, _text, require
from equivalence.host_update_isolation_evidence import native_refusal_names_source

ROOT = Path(__file__).resolve().parents[1]
EMPTY_ANSWER = "No source-backed memory found."


def _one(rows, predicate, message):
    found = [row for row in rows if predicate(row)]
    require(len(found) == 1, message)
    return found[0]


def _event(raw, name, label=None):
    return _one(raw["events"], lambda row: row["event"] == name and (
        label is None or row.get("label", row.get("turn")) == label),
        f"boundary lifecycle lacks unique {name} {label} receipt")


def _source(path, text=None):
    return ({"path": path, "kind": "missing"} if text is None else
            {"path": path, "kind": "file", "text": text, "hex": text.encode().hex()})


def _sources(value):
    root = value["warmup"]["save"]["content"] if value["scenario"] == "refused-foreground" else value["save"]["content"]
    maintenance = value.get("maintenance")
    daily = None
    if maintenance:
        body = (maintenance["body"] if value["scenario"] == "committed-maintenance" else
                "" if value.get("fixtureFiles") else None)
        daily = _source(maintenance["relativePath"], body)
    return _source(value["source"], root), daily


def _plan(value):
    plan = []
    if value.get("warmup"):
        plan.append(("warmup-save", "save", value["warmup"]["save"], "warmup"))
    return plan + [("save", "save", value["save"], "save"), ("followup", "recall", value["followup"], "followup")]


def _warning(search):
    return "\n".join(search[key] for key in ("warning", "action") if isinstance(search.get(key), str) and search[key])


def _answer(search, got):
    return "\n".join(item for item in (got["text"] if got else None, _warning(search)) if item) or EMPTY_ANSWER


def _finite(value):
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_finite(item) for item in value.values())
    if isinstance(value, list):
        return all(_finite(item) for item in value)
    return True


def _stage(public, label, *, reading, sources, publication=False):
    require(isinstance(public, dict) and set(public) == {"deliveries", "dispatchReturn", "search", "get"},
            "boundary public channel stage is incomplete or has reassigned fields")
    deliveries = public["deliveries"]
    require(isinstance(deliveries, list) and len(deliveries) == 1, "boundary public deliveries are missing or duplicated")
    payload = deliveries[0]
    require(isinstance(payload, dict) and set(payload) == {"text", "replyToTag", "replyToId", "audioAsVoice"}
            and isinstance(payload["text"], str) and payload["replyToTag"] is False
            and payload["audioAsVoice"] is False and payload["replyToId"] == "fixture-" + label,
            "boundary public complete delivered payload lost a field or changed its user identity")
    dispatch = public["dispatchReturn"]
    require(isinstance(dispatch, dict) and set(dispatch) == {"queuedFinal", "counts"}
            and dispatch["queuedFinal"] is True and _same(dispatch["counts"], {"tool": 0, "block": 0, "final": len(deliveries)}),
            "boundary public dispatch return is incomplete or disagrees with actual delivery accounting")
    if not reading:
        require(public["search"] is None and public["get"] is None,
                "boundary public write stage invented a memory read")
        return
    search, got = public["search"], public["get"]
    require(isinstance(search, dict) and isinstance(search.get("results"), list) and _finite(search),
            "boundary public actual search payload is missing or nonfinite")
    if publication:
        require(search.get("disabled") is True and search.get("unavailable") is True
                and search.get("error") == "unable to open database file" and not search["results"]
                and isinstance(search.get("warning"), str) and "unable to open database file" in search["warning"]
                and isinstance(search.get("action"), str) and bool(search["action"])
                and isinstance(search.get("debug"), dict),
                "boundary public publication failure did not reach its complete error/warning carrier")
    else:
        debug = search.get("debug", {})
        require(search.get("provider") == "none" and search.get("citations") == "off"
                and _same(debug.get("hits"), len(search["results"])) and _same(debug.get("withheldHits"), 0)
                and _same(debug.get("searchWindow"), 5), "boundary public complete ordinary search debug fields changed")
    if search["results"]:
        require(len(search["results"]) == 1, "boundary public closed corpus unexpectedly has multiple search hits")
        first = search["results"][0]
        source = next((item for item in sources if item and item["path"] == first.get("path")), None)
        require(source and source["kind"] == "file" and isinstance(got, dict)
                and got.get("status") == "ok" and got.get("path") == first["path"]
                and type(first.get("startLine")) is int and type(first.get("endLine")) is int
                and first["startLine"] > 0 and first["endLine"] >= first["startLine"]
                and _same(got.get("from"), first["startLine"]) and type(got.get("lines")) is int
                and got["lines"] > 0 and first.get("source") == "memory" and first.get("corpus") == "memory",
                "boundary public getter is not bound to the actual first hit and owned source")
        selected = source["text"].splitlines()[got["from"] - 1:got["from"] - 1 + got["lines"]]
        require(selected and got.get("text") == "\n".join(selected),
                "boundary public getter text was not read from the actual committed source range")
    else:
        require(got is None, "boundary public empty search invented a getter")
    require(payload["text"] == _answer(search, got), "boundary public reply did not consume its actual search/get warning dataflow")


def _validate_result(case, result):
    validate_case(case)
    value = case["input"]
    require(isinstance(result, dict) and set(result) == {"provider", "scenario", "source", "maintenanceSource", "warmup", "save", "followup"}
            and result["provider"] == "none" and result["scenario"] == value["scenario"],
            "boundary public result is incomplete or belongs to another profile")
    root, daily = _sources(value)
    require(_same(result["source"], root) and _same(result["maintenanceSource"], daily),
            "boundary public source bytes do not reflect the declared real write/refusal schedule")
    for label, kind, _directive, key in _plan(value):
        publication = value["scenario"] == "cold-publication-failure"
        reading = kind == "recall" or label == "save" and publication
        _stage(result[key], label, reading=reading, sources=(root, daily), publication=publication and reading)
        if not reading:
            expected = "The memory write failed." if label == "save" and value["scenario"] == "refused-foreground" else "Saved."
            require(result[key]["deliveries"][0]["text"] == expected,
                    "boundary public acknowledgment differs from the actual producer-outcome script")
    if not value.get("warmup"):
        require(result["warmup"] is None, "boundary public cold fixture borrowed a warmup")
    found = bool(result["followup"]["search"]["results"])
    require(found is (value["scenario"] in {"committed-maintenance", "refused-foreground"}),
            "boundary public retrieval does not reflect its actually committed or refused source")
    return True


def _messages(value):
    if isinstance(value, list):
        for item in value:
            yield from _messages(item)
    elif isinstance(value, dict):
        if value.get("role") in {"user", "assistant", "toolResult"}:
            yield value
        elif isinstance(value.get("message"), dict):
            yield from _messages(value["message"])


def _user(messages, prompt):
    return any(message.get("role") == "user" and prompt in _text(message) for message in _messages(messages))


def _catalog_messages(snapshot):
    tables = snapshot.get("tables", {})
    require(isinstance(tables, dict), "SDK admission catalog snapshot lost physical event tables")
    return [json.loads(row["event_json"]) for row in tables.get("memory_session_events", [])]


def _native_database(files, value):
    require(isinstance(files, list) and files, "native admission physical SQLite snapshots were discarded")
    database = _one(files, lambda row: row["path"] == "openclaw-agent.sqlite",
                    "native admission physical session database was reassigned")
    tables = {table["name"]: table["rows"] for table in database["tables"]}
    node = _one(tables["session_nodes"], lambda row: row["session_key"] == value["identity"]["sessionKey"],
                "native admission physical session node belongs to another session")
    require(node["current_session_id"] == value["identity"]["sessionId"]
            and json.loads(node["entry_json"])["sessionId"] == value["identity"]["sessionId"],
            "native admission physical current session identity changed")
    window = _one(tables["session_windows"], lambda row: row["session_key"] == value["identity"]["sessionKey"]
                  and row["session_id"] == value["identity"]["sessionId"], "native admission physical session window was lost")
    require(window["status"] is None and window["ended_at"] is None,
            "native admission physical session window is not the current unended original window")
    return tables


def _native_user_readback(tables, value, prompt):
    rows = [row for row in tables["transcript_events"] if row["session_id"] == value["identity"]["sessionId"]
            and isinstance(row.get("event_json"), str)]
    found = [(row, json.loads(row["event_json"])) for row in rows]
    found = [(row, event) for row, event in found if event.get("type") == "message"
             and event.get("message", {}).get("role") == "user" and prompt in _text(event["message"])]
    require(len(found) == 1, "native admission actual user readback is missing, duplicated or belongs to another prompt")
    row, event = found[0]
    identity = _one(tables["transcript_event_identities"], lambda item: item["session_id"] == row["session_id"]
                    and item["seq"] == row["seq"], "native admission physical user identity/sequence was lost")
    require(identity["event_id"] == event["id"] and identity["event_type"] == "message"
            and identity["parent_id"] == event.get("parentId")
            and event["message"].get("__openclaw", {}).get("senderIsOwner") is False,
            "native admission physical user message has another identity, parent or owner authority")
    return event


def _native_has_user(tables, value, prompt):
    events = [json.loads(row["event_json"]) for row in tables["transcript_events"]
              if row["session_id"] == value["identity"]["sessionId"] and isinstance(row.get("event_json"), str)]
    return _user(events, prompt)


def _native_dispatch(events, call, name, arguments, *, failed):
    starts = [r for r in events if r.get("stream") == "tool" and r["data"].get("phase") == "start"
              and r["data"].get("toolCallId") == call["id"]]
    ends = [r for r in events if r.get("stream") == "tool" and r["data"].get("phase") == "result"
            and r["data"].get("toolCallId") == call["id"]]
    require(len(starts) == len(ends) == 1 and starts[0]["seq"] < ends[0]["seq"]
            and starts[0]["runId"] == ends[0]["runId"] and starts[0]["data"].get("name") == ends[0]["data"].get("name") == name
            and _same(starts[0]["data"].get("args"), arguments) and ends[0]["data"].get("isError") is failed,
            "native dispatch lacks its genuine original start/result/error receipts")
    return ends[0]["data"]["result"]


def _native_memory(turn, call, carrier, name, arguments):
    require(call["name"] == "tool_call" and _same(call["arguments"], {"id": name, "args": arguments})
            and carrier.get("role") == "toolResult" and carrier.get("toolName") == "tool_call"
            and carrier.get("toolCallId") == call["id"]
            and _contains(carrier, turn["modelCalls"][call["modelCall"] + 1]["context"]["messages"]),
            "native model/carrier did not consume its actual deferred memory dispatch")
    wrapped = json.loads(_text(carrier))
    require(wrapped["tool"].get("name") == name and wrapped["tool"].get("source") == "openclaw",
            "native dispatch returned another deferred memory owner")
    receipt = wrapped["result"]
    payload = json.loads(_text(receipt))
    require(_same(payload, receipt.get("details")), "native carrier complete visible JSON differs from memory details")
    failed = carrier.get("isError") is True
    require(failed is (payload.get("disabled") is True or payload.get("unavailable") is True or payload.get("status") == "error"),
            "native actual memory error carrier flags contradict its unavailable/error payload")
    _native_dispatch(turn["toolEvents"], call, "tool_call", call["arguments"], failed=failed)
    nested = _one(turn["toolEvents"], lambda row: row.get("stream") == "tool" and row["data"].get("phase") == "start"
                  and row["data"].get("name") == name and row["data"].get("parentToolCallId") == call["id"],
                  "native dispatch lacks its actual nested memory-tool start")
    actual = _native_dispatch(turn["toolEvents"], {"id": nested["data"]["toolCallId"]}, name, arguments, failed=failed)
    require(_same(actual, receipt), "native carrier differs from its genuine nested result")
    return payload


def _metadata(value, raw, *, native):
    workspace = Path(raw["fixtureBase"]) / "workspace"
    expected = [(label, value["source"]) for label, kind, _directive, _key in _plan(value)
                if kind == "save" and not (label == "save" and value["scenario"] == "refused-foreground")]
    if value["scenario"] == "committed-maintenance":
        expected.append(("maintenance", value["maintenance"]["relativePath"]))
    rows = raw["metadataOperations" if native else "metadata"]
    require(len(rows) == len(expected), "native metadata producer receipts missing or duplicated" if native else "SDK metadata producer receipts missing or duplicated")
    for label, target in expected:
        row = _one(rows, lambda item: item.get("turn" if native else "label") == label,
                   "native metadata target was reassigned" if native else "SDK metadata target was reassigned")
        require(int(row["startedAtNs"]) <= int(row["finishedAtNs"]), "boundary source metadata operation was reordered")
        if native:
            before, after = row["before"], row["after"]
            require(row["operation"] == "utimesSync" and row["target"] == target
                    and row["placement"] == value["sourceMetadataFixture"]["placement"] and row["returnedUndefined"] is True
                    and _same(row["arguments"], [str(workspace / target), value["nowMs"] / 1000, value["nowMs"] / 1000])
                    and before["sha256"] == after["sha256"] and before["ino"] == after["ino"]
                    and after["absolutePath"] == str(workspace / target) and after["mtimeMs"] == value["nowMs"],
                    "native source/metadata fixture changed bytes, target, inode or actual producer mtime")
        else:
            before, after = row["before"], row["after"]
            instant = str(value["nowMs"] * 1_000_000)
            require(row["operation"] == "os.utime" and row["path"] == str(workspace / target) and row["returnedNone"] is True
                    and _same(row["arguments"], {"ns": [instant, instant]}) and _same(before["source"], after["source"])
                    and before["stat"]["ino"] == after["stat"]["ino"] and after["stat"]["mtimeNs"] == instant
                    and after["source"]["path"] == target,
                    "SDK source/metadata fixture changed bytes, target, inode or actual producer mtime")


def _fixtures(value, raw, *, native):
    rows = raw["fixtureOperations" if native else "fixtures"]
    require(len(rows) == len(value.get("fixtureFiles", [])), "boundary fixture target creation was missing or added")
    for spec, row in zip(value.get("fixtureFiles", []), rows, strict=True):
        if native:
            require(all(_same(row.get(k), v) for k, v in spec.items())
                    and _same(row["observation"], _source(spec["path"], spec["content"]))
                    and row["metadata"]["nlink"] == 1 and row["metadata"]["size"] == 0,
                    "native source fixture is not the owned empty single-link target")
        else:
            require(_same(row["specification"], spec) and _same(row["actual"]["source"], _source(spec["path"], spec["content"]))
                    and row["actual"]["stat"]["nlink"] == 1 and row["actual"]["stat"]["size"] == 0,
                    "SDK source fixture is not the owned empty single-link target")


def _faults(value, raw, *, native):
    rows = raw["faultOperations" if native else "faults"]
    fault = value.get("fault")
    if not fault:
        require(not rows, "boundary fault was inserted into a non-fault schedule")
        return
    workspace = Path(raw["fixtureBase"]) / "workspace"
    if fault["recipe"] == "actual-source-second-hard-link":
        target, label = fault["target"], "foreground" if value["scenario"] == "refused-foreground" else "maintenance"
        if native:
            require(len(rows) == 2 and [row["operation"] for row in rows] == ["arm", "remove"]
                    and all(row["kind"] == "hard-link" and row["target"] == target and row["label"] == label for row in rows),
                    "native fault lacks actual hard-link arm/remove operations")
            arm, removed = rows
            require(arm["before"]["absolutePath"] == str(workspace / target) and arm["before"]["nlink"] == 1
                    and arm["after"]["nlink"] == arm["aliasStat"]["nlink"] == 2
                    and arm["before"]["ino"] == arm["after"]["ino"] == arm["aliasStat"]["ino"] == removed["after"]["ino"]
                    and removed["before"]["nlink"] == 2 and removed["after"]["nlink"] == 1
                    and arm["before"]["sha256"] == arm["after"]["sha256"] == removed["after"]["sha256"],
                    "native fault/source is not one real unchanged hard-linked inode")
        else:
            require(len(rows) == 1, "SDK fault has missing or added hard-link operations")
            row = rows[0]
            before, armed, removed = row["before"], row["armed"], row["removed"]
            require(row["target"] == str(workspace / target) and row["label"] == label
                    and before["stat"]["nlink"] == removed["stat"]["nlink"] == 1
                    and armed["stat"]["nlink"] == row["linkStat"]["nlink"] == 2
                    and before["stat"]["ino"] == armed["stat"]["ino"] == row["linkStat"]["ino"] == removed["stat"]["ino"]
                    and _same(before["source"], armed["source"]) and _same(armed["source"], removed["source"])
                    and row["linkExistsAfter"] is False,
                    "SDK fault/source is not one real unchanged hard-linked inode")
    else:
        require(len(rows) == 1, "boundary publication fault missing or duplicated")
        row = rows[0]
        if native:
            database = raw["resolvedMemorySearch"]["store"]["databasePath"]
            require(row["kind"] == "publication-sidecar-symlink" and row["operation"] == "arm"
                    and row["database"] == database and row["sidecar"] == database + ".reindex-lock.sqlite"
                    and row["isSymbolicLink"] is True and row["readlink"] == row["target"]
                    and Path(row["target"]).is_relative_to(Path(raw["fixtureBase"])),
                    "native publication fault points outside its actual resolved publisher sidecar")
        else:
            require(row["recipe"] == fault["recipe"] and row["target"] == str(Path(raw["fixtureBase"]) / "index.sqlite-journal")
                    and row["isSymlink"] is True and row["targetExists"] is False
                    and Path(row["pointsTo"]).is_relative_to(Path(raw["fixtureBase"])),
                    "SDK publication fault points outside its actual index journal")


def _native_owner(raw, value):
    if not value.get("maintenance"):
        require(not raw["maintenanceCalls"], "native maintenance model ran in a low-usage error schedule")
        return
    plan = raw["resolvedFlushPlan"]
    require(plan["relativePath"] == value["maintenance"]["relativePath"]
            and _same(plan["reserveTokensFloor"], value["policy"]["reserveTokens"])
            and _same(plan["softThresholdTokens"], value["policy"]["softThresholdTokens"])
            and plan["prompt"].startswith("Pre-compaction memory flush.")
            and "prompt" not in raw["config"]["agents"]["defaults"]["compaction"]["memoryFlush"],
            "native maintenance due plan was replaced or uses an ineffective custom prompt")
    follow = next(turn for turn in raw["turns"] if turn["label"] == "followup")
    entry = follow["agentRunStarts"][0]["entry"]
    threshold = value["policy"]["contextWindowTokens"] - plan["reserveTokensFloor"] - plan["softThresholdTokens"]
    require(entry.get("totalTokensFresh") is True and _same(entry.get("totalTokens"), value["firstTurnUsage"]["input"])
            and entry["totalTokens"] >= threshold,
            "native maintenance is merely a no-op owner without real due persisted usage")
    delivery = _event(raw, "actual-terminal-delivery", "save")
    state = _one(delivery["owners"], lambda item: item["sessionKey"] == value["identity"]["sessionKey"],
                 "native maintenance owner belongs to another session")
    owner = _one(state["owners"], lambda item: item["preemptible"] is True,
                 "native maintenance lacks its real scheduler-created optional owner")
    owner_id = owner["id"]
    aborted = _one(raw["events"], lambda row: row["event"] == "actual-maintenance-abort" and row["ownerId"] == owner_id,
                   "native maintenance lacks its actual owner abort")
    done = _one(raw["events"], lambda row: row["event"] == "actual-maintenance-done" and row["ownerId"] == owner_id,
                "native maintenance lacks its actual owner.done settlement")
    next_call, started = _event(raw, "host-submission-attempt", "followup"), _event(raw, "actual-agent-run-start", "followup")
    model = _one(raw["events"], lambda row: row["event"] == "actual-model-invocation" and row.get("turn") == "followup" and row["index"] == 0,
                 "native admission lacks its next actual model invocation")
    require(next_call["sequence"] < aborted["sequence"] < done["sequence"] < started["sequence"] < model["sequence"],
            "native admission began before real maintenance abort/owner.done settlement")
    for row in (aborted, done):
        checkpoint = row["checkpoint"]
        tables = _native_database(checkpoint["sqlite"], value)
        require(checkpoint["entry"]["sessionId"] == value["identity"]["sessionId"]
                and not _user(checkpoint["transcript"], value["followup"]["prompt"])
                and not _native_has_user(tables, value, value["followup"]["prompt"]),
                "native admission persisted/read back the next user before actual owner.done settlement")
    scenario = value["scenario"]
    aborted_session = _one(aborted["owners"], lambda row: row["sessionKey"] == value["identity"]["sessionKey"],
                           "native maintenance abort snapshot belongs to another session")
    aborted_owner = _one(aborted_session["owners"], lambda row: row["id"] == owner_id,
                         "native maintenance abort snapshot lost its actual owner")
    require(aborted_owner["preemptible"] is True and aborted_owner["aborted"] is True
            and aborted_owner["writesReleased"] is False
            and aborted_owner["running"] is (scenario != "pending-optional-preemption"),
            "native maintenance abort used another pending/running owner state")
    if scenario == "pending-optional-preemption":
        held, released = _event(raw, "actual-delivery-ack-held", "save"), _event(raw, "actual-delivery-ack-released", "save")
        require(owner["running"] is False and owner["writesReleased"] is False and not raw["maintenanceCalls"]
                and held["ownerId"] == released["ownerId"] == owner_id
                and delivery["sequence"] < held["sequence"] < next_call["sequence"] < aborted["sequence"] < released["sequence"] < done["sequence"],
                "native maintenance pending preemption borrowed a running/no-op owner or fake delivery gate")
        released_session = _one(released["owners"], lambda row: row["sessionKey"] == value["identity"]["sessionKey"],
                                "native maintenance delivery release belongs to another session")
        released_owner = _one(released_session["owners"], lambda row: row["id"] == owner_id,
                              "native maintenance delivery release lost its actual owner")
        require(released_owner["running"] is False and released_owner["aborted"] is True
                and released_owner["writesReleased"] is False, "native maintenance pending delivery gate borrowed a running/settled owner")
    elif scenario == "target-open-preparation":
        require(not raw["maintenanceCalls"], "native target preparation reached a model/write before its real open settled")
    else:
        calls = raw["maintenanceCalls"]
        require(len(calls) == 2 and [call["index"] for call in calls] == [0, 1]
                and calls[0]["signal"]["present"] is True and calls[0]["signal"]["aborted"] is False
                and _user(calls[0]["context"]["messages"], value["save"]["prompt"]),
                "native maintenance model did not consume its actual persisted foreground history")
        emitted = calls[0]["reply"]["content"]
        require(len(emitted) == 1 and emitted[0]["type"] == "toolCall" and emitted[0]["name"] == "write"
                and _same(emitted[0]["arguments"], {"path": value["maintenance"]["relativePath"], "content": value["maintenance"]["body"]}),
                "native maintenance dispatch did not emit its actual declared producer tool")
        receipt = calls[1]["producingToolResult"]
        failed = scenario == "refused-maintenance"
        require(receipt.get("toolName") == "write" and receipt.get("toolCallId") == emitted[0]["id"]
                and receipt.get("isError") is failed and _contains(receipt, calls[1]["context"]["messages"]),
                "native maintenance error/result was not consumed by its actual model")
        events = [event for turn in raw["turns"] for event in turn["toolEvents"]]
        dispatched = _native_dispatch(events, emitted[0], "write", emitted[0]["arguments"], failed=failed)
        require(_same(dispatched["content"], receipt["content"]),
                "native maintenance model carrier differs from the actual producer dispatch result")
        consumed = _event(raw, "actual-maintenance-write-result-consumed")
        require(consumed["failed"] is failed and _same(consumed["receipt"], receipt)
                and consumed["sequence"] < next_call["sequence"],
                "native maintenance actual producer result was still missing before next admission")
        if failed:
            require(_same(json.loads(_text(receipt)), {"status": "error", "tool": "write", "error": "path alias escape blocked"}),
                    "native maintenance refusal has another actual alias-boundary cause")
        else:
            require(_same(calls[1]["actualSource"], _source(value["maintenance"]["relativePath"], value["maintenance"]["body"])),
                    "native maintenance source was not actually committed before next submission")


def _lease(value, raw, *, native):
    lease = raw["lease"]
    if value["scenario"] != "target-open-preparation":
        require(lease is None, "boundary lease capability leaked into another schedule")
        return
    prefix = "native" if native else "SDK"
    require(isinstance(lease, dict), prefix + " lease lacks its actual helper process")
    rows = lease["events" if native else "receipts"]
    names = [row["event"] for row in rows]
    require(names in (["ARMED", "BREAK", "RELEASED", "VERIFIED", "RELEASED", "CLOSED"],
                      ["ARMED", "BREAK", "RELEASED", "VERIFIED", "CLOSED"]), prefix + " lease lacks actual kernel break/release/descriptor verification")
    require([row["sequence"] for row in rows] == list(range(len(rows)))
            and [int(row["atNs"]) for row in rows] == sorted(int(row["atNs"]) for row in rows)
            and type(lease["pid"]) is int and lease["pid"] > 0 and lease["pid"] != raw["pid"]
            and all(row["kind"] == "host-turn-barrier-boundaries-lease" and row["pid"] == lease["pid"]
                    and row["ppid"] == raw["pid"] for row in rows), prefix + " lease receipts came from another helper/parent or were reordered")
    target = str(Path(raw["fixtureBase"]) / "workspace" / value["maintenance"]["relativePath"])
    identity = rows[0]["target"]
    require(identity["path"] == target and identity["size"] == 0 and identity["nlink"] == 1
            and identity["sha256"] == hashlib.sha256(b"").hexdigest()
            and all(_same(row["target"], identity) for row in rows)
            and rows[0]["held"] is True and rows[0]["leaseType"] == 0
            and rows[1]["signal"] == 29 and rows[1]["held"] is True
            and next(row for row in rows if row["event"] == "VERIFIED")["leaseType"] == 0,
            prefix + " lease did not hold/reacquire one actual unchanged empty target inode")
    if native:
        require(lease["exit"] == {"code": 0, "signal": None} and lease["stderr"] == ""
                and lease["ppid"] == raw["pid"] and lease["arguments"][-1] == str(raw["pid"]),
                "native lease helper exited badly or borrowed another parent")
        executable = lease["executable"]
        require(_same(rows[0]["executable"], {"path": executable["execPath"], "sha256": executable["sha256"], "version": executable["version"]}),
                "native lease executed another Python binary")
        require(_same(rows[0]["script"], lease["helper"])
                and lease["helper"]["path"] == str(ROOT / "equivalence/host_turn_barrier_boundaries_lease.py")
                and lease["arguments"] == ["-I", "-B", lease["helper"]["path"], "--workspace", str(Path(raw["fixtureBase"]) / "workspace"),
                                           "--relative-path", value["maintenance"]["relativePath"], "--owner-pid", str(raw["pid"])],
                "native lease actual script/arguments differ from the closed helper authority")
        observed = [row["receipt"] for row in raw["events"] if row["event"].startswith("actual-lease-") and "receipt" in row]
        require(_same(observed, rows), "native lease stdout observations lost actual protocol receipts")
        live = _event(raw, "actual-node-event-loop-live-after-abort")
        require(live["nextModelCalls"] == 0, "native admission/model ran while its real target write-open was pending")
        released = _event(raw, "actual-lease-released") if names.count("RELEASED") == 1 else next(row for row in raw["events"] if row["event"] == "actual-lease-released")
        require(live["sequence"] < released["sequence"], "native lease released before its real abort/liveness checkpoint")
        done_event = next(row for row in raw["events"] if row["event"] == "actual-maintenance-done" and row["ownerId"] == live["ownerId"])
    else:
        require(lease["exitCode"] == 0 and lease["stderr"] == "" and lease["parentPid"] == raw["pid"]
                and _same([json.loads(wire) for wire in lease["stdout"]], rows),
                "SDK lease actual stdout/exit/parent was substituted")
        require(rows[0]["executable"]["path"] == lease["executable"]
                and rows[0]["executable"]["sha256"] == lease["executableSha256"], "SDK lease executed another Python binary")
        require(_same(rows[0]["script"], {"path": lease["helperPath"], "sha256": lease["helperSha256"]})
                and lease["helperPath"] == str(ROOT / "equivalence/host_turn_barrier_boundaries_lease.py")
                and lease["argv"][1:] == ["-m", "equivalence.host_turn_barrier_boundaries_lease", "--workspace",
                                          str(Path(raw["fixtureBase"]) / "workspace"), "--relative-path",
                                          value["maintenance"]["relativePath"], "--owner-pid", str(raw["pid"])],
                "SDK lease actual script/arguments differ from its owned helper authority")
        live = _event(raw, "event-loop-live-after-actual-abort")
        aborted = _event(raw, "optional-abort-observed")
        release_command = next(row for row in raw["events"] if row["event"] == "lease-command" and row["command"] == "RELEASE")
        require(aborted["sequence"] < live["sequence"] < release_command["sequence"],
                "SDK lease lost its real abort/event-loop liveness before physical open release")
        done_event = _one(raw["events"], lambda row: row["event"] == "optional-done-observed" and row["job"]["id"] == 1,
                          "SDK maintenance lacks its actual first owner.done callback")
    released_receipt = next(row for row in rows if row["event"] == "RELEASED")
    verified_receipt = next(row for row in rows if row["event"] == "VERIFIED")
    require(int(released_receipt["atNs"]) < int(done_event["atNs"]) < int(verified_receipt["atNs"]),
            prefix + " lease descriptor verification/actual owner.done was not after physical target-open release")
    commands = lease["commands"] if native else [json.loads(wire) for wire in lease["stdin"]]
    require([row["command"] for row in commands] in (["RELEASE", "VERIFY", "RELEASE", "STOP"], ["RELEASE", "VERIFY", "STOP"])
            and len({row["id"] for row in commands}) == len(commands)
            and [row["id"] for row in rows if row["event"] in {"RELEASED", "VERIFIED", "CLOSED"}]
            == [row["id"] for row in commands], prefix + " lease commands were replayed, omitted or detached from actual acknowledgments")


def _native(case, raw, result):
    value = case["input"]
    require(raw.get("kind") == "host-turn-barrier-boundaries-native" and _same(raw.get("input"), value)
            and _same(raw.get("request"), value) and _same(raw.get("result"), result) and "error" not in raw
            and type(raw.get("pid")) is int and type(raw.get("ppid")) is int and raw["pid"] > 0 and raw["ppid"] > 0
            and raw["pid"] != raw["ppid"], "native boundary capture is detached from its actual input/process/result")
    require(all(_same(raw["scope"].get(key), item) for key, item in value["identity"].items()), "native boundary session identity changed")
    defaults, resolved = raw["config"]["agents"]["defaults"], raw["resolvedMemorySearch"]
    require(defaults.get("skipBootstrap") is True and defaults["compaction"]["enabled"] is True
            and defaults["compaction"]["memoryFlush"]["enabled"] is True and resolved["provider"] == "none"
            and resolved["sources"] == ["memory"] and resolved["searchSources"] == ["memory"]
            and all(resolved["sync"][key] is True for key in ("onSessionStart", "onSearch", "watch")),
            "native boundary owner changed its actual corpus, bootstrap or maintenance/synchronization policy")
    _events(raw["events"])
    plan = _plan(value)
    require([row["label"] for row in raw["turns"]] == [item[0] for item in plan], "native boundary actual turn plan was substituted")
    for turn, (label, kind, directive, key) in zip(raw["turns"], plan, strict=True):
        require(turn["kind"] == kind and _same(turn["instruction"], directive)
                and _same(turn["deliveries"], result[key]["deliveries"])
                and _same(turn["dispatchResult"], result[key]["dispatchReturn"]), "native boundary full channel return/delivery was dropped or reassigned")
        ctx = turn["dispatchContext"]
        require(all(ctx.get(field) == directive["prompt"] for field in ("Body", "RawBody", "BodyForAgent", "BodyForCommands"))
                and ctx["SessionKey"] == value["identity"]["sessionKey"] and ctx["MessageSid"] == "fixture-" + label,
                "native boundary caller bypassed its actual full dispatcher input")
        entered, returned = _event(raw, "host-submission-attempt", label), _event(raw, "actual-host-return", label)
        require(entered["sequence"] < returned["sequence"] and _same(returned["deliveries"], turn["deliveries"])
                and _same(returned["dispatchReturn"], turn["dispatchResult"]), "native boundary actual channel return differs from public accounting")
        starts = turn["agentRunStarts"]
        require(len(starts) == 1 and starts[0]["entry"]["sessionId"] == value["identity"]["sessionId"],
                "native admission lacks its genuine original agent-run-start receipt")
        admitted = _event(raw, "actual-agent-run-start", label)
        require(_same(admitted["observation"], starts[0]),
                "native admission agent-run-start event is detached from its actual observed callback")
        first_model = _one(raw["events"], lambda row: row["event"] == "actual-model-invocation"
                           and row.get("turn") == label and row["index"] == 0,
                           "native admission lacks its first genuine foreground model invocation")
        require(entered["sequence"] < admitted["sequence"] < first_model["sequence"],
                "native admission/model began before its actual foreground submission")
        lifecycle = _one(turn["toolEvents"], lambda row: row.get("stream") == "lifecycle" and row["data"].get("phase") == "start"
                         and row["runId"] == starts[0]["runId"], "native admission start borrowed another actual run identity")
        require(lifecycle["runId"] == starts[0]["runId"], "native admission lifecycle/run identity changed")
        physical = _native_database(starts[0]["sqlite"], value)
        _native_database(turn["before"]["sqlite"], value)
        after_physical = _native_database(turn["after"]["sqlite"], value)
        actual_user = _native_user_readback(after_physical, value, directive["prompt"])
        require(_contains(actual_user, turn["after"]["transcript"])
                and not _user(turn["before"]["transcript"], directive["prompt"]),
                "native admission user readback was borrowed from before this actual turn")
        if label == "followup":
            readback = _native_user_readback(physical, value, directive["prompt"])
            require(_contains(readback, starts[0]["transcript"]),
                    "native admission next user was not physically read back at the actual run-start checkpoint")
        model = turn["modelCalls"]
        require(model and [row["index"] for row in model] == list(range(len(model)))
                and _user(model[0]["context"]["messages"], directive["prompt"]), "native model never received its declared actual user input")
        usage = value["firstTurnUsage"] if label == "save" else value["warmup"]["usage"] if label == "warmup-save" else value["followupUsage"]
        require(all(_same(row["reply"]["usage"].get("input"), usage["input"])
                    and _same(row["reply"]["usage"].get("output"), usage["output"])
                    and _same(row["reply"]["usage"].get("totalTokens"), usage["total"])
                    and row["reply"]["timestamp"] == value["nowMs"] for row in model),
                "native model actual emitted usage/clock differs from its declared foreground accounting")
        calls = turn["toolCalls"]
        require(all(_contains({k: v for k, v in call.items() if k != "modelCall"}, model[call["modelCall"]]["reply"]["content"])
                    for call in calls), "native dispatch was not emitted by its actual model")
        offset = 0
        if kind == "save":
            require(calls and calls[0]["name"] == "write" and _same(calls[0]["arguments"], {"path": value["source"], "content": directive["content"]}),
                    "native producer dispatch changed its actual save tool/path/bytes")
            failed = label == "save" and value["scenario"] == "refused-foreground"
            dispatched = _native_dispatch(turn["toolEvents"], calls[0], "write", calls[0]["arguments"], failed=failed)
            receipt = turn["producingToolResult"]
            require(receipt["toolName"] == "write" and receipt["toolCallId"] == calls[0]["id"] and receipt.get("isError") is failed
                    and _contains(receipt, model[1]["context"]["messages"]) and _same(dispatched["content"], receipt["content"]),
                    "native producer error/result was not consumed from its actual dispatch by its real model")
            if failed:
                error = json.loads(_text(receipt))
                require(error.get("status") == "error" and error.get("tool") == "write"
                        and native_refusal_names_source(error.get("error"), str(Path(raw["fixtureBase"]) / "workspace")),
                        "native producer refusal names another actual cause or source path")
            offset = 1
        reading = kind == "recall" or "verificationSearch" in directive
        if reading:
            options = directive["search" if kind == "recall" else "verificationSearch"]
            payload = _native_memory(turn, calls[offset], turn["searchCarrier"], "memory_search", options)
            require(_same(payload, turn["search"]) and _same(payload, result[key]["search"]), "native source search result lost complete public fields")
            offset += 1
            if payload["results"]:
                first = payload["results"][0]
                args = {"path": first["path"], "from": first["startLine"], "lines": first["endLine"] - first["startLine"] + 1}
                got = _native_memory(turn, calls[offset], turn["getCarrier"], "memory_get", args)
                require(_same(got, result[key]["get"]) and _same(args, turn["selectedGetArguments"]), "native getter did not follow its actual first search hit")
                offset += 1
        require(len(calls) == offset and _text(model[-1]["reply"]) == result[key]["deliveries"][0]["text"],
                "native model/dispatch supplied an unconsumed or fabricated terminal reply")
        delivery = _event(raw, "actual-terminal-delivery", label)
        require(_same(delivery["payload"], result[key]["deliveries"][0]) and delivery["info"]["kind"] == "final"
                and first_model["sequence"] < delivery["sequence"] < returned["sequence"],
                "native channel error/reply never reached its actual external final delivery after inference")
    next_call = _event(raw, "host-submission-attempt", "followup")
    require(_event(raw, "actual-terminal-delivery", "save")["sequence"] < next_call["sequence"],
            "native boundary public error/reply was not actually delivered before the next foreground submission/admission")
    if value["scenario"] != "pending-optional-preemption":
        require(_event(raw, "actual-host-return", "save")["sequence"] < next_call["sequence"],
                "native admission bypassed the actual prior host return/error delivery")
    if value.get("warmup"):
        require(_event(raw, "actual-host-return", "warmup-save")["sequence"] < _event(raw, "host-submission-attempt", "save")["sequence"],
                "native admission borrowed an unsettled warmup/source")
    _metadata(value, raw, native=True)
    _fixtures(value, raw, native=True)
    _faults(value, raw, native=True)
    _native_owner(raw, value)
    _lease(value, raw, native=True)
    _native_database(raw["closedSqlite"], value)
    require(_same(raw["closedSource"], result["source"]) and _same(raw["closedMaintenanceSource"], result["maintenanceSource"])
            and all(row["ok"] is True for row in raw["closeReceipts"])
            and not any(session["owners"] for session in raw["closeOwners"]), "native boundary close lost its real owner/source settlement")


def _sdk_call(record, call, ordinal):
    message, payload = call["observed"]["message"], call["observed"]["payload"]
    returned = call["returned"]
    require(message.get("role") == "toolResult" and message.get("toolName") == call["name"] and message.get("toolCallId") == call["id"]
            and _same(message.get("details"), payload)
            and _same(returned.get("details", returned), payload)
            and _contains(message, record["modelCalls"][ordinal + 1]["messages"])
            and _contains(call["assistant"], record["modelCalls"][ordinal + 1]["messages"])
            and _same(call["assistant"]["content"], [{"type": "toolCall", "id": call["id"], "name": call["name"], "arguments": call["arguments"]}]),
            "SDK dispatch/model actual result/carrier was substituted or not consumed")
    if call["name"] == "write" and message.get("isError") is False:
        require(_same(payload, {"changed": True}) and returned.get("status") == "ok"
                and returned.get("path") == call["arguments"]["path"] and returned.get("action") == "appended"
                and returned.get("text") == _text(message), "SDK actual append receipt was replaced by a fabricated success")
    else:
        require(_same(json.loads(_text(message)), payload), "SDK actual tool JSON carrier lost complete payload fields")
    if "details" in returned:
        require(_same(returned["content"], message["content"]) and returned.get("isError", False) is message.get("isError", False),
                "SDK actual complete producer carrier differs from its consumed result")
    return payload, message.get("isError", False)


def _sdk_owner(value, raw):
    jobs = raw["closedMaintenance"]["jobs"]
    if not value.get("maintenance"):
        require(not raw["maintenance"], "SDK maintenance model ran in the low-usage error schedule")
        return
    job = _one(jobs, lambda item: item["id"] == 1, "SDK maintenance lost its real first scheduled job")
    phases = job["events"]
    require(phases and phases[0]["phase"] == "pending" and job["settled"] is True and job["cancelRequested"] is True
            and [int(row["atNs"]) for row in phases] == sorted(int(row["atNs"]) for row in phases),
            "SDK maintenance intrinsic lifecycle did not retain actual registration/cancellation/settlement")
    abort = _one(phases, lambda row: row["phase"] == "foreground-preemption-requested", "SDK maintenance lacks its actual foreground preemption")
    done = _one(phases, lambda row: row["phase"] == "settled", "SDK maintenance cancellation was relabelled as actual settlement")
    next_model = _event(raw, "model-enter", "followup")
    require(int(abort["atNs"]) < int(done["atNs"]) < int(next_model["atNs"]),
            "SDK admission model entered before its actual maintenance producer settled")
    model_messages = _catalog_messages(next_model["catalogSnapshot"])
    require(_user(model_messages, value["followup"]["prompt"]), "SDK admission lacks the actual next user in its physical catalog")
    nodes = next_model["catalogSnapshot"]["tables"]["memory_session_nodes"]
    node = _one(nodes, lambda row: row["agent"] == value["identity"]["agentId"] and row["session_key"] == value["identity"]["sessionKey"],
                "SDK maintenance due usage belongs to another actual catalog/session")
    entry = json.loads(node["entry_json"])
    threshold = value["policy"]["contextWindowTokens"] - value["policy"]["reserveTokens"] - value["policy"]["softThresholdTokens"]
    require(entry.get("totalTokensFresh") is True and _same(entry.get("totalTokens"), value["firstTurnUsage"]["input"])
            and entry["totalTokens"] >= threshold, "SDK maintenance was merely a generic no-op owner without real due usage")
    done_observed = _one(raw["events"], lambda row: row["event"] == "optional-done-observed" and row["job"]["id"] == job["id"],
                         "SDK maintenance lacks its actual first owner.done callback")
    require(done_observed["job"]["settled"] is True and _same(done_observed["job"], job)
            and int(done["atNs"]) <= int(done_observed["atNs"]) < int(next_model["atNs"]),
            "SDK maintenance callback did not observe real settlement before next admission/model")
    scenario = value["scenario"]
    if scenario == "pending-optional-preemption":
        require(not raw["maintenance"] and abort["running"] is False
                and not any(row["phase"] == "started" for row in phases),
                "SDK maintenance pending preemption used a running or no-op fixture owner")
    elif scenario == "target-open-preparation":
        require(not raw["maintenance"] and abort["running"] is True, "SDK target-open boundary did not hold actual running preparation")
    else:
        require(len(raw["maintenance"]) == 1, "SDK maintenance model/producer was missing or duplicated")
        record = raw["maintenance"][0]
        require(len(record["toolCalls"]) == 1 and _user(record["modelCalls"][0]["messages"], value["save"]["prompt"])
                and record["modelCalls"][0]["flushTarget"] == value["maintenance"]["relativePath"],
                "SDK maintenance model lost its actual admitted request/history/target")
        call = record["toolCalls"][0]
        payload, failed = _sdk_call(record, call, 0)
        require(call["name"] == "write" and _same(call["arguments"], {"path": value["maintenance"]["relativePath"], "content": value["maintenance"]["body"]})
                and failed is (scenario == "refused-maintenance") and _same(record["consumedResult"], call),
                "SDK maintenance real producer/refusal was changed or never consumed")
        if failed:
            require("more than one hard link" in payload.get("error", ""), "SDK maintenance refusal has another actual cause")
        else:
            require(_same(record["sourceAfterResult"], _source(value["maintenance"]["relativePath"], value["maintenance"]["body"])),
                    "SDK maintenance source was not actually committed before the next request")
        require(_event(raw, "maintenance-result-consumed")["sequence"] < _event(raw, "host-call", "followup")["sequence"],
                "SDK maintenance result/error was not consumed before next submission")
    if scenario in {"pending-optional-preemption", "target-open-preparation"}:
        observed = _event(raw, "optional-abort-observed")
        require(not _user(_catalog_messages(observed["catalogSnapshot"]), value["followup"]["prompt"]),
                "SDK admission persisted the next user before required maintenance settlement")
        require(not _user(_catalog_messages(done_observed["catalogSnapshot"]), value["followup"]["prompt"]),
                "SDK admission persisted next user before actual owner.done was observed")


def _sdk(case, dispatch, result):
    value = case["input"]
    require(dispatch.get("kind") == "host-turn-barrier-boundaries-sdk-dispatch" and _same(dispatch.get("input"), value)
            and _same(dispatch.get("exit"), {"code": 0}) and type(dispatch.get("pid")) is int
            and type(dispatch.get("coordinatorPid")) is int and dispatch["pid"] > 0 and dispatch["coordinatorPid"] > 0
            and dispatch["pid"] != dispatch["coordinatorPid"] and int(dispatch["startedAtNs"]) < int(dispatch["finishedAtNs"]),
            "SDK boundary process dispatch failed or belongs to another actual input")
    wire = dispatch["requestJson"]
    request = json.loads(wire)
    require(hashlib.sha256(wire.encode()).hexdigest() == dispatch["requestSha256"] and _same(request, dispatch["request"])
            and _same(request["input"], value) and dispatch["argv"][1:] == ["-m", "equivalence.host_turn_barrier_boundaries_sdk_cli"]
            and dispatch["environmentKeys"] == ["LANG", "OPENCLAW_HOME", "OPENCLAW_STATE_DIR", "PATH", "PYTHONPATH", "TZ"],
            "SDK boundary actual protected process carrier was changed")
    output = json.loads(dispatch["stdout"])
    require(_same(output, dispatch["observation"]) and _same(output["result"], result), "SDK boundary stdout lost its complete public result")
    raw = output["raw"]
    require(raw.get("kind") == "host-turn-barrier-boundaries" and raw.get("engine") == "sdk"
            and raw.get("caseId") == case["id"] and _same(raw.get("input"), value) and _same(raw.get("result"), result)
            and raw["pid"] == dispatch["pid"] and raw["ppid"] == dispatch["coordinatorPid"]
            and raw["fixtureBase"] == request["directory"] and raw["implementationRoot"] == str(ROOT)
            and _same(raw["ownerPolicy"], {"memoryPublication": "on-search", "optionalMaintenance": "background"})
            and _same(raw["foregroundAuthority"], {"channel": "webchat", "senderId": "fixture-user", "configuredOwnerGrant": False, "senderIsOwner": False})
            and _same(raw["clock"], {"owner": "public-host-clock", "nowMs": value["nowMs"], "monotonicAndTimers": "unmodified"}),
            "SDK boundary actual owner/process/clock/input identity changed")
    _events(raw["events"])
    plan = _plan(value)
    require([row["label"] for row in raw["turns"]] == [item[0] for item in plan], "SDK boundary actual turn plan was substituted")
    for turn, (label, kind, directive, key) in zip(raw["turns"], plan, strict=True):
        require(_same(turn["directive"], directive) and _same(turn["public"], result[key]), "SDK boundary complete channel stage was dropped or reassigned")
        outcome = turn["outcome"]
        require(outcome["transcript_committed"] is True and outcome["session"]["session_id"] == value["identity"]["sessionId"]
                and outcome["session"]["session_key"] == value["identity"]["sessionKey"]
                and _same(outcome["payloads"], result[key]["deliveries"]), "SDK boundary raw HostTurnOutcome lost its actual admission or full delivered payloads")
        usage = value["firstTurnUsage"] if label == "save" else value["warmup"]["usage"] if label == "warmup-save" else value["followupUsage"]
        require(outcome["session"]["entry"].get("totalTokensFresh") is True
                and _same(outcome["session"]["entry"].get("totalTokens"), usage["input"]),
                "SDK actual HostTurnOutcome usage does not match its declared/persisted foreground accounting")
        require(_user(turn["modelCalls"][0]["messages"], directive["prompt"]), "SDK model never received its actual declared input")
        require(all(call["trust"]["senderIsOwner"] is False for call in turn["modelCalls"]),
                "SDK source producer elevated an ordinary external user to configured owner authority")
        users = [row for row in outcome["appends"] if row["message"].get("role") == "user"]
        require(len(users) == 1 and users[0]["appended"] is True and _text(users[0]["message"]) == directive["prompt"]
                and users[0]["message"]["id"] == "fixture-" + label,
                "SDK admission lost the actual committed user message and transport identity")
        calls = turn["toolCalls"]
        for ordinal, call in enumerate(calls):
            _sdk_call(turn, call, ordinal)
        offset = 0
        if kind == "save":
            failed = label == "save" and value["scenario"] == "refused-foreground"
            require(calls and calls[0]["name"] == "add_memory_entry"
                    and _same(calls[0]["arguments"], {"section": directive["section"], "text": directive["text"]})
                    and calls[0]["observed"]["message"].get("isError", False) is failed
                    and outcome["memory_writes_committed"] is (not failed),
                    "SDK real curated producer commit/refusal was forged")
            if failed:
                require("more than one hard link" in calls[0]["observed"]["payload"].get("error", ""), "SDK foreground refusal has another actual cause")
            offset = 1
        if kind == "recall" or "verificationSearch" in directive:
            options = directive["search" if kind == "recall" else "verificationSearch"]
            require(calls[offset]["name"] == "memory_search" and _same(calls[offset]["arguments"], options)
                    and _same(calls[offset]["observed"]["payload"], result[key]["search"]), "SDK actual search dispatch lost complete public fields")
            offset += 1
            if result[key]["search"]["results"]:
                first = result[key]["search"]["results"][0]
                args = {"path": first["path"], "from": first["startLine"], "lines": first["endLine"] - first["startLine"] + 1}
                require(calls[offset]["name"] == "memory_get" and _same(calls[offset]["arguments"], args)
                        and _same(calls[offset]["observed"]["payload"], result[key]["get"]), "SDK actual source getter did not follow the first hit")
                offset += 1
        require(len(calls) == offset and _text(turn["terminalMessage"]) == result[key]["deliveries"][0]["text"]
                and _contains(turn["terminalMessage"], turn["terminalInput"]["messages"]), "SDK model fabricated or detached its actual terminal reply")
        delivered = [row for row in raw["events"] if row["event"] == "channel-final-delivered" and row["label"] == label]
        require(_same([row["payload"] for row in delivered], result[key]["deliveries"])
                and _same(_event(raw, "delivery-ack", label)["counts"], result[key]["dispatchReturn"]["counts"]),
                "SDK public dispatch accounting was not derived from actual complete delivered callbacks")
        entered, model = _event(raw, "host-call", label), _event(raw, "model-enter", label)
        terminal, delivered_event = _event(raw, "terminal-reply", label), _event(raw, "channel-final-delivered", label)
        acknowledged, returned = _event(raw, "delivery-ack", label), _event(raw, "host-return", label)
        require(entered["sequence"] < model["sequence"] < terminal["sequence"] < delivered_event["sequence"]
                < acknowledged["sequence"] < returned["sequence"],
                "SDK admission/model/delivery actual lifecycle was reordered or began before foreground submission")
    next_call = _event(raw, "host-call", "followup")
    require(_event(raw, "channel-final-delivered", "save")["sequence"] < next_call["sequence"],
            "SDK boundary public error/reply was not actually delivered before the next foreground submission/admission")
    if value["scenario"] != "pending-optional-preemption":
        require(_event(raw, "host-return", "save")["sequence"] < next_call["sequence"],
                "SDK admission bypassed the actual prior host return/error delivery")
    if value.get("warmup"):
        require(_event(raw, "host-return", "warmup-save")["sequence"] < _event(raw, "host-call", "save")["sequence"],
                "SDK admission borrowed an unsettled warmup/source")
    _metadata(value, raw, native=False)
    _fixtures(value, raw, native=False)
    _faults(value, raw, native=False)
    _sdk_owner(value, raw)
    _lease(value, raw, native=False)
    require(raw["closedLifecycle"]["closed"] is True and raw["closedStatus"]["closed"] is True
            and all(job["settled"] is True for job in raw["closedMaintenance"]["jobs"]), "SDK boundary close failed to join its actual admitted owners")


def validate_result(case, result):
    try:
        return _validate_result(case, result)
    except (KeyError, IndexError, TypeError, AttributeError, StopIteration, json.JSONDecodeError) as error:
        raise ValueError("boundary public result is structurally incomplete") from error


def validate_capture(case, raw, result, *, native):
    validate_result(case, result)
    try:
        (_native if native else _sdk)(case, raw, result)
    except (KeyError, IndexError, TypeError, AttributeError, StopIteration, json.JSONDecodeError) as error:
        raise ValueError(("native" if native else "SDK") + " boundary evidence is structurally incomplete") from error
    return True


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
    require(len(originals) == len(copies) == 1, "boundary replay requires exactly one actual capture per engine")
    validate_pair(case, originals[0], copies[0], native, sdk)
    return {"validated": True, "nativeSnapshots": 1, "sdkSnapshots": 1}
