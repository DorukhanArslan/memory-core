"""Stored recall annotations and trusted project context reach real retrieval owners."""
from __future__ import annotations

import dataclasses
import sqlite3

import pytest

from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.index.hybrid import (
    HYBRID_METADATA_MISSING,
    HybridResult,
    HybridVectorResult,
    apply_importance_multiplier,
    apply_project_ranking,
)
from memory_core.index.identity import INDEX_SOURCES_TABLE
from memory_core.index.keyword_search import KeywordHit
from memory_core.index.publication import CHUNK_PROVENANCE_TABLE, CHUNK_RECALL_TABLE
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.workspace import MemoryWorkspace


class ConstantEmbedding:
    provider_id = "importance-unit"
    model = "constant"

    def embed_documents(self, texts):
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text):
        return [1.0, 0.0]


def make_store(tmp_path, *, mode="keyword", text=None):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "MEMORY.md").write_text(text or (
        "- comet alpha <!-- importance: 10 --> <!-- trigger: launch, release --> "
        "<!-- project: alpha -->\n"
        "- comet beta <!-- importance: 1 --> <!-- project: beta -->\n"
    ), encoding="utf-8")
    store = SQLiteMemoryStore(MemoryConfig(
        workspace_dir=root, store_path=tmp_path / "index.sqlite",
        flags=FeatureFlags(vector_search=mode != "keyword", text_search=mode != "vector",
                           temporal_decay=False, mmr=False),
    ), ConstantEmbedding() if mode != "keyword" else None)
    store.reindex(MemoryWorkspace(root))
    return store


def keyword(identifier, **fields):
    return KeywordHit(identifier, "MEMORY.md", 1, 1, "memory", "comet", 0.8, 0.4, **fields)


@pytest.mark.parametrize("mode", ["keyword", "vector", "hybrid"])
def test_persisted_annotations_and_provenance_survive_public_search(tmp_path, mode):
    store = make_store(tmp_path, mode=mode)
    with store.connect() as db:
        persisted = db.execute(f"SELECT importance,triggers,project_key FROM {CHUNK_RECALL_TABLE} "
                               "ORDER BY importance DESC").fetchall()
    assert persisted == [(10, "launch; release", "alpha"), (1, None, "beta")]
    rows = [entry.to_payload() for entry in store.search("comet", active_project_keys=["alpha"])]
    assert [entry["projectKey"] for entry in rows] == ["alpha", "beta"]
    assert rows[0]["importance"] == 10 and rows[0]["triggers"] == "launch; release"
    assert rows[0]["provenance"]["originClass"] == "agent"
    assert "sourceMtime" not in rows[0]
    assert ("vectorScore" in rows[0]) == (mode == "hybrid")
    assert ("textScore" in rows[0]) == (mode != "vector")
    assert ("id" in rows[0]) == (mode == "vector")


def test_project_context_can_change_order_without_changing_stored_annotations(tmp_path):
    store = make_store(tmp_path, text=(
        "- comet alpha <!-- importance: 8 --> <!-- project: alpha -->\n"
        "- comet beta <!-- importance: 8 --> <!-- project: beta -->\n"
    ))
    alpha = store.search("comet", active_project_keys=["alpha"])
    beta = store.search("comet", active_project_keys=["beta"])
    assert [item.project_key for item in alpha] == ["alpha", "beta"]
    assert [item.project_key for item in beta] == ["beta", "alpha"]
    with store.connect() as db:
        assert {row[0] for row in db.execute(f"SELECT project_key FROM {CHUNK_RECALL_TABLE}")} == {
            "alpha", "beta",
        }


def test_invalid_project_annotation_is_excluded_even_without_active_projects(tmp_path):
    store = make_store(tmp_path, text=(
        "- comet good <!-- importance: 1 -->\n"
        "- comet bad <!-- importance: 10 --> <!-- project: alpha; -->\n"
    ))
    with store.connect() as db:
        assert db.execute(f"SELECT 1 FROM {CHUNK_RECALL_TABLE} WHERE project_key=?",
                          ("!invalid-project-annotation",)).fetchone()
    assert [item.snippet for item in store.search("comet")] == ["- comet good"]


