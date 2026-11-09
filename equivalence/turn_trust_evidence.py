"""Bind the mixed caller's public wire to complete original execution receipts."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re

from equivalence.get_contract import map_get_fixture_paths
from equivalence.search_contract import _same_json
from equivalence.turn_trust_runtime_bindings import (
    AGENT_LOOP_ARTIFACTS, TURN_TOOL_ARTIFACTS, PERSISTENCE_ARTIFACTS, READ_PROJECTION_ARTIFACTS,
)


def _finite(value):
    return type(value) in {int, float} and math.isfinite(value)


def validate_turn_trust_raw(row, case, diagnostic, evidence_directory, *, approved_source,
                            reference_source_imports, bootstrap, release_by_pid, local_by_pid,
                            process_parents, worker_imports):
    """Validate authority and data transfer, never replay taint or quarantine policy."""
    from equivalence.runtime_oracle import ROOT, RuntimeOracleError

    def require(condition, message):
        if not condition:
            raise RuntimeOracleError(message)

    def same(left, right, message):
        require(_same_json(left, right), message)

    def artifacts(records, files):
        require(isinstance(records, list), "Original artifact records must remain an ordered array")
        seen = set()
        for record in records:
            require(isinstance(record, dict) and set(record) == {"relativePath", "provenance"}
                    and record["relativePath"] in files and record["relativePath"] not in seen,
                    "An original artifact record lost its actual written file identity")
            seen.add(record["relativePath"])
            provenance = record["provenance"]
            require(isinstance(provenance, dict) and {"fileHash", "originClass", "observedAt"} <= provenance.keys()
                    and provenance["originClass"] in {"agent", "untrusted"} and _finite(provenance["observedAt"])
                    and provenance["fileHash"] == hashlib.sha256(files[record["relativePath"]].encode()).hexdigest(),
                    "Actual persisted artifact bytes, hash or complete provenance were changed")

    if row.get("ok") is not True:
        return
    try:
        require(isinstance(diagnostic, list) and len(diagnostic) == 1 and isinstance(diagnostic[0], dict),
                "Turn trust requires one complete original mixed-profile observation")
        raw, value = diagnostic[0], case["input"]
        require(set(raw) == {"fixtureBase", "kind", "pid", "config", "input", "sourceAuthority", "clock",
                            "taintCreations", "toolFactoryCalls", "toolInvocations", "nativeObservations", "innerWrites",
                            "modelCalls", "events", "persistence", "attempts", "reopen", "sessionScope", "sessionUpsert"},
                "The mixed caller lost or invented a complete raw observation channel")
        require(value.get("kind") == raw["kind"] == "turn-trust" and _finite(value.get("nowMs")),
                "The mixed caller's literal source profile or clock changed")
        same(raw["input"], value, "The mixed caller received different shared literal input")
        base = raw["fixtureBase"]
        require(isinstance(base, str) and Path(base).is_absolute() and Path(base).parent == evidence_directory
                and re.fullmatch(r"native-turn-trust-[A-Za-z0-9_-]+", Path(base).name),
                "Turn trust storage escaped its exact owned case directory")
        same(raw["sourceAuthority"], approved_source, "The source taint caller used another source authority")
        require(isinstance(approved_source, dict), "The mixed source owner has no explicit authority")
        pid = raw["pid"]
        require(type(pid) is int and pid > 0, "The original mixed caller PID is missing")
        same(reference_source_imports, [{key: approved_source[key] for key in
             ("path", "relativePath", "sha256", "referenceCommit")} | {"pid": pid, "threadId": 0}],
             "The actual sole source import must execute in this exact original caller process")
        same(raw["clock"], {"owner": "node:test", "apis": ["Date"], "nowMs": value["nowMs"],
             "dateConstructorReplaced": True, "setTimeoutUnchanged": True, "performanceNowUnchanged": True},
             "Turn trust may control only the original builtin Date clock")
        agent = value.get("agentId", "main")
        require(isinstance(agent, str) and agent not in {"", ".", ".."} and not re.search(r"[\\/]", agent),
                "The turn agent identity escaped its owned root")
        workspace = str(Path(base) / "workspace")
        scope = {"agentId": agent, "storePath": str(Path(base) / "state/agents" / agent / "sessions/sessions.json"),
                 "sessionKey": value["sessionKey"], "sessionId": value["sessionId"]}
        database_path = str(Path(base) / "state/agents" / agent / "agent/openclaw-agent.sqlite")
        same(raw["sessionScope"], scope, "The original session owner received another transcript identity")
        config = {"agents": {"defaults": {"workspace": workspace}, "list": [{"id": agent, "default": True}]},
                  "logging": {"level": "silent", "consoleLevel": "silent", "file": str(Path(base) / "native.log")},
                  "session": {"maintenance": {"mode": "warn"}}, "memory": {"search": {"enabled": False}},
                  "tools": {"profile": "coding", "loopDetection": {"enabled": False}, "fs": {"workspaceOnly": True}}}
        same(raw["config"], config, "The real coding tool owner received a different host configuration")
        same(raw["sessionUpsert"], {"request": {**scope, "entry": {"sessionId": value["sessionId"], "updatedAt": value["nowMs"]}},
                                   "returnedUndefined": True},
             "The original session upsert lost literal inputs or its actual undefined-return receipt")
        for name in ("taintCreations", "toolFactoryCalls", "toolInvocations", "nativeObservations", "innerWrites",
                     "modelCalls", "events", "persistence", "attempts"):
            require(isinstance(raw[name], list), "An actual mixed execution channel is not an ordered array")
        turns = value["turns"]
        require(isinstance(turns, list) and turns and len({turn["id"] for turn in turns}) == len(turns),
                "The shared turn identities must remain distinct and ordered")
        flattened = [(turn, attempt) for turn in turns for attempt in turn["attempts"]]
        require(len(flattened) == len(raw["attempts"]) == len(raw["toolFactoryCalls"])
                and len({(turn["id"], attempt["id"]) for turn, attempt in flattened}) == len(flattened),
                "Actual attempts or factory invocations were dropped, duplicated or rebound")
        same(raw["taintCreations"], [{"turnId": turn["id"], "initiallyTainted": False} for turn in turns],
             "Each logical turn requires one actual default-false source state, reused across attempts")
        definitions = [*value["tools"], {"name": "write_memory", "result": value["writeResult"]}]
        require(len({definition["name"] for definition in definitions}) == len(definitions),
                "The actual registry contains duplicate controlled tool identities")
        by_name = {definition["name"]: definition for definition in definitions}
        model = {"id": "fixture-trust-model", "name": "Fixture trust model", "api": "openai-completions", "provider": "openai",
                 "baseUrl": "https://fixture.invalid", "reasoning": False, "input": ["text"],
                 "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}, "contextWindow": 10000, "maxTokens": 1000}
        expected_tools = [{"name": definition["name"], "label": definition["name"], "description": "Literal fixture tool",
                           "parameters": {"type": "object", "properties": {}, "additionalProperties": True},
                           **({"resultContentSource": definition["resultContentSource"]} if definition.get("resultContentSource") else {})}
                          for definition in definitions]
        allowed_attempts = {(turn["id"], attempt["id"]) for turn, attempt in flattened}
        for name in ("toolFactoryCalls", "toolInvocations", "innerWrites", "modelCalls", "events", "persistence", "attempts"):
            require(all(isinstance(item, dict) and (item.get("turnId"), item.get("attemptId", item.get("id"))) in allowed_attempts
                        for item in raw[name]), "A raw call or event belongs to an undeclared logical turn/attempt")
        calls = [(turn["id"], attempt["id"], call) for turn, attempt in flattened for response in attempt["responses"]
                 for call in response["content"] if call.get("type") == "toolCall"]
        require(len(calls) == len(raw["toolInvocations"]), "A declared sequential tool invocation lost its original public execute receipt")
        for (turn_id, attempt_id, call), invoked in zip(calls, raw["toolInvocations"], strict=True):
            require(call["name"] in by_name and set(invoked) in (
                {"turnId", "attemptId", "toolCallId", "toolName", "arguments", "result", "identity"},
                {"turnId", "attemptId", "toolCallId", "toolName", "arguments", "error", "stack", "identity"}),
                "An original tool invocation lost its complete result/error or forwarding receipts")
            same({key: invoked[key] for key in ("turnId", "attemptId", "toolCallId", "toolName", "arguments")},
                 {"turnId": turn_id, "attemptId": attempt_id, "toolCallId": call["id"], "toolName": call["name"], "arguments": call["arguments"]},
                 "An actual wrapped execution changed the literal tool identity or arguments")
            is_error = "error" in invoked
            same(invoked["identity"], {"receiverIsOriginalWrapped": True, "argumentArrayForwardedUnchanged": True,
                 "errorRethrownUnchanged" if is_error else "resultReturnedUnchanged": True},
                 "The controlled host substituted the original wrapped receiver, arguments, return or thrown object")
            definition = by_name[call["name"]]
            if is_error:
                require(isinstance(invoked["stack"], str) and isinstance(invoked["error"], dict)
                        and {"name", "message"} <= invoked["error"].keys(), "An original thrown error lost its full diagnostic metadata")
                if "error" in definition:
                    require(all(_same_json(invoked["error"].get(key), item) for key, item in definition["error"].items()),
                            "The genuine wrapper lost a literal thrown error property")
            else:
                same(invoked["result"], definition["result"], "The original wrapped tool lost fields from its complete actual registered return")
        observations = raw["nativeObservations"]
        turn_ids = {turn["id"] for turn in turns}
        for observed in observations:
            require(observed.get("turnId") in turn_ids, "A source observation belongs to an undeclared turn")
            require(isinstance(observed, dict) and type(observed.get("before")) is bool and type(observed.get("after")) is bool,
                    "An actual source-state observation lost its before/after boolean receipts")
            if observed.get("origin") == "trusted-host-presentation":
                require(set(observed) == {"turnId", "observation", "origin", "before", "after"},
                        "A trusted host presentation falsely claimed dispatched execution identity")
            else:
                require(observed.get("origin") == "dispatched-tool" and set(observed) == {
                    "turnId", "attemptId", "toolCallId", "observation", "origin", "before", "after"},
                    "An actual dispatch outcome lost its exact origin and invocation identity")
                fact = observed["observation"]
                require(isinstance(fact, dict) and isinstance(fact.get("toolName"), str)
                        and isinstance(fact.get("argsHash"), str) and isinstance(fact.get("resultHash"), str),
                        "The complete native outcome and its diagnostic hashes were lost")
        expected_observation_order = []
        for turn in turns:
            expected_observation_order += [(turn["id"], "trusted-host-presentation", None, None)
                                           for _ in turn.get("presentationObservations", [])]
            expected_observation_order += [(turn_id, "dispatched-tool", attempt_id, call["id"])
                                           for turn_id, attempt_id, call in calls if turn_id == turn["id"]]
        require([(item["turnId"], item["origin"], item.get("attemptId"), item.get("toolCallId")) for item in observations]
                == expected_observation_order, "The original host/dispatch observation order was changed or repaired")
        dispatched = [observed for observed in observations if observed["origin"] == "dispatched-tool"]
        require(len(dispatched) == len(calls), "Original dispatched outcome callbacks were dropped or fabricated")
        for (turn_id, attempt_id, call), observed in zip(calls, dispatched, strict=True):
            require((observed["turnId"], observed["attemptId"], observed["toolCallId"], observed["observation"]["toolName"])
                    == (turn_id, attempt_id, call["id"], call["name"]),
                    "A source observation was attributed to another original wrapped invocation")
            fact = observed["observation"]
            require(re.fullmatch(re.escape(call["name"]) + r":[0-9a-f]{64}", fact["argsHash"])
                    and re.fullmatch(r"[0-9a-f]{64}", fact["resultHash"]),
                    "Actual dispatched diagnostic hashes were dropped or replaced")
            same({key: fact[key] for key in ("resultContentSource",) if key in fact},
                 {key: by_name[call["name"]][key] for key in ("resultContentSource",) if key in by_name[call["name"]]},
                 "The actual outcome callback lost its trusted registered result-source identity")
        expected_inner = [(turn_id, attempt_id, call) for turn_id, attempt_id, call in calls if call["name"] == "write_memory"]
        require(len(expected_inner) == len(raw["innerWrites"]), "A real native coding write or complete inner result was dropped")
        for expected, written in zip(expected_inner, raw["innerWrites"], strict=True):
            turn_id, attempt_id, call = expected
            require(set(written) == {"turnId", "attemptId", "toolCallId", "args", "taintedAtWrite", "result"}
                    and isinstance(written["result"], dict) and isinstance(written["result"].get("content"), list)
                    and type(written["taintedAtWrite"]) is bool,
                    "An actual native coding writer lost its complete return or live-state receipt")
            same({key: written[key] for key in ("turnId", "attemptId", "toolCallId", "args")},
                 {"turnId": turn_id, "attemptId": attempt_id, "toolCallId": call["id"], "args": call["arguments"]},
                 "The actual coding writer received another invocation or literal file mutation")
        expected_models = [(turn["id"], attempt["id"], index, response) for turn, attempt in flattened
                           for index, response in enumerate(attempt["responses"])]
        require(len(expected_models) == len(raw["modelCalls"]), "Actual model callbacks differ from the complete literal response script")
        for (turn_id, attempt_id, index, response), callback in zip(expected_models, raw["modelCalls"], strict=True):
            require(isinstance(response, dict) and response.get("role") == "assistant" and "__openclaw" not in response
                    and isinstance(response.get("turnId"), str) and bool(response["turnId"]),
                    "Scripted assistants cannot manufacture original taint stamps")
            same({key: callback[key] for key in ("turnId", "attemptId", "responseIndex", "response")},
                 {"turnId": turn_id, "attemptId": attempt_id, "responseIndex": index, "response": response},
                 "The actual AgentLoop received another model response or script position")
            same(callback["model"], model, "The original AgentLoop used a different scripted model identity")
            require(set(callback) == {"turnId", "attemptId", "responseIndex", "model", "context", "options", "response"}
                    and isinstance(callback["context"], dict) and set(callback["context"]) == {"systemPrompt", "messages", "tools"}
                    and callback["context"]["systemPrompt"] == "" and isinstance(callback["context"]["messages"], list),
                    "The original AgentLoop model callback lost its complete context")
            same(callback["context"]["tools"], expected_tools, "The actual model saw a substituted tool registry")
            same(callback["options"], {"model": model, "signal": {}, "asyncToolExecution": True},
                 "The original model callback lost its complete controlled execution options")
        actual_persisted = []
        expected_turns, known_files = [], {}
        attempt_index = 0
        for turn in turns:
            turn_observations = [item for item in observations if item["turnId"] == turn["id"]]
            host = [item for item in turn_observations if item["origin"] == "trusted-host-presentation"]
            same([item["observation"] for item in host], turn.get("presentationObservations", []),
                 "Trusted host presentation observations differ from their declared complete literal input")
            require(all(item["observation"].get("presentationOnly") is True for item in host),
                    "Trusted host observations cannot impersonate dispatched tool outcomes")
            state = False
            for item in host:
                require(item["before"] is state, "The genuine turn source state was replaced before a host presentation")
                state = item["after"]
            turn_attempts = []
            for turn_attempt_index, attempt in enumerate(turn["attempts"]):
                snapshot, factory = raw["attempts"][attempt_index], raw["toolFactoryCalls"][attempt_index]
                attempt_index += 1
                identity = {"turnId": turn["id"], "attemptId": attempt["id"]}
                options = {"config": config, "agentId": agent, "workspaceDir": workspace, "cwd": workspace,
                           "sessionId": value["sessionId"], "sessionKey": value["sessionKey"], "runId": f"{turn['id']}:{attempt['id']}",
                           **({"senderIsOwner": turn["senderIsOwner"]} if "senderIsOwner" in turn else {}),
                           "isTurnTainted": "actual-state.isTainted", "onToolOutcome": "actual-state.observe",
                           "requireWorkspaceOnly": True, "wrapBeforeToolCallHook": False,
                           "toolConstructionPlan": {"includeBaseCodingTools": True, "includeShellTools": False,
                               "includeChannelTools": False, "includeOpenClawTools": False, "includePluginTools": False}}
                same(factory, {**identity, "options": options, "callbackIdentity": {
                     "sameTurnTaintReader": True, "sameTurnOutcomeObserver": True}, "toolNames": factory["toolNames"],
                     "taintedAtConstruction": state}, "The original coding factory lost live callbacks, literal owner identity or retry state")
                require(isinstance(factory["toolNames"], list) and "write" in factory["toolNames"]
                        and len(set(factory["toolNames"])) == len(factory["toolNames"]),
                        "The actual native coding factory did not supply its genuine write tool")
                require(all(set(item) == {"turnId", "attemptId", "event"} for item in raw["events"]),
                        "An original emitted event lost its complete enclosing invocation identity")
                events = [item["event"] for item in raw["events"] if all(item.get(key) == fact for key, fact in identity.items())]
                require(events and events[0].get("type") == "agent_start" and events[-1].get("type") == "agent_end",
                        "The original AgentLoop lifecycle boundaries were omitted")
                messages = [event["message"] for event in events if event.get("type") == "message_end"]
                same(snapshot["messages"], messages, "Original emitted message_end values differ from complete returned attempt messages")
                same(events[-1].get("messages"), messages, "The actual agent_end receipt lost complete attempt messages")
                require(all(isinstance(event, dict) and event.get("type") in {
                    "agent_start", "turn_start", "message_start", "message_end", "tool_execution_start", "tool_execution_end", "turn_end", "agent_end"}
                    for event in events), "A literal done-only stream emitted an unreviewed lifecycle channel")
                same([event["message"] for event in events if event["type"] == "message_start"], messages,
                     "The complete original message lifecycle starts or ends were dropped")
                assistants = [message for message in messages if message.get("role") == "assistant"]
                require(len(assistants) == len(attempt["responses"])
                        and sum(event["type"] == "turn_start" for event in events) == len(assistants),
                        "An actual scripted assistant turn or lifecycle start was dropped")
                for assistant, response in zip(assistants, attempt["responses"], strict=True):
                    same({key: assistant[key] for key in response}, response,
                         "The original assistant stamp caller changed a literal response field")
                    require(set(assistant) <= set(response) | {"__openclaw"},
                            "The original assistant result introduced an undeclared generated identity")
                turn_ends = [event for event in events if event["type"] == "turn_end"]
                same([event["message"] for event in turn_ends], assistants,
                     "The original turn_end receipts lost complete assistant messages")
                if turn_attempt_index == 0:
                    require(messages and _same_json(messages[0], turn["prompt"]), "The actual original AgentLoop lost its literal new-turn user prompt")
                invocations = [item for item in raw["toolInvocations"] if all(item.get(key) == fact for key, fact in identity.items())]
                outcomes = [{"id": item["toolCallId"], "name": item["toolName"], "input": item["arguments"],
                             **({"result": item["result"]} if "result" in item else {"error": item["error"]})} for item in invocations]
                same(snapshot["toolOutcomes"], outcomes, "Attempt output dropped complete original wrapped returns or thrown error fields")
                starts = [event for event in events if event["type"] == "tool_execution_start"]
                ends = [event for event in events if event["type"] == "tool_execution_end"]
                same(starts, [{"type": "tool_execution_start", "toolCallId": item["toolCallId"],
                     "toolName": item["toolName"], "args": item["arguments"]} for item in invocations],
                     "Original tool execution starts changed literal dispatch arguments or identity")
                require(len(ends) == len(invocations), "An original tool execution-end receipt was dropped")
                tool_messages = [message for message in messages if message.get("role") == "toolResult"]
                same([message for event in turn_ends for message in event["toolResults"]], tool_messages,
                     "Original turn-end tool results differ from complete emitted messages")
                require(len(tool_messages) == len(invocations), "Original emitted tool-result messages were dropped")
                for invoked, ended, message in zip(invocations, ends, tool_messages, strict=True):
                    require(set(ended) == {"type", "toolCallId", "toolName", "result", "isError", "executionStarted"}
                            and ended["toolCallId"] == message.get("toolCallId") == invoked["toolCallId"]
                            and ended["toolName"] == message.get("toolName") == invoked["toolName"]
                            and ended["executionStarted"] is True and ended["isError"] is ("error" in invoked)
                            and message.get("isError") is ended["isError"],
                            "The original execution/result projection lost real invocation or error receipts")
                    if "result" in invoked:
                        same(ended["result"], invoked["result"], "The execution-end event dropped complete actual outer return fields")
                    require(isinstance(ended["result"], dict), "The real execution-end result lost its original carrier")
                    same({key: message.get(key) for key in ("content", "details")},
                         {key: ended["result"].get(key) for key in ("content", "details")},
                         "The actual emitted tool-result payload differs from its original execution carrier")
                attempt_observations = [item for item in dispatched if all(item.get(key) == fact for key, fact in identity.items())]
                for observed in attempt_observations:
                    require(observed["before"] is state, "The source state was reset or substituted during an actual attempt")
                    for written in raw["innerWrites"]:
                        if all(written.get(key) == observed.get(key) for key in ("turnId", "attemptId", "toolCallId")):
                            require(written["taintedAtWrite"] is state, "The actual coding write lost the source state's live pre-outcome value")
                    state = observed["after"]
                same(snapshot["trust"], {"tainted": state}, "An attempt reported a different actual sticky source state")
                for written in raw["innerWrites"]:
                    if all(written.get(key) == fact for key, fact in identity.items()):
                        relative = written["args"]["path"]
                        require(isinstance(relative, str) and not Path(relative).is_absolute()
                                and ".." not in relative.replace("\\", "/").split("/")
                                and isinstance(written["args"]["content"], str), "A native coding write escaped its literal owned file")
                        known_files[relative] = written["args"]["content"]
                same(snapshot["files"], known_files, "Actual file facts differ from completed original literal coding writes")
                artifacts(snapshot["artifacts"], known_files)
                require(set(snapshot) == {"turnId", "id", "messages", "toolOutcomes", "trust", "artifacts", "files"}
                        and snapshot["turnId"] == turn["id"] and snapshot["id"] == attempt["id"],
                        "The complete original attempt snapshot or ordered identity changed")
                turn_attempts.append({key: item for key, item in snapshot.items() if key != "turnId"})
                actual_persisted.extend((identity, message) for message in messages)
            expected_turns.append({"id": turn["id"], "attempts": turn_attempts, "trust": {"tainted": state}})
        require(len(actual_persisted) == len(raw["persistence"]), "A real emitted message lost its actual append accessor receipt")
        turn_message_indexes = {turn["id"]: 0 for turn in turns}
        for (identity, message), persisted in zip(actual_persisted, raw["persistence"], strict=True):
            index = turn_message_indexes[identity["turnId"]]
            turn_message_indexes[identity["turnId"]] += 1
            same({key: persisted[key] for key in ("turnId", "attemptId", "scope", "options")},
                 {**identity, "scope": scope, "options": {"message": message, "eventId": f"{identity['turnId']}:message:{index}",
                                                        "now": value["nowMs"], "cwd": "/fixture/workspace"}},
                 "An actual append received another emitted message, event identity, owner, cwd or clock")
            result = persisted["result"]
            require(set(persisted) == {"turnId", "attemptId", "scope", "options", "result"}
                    and isinstance(result, dict) and result.get("appended") is True
                    and isinstance(result.get("anchor"), dict) and "message" in result
                    and result.get("messageId") == persisted["options"]["eventId"],
                    "A real successful append lost its complete persisted result or original entry anchor")
            anchor = result["anchor"]
            require(all(_same_json(anchor.get(key), scope[key]) for key in ("agentId", "sessionId", "sessionKey"))
                    and anchor.get("storePath") == database_path and anchor.get("entryId") == result["messageId"]
                    and isinstance(anchor.get("generation"), str) and re.fullmatch(r"[0-9a-f]{32}", anchor["generation"]),
                    "The actual append anchor escaped its original database/session generation")
        reopened = raw["reopen"]
        require(isinstance(reopened, dict) and set(reopened) == {"pid", "request", "exit", "stdout", "stderr", "result"}
                and reopened["exit"] == {"code": 0, "signal": None}
                and isinstance(reopened["stdout"], str) and isinstance(reopened["stderr"], str),
                "The fresh reader lost its complete successful process output and exit")
        child = reopened["result"]
        same(json.loads(reopened["stdout"]), child, "Fresh reader raw observations differ from complete original stdout")
        child_pid = reopened["pid"]
        require(type(child_pid) is int and child_pid > 0 and child_pid != pid
                and child.get("pid") == child_pid and child.get("ppid") == pid
                and process_parents.get(child_pid) == pid,
                "Persisted verification must use its genuine distinct child OS process")
        require(set(child) == {"pid", "ppid", "request", "scope", "events", "currentEntry", "sourceEntry", "sourceCutoff",
                               "observations", "readRequest", "databasePath", "sessionSql", "artifacts"},
                "The fresh original reader omitted a complete SQL/source observation channel")
        request = reopened["request"]
        require(isinstance(request, dict) and set(request) == {"directory", "runtimeRoot", "input"}
                and isinstance(request["runtimeRoot"], str) and Path(request["runtimeRoot"]).is_absolute(),
                "The fresh reader received an invalid original runtime request")
        same({key: request[key] for key in ("directory", "input")}, {"directory": base, "input": {
             "nowMs": value["nowMs"], "agentId": agent, "sessionId": value["sessionId"], "sessionKey": value["sessionKey"]}},
             "A fresh reader received forwarded messages or another identity instead of reopening storage")
        same(child["request"], request, "The actual child process received another original request")
        same(child["scope"], scope, "The fresh original accessor reopened another session owner")
        same(child["readRequest"], {"absPath": value["sessionKey"], "options": {
             **scope, "sessionKind": "interactive", "updatedAtMs": value["nowMs"], "onTranscriptMessage": True}},
             "The original source projection lost its requested SQLite identity or actual observer")
        require(child["databasePath"] == database_path and isinstance(child["events"], list)
                and isinstance(child["observations"], list) and isinstance(child["currentEntry"], dict)
                and child["currentEntry"].get("sessionId") == value["sessionId"],
                "The reopened actual transcript/catalog/storage identity changed")
        stored = child["events"]
        actual_messages = [event for event in stored if isinstance(event, dict) and event.get("type") == "message"]
        require(len(actual_messages) == len(raw["persistence"]), "Reopened stored messages were dropped or fabricated")
        for event, persisted in zip(actual_messages, raw["persistence"], strict=True):
            require(event.get("id") == persisted["result"]["messageId"]
                    and _same_json(event.get("message"), persisted["result"]["message"]),
                    "The fresh persisted event differs from its actual original append result")
        source = child["sourceEntry"]
        require(source is None or isinstance(source, dict), "The actual reopened source result lost nullable entry semantics")
        if source is not None:
            require({"path", "absPath", "mtimeMs", "size", "hash", "content", "lineMap", "lineProvenance", "messageTimestampsMs", "sessionKind"} <= source.keys()
                    and source["absPath"] == value["sessionKey"] and isinstance(source["content"], str)
                    and re.fullmatch(r"[0-9a-f]{64}", source["hash"])
                    and all(isinstance(source[key], list) for key in ("lineMap", "lineProvenance", "messageTimestampsMs")),
                    "The actual source projection lost complete content/hash/range/provenance metadata")
            lines = source["content"].split("\n") if source["content"] else []
            require(all(len(source[key]) == len(lines) for key in ("lineMap", "lineProvenance", "messageTimestampsMs"))
                    and _finite(source["mtimeMs"]) and _finite(source["size"]),
                    "Actual source ranges and timestamps no longer align with complete exported content")
        require(isinstance(child["sourceCutoff"], dict), "The original symbol reset-cutoff reader was omitted")
        schemas = child["sessionSql"]
        require(isinstance(schemas, dict) and {"session_nodes", "session_windows", "transcript_events", "transcript_event_identities",
                "transcript_rewrite_watermarks", "session_transcript_active_events"} <= schemas.keys(),
                "The fresh reader omitted complete actual catalog/transcript SQL tables")
        for name, table in schemas.items():
            require(re.fullmatch(r"(?:session|transcript)_[A-Za-z0-9_]+", name)
                    and isinstance(table, dict) and set(table) == {"columns", "rows"}
                    and isinstance(table["columns"], list) and table["columns"] and isinstance(table["rows"], list),
                    "The fresh reader lost an original SQL table schema or complete rows")
            columns = [column["name"] for column in table["columns"]]
            require(len(set(columns)) == len(columns) and all(isinstance(column, str) for column in columns)
                    and all(isinstance(entry, dict) and set(entry) == set(columns) for entry in table["rows"]),
                    "Actual SQL rows no longer retain every original declared column")
        physical = schemas["transcript_events"]["rows"]
        identities = schemas["transcript_event_identities"]["rows"]
        require(len(physical) == len(stored) == len(identities)
                and all(entry.get("session_id") == value["sessionId"] for entry in [*physical, *identities]),
                "The actual persisted SQL transcript or event identities do not cover the reopened source")
        by_seq = {entry["seq"]: entry for entry in physical}
        by_event = {entry["event_id"]: entry for entry in identities}
        require(len(by_seq) == len(physical) and len(by_event) == len(identities),
                "The actual persisted SQL transcript contains duplicated physical identities")
        for index, event in enumerate(stored):
            require(index in by_seq and isinstance(event, dict) and event.get("id") in by_event,
                    "The actual source order has no complete persisted SQL identity")
            physical_row, identity_row = by_seq[index], by_event[event["id"]]
            require(identity_row["seq"] == index and identity_row["event_type"] == event.get("type"),
                    "The persisted source event lost its actual SQL sequence/type identity")
            if isinstance(physical_row.get("event_json"), str):
                same(json.loads(physical_row["event_json"]), event,
                     "The actual plaintext SQL payload differs from the complete original source read")
            else:
                payload = physical_row.get("event_zstd")
                require(isinstance(payload, dict) and set(payload) == {"type", "hex"} and payload["type"] == "bytes"
                        and isinstance(payload["hex"], str) and re.fullmatch(r"(?:[0-9a-f]{2})+", payload["hex"]),
                        "A compressed SQL payload lost its complete original physical bytes")
        same(child["artifacts"], raw["attempts"][-1]["artifacts"], "Fresh storage lost or changed the complete actual artifact provenance")
        artifacts(child["artifacts"], known_files)
        main_pids = {entry["pid"] for entry in bootstrap if entry["isMainThread"]}
        require({pid, child_pid} <= main_pids and {entry["pid"] for entry in bootstrap} <= main_pids,
                "Every actual process and thread requires its original inherited protection")
        for helper in main_pids - {pid, child_pid}:
            require(process_parents.get(helper) in {pid, child_pid}
                    and "dist/infra/sqlite-integrity.worker.js" in release_by_pid.get(helper, set())
                    and "dist/openclaw-agent-db-maintenance-DBuIm8El.mjs" in release_by_pid.get(process_parents.get(helper), set())
                    and not local_by_pid.get(helper), "An extra process has no genuine SQLite integrity owner and caller lineage")
        require(set(release_by_pid) <= main_pids and set(local_by_pid) <= main_pids,
                "A process without a protected main bootstrap supplied execution authority")
        require(set((*AGENT_LOOP_ARTIFACTS, *TURN_TOOL_ARTIFACTS, *PERSISTENCE_ARTIFACTS)) <= release_by_pid.get(pid, set()),
                "The exact original caller omitted its real AgentLoop/tool/write/append owners")
        require(set((*READ_PROJECTION_ARTIFACTS, "dist/memory-artifact-provenance-DhnyWiV1.mjs", "dist/plugin-state-store-BPUaLoVD.mjs"))
                <= release_by_pid.get(child_pid, set()), "The exact fresh reader omitted real persisted source/provenance owners")
        require({str(ROOT / "equivalence/release-oracle.mjs"), str(ROOT / "equivalence/turn-trust-runtime.mjs"),
                 str(ROOT / "equivalence/get-contract-runtime.mjs")} <= local_by_pid.get(pid, set())
                and str(ROOT / "equivalence/turn-trust-reopen-cli.mjs") in local_by_pid.get(child_pid, set()),
                "The actual mixed caller/fresh reader did not execute their authenticated adapters")
        require(all(item.get("pid") in main_pids and type(item.get("threadId")) is int and item["threadId"] > 0
                    for item in worker_imports), "A protected worker import has no genuine bootstrapped process")
        expected_public = {"provider": "none", "turns": expected_turns, "storedEvents": stored,
                           "sourceEntry": source, "artifacts": child["artifacts"], "files": known_files}
        same(row["result"], map_get_fixture_paths(expected_public, base),
             "Public turn-trust output differs from complete original tool/messages/persisted observations")
    except RuntimeOracleError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError) as error:
        raise RuntimeOracleError("The original mixed turn-trust evidence has an invalid complete shape") from error
