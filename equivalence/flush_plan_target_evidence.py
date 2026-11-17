"""Reopen physical workspaces and verify both sides of the automatic flush."""
from __future__ import annotations

import base64
import hashlib
from itertools import groupby
from pathlib import Path

from equivalence.flush_execution_bindings import COMPILED_HASHES
from equivalence.flush_plan_target import PROVIDER, canonical, published_workspace, validate_case
from equivalence.flush_plan_target_sdk import snapshot
from equivalence.model_runtime_authority import APPROVED_NODE_RUNTIME


def require(condition, message):
    if not condition:
        raise ValueError(message)


def same(value, expected, message):
    require(canonical(value) == canonical(expected), message)


def seed_tree(value):
    tree = {}
    for name in [*value["files"], *value["directories"]]:
        for parent in Path(name).parents:
            if str(parent) != ".":
                tree[parent.as_posix()] = {"kind": "directory"}
    for name in value["directories"]:
        tree[name] = {"kind": "directory"}
    for name, text in value["files"].items():
        tree[name] = {"kind": "file", "base64": base64.b64encode(text.encode()).decode("ascii")}
    return tree


def check_raw(case, snapshots, directory, kind):
    validate_case(case)
    require(isinstance(snapshots, list) and len(snapshots) == 1, "Missing full flush capture")
    raw = snapshots[0]
    require(raw["kind"] == kind and "error" not in raw, "The flush worker failed")
    same(raw["input"], case["input"], "Flush worker input changed")
    same(raw["initial"], seed_tree(case["input"]), "Flush literal files were not installed")
    root = Path(directory) / "workspace"
    require(root.is_dir() and not root.is_symlink(), "The retained physical workspace is missing")
    same(snapshot(root), raw["final"], "The physical workspace no longer matches its recorded bytes")
    return raw


def check_prompts(request, plan, tree):
    require(tree.get(plan["relativePath"], {}).get("kind") == "file",
            "A model ran before the daily target was a real regular file")
    messages = request["messages"]
    system = request.get("systemPrompt") or next(
        (m["content"] for m in messages if m.get("role") == "system"), "")
    require(plan["systemPrompt"] in system and any(m.get("role") == "user" and
            isinstance(m.get("content"), str) and plan["prompt"] in m["content"] for m in messages),
            "The model did not receive both complete plan prompts")
    require(isinstance(request["tools"], (list, tuple)) and
            any(t.get("name") == "write" for t in request["tools"]), "Missing actual maintenance tool context")


def check_plans(value, plans):
    if value["flush"].get("enabled") is False:
        same(plans, [None], "Disabled host unexpectedly admitted a flush")
        return
    require(len(plans) == 2 and all(isinstance(p, dict) for p in plans),
            "Both ordinary admission and disk preparation must resolve the real plan")
    for plan in plans:
        keys = {"softThresholdTokens", "forceFlushTranscriptBytes", "reserveTokensFloor",
                "prompt", "systemPrompt", "relativePath"}
        expected_model = value["flush"].get("model", "").strip()
        if expected_model:
            keys.add("model")
            require(plan.get("model") == expected_model, "Bound model override was lost")
        require(set(plan) == keys and all(type(plan[k]) is int for k in
                ("softThresholdTokens", "forceFlushTranscriptBytes", "reserveTokensFloor")),
                "Incomplete native or SDK flush plan")
        require(all(plan["relativePath"] in plan[k] for k in ("prompt", "systemPrompt")),
                "Flush plan prompts lost their generated daily target")


