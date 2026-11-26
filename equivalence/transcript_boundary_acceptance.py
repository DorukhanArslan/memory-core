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
