"""Stored annotation and importance/project ranking comparisons.

The adapters call the real preparation, publication, metadata-reader and search
owners. Public result payloads are retained without projection or rounding.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
from typing import Any


_NOW_MS = 1738368000000
_DAY_MS = 86_400_000
_PROVENANCE = {"originClass": "owner", "sessionKind": "interactive", "observedAt": _NOW_MS}
_PROFILE = (
    "Actual importance/project owners and complete hybrid results, original annotation "
    "preparation, real SQLite metadata reads, and separately authenticated provider-none "
    "public stored searches after actual indexing. Public rows retain every returned field "
    "and their order. Runtime temporal decay is explicitly disabled; fixed-clock source "
    "hybrid cases exercise modifier order with decay/MMR. Path ties use printable ASCII; "
    "Unicode content and annotations remain exact. General ICU, alternate tokenizers, "
    "accelerated KNN and automatic trigger/project candidate admission remain unverified."
)
_POLICY = (
    "No public result normalization, field projection, score rounding or tolerance. The "
    "declared published SQL view retains source/path/range/text, recall annotations and all "
    "provenance fields, preserving multiplicity and ordering by actual SQL. Private chunk "
    "IDs and update clocks are outside that logical view but remain in both raw diagnostics. "
    "Preparation maps private SDK chunk identity fields to the original preparation payload; "
    "optional native fields remain absent when their SDK owner records no value. In the "
    "declared text-only preparation profile, embeddingInput.text carries the actual SDK "
    "chunk text passed as a string to embed_documents; the native owner wraps that same "
    "argument in its private text-input object. Multimodal and provider-enforcement inputs "
    "are not claimed."
)


def _result(identifier: str, score: float = 0.8, **fields: Any) -> dict[str, Any]:
    return {"path": f"memory/{identifier}.md", "startLine": 1, "endLine": 2,
            "score": score, "vectorScore": score, "textScore": 0.0,
            "snippet": f"cedar {identifier}", "source": "memory", **fields}


def _vector(identifier: str, score: float = 0.8, **fields: Any) -> dict[str, Any]:
    result = _result(identifier, score, **fields)
    result.pop("score")
    result.pop("textScore")
    return {"id": identifier, **result}


def _chunk(identifier: str, **fields: Any) -> dict[str, Any]:
    return {"id": identifier, "path": f"memory/{identifier}.md", "source": "memory",
            "startLine": 1, "endLine": 2, "text": f"cedar {identifier}", **fields}


def _recall(identifier: str, **fields: Any) -> dict[str, Any]:
    return {"chunkId": identifier, "importance": None, "triggers": None,
            "projectKey": None, **fields}


def _provenance(identifier: str, **fields: Any) -> dict[str, Any]:
    return {"chunkId": identifier, **_PROVENANCE, "supersedesKey": None, **fields}


def build_importance_project_cases() -> list[dict[str, Any]]:
    """Bounded annotation-to-public-search and ranking-boundary comparisons."""
    cases: list[dict[str, Any]] = []

    def add(name: str, kind: str, **arguments: Any) -> None:
        cases.append({
            "id": f"importance-project-{name}", "requirement": "retrieval.importance-project",
            "operation": "importance-project-runtime" if kind == "stored-search" else "importance-project",
            "covers": [], "input": {"kind": kind, **deepcopy(arguments)},
            "driverScope": _PROFILE, "normalizationPolicy": _POLICY,
        })

    modifiers = [
        ("modifiers-empty", [], {}),
        ("modifiers-absent-and-null", [_result("absent"), _result("null", importance=None,
         triggers=None, projectKey=None, provenance=None)], {}),
        ("modifiers-importance-floor-clamp", [
            _result(str(i), importance=value) for i, value in enumerate((-3, 0, 1, 1.99, 5, 9.9, 10, 100))
        ], {}),
        ("modifiers-importance-zero-score", [_result("zero", 0, importance=10),
         _result("negative", -0.2, importance=1)], {}),
        ("modifiers-project-no-active", [_result("plain"), _result("active", projectKey="alpha"),
         _result("invalid", projectKey="alpha; !invalid-project-annotation")], {}),
        ("modifiers-project-empty-active", [_result("active", projectKey="alpha"),
         _result("invalid", projectKey="!invalid-project-annotation")], {"activeProjectKeys": []}),
        ("modifiers-active-inactive-unscoped", [_result("plain"),
         _result("active", projectKey="alpha"), _result("inactive", projectKey="beta")],
         {"activeProjectKeys": ["alpha"]}),
        ("modifiers-all-project-keys-required", [_result("one", projectKey="alpha"),
         _result("both", projectKey="alpha; beta"), _result("other", projectKey="gamma")],
         {"activeProjectKeys": ["alpha"]}),
        ("modifiers-host-keys-are-exact", [_result("stored", projectKey=" alpha ; beta ")],
         {"activeProjectKeys": [" alpha ", "beta"]}),
        ("modifiers-stored-key-trim", [_result("stored", projectKey=" alpha ; beta ")],
         {"activeProjectKeys": ["alpha", "beta", "alpha"]}),
        ("modifiers-empty-stored-keys", [_result("empty", projectKey=""),
         _result("spaces", projectKey=" ; \t ; "), _result("null", projectKey=None)],
         {"activeProjectKeys": ["alpha"]}),
        ("modifiers-retain-full-metadata", [_result("full", importance=8, projectKey="alpha",
         triggers="Çay; cedar 😀\x00", provenance={**_PROVENANCE, "supersedesKey": "old-entry"})],
         {"activeProjectKeys": ["alpha"]}),
    ]
    for name, results, options in modifiers:
        add(name, "modifiers", results=results, **options)

    def hybrid(name: str, vector: list[dict[str, Any]], **options: Any) -> None:
        add(name, "hybrid", **{"vector": vector, "keyword": [], "vectorWeight": 0.7,
                               "textWeight": 0.3, **options})

    hybrid("hybrid-importance-changes-order", [_vector("low", 0.9, importance=1),
           _vector("high", 0.8, importance=10)])
    hybrid("hybrid-active-project-changes-order", [_vector("inactive", 0.9, projectKey="beta"),
           _vector("active", 0.8, projectKey="alpha")], activeProjectKeys=["alpha"])
    hybrid("hybrid-invalid-excluded-before-window", [_vector("invalid", 1,
           projectKey="!invalid-project-annotation"), _vector("valid", 0.6, importance=10)])
    hybrid("hybrid-exact-tier-beats-importance", [_vector("ordinary", 1, importance=10),
           _vector("exact", 0.01, importance=1, exactPathSpecificity=3)])
    hybrid("hybrid-project-exact-public-confidence", [_vector("active", 0.2, importance=10,
           projectKey="alpha", exactPathSpecificity=3), _vector("inactive", 0.9,
           projectKey="beta", exactPathSpecificity=3)], activeProjectKeys=["alpha"])
    hybrid("hybrid-decay-before-importance-project", [_vector("old", 1,
           path="memory/2025-01-01.md", importance=10, projectKey="alpha"),
           _vector("fresh", 0.7, path="memory/2025-02-01.md", importance=1, projectKey="beta")],
           activeProjectKeys=["alpha"], temporalDecay={"enabled": True, "halfLifeDays": 30},
           nowMs=_NOW_MS)
    hybrid("hybrid-mmr-after-modifiers", [_vector("one", 0.95, snippet="cedar tea preference",
           importance=1, projectKey="beta"), _vector("two", 0.9, snippet="cedar tea preference",
           importance=10, projectKey="alpha"), _vector("three", 0.8, snippet="distant mountain",
           importance=8, projectKey="alpha")], activeProjectKeys=["alpha"],
           mmr={"enabled": True, "lambda": 0.5})
    hybrid("hybrid-overlap-retains-authoritative-annotations", [_vector("same", importance=10,
           projectKey="alpha", triggers="source trigger", provenance=_PROVENANCE)], keyword=[{
               "id": "same", "path": "memory/same.md", "source": "memory", "startLine": 1,
               "endLine": 2, "snippet": "keyword text", "textScore": 0.8,
               "importance": 1, "projectKey": "beta", "triggers": "keyword trigger",
               "provenance": {**_PROVENANCE, "originClass": "untrusted"},
           }], activeProjectKeys=["alpha"])

    def prepare(name: str, content: str, **options: Any) -> None:
        add(name, "prepare", **{
            "entry": {"path": "MEMORY.md", "mtimeMs": _NOW_MS}, "source": "memory",
            "content": content, "pathClassification": {"curatedRoot": True, "originClass": "agent"},
            "chunking": {"tokens": 400, "overlap": 80}, "hardMaxInputTokens": 8192, **options,
        })

    prepare("prepare-empty", "")
    prepare("prepare-neutral-entry", "# Memory\n- Cedar tea preference.\n")
    prepare("prepare-all-annotations", "- Cedar tea. <!-- importance: 10 --> <!-- trigger: tea, cedar --> <!-- project: alpha -->\n")
    prepare("prepare-importance-valid-boundaries", "- One. <!-- importance: 1 -->\n- Ten. <!-- importance: 10 -->\n")
    prepare("prepare-importance-invalid-values", "- Invalid. <!-- importance: 0 --> <!-- importance: 11 --> <!-- importance: -1 --> <!-- importance: 1.5 -->\n")
    prepare("prepare-importance-maximum", "- Highest. <!-- importance: 3 --> <!-- importance: 9 --> <!-- importance: 0008 -->\n")
    prepare("prepare-trigger-order-deduplication", "- Fact. <!-- trigger: tea, cedar; tea; Çay 😀 --> <!-- trigger: cedar; second -->\n")
    prepare("prepare-suffix-requires-closing-marker", "- Fact. <!-- importance: 9 --> after text\n- Next. <!-- trigger: valid -->\n")
    prepare("prepare-multiple-project-normalization", "- Fact. <!-- project: GitHub.COM/Team/Repo; path:/Workspace/Repo; alpha -->\n")
    prepare("prepare-invalid-project-key-fails-closed", "- Fact. <!-- project: alpha;;beta -->\n")
    prepare("prepare-unclosed-project-fails-closed", "- Fact. <!-- project: alpha\n")
    prepare("prepare-user-file-project-excluded", "- Persona. <!-- importance: 8 --> <!-- trigger: persona --> <!-- project: alpha -->\n",
            entry={"path": "USER.md", "mtimeMs": _NOW_MS})
    prepare("prepare-noncurated-project-only", "A note. <!-- importance: 9 --> <!-- trigger: ignored --> <!-- project: alpha -->\n",
            entry={"path": "memory/note.md", "mtimeMs": _NOW_MS},
            pathClassification={"curatedRoot": False, "originClass": "agent"})
    prepare("prepare-fragments-inherit-entry-annotations", "- " + "cedar preference " * 20
            + "<!-- importance: 9 --> <!-- trigger: long fact --> <!-- project: alpha -->\n",
            chunking={"tokens": 8, "overlap": 2})

    def recall(name: str, chunks: list[dict[str, Any]], **options: Any) -> None:
        add(name, "recall", **{"chunks": chunks, "recall": [], "provenance": [],
                               "ids": [row["id"] for row in chunks], **options})

    recall("recall-empty-request", [_chunk("one")], ids=[])
    recall("recall-complete", [_chunk("one")], recall=[_recall("one", importance=9,
           triggers="cedar; tea", projectKey="alpha")], provenance=[_provenance("one")])
    recall("recall-missing-chunk-is-excluded", [_chunk("one")], ids=["missing", "one"])
    recall("recall-live-missing-metadata-is-neutral", [_chunk("one")], provenance=[_provenance("one")])
    recall("recall-live-missing-provenance-is-retained", [_chunk("one")],
           recall=[_recall("one", importance=8, projectKey="alpha")])
    recall("recall-duplicate-request-ids", [_chunk("one"), _chunk("two")],
           ids=["two", "one", "two", "one"], recall=[_recall("one", importance=1), _recall("two", importance=10)])
    recall("recall-null-annotations", [_chunk("one")], recall=[_recall("one")])
    recall("recall-raw-annotation-whitespace-retained", [_chunk("one")],
           recall=[_recall("one", triggers="  tea ; cedar  ", projectKey=" alpha ; beta ")])
    recall("recall-invalid-provenance-is-omitted", [_chunk("good"), _chunk("origin"), _chunk("kind")],
           ignoreChecks=True, provenance=[_provenance("good"), _provenance("origin", originClass="invalid"),
                                          _provenance("kind", sessionKind="invalid")])
    recall("recall-blank-supersedes-is-omitted", [_chunk("one")],
           provenance=[_provenance("one", supersedesKey=" \t ")])
    recall("recall-nonblank-supersedes-bytes-retained", [_chunk("one")],
           provenance=[_provenance("one", supersedesKey=" old-key ")])
    recall("recall-shared-path-distinct-source-identities", [_chunk("memory", path="same.md"),
           _chunk("session", path="same.md", source="sessions")], ids=["session", "memory"],
           recall=[_recall("memory", importance=10), _recall("session", importance=1)],
           provenance=[_provenance("memory"), _provenance("session", originClass="untrusted", sessionKind="cron")])

    def stored(name: str, files: dict[str, str], steps: list[dict[str, Any]]) -> None:
        add(name, "stored-search", files=files, mtimeMs=_NOW_MS,
            temporalDecay={"enabled": False, "halfLifeDays": 30}, steps=steps)

    def search(query: str = "cedar", **options: Any) -> dict[str, Any]:
        return {"query": query, "maxResults": 5, "minScore": 0, **options}

    stored("stored-neutral-preservation", {"MEMORY.md": "- Cedar preference.\n"}, [search()])
    stored("stored-importance-affects-ranking", {"MEMORY.md":
           "- Cedar preference. <!-- importance: 1 -->\n- Cedar preference. <!-- importance: 10 -->\n"},
           [search()])
    stored("stored-active-inactive-and-unscoped", {"MEMORY.md":
           "- Cedar preference. <!-- project: alpha -->\n- Cedar preference. <!-- project: beta -->\n- Cedar preference.\n"},
           [search(activeProjectKeys=["alpha"]), search(activeProjectKeys=["beta"])])
    stored("stored-invalid-project-excluded-without-active", {"MEMORY.md":
           "- Cedar invalid. <!-- project: alpha;;beta -->\n- Cedar valid. <!-- project: alpha -->\n"},
           [search(), search(activeProjectKeys=["alpha"])])
    stored("stored-multiple-project-key-gate", {"MEMORY.md":
           "- Cedar one. <!-- project: alpha -->\n- Cedar both. <!-- project: alpha; beta -->\n"},
           [search(activeProjectKeys=["alpha"]), search(activeProjectKeys=["alpha", "beta"])])
    stored("stored-basename-project-confidence", {
           "memory/a/note.md": "Cedar preference. <!-- project: alpha -->\n",
           "memory/b/note.md": "Cedar preference. <!-- project: beta -->\n"},
           [search("note.md", activeProjectKeys=["alpha"]), search("note.md", activeProjectKeys=["beta"])])
    stored("stored-annotations-update-and-reopen", {"MEMORY.md":
           "- Cedar preference. <!-- importance: 1 --> <!-- project: beta -->\n"},
           [search(activeProjectKeys=["alpha"]), search(activeProjectKeys=["alpha"], reopen=True,
            write={"MEMORY.md": "- Cedar preference. <!-- importance: 10 --> <!-- project: alpha -->\n"}),
            search(activeProjectKeys=["alpha"], reopen=True)])
    stored("stored-triggers-provenance-and-user-scope", {
           "MEMORY.md": "- Cedar preference. <!-- importance: 9 --> <!-- trigger: tea, Çay 😀 --> <!-- project: alpha -->\n",
           "USER.md": "- Cedar persona. <!-- importance: 8 --> <!-- trigger: persona --> <!-- project: beta -->\n"},
           [search(activeProjectKeys=["alpha"]), search(activeProjectKeys=["beta"], minScore=0.5)])
    stored_boundaries = {
        "stored-importance-affects-ranking", "stored-active-inactive-and-unscoped",
        "stored-invalid-project-excluded-without-active", "stored-multiple-project-key-gate",
        "stored-basename-project-confidence", "stored-annotations-update-and-reopen",
    }
    for case in cases:
        name = case["id"].removeprefix("importance-project-")
        kind = case["input"]["kind"]
        if name == "modifiers-empty":
            continue
        case["covers"].append("retrieval.importance-project.outcomes")
        if kind in {"modifiers", "hybrid"} or name in stored_boundaries:
            case["covers"].append("retrieval.importance-project.boundaries")
    return cases


_KEYS = {"startLine": "start_line", "endLine": "end_line", "vectorScore": "vector_score",
         "textScore": "text_score", "projectKey": "project_key", "exactPathSpecificity": "exact_path_specificity",
         "hasBodyMatch": "has_body_match", "rankingScore": "ranking_score", "pathScore": "path_score"}


def _construct(cls: type, row: dict[str, Any]) -> Any:
    return cls(**{_KEYS.get(key, key): value for key, value in row.items()})


def _logical_published(store: Any) -> list[dict[str, Any]]:
    with store.connect() as db:
        rows = db.execute(
            "SELECT c.path,c.source,c.start_line,c.end_line,c.text,r.importance,r.triggers,r.project_key,"
            "p.origin_class,p.session_kind,p.observed_at,p.supersedes_key FROM chunks c "
            "LEFT JOIN memory_index_chunk_recall_metadata r ON r.chunk_id=c.id "
            "LEFT JOIN memory_index_chunk_provenance p ON p.chunk_id=c.id "
            "ORDER BY c.source,c.path,c.start_line,c.end_line,c.text"
        ).fetchall()
    return [{"path": r[0], "source": r[1], "startLine": r[2], "endLine": r[3], "text": r[4],
             "importance": r[5], "triggers": r[6], "projectKey": r[7], "provenance": {
                 "originClass": r[8], "sessionKind": r[9], "observedAt": r[10], "supersedesKey": r[11],
             }} for r in rows]


def run_importance_project(arguments: dict[str, Any], *, evidence_directory: Path | None = None) -> dict[str, Any]:
    """Arrange declared fixtures and invoke real production owners."""
    from memory_core.config import MemoryConfig
    from memory_core.flags import FeatureFlags
    from memory_core.index.hybrid import (
        HybridKeywordResult, HybridResult, HybridVectorResult, apply_importance_multiplier,
        apply_project_ranking, merge_hybrid_results,
    )
    from memory_core.index.temporal_decay import TemporalDecayConfig
    from memory_core.index.sqlite_store import SQLiteMemoryStore

    value = deepcopy(arguments)
    kind = value["kind"]
    if kind == "modifiers":
        rows = [_construct(HybridResult, row) for row in value["results"]]
        importance = apply_importance_multiplier(rows)
        projects = apply_project_ranking(rows, value.get("activeProjectKeys"))
        ranked = apply_project_ranking(importance, value.get("activeProjectKeys"))
        return {"importanceOnly": [row.to_payload() for row in importance],
                "projectOnly": [row.to_payload() for row in projects],
                "results": [row.to_payload() for row in ranked]}
    if kind == "hybrid":
        decay, mmr = value.get("temporalDecay", {}), value.get("mmr", {})
        rows = merge_hybrid_results(
            vector=[_construct(HybridVectorResult, row) for row in value["vector"]],
            keyword=[_construct(HybridKeywordResult, row) for row in value["keyword"]],
            vector_weight=value["vectorWeight"], text_weight=value["textWeight"],
            active_project_keys=value.get("activeProjectKeys"),
            temporal_decay=TemporalDecayConfig(enabled=decay.get("enabled", False),
                                              half_life_days=decay.get("halfLifeDays", 30)),
            mmr_enabled=mmr.get("enabled", False), mmr_lambda=mmr.get("lambda", 0.7),
            now_ms=value.get("nowMs"), session_source_mtimes=value.get("sessionSourceMtimes"),
            memory_source_mtimes=value.get("memorySourceMtimes"),
        )
        return {"merged": [row.to_payload() for row in rows]}
    if kind == "prepare":
        from memory_core.index.preparation import prepare_chunk_metadata
        from memory_core.index.sqlite_store import IndexSourceSnapshot, _text_hash

        entry, content = value["entry"], value["content"]
        if any(key in entry for key in ("lineMap",)) or "provider" in value or "cutoffLine" in value:
            raise ValueError("Importance preparation does not verify embedding enforcement or session remapping")
        snapshot = IndexSourceSnapshot(entry["path"], value["source"], _text_hash(content), content,
                                       entry["mtimeMs"], len(content.encode("utf-8")), canonical_path=entry["path"])
        chunks = SQLiteMemoryStore._prepare_source_chunks(snapshot, value["chunking"]["tokens"],
                                                          value["chunking"]["overlap"])
        prepared = []
        for chunk in chunks:
            provenance, recall = prepare_chunk_metadata(
                path=entry["path"], source=value["source"], text=content, mtime_ms=entry["mtimeMs"],
                chunk=chunk, line_provenance=entry.get("lineProvenance"),
                classification=value["pathClassification"],
            )
            row = {"startLine": chunk.start_line, "endLine": chunk.end_line,
                   "text": chunk.text, "hash": _text_hash(chunk.text),
                   "embeddingInput": {"text": chunk.text}, "provenance": {
                       "originClass": provenance.origin_class, "sessionKind": provenance.session_kind,
                       "observedAt": provenance.observed_at,
                   }, "importance": recall.importance, "triggers": recall.triggers,
                   "projectKey": recall.project_key}
            if provenance.supersedes_key is not None:
                row["provenance"]["supersedesKey"] = provenance.supersedes_key
            if chunk.entry_start_line is not None:
                row["entryStartLine"] = chunk.entry_start_line
                row["entryEndLine"] = chunk.entry_end_line
            prepared.append(row)
        return {"prepared": {**({"contentHash": _text_hash(content)} if value["source"] == "memory" else {}),
                             "chunks": prepared}}
    if kind not in {"recall", "stored-search"}:
        raise ValueError(f"Unsupported importance/project operation: {kind}")

    with tempfile.TemporaryDirectory(prefix="memory-importance-project-") as temporary:
        root = Path(temporary)
        config = MemoryConfig(workspace_dir=root, store_path=root / "index.sqlite", flags=FeatureFlags(
            vector_search=False, text_search=True, mmr=False, temporal_decay=False,
        ))
        store = SQLiteMemoryStore(config, None)
        if kind == "recall":
            db = store.connect()
            try:
                if value.get("ignoreChecks"):
                    db.execute("PRAGMA ignore_check_constraints=ON")
                for row in value["chunks"]:
                    db.execute("INSERT INTO chunks(id,path,start_line,end_line,source,text,embedding) VALUES (?,?,?,?,?,?,?)",
                               (row["id"], row["path"], row["startLine"], row["endLine"], row["source"], row["text"], "[]"))
                for row in value["recall"]:
                    db.execute("INSERT INTO memory_index_chunk_recall_metadata VALUES (?,?,?,?)",
                               (row["chunkId"], row["importance"], row["triggers"], row["projectKey"]))
                for row in value["provenance"]:
                    db.execute("INSERT INTO memory_index_chunk_provenance VALUES (?,?,?,?,?)",
                               (row["chunkId"], row["originClass"], row["sessionKind"],
                                row["observedAt"], row["supersedesKey"]))
                db.commit()
                return {"rows": list(store.read_recall_metadata(value["ids"], db=db).values())}
            finally:
                db.close()

        from memory_core.workspace import MemoryWorkspace

        if value.get("temporalDecay", {}).get("enabled"):
            raise ValueError("Stored-search fixtures use clock-neutral ranking; fixed-clock hybrid cases verify decay")

        def write(files: dict[str, str]) -> None:
            for relative, text in files.items():
                path = Path(relative)
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError("Workspace files must remain in their private fixture root")
                filename = root / path
                filename.parent.mkdir(parents=True, exist_ok=True)
                filename.write_text(text, encoding="utf-8")
                os.utime(filename, ns=(value["mtimeMs"] * 1_000_000, value["mtimeMs"] * 1_000_000))

        workspace = MemoryWorkspace(root)
        write(value["files"])
        store.reindex(workspace)
        steps, raw = [], []
        for step in value["steps"]:
            write(step.get("write", {}))
            for relative in step.get("remove", []):
                path = Path(relative)
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError("Workspace files must remain in their private fixture root")
                (root / path).unlink()
            if step.get("reopen"):
                store = SQLiteMemoryStore(config, None)
            if step.get("write") or step.get("remove") or step.get("sync"):
                store.reindex(workspace)
            rows = store.search(step["query"], max_results=step["maxResults"], min_score=step["minScore"],
                                active_project_keys=step.get("activeProjectKeys"),
                                sources=set(step["sources"]) if step.get("sources") is not None else None)
            result = {"rows": [row.to_payload() for row in rows], "published": _logical_published(store)}
            steps.append(result)
            raw.append({"query": deepcopy(step), "results": deepcopy(result),
                        "published": store.read_published_index()})
        if evidence_directory is not None:
            evidence_directory.mkdir(parents=True, exist_ok=True)
            (evidence_directory / "python-raw.json").write_text(
                json.dumps(raw, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8",
            )
        return {"provider": "none", "steps": steps}
