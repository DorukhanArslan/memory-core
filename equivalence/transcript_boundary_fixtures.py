"""Common literal bytes/events; no projected result or visibility decision is supplied."""
from __future__ import annotations
from copy import deepcopy
import json

_NOW = 1794000000000
_CACHE_INPUT = {'kind': 'boundary', 'source': 'jsonl', 'nowMs': 1794000000000, 'fileName': '00000000-0000-4000-8000-000000000027.jsonl.reset.2026-11-09T00-00-00Z.zst', 'environmentFault': {'kind': 'preferred-temp-root-unavailable'}, 'initial': {'rawBytes': [40, 181, 47, 253, 32, 112, 245, 2, 0, 242, 5, 20, 25, 128, 169, 109, 134, 154, 182, 216, 98, 220, 37, 160, 73, 74, 175, 198, 88, 168, 233, 141, 152, 69, 24, 72, 1, 6, 128, 181, 214, 85, 238, 57, 143, 200, 65, 13, 121, 132, 87, 196, 24, 7, 127, 164, 82, 108, 22, 16, 2, 105, 208, 11, 62, 47, 126, 49, 29, 155, 243, 170, 140, 148, 78, 206, 60, 80, 62, 163, 132, 205, 71, 24, 213, 43, 124, 254, 177, 88, 39, 1, 3, 0, 166, 42, 94, 82, 161, 112, 197, 116, 2], 'mtimeMs': 1794000000000.125}, 'steps': [{'op': 'read', 'label': 'first'}, {'op': 'write', 'label': 'same-size-replacement', 'rawBytes': [40, 181, 47, 253, 32, 112, 245, 2, 0, 242, 5, 20, 25, 128, 169, 109, 134, 154, 182, 216, 98, 220, 37, 160, 73, 74, 175, 198, 216, 163, 246, 141, 204, 100, 72, 96, 10, 3, 128, 181, 214, 85, 238, 57, 143, 200, 65, 13, 121, 132, 87, 196, 24, 7, 127, 164, 82, 108, 22, 16, 2, 105, 208, 11, 62, 47, 126, 49, 29, 155, 243, 170, 140, 148, 78, 206, 60, 80, 62, 163, 132, 205, 71, 24, 213, 43, 124, 254, 177, 88, 39, 1, 3, 0, 166, 42, 94, 82, 161, 112, 197, 116, 2], 'sameSize': True, 'mtimeMs': 1794000000000.875}, {'op': 'read', 'label': 'replaced'}]}


