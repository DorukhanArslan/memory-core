"""Drive a real SDK session, then open its catalog in a separate Python process."""
from __future__ import annotations

import asyncio
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from equivalence.automation_job_state import wire
from memory_core.compaction_replay import ReplayModel
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.host import HistoryReplayContext, HostModelResult, HostSessionRunner, RuntimePromptInput, SessionState
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
from memory_core.session_catalog import MemorySessionCatalog


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_events(path, session_id):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise ValueError("The SDK transcript database failed its integrity check")
        return [json.loads(row[0]) for row in db.execute(
            "SELECT event_json FROM memory_session_events WHERE agent='main' AND session_id=? ORDER BY seq",
            (session_id,))]


def retained(events):
    messages = [e["message"] for e in events if e.get("type") == "message"]
    [checkpoint] = [m["providerReplay"] for m in messages if "providerReplay" in m]
    [call] = [b for m in messages if m["role"] == "assistant" for b in m["content"] if b["type"] == "toolCall"]
    [result] = [m for m in messages if m["role"] == "toolResult"]
    return {"checkpoint": checkpoint, "call": call, "result": {k: v for k, v in result.items()
            if k not in ("timestamp", "__openclaw")}}


def assistant(model, timestamp, response_id, stop):
    return {"role": "assistant", "content": [], "api": model.api, "provider": model.provider,
            "model": model.id, "responseId": response_id, "timestamp": timestamp, "stopReason": stop,
            "usage": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 0,
                      "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0}}}


def complete_text(message, item):
    for part in item["content"]:
        if part["type"] != "output_text":
            raise ValueError("A text provider reply was required")
        message["content"].append({"type": "text", "text": part["text"],
            "textSignature": json.dumps({"v": 1, "id": item["id"]}, separators=(",", ":"))})


async def drive(case, directory, phase):
    value = case["input"]
    facts = value["model"]
    model = ReplayModel(facts["provider"], facts["api"], facts["id"] if phase == "seed" else value["attemptModelId"],
                        facts["baseUrl"], tuple(facts["input"]), facts["reasoning"])
    clock = value["seedMs" if phase == "seed" else "attemptMs"]
    workspace = directory / "workspace"
    db_path = directory / "catalog.sqlite"
    if phase == "seed":
        workspace.mkdir()
        (workspace / value["file"]["path"]).write_text(value["file"]["text"], encoding="utf8")
    elif not db_path.is_file():
        raise ValueError("The reopened SDK session must already exist")
    catalog = MemorySessionCatalog(db_path, clock_ms=lambda: clock)
    config = MemoryConfig(workspace_dir=workspace, store_path=directory / "index.sqlite",
        flags=FeatureFlags(vector_search=False, temporal_decay=False))
    runner = HostSessionRunner.open(workspace, catalog=catalog, config=config,
        session=SessionState.new(session_key=value["sessionKey"], session_id=value["sessionId"]),
        identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY, seed_bootstrap=False, now_ms=lambda: clock,
        timezone="UTC", time_format="24")
    history = HistoryReplayContext(model, {"channels": {"telegram": {"dmHistoryLimit": value["historyLimit"]}}},
                                  {"accountId": "default", "peerId": "assembly-peer", "chatType": "direct"})
    options = RuntimePromptInput(history_replay=history, offered_tool_names=["memory_get"])
    raw = {"pid": os.getpid(), "ppid": os.getppid(), "phase": phase, "caseSha256": digest(wire(case)),
           "database": str(db_path), "sourceFile": str(Path(__file__).resolve()), "hostCalls": []}
    prompts = value["users"] if phase == "seed" else [value["prompt"]]
    for index, prompt in enumerate(prompts):
        async def execute(turn):
            if phase == "reopen":
                raw["wireInput"] = turn.responses_input()
                raw["stages"] = turn.model_prompt.history_replay.stages
                message = assistant(model, clock, value["attemptResponseId"], "stop")
                complete_text(message, value["replyItem"])
                turn.record_message(message)
            else:
                if index == value["checkpointAfterUser"]:
                    checkpoint = assistant(model, clock, value["seedResponseIds"][0], "stop")
                    tracker = turn.responses_compaction_tracker(checkpoint)
                    item = value["checkpointItem"]
                    tracker.added(item, len(checkpoint["content"]))
                    tracker.completed(item, len(checkpoint["content"]))
                    complete_text(checkpoint, value["checkpointTextItem"])
                    turn.record_message(checkpoint)
                if index == len(prompts) - 1:
                    item = value["callItem"]
                    generated = assistant(model, clock, value["seedResponseIds"][1], "toolUse")
                    call = {"type": "toolCall", "id": item["call_id"] + "|" + item["id"],
                            "name": item["name"], "arguments": json.loads(item["arguments"])}
                    generated["content"].append(call)
                    turn.record_message(generated)
                    raw["tool"] = turn.dispatch(call["id"], call["name"], call["arguments"])
            return HostModelResult()
        outcome = await runner.run_turn(prompt, execute=execute, prompt_context=options,
                                        request_id=f"assembly-{phase}-{index}")
        if not outcome.ready:
            raise ValueError(f"SDK {phase} failed: {outcome.failures}")
        raw["hostCalls"].append({"request": prompt, "ready": outcome.ready,
            "transcriptCommitted": outcome.transcript_committed, "turnId": outcome.turn_id})
    return raw


def run_sdk(case, directory):
    directory = Path(directory)
    request = directory / "case.json"
    request.write_bytes(wire(case))
    processes = []
    for phase in ("seed", "reopen"):
        command = [sys.executable, "-m", "equivalence.compaction_assembly_sdk", phase, str(request)]
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=Path(__file__).resolve().parents[1],
            env={"PATH": os.defpath, "TZ": "UTC", "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"})
        try:
            stdout, stderr = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise
        (directory / (phase + ".out")).write_bytes(stdout)
        (directory / (phase + ".err")).write_bytes(stderr)
        if proc.returncode:
            raise ValueError(f"SDK {phase} failed: {stderr.decode(errors='replace')[-1200:]}")
        processes.append({"pid": proc.pid, "ppid": os.getpid(), "exitCode": proc.returncode, "phase": phase,
            "stdoutSha256": digest(stdout), "stderrSha256": digest(stderr), "command": command})
        if phase == "seed":
            with closing(sqlite3.connect(directory / "catalog.sqlite")) as source, closing(
                    sqlite3.connect(directory / "seed.sqlite")) as target:
                source.backup(target)
    raw = {"caseSha256": digest(wire(case)), "processes": processes,
           "driverSha256": digest(Path(__file__).read_bytes())}
    actual = read_sdk(case, raw, directory, directory)
    (directory / "python-raw.json").write_bytes(wire([raw]))
    return actual


