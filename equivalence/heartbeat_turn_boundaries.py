"""Compare the actual flush and session-corpus boundaries for automatic heartbeat turns."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

REQUIREMENT = "heartbeat.turn-decisions"
DEFINITION_SHA256 = "97cffc893c159cafa96b156fc777712f8e250487612f443993386d1a7e02b73a"
POINT = REQUIREMENT + ".boundaries"
FLUSH = "heartbeat-turn-eligible-flush-control"
CORPUS = "heartbeat-turn-corpus-"
HEARTBEAT_PROMPT = ("Follow the heartbeat monitor scratch context when provided. Recurring tasks are automations; "
                    "create or change their schedules with the automations tool, not heartbeat scratch. "
                    "Do not infer or repeat old tasks from prior chats. If nothing needs attention, reply NO_REPLY.")
MOMENT = 1777824000000
ACCEPTANCE = "Observe the flush owner with identical eligible inputs and reopen the actual session-memory source."
POLICY = "Compare all returned business fields, physical bytes and message callbacks. Only the owned absolute file root and generated run identities use their existing role-based normalization."


def _wire(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()


def _message(role, content, **fields):
    return {"type": "message", "message": {"role": role, "content": content, **fields}}


def _corpus_case(label, messages):
    records = [{"type": "session", "id": "heartbeat-reading", "timestamp": "2026-05-03T00:00:00Z"}, *messages]
    jsonl = "".join(json.dumps(row, ensure_ascii=True, separators=(",", ":")) + "\n" for row in records)
    return {"id": CORPUS + label, "requirement": REQUIREMENT, "covers": [POINT],
            "operation": "session-projection", "normalizationPolicy": POLICY, "driverScope": ACCEPTANCE,
            "input": {"reopenHeartbeatCorpus": True, "mtimeMs": MOMENT, "jsonl": jsonl}}


def build_cases():
    from equivalence.flush_execution import TARGET, _reply, _step, _write

    write = _reply(_write("- Please retain this ordinary maintenance note.\n"))
    steps = [
        {**_step("automatic-poll", write), "isHeartbeat": True},
        {**_step("ordinary-conversation", write), "isHeartbeat": False},
        {**_step("automatic-poll-next-cycle", write, cycle=1), "isHeartbeat": True},
    ]
    flush = {"id": FLUSH, "requirement": REQUIREMENT, "covers": [POINT], "operation": "flush-execution-runtime",
             "normalizationPolicy": POLICY, "driverScope": ACCEPTANCE,
             "input": {"nowMs": MOMENT, "target": TARGET, "initialText": None,
                       "sessionKey": "agent:main:main", "entry": {"sessionId": "heartbeat-flush-control",
                       "updatedAt": MOMENT, "compactionCount": 0, "totalTokens": 176000,
                       "totalTokensFresh": True, "totalTokensVersion": 1},
                       "sourceMessages": [{"role": "user", "content": "Keep this maintenance note."}],
                       "steps": steps, "queries": []}}
    event = {"kind": "internal_system", "sourceTool": "heartbeat"}
    owner = [_message("user", "Keep ordinary before the poll."),
             _message("user", "[OpenClaw heartbeat poll]", provenance=event),
             _message("assistant", [{"type": "text", "text": "private poll context"}]),
             _message("assistant", "HEARTBEAT_OK"),
             _message("user", "Keep ordinary after the poll."),
             _message("assistant", "The alarm threshold was changed.")]
    tokens = [_message("user", HEARTBEAT_PROMPT),
              _message("assistant", "NO_REPLY"),
              _message("assistant", "HEARTBEAT_OK"),
              _message("user", "Keep ordinary user text mentioning HEARTBEAT_OK."),
              _message("assistant", "The previous command printed NO_REPLY as output.")]
    repeated = [_message("user", "First automatic wake.", provenance=event),
                _message("assistant", "ignore wake one"), _message("user", "Keep ordinary middle."),
                _message("user", "Second automatic wake.", provenance=event),
                _message("assistant", "ignore wake two"), _message("user", "Keep ordinary tail.")]
    return [flush, _corpus_case("source-turn", owner), _corpus_case("acknowledgements", tokens),
            _corpus_case("successive-wakes", repeated)]


def read_corpus(value):
    from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
    from memory_core.session_corpus import MemoryCoreSessionCorpus, SessionCorpusFile

    with TemporaryDirectory(prefix="heartbeat-corpus-") as temporary:
        root = Path(temporary)
        relative = Path("agents/main/sessions/heartbeat.jsonl")
        path = root / relative
        path.parent.mkdir(parents=True)
        path.write_bytes(value["jsonl"].encode())
        ns = value["mtimeMs"] * 1_000_000
        os.utime(path, ns=(ns, ns))
        file = SessionCorpusFile("sessions/main/heartbeat.jsonl", path, session_kind="unknown")
        reads = []
        for _ in range(2):
            observed = []
            corpus = MemoryCoreSessionCorpus(root, runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)
            item = corpus.read_source_entry(file, on_transcript_message=lambda message, at:
                                            observed.append({"message": deepcopy(message), "at": at}))
            if item is None or item.get("absPath") != str(path):
                raise ValueError("SDK session reader did not open its owned file")
            reads.append({"entry": {**item, "absPath": relative.as_posix()}, "observed": observed,
                          "sourceSha256": sha256(path.read_bytes()).hexdigest()})
        return {"reads": reads}


def _members(cases):
    return [row for row in cases if row.get("id") == FLUSH or str(row.get("id", "")).startswith(CORPUS)
            or POINT in row.get("covers", ())]


def validate_registration(cases):
    rows = _members(cases)
    if rows and sha256(_wire(rows)).hexdigest() != DEFINITION_SHA256:
        raise ValueError("Heartbeat exclusion requires the complete original four-case definition")


def _require(value, message):
    if not value:
        raise ValueError(message)


def validate_corpus(case, result, sources):
    owners = {item["path"] for item in sources}
    _require("packages/memory-host-sdk/src/host/session-files.ts" in owners,
             "Missing the original corpus reader")
    reads = result["reads"]
    _require(len(reads) == 2 and reads[0] == reads[1], "The stored transcript changed between opens")
    sample = reads[0]
    records = [json.loads(text) for text in case["input"]["jsonl"].splitlines()]
    _require(sample["sourceSha256"] == sha256(case["input"]["jsonl"].encode()).hexdigest(),
             "Corpus source bytes changed")
    _require([event["message"] for event in sample["observed"]] == [row["message"] for row in records[1:]],
             "Corpus callback omitted or reordered an input message")
    ordinals = {"source-turn": [2, 6, 7], "acknowledgements": [5, 6], "successive-wakes": [4, 7]}
    kept = ordinals[case["id"].removeprefix(CORPUS)]
    rows = [records[line - 1]["message"] for line in kept]
    entry = sample["entry"]
    _require(entry["content"].splitlines() == [msg["role"].capitalize() + ": " + msg["content"] for msg in rows]
             and entry["lineMap"] == kept, "Heartbeat source mapping did not preserve the ordinary messages")
    _require(entry["size"] == len(case["input"]["jsonl"].encode()) and entry["mtimeMs"] == MOMENT
             and entry["path"] == "sessions/main/heartbeat.jsonl", "Corpus file identity differs")


def validate_flush(case, result, raw_native, raw_sdk):
    snapshots = result["snapshots"]
    expected_labels = [step["label"] for step in case["input"]["steps"]]
    _require([s["label"] for s in snapshots] == expected_labels
             and [s["outcome"] for s in snapshots] == ["skipped", "completed", "skipped"],
             "Eligible normal and heartbeat flush decisions did not follow the input order")
    first, middle, last = snapshots
    _require(first["bytesBase64"] is None and middle["bytesBase64"] and middle["bytesBase64"] == last["bytesBase64"]
             and not first["provenance"] and middle["provenance"] == last["provenance"] and len(middle["provenance"]) == 1,
             "Automatic polls must leave the actual maintenance file and provenance untouched")
    _require([s["modelCalls"] for s in snapshots] == [0, 2, 0]
             and [len(s["toolResults"]) for s in snapshots] == [0, 1, 0] and all(s["sourceUnchanged"] for s in snapshots),
             "Model/tool activity or the original conversation was not preserved")
    _require(len(raw_native) == len(raw_sdk) == len(snapshots), "Missing raw native or SDK flush drives")
    for n, s, obs in zip(raw_native, raw_sdk, snapshots, strict=True):
        _require(n.get("invokedOwner") == "runMemoryFlushIfNeeded" and len(n["modelCalls"]) == obs["modelCalls"]
                 and len(n["toolEvents"]) == len(s["receipts"]) == len(obs["toolResults"])
                 and n["bytesBase64"] == s["bytesBase64"] == obs["bytesBase64"]
                 and n["persistedEntry"]["sessionId"] == case["input"]["entry"]["sessionId"]
                 and (s["request"] is not None) == (obs["outcome"] == "completed")
                 and isinstance(n["sourceTranscript"], list) and n["sourceTranscript"],
                 "The genuine model, tool, source session or retained store evidence is incomplete")


def family_complete(rows):
    members = _members(rows)
    definitions = build_cases()
    return (len(members) == len(definitions) and
            all(all(row.get(key) == value for key, value in definition.items()) and row.get("status") == "matched"
                and row.get("heartbeatExclusionEvidenceValidated") is True
                for row, definition in zip(members, definitions, strict=True)))
