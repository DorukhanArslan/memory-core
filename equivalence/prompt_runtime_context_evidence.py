"""Authenticate complete prompt components and whole real model-bound messages.

This checks custody and fixture invariants. Prompt projection and tool-result
composition remain production owners; no expected message packet is built here.
"""
from __future__ import annotations

import hashlib
import base64
import json
import math
from pathlib import Path
import re
import stat
from datetime import datetime
import zlib

from equivalence.embedding_cache_lifecycle_evidence import HOST_LINK
from equivalence.forget_lineage_evidence import _bytes, physical_snapshot
from equivalence.forget_lineage_outcomes_evidence import _files, _tables, _sdk_physical
from equivalence.prompt_runtime_context import EVIDENCE, HOST_TIMEZONE, HOST_TIME_FORMAT, TOOL_NAMES, validate_case
from equivalence.search_contract import _same_json, decode_search_tool_envelope
from equivalence.session_reset_boundaries_evidence import _sources, _outcome
from memory_core.bootstrap._js import js_trim

ROOT = Path(__file__).resolve().parents[1]
SESSION = "prompt-runtime-session"
CLOSE_OWNERS = ("closeActiveMemorySearchManagersCore", "closeAllMemoryIndexManagers", "disposeSessionMcpRuntime", "GatewayScheduler.stop",
                "closeOpenClawAgentDatabasesAsync", "closePluginStateDatabaseAsync")
MAX_NATIVE_CAPTURE_BYTES = 128 * 1024**2


