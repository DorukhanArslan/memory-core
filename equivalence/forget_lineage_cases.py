"""Six input-only forget/lineage diagnostics; none awards acceptance credit."""
from copy import deepcopy
import hashlib

NOW = 1_794_268_800_000
ISO = "2026-11-10T00:00:00.000Z"
CORPUS = "memory/.dreams/session-corpus/2026-11-10.txt"
OPERATION = "forget-lineage-runtime"
REQUIREMENT = "forget.lineage-tombstones"
PROFILE = ("Actual forget, persisted session selection, tombstone admission and grounded-backfill "
           "owners, without providers. Replay exercises admission and persistence, not a full host scan. "
           "Reopen reconstructs owners and rereads durable databases; it is not a fresh process.")
POLICY = ("Common literal inputs only; complete reports, errors, owner returns and logical states. "
          "All workspace files are compared except memory/.dreams/{short-term-recall,phase-signals,"
          "consolidation-preimages,session-ingestion}.json, whose complete owner reads are compared separately. "
          "Complete physical files and database schema/rows remain raw. No field dropping or tolerance. "
          "Native undefined returns and SDK integer returns remain distinct. Covers stays empty.")


def _note(key, text):
    return f"<!-- openclaw-memory-promotion:{key} -->\n- {text}\n"


def _origin(key, session, agent="main"):
    return {"entryKey": key, "agentId": agent, "sessionId": session,
            "sessionKey": f"agent:{agent}:dm:{session.lower()}", "originClass": "owner", "observedAt": NOW - 1000}


def _session(identifier, agent="main", *, age=1000, hook="gmail", actor="actor-a"):
    return {"agentId": agent, "sessionId": identifier, "sessionKey": f"agent:{agent}:dm:{identifier.lower()}",
            "createdAt": NOW - age, "hookExternalContentSource": hook,
            "participants": [{"type": "profile", "id": actor}],
            "messages": [{"role": "user", "content": f"Remember the independent {agent} {identifier} planning fact.",
                          "timestamp": NOW - 1000}]}


def _forget(**selectors):
    return {"op": "forget", **selectors}


def _sequence():
    return [_forget(sessionIds=["A"], dryRun=True), _forget(sessionIds=["A"]), _forget(sessionIds=["A"])]


def _hit(session, line, agent="main"):
    return {"path": CORPUS, "startLine": line, "endLine": line, "source": "memory", "score": 0.58,
            "snippet": f"User: Remember the independent {agent} {session} planning fact.",
            "sessionOrigin": {"agentId": agent, "sessionId": session, "sessionKey": f"agent:{agent}:dm:{session.lower()}"},
            "provenance": {"originClass": "owner", "sessionKind": "interactive", "observedAt": NOW - 1000}}


def _recall(key, text):
    return {"key": key, "path": "memory/2026-11-10.md", "startLine": 1, "endLine": 1, "source": "memory",
            "snippet": text, "recallCount": 1, "dailyCount": 0, "groundedCount": 0, "totalScore": 0.8,
            "maxScore": 0.8, "firstRecalledAt": ISO, "lastRecalledAt": ISO,
            "queryHashes": ["literal-query"], "recallDays": ["2026-11-10"], "conceptTags": []}


def build_cases():
    memory = "# Memory\n\n" + _note("note-a", "Only meeting A.") + _note("note-b", "Only meeting B.")
    memory += "<!-- openclaw-memory-lineage:shared-ab -->\n" + _note("note-ab", "One indivisible note from A and B.")
    base = {"kind": "forget-lineage-tombstones", "nowMs": NOW, "timezone": "UTC", "agentId": "main",
            "files": {"MEMORY.md": memory}, "sessions": [_session("A"), _session("B", age=86_400_000, hook="webhook", actor="actor-b")],
            "origins": [_origin("note-a", "A"), _origin("note-b", "B"), _origin("note-ab", "A"), _origin("note-ab", "B")],
            "operations": _sequence()}
    variants = {name: deepcopy(base) for name in ("direct", "promoted-mixed", "missing-origin", "derived-artifacts", "replay-admission", "selectors")}
    variants["direct"]["files"]["memory/2026-11-10.md"] = (
        "# Daily\n\n## Imported from main:A\nA private direct section.\n\n## Independent B\nKeep B's separate section.\n")
    missing = variants["missing-origin"]
    missing["origins"] = [_origin("note-b", "B")]
    missing["files"]["MEMORY.md"] += _note("unknown-source", "A note with no recorded source or session reference.")
    missing["operations"] = [_forget(sessionIds=["A", "unknown-session"], dryRun=True),
                             _forget(sessionIds=["A", "unknown-session"]), _forget(sessionIds=["A", "unknown-session"])]
    derived = variants["derived-artifacts"]
    quote = "User: Remember that meeting A budgets must stay private."
    derived["files"].update({"DREAMS.md": "# Dreams\n\n" + _note("note-a", "A derived dream.") + _note("note-b", "A retained B dream."),
                             CORPUS: f"[main/sessions/main/A#L1] {quote}\n[main/sessions/main/B#L1] User: Keep B's independent planning fact.\n",
                             "memory/2026-11-10.md": f"# Daily\n- Quoted: {quote}\n- B's unrelated daily fact.\n"})
    derived["recall"] = {"version": 1, "updatedAt": ISO, "entries": {key: _recall(key, text) for key, text in
                         (("note-a", "A derived recall."), ("note-b", "B retained recall."))}}
    derived["phase"] = {"version": 1, "updatedAt": ISO, "entries": {key: {"key": key, "lightHits": 1, "remHits": 0,
                        "lastLightAt": ISO, "lastRemAt": None, "updatedAt": ISO} for key in ("note-a", "note-b")}}
    derived["preimages"] = [{"createdAt": ISO, "content": memory, "contentHash": hashlib.sha256(memory.encode()).hexdigest()}]
    derived["ingestion"] = {"version": 3, "files": {f"main:sessions/main/{s}": {"mtimeMs": NOW, "size": 4,
                           "contentHash": f"literal-{s}", "lineCount": 1, "lastContentLine": 1} for s in ("A", "B")},
                           "seenMessages": {f"main:sessions/main/{s}": [f"literal-message-{s}"] for s in ("A", "B")}}
    replay = variants["replay-admission"]
    replay["sessions"].append(_session("A", "other", hook="webhook", actor="actor-other"))
    replay["operations"] = [_forget(sessionIds=["A"]), {"op": "reopen"}, {"op": "replay", "agentIds": ["main", "other"],
                            "backfill": {"day": "2026-11-10", "results": [_hit("A", 1), _hit("B", 2), _hit("A", 3, "other")]}}]
    variants["selectors"]["operations"] = [
        _forget(sessionIds=["A"], dryRun=True), _forget(sessionIds=["agent:main:dm:a"], dryRun=True),
        _forget(hookSources=["gmail"], dryRun=True), _forget(participants=["actor-a"], dryRun=True),
        _forget(sessionIds=["A", "B"], since=NOW - 3_600_000, dryRun=True), _forget(),
        _forget(participants=["actor-a"], since=NOW - 3_600_000)]
    return [{"id": "forget-lineage-" + name, "operation": OPERATION, "requirement": REQUIREMENT,
             "covers": [], "input": value, "driverScope": PROFILE, "normalizationPolicy": POLICY}
            for name, value in variants.items()]


def validate_case(case):
    if case not in build_cases():
        raise ValueError("Forget lineage diagnostics require one exact common input with empty covers")
    return deepcopy(case)
