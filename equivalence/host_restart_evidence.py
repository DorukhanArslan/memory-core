"""Replay restart custody, actual tool dataflow and complete public results.

Replay is a structural guard, not a substitute for authenticated live processes.
No score, timestamp, warning, error or output field is repaired here.
"""
import hashlib
import json
from pathlib import Path

from equivalence.host_restart import validate_case
from equivalence.promotion_apply_family import differences


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _wire(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _text(message):
    content = message.get("content", [])
    return content if isinstance(content, str) else "".join(
        item["text"] for item in content if item.get("type") == "text")


def _decode(message):
    payload = json.loads(_text(message))
    if "details" in message:
        require(payload == message["details"], "Model-visible JSON differs from complete tool details")
    return payload


def _tool_message(messages, name):
    found = [item for item in messages if item.get("role") == "toolResult" and item.get("toolName") == name]
    require(len(found) == 1, "A read must retain exactly one actual tool result")
    return found[0]


def _get_arguments(search):
    hit = search["results"][0]
    return {"path": hit["path"], "from": hit["startLine"],
            "lines": hit["endLine"] - hit["startLine"] + 1, "corpus": "memory"}


def _read(case, public, initial, terminal, tool_calls, assistant, *, failure):
    token = case["input"]["phases"][0]["write"]["text"].removeprefix("My drink preference is ").removesuffix(".")
    require(token and token not in _wire(initial), "A fresh reader received the saved answer in its initial model input")
    require(public["query"] == case["input"]["phases"][0]["recall"]["query"], "The reader used an undeclared answer-bearing query")
    require([call["name"] for call in tool_calls] == (["memory_search", "memory_get"] if public["get"] is not None else ["memory_search"]),
            "The real read tool sequence differs from its public result")
    require(tool_calls[0]["arguments"] == {"query": public["query"], "maxResults": 5, "minScore": 0, "corpus": "memory"},
            "Search was not the declared generic source query")
    require(_decode(_tool_message(terminal["messages"], "memory_search")) == public["search"],
            "The complete search result differs from the terminal model input")
    require(tool_calls[0]["payload"] == public["search"], "Search result was rewritten after execution")
    if public["get"] is not None:
        source_path = case["input"]["phases"][0]["write"]["path"]
        require(public["search"]["results"][0]["path"] == source_path == public["get"]["path"],
                "The primary hit and get do not refer to the actual saved source")
        require(tool_calls[1]["arguments"] == _get_arguments(public["search"]), "Get range did not come from the actual first search hit")
        require(_decode(_tool_message(terminal["messages"], "memory_get")) == public["get"] == tool_calls[1]["payload"],
                "Get payload was rewritten or came from outside the actual model context")
        payload = public["get"]
        expected = payload["text"] if isinstance(payload.get("text"), str) and payload["text"] else _wire(payload)
        require(payload.get("status") == ("error" if failure else "ok"), "The genuine filesystem failure was hidden or invented")
        if not failure:
            source = case["input"]["phases"][0]["write"]["content"]
            selected = source.splitlines()[payload["from"] - 1:payload["from"] - 1 + payload["lines"]]
            require(payload["text"] == "\n".join(selected), "Get text is not backed by the actual saved source range")
    else:
        require(public["session"] == "isolated" and public["search"]["results"] == [], "A primary reader lost the saved corpus")
        expected = "No source-backed memory found."
    require(public["answer"] == expected == _text(assistant), "The terminal answer did not come from the actual tool result")


def _validate_capture(case, raw, result, *, native, policy):
    if policy:
        from equivalence.host_restart_policy import validate_case as validate_literal
    else:
        validate_literal = validate_case
    validate_literal(case)
    value = case["input"]
    require(raw["input"] == value and result["provider"] == "none", "The host consumed another case or a provider")
    records = raw["children"] if native else raw["phases"]
    require(len(records) == 2 and [record["label"] for record in records] == ["produce", "restart"], "Missing independent host phases")
    require(len({raw["coordinatorPid"], *(record["pid"] for record in records)}) == 3, "A host phase reused a process")
    require(int(records[0]["startedAtNs"]) < int(records[0]["finishedAtNs"]) < int(records[1]["startedAtNs"]) < int(records[1]["finishedAtNs"]),
            "The producer had not exited before the reader host started")
    identity = value["identity"]
    require(len({identity[key]["sessionId"] for key in ("writer", "fresh", "restarted", "isolated")}) == 4,
            "A fresh reader reused history from the writer or earlier reader")
    observed = []
    for ordinal, record in enumerate(records):
        request = record["request"]
        require(request == {"directory": raw["fixtureBase"], **({"runtimeRoot": request["runtimeRoot"]} if native else {}),
                **({"policy": value["policy"]} if policy else {}),
                "identity": identity, "nowMs": value["nowMs"], "phase": value["phases"][ordinal],
                "sourcePath": value["phases"][0]["write"]["path"]}, "A reader inherited a full case or an undeclared carrier")
        if ordinal == 1:
            token = value["phases"][0]["write"]["text"].removeprefix("My drink preference is ").removesuffix(".")
            require(token not in _wire(request), "The restarted child received the saved fact through its process input")
        stdin = record["stdin"] if native else record["requestJson"]
        require(json.loads(stdin) == request and hashlib.sha256(stdin.encode()).hexdigest() == record["stdinSha256" if native else "requestSha256"],
                "Host process input differs from the recorded custody digest")
        require(record["exit"] == ({"code": 0, "signal": None} if native else {"code": 0}), "A genuine host phase did not exit cleanly")
        output = record["output"] if native else record["observation"]
        require(json.loads(record["stdout"]) == output, "A host observation differs from actual child stdout")
        phase = output["raw"]
        require(phase["pid"] == record["pid"] and phase["ppid"] == raw["coordinatorPid"] and phase["request"] == request,
                "Phase identity or input changed after process launch")
        if ordinal == 0:
            require(phase["initialSource"]["kind"] == "missing", "The source was seeded instead of produced by the real tool")
        public_phase = output["result"]
        require([item["session"] for item in public_phase["reads"]] == (["fresh"] if ordinal == 0 else ["restarted", "isolated"]),
                "Missing same-host, restarted-host or isolated read")
        if native:
            require(len(phase["closeReceipts"]) == 2 and all(item["completed"] for item in phase["closeReceipts"]), "Original host resources did not close")
            for session in phase["sessions"]:
                require(session["initialEvents"] == [] and session["historyConstruction"]["messages"] == []
                        and session["scope"]["sessionKey"] not in session["loadedStore"], "A fresh identity discarded existing session history")
                require(session["persistence"] and all(item["result"]["appended"] for item in session["persistence"]), "The native host did not persist actual loop messages")
            writer = phase["loops"][0] if ordinal == 0 else None
            if writer:
                events = writer["toolEvents"]
                require(len(events) == 1 and events[0]["toolName"] == "write" and events[0]["executionStarted"] and not events[0]["isError"],
                        "The original coding producer did not really execute")
        else:
            require(all(not row["activeTurn"] and row["outstandingBlockingSources"] == 0 for row in phase["settlement"]), "The SDK host left active producers")
            if ordinal == 0:
                writer = phase["turns"][0]
                require(writer["toolCalls"][0]["name"] == "append_daily_note" and writer["outcome"]["memory_writes_committed"], "The SDK producer was not a real published host write")
        for public in public_phase["reads"]:
            failure = ordinal == 1 and public["session"] == "restarted" and "beforeGet" in request["phase"]
            if native:
                loop = next(item for item in phase["loops"] if item["label"] == public["session"])
                initial, terminal = loop["modelCalls"][0]["context"], loop["modelCalls"][-1]["context"]
                token = value["phases"][0]["write"]["text"].removeprefix("My drink preference is ").removesuffix(".")
                require(token not in _wire({key: loop["modelCalls"][0][key] for key in ("model", "context", "options")}),
                        "The saved answer leaked through actual initial model options or descriptor")
                assistant = loop["messages"][-1]
                calls = []
                for event in loop["toolEvents"]:
                    require(event["executionStarted"] and not event["isError"], "The real host tool dispatch failed")
                    arguments = [block["arguments"] for call in loop["modelCalls"] for block in call["response"]["content"]
                                 if block.get("type") == "toolCall" and block["id"] == event["toolCallId"]]
                    require(len(arguments) == 1, "A tool event has no unique real model request")
                    calls.append({"name": event["toolName"], "arguments": arguments[0], "payload": _decode(event["result"])})
            else:
                turn = next(item for item in phase["turns"] if item["session"] == public["session"])
                initial, terminal, assistant = turn["modelInput"], turn["terminalInput"], turn["assistant"]
                require(all(item["returned"] == item["observed"]["payload"] == _decode(item["observed"]["message"])
                            for item in turn["toolCalls"]), "SDK direct returns differ from its actual model-visible results")
                calls = [{"name": item["name"], "arguments": item["arguments"], "payload": item["observed"]["payload"]} for item in turn["toolCalls"]]
                require(turn["outcome"]["transcript_committed"] and not turn["outcome"]["cancelled"], "The SDK host did not commit the read transcript")
                require(bool(turn["outcome"]["failures"]) == failure, "The SDK suppressed or invented an operational failure")
            _read(case, public, initial, terminal, calls, assistant, failure=failure)
            if public["session"] == "isolated":
                if native:
                    last = phase["snapshots"][-1]
                    require(last["isolatedSource"]["kind"] == "missing", "The isolated native workspace contains the primary source")
                    manager = next(item for item in last["memory"] if item["agentId"] == identity["isolatedAgentId"])
                    memory = next(item for item in manager["status"]["sourceCounts"] if item["source"] == "memory")
                    chunks = next(item for item in manager["sql"]["tables"] if item["name"] == "memory_index_chunks")["rows"]
                    require(memory["chunks"] == 0 and token not in _wire(chunks), "The isolated native index contains primary memory")
                else:
                    snapshot = next(item for item in phase["snapshots"] if item["session"] == "isolated")
                    chunks = snapshot["published"]["chunks"]
                    clean = (not any(item["source"] == "memory" for item in chunks) and token not in _wire(chunks)) if policy else not chunks
                    require(snapshot["source"]["kind"] == "missing" and clean,
                            "The isolated SDK workspace/index contains the primary corpus")
        source = public_phase["source"]
        if ordinal == 1 and "beforeGet" in request["phase"]:
            require(source["kind"] == "directory", "The post-search filesystem mutation did not occur")
            mutation = phase["mutations"][0] if native else phase["turns"][0]["sourceMutation"]
            before = mutation["before"]["source"] if native else mutation["before"]
            after = mutation["after"]["source"] if native else mutation["after"]
            retired = mutation["after"]["retired"] if native else mutation["retiredSource"]
            require(before["kind"] == "file" and after["kind"] == "directory"
                    and retired["hex"] == value["phases"][0]["write"]["content"].encode().hex(),
                    "The operational error lacks real source-byte custody")
        else:
            content = value["phases"][0]["write"]["content"]
            require(source == {"path": request["sourcePath"], "kind": "file", "text": content, "hex": content.encode().hex()},
                    "The real producer changed the saved source corpus")
        observed.append(public_phase)
    require(result == {"provider": "none", "phases": observed}, "A comparable result differs from its full host observations")
    return {"structuralCustodyPassed": True, "acceptancePointsAwarded": 0}


def validate_capture(case, raw, result, *, native):
    return _validate_capture(case, raw, result, native=native, policy=False)


def replay_case(case, directory):
    directory = Path(directory)
    native = json.loads((directory / "evidence/native-raw.json").read_text())[0]
    sdk = json.loads((directory / "evidence/python-raw.json").read_text())[0]
    original = json.loads((directory / "stdout.json").read_text())["result"]
    implementation = json.loads((directory / "sdk-output.json").read_text())
    validate_capture(case, native, original, native=True)
    validate_capture(case, sdk, implementation, native=False)
    return {"structuralCustodyPassed": True, "differences": differences(original, implementation), "acceptancePointsAwarded": 0}
