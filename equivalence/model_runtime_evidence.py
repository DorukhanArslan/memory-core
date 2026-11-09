"""Bind complete published helper/session values to fresh processes and SQL."""
from __future__ import annotations

import hashlib
import json
from functools import wraps
from pathlib import Path
import re

from equivalence.model_runtime_authority import validate_model_node_authority
from equivalence.model_runtime_bindings import (
    REQUIRED_HELPER_ARTIFACTS, REQUIRED_SESSION_READ_ARTIFACTS, REQUIRED_SESSION_WRITE_ARTIFACTS,
)
from equivalence.search_contract import _same_json


ENVIRONMENT_KEYS = ["LANG", "MEMORY_EQ_RELEASE_CONTEXT", "NODE_OPTIONS", "PATH", "TZ"]
IDENTITY_KEYS = ("nowMs", "agentId", "sessionId", "sessionKey")
POLICY_KEYS = ("systemPrompt", "model", "patterns", "registeredSecrets")
SQL_TABLES = {"session_nodes", "session_windows", "transcript_events", "transcript_event_identities",
              "transcript_rewrite_watermarks", "session_transcript_active_events"}


def _guard(function):
    @wraps(function)
    def checked(*args, **kwargs):
        from equivalence.runtime_oracle import RuntimeOracleError

        try:
            return function(*args, **kwargs)
        except (KeyError, IndexError, TypeError, ValueError, OSError) as error:
            if isinstance(error, RuntimeOracleError):
                raise
            raise RuntimeOracleError("The model boundary returned malformed original execution evidence") from None
    return checked


def _require(condition, message):
    if not condition:
        from equivalence.runtime_oracle import RuntimeOracleError

        raise RuntimeOracleError(message)


def _same(left, right, message):
    _require(_same_json(left, right), message)


def _registry(snapshot):
    _require(isinstance(snapshot, dict) and set(snapshot) == {"revision", "values"}
             and type(snapshot["revision"]) is int and snapshot["revision"] >= 0
             and isinstance(snapshot["values"], list)
             and all(isinstance(value, str) for value in snapshot["values"])
             and len(set(snapshot["values"])) == len(snapshot["values"]),
             "An actual secret registry snapshot lost its unchanged revision or exact surface forms")


def _registry_journal(journal, expected):
    _require(isinstance(journal, list) and len(journal) == len(expected),
             "Every real registry observation and literal registration must remain retained")
    revision = -1
    for entry, (stage, secret) in zip(journal, expected, strict=True):
        _require(isinstance(entry, dict) and set(entry) == ({"stage", "snapshot"} if secret is None else {"stage", "secret", "snapshot"})
                 and entry["stage"] == stage and entry.get("secret") == secret,
                 "A registry observation changed its actual stage or literal registration")
        _registry(entry["snapshot"])
        _require(entry["snapshot"]["revision"] >= revision, "A process registry revision was reset or offset")
        revision = entry["snapshot"]["revision"]
    _same(journal[0]["snapshot"], {"revision": 0, "values": []}, "Every model case and phase must start with a genuinely empty process registry")


def _markers(markers, message):
    content = message.get("content") if isinstance(message, dict) else None
    content = content if isinstance(content, list) else []
    _require(isinstance(markers, list) and len(markers) == len(content), "The complete actual prepared-marker vector was omitted")
    for index, (marker, block) in enumerate(zip(markers, content, strict=True)):
        text = isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
        _require(isinstance(marker, dict) and set(marker) == ({"index", "type", "prepared", "text"} if text else {"index", "type"})
                 and marker["index"] == index and marker["type"] == (block.get("type") if isinstance(block, dict) else None)
                 and (not text or type(marker["prepared"]) is bool and marker["text"] == block["text"]),
                 "A real marker observation dropped a block, text, identity result or ordering")


