"""Authoritative session visibility over real catalog, storage and read paths."""

from dataclasses import replace

import pytest

from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.session_visibility import (
    SessionOwnershipLookup,
    SessionVisibilityContext,
    SessionVisibilityPolicy,
    filter_memory_search_hits_by_session_visibility,
    read_visible_session_source,
    resolve_memory_search_source_policy,
    resolve_session_tool_access,
    session_visibility_decision,
)
from memory_core.tools.common import MemoryToolError
from memory_core.tools.deadline import MemoryToolDeadlineContext
from memory_core.tools.memory_search import MemorySearchToolContext, execute_memory_search_tool


ALICE = "agent:main:direct:alice"
BOB = "agent:main:direct:bob"
NOW = 1_804_723_200_000


def event(text, identity="message-1"):
    return {"type": "message", "id": identity, "message": {"role": "user", "content": text}}


def session(catalog, key, session_id, text="Cobalt private source.", **metadata):
    catalog.upsert_session(key, {"sessionId": session_id, "chatType": "direct", **metadata})
    catalog.replace_events(session_id, [event(text)])


def catalog_at(tmp_path):
    return MemorySessionCatalog(tmp_path / "catalog.sqlite", clock_ms=lambda: NOW)


def hit(session_id, *, agent="main", end=1):
    return {"source": "sessions", "path": f"sessions/{agent}/{session_id}.jsonl",
            "startLine": 1, "endLine": end, "score": 0.8, "snippet": "Source evidence.",
            "provenance": {"originClass": "owner", "sessionKind": "interactive", "observedAt": NOW}}


def context(catalog, visibility=None, **changes):
    return SessionVisibilityContext.from_catalog(
        catalog, SessionVisibilityPolicy(visibility=visibility, **changes),
    )


def filtered(rows, catalog, *, requester=BOB, visibility=None, recall=None, sandboxed=False):
    return filter_memory_search_hits_by_session_visibility(
        rows, context=context(catalog, visibility), agent_id="main",
        requester_session_key=requester, conversation_recall=recall, sandboxed=sandboxed,
    )


def test_no_requester_is_not_authority_but_native_default_all_allows_same_agent(tmp_path):
    catalog = catalog_at(tmp_path)
    session(catalog, ALICE, "alice")
    session(catalog, BOB, "bob")
    rows = [hit("alice"), hit("bob")]
    assert filtered(rows, catalog, requester=None) == []
    assert filtered(rows, catalog) == rows
    assert filtered(rows, catalog, visibility="self") == [rows[1]]
    memory_row = {"source": "memory", "path": "MEMORY.md", "snippet": "public memory"}
    assert filtered([memory_row, *rows], catalog, requester=None) == [memory_row]


def test_real_index_filters_before_small_result_limit_and_reports_withheld_hits(tmp_path):
    catalog = catalog_at(tmp_path)
    for number in range(5):
        session(catalog, f"agent:main:direct:peer-{number}", f"peer-{number}", "Cobalt private source.")
    session(catalog, BOB, "bob", "Cobalt private source.")
    visibility = context(catalog, "self")
    memory = Memory.from_workspace(
        tmp_path, initialize=False, session_catalog=catalog, session_visibility=visibility,
        config=MemoryConfig(workspace_dir=tmp_path, flags=FeatureFlags(vector_search=False), citation_mode="off"),
    )
    result = memory.search("Cobalt", corpus="sessions", max_results=1, agent_session_key=BOB)
    assert [row["path"] for row in result["results"]] == ["sessions/main/bob.jsonl"]
    assert result["debug"]["candidateHits"] == 6
    assert result["debug"]["withheldHits"] == 5
    assert result["debug"]["searchWindow"] == 6
    assert result["debug"]["hits"] == 1
    assert result["results"][0]["provenance"]["originClass"] == "untrusted"


def test_sandbox_clamp_and_real_persisted_child_lineage(tmp_path):
    catalog = catalog_at(tmp_path)
    session(catalog, BOB, "bob")
    child_key = "agent:main:subagent:child"
    session(catalog, child_key, "child", spawnedBy=BOB, status="running")
    session(catalog, ALICE, "alice")
    rows = [hit("bob"), hit("child"), hit("alice")]
    assert filtered(rows, catalog, sandboxed=True) == rows[:2]
    catalog.upsert_session(child_key, {"sessionId": "child", "spawnedBy": BOB,
                                       "chatType": "direct", "status": "done", "endedAt": NOW - 1_800_001})
    assert filtered(rows, catalog, sandboxed=True) == rows[:1]
    assert filtered(rows, catalog, visibility="tree") == rows[:1]


