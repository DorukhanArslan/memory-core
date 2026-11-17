"""Locked inputs to the original diary publication and provenance requirements."""
from copy import deepcopy
import hashlib

from equivalence.dream_light import NOW, canonical

OPERATION = "dream-diary-publication-runtime"
REQUIREMENT = "dreaming.diary-provenance"
POINTS = (REQUIREMENT + ".outcomes", REQUIREMENT + ".boundaries")
START, END = "<!-- openclaw:dreaming:diary:start -->", "<!-- openclaw:dreaming:diary:end -->"
NOTE = "memory/2026-01-01.md"
SOURCE = {"key": "leaf", "path": NOTE, "startLine": 2, "endLine": 2, "source": "memory",
          "snippet": "One green leaf survived.", "recallCount": 1, "dailyCount": 0, "groundedCount": 0,
          "totalScore": 0.75, "maxScore": 0.75, "queryHashes": ["leaf"], "conceptTags": ["leaf"],
          "recallDays": ["2026-01-01"], "firstRecalledAt": "2026-01-01T09:00:00.000Z",
          "lastRecalledAt": "2026-01-01T09:00:00.000Z"}
PRIOR = "Copper leaves turned amber."
OLD = f"# Dream Diary\n\n{START}\n---\n\n*Earlier*\n\n{PRIOR}\n\n{END}\n"
LEAF = "I saw the leaf again. [memory/2026-01-01.md:2-2]"


def _case(label, files, steps):
    return {"id": "dream-diary-" + label, "operation": OPERATION, "requirement": REQUIREMENT,
            "covers": list(POINTS), "input": {"files": {NOTE: "# Field\nOne green leaf survived.\n", **files},
                                             "source": deepcopy(SOURCE), "operations": steps}}


def _append(text=LEAF, keys=("leaf",), recent=(), *, delta=0, zone="UTC"):
    return {"op": "append", "narrative": text, "keys": list(keys), "recent": list(recent),
            "nowMs": NOW + delta, "timezone": zone}


def definitions():
    return [
        _case("phase-and-trust", {"DREAMS.md": OLD}, [
            {"op": "phase", "phase": "light", "nowMs": NOW, "timezone": "UTC",
             "lines": ["- Candidate: One green leaf survived.", "  - evidence: memory/2026-01-01.md:2-2"],
             "storageMode": "both"},
            _append(recent=(PRIOR,), zone="America/New_York"),
        ]),
        _case("lowercase-and-truncation", {"dreams.md": "Outside diary.\n" + START + "\nKeep this.\n"}, [
            _append("An earlier, delicate wing.", zone="Asia/Tokyo"),
            _append("Many lines\n" + "a" * 348 + "🪴" * 9, delta=86_400_000, zone="America/Los_Angeles"),
        ]),
        _case("vanished-source", {"DREAMS.md": OLD}, [
            {"op": "forget-source", "key": "leaf", "nowMs": NOW},
            _append(recent=(PRIOR,)),
        ]),
        _case("missing-quoted-context", {"DREAMS.md": OLD}, [
            {"op": "change-diary", "text": OLD.replace(PRIOR, "The entry was corrected.")},
            _append(recent=(PRIOR,)),
        ]),
        _case("older-quoted-entry", {"DREAMS.md": OLD.replace(END, "\n".join(
            f"---\n\n*Afterwards*\n\nDay {day}." for day in range(5)) + "\n" + END)}, [
            _append(recent=(PRIOR,)),
        ]),
        _case("publisher-failure", {"DREAMS.md": OLD, "owner-copy.md": "External witness.\n"}, [
            {"op": "make-symlink", "path": "DREAMS.md", "target": "owner-copy.md"},
            _append(), {"op": "restore-file", "path": "DREAMS.md", "text": OLD},
            _append("Publication after retry.", delta=1_000),
        ]),
        _case("competing-diary-writers", {"DREAMS.md": OLD}, [
            {"op": "race", "first": "First writer preserved this line.", "second": _append(
                "Second writer observed it.", recent=(PRIOR,), delta=1_000), "nowMs": NOW},
        ]),
    ]


DEFINITION_SHA256 = "08cf043ecf14c2bb6e6409f035b2a15c392f3aba1700de060016501a857ce8bc"


def build_cases():
    values = definitions()
    if hashlib.sha256(canonical(values)).hexdigest() != DEFINITION_SHA256:
        raise ValueError("Diary publication definitions changed")
    return values


def validate_registration(rows):
    family = [row for row in rows if row.get("operation") == OPERATION or row.get("requirement") == REQUIREMENT
              or set(row.get("covers", ())).intersection(POINTS)]
    if family and family != build_cases():
        raise ValueError("Diary publication requires every frozen operation and both original conditions")
