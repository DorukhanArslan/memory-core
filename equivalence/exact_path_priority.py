"""Actual exact-path candidates, keyword limits and hybrid priority composition.

The reference runs its unchanged matcher, SQLite path reader, private keyword
merge/limit owners and hybrid result owners. Python calls the corresponding
production APIs. Comparisons retain complete ordered rows without rounding.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import fields
import json
from pathlib import Path
import tempfile
from typing import Any


_PROFILE = (
    "Actual exact-path matcher and real SQLite unicode61 path candidates; separate authenticated "
    "compiled-runtime cases exercise original keyword merge/limit methods. Source pipeline "
    "cases compose actual path candidates and disjoint declared body candidates with the actual "
    "hybrid merger/selector, without claiming private manager premerge or full-manager execution. "
    "Full ordered row fields, scores, sources and ranges remain exact. "
    "Unicode matcher/substring/content inputs are exercised; tied path/id ordering uses "
    "printable ASCII. The existing engine Unicode collation diagnostic remains separate and "
    "uncredited. Full manager orchestration, annotation storage and alternate tokenizers "
    "remain unverified."
)
_NOW_MS = 1738368000000
_DAY_MS = 86_400_000


def _chunk(identifier: str, path: str = "memory/note.md", **fields_: Any) -> dict[str, Any]:
    return {"id": identifier, "path": path, "source": "memory", "startLine": 1,
            "endLine": 3, "text": f"source {identifier}", **fields_}


def _hit(identifier: str, path: str = "memory/note.md", **fields_: Any) -> dict[str, Any]:
    return {"id": identifier, "path": path, "source": "memory", "startLine": 1,
            "endLine": 3, "snippet": f"body {identifier}", "score": 0.6,
            "textScore": 0.4, "pathScore": 0.0, "exactPathSpecificity": 0,
            "hasBodyMatch": True, **fields_}


def _vector(identifier: str, path: str, **fields_: Any) -> dict[str, Any]:
    return {"id": identifier, "path": path, "source": "memory", "startLine": 1,
            "endLine": 3, "snippet": f"vector {identifier}", "vectorScore": 0.8, **fields_}


def build_exact_path_priority_cases() -> list[dict[str, Any]]:
    """Substantive identity, candidate admission and content-priority controls."""
    cases: list[dict[str, Any]] = []

    def add(name: str, kind: str, **arguments: Any) -> None:
        cases.append({
            "id": f"exact-path-{name}", "requirement": "retrieval.exact-path-priority",
            "operation": "exact-path-runtime" if kind in {"limit", "merge-limit"} else "exact-path-priority",
            "covers": [],
            "input": {"kind": kind, **deepcopy(arguments)}, "driverScope": _PROFILE,
            "normalizationPolicy": (
                "No output normalization, tolerance or field projection. Compare complete "
                "ordered JSON rows and all score/specificity/source/range/snippet fields. "
                "Private schema names and fixture database roots are not observable outputs. "
                "The actual merge then actual limiter owns final ordering in both languages; "
                "raw private-merge insertion order is not claimed."
            ),
        })

    paths = ["memory/note.md", "note.md", "other/note.txt", "memory/notes.md", "memory/note"]
    for name, query in (
        ("matcher-empty", ""), ("matcher-dot", "."), ("matcher-full", "memory/note.md"),
        ("matcher-basename", "note.md"), ("matcher-stem", "note"),
        ("matcher-partial-is-not-exact", "not"), ("matcher-directory-disallows-stem", "memory/note"),
        ("matcher-case-slashes-prefix", " ./MEMORY\\NOTE.MD "),
    ):
        add(name, "matcher", query=query, paths=paths)
    for name, query, candidates in (
        ("matcher-dotfiles", ".env", [".env", "memory/.env", "memory/.env.md", "memory/env.md"]),
        ("matcher-multiple-extensions", "note.v2", ["memory/note.v2.md", "memory/note.v2", "memory/note.md"]),
        ("matcher-nfc-equivalence", "memory/Cafe\u0301.md", ["memory/Café.md", "memory/Cafe\u0301.md"]),
        ("matcher-contextual-lowercase", "memory/ΟΣ.md", ["memory/ος.md", "memory/οσ.md"]),
        ("matcher-bom-trim", "\ufeffnote.md\ufeff", ["memory/note.md", "note.md"]),
        ("matcher-next-line-is-not-trim", "\u0085note.md\u0085", ["memory/note.md", "\u0085note.md\u0085"]),
        ("matcher-control-is-not-trim", "\x1cnote.md\x1c", ["memory/note.md", "\x1cnote.md\x1c"]),
        ("matcher-removes-one-dot-prefix", "././memory/note.md", ["memory/note.md", "./memory/note.md", "././memory/note.md"]),
    ):
        add(name, "matcher", query=query, paths=candidates)

    def merge(name: str, sets: list[list[dict[str, Any]]], query: str = "note", limit: int = 3) -> None:
        add(name, "merge-limit", resultSets=sets, query=query, limit=limit)

    merge("merge-empty", [[]])
    merge("merge-full-basename-stem-tiers", [[
        _hit("stem", "memory/note.md", score=1),
        _hit("basename", "other/note", score=0.5),
        _hit("full", "note", score=0.01),
    ]])
    merge("merge-only-original-query-claims-exact", [[
        _hit("fallback", "memory/note.md", exactPathSpecificity=3),
        _hit("body", "memory/body.md", score=0.9),
    ]], query="tell me about note")
    path_hit = _hit("same", score=0.9, textScore=0, pathScore=0.9, hasBodyMatch=False,
                    snippet="path first chunk")
    body_hit = _hit("same", score=0.2, textScore=0.1, pathScore=0, snippet="body authority")
    merge("merge-body-snippet-over-path", [[path_hit], [body_hit]])
    merge("merge-path-does-not-replace-body", [[body_hit], [path_hit]])
    merge("merge-duplicate-body-components", [[_hit("same", score=0.2, textScore=0.7)],
          [_hit("same", score=0.8, textScore=0.4, pathScore=0.9, snippet="longer body text")]])
    merge("merge-snippet-length-is-utf16", [[_hit("same", snippet="ab"),
                                             _hit("other", "memory/other.md", snippet="abc"),
                                             _hit("adversarial", "memory/adversarial.md", snippet="ab")],
          [_hit("same", snippet="😀"), _hit("other", "memory/other.md", snippet="😀x"),
           _hit("adversarial", "memory/adversarial.md", snippet="😀x")]])
    merge("merge-keeps-first-source-range-identity", [[_hit("same", startLine=8, endLine=12)],
          [_hit("same", "sessions/note.md", source="sessions", startLine=1, endLine=2)]])
    merge("merge-exact-path-only-uniform-baseline", [[
        _hit("one", "a/note.md", score=0.9, textScore=0, pathScore=0.9, hasBodyMatch=False),
        _hit("two", "b/note.md", score=0.1, textScore=0, pathScore=0.1, hasBodyMatch=False),
        _hit("partial", "c/note-draft.md", score=0.8, textScore=0, pathScore=0.8, hasBodyMatch=False),
    ]])
    merge("merge-exact-body-precedes-path-only", [[
        _hit("path", "a/note.md", score=1, textScore=0, pathScore=0, hasBodyMatch=False),
        _hit("body", "b/note.md", score=0.01),
    ]])
    merge("merge-ascii-path-line-id-ties", [[
        _hit("z", "memory/b.md"), _hit("b", "memory/a.md", startLine=5),
        _hit("c", "memory/a.md", startLine=2), _hit("a", "memory/a.md", startLine=2),
    ]], query="unmatched")

    cap_rows = [_hit(f"p{i:03d}", f"folder-{i:03d}/note.md", score=1,
                      textScore=0, pathScore=0, exactPathSpecificity=1, hasBodyMatch=False)
                for i in range(201)]
    add("limit-cap-keeps-all-chunks-of-retained-path", "limit", rows=[
        *cap_rows, _hit("extra", "folder-000/note.md", startLine=20, endLine=30, score=1,
                       textScore=0, pathScore=0, exactPathSpecificity=1, hasBodyMatch=False),
        _hit("partial", "memory/ordinary.md", score=0.8),
    ], limit=1)
    add("limit-body-window-plus-path-headroom", "limit", rows=[
        *[_hit(f"body{i}", f"b{i}/note.md", score=0.9-i*0.1, exactPathSpecificity=1)
          for i in range(4)],
        _hit("path", "a/note.md", score=1, textScore=0, exactPathSpecificity=1,
             hasBodyMatch=False), _hit("partial", "memory/ordinary.md", score=0.8),
    ], limit=2)
    add("limit-zero-keeps-path-only-headroom", "limit", rows=[
        _hit("body", exactPathSpecificity=1),
        _hit("path", "a/note.md", score=1, textScore=0, exactPathSpecificity=1,
             hasBodyMatch=False), _hit("partial", "memory/ordinary.md"),
    ], limit=0)
    add("limit-source-is-part-of-path-cap-key", "limit", rows=[
        *cap_rows[:199], _hit("session", cap_rows[0]["path"], source="sessions", score=1,
                            textScore=0, exactPathSpecificity=1, hasBodyMatch=False),
        cap_rows[199],
    ], limit=1)

    def search(name: str, chunks: list[dict[str, Any]], **arguments: Any) -> None:
        add(name, "path-search", **{"query": "note", "chunks": chunks, "limit": 3,
                                    "snippetMaxChars": 700, "ftsTokenizer": "unicode61",
                                    **arguments})

    simple = [_chunk("stem", "memory/note.md"), _chunk("partial", "memory/note-draft.md"),
              _chunk("body", "memory/unrelated.md", text="note appears only in body")]
    search("search-full-path", simple, query="memory/note.md")
    search("search-basename", simple, query="note.md")
    search("search-stem-and-partial", simple)
    search("search-empty-query", simple, query="")
    search("search-zero-limit", simple, limit=0)
    search("search-default-total-limit", simple, limit=1)
    search("search-explicit-exact-headroom", simple, limit=1, exactPathLimit=200)
    search("search-explicit-zero-exact-budget", simple, limit=3, exactPathLimit=0)
    search("search-query-distinct-from-exact-query", simple, query="unrelated", exactPathQuery="note")
    search("search-escaped-percent-is-literal", [_chunk("literal", "memory/100%note.md"),
           _chunk("other", "memory/100Xnote.md")], query="100%note.md")
    search("search-escaped-underscore-is-literal", [_chunk("literal", "memory/my_note.md"),
           _chunk("other", "memory/myXnote.md")], query="my_note.md")
    search("search-backslash-normalization", simple, query=".\\MEMORY\\NOTE.MD")
    search("search-unicode-nfc", [_chunk("unicode", "memory/Cafe\u0301.md")], query="Café.md")
    search("search-unicode-simplefold-long-s", [_chunk("unicode", "memory/Sdraft.md")], query="ſ")
    search("search-unicode-simplefold-ligature", [_chunk("unicode", "memory/ﬆdraft.md")], query="ﬅ")
    search("search-unicode-dotless-i-does-not-match-i", [_chunk("unicode", "memory/inside.md")], query="ı")
    search("search-bom-normalization", simple, query="\ufeffnote.md\ufeff")
    first_chunks = [
        _chunk("later", startLine=7, endLine=9), _chunk("z", startLine=1, endLine=5),
        _chunk("b", startLine=1, endLine=3), _chunk("a", startLine=1, endLine=3),
        _chunk("session", source="sessions", startLine=11, endLine=12),
    ]
    search("search-first-chunk-source-range-and-id", first_chunks, exactPathLimit=200)
    search("search-source-filter-before-candidate-limit", first_chunks, sources=["sessions"], limit=1)
    search("search-empty-sources-means-no-filter", first_chunks, sources=[], limit=2)
    for size in (0, 4, 5):
        search(f"search-snippet-utf16-nul-{size}", [_chunk("snippet", text="a😀\x00café tail")],
               snippetMaxChars=size)
    orphan_paths = [{"path": f"a{i:03d}/note.md", "source": "memory"} for i in range(201)]
    live = _chunk("live", "z/live/note.md")
    search("search-orphan-exact-paths-before-live-cap", [live],
           paths=[*orphan_paths, {"path": live["path"], "source": live["source"]}],
           exactPathLimit=200, limit=1)
    live_partial = _chunk("live", "z/note-live.md")
    search("search-orphan-lexical-path-before-live-limit", [live_partial],
           paths=[{"path": "a/note-draft.md", "source": "memory"},
                  {"path": live_partial["path"], "source": "memory"}], exactPathQuery="absent", limit=1)
    search("search-exact-flood-preserves-partial-budget", [
        *[_chunk(f"exact-{i:03d}", f"folder-{i:03d}/note.md") for i in range(202)],
        _chunk("partial", "z/note-draft.md"),
    ], limit=1, exactPathLimit=200)

    def pipeline(name: str, chunks: list[dict[str, Any]], **arguments: Any) -> None:
        add(name, "pipeline", **{"query": "note", "chunks": chunks, "limit": 3,
                                 "exactPathLimit": 200, "snippetMaxChars": 700,
                                 "ftsTokenizer": "unicode61", "bodyRows": [], "vector": [],
                                 "vectorWeight": 0.7, "textWeight": 0.3,
                                 "maxResults": 3, "minScore": 0.5, **arguments})

    pipeline("pipeline-filename-beats-body-only", simple,
             bodyRows=[_hit("body", "memory/unrelated.md", score=1, textScore=0.9)])
    pipeline("pipeline-strong-vector-does-not-cross-exact-tier", simple,
             vector=[_vector("body", "memory/unrelated.md", vectorScore=1)])
    pipeline("pipeline-body-exact-before-path-only", [_chunk("path", "a/note.md"),
             _chunk("body-first", "b/note.md"),
             _chunk("body-second", "b/note.md", startLine=7, endLine=9)],
             bodyRows=[_hit("body-second", "b/note.md", startLine=7, endLine=9,
                            score=0.01, textScore=0.01)])
    pipeline("pipeline-original-query-not-fallback-term", simple, query="note",
             exactPathQuery="tell me about note",
             bodyRows=[_hit("body", "memory/unrelated.md", score=1, textScore=0.9)])
    pipeline("pipeline-mmr-preserves-exact-tier", simple,
             vector=[_vector("body", "memory/unrelated.md", vectorScore=1)],
             mmr={"enabled": True, "lambda": 0})
    pipeline("pipeline-indexed-recency-within-exact-tier", [_chunk("old-path", "remote/a/note.md"),
             _chunk("old-body", "remote/a/note.md", startLine=7, endLine=9),
             _chunk("fresh", "remote/b/note.md")],
             bodyRows=[_hit("old-body", "remote/a/note.md", startLine=7, endLine=9,
                            score=0.9, textScore=0.9)],
             temporalDecay={"enabled": True}, nowMs=_NOW_MS,
             memorySourceMtimes={"remote/a/note.md": _NOW_MS - 90*_DAY_MS,
                                 "remote/b/note.md": _NOW_MS})
    pipeline("pipeline-project-public-confidence", [_chunk("active", "a/note.md"),
             _chunk("inactive", "b/note.md")],
             vector=[_vector("active", "a/note.md", importance=10, projectKey="alpha",
                             provenance={"originClass": "owner", "sessionKind": "interactive",
                                         "observedAt": _NOW_MS}),
                     _vector("inactive", "b/note.md", projectKey="beta")],
             activeProjectKeys=["alpha"], minScore=1.0)
    candidate_boundaries = {
        "search-default-total-limit", "search-explicit-exact-headroom",
        "search-explicit-zero-exact-budget", "search-query-distinct-from-exact-query",
        "search-first-chunk-source-range-and-id", "search-source-filter-before-candidate-limit",
        "search-empty-sources-means-no-filter", "search-snippet-utf16-nul-0",
        "search-snippet-utf16-nul-4", "search-snippet-utf16-nul-5",
        "search-orphan-exact-paths-before-live-cap", "search-orphan-lexical-path-before-live-limit",
        "search-exact-flood-preserves-partial-budget",
    }
    for case in cases:
        kind = case["input"]["kind"]
        name = case["id"].removeprefix("exact-path-")
        if kind != "limit":
            case["covers"].append("retrieval.exact-path-priority.outcomes")
        if (kind in {"limit", "pipeline"} or name in candidate_boundaries
                or kind == "merge-limit" and name != "merge-empty"):
            case["covers"].append("retrieval.exact-path-priority.boundaries")
    return cases


_KEYS = {"startLine": "start_line", "endLine": "end_line", "textScore": "text_score",
         "pathScore": "path_score", "exactPathSpecificity": "exact_path_specificity",
         "hasBodyMatch": "has_body_match", "vectorScore": "vector_score",
         "projectKey": "project_key"}


def _keyword_payload(hit: Any) -> dict[str, Any]:
    """Rename every genuine dataclass field; do not select a result subset."""
    reverse = {value: key for key, value in _KEYS.items()}
    return {reverse.get(field.name, field.name): getattr(hit, field.name) for field in fields(hit)}


def run_exact_path_priority(arguments: dict[str, Any], *,
                            evidence_directory: Path | None = None) -> dict[str, Any]:
    """Arrange actual storage and invoke production matcher/candidate/ranking APIs."""
    from memory_core.config import MemoryConfig
    from memory_core.flags import FeatureFlags
    from memory_core.index.hybrid import (
        HybridKeywordResult, HybridVectorResult, merge_hybrid_results, select_hybrid_search_results,
    )
    from memory_core.index.keyword_search import (
        KeywordHit, limit_keyword_search_hits, merge_keyword_search_hits, prepare_exact_path_matcher,
    )
    from memory_core.index.sqlite_store import SQLiteMemoryStore
    from memory_core.index.temporal_decay import TemporalDecayConfig

    value = deepcopy(arguments)
    kind = value["kind"]
    if kind == "matcher":
        matcher = prepare_exact_path_matcher(value["query"])
        return {"specificities": [matcher(path) for path in value["paths"]]}
    if kind not in {"merge-limit", "limit", "path-search", "pipeline"}:
        raise ValueError(f"Unsupported exact-path operation: {kind}")

    def construct(cls: type, row: dict[str, Any]) -> Any:
        return cls(**{_KEYS.get(key, key): item for key, item in row.items()})

    if kind in {"merge-limit", "limit"}:
        snapshots = []
        if kind == "limit":
            rows = [construct(KeywordHit, row) for row in value["rows"]]
            snapshots.append({"phase": "constructed", "rows": [_keyword_payload(row) for row in rows]})
        else:
            result_sets = [[construct(KeywordHit, row) for row in result_set]
                           for result_set in value["resultSets"]]
            snapshots.append({"phase": "constructed", "resultSets": [
                [_keyword_payload(row) for row in result_set] for result_set in result_sets
            ]})
            rows = merge_keyword_search_hits(result_sets, value["query"])
            snapshots.append({"phase": "merged", "rows": [_keyword_payload(row) for row in rows]})
        selected = limit_keyword_search_hits(rows, value["limit"])
        payload = [_keyword_payload(row) for row in selected]
        snapshots.append({"phase": "limited", "rows": payload})
        if evidence_directory is not None:
            evidence_directory.mkdir(parents=True, exist_ok=True)
            (evidence_directory / "python-raw.json").write_text(
                json.dumps(snapshots, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
            )
        return {"provider": "none", "rows": payload}

    if value.get("ftsTokenizer", "unicode61") != "unicode61":
        raise ValueError("Only the paired unicode61 path-index capability is verified")
    with tempfile.TemporaryDirectory(prefix="memory-exact-path-") as temporary:
        root = Path(temporary)
        store = SQLiteMemoryStore(MemoryConfig(
            workspace_dir=root, store_path=root / "index.sqlite",
            flags=FeatureFlags(vector_search=False),
        ), None)
        db = store.connect()
        try:
            for row in value["chunks"]:
                db.execute("INSERT INTO chunks(id,path,start_line,end_line,source,text,embedding) "
                           "VALUES (?,?,?,?,?,?,?)", (row["id"], row["path"], row["startLine"],
                           row["endLine"], row["source"], row["text"], "[]"))
            paths = value.get("paths")
            if paths is None:
                paths = [{"path": path, "source": source} for path, source in
                         dict.fromkeys((row["path"], row["source"]) for row in value["chunks"])]
            db.executemany("INSERT INTO paths_fts(path,source) VALUES (?,?)",
                           [(row["path"], row["source"]) for row in paths])
            db.commit()
            path_rows = store.search_path_candidates(
                value["query"], limit=value["limit"],
                exact_path_query=value.get("exactPathQuery"),
                exact_path_limit=value.get("exactPathLimit"),
                sources=set(value["sources"]) if value.get("sources") is not None else None,
                snippet_max_chars=value["snippetMaxChars"], db=db,
            )
            if kind == "path-search":
                return {"rows": [_keyword_payload(row) for row in path_rows]}
            original_query = value.get("exactPathQuery", value["query"])
            matcher = prepare_exact_path_matcher(original_query)
            body_rows = [construct(KeywordHit, {**row, "exactPathSpecificity": matcher(row["path"])})
                         for row in value["bodyRows"]]
            # This declared component composition invokes no private manager
            # premerge. Its body IDs are disjoint from path-projected IDs.
            keyword_rows = [*path_rows, *body_rows]
            vectors = [construct(HybridVectorResult, {**row, "exactPathSpecificity": matcher(row["path"])})
                       for row in value["vector"]]
            keywords = [HybridKeywordResult(
                id=row.id, path=row.path, start_line=row.start_line, end_line=row.end_line,
                source=row.source, snippet=row.snippet, text_score=row.text_score,
                ranking_score=row.score, path_score=row.path_score,
                exact_path_specificity=row.exact_path_specificity, has_body_match=row.has_body_match,
            ) for row in keyword_rows]
            decay = value.get("temporalDecay", {})
            mmr = value.get("mmr", {})
            merged = merge_hybrid_results(
                vector=vectors, keyword=keywords, vector_weight=value["vectorWeight"],
                text_weight=value["textWeight"], temporal_decay=TemporalDecayConfig(
                    enabled=decay.get("enabled", False), half_life_days=decay.get("halfLifeDays", 30),
                ), mmr_enabled=mmr.get("enabled", False), mmr_lambda=mmr.get("lambda", 0.7),
                now_ms=value.get("nowMs"), session_source_mtimes=value.get("sessionSourceMtimes"),
                memory_source_mtimes=value.get("memorySourceMtimes"),
                active_project_keys=value.get("activeProjectKeys"),
            )
            selected = select_hybrid_search_results(merged=merged, keyword=keywords,
                                                   max_results=value["maxResults"],
                                                   min_score=value["minScore"])
            return {"pathRows": [_keyword_payload(row) for row in path_rows],
                    "merged": [row.to_payload() for row in merged],
                    "selected": [row.to_payload() for row in selected]}
        finally:
            db.close()
