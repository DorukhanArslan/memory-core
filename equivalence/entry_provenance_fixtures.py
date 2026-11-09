"""Literal bounded inputs for the original entry identity/provenance contract.

No expected outputs or acceptance registration live here. The byte-limit inputs
also reproduce the pinned primitive without paid embedding calls.
"""
from copy import deepcopy
import random


def embedding_byte_limit_inputs():
    texts = [[], [97] * 33, [0x6F22, 0x5B57] * 4, [0xD83D, 0xDE00, 97] * 4,
             [97, 0xD800, 98, 0xDC00, 99], [0xD800, 0xDC00, 0xD800, 0xDC00],
             [0xDC00, 0xD800, 0, 10, 13, 0xFEFF]]
    generator = random.Random(271828)
    alphabet = [0, 10, 32, 65, 97, 0x00E9, 0x6F22, 0xD800, 0xDC00, 0xD83D, 0xDE00]
    texts.extend([[generator.choice(alphabet) for _ in range(size)] for size in (1, 2, 7, 16, 63)])
    return [{"id": f"text-{index}-cap-{cap}", "units": units, "limit": cap}
            for index, units in enumerate(texts) for cap in (-1, 0, 1, 2, 3, 4, 5, 16, 31.5)]


def build_entry_provenance_cases():
    """Pending genuine runtime profiles; neither condition is credited here."""
    scenarios = [
        ("canonical-collision-invalidation", {"kind": "published-memory", "mtimeMs": 1700000000000,
            "files": {"MEMORY.md": "a" * 5000}, "steps": [
                {"label": "initial", "nowMs": 1800000000000},
                {"label": "unchanged", "nowMs": 1800000001000},
                {"label": "same-bytes", "nowMs": 1800000002000, "write": {"MEMORY.md": "a" * 5000}},
                {"label": "changed-same-size-time", "nowMs": 1800000003000,
                 "write": {"MEMORY.md": "a" * 4999 + "b"}},
            ]}),
        ("provider-entry-fragments", {"kind": "prepared-provider", "nowMs": 1800000000000, "mtimeMs": 1700000000000,
            "path": "MEMORY.md", "content": "- " + "abcdefghijklmnop" * 6 + " <!-- importance: 7 -->",
            "provider": {"id": "fixture", "model": "fixture-limit", "maxInputTokens": 16}, "embeddingVector": [1, 0], "hardMaxInputTokens": 8000,
            "chunking": {"tokens": 400, "overlap": 80}}),
    ]
    key = "agent:main:direct:entry-provenance"
    events = [
        {"type": "session", "version": 4, "id": "entry-provenance", "timestamp": "2026-11-09T00:00:00.000Z", "cwd": "/fixture/workspace"},
        {"type": "message", "id": "owner", "message": {"role": "user", "content": "Earlier owner context. " * 40,
            "timestamp": 1794182400000, "__openclaw": {"senderIsOwner": True}}},
        {"type": "message", "id": "assistant", "message": {"role": "assistant", "content": "Assistant continuation. " * 40,
            "timestamp": 1794182401000}},
        {"type": "message", "id": "tainted", "message": {"role": "user", "content": "Retained untrusted context. " * 40,
            "timestamp": 1794182402000, "__openclaw": {"senderIsOwner": False, "turnTainted": True}}},
        {"type": "message", "id": "after", "message": {"role": "assistant", "content": "Later answer. " * 40,
            "timestamp": 1794182403000, "__openclaw": {"turnTainted": True}}},
    ]
    scenarios.append(("session-provenance-replacement-reset", {"kind": "session-projection", "sessionKey": key,
        "sessionId": "entry-provenance", "sessions": [{"sessionKey": key,
            "entry": {"sessionId": "entry-provenance", "chatType": "direct", "updatedAt": 1800000000000},
            "events": events}], "steps": [
                {"label": "initial", "nowMs": 1800000000000, "force": True},
                {"label": "revision-only", "nowMs": 1800000000500, "force": False, "events": deepcopy(events),
                 "syncSessions": [{"agentId": "main", "sessionId": "entry-provenance", "sessionKey": key}]},
                {"label": "replace-provenance", "nowMs": 1800000001000, "force": False,
                 "syncSessions": [{"agentId": "main", "sessionId": "entry-provenance", "sessionKey": key}], "events": [
                    *deepcopy(events[:1]),
                    {**deepcopy(events[1]), "message": {**deepcopy(events[1]["message"]), "__openclaw": {"senderIsOwner": False}}},
                    *deepcopy(events[2:])]},
                {"label": "valid-reset", "nowMs": 1800000002000, "force": False,
                 "syncSessions": [{"agentId": "main", "sessionId": "entry-provenance", "sessionKey": key}],
                 "events": [*deepcopy(events), {"type": "reset", "id": "reset", "firstKeptEntryId": "tainted"}]},
                {"label": "invalid-reset", "nowMs": 1800000003000, "force": False,
                 "syncSessions": [{"agentId": "main", "sessionId": "entry-provenance", "sessionKey": key}],
                 "events": [*deepcopy(events), {"type": "reset", "id": "bad-reset", "firstKeptEntryId": "missing"}]},
        ]}))
    return [{"id": "entry-provenance-" + name, "requirement": "chunking.entry-provenance", "covers": [],
             "operation": "entry-provenance-runtime", "input": deepcopy(value)} for name, value in scenarios]