def test_raw_metadata_reader_keeps_live_chunks_when_optional_owner_rows_are_missing(tmp_path):
    store = make_store(tmp_path)
    with store.connect() as db:
        db.execute("INSERT INTO chunks VALUES (?,?,?,?,?,?,?)",
                   ("unowned", "memory/other.md", 1, 1, "memory", "comet", "[]"))
        result = store.read_recall_metadata(["missing", "unowned", "unowned"], db=db)
    assert result == {"unowned": {"id": "unowned", "importance": None,
                                  "triggers": None, "project_key": None}}


def test_enrichment_filters_missing_chunks_and_preserves_preexisting_optional_values(tmp_path):
    store = make_store(tmp_path)
    with store.connect() as db:
        identifier, = db.execute("SELECT id FROM chunks ORDER BY start_line LIMIT 1").fetchone()
        db.execute(f"UPDATE {CHUNK_RECALL_TABLE} SET importance=NULL,triggers='  ',project_key=NULL")
        db.execute(f"DELETE FROM {CHUNK_PROVENANCE_TABLE}")
        rows = store.attach_recall_metadata([
            keyword(identifier, importance=9, triggers="existing", project_key=None,
                    provenance={"already": "present"}), keyword("missing"),
        ], db=db, include_memory_mtimes=False)
    assert len(rows) == 1
    assert (rows[0].importance, rows[0].triggers, rows[0].project_key) == (9, "existing", None)
    assert rows[0].provenance == {"already": "present"}
    assert "sourceMtime" not in rows[0].to_payload()


@pytest.mark.parametrize("origin,kind,observed,supersedes,expected", [
    ("owner", "interactive", 0, " original ",
     {"originClass": "owner", "sessionKind": "interactive", "observedAt": 0,
      "supersedesKey": " original "}),
    ("system", "cron", 12.5, "\ufeff ",
     {"originClass": "system", "sessionKind": "cron", "observedAt": 12.5}),
    ("not-an-origin", "interactive", 1, None, None),
    ("owner", "not-a-session", 1, None, None),
    ("owner", "interactive", "1", None, None),
])
def test_provenance_reader_validates_closed_types_and_retains_original_supersedes_bytes(
    tmp_path, origin, kind, observed, supersedes, expected,
):
    store = make_store(tmp_path)
    with sqlite3.connect(":memory:") as db:
        db.executescript("CREATE TABLE chunks(id TEXT PRIMARY KEY);"
                         f"CREATE TABLE {CHUNK_RECALL_TABLE}(chunk_id,importance,triggers,project_key);"
                         f"CREATE TABLE {CHUNK_PROVENANCE_TABLE}"
                         "(chunk_id,origin_class,session_kind,observed_at,supersedes_key);")
        db.execute("INSERT INTO chunks VALUES ('a')")
        db.execute(f"INSERT INTO {CHUNK_PROVENANCE_TABLE} VALUES (?,?,?,?,?)",
                   ("a", origin, kind, observed, supersedes))
        row = store.read_recall_metadata(["a"], db=db)["a"]
    if expected is None:
        assert "provenance" not in row
    else:
        assert row["provenance"] == expected


def test_source_mtime_reads_use_candidate_source_and_final_public_results_strip_them(tmp_path):
    store = make_store(tmp_path)
    with store.connect() as db:
        identifier, = db.execute("SELECT id FROM chunks ORDER BY start_line LIMIT 1").fetchone()
        db.execute(f"UPDATE {INDEX_SOURCES_TABLE} SET mtime=123456")
        enriched, = store.attach_recall_metadata([keyword(identifier)], db=db)
    assert enriched.to_payload()["sourceMtime"] == 123456
    assert "sourceMtime" not in store.search("comet")[0].to_payload()


