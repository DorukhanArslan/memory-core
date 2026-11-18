"""Compact frozen inputs for both original history-repair conditions.

These are damaged durable inputs, never expected repaired messages. Every leaf
is submitted through the real host/model boundary on both sides.
"""
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json

OPERATION = "prompt-history-repair-runtime"
REQUIREMENT = "prompt.history-repair"
POINTS = ("prompt.history-repair.outcomes", "prompt.history-repair.boundaries")
NOW = 1_767_225_600_000
SESSION_KEY = "agent:main:telegram:direct:history-peer"
SESSION_ID = "prompt-history-session"
TOOL_NAMES = ("memory_search", "memory_get", "sessions_search", "sessions_history", "session_status")
MODEL = {"id": "fixture-model", "api": "openai-completions",
         "provider": "fixture-prompt-runtime-model", "reasoning": False}
RESPONSES_MODEL = {**MODEL, "id": "fixture-responses-model", "api": "openai-responses"}
POLICY = (
    "Compare every whole ordered message from every actual provider callback, "
    "including all surviving content, call/result ids, signatures, usage and "
    "metadata. Retain complete raw requests, replies, errors, source-owned "
    "history stages, resolved model/policy/configuration, durable events, SQL "
    "and physical files. Authenticate original seed events and preserve every "
    "existing durable event exactly through attempts and reopen; repaired "
    "model context and synthetic missing results must not overwrite history. "
    "No message or field is discarded by comparison to hide a difference. "
    "Exact JSON numbers compare with booleans distinct and no tolerance."
)
DRIVER_SCOPE = (
    "Genuine original OpenClaw embedded harness attempts and production SDK "
    "HostSessionRunner/model_request callbacks over actual SQLite catalogs. "
    "The offline provider supplies literal assistant text/tool requests and "
    "genuine memory_get runs against a literal source; it does not repair or "
    "compose history. Two unowned provider transport "
    "fallbacks, openai-completions and openai-responses, explicit model metadata, "
    "UTC and configured 24-hour display, session projection version 4, and "
    "sequential ordinary attempts are fixed. Replay policy and history limits "
    "are derived from model, channel configuration and route facts. Windowing "
    "covers disabled limits, the 1.5x cushion/batch boundary at three/four/five "
    "prior user turns for limit two, and a genuine canonical compaction-summary "
    "prelude; it does not claim execution of the compaction lifecycle. Signed "
    "Anthropic/Google signature transforms, media transformations, reset-retained "
    "symbol preludes, compaction replay checkpoints, bundled provider hooks, "
    "transport-wire conversion after the callback, concurrency, retries and "
    "external model acceptance are outside this bounded family. Only the "
    "complete frozen integrated family and authenticated physical/source "
    "evidence may earn the two original points atomically."
)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf8")


def case_wire(case):
    return canonical({key: case[key] for key in ("id", "operation", "input")})


