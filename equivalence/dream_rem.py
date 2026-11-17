"""Frozen real-workspace inputs for the original REM phase's two checklist conditions."""
from __future__ import annotations

import hashlib
import json

OPERATION = "dream-rem-runtime"
POINTS = ("dreaming.rem.outcomes", "dreaming.rem.boundaries")
RECALL = "memory/.dreams/short-term-recall.json"
SIGNALS = "memory/.dreams/phase-signals.json"
NOTE = "memory/2025-11-01-observatory.md"
NOW = 1_767_268_800_000
ISO = "2026-01-01T09:00:00.000Z"
POLICY = ("Compare complete report and diary bytes, canonical recall and phase stores, host events, "
          "full ordered narrative requests, degraded/pending phase counts and physical workspace readbacks. "
          "Only the owned workspace's absolute path varies. Preserve all raw files, calls, logs and errors.")
DRIVER_SCOPE = ("A real local UTC workspace runs the ordinary awaited REM sweep from both public entry points. "
                "The deterministic injected provider replies or raises at the model boundary. The original "
                "and SDK execute their normal selection, evidence, storage, fallback and source revalidation "
                "owners. Remote provider transport and detached cron scheduling have separate owners.")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()


def _entry(key, snippet, line, *, tags, count=4, score=0.82, path=NOTE, when=ISO, **fields):
    return {"key": key, "path": path, "startLine": line, "endLine": line, "source": "memory",
            "snippet": snippet, "recallCount": count, "dailyCount": 0, "groundedCount": 0,
            "totalScore": score * count, "maxScore": score, "firstRecalledAt": when,
            "lastRecalledAt": when, "queryHashes": [key], "recallDays": [], "conceptTags": tags, **fields}


def _case(name, entries, *, signals=None, files=None, operations=None, strength=0.75,
          limit=3, mode="separate", provider=None, agent="main", model=None):
    files = {NOTE: "# Notebook\n\n" + "\n".join(e["snippet"] for e in entries if e["path"] == NOTE) + "\n",
             **(files or {})}
    files[RECALL] = json.dumps({"version": 1, "updatedAt": ISO, "entries": {e["key"]: e for e in entries}})
    if signals:
        files[SIGNALS] = json.dumps({"version": 1, "updatedAt": ISO, "entries": signals})
    return {"id": f"dream-rem-{name}", "requirement": "dreaming.rem", "operation": OPERATION,
            "input": {"files": files, "options": {"enabled": True, "timezone": "UTC", "lookbackDays": 2,
                      "limit": limit, "minPatternStrength": strength, "storageMode": mode,
                      "provider": provider, "agentId": agent, "model": model},
                      "operations": operations or [{"op": "rem", "nowMs": NOW}]},
            "covers": list(POINTS), "normalizationPolicy": POLICY, "driverScope": DRIVER_SCOPE}


def _frozen_cases():
    fern = _entry("fern", "Ferns unfurled beside the east dome.", 3, tags=["ＦＥＲＮ", "fern", "weather"])
    dew = _entry("dew", "Dew formed beads on the telescope.", 4, tags=["weather", "dawn"])
    weak = _entry("mist", "A trace of morning mist.", 5, tags=["weather"], count=1, score=0.1)
    old = _entry("archive", "A retired observation.", 6, tags=["dawn"], promotedAt=ISO)
    duplicate = _entry("fern-copy", fern["snippet"], 7, tags=["weather", "sprout"], count=5)
    def signal(key, **fields):
        return {"key": key, "lightHits": 1, "remHits": 0, "lastLightAt": ISO, **fields}
    return [
        _case("staged-then-consumed", [fern, weak, dew, old], mode="both",
              signals={"fern": signal("fern"), "mist": signal("mist"),
                       "dew": signal("dew", lastRemConsideredAt=ISO),
                       "archive": signal("archive", lastRemAt=ISO)},
              operations=[{"op": "rem", "nowMs": NOW}, {"op": "rem", "nowMs": NOW + 1000}]),
        _case("themes-evidence-diary", [fern, duplicate, dew, weak, old], strength=0.6,
              files={"DREAMS.md": "# Private notes\n\nThe ink has dried.\n"}, model="fixture/diarist",
              provider=[{"text": "  I folded the fern tip into the margin.  "}]),
        _case("lost-and-blocked", [fern, _entry("absent", "Gone.", 1, path="memory/2025-11-02-absent.md",
              tags=["weather"]), _entry("blocked", "Restricted.", 8, tags=["weather"],
              provenance={"originClass": "untrusted", "sessionKind": "unknown", "observedAt": NOW - 1}),
              _entry("stale", "Expired.", 9, tags=["weather"], when="2025-12-01T09:00:00.000Z")],
              signals={key: signal(key) for key in ("absent", "blocked", "stale")},
              operations=[{"op": "rem", "nowMs": NOW}, {"op": "remove", "path": NOTE},
                          {"op": "rem", "nowMs": NOW + 1000}]),
        _case("no-truth-empty-reply", [weak], provider=[{"text": "  "}],
              files={"DREAMS.md": "# Dream Diary\n\n<!-- openclaw:dreaming:diary:start -->\nOld entry.\n"}),
        _case("model-retry", [dew], model="fixture/unavailable",
              provider=[{"error": "unknown model"}, {"text": "The silver dome cooled."}]),
        _case("source-removed-during-completion", [fern, dew],
              provider=[{"removeKey": "dew", "text": "This observation was withdrawn."}]),
        _case("publication-failure", [fern], files={"DREAMS.md/keep.txt": "Existing directory"},
              provider=[{"text": "An entry waiting for its page."}]),
        _case("no-owner", [weak], agent=None, provider=[]),
    ]


def build_cases():
    rows = _frozen_cases()
    if hashlib.sha256(canonical(rows)).hexdigest() != DEFINITION_SHA256:
        raise ValueError("REM dreaming fixture definitions changed")
    return rows


def validate_case(case):
    expected = next((r for r in build_cases() if r["id"] == case.get("id")), None)
    if expected is None or canonical({key: case.get(key) for key in expected}) != canonical(expected):
        raise ValueError("REM dreaming requires a complete frozen case")


def members(cases):
    return [c for c in cases if c.get("requirement") == "dreaming.rem" or c.get("operation") == OPERATION
            or set(c.get("covers", ())).intersection(POINTS)]


def validate_registration(cases):
    family = members(cases)
    if family:
        if [r["id"] for r in family] != [r["id"] for r in build_cases()]:
            raise ValueError("Both REM points require every ordered fixture")
        for row in family:
            validate_case(row)


def family_complete(rows):
    family = members(rows)
    if not family:
        return False
    try:
        validate_registration(rows)
    except (KeyError, TypeError, ValueError):
        return False
    return all(r["status"] == "matched" and r.get("runtimeEvidenceValidated") is True for r in family)


DEFINITION_SHA256 = "228a41f65979ab9fa23a36f0ee42799e875fa265f72a92b220971ea3171089f1"
