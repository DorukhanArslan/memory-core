"""Frozen archive reconstruction case and the exact source-family registration."""
from __future__ import annotations

import base64
import hashlib
import json

from equivalence.transcript_boundary_fixtures import build_transcript_boundary_cases

POINT = "sessions.transcript-filtering.boundaries"
OPERATION = "transcript-boundary-runtime"
FAMILY_SHA256 = "b8571f5328b298784a359c1174eed4ed864a9d3e48c3bc1a9b94eba7c5139131"

# Two ordinary Zstandard frames carrying a torn first row, a blank line,
# messages and a reset row. Their compressed sizes are equal.
_FRAMES = (
    "KLUv/WAFAJUEAMJIHB1wNc4BlT2dyGyStG4va6uPccbYC6r4C71k/eOvCcV7B6Ig07VkKzzVd+2qxAlzsnJw9Gm4Q8RX12Lk46K+dwQGAiTZMfVFtm5kgsG0xsDGqYSTn/hsAEZW3ICmqZ+EjCjLyMioXWRORufcT1Gktj8BCwAYW47GHAf/KkYiYAiQqXFs2Pg4KkkFeLMcEsw8",
    "KLUv/WAFAJUEAMJIHB1wNc4BlT2dyGyStG4va6uPccYPYeyAzrxk/eOfCcV7B6Ig07VkKzzVd+2qxAlzsnJw9Gm4Q8RX12Lk46K+dwQGAiTZMfVFtm5kgsG0xsDGqYSTn/hsAEZW3ICmqZ+EjCjLyMioXWRORufcT1Gktj8BCwAYW47GHAf/KkYiYAiQqXFs2Pg4KkkFeLMcEsw8",
)


def covered_case():
    a, b = (list(base64.b64decode(frame, validate=True)) for frame in _FRAMES)
    now = 1794000000000
    return {
        "id": "transcript-boundary-compressed-malformed-reset-replacement",
        "operation": OPERATION,
        "requirement": "sessions.transcript-filtering",
        "covers": [POINT],
        "driverScope": "Real compressed reset archive, complete JSONL projection, callbacks, changed "
                       "and colliding source revisions, deletion. The existing family includes the "
                       "real SQLite worker, reset cutoff and malformed source reads.",
        "normalizationPolicy": "Only the exact owned fixture-root prefix maps to $FIXTURE.",
        "input": {"kind": "boundary", "source": "jsonl", "nowMs": now, "observer": True,
                  "fileName": "00000000-0000-4000-8000-000000000035.jsonl.reset.2026-11-09T00-00-00Z.zst",
                  "environmentFault": {"kind": "preferred-temp-root-unavailable"},
                  "initial": {"rawBytes": a, "mtimeMs": now},
                  "steps": [{"op": "read", "label": "original"},
                            {"op": "write", "rawBytes": b, "mtimeMs": now + 1000.125, "sameSize": True},
                            {"op": "read", "label": "new-generation"},
                            {"op": "write", "rawBytes": a, "mtimeMs": now + 1000.875, "sameSize": True},
                            {"op": "read", "label": "same-generation"},
                            {"op": "remove"},
                            {"op": "read", "label": "absent"}]},
    }


def build_cases():
    return [*build_transcript_boundary_cases(), covered_case()]


