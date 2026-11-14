"""Global V5 SDK watcher RPC, source-version and interruption custody.

The enclosing guard authenticates actual processes, stdout, original API frames
and gates first. This module joins those independent records without producing
a memory operation, file version, completion or delivery witness.
"""
from __future__ import annotations

import os


HOLD_NS = 30_000_000_000


def _held_kill_interval(trigger, entered, returned, reaped, frontier):
    """Validate exact monotonic scalars; this alone is never capture proof."""
    from equivalence.forget_index_fence_evidence import _ns, require
    trigger, entered, returned, reaped, frontier = map(_ns, (trigger, entered, returned, reaped, frontier))
    require(trigger <= entered <= returned <= reaped <= frontier and returned < trigger + HOLD_NS,
            "SDK interruption was not killed and reaped inside the actual gate hold deadline")


def _no_interrupted_source_mutations(io, events, *, label):
    """Check authenticated source fragments; this alone proves no capture."""
    from equivalence.forget_index_fence_evidence import require

    def readonly_open(arguments):
        require(isinstance(arguments, list) and len(arguments) >= 2
                and type(arguments[1]) is int and arguments[1] >= 0,
                "SDK interrupted source open lost its exact original integer flags")
        flags = arguments[1]
        require(flags & os.O_ACCMODE == os.O_RDONLY and not flags & (os.O_TRUNC | os.O_CREAT),
                "SDK interrupted source retained a writable or filesystem-mutating open admission")

    mutations = {"write", "pwrite", "replace", "unlink", "ftruncate"}
    for row in io:
        require(row.get("syscall") not in mutations and row.get("event") != "original-full-write-return",
                "SDK interrupted source discarded a successful or uncertain source mutation")
        if row.get("syscall") == "open":
            readonly_open(row["arguments"])
    for event in events.values():
        if (event["event"] == "original-call" and event.get("name") == "_io"
                and event["callLabel"] == label and event["callKind"] == "forget"):
            arguments = event["arguments"]
            function = arguments["function"]
            require(function["qualname"] not in mutations,
                    "SDK interruption omitted a real source write attempt or rejected-publication uncertainty")
            if function["qualname"] == "open":
                require(function["module"] in {"posix", "os"},
                        "SDK interrupted source open borrowed another callable")
                # Entry is authoritative even when os.open raises or its
                # return has not been observed at the interruption cutoff.
                readonly_open(arguments["args"])


