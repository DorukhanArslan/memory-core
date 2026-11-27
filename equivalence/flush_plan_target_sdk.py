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
import stat
import tempfile

from equivalence.flush_plan_target import BOUNDARY, PROVIDER, published_workspace, validate_case
from equivalence.promotion_apply_runtime import _json_value
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.host.kit import HostKit
from memory_core.host.lifecycle import HostModelResult, HostSessionRunner
from memory_core.host.session import SessionState, TurnUsage
from memory_core.memory_flush import build_memory_flush_plan_from_config, ensure_memory_flush_target_file
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
from memory_core.session_catalog import MemorySessionCatalog


def alias_witness(workspace, pair):
    """Observe the two seeded directory entries without following any links."""
    entries = {}
    for role in ("target", "alias"):
        path = workspace / pair[role]
        if not path.is_relative_to(workspace) or path.resolve(strict=True) != path.absolute():
            raise ValueError("Invalid flush fixture path")
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("The shared flush fixture must be a regular file")
        entries[role] = {"dev": str(info.st_dev), "ino": str(info.st_ino), "nlink": info.st_nlink}
    return entries


def snapshot(workspace, read_only_alias=None):
    result = {}
    linked_names = []
    if read_only_alias:
        identity = alias_witness(workspace, read_only_alias)
        if identity["target"] == identity["alias"] and identity["target"]["nlink"] == 2:
            linked_names = sorted(read_only_alias.values())
    for file in sorted(workspace.rglob("*")):
        name = file.relative_to(workspace).as_posix()
        if file.is_symlink():
            raise ValueError("Unexpected link in flush workspace")
        if file.is_dir():
            result[name] = {"kind": "directory"}
        elif (file.is_file() and (file.stat().st_nlink == 1 or name in linked_names)
              and file.stat().st_size <= 4 * 1024 * 1024):
            result[name] = {"kind": "file", "base64": base64.b64encode(file.read_bytes()).decode("ascii")}
            if name in linked_names:
                result[name]["linkedAs"] = linked_names
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
    alias = value.get("readOnlyAlias")
    if alias:
        os.link(workspace / alias["target"], workspace / alias["alias"])
        raw["aliasWitnesses"] = []

    def files(*, witness=False):
        if alias and witness:
            raw["aliasWitnesses"].append(alias_witness(workspace, alias))
        return snapshot(workspace, alias)

    raw["initial"] = files(witness=True)
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
                                        "return": _json_value(arg), "files": files()})

    async def foreground(turn):
        nonlocal host_clock
        raw["foreground"].append(turn.model_request())
        raw["beforeMaintenance"] = files()
        host_clock = value["nowMs"]
        return HostModelResult(usage=TurnUsage(prompt_tokens=176000))

    async def execute_candidate(turn, candidate, selection):
        model = candidate.model
        reply = value["responses"][model]
        raw["deliveries"].append({"selection": wire_selection(selection),
                                  "candidate": {"provider": candidate.provider, "model": model}, "reply": reply,
                                  "request": {"tools": turn.tools, "messages": turn.messages}, "target": turn.flush_request.target,
                                  "files": files(witness=True)})
        if reply == "unavailable":
            raise FlushModelUnavailable("429 rate limit for selected fixture model")
        saved = turn.record_message({"role": "assistant", "content": [{"type": "text", "text": reply}]})
        if case["covers"] == [BOUNDARY]:
            raw["deliveries"][-1]["recordedAssistant"] = saved
        return HostModelResult()

    executor = FlushModelExecutor(provider=PROVIDER, model=value["primary"],
        fallbacks=tuple(f"{PROVIDER}/{model}" for model in value["fallbacks"]), execute_candidate=execute_candidate)
    previous = sys.getprofile()
    try:
        sys.setprofile(observe)
        result = await runner.run_turn("Remember my field note.", execute=foreground, execute_flush=executor,
                                       context_window_tokens=value["contextWindowTokens"])
        raw["result"] = _json_value(result)
        raw["final"] = files(witness=True)
        raw["stamp"] = deepcopy(result.session.entry.get("memoryFlush"))
        raw["complete"] = True
    except Exception as error:
        raw["error"] = _json_value(error)
        raise
    finally:
        sys.setprofile(previous)
        (directory / "python-raw.json").write_text(json.dumps([raw], ensure_ascii=True, allow_nan=False, separators=(",", ":")))
    selection = raw["deliveries"][0]["selection"] if raw["deliveries"] else None
    public = {"provider": "none", "plans": [p["result"] for p in raw["plans"]], "selection": selection,
              "candidates": [d["candidate"] for d in raw["deliveries"]],
              "files": published_workspace(raw["initial"], raw["beforeMaintenance"], raw["final"]),
              "outcome": "skipped" if raw["stamp"] is None else "completed" if raw["stamp"]["kind"] == "succeeded" else "failed",
              "stamp": raw["stamp"]}
    if case["covers"] == [BOUNDARY]:
        public["replies"] = [block["text"] for d in raw["deliveries"]
                             for block in d["recordedAssistant"]["content"] if block["type"] == "text"]
    return public