def _digest(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def validate_registration(cases):
    if any(POINT in row["covers"] for row in cases):
        selected = [row for row in cases if row["operation"] == OPERATION or POINT in row["covers"]]
        if _digest(selected) != FAMILY_SHA256:
            raise ValueError("Transcript filtering requires the frozen eight source cases and compressed reset archive")


def family_complete(rows):
    expected = build_cases()
    selected = [row for row in rows if row["operation"] == OPERATION or POINT in row["covers"]]
    fields = ("id", "requirement", "operation", "covers", "input")
    if len(selected) != len(expected) or _digest(expected) != FAMILY_SHA256:
        return False
    return all(row.get("status") == "matched" and row.get("runtimeEvidenceValidated") is True
               and all(row.get(key) == original[key] for key in fields)
               for row, original in zip(selected, expected, strict=True))


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def review_pair(case, native_public, sdk_public, native_raw, sdk_raw):
    """Bind the two public replies to the independent physical source reads."""
    from pathlib import Path
    import stat
    from equivalence.get_contract import map_get_fixture_paths
    from equivalence.search_contract import _same_json
    from equivalence.transcript_boundary_evidence import _input_bytes

    inputs = case["input"]
    original, = native_raw
    sdk, = sdk_raw
    base = Path(sdk["fixtureBase"])
    _require(base.is_absolute() and base.name.startswith("python-transcript-boundary-")
             and set(sdk) == {"fixtureBase", "kind", "source", "reads", "sourceCaptures", "mutations"}
             and sdk["kind"] == inputs["kind"] and sdk["source"] == inputs["source"], "SDK source identity changed")
    steps = inputs["steps"]
    mutations = ([{"op": "initial", "input": inputs["initial"]}] if "initial" in inputs else [])
    mutations.extend(step for step in steps if step["op"] != "read")
    _require(_same_json(sdk["mutations"], mutations), "SDK source writes differ from the literal mutations")
    for side, public in ((original, native_public), (sdk, sdk_public)):
        observed = {"provider": "none", "reads": [r["result"] for r in side["reads"]]}
        _require(_same_json(map_get_fixture_paths(observed, side["fixtureBase"]), public),
                 "Public transcript observations differ from original reads")
    agent = inputs.get("agentId", "main")
    session = inputs.get("sessionId", "boundary")
    filename = inputs.get("fileName", session + ".jsonl")
    physical = base / "state" / "agents" / agent / "sessions" / filename
    key = inputs.get("sessionKey", f"agent:{agent}:dm:boundary")
    reads = iter(zip(sdk["reads"], sdk["sourceCaptures"], original["sourceCaptures"], strict=True))
    last = inputs.get("initial")
    kind = "file" if last is not None else "remove"
    for step in steps:
        if step["op"] != "read":
            last = step
            kind = "file" if step["op"] in {"write", "replace-events"} else step["op"]
            continue
        actual, capture, reference = next(reads)
        req = actual["request"]
        sqlite = inputs["source"] == "sqlite"
        _require(req["onTranscriptMessage"] is (bool(inputs.get("observer")) or bool(step.get("observer")))
                 and req["options"] == {"sessionKind": "interactive", **inputs.get("options", {}),
                                        **step.get("options", {})}
                 and actual["result"].get("label") == step["label"]
                 and req["file"]["abs_path"] == (key if sqlite else str(physical))
                 and req["file"]["session_id"] == session, "SDK transcript request changed")
        if sqlite:
            _require(isinstance(capture["entry"], dict) and capture["entry"]["sessionId"] == session
                     and _same_json(capture["events"], reference["events"]),
                     "The two physical SQLite transcripts differ")
            continue
        _require(capture["filename"] == str(physical), "SDK read an unrelated physical path")
        if kind == "remove":
            _require(capture["error"]["name"] == "FileNotFoundError" and "stat" not in capture,
                     "Deleted SDK transcript is still present")
            continue
        info = capture["stat"]
        if kind == "file":
            data = _input_bytes(last)
            _require(stat.S_ISREG(int(info["mode"])) and int(info["size"]) == len(data)
                     and bytes(capture["bytes"]) == data and capture["bytes"] == reference["bytes"]
                     and abs(int(info["mtime_ns"]) / 1_000_000 - last.get("mtimeMs", inputs["nowMs"])) <= 0.002,
                     "SDK transcript bytes, size or modification time differ from the literal source")
        elif kind == "directory":
            _require(stat.S_ISDIR(int(info["mode"])), "SDK directory lost its filesystem identity")
        else:
            _require(kind == "symlink" and stat.S_ISLNK(int(info["mode"]))
                     and capture["target"] == str(base / "symlink-target.jsonl"), "SDK symlink target changed")
    _require(next(reads, None) is None, "SDK transcript contains extra reads")
    return {"source": inputs["source"], "physicalReads": len(sdk["reads"]),
            "mutations": len(mutations), "publicMatch": _same_json(native_public, sdk_public)}


def replay(case, row, native_diag, sdk_diag, trace, evidence_root):
    """Reopen retained bytes and re-run the native source/worker and SDK source checks."""
    from pathlib import Path
    import stat
    from equivalence.search_contract import _same_json
    from equivalence.transcript_boundary_evidence import validate_transcript_boundary_raw
    from equivalence.transcript_boundary_runtime_bindings import COMPILED_HASHES

    root = Path(evidence_root).resolve(strict=True)
    _require(all(obj["id"] == case["id"] for obj in (row, native_diag, sdk_diag, trace))
             and row["runtimeEvidenceValidated"] is True and row["status"] in {"matched", "mismatched"}
             and all(row.get(k) == case[k] for k in ("operation", "requirement", "covers", "input")),
             "Unexpected transcript case identity")
    snapshots, files = [], {}
    for record, side, path_field, size_field, filename in (
        (native_diag, "native", "retainedNativeRawPath", "nativeRawBytes", "native-raw.json"),
        (sdk_diag, "python", "retainedSdkRawPath", "sdkRawBytes", "python-raw.json"),
    ):
        path = Path(record[path_field])
        # Hosted artifacts may be downloaded at a different absolute root.
        relative = Path(path.parent.name) / path.name
        actual = root / relative
        _require(record["side"] == side and path.parent.parent.name == root.name
                 and relative.parent.name.startswith(("native" if side == "native" else "sdk") + "-attempt-")
                 and actual.name == filename and actual.resolve(strict=True) == actual,
                 "Unexpected transcript capture location")
        info = actual.lstat()
        _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= 16 * 1024 * 1024,
                 "Invalid transcript capture file")
        wire = actual.read_bytes()
        decoded = json.loads(wire)
        _require(len(wire) == record[size_field] and hashlib.sha256(wire).hexdigest() == record["sha256"]
                 and _same_json(decoded, record["rawSnapshots"]), "Physical transcript capture digest changed")
        snapshots.append(decoded)
        files[side] = str(relative)
    loaded, workers, threads, streams = {}, [], set(), {}
    for stream in trace["transcriptBoundaryTransport"]["rawProcessWorkerTraces"]:
        data = stream["text"].encode()
        _require(len(data) == stream["bytes"] and hashlib.sha256(data).hexdigest() == stream["sha256"]
                 and data.endswith(b"\n"), "Protected transcript process/worker trace changed")
        bootstrap, *events = map(json.loads, data.splitlines())
        pid, thread = bootstrap["pid"], bootstrap["threadId"]
        _require(bootstrap["event"] == "bootstrap" and bootstrap["fetchDenied"] is True
                 and bootstrap["providerMode"] == "none" and bootstrap["isMainThread"] is (thread == 0)
                 and stream["name"] == f"{pid}-{thread}.jsonl" and (pid, thread) not in threads,
                 "Original transcript worker identity changed")
        threads.add((pid, thread))
        streams[stream["name"]] = stream["sha256"]
        for event in events:
            _require(event["pid"] == pid and event["threadId"] == thread
                     and event["event"] in ("load", "resolve-native"), "Unexpected transcript worker event")
            if event["event"] == "load" and event["kind"] == "release" and event["package"] == "node_modules/openclaw":
                path = event["path"]
                if path in COMPILED_HASHES:
                    _require(COMPILED_HASHES[path] == event["sha256"], "Pinned transcript reader bytes changed")
                loaded.setdefault(pid, set()).add(path)
                if thread:
                    workers.append({"package": event["package"], "path": path, "threadId": thread, "pid": pid})
    _require(threads == {(t["pid"], t["threadId"]) for t in trace["threads"]}
             and sum(thread == 0 for _, thread in threads) == 1, "Missing original transcript process or worker")
    native, sdk = snapshots
    validate_transcript_boundary_raw({"ok": True, "result": row["openclaw"]}, case, native,
                                     Path(native[0]["fixtureBase"]).parent, release_by_pid=loaded,
                                     worker_imports=workers)
    review = review_pair(case, row["openclaw"], row["python"], native, sdk)
    _require(review["publicMatch"] == (row["status"] == "matched"), "Reported transcript result differs from the evidence")
    return {"id": case["id"], "validated": True, **review, "threads": len(threads),
            "nativeSha256": native_diag["sha256"], "sdkSha256": sdk_diag["sha256"],
            "rawFiles": files, "traceSha256": streams}
