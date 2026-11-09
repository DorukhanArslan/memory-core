"""Non-executing protocol fixtures test transport guards, never taint policy."""
from copy import deepcopy
import hashlib
import json

import pytest

from equivalence.get_contract import map_get_fixture_paths
from equivalence.runtime_oracle import ROOT, RuntimeOracleError
from equivalence.turn_trust_evidence import validate_turn_trust_raw
from equivalence.turn_trust_runtime_bindings import (
    AGENT_LOOP_ARTIFACTS, TURN_TOOL_ARTIFACTS, PERSISTENCE_ARTIFACTS, READ_PROJECTION_ARTIFACTS,
)

_NOW = 1794268800000


def _fixture(tmp_path):
    base = str(tmp_path / "native-turn-trust-fixture")
    workspace = base + "/workspace"
    scope = {"agentId": "main", "storePath": base + "/state/agents/main/sessions/sessions.json",
             "sessionKey": "agent:main:dm:trust", "sessionId": "trust"}
    db = base + "/state/agents/main/agent/openclaw-agent.sqlite"
    model = {"id": "fixture-trust-model", "name": "Fixture trust model", "api": "openai-completions", "provider": "openai",
             "baseUrl": "https://fixture.invalid", "reasoning": False, "input": ["text"],
             "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}, "contextWindow": 10000, "maxTokens": 1000}
    network = {"content": [{"type": "text", "text": "A"}], "details": {"source": "fixture"}, "outerOnly": [True, None]}
    write_result = {"content": [{"type": "text", "text": "Written"}], "details": {"changed": True}, "outerOnly": {"kept": 1}}

    def assistant(content, identifier, reason):
        return {"role": "assistant", "content": content, "api": model["api"], "provider": model["provider"],
                "model": model["id"], "stopReason": reason, "timestamp": _NOW, "turnId": identifier}

    first = assistant([{"type": "toolCall", "id": "fetch", "name": "web", "arguments": {"q": "A"}}], "response-1", "toolUse")
    second = assistant([{"type": "toolCall", "id": "write", "name": "write_memory", "arguments": {"path": "memory/test.md", "content": "A"}}], "response-2", "toolUse")
    final = assistant([{"type": "text", "text": "Done"}], "response-3", "stop")
    prompt = {"role": "user", "content": [{"type": "text", "text": "Save A"}], "timestamp": _NOW}
    host = {"toolName": "host_presentation", "argsHash": "", "resultHash": "", "resultContentSource": "network",
            "presentationOnly": True, "terminalPresentation": "Fixture host update"}
    value = {"kind": "turn-trust", "nowMs": _NOW, "agentId": "main", "sessionId": "trust", "sessionKey": scope["sessionKey"],
             "tools": [{"name": "web", "resultContentSource": "network", "result": network}], "writeResult": write_result,
             "turns": [{"id": "turn", "senderIsOwner": True, "prompt": prompt, "presentationObservations": [host],
                        "attempts": [{"id": "a", "responses": [first]}, {"id": "b", "responses": [second, final]}]}]}
    cfg = {"agents": {"defaults": {"workspace": workspace}, "list": [{"id": "main", "default": True}]},
           "logging": {"level": "silent", "consoleLevel": "silent", "file": base + "/native.log"},
           "session": {"maintenance": {"mode": "warn"}}, "memory": {"search": {"enabled": False}},
           "tools": {"profile": "coding", "loopDetection": {"enabled": False}, "fs": {"workspaceOnly": True}}}
    source = {"path": "/approved/original/turn-taint-state.ts", "relativePath": "src/agents/embedded-agent-runner/run/turn-taint-state.ts",
              "sha256": "a" * 64, "referenceCommit": "b" * 40}
    raw = {"fixtureBase": base, "kind": "turn-trust", "pid": 101, "input": deepcopy(value), "config": cfg,
           "sourceAuthority": deepcopy(source), "clock": {"owner": "node:test", "apis": ["Date"], "nowMs": _NOW,
               "dateConstructorReplaced": True, "setTimeoutUnchanged": True, "performanceNowUnchanged": True},
           "sessionScope": scope, "sessionUpsert": {"request": {**scope, "entry": {"sessionId": "trust", "updatedAt": _NOW}}, "returnedUndefined": True},
           "taintCreations": [{"turnId": "turn", "initiallyTainted": False}], "toolFactoryCalls": [], "toolInvocations": [],
           "nativeObservations": [{"turnId": "turn", "origin": "trusted-host-presentation", "observation": host, "before": False, "after": False}],
           "innerWrites": [], "modelCalls": [], "events": [], "persistence": [], "attempts": [], "reopen": None}
    definitions = [*value["tools"], {"name": "write_memory", "result": write_result}]
    tools = [{"name": d["name"], "label": d["name"], "description": "Literal fixture tool",
              "parameters": {"type": "object", "properties": {}, "additionalProperties": True},
              **({"resultContentSource": d["resultContentSource"]} if "resultContentSource" in d else {})} for d in definitions]
    tool_messages = [{"role": "toolResult", "toolCallId": "fetch", "toolName": "web", "content": network["content"],
                      "details": network["details"], "isError": False, "timestamp": _NOW, "__openclaw": {"resultContentSource": "network"}},
                     {"role": "toolResult", "toolCallId": "write", "toolName": "write_memory", "content": write_result["content"],
                      "details": write_result["details"], "isError": False, "timestamp": _NOW}]
    second_stamped, final_stamped = deepcopy(second), deepcopy(final)
    second_stamped["__openclaw"] = {"turnTainted": True}
    final_stamped["__openclaw"] = {"turnTainted": True}
    messages_by_attempt = [[prompt, first, tool_messages[0]], [second_stamped, tool_messages[1], final_stamped]]
    artifact = {"relativePath": "memory/test.md", "provenance": {"fileHash": hashlib.sha256(b"A").hexdigest(),
                "originClass": "untrusted", "observedAt": _NOW, "sessionId": "trust", "sessionKey": scope["sessionKey"]}}
    all_messages = []
    for index, attempt in enumerate(value["turns"][0]["attempts"]):
        identity = {"turnId": "turn", "attemptId": attempt["id"]}
        options = {"config": cfg, "agentId": "main", "workspaceDir": workspace, "cwd": workspace, "sessionId": "trust",
                   "sessionKey": scope["sessionKey"], "runId": "turn:" + attempt["id"], "senderIsOwner": True,
                   "isTurnTainted": "actual-state.isTainted", "onToolOutcome": "actual-state.observe", "requireWorkspaceOnly": True,
                   "wrapBeforeToolCallHook": False, "toolConstructionPlan": {"includeBaseCodingTools": True,
                      "includeShellTools": False, "includeChannelTools": False, "includeOpenClawTools": False, "includePluginTools": False}}
        raw["toolFactoryCalls"].append({**identity, "options": deepcopy(options), "callbackIdentity": {
             "sameTurnTaintReader": True, "sameTurnOutcomeObserver": True}, "toolNames": ["write"], "taintedAtConstruction": index == 1})
        literal_call = attempt["responses"][0]["content"][0]
        outcome = {"id": literal_call["id"], "name": literal_call["name"], "input": literal_call["arguments"],
                   "result": network if index == 0 else write_result}
        raw["toolInvocations"].append({**identity, "toolCallId": outcome["id"], "toolName": outcome["name"],
             "arguments": deepcopy(outcome["input"]), "result": deepcopy(outcome["result"]), "identity": {
                 "receiverIsOriginalWrapped": True, "argumentArrayForwardedUnchanged": True, "resultReturnedUnchanged": True}})
        raw["nativeObservations"].append({**identity, "toolCallId": outcome["id"], "origin": "dispatched-tool",
             "observation": {"toolName": outcome["name"], "argsHash": outcome["name"] + ":" + "c" * 64,
                             "resultHash": "d" * 64, **({"resultContentSource": "network"} if index == 0 else {})},
             "before": index == 1, "after": True})
        messages = deepcopy(messages_by_attempt[index])
        snapshot = {"turnId": "turn", "id": attempt["id"], "messages": messages, "toolOutcomes": [deepcopy(outcome)],
                    "trust": {"tainted": True}, "artifacts": [] if index == 0 else [deepcopy(artifact)],
                    "files": {} if index == 0 else {"memory/test.md": "A"}}
        raw["attempts"].append(snapshot)
        lifecycle = [{"type": "agent_start"}]
        for response_index, literal in enumerate(attempt["responses"]):
            lifecycle.append({"type": "turn_start"})
            if index == 0:
                lifecycle += [{"type": "message_start", "message": prompt}, {"type": "message_end", "message": prompt}]
            actual = messages[1 if index == 0 else (0 if response_index == 0 else 2)]
            lifecycle += [{"type": "message_start", "message": actual}, {"type": "message_end", "message": actual}]
            results = []
            if response_index == 0:
                lifecycle += [{"type": "tool_execution_start", "toolCallId": outcome["id"], "toolName": outcome["name"], "args": outcome["input"]},
                              {"type": "tool_execution_end", "toolCallId": outcome["id"], "toolName": outcome["name"], "result": outcome["result"],
                               "isError": False, "executionStarted": True},
                              {"type": "message_start", "message": tool_messages[index]}, {"type": "message_end", "message": tool_messages[index]}]
                results = [tool_messages[index]]
            lifecycle.append({"type": "turn_end", "message": actual, "toolResults": results})
            raw["modelCalls"].append({**identity, "responseIndex": response_index, "model": deepcopy(model),
                 "context": {"systemPrompt": "", "messages": deepcopy(all_messages), "tools": deepcopy(tools)},
                 "options": {"model": deepcopy(model), "signal": {}, "asyncToolExecution": True}, "response": deepcopy(literal)})
        lifecycle.append({"type": "agent_end", "messages": messages})
        raw["events"] += [{**identity, "event": deepcopy(event)} for event in lifecycle]
        all_messages += messages
    raw["innerWrites"] = [{"turnId": "turn", "attemptId": "b", "toolCallId": "write", "args": deepcopy(second["content"][0]["arguments"]),
                           "taintedAtWrite": True, "result": {"content": [{"type": "text", "text": "Original coding result"}], "details": {"changed": True}}}]
    stored = [{"type": "session", "id": "trust", "version": 4, "timestamp": "2026-11-10T00:00:00.000Z", "cwd": "/fixture/workspace"}]
    for index, event in enumerate(item for item in raw["events"] if item["event"]["type"] == "message_end"):
        message = deepcopy(event["event"]["message"])
        event_id = f"turn:message:{index}"
        options = {"message": message, "eventId": event_id, "now": _NOW, "cwd": "/fixture/workspace"}
        result = {"appended": True, "messageId": event_id, "message": message,
                  "anchor": {"agentId": "main", "sessionId": "trust", "sessionKey": scope["sessionKey"], "storePath": db,
                             "entryId": event_id, "generation": "e" * 32, "rawSeq": index + 1}}
        raw["persistence"].append({"turnId": event["turnId"], "attemptId": event["attemptId"], "scope": deepcopy(scope), "options": options, "result": result})
        stored.append({"type": "message", "id": event_id, "message": deepcopy(message)})
    tables = {name: {"columns": [{"name": "id"}], "rows": []} for name in (
        "session_nodes", "session_windows", "transcript_rewrite_watermarks", "session_transcript_active_events")}
    tables["transcript_events"] = {"columns": [{"name": name} for name in ("session_id", "seq", "event_json")],
                                  "rows": [{"session_id": "trust", "seq": index, "event_json": json.dumps(event)} for index, event in enumerate(stored)]}
    tables["transcript_event_identities"] = {"columns": [{"name": name} for name in ("session_id", "seq", "event_id", "event_type")],
                                           "rows": [{"session_id": "trust", "seq": index, "event_id": event["id"], "event_type": event["type"]}
                                                    for index, event in enumerate(stored)]}
    entry = {"path": "sessions/main/trust.jsonl", "absPath": scope["sessionKey"], "mtimeMs": _NOW, "size": 100,
             "hash": "f" * 64, "content": "User: A", "lineMap": [1], "messageTimestampsMs": [_NOW], "lineProvenance": [{}], "sessionKind": "interactive"}
    request = {"directory": base, "runtimeRoot": "/approved/runtime/node_modules/openclaw", "input": {
               "nowMs": _NOW, "agentId": "main", "sessionId": "trust", "sessionKey": scope["sessionKey"]}}
    child = {"pid": 102, "ppid": 101, "request": deepcopy(request), "scope": deepcopy(scope), "events": stored,
             "currentEntry": {"sessionId": "trust"}, "sourceEntry": entry, "sourceCutoff": {"state": "absent"},
             "observations": [{"message": prompt, "timestampMs": _NOW}], "databasePath": db, "sessionSql": tables,
             "readRequest": {"absPath": scope["sessionKey"], "options": {**scope, "sessionKind": "interactive", "updatedAtMs": _NOW, "onTranscriptMessage": True}},
             "artifacts": [deepcopy(artifact)]}
    raw["reopen"] = {"pid": 102, "request": request, "exit": {"code": 0, "signal": None}, "stdout": json.dumps(child), "stderr": "", "result": child}
    public = {"provider": "none", "turns": [{"id": "turn", "attempts": [{key: item for key, item in a.items() if key != "turnId"} for a in raw["attempts"]],
               "trust": {"tainted": True}}], "storedEvents": stored, "sourceEntry": entry, "artifacts": child["artifacts"], "files": {"memory/test.md": "A"}}
    kwargs = {"approved_source": source, "reference_source_imports": [{**source, "pid": 101, "threadId": 0}],
              "bootstrap": [{"pid": 101, "isMainThread": True}, {"pid": 102, "isMainThread": True}],
              "release_by_pid": {101: set((*AGENT_LOOP_ARTIFACTS, *TURN_TOOL_ARTIFACTS, *PERSISTENCE_ARTIFACTS)),
                                 102: set((*READ_PROJECTION_ARTIFACTS, "dist/memory-artifact-provenance-DhnyWiV1.mjs", "dist/plugin-state-store-BPUaLoVD.mjs"))},
              "local_by_pid": {101: {str(ROOT / "equivalence" / name) for name in ("release-oracle.mjs", "turn-trust-runtime.mjs", "get-contract-runtime.mjs")},
                               102: {str(ROOT / "equivalence/turn-trust-reopen-cli.mjs")}}, "process_parents": {101: 99, 102: 101}, "worker_imports": []}
    return {"ok": True, "result": deepcopy(map_get_fixture_paths(public, base))}, {"input": deepcopy(value)}, [raw], tmp_path, kwargs


def _validate(fixture):
    row, case, raw, directory, kwargs = fixture
    validate_turn_trust_raw(row, case, raw, directory, **kwargs)


def _recapture_child(fixture):
    record = fixture[2][0]["reopen"]
    record["stdout"] = json.dumps(record["result"])


def test_complete_labelled_mixed_caller_protocol_is_accepted(tmp_path):
    _validate(_fixture(tmp_path))


@pytest.mark.parametrize("mutation", [
    lambda f: f[0]["result"]["turns"][0]["attempts"][0]["toolOutcomes"][0]["result"].pop("outerOnly"),
    lambda f: f[2][0]["toolInvocations"][0]["result"].pop("outerOnly"),
    lambda f: f[2][0]["toolInvocations"].clear(),
    lambda f: f[2][0]["toolInvocations"][0]["identity"].update(receiverIsOriginalWrapped=False),
    lambda f: f[2][0]["toolInvocations"][0]["identity"].update(argumentArrayForwardedUnchanged=False),
    lambda f: f[2][0]["toolInvocations"][0]["identity"].update(resultReturnedUnchanged=False),
    lambda f: f[2][0]["toolInvocations"][0]["arguments"].update(q="other"),
    lambda f: f[2][0]["toolFactoryCalls"][1]["callbackIdentity"].update(sameTurnTaintReader=False),
    lambda f: f[2][0]["toolFactoryCalls"][1]["options"].update(senderIsOwner=False),
    lambda f: f[2][0]["toolFactoryCalls"][1].update(taintedAtConstruction=False),
    lambda f: f[2][0]["nativeObservations"][1].pop("origin"),
    lambda f: f[2][0]["nativeObservations"][1].update(toolCallId="other"),
    lambda f: f[2][0]["nativeObservations"][1]["observation"].pop("resultContentSource"),
    lambda f: f[2][0]["nativeObservations"][1]["observation"].update(resultHash="fabricated"),
    lambda f: f[2][0]["nativeObservations"][0].update(turnId="undeclared"),
    lambda f: f[2][0]["nativeObservations"].reverse(),
    lambda f: f[2][0]["taintCreations"].append({"turnId": "turn", "initiallyTainted": False}),
    lambda f: f[2][0]["innerWrites"][0].update(taintedAtWrite=False),
    lambda f: f[2][0]["innerWrites"][0]["args"].update(content="different bytes"),
    lambda f: f[2][0]["attempts"][1]["files"].update({"memory/test.md": "changed"}),
    lambda f: f[2][0]["modelCalls"][0]["response"].update(__openclaw={"turnTainted": True}),
    lambda f: f[2][0]["modelCalls"][0]["context"]["tools"].pop(),
    lambda f: f[2][0]["modelCalls"][0]["options"].update(asyncToolExecution=False),
    lambda f: f[2][0]["sessionUpsert"].update(returnedUndefined=False),
    lambda f: f[2][0]["persistence"][0]["options"].update(cwd="/different/workspace"),
    lambda f: f[2][0]["persistence"][0]["result"]["anchor"].update(storePath="/unowned/database"),
    lambda f: f[2][0]["clock"].update(performanceNowUnchanged=False),
    lambda f: f[2][0].update(fixtureBase="/tmp/native-turn-trust-unowned"),
    lambda f: f[4]["reference_source_imports"][0].update(pid=102),
    lambda f: f[4]["reference_source_imports"][0].update(threadId=1),
    lambda f: f[4]["reference_source_imports"].append(deepcopy(f[4]["reference_source_imports"][0])),
    lambda f: f[4]["release_by_pid"][101].difference_update(AGENT_LOOP_ARTIFACTS),
    lambda f: f[4]["release_by_pid"][101].difference_update(TURN_TOOL_ARTIFACTS),
    lambda f: f[4]["release_by_pid"][102].difference_update(READ_PROJECTION_ARTIFACTS),
    lambda f: f[4]["local_by_pid"][102].clear(),
    lambda f: f[4]["process_parents"].update({102: 999}),
    lambda f: f[4]["bootstrap"].pop(),
])
def test_original_caller_receipts_and_complete_public_wire_cannot_be_repaired(tmp_path, mutation):
    fixture = _fixture(tmp_path)
    mutation(fixture)
    with pytest.raises(RuntimeOracleError):
        _validate(fixture)


@pytest.mark.parametrize("mutation", [
    lambda child: child["request"]["input"].update(messages=[]),
    lambda child: child["readRequest"]["options"].update(onTranscriptMessage=False),
    lambda child: child.update(databasePath="/unowned/database.sqlite"),
    lambda child: child.pop("sourceCutoff"),
    lambda child: child["sessionSql"].pop("session_nodes"),
    lambda child: child["sessionSql"]["transcript_events"]["rows"].clear(),
    lambda child: child["sessionSql"]["transcript_events"]["rows"][0].update(event_json='{"id":"fabricated"}'),
    lambda child: child["sessionSql"]["transcript_event_identities"]["rows"][1].update(seq=55),
    lambda child: child["events"][1]["message"].update(content=[{"type": "text", "text": "forged"}]),
    lambda child: child["artifacts"][0]["provenance"].update(fileHash="0" * 64),
])
def test_fresh_process_stdout_and_sql_source_links_cannot_be_rewritten_together(tmp_path, mutation):
    fixture = _fixture(tmp_path)
    mutation(fixture[2][0]["reopen"]["result"])
    _recapture_child(fixture)
    with pytest.raises(RuntimeOracleError):
        _validate(fixture)


def test_actual_emitted_execution_end_channel_cannot_be_dropped(tmp_path):
    fixture = _fixture(tmp_path)
    raw = fixture[2][0]
    raw["events"] = [item for item in raw["events"] if item["event"]["type"] != "tool_execution_end"]
    with pytest.raises(RuntimeOracleError, match="execution-end"):
        _validate(fixture)


def test_original_throw_shape_preserves_properties_and_object_forwarding(tmp_path):
    fixture = _fixture(tmp_path)
    row, case, rows, _, _ = fixture
    raw = rows[0]
    error = {"name": "Error", "message": "Declared remote error", "code": "FIXTURE_REMOTE", "nested": {"kept": [True, None]}}
    for value in (case["input"], raw["input"]):
        value["tools"][0].pop("result")
        value["tools"][0]["error"] = deepcopy(error)
    invoked = raw["toolInvocations"][0]
    invoked.pop("result")
    invoked.update(error=deepcopy(error), stack="Error: Declared remote error\n fixture-owner")
    invoked["identity"].pop("resultReturnedUnchanged")
    invoked["identity"]["errorRethrownUnchanged"] = True
    carrier = {"content": [{"type": "text", "text": error["message"]}], "details": {}}
    message = next(item for item in raw["attempts"][0]["messages"] if item.get("role") == "toolResult")
    message.update(**deepcopy(carrier), isError=True)
    for item in raw["events"]:
        event = item["event"]
        if event.get("toolCallId") == "fetch" and event["type"] == "tool_execution_end":
            event.update(result=deepcopy(carrier), isError=True)
        if event["type"] in {"message_start", "message_end"} and event["message"].get("toolCallId") == "fetch":
            event["message"] = deepcopy(message)
        if event["type"] == "turn_end" and event["toolResults"]:
            if event["toolResults"][0].get("toolCallId") == "fetch":
                event["toolResults"] = [deepcopy(message)]
        if event["type"] == "agent_end" and item["attemptId"] == "a":
            event["messages"] = deepcopy(raw["attempts"][0]["messages"])
    outcome = raw["attempts"][0]["toolOutcomes"][0]
    outcome.pop("result")
    outcome["error"] = deepcopy(error)
    for item in raw["persistence"]:
        if item["options"]["message"].get("toolCallId") == "fetch":
            item["options"]["message"] = deepcopy(message)
            item["result"]["message"] = deepcopy(message)
    child = raw["reopen"]["result"]
    for index, event in enumerate(child["events"]):
        if event.get("message", {}).get("toolCallId") == "fetch":
            event["message"] = deepcopy(message)
            child["sessionSql"]["transcript_events"]["rows"][index]["event_json"] = json.dumps(event)
    _recapture_child(fixture)
    public = {"provider": "none", "turns": [{"id": "turn", "attempts": [{key: value for key, value in snapshot.items() if key != "turnId"}
               for snapshot in raw["attempts"]], "trust": {"tainted": True}}], "storedEvents": child["events"], "sourceEntry": child["sourceEntry"],
              "artifacts": child["artifacts"], "files": raw["attempts"][-1]["files"]}
    row["result"] = map_get_fixture_paths(public, raw["fixtureBase"])
    _validate(fixture)
    row["result"]["turns"][0]["attempts"][0]["toolOutcomes"][0]["error"].pop("nested")
    with pytest.raises(RuntimeOracleError, match="Public turn-trust"):
        _validate(fixture)


def test_unknown_native_public_metadata_must_stay_in_the_comparison(tmp_path):
    fixture = _fixture(tmp_path)
    fixture[0]["result"]["sourceEntry"]["unknownOriginalField"] = {"kept": 1}
    with pytest.raises(RuntimeOracleError, match="Public turn-trust"):
        _validate(fixture)


def test_genuine_incidental_integrity_child_requires_actual_parent_and_launcher(tmp_path):
    fixture = _fixture(tmp_path)
    kwargs = fixture[-1]
    kwargs["bootstrap"].append({"pid": 103, "isMainThread": True})
    kwargs["process_parents"][103] = 102
    kwargs["release_by_pid"][103] = {"dist/infra/sqlite-integrity.worker.js"}
    kwargs["release_by_pid"][102].add("dist/openclaw-agent-db-maintenance-DBuIm8El.mjs")
    _validate(fixture)
    kwargs["process_parents"][103] = 999
    with pytest.raises(RuntimeOracleError, match="integrity owner"):
        _validate(fixture)
