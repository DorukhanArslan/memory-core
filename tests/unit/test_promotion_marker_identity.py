"""Qualified marker readers preserve Q22 defaults and actual stored ownership."""
from dataclasses import replace
import sqlite3

import pytest

from memory_core.consolidation.artifacts import read_memory_preimages, store_memory_preimage
from memory_core.consolidation.markers import extract_promotion_markers, format_promotion_marker
from memory_core.consolidation.origins import MemoryEntryOrigin, MemoryEntryOriginLedger, prune_memory_entry_origins
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY as CORE, OPENCLAW_COMPAT_RUNTIME_IDENTITY as NATIVE


@pytest.mark.parametrize("identity,expected", [(None, ["core", "native"]), (CORE, ["core"]), (NATIVE, ["native"])])
def test_default_dual_and_explicit_single_readers_use_the_same_complete_text(identity, expected):
    text = format_promotion_marker("core", CORE) + "\n" + format_promotion_marker("native", NATIVE)
    assert extract_promotion_markers(text, identity=identity) == expected


@pytest.mark.parametrize("location,space,expected", [
    ("prefix", "\u0085", []), ("key", "\u0085", ["\u0085key"]),
    ("prefix", "\ufeff", ["key"]), ("key", "\ufeff", ["key"]),
])
@pytest.mark.parametrize("identity", [None, NATIVE])
def test_extract_uses_js_whitespace_and_trim_without_python_space_aliases(location, space, expected, identity):
    text = ("<!--" + space + NATIVE.promotion_marker_prefix + "key -->" if location == "prefix" else
        "<!-- " + NATIVE.promotion_marker_prefix + space + "key -->")
    assert extract_promotion_markers(text, identity=identity) == expected


def test_extract_character_class_preserves_line_terminators_inside_the_key():
    # Native extraction uses [^\n], while its budget marker uses a JS dot.
    for separator in ("\r", "\u2028", "\u2029"):
        text = format_promotion_marker("left" + separator + "right", NATIVE)
        assert extract_promotion_markers(text, identity=NATIVE) == ["left" + separator + "right"]


def test_custom_non_ascii_prefix_is_literal_and_escaped():
    custom = replace(CORE, promotion_marker_prefix="host.\u03a3+:")
    assert extract_promotion_markers(format_promotion_marker("key", custom), identity=custom) == ["key"]
    assert extract_promotion_markers("<!-- host.\u03c3+:key -->", identity=custom) == []


@pytest.mark.parametrize("identity,expected", [(None, {"core", "native"}), (NATIVE, {"native"}), (CORE, {"core"})])
def test_actual_preimage_storage_returns_only_the_selected_reader_keys(tmp_path, identity, expected):
    content = format_promotion_marker("core", CORE) + "\n" + format_promotion_marker("native", NATIVE)
    actual = store_memory_preimage(tmp_path, content, 1779811200000, identity=identity)
    assert actual == expected
    assert read_memory_preimages(tmp_path)[0]["content"] == content


@pytest.mark.parametrize("identity,expected", [(None, {"core-diary", "native-diary", "core-index", "native-index"}),
    (NATIVE, {"native-diary", "native-index"})])
def test_builtin_sql_index_and_diary_pruning_use_one_reader_identity(tmp_path, identity, expected):
    database = tmp_path / "agent.sqlite"
    ledger = MemoryEntryOriginLedger(lambda _agent: database)
    keys = {"core-diary", "native-diary", "core-index", "native-index", "unreferenced"}
    ledger.record("main", [MemoryEntryOrigin(key, "main", "source", "agent:main:source", "owner", 1000) for key in keys])
    (tmp_path / "DREAMS.md").write_text(format_promotion_marker("core-diary", CORE) + "\n" + format_promotion_marker("native-diary", NATIVE))
    # Literal persisted host index rows exercise the builtin compatibility
    # reader, not an injected callback or a claimed Native publication.
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE memory_index_chunks (id TEXT, source TEXT, text TEXT)")
        db.executemany("INSERT INTO memory_index_chunks VALUES (?, 'memory', ?)", [
            ("core", format_promotion_marker("core-index", CORE)), ("native", format_promotion_marker("native-index", NATIVE))])
    assert ledger.indexed_promotion_keys("main", identity=identity) == expected.intersection({"core-index", "native-index"})
    prune_memory_entry_origins(ledger, workspace_dir=tmp_path, agent_ids=["main"], entry_keys=keys,
        retained_entry_keys=set(), identity=identity)
    assert {row.entry_key for row in ledger.list("main")} == expected


def test_opaque_host_index_authority_keeps_its_declared_boundary(tmp_path):
    seen = []
    ledger = MemoryEntryOriginLedger(lambda _agent: tmp_path / "unused.sqlite",
        indexed_promotion_keys=lambda agent: seen.append(agent) or {"host-selected"})
    assert ledger.indexed_promotion_keys("main", identity=NATIVE) == {"host-selected"}
    assert seen == ["main"] and not (tmp_path / "unused.sqlite").exists()