def _policy(policy, logging, registry=None):
    _require(isinstance(policy, dict) and set(policy) == {"patterns", "fullContext", "registryRevision"}
             and policy["fullContext"] is False and type(policy["registryRevision"]) is int and policy["registryRevision"] >= 0,
             "Compiled profiles cannot manufacture the private source-only full-context mark")
    _same(policy["patterns"], logging.get("redactPatterns", []), "The actual prepared policy changed its literal configured patterns")
    if registry is not None:
        _registry(registry)
        _require(policy["registryRevision"] == registry["revision"], "Prepared policy and actual registry revisions disagree")


def _sql(schemas, events, session_id):
    _require(isinstance(schemas, dict) and SQL_TABLES <= schemas.keys(), "The original catalog/transcript SQL tables were dropped")
    for name, table in schemas.items():
        _require(isinstance(name, str) and re.fullmatch(r"(?:session|transcript)_[A-Za-z0-9_]+", name)
                 and isinstance(table, dict) and set(table) == {"columns", "rows"}
                 and isinstance(table["columns"], list) and table["columns"] and isinstance(table["rows"], list),
                 "A SQL table lost its actual original schema or complete rows")
        columns = [column["name"] for column in table["columns"]]
        _require(all(isinstance(column, str) for column in columns) and len(columns) == len(set(columns))
                 and all(isinstance(row, dict) and set(row) == set(columns) for row in table["rows"]),
                 "A persisted row omitted an original physical SQL column")
    physical, identities = schemas["transcript_events"]["rows"], schemas["transcript_event_identities"]["rows"]
    _require(isinstance(events, list) and len(physical) == len(events) == len(identities)
             and all(row.get("session_id") == session_id for row in [*physical, *identities]),
             "Physical transcript/event identity rows no longer cover the complete original read")
    by_seq = {row["seq"]: row for row in physical}
    by_id = {row["event_id"]: row for row in identities}
    _require(len(by_seq) == len(physical) and len(by_id) == len(identities), "Physical SQL identities were duplicated")
    for seq, event in enumerate(events):
        _require(isinstance(event, dict) and seq in by_seq and event.get("id") in by_id
                 and by_id[event["id"]]["seq"] == seq and by_id[event["id"]]["event_type"] == event.get("type"),
                 "A raw transcript event lost its true SQL sequence or event identity")
        stored = by_seq[seq]
        if isinstance(stored.get("event_json"), str):
            _same(json.loads(stored["event_json"]), event, "Original plaintext SQL and actual transcript read disagree")
        else:
            payload = stored.get("event_zstd")
            _require(isinstance(payload, dict) and set(payload) == {"type", "hex"} and payload["type"] == "bytes"
                     and isinstance(payload["hex"], str) and re.fullmatch(r"(?:[0-9a-f]{2})+", payload["hex"]),
                     "A compressed transcript SQL payload lost its complete physical bytes")


