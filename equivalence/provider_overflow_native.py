"""Authenticate the pinned original run and reopen the real transcript and dispatch records."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
from contextlib import closing
from hashlib import sha256

from equivalence.compaction_assembly_inputs import inputs as assembly_inputs
from equivalence.heartbeat_runtime_bindings import REFERENCE_COMMIT
from equivalence.model_runtime_authority import prepare_model_node_authority
from equivalence.provider_overflow_cases import build_cases, wire

DIR = Path(__file__).resolve().parent
DRIVER = DIR / "provider_overflow_native.mjs"
ASSEMBLY = DIR / "compaction_assembly_native.mjs"
CHECKPOINT = DIR / "provider_overflow_checkpoint.mjs"
PRELOAD = DIR / "provider_overflow_preload.mjs"
PLUGIN = DIR / "prompt-runtime-provider/index.mjs"
SOURCE = (
    "src/agents/embedded-agent-runner/run-orchestrator.ts", "src/agents/embedded-agent-runner/run/attempt-recovery.ts",
    "src/agents/embedded-agent-runner/run/attempt-prompt-phase.ts", "src/agents/embedded-agent-runner/run/attempt-prompt-preflight.ts",
    "src/agents/embedded-agent-runner/run/overflow-context-recovery.ts", "src/agents/embedded-agent-runner/run/compaction-runtime.ts",
    "src/agents/embedded-agent-runner/run/attempt-setup.ts", "src/agents/embedded-agent-runner/tool-result-context-guard.ts",
    "src/agents/embedded-agent-runner/tool-result-truncation.ts", "src/agents/embedded-agent-runner/run/session-prompt-state.ts",
    "src/agents/sessions/agent-session-compaction.ts", "packages/agent-core/src/harness/compaction/compaction.ts",
    "src/agents/embedded-agent-runner/transcript-rewrite.ts", "src/agents/embedded-agent-runner/run/attempt-terminal-evidence.ts",
)
HARN = "dist/builtin-openclaw-D1Xfnzzr.mjs"
EMBED = "dist/embedded-agent-gxn-c3nS.mjs"
SQL = "dist/session-accessor-CiKKTlbe.mjs"
AI = "dist/internal/openai.mjs"
CONTINUE = ("Continue the current task from the existing transcript, preserving completed work. "
            "If an action was interrupted, inspect its state before deciding whether to retry it. Do not restart the task or repeat completed actions.")


def digest(data):
    return sha256(data).hexdigest()


def _file(directory, name):
    path = (directory / name).resolve(strict=True)
    if not path.is_relative_to(directory) or path != directory / name or not path.is_file():
        raise ValueError("Overflow evidence was moved outside its attempt")
    return path


def _rows(database, session):
    from zstandard import ZstdDecompressor

    with closing(sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True)) as connection:
        values = connection.execute(
            "SELECT seq,event_json,event_zstd FROM transcript_events WHERE session_id=? ORDER BY seq", (session,)
        ).fetchall()
    rows = []
    for index, (seq, text, compressed) in enumerate(values):
        if seq != index or (text is None) == (compressed is None):
            raise ValueError("Original transcript has missing or ambiguous physical rows")
        if compressed is not None:
            with ZstdDecompressor().stream_reader(io.BytesIO(compressed)) as stream:
                text = stream.read(8 * 1024 * 1024 + 1)
            if len(text) > 8 * 1024 * 1024:
                raise ValueError("Unexpectedly large original transcript event")
        rows.append(json.loads(text))
    return rows


def _phase_cases(case):
    if "checkpoint" not in case["input"]:
        return [("run", DRIVER, case)]
    spec = case["input"]
    data = assembly_inputs()[spec["checkpoint"]]
    data["model"]["contextWindow"] = spec["contextWindow"]
    data.update(prompt=spec["prompt"] * spec["promptRepeat"], seedMs=spec["clock"] - 60_000, attemptMs=spec["clock"])
    seed = ("seed", ASSEMBLY, {"input": data})
    if spec.get("outerRecovery"):
        return [seed, ("recovery", CHECKPOINT, {"input": {**data, "sequence": spec["sequence"]}})]
    return [seed, ("reopen", ASSEMBLY, {"input": data})]


def _logs(directory, phases, table, node_path, identity):
    receipts, loads, main = [], set(), set()
    root_pids = {p["pid"]: p for p in phases}
    for path in sorted(directory.glob("trace-*.jsonl")):
        payload = path.read_bytes()
        head, *records = [json.loads(line) for line in payload.splitlines()]
        pid, parent, tid = head["pid"], head["ppid"], head["threadId"]
        process = root_pids.get(pid) or root_pids.get(parent)
        if not process or head["event"] != "bootstrap" or head["node"] != node_path or head["contextSha256"] != identity:
            raise ValueError("A captured overflow worker lacks its parent's official runtime authority")
        if path.name != f"trace-{pid}-{tid}.jsonl":
            raise ValueError("Unexpected process or worker trace filename")
        indices = [r["load"] for r in records]
        if any(type(i) is not int or str(i) not in table for i in indices) or len(indices) != len(set(indices)):
            raise ValueError("Invalid overflow module trace indices")
        if tid == 0 and pid in root_pids:
            if head["entry"] != process["driver"] or parent != process["parent"]:
                raise ValueError("Original overflow engine has different process ancestry")
            names = {table[str(i)]["path"] for i in indices}
            required = {Path(head["entry"]).name, SQL}
            if process["phase"] == "run":
                if not any(table[str(i)] == {"package": "driver", "path": PLUGIN.name, "sha256": digest(PLUGIN.read_bytes())}
                           for i in indices):
                    raise ValueError("The original did not instantiate the registered offline provider")
                required |= {EMBED, HARN, "dist/session-accessor.sqlite-read-BsSfe2AE.mjs"}
            elif process["phase"] == "recovery":
                required |= {HARN, EMBED, AI}
            elif process["phase"] == "reopen":
                required |= {HARN, AI}
            else:
                required |= {AI, "dist/tools-DotaQGXh.mjs"}
            if not required <= names:
                raise ValueError("Missing overflow module owners: " + str(required - names))
            main.add(pid)
        loads.update(str(i) for i in indices)
        receipts.append({"filename": path.name, "sha256": digest(payload), "phase": process["phase"], "bootstrap": head,
                         "loads": len(indices)})
    if main != set(root_pids):
        raise ValueError("An original overflow process lacks its load trace")
    return receipts, loads


def _text(content):
    if isinstance(content, str):
        return content
    return "".join(b["text"] for b in content if b.get("type") == "text")


def _observation(case, original, log, physical_rows):
    spec = case["input"]
    if original["after"] != physical_rows:
        raise ValueError("The SQLite transcript differs from the original visible owner")
    user = spec["prompt"] * spec["promptRepeat"]
    before_ids = {r.get("id") for r in original["before"]}
    physical_by_id = {e.get("id"): e for e in physical_rows}
    if any(physical_by_id.get(e.get("id")) != e for e in original["before"]):
        raise ValueError("The run replaced an existing stored transcript event")
    new_events = [e for e in physical_rows if e.get("id") not in before_ids]
    admitted = sum(e.get("type") == "message" and e["message"]["role"] == "user"
                   and _text(e["message"]["content"]).strip() == user.strip() for e in new_events)
    checkpoints = [e for e in new_events if e.get("type") == "compaction"]
    if any(not e.get("summary") or not e.get("firstKeptEntryId") for e in checkpoints):
        raise ValueError("An original summary lacks its durable boundary")
    result = original["result"]
    if spec.get("outerRecovery"):
        return _checkpoint_recovery(case, original, log, admitted, checkpoints)
    if "checkpoint" in spec:
        recovery = result["preflightRecovery"]
        if (result["terminal"].get("source") != "precheck" or recovery["overflowTokens"] <= 0 or original["requests"]
                or not any(e.get("message", {}).get("providerReplay") for e in physical_rows)):
            raise ValueError("Original eligible checkpoint must stop before the provider")
        return {"preflight": [{"route": recovery["route"], "admitted": False}], "midturn": [],
                "dispatches": [], "tools": [], "compactionAttempts": 0, "compactionsCommitted": len(checkpoints),
                "durableUserAdmissions": admitted, "durableToolResults": [], "terminal": {"kind": "precheck", "text": None}}
    preflight, midturn, attempts = [], [], 0
    for line in log.splitlines():
        message = json.loads(line).get("1")
        if not isinstance(message, str):
            continue
        if message.startswith("[context-overflow-precheck] pre-prompt check "):
            preflight.append({"route": re.search(r" route=([a-z_]+) ", message)[1], "admitted": True})
        if message.startswith("[context-overflow-midturn-precheck] tool-result-guard check "):
            midturn.append(re.search(r" route=([a-z_]+) ", message)[1])
        if message.startswith("[compaction-diag] start "):
            attempts += 1
    calls = []
    if len(original["calls"]) != len(spec["sequence"]):
        raise ValueError("Unexpected original provider dispatch count")
    for record, expected in zip(original["calls"], spec["sequence"], strict=True):
        messages, response = record["context"]["messages"], record["assistant"]
        last = _text(messages[-1]["content"])
        summary = len(messages) == 1 and "<conversation>" in last and "</conversation>" in last
        if response["stopReason"] == "toolUse":
            reply = {"read": len(response["content"])}
        elif response["stopReason"] == "error":
            reply = {"error": response["errorMessage"]}
        else:
            reply = {"text": _text(response["content"])}
        if reply != expected:
            raise ValueError("Original provider returned a response outside its script")
        calls.append({"kind": "summary" if summary else "provider", "continuation": CONTINUE if last.endswith(CONTINUE) else None,
                      "reply": reply})
    before = [e["event"] for e in original["toolEvents"] if e["when"] == "before_tool_call"]
    after = [e["event"] for e in original["toolEvents"] if e["when"] == "after_tool_call"]
    completed = {e["toolCallId"]: e for e in after}
    if len(completed) != len(after) or {e["toolCallId"] for e in before} != set(completed) or len(before) != len(after):
        raise ValueError("Original tool completed without its matching admission")
    tools = []
    for event in before:
        done = completed[event["toolCallId"]]
        if done["params"] != event["params"] or done["toolName"] != event["toolName"] or "result" not in done:
            raise ValueError("An original tool completion has a different input, owner or missing result")
        tools.append({"id": event["toolCallId"], "name": event["toolName"], "arguments": event["params"]})
    tool_ids = {t["id"] for t in tools}
    results = [{"id": m["toolCallId"], "textSha256": digest(_text(m["content"]).encode())}
               for e in original["visible"] if (m := e.get("message", {})).get("role") == "toolResult"
               and m["toolCallId"] in tool_ids]
    if set(x["id"] for x in results) != tool_ids or len(results) != len(tool_ids):
        raise ValueError("A completed original tool is absent or duplicated in the durable branch")
    if case["id"] == "provider-overflow-midturn-truncate":
        first = {}
        for event in new_events:
            message = event.get("message", {})
            if message.get("role") == "toolResult" and message["toolCallId"] in tool_ids:
                first.setdefault(message["toolCallId"], digest(_text(message["content"]).encode()))
        changed = [r["id"] for r in results if first.get(r["id"]) != r["textSha256"]]
        counts = [int(m[1]) for line in log.splitlines() if isinstance(msg := json.loads(line).get("1"), str)
                  and (m := re.match(r"\[tool-result-truncation\] Truncated (\d+) tool result\(s\)", msg))]
        if not changed or len(changed) >= len(tools) or counts != [len(changed)]:
            raise ValueError("Stored truncated and protected tool results disagree with the original disjoint branch")
    [payload] = result["payloads"]
    failure = result["meta"].get("error", {}).get("kind")
    if (payload.get("isError") is True) != bool(failure):
        raise ValueError("The dispatch outcome disagrees with the run error")
    return {"preflight": preflight, "midturn": midturn, "dispatches": calls, "tools": tools,
            "compactionAttempts": attempts, "compactionsCommitted": len(checkpoints), "durableUserAdmissions": admitted,
            "durableToolResults": results, "terminal": {"kind": failure or "completed", "text": payload["text"]}}


def _checkpoint_recovery(case, original, log, admitted, checkpoints):
    """Reconstruct admissions from actual rejection, compaction dispatch and wire requests."""
    checks, attempts = [], 0
    for line in log.splitlines():
        message = json.loads(line).get("1")
        if not isinstance(message, str):
            continue
        if message.startswith("[context-overflow-precheck] pre-prompt check "):
            checks.append({"route": re.search(r" route=([a-z_]+) ", message)[1], "admitted": None})
        elif message.startswith("[context-overflow-diag]") and "source=promptError trigger=budget" in message:
            if not checks or checks[-1]["admitted"] is not None:
                raise ValueError("Context rejection did not follow an original precheck")
            checks[-1]["admitted"] = False
        elif message.startswith("[context-pressure-diagnostic] admitted provider attempt "):
            if not checks or checks[-1]["admitted"] is not None:
                raise ValueError("Provider was admitted outside its original precheck")
            checks[-1]["admitted"] = True
        elif message.startswith("[compaction-diag] start "):
            attempts += 1
    calls = []
    raw_requests = original["requests"]
    for req, supplied in zip(raw_requests, case["input"]["sequence"], strict=True):
        if req["method"] != "POST" or req["url"] != original["model"]["baseUrl"] + "/responses":
            raise ValueError("Unknown original checkpoint provider method/endpoint")
        last = json.loads(req["body"])["input"][-1]
        if last.get("role") != "user":
            raise ValueError("An original checkpoint dispatch has no foreground or summary input")
        text = "".join(b["text"] for b in last["content"] if b["type"] == "input_text")
        result = req["response"]
        events = [json.loads(line[6:]) for line in result["body"].splitlines()
                  if line.startswith("data: {")]
        [completed] = [e for e in events if e["type"] == "response.completed"]
        [answer] = completed["response"]["output"]
        reply = {"text": "".join(b["text"] for b in answer["content"] if b["type"] == "output_text")}
        if result["status"] != 200 or result["contentType"] != "text/event-stream" or supplied != reply:
            raise ValueError("The captured checkpoint provider wire differs from the original reply")
        calls.append({"kind": "summary" if "<conversation>" in text and "</conversation>" in text else "provider",
                      "continuation": CONTINUE if text.endswith(CONTINUE) else None, "reply": reply})
    [payload] = original["result"]["payloads"]
    if (payload.get("isError") or original["result"]["meta"].get("error") or not checkpoints
            or not calls or checks[0]["admitted"] is not False or checks[-1]["admitted"] is not True
            or calls[-1]["kind"] != "provider" or len(calls) != len(raw_requests)):
        raise ValueError("The original checkpoint recovery lacks rejection, compaction and final admission")
    return {"preflight": checks, "midturn": [], "dispatches": calls, "tools": [],
            "compactionAttempts": attempts, "compactionsCommitted": len(checkpoints), "durableUserAdmissions": admitted,
            "durableToolResults": [], "terminal": {"kind": "completed", "text": payload["text"]}}


def run_native(case, node, checkout, runtime, directory):
    if wire(case) not in {wire(c) for c in build_cases()} or runtime["buildAttestation"]["commit"] != REFERENCE_COMMIT:
        raise ValueError("Unexpected overflow case or original release")
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    for part in ("tmp", "state", "cache"):
        (directory / part).mkdir()
    node = node.resolve(strict=True)
    root = Path(runtime["runtimeRoot"])
    sources = []
    for name in SOURCE:
        data = (checkout / name).read_bytes()
        if subprocess.check_output(["git", "show", REFERENCE_COMMIT + ":" + name], cwd=checkout) != data:
            raise ValueError("Changed original overflow source owner: " + name)
        sources.append({"path": name, "sha256": digest(data)})
    table_rows = [(str(Path(pkg["directory"]) / f["path"]), f["sha256"], pkg["location"], f["path"])
                  for pkg in runtime["packages"] for f in pkg["files"]]
    table_rows.extend((str(f), digest(f.read_bytes()), "driver", f.name) for f in (DRIVER, ASSEMBLY, CHECKPOINT, PLUGIN))
    table = {str(i): {"package": pkg, "path": f, "sha256": h} for i, (_, h, pkg, f) in enumerate(table_rows)}
    captures, artifacts = [], []
    (directory / "case.json").write_bytes(wire(case))
    phases = _phase_cases(case)
    with tempfile.TemporaryDirectory(prefix="provider-overflow-authority-") as temporary:
        authority = Path(temporary) / "identity.json"
        authority.write_bytes(wire({"files": [r[:2] for r in table_rows], "trace": str(directory / "trace"),
                                    "fixture": str(PLUGIN), "state": str(directory / "state")}))
        authority_sha = digest(authority.read_bytes())
        env = {"PATH": str(node.parent) + os.pathsep + os.defpath, "TZ": "UTC", "LC_ALL": "C.UTF-8",
               "HOME": str(directory), "OPENCLAW_HOME": str(directory), "OPENCLAW_STATE_DIR": str(directory / "state"),
               "OPENCLAW_CONFIG_PATH": str(directory / "config.json"), "XDG_CACHE_HOME": str(directory / "cache"),
               "TMPDIR": str(directory / "tmp"), "JITI_FS_CACHE": "false", "MEMORY_EQ_ASSEMBLY_AUTHORITY": str(authority),
               "NODE_OPTIONS": "--import=" + PRELOAD.as_uri()}
        for phase, driver, request in phases:
            req = directory / (phase + "-input.json")
            req.write_bytes(wire(request))
            cmd = [str(node), str(driver)] + ([str(req), str(root), str(directory), phase] if driver == ASSEMBLY
                                              else [str(req), str(root), str(directory)])
            with (directory / (phase + ".out")).open("xb") as out, (directory / (phase + ".err")).open("xb") as err:
                with subprocess.Popen(cmd, stdout=out, stderr=err, env=env, cwd=directory) as process:
                    try:
                        status = process.wait(timeout=80)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        raise
            if status != 0:
                raise ValueError("Official overflow process failed: " + (directory / (phase + ".err")).read_text()[-1000:])
            item = "capture.json" if phase == "run" else phase + ".json"
            value = json.loads(_file(directory, item).read_bytes())
            if value["pid"] != process.pid:
                raise ValueError("Original overflow worker identity did not survive")
            source = Path(value.get("database") or value["databasePath"]).resolve(strict=True)
            if not source.is_relative_to(directory):
                raise ValueError("Original overflow database is outside its retained attempt")
            snapshot = phase + ".sqlite"
            with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as live, closing(sqlite3.connect(directory / snapshot)) as copy:
                live.backup(copy)
            artifacts.extend([item, snapshot, req.name, phase + ".out", phase + ".err"])
            captures.append({"phase": phase, "pid": process.pid, "parent": os.getpid(), "driver": str(driver),
                             "returncode": status, "result": item, "input": req.name, "snapshot": snapshot})
        receipts, loaded = _logs(directory, captures, table, str(node), authority_sha)
    retained = {i: table[i] for i in sorted(loaded, key=int)}
    (directory / "modules.json").write_bytes(wire(retained))
    final_log = {"recovery": "recovery.log", "reopen": "reopen.log", "run": "log.jsonl"}[captures[-1]["phase"]]
    artifacts.extend(["case.json", "modules.json", final_log])
    raw = {"sources": sources, "caseSha256": digest(wire(case)), "node": prepare_model_node_authority(node),
           "release": {key: runtime[key] for key in ("buildAttestation", "lockfileSha256", "manifestSha256")},
           "preloadSha256": digest(PRELOAD.read_bytes()), "phases": captures, "moduleAuthoritySha256": authority_sha,
           "receipts": receipts, "files": {p: digest(_file(directory, p).read_bytes()) for p in artifacts}}
    actual = read_native(case, raw, directory)
    diagnostic = wire([raw])
    (directory / "native-raw.json").write_bytes(diagnostic)
    return {"kind": "official-release-runtime-comparison", "sources": [],
            "results": [{"id": case["id"], "ok": True, "result": actual}],
            "releaseSources": [r for r in retained.values() if r["package"] != "driver"],
            "releaseTrace": {"phases": captures, "receipts": receipts, "moduleAuthoritySha256": authority_sha},
            "runtimeDiagnostics": [{"id": case["id"], "rawSnapshots": [raw], "sha256": digest(diagnostic),
                                    "validationStatus": "verified", "evidenceDirectory": str(directory)}]}


def read_native(case, raw, directory):
    directory = Path(directory).resolve()
    if (_file(directory, "case.json").read_bytes() != wire(case) or raw["caseSha256"] != digest(wire(case))
            or raw["preloadSha256"] != digest(PRELOAD.read_bytes()) or raw["release"]["buildAttestation"]["commit"] != REFERENCE_COMMIT
            or [s["path"] for s in raw["sources"]] != list(SOURCE)):
        raise ValueError("Retained overflow input, source or runtime changed")
    for name, sha in raw["files"].items():
        if digest(_file(directory, name).read_bytes()) != sha:
            raise ValueError("Retained overflow artifact changed: " + name)
    table = json.loads(_file(directory, "modules.json").read_bytes())
    driver_hashes = {f.name: digest(f.read_bytes()) for f in (DRIVER, ASSEMBLY, CHECKPOINT, PLUGIN)}
    if any(item["sha256"] != driver_hashes.get(item["path"]) for item in table.values() if item["package"] == "driver"):
        raise ValueError("A captured original driver no longer matches its loaded bytes")
    logs, loaded = _logs(directory, raw["phases"], table, raw["node"]["execPath"], raw["moduleAuthoritySha256"])
    if raw["receipts"] != logs or set(table) != loaded:
        raise ValueError("Incomplete original overflow process receipts")
    for (phase, driver, request), proc in zip(_phase_cases(case), raw["phases"], strict=True):
        if (proc["phase"] != phase or proc["returncode"] or Path(proc["driver"]).name != driver.name
                or _file(directory, proc["input"]).read_bytes() != wire(request)):
            raise ValueError("Different original dispatch inputs or process")
        original = json.loads(_file(directory, proc["result"]).read_bytes())
        physical = _rows(_file(directory, proc["snapshot"]), original["scope"]["sessionId"])
        if phase == "seed" and (original["persisted"] != physical or len(original["requests"]) != 2):
            raise ValueError("Unverified official checkpoint and tool seed")
    filename = {"recovery": "recovery.log", "reopen": "reopen.log", "run": "log.jsonl"}[raw["phases"][-1]["phase"]]
    return _observation(case, original, _file(directory, filename).read_text(), physical)
