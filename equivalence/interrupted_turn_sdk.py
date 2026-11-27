"""Run the SDK host twice against one durable catalog and retain its actual crash evidence."""
from __future__ import annotations

import asyncio
from contextlib import closing
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import stat
import subprocess
import sys
from unittest.mock import patch

from equivalence.interrupted_turn_acceptance import DAILY_PATH
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.host.lifecycle import HostModelResult, HostSessionRunner, HostTurn
from memory_core.host.session import SessionState
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
from memory_core.session_catalog import MemorySessionCatalog

ROOT = Path(__file__).resolve().parents[1]
FIRST = "interrupted-first-turn"
NEXT = "independent-next-turn"


def _save(path, value):
    def wire(item):
        if is_dataclass(item):
            return {field.name: getattr(item, field.name) for field in fields(item)}
        if isinstance(item, Mapping):
            return dict(item)
        raise TypeError(f"Unsupported SDK observation {type(item).__name__}")

    path.write_text(json.dumps(value, ensure_ascii=True, allow_nan=False, default=wire) + "\n", encoding="utf-8")


def _read(path):
    return json.loads(path.read_bytes())


def _paths(value):
    return {"original": value["original"]["relativePath"], "independent": DAILY_PATH}


def _snapshot(root, stage, value):
    target = root / stage
    target.mkdir()
    with closing(sqlite3.connect((root / "sessions.sqlite").as_uri() + "?mode=ro", uri=True)) as source:
        with closing(sqlite3.connect(target / "sessions.sqlite")) as copy:
            source.backup(copy)
    for label, relative in _paths(value).items():
        source = root / "workspace" / relative
        if source.is_file():
            (target / (label + ".txt")).write_bytes(source.read_bytes())


def _dispatch(turn, identifier, name, arguments):
    turn.record_message({"role": "assistant", "content": [
        {"type": "toolCall", "id": identifier, "name": name, "arguments": arguments}]})
    return turn.dispatch(identifier, name, arguments)


async def _phase(root, phase):
    value = _read(root / "case.json")["input"]
    owner = value["identity"]
    workspace = root / "workspace"
    catalog = MemorySessionCatalog(root / "sessions.sqlite", agent_id=owner["agentId"], clock_ms=lambda: value["nowMs"])
    state = SessionState.new(session_id=owner["sessionId"], session_key=owner["sessionKey"])
    config = MemoryConfig(workspace_dir=workspace, store_path=root / "index.sqlite", agent_id=owner["agentId"],
                          flags=FeatureFlags(vector_search=False, temporal_decay=False))
    runner = HostSessionRunner.open(workspace, session=state, catalog=catalog, config=config,
                                    now_ms=lambda: value["nowMs"], identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
                                    interrupted_publication=value["sdkPolicy"])
    original = value["original"]

    if phase == "cut":
        def stop(edge, emitted=None):
            _snapshot(root, "cut", value)
            _save(root / "interrupt.json", {"pid": os.getpid(), "cut": edge, "emitted": emitted})
            os.kill(os.getpid(), signal.SIGKILL)

        real_record = HostTurn._record
        real_intent = runner._ensure_memory_intent

        def record(turn, message):
            if value["cut"] == "after-write" and message.get("role") == "toolResult":
                stop("after-write", message)
            return real_record(turn, message)

        def intent(session, *, turn_id):
            real_intent(session, turn_id=turn_id)
            if value["cut"] == "before-write":
                stop("before-write")

        async def first(turn):
            _save(root / "initial-model.json", turn.model_request())
            _dispatch(turn, original["callId"], "add_memory_entry",
                      {"section": original["section"], "text": original["text"]})
            raise RuntimeError("The controlled cut was never reached")

        with patch.object(runner, "_ensure_memory_intent", intent), patch.object(HostTurn, "_record", record):
            await runner.run_turn(original["prompt"], execute=first, request_id=FIRST)
        raise RuntimeError("The writer exited without the declared interruption")

    _snapshot(root, "reopen", value)
    step = value["followup"]
    model_inputs = []

    async def second(turn):
        model_inputs.append(turn.model_request())
        write = step["write"]
        if write:
            _dispatch(turn, write["callId"], "append_daily_note", {"text": write["text"], "date": write["date"]})
            model_inputs.append(turn.model_request())
        turn.record_message({"role": "assistant", "content": [{"type": "text", "text": step["reply"]}]})
        return HostModelResult(payloads=({"text": step["reply"]},))

    outcome = await runner.run_turn(step["prompt"], execute=second, request_id=NEXT)
    _save(root / "followup.json", {"pid": os.getpid(), "modelInputs": model_inputs, "outcome": outcome})
    _snapshot(root, "final", value)