def decode_native_capture(envelope):
    """Decode only this family's bounded, complete lossless raw transport.

    Decoding does not authenticate execution or award points. The caller must
    still run validate_native against the exact case and runtime authority.
    """
    _require(isinstance(envelope, dict)
             and set(envelope) == {"kind", "encoding", "uncompressedBytes", "sha256", "data"}
             and envelope["kind"] == "prompt-runtime-context-lossless-raw"
             and envelope["encoding"] == "gzip-json-base64", "an undeclared Native raw transport was supplied")
    size = envelope["uncompressedBytes"]
    _require(type(size) is int and 0 < size <= MAX_NATIVE_CAPTURE_BYTES,
             "the Native raw decoded size exceeds its distinct bounded authority")
    _require(isinstance(envelope["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", envelope["sha256"])
             and isinstance(envelope["data"], str) and len(envelope["data"]) <= 16 * 1024**2,
             "Native raw transport metadata exceeds the existing outer-file bound")
    try:
        compressed = base64.b64decode(envelope["data"].encode("ascii"), validate=True)
        _require(base64.b64encode(compressed).decode("ascii") == envelope["data"], "Native raw base64 is not canonical")
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        decoded = decoder.decompress(compressed, size + 1)
        _require(decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail
                 and len(decoded) == size and hashlib.sha256(decoded).hexdigest() == envelope["sha256"],
                 "Native raw gzip framing, full decoded size or SHA-256 changed")

        def object_pairs(pairs):
            result = {}
            for key, value in pairs:
                _require(key not in result, "a duplicate key entered the complete Native raw JSON")
                result[key] = value
            return result

        def invalid_constant(_value):
            raise ValueError("prompt runtime context: Native raw JSON contains a non-finite number")

        raw = json.loads(decoded.decode("utf8"), object_pairs_hook=object_pairs, parse_constant=invalid_constant)

        def finite(value):
            if isinstance(value, float):
                _require(math.isfinite(value), "Native raw JSON contains an overflowing number")
            elif isinstance(value, dict):
                for item in value.values():
                    finite(item)
            elif isinstance(value, list):
                for item in value:
                    finite(item)

        finite(raw)
    except (ValueError, zlib.error) as error:
        raise ValueError("prompt runtime context: invalid complete Native raw transport") from error
    _require(isinstance(raw, list) and len(raw) == 1 and isinstance(raw[0], dict)
             and raw[0].get("kind") == "prompt-runtime-context-native-raw",
             "the complete Native raw singleton or family identity changed")
    return raw


def _require(value, message):
    if not value:
        raise ValueError("prompt runtime context: " + message)


def _same(left, right, message):
    _require(_same_json(left, right), message)


def _ordered_tokens(text, tokens):
    positions = [text.find(token) for token in tokens]
    _require(all(position >= 0 for position in positions) and positions == sorted(positions),
             "the actual runtime fragments lost their declared insertion order")


def _text(messages):
    """Read every actual textual content block without changing its message."""
    result = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            result.append(content)
        elif isinstance(content, list):
            result.extend(block["text"] for block in content
                          if isinstance(block, dict) and block.get("type") == "text"
                          and isinstance(block.get("text"), str))
    return "\n".join(result)


def _native_json_details(value):
    """Read the raw capture's JS undefined tags using JSON transport semantics.

    Raw tool returns remain untouched. JSON.stringify omits undefined object
    properties and writes undefined array entries as null; the actual carrier
    text is checked independently against this complete transport value.
    """
    missing = object()

    def project(item):
        if isinstance(item, dict):
            if item == {"type": "undefined"}:
                return missing
            result = {}
            for key, child in item.items():
                projected = project(child)
                if projected is not missing:
                    result[key] = projected
            return result
        if isinstance(item, list):
            values = [project(child) for child in item]
            return [None if child is missing else child for child in values]
        return item

    result = project(value)
    _require(result is not missing, "a complete JSON tool result cannot itself be undefined")
    return result


def _physical_native(raw):
    captures = [physical_snapshot(capture) for capture in raw["physical"]]
    _require(len(captures) == len(raw["operations"]) + 2,
             "an initial, operation or closed physical capture is missing")
    config = raw["config"]
    for index, (capture, reference) in enumerate(zip(captures, raw["physical"], strict=True)):
        label = "initial" if index == 0 else "closed" if index == len(captures) - 1 else str(index - 1)
        path = Path(reference["path"])
        _require(path.parent == Path(raw["fixtureBase"]).parent
                 and path.name == "native-physical-" + label + ".json", "physical capture order/owner changed")
        _same(capture["fixture"]["root"], raw["fixtureBase"], "physical fixture root changed")
        _same(capture["state"]["root"], raw["stateDirectory"], "physical state root changed")
        for name in ("fixture", "state"):
            files = _files(capture[name])
            _tables(capture[name], files)
            _links(capture[name], raw["runtimeRoot"], name == "fixture")
        if 0 < index < len(captures) - 1 and "config" in raw["operations"][index - 1]:
            config = raw["operations"][index - 1]["config"]
        _same(json.loads(_bytes(capture["config"])), config, "whole physical configuration changed")
    return captures


def _links(tree, runtime_root, fixture):
    links = tree.get("links")
    _require(isinstance(links, dict), "the complete physical symbolic-link map is missing")
    for name, row in links.items():
        _require(not fixture and HOST_LINK.fullmatch(name)
                 and set(row) == {"target", "resolvedTarget", "lstatIdentity"},
                 "an undeclared physical symbolic link was admitted")
        _require(Path(row["target"]).is_absolute() and row["target"] == row["resolvedTarget"] == runtime_root,
                 "the original plugin host link changed its real target")
        identity = row["lstatIdentity"]
        _require(set(identity) == {"device", "inode", "mode", "nlink", "uid", "gid", "size", "mtimeNs", "ctimeNs"}
                 and all(isinstance(value, str) and re.fullmatch(r"-?[0-9]+", value)
                         for value in identity.values()) and stat.S_ISLNK(int(identity["mode"]))
                 and int(identity["size"]) == len(row["target"].encode("utf8")),
                 "the original host link lost its complete no-follow identity")
        _require(not any(path == name or path.startswith(name + "/") for path in tree["files"]),
                 "the physical producer followed a symbolic link")


def _physical_database(capture, filename):
    path = Path(filename)
    _require(path.is_absolute(), "an actual SQL path is not absolute")
    trees = (capture["fixture"], capture["state"]) if "fixture" in capture else (capture,)
    for tree in trees:
        if path.is_relative_to(tree["root"]):
            relative = path.relative_to(tree["root"]).as_posix()
            _require(relative in tree["databases"], "an actual SQL handle has no physical database")
            return tree["databases"][relative]
    raise ValueError("prompt runtime context: a SQL handle escaped its owned physical roots")


def _event_payload(row):
    text, compressed = row.get("event_json"), row.get("event_zstd")
    if isinstance(text, str):
        _require(compressed is None, "a stored transcript has conflicting encodings")
        payload = text.encode("utf8")
    else:
        _require(text is None and isinstance(compressed, dict)
                 and set(compressed) == {"type", "hex"} and compressed["type"] == "bytes"
                 and isinstance(compressed["hex"], str) and re.fullmatch(r"(?:[0-9a-f]{2})+", compressed["hex"]),
                 "the compressed transcript lost its physical bytes")
        data = bytes.fromhex(compressed["hex"])
        _require(0 < len(data) <= 4 * 1024**2, "compressed transcript exceeds the original payload bound")
        try:
            from compression import zstd
        except ImportError:
            import zstandard
            payload = zstandard.ZstdDecompressor().decompress(
                data, max_output_size=4 * 1024**2, allow_extra_data=False)
        else:
            decoder = zstd.ZstdDecompressor()
            payload = decoder.decompress(data, max_length=4 * 1024**2 + 1)
            _require(decoder.eof and not decoder.unused_data, "compressed transcript contains extra frames")
        _require(len(payload) <= 4 * 1024**2, "decoded transcript exceeds the original payload bound")
    for key in ("event_utf8_bytes", "byte_size"):
        if row.get(key) is not None:
            _same(len(payload), row[key], "stored transcript UTF-8 byte size changed")
    return json.loads(payload.decode("utf8"))


def _transcript_sql(snapshot, events, native):
    tables = _sql(snapshot)
    name = "transcript_events" if native else "memory_session_events"
    _require(name in tables, "the actual transcript SQL table is missing")
    rows = tables[name]
    _require(all(row.get("session_id") == SESSION and (native or row.get("agent") == "main") for row in rows),
             "a transcript row escaped the actual session")
    rows = sorted(rows, key=lambda row: row["seq"])
    first = 0 if native else 1
    _same([row["seq"] for row in rows], list(range(first, first + len(events))),
          "the complete actual transcript SQL sequence changed")
    _same([_event_payload(row) for row in rows], events,
          "the actual transcript read differs from complete physical SQL payloads")
    if native:
        identities = tables.get("transcript_event_identities")
        _require(isinstance(identities, list) and len(identities) == len(events), "actual event identities were dropped")
        by_seq = {row["seq"]: row for row in identities}
        _require(len(by_seq) == len(events), "actual transcript identities were duplicated")
        for index, event in enumerate(events):
            row = by_seq.get(index, {})
            _require(row.get("session_id") == SESSION and row.get("event_id") == event.get("id")
                     and row.get("event_type") == event.get("type"), "a physical event lost its actual identity")


def _custody(case, raw, captures, native):
    states = raw["states"]
    _require(len(states) == len(raw["operations"]) + 1, "an initial or per-operation actual state is missing")
    _same(raw["initialState"], states[0], "the actual initial state was replaced")
    initial_tree = captures[0]["fixture"] if native else captures[0]
    initial_files = _files(initial_tree)
    for relative, text in case["input"]["files"].items():
        _same(initial_files.get("workspace/" + relative), text.encode("utf8"),
              "an actual initial source differs from its literal fixture bytes")
    if native:
        seeds = raw["transcriptSeeds"]
        _require(len(seeds) == 1, "the original transcript seed is missing")
        seed = seeds[0]
        _same(seed["literalMessages"], case["input"]["messages"], "the literal initial messages changed")
        _same(seed["events"], seed["actualStoredEvents"], "the actual seed write/read changed events")
        _same(seed["events"], states[0]["transcript"], "the original initial transcript changed after seeding")
        _same([event["message"] for event in seed["events"] if event.get("type") == "message"],
              case["input"]["messages"], "the original seeded source messages changed")
        _require(seed["header"]["version"] == case["input"]["sessionVersion"] and seed["header"]["id"] == SESSION
                 and seed["databasePath"] == raw["transcriptDatabasePath"], "the actual seed header/database changed")
    else:
        _same(raw["transcriptSeeds"], states[0]["transcript"], "the actual SDK initial seed/read changed")
        events = states[0]["transcript"]
        _require(events[0]["type"] == "session" and events[0]["id"] == SESSION
                 and events[0]["version"] == case["input"]["sessionVersion"], "the actual SDK session header changed")
        _require(len(events) == len(case["input"]["messages"]) + 1, "an SDK literal seed message is missing")
        for event, message in zip(events[1:], case["input"]["messages"], strict=True):
            if message["role"] == "custom":
                _require(event["type"] == "custom_message", "a real custom seed used the wrong event type")
                _same({key: event[key] for key in message if key not in {"role", "timestamp"}},
                      {key: value for key, value in message.items() if key not in {"role", "timestamp"}},
                      "the actual SDK custom source payload changed")
            else:
                _same(event["message"], message, "an actual SDK ordinary source message changed")
    for index, state in enumerate(states):
        if native:
            _same(state["operationIndex"], index - 1, "the actual state order changed")
        key = "agent" if native else "catalog"
        _transcript_sql(state["sql"][key], state["transcript"], native)
        path = raw["transcriptDatabasePath"] if native else raw["catalogDatabasePath"]
        paths = ({"agent": raw["transcriptDatabasePath"], "state": raw["stateDatabasePath"]}
                 if native else raw["databasePaths"])
        _same(set(state["sql"]), set(paths), "an actual SQL connection/map was omitted")
        # Snapshots are separate real read transactions. Authenticate relevant
        # transcript custody; unrelated background-owned tables remain full raw.
        _transcript_sql(_physical_database(captures[index], path), state["transcript"], native)
        tree = captures[index]["fixture"] if native else captures[index]
        _sources(state["sources"], raw["workspace"], _files(tree))
        for database in state["sql"].values():
            _sql(database)
        for filename in paths.values():
            _sql(_physical_database(captures[index], filename))
    for index, operation in enumerate(raw["operations"]):
        for prefix, state in (("before", states[index]), ("after", states[index + 1])):
            _same(operation[prefix + "Transcript"], state["transcript"], "actual transcript custody changed between reads")
            key = "agent" if native else "catalog"
            _transcript_sql(operation[prefix + "Sql"][key], state["transcript"], native)
            tree = captures[index if prefix == "before" else index + 1]
            _sources(operation["sources" + prefix.title()], raw["workspace"],
                     _files(tree["fixture"] if native else tree))
    if native:
        _transcript_sql(_physical_database(captures[-1], raw["transcriptDatabasePath"]), states[-1]["transcript"], True)


def _sql(snapshot):
    _require(isinstance(snapshot, dict) and isinstance(snapshot.get("schema"), list)
             and isinstance(snapshot.get("tables"), dict), "a complete SQL snapshot is absent")
    tables = snapshot["tables"]
    names = [row["name"] for row in snapshot["schema"] if row["type"] == "table"]
    _require(len(names) == len(set(names)) and set(names) == set(tables)
             and all(isinstance(rows, list) and all(isinstance(row, dict) for row in rows)
                     for rows in tables.values()), "an actual SQL table or row was omitted")
    return tables


def _history(operation, specification, evidence):
    before, after = operation["beforeTranscript"], operation["afterTranscript"]
    _require(isinstance(before, list) and isinstance(after, list) and len(after) >= len(before),
             "the complete durable transcript was lost")
    _same(after[:len(before)], before, "an existing durable transcript event changed")
    if specification["op"] == "reopen":
        _same(after, before, "reopening rewrote committed history")
    # A transient fragment may appear in a prior intentionally seeded custom
    # event. Check new actual events, never erase those original source rows.
    appended = json.dumps(after[len(before):], ensure_ascii=False)
    for token in evidence.get("transientTokens", []):
        _require(token not in appended, "transient model text leaked into durable history: " + token)
    for key in ("beforeSql", "afterSql"):
        for database in operation[key].values():
            _sql(database)


def _guidance(specification, operation, observed, native):
    guidance = observed["memoryGuidance"]
    _require(isinstance(guidance, dict) and set(guidance) == {"toolAvailability", "lines"},
             "the complete effective memory-guidance component changed shape")
    availability, lines = guidance["toolAvailability"], guidance["lines"]
    _require(set(availability) == set(TOOL_NAMES)
             and all(type(value) is bool for value in availability.values())
             and isinstance(lines, list) and all(isinstance(line, str) for line in lines),
             "the complete dependency map or guidance output was omitted")
    _same(availability, {name: name in specification["tools"] for name in TOOL_NAMES},
          "the actual offered dependency map differs from the literal tool policy")
    _same(operation["effectiveMemoryGuidance"], guidance, "effective guidance was replaced in public output")
    calls = operation["memoryPromptCalls"]
    successful = [call for call in calls if "returnValue" in call]
    _require(successful, "effective memory guidance has no actual production builder receipt")
    effective = successful[-1]
    _same(effective["returnValue"]["value"] if native else effective["returnValue"], lines,
          "the effective whole guidance differs from the actual final builder return")
    _same(effective["toolAvailability"], availability, "the actual effective builder dependency map changed")
    if native:
        _require(all(call["originalInvocations"] == 1 and call.get("returnedExactOriginalValue") is True
                     for call in successful), "the passive observer replaced the original builder result")
    for call in operation["providerCalls"]:
        context = call["request"]["context"]
        _require(isinstance(context.get("systemPrompt"), str) and isinstance(context.get("tools"), list),
                 "the full actual system prompt or offered tool registry was dropped")
        offered = [tool["name"] for tool in context["tools"]]
        _require(len(offered) == len(set(offered)), "an actual offered tool definition was duplicated")
        names = set(offered)
        _same(availability, {name: name in names for name in TOOL_NAMES},
              "the effective component does not reflect actual provider-offered tools")
        if lines:
            # The source renderers consume a final empty separator. Preserve
            # every owner-returned line in public and test its actual framing.
            _require("\n".join(lines).rstrip("\n") in context["systemPrompt"],
                     "the actual full system prompt lacks the whole effective guidance section")
        else:
            _require("## Memory Recall" not in context["systemPrompt"],
                     "an undeclared memory guidance section reached the model")


def _clock(specification, operation, observed, native):
    clock = observed["clock"]
    if not specification.get("includeClock"):
        _same(clock, None, "an unrequested clock result was fabricated")
        _require("clockCall" not in operation, "an undeclared clock producer executed")
        return
    _require(isinstance(clock, dict) and set(clock) == {"userTimezone", "formattedTime", "timeLine"},
             "the complete real clock component was omitted")
    call = operation["clockCall"]
    actual = call["returnValue"]["value"] if native else call["returnValue"]
    _same(clock, actual, "the whole actual clock return was rewritten")
    if native:
        _require(call["owner"] == "resolveCronStyleNow" and call["arguments"][1] == specification["nowMs"],
                 "the actual clock owner received a different fixed time")
        _same(call["arguments"][0], operation["config"], "the actual clock owner received different config")
    else:
        _same(call["arguments"], {"now_ms": specification["nowMs"], "timezone": specification.get("timezone", ""),
                                  "time_format": HOST_TIME_FORMAT, "host_timezone": HOST_TIMEZONE},
              "the SDK clock owner received different explicit host facts")
    for provider in operation["providerCalls"]:
        _require(clock["timeLine"] in _text(provider["request"]["context"]["messages"]),
                 "the real clock producer's whole timeLine did not reach the model")
    if js_trim(specification.get("timezone", "")) in ("", "Invalid/Fixture"):
        _same(clock["userTimezone"], HOST_TIMEZONE, "blank or invalid timezone lost actual host fallback")


def _tools(specification, operation, native):
    scripts, calls = specification.get("scriptedTools", []), operation["providerCalls"]
    if not scripts:
        _same(operation["toolCalls"], [], "an undeclared real tool call executed")
        return
    _require(len(calls) == len(scripts) + 1, "a real tool loop lost a provider request")
    for index, script in enumerate(scripts):
        response = calls[index]["response"]
        _same(response["content"], [{"type": "toolCall", **script}], "the real model requested a different tool call")
        later = calls[index + 1]["request"]["context"]["messages"]
        _require(isinstance(response.get("responseId"), str) and response["responseId"],
                 "the actual provider tool response lost its stable response identity")
        assistants = [message for message in later if message.get("role") == "assistant"
                      and message.get("responseId") == response["responseId"]]
        _require(len(assistants) == 1, "the actual provider tool response lost its unique model-bound owner")
        assistant = assistants[0]
        for key, value in response.items():
            if key != "content":
                _same(assistant.get(key), value, "an unchanged provider response field changed before replay")
        content = assistant.get("content")
        _require(isinstance(content, list) and len(content) == 1 and isinstance(content[0], dict)
                 and set(content[0]) == set(response["content"][0]),
                 "the actual assistant tool request dropped or added a content field")
        for key, value in response["content"][0].items():
            if key != "id":
                _same(content[0][key], value, "the actual tool request changed a name, argument or other content field")
        observed_id = content[0]["id"]
        _require(isinstance(observed_id, str) and observed_id, "the actual projected tool ID is absent")
        # The original provider policy may sanitize IDs during model replay.
        # Bind the observed ID to its real result; never reproduce a sanitizer
        # or rewrite any ID in the complete public message comparison.
        results = [message for message in later if message.get("role") == "toolResult"
                   and message.get("toolCallId") == observed_id]
        _require(len(results) == 1 and results[0].get("toolName") == script["name"]
                 and results[0].get("isError") is not True, "a genuine successful tool result is missing")
        if native:
            receipts = [row for row in operation["toolCalls"] if row["event"].get("toolCallId") == script["id"]]
            _same([row["hook"] for row in receipts], ["before_tool_call", "after_tool_call"],
                  "the genuine passive before/after tool hooks were lost or reordered")
            for row in receipts:
                _same(row["event"]["toolName"], script["name"], "a real tool observer changed tool name")
                _same(row["event"]["params"], script["arguments"], "a real tool observer changed arguments")
            event = receipts[-1]["event"]
            _require("result" in event and event.get("error") in (None, {"type": "undefined"}),
                     "the original tool did not return successfully")
            result = event["result"]
        else:
            receipts = [row for row in operation["toolCalls"] if row["toolCallId"] == script["id"]]
            _require(len(receipts) == 1, "a real SDK tool dispatch receipt is missing or duplicated")
            receipt = receipts[0]
            _same(receipt["tool"], script["name"], "the SDK dispatch changed tool name")
            _same(receipt["arguments"], script["arguments"], "the SDK dispatch changed arguments")
            _require(receipt["apiOutcome"]["kind"] == "return", "the real SDK tool did not return")
            result = receipt["apiOutcome"]["returnValue"]["value"]
            before, after = receipt["beforeMessages"], receipt["afterMessages"]
            _same(after[:len(before)], before, "a genuine tool dispatch rewrote earlier host messages")
            added = [message for message in after[len(before):] if message.get("role") == "toolResult"
                     and message.get("toolCallId") == script["id"]]
            _require(len(added) == 1, "the real SDK dispatch did not append its actual result")
            _same(added[0]["content"], results[0]["content"], "the actual SDK tool result was rewritten for the model")
        if native or (isinstance(result, dict) and "content" in result and "details" in result):
            _same(results[0]["content"], result["content"], "whole actual tool content changed before the next model call")
            envelope = ({**result, "details": _native_json_details(result["details"])} if native else result)
            business = decode_search_tool_envelope(envelope)["details"]
        else:
            # HostKit returns the complete business mapping. The production
            # result-message owner renders it; retain that actual content and
            # authenticate its complete details rather than recreating text.
            _require(isinstance(result, dict), "the actual SDK tool business result is not a mapping")
            _same(added[0]["details"], result, "the actual SDK result lost or changed a business field")
            business = result
        source_rows = operation["sourcesAfter"]
        sources = ({name: _bytes(row["bytes"]) for name, row in source_rows.items()}
                   if native else {row["path"]: _bytes(row["bytes"]) for row in source_rows})
        if script["name"] == "memory_get":
            relative = script["arguments"]["path"]
            _require(relative in sources and business.get("status") == "ok" and business.get("from") == 1,
                     "the actual get did not read its declared real source")
            _same(business["text"].rstrip("\n"), sources[relative].decode("utf8").rstrip("\n"),
                  "the complete actual get result differs from owned source bytes")
        else:
            hits = business.get("results")
            _require(isinstance(hits, list) and hits, "the genuine recall search returned no source hit")
            for hit in hits:
                _require(hit["path"] in sources and type(hit["startLine"]) is int and type(hit["endLine"]) is int
                         and 1 <= hit["startLine"] <= hit["endLine"] <= len(sources[hit["path"]].decode("utf8").split("\n")),
                         "a genuine recall hit escaped its actual source range")


def _operations(case, raw, public, native):
    _require(set(public) == {"observations"}, "the whole public component packet changed shape")
    operations, observations = raw["operations"], public["observations"]
    _require(len(operations) == len(observations) == len(case["input"]["operations"]),
             "an operation or complete observation was dropped")
    evidence = EVIDENCE[case["id"]]
    total_calls = 0
    previous = None
    for index, (specification, operation, observed) in enumerate(zip(
            case["input"]["operations"], operations, observations, strict=True)):
        _same(operation["operation"], specification, "the driven literal operation changed")
        _outcome(operation["apiOutcome"])
        _same(operation["observation"], observed, "a complete raw observation was rewritten")
        _require(set(observed) == {"operation", "memoryGuidance", "clock", "modelCalls"},
                 "a complete observation field was added or removed")
        _same(observed["operation"], specification, "the public operation changed")
        _history(operation, specification, evidence)
        if previous is not None:
            _same(operation["beforeTranscript"], previous, "committed history changed between actual operations")
        previous = operation["afterTranscript"]
        if specification["op"] == "reopen":
            _same(observed, {"operation": specification, "memoryGuidance": None,
                             "clock": None, "modelCalls": []}, "reopen invented model/component work")
            _same(operation["providerCalls"], [], "reopen secretly called the model")
            continue
        _guidance(specification, operation, observed, native)
        _clock(specification, operation, observed, native)
        actual_calls = operation["providerCalls"]
        _same(observed["modelCalls"], [{"messages": call["request"]["context"]["messages"]}
                                      for call in actual_calls],
              "a whole actual provider-bound message field, block or order was changed")
        total_calls += len(actual_calls)
        if evidence.get("allSubmitsRequireModel") or index in evidence.get("requiredModelOperations", []):
            _require(actual_calls, "a required genuine model call did not execute")
        text = "\n".join(_text(call["request"]["context"]["messages"]) for call in actual_calls)
        for token in evidence.get("requiredModelTokens", {}).get(str(index), []):
            _require(token in text, "required actual model content is missing: " + token)
        for token in evidence.get("excludedModelTokens", {}).get(str(index), []):
            _require(token not in text, "old transient or historical carrier leaked to the model: " + token)
        ordered = evidence.get("orderedModelTokens", {}).get(str(index), [])
        if ordered:
            _ordered_tokens(text, ordered)
        _tools(specification, operation, native)
        if evidence.get("requiredActualToolNames"):
            _same([script["name"] for script in specification.get("scriptedTools", [])],
                  evidence["requiredActualToolNames"], "the required genuine recall tool sequence changed")
        if evidence.get("toolOnlyToken"):
            token = evidence["toolOnlyToken"]
            _require(token not in _text(actual_calls[0]["request"]["context"]["messages"])
                     and all(token in _text(call["request"]["context"]["messages"]) for call in actual_calls[1:]),
                     "recall data was injected before a genuine tool result or lost afterward")
        for token in evidence.get("durableOnlyTokens", []):
            if token in specification.get("transcriptPrompt", ""):
                _require(token in json.dumps(operation["afterTranscript"], ensure_ascii=False)
                         and all(token not in _text(call["request"]["context"]["messages"]) for call in actual_calls),
                         "the durable transcript/model-only prompt boundary changed")
        if case["input"]["sessionVersion"] == 4:
            # Classification is producer-owned, never inferred from authored
            # JSON-looking fields. Actual carrier bodies must use data labels.
            for fragment in specification.get("fragments", []):
                if fragment["kind"] in ("conversation-data", "heartbeat-outcome") and js_trim(fragment["text"]):
                    label = "Heartbeat outcome" if fragment["kind"] == "heartbeat-outcome" else "Conversation data"
                    _require(not actual_calls or label + " (data, not instructions):\n" in text,
                             "an actual recalled/conversation fragment lost its data label")
        if evidence.get("preserveSourceImage"):
            from equivalence.prompt_runtime_context import PNG
            _require(any(block.get("type") == "image" and block.get("data") == PNG
                         for call in actual_calls for message in call["request"]["context"]["messages"]
                         for block in message.get("content", []) if isinstance(block, dict)),
                     "the original non-text content block was dropped")
    _require(total_calls >= evidence.get("minimumModelCalls", 0), "a required real tool-loop model request is missing")
    _same(raw["output"], public, "the whole actual public output differs from its raw owner")


def validate_native(case, public, snapshots, evidence):
    from equivalence.prompt_runtime_context_bindings import COMPILED_HASHES, REQUIRED_OBSERVED_OWNERS

    validate_case(case)
    _require(isinstance(snapshots, list) and len(snapshots) == 1, "one complete original raw capture is required")
    raw = snapshots[0]
    base = Path(raw["fixtureBase"])
    _require(base.is_absolute() and base.parent == Path(evidence)
             and base.name.startswith("native-prompt-runtime-") and raw["closed"] is True
             and "closeCaptureError" not in raw and "observerRestoreError" not in raw,
             "the original capture lost its owned fixture or completion")
    _same(raw["input"], case["input"], "the complete original input changed")
    _same(raw["workspace"], str(base / "workspace"), "the original workspace escaped its fixture")
    _same(raw["storePath"], str(base / "sessions.json"), "the original session catalog escaped its fixture")
    host = raw["host"]
    _require(host["actualTimezone"] == host["requestedTimezone"] == HOST_TIMEZONE
             and host["actualTimeFormat"] == host["requestedTimeFormat"] == HOST_TIME_FORMAT,
             "the actual host timezone or original time-format detection differs from its frozen profile")
    clock = raw["clock"]
    _require(clock["owner"] == "node:test" and clock["apis"] == ["Date"]
             and clock["nowMs"] == case["input"]["nowMs"] and clock["dateConstructorReplaced"] is True
             and clock["setTimeoutUnchanged"] is True and clock["performanceNowUnchanged"] is True
             and clock["originalDateRestored"] is True,
             "the original Date fixture changed scheduler time or was not restored")
    readings = clock["readings"]
    requested = [case["input"]["nowMs"], *(operation["nowMs"] for operation in case["input"]["operations"])]
    _same([row["operationIndex"] for row in readings], list(range(-1, len(requested) - 1)),
          "an actual per-operation wall-clock read was omitted")
    _same([row["requestedNowMs"] for row in readings], requested, "the literal operation clock changed")
    _same([row["actualNowMs"] for row in readings], requested, "the actual operation Date clock changed")
    _require(all(int(datetime.fromisoformat(row["iso"]).timestamp() * 1000) == now
                 for row, now in zip(readings, requested, strict=True)), "actual Date construction changed")
    owners = raw["codeOwners"]
    _require({(row["modulePath"], row["exportName"], row["name"]) for row in owners}
             == set(REQUIRED_OBSERVED_OWNERS) and len(owners) == len(REQUIRED_OBSERVED_OWNERS),
             "an actual original owner is absent or duplicated")
    for owner in owners:
        _same(owner["compiledSha256"], COMPILED_HASHES[owner["modulePath"]], "an actual compiled owner changed")
        _same(owner["functionSourceSha256"], hashlib.sha256(owner["functionSource"].encode()).hexdigest(),
              "the whole original function-source receipt changed")
    observer = raw["memoryPromptObserver"]
    _require(observer["pluginId"] == "memory-core" and observer["restored"] is True,
             "the original passive memory capability observer was not restored")
    _same(observer["calls"], [call for operation in raw["operations"] for call in operation["memoryPromptCalls"]],
          "an actual memory-builder invocation was dropped")
    _same(raw["toolCalls"], [call for operation in raw["operations"] for call in operation["toolCalls"]],
          "a genuine passive tool observation was dropped")
    _same([row["operation"] for row in raw["closeReceipts"]], list(CLOSE_OWNERS),
          "an actual original lifecycle owner was not closed")
    _require(all("returnValue" in row and "error" not in row for row in raw["closeReceipts"]),
             "an actual original lifecycle close failed")
    captures = _physical_native(raw)
    _custody(case, raw, captures, True)
    for index, operation in enumerate(raw["operations"]):
        if operation["operation"]["op"] == "reopen":
            continue
        specification = operation["operation"]
        params = operation["callArguments"][0]
        runs = [call for call in raw["calls"] if call.get("operationIndex") == index
                and call["operation"] == "OpenClawAgentHarness.runAttempt"]
        _require(len(runs) == 1, "the actual original harness invocation is missing or duplicated")
        _same(runs[0]["arguments"], operation["callArguments"], "the original harness received different real arguments")
        _same(params["prompt"], specification["effectivePrompt"], "the actual original effective prompt changed")
        fragments = list(specification["fragments"])
        if specification["includeClock"]:
            fragments.append({"kind": "runtime-instruction", "text": operation["clockCall"]["returnValue"]["value"]["timeLine"]})
        _same(params["runtimeContextFragments"], fragments, "the original runtime fragments were changed before submission")
        for name in ("transcriptPrompt", "currentInboundContext", "suppressNextUserMessagePersistence"):
            _same(params.get(name), specification.get(name), "a literal original prompt boundary argument changed")
        _require(params["runId"] == "prompt-runtime-" + str(index), "the real original turn identity changed")
        recorder = operation["userTurnRecorder"]
        text = specification.get("transcriptPrompt", specification["effectivePrompt"])
        # Check the predeclared optional host-recorder profile; this does not
        # construct a prompt projection or fabricate a recorder return.
        supplied = bool(js_trim(text))
        _same(recorder["transcriptInputText"], text, "the optional original recorder received different host text")
        _require(recorder["supplied"] is supplied and recorder["parameterPresent"] is supplied
                 and ("userTurnTranscriptRecorder" in params) is supplied,
                 "the original optional human-recorder admission profile changed")
        factory = [call for call in raw["calls"] if call.get("operationIndex") == index
                   and call["operation"] == "createUserTurnTranscriptRecorder"]
        _require(len(factory) == int(supplied), "the real optional recorder factory call was invented or omitted")
        if supplied:
            _same(recorder["input"], {"text": text, "idempotencyKey": "prompt-runtime-" + str(index),
                                      "timestamp": specification["nowMs"]}, "actual original recorder input changed")
            _require(recorder["owner"] == "createUserTurnTranscriptRecorder" and "after" in recorder,
                     "the real supplied recorder lacks its original owner/readback")
        else:
            _require(set(recorder) == {"supplied", "transcriptInputText", "parameterPresent"},
                     "the absent original human recorder acquired a fabricated result")
        _require(all(row["operationIndex"] == index and row["timestamp"] == specification["nowMs"]
                     for row in operation["toolCalls"]), "an actual passive tool observation changed operation/clock")
        if specification.get("scriptedTools"):
            _require(operation["indexPreparation"]["utimes"] and "syncReturn" in operation["indexPreparation"],
                     "real recall omitted the original source clock/index preparation")
            for receipt in operation["indexPreparation"]["utimes"]:
                _require(receipt["mtimeMs"] == case["input"]["fileMtimeMs"]
                         and int(receipt["after"]["mtimeNs"]) == case["input"]["fileMtimeMs"] * 1_000_000,
                         "the actual original index source mtime differs from its fixture")
            _require(operation["recallDrain"]["importPath"] == "dist/short-term-promotion-record-CEpBdgKW.mjs"
                     and operation["recallDrain"]["preparationReturn"] == {"type": "undefined"},
                     "the real original recall FIFO barrier is missing")
    _operations(case, raw, public, True)


def validate_pair(case, native_raw, sdk_raw, native_public, sdk_public, sdk_directory):
    validate_native(case, native_public, [native_raw], Path(native_raw["fixtureBase"]).parent)
    directory = Path(sdk_directory).resolve()
    raw_file = directory / "python-raw.json"
    _require(not raw_file.is_symlink(), "the actual SDK raw capture is a symbolic link")
    retained = json.loads(raw_file.read_text())
    _require(isinstance(retained, list) and len(retained) == 1, "the SDK raw file lost its exact singleton carrier")
    _same(retained[0], sdk_raw, "the supplied SDK raw differs from retained disk bytes")
    _same(sdk_raw["input"], case["input"], "the complete SDK input changed")
    _require(sdk_raw["closed"] is True, "the SDK prompt owner was not closed")
    _same(sdk_raw["fixtureRoot"], str(directory / "sdk-fixture"), "the actual SDK fixture escaped its owner")
    _same(sdk_raw["workspace"], str(directory / "sdk-fixture" / "workspace"), "the actual SDK workspace escaped its owner")
    _same(sdk_raw["databasePaths"], {name: str(directory / "sdk-fixture" / (name + ".sqlite"))
                                    for name in ("catalog", "index", "trust")}, "an actual SDK SQL handle escaped its owner")
    _same(sdk_raw["catalogDatabasePath"], sdk_raw["databasePaths"]["catalog"], "the actual SDK catalog path changed")
    _same(sdk_raw["host"], {"timezone": HOST_TIMEZONE, "timeFormat": HOST_TIME_FORMAT}, "SDK explicit host facts changed")
    owners = sdk_raw["owners"]
    required = {"HostSessionRunner.run_turn", "HostSessionRunner._prepare_model_prompt", "HostTurn.model_request",
                "HostTurn.record_message", "HostTurn.dispatch", "HostKit.before_turn", "HostKit.dispatch",
                "MemorySessionCatalog.read_continuation", "MemorySessionCatalog.read_transcript",
                "MemorySessionCatalog.append_message", "Memory.from_workspace", "SQLiteMemoryStore.reindex",
                "ModelPrompt", "normalize_model_messages", "build_prompt_section", "resolve_cron_style_now",
                "project_runtime_context_fragments", "resolve_runtime_context_prompt_parts", "TurnToolDispatcher.dispatch",
                "sanitize_tool_call_ids", "resolve_memory_search_source_policy",
                "serialize_model_tool_json", "_js_number_to_string", "_search_debug"}
    _require({owner["name"] for owner in owners} == required and len(owners) == len(required),
             "an actual SDK production owner is absent or duplicated")
    for owner in owners:
        path = Path(owner["path"])
        _require(path.is_relative_to(ROOT / "memory_core") and path.is_file() and not path.is_symlink(),
                 "an actual SDK owner escaped production source")
        _same(hashlib.sha256(path.read_bytes()).hexdigest(), owner["sha256"], "an SDK production owner changed")
    captures = _sdk_physical(sdk_raw, directory)
    _require(len(captures) == len(sdk_raw["operations"]) + 1, "an actual SDK physical phase is missing")
    for index, (capture, reference) in enumerate(zip(captures, sdk_raw["physical"], strict=True)):
        _same(capture["root"], sdk_raw["fixtureRoot"], "the SDK physical root changed")
        label = "initial" if index == 0 else f"operation-{index - 1:03d}"
        _same(Path(reference["path"]).name, "physical-" + label + ".json", "the SDK physical phase order changed")
        files = _files(capture)
        _tables(capture, files)
    _custody(case, sdk_raw, captures, False)
    policy = sdk_raw["sourcePolicy"]
    _require(set(policy) == {"configuredSources", "rememberAcrossConversations", "configuredSessionMemory", "resolved"},
             "the complete actual SDK source-policy observation changed shape")
    native_policy = native_raw["config"]["memory"]["search"]
    _same(policy["configuredSources"], native_policy["sources"], "SDK source selection differs from actual Native host config")
    _same(policy["rememberAcrossConversations"], native_policy["rememberAcrossConversations"],
          "SDK cross-conversation policy differs from actual Native host config")
    _same(policy["configuredSessionMemory"], native_policy["experimental"]["sessionMemory"],
          "SDK session-memory policy differs from actual Native host config")
    _same({key: value for key, value in policy.items() if key != "resolved"}, {
        "configuredSources": ["memory"], "rememberAcrossConversations": False, "configuredSessionMemory": False},
        "the predeclared real memory-only host source facts changed")
    _same(policy["resolved"], {"sources": ["memory"], "searchSources": ["memory"], "sessionMemory": False},
          "the complete actual SDK source policy does not reflect the literal Native host facts")
    _same(sdk_raw["sourcePolicyCall"]["arguments"], {
        "configured_sources": ["memory"], "remember_across_conversations": False, "configured_session_memory": False},
        "the real public source-policy resolver received different host facts")
    _same(sdk_raw["sourcePolicyCall"]["returnValue"], policy["resolved"],
          "the actual public source-policy resolver return was rewritten")
    _same(sdk_raw["workspaceIndexSources"], ["memory"], "the initial actual SDK workspace source scope changed")
    for state, capture in zip(sdk_raw["states"], captures, strict=True):
        _same(state["workspaceIndexSources"], ["memory"], "the actual SDK workspace index admitted session sources")
        for database in (state["sql"]["index"], _physical_database(capture, sdk_raw["databasePaths"]["index"])):
            rows = _sql(database).get("chunks")
            _require(isinstance(rows, list) and all(row.get("source") == "memory" for row in rows),
                     "the actual SDK index contains a source excluded by its real host policy")
    _require(len(sdk_raw["mtimeWrites"]) == len(case["input"]["files"]), "a real SDK source mtime write is missing")
    for receipt in sdk_raw["mtimeWrites"]:
        _require(receipt["owner"] == "os.utime" and receipt["arguments"]["ns"] == [case["input"]["fileMtimeMs"] * 1_000_000] * 2,
                 "the SDK source clock write differs from its literal fixture")
        target = receipt["arguments"]["path"]
        witnesses = [row for row in receipt["sourcesAfter"] if row["absolutePath"] == target]
        _require(len(witnesses) == 1 and int(witnesses[0]["identity"]["mtimeNs"]) == case["input"]["fileMtimeMs"] * 1_000_000,
                 "the actual SDK source mtime write did not reach its file")
    clock = sdk_raw["clock"]
    _require(set(clock["restored"]) == {"timeNs", "time", "monotonic", "sleep", "temporalDecayDatetime", "profiler"}
             and all(value is True for value in clock["restored"].values())
             and set(clock["inheritedDatetimeMethodsUnchanged"]) == {"fromtimestamp", "timestamp", "isoformat", "astimezone"}
             and all(value is True for value in clock["inheritedDatetimeMethodsUnchanged"].values()),
             "the SDK clock/profiler changed scheduler time or was not restored")
    requested = [case["input"]["nowMs"], *(operation["nowMs"] for operation in case["input"]["operations"])]
    _require(len(clock["reads"]) == len(requested), "an actual SDK operation clock read is missing")
    for index, (reading, now) in enumerate(zip(clock["reads"], requested, strict=True)):
        _require(reading["phase"] == ("initial" if index == 0 else "operation")
                 and reading["operationIndex"] == (None if index == 0 else index - 1)
                 and reading["requestedNowMs"] == reading["timeMs"] == reading["temporalDecayNowMs"] == now
                 and reading["timeNs"] == now * 1_000_000
                 and reading["monotonicUnchanged"] is True and reading["sleepUnchanged"] is True,
                 "the SDK actual wall clock differs from the paired original clock")
    for index, operation in enumerate(sdk_raw["operations"]):
        specification = operation["operation"]
        if specification["op"] == "reopen":
            continue
        _same(operation["sourcePolicy"], policy["resolved"], "the actual SDK memory client lost its complete source policy")
        _same(operation["workspaceIndexSources"], ["memory"], "the submitted SDK workspace admitted session index sources")
        _require(operation["modelPromptClosed"] is True, "the actual SDK transient model owner was not closed")
        arguments = operation["callArguments"]
        _same(arguments["user_message"], specification["effectivePrompt"], "the actual SDK effective prompt changed")
        _same(arguments["request_id"], "prompt-runtime-" + str(index), "the actual SDK turn identity changed")
        _same(arguments["prompt_context"], {
            "fragments": specification["fragments"], "transcript_prompt": specification.get("transcriptPrompt"),
            "current_inbound_context": specification.get("currentInboundContext"),
            "suppress_next_user_message_persistence": specification.get("suppressNextUserMessagePersistence", False),
            "offered_tool_names": specification["tools"], "citations_mode": specification["citationsMode"],
            "timezone": specification.get("timezone"), "host_timezone": HOST_TIMEZONE,
            "host_time_format": HOST_TIME_FORMAT, "include_clock": specification["includeClock"],
            "append_only_runtime_context": False, "tool_call_id_mode": "strict"},
              "an actual SDK prompt owner input was rewritten")
        registered = operation["registeredTools"]
        _same(registered, sdk_raw["registeredTools"], "an actual SDK registered tool definition changed")
        by_name = {tool["name"]: tool for tool in registered}
        _require(len(by_name) == len(registered) and set(TOOL_NAMES) <= set(by_name), "the actual SDK registry lost capabilities")
        for call in operation["providerCalls"]:
            _same(call["request"]["context"]["tools"], [by_name[name] for name in specification["tools"]],
                  "provider-offered SDK tools differ from the actual registered definitions")
    _operations(case, sdk_raw, sdk_public, False)
    return native_public, sdk_public