def read_sdk(case, raw, recorded_root, retained_root):
    directory = Path(retained_root)
    recorded = Path(recorded_root)
    value = case["input"]
    if (raw["driverSha256"] != digest(Path(__file__).read_bytes()) or
            raw["caseSha256"] != digest(wire(case)) or (directory / "case.json").read_bytes() != wire(case)):
        raise ValueError("Different SDK case or driver")
    executions = []
    if len({r["pid"] for r in raw["processes"]}) != 2:
        raise ValueError("The two SDK captures must be separate processes")
    for phase, os_record in zip(("seed", "reopen"), raw["processes"], strict=True):
        stdout, stderr = [(directory / (phase + ext)).read_bytes() for ext in (".out", ".err")]
        result = json.loads(stdout)
        prompts = value["users"] if phase == "seed" else [value["prompt"]]
        if (result["pid"] != os_record["pid"] or result["ppid"] != os_record["ppid"] or os_record["phase"] != phase
                or os_record["exitCode"] != 0 or [digest(stdout), digest(stderr)] !=
                [os_record["stdoutSha256"], os_record["stderrSha256"]] or result["phase"] != phase
                or result["database"] != str(recorded / "catalog.sqlite") or result["caseSha256"] != raw["caseSha256"]
                or os_record["command"][1:] != ["-m", "equivalence.compaction_assembly_sdk", phase, str(recorded / "case.json")]
                or result["hostCalls"] != [{"request": p, "ready": True, "transcriptCommitted": True,
                                           "turnId": f"assembly-{phase}-{i}"} for i, p in enumerate(prompts)]):
            raise ValueError("The SDK did not run both registered normal host callbacks")
        executions.append(result)
    before, after = [read_events(directory / name, value["sessionId"]) for name in ("seed.sqlite", "catalog.sqlite")]
    if (after[:len(before)] != before or len(after) <= len(before)
            or (directory / "workspace" / value["file"]["path"]).read_text() != value["file"]["text"]):
        raise ValueError("The SDK did not reopen its durable seed state")
    facts = retained(after)
    if facts["result"]["details"] != executions[0]["tool"]:
        raise ValueError("Persisted tool result disagrees with the actual memory tool")
    stages = {r["stage"]: r["messages"] for r in executions[1]["stages"]}
    if len(stages["session:limited"]) >= len(stages["session:validated"]):
        raise ValueError("The SDK did not apply the configured history limit")
    if value["checkpointAfterUser"] == 0:
        owner = stages["session:limited"][0]
        if (owner.get("responseId") != value["seedResponseIds"][0] or owner["content"] != []
                or owner.get("providerReplay") != facts["checkpoint"]
                or any(m.get("responseId") == owner["responseId"] for m in stages["stream:context"])):
            raise ValueError("The SDK lost the projected checkpoint before the final message filter")
    final_assistant = after[-1].get("message", {})
    if (final_assistant.get("responseId") != value["attemptResponseId"] or
            not any(e.get("message", {}).get("content") == value["prompt"] for e in after[len(before):])):
        raise ValueError("The SDK failed to persist the reopened response and its prompt")
    return {"input": executions[1]["wireInput"], "tool": executions[0]["tool"],
            "retainedBefore": retained(before), "retainedAfter": facts}


if __name__ == "__main__":
    phase, input_path = sys.argv[1:]
    request = Path(input_path)
    sys.stdout.buffer.write(wire(asyncio.run(drive(json.loads(request.read_bytes()), request.parent, phase))))
