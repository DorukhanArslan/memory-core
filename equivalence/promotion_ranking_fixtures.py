"""Literal promotion ranking inputs, declared before protected comparisons."""
from copy import deepcopy


NOW_MS = 1775210460000
NOW_ISO = "2026-04-03T10:01:00.000Z"
RELEVANCE_ONLY = {"frequency": 0, "relevance": 1, "diversity": 0,
                  "recency": 0, "consolidation": 0, "conceptual": 0}


def _entry(key, **overrides):
    return {"key": key, "path": "memory/2026-04-01.md", "startLine": 1, "endLine": 1,
            "source": "memory", "snippet": "Durable cedar preference.", "recallCount": 3,
            "dailyCount": 0, "groundedCount": 0, "totalScore": 2.25, "maxScore": 0.75,
            "firstRecalledAt": "2026-04-01T10:00:00.000Z", "lastRecalledAt": NOW_ISO,
            "queryHashes": ["a", "b", "c"], "userQueryHashes": ["a", "b", "c"],
            "recallDays": ["2026-04-01", "2026-04-02", "2026-04-03"],
            "conceptTags": ["cedar", "tea"], **overrides}


def _query(label, **options):
    return {"label": label, "options": {"limit": 32, "minScore": 0,
            "minRecallCount": 0, "minUniqueQueries": 0, **options}}


def build_promotion_ranking_cases():
    profiles = []

    def add(name, entries, queries, phase=None, *, diagnostic=False):
        profiles.append({"id": "promotion-ranking-" + name,
            "requirement": "promotion.ranking-gates", "operation": "promotion-ranking-runtime",
            "covers": [], "driverScope": "Genuine original rank and SQLite store owners; real SDK rank over its JSON store. "
                "Whole ordered candidates and logical before/after state; full independent physical state remains raw. "
                "No provider, apply or host lifecycle claim.",
            "declaredDeviation": "Uncredited diagnostic input." if diagnostic else "Uncredited pending independent review.",
            "input": {"kind": "promotion-ranking", "nowMs": NOW_MS,
                "store": {"version": 1, "updatedAt": NOW_ISO,
                          "entries": {entry["key"]: deepcopy(entry) for entry in entries}},
                "phase": {"version": 1, "updatedAt": NOW_ISO, "entries": deepcopy(phase or {})},
                "queries": deepcopy(queries)}})

    add("signals-and-components", [
        _entry(f"signal-{n}", path=f"memory/2026-04-01-{n:02}.md", recallCount=n,
               totalScore=n * 0.75) for n in range(11)
    ], [_query("ungated"), _query("signals-3", minRecallCount=3), _query("score-075", minScore=.75)])
    add("custom-weights", [_entry("weighted")], [
        _query("relevance", weights=RELEVANCE_ONLY), _query("partial", weights={"relevance": 3}),
        _query("negative", weights={"frequency": -1, "recency": 2}),
        _query("zeros", weights={key: 0 for key in RELEVANCE_ONLY}),
        _query("negative-all", weights={key: -2 for key in RELEVANCE_ONLY}),
    ])
    add("score-boundary", [_entry("boundary")], [
        _query("below", weights=RELEVANCE_ONLY, minScore=.7499999999999999),
        _query("equal", weights=RELEVANCE_ONLY, minScore=.75),
        _query("above", weights=RELEVANCE_ONLY, minScore=.7500000000000001),
    ])
    add("frequency-boundary", [_entry("frequency", recallCount=2, totalScore=1.5)], [
        _query("equal", weights={**RELEVANCE_ONLY, "frequency": 1, "relevance": 0},
               minScore=.45815690999132613),
        _query("above", weights={**RELEVANCE_ONLY, "frequency": 1, "relevance": 0},
               minScore=.4581569099913262),
    ])
    add("diversity-and-age", [
        _entry("fresh", userQueryHashes=["a"]),
        _entry("aged", path="memory/2026-03-20.md", lastRecalledAt="2026-03-20T10:01:00.000Z"),
        _entry("older", path="memory/2026-03-19.md", lastRecalledAt="2026-03-19T10:01:00.000Z"),
    ], [_query("all"), _query("diversity", minUniqueQueries=3),
        _query("age-equal", maxAgeDays=14), _query("age-below", maxAgeDays=13),
        _query("half-life-1", recencyHalfLifeDays=1), _query("half-life-30", recencyHalfLifeDays=30)])
    add("tie-order-and-limit", [
        _entry("upper", path="memory/2026-04-01-A.md"),
        _entry("lower", path="memory/2026-04-01-a.md"),
        _entry("higher-recalls", path="memory/2026-04-01-z.md", recallCount=4, totalScore=3),
    ], [_query("all", weights=RELEVANCE_ONLY), _query("limited", weights=RELEVANCE_ONLY, limit=2),
        _query("none", limit=0)])
    add("origin-and-promoted-visibility", [
        _entry("owner", provenance={"originClass": "owner"}),
        _entry("agent", provenance={"originClass": "agent"}),
        _entry("system", provenance={"originClass": "system"}),
        _entry("untrusted", provenance={"originClass": "untrusted"}),
        _entry("promoted", promotedAt=NOW_ISO),
    ], [_query("hide-promoted"), _query("include-promoted", includePromoted=True)])
    add("path-and-transcript-gates", [
        _entry("daily"), _entry("long-term", path="MEMORY.md"),
        _entry("unrelated", path="random.md"), _entry("dreaming", path="memory/dreaming/2026-04-01.md"),
        _entry("daily-turn", snippet="User: Prefers cedar tea."),
        _entry("corpus", path="memory/.dreams/session-corpus/2026-04-01.md",
               snippet="User: Prefers cedar tea. Assistant: Recorded."),
    ], [_query("gates")])
    phase = {"boosted": {"key": "boosted", "lightHits": 3, "remHits": 2,
                         "lastLightAt": NOW_ISO, "lastRemAt": "2026-03-20T10:01:00.000Z"}}
    add("phase-boost", [_entry("boosted")], [_query("boost"), _query("custom", weights=RELEVANCE_ONLY)], phase)
    add("multiline-store-diagnostic", [_entry("multiline", snippet="Durable cedar\npreference.")],
        [_query("rank")], diagnostic=True)
    add("equal-path-stability-diagnostic", [_entry("z"), _entry("a"), _entry("b")],
        [_query("rank", weights=RELEVANCE_ONLY)], diagnostic=True)
    add("old-phase-diagnostic", [_entry("old-phase")], [_query("rank")], {
        "old-phase": {"key": "old-phase", "lightHits": 3, "remHits": 2,
                      "lastLightAt": "2026-02-01T10:01:00.000Z", "lastRemAt": "2026-02-01T10:01:00.000Z"}},
        diagnostic=True)
    add("limit-boundaries", [_entry("first"), _entry("second", path="memory/2026-04-02.md")], [
        _query("negative", limit=-1), _query("fraction-below-one", limit=.5),
        _query("fraction-above-one", limit=1.9), _query("unbounded-null", limit=None),
        _query("unbounded-boolean", limit=True),
    ])
    return profiles
