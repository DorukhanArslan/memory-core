"""Bind natural host observations to real requests, tools, sources and replies.

This guard awards nothing. The harness separately compares complete public
results and requires the entire frozen family for the original outcome point.
It makes no claim about optional-maintenance preemption, failure admission or
the restart family's per-message physical SQL commit chain.
"""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
from equivalence.host_turn_barrier import validate_case

ROOT = Path(__file__).resolve().parents[1]
EMPTY_ANSWER = "No source-backed memory found."


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _same(left, right):
    """JSON booleans never stand in for numbers in a custody binding."""
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all((_same(left[key], right[key]) for key in left))
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all((_same(a, b) for a, b in zip(left, right)))
    return left == right


def _contains(value, collection):
    if isinstance(collection, str):
        return isinstance(value, str) and value in collection
    return any((_same(value, item) for item in collection))


def _text(message):
    content = message.get("content", [])
    return (
        content
        if isinstance(content, str)
        else "".join((block["text"] for block in content if _same(block.get("type"), "text")))
    )


def _source(text):
    return {"path": "MEMORY.md", "kind": "file", "text": text, "hex": text.encode().hex()}


def _plan(value):
    plan = []
    if _same(value["initialState"], "warm"):
        plan.extend(
            [
                ("warmup-save", "save", value["warmup"]["save"]),
                ("warmup-recall", "recall", value["warmup"]["recall"]),
            ]
        )
    plan.extend([("save", "save", value["save"]), ("followup", "recall", value["followup"])])
    return plan


def _read(public, directive, source):
    require(
        isinstance(public, dict) and _same(set(public), {"search", "get", "reply"}),
        "A public read is incomplete or contains reassigned fields",
    )
    search = public["search"]
    require(
        isinstance(search, dict)
        and isinstance(search.get("results"), list)
        and _same(search.get("provider"), "none")
        and _same(search.get("citations"), "off"),
        "The real memory-only search result is missing",
    )
    debug = search.get("debug")
    require(
        isinstance(debug, dict)
        and _same(debug.get("hits"), len(search["results"]))
        and _same(debug.get("withheldHits"), 0),
        "The tool did not execute its complete ordinary search",
    )
    reply = public["reply"]
    require(
        isinstance(reply, dict)
        and _same(set(reply), {"text", "replyToTag", "audioAsVoice"})
        and (reply["replyToTag"] is False)
        and (reply["audioAsVoice"] is False),
        "The complete actual host reply is missing",
    )
    if search["results"]:
        first, got = (search["results"][0], public["get"])
        require(
            isinstance(got, dict)
            and _same(got.get("status"), "ok")
            and (
                _same(got.get("path"), first.get("path")) and _same(first.get("path"), "MEMORY.md")
            )
            and _same(got.get("from"), first.get("startLine"))
            and (type(got.get("lines")) is int),
            "The source read does not follow the actual first hit",
        )
        lines = source.splitlines()
        selected = lines[got["from"] - 1 : got["from"] - 1 + got["lines"]]
        require(
            selected
            and _same(got.get("text"), "\n".join(selected))
            and _same(reply["text"], got["text"]),
            "The reply did not consume the actual source range",
        )
    else:
        require(
            public["get"] is None
            and _same(reply["text"], EMPTY_ANSWER)
            and _same(debug.get("candidateHits"), 0),
            "An empty actual search cannot invent a source-backed reply",
        )
    require(_same(directive["getRange"], "first-actual-search-hit"), "The retrieval plan changed")