def _iso(now):
    return datetime.fromtimestamp(now / 1000, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _usage():
    return {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0,
            "totalTokens": 0, "cost": {"input": 0, "output": 0, "cacheRead": 0,
                                        "cacheWrite": 0, "total": 0}}


def _user(text):
    return {"role": "user", "content": text}


def _assistant(content, *, stop="toolUse", model=None, **metadata):
    model = model or MODEL
    return {"role": "assistant", "content": deepcopy(content), "api": model["api"],
            "provider": model["provider"], "model": model["id"], "usage": _usage(),
            "stopReason": stop, **metadata}


def _text(text, **metadata):
    return {"type": "text", "text": text, **metadata}


def _call(identifier, *, name="memory_get", arguments=None, **fields):
    return {"type": "toolCall", "id": identifier, "name": name,
            "arguments": {"path": "MEMORY.md"} if arguments is None else arguments, **fields}


def _result(identifier, text, *, name="memory_get", **metadata):
    return {"role": "toolResult", "toolCallId": identifier, "toolName": name,
            "content": [_text(text)], "isError": False, **metadata}


def _events(messages):
    events = []
    for index, message in enumerate(messages):
        now = NOW - 60_000 + index * 100
        events.append({"type": "message", "id": f"history-seed-{index}",
                       "parentId": events[-1]["id"] if events else None,
                       "timestamp": _iso(now), "message": {**deepcopy(message), "timestamp": now}})
    return events


def _submit(text="historycurrentcedar requests a fresh answer.", **fields):
    return {"op": "submit", "prompt": text, "tools": list(TOOL_NAMES), **fields}


def _base(messages, *, model=None, limit=None, operations=None, prelude=False):
    events = _events(messages)
    if prelude:
        events.append({"type": "compaction", "id": "history-compaction-prelude",
                       "parentId": events[-1]["id"], "timestamp": _iso(NOW - 1000),
                       "summary": "historypreludecedar is retained summarized context.",
                       "tokensBefore": 1000, "firstKeptEntryId": events[0]["id"]})
    operations = operations or [_submit(), {"op": "reopen"},
                                _submit("historyresumecedar replays the original damaged durable facts.")]
    return {"kind": "prompt-history-repair", "identity": "openclaw", "nowMs": NOW,
            "hostTimezone": "UTC", "hostTimeFormat": "24", "sessionVersion": 4,
            "sessionKey": SESSION_KEY, "sessionId": SESSION_ID, "files": {},
            "transcriptEvents": events, "model": deepcopy(model or MODEL),
            "channelConfig": {} if limit is None else {"telegram": {"dmHistoryLimit": limit}},
            "route": {"accountId": "default", "peerId": "history-peer", "chatType": "direct"},
            "operations": [{"nowMs": NOW + index * 1000, **deepcopy(operation)}
                           for index, operation in enumerate(operations)]}


def _pairing():
    synthetic = _result("replace!cedar", "[openclaw] missing tool result in session history; inserted synthetic error result for transcript repair.",
                        isError=True, details={"openclawSyntheticMissingToolResult": True})
    value = _base([
        _user("pairingcedar original durable request."),
        _result("orphan!cedar", "orphancedar must remain only in durable history."),
        _assistant([_call("missing!cedar"), _call("late!cedar"), _call("replace!cedar")]),
        synthetic, _result("replace!cedar", "realreplacementcedar", details={"retainedSecret": "detailcedar"}),
        _user("displacedcedar remains ordinary user data."),
        _result("late!cedar", "laterealcedar"), _result("late!cedar", "duplicateresultcedar"),
        _assistant([_text("pairingtailcedar remains visible.")], stop="stop"),
    ], operations=[_submit(scriptedTools=[{"id": "livegetcedar", "name": "memory_get",
         "arguments": {"path": "memory/history-live.md", "from": 1, "lines": 20}}]),
         {"op": "reopen"}, _submit("historyresumecedar replays the original damaged durable facts.")])
    value["files"] = {"memory/history-live.md": "livegetpayloadcedar is an actual grounded source.\n"}
    return value


def _occurrences():
    return _base([
        _user("occurrencecedar original request."),
        _assistant([_call("same!cedar"), _call("same!cedar")]),
        _result("same!cedar", "samefirstcedar"), _result("same!cedar", "samesecondcedar"),
        _user("repeatnextcedar"), _assistant([_call("repeat!cedar")]),
        _assistant([_call("repeat!cedar")]), _result("repeat!cedar", "localrepeatcedar"),
        _result("repeat!cedar", "ambiguousextracedar"),
        _user("occurrencetailcedar"), _assistant([_text("occurrencetailanswercedar")], stop="stop"),
    ])


def _invalid():
    invalid = [_call("valid!cedar", name=" memory_get "),
               {"type": "toolCall", "id": "noinputcedar", "name": "memory_get"},
               _call("", name="memory_get"), _call("badnamecedar", name="bad name"),
               _call("unavailablecedar", name="retired_history_tool"),
               _call("nullinputcedar", arguments=None, input=None),
               _call("streamcedar", partialJson='{"path":'),
               _text("invalidsurvivorcedar remains visible.")]
    invalid[5]["arguments"] = None
    return _base([
        _user("invalidcedar original request."), _assistant(invalid),
        _result("valid!cedar", "validresultcedar"),
        _assistant([_call("completedcedar", name="retired_history_tool")]),
        _result("completedcedar", "completedremovedcedar", name="retired_history_tool"),
        _user("invalidtailcedar"), _assistant([_text("invalidtailanswercedar")], stop="stop"),
    ])


def _failed():
    return _base([
        _user("failedcedar original request."),
        _assistant([_call("failedsharedcedar")]),
        _assistant([_call("failedsharedcedar"), _text("failedframecedar")], stop="error"),
        _result("failedsharedcedar", "failedoutputcedar"),
        _assistant([_call("abortedcedar"), _text("abortedframecedar")], stop="aborted"),
        _result("abortedcedar", "abortedoutputcedar"),
        _assistant([_text("textonlyerrorcedar remains real text.")], stop="error"),
        _assistant([_text("[assistant turn failed before producing content]")], stop="error"),
        _assistant([{"type": "thinking", "thinking": "incompletereasoningcedar",
                     "thinkingSignature": "partialcedar"}], stop="length"),
        _assistant([_text("visiblelengthcedar")], stop="length"),
        _assistant([_text("NO_REPLY")], stop="stop"),
        _assistant([_text("mirroronlycedar")], stop="stop",
                   model={**MODEL, "provider": "openclaw", "id": "delivery-mirror"}),
        _user("failedtailcedar"), _assistant([_text("failedtailanswercedar")], stop="stop"),
    ])


def _window(limit):
    messages = []
    for index in range(3 if limit else 5):
        messages.extend([_user(f"historyturn{index}cedar old user."),
                         _assistant([_text(f"historyanswer{index}cedar")], stop="stop")])
    return _base(messages, limit=limit, prelude=True, operations=[
        _submit("historynew0cedar"), _submit("historynew1cedar"), {"op": "reopen"},
        _submit("historynew2cedar")])


def _responses_ids():
    reasoning = {"type": "thinking", "thinking": "responsepairreasoningcedar",
                 "thinkingSignature": '{"id":"rs_paircedar","type":"reasoning","encrypted_content":"opaque-paircedar"}'}
    long_id = "call_" + "longcedar" * 12 + "|fc_" + "longitemcedar" * 8
    return _base([
        _user("responsesidscedar original request."),
        _assistant([reasoning, _call("call_paircedar|fc_paircedar", partialJson='{"path":"MEMORY.md"}')], model=RESPONSES_MODEL),
        _result("call_paircedar|fc_paircedar", "responsepairedresultcedar"),
        _assistant([_call("call_noreasoncedar|fc_noreasoncedar"), _call(long_id),
                    _call("bad id!cedar|bad item!cedar"),
                    _call("call_partialcedar|fc_partialcedar", partialJson='{"path":'),
                    _text("responsesurvivorcedar")], model=RESPONSES_MODEL),
        _result(long_id, "longresultcedar"),
        _user("responseidstailcedar"),
        _assistant([_text("responseidstailanswercedar")], stop="stop", model=RESPONSES_MODEL),
    ], model=RESPONSES_MODEL)


def _responses_metadata():
    thinking = {"type": "thinking", "thinking": "replayreasoningcedar",
                "thinkingSignature": '{"id":"rs_replaycedar","type":"reasoning","encrypted_content":"opaquereplaycedar"}'}
    value = _base([
        _user("responsesmetadatacedar original request."),
        _assistant([thinking, _text("replayvisiblecedar", textSignature='{"v":1,"id":"msg_replaycedar","phase":"commentary"}'),
                    _call("call_replaycedar|fc_replaycedar")], model=RESPONSES_MODEL),
        _result("call_replaycedar|fc_replaycedar", "replayresultcedar"),
        _user("replaytailcedar"), _assistant([_text("replaytailanswercedar")], stop="stop", model=RESPONSES_MODEL),
    ], model=RESPONSES_MODEL, operations=[_submit("samemodelcedar"),
        _submit("switchedmodelcedar", model={**RESPONSES_MODEL, "id": "fixture-responses-switched"}),
        {"op": "reopen"}, _submit("switchresumecedar")])
    snapshot = {"type": "custom", "id": "history-model-snapshot", "parentId": value["transcriptEvents"][-1]["id"],
                "timestamp": _iso(NOW - 500), "customType": "model-snapshot",
                "data": {"timestamp": NOW - 60_000, "provider": RESPONSES_MODEL["provider"],
                         "modelApi": RESPONSES_MODEL["api"], "modelId": RESPONSES_MODEL["id"]}}
    value["transcriptEvents"].append(snapshot)
    return value


_BUILDERS = (
    ("pairing", _pairing), ("occurrences", _occurrences), ("invalid-calls", _invalid),
    ("failed-turns", _failed), ("window-batches", lambda: _window(2)),
    ("window-disabled", lambda: _window(0)), ("responses-ids", _responses_ids),
    ("responses-metadata", _responses_metadata),
)
CASE_HASHES = {
    "prompt-history-repair-pairing": "a28786cb120a4a6a8ce7dfd14d7071b2f3be16785da26d685fe6caaab9c2189a",
    "prompt-history-repair-occurrences": "f59708614dbf64a63105ad91c1cdb9a8eace1966094f2785ecfd3447d79f71e5",
    "prompt-history-repair-invalid-calls": "2dfb7b926dc6772f4220818ea1dc2740424f983f6cef1a559bb64c58f28493b4",
    "prompt-history-repair-failed-turns": "4d45c183e6072061ba2643fccca00c33d0840e25e3a0c95ae2efd50b5717da47",
    "prompt-history-repair-window-batches": "f133dbc16750d8cc12cb431057488dbccca550149e8ae711ef48ae580a05c19e",
    "prompt-history-repair-window-disabled": "82f659c5529146a7778f40f03bd58b21702ba89d59ca7e42530c20ce06ca58ce",
    "prompt-history-repair-responses-ids": "0c32dcf34191b13440c8d83c77afaa174e487a328cd32b24e30365966c9180ee",
    "prompt-history-repair-responses-metadata": "516f22acd2cc76eb2cfa6e2a2002933b77f6ab6adf84edb57120a956936fd3a6",
}

# Presence/absence guards are independent fixture custody assertions. They are
# never used to construct the repaired packet or replace either engine's result.
EVIDENCE = {
    "pairing": {"required": ["realreplacementcedar", "laterealcedar", "displacedcedar"],
                "excluded": ["orphancedar", "duplicateresultcedar", "detailcedar"]},
    "occurrences": {"required": ["samefirstcedar", "samesecondcedar", "localrepeatcedar"],
                    "excluded": ["ambiguousextracedar"]},
    "invalid-calls": {"required": ["invalidsurvivorcedar", "validresultcedar", "completedremovedcedar"],
                      "excluded": ["noinputcedar", "badnamecedar", "unavailablecedar", "nullinputcedar", "streamcedar"]},
    "failed-turns": {"required": ["textonlyerrorcedar", "visiblelengthcedar"],
                     "excluded": ["failedframecedar", "failedoutputcedar", "abortedframecedar", "abortedoutputcedar",
                                  "incompletereasoningcedar", "mirroronlycedar", "[assistant turn failed before producing content]"]},
    "window-batches": {"required": ["historypreludecedar"]},
    "window-disabled": {"required": ["historypreludecedar", "historyturn0cedar", "historyturn4cedar"]},
    "responses-ids": {"required": ["responsepairreasoningcedar", "responsepairedresultcedar", "longresultcedar", "responsesurvivorcedar"],
                      "excluded": ["call_partialcedar", "partialJson"]},
    "responses-metadata": {"required": ["replayvisiblecedar", "replayresultcedar"]},
}


def _definitions():
    return [{"id": "prompt-history-repair-" + suffix, "operation": OPERATION,
             "requirement": REQUIREMENT, "covers": list(POINTS), "input": builder(),
             "normalizationPolicy": POLICY, "driverScope": DRIVER_SCOPE}
            for suffix, builder in _BUILDERS]


def build_cases():
    cases = _definitions()
    if {case["id"]: hashlib.sha256(case_wire(case)).hexdigest() for case in cases} != CASE_HASHES:
        raise ValueError("The complete frozen history-repair family changed")
    return cases


def validate_case(case):
    expected = next((value for value in build_cases() if value["id"] == case.get("id")), None)
    if expected is None or canonical(case) != canonical(expected):
        raise ValueError("History repair requires its exact complete frozen definition")
    return deepcopy(case)


def validate_input(value):
    if not any(canonical(value) == canonical(case["input"]) for case in build_cases()):
        raise ValueError("History repair requires an exact frozen common input")


def family_members(cases):
    return [case for case in cases if case.get("operation") == OPERATION
            or str(case.get("id", "")).startswith("prompt-history-repair-")
            or set(case.get("covers", ())) & set(POINTS)]


def validate_registration(cases):
    family = family_members(cases)
    if family:
        if [case.get("id") for case in family] != [case["id"] for case in build_cases()]:
            raise ValueError("History repair requires all eight cases once in frozen order")
        for case in family:
            validate_case(case)


def family_complete(rows):
    family = family_members(rows)
    if [row.get("id") for row in family] != [case["id"] for case in build_cases()]:
        return False
    try:
        for row in family:
            validate_case({key: row[key] for key in ("id", "operation", "requirement", "covers", "input",
                                                     "normalizationPolicy", "driverScope")})
            if row.get("status") != "matched" or row.get("runtimeEvidenceValidated") is not True:
                return False
        return True
    except (KeyError, TypeError, ValueError):
        return False