def test_owner_qualified_peer_and_incognito_rows_do_not_bypass_scope(tmp_path):
    catalog = catalog_at(tmp_path)
    session(catalog, BOB, "bob")
    session(catalog, "agent:main:dashboard:incognito-hidden", "incognito")
    rows = [hit("bob"), hit("bob", agent="peer"), hit("incognito")]
    assert filtered(rows, catalog, visibility="self") == rows[:1]
    assert filtered(rows, catalog, requester=BOB, visibility="agent") == [rows[0], rows[2]]
    # Ordinary agent-wide mode has the native same-agent-live orphan fallback;
    # it does not prove that an incognito transcript was admitted to the index.


def test_private_recall_requires_valid_requester_and_all_aliases_private(tmp_path):
    catalog = catalog_at(tmp_path)
    session(catalog, BOB, "bob", sessionFile="bob.jsonl")
    session(catalog, ALICE, "alice", sessionFile="same-source.jsonl")
    recall = {"scope": "same-agent-private", "corpus": "sessions", "anchorSessionKey": BOB}
    rows = [hit("alice"), hit("bob")]
    assert filtered(rows, catalog, recall=recall) == rows[:1]
    assert filtered(rows, catalog, recall=recall, requester=BOB + ":active-memory:012345abcdef") == rows[:1]
    assert filtered(rows, catalog, recall=recall, requester=BOB + ":active-memory:012345abcde") == []
    assert filtered(rows, catalog, recall=recall, sandboxed=True) == []
    catalog.upsert_session("agent:main:discord:group:shared", {
        "sessionId": "different-id", "sessionFile": "same-source.jsonl", "chatType": "group",
    })
    assert filtered(rows, catalog, recall=recall) == []
    assert filtered(rows, catalog) == rows


def test_shared_anchor_alias_and_explicit_without_direct_metadata_fail_closed(tmp_path):
    catalog = catalog_at(tmp_path)
    session(catalog, BOB, "bob")
    session(catalog, ALICE, "alice")
    recall = {"scope": "same-agent-private", "corpus": "sessions", "anchorSessionKey": BOB}
    catalog.upsert_session("agent:main:telegram:group:shared", {"sessionId": "bob", "chatType": "group"})
    assert filtered([hit("alice")], catalog, recall=recall) == []
    explicit = "agent:main:explicit:ui"
    catalog.upsert_session(explicit, {"sessionId": "ui"})
    recall["anchorSessionKey"] = explicit
    assert filtered([hit("alice")], catalog, recall=recall, requester=explicit) == []
    catalog.upsert_session(explicit, {"sessionId": "ui", "delivery": {"kind": "external", "origin": {"chatType": "direct"}}})
    assert filtered([hit("alice")], catalog, recall=recall, requester=explicit)


def test_recall_live_anchor_uses_real_reset_cutoff_and_archives_keep_distinct_rules(tmp_path):
    catalog = catalog_at(tmp_path)
    session(catalog, BOB, "bob")
    catalog.replace_events("bob", [event("before", "one"), event("retained", "two"),
                                   {"type": "reset", "firstKeptEntryId": "two"}])
    reset = "bob-old.jsonl.reset.2026-09-09T12-00-00.000Z"
    deleted = "bob-old.jsonl.deleted.2026-09-09T12-00-00.000Z"
    catalog.record_archive(reset, "bob-old", session_key=BOB)
    catalog.record_archive(deleted, "bob-old", session_key=BOB)
    rows = [hit("bob", end=1), hit("bob", end=2),
            {**hit("old"), "path": "sessions/main/" + reset},
            {**hit("old"), "path": "sessions/main/" + deleted}]
    recall = {"scope": "same-agent-private", "corpus": "sessions", "anchorSessionKey": BOB}
    assert filtered(rows, catalog, recall=recall) == [rows[0], rows[2]]


def test_invalid_recall_keeps_only_configured_memory_and_lazy_memory_only_path(tmp_path):
    catalog = catalog_at(tmp_path)
    session(catalog, BOB, "bob")
    memory_row = {"source": "memory", "path": "MEMORY.md", "snippet": "workspace"}
    rows = [memory_row, hit("bob")]
    assert filtered(rows, catalog, recall={}) == []
    assert filtered(rows, catalog, recall={"corpus": "configured"}) == [memory_row]
    ctx = SessionVisibilityContext(load_catalog=lambda: pytest.fail("Memory-only recall must not load the catalog"))
    assert filter_memory_search_hits_by_session_visibility([memory_row], context=ctx) == [memory_row]