def validate_result(case, result):
    validate_case(case)
    value = case["input"]
    require(
        isinstance(result, dict)
        and _same(set(result), {"provider", "warmup", "source", "followup"})
        and _same(result["provider"], "none")
        and _same(result["source"], _source(value["save"]["content"])),
        "The public outcome is detached from its saved corpus",
    )
    if _same(value["initialState"], "warm"):
        _read(result["warmup"], value["warmup"]["recall"], value["warmup"]["save"]["content"])
        require(
            result["warmup"]["search"]["results"],
            "A warm index needs a genuine positive retrieval control",
        )
    else:
        require(result["warmup"] is None, "A cold case cannot borrow a warmup")
    _read(result["followup"], value["followup"], value["save"]["content"])
    if _same(value["initialState"], "cold"):
        require(
            result["followup"]["search"]["results"],
            "The cold natural save/follow-up did not retrieve its corpus",
        )
    return True


def _events(rows):
    require(isinstance(rows, list) and rows, "Missing actual lifecycle chronology")
    sequences = [row["sequence"] for row in rows]
    instants = [int(row["atNs"]) for row in rows]
    require(
        all((type(item) is int for item in sequences))
        and _same(sequences, sorted(set(sequences)))
        and _same(instants, sorted(instants)),
        "Lifecycle observations were reordered or duplicated",
    )


def _event(rows, name, label, *, native):
    matches = [
        row
        for row in rows
        if _same(row["event"], name)
        and (
            _same(row.get("label"), label)
            if not native or _contains("label", row)
            else _same(row.get("turn"), label)
        )
    ]
    require(_same(len(matches), 1), f"Missing unique {label} {name} receipt")
    return matches[0]


def _native_tool(turn, call, *, expected_name, arguments):
    events = [event for event in turn["toolEvents"] if _same(event.get("stream"), "tool")]
    starts = [
        event
        for event in events
        if _same(event["data"].get("phase"), "start")
        and _same(event["data"].get("toolCallId"), call["id"])
    ]
    ends = [
        event
        for event in events
        if _same(event["data"].get("phase"), "result")
        and _same(event["data"].get("toolCallId"), call["id"])
    ]
    require(
        (_same(len(starts), len(ends)) and _same(len(ends), 1))
        and starts[0]["seq"] < ends[0]["seq"]
        and _same(starts[0]["runId"], ends[0]["runId"])
        and (
            _same(starts[0]["data"].get("name"), ends[0]["data"].get("name"))
            and _same(ends[0]["data"].get("name"), expected_name)
        )
        and _same(starts[0]["data"].get("args"), arguments)
        and (ends[0]["data"].get("isError") is False),
        "The native dispatch lacks its actual original start/result events",
    )
    return ends[0]["data"]["result"]


def _native_memory(turn, call, carrier, name, arguments):
    require(
        _same(call["name"], "tool_call")
        and _same(call["arguments"], {"id": name, "args": arguments}),
        "The original deferred memory dispatch changed",
    )
    _native_tool(turn, call, expected_name="tool_call", arguments=call["arguments"])
    require(
        _same(carrier.get("role"), "toolResult")
        and _same(carrier.get("toolName"), "tool_call")
        and _same(carrier.get("toolCallId"), call["id"])
        and (carrier.get("isError") is False),
        "The model did not consume its actual deferred-tool carrier",
    )
    later = turn["modelCalls"][call["modelCall"] + 1]["context"]["messages"]
    require(
        _contains(carrier, later),
        "A native result was detached from its following actual model input",
    )
    wrapped = json.loads(_text(carrier))
    require(
        _same(wrapped["tool"].get("name"), name)
        and _same(wrapped["tool"].get("source"), "openclaw"),
        "The deferred dispatcher returned another tool",
    )
    receipt = wrapped["result"]
    payload = json.loads(_text(receipt))
    require(
        _same(payload, receipt.get("details")),
        "The complete native memory details differ from their visible JSON",
    )
    starts = [
        event
        for event in turn["toolEvents"]
        if _same(event.get("stream"), "tool")
        and _same(event["data"].get("phase"), "start")
        and _same(event["data"].get("name"), name)
        and _same(event["data"].get("parentToolCallId"), call["id"])
    ]
    require(
        _same(len(starts), 1) and _same(starts[0]["data"].get("args"), arguments),
        "The nested original memory owner was not actually dispatched",
    )
    nested = _native_tool(
        turn, {"id": starts[0]["data"]["toolCallId"]}, expected_name=name, arguments=arguments
    )
    require(
        _same(nested, receipt),
        "The public memory payload differs from the actual nested dispatch result",
    )
    return payload