def build_transcript_boundary_cases():
    cases = []
    def add(name, value, *, diagnostic=False):
        cases.append({"id": "transcript-boundary-" + name,
                      "requirement": "sessions.transcript-filtering", "covers": [],
                      "operation": "transcript-boundary-runtime", "input": deepcopy(value),
                      "driverScope": "Actual original file/archive or SQLite source projection; complete source metadata, hash, physical raw ordinals, callbacks, reset cutoff and errors. No active-leaf ingestion claim. Archive cache collision remains a named uncredited diagnostic.",
                      "normalizationPolicy": "Only the exact owned fixture-root prefix is mapped to $FIXTURE; complete raw inputs, physical files, SQL records and outputs remain retained. No content, hash, order, error, score or metadata repair.",
                      **({"diagnosticOnly": True} if diagnostic else {})})
    def event(identifier, text, role="user", parent=None):
        return {"type": "message", "id": identifier, "parentId": parent,
                "message": {"role": role, "content": text, "timestamp": _NOW,
                            "__openclaw": {"senderIsOwner": True}}}
    events = [{"type":"session","version":4,"id":"boundary","cwd":"/fixture/workspace","timestamp":"2026-11-06T21:20:00.000Z"},
              event("root", "Cedar root"), event("abandoned", "Cedar abandoned", "assistant", "root"),
              {"type":"leaf", "id":"root"}, event("active", "Cedar active", "assistant", "root"),
              event("side", "Cedar side append", "user", "root"),
              {"type":"message", "id":"tool", "parentId":"active", "message":{"role":"toolResult", "toolCallId":"call-1", "toolName":"lookup", "content":[{"type":"text","text":"Cedar tool payload"}], "isError":False,"timestamp":_NOW}},
              {"type":"reset", "id":"cutoff", "firstKeptEntryId":"active"}, event("after", "Cedar after reset", parent="side")]
    malformed = b'\xef\xbb\xbf'+json.dumps(events[0],separators=(",",":" )).encode()+b'\r\n\n{bad JSON}\nnull\n[]\n'+b'\n'.join(json.dumps(e,separators=(",",":" )).encode() for e in events[1:])+b'\n'+b'\xff\n'
    add("jsonl-physical-order-malformed-observer", {"kind":"boundary","source":"jsonl","nowMs":_NOW,
        "observer":True,"initial":{"rawBytes":list(malformed)},"steps":[{"op":"read","label":"physical-order"}]})
    add("sqlite-ordered-forks-latest-reset", {"kind":"boundary","source":"sqlite","nowMs":_NOW,
        "initial":{"events":events}, "steps":[{"op":"read","label":"worker-order"},
        {"op":"read","label":"observed-order","observer":True},
        {"op":"replace-events","label":"latest-invalid-reset","events":[*events,{"type":"reset","id":"bad-cutoff","firstKeptEntryId":"unknown"}]},
        {"op":"read","label":"invalid-cutoff"},
        {"op":"replace-events","label":"latest-valid-reset","events":[*events,{"type":"reset","id":"latest"},event("last","Cedar latest")]},
        {"op":"read","label":"latest-cutoff"}]})
    add("plain-file-lifecycle", {"kind":"boundary","source":"jsonl","nowMs":_NOW,
        "fileName":"boundary.jsonl.reset.2026-11-09T00-00-00Z", "steps":[{"op":"read","label":"missing"},
        {"op":"write","label":"create","events":events},{"op":"read","label":"created"},
        {"op":"remove","label":"delete"},{"op":"read","label":"disappeared"},
        {"op":"directory","label":"nonregular"},{"op":"read","label":"directory"},
        {"op":"symlink","label":"symlink","events":events},{"op":"read","label":"symlink-target"}]})
    archive={"kind":"boundary","source":"jsonl","nowMs":_NOW,
             "fileName":"boundary.jsonl.reset.2026-11-09T00-00-00Z.zst",
             "environmentFault":{"kind":"preferred-temp-root-unavailable"}}
    first=_CACHE_INPUT["initial"]["rawBytes"]
    second=_CACHE_INPUT["steps"][1]["rawBytes"]
    add("compressed-archive-replaced-deleted", {**archive,"initial":{"rawBytes":first},"steps":[
        {"op":"read","label":"first"},{"op":"write","label":"replace","rawBytes":second,"mtimeMs":_NOW+1000},
        {"op":"read","label":"replaced"},{"op":"remove","label":"delete"},{"op":"read","label":"disappeared"}]})
    add("compressed-codec-boundaries", {**archive,"steps":[{"op":"read","label":"missing"},
        {"op":"write","label":"corrupt","rawBytes":list(b"not a zstd frame")}, {"op":"read","label":"corrupt"},
        {"op":"write","label":"empty","rawBytes":[]}, {"op":"read","label":"empty"},
        {"op":"write","label":"truncated","rawBytes":first[:-8],"mtimeMs":_NOW+1000}, {"op":"read","label":"truncated"},
        {"op":"write","label":"concatenated","rawBytes":first+second,"mtimeMs":_NOW+2000}, {"op":"read","label":"first-frame-only"}]})
    for source in ("jsonl","sqlite"):
        add(source+"-observer-error", {"kind":"boundary","source":source,"nowMs":_NOW,"initial":{"events":events},
            "observer":True,"observerError":{"name":"Error","message":"Declared transcript observer failure","code":"FIXTURE_OBSERVER"},
            "steps":[{"op":"read","label":"observer-failed"}]})
    add("compressed-same-size-mtime-cache-diagnostic", _CACHE_INPUT, diagnostic=True)
    return cases
