"""Authenticate two cold processes and reread the original retained session and HTTP wire."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile

from equivalence.compaction_assembly_inputs import inputs
from equivalence.heartbeat_runtime_bindings import REFERENCE_COMMIT
from equivalence.model_runtime_authority import prepare_model_node_authority
from equivalence.release_runtime import prepare_release_runtime

MODULE = Path(__file__).resolve().parent
DRIVER = MODULE / "compaction_assembly_native.mjs"
PRELOAD = MODULE / "compaction_assembly_native_preload.mjs"
SOURCE_OWNERS = (
    "src/agents/harness/context-engine-lifecycle.ts", "src/context-engine/legacy.ts", "src/agents/cache-trace.ts",
    "src/agents/embedded-agent-runner/history.ts", "src/agents/embedded-agent-runner/run/attempt-history-prepare.ts",
    "src/agents/embedded-agent-runner/run/attempt.ts", "src/agents/embedded-agent-runner/run/attempt-prompt-build.ts",
    "src/agents/sessions/session-manager.ts", "src/agents/sessions/session-manager-codec.ts",
    "src/agents/embedded-agent-helpers/openai.ts", "src/agents/embedded-agent-runner/run/attempt-llm-boundary.ts",
    "packages/ai/src/providers/openai-responses.ts", "packages/ai/src/providers/openai-provider-client.ts",
    "packages/ai/src/transports/openai-responses-compaction-replay.ts", "packages/ai/src/transports/provider-compaction-replay.ts",
    "extensions/openai/index.ts", "extensions/memory-core/src/tools.ts", "extensions/memory-core/src/memory-read-tool.ts",
)
HARN = "dist/builtin-openclaw-D1Xfnzzr.mjs"
SQL = "dist/session-accessor-CiKKTlbe.mjs"
AI = "dist/openai-responses-cNWyKDF8.mjs"


def wire(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _artifact(root, recorded, original):
    relative = Path(original).relative_to(recorded)
    if any(part in (".", "..") for part in relative.parts):
        raise ValueError("Noncanonical original assembly output")
    target = root / relative
    if target.resolve(strict=True) != target or not target.is_file():
        raise ValueError("Assembly output escaped its captured directory")
    return target


def _rows(path, session_id):
    with sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True) as db:
        rows = db.execute("SELECT seq,event_json,event_zstd FROM transcript_events WHERE session_id=? ORDER BY seq", (session_id,)).fetchall()
    if not rows or any(i != seq or compressed is not None or not text for i, (seq, text, compressed) in enumerate(rows)):
        raise ValueError("Unexpected physical original assembly transcript")
    return [json.loads(text) for _, text, _ in rows]


def _facts(events, definition):
    messages = [event["message"] for event in events if event.get("type") == "message"]
    checkpoint, = [m["providerReplay"] for m in messages if m.get("providerReplay", {}).get("id") == definition["checkpointItem"]["id"]]
    call, = [block for m in messages if m.get("role") == "assistant" for block in m["content"]
             if block.get("type") == "toolCall" and block.get("name") == definition["callItem"]["name"]]
    result, = [m for m in messages if m.get("role") == "toolResult" and m["toolCallId"] == call["id"]]
    return {"checkpoint": checkpoint, "call": call, "result": {key: value for key, value in result.items() if key not in ("timestamp", "__openclaw")}}


def _check_trace(directory, rows, phases, node, context_sha):
    files, loaded, boots = [], set(), []
    for filename in sorted(directory.glob("trace-*.jsonl")):
        payload = filename.read_bytes()
        head, *records = [json.loads(line) for line in payload.splitlines()]
        pid, tid = head["pid"], head["threadId"]
        if (head.get("event") != "bootstrap" or head.get("node") != str(node) or head.get("contextSha256") != context_sha
                or filename.name != f"trace-{pid}-{tid}.jsonl"):
            raise ValueError("Original assembly trace bootstrap changed")
        if pid in phases:
            phase = phases[pid]
            if tid == 0 and (head["entry"] != str(DRIVER) or head["ppid"] != os.getpid()):
                raise ValueError("Unexpected assembly process bootstrap")
        elif head["ppid"] in phases:
            phase = phases[head["ppid"]]
        else:
            raise ValueError("Unexpected assembly worker lineage")
        indices = [r["load"] for r in records]
        if (len(indices) != len(set(indices)) or any(type(i) is not int or not 0 <= i < len(rows) for i in indices)):
            raise ValueError("Invalid original assembly module trace")
        if pid in phases and tid == 0:
            must = {AI, SQL, DRIVER.name, "dist/internal/openai.mjs"}
            must.add("dist/tools-DotaQGXh.mjs" if phase == "seed" else HARN)
            if not must <= {rows[i][3] for i in indices}:
                raise ValueError("Missing original assembly phase code owners")
        loaded.update(indices)
        boots.append({**head, "phase": phase})
        files.append({"path": str(filename), "sha256": digest(payload), "loads": len(records)})
    if not all(any(h["pid"] == pid and h["threadId"] == 0 for h in boots) for pid in phases):
        raise ValueError("Missing original assembly process")
    table = {str(i): {"package": rows[i][2], "path": rows[i][3], "sha256": rows[i][1]} for i in sorted(loaded)}
    (directory / "loaded-modules.json").write_bytes(wire(table))
    return {"bootstraps": boots, "traces": files, "moduleTableSha256": digest(wire(table)),
            "loaded": sorted([v for v in table.values() if v["package"] != "driver"], key=lambda row: (row["package"], row["path"]))}


def run_native(case, *, checkout: Path, runtime_root: Path, node: Path, evidence_directory: Path, runtime=None):
    if case["input"] not in inputs().values():
        raise ValueError("Unreviewed context assembly configuration")
    root = runtime_root.resolve(strict=True)
    checkout = checkout.resolve(strict=True)
    runtime = runtime or prepare_release_runtime(checkout, root.parents[1])
    if (runtime["runtimeRoot"] != str(root) or runtime["kind"] != "verified-release-runtime"
            or runtime["buildAttestation"]["commit"] != REFERENCE_COMMIT):
        raise ValueError("Original assembly requires the pinned runtime")
    node = node.resolve(strict=True)
    authority = prepare_model_node_authority(node)
    sources = []
    for name in SOURCE_OWNERS:
        committed = subprocess.check_output(["git", "-C", str(checkout), "show", REFERENCE_COMMIT + ":" + name])
        if (checkout / name).read_bytes() != committed:
            raise ValueError("Changed assembly source owner: " + name)
        sources.append({"path": name, "sha256": digest(committed)})
    rows = [(str(Path(pkg["directory"]) / item["path"]), item["sha256"], pkg["location"], item["path"])
            for pkg in runtime["packages"] for item in pkg["files"]]
    rows.append((str(DRIVER), digest(DRIVER.read_bytes()), "driver", DRIVER.name))
    directory = evidence_directory.resolve() / "context-assembly-original"
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    for part in ("tmp", "cache", "state"):
        (directory / part).mkdir()
    request = directory / "request.json"
    request.write_bytes(wire(case))
    phases = {}
    with tempfile.TemporaryDirectory(prefix="assembly-authority-") as temp:
        context = Path(temp) / "authority.json"
        payload = wire({"files": [row[:2] for row in rows], "trace": str(directory / "trace")})
        context.write_bytes(payload)
        env = {"TZ": "UTC", "LC_ALL": "C.UTF-8", "PATH": str(node.parent) + os.pathsep + os.defpath,
               "HOME": str(directory), "TMPDIR": str(directory / "tmp"), "XDG_CACHE_HOME": str(directory / "cache"),
               "OPENCLAW_STATE_DIR": str(directory / "state"), "OPENCLAW_HOME": str(directory), "JITI_FS_CACHE": "false",
               "MEMORY_EQ_ASSEMBLY_AUTHORITY": str(context), "NODE_OPTIONS": "--import=" + PRELOAD.as_uri()}
        for phase in ("seed", "reopen"):
            with (directory / (phase + ".stdout")).open("xb") as stdout, (directory / (phase + ".stderr")).open("xb") as stderr:
                with subprocess.Popen([str(node), str(DRIVER), str(request), str(root), str(directory), phase],
                                      cwd=directory, env=env, stdout=stdout, stderr=stderr) as process:
                    phases[process.pid] = phase
                    if process.wait(timeout=85):
                        raise ValueError("Original assembly " + phase + " failed: " + (directory / (phase + ".stderr")).read_text()[-1400:])
            phase_data = json.loads((directory / (phase + ".json")).read_bytes())
            if phase_data["pid"] != process.pid:
                raise ValueError("Phase output came from a different process")
            # A transactionally coherent database copied before any reader or writer reopens it.
            sqlite = Path(phase_data["databasePath"])
            with sqlite3.connect(sqlite.as_uri() + "?mode=ro", uri=True) as source, sqlite3.connect(directory / (phase + ".sqlite")) as snapshot:
                source.backup(snapshot)
        trace = _check_trace(directory, rows, phases, node, digest(payload))
    artifacts = ["request.json", "seed.json", "reopen.json", "seed.sqlite", "reopen.sqlite", "loaded-modules.json",
                 "cache.jsonl", "workspace/" + case["input"]["file"]["path"]]
    raw = {"directory": str(directory), "launches": [{"pid": p, "phase": v} for p, v in phases.items()],
           "sourceOwners": sources, "nodeRuntime": authority, "driverSha256": digest(DRIVER.read_bytes()),
           "preloadSha256": digest(PRELOAD.read_bytes()), "artifacts": {name: digest((directory / name).read_bytes()) for name in artifacts}}
    actual = read_native(case, raw, directory.parent, directory.parent, trace)
    return {"actual": actual, "raw": raw, "releaseSources": trace["loaded"], "releaseTrace": trace}


def read_native(case, raw, recorded_root, retained_root, trace):
    """Re-read the original HTTP capture, transcript snapshots and module trace after relocation."""
    original = Path(raw["directory"])
    record_base, retained = Path(recorded_root), Path(retained_root).resolve(strict=True)
    value = case["input"]
    if (value not in inputs().values() or raw["driverSha256"] != digest(DRIVER.read_bytes())
            or raw["preloadSha256"] != digest(PRELOAD.read_bytes())):
        raise ValueError("Unrecognized original compaction authority")
    names = {"request.json", "seed.json", "reopen.json", "seed.sqlite", "reopen.sqlite", "loaded-modules.json",
             "cache.jsonl", "workspace/" + value["file"]["path"]}
    if set(raw["artifacts"]) != names:
        raise ValueError("Incomplete original assembly artifact set")
    files = {name: _artifact(retained, record_base, original / name) for name in names}
    if any(digest(files[name].read_bytes()) != expected for name, expected in raw["artifacts"].items()):
        raise ValueError("Original assembly evidence bytes changed")
    if json.loads(files["request.json"].read_bytes()) != case or files["workspace/" + value["file"]["path"]].read_bytes() != value["file"]["text"].encode():
        raise ValueError("The original assembly did not use the declared common input")
    table = json.loads(files["loaded-modules.json"].read_bytes())
    if (digest(files["loaded-modules.json"].read_bytes()) != trace["moduleTableSha256"]
            or sorted((row for row in table.values() if row["package"] != "driver"), key=lambda r: (r["package"], r["path"])) != trace["loaded"]):
        raise ValueError("Context assembly loaded module identity changed")
    loaded = set()
    observed = []
    for entry in trace["traces"]:
        payload = _artifact(retained, record_base, entry["path"]).read_bytes()
        head, *rows = [json.loads(line) for line in payload.splitlines()]
        if (digest(payload) != entry["sha256"] or len(rows) != entry["loads"] or
                not any(head == {k: v for k, v in b.items() if k != "phase"} for b in trace["bootstraps"])):
            raise ValueError("Original assembly module log changed")
        indices = [str(row["load"]) for row in rows]
        if len(set(indices)) != len(indices) or any(index not in table for index in indices):
            raise ValueError("Invalid assembly load IDs")
        loaded.update(indices)
        observed.append(head)
    if loaded != set(table) or len(observed) != len(trace["bootstraps"]):
        raise ValueError("Missing assembly import observations")
    seed, reopen = (json.loads(files[name + ".json"].read_bytes()) for name in ("seed", "reopen"))
    scoped = {"sessionId": value["sessionId"], "sessionKey": value["sessionKey"], "agentId": "main",
              "storePath": str(original / "sessions.json")}
    for phase, out, clock in (("seed", seed, value["seedMs"]), ("reopen", reopen, value["attemptMs"])):
        matching = [b for b in trace["bootstraps"] if b["phase"] == phase and b["threadId"] == 0 and b["entry"].endswith("/" + DRIVER.name)]
        if (len(matching) != 1 or matching[0]["pid"] != out["pid"] or out["phase"] != phase
                or out["clock"] != clock or out["scope"] != scoped or out["node"] != matching[0]["node"]
                or out["config"]["tools"]["allow"] != ["memory_get"] or out["config"]["channels"]["telegram"]["dmHistoryLimit"] != value["historyLimit"]):
            raise ValueError("Original assembly phase identity or scope changed")
    if (seed["pid"] == reopen["pid"] or raw["launches"] != [{"pid": seed["pid"], "phase": "seed"}, {"pid": reopen["pid"], "phase": "reopen"}]
            or seed["databasePath"] != reopen["databasePath"] or Path(seed["databasePath"]).name != "openclaw-agent.sqlite"):
        raise ValueError("Original assembly did not cold-reopen the same database")
    before = _rows(files["seed.sqlite"], value["sessionId"])
    after = _rows(files["reopen.sqlite"], value["sessionId"])
    if not (before == seed["events"] == seed["persisted"] == reopen["before"] == after[:len(before)]
            and after == reopen["after"] and len(after) > len(before)):
        raise ValueError("Original physical assembly transcript differs from session API results")
    facts, kept = _facts(before, value), _facts(after, value)
    if (facts != kept or facts["checkpoint"] != seed["checkpointAssistant"].get("providerReplay")
            or seed["callAssistant"].get("content") != [facts["call"]]
            or seed["tool"]["details"] != facts["result"]["details"] or seed["tool"]["content"] != facts["result"]["content"]
            or json.loads(seed["tool"]["content"][0]["text"]) != seed["tool"]["details"]):
        raise ValueError("Original provider continuation or actual memory tool response lost durable identity")
    if reopen["result"]["terminal"] != {"kind": "ok"} or not reopen["result"]["hasSuccessfulModelResponse"]:
        raise ValueError("Original embedded attempt did not complete with a successful model response")
    if not {"openai", "memory-core"} <= {p["id"] for p in reopen["plugins"] if p["status"] == "loaded"}:
        raise ValueError("The original provider and memory plugin were not active")
    if len(seed["requests"]) != 2 or len(reopen["requests"]) != 1:
        raise ValueError("Missing or extra context assembly provider requests")
    for record, fixture_items, identifier in zip([*seed["requests"], *reopen["requests"]],
            ([value["checkpointItem"], value["checkpointTextItem"]], [value["callItem"]], [value["replyItem"]]),
            [*value["seedResponseIds"], value["attemptResponseId"]], strict=True):
        reply = record["reply"]
        chunks = reply["body"].split("\n\n")
        events = [json.loads(c.split("\ndata: ")[1]) for c in chunks[:-2]]
        if (record["method"] != "POST" or record["url"] != value["model"]["baseUrl"] + "/responses"
                or reply["status"] != 200 or reply["contentType"] != "text/event-stream"
                or chunks[-2:] != ["data: [DONE]", ""]
                or [e["item"] for e in events if e["type"] == "response.output_item.done"] != fixture_items
                or events[-1] != {"type": "response.completed", "response": {"id": identifier, "status": "completed", "output": fixture_items}}):
            raise ValueError("Original offline provider response differs from the declared inputs")
    request = json.loads(reopen["requests"][0]["body"])
    if request["model"] != value["attemptModelId"] or [t["name"] for t in request["tools"]] != ["memory_get"]:
        raise ValueError("Genuine reopened request used an unexpected route or tool set")
    stages = [json.loads(line) for line in files["cache.jsonl"].read_bytes().splitlines()]
    stage = {s["stage"]: s for s in stages if s["runId"] == "assembly-reopen"}
    if not {"session:loaded", "session:sanitized", "session:limited", "prompt:before", "stream:context", "session:after"} <= stage.keys():
        raise ValueError("Missing original context-preparation or transport-stage evidence")
    if len(stage["session:limited"]["messages"]) >= len(stage["session:loaded"]["messages"]):
        raise ValueError("Original history limit did not truncate the active transcript")
    visible = request["input"]
    # The upstream cache trace redacts opaque replay metadata in displayed messages.
    # Its pre-redaction per-message SHA-256 still binds the entire original checkpoint.
    limited = stage["session:limited"]
    index, = [i for i, message in enumerate(limited["messages"]) if message.get("responseId") == value["seedResponseIds"][0]]
    restored = {**limited["messages"][index], "providerReplay": facts["checkpoint"]}
    if digest(wire(restored)) != limited["messageFingerprints"][index]:
        raise ValueError("Original limited history lost authenticated provider replay metadata")
    if value["checkpointAfterUser"] == 0:
        projected = stage["session:limited"]["messages"][0]
        if (projected.get("responseId") != value["seedResponseIds"][0] or projected["content"] != []
                or any(m.get("responseId") == projected["responseId"] for m in stage["prompt:before"]["messages"])):
            raise ValueError("Missing intermediate observation of the cropped checkpoint owner")
    checkpoint = [item for item in visible if item["type"] == "compaction"]
    expected = [value["checkpointItem"]] if value["checkpointAfterUser"] == 2 and value["model"]["id"] == value["attemptModelId"] else []
    if (checkpoint != expected or [r["output"] for r in visible if r["type"] == "function_call_output"] != [facts["result"]["content"][0]["text"]]
            or [r["call_id"] for r in visible if r["type"] == "function_call"] != [value["callItem"]["call_id"]]):
        raise ValueError("Original reopened provider request lost a required control or tool output")
    return {"input": visible, "tool": seed["tool"]["details"], "retainedBefore": facts, "retainedAfter": kept}
