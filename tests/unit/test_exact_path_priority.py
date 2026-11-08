"""Observable path admission, filename headroom and body/path composition."""
from __future__ import annotations

import sqlite3

import pytest

from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.index.keyword_search import (
    KeywordHit, limit_keyword_search_hits, merge_keyword_search_hits,
    normalized_literal_contains, prepare_exact_path_matcher,
)
from memory_core.index.sqlite_store import SQLiteMemoryStore


@pytest.mark.parametrize("query,path,specificity", [
    ("\ufeff./MEMORY\\Note.md\ufeff", "memory/note.md", 3),
    ("\u0085note.md", "memory/note.md", 0),
    ("\u001cnote.md", "memory/note.md", 0),
    ("note.md", "memory/note.md", 2),
    ("note", "memory/note.md", 1),
    ("memory/note", "memory/note.md", 0),
    ("café.md", "memory/cafe\u0301.md", 2),
    (".env", "memory/.env", 2),
])
def test_original_query_path_identity_uses_js_trimming_and_specificity(query, path, specificity):
    assert prepare_exact_path_matcher(query)(path) == specificity


@pytest.mark.parametrize("value,term,expected", [
    ("ſource.md", "source", 1), ("ﬅyle.md", "ﬆyle", 1),
    ("ẞ.md", "ß", 1), ("Σ.md", "ς", 1),
    ("İ.md", "i", 0), ("ı.md", "I", 0), ("ß.md", "ss", 0),
])
def test_literal_path_substrings_use_simple_instead_of_full_or_python_regex_folding(
    value, term, expected,
):
    assert normalized_literal_contains(value, term) == expected


def hit(identifier, *, path="memory/note.md", snippet="body", body=True, score=0.3):
    return KeywordHit(identifier, path, 1, 2, "memory", snippet, score, 0.2,
                      path_score=0.1, has_body_match=body)


def test_duplicate_snippets_compare_utf16_units_and_keep_an_equal_length_original():
    original = hit("same", snippet="😀")
    incoming = hit("same", snippet="aa")
    merged, = merge_keyword_search_hits([[original], [incoming]], "note")
    assert merged.snippet == "😀"


def test_body_snippet_replaces_a_path_projection_without_gaining_fallback_exactness():
    path = hit("same", path="memory/notes.md", snippet="long path projection", body=False)
    body = hit("same", path="memory/notes.md", snippet="x", body=True)
    merged, = merge_keyword_search_hits([[path], [body]], "find notes from yesterday")
    assert (merged.snippet, merged.has_body_match, merged.exact_path_specificity) == ("x", True, 0)


def test_limiter_reserves_non_exact_capacity_beside_exact_filename_headroom():
    exact = [hit(str(i), path=f"memory/{i}/note.md", body=False) for i in range(201)]
    ordinary = hit("ordinary", path="memory/note-extra.md", score=0.9)
    merged = merge_keyword_search_hits([exact, [ordinary]], "note")
    selected = limit_keyword_search_hits(merged, 1)
    assert len(selected) == 201
    assert sum(row.exact_path_specificity > 0 for row in selected) == 200
    assert selected[-1].id == "ordinary"