def _transport(row, case, diagnostic, evidence_directory, *, kind, prefix, runtime_root, bootstrap,
               release_by_pid, local_by_pid, process_parents):
    from equivalence.runtime_oracle import ROOT

    _require(row.get("ok") is True and isinstance(diagnostic, list) and len(diagnostic) == 1,
             "A model boundary must retain its complete successful original execution")
    raw = diagnostic[0]
    _require(isinstance(raw, dict) and set(raw) == {"kind", "fixtureBase", "coordinatorPid", "input", "runtime", "phases" if kind == "model-session" else "child"}
             and raw["kind"] == kind, "The model coordinator lost an original evidence channel")
    _same(raw["input"], case["input"], "The model coordinator changed the literal fixture input")
    base, coordinator = raw["fixtureBase"], raw["coordinatorPid"]
    _require(isinstance(base, str) and Path(base).is_absolute() and Path(base).parent == evidence_directory
             and re.fullmatch(prefix + r"[A-Za-z0-9_-]+", Path(base).name), "Model storage escaped this exact owned case")
    runtime = validate_model_node_authority(raw["runtime"])
    records = raw["phases"] if kind == "model-session" else [raw["child"]]
    _require(isinstance(records, list) and len(records) == (3 if kind == "model-session" else 1),
             "The model case lost a fresh OS process")
    pids = [coordinator, *(record.get("pid") for record in records)]
    _require(all(type(pid) is int and pid > 0 for pid in pids) and len(set(pids)) == len(pids),
             "Model phases must execute in distinct real processes")
    main_pids = {entry["pid"] for entry in bootstrap if entry.get("isMainThread") is True}
    _require(set(pids) <= main_pids and all(process_parents.get(pid) == coordinator for pid in pids[1:]),
             "A fresh model child bypassed the protected parent/preload lineage")
    for entry in bootstrap:
        _same(entry.get("runtime"), runtime, "A model process or worker used an unauthenticated Node/ICU/Unicode executable")
    for helper in main_pids - set(pids):
        _require(process_parents.get(helper) in pids[1:] and "dist/infra/sqlite-integrity.worker.js" in release_by_pid.get(helper, set())
                 and "dist/openclaw-agent-db-maintenance-DBuIm8El.mjs" in release_by_pid.get(process_parents.get(helper), set())
                 and not local_by_pid.get(helper), "An extra process has no actual SQLite integrity owner and caller lineage")
    adapter = "model-session-runtime.mjs" if kind == "model-session" else "model-tool-result-runtime.mjs"
    _require({str(ROOT / "equivalence/release-oracle.mjs"), str(ROOT / "equivalence" / adapter),
              str(ROOT / "equivalence/model-runtime-observation.mjs")} <= local_by_pid.get(coordinator, set()),
             "The protected model coordinator or exact observation utility did not execute")
    return raw, records, base, runtime


def _child(record, request, *, runtime, cli, phase_module, coordinator, local_by_pid, previous_finish=-1):
    from equivalence.runtime_oracle import ROOT

    expected_keys = {"pid", "request", "requestJson", "requestSha256", "argv", "environmentKeys", "startedAtNs",
                     "exit", "finishedAtNs", "stdout", "stderr", "raw"}
    if "label" in record:
        expected_keys.add("label")
    _require(set(record) == expected_keys and record["exit"] == {"code": 0, "signal": None},
             "A model child lost its successful real exit or original transport")
    _same(record["request"], request, "A fresh model child received another script, secret, identity or prior history")
    _require(isinstance(record["requestJson"], str)
             and hashlib.sha256(record["requestJson"].encode()).hexdigest() == record["requestSha256"],
             "A model child request lost its exact bytes/hash")
    _same(json.loads(record["requestJson"]), request, "The actual model child request bytes differ from the literal fixture")
    _same(record["argv"], [runtime["execPath"], str(ROOT / "equivalence" / cli)], "A model child executed a different script or binary")
    _same(record["environmentKeys"], ENVIRONMENT_KEYS, "A model child inherited ambient credentials, test flags or extra capabilities")
    start, finish = record["startedAtNs"], record["finishedAtNs"]
    _require(isinstance(start, str) and start.isdigit() and isinstance(finish, str) and finish.isdigit()
             and previous_finish <= int(start) < int(finish), "A model child continued before the previous OS process exited")
    _require(isinstance(record["stdout"], str) and isinstance(record["stderr"], str), "A child output stream was dropped")
    output = json.loads(record["stdout"])
    _require(isinstance(output, dict) and set(output) == {"result", "raw"}, "The complete original model child output changed")
    _same(output["raw"], record["raw"], "A model raw record differs from its original complete stdout")
    observed = record["raw"]
    _require(observed.get("pid") == record["pid"] and observed.get("ppid") == coordinator,
             "A model observation forged another child or parent process")
    _same(observed.get("request"), request, "A model child observed different actual inputs")
    _same(observed.get("runtime"), runtime, "A model phase used another executable or Unicode engine")
    _require({str(ROOT / "equivalence" / cli), str(ROOT / "equivalence" / phase_module),
              str(ROOT / "equivalence/model-runtime-observation.mjs")} <= local_by_pid.get(record["pid"], set()),
             "A model child did not execute its protected actual phase and observation utility")
    return output, int(finish)


