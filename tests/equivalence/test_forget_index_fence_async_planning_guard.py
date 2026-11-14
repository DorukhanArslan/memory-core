"""Pure admission tests; these synthetic controls supply no original evidence."""
from copy import deepcopy
import hashlib
import json

import pytest

from equivalence import forget_index_fence_evidence as guard
from equivalence.forget_index_fence_v5 import build_cases


@pytest.fixture(params=["stored", "direct"])
def planning_control(request, tmp_path, monkeypatch):
    name = request.param
    scenario = ("stored-promotion-model-plan-before-forget" if name == "stored"
                else "direct-absent-at-plan-retained-source-other-session-forgotten")
    case = next(row for row in build_cases() if row["input"]["scenario"] == scenario)
    declaration = case["input"]["gates"][0]
    label, boundary = declaration["callLabel"], declaration["boundary"]
    mode = ("deferred-original-model-completion" if name == "stored"
            else "deferred-original-realpath-return")
    pid, instance, command_id, watch_id = 101, 1, 14, 18
    scope = {"protocol": "async-local-original-command-v1", "commandId": command_id,
             "operation": "original-promotion", "label": label}
    def ns(seconds):
        return str(seconds * 1_000_000_000)
    identity = {"pid": pid, "threadId": 0, "actor": "promoter", "instance": instance}
    receipt = {**declaration, **identity, "sequence": 10, "enteredAtNs": ns(4),
               "mode": mode, "commandScope": scope, "gateTimeoutMs": 30_000,
               "gateDeadlineNs": ns(34)}
    runtime = tmp_path / "runtime/node_modules/openclaw"
    module = "dist/short-term-promotion-MX1vHJuE.mjs"
    original = runtime / module
    original.parent.mkdir(parents=True)
    original.write_text("async function consolidateMemory() {}\nasync function resolveMemoryPromotionLockTarget() {}\n")
    source_name = "consolidateMemory" if name == "stored" else "resolveMemoryPromotionLockTarget"
    receipt["originalStack"] = f"Error: actual unit boundary\n    at {source_name} ({original.as_uri()}:1:1)"
    receipt["sourceOwner"] = ("consolidateMemory.actual-subagent-complete-await" if name == "stored"
                              else "resolveMemoryPromotionLockTarget.actual-realpath-return")
    raw = {"fixtureBase": str(tmp_path / "fixture"), "steps": []}
    workspace = str(tmp_path / "fixture/workspace")
    if name == "stored":
        receipt["request"] = {"agentId": "main", "message": "whole actual planning request"}
    else:
        receipt.update(arguments={"unitValue": [workspace]}, result={"unitValue": workspace})
    # Carrier decoding already has independent tests. This unit exercises the
    # planning guard's use of the WHOLE decoded original arguments and result.
    monkeypatch.setattr(guard, "_native_value", lambda value, *_: value["unitValue"])
    command = {"id": command_id, "operation": "original-promotion", "label": label,
               "startedAtNs": ns(1), "settledAtNs": ns(21)}
    entry = {"id": command_id, "operation": command["operation"], "label": label,
             "startedAtNs": ns(2), "settledAtNs": ns(20), "originalEntered": {"atNs": ns(3)}}
    if name == "stored":
        response = case["input"]["promotions"][label]["consolidation"]["completion"]["text"]
        entry["completions"] = [{"request": deepcopy(receipt["request"]), "returned": {"text": response}}]
    declared = case["input"]["steps"]
    wait = next(row for row in declared if row["operation"] == "await-original-watch-effects"
                and row.get("afterCalls") == ["forget:selected"])
    release_step = next(row for row in declared if row["operation"] == "release-gate"
                        and row["gate"] == declaration["name"])
    watch_command = {"id": watch_id, "operation": wait["operation"], "label": wait["label"],
                     "startedAtNs": ns(8), "settledAtNs": ns(13),
                     "settlement": {"controlBlocked": False, "error": None}}
    watch_entry = {"id": watch_id, "operation": wait["operation"], "label": wait["label"],
                   "startedAtNs": ns(9), "settledAtNs": ns(12),
                   "watchEffects": {"protocol": "original-watch-effects-v5", "kind": "effects",
                                    "label": wait["label"], "startedAtNs": ns(10), "finishedAtNs": ns(11)}}
    raw["steps"] = [{"step": deepcopy(wait), "startedAtNs": ns(7), "finishedAtNs": ns(14)},
                    {"step": deepcopy(release_step), "startedAtNs": ns(15), "finishedAtNs": ns(17)}]
    gate = {**declaration, "armedAtNs": ns(1), "releasedAtNs": ns(16), "receipt": receipt}
    raw["gates"] = [gate]
    child = {"pid": pid, "actor": "promoter", "instance": instance, "commands": [command, watch_command]}
    actor = {"pid": pid, "actor": "promoter", "instance": instance, "calls": [entry, watch_entry]}
    events = [{"event": "fence-gate-enter", **receipt}]
    for sequence, kind, at in [(11, "setImmediate", 5), (12, "setTimeout", 6)]:
        events.append({"event": "async-gate-mainloop-progress", **identity,
                       "sequence": sequence, "atNs": ns(at), "gate": gate["name"], "kind": kind,
                       "mode": mode, "commandScope": deepcopy(scope), "gateEnterAtNs": receipt["enteredAtNs"],
                       "observedCommandScope": deepcopy(scope),
                       "callLabel": label})
    events.append({"event": "original-watch-control-enter", **identity, "sequence": 13,
                   "atNs": ns(9), "commandId": watch_id, "operation": wait["operation"],
                   "label": wait["label"], "callLabel": wait["label"]})
    events.append({"event": "fence-gate-release", **identity, "sequence": 15, "atNs": ns(19),
                   "gate": gate["name"], "boundary": boundary, "callLabel": label,
                   "mode": mode, "commandScope": deepcopy(scope), "gateEnterSequence": receipt["sequence"],
                   "observedCommandScope": deepcopy(scope),
                   "gateTimeoutMs": 30_000, "gateDeadlineNs": receipt["gateDeadlineNs"],
                   "consumedAtNs": ns(18), "releaseStep": deepcopy(release_step)})
    directory = tmp_path / "native"
    (directory / "gates").mkdir(parents=True)
    (directory / "gates" / (gate["name"] + ".hit.json")).write_text(json.dumps(receipt))
    (directory / "gates" / (gate["name"] + ".release")).write_text(json.dumps(release_step))
    imports = {(pid, 0): {"releaseImports": [{"package": "node_modules/openclaw", "path": module,
                    "sha256": hashlib.sha256(original.read_bytes()).hexdigest()}]}}
    return {"args": [case, receipt, gate, raw, {pid: (child, actor)}, {(pid, 0): events}, {}, None,
                      {"runtime": {"runtimeRoot": str(runtime)}}, imports, directory],
            "receipt": receipt, "command": command, "entry": entry, "watch": watch_entry,
            "watchCommand": watch_command, "events": events, "child": child, "actor": actor,
            "mode": name, "ns": ns, "original": original}


