"""Authenticate notice observations without prescribing a warning or a match.

The registered four-case inputs and whole public carriers retain their original
guards.  This zero-credit observer distinguishes Native's source-bound capture
edge from the SDK's directly inspected closure and actual reader invocations.
It executes no program, executable or expression supplied by captured data.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from equivalence.host_turn_barrier import CASE_HASHES, validate_case
from equivalence.host_turn_barrier_evidence import (
    _native as _original_native, _same, _sdk as _original_sdk, require,
    validate_result,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/next_turn_notice_observation_contract.json"
CONTRACT_SHA256 = "bceed5c96344270816f676d27fa02117370b714d69c6b1cc492aab7b5cb98585"


def _one(rows, predicate, message):
    matches = [row for row in rows if predicate(row)]
    require(len(matches) == 1, "notice " + message)
    return matches[0]


def _index(rows, key, message):
    require(isinstance(rows, list) and all(isinstance(row, dict) and row.get(key) is not None for row in rows),
            "notice " + message)
    result = {row[key]: row for row in rows}
    require(len(result) == len(rows), "notice duplicated " + message)
    return result


def _scalar(value):
    require(isinstance(value, dict) and type(value.get("sequencePresent")) is bool
            and type(value.get("warningPresent")) is bool,
            "notice primitive scalar observation is absent")
    if value["sequencePresent"]:
        require(type(value.get("sequence")) is int and value["sequence"] >= 0,
                "notice actual sequence is not a nonnegative original integer")
    if value["warningPresent"]:
        require(isinstance(value.get("warning"), str), "notice original warning is not a string")
    return value


def _sample(call, phase, *, native):
    value = call[phase + "Notice"]
    return None if value is None else _scalar(value if native else value["noticeScalar"])


def _header(case, raw, *, native, approved_reference=None, approved_runtime=None):
    validate_case(case)
    require(hashlib.sha256(CONTRACT.read_bytes()).hexdigest() == CONTRACT_SHA256,
            "notice independently frozen observation contract changed")
    contract = json.loads(CONTRACT.read_text())
    observed = raw["noticeObservations"]
    require(observed["version"] == 1 and observed["contractSha256"] == CONTRACT_SHA256
            and observed["caseWireSha256"] == CASE_HASHES[case["id"]]
            and observed["pid"] == raw["pid"] and observed["ppid"] == raw["ppid"]
            and type(observed["installSequence"]) is int and observed["installSequence"] >= 0
            and str(observed["installAtNs"]).isdigit()
            and not observed.get("observerFailures"),
            "notice observer contract/input/process/install authority is detached")
    actor = ROOT / ("equivalence/host-turn-barrier-runtime.mjs" if native else "equivalence/host_turn_barrier_sdk.py")
    require(hashlib.sha256(actor.read_bytes()).hexdigest() == observed["instrumentedActorSha256"],
            "notice capture belongs to another instrumented caller generation")
    pinned = {row["path"]: row["sha256"] for row in contract["sourceAuthority"]}
    for group in ("originalSourceBindings", "compiledBindings"):
        rows = observed[group]
        require(isinstance(rows, list) and (rows or not native and group == "compiledBindings"),
                "notice original source authority is missing")
        for row in rows:
            path = Path(row["path"])
            if native:
                require(not path.is_absolute() and pinned.get(row["path"]) == row["sha256"],
                        "notice original Native source/compiled authority is not independently pinned")
                if group == "originalSourceBindings":
                    prefix = "work/openclaw-v2026.9.9/"
                    require(row["path"].startswith(prefix), "notice original logical source pin escaped its reference tree")
                    selected = approved_reference or os.environ.get("MEMORY_NEXT_TURN_NOTICE_REFERENCE_ROOT")
                    base = Path(selected) if selected else ROOT / "work/openclaw-v2026.9.9"
                    path = base.resolve(strict=True) / row["path"][len(prefix):]
                else:
                    prefix = ".reference/release-runtime/node_modules/openclaw/"
                    require(row["path"].startswith(prefix), "notice compiled logical source pin escaped its original package")
                    selected = approved_runtime or os.environ.get("MEMORY_NEXT_TURN_NOTICE_RUNTIME_ROOT")
                    base = Path(selected) if selected else ROOT / ".reference/release-runtime/node_modules/openclaw"
                    path = base.resolve(strict=True) / row["path"][len(prefix):]
            else:
                require(path.is_absolute() and path.is_relative_to(ROOT / "memory_core")
                        and path.suffix == ".py", "notice SDK imported a source outside the current production tree")
            require(path.is_file() and path.resolve() == path and not path.is_symlink()
                    and hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"],
                    "notice actual original source bytes changed")
    return observed


def _clock(raw, observed, *, native):
    events = _index(observed["events"], "sequence", "original observation event sequence")
    require(events, "notice original observation events missing")
    rows = sorted(events.values(), key=lambda row: row["sequence"])
    require(all(type(row["sequence"]) is int and str(row["atNs"]).isdigit()
                and row["sequence"] >= observed["installSequence"]
                and int(row["atNs"]) >= int(observed["installAtNs"]) for row in rows),
            "notice observed event precedes actual installation or lost monotonic time")
    # Existing synchronous snapshots allocate real sequence numbers too.  Neither
    # namespace is required to be contiguous and no artificial yield is inferred.
    original = _index(raw["events"], "sequence", "whole-host event sequence")
    for seq in set(events) & set(original):
        require(_same(events[seq], original[seq]), "notice shared event clock reused a sequence for another event")
    threads = {row.get("threadId", 0) for row in rows}
    for thread in threads:
        times = [int(row["atNs"]) for row in rows if row.get("threadId", 0) == thread]
        require(times == sorted(times), "notice per-thread original observations were reordered")
    return events


def _calls(observed, events, *, native):
    calls = _index(observed["calls"], "callId", "actual original calls")
    require(calls, "notice actual original calls missing")
    for call in calls.values():
        start, end = call["enterSequence"], call["returnSequence"]
        require(type(start) is type(end) is int and start < end and start in events and end in events
                and events[start]["callId"] == events[end]["callId"] == call["callId"]
                and events[start]["method"] == events[end]["method"] == call["method"]
                and events[start]["phase"] == "enter" and events[end]["phase"] in {"return", "error"}
                and call["originalInvocations"] == 1 and type(call["originalInvocations"]) is int,
                "notice original call interval/delegate count changed")
        if call["method"] not in {"_capture_rebuild_notice", "notice-reader"}:
            require(call["originalReceiverIsExactOwner"] is True,
                    "notice forwarding substituted the original receiver")
        before, after = _sample(call, "before", native=native), _sample(call, "after", native=native)
        if before is not None and after is not None:
            require(after["sequence"] >= before["sequence"], "notice original sequence moved backwards")
        parent = call.get("parentSynchronousCallId")
        if parent is not None:
            require(parent in calls and calls[parent]["enterSequence"] < start < end < calls[parent]["returnSequence"],
                    "notice synchronous call parent does not enclose the original invocation")
        if "errorRef" in call:
            require(events[end].get("errorRef") == call["errorRef"], "notice original thrown error identity changed")
    entered = [row for row in events.values() if row.get("phase") == "enter" and row.get("callId")]
    finished = [row for row in events.values() if row.get("phase") in {"return", "error"} and row.get("callId")]
    require(len(entered) == len(finished) == len(calls), "notice original invocation events were dropped")
    return calls


def _native(observed, calls, events, raw):
    managers = _index(observed["managers"], "managerRef", "actual Native managers")
    notices = _index(observed["notices"], "noticeRef", "actual Native notice objects")
    contexts = _index(observed["databaseContexts"], "databaseContextRef", "actual publication contexts")
    hooks = {(row["declaringPrototypeRef"], row["method"]): row for row in observed["hookDescriptors"]}
    require(len(hooks) == len(observed["hookDescriptors"])
            and {"status", "search", "syncAdmitted", "runSync", "recordAutomaticRebuild"}
            <= {row["method"] for row in hooks.values()}, "notice original Native prototype hooks missing")
    receipts = {(row["declaringPrototypeRef"], row["method"]): row for row in observed["restoreReceipts"]}
    require(set(receipts) == set(hooks) and all(row["restoredExactDescriptor"] is True for row in receipts.values()),
            "notice original Native descriptors were not restored")
    for key, hook in hooks.items():
        require(hook["originalFunctionRef"] != hook["observedFunctionRef"]
                and receipts[key]["originalFunctionRef"] == hook["originalFunctionRef"],
                "notice Native observer/original function identity was reassigned")
    increments = []
    for call in calls.values():
        key = call["declaringPrototypeRef"], call["method"]
        require(key in hooks and call["originalFunctionRef"] == hooks[key]["originalFunctionRef"],
                "notice Native invocation did not forward its declared original function")
        kind = call["kind"]
        if kind == "manager":
            require(call["managerRef"] in managers and call["receiverRef"] == call["managerRef"]
                    and call["noticeRef"] == managers[call["managerRef"]]["noticeRef"]
                    and call["noticeRef"] in notices,
                    "notice Native manager/live notice identity is detached")
        elif kind == "publication":
            require(call["databaseContextRef"] in contexts and call["receiverRef"] == call["databaseContextRef"],
                    "notice publication used another original database context")
        else:
            require(kind == "static" and call["receiverRef"] == call["declaringPrototypeRef"],
                    "notice original static manager acquisition receiver changed")
        if call.get("returnKind") == "promise":
            require(call["returnedExactOriginalPromise"] is True
                    and call["returnValue"] == {"privateType": "Promise", "ref": call["originalReturnRef"]}
                    and call["returnRef"] == call["originalReturnRef"]
                    and call["settlement"] in {"fulfilled", "rejected"}
                    and call["returnSequence"] < call["settleSeq"]
                    and events[call["settleSeq"]]["callId"] == call["callId"],
                    "notice original Native Promise was replaced or settlement omitted")
            if call["settlement"] == "rejected":
                require(call.get("settledErrorRef") and isinstance(call["settledError"], dict),
                        "notice original Native rejection was hidden")
        if call["method"] == "recordAutomaticRebuild":
            before, after = _sample(call, "before", native=True), _sample(call, "after", native=True)
            require(after["sequence"] == before["sequence"] + 1 and isinstance(call["callerStack"], str),
                    "notice real original rebuild increment is absent or detached")
            increments.append(call)
    statuses = _index(observed["statuses"], "callId", "actual original Native status returns")
    require(set(statuses) == {key for key, row in calls.items() if row["method"] == "status"},
            "notice original Native status return was omitted")
    for key, status in statuses.items():
        call = calls[key]
        require(status["statusRef"] == call["originalReturnRef"] and status["managerRef"] == call["managerRef"]
                and status["noticeRef"] == call["noticeRef"] and status["returnSeq"] == call["returnSequence"]
                and _same(status["notice"], call["afterNotice"]),
                "notice status copy was substituted for its actual original live notice")
    facts = []
    for edge in observed["captureEdges"]:
        status, search = statuses[edge["statusCallId"]], calls[edge["searchCallId"]]
        require(edge["kind"] == "source-bound-synchronous-edge" and edge["noDirectReaderClaim"] is True
                and search["method"] == "search" and status["managerRef"] == search["managerRef"]
                and edge["noticeRef"] == status["noticeRef"] == search["noticeRef"]
                and edge["capturedSequence"] == status["notice"]["sequence"]
                and edge["statusReturnSeq"] == status["returnSeq"] < edge["searchEnterSeq"] == search["enterSequence"]
                and "searchOnce" in status["callerStack"],
                "notice Native source-bound capture edge was relabelled or borrowed")
        between = [row for row in calls.values() if edge["statusReturnSeq"] < row["enterSequence"] < edge["searchEnterSeq"]]
        require(not between, "notice Native capture edge contains an intervening original invocation")
        changes = [row for row in increments if row["noticeRef"] == edge["noticeRef"]
                   and edge["searchEnterSeq"] < row["enterSequence"] < search.get("settleSeq", search["returnSequence"])]
        facts.append({"searchCallId": search["callId"], "noticeRef": edge["noticeRef"],
                      "capturedSequence": edge["capturedSequence"], "incrementCallIdsBeforeSearchSettlement": [row["callId"] for row in changes],
                      "captureKind": "source-bound-synchronous-edge", "lexicalReaderObserved": False,
                      "causeStatus": "observed-increment-inside-search" if changes else "inconclusive-until-tool-checkpoint"})
    require(facts, "notice Native actual public capture edge missing")
    return {"validated": True, "captureFacts": facts, "incrementCalls": len(increments),
            "warningPolicyChanged": False, "acceptancePointsAwarded": 0}


def _sdk(observed, calls, raw):
    refs = _index(observed["references"], "ref", "SDK actual object references")
    require(len({row["objectId"] for row in refs.values()}) == len(refs),
            "notice SDK gave a shared actual object multiple identities")
    hooks = {(row["targetRef"], row["name"]): row for row in observed["hookDescriptors"]}
    receipts = {(row["targetRef"], row["name"]): row for row in observed["restoration"]}
    require(len(hooks) == len(observed["hookDescriptors"]) and set(hooks) == set(receipts)
            and all(row["restoredExactOwnDescriptor"] is True
                    and (not row["inherited"] or row["observerInstanceAttributeAbsent"] is True)
                    for row in receipts.values()), "notice SDK observer descriptors were not restored")
    hook_functions = {row["originalFunctionRef"] for row in hooks.values()}
    captures = _index(observed["captures"], "captureCallId", "SDK exact original closure captures")
    require(captures, "notice SDK original closure captures missing")
    facts = []
    for key, capture in captures.items():
        call = calls[key]
        original, exposed = capture["originalReaderRef"], capture["observedReaderRef"]
        require(call["method"] == "_capture_rebuild_notice" and original != exposed
                and original in refs and exposed in refs and capture["noticeRef"] in refs
                and capture["closureFreevars"] == ["notice", "sequence"]
                and set(capture["closureCellRefs"]) == {"notice", "sequence"}
                and capture["closureCellRefs"]["notice"] == capture["noticeRef"]
                and _same(refs[capture["closureCellRefs"]["sequence"]]["primitiveValue"], capture["capturedSequence"])
                and call["returnRef"] == original and call["originalReaderRef"] == original
                and call["observedReaderRef"] == exposed and call["args"]["statusRef"] == capture["statusRef"],
                "notice SDK exact closure/exposed forwarding identity was substituted")
        _scalar(capture["noticeScalar"])
        readers = [row for row in calls.values() if row["method"] == "notice-reader" and row["captureCallId"] == key]
        require(readers, "notice SDK original warning reader was never actually invoked")
        for reading in readers:
            require(reading["originalReaderRef"] == reading["originalFunctionRef"] == original
                    and reading["observedReaderRef"] == exposed
                    and reading["capturedSequence"] == capture["capturedSequence"]
                    and call["returnSequence"] < reading["enterSequence"]
                    and reading["capturedNoticeBefore"]["noticeRef"] == reading["capturedNoticeAfter"]["noticeRef"] == capture["noticeRef"],
                    "notice SDK reader invoked another closure or was eagerly evaluated")
            before = _scalar(reading["capturedNoticeBefore"]["noticeScalar"])
            after = _scalar(reading["capturedNoticeAfter"]["noticeScalar"])
            stable = _same(before, after)
            if "errorRef" in reading:
                require(reading["errorRef"] in refs and "error" in refs[reading["errorRef"]],
                        "notice SDK original reader exception was replaced or omitted")
            elif stable:
                expected = before.get("warning") if before.get("sequence") != capture["capturedSequence"] else None
                require(_same(reading.get("returnPrimitive"), expected),
                        "notice SDK original reader return differs from its actual stable closure cells")
            facts.append({"captureCallId": key, "readerCallId": reading["callId"],
                          "noticeRef": capture["noticeRef"], "capturedSequence": capture["capturedSequence"],
                          "noticeIsOwnerObject": capture["noticeIsOwnerObject"],
                          "returnPrimitive": reading.get("returnPrimitive"),
                          "causeStatus": "exact-stable-original-reader-rule" if stable else "inconclusive-concurrent-notice-write"})
    for call in calls.values():
        if call["method"] == "notice-reader":
            require(call["captureCallId"] in captures, "notice SDK reader lacks an original capture")
        else:
            require(call["originalFunctionRef"] in hook_functions,
                    "notice SDK invocation did not forward a declared original function")
    return {"validated": True, "captureFacts": facts, "warningPolicyChanged": False, "acceptancePointsAwarded": 0}


def validate_observations(case, raw, *, native, approved_reference=None, approved_runtime=None):
    try:
        observed = _header(case, raw, native=native, approved_reference=approved_reference,
                           approved_runtime=approved_runtime)
        events = _clock(raw, observed, native=native)
        calls = _calls(observed, events, native=native)
        return _native(observed, calls, events, raw) if native else _sdk(observed, calls, raw)
    except (KeyError, IndexError, TypeError, AttributeError, json.JSONDecodeError, OSError) as error:
        raise ValueError("notice original observation custody is structurally incomplete") from error


def validate_capture(case, capture, result, *, native, approved_node=None, approved_reference=None, approved_runtime=None):
    # No V8 operation is required here.  In particular approved_node is never
    # selected from raw and no captured program/path is executed by this guard.
    validate_result(case, result)
    if native:
        _original_native(case, capture, result)
        raw = capture
    else:
        _original_sdk(case, capture, result)
        raw = capture["observation"]["raw"]
    return validate_observations(case, raw, native=native, approved_reference=approved_reference,
                                 approved_runtime=approved_runtime)


def validate_pair(case, native_raw, sdk_raw, native_result, sdk_result, *, approved_node=None,
                  approved_reference=None, approved_runtime=None):
    return {"validated": True,
            "native": validate_capture(case, native_raw, native_result, native=True, approved_node=approved_node,
                                       approved_reference=approved_reference, approved_runtime=approved_runtime),
            "sdk": validate_capture(case, sdk_raw, sdk_result, native=False),
            "acceptancePointsAwarded": 0}


def replay_case(case, directory, *, approved_node=None, approved_reference=None, approved_runtime=None):
    directory = Path(directory)
    original = json.loads((directory / "stdout.json").read_text())["result"]
    sdk = json.loads((directory / "sdk-output.json").read_text())
    natives = json.loads((directory / "evidence/native-raw.json").read_text())
    copies = json.loads((directory / "evidence/python-raw.json").read_text())
    require(len(natives) == len(copies) == 1, "notice replay requires exactly one original capture per engine")
    return validate_pair(case, natives[0], copies[0], original, sdk, approved_node=approved_node,
                         approved_reference=approved_reference, approved_runtime=approved_runtime)