def _native(case, raw, result):
    value = case["input"]
    require(
        _same(raw.get("kind"), "host-turn-barrier-native")
        and (_same(raw.get("input"), raw.get("request")) and _same(raw.get("request"), value))
        and _same(raw.get("result"), result)
        and (type(raw.get("pid")) is int)
        and (raw["pid"] > 0)
        and (type(raw.get("ppid")) is int)
        and (raw["ppid"] > 0)
        and (not _same(raw["pid"], raw["ppid"])),
        "The original full-caller capture is detached from its input or process",
    )
    scope = raw["scope"]
    require(
        all((_same(scope.get(key), item) for key, item in value["identity"].items())),
        "The original host identity changed",
    )
    resolved = raw["resolvedMemorySearch"]
    require(
        _same(resolved.get("sources"), ["memory"])
        and all(
            (resolved["sync"].get(key) is True for key in ("onSessionStart", "onSearch", "watch"))
        ),
        "The actual native synchronization policy changed",
    )
    require(
        raw["config"]["agents"]["defaults"]["compaction"]["enabled"] is True,
        "The full host cannot disable optional maintenance to claim an outcome",
    )
    _events(raw["events"])
    plan = _plan(value)
    require(
        _same([turn["label"] for turn in raw["turns"]], [item[0] for item in plan]),
        "The host ran another turn plan",
    )
    prior = {"path": "MEMORY.md", "kind": "missing"}
    previous_return = None
    metadata = raw["metadataOperations"]
    require(
        _same(len(metadata), sum((_same(kind, "save") for _, kind, _ in plan))),
        "Producer metadata is missing or duplicated",
    )
    for turn, (label, kind, instruction) in zip(raw["turns"], plan, strict=True):
        require(
            _same(turn["kind"], kind)
            and _same(turn["instruction"], instruction)
            and _same(turn["before"]["source"], prior),
            "The actual native turn was reassigned or opened another corpus",
        )
        params = turn["callInput"]
        require(
            not _contains("replyOperation", params)
            and _same(params["followupRun"], turn["followupRun"])
            and _same(params["commandBody"], instruction["prompt"])
            and _same(params["sessionKey"], scope["sessionKey"])
            and _same(params["storePath"], scope["storePath"]),
            "The full native admission was bypassed or changed",
        )
        run = params["followupRun"]
        require(
            _same(run["prompt"], instruction["prompt"])
            and all((_same(run["run"].get(key), item) for key, item in value["identity"].items()))
            and _same(run["run"]["config"], raw["config"])
            and _same(run["run"]["workspaceDir"], str(Path(raw["fixtureBase"]) / "workspace"))
            and _same(raw["config"]["agents"]["defaults"]["workspace"], run["run"]["workspaceDir"]),
            "The actual full-host model request changed",
        )
        entered = _event(raw["events"], "host-submission-attempt", label, native=True)
        returned = _event(raw["events"], "actual-host-return", label, native=True)
        require(
            _same(returned.get("reply"), turn["reply"])
            and entered["sequence"] < returned["sequence"]
            and (previous_return is None or previous_return["sequence"] < entered["sequence"]),
            "The immediate follow-up did not follow its actual host return",
        )
        previous_return = returned
        model = turn["modelCalls"]
        require(
            model
            and any(
                (
                    _same(message.get("role"), "user")
                    and _contains(instruction["prompt"], _text(message))
                    for message in model[0]["context"]["messages"]
                )
            ),
            "The native model did not receive the declared user input",
        )
        calls = turn["toolCalls"]
        require(
            calls
            and all(
                (
                    _contains(
                        {key: item for key, item in call.items() if not _same(key, "modelCall")},
                        model[call["modelCall"]]["reply"]["content"],
                    )
                    for call in calls
                )
            ),
            "A dispatch was not emitted by the actual scripted model",
        )
        if _same(kind, "save"):
            expected = _source(instruction["content"])
            require(
                _same(len(calls), 1)
                and _same(calls[0]["name"], "write")
                and _same(
                    calls[0]["arguments"],
                    {"path": value["source"], "content": instruction["content"]},
                ),
                "The genuine original producer changed",
            )
            _native_tool(turn, calls[0], expected_name="write", arguments=calls[0]["arguments"])
            carrier = turn["producingToolResult"]
            require(
                _contains(carrier, model[1]["context"]["messages"])
                and _same(carrier.get("toolCallId"), calls[0]["id"])
                and _same(carrier.get("toolName"), "write")
                and (carrier.get("isError") is False),
                "The original save did not consume its successful actual tool result",
            )
            receipt = next((row for row in metadata if _same(row["turn"], label)), None)
            digest = hashlib.sha256(instruction["content"].encode()).hexdigest()
            require(
                receipt
                and _same(receipt["operation"], "utimesSync")
                and (receipt["returnedUndefined"] is True)
                and _same(receipt["placement"], value["sourceMetadataFixture"]["placement"])
                and (
                    _same(receipt["before"]["sha256"], receipt["after"]["sha256"])
                    and _same(receipt["after"]["sha256"], digest)
                )
                and _same(receipt["after"]["nlink"], 1)
                and _same(receipt["after"]["mtimeMs"], value["nowMs"])
                and _same(
                    receipt["arguments"],
                    [
                        receipt["before"]["absolutePath"],
                        value["nowMs"] / 1000,
                        value["nowMs"] / 1000,
                    ],
                )
                and (int(receipt["startedAtNs"]) <= int(receipt["finishedAtNs"])),
                "The native metadata fixture was not the declared byte-preserving operation",
            )
            metadata_event = _event(raw["events"], "source-metadata", label, native=True)
            tool_results = [
                event
                for event in raw["events"]
                if _same(event["event"], "actual-agent-event")
                and _same(event["observation"].get("stream"), "tool")
                and _same(event["observation"]["data"].get("phase"), "result")
                and _same(event["observation"]["data"].get("toolCallId"), calls[0]["id"])
            ]
            terminal_events = [
                event
                for event in raw["events"]
                if _same(event["event"], "actual-agent-event")
                and _same(event.get("turn"), label)
                and _same(event["observation"].get("stream"), "assistant")
                and _same(event["observation"]["data"].get("text"), turn["reply"]["text"])
            ]
            path = str(Path(run["run"]["workspaceDir"]) / value["source"])
            require(
                (_same(len(tool_results), len(terminal_events)) and _same(len(terminal_events), 1))
                and int(tool_results[0]["atNs"])
                < int(receipt["startedAtNs"])
                <= int(receipt["finishedAtNs"])
                <= int(metadata_event["atNs"])
                < int(terminal_events[0]["atNs"])
                < int(returned["atNs"])
                and (
                    _same(receipt["before"]["absolutePath"], receipt["after"]["absolutePath"])
                    and _same(receipt["after"]["absolutePath"], path)
                )
                and _same(receipt["before"]["ino"], receipt["after"]["ino"]),
                "The native metadata fixture escaped its actual producer callback or workspace",
            )
            prior = expected
        else:
            public = result["warmup"] if _same(label, "warmup-recall") else result["followup"]
            observed = _native_memory(
                turn, calls[0], turn["searchCarrier"], "memory_search", instruction["search"]
            )
            require(
                _same(observed, turn["search"]) and _same(turn["search"], public["search"]),
                "The public search dropped or repaired native fields",
            )
            if observed["results"]:
                first = observed["results"][0]
                args = {
                    "path": first["path"],
                    "from": first["startLine"],
                    "lines": first["endLine"] - first["startLine"] + 1,
                }
                require(
                    _same(len(calls), 2) and _same(turn["selectedGetArguments"], args),
                    "The get range was not selected from the actual native hit",
                )
                got = _native_memory(turn, calls[1], turn["getCarrier"], "memory_get", args)
                require(
                    _same(got, turn["get"]) and _same(turn["get"], public["get"]),
                    "The public get differs from actual native dispatch",
                )
            else:
                require(
                    _same(len(calls), 1) and turn["get"] is public["get"] is None,
                    "The host invented a source read after an empty search",
                )
            require(
                _same(turn["reply"], public["reply"]),
                "The public reply differs from the actual full caller",
            )
        require(
            _same(turn["after"]["source"], prior)
            and _same(turn["reply"]["text"], _text(model[-1]["reply"])),
            "The committed source or delivered native reply was replaced",
        )
    final = _event(raw["events"], "public-outcome-fixed", "followup", native=True)
    joins = [row for row in raw["events"] if row["event"].startswith("teardown-maintenance-join-")]
    require(
        _same(len(joins), 2) and all((row["sequence"] > final["sequence"] for row in joins)),
        "A fixture maintenance wait was inserted before the compared outcome",
    )
    require(
        _same(raw.get("closeOwners"), [])
        and _same(raw.get("closedSource"), prior)
        and _same(
            [row["label"] for row in raw["closeReceipts"]],
            ["memory-managers", "mcp-runtime", "scheduler", "agent-databases"],
        )
        and all((row["ok"] is True for row in raw["closeReceipts"])),
        "Original accepted work did not close honestly",
    )


