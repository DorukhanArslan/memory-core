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