def _events(root, stage, value):
    owner = value["identity"]
    with closing(sqlite3.connect((root / stage / "sessions.sqlite").as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        rows = db.execute("SELECT event_json FROM memory_session_events WHERE agent=? AND session_id=? ORDER BY seq",
                          (owner["agentId"], owner["sessionId"]))
        events = [json.loads(row[0]) for row in rows]
        entry, = db.execute("SELECT entry_json FROM memory_session_nodes WHERE agent=? AND session_key=?",
                            (owner["agentId"], owner["sessionKey"])).fetchone()
        if json.loads(entry)["sessionId"] != owner["sessionId"]:
            raise ValueError("The snapshot belongs to a different session")
        return [e["message"] for e in events if e.get("type") == "message"], json.loads(entry)


def _results(messages, original_id):
    results = []
    for message in messages:
        if message.get("role") == "toolResult" and message.get("toolCallId") == original_id:
            if message.get("toolName") != "add_memory_entry":
                raise ValueError("SDK tool result no longer identifies its original writer")
            results.append({"id": original_id, "isError": message.get("isError"), "content": message["content"]})
    return results


def _view(root, stage, value):
    messages, entry = _events(root, stage, value)
    original = value["original"]
    calls = []
    for message in messages:
        if message.get("role") != "assistant" or not isinstance(message.get("content"), list):
            continue
        for block in message["content"]:
            if block.get("type") == "toolCall" and block.get("id") == original["callId"]:
                if block.get("name") != "add_memory_entry" or block.get("arguments") != {
                    "section": original["section"], "text": original["text"]
                }:
                    raise ValueError("The original recorded SDK call changed identity or arguments")
                calls.append(block["id"])
    files = {}
    for label in _paths(value):
        source = root / stage / (label + ".txt")
        files[label] = source.read_bytes().decode("utf-8") if source.is_file() else None
    return {"files": files, "originalCalls": calls, "originalResults": _results(messages, original["callId"])}, entry


def review_case(case, directory):
    root = Path(directory).resolve(strict=True)
    value = case["input"]
    launch = _read(root / "processes.json")
    cut = _read(root / "interrupt.json")
    follow = _read(root / "followup.json")
    if (_read(root / "case.json") != case or cut["cut"] != value["cut"] or cut["pid"] == follow["pid"]
            or launch != [[cut["pid"], -signal.SIGKILL], [follow["pid"], 0]]):
        raise ValueError("SDK recovery does not retain the original case, killed writer and fresh reader")
    manifest = _read(root / "capture.json")
    if manifest != _hashes(root):
        raise ValueError("The retained original SDK capture changed")
    original = value["original"]
    emitted = cut["emitted"]
    if value["cut"] == "after-write":
        if (not isinstance(emitted, dict) or emitted.get("role") != "toolResult"
                or emitted.get("toolCallId") != original["callId"] or emitted.get("toolName") != "add_memory_entry"):
            raise ValueError("The cut is missing the original SDK tool's unpersisted response")
    elif emitted is not None:
        raise ValueError("The pre-write cut already emitted a tool result")
    views = {}
    for stage in ("cut", "reopen", "final"):
        views[stage], entry = _view(root, stage, value)
        if stage == "cut":
            marker = entry["sdkHostLifecycle"]["pendingMemoryPublication"]
            if marker.get("stage") != "intent" or marker["turnId"] != FIRST:
                raise ValueError("The SDK did not durably enter the original memory writer at the cut")
    inputs = follow["modelInputs"]
    prompts = [(_read(root / "initial-model.json"), original["prompt"])]
    if inputs:
        prompts.append((inputs[0], value["followup"]["prompt"]))
    for request, expected in prompts:
        users = [message["content"] for message in request["messages"] if message.get("role") == "user"]
        if not users or not isinstance(users[-1], str) or not users[-1].endswith(expected):
            raise ValueError("The SDK model request belongs to a different prompt")
    executed = [tool for tool in follow["outcome"]["tools"] if tool["sourceExecuted"]]
    write = value["followup"]["write"]
    if write:
        for tool in executed:
            if tool["toolCallId"] == write["callId"] and (
                tool["name"] != "append_daily_note" or tool["arguments"] != {"text": write["text"], "date": write["date"]}
            ):
                raise ValueError("The independent SDK tool call changed name or arguments")
    return {**views, "firstModelOriginalResults": _results(inputs[0]["messages"], original["callId"]) if inputs else [],
            "newTurnToolCalls": [tool["toolCallId"] for tool in executed],
            "replies": [payload["text"] for payload in follow["outcome"]["payloads"]]}


def _hashes(root):
    files = [root / name for name in ("case.json", "initial-model.json", "interrupt.json", "followup.json", "processes.json")]
    for stage in ("cut", "reopen", "final"):
        snapshot = root / stage
        if snapshot.resolve(strict=True) != snapshot:
            raise ValueError("Unowned SDK snapshot directory")
        files.append(snapshot / "sessions.sqlite")
        for label in ("original", "independent"):
            note = snapshot / (label + ".txt")
            if os.path.lexists(note):
                files.append(note)
    digests = {}
    for path in files:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Invalid SDK capture file")
        digests[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


def run_case(case, directory):
    root = Path(directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    for name in ("workspace", "home", "tmp"):
        (root / name).mkdir()
    _save(root / "case.json", case)
    env = {"PATH": os.defpath, "HOME": str(root / "home"), "TMPDIR": str(root / "tmp"), "TZ": "UTC", "LANG": "C.UTF-8",
           "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
    statuses = []
    for phase, expected in (("cut", -signal.SIGKILL), ("next", 0)):
        if phase == "next" and case["input"]["externalEdit"] is not None:
            target = root / "workspace" / case["input"]["original"]["relativePath"]
            target.write_bytes(case["input"]["externalEdit"].encode("utf-8"))
        with (root / (phase + ".log")).open("wb") as log:
            with subprocess.Popen([sys.executable, "-m", "equivalence.interrupted_turn_sdk", phase, str(root)],
                                  cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT) as child:
                try:
                    code = child.wait(timeout=90)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
                    raise
                statuses.append([child.pid, code])
        if code != expected:
            raise RuntimeError(f"SDK {phase} exited {code}, see {root / (phase + '.log')}")
    _save(root / "processes.json", statuses)
    _save(root / "capture.json", _hashes(root))
    return review_case(case, root)


if __name__ == "__main__":
    which, path = sys.argv[1:]
    if which not in {"cut", "next"}:
        raise SystemExit("Expected cut or next")
    asyncio.run(_phase(Path(path).resolve(strict=True), which))
