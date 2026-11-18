"""Authenticate complete callback messages and unchanged physical durable facts.

This guard never builds a repaired transcript. Source-owned stages provide
causality; complete callback requests remain the comparison boundary.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re
import zlib

from equivalence.forget_lineage_evidence import _bytes
from equivalence.forget_lineage_outcomes_evidence import _files, _tables, _sdk_physical
from equivalence.prompt_history_repair import (
    EVIDENCE, SESSION_ID, canonical, validate_case,
)
from equivalence.prompt_runtime_context_evidence import (
    CLOSE_OWNERS, _event_payload, _native_json_details, _physical_database, _physical_native, _sql, _tools,
)
from equivalence.search_contract import _same_json
from equivalence.session_reset_boundaries_evidence import _sources

ROOT = Path(__file__).resolve().parents[1]
MAX_NATIVE_CAPTURE_BYTES = 128 * 1024**2


def _require(value, message):
    if not value:
        raise ValueError("prompt history repair: " + message)


def _same(left, right, message):
    _require(_same_json(left, right), message)


def decode_native_capture(envelope):
    _require(isinstance(envelope, dict) and set(envelope) == {
        "kind", "encoding", "uncompressedBytes", "sha256", "data"}
        and envelope["kind"] == "prompt-history-repair-lossless-raw"
        and envelope["encoding"] == "gzip-json-base64", "undeclared raw transport")
    size = envelope["uncompressedBytes"]
    _require(type(size) is int and 0 < size <= MAX_NATIVE_CAPTURE_BYTES
             and isinstance(envelope["data"], str) and len(envelope["data"]) <= 16 * 1024**2
             and isinstance(envelope["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", envelope["sha256"]),
             "raw transport exceeds its existing bounded authority")
    try:
        compressed = base64.b64decode(envelope["data"].encode("ascii"), validate=True)
        _same(base64.b64encode(compressed).decode("ascii"), envelope["data"], "noncanonical base64")
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        payload = decoder.decompress(compressed, size + 1)
        _require(decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail
                 and len(payload) == size and hashlib.sha256(payload).hexdigest() == envelope["sha256"],
                 "raw framing, complete size or digest changed")

        def pairs(rows):
            result = {}
            for key, value in rows:
                _require(key not in result, "duplicate raw JSON key")
                result[key] = value
            return result

        def constant(_value):
            raise ValueError("nonfinite raw number")

        raw = json.loads(payload.decode("utf8"), object_pairs_hook=pairs, parse_constant=constant)
        canonical(raw)  # Reject overflow-to-infinity as well as literal constants.
    except (ValueError, UnicodeError, zlib.error) as error:
        raise ValueError("prompt history repair: invalid complete raw transport") from error
    _require(isinstance(raw, list) and len(raw) == 1 and isinstance(raw[0], dict)
             and raw[0].get("kind") == "prompt-history-repair-native-raw", "wrong raw singleton/family")
    return raw


def _transcript_sql(snapshot, events, native):
    tables = _sql(snapshot)
    rows = tables.get("transcript_events" if native else "memory_session_events")
    _require(isinstance(rows, list) and all(row.get("session_id") == SESSION_ID
        and (native or row.get("agent") == "main") for row in rows), "transcript SQL escaped its session")
    rows = sorted(rows, key=lambda row: row["seq"])
    start = 0 if native else 1
    _same([row["seq"] for row in rows], list(range(start, start + len(events))), "incomplete SQL sequence")
    _same([_event_payload(row) for row in rows], events, "actual transcript differs from whole physical SQL payloads")
    if native:
        identities = tables.get("transcript_event_identities")
        _require(isinstance(identities, list) and len(identities) == len(events), "physical event identities omitted")
        by_seq = {row["seq"]: row for row in identities}
        _require(len(by_seq) == len(events), "duplicate physical event identities")
        for index, event in enumerate(events):
            row = by_seq.get(index, {})
            _require(row.get("session_id") == SESSION_ID and row.get("event_id") == event.get("id")
                     and row.get("event_type") == event.get("type"), "physical event identity changed")


def _preserve_history(before, after, *, reopen=False, allowed_result_ids=()):
    _require(isinstance(before, list) and isinstance(after, list) and len(after) >= len(before),
             "complete durable history omitted")
    _same(after[:len(before)], before, "an original durable event was rewritten or removed")
    if reopen:
        _same(after, before, "reopen changed committed durable history")
    # Every fixture has only historical calls. The transport returns plain text,
    # so a newly durable tool result would be an impermissible replay repair.
    for event in after[len(before):]:
        message = event.get("message", {})
        _require(not (event.get("type") == "message" and message.get("role") == "toolResult"
            and message.get("toolCallId") not in allowed_result_ids), "synthetic replay result was persisted")


def _custody(case, raw, captures, native):
    states, operations = raw["states"], raw["operations"]
    _require(len(states) == len(operations) + 1, "an actual state phase omitted")
    _same(raw["initialState"], states[0], "initial state changed")
    initial = states[0]["transcript"]
    _require(initial and initial[0].get("type") == "session" and initial[0].get("id") == SESSION_ID
             and initial[0].get("version") == case["input"]["sessionVersion"], "canonical header changed")
    _same(initial[1:], case["input"]["transcriptEvents"], "raw canonical seed events were rewritten")
    if native:
        seeds = raw["transcriptSeeds"]
        _require(isinstance(seeds, list) and len(seeds) == 1, "actual seed custody omitted")
        _same(seeds[0]["literalEvents"], case["input"]["transcriptEvents"], "literal native seed changed")
        _same(seeds[0]["events"], initial, "native seed write changed")
        _same(seeds[0]["actualStoredEvents"], initial, "native seed readback changed")
        _same(seeds[0]["databasePath"], raw["transcriptDatabasePath"], "native seed SQL owner changed")
    else:
        _same(raw["transcriptSeeds"], initial, "SDK seed readback changed")
    key = "agent" if native else "catalog"
    actual_result_ids = {script["id"] for operation in case["input"]["operations"]
                         for script in operation.get("scriptedTools", [])}
    filename = raw["transcriptDatabasePath"] if native else raw["catalogDatabasePath"]
    table_name = "transcript_events" if native else "memory_session_events"
    original_rows = sorted(_sql(states[0]["sql"][key])[table_name], key=lambda row: row["seq"])
    initial_tree = captures[0]["fixture"] if native else captures[0]
    for relative, text in case["input"]["files"].items():
        _same(_files(initial_tree).get("workspace/" + relative), text.encode("utf8"), "literal physical source bytes changed")
    for index, state in enumerate(states):
        _transcript_sql(state["sql"][key], state["transcript"], native)
        current_rows = sorted(_sql(state["sql"][key])[table_name], key=lambda row: row["seq"])
        for original, current in zip(original_rows, current_rows[:len(original_rows)], strict=True):
            _same({name: original.get(name) for name in ("event_json", "event_zstd", "event_utf8_bytes", "byte_size")},
                  {name: current.get(name) for name in ("event_json", "event_zstd", "event_utf8_bytes", "byte_size")},
                  "original canonical SQL payload bytes were re-encoded or rewritten")
        _transcript_sql(_physical_database(captures[index], filename), state["transcript"], native)
        _preserve_history(initial, state["transcript"], allowed_result_ids=actual_result_ids)
        for database in state["sql"].values():
            _sql(database)
        tree = captures[index]["fixture"] if native else captures[index]
        _sources(state["sources"], raw["workspace"], _files(tree))
    for index, operation in enumerate(operations):
        _same(operation["beforeTranscript"], states[index]["transcript"], "before-state custody changed")
        _same(operation["afterTranscript"], states[index + 1]["transcript"], "after-state custody changed")
        for prefix in ("before", "after"):
            _transcript_sql(operation[prefix + "Sql"][key], operation[prefix + "Transcript"], native)
        _same(operation["sourcesBefore"], states[index]["sources"], "actual source before-state custody changed")
        _same(operation["sourcesAfter"], states[index + 1]["sources"], "actual source after-state custody changed")
        _preserve_history(operation["beforeTranscript"], operation["afterTranscript"],
                          reopen=operation["operation"]["op"] == "reopen", allowed_result_ids=actual_result_ids)
    if native:
        _transcript_sql(_physical_database(captures[-1], filename), states[-1]["transcript"], True)


def _messages_guard(case, ordinal, messages):
    _require(isinstance(messages, list) and messages and all(isinstance(message, dict) for message in messages),
             "complete actual provider messages absent")
    suffix = case["id"].removeprefix("prompt-history-repair-")
    evidence = EVIDENCE[suffix]
    serialized = canonical(messages).decode("utf8")
    for token in evidence.get("required", []):
        _require(token in serialized, "required historical fact missing: " + token)
    for token in evidence.get("excluded", []):
        _require(token not in serialized, "excluded damaged replay fact survived: " + token)
    if suffix == "window-batches":
        required, excluded = ({0: ([0, 1, 2], []), 1: ([2], [0, 1]), 3: ([2], [0, 1])}[ordinal])
        for index in required:
            _require(f"historyturn{index}cedar" in serialized, "history cushion/batch dropped a retained turn")
        for index in excluded:
            _require(f"historyturn{index}cedar" not in serialized, "history batch retained an evicted turn")
    if suffix == "responses-metadata":
        if ordinal == 0:
            _require("rs_replaycedar" in serialized and "msg_replaycedar" in serialized
                     and "fc_replaycedar" in serialized, "same-model replay metadata was lost")
        else:
            _require(all(token not in serialized for token in ("rs_replaycedar", "msg_replaycedar", "fc_replaycedar")),
                     "stale route replay metadata returned")
            _require("commentary" in serialized, "model switch lost independent Responses phase metadata")


def _fingerprints(messages):
    return [hashlib.sha256(canonical(message)).hexdigest() for message in messages]


def _trace_record(record, original_messages):
    messages = record.get("messages")
    _require(isinstance(messages, list) and record.get("messageCount") == len(messages), "whole source stage messages omitted")
    fingerprints = record.get("messageFingerprints")
    _require(isinstance(fingerprints, list) and len(fingerprints) == len(messages)
             and all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) for value in fingerprints),
             "source stage fingerprints omitted")
    _same(record.get("messagesDigest"), hashlib.sha256(canonical("|".join(fingerprints))).hexdigest(),
          "complete ordered stage digest changed")
    roles = []
    for message, fingerprint in zip(messages, fingerprints, strict=True):
        if isinstance(message, dict):
            roles.append(message.get("role"))
        else:
            # CacheTrace fingerprints the original, then redacts its display.
            # A display marker needs a complete, separately recorded message.
            _require(message == "[Truncated]" and fingerprint in original_messages,
                     "source trace display has no authenticated whole message")
            roles.append(original_messages[fingerprint]["role"])
    _same(record.get("messageRoles"), roles, "source stage roles omitted")


def _native_trace(case, raw, ordinal, operation):
    trace = operation["cacheTrace"]
    payload = _bytes(trace["bytes"])
    _require(trace["completeLines"] is True and payload.endswith(b"\n"), "source trace was not completely drained")
    records = [json.loads(line) for line in payload.decode("utf8").splitlines()]
    _same(records, trace["records"], "whole source trace JSONL changed")
    selected = [row for row in records if row.get("runId") == f"prompt-history-{ordinal}"]
    _same(selected, trace["selectedRecords"], "source attempt stage selection changed")
    _same([row["seq"] for row in selected], list(range(1, len(selected) + 1)), "source stage ordering/sequence changed")
    wanted = ("session:loaded", "session:sanitized", "session:limited", "prompt:before", "prompt:images", "stream:context", "session:after")
    positions = []
    for stage in wanted:
        found = [index for index, row in enumerate(selected) if row.get("stage") == stage]
        expected_count = len(operation["providerCalls"]) if stage == "stream:context" else 1
        _require(len(found) == expected_count, "a required genuine source stage is missing/duplicated: " + stage)
        positions.append(found[0])
    _require(positions == sorted(positions), "genuine source history stage causality changed")
    model = operation["model"]
    whole_messages = [event["message"] for event in operation["beforeTranscript"]
                      if event.get("type") == "message"]
    whole_messages.extend(message for call in operation["providerCalls"]
                          for message in call["request"]["context"]["messages"])
    originals = dict(zip(_fingerprints(whole_messages), whole_messages, strict=True))
    for row in selected:
        _require(row.get("sessionId") == SESSION_ID and row.get("sessionKey") == case["input"]["sessionKey"]
                 and row.get("provider") == model["provider"] and row.get("modelId") == model["id"]
                 and row.get("modelApi") == model["api"] and row.get("workspaceDir") == raw["workspace"],
                 "source stage escaped actual attempt/model/session")
        if "messages" in row:
            _trace_record(row, originals)
    streams = [row for row in selected if row.get("stage") == "stream:context"]
    for stream, call in zip(streams, operation["providerCalls"], strict=True):
        _same(stream["messageFingerprints"], _fingerprints(call["request"]["context"]["messages"]),
              "whole callback request differs from source-owned stream stage")
    return {row["stage"]: row for row in selected if row.get("stage") in wanted}


def _verify_diagnostic_arguments(wire, expected):
    """Compare the JSON arguments of a real call, including backward aliases.

    The native observer assigns each array/object an index on first visit. A
    later occurrence of the same object names that index. Verify the value at
    each reference against its original completed subtree without expanding
    a graph of untrusted references.
    """
    values = []
    completed = set()

    def visit(encoded, value):
        if isinstance(encoded, dict) and encoded.get("type") == "reference":
            target = encoded.get("target")
            _require(set(encoded) == {"type", "target"} and type(target) is int
                     and target in completed, "invalid diagnostic argument reference")
            _same(values[target], value, "diagnostic argument reference identifies a different value")
            return
        if isinstance(value, (list, dict)):
            index = len(values)
            values.append(value)
            if isinstance(value, list):
                _require(isinstance(encoded, list) and len(encoded) == len(value),
                         "diagnostic argument array changed")
                for item, original in zip(encoded, value, strict=True):
                    visit(item, original)
            else:
                _require(isinstance(encoded, dict) and encoded.keys() == value.keys(),
                         "diagnostic argument object changed")
                for key, item in encoded.items():
                    visit(item, value[key])
            completed.add(index)
            return
        _same(encoded, value, "diagnostic argument value changed")

    visit(wire, expected)


def _tool_catalog(specification, operation, native):
    def names(tools, label):
        _require(isinstance(tools, list) and all(isinstance(tool, dict)
            and isinstance(tool.get("name"), str) and tool["name"] for tool in tools),
            label + " definitions omitted")
        actual = [tool["name"] for tool in tools]
        _require(len(actual) == len(set(actual)), label + " tool name duplicated")
        _same(set(actual), set(specification["tools"]), label + " tool names differ from literal policy")
        return actual

    for call in operation["providerCalls"]:
        names(call["request"]["context"].get("tools"), "actual callback")
    if not native:
        registered = operation.get("registeredTools")
        names(registered, "actual SDK registry")
        by_name = {tool["name"]: tool for tool in registered}
        for call in operation["providerCalls"]:
            # Production ModelPrompt preserves offered_tool_names order and the
            # exact registered definitions; native catalog ordering is separate.
            _same(call["request"]["context"]["tools"], [by_name[name] for name in specification["tools"]],
                  "actual SDK callback tools differ from registered definitions")
        _same(operation["historyReplay"]["allowedToolNames"], specification["tools"],
              "actual SDK replay tool names differ from literal policy")


def _operations(case, raw, public, native):
    _same(raw["input"], case["input"], "complete common input changed")
    _same(raw["output"], public, "public output was not its whole raw actual result")
    observations = public.get("observations")
    _require(isinstance(observations, list) and len(observations) == len(case["input"]["operations"])
             and len(raw["operations"]) == len(observations), "an actual operation was omitted")
    model = case["input"]["model"]
    for ordinal, (specification, operation, observed) in enumerate(zip(
            case["input"]["operations"], raw["operations"], observations, strict=True)):
        _same(operation["operation"], specification, "actual operation specification changed")
        _same(observed["operation"], specification, "public operation specification changed")
        _same(operation["observation"], observed, "whole operation observation changed")
        _require(operation.get("apiOutcome", {}).get("kind") == "return", "actual host attempt failed")
        calls = operation["providerCalls"]
        if specification["op"] == "reopen":
            _same(calls, [], "reopen invented an actual provider callback")
            _same(observed["modelCalls"], [], "reopen invented a public model call")
            continue
        model = specification.get("model", model)
        scripts = specification.get("scriptedTools", [])
        _require(len(calls) == len(scripts) + 1, "literal transport lost a genuine model callback")
        _same({key: operation["model"][key] for key in model}, model, "actual operation model changed")
        request = calls[0]["request"]
        _same({key: request["model"][key] for key in model}, model, "callback received a different model")
        expected = [{"messages": call["request"]["context"]["messages"]} for call in calls]
        _same(observed["modelCalls"], expected, "whole actual callback messages were replaced/dropped")
        _tool_catalog(specification, operation, native)
        for index, call in enumerate(calls):
            _messages_guard(case, ordinal, call["request"]["context"]["messages"])
            response = call["response"]
            content = ([{"type": "toolCall", **scripts[index]}] if index < len(scripts)
                       else [{"type": "text", "text": "history fixture complete"}])
            _require(response.get("timestamp") == specification["nowMs"] and response.get("api") == model["api"]
                     and response.get("provider") == model["provider"] and response.get("model") == model["id"]
                     and response.get("content") == content, "literal transport supplied an undeclared reply/clock/model")
            if index < len(scripts):
                _same(response.get("responseId"), f"prompt-history-tool-response-{ordinal}-{index}", "actual tool response identity changed")
        _tools(specification, operation, native)
        if scripts:
            first, later = (canonical(item["messages"]).decode() for item in expected)
            _require("livegetpayloadcedar" not in first and "livegetpayloadcedar" in later,
                     "actual grounded tool payload was fabricated before dispatch or omitted afterward")
            before_missing = [message for message in expected[0]["messages"] if message.get("role") == "toolResult"
                and "missing tool result in session history" in canonical(message).decode()]
            after_missing = [message for message in expected[1]["messages"] if message.get("role") == "toolResult"
                and "missing tool result in session history" in canonical(message).decode()]
            _require(before_missing and all(message.get("timestamp") == specification["nowMs"] for message in before_missing),
                     "missing-result timestamp did not come from actual trusted host clock")
            _same(after_missing, before_missing, "prepared historical synthetic results changed across live callbacks")
            results = [message for message in expected[1]["messages"] if message.get("role") == "toolResult"
                       and message.get("toolCallId") == scripts[0]["id"]]
            _require(len(results) == 1 and "details" not in results[0],
                     "model boundary lost the live result or exposed private tool details")
            if native:
                hook = [row for row in operation["toolCalls"] if row["hook"] == "after_tool_call"
                        and row["event"].get("toolCallId") == scripts[0]["id"]][0]
                details = _native_json_details(hook["event"]["result"]["details"])
            else:
                details = operation["toolCalls"][0]["apiOutcome"]["returnValue"]["value"]
                if isinstance(details, dict) and "details" in details and "content" in details:
                    details = details["details"]
            durable = [event["message"] for event in operation["afterTranscript"]
                       if event.get("message", {}).get("role") == "toolResult"
                       and event["message"].get("toolCallId") == scripts[0]["id"]]
            _require(len(durable) == 1, "actual durable tool result missing or duplicated")
            _same(durable[0]["details"], details, "durable tool result lost actual business details")
            _same(results[0]["content"], durable[0]["content"], "model boundary changed the live tool result content")
        if native:
            params = operation["callArguments"][0]
            _require(params["runId"] == f"prompt-history-{ordinal}" and params["prompt"] == specification["prompt"]
                     and params["sessionKey"] == case["input"]["sessionKey"] and params["sessionId"] == SESSION_ID,
                     "actual original harness arguments changed")
            _same(params["config"]["channels"], case["input"]["channelConfig"], "actual channel configuration changed")
            _same({"accountId": params.get("agentAccountId"), "peerId": params.get("conversationRoutePeerId"),
                   "chatType": params.get("chatType")}, case["input"]["route"], "actual route facts changed")
            runs = [row for row in raw["calls"] if row.get("operationIndex") == ordinal
                    and row.get("operation") == "OpenClawAgentHarness.runAttempt"]
            _require(len(runs) == 1 and "returnValue" in runs[0], "genuine original harness invocation missing")
            _same(runs[0]["arguments"], operation["callArguments"], "actual original harness arguments replaced")
            _native_trace(case, raw, ordinal, operation)
        else:
            args = operation["callArguments"]
            _require(args["user_message"] == specification["prompt"] and args["request_id"] == f"prompt-history-{ordinal}",
                     "actual SDK runner arguments changed")
            replay = operation["historyReplay"]
            _require(operation["modelPromptClosed"] is True, "SDK model prompt owner was not closed")
            _same(replay["context"]["model"], {"base_url": None, "input": ["text", "image"], **model,
                "params": model.get("params"), "compat": model.get("compat")},
                  "actual SDK replay model context changed")
            _same(replay["context"]["config"]["channels"], case["input"]["channelConfig"], "SDK channel facts changed")
            _same(replay["context"]["route"], case["input"]["route"], "SDK route facts changed")
            stages = replay["stages"]
            names = [row["stage"] for row in stages]
            _same(names, ["session:sanitized", "session:validated", "session:limited",
                         *[name for _ in calls for name in ("stream:malformed-tool-calls", "stream:context")]],
                  "actual SDK stage causality changed")
            _same([row["messages"] for row in stages if row["stage"] == "stream:context"],
                  [item["messages"] for item in expected], "actual SDK stream stages differ from callbacks")


def validate_native(case, public, snapshots, evidence):
    from equivalence.prompt_history_repair_bindings import COMPILED_HASHES, REQUIRED_OBSERVED_OWNERS

    validate_case(case)
    _require(isinstance(snapshots, list) and len(snapshots) == 1, "one complete native raw capture required")
    raw = snapshots[0]
    base = Path(raw["fixtureBase"])
    _require(raw.get("kind") == "prompt-history-repair-native-raw" and base.is_absolute()
             and base.parent == Path(evidence) and base.name.startswith("native-prompt-history-")
             and raw.get("closed") is True and not any(name in raw for name in
                 ("error", "closeCaptureError", "observerRestoreError", "configClearError")), "native capture incomplete/unowned")
    _same(raw["workspace"], str(base / "workspace"), "native workspace escaped fixture")
    owners = raw["codeOwners"]
    _same({(row["modulePath"], row["exportName"], row["name"]) for row in owners}, set(REQUIRED_OBSERVED_OWNERS),
          "genuine invoked original owners missing")
    _require(len(owners) == len(REQUIRED_OBSERVED_OWNERS), "original owner duplicated")
    for owner in owners:
        _same(owner["compiledSha256"], COMPILED_HASHES[owner["modulePath"]], "compiled original owner changed")
        _same(owner["functionSourceSha256"], hashlib.sha256(owner["functionSource"].encode()).hexdigest(), "function receipt changed")
    diagnostics = raw["diagnosticCodeOwners"]
    diagnostic_manifest = {("dist/helpers-DnieXpdv.mjs", "m", "resolveTranscriptPolicy.diagnostic"),
        ("dist/builtin-openclaw-D1Xfnzzr.mjs", "Y", "getHistoryLimitFromSessionKey.diagnostic")}
    _same({(row["modulePath"], row["exportName"], row["name"]) for row in diagnostics}, diagnostic_manifest,
          "post-attempt diagnostic owners were borrowed or omitted")
    _require(len(diagnostics) == len(diagnostic_manifest), "post-attempt diagnostic owner duplicated")
    for owner in diagnostics:
        _same(owner["compiledSha256"], COMPILED_HASHES[owner["modulePath"]], "diagnostic compiled owner changed")
        _same(owner["functionSourceSha256"], hashlib.sha256(owner["functionSource"].encode()).hexdigest(), "diagnostic function receipt changed")
    _same([row["operation"] for row in raw["closeReceipts"]], list(CLOSE_OWNERS), "native lifecycle close omitted")
    _require(all("returnValue" in row and "error" not in row for row in raw["closeReceipts"]), "native close failed")
    clock = raw["clock"]
    _require(clock["owner"] == "node:test" and clock["apis"] == ["Date"] and clock["dateConstructorReplaced"] is True
             and clock["setTimeoutUnchanged"] is True and clock["performanceNowUnchanged"] is True
             and clock["originalDateRestored"] is True, "native host clock/scheduler authority changed")
    expected = [case["input"]["nowMs"], *(operation["nowMs"] for operation in case["input"]["operations"])]
    _same([row["actualNowMs"] for row in clock["readings"]], expected, "native actual operation clocks changed")
    _require(raw["host"]["actualTimezone"] == "UTC" and raw["host"]["actualTimeFormat"] == "24", "explicit native host facts changed")
    captures = _physical_native(raw)
    _custody(case, raw, captures, True)
    trace_path = Path(raw["cacheTrace"]["path"])
    _require(trace_path == Path(raw["stateDirectory"]) / "logs/cache-trace.jsonl", "source diagnostic path escaped state owner")
    _same(_files(captures[-1]["state"])["logs/cache-trace.jsonl"], _bytes(raw["cacheTrace"]["bytes"]),
          "whole source diagnostics differ from physical bytes")
    _operations(case, raw, public, True)


def validate_pair(case, native_raw, sdk_raw, native_public, sdk_public, sdk_directory):
    validate_native(case, native_public, [native_raw], Path(native_raw["fixtureBase"]).parent)
    directory = Path(sdk_directory).resolve()
    raw_file = directory / "python-raw.json"
    _require(not raw_file.is_symlink(), "SDK raw evidence is a symlink")
    _same(json.loads(raw_file.read_text()), [sdk_raw], "retained SDK raw bytes changed")
    _require(sdk_raw.get("kind") == "prompt-history-repair-sdk" and sdk_raw.get("closed") is True,
             "actual SDK capture incomplete")
    _same(sdk_raw["fixtureRoot"], str(directory / "sdk-fixture"), "SDK fixture escaped evidence owner")
    _same(sdk_raw["databasePaths"], {name: str(directory / "sdk-fixture" / (name + ".sqlite"))
                                    for name in ("catalog", "index", "trust")}, "SDK actual SQL path changed")
    for owner in sdk_raw["owners"]:
        path = Path(owner["path"])
        _require(path.is_file() and not path.is_symlink() and path.is_relative_to(ROOT / "memory_core"), "SDK owner escaped production")
        _same(hashlib.sha256(path.read_bytes()).hexdigest(), owner["sha256"], "production SDK source changed")
    required = {"HostSessionRunner.run_turn", "HostSessionRunner._prepare_model_prompt", "HostTurn.model_request",
        "HostTurn.record_message", "MemorySessionCatalog.read_continuation", "MemorySessionCatalog.read_transcript",
        "MemorySessionCatalog.append_message", "MemorySessionCatalog.replace_events", "ModelPrompt", "HistoryReplay",
        "HistoryReplay.prepare", "HistoryReplay.request", "resolve_history_replay_policy"}
    _same({owner["name"] for owner in sdk_raw["owners"]}, required, "SDK production owner receipt missing")
    _require(len(sdk_raw["owners"]) == len(required), "SDK production owner duplicated")
    captures = _sdk_physical(sdk_raw, directory)
    _require(len(captures) == len(sdk_raw["operations"]) + 1, "SDK physical phase omitted")
    for capture in captures:
        _same(capture["root"], sdk_raw["fixtureRoot"], "SDK physical root changed")
        files = _files(capture)
        _tables(capture, files)
    _custody(case, sdk_raw, captures, False)
    _require(all(value is True for value in sdk_raw["clock"]["restored"].values()), "SDK clock fixture was not restored")
    _same([row["actualNowMs"] for row in sdk_raw["clock"]["readings"]],
          [operation["nowMs"] for operation in case["input"]["operations"]], "SDK host clocks changed")
    _operations(case, sdk_raw, sdk_public, False)
    for ordinal, (native, sdk) in enumerate(zip(native_raw["operations"], sdk_raw["operations"], strict=True)):
        if native["operation"]["op"] == "reopen":
            continue
        trace = _native_trace(case, native_raw, ordinal, native)
        stages = {row["stage"]: row["messages"] for row in sdk["historyReplay"]["stages"]}
        for name in ("session:sanitized", "session:limited"):
            _same(trace[name]["messageFingerprints"], _fingerprints(stages[name]), "whole production history stage differs: " + name)
        expected_limit = case["input"]["channelConfig"].get("telegram", {}).get("dmHistoryLimit")
        _same(sdk["historyReplay"]["historyLimit"], expected_limit, "SDK effective source-derived history limit changed")
        diagnostic = native["replayPolicy"]
        _require(diagnostic["role"] == "diagnostic-after-attempt", "policy diagnostic was substituted for an attempt")
        model = native["model"]
        _verify_diagnostic_arguments(diagnostic["arguments"], [{
            "modelApi": model["api"], "modelId": model["id"], "provider": model["provider"],
            "config": native["config"], "workspaceDir": native_raw["workspace"], "model": model,
        }])
        _same(diagnostic["returnValue"], sdk["historyReplay"]["policy"], "actual resolved provider replay policies differ")
        limit = native["historyLimit"]
        _require(limit["role"] == "diagnostic-after-attempt", "history-limit diagnostic was substituted for an attempt")
        _same(limit["arguments"], [case["input"]["sessionKey"], native["config"], case["input"]["route"]],
              "history-limit resolver received different actual route/configuration")
        _same(limit["returnValue"].get("value"), expected_limit, "actual original history limit differs from frozen facts")
        for name, receipt in (("resolveTranscriptPolicy.diagnostic", diagnostic), ("getHistoryLimitFromSessionKey.diagnostic", limit)):
            calls = [row for row in native_raw["calls"] if row.get("operationIndex") == ordinal and row.get("operation") == name]
            _require(len(calls) == 1 and "returnValue" in calls[0], "genuine post-attempt diagnostic resolver call missing")
            _same(calls[0]["arguments"], receipt["arguments"], "diagnostic resolver call arguments replaced")
    return native_public, sdk_public
