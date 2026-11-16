"""Closed input-only family for both original recall-recording conditions."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json

OPERATION = "recall-signals-runtime"
REQUIREMENT = "promotion.recall-signals"
POINTS = ("promotion.recall-signals.outcomes", "promotion.recall-signals.boundaries")
NOW = 1_794_268_800_000
DAY = "2026-11-10"
DAILY = "memory/2026-11-10.md"
NEXT = "memory/2026-11-11.md"
CORPUS = "memory/.dreams/session-corpus/2026-11-10.txt"
FAILURE_MARKER = "recall-origin-write-blocked"
CASE_HASHES = {
    "recall-signals-filtering-events": "cdb91f6f91d3b9dac3dbaa4672146d1e5c67093c76f65d583137cc70755ee085",
    "recall-signals-claim-identity": "af37efa21e69e9cb1fe6e2f1080fd0cda58b7e139a1244f9c33bae092527e665",
    "recall-signals-day-dedupe": "5138614e246a45b478e7a5279981dd039086d6880f4c94f15785219c6f4c0507",
    "recall-signals-caps-retention": "67f887a813f663b1fec72c09447f662084e3207ae2779dd51aef034dbaa05433",
    "recall-signals-source-lineage": "3d21b3a6d173d22189b6c9878fe92748cd43d4bf06c5e14fe7702200b4852205",
    "recall-signals-origin-failure-recovery": "00e8feb5d9195f5a6b9c507dd50c0cf83e9ee313eb4aaf1d48dc72d7bacd6239",
}
POLICY = (
    "Compare the complete before state and every operation, completion outcome, "
    "canonical recall store, origin and tombstone rows, and complete stored-form "
    "host events. Actual Native void returns, SDK integer returns, and complete "
    "exceptions remain distinct in retained raw evidence; none is coerced into "
    "a fabricated common return. Literal source ranges and current source bytes "
    "and revisions are authenticated before dispatch. Append-grounded calls feed "
    "the actual corpus appender return directly to the actual grounded writer. "
    "All physical files, SQL rows, original arguments, producer returns and "
    "publication-order evidence remain retained without rewriting."
)
DRIVER_SCOPE = (
    "Actual recordShortTermRecalls recall/daily variants, grounded wrapper, "
    "source corpus appender, recall-store and event readers, durable origins and "
    "tombstones, and their SDK counterparts. Origin failure uses a real SQLite "
    "BEFORE INSERT abort followed by recovery. Seed stores are complete input "
    "facts, never writer outcomes. No provider, full dreaming lifecycle, stale "
    "source rejection, invalid TypeScript numeric inputs, or cross-process claim."
)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf8")


def case_wire(case):
    return canonical({key: case[key] for key in ("id", "operation", "input")})


def _iso(now):
    return datetime.fromtimestamp(now / 1000, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _hash(value):
    return hashlib.sha1(value.encode("utf8")).hexdigest()[:12]


def _hit(path, line, text, **extra):
    return {"path": path, "startLine": line, "endLine": line, "source": "memory", "score": .75,
            "snippet": text, "provenance": {"originClass": "owner", "sessionKind": "interactive",
                                             "observedAt": NOW}, **extra}


def _call(query, results, *, now=NOW, **extra):
    return {"op": "recall", "nowMs": now, "query": query, "results": deepcopy(results), **extra}


def _ground(query, items, *, now=NOW, **extra):
    return {"op": "grounded", "nowMs": now, "query": query, "items": deepcopy(items), **extra}


def _base(files, operations, **extra):
    return {"kind": "recall-signals", "nowMs": NOW, "timezone": "UTC", "files": files,
            "store": {"version": 1, "updatedAt": _iso(NOW), "entries": {}},
            "tombstones": [], "operations": operations, **extra}


def _filtering():
    text = ["A retained planning fact.", "<!-- openclaw-memory-promotion:copied -->",
            "[dreaming-narrative] User: Write a dream diary entry from these memory fragments:",
            "Session Key: secret Session ID: private", "Conversation Summary: do not stage this.",
            "User: An ordinary transcript turn.",
            "Save important context from this session to the daily memory file. STRICT RULES:",
            "[score=0.8 signals=2 recalls=2 avg=0.7 source=memory/2026-11-10.md]",
            "Candidate: copied; confidence: 0.9; evidence: memory/2026-11-10.md; status: staged; recalls: 2",
            "", "Another independent planning fact."]
    files = {DAILY: "\n".join(text) + "\n", "MEMORY.md": "A curated fact.\n", "2026-11-10.md": text[0] + "\n",
             "memory/dreaming/2026-11-10.md": "A dreaming artifact.\n", CORPUS: text[5] + "\n"}
    long_path = "memory/" + "p" * 120 + "/" + "q" * 120 + "/2026-11-10.md"
    files[long_path] = text[0] + "\n"
    valid = _hit(DAILY, 1, text[0])
    skipped = _hit("MEMORY.md", 1, "A curated fact.")
    calls = [_call(" \t", [valid]), _call("empty", []),
             _call("non-memory", [{**valid, "source": "sessions"}]), _call("skip only", [skipped]),
             _ground("grounded skip only", [skipped]),
             _call("contamination only", [_hit(DAILY, index + 1, value) for index, value in enumerate(text) if 1 <= index <= 8]),
             _call("mixed", [_hit(DAILY, index + 1, value) for index, value in enumerate(text)] +
                   [skipped, _hit("memory/dreaming/2026-11-10.md", 1, "A dreaming artifact.")]),
             _call("basename and clamped scores", [_hit("2026-11-10.md", 1, text[0], score=1.5), {**valid, "score": -.5}]),
             _call("corpus recall", [_hit(CORPUS, 1, text[5])]),
             _ground("corpus grounded", [_hit(CORPUS, 1, text[5])]),
             _call("path and query limits " + "é" * 1024, [_hit(long_path, 1, text[0])] * 11),
             _call("event JSON limit " + "\x01" * 1400, [valid])]
    return _base(files, calls)


def _identity():
    a, b = "Cedar tea is preferred.", "Backups run after midnight."
    changed, empty, absent = "Backups run after midnight on weekdays.", "An empty explicit identity.", "An absent identity."
    files = {DAILY: f"{a}\n{b}\n{empty}\n{absent}\n", NEXT: f"{a}\n{b}\n{changed}\n"}
    calls = [_call("recall first", [_hit(DAILY, 1, a)]),
             _call("daily after recall", [_hit(NEXT, 1, a)], now=NOW + 1, signalType="daily"),
             _call("daily first", [_hit(DAILY, 2, b)], now=NOW + 2, signalType="daily"),
             _call("recall after daily", [_hit(NEXT, 2, b, projectKey="GITHUB.com/Owner/Repo",
                   provenance={"originClass": "untrusted", "sessionKind": "unknown", "observedAt": NOW + 3})], now=NOW + 3),
             _ground("grounded after daily", [_hit(NEXT, 2, b, signalCount=2,
                     projectKey="github.com/Owner/Repo; path:/Case")], now=NOW + 4),
             _call("daily first", [_hit(NEXT, 2, b)], now=NOW + 5, signalType="daily"),
             _call("daily first", [_hit(NEXT, 3, changed, identitySnippet=b)], now=NOW + 6, signalType="daily"),
             _call("explicit empty", [_hit(DAILY, 3, empty, identitySnippet="")], now=NOW + 7, signalType="daily"),
             _call("absent identity", [_hit(DAILY, 4, absent)], now=NOW + 8, signalType="daily")]
    return _base(files, calls)


def _days():
    text = "The maintenance window follows the local calendar."
    hit = _hit(DAILY, 1, text)
    before, after = NOW + 20 * 3_600_000 + 59 * 60_000, NOW + 21 * 3_600_000 + 60_000
    calls = [_call(" Calendar Query ", [hit], now=before, dedupeByQueryPerDay=True),
             _call("calendar query", [hit], now=before + 1000, dedupeByQueryPerDay=True),
             _call("calendar query", [hit], now=after, dedupeByQueryPerDay=True),
             _call("changed query", [hit], now=after + 1, dedupeByQueryPerDay=True),
             _call("explicit bucket", [hit], now=after + 2, dayBucket="2026-11-15T12:00:00Z"),
             _call("invalid bucket", [hit], now=after + 3, dayBucket="not-a-day"),
             _ground("outer", [{**hit, "query": " Inner Query ", "dayBucket": "2026-11-16", "signalCount": 3}],
                     now=after + 4, dedupeByQueryPerDay=True, dayBucket="2026-11-17"),
             _ground("other outer", [{**hit, "query": "inner query", "dayBucket": "2026-11-16", "signalCount": 7}],
                     now=after + 5, dedupeByQueryPerDay=True),
             _call("daily local", [hit], now=after + 6, signalType="daily", dedupeByQueryPerDay=True),
             _ground("empty item bucket", [{**hit, "query": "", "dayBucket": ""}],
                     now=after + 7, dayBucket="2026-11-17")]
    return _base({DAILY: text + "\n"}, calls, timezone="Europe/Istanbul")


def _seed_entry(key, path, line, snippet, stamp):
    return {"key": key, "path": path, "startLine": line, "endLine": line, "source": "memory",
            "snippet": snippet, "recallCount": 1, "dailyCount": 0, "groundedCount": 0,
            "totalScore": .75, "maxScore": .75, "firstRecalledAt": stamp, "lastRecalledAt": stamp,
            "queryHashes": [_hash("seed")], "userQueryHashes": [_hash("seed")],
            "recallDays": ["2026-11-09"], "conceptTags": []}


def _caps():
    texts = [f"Retained source fact {index:03d}." for index in range(510)]
    texts += ["x" * 799 + "😀tail"]
    files, entries = {DAILY: "\n".join(texts) + "\n"}, {}
    for index, text in enumerate(texts[:510], 1):
        key = f"memory:{DAILY}:{index}:{index}"
        entries[key] = _seed_entry(key, DAILY, index, text, _iso(NOW - 1000))
    for letter in ("A", "a"):
        path, text = f"memory/{letter}/2026-11-10.md", "An equal-priority retained fact."
        files[path] = text + "\n"
        key = f"memory:{path}:1:1"
        entries[key] = _seed_entry(key, path, 1, text, _iso(NOW - 86_400_000))
    first = entries[f"memory:{DAILY}:1:1"]
    first.update(recallCount=31, totalScore=23.25,
                 queryHashes=[_hash(f"prior-{index:02d}") for index in range(31)],
                 userQueryHashes=[_hash(f"prior-{index:02d}") for index in range(31)],
                 recallDays=[f"2026-10-{index:02d}" for index in range(1, 16)])
    calls = [_call("cap-32", [_hit(DAILY, 1, texts[0])], dayBucket="2026-11-10"),
             _call("cap-33", [_hit(DAILY, 1, texts[0])], now=NOW + 1, dayBucket="2026-11-11"),
             _call("entry-513", [_hit(DAILY, 511, texts[510])], now=NOW + 2)]
    return _base(files, calls, store={"version": 1, "updatedAt": _iso(NOW), "entries": entries})


def _candidate(session, text, index=0):
    scope = "main:sessions/main/" + session
    return {"day": DAY, "snippet": text, "rendered": f"[{scope}#L1] {text}",
            "provenance": {"originClass": "owner", "sessionKind": "interactive", "observedAt": NOW},
            "sessionOrigin": {"agentId": "main", "sessionId": session, "sessionKey": "agent:main:dm:" + session.lower()},
            "contentIndex": index, "hash": "literal-source-" + session, "lineNumber": 1,
            "scope": scope, "stateKey": scope}


def _append(query, lines, *, now=NOW, **extra):
    return {"op": "append-grounded", "nowMs": now, "query": query,
            "append": {"day": DAY, "lines": lines}, "dayBucket": DAY, **extra}


def _lineage():
    a, b = _candidate("A", "A forgotten claim must stay excluded."), _candidate("B", "B remains independently eligible.", 1)
    calls = [_append("grounded live sources", [a, b]),
             _append("grounded duplicate", [deepcopy(b)], now=NOW + 1),
             _call("recalled corpus", [_hit(CORPUS, 2, b["snippet"], sessionOrigin=b["sessionOrigin"])], now=NOW + 2)]
    return _base({CORPUS: ""}, calls, tombstones=[{"agentId": "main", "sessionIds": ["A"]}])


def _failure():
    b, c = _candidate("B", "A successful independent baseline."), _candidate("C", "Lineage must precede staged state.")
    calls = [_append("baseline", [b]), _append("failure", [c], now=NOW + 1, failOrigins=True),
             _append("failure", [deepcopy(c)], now=NOW + 2)]
    return _base({CORPUS: ""}, calls)


def build_cases():
    values = (('filtering-events', _filtering()), ('claim-identity', _identity()), ('day-dedupe', _days()),
              ('caps-retention', _caps()), ('source-lineage', _lineage()), ('origin-failure-recovery', _failure()))
    cases = [{"id": "recall-signals-" + name, "operation": OPERATION, "requirement": REQUIREMENT,
              "covers": list(POINTS), "input": value, "normalizationPolicy": POLICY, "driverScope": DRIVER_SCOPE}
             for name, value in values]
    if [case["id"] for case in cases] != list(CASE_HASHES) or any(
            hashlib.sha256(case_wire(case)).hexdigest() != CASE_HASHES[case["id"]] for case in cases):
        raise ValueError("Recall signals differ from the complete frozen six-case authority")
    return cases


def validate_case(case):
    if not isinstance(case, dict) or not any(canonical(case) == canonical(original) for original in build_cases()):
        raise ValueError("Recall signals require an exact complete registered family member")
    return deepcopy(case)


def validate_input(value):
    if not any(canonical(value) == canonical(case["input"]) for case in build_cases()):
        raise ValueError("Recall signals require one exact frozen common input")


def family_members(cases):
    return [case for case in cases if case.get("operation") == OPERATION
            or str(case.get("id", "")).startswith("recall-signals-") or set(case.get("covers", ())) & set(POINTS)]


def validate_registration(cases):
    family = family_members(cases)
    if family:
        if [case.get("id") for case in family] != list(CASE_HASHES):
            raise ValueError("Recall signals require the complete unchanged six-case family atomically")
        for case in family:
            validate_case(case)


def family_complete(rows):
    family = family_members(rows)
    if [row.get("id") for row in family] != list(CASE_HASHES):
        return False
    try:
        for row in family:
            validate_case({key: row[key] for key in (
                "id", "operation", "requirement", "covers", "input", "normalizationPolicy", "driverScope")})
        return bool(family) and all(row.get("status") == "matched" and row.get("runtimeEvidenceValidated") is True for row in family)
    except (KeyError, TypeError, ValueError):
        return False
