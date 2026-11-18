"""Drive the public host turn and its routed automatic maintenance callback."""
from __future__ import annotations

import asyncio
import base64
from copy import deepcopy
from dataclasses import asdict
import hashlib
import inspect
import json
from pathlib import Path
import sys
import os
import tempfile

from equivalence.flush_plan_target import PROVIDER, published_workspace, validate_case
from equivalence.promotion_apply_runtime import _json_value
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.host.kit import HostKit
from memory_core.host.lifecycle import HostModelResult, HostSessionRunner
from memory_core.host.session import SessionState, TurnUsage
from memory_core.memory_flush import build_memory_flush_plan_from_config, ensure_memory_flush_target_file
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
from memory_core.session_catalog import MemorySessionCatalog


def snapshot(workspace):
    result = {}
    for file in sorted(workspace.rglob("*")):
        name = file.relative_to(workspace).as_posix()
        if file.is_symlink():
            raise ValueError("Unexpected link in flush workspace")
        if file.is_dir():
            result[name] = {"kind": "directory"}
        elif file.is_file() and file.stat().st_nlink == 1 and file.stat().st_size <= 4 * 1024 * 1024:
            result[name] = {"kind": "file", "base64": base64.b64encode(file.read_bytes()).decode("ascii")}
        else:
            raise ValueError("Unexpected flush file kind")
    return result


def wire_plan(plan):
    if plan is None:
        return None
    names = {"soft_threshold_tokens": "softThresholdTokens", "force_flush_transcript_bytes": "forceFlushTranscriptBytes",
             "reserve_tokens_floor": "reserveTokensFloor", "system_prompt": "systemPrompt", "relative_path": "relativePath"}
    return {names.get(key, key): v for key, v in asdict(plan).items() if v is not None}


def wire_selection(selection):
    return {"provider": selection.provider, "model": selection.model,
            "fallbacksOverride": {"kind": "undefined"} if selection.fallbacks_override is None else list(selection.fallbacks_override),
            "requestedRouteResolution": {"kind": "undefined"} if selection.requested_route_resolution is None else selection.requested_route_resolution}


def run_sdk(case, evidence_directory=None):
    if evidence_directory is None:
        with tempfile.TemporaryDirectory(prefix="flush-plan-sdk-") as directory:
            return run_sdk(case, Path(directory))
    validate_case(case)
    return asyncio.run(_run(case, Path(evidence_directory)))


async def _run(case, directory):
    from memory_core.host import FlushModelExecutor, FlushModelUnavailable

    value = case["input"]
    directory.mkdir(parents=True, exist_ok=True)
    workspace = directory / "workspace"
    workspace.mkdir()
    raw = {"kind": "sdk-flush-plan-target", "id": case["id"], "input": deepcopy(value), "workspace": str(workspace),
           "plans": [], "prepareCalls": [], "deliveries": [], "foreground": [], "owners": [],
           "pid": os.getpid(), "execPath": sys.executable, "calls": []}
    for owner in (HostSessionRunner.run_turn, HostKit.prepare_flush, FlushModelExecutor.__call__, build_memory_flush_plan_from_config,
                  ensure_memory_flush_target_file):
        path = Path(inspect.getsourcefile(owner)).resolve()
        raw["owners"].append({"name": owner.__qualname__, "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    for rel in value["directories"]:
        (workspace / rel).mkdir(parents=True)
    for rel, content in value["files"].items():
        file = workspace / rel
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(content.encode("utf8"))
    raw["initial"] = snapshot(workspace)
    session = SessionState.new(session_key="agent:main:main", session_id="session")
    # The source session has an ordinary existing catalog clock. The host separately
    # supplies the flush evaluation time, as the native plan resolver does.
    catalog = MemorySessionCatalog(directory / "sessions.sqlite", clock_ms=lambda: 1767305100000)
    host_clock = 1767305100000
    runner = HostSessionRunner.open(workspace, catalog=catalog, session=session,
        config=MemoryConfig(workspace_dir=workspace, store_path=directory / "index.sqlite", flags=FeatureFlags(vector_search=False)),
        now_ms=lambda: host_clock, timezone=value["hostTimezone"], flush_timezone=value["timezone"],
        flush_config=value["flush"], time_format=value["formats"]["sdk"], identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)

    observed = {HostSessionRunner.run_turn.__code__: "HostSessionRunner.run_turn",
                HostKit.prepare_flush.__code__: "HostKit.prepare_flush",
                FlushModelExecutor.__call__.__code__: "FlushModelExecutor.__call__"}

    def observe(frame, event, arg):
        if event == "call" and frame.f_code in observed:
            raw["calls"].append(observed[frame.f_code])
        if frame.f_code is build_memory_flush_plan_from_config.__code__ and event == "return":
            raw["plans"].append({"args": {k: deepcopy(frame.f_locals.get(k)) for k in ("cfg", "now_ms", "context_window_tokens", "time_format")},
                                 "return": _json_value(arg), "result": wire_plan(arg)})
        elif frame.f_code is ensure_memory_flush_target_file.__code__ and event in {"call", "return"}:
            raw["prepareCalls"].append({"event": event, "target": frame.f_locals["relative_path"],
                                        "return": _json_value(arg), "files": snapshot(workspace)})

    async def foreground(turn):
        nonlocal host_clock
        raw["foreground"].append(turn.model_request())
        raw["beforeMaintenance"] = snapshot(workspace)
        host_clock = value["nowMs"]
        return HostModelResult(usage=TurnUsage(prompt_tokens=176000))

    async def execute_candidate(turn, candidate, selection):
        model = candidate.model
        reply = value["responses"][model]
        raw["deliveries"].append({"selection": wire_selection(selection),
                                  "candidate": {"provider": candidate.provider, "model": model}, "reply": reply,
                                  "request": {"tools": turn.tools, "messages": turn.messages}, "target": turn.flush_request.target,
                                  "files": snapshot(workspace)})
        if reply == "unavailable":
            raise FlushModelUnavailable("429 rate limit for selected fixture model")
        turn.record_message({"role": "assistant", "content": [{"type": "text", "text": reply}]})
        return HostModelResult()

    executor = FlushModelExecutor(provider=PROVIDER, model=value["primary"],
        fallbacks=tuple(f"{PROVIDER}/{model}" for model in value["fallbacks"]), execute_candidate=execute_candidate)
    previous = sys.getprofile()
    try:
        sys.setprofile(observe)
        result = await runner.run_turn("Remember my field note.", execute=foreground, execute_flush=executor,
                                       context_window_tokens=value["contextWindowTokens"])
        raw["result"] = _json_value(result)
        raw["final"] = snapshot(workspace)
        raw["stamp"] = deepcopy(result.session.entry.get("memoryFlush"))
        raw["complete"] = True
    except Exception as error:
        raw["error"] = _json_value(error)
        raise
    finally:
        sys.setprofile(previous)
        (directory / "python-raw.json").write_text(json.dumps([raw], ensure_ascii=True, allow_nan=False, separators=(",", ":")))
    selection = raw["deliveries"][0]["selection"] if raw["deliveries"] else None
    return {"provider": "none", "plans": [p["result"] for p in raw["plans"]], "selection": selection,
            "candidates": [d["candidate"] for d in raw["deliveries"]], "files": published_workspace(raw["initial"], raw["beforeMaintenance"], raw["final"]),
            "outcome": "skipped" if raw["stamp"] is None else "completed" if raw["stamp"]["kind"] == "succeeded" else "failed",
            "stamp": raw["stamp"]}