@_guard
def validate_model_tool_result_raw(row, case, diagnostic, evidence_directory, *, runtime_root, bootstrap,
                                   release_by_pid, local_by_pid, process_parents, worker_imports):
    del worker_imports
    value = case["input"]
    _require(value.get("kind") == "model-helper", "A helper cannot claim the whole AgentSession profile")
    raw, records, base, runtime = _transport(row, case, diagnostic, evidence_directory, kind="model-helper",
        prefix="native-model-helper-", runtime_root=runtime_root, bootstrap=bootstrap, release_by_pid=release_by_pid,
        local_by_pid=local_by_pid, process_parents=process_parents)
    record = records[0]
    request = {"input": value, "directory": base, "runtimeRoot": runtime_root}
    output, _ = _child(record, request, runtime=runtime, cli="model-tool-result-cli.mjs", phase_module="model-tool-result-phase.mjs",
                        coordinator=raw["coordinatorPid"], local_by_pid=local_by_pid)
    observed = record["raw"]
    _require(set(observed) == {"pid", "ppid", "request", "runtime", "config", "registry", "stages", "result", "identity",
                              *({"storageRequest"} if "block" in value else set())},
             "A helper raw observation lost a complete original channel")
    _require(set(REQUIRED_HELPER_ARTIFACTS) <= release_by_pid.get(record["pid"], set()), "A whole-result helper omitted its actual cache/redaction/storage/config owner")
    logging = {"level": "silent", "consoleLevel": "silent", "file": str(Path(base) / "native.log"),
               **({"redactPatterns": value["patterns"]} if "patterns" in value else {})}
    _same(observed["config"], {"logging": logging}, "The helper changed its actual literal logging configuration")
    expected_registry = [("initial", None), *[("literal-registration", item) for item in value.get("registeredSecrets", [])],
                         *[("later-registration", item) for item in value.get("laterRegisteredSecrets", [])], ("final", None)]
    _registry_journal(observed["registry"], expected_registry)
    expected_identity = set()
    expected_result = set()
    stages = observed["stages"]
    _require(isinstance(stages, list), "Actual whole-helper stages were dropped")
    position = 0
    if "value" in value:
        expected_identity |= {"sanitizedOutputReuse", "originalInputReuse"}
        expected_result |= {"sanitized", "arguments"}
        stage = stages[position]
        position += 1
        _require(stage["stage"] == "whole-sanitize", "The original whole-sanitizer stage disappeared")
        _same(stage["input"], value["value"], "The whole sanitizer received a different literal result")
        _same(stage["output"], observed["result"]["sanitized"], "The complete sanitized result was changed or truncated")
        _same(stage["arguments"], observed["result"]["arguments"], "The complete original sanitized arguments were changed")
        _same(stage["identity"], {key: observed["identity"][key] for key in ("sanitizedOutputReuse", "originalInputReuse")},
              "The real sanitizer/cache identity observations were dropped or changed")
        _policy(stage["policy"], logging)
    if "block" in value:
        expected_identity |= {"preparedBlockReuse", "storageMessageReuse", "storageBlockPrepared"}
        expected_result |= {"prepared", "stored"}
        stage, stored = stages[position:position + 2]
        position += 2
        _require(stage["stage"] == "prepared-block" and stored["stage"] == "storage-return", "The actual prepared/storage stages changed order")
        _same(stage["input"], value["block"], "The original preparer received another literal block")
        _markers(stage["markers"], {"content": [stage["output"]]})
        _policy(stage["policy"], logging)
        _same(stage["identity"], {"preparedBlockReuse": observed["identity"]["preparedBlockReuse"]}, "Prepared block reuse was replaced")
        storage = observed["storageRequest"]
        _same(storage["config"], {"logging": logging}, "The original storage helper received another policy")
        _same({key: item for key, item in storage["message"].items() if key != "content"}, value["message"], "The actual storage message metadata changed")
        block = dict(stage["output"])
        if "replacePreparedText" in value:
            block["text"] = value["replacePreparedText"]
        _same(storage["message"]["content"], [block], "The actual prepared block mutation was repaired or skipped")
        _same(observed["result"]["prepared"], block, "The full original mutable prepared value was dropped")
        _markers(storage["markers"], storage["message"])
        _policy(storage["policy"], logging)
        _same(stored["output"], observed["result"]["stored"], "The complete real storage helper result was changed")
        _markers(stored["markers"], stored["output"])
        _policy(stored["policy"], logging)
        _same(stored["identity"], {key: observed["identity"][key] for key in ("storageMessageReuse", "storageBlockPrepared")}, "Actual storage identity observations changed")
    _require(len(stages) == position and set(observed["result"]) == expected_result and set(observed["identity"]) == expected_identity
             and all(type(item) is bool for item in observed["identity"].values()), "A whole-helper result or identity field was omitted or invented")
    _same(output["result"], {"provider": "none", "result": observed["result"], "identity": observed["identity"]}, "Public helper output differs from complete original values/identity observations")
    _same(row["result"], output["result"], "The parent replaced an original helper result")


