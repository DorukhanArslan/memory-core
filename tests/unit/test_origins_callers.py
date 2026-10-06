"""Offline tests of the origins ledger callers, tombstones, the revision fence and the quarantine.

What the real TS code can show is compared in tests/integration/test_origins_callers_oracle.py and
tests/integration/test_promotion_apply_oracle.py; this file holds what the oracle cannot reach: the
REM branch of the diary builder, the publication fence's message, failure ordering, store limits.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from memory_core.config import MemoryConfig
from memory_core.consolidation.artifact_provenance import (
    MemoryArtifactProvenance,
    MemoryArtifactProvenanceFullError,
    MemoryArtifactProvenanceStore,
    normalize_memory_artifact_relative_path,
    with_daily_file_quarantine,
)
from memory_core.consolidation.origins import (
    MemoryEntryOrigin,
    MemoryEntryOriginLedger,
    MemoryIndexRevisionConflictError,
)
from memory_core.consolidation.recall import record_short_term_recalls
from memory_core.consolidation.session_backfill import (
    SessionBackfillCandidate,
    build_session_backfill_diary_entries,
    coalesce_backfill_claims,
    session_backfill_entry_key,
)
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY

NOW_MS = 1779811200000


def _ledger(tmp_path: Path) -> MemoryEntryOriginLedger:
    return MemoryEntryOriginLedger(lambda agent: tmp_path / "agents" / f"{agent}.sqlite")


def _config(tmp_path: Path) -> MemoryConfig:
    workspace = tmp_path / "ws"
    (workspace / "memory").mkdir(parents=True)
    (workspace / "memory" / "2026-05-08.md").write_text("# day\n\n- A fact.\n", "utf-8")
    return MemoryConfig(workspace_dir=workspace, store_path=tmp_path / "index.sqlite")


def _hit(**over: Any) -> dict[str, Any]:
    hit = {
        "path": "memory/2026-05-08.md",
        "startLine": 3,
        "endLine": 3,
        "score": 0.8,
        "snippet": "- A fact.",
        "source": "memory",
    }
    hit.update(over)
    return hit


# --- recall lineage ---------------------------------------------------------------------------


def test_recall_ignores_session_origins_without_a_ledger(tmp_path: Path) -> None:
    config = _config(tmp_path)
    written = record_short_term_recalls(
        config=config,
        query="facts",
        results=[_hit(sessionOrigin={"agentId": "a", "sessionId": "s"})],
        now_ms=NOW_MS,
    )
    assert written == 1


def test_a_failed_ledger_write_leaves_no_staged_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(tmp_path)
    ledger = _ledger(tmp_path)

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("ledger down")

    monkeypatch.setattr(ledger, "record", boom)
    with pytest.raises(RuntimeError, match="ledger down"):
        record_short_term_recalls(
            config=config,
            query="facts",
            results=[_hit(sessionOrigin={"agentId": "a", "sessionId": "s"})],
            now_ms=NOW_MS,
            origins=ledger,
        )
    store = Path(config.workspace_dir) / "memory" / ".dreams" / "short-term-recall.json"
    assert not store.exists() or json.loads(store.read_text("utf-8"))["entries"] == {}


def test_recall_origin_rows_carry_the_hit_provenance(tmp_path: Path) -> None:
    config = _config(tmp_path)
    ledger = _ledger(tmp_path)
    record_short_term_recalls(
        config=config,
        query="facts",
        results=[
            _hit(
                sessionOrigin={"agentId": "a", "sessionId": "s", "sessionKey": "agent:a:s"},
                provenance={"originClass": "owner", "sessionKind": "interactive", "observedAt": 77},
            ),
            _hit(sessionOrigin={"agentId": "a", "sessionId": "t"}),  # default provenance: agent at now
        ],
        now_ms=NOW_MS,
        origins=ledger,
    )
    rows = {row.session_id: row for row in ledger.list("a")}
    assert (rows["s"].origin_class, rows["s"].observed_at, rows["s"].session_key) == ("owner", 77, "agent:a:s")
    assert (rows["t"].origin_class, rows["t"].observed_at, rows["t"].session_key) == ("agent", NOW_MS, None)
    assert rows["s"].entry_key == rows["t"].entry_key == "memory:memory/2026-05-08.md:3:3"


def test_a_tombstone_recorded_between_scan_and_lock_drops_the_hit(tmp_path: Path) -> None:
    config = _config(tmp_path)
    ledger = _ledger(tmp_path)
    ledger.record_session_tombstones("a", ["gone"])
    assert (
        record_short_term_recalls(
            config=config,
            query="facts",
            results=[_hit(sessionOrigin={"agentId": "a", "sessionId": "gone"})],
            now_ms=NOW_MS,
            origins=ledger,
        )
        == 0
    )
    assert ledger.list("a") == []


# --- tombstones and the revision fence --------------------------------------------------------


def test_tombstones_bump_the_revision_only_when_new(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    assert ledger.index_revision("a") is None
    assert ledger.record_session_tombstones("a", ["s1", "s1", "s2"], created_at=5) == 2
    assert ledger.index_revision("a") == 1
    assert ledger.record_session_tombstones("a", ["s1"], created_at=6) == 0
    assert ledger.index_revision("a") == 1
    assert ledger.record_session_tombstones("a", [], created_at=7) == 0
    assert ledger.record_session_tombstones("b", ["s1"], reason="purged", created_at=8) == 1
    assert [(t.session_id, t.reason, t.created_at) for t in ledger.list_session_tombstones("a")] == [
        ("s1", "forgotten", 5),
        ("s2", "forgotten", 5),
    ]
    assert [t.reason for t in ledger.list_session_tombstones("b", ["s1"])] == ["purged"]
    assert ledger.list_session_tombstones("a", []) == []


def test_tombstone_ids_are_global_per_database_but_listed_per_agent(tmp_path: Path) -> None:
    shared = MemoryEntryOriginLedger(lambda _agent: tmp_path / "one.sqlite")
    assert shared.record_session_tombstones("a", ["s1"]) == 1
    # session_id is the primary key: another agent of the same database cannot claim it (upstream).
    assert shared.record_session_tombstones("b", ["s1"]) == 0
    assert shared.list_session_tombstones("b") == []


def test_the_fence_rejects_a_rebuild_prepared_before_a_forget(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.bump_index_revision("a")
    prepared = ledger.index_revision("a")
    assert prepared == 1
    ledger.assert_index_revision("a", prepared)  # nothing happened: publishing is allowed
    ledger.record_session_tombstones("a", ["forgotten"])  # a forget lands while the rebuild runs
    with pytest.raises(MemoryIndexRevisionConflictError) as error:
        ledger.assert_index_revision("a", prepared)
    # manager-db-kernel.ts publishMemoryDatabaseTables, verbatim.
    assert str(error.value) == (
        "Memory index changed while full reindex was building "
        "(expected revision 1, found 2); retry the full reindex."
    )
    ledger.assert_index_revision("a", 2)


def test_the_fence_needs_a_state_row(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    with pytest.raises(ValueError, match="missing or invalid"):
        ledger.assert_index_revision("never", 0)


def test_tombstone_batches_roll_back_together(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.record_session_tombstones("a", ["seed"])
    path = ledger.database_path("a")
    with sqlite3.connect(path) as db:
        db.execute("DROP TABLE memory_index_state")
        db.execute("CREATE TABLE memory_index_state (id INTEGER PRIMARY KEY CHECK (id = 1), revision TEXT)")
        db.execute(
            "CREATE TRIGGER no_bump BEFORE UPDATE ON memory_index_state BEGIN SELECT RAISE(ABORT, 'fenced'); END"
        )
        db.execute("INSERT INTO memory_index_state VALUES (1, '0')")
    with pytest.raises(sqlite3.DatabaseError, match="fenced"):
        ledger.record_session_tombstones("a", ["x", "y"])
    assert [t.session_id for t in ledger.list_session_tombstones("a")] == ["seed"]


# --- artifact provenance ----------------------------------------------------------------------


def test_tracked_paths() -> None:
    track = normalize_memory_artifact_relative_path
    assert track("memory/2026-05-08.md") == "memory/2026-05-08.md"
    assert track("memory\\2026-05-08.md") == "memory/2026-05-08.md"
    assert track("MEMORY.md") == "MEMORY.md"
    assert track("users/alice/USER.md") == "users/alice/USER.md"
    assert track("users/-bad/USER.md") is None
    assert track("memory/dreaming/x.md") is None
    assert track("memory/.dreams/x.md") is None
    assert track("memory/notes.txt") is None
    assert track("memory/../MEMORY.md") is None
    assert track("/memory/x.md") is None
    assert track("") is None


def test_provenance_rollback_restores_the_previous_record(tmp_path: Path) -> None:
    store = MemoryArtifactProvenanceStore(tmp_path / "p.sqlite")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    path = "memory/2026-05-08.md"

    def write(before: str, after: str, klass: str = "agent", observed: int = 1):
        return store.record_write(
            workspace_dir=workspace,
            relative_path=path,
            content_before=before,
            content_after=after,
            origin_class=klass,
            observed_at=observed,
        )

    write("", "one", observed=1)
    first = store.read(workspace_dir=workspace, relative_path=path)
    undo_two = write("one", "two", "untrusted", observed=2)
    assert undo_two is not None
    assert store.read(workspace_dir=workspace, relative_path=path).origin_class == "untrusted"  # type: ignore[union-attr]
    undo_two()
    assert store.read(workspace_dir=workspace, relative_path=path) == first
    # A rollback does not undo a later write that replaced its record.
    undo_three = write("one", "three", observed=3)
    write("three", "four", observed=4)
    undo_three()
    assert store.read(workspace_dir=workspace, relative_path=path).observed_at == 4  # type: ignore[union-attr]
    assert store.record_write(
        workspace_dir=workspace,
        relative_path="notes/x.md",
        content_before="",
        content_after="x",
        origin_class="agent",
        observed_at=1,
    ) is None


def test_clear_only_removes_a_record_that_still_matches(tmp_path: Path) -> None:
    store = MemoryArtifactProvenanceStore(tmp_path / "p.sqlite")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    kwargs = {"workspace_dir": workspace, "relative_path": "MEMORY.md"}
    store.record_write(**kwargs, content_before="", content_after="v1", origin_class="agent", observed_at=1)
    store.clear(**kwargs, content_before="not v1")
    assert store.read(**kwargs) is not None
    store.clear(**kwargs, content_before="v1")
    assert store.read(**kwargs) is None


def test_the_store_rejects_new_files_when_full_but_updates_known_ones(tmp_path: Path) -> None:
    store = MemoryArtifactProvenanceStore(tmp_path / "p.sqlite", max_entries=1)
    workspace = tmp_path / "ws"
    workspace.mkdir()

    def record(path: str, after: str) -> None:
        store.record_write(
            workspace_dir=workspace,
            relative_path=path,
            content_before="",
            content_after=after,
            origin_class="agent",
            observed_at=1,
        )

    record("memory/a.md", "1")
    record("memory/a.md", "2")
    with pytest.raises(MemoryArtifactProvenanceFullError):
        record("memory/b.md", "1")
    assert [relative for relative, _record in store.list(workspace)] == ["memory/a.md"]


def test_records_are_per_workspace_and_a_foreign_record_reads_as_absent(tmp_path: Path) -> None:
    store = MemoryArtifactProvenanceStore(tmp_path / "p.sqlite")
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir()
    two.mkdir()
    store.record_write(
        workspace_dir=one,
        relative_path="memory/a.md",
        content_before="",
        content_after="x",
        origin_class="untrusted",
        observed_at=3,
        session_id="s",
        session_key="k",
    )
    assert store.list(two) == []
    [(relative, record)] = store.list(one)
    assert (relative, record.origin_class, record.session_id, record.session_key) == ("memory/a.md", "untrusted", "s", "k")
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE memory_artifact_provenance SET value = '{\"version\": 2}'")
    assert store.list(one) == []
    assert store.read(workspace_dir=one, relative_path="memory/a.md") is None


@dataclass(frozen=True)
class _Candidate:
    path: str
    provenance: dict[str, Any] | None


def test_with_daily_file_quarantine() -> None:
    untrusted = MemoryArtifactProvenance("0" * 64, "untrusted", 99)
    trusted = MemoryArtifactProvenance("0" * 64, "agent", 98)
    records = {"memory/a.md": untrusted, "memory/b.md": trusted}
    cut = with_daily_file_quarantine(_Candidate("memory\\a.md", {"originClass": "agent", "sessionKind": "cron", "observedAt": 1}), records)
    assert cut.provenance == {"originClass": "untrusted", "sessionKind": "cron", "observedAt": 99}
    assert with_daily_file_quarantine(_Candidate("memory/a.md", None), records).provenance == {
        "originClass": "untrusted",
        "sessionKind": "unknown",
        "observedAt": 99,
    }
    keep = _Candidate("memory/b.md", {"originClass": "agent", "sessionKind": "cron", "observedAt": 1})
    assert with_daily_file_quarantine(keep, records) is keep
    other = _Candidate("memory/c.md", None)
    assert with_daily_file_quarantine(other, records) is other


# --- session backfill -------------------------------------------------------------------------


def _backfill_candidate(snippet: str, session: str | None = "s1", klass: str = "owner") -> SessionBackfillCandidate:
    return SessionBackfillCandidate(
        day="2026-05-08",
        snippet=snippet,
        rendered=f"User: {snippet}",
        provenance={"originClass": klass, "sessionKind": "interactive", "observedAt": 5},
        session_origin={"agentId": "main", "sessionId": session} if session else None,
    )


def test_diary_entries_are_marked_and_recorded_before_return(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    entries = build_session_backfill_diary_entries(
        ledger=ledger,
        agent_id="main",
        days=[("2026-05-08", [_backfill_candidate("One."), _backfill_candidate("Two.", None)])],
        identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
    )
    key = session_backfill_entry_key("2026-05-08", "- One.")
    assert entries == [
        {
            "isoDay": "2026-05-08",
            "sourcePath": "memory/.dreams/session-corpus/2026-05-08.txt",
            "bodyLines": [
                "Session backfill found 2 trusted candidates.",
                f"<!-- openclaw-memory-promotion:{key} -->\n- One.",
                f"<!-- openclaw-memory-promotion:{session_backfill_entry_key('2026-05-08', '- Two.')} -->\n- Two.",
            ],
        }
    ]
    assert [(row.entry_key, row.session_id) for row in ledger.list("main")] == [(key, "s1")]


def test_the_default_identity_writes_the_neutral_marker(tmp_path: Path) -> None:
    [entry] = build_session_backfill_diary_entries(
        ledger=_ledger(tmp_path), agent_id="main", days=[("2026-05-08", [_backfill_candidate("One.", None)])]
    )
    assert entry["bodyLines"][0] == "Session backfill found 1 trusted candidate."
    assert entry["bodyLines"][1].startswith("<!-- memory-core-memory-promotion:memory:session-backfill:")


def test_rem_preview_marks_each_item_with_the_sources_it_cites(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    seen: dict[str, Any] = {}

    def preview(rel_path: str, content: str, format_item: Any) -> str | None:
        seen.update(rel_path=rel_path, content=content)
        # Candidates sit on lines 3 and 4 of the virtual file (heading and blank line before them).
        return "## Facts\n\n" + format_item("- first item", [f"{rel_path}:3-3"]) + "\n" + format_item(
            "- both", [f"{rel_path}:3-4"]
        )

    [entry] = build_session_backfill_diary_entries(
        ledger=ledger,
        agent_id="main",
        days=[("2026-05-08", [_backfill_candidate("One.", "s1"), _backfill_candidate("Two.", "s2")])],
        rem_preview=preview,
        identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
    )
    assert seen == {
        "rel_path": "memory/2026-05-08.md",
        "content": "## Session transcript\n\nUser: One.\nUser: Two.\n",
    }
    assert entry["bodyLines"][0] == "Facts"  # the "## " heading marker is stripped
    first = session_backfill_entry_key("2026-05-08", "- first item")
    both = session_backfill_entry_key("2026-05-08", "- both")
    assert sorted((row.entry_key, row.session_id) for row in ledger.list("main")) == sorted(
        [(first, "s1"), (both, "s1"), (both, "s2")]
    )


def test_an_empty_rem_preview_falls_back_to_the_count_block(tmp_path: Path) -> None:
    [entry] = build_session_backfill_diary_entries(
        ledger=_ledger(tmp_path),
        agent_id="main",
        days=[("2026-05-08", [_backfill_candidate("One.", None)])],
        rem_preview=lambda *_args: None,
    )
    assert entry["bodyLines"][0] == "Session backfill found 1 trusted candidate."


def test_a_session_of_another_agent_fails_the_whole_batch(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    foreign = SessionBackfillCandidate(
        day="2026-05-08",
        snippet="x",
        rendered="x",
        provenance={"originClass": "owner", "sessionKind": "interactive", "observedAt": 1},
        session_origin={"agentId": "other", "sessionId": "s"},
    )
    with pytest.raises(ValueError, match="another agent"):
        build_session_backfill_diary_entries(
            ledger=ledger, agent_id="main", days=[("2026-05-08", [_backfill_candidate("ok"), foreign])]
        )
    assert ledger.list("main") == [] and ledger.list("other") == []


def test_coalescing_keeps_each_source_and_shares_the_first_citation() -> None:
    results = [
        {"path": "a", "startLine": 1, "endLine": 1, "snippet": "User: Same  thing", "sessionOrigin": {"sessionId": "1"}},
        {"path": "b", "startLine": 9, "endLine": 9, "snippet": "assistant: same THING", "sessionOrigin": {"sessionId": "2"}},
        {"path": "c", "startLine": 3, "endLine": 3, "snippet": "Assistant:  "},
    ]
    out = coalesce_backfill_claims(results)
    assert [(r["path"], r["startLine"], r["snippet"], r["sessionOrigin"]["sessionId"]) for r in out] == [
        ("a", 1, "Same  thing", "1"),
        ("a", 1, "Same  thing", "2"),
    ]


def test_origin_dataclass_roundtrip_through_the_session_backfill_rows(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    added = ledger.record("main", [MemoryEntryOrigin("k", "main", "s", None, "owner", 1)])
    assert [item.session_id for item in added] == ["s"]