def test_planning_control_holds_only_original_result_while_watcher_settles(planning_control):
    guard._native_async_planning_gate(*planning_control["args"])


def test_v5_gate_admission_checks_the_async_planning_protocol(planning_control):
    case, receipt, gate, raw, actors, passive, authority, node, context, imports, directory = planning_control["args"]
    guard._native_gates(case, raw, actors, passive, authority, node, directory, context=context, imports=imports)
    # Keep the independent gate-file/passive views coherent: the V5-specific
    # admission must still refuse a synchronous planning hold.
    receipt.pop("mode")
    planning_control["events"][0].pop("mode")
    (directory / "gates" / (gate["name"] + ".hit.json")).write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="froze an actor thread"):
        guard._native_gates(case, raw, actors, passive, authority, node, directory, context=context, imports=imports)


@pytest.mark.parametrize("attack", [
    "thread-blocking-mode", "worker-reply-mode", "wrong-planning-mode", "worker-thread",
    "scope-protocol", "scope-command", "scope-label", "scope-watcher", "duplicate-command",
    "source-owner", "source-frame", "source-module", "source-bytes", "changed-request-or-arguments",
    "changed-original-result", "missing-progress", "duplicated-progress", "progress-label",
    "progress-scope", "progress-process", "progress-after-release", "release-label", "release-mode", "release-scope",
    "missing-progress-context", "null-progress-context", "watcher-progress-context",
    "missing-release-context", "null-release-context", "watcher-release-context",
    "release-process", "release-timeout-type",
    "release-gate", "release-step", "widened-deadline", "at-deadline", "late-release", "early-public-settlement",
    "watcher-not-entered", "watcher-label", "watcher-blocked", "watcher-finished-after-release",
])
def test_planning_control_rejects_borrowed_or_deadlocked_boundary(planning_control, attack):
    value = planning_control
    receipt, events, ns = value["receipt"], value["events"], value["ns"]
    release, progress = events[-1], events[1]
    if attack == "thread-blocking-mode":
        receipt.pop("mode")
    elif attack == "worker-reply-mode":
        receipt["mode"] = "deferred-original-worker-reply"
    elif attack == "wrong-planning-mode":
        receipt["mode"] = ("deferred-original-realpath-return" if value["mode"] == "stored"
                           else "deferred-original-model-completion")
    elif attack == "worker-thread":
        receipt["threadId"] = 2
    elif attack == "scope-protocol":
        receipt["commandScope"]["protocol"] = "global-mutable-label"
    elif attack == "scope-command":
        receipt["commandScope"]["commandId"] += 1
    elif attack == "scope-label":
        receipt["commandScope"]["label"] = "selectedWatch"
    elif attack == "scope-watcher":
        receipt["commandScope"].update(commandId=18, operation="await-original-watch-effects", label="selectedWatch")
    elif attack == "duplicate-command":
        value["child"]["commands"].append(deepcopy(value["command"]))
    elif attack == "source-owner":
        receipt["sourceOwner"] = "guessed-model-or-file-result"
    elif attack == "source-frame":
        receipt["originalStack"] = "Error: fixture-generated result without original caller"
    elif attack == "source-module":
        value["args"][9][101, 0]["releaseImports"][0]["path"] = "dist/another-promotion.mjs"
    elif attack == "source-bytes":
        value["original"].write_text("changed original source")
    elif attack == "changed-request-or-arguments":
        if value["mode"] == "stored":
            receipt["request"]["message"] = "a different model request"
        else:
            receipt["arguments"]["unitValue"] = ["/another/workspace"]
    elif attack == "changed-original-result":
        if value["mode"] == "stored":
            value["entry"]["completions"][0]["returned"] = {"text": "rewritten model response"}
        else:
            receipt["result"]["unitValue"] = "/rewritten/realpath"
    elif attack == "missing-progress":
        events.remove(progress)
    elif attack == "duplicated-progress":
        events.append(deepcopy(progress))
    elif attack == "progress-label":
        progress["callLabel"] = "selectedWatch"
    elif attack == "progress-scope":
        progress["commandScope"]["commandId"] = 18
    elif attack == "missing-progress-context":
        progress.pop("observedCommandScope")
    elif attack == "null-progress-context":
        progress["observedCommandScope"] = None
    elif attack == "watcher-progress-context":
        progress["observedCommandScope"].update(commandId=18, operation="await-original-watch-effects", label="selectedWatch")
    elif attack == "progress-process":
        progress["pid"] += 1
    elif attack == "progress-after-release":
        progress.update(sequence=16, atNs=ns(22))
    elif attack == "release-label":
        release["callLabel"] = "selectedWatch"
    elif attack == "release-mode":
        release["mode"] = "deferred-original-worker-reply"
    elif attack == "release-scope":
        release["commandScope"]["commandId"] = 18
    elif attack == "missing-release-context":
        release.pop("observedCommandScope")
    elif attack == "null-release-context":
        release["observedCommandScope"] = None
    elif attack == "watcher-release-context":
        release["observedCommandScope"].update(commandId=18, operation="await-original-watch-effects", label="selectedWatch")
    elif attack == "release-process":
        release["pid"] += 1
    elif attack == "release-timeout-type":
        release["gateTimeoutMs"] = 30_000.0
    elif attack == "release-gate":
        release["gateEnterSequence"] += 1
    elif attack == "release-step":
        release["releaseStep"] = {"operation": "release-gate", "gate": "another"}
    elif attack == "widened-deadline":
        receipt.update(gateTimeoutMs=60_000, gateDeadlineNs=ns(64))
        release.update(gateTimeoutMs=60_000, gateDeadlineNs=ns(64))
    elif attack in {"at-deadline", "late-release"}:
        release.update(consumedAtNs=ns(34 if attack == "at-deadline" else 35), atNs=ns(36))
        value["entry"]["settledAtNs"], value["command"]["settledAtNs"] = ns(37), ns(38)
    elif attack == "early-public-settlement":
        value["entry"]["settledAtNs"] = ns(12)
    elif attack == "watcher-not-entered":
        events.remove(events[-2])
    elif attack == "watcher-label":
        events[-2]["callLabel"] = receipt["callLabel"]
    elif attack == "watcher-blocked":
        value["watchCommand"]["settlement"]["controlBlocked"] = True
    else:
        value["watch"]["watchEffects"]["finishedAtNs"] = ns(22)
    with pytest.raises((ValueError, KeyError)):
        guard._native_async_planning_gate(*value["args"])


def test_planning_deadline_covers_consumption_before_logging(planning_control):
    value = planning_control
    value["events"][-1].update(consumedAtNs=str(int(value["ns"](34)) - 1), atNs=value["ns"](35))
    value["entry"]["settledAtNs"] = value["ns"](36)
    value["command"]["settledAtNs"] = value["ns"](37)
    guard._native_async_planning_gate(*value["args"])