def _interrupted_source(case, stopped, *, raw, processes, observations, frontier):
    from equivalence.forget_index_fence_evidence import _ns, _same, _same_json, require

    require(isinstance(stopped, dict) and set(stopped) == {"kind", "callKey", "actor", "pid", "call",
            "sourceObservation", "markerGate", "sourceIOCutoff", "kill", "reap"}
            and stopped["kind"] == "original-interrupted-source-call", "SDK interrupted-source carrier changed")
    pid, key = stopped["pid"], stopped["callKey"]
    require(pid in processes and pid in observations, "SDK interrupted source borrowed an unknown process")
    process = processes[pid]
    final, events, returns = observations[pid]
    call = stopped["call"]
    require(stopped["actor"] == process["actor"] == final["actor"] == call["actor"]
            and call["pid"] == pid and call["kind"] == "forget" and key == "forget:" + call["label"]
            and "apiEntry" in call and "enterSeq" in call and "returnSeq" not in call
            and "watchTargetCapture" not in call and call.get("termination") == {"signal": "SIGKILL", "pid": pid},
            "SDK completed or foreign API call was relabelled interrupted")
    _same(raw["publicCalls"][key], call, "SDK interrupted call differs from the actual coordinator outcome")
    pending = {name: item for name, item in call.items() if name != "termination"}
    _same(final["publicCalls"][key], pending, "SDK interrupted call differs from the actual pending original frame")
    ref = stopped["sourceObservation"]
    require(set(ref) == {"pid", "commandId", "stdoutResponseIndex"} and ref["pid"] == pid
            and type(ref["stdoutResponseIndex"]) is int and ref["stdoutResponseIndex"] >= 0,
            "SDK interrupted source lost its actual observation selector")
    matching = [(index, response) for index, response in enumerate(process["stdoutResponses"])
                if key in response["observation"]["publicCalls"]]
    require(matching and matching[-1][0] == ref["stdoutResponseIndex"],
            "SDK interruption selected an older pending observation over its actual last response")
    response = matching[-1][1]
    require(response["ok"] is True and response["id"] == ref["commandId"],
            "SDK interrupted source borrowed another command response")
    _same(response["observation"], final, "SDK interruption omitted a later original process observation")
    _same(response["observation"]["publicCalls"][key], pending, "SDK interrupted source changed its actual observed call")
    command = process["stdinCommands"][ref["stdoutResponseIndex"]]
    require(command["id"] == ref["commandId"], "SDK interrupted-source response lost its real command request")
    api = events[call["apiEntry"]["sequence"]]
    require(api["event"] == "original-call" and api["name"] == "forget_memory_entries"
            and api["callLabel"] == call["label"] and api["callKind"] == "forget"
            and api["sequence"] not in returns and events[call["enterSeq"]]["event"] == "public-call-enter",
            "SDK interrupted source had already returned or never entered its original forget API")

    marker = stopped["markerGate"]
    name = marker["name"]
    gate = final["functionalGates"][name]
    _same(marker, {"name": name, **gate}, "SDK interruption fabricated its held original gate snapshot")
    literal = next((gate for gate in case["input"]["gates"] if gate["name"] == name), None)
    _same(gate["specification"], literal, "SDK interruption gate differs from frozen causal input")
    require(literal is not None and literal["boundary"] == "forget.marker-committed-before-purge"
            and literal["actor"] == process["actor"] and literal["callLabel"] == call["label"]
            and gate["armed"] is True and gate["reached"] is True and gate["released"] is False
            and len(gate["hits"]) == 1, "SDK interrupted source was not held before original source publication")
    trigger = events[gate["hits"][0]["triggerSequence"]]
    require(trigger["event"] == "original-call" and trigger["name"] == "purge_memory_index"
            and trigger["callLabel"] == call["label"] and trigger["threadId"] == api["threadId"]
            and trigger["sequence"] not in returns,
            "SDK interrupted-source marker was not an actual pending pre-purge original frame")
    marker_calls = [event for event in events.values() if event["event"] == "original-call"
                    and event.get("name") == "MemoryEntryOriginLedger.record_session_tombstones_if_lineage_current"
                    and event["callLabel"] == call["label"] and event["sequence"] in returns
                    and event["sequence"] < trigger["sequence"] and returns[event["sequence"]]["returned"] is True]
    require(marker_calls, "SDK interrupted source lacks its actual original committed tombstone return")

    kill = stopped["kill"]
    _same(kill, process["kill"], "SDK interruption changed its actual process kill receipt")
    require(kill["signal"] == "SIGKILL" and kill["pid"] == pid and kill["pollBefore"] is None
            and kill["returnValue"] is None and process["exit"] == {"code": -9},
            "SDK interruption did not retain the actual successful SIGKILL and OS exit")
    kill_enter, kill_return, reaped = _ns(kill["enteredAtNs"]), _ns(kill["returnedAtNs"]), _ns(process["reapedAtNs"])
    require(_ns(api["atNs"]) < _ns(trigger["atNs"]), "SDK marker trigger preceded original API admission")
    _held_kill_interval(trigger["atNs"], kill["enteredAtNs"], kill["returnedAtNs"], process["reapedAtNs"], frontier)
    _same(stopped["reap"], {"exit": process["exit"], "reapedAtNs": process["reapedAtNs"]},
          "SDK interruption fabricated a successful process reap")
    stops = [step for step in raw["steps"] if step["specification"]["operation"] == "stop-original-process"
             and step["specification"].get("actor") == process["actor"]
             and step["specification"].get("mode") == "SIGKILL" and _same_json(step["returned"], kill)]
    reaps = [step for step in raw["steps"] if step["specification"]["operation"] == "reap-original-process"
             and step["specification"].get("actor") == process["actor"] and _same_json(step["returned"], process["exit"])
             and _ns(step["enteredAtNs"]) <= reaped <= _ns(step["settledAtNs"])]
    require(len(stops) == len(reaps) == 1 and _ns(stops[0]["enteredAtNs"]) <= kill_enter
            <= kill_return <= _ns(stops[0]["settledAtNs"]) <= _ns(reaps[0]["enteredAtNs"]),
            "SDK interrupted source death was not the actual frozen stop/reap sequence")

    io = [row for row in final["sourceClockOriginalIO"] if (row.get("scope") or {}).get("kind") == call["kind"]
          and row["scope"].get("label") == call["label"]]
    clocks = [row for row in final["sourceClockReceipts"] if row.get("callKey") == key]
    _same(stopped["sourceIOCutoff"], {"originalIO": io, "sourceClockReceipts": clocks,
          "lastOriginalSequence": max((row["sequence"] for row in final["originalCalls"]), default=None),
          "lastSourceIOSequence": max((row["sequence"] for row in final["sourceClockOriginalIO"]), default=None)},
          "SDK interrupted source cut omitted or replaced actual recorded operations")
    require(not any(row.get("committed") for row in clocks),
            "SDK interrupted source discarded an actual committed filesystem version")
    _no_interrupted_source_mutations(io, events, label=call["label"])
    return True


