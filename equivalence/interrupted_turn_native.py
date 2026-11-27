"""Physically interrupt and reopen the authenticated official OpenClaw dispatcher."""
from __future__ import annotations

import base64
from contextlib import closing
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import signal
import sqlite3
import stat
import subprocess
import tempfile

from equivalence.interrupted_turn_acceptance import DAILY_PATH, build_cases
from equivalence.model_runtime_authority import prepare_model_node_authority
from equivalence.release_runtime import prepare_release_runtime

HERE = Path(__file__).resolve().parent
ACTOR = HERE / "interrupted-turn-native.mjs"
PRELOAD = HERE / "interrupted-turn-native-preload.mjs"
PROVIDER = HERE / "host-turn-barrier-provider/index.mjs"
LOCAL = (ACTOR, PRELOAD, PROVIDER, PROVIDER.with_name("openclaw.plugin.json"))
OWNERS = ("dist/dispatch-from-config-BG9rT_X3.mjs", "dist/reply-dispatcher-XbSXLzuk.mjs",
          "dist/session-accessor-CiKKTlbe.mjs", "dist/tool-result-pairing-Cxh1CJVG.mjs",
          "dist/extensions/memory-core/manager-runtime.js")


def _bytes(path):
    info = path.lstat()
    if (path.resolve(strict=True) != path or not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1 or info.st_size > 64 * 1024 * 1024):
        raise ValueError("Invalid retained native observation")
    return path.read_bytes()


def _json(path):
    return json.loads(_bytes(path))


def _hash(path):
    return sha256(_bytes(path)).hexdigest()


def _save(path, obj):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(obj, stream, ensure_ascii=True, separators=(",", ":"))


@dataclass(frozen=True)
class _Authority:
    node: dict
    root: Path
    files: dict
    identity: dict


def authenticate_native(checkout, node, runtime):
    release = prepare_release_runtime(Path(checkout), Path(runtime))
    executable = prepare_model_node_authority(Path(node))
    local = {str(path): _hash(path) for path in LOCAL}
    files = {str(Path(pkg["directory"]) / item["path"]): item["sha256"]
             for pkg in release["packages"] for item in pkg["files"]}
    identity = {"release": release["buildAttestation"], "manifestSha256": release["manifestSha256"],
                "lockfileSha256": release["lockfileSha256"], "node": executable,
                "oracle": {str(path.relative_to(HERE)): local[str(path)] for path in LOCAL}}
    return _Authority(executable, Path(release["runtimeRoot"]), {**files, **local}, identity)


def _authority(checkout, node, runtime):
    if isinstance(runtime, _Authority):
        return runtime
    return authenticate_native(checkout, node, runtime)


def _read_db(path):
    return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)


def _physical(root, case, phase):
    """Keep checkpointed copies with WAL contents and separate byte-exact filesystem evidence."""
    capture = root / phase
    capture.mkdir()
    state = root / "state"
    with closing(_read_db(state / "openclaw-agent.sqlite")) as src:
        with closing(sqlite3.connect(capture / "session.sqlite")) as dest:
            src.backup(dest)
            dest.execute("PRAGMA journal_mode=DELETE")
    for label, relative in (("original", case["input"]["original"]["relativePath"]), ("independent", DAILY_PATH)):
        path = state / "workspace" / relative
        if path.exists() or path.is_symlink():
            (capture / label).write_bytes(_bytes(path))


def _history(db, session_id):
    with closing(_read_db(db)) as connection:
        rows = connection.execute("SELECT event_json, event_zstd FROM transcript_events WHERE session_id=? ORDER BY seq",
                                  (session_id,)).fetchall()
    if not rows or any(raw is None or compressed is not None for raw, compressed in rows):
        raise ValueError("Expected plain original session event rows for these small fixtures")
    return [json.loads(raw) for raw, _ in rows]


def _original(messages, original):
    calls, results = [], []
    for message in messages:
        if message.get("role") == "assistant":
            for block in message["content"]:
                if block.get("type") == "toolCall" and block["id"] == original["callId"]:
                    if (block["name"] != "write" or block["arguments"] !=
                            {"path": original["relativePath"], "content": original["content"]}):
                        raise ValueError("Original native write arguments or caller changed")
                    calls.append(block["id"])
        elif message.get("role") == "toolResult" and message["toolCallId"] == original["callId"]:
            if message.get("toolName") != "write":
                raise ValueError("Original native tool result bound to another producer")
            results.append({"id": message["toolCallId"], "isError": message.get("isError"), "content": message["content"]})
    return calls, results