def _sdk(case, dispatch, result):
    value = case["input"]
    require(
        type(dispatch.get("pid")) is int
        and type(dispatch.get("coordinatorPid")) is int
        and (dispatch["pid"] > 0)
        and (dispatch["coordinatorPid"] > 0)
        and (not _same(dispatch["pid"], dispatch["coordinatorPid"])),
        "SDK process identities must be distinct positive integers",
    )
    require(
        _same(dispatch.get("kind"), "host-turn-barrier-sdk-dispatch")
        and _same(dispatch.get("input"), value)
        and _same(dispatch.get("exit"), {"code": 0})
        and (int(dispatch["startedAtNs"]) < int(dispatch["finishedAtNs"])),
        "The SDK process dispatch failed or belongs to another literal",
    )
    wire = dispatch["requestJson"]
    request = json.loads(wire)
    require(
        _same(hashlib.sha256(wire.encode()).hexdigest(), dispatch["requestSha256"])
        and _same(request, dispatch["request"])
        and _same(request["input"], value)
        and _same(dispatch["argv"][1:], ["-m", "equivalence.host_turn_barrier_sdk_cli"])
        and _same(
            dispatch["environmentKeys"],
            ["LANG", "OPENCLAW_HOME", "OPENCLAW_STATE_DIR", "PATH", "PYTHONPATH", "TZ"],
        ),
        "The SDK host borrowed or changed its protected input carrier",
    )
    output = json.loads(dispatch["stdout"])
    require(
        _same(output, dispatch["observation"]) and _same(output["result"], result),
        "SDK stdout differs from its public outcome",
    )
    raw = output["raw"]
    require(
        _same(raw.get("kind"), "host-turn-barrier")
        and _same(raw.get("engine"), "sdk")
        and _same(raw.get("input"), value)
        and _same(raw.get("pid"), dispatch["pid"])
        and _same(raw.get("ppid"), dispatch["coordinatorPid"])
        and _same(raw.get("fixtureBase"), request["directory"])
        and _same(raw.get("implementationRoot"), str(ROOT))
        and _same(raw.get("ownerPolicy"), "on-search")
        and _same(raw.get("result"), result),
        "The SDK raw host is detached from its actual process or owner",
    )
    require(
        _same(
            raw["clock"],
            {
                "owner": "public-host-clock",
                "nowMs": value["nowMs"],
                "monotonicAndTimers": "unmodified",
            },
        ),
        "The SDK changed its declared clock authority",
    )
    _events(raw["events"])
    plan = _plan(value)
    require(
        _same([row["label"] for row in raw["turns"]], [item[0] for item in plan]),
        "The SDK ran another natural host plan",
    )
    prior, previous_return = ({"path": "MEMORY.md", "kind": "missing"}, None)
    require(
        _same(len(raw["metadata"]), sum((_same(kind, "save") for _, kind, _ in plan))),
        "SDK producer metadata is missing or duplicated",
    )
    for turn, (label, kind, instruction) in zip(raw["turns"], plan, strict=True):
        require(
            _same(turn["directive"], instruction) and _same(turn["sourceBefore"], prior),
            "The SDK turn used another corpus or request",
        )
        entered = _event(raw["events"], "host-call", label, native=False)
        returned = _event(raw["events"], "host-return", label, native=False)
        require(
            entered["sequence"] < returned["sequence"]
            and (previous_return is None or previous_return["sequence"] < entered["sequence"]),
            "The SDK next turn bypassed actual host settlement",
        )
        previous_return = returned
        calls, outcome = (turn["toolCalls"], turn["outcome"])
        require(
            outcome["transcript_committed"] is True
            and (not outcome["failures"])
            and _same(outcome["session"]["session_id"], value["identity"]["sessionId"])
            and _same(outcome["session"]["session_key"], value["identity"]["sessionKey"]),
            "The SDK turn was not actually admitted and completed",
        )
        require(
            any(
                (
                    _same(message.get("role"), "user")
                    and _same(_text(message), instruction["prompt"])
                    for message in turn["modelCalls"][0]["messages"]
                )
            ),
            "The SDK model did not receive its declared input",
        )
        for ordinal, call in enumerate(calls):
            message = call["observed"]["message"]
            payload = json.loads(_text(message))
            require(
                (
                    _same(payload, message.get("details"))
                    and _same(message.get("details"), call["observed"]["payload"])
                    and _same(call["observed"]["payload"], call["returned"])
                )
                and _same(message.get("toolCallId"), call["id"])
                and _same(message.get("toolName"), call["name"])
                and _contains(message, turn["modelCalls"][ordinal + 1]["messages"])
                and _contains(call["assistant"], turn["modelCalls"][ordinal + 1]["messages"])
                and _same(
                    call["assistant"]["content"],
                    [
                        {
                            "type": "toolCall",
                            "id": call["id"],
                            "name": call["name"],
                            "arguments": call["arguments"],
                        }
                    ],
                ),
                "The SDK actual dispatch and model-visible payload differ",
            )
        if _same(kind, "save"):
            require(
                _same(len(calls), 1)
                and _same(calls[0]["name"], "add_memory_entry")
                and _same(
                    calls[0]["arguments"],
                    {"section": instruction["section"], "text": instruction["text"]},
                )
                and _same(calls[0]["returned"].get("status"), "ok")
                and (outcome["memory_writes_committed"] is True),
                "The registered SDK producer did not actually commit",
            )
            prior = _source(instruction["content"])
            operation = next((row for row in raw["metadata"] if _same(row["label"], label)), None)
            instant = str(value["nowMs"] * 1000000)
            require(
                operation
                and _same(operation["operation"], "os.utime")
                and (operation["returnedNone"] is True)
                and _same(operation["arguments"], {"ns": [instant, instant]})
                and (
                    _same(operation["before"]["source"], operation["after"]["source"])
                    and _same(operation["after"]["source"], prior)
                )
                and _same(operation["after"]["stat"]["mtimeNs"], instant)
                and _same(operation["after"]["stat"]["nlink"], 1)
                and (int(operation["startedAtNs"]) <= int(operation["finishedAtNs"])),
                "The SDK metadata fixture changed bytes or timing inputs",
            )
            metadata_event = _event(raw["events"], "source-metadata", label, native=False)
            tool_result = _event(raw["events"], "tool-result", label, native=False)
            terminal_event = _event(raw["events"], "terminal-reply", label, native=False)
            require(
                _same(
                    operation["path"], str(Path(raw["fixtureBase"]) / "workspace" / value["source"])
                )
                and _same(operation["before"]["stat"]["ino"], operation["after"]["stat"]["ino"])
                and _same(operation["before"]["stat"]["dev"], operation["after"]["stat"]["dev"])
                and (
                    int(tool_result["atNs"])
                    < int(operation["startedAtNs"])
                    <= int(operation["finishedAtNs"])
                    <= int(metadata_event["atNs"])
                    < int(terminal_event["atNs"])
                    < int(returned["atNs"])
                ),
                "The SDK metadata fixture escaped its actual producer callback or workspace",
            )
        else:
            public = result["warmup"] if _same(label, "warmup-recall") else result["followup"]
            require(
                _same(calls[0]["name"], "memory_search")
                and _same(calls[0]["arguments"], instruction["search"])
                and _same(calls[0]["returned"], public["search"]),
                "SDK public search lost or repaired fields",
            )
            if public["search"]["results"]:
                first = public["search"]["results"][0]
                require(
                    _same(len(calls), 2)
                    and _same(calls[1]["name"], "memory_get")
                    and _same(
                        calls[1]["arguments"],
                        {
                            "path": first["path"],
                            "from": first["startLine"],
                            "lines": first["endLine"] - first["startLine"] + 1,
                        },
                    )
                    and _same(calls[1]["returned"], public["get"]),
                    "SDK source read did not follow its actual search",
                )
            else:
                require(
                    _same(len(calls), 1) and public["get"] is None,
                    "SDK invented a source read after an empty result",
                )
            require(_same(turn["reply"], public["reply"]), "The SDK delivered another public reply")
        require(
            _same(turn["sourceAfter"], prior)
            and _same(outcome["payloads"], [turn["reply"]])
            and _contains(turn["terminalMessage"], turn["terminalInput"]["messages"])
            and _same(turn["reply"]["text"], _text(turn["terminalMessage"])),
            "The SDK terminal reply or saved source was replaced",
        )
    require(
        raw["closedStatus"]["closed"] is True
        and _same(raw["closedStatus"]["activeTurns"], 0)
        and (
            _event(raw["events"], "close-call", None, native=False)["sequence"]
            > previous_return["sequence"]
        ),
        "The SDK close was used as a pre-read barrier",
    )


def validate_pair(case, native_raw, sdk_raw, native_result, sdk_result):
    """Validate each side's custody without repairing or comparing its output."""
    validate_result(case, native_result)
    validate_result(case, sdk_result)
    _native(case, native_raw, native_result)
    _sdk(case, sdk_raw, sdk_result)
    return True


def replay_case(case, directory):
    """Replay only actual retained outputs; this is not another execution."""
    directory = Path(directory)
    original = json.loads((directory / "stdout.json").read_text())["result"]
    sdk = json.loads((directory / "sdk-output.json").read_text())
    native_raw = json.loads((directory / "evidence/native-raw.json").read_text())
    sdk_raw = json.loads((directory / "evidence/python-raw.json").read_text())
    require(
        _same(len(native_raw), len(sdk_raw)) and _same(len(sdk_raw), 1),
        "The replay must use exactly one actual capture per engine",
    )
    require(
        validate_pair(case, native_raw[0], sdk_raw[0], original, sdk) is True,
        "The retained capture custody did not validate",
    )
    return {"validated": True, "nativeSnapshots": 1, "sdkSnapshots": 1}