def test_active_project_input_is_exact_and_every_stored_project_key_must_match():
    rows = [HybridResult("a", 1, 1, 1, 0, 0, "comet", "memory", project_key="alpha; beta")]
    assert apply_project_ranking(rows, ["alpha", "beta"])[0].score == 1.15
    assert apply_project_ranking(rows, ["alpha"])[0].score == 0.9
    assert apply_project_ranking(rows, [" alpha", "beta"])[0].score == 0.9


def test_modifier_owners_preserve_all_fields_and_do_not_mutate_inputs():
    row = HybridResult("a", 1, 2, 0.8, 0.7, 0.6, "raw", "memory",
                       importance=10, triggers="launch", project_key="alpha", provenance={})
    weighted = apply_project_ranking(apply_importance_multiplier([row]), ["alpha"])[0]
    assert weighted.to_payload() == {**row.to_payload(), "score": 0.8 * 1.25 * 1.15}
    assert row.score == 0.8


def test_keyword_exact_confidence_uses_project_multiplier_after_private_ordering(tmp_path):
    store = make_store(tmp_path)
    rows = store._finalize_keyword_only([
        keyword("active", importance=1, project_key="alpha", exact_path_specificity=3),
        keyword("other", importance=10, project_key="beta", exact_path_specificity=3),
    ], 2, 0, active_project_keys=["alpha"])
    assert [(row.project_key, row.score) for row in rows] == [("beta", 0.9), ("alpha", 1.15)]
    assert all("vectorScore" not in row.to_payload() for row in rows)


def test_read_generation_keeps_ranking_metadata_coherent_with_the_searched_text(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    with store.connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        identifier, = db.execute("SELECT id FROM chunks ORDER BY start_line LIMIT 1").fetchone()
    original = store._query_body_hits
    changed = False

    def replace_after_body(*args, **kwargs):
        nonlocal changed
        rows = original(*args, **kwargs)
        if not changed:
            changed = True
            with store.connect() as writer:
                writer.execute(f"UPDATE {CHUNK_RECALL_TABLE} SET importance=1,project_key='changed' "
                               "WHERE chunk_id=?", (identifier,))
        return rows

    monkeypatch.setattr(store, "_query_body_hits", replace_after_body)
    first = store.search("comet", active_project_keys=["alpha"])
    assert first[0].project_key == "alpha" and first[0].importance == 10
    second = store.search("comet")
    assert any(row.project_key == "changed" and row.importance == 1 for row in second)


def test_native_branch_shapes_retain_numeric_python_attributes_without_inventing_ids():
    generic = HybridResult("a", 1, 2, 0.5, 0.4, 0.2, "text", "memory")
    assert not hasattr(generic, "id")
    vector = dataclasses.replace(generic, _retrieval_mode="vector", _vector_id="candidate")
    assert vector.id == "candidate" and vector.vector_score == 0.4 and vector.text_score == 0.2
    assert vector.to_payload() == {"path": "a", "startLine": 1, "endLine": 2,
                                   "score": 0.5, "snippet": "text", "source": "memory",
                                   "id": "candidate"}
    assert HybridVectorResult("id", "a", 1, 2, "memory", "text", 0.5).source_mtime is (
        HYBRID_METADATA_MISSING
    )


def test_active_project_context_preserves_native_two_hundred_result_window(tmp_path):
    store = make_store(tmp_path)
    root = store.config.workspace_dir
    (root / "MEMORY.md").unlink()
    for i in range(201):
        path = root / "memory" / f"a{i:03}" / "note.md"
        path.parent.mkdir(parents=True)
        path.write_text("note " + "filler " * 30, encoding="utf-8")
    for i in range(51):
        path = root / "memory" / f"z{i:03}.md"
        path.write_text("note", encoding="utf-8")
    store.reindex(MemoryWorkspace(root))
    assert len(store.search("note", max_results=250)) == 250
    assert len(store.search("note", max_results=250, active_project_keys=["alpha"])) == 200