def _boundary(directory, phase, observed, request):
    target = directory / phase
    disk = _history(target / "session.sqlite", request["identity"]["sessionId"])
    if disk != observed["transcript"] or observed["entry"]["sessionId"] != request["identity"]["sessionId"]:
        raise ValueError("Native accessor did not reproduce the retained SQLite state")
    files = {}
    for key, relative in (("original", request["original"]["relativePath"]), ("independent", DAILY_PATH)):
        path = target / key
        value = _bytes(path) if path.exists() or path.is_symlink() else None
        encoded = None if value is None else base64.b64encode(value).decode("ascii")
        if observed["files"][relative] != encoded:
            raise ValueError("Native file receipt differs from physical bytes")
        files[key] = None if value is None else value.decode("utf-8")
    calls, results = _original((row["message"] for row in disk if row["type"] == "message"), request["original"])
    return {"files": files, "originalCalls": calls, "originalResults": results}


def _environment(root, phase, auth):
    return {"PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC", "HOME": str(root / "home"),
            "TMPDIR": str(root / "tmp"), "XDG_CACHE_HOME": str(root / "cache"), "XDG_CONFIG_HOME": str(root / "xdg"),
            "OPENCLAW_HOME": str(root), "OPENCLAW_STATE_DIR": str(root), "OPENCLAW_CONFIG_PATH": str(root / "config.json"),
            "OPENCLAW_SKIP_CHANNELS": "1", "OPENCLAW_SKIP_CALENDAR": "1", "OPENCLAW_LOG_DIR": str(root / "logs"),
            "NODE_DISABLE_COMPILE_CACHE": "1", "JITI_FS_CACHE": "false", "CI": "true", "DO_NOT_TRACK": "1",
            "RECOVERY_AUTHORITY": str(auth), "root": str(root), "phase": phase}


def _run_phase(root, spec, phase, auth, authority):
    (root / (phase + "-trace")).mkdir()
    argv = [authority.node["execPath"], "--import", str(PRELOAD), str(ACTOR), str(spec), phase]
    with subprocess.Popen(argv, cwd=root, env=_environment(root, phase, auth), stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True) as process:
        try:
            output, _ = process.communicate(timeout=180)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise
        expected = -signal.SIGKILL if phase == "cut" else 0
        if process.returncode != expected:
            raise ValueError(f"Native {phase} returned {process.returncode}: {output[-3000:].decode(errors='replace')}")
        return {"pid": process.pid, "ppid": os.getpid(), "exit": process.returncode}


def _sources(directory, phase, process, authority):
    root = directory / "state"
    traces = sorted((root / (phase + "-trace")).glob("*.jsonl"))
    seen, main = set(), False
    for trace in traces:
        rows = [json.loads(line) for line in _bytes(trace).splitlines()]
        first = rows[0]
        if (first["event"] != "bootstrap" or first["phase"] != phase or first["node"] != authority.node
                or first["pid"] != process["pid"] or trace.name != f"{first['pid']}-{first['threadId']}.jsonl"
                or first["preloadSha256"] != authority.files[str(PRELOAD)] or first["ppid"] != process["ppid"]):
            raise ValueError("Unbound native process or worker trace")
        main |= first["threadId"] == 0
        for row in rows[1:]:
            if row["event"] != "source" or row["sha256"] != authority.files.get(row["source"]):
                raise ValueError("Loaded native source or offline provider differs from its authority")
            if "capture" in row and (row["source"] != str(PROVIDER)
                    or not row["capture"].startswith("tmp/plugin-captures/")):
                raise ValueError("Unbound native transport copy")
            seen.add(row["source"])
    required = {str(authority.root / owner) for owner in OWNERS} | {str(ACTOR), str(PROVIDER)}
    if not main or not required.issubset(seen):
        raise ValueError(f"Incomplete original host source evidence: {sorted(required - seen)}")


def _user_prompts(raw, expected):
    # This caller prefixes direct user utterances with its visible host clock.
    # The other user-role blocks are generated runtime context, retained verbatim.
    utterances = [m["content"] for m in raw["calls"][0]["messages"]
                  if m["role"] == "user" and isinstance(m["content"], str)]
    return [text.partition("] ")[2] for text in utterances] == expected


def _inventory(directory):
    paths = [directory / "state" / (phase + ".json") for phase in ("cut", "reopen")]
    for phase in ("cut", "reopen"):
        paths.extend((directory / "state" / (phase + "-trace")).glob("*.jsonl"))
    for phase in ("cut", "reopen", "final"):
        paths.extend((directory / phase).iterdir())
    return {str(path.relative_to(directory)): _hash(path) for path in sorted(paths)}