@_guard
def validate_model_session_raw(row, case, diagnostic, evidence_directory, *, runtime_root, bootstrap,
                               release_by_pid, local_by_pid, process_parents, worker_imports):
    del worker_imports
    value = case["input"]
    _require(value.get("kind") == "model-session" and value.get("agentId") == "main"
             and [phase.get("label") for phase in value.get("phases", [])] == ["write", "continue", "verify"]
             and value["phases"][2] == {"label": "verify"}, "The compiled model session requires three fixed phases")
    raw, records, base, runtime = _transport(row, case, diagnostic, evidence_directory, kind="model-session",
        prefix="native-model-session-", runtime_root=runtime_root, bootstrap=bootstrap, release_by_pid=release_by_pid,
        local_by_pid=local_by_pid, process_parents=process_parents)
    previous_finish, previous_events, saved_config, results = -1, None, None, []
    for record, phase in zip(records, value["phases"], strict=True):
        label = phase["label"]
        phase_input = {key: value[key] for key in IDENTITY_KEYS}
        if label != "verify":
            phase_input.update({key: value[key] for key in POLICY_KEYS if key in value})
        request = {"input": phase_input, "phase": phase, "directory": base, "runtimeRoot": runtime_root}
        _require(record.get("label") == label, "The actual model phase order changed")
        output, previous_finish = _child(record, request, runtime=runtime, cli="model-session-phase-cli.mjs",
            phase_module="model-session-phase.mjs", coordinator=raw["coordinatorPid"], local_by_pid=local_by_pid,
            previous_finish=previous_finish)
        observed, pid = record["raw"], record["pid"]
        keys = {"phase", "pid", "ppid", "request", "runtime", "configBytes", "config", "clock", "registry", "stages",
                "events", "contexts", "executions", "persisted", "applicationWrites", "scope", "before", "databasePath",
                "sessionSqlBefore", "entries", "after", "currentEntry", "sessionSqlAfter", "context", "modelMessages"}
        if label != "verify":
            keys |= {"guardRequest", "providerRegistration", "createRequest", "prompt", "responsesConsumed", "activeToolNames"}
            if "directGuardMessage" in phase:
                keys.add("directGuardRequest")
            if "modeProbe" in phase:
                keys.add("explicitOffDiagnostic")
        _require(set(observed) == keys, "A full model phase raw channel was dropped or replaced")
        _require(observed.get("phase") == label and set(REQUIRED_SESSION_READ_ARTIFACTS) <= release_by_pid.get(pid, set()),
                 "A fresh model phase omitted its actual persisted-read/context/SQLite owner")
        _same(observed["clock"], {"owner": "node:test", "apis": ["Date"], "nowMs": value["nowMs"],
            "dateConstructorReplaced": True, "setTimeoutUnchanged": True, "performanceNowUnchanged": True},
            "Model phases may control only the original builtin Date clock")
        _require(isinstance(observed["configBytes"], str), "The original persisted host config bytes disappeared")
        _same(json.loads(observed["configBytes"]), observed["config"], "The model phase changed the persisted host configuration")
        if saved_config is None:
            saved_config = observed["configBytes"]
        _require(observed["configBytes"] == saved_config, "A reopened model phase received a replaced host policy")
        expected_logging = {"level": "silent", "consoleLevel": "silent", "file": str(Path(base) / "native.log"),
                            **({"redactPatterns": value["patterns"]} if "patterns" in value else {})}
        expected_cfg = {"agents": {"defaults": {"workspace": str(Path(base) / "workspace")}}, "logging": expected_logging,
                        "session": {"maintenance": {"mode": "warn"}}}
        _same(observed["config"], expected_cfg, "The actual host config weakened the declared source/tool policy")
        scope = {"agentId": "main", "sessionId": value["sessionId"], "sessionKey": value["sessionKey"],
                 "storePath": str(Path(base) / "state/agents/main/sessions/sessions.json")}
        _same(observed["scope"], scope, "The actual persisted session owner identity changed")
        _require(observed["databasePath"] == str(Path(base) / "state/agents/main/agent/openclaw-agent.sqlite"),
                 "The model phase read another physical database")
        if previous_events is not None:
            _same(observed["before"], previous_events, "A fresh process was seeded with fake history or lost persisted messages")
        _sql(observed["sessionSqlBefore"], observed["before"], value["sessionId"])
        _sql(observed["sessionSqlAfter"], observed["after"], value["sessionId"])
        previous_events = observed["after"]
        writes = observed["applicationWrites"]
        _require(isinstance(writes, list) and len(writes) == (1 if label == "write" else 0), "A reopened phase performed extra application catalog writes")
        if writes:
            _same(writes[0], {"target": scope, "entry": {"sessionId": value["sessionId"], "updatedAt": value["nowMs"]},
                              "returnedUndefined": True}, "The original public catalog upsert arguments or void result changed")
        journal = [("initial", None)]
        if label != "verify":
            _require(set(REQUIRED_SESSION_WRITE_ARTIFACTS) <= release_by_pid.get(pid, set()), "An executing phase omitted its real AgentSession/preparer/guardcap/append owner")
            journal.extend(("literal-registration", item) for item in value.get("registeredSecrets", []))
            journal.append(("provider-fixture-auth", None))
            journal.extend(("live-event-registration", phase["lateRegisteredSecret"]) for event in observed["events"]
                           if event.get("type") == "message_end" and event.get("message", {}).get("role") == "toolResult" and phase.get("lateRegisteredSecret"))
            _same(observed["guardRequest"], {"config": expected_cfg, "onMessagePersisted": True}, "The genuine guard callback or persistence policy was bypassed")
            workspace = str(Path(base) / "workspace")
            _same(observed["createRequest"], {"cwd": workspace, "agentDir": workspace, "model": value["model"],
                  "settingsInput": {"compaction": {"enabled": False}, "retry": {"enabled": False}},
                  "loaderInput": {"cwd": workspace, "agentDir": workspace, "noExtensions": True, "noSkills": True,
                    "noPromptTemplates": True, "noThemes": True, "noContextFiles": True, "systemPrompt": value["systemPrompt"]},
                  "noTools": "builtin", "customTools": [{"name": "lookup", "label": "Lookup", "description": "Return a declared synthetic fixture result.",
                    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}}]},
                  "The actual AgentSession/model/resource/tool setup changed its literal caller contract")
            if "directGuardMessage" in phase:
                _same(observed["directGuardRequest"], phase["directGuardMessage"], "The genuine direct guard received a different literal message")
            _require(observed["activeToolNames"] == ["lookup"], "The real registered toolset changed or bypassed its original session")
            _require(observed["prompt"] == phase["prompt"] and observed["responsesConsumed"] == len(phase["responses"]),
                     "The original AgentSession did not consume the complete literal script")
            _same(observed["providerRegistration"], {"provider": value["model"]["provider"], "api": value["model"]["api"], "streamSimple": True}, "The actual provider registry was replaced or bypassed")
            _require(isinstance(observed["contexts"], list) and len(observed["contexts"]) == len(phase["responses"]), "A complete real provider context was dropped")
            for context in observed["contexts"]:
                _same(context["model"], value["model"], "The actual registry served a different literal model")
            tool_calls = [block for response in phase["responses"] for block in response.get("content", []) if block.get("type") == "toolCall"]
            _require(len(observed["executions"]) == len(tool_calls), "A genuine registered tool execution was omitted")
            for execution, call in zip(observed["executions"], tool_calls, strict=True):
                _require(execution["callId"] == call["id"], "A tool observation belongs to another actual call")
                _same(execution["arguments"], call["arguments"], "The real registered tool received different arguments")
                _same(execution["result"], phase["toolResult"], "The actual tool returned a different complete literal payload")
                _require(set(execution["identities"]) == {"preparedOutputReuse", "originalInputReuse"}
                         and all(type(item) is bool for item in execution["identities"].values()), "Actual cache identity diagnostics were dropped")
        else:
            _require(not observed["contexts"] and not observed["executions"] and not observed["events"]
                     and not observed["persisted"] and not observed["stages"], "A fresh verifier executed a supplied script, tool or append")
            _same(observed["before"], observed["after"], "The third phase changed the persisted transcript")
            _require(not {"guardRequest", "createRequest", "providerRegistration", "prompt", "responsesConsumed"} & observed.keys(),
                     "An identity-only verifier constructed an executing AgentSession")
        journal.append(("final", None))
        _registry_journal(observed["registry"], journal)
        for stage in observed["stages"]:
            _require(isinstance(stage, dict) and set(stage) == {"stage", "message", "policy", "registry", "markers"}
                     and isinstance(stage["stage"], str), "A complete actual prepare/live/persist stage was dropped")
            _policy(stage["policy"], expected_logging, stage["registry"])
            _markers(stage["markers"], stage["message"])
        _same([stage["message"] for stage in observed["stages"] if stage["stage"] == "persisted-callback"], observed["persisted"], "The actual persistence callbacks lost complete messages or marker receipts")
        _same([{ "stage": stage["stage"], "message": stage["message"] } for stage in observed["stages"] if stage["stage"].startswith("event:")],
              [{"stage": "event:" + event["type"], "message": event["message"]} for event in observed["events"] if "message" in event],
              "An actual live event lost its complete ordered prepared-marker/policy observation")
        _same([stage["message"] for stage in observed["stages"] if stage["stage"] == "tool-return"],
              [execution["result"] for execution in observed["executions"]], "A genuine tool return lost its actual marker/policy observation")
        _require(all(stage["stage"] in {"tool-return", "persisted-callback"} or stage["stage"].startswith("event:") for stage in observed["stages"]),
                 "A model stage was invented or relabelled")
        expected = {"phase": label, "providerMessages": [entry["context"]["messages"] for entry in observed["contexts"]],
                    "toolExecutions": [{key: item[key] for key in ("callId", "arguments", "result", "telemetry")} for item in observed["executions"]],
                    "persistedMessages": observed["persisted"], "storedMessages": [event["message"] for event in observed["after"] if event.get("type") == "message"],
                    "modelContext": observed["context"], "modelMessages": observed["modelMessages"],
                    **({"explicitOffDiagnostic": observed["explicitOffDiagnostic"]} if "explicitOffDiagnostic" in observed else {})}
        _same(output["result"], expected, "The complete public phase differs from real provider/persistence/context observations")
        results.append(expected)
    _same(row["result"], {"provider": "none", "phases": results}, "The parent changed or dropped an actual fresh phase result")
