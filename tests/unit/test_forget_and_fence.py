"""Offline tests of the forget flow, the index revision fence and what the oracle cannot reach.

The real TS flow is compared in tests/integration/test_forget_oracle.py (35 seeded workspaces), the
fence's ledger half in tests/integration/test_origins_callers_oracle.py. This file holds the parts that
need another process or the host in upstream: the ``since`` and participant selectors, retained archives,
a lineage that changes while the flow plans, a rebuild that races a forget (``SQLiteMemoryStore.reindex``
against the revision), tombstoned transcripts leaving the session corpus.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.consolidation.forget import (
    SessionArchive,
    SessionInstance,
    forget_memory_entries,
    references_session,
    resolve_memory_session_targets,
    scrub_memory_content,
)
from memory_core.consolidation.origins import (
    MemoryEntryOrigin,
    MemoryEntryOriginLedger,
    MemoryIndexRevisionConflictError,
)
from memory_core.flags import FeatureFlags
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.workspace import MemoryWorkspace

PRE = "memory-core-memory-promotion:"


def _ledger(tmp_path: Path, name: str = "ledger") -> MemoryEntryOriginLedger:
    return MemoryEntryOriginLedger(lambda agent: tmp_path / f"{name}-{agent}.sqlite")


def _origin(key: str, agent: str, session: str) -> MemoryEntryOrigin:
    return MemoryEntryOrigin(key, agent, session, f"agent:{agent}:{session}", "owner", 1)


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "ws"
    (workspace / "memory").mkdir(parents=True)
    (workspace / "MEMORY.md").write_text("# Memory\n\n- A durable fact.\n", "utf-8")
    (workspace / "memory" / "2026-05-08.md").write_text("# day\n\n- A daily fact.\n", "utf-8")
    return workspace


def _config(workspace: Path, tmp_path: Path, name: str = "index") -> MemoryConfig:
    return MemoryConfig(
        workspace_dir=workspace, store_path=tmp_path / f"{name}.sqlite", flags=FeatureFlags(vector_search=False)
    )


# --- selectors ---------------------------------------------------------------------------------


def test_selectors_resolve_against_instances_archives_and_dates() -> None:
    day = 86_400_000
    instances = [
        SessionInstance("a", "s-old", "agent:a:old", 1 * day, hook_external_content_source="webhook"),
        SessionInstance("a", "s-new", "agent:a:new", 5 * day, participants=({"id": "alice", "kind": "user"},)),
        SessionInstance("b", "s-other", "agent:b:other", 3 * day),
    ]
    archives = [SessionArchive("s-arch", "agent:a:arch", 2 * day), SessionArchive("s-arch-new", "agent:a:arch2", 9 * day)]

    def ids(**selectors: Any) -> dict[str, str]:
        targets = resolve_memory_session_targets("a", instances=instances, archives=archives, **selectors)
        return {t.session_id: t.resolution for t in targets}

    assert ids(session_ids=["agent:a:new", "s-arch", "ghost"]) == {
        "s-new": "live",
        "s-arch": "archived",
        "ghost": "unresolved",
    }
    assert ids(hook_sources=["webhook"]) == {"s-old": "live"}
    assert ids(participants=["alice"]) == {"s-new": "live"}
    assert ids(session_ids=["s-old", "s-new", "s-arch", "s-arch-new"], since=3 * day) == {"s-new": "live", "s-arch-new": "archived"}
    assert ids(session_ids=["s-old"], since="1970-01-03T00:00:00Z") == {}
    assert ids() == {}
    with pytest.raises(ValueError, match="Invalid memory session date"):
        ids(session_ids=["s-old"], since="not a date")
    # Another agent's session is not this agent's target.
    assert ids(session_ids=["s-other"]) == {"s-other": "unresolved"}


def test_forget_needs_a_selector_and_reports_participant_matches(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    with pytest.raises(ValueError, match="requires a session, hook source, or participant selector"):
        forget_memory_entries(config=_config(workspace, tmp_path), agent_id="a", origins=_ledger(tmp_path))
    report = forget_memory_entries(
        config=_config(workspace, tmp_path),
        agent_id="a",
        origins=_ledger(tmp_path),
        participants=["bob", "alice", "alice"],
        instances=[
            SessionInstance("a", "s1", "agent:a:s1", 1, participants=({"id": "alice", "name": "A"}, {"id": "carol"})),
            SessionInstance("a", "s2", "agent:a:s2", 2, participants=({"id": "alice", "name": "A"},)),
        ],
        dry_run=True,
    ).to_json()
    assert report["sessionIds"] == ["s1", "s2"]
    assert report["participantMatches"] == [
        {"actorId": "alice", "identities": [{"id": "alice", "name": "A"}]},
        {"actorId": "bob", "identities": []},
    ]


def test_dry_run_touches_nothing(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    ledger = _ledger(tmp_path)
    ledger.record("a", [_origin("k1", "a", "s1")])
    (workspace / "MEMORY.md").write_text(f"# Memory\n\n<!-- {PRE}k1 -->\n- Promoted fact.\n", "utf-8")
    before = (workspace / "MEMORY.md").read_text("utf-8")
    report = forget_memory_entries(
        config=_config(workspace, tmp_path), agent_id="a", origins=ledger, session_ids=["s1"], dry_run=True
    )
    assert report.entry_keys == ["k1"] and report.artifacts["memoryEntries"] == 1
    assert (workspace / "MEMORY.md").read_text("utf-8") == before
    assert ledger.list_session_tombstones("a") == [] and ledger.index_revision("a") is None
    assert [o.entry_key for o in ledger.list("a")] == ["k1"]


# --- the flow ----------------------------------------------------------------------------------


def test_both_marker_prefixes_and_a_lineage_marker_leave_with_their_entry(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    ledger = _ledger(tmp_path)
    ledger.record("a", [_origin("k1", "a", "s1"), _origin("k2", "a", "s1")])
    (workspace / "MEMORY.md").write_text(
        "# Memory\n\n"
        f"<!-- memory-core-memory-lineage:lin -->\n<!-- {PRE}k1 -->\n- First fact.\n  continued\n"
        "<!-- openclaw-memory-promotion:k2 -->\n- Second fact.\n"
        "<!-- openclaw-memory-promotion:keep -->\n- Kept fact.\n",
        "utf-8",
    )
    forget_memory_entries(config=_config(workspace, tmp_path), agent_id="a", origins=ledger, session_ids=["s1"])
    assert (workspace / "MEMORY.md").read_text("utf-8") == (
        "# Memory\n\n<!-- openclaw-memory-promotion:keep -->\n- Kept fact.\n"
    )
    assert ledger.list("a") == []


def test_a_lineage_that_changes_while_planning_plans_again(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    ledger = _ledger(tmp_path)
    ledger.record("a", [_origin("k1", "a", "s1")])
    (workspace / "MEMORY.md").write_text(
        f"# Memory\n\n<!-- {PRE}k1 -->\n- First.\n<!-- {PRE}k2 -->\n- Second.\n", "utf-8"
    )
    calls: list[str] = []

    def corpus_entries(agent: str):
        # Called while the plan is built: another writer records a second origin of the same session.
        calls.append(agent)
        if len(calls) == 1:
            ledger.record("a", [_origin("k2", "a", "s1")])
        return []

    report = forget_memory_entries(
        config=_config(workspace, tmp_path),
        agent_id="a",
        origins=ledger,
        session_ids=["s1"],
        corpus_entries=corpus_entries,
    )
    assert len(calls) == 2  # planned twice: the tombstone transaction saw the new row and rolled back
    assert report.entry_keys == ["k1", "k2"]
    assert (workspace / "MEMORY.md").read_text("utf-8") == "# Memory\n\n"
    assert ledger.list("a") == []
    assert [t.session_id for t in ledger.list_session_tombstones("a")] == ["s1"]


def test_a_changed_file_is_not_overwritten(tmp_path: Path) -> None:
    from memory_core.consolidation.forget import MemoryWriteConflictError, commit_memory_content

    path = tmp_path / "f.md"
    path.write_text("planned", "utf-8")
    path.write_text("edited meanwhile", "utf-8")
    with pytest.raises(MemoryWriteConflictError, match="f.md changed before the memory forget rewrite could commit"):
        commit_memory_content(path, expected_content="planned", content="x", label="f.md")
    assert path.read_text("utf-8") == "edited meanwhile"


def test_session_references_follow_the_owners_grammar() -> None:
    ids = {"abc"}
    assert references_session("[a/sessions/a/abc#L1] hi", "a", ids)
    assert references_session("a:abc", "a", ids)
    assert references_session("sessions/a/abc.jsonl", "a", ids)
    assert references_session("sessions/a/abc.jsonl.reset.2026-05-26T16-00-00.123Z", "a", ids)
    assert references_session("see Session ID: abc;", "a", ids)
    assert not references_session("sessions/a/abcd.jsonl", "a", ids)
    assert not references_session("sessions/b/abc.jsonl", "a", ids)
    assert not references_session("xa:abc", "a", ids)
    assert not references_session("sessions/a/abc.jsonl.bak.2026-05-26T16-00-00.123Z", "a", ids)


def test_scrub_removes_session_sections_by_heading_level() -> None:
    text = "# T\n## From a:s1\nbody\n### Sub\nsub body\n## Other\nkeep\n"
    scrubbed = scrub_memory_content(
        content=text, entry_keys=set(), session_ids={"s1"}, corpus_snippets=set(), agent_id="a"
    )
    assert scrubbed.content == "# T\n## Other\nkeep\n" and scrubbed.removed_entries == 1


# --- the revision fence ------------------------------------------------------------------------


def _fenced_store(tmp_path: Path, *, same_database: bool):
    workspace = _workspace(tmp_path)
    ledger = _ledger(tmp_path)
    config = _config(workspace, tmp_path)
    if same_database:
        ledger = MemoryEntryOriginLedger(lambda agent: config.store_path)
    store = SQLiteMemoryStore(config, None, revision_fence=ledger.revision_fence("a"))
    return workspace, ledger, store


@pytest.mark.parametrize("same_database", [True, False])
def test_a_forget_during_the_build_fails_the_publication(tmp_path: Path, same_database: bool) -> None:
    workspace, ledger, store = _fenced_store(tmp_path, same_database=same_database)
    memory_workspace = MemoryWorkspace(workspace)
    assert store.reindex(memory_workspace) == 2
    published = store.count_chunks()
    revision = ledger.index_revision("a")
    assert revision is not None and revision >= 1  # the publication bumped it

    original = memory_workspace.discover_indexable_files

    def discover_then_forget():
        files = original()
        ledger.record_session_tombstones("a", ["s1"])  # a forget lands while the rebuild is being built
        return files

    memory_workspace.discover_indexable_files = discover_then_forget  # type: ignore[method-assign]
    (workspace / "memory" / "2026-05-09.md").write_text("- New fact.\n", "utf-8")
    with pytest.raises(MemoryIndexRevisionConflictError, match="expected revision"):
        store.reindex(memory_workspace)
    assert store.count_chunks() == published  # the published index is untouched
    memory_workspace.discover_indexable_files = original  # type: ignore[method-assign]
    assert store.reindex(memory_workspace) == 3  # the retry builds from the newest revision


@pytest.mark.parametrize("same_database", [True, False])
def test_a_publication_fences_a_build_prepared_before_it(tmp_path: Path, same_database: bool) -> None:
    workspace, ledger, store = _fenced_store(tmp_path, same_database=same_database)
    memory_workspace = MemoryWorkspace(workspace)
    original = memory_workspace.discover_indexable_files
    inner_ran: list[bool] = []

    def discover_then_publish_elsewhere():
        files = original()
        if not inner_ran:
            inner_ran.append(True)
            other = SQLiteMemoryStore(store.config, None, revision_fence=ledger.revision_fence("a"))
            other.reindex(MemoryWorkspace(workspace))  # another rebuild publishes first
        return files

    memory_workspace.discover_indexable_files = discover_then_publish_elsewhere  # type: ignore[method-assign]
    with pytest.raises(MemoryIndexRevisionConflictError):
        store.reindex(memory_workspace)
    memory_workspace.discover_indexable_files = original  # type: ignore[method-assign]
    assert store.reindex(memory_workspace) == 2


def test_the_first_publication_without_a_revision_row_is_allowed(tmp_path: Path) -> None:
    workspace, ledger, store = _fenced_store(tmp_path, same_database=False)
    assert ledger.index_revision("a") is None
    store.reindex(MemoryWorkspace(workspace))
    assert ledger.index_revision("a") == 1


def test_a_store_without_a_fence_never_touches_the_ledger(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    store = SQLiteMemoryStore(_config(workspace, tmp_path), None)
    assert store.revision_fence is None and store.reindex(MemoryWorkspace(workspace)) == 2


def test_memory_opens_with_a_fence(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    ledger = _ledger(tmp_path)
    memory = Memory.from_workspace(
        workspace, config=_config(workspace, tmp_path), initialize=False, revision_fence=ledger.revision_fence("a")
    )
    assert memory.store.revision_fence is not None and ledger.index_revision("a") == 1


def test_forget_fences_an_index_rebuilt_from_before_it(tmp_path: Path) -> None:
    workspace, ledger, store = _fenced_store(tmp_path, same_database=False)
    memory_workspace = MemoryWorkspace(workspace)
    store.reindex(memory_workspace)
    original = memory_workspace.discover_indexable_files

    def discover_then_forget():
        files = original()
        forget_memory_entries(
            config=store.config, agent_id="a", origins=ledger, session_ids=["s9"], store=store
        )
        return files

    memory_workspace.discover_indexable_files = discover_then_forget  # type: ignore[method-assign]
    with pytest.raises(MemoryIndexRevisionConflictError):
        store.reindex(memory_workspace)


def test_forget_purges_the_index_rows_of_rewritten_files(tmp_path: Path) -> None:
    workspace, ledger, store = _fenced_store(tmp_path, same_database=False)
    ledger.record("a", [_origin("k1", "a", "s1")])
    (workspace / "MEMORY.md").write_text(f"# Memory\n\n<!-- {PRE}k1 -->\n- Promoted fact.\n- Other fact.\n", "utf-8")
    memory_workspace = MemoryWorkspace(workspace)
    store.reindex(memory_workspace)
    before = store.count_chunks()
    report = forget_memory_entries(
        config=store.config, agent_id="a", origins=ledger, session_ids=["s1"], store=store
    )
    assert report.artifacts["indexChunks"] >= 1
    assert store.count_chunks() < before
    store.reindex(memory_workspace)  # a later reindex brings the rewritten file back, scrubbed
    with store.connect() as db:
        texts = [row[0] for row in db.execute("SELECT text FROM chunks WHERE path = 'MEMORY.md'")]
    assert texts and all("Promoted fact" not in text for text in texts)


# --- tombstones and the session corpus ---------------------------------------------------------


def test_forgotten_sessions_leave_the_session_corpus(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    state = tmp_path / "state"
    sessions = state / "agents" / "a" / "sessions"
    sessions.mkdir(parents=True)
    for session in ("s1", "s2"):
        (sessions / f"{session}.jsonl").write_text(
            json.dumps({"type": "message", "message": {"role": "user", "content": f"hello from {session}"}}) + "\n", "utf-8"
        )
    (sessions / "sessions.json").write_text(
        json.dumps({f"k{n}": {"sessionFile": f"s{n}.jsonl"} for n in (1, 2)}), "utf-8"
    )
    ledger = _ledger(tmp_path)

    def forgotten(session_id: str) -> bool:
        return bool(ledger.list_session_tombstones("a", [session_id]))

    memory_workspace = MemoryWorkspace(workspace, openclaw_state_dir=state, agent_id="a", is_session_forgotten=forgotten)
    assert sorted(f.rel_path for f in memory_workspace.discover_session_transcript_files()) == [
        "sessions/a/s1.jsonl",
        "sessions/a/s2.jsonl",
    ]
    ledger.record_session_tombstones("a", ["s1"])
    assert [f.rel_path for f in memory_workspace.discover_session_transcript_files()] == ["sessions/a/s2.jsonl"]