def review_case(case, directory, *, checkout, node, runtime):
    directory = Path(directory)
    if case not in build_cases() or directory.resolve(strict=True) != directory:
        raise ValueError("Unregistered native interrupted-turn input or aliased evidence")
    auth = _authority(checkout, node, runtime)
    capture = _json(directory / "capture.json")
    if capture["case"] != case or capture["authority"] != auth.identity or capture["files"] != _inventory(directory):
        raise ValueError("Interrupted-turn native raw evidence differs from its original capture")
    raw = {phase: _json(directory / "state" / (phase + ".json")) for phase in ("cut", "reopen")}
    request = case["input"]
    for phase, row in raw.items():
        process = capture["processes"][phase]
        if (row["pid"] != process["pid"] or row["ppid"] != process["ppid"] or row["phase"] != phase
                or row["input"] != request or row["node"] != auth.node["execPath"]
                or any(row["scope"][key] != request["identity"][key] for key in ("agentId", "sessionKey"))
                or row["providers"] != ["fixture-turn-barrier-model"] or "provider-stream-created" not in row["pluginEvents"]
                or process["exit"] != (-signal.SIGKILL if phase == "cut" else 0)):
            raise ValueError("Detached native interruption, provider or process receipt")
        for e in row["events"]:
            if e["stream"] != "tool" or any(e[key] != row["scope"][key] for key in ("agentId", "sessionKey")):
                raise ValueError("Outside-session execution event in native interrupted-turn capture")
        _sources(directory, phase, process, auth)
    cut, opened = raw["cut"], raw["reopen"]
    event = cut["events"][-1]["data"]
    if (cut["pid"] == opened["pid"] or cut["scope"] != opened["scope"] or len(cut["calls"]) != 1
            or event["name"] != "write" or event["toolCallId"] != request["original"]["callId"]
            or event["phase"] != ("start" if request["cut"] == "before-write" else "result")
            or cut["closeReceipts"] or cut["deliveries"]
            or opened["closeReceipts"] != ["memory", "mcp", "scheduler", "sessions"]
            or not opened["calls"]):
        raise ValueError("Native dispatch did not cross the designated cutoff and fresh public request")
    if _original([cut["calls"][0]["response"]], request["original"])[0] != [request["original"]["callId"]]:
        raise ValueError("Native interruption lost its original provider request")
    prompts = [request["original"]["prompt"]]
    if not _user_prompts(cut, prompts) or not _user_prompts(opened, prompts + [request["followup"]["prompt"]]):
        raise ValueError("Actual native inference conversation differs from the registered requests")
    calls = [e["data"]["toolCallId"] for e in opened["events"] if e["data"]["phase"] == "start"]
    # Check the original transport supplied the requested independent write, when present.
    for record in opened["calls"]:
        for block in record["response"]["content"]:
            if block["type"] == "toolCall" and request["followup"]["write"] and block["id"] == request["followup"]["write"]["callId"]:
                write = request["followup"]["write"]
                if block["name"] != "write" or block["arguments"] != {"path": write["relativePath"], "content": write["content"]}:
                    raise ValueError("Independent native writer changed identity or arguments")
    return {"cut": _boundary(directory, "cut", cut["after"], request),
            "reopen": _boundary(directory, "reopen", opened["before"], request),
            "firstModelOriginalResults": _original(opened["calls"][0]["messages"], request["original"])[1],
            "newTurnToolCalls": calls, "replies": [d["payload"]["text"] for d in opened["deliveries"]],
            "final": _boundary(directory, "final", opened["after"], request)}


def run_case(case, directory, *, checkout, node, runtime):
    if case not in build_cases():
        raise ValueError("Unregistered native interrupted-turn case")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if directory.resolve(strict=True) != directory or any(directory.iterdir()):
        raise ValueError("Expected an empty owned interruption directory")
    auth = _authority(checkout, node, runtime)
    root = directory / "state"
    root.mkdir()
    for name in ("tmp", "home", "cache", "xdg"):
        (root / name).mkdir()
    processes = {}
    with tempfile.TemporaryDirectory(prefix="interrupted-turn-control-") as temp:
        spec, allow = Path(temp) / "spec.json", Path(temp) / "authority.json"
        _save(spec, {"input": case["input"], "root": str(root), "runtimeRoot": str(auth.root)})
        _save(allow, {"files": auth.files, "node": auth.node})
        processes["cut"] = _run_phase(root, spec, "cut", allow, auth)
        _physical(directory, case, "cut")
        if case["input"]["externalEdit"] is not None:
            target = root / "workspace" / case["input"]["original"]["relativePath"]
            target.write_bytes(case["input"]["externalEdit"].encode("utf-8"))
        _physical(directory, case, "reopen")
        processes["reopen"] = _run_phase(root, spec, "reopen", allow, auth)
        _physical(directory, case, "final")
    _save(directory / "capture.json", {"case": case, "processes": processes,
                                     "authority": auth.identity, "files": _inventory(directory)})
    return review_case(case, directory, checkout=checkout, node=node, runtime=auth)