def validate_sdk_watch_transport_v5(case, raw, processes, observations, watch_proofs):
    """Bind frozen host steps to genuine actor RPCs and side-local source facts."""
    from equivalence.forget_index_fence_evidence import _ns, _same, _same_json, require
    from equivalence.forget_index_fence_v5 import validate_case

    validate_case(case)
    _same(raw["input"], case["input"], "SDK watcher host used another frozen input")
    require(len(raw["steps"]) == len(case["input"]["steps"]), "SDK watch transport omitted frozen host steps")
    actual_calls = {}
    for pid, (observation, _, _) in observations.items():
        require(pid in processes and pid in watch_proofs, "SDK watch transport has an unauthenticated actor")
        proof = watch_proofs[pid]
        for key, call in observation["publicCalls"].items():
            require(key not in actual_calls and call["pid"] == pid,
                    "SDK watch source calls were duplicated across process epochs")
            actual_calls[key] = call
            if "returnSeq" in call:
                require(sum(_same_json(call["watchTargetCapture"], target) for target in proof["targets"]) == 1,
                        "SDK watch source target has no independently checked original completion capture")
                _same(raw["publicCalls"][key], call, "SDK host source call differs from its actual originating process")

    used, expected_commands = set(), set()
    for pid, process in processes.items():
        for command in process["stdinCommands"]:
            if command["operation"] in {"watch-ready", "watch-effects"}:
                expected_commands.add((pid, command["id"]))
    for step, literal in zip(raw["steps"], case["input"]["steps"], strict=True):
        _same(step["specification"], literal, "SDK watch transport reordered a frozen host step")
        operation = literal["operation"]
        if operation not in {"await-original-watch-ready", "await-original-watch-effects"}:
            continue
        begin, end = _ns(step["enteredAtNs"]), _ns(step["settledAtNs"])
        require(begin < end and step["status"] == "settled" and isinstance(step["returned"], list)
                and [row["actor"] for row in step["returned"]] == literal["actors"],
                "SDK watch step changed its actual actor frontier or complete results")
        completed, interrupted, targets = [], [], []
        for key in literal.get("afterCalls", []):
            require(key in actual_calls and key in raw["publicCalls"], "SDK watch frontier names an unobserved original source call")
            call = raw["publicCalls"][key]
            if "watchTargetCapture" in call:
                _same(call, actual_calls[key], "SDK watcher source capture belongs to another original call")
                require(_ns(call["watchTargetCapture"]["completedAtNs"]) <= begin,
                        "SDK watcher frontier preceded its source's actual completion-time capture")
                completed.append(call)
                targets.extend(call["watchTargetCapture"]["versions"])
            else:
                require(call.get("termination") == {"signal": "SIGKILL", "pid": call["pid"]},
                        "SDK absent target capture was silently treated as source absence")
                interrupted.append(call)
        current = {}
        for process in raw["processes"]:
            if _ns(process["startedAtNs"]) < begin:
                current[process["actor"]] = process
        for row in step["returned"]:
            require(row["label"] == literal["label"] and "lifecycle" in row,
                    "SDK watcher result borrowed another frozen control label")
            lifecycle = row["lifecycle"]
            require(lifecycle["actor"] == row["actor"] and type(lifecycle["processPresent"]) is bool
                    and type(lifecycle["acquired"]) is bool,
                    "SDK watcher receiver lifecycle carrier was coerced")
            process = current.get(row["actor"])
            if operation == "await-original-watch-effects":
                _same(row["sourceCalls"], completed, "SDK watcher replaced complete side-local originating public calls")
                _same(row["versions"], targets, "SDK watcher frontier recaptured or superseded an actual retained version")
                entries = row["interruptedSourceCalls"]
                require([entry["callKey"] for entry in entries] == ["forget:" + call["label"] for call in interrupted],
                        "SDK watcher omitted or injected an interrupted original source call")
                for entry in entries:
                    _interrupted_source(case, entry, raw=raw, processes=processes, observations=observations,
                                        frontier=step["enteredAtNs"])
            if process is None:
                require(lifecycle["processPresent"] is False and lifecycle["pid"] is None and lifecycle["poll"] is None
                        and lifecycle["acquired"] is False and lifecycle["ownerClosedFromOriginalReceipt"] is None
                        and "commandId" not in lifecycle
                        and row["outcome"] == {"status": "absent", "reason": "actor-never-started"},
                        "SDK watcher absence invented a process or positive delivery")
                continue
            pid = process["pid"]
            require(lifecycle["processPresent"] is True and lifecycle["pid"] == pid,
                    "SDK watcher step selected another actual process epoch")
            if "commandId" not in lifecycle:
                require(row["outcome"]["status"] == "absent", "SDK undispatched watcher control supplied positive proof")
                observation, events, returns = observations[pid]
                if lifecycle["poll"] is not None:
                    require(process["exit"]["code"] == lifecycle["poll"] and _ns(process["reapedAtNs"]) <= begin
                            and row["outcome"]["reason"] == "original-process-exited",
                            "SDK watcher absence used a future or unreaped process exit")
                elif lifecycle["ownerClosedFromOriginalReceipt"] is True:
                    closed = [event for event in events.values() if event["event"] == "original-call"
                              and event.get("name") == "ManagedSQLiteMemoryStore.close" and event["sequence"] in returns
                              and _ns(returns[event["sequence"]]["atNs"]) <= begin]
                    require(closed and row["outcome"]["reason"] == "original-owner-closed",
                            "SDK watcher absence guessed an original owner close")
                else:
                    require(lifecycle["acquired"] is False and row["outcome"]["reason"] == "original-owner-not-acquired",
                            "SDK watcher absence hid an active acquired owner")
                    require(not any(event["event"] == "original-call" and event.get("name") in {
                                    "MemoryFileWatcher.__init__", "MemoryFileWatcher.start", "ManagedSQLiteMemoryStore.search"}
                                    and _ns(event["atNs"]) < begin for event in events.values()),
                            "SDK unacquired-owner absence omitted an actual earlier managed lifecycle")
                continue
            command_id = lifecycle["commandId"]
            require(type(command_id) is int and (pid, command_id) not in used
                    and lifecycle["poll"] is None and lifecycle["acquired"] is True
                    and lifecycle["ownerClosedFromOriginalReceipt"] is False,
                    "SDK watcher RPC targeted a dead, closed or unacquired owner")
            matches = [(command, response) for command, response in zip(process["stdinCommands"], process["stdoutResponses"], strict=True)
                       if command["id"] == command_id and response["id"] == command_id]
            require(len(matches) == 1 and matches[0][1]["ok"] is True,
                    "SDK watch step lacks its unique actual command/stdout pair")
            command, response = matches[0]
            expected_operation = "watch-ready" if operation == "await-original-watch-ready" else "watch-effects"
            require(command["operation"] == expected_operation and command["label"] == literal["label"],
                    "SDK watch transport invoked a different original control")
            before = process["stdinCommands"][:command_id - 1]
            require(any(previous["operation"] == "acquire" for previous in before),
                    "SDK watch RPC acquired a missing owner instead of inspecting an existing one")
            if operation == "await-original-watch-effects":
                _same(command["versions"], targets, "SDK watcher RPC refreshed its actual retained source versions")
                _same(command["sourceCalls"], completed, "SDK watcher RPC changed its source call custody")
                _same(command["interruptedSourceCalls"], row["interruptedSourceCalls"],
                      "SDK watcher RPC altered its typed interrupted source proof")
            actor_row = {key: item for key, item in row.items() if key != "lifecycle"}
            _same(response["result"], actor_row, "SDK host watcher result differs from actual child stdout")
            proof = watch_proofs[pid]["waits"][literal["label"]]
            _same(proof, actor_row, "SDK watcher host step lost its independently checked actor proof")
            _, events, _ = observations[pid]
            require(begin <= _ns(events[proof["enterSeq"]]["atNs"])
                    < _ns(events[proof["returnSeq"]]["atNs"]) <= end,
                    "SDK watcher control escaped its actual frozen host step lifetime")
            used.add((pid, command_id))
    require(used == expected_commands, "SDK watcher commands were omitted or injected outside the frozen schedule")
    return True