def test_row_checker_preserves_denial_evidence_and_native_child_override():
    policy = SessionVisibilityPolicy(visibility="tree", agent_to_agent_enabled=False)
    denied = session_visibility_decision(
        {"key": "agent:peer:direct:other"}, policy=policy, requester_session_key=BOB,
    )
    assert denied == {
        "allowed": False, "status": "forbidden", "reasonCode": "cross_agent_visibility_restricted",
        "policyRefs": ["tools.sessions.visibility"],
        "contextFieldsUsed": ["requesterAgentId", "targetAgentId", "visibility"], "missingEvidence": [],
    }
    assert session_visibility_decision(
        {"key": "agent:peer:subagent:child", "spawnedBy": BOB}, policy=policy,
        requester_session_key=BOB,
    ) == {"allowed": True}


def test_requester_owner_mismatch_keeps_native_error_metadata_after_memory_early_return(tmp_path):
    catalog = catalog_at(tmp_path)
    session(catalog, BOB, "bob")
    ctx = context(catalog, configured_agent_ids=("main", "peer"))
    with pytest.raises(MemoryToolError) as raised:
        filter_memory_search_hits_by_session_visibility(
            [hit("bob")], context=ctx, agent_id="main", requester_session_key="agent:peer:main",
        )
    assert raised.value.name == "AgentSelectionRequiredError"
    assert raised.value.code == "AGENT_SELECTION_REQUIRED"
    assert raised.value.agentIds == ["main", "peer"]
    assert raised.value.surface == "session agent resolution"
    assert raised.value.hint == 'The agent-scoped session key belongs to "peer", not "main".'
    assert not hasattr(raised.value, "status")
    memory = {"source": "memory", "path": "MEMORY.md", "snippet": "workspace memory"}
    assert filter_memory_search_hits_by_session_visibility(
        [memory], context=ctx, agent_id="main", requester_session_key="agent:peer:main",
    ) == [memory]
    prepared_access = replace(ctx, policy=replace(ctx.policy, agent_to_agent_enabled=False))
    assert resolve_session_tool_access(
        prepared_access, requester_session_key="agent:peer:main", target_session_key=BOB,
        agent_id="main",
    ) == {"allowed": True}


def test_real_source_reads_follow_current_identity_and_keep_tombstones_separate(tmp_path):
    catalog = catalog_at(tmp_path)
    session(catalog, BOB, "first", "Original source.")
    ctx = context(catalog, "self")
    before = read_visible_session_source(catalog, ctx, requester_session_key=BOB, target_session_key=BOB)
    assert before == {"access": {"allowed": True}, "sessionId": "first", "events": [event("Original source.")]}
    catalog.tombstone_session("first")
    assert read_visible_session_source(catalog, ctx, requester_session_key=BOB, target_session_key=BOB) == before
    session(catalog, BOB, "second", "Current source.")
    after = read_visible_session_source(catalog, ctx, requester_session_key=BOB, target_session_key=BOB)
    assert after == {"access": {"allowed": True}, "sessionId": "second", "events": [event("Current source.")]}
    denied = read_visible_session_source(catalog, ctx, requester_session_key=ALICE, target_session_key=BOB)
    assert denied["events"] == [] and "sessionId" not in denied
    assert denied["access"]["reasonCode"] == "self_visibility_restricted"


def test_source_describe_proves_lineage_and_expected_identity_is_revalidated(tmp_path):
    catalog = catalog_at(tmp_path)
    child = "agent:main:subagent:child"
    session(catalog, child, "first", parentSessionKey=BOB)
    ctx = context(catalog, "tree")
    assert resolve_session_tool_access(ctx, requester_session_key=BOB, target_session_key=child) == {
        "allowed": True, "expectedSessionId": "first",
    }
    granted = replace(ctx, scoped_access=lambda requester, target: "first")
    session(catalog, child, "second", parentSessionKey=BOB)
    with pytest.raises(MemoryToolError, match="changed after access was granted"):
        read_visible_session_source(catalog, granted, requester_session_key=BOB, target_session_key=child)