def validate_native(case, public, snapshots, evidence_directory, loaded):
    value = case["input"]
    raw = check_raw(case, snapshots, evidence_directory, "native-flush-plan-target")
    owner = "dist/agent-runner-memory-Cc4lCZcs.mjs"
    require(raw["process"]["version"] == APPROVED_NODE_RUNTIME["nodeVersion"] and
            raw["process"]["sha256"] == APPROVED_NODE_RUNTIME["sha256"] and
            min(raw["process"]["pid"], raw["process"]["ppid"]) > 0,
            "Native flush lost its actual approved process")
    require(raw["routing"]["sha256"] == COMPILED_HASHES[owner] and
            raw["routing"]["url"].endswith("/node_modules/openclaw/" + owner),
            "Native selection moved outside the official host runner")
    for module in (owner, "dist/extensions/memory-core/index.js", "dist/extensions/memory-core/manager-runtime.js"):
        require(loaded.get(("node_modules/openclaw", module), {}).get("sha256") == COMPILED_HASHES[module],
                "The original flush host, plugin or manager was not loaded")
    cfg = raw["cfg"]["agents"]["defaults"]
    same(cfg["compaction"]["memoryFlush"], value["flush"], "Original configuration changed")
    same(cfg["model"], {"primary": PROVIDER + "/" + value["primary"],
                        "fallbacks": [PROVIDER + "/" + m for m in value["fallbacks"]]}, "Wrong conversational routing")
    require(cfg["userTimezone"] == value["timezone"] and cfg["contextTokens"] == value["contextWindowTokens"],
            "Wrong original zone or model token window")
    plans = [p["result"] for p in raw["plans"]]
    check_plans(value, plans)
    for p in raw["plans"]:
        same(p["owner"], {"name": "buildMemoryFlushPlan", "sha256": "6f55f0fea438933d6e3bd7b844d1fac0186f4ec21e34fb5aebc2133427a4f963"}, "The registered flush plan owner changed")
        same(p["args"], {"nowMs": value["nowMs"], "contextWindowTokens": value["contextWindowTokens"]},
             "Original plan received a different clock or context budget")
    require(not raw["routing"]["errors"], "Original host selections could not be observed")
    same(raw["routing"]["sites"], {"requested": 910, "candidate": 1015, "failure": 1113},
         "The pinned original source lines moved")
    frames = raw["routing"]["receipts"]
    owners = {"selection": ("prepareMemoryFlushAttempt", 910), "candidate": ("runCandidate", 1015),
              "failure": ("recordMemoryFlushFailure", 1113)}
    for frame in frames:
        require((frame["functionName"], frame["line"]) == owners[frame["site"]], "Wrong original model frame")
    select = [r["values"] for r in frames if r["site"] == "selection"]
    routes = [r["values"] for r in frames if r["site"] == "candidate"]
    failures = [r["values"] for r in frames if r["site"] == "failure"]
    require(len(select) == bool(routes) and bool(failures) == (raw["result"]["outcome"] == "failed"),
            "Incomplete original route or failure trace")
    calls = raw["modelStarts"]
    observed = [(call["model"]["provider"], call["model"]["id"]) for call in calls]
    same([{"provider": k[0], "model": k[1]} for k, _ in groupby(observed)], routes,
         "The original transport did not execute its selected model candidates")
    for call in calls:
        check_prompts(call["context"], plans[-1], call["files"])
        require(call["runContexts"], "Missing original maintenance execution")
        answer = value["responses"][call["model"]["id"]]
        same(call["reply"], {"error": "429 rate limit for selected fixture model"} if
             answer == "unavailable" else {"text": answer}, "Unbound model reply")
    phases = [p["phase"] for p in raw["progress"]]
    require(phases.count("plan-resolved") == len(plans) and phases.count("model-stream-called") == len(calls)
            and "before-native-run:prepare daily note" in phases and phases[-1] == "after-native-run:prepare daily note",
            "Incomplete native progress and model capture")
    stamp = raw["result"]["sessionEntry"].get("memoryFlush")
    same(raw["persisted"].get("memoryFlush"), stamp, "Native flush result was not durable")
    same(public, {"provider": "none", "plans": plans, "selection": select[0] if select else None,
                  "candidates": routes, "outcome": raw["result"]["outcome"], "stamp": stamp, "files": raw["final"]},
         "Native output disagrees with its original calls and physical files")


def validate_sdk(case, public, snapshots, directory):
    value = case["input"]
    raw = check_raw(case, snapshots, directory, "sdk-flush-plan-target")
    require(raw["complete"] is True and raw["pid"] > 0 and raw["id"] == case["id"], "Missing completed SDK host turn")
    owners = {"HostSessionRunner.run_turn": "host/lifecycle.py", "HostKit.prepare_flush": "host/kit.py",
              "FlushModelExecutor.__call__": "host/lifecycle.py", "build_memory_flush_plan_from_config": "memory_flush.py",
              "ensure_memory_flush_target_file": "memory_flush.py"}
    root = Path(__file__).resolve().parents[1] / "memory_core"
    require(len(raw["owners"]) == len(owners) and {o["name"] for o in raw["owners"]} == set(owners),
            "Unexpected or missing SDK host owner")
    for item in raw["owners"]:
        name = owners[item["name"]]
        require(item["path"].endswith("/memory_core/" + name) and
                item["sha256"] == hashlib.sha256((root / name).read_bytes()).hexdigest(), "Changed SDK host owner")
    require({"HostSessionRunner.run_turn", "HostKit.prepare_flush"}.issubset(raw["calls"]) and
            len(raw["foreground"]) == 1, "SDK failed to enter from the public host turn")
    plans = [p["result"] for p in raw["plans"]]
    check_plans(value, plans)
    for call in raw["plans"]:
        args = call["args"]
        require(args["now_ms"] == value["nowMs"] and args["context_window_tokens"] == value["contextWindowTokens"]
                and args["time_format"] == value["formats"]["sdk"], "Wrong SDK flush clock or context budget")
        same(args["cfg"]["agents"]["defaults"]["compaction"]["memoryFlush"], value["flush"], "SDK flush configuration changed")
    prepare = raw["prepareCalls"]
    require([r["event"] for r in prepare] == ([] if plans == [None] else ["call", "return"]),
            "Unexpected target preparation order")
    if prepare:
        require(all(p["target"] == plans[-1]["relativePath"] for p in prepare), "SDK prepared another target")
    deliveries = raw["deliveries"]
    require(bool(deliveries) == ("FlushModelExecutor.__call__" in raw["calls"]), "Missing real SDK route")
    for delivery in deliveries:
        check_prompts(delivery["request"], plans[-1], delivery["files"])
        same(delivery["selection"], deliveries[0]["selection"], "SDK changed its requested route during fallback")
        require(delivery["reply"] == value["responses"][delivery["candidate"]["model"]]
                and delivery["target"] == plans[-1]["relativePath"], "Misrouted SDK model or file")
    stamp = raw["stamp"]
    outcome = "skipped" if stamp is None else "completed" if stamp["kind"] == "succeeded" else "failed"
    require(raw["result"]["$type"].endswith(".HostTurnOutcome") and
            bool(raw["result"]["fields"]["failures"]) == (outcome == "failed"), "Missing SDK outcome/error")
    same(public, {"provider": "none", "plans": plans, "outcome": outcome, "stamp": stamp,
                  "selection": deliveries[0]["selection"] if deliveries else None,
                  "candidates": [d["candidate"] for d in deliveries],
                  "files": published_workspace(raw["initial"], raw["beforeMaintenance"], raw["final"])},
         "SDK result disagrees with its model calls or physical filesystem")
