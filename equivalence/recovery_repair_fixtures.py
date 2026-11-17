"""Literal workspace failures for audit, surgical repair, and repeated repair."""
from copy import deepcopy
from hashlib import sha256

from equivalence.dream_light import canonical

OPERATION = "recovery-artifact-repair-runtime"
REQUIREMENT = "recovery.repair-diagnostics"
POINTS = (REQUIREMENT + ".outcomes", REQUIREMENT + ".boundaries")
NOW = 1767268800000
ISO = "2026-01-01T09:00:00.000Z"
NOTE = "memory/2026-01-01.md"
CORPUS = "memory/.dreams/session-corpus"
INGEST = "memory/.dreams/session-ingestion.json"
POLICY = ("Compare full audit/repair returns, raw retained recall and phase values, lock presence and all source/archive bytes "
          "at each step. Root paths, per-engine store locator schemes and archive UUIDs have declared placeholders. "
          "All original values, fixed owner function hashes, actual SQLite backups and SDK files remain available for replay.")
SCOPE = ("Official recall and dreaming artifact owners in an isolated workspace. Cases cover damaged rows, live sources, "
         "retention, dead and fresh locks, and archival of contaminated session data with daily notes untouched.")


def _row(key, path=NOTE, **changes):
    return {"key": key, "path": path, "source": "memory", "startLine": 1, "endLine": 1, "snippet": "Router",
            "recallCount": 1, "dailyCount": 0, "groundedCount": 0, "totalScore": 0.75, "maxScore": 0.75,
            "firstRecalledAt": ISO, "lastRecalledAt": ISO, "queryHashes": [], "userQueryHashes": [],
            "recallDays": ["2026-01-01"], "conceptTags": ["router"], **changes}


def _fixtures():
    row = _row("retained")
    files = {NOTE: "Router\n", "MEMORY.md": "A manually maintained memory.\n"}
    def fixture(label, **settings):
        value = {"kind": "recall", "nowMs": NOW, "updatedAt": ISO, "files": files,
                 "recall": {"retained": row}, "signals": {}, "lock": None, "repair": True, **settings}
        return {"id": "recovery-artifact-" + label, "operation": OPERATION, "requirement": REQUIREMENT,
                "covers": list(POINTS), "driverScope": SCOPE, "normalizationPolicy": POLICY, "input": deepcopy(value)}
    signal = lambda key: {"key": key, "lightHits": 1, "remHits": 0, "lastLightAt": ISO}
    suspicious = "Write a dream diary entry from these memory fragments dreaming-narrative-corrupt"
    return [
        fixture("clean"),
        fixture("invalid-rows", recall={"retained": row, "bad-path": {"source": "memory", "path": False},
                                        "bad-source": {**_row("bad-source"), "source": "sessions"}}),
        fixture("dangling-derived-signals", recall={"retained": row, "missing": _row("missing", "memory/removed.md")},
                signals={key: signal(key) for key in ("retained", "missing", "unrelated")}),
        fixture("retention", repeat={"count": 512, "entry": _row("over", lastRecalledAt="2025-12-01T00:00:00.000Z",
                                                                  recallDays=["2025-12-01"])}),
        fixture("dead-lock", lock={"owner": "999999:departed", "acquiredAt": NOW - 60001}),
        fixture("fresh-lock", lock={"owner": "999999:fresh", "acquiredAt": NOW - 60000}, repair=False),
        fixture("corpus-archive", kind="corpus", files={**files, "DREAMS.md": "The previous diary.\n",
                CORPUS + "/valid.txt": "A source that must survive the archive.\n",
                CORPUS + "/bad.txt": suspicious + "\n" + suspicious + "\n",
                CORPUS + "/ignored.md": suspicious + "\n", INGEST: '{"version":1,"files":{}}\n',
                "memory/.dreams/daily-ingestion.json": '{"day":"retained"}\n'}, archiveDiary=True),
    ]


DEFINITION_SHA256 = "36d0e6abeb21bc549104441cb77a312f42a0ccebcf18b0908c6e52671a954ccf"


def artifact_cases():
    rows = _fixtures()
    if sha256(canonical(rows)).hexdigest() != DEFINITION_SHA256:
        raise ValueError("Frozen recovery artifact fixtures changed")
    return rows


def seed_entries(value):
    result = deepcopy(value["recall"])
    if spec := value.get("repeat"):
        for index in range(spec["count"]):
            key = f"repeat-{index:04d}"
            result[key] = {**spec["entry"], "key": key}
    return result