def test_lookup_failure_preserves_complete_denial_and_cannot_override_self(tmp_path):
    catalog = catalog_at(tmp_path)
    ctx = replace(context(catalog, "tree"), load_spawned_keys=lambda requester: SessionOwnershipLookup(
        failure_kind="credentials",
    ))
    target = "agent:main:subagent:unknown"
    assert resolve_session_tool_access(ctx, requester_session_key=BOB, target_session_key=target) == {
        "allowed": False, "status": "forbidden", "reasonCode": "session_ownership_lookup_failed_credentials",
        "policyRefs": ["tools.sessions.visibility"], "contextFieldsUsed": ["requesterSessionKey", "targetSessionKey"],
        "missingEvidence": ["session.owner"],
    }
    narrowed = replace(ctx, policy=replace(ctx.policy, visibility="self"))
    assert resolve_session_tool_access(narrowed, requester_session_key=BOB, target_session_key=target)["reasonCode"] == "self_visibility_restricted"


def test_source_policy_controls_real_index_admission_and_ordinary_queries(tmp_path):
    catalog = catalog_at(tmp_path)
    session(catalog, BOB, "bob")
    policy = resolve_memory_search_source_policy(remember_across_conversations=True)
    assert policy == {"sources": ["memory", "sessions"], "searchSources": ["memory"], "sessionMemory": True}
    memory = Memory.from_workspace(
        tmp_path, initialize=False, session_catalog=catalog, source_policy=policy,
        config=MemoryConfig(workspace_dir=tmp_path, flags=FeatureFlags(vector_search=False)),
    )
    assert memory.store.count_chunks() == 1
    assert memory.search("Cobalt", agent_session_key=BOB)["results"] == []
    result = memory.search("Cobalt", agent_session_key=BOB, context=MemorySearchToolContext(
        conversation_recall={"scope": "same-agent-private", "corpus": "configured", "anchorSessionKey": ALICE},
    ))
    assert result["results"] == []


def test_policy_change_revokes_cooldown_without_catalog_revision_churn(tmp_path, monkeypatch):
    catalog = catalog_at(tmp_path)
    memory = Memory.from_workspace(
        tmp_path, initialize=False, session_catalog=catalog,
        config=MemoryConfig(workspace_dir=tmp_path, flags=FeatureFlags(vector_search=False)),
    )
    attempts = []

    def fail(*args, **kwargs):
        attempts.append(True)
        raise RuntimeError("provider failed")

    monkeypatch.setattr(memory.store, "search", fail)
    broad = MemorySearchToolContext(session_visibility=context(catalog))
    assert execute_memory_search_tool(memory.config, memory.store, {"query": "x"}, context=broad)["unavailable"]
    session(catalog, BOB, "bob")
    assert execute_memory_search_tool(memory.config, memory.store, {"query": "x"}, context=broad)["unavailable"]
    assert len(attempts) == 1
    narrowed = replace(broad, session_visibility=context(catalog, "self"))
    assert execute_memory_search_tool(memory.config, memory.store, {"query": "x"}, context=narrowed)["unavailable"]
    assert len(attempts) == 2


def test_sessions_only_recall_never_salvages_memory_partial_after_deadline(tmp_path, monkeypatch):
    catalog = catalog_at(tmp_path)
    session(catalog, BOB, "bob")
    (tmp_path / "MEMORY.md").write_text("Cobalt workspace evidence.\n", encoding="utf-8")
    memory = Memory.from_workspace(
        tmp_path, initialize=False, session_catalog=catalog,
        config=MemoryConfig(workspace_dir=tmp_path, flags=FeatureFlags(vector_search=False)),
    )
    now = [0]
    published = []

    def search(query, **options):
        rows = [{"path": "MEMORY.md", "source": "memory", "startLine": 1,
                 "endLine": 1, "score": 0.9, "snippet": "Cobalt workspace evidence."}]
        options["on_partial_results"](rows)
        published.extend(rows)
        # The real settlement owner must notice elapsed absolute time even if
        # this host scheduler has not dispatched its pending timer callback.
        now[0] = 30_000
        return []

    monkeypatch.setattr(memory.store, "search", search)
    execution = MemoryToolDeadlineContext(
        clock=lambda: now[0], schedule=lambda delay, callback: lambda: None,
    )
    result = memory.search("Cobalt", agent_session_key=BOB, context=MemorySearchToolContext(
        clock=lambda: now[0], execution=execution,
        conversation_recall={"scope": "same-agent-private", "corpus": "sessions", "anchorSessionKey": BOB},
    ))
    assert published and published[0]["source"] == "memory"
    assert result["timedOut"] is True
    assert result["results"] == []
    assert "partial" not in result
