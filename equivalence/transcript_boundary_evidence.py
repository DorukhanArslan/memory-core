"""Bind public transcript reads to complete original source observations."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import re
import stat
from typing import Any

from equivalence.get_contract import map_get_fixture_paths
from equivalence.search_contract import _same_json
from equivalence.transcript_boundary_runtime_bindings import (
    ARCHIVE_ARTIFACTS, REQUIRED_BOUNDARY_ARTIFACTS, SQLITE_BOUNDARY_ARTIFACTS,
    TRANSCRIPT_WORKER_ARTIFACTS, TRANSCRIPT_WORKER_PARENT_ARTIFACTS,
)


def _finite(value: Any) -> bool:
    return type(value) in {int, float} and math.isfinite(value)


def _bytes(value: Any) -> bytes:
    if not isinstance(value, list) or any(type(item) is not int or not 0 <= item <= 255 for item in value):
        raise ValueError("Transcript evidence lost an original byte array")
    return bytes(value)


def _input_bytes(value: dict) -> bytes:
    if "rawBytes" in value:
        return _bytes(value["rawBytes"])
    from memory_core.bootstrap._js import js_json_stringify, js_utf8_encode

    events = value.get("events") or []
    if not isinstance(events, list):
        raise ValueError("Literal transcript events must remain an ordered list")
    return js_utf8_encode("\n".join(js_json_stringify(event) for event in events) + ("\n" if events else ""))


def validate_transcript_boundary_raw(
    row: dict, case: dict, diagnostic: list, evidence_directory: Path, *,
    release_by_pid: dict[int, set[str]], worker_imports: list[dict],
) -> None:
    """Validate transport and authority; never recompute transcript filtering."""
    from equivalence.runtime_oracle import RuntimeOracleError

    def require(condition: bool, message: str) -> None:
        if not condition:
            raise RuntimeOracleError(message)

    if row.get("ok") is not True:
        return
    try:
        require(isinstance(diagnostic, list) and len(diagnostic) == 1 and isinstance(diagnostic[0], dict),
                "Transcript boundaries require one complete original source observation")
        raw, arguments, public = diagnostic[0], case["input"], row["result"]
        require(arguments.get("kind") == "boundary" and arguments.get("source") in {"jsonl", "sqlite"},
                "The transcript boundary source profile changed")
        require(_finite(arguments.get("nowMs")), "Transcript source clocks require a finite literal input")
        source, now = arguments["source"], arguments["nowMs"]
        base = raw.get("fixtureBase")
        require(isinstance(base, str) and Path(base).is_absolute()
                and Path(base).parent == evidence_directory
                and re.fullmatch(r"native-transcript-boundary-[A-Za-z0-9_-]+", Path(base).name) is not None,
                "Transcript source evidence escaped its owned fixture directory")
        require(set(raw) == {"fixtureBase", "kind", "source", "constructorSkipped", "managerFixture",
                             "indexManagerConstructed", "clock", "mutations", "writeCalls", "reads", "sourceCaptures",
                             "cacheCaptures", "observerCalls", "environmentFault"},
                "Transcript source evidence omitted or invented an observation channel")
        require(raw.get("kind") == "boundary" and raw.get("source") == source
                and raw.get("constructorSkipped") is True and raw.get("managerFixture") is False
                and raw.get("indexManagerConstructed") is False,
                "A source read cannot claim substituted or constructed index-manager execution")
        require(_same_json(raw.get("clock"), {"owner": "node:test", "apis": ["Date"], "nowMs": now,
                "dateConstructorReplaced": True, "setTimeoutUnchanged": True, "performanceNowUnchanged": True}),
                "Transcript clocks replaced an unapproved scheduling or performance owner")
        require(isinstance(public, dict) and set(public) == {"provider", "reads"} and public["provider"] == "none",
                "Transcript public results require the complete declared source-read wire")
        require(isinstance(release_by_pid, dict) and len(release_by_pid) == 1,
                "A boundary read requires its single authenticated original native process")
        pid, loaded = next(iter(release_by_pid.items()))
        require(set(REQUIRED_BOUNDARY_ARTIFACTS) <= loaded,
                "The actual complete native transcript source owners did not execute")
        agent = arguments.get("agentId", "main")
        session = arguments.get("sessionId", "boundary")
        key = arguments.get("sessionKey", f"agent:{agent}:dm:boundary")
        filename = arguments.get("fileName", f"{session}.jsonl")
        require(isinstance(agent, str) and not re.search(r"[\\/]", agent)
                and agent not in {"", ".", ".."} and isinstance(filename, str)
                and filename not in {"", ".", ".."} and Path(filename).name == filename,
                "Transcript source identity is not an owned literal name")
        physical = Path(base) / "state" / "agents" / agent / "sessions" / filename
        scope = {"agentId": agent, "sessionId": session, "sessionKey": key,
                 "storePath": str(Path(base) / "state" / "agents" / agent / "sessions" / "sessions.json")}
        steps = arguments.get("steps", [{"op": "read", "label": "initial"}])
        require(isinstance(steps, list) and all(isinstance(step, dict) for step in steps),
                "Source reads require ordered literal mutation/read steps")
        read_steps = [step for step in steps if step.get("op") == "read"]
        require(bool(read_steps), "A transcript boundary fixture did not execute a source read")
        for name in ("reads", "sourceCaptures", "cacheCaptures", "observerCalls", "mutations", "writeCalls"):
            require(isinstance(raw[name], list), "A source observation channel is not a complete ordered array")
        require(all(isinstance(read, dict) and set(read) == {"request", "result"}
                    and isinstance(read["request"], dict) and isinstance(read["result"], dict) for read in raw["reads"]),
                "A native source read lost its complete request/reply pair")
        require(len(raw["reads"]) == len(read_steps) == len(raw["sourceCaptures"]),
                "Source reads or physical source captures were dropped or duplicated")
        require(_same_json(map_get_fixture_paths({"provider": "none", "reads": [read["result"] for read in raw["reads"]]}, base), public),
                "Public source results differ from complete original source replies")
        mutations = []
        if "initial" in arguments and arguments["initial"] is not None:
            mutations.append({"op": "initial", "input": arguments["initial"]})
        for step in steps:
            if step.get("op") != "read":
                mutations.append({"op": step.get("op"), **({"label": step["label"]} if "label" in step else {}), "input": step})
        require(_same_json(raw["mutations"], mutations), "Actual transcript mutations differ from the shared literal inputs")
        write_inputs = [mutation["input"] for mutation in mutations
                        if mutation["op"] in {"initial", "write", "replace-events"}] if source == "sqlite" else []
        require(len(raw["writeCalls"]) == len(write_inputs),
                "Actual SQLite writer requests or post-write source captures were dropped or duplicated")
        for call, value in zip(raw["writeCalls"], write_inputs, strict=True):
            require(isinstance(call, dict) and set(call) == {"request", "capture"}
                    and _same_json(call["request"], {"scope": scope, "events": value.get("events") or []}),
                    "The original SQLite writer did not receive the shared complete literal request")
            captured = call["capture"]
            require(isinstance(captured, dict) and set(captured) == {"scope", "entry", "events"}
                    and _same_json(captured["scope"], scope) and isinstance(captured["entry"], dict)
                    and isinstance(captured["events"], list),
                    "The actual completed SQLite writer lost its complete persisted source capture")
        compressed = source == "jsonl" and filename.endswith(".zst")
        require(len(raw["cacheCaptures"]) == (len(read_steps) if compressed else 0),
                "Archive cache observations were dropped or attached to another source profile")
        fault = raw["environmentFault"]
        require(isinstance(fault, dict) and set(fault) == {"input", "calls", "restored"}
                and _same_json(fault["input"], arguments.get("environmentFault"))
                and isinstance(fault["calls"], list) and isinstance(fault["restored"], list),
                "The declared source temporary-root condition lost its real admission/restoration evidence")
        require(_same_json(fault["restored"], [True] * (len(read_steps) if compressed else 0)),
                "The original filesystem admission owner was not restored after each source read")
        if compressed:
            require(arguments.get("environmentFault", {}).get("kind") == "preferred-temp-root-unavailable",
                    "Compressed reads did not declare the owned temporary-root fallback condition")
            require(set(ARCHIVE_ARTIFACTS) <= loaded, "Actual archive materialization and Zstd owners did not execute")
        else:
            require(not fault["calls"], "A plain/SQLite source invented archive filesystem faults")
        for call in fault["calls"]:
            require(isinstance(call, dict) and set(call) == {"readIndex", "operation", "path", "code"}
                    and type(call["readIndex"]) is int and 0 <= call["readIndex"] < len(read_steps)
                    and call["operation"] == "lstatSync" and call["path"].rstrip("/") == "/tmp/openclaw"
                    and call["code"] == "EACCES", "The temporary-root fault reached an undeclared filesystem operation")
        for call in raw["observerCalls"]:
            require(isinstance(call, dict) and set(call) == {"readIndex", "message", "timestampMs"}
                    and type(call["readIndex"]) is int and 0 <= call["readIndex"] < len(read_steps)
                    and isinstance(call["message"], dict) and _finite(call["timestampMs"]) and call["timestampMs"] >= 0,
                    "An actual transcript observer call lost its original message/time/read identity")
        state_kind, state_bytes, state_events = "missing", None, []
        state_mtime = now
        if "initial" in arguments and arguments["initial"] is not None:
            state_kind, state_bytes = "file", _input_bytes(arguments["initial"])
            state_events = arguments["initial"].get("events") or []
            state_mtime = arguments["initial"].get("mtimeMs", now)
        read_index = 0
        write_index = 0
        stored_source = None
        if source == "sqlite" and "initial" in arguments and arguments["initial"] is not None:
            stored_source = raw["writeCalls"][write_index]["capture"]
            write_index += 1
        worker_needed = False
        for step in steps:
            operation = step.get("op")
            if operation != "read":
                require(operation in {"write", "replace-events", "remove", "directory", "symlink"},
                        "An unsupported source mutation entered the accepted transcript transport")
                if operation in {"write", "replace-events", "symlink"}:
                    encoded = _input_bytes(step)
                    if step.get("sameSize"):
                        require(state_bytes is not None and len(encoded) == len(state_bytes),
                                "The actual literal cache-collision mutation did not retain its source byte length")
                    state_kind, state_bytes = ("symlink" if operation == "symlink" else "file"), encoded
                    state_events = step.get("events") or []
                    state_mtime = step.get("mtimeMs", now)
                    if source == "sqlite":
                        stored_source = raw["writeCalls"][write_index]["capture"]
                        write_index += 1
                else:
                    state_kind, state_bytes = ("missing" if operation == "remove" else "directory"), None
                continue
            observed = raw["reads"][read_index]
            result = observed.get("result")
            require(isinstance(observed, dict) and set(observed) == {"request", "result"}
                    and isinstance(result, dict), "A native source read lost its complete request/reply pair")
            options = {"sessionKind": "interactive", **(arguments.get("options") or {}), **(step.get("options") or {})}
            if source == "sqlite":
                options.update(scope)
                options["updatedAtMs"] = arguments.get("updatedAtMs") if arguments.get("updatedAtMs") is not None else now
            observing = arguments.get("observer") is True or step.get("observer") is True
            if observing:
                options["onTranscriptMessage"] = True
            require(_same_json(observed["request"], {"absPath": key if source == "sqlite" else str(physical), "options": options}),
                    "The actual public source reader received different options, observer or identity")
            expected_calls = [{"message": call["message"], "timestampMs": call["timestampMs"]}
                              for call in raw["observerCalls"] if call["readIndex"] == read_index]
            require(_same_json(result.get("observedMessages"), expected_calls)
                    and (observing or not expected_calls), "A source reply lost or invented real observer callbacks")
            require(("label" in result) == ("label" in step) and ("label" not in step or result["label"] == step["label"]),
                    "A native source read changed its requested ordered step identity")
            if "error" in result:
                require(source == "sqlite" and "entry" not in result and "resetRecallCutoff" not in result
                        and set(result) == {"error", "observedMessages", *(["label"] if "label" in step else [])}
                        and isinstance(result["error"], dict) and isinstance(result["error"].get("name"), str)
                        and isinstance(result["error"].get("message"), str),
                        "File read errors must stay nullable; actual SQLite errors must retain their complete metadata")
            else:
                entry = result.get("entry")
                require(set(result) == {"entry", "observedMessages",
                        *(["label"] if "label" in step else []),
                        *(["resetRecallCutoff"] if entry is not None else [])}
                        and (entry is None or isinstance(entry, dict)),
                        "A source reader lost or invented complete nullable success fields")
                require(("resetRecallCutoff" in result) is (entry is not None), "Source reset metadata was omitted or invented")
                if entry is not None:
                    fields = {"path", "absPath", "mtimeMs", "size", "hash", "content", "lineMap", "messageTimestampsMs", "lineProvenance", "sessionKind"}
                    require(fields <= entry.keys() and isinstance(entry["content"], str)
                            and re.fullmatch(r"[0-9a-f]{64}", entry["hash"]) is not None
                            and _finite(entry["mtimeMs"]) and _finite(entry["size"]),
                            "A complete native source entry lost content, identity, hash, clock or byte metadata")
                    lines = entry["content"].split("\n") if entry["content"] else []
                    require(all(isinstance(entry[name], list) and len(entry[name]) == len(lines)
                                for name in ("lineMap", "messageTimestampsMs", "lineProvenance")),
                            "Source ranges, timestamps or provenance no longer align with the complete exported content")
                    require(entry["absPath"] == observed["request"]["absPath"], "A source entry changed its actual read identity")
            capture = raw["sourceCaptures"][read_index]
            require(isinstance(capture, dict), "An actual stored source capture is missing")
            if source == "sqlite":
                require(set(capture) in ({"scope", "entry", "events"}, {"scope", "error"})
                        and _same_json(capture.get("scope"), scope), "A SQLite capture read another catalog owner or transcript")
                if stored_source is not None:
                    require(_same_json(capture, stored_source),
                            "A SQLite read source differs from the complete actual post-write persisted capture")
                elif "events" in capture:
                    require(_same_json(capture["events"], state_events),
                            "An unwritten SQLite source invented persisted transcript events")
                else:
                    require(isinstance(capture.get("error"), dict), "An unavailable SQLite source lost its actual operational failure")
                worker_needed |= not observing and "parseYieldEveryLines" not in options
            else:
                require(capture.get("filename") == str(physical), "A file capture read a different original source path")
                if state_kind == "missing":
                    require(set(capture) == {"filename", "error"} and isinstance(capture.get("error"), dict),
                            "A deleted source was replaced with fabricated surviving bytes")
                    require(result.get("entry") is None, "A missing physical source invented a successful source entry")
                else:
                    physical_stat = capture.get("stat")
                    require(isinstance(physical_stat, dict) and set(physical_stat) == {"dev", "ino", "mode", "size", "mtimeNs", "ctimeNs"}
                            and all(isinstance(value, str) and re.fullmatch(r"-?[0-9]+", value) for value in physical_stat.values()),
                            "A physical source capture lost its actual filesystem identity")
                    mode = int(physical_stat["mode"])
                    if state_kind == "file":
                        require(set(capture) == {"filename", "stat", "bytes"}
                                and stat.S_ISREG(mode) and _bytes(capture.get("bytes")) == state_bytes
                                and int(physical_stat["size"]) == len(state_bytes),
                                "Actual source bytes differ from the literal file mutation")
                        require(_finite(state_mtime) and abs(int(physical_stat["mtimeNs"]) / 1_000_000 - state_mtime) <= 0.001,
                                "A literal source write changed its requested physical modification time")
                        if result.get("entry") is not None:
                            require(result["entry"]["size"] == len(state_bytes), "A source entry lost its original physical byte size")
                    elif state_kind == "directory":
                        require(set(capture) == {"filename", "stat"} and stat.S_ISDIR(mode), "A directory source was replaced with a forged regular file")
                        require(result.get("entry") is None, "A directory source invented a successful regular-file entry")
                    else:
                        require(set(capture) == {"filename", "stat", "target", "targetBytes"}
                                and stat.S_ISLNK(mode) and capture.get("target") == str(Path(base) / "symlink-target.jsonl")
                                and _bytes(capture.get("targetBytes")) == state_bytes,
                                "An owned symlink changed its original target or target bytes")
            if compressed:
                cached = raw["cacheCaptures"][read_index]
                cache_root = Path(base) / "tmp"
                require(isinstance(cached, dict) and set(cached) == {"root", "files", *(["label"] if "label" in step else [])}
                        and cached.get("root") == str(cache_root) and cached.get("label") == step.get("label")
                        and isinstance(cached.get("files"), list), "A materialized archive lost its owned cache observation")
                cache_key = hashlib.sha256(str(physical).encode()).hexdigest()[:32]
                seen = set()
                for item in cached["files"]:
                    require(isinstance(item, dict) and set(item) == {"path", "size", "sha256", "bytes"}
                            and isinstance(item["path"], str) and item["path"] not in seen,
                            "Archive materialization cache entries were dropped or duplicated")
                    cached_path = Path(item["path"])
                    relative = cached_path.relative_to(cache_root)
                    require(cached_path.is_absolute() and ".." not in relative.parts and len(relative.parts) == 3
                            and re.fullmatch(r"openclaw(?:-[0-9]+)?", relative.parts[0]) is not None
                            and relative.parts[1] == "session-archive-read-cache"
                            and re.fullmatch(re.escape(cache_key) + r"-[0-9]+-[0-9]+\.jsonl", relative.name) is not None,
                            "Archive materialization escaped the actual owned secure-temp fallback or source cache key")
                    content = _bytes(item["bytes"])
                    require(type(item["size"]) is int and item["size"] == len(content)
                            and item["sha256"] == hashlib.sha256(content).hexdigest(),
                            "Original materialization cache bytes, length or hash were changed")
                    seen.add(item["path"])
                if result.get("entry") is not None:
                    require(state_kind == "file" and any(
                        Path(item["path"]).name == f"{cache_key}-{len(state_bytes)}-{int(capture['stat']['mtimeNs']) // 1_000_000}.jsonl"
                        for item in cached["files"]),
                        "A successful compressed read lost its actual source-identity materialization cache")
            read_index += 1
        if source == "sqlite":
            require(set(SQLITE_BOUNDARY_ARTIFACTS) <= loaded,
                    "The actual public SQLite transcript writer/read accessor owners did not execute")
        if worker_needed:
            require(set(TRANSCRIPT_WORKER_PARENT_ARTIFACTS) <= loaded,
                    "A default SQLite source read bypassed its actual public transcript worker launch owner")
            by_thread: dict[tuple[int, int], set[str]] = {}
            for item in worker_imports:
                if item.get("package") == "node_modules/openclaw" and item.get("pid") == pid and item.get("threadId", 0) > 0:
                    by_thread.setdefault((item["pid"], item["threadId"]), set()).add(item["path"])
            actual_reader = set(TRANSCRIPT_WORKER_ARTIFACTS) | {
                "dist/session-files-DVVT4Ngb.mjs", "dist/session-accessor.sqlite-read-BsSfe2AE.mjs",
            }
            require(any(actual_reader <= paths for paths in by_thread.values()),
                    "Incidental workers cannot stand in for the genuine protected transcript reader/projection worker")
    except RuntimeOracleError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError) as error:
        raise RuntimeOracleError("The original transcript boundary evidence has an invalid complete source shape") from error