def make_store(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    return SQLiteMemoryStore(MemoryConfig(
        workspace_dir=root, store_path=tmp_path / "index.sqlite",
        flags=FeatureFlags(vector_search=False, temporal_decay=False, mmr=False),
    ), None)


def seed(db, identifier, path, *, source="memory", text="source text", first=1, last=2):
    db.execute("INSERT INTO chunks VALUES (?,?,?,?,?,?,?)",
               (identifier, path, first, last, source, text, "[]"))


def path_row(db, path, *, source="memory"):
    db.execute("INSERT INTO paths_fts(path,source) VALUES (?,?)", (path, source))


def test_live_exact_paths_are_filtered_before_the_bounded_filename_window(tmp_path):
    store = make_store(tmp_path)
    with store.connect() as db:
        for i in range(205):
            path_row(db, f"memory/a{i:03}/note.md")
        path_row(db, "memory/z/note.md")
        seed(db, "live", "memory/z/note.md")
    rows = store.search_path_candidates("note", limit=1, exact_path_limit=1)
    assert [(row.id, row.path) for row in rows] == [("live", "memory/z/note.md")]


def test_live_partial_paths_are_filtered_before_the_lexical_window(tmp_path):
    store = make_store(tmp_path)
    with store.connect() as db:
        for i in range(12):
            path_row(db, f"memory/a{i:02}/report-extra.md")
        path_row(db, "memory/z/report-extra.md")
        seed(db, "live", "memory/z/report-extra.md")
    rows = store.search_path_candidates("report", limit=1, exact_path_limit=0)
    assert [row.id for row in rows] == ["live"]


def test_implicit_total_limit_and_explicit_filename_headroom_have_distinct_contracts(tmp_path):
    store = make_store(tmp_path)
    with store.connect() as db:
        for i, path in enumerate(("memory/a/note.md", "memory/b/note.md", "memory/note-extra.md")):
            path_row(db, path)
            seed(db, str(i), path)
    implicit = store.search_path_candidates("note", limit=1)
    explicit = store.search_path_candidates("note", limit=1, exact_path_limit=2)
    assert len(implicit) == 1
    assert len(explicit) == 3
    assert [row.exact_path_specificity for row in explicit] == [1, 1, 0]


def test_ascii_exact_candidates_use_the_original_lexical_plan_before_path_patterns(tmp_path):
    store = make_store(tmp_path)
    with store.connect() as db:
        path_row(db, "memory/target.md")
        seed(db, "target", "memory/target.md")
    assert store.search_path_candidates("unrelated", exact_path_query="target.md", limit=2) == []


def test_like_metacharacters_in_exact_names_are_literals(tmp_path):
    store = make_store(tmp_path)
    with store.connect() as db:
        for i, path in enumerate(("memory/note_%.md", "memory/noteAA.md")):
            path_row(db, path)
            seed(db, str(i), path)
    rows = store.search_path_candidates("note_%.md", limit=3)
    assert [(row.path, row.exact_path_specificity) for row in rows] == [("memory/note_%.md", 2)]


def test_path_source_filter_and_first_chunk_order_own_the_projected_payload(tmp_path):
    store = make_store(tmp_path)
    with store.connect() as db:
        for source in ("memory", "sessions"):
            path_row(db, "shared/note.md", source=source)
            seed(db, source + "later", "shared/note.md", source=source, first=5, text="later")
            seed(db, source + "first", "shared/note.md", source=source,
                 text="A\x00😀漢tail", first=1, last=3)
    row, = store.search_path_candidates("note", limit=1, sources={"sessions"}, snippet_max_chars=4)
    assert (row.id, row.source, row.start_line, row.end_line, row.snippet) == (
        "sessionsfirst", "sessions", 1, 3, "A\x00😀",
    )


def test_path_and_first_chunk_payload_share_the_statement_snapshot(tmp_path, monkeypatch):
    import memory_core.index.sqlite_store as owner

    store = make_store(tmp_path)
    with store.connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        path_row(db, "memory/note.md")
        seed(db, "row", "memory/note.md", text="original")
    writer = sqlite3.connect(store.path)
    original_factory = owner.prepare_exact_path_matcher
    changed = False

    def factory(query):
        original = original_factory(query)

        def match(path):
            nonlocal changed
            if not changed:
                changed = True
                writer.execute("UPDATE chunks SET text='replacement' WHERE id='row'")
                writer.commit()
            return original(path)
        return match

    monkeypatch.setattr(owner, "prepare_exact_path_matcher", factory)
    try:
        with store.connect() as db:
            row, = store.search_path_candidates("note", limit=1, db=db)
        assert changed
        assert row.snippet == "original"
        assert writer.execute("SELECT text FROM chunks WHERE id='row'").fetchone()[0] == "replacement"
    finally:
        writer.close()
