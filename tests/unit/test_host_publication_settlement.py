"""Actual publisher faults through host admission, indexing and acknowledgment."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import threading

import pytest

from memory_core.config import MemoryConfig
from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
from memory_core.flags import FeatureFlags
from memory_core.host.lifecycle import HostModelResult, HostSessionRunner
from memory_core.host.session import SessionState
from memory_core.memory_write_provenance import MemoryWriteProvenanceObserver
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.turn_tool_dispatch import TurnTool


NOW = 1_794_182_400_000
KEY = "agent:main:dm:publication"
ID = "publication"


class LiteralIOError(OSError):
    name = "Error"

    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _runner(root):
    config = MemoryConfig(workspace_dir=root / "workspace",
        flags=FeatureFlags(vector_search=False, temporal_decay=False))
    return HostSessionRunner.open(config.workspace_dir,
        catalog=MemorySessionCatalog(root / "sessions.sqlite", clock_ms=lambda: NOW),
        session=SessionState.new(session_key=KEY, session_id=ID), config=config)


def _target(runner):
    path = runner.kit.memory.workspace.root / "MEMORY.md"
    path.write_text("# Memory\n\n## Notes\n- original\n")
    return path


def _fault(monkeypatch, target, *, stage):
    actual = os.replace

    def replace(source, destination):
        if Path(destination) != target:
            return actual(source, destination)
        if stage == "refused":
            raise LiteralIOError("EACCES", "literal rename refusal")
        result = actual(source, destination)
        if stage == "uncertain":
            raise LiteralIOError("EIO", "literal dispatched rename failure")
        external = target.parent / "external-replacement"
        external.write_text("external survivor COBALT-942\n")
        actual(external, target)
        return result

    monkeypatch.setattr(os, "replace", replace)
    return actual


def _call(turn, name, arguments, identifier):
    turn.record_message({"role": "assistant", "content": [{"type": "toolCall",
        "id": identifier, "name": name, "arguments": deepcopy(arguments)}]})
    return turn.dispatch(identifier, name, arguments)


async def _save(turn):
    _call(turn, "add_memory_entry", {"section": "Notes", "text": "new"}, "save")
    return HostModelResult()


def _auxiliary(runner):
    return runner.catalog.get_session_entry(KEY)["sdkHostLifecycle"]


@pytest.mark.parametrize("stage", ["committed", "uncertain"])
def test_actual_publisher_state_survives_host_settlement_and_untrusted_provenance(tmp_path, monkeypatch, stage):
    async def scenario():
        runner = _runner(tmp_path)
        path = _target(runner)
        _fault(monkeypatch, path, stage=stage)
        outcome = await runner.run_turn("Save new", execute=_save, request_id="actual-fault", sender_is_owner=False)
        assert outcome.tools[0]["result"]["publication"] == stage
        assert outcome.memory_publication == stage
        assert outcome.memory_writes_committed is (stage == "committed")
        assert outcome.index_status == "ready" and not outcome.ready
        failure = next(item for item in outcome.failures if item.phase == "tool")
        assert failure.publication == stage and failure.committed is (stage == "committed")
        provenance = runner.artifact_provenance.read(workspace_dir=path.parent, relative_path=path.name)
        assert provenance is not None and provenance.origin_class == "untrusted"
        if stage == "committed":
            # The publisher knows its rename returned; it does not promise the
            # requested content survived the following external replacement.
            assert path.read_text() == "external survivor COBALT-942\n"
            assert provenance.file_hash != hashlib.sha256(path.read_bytes()).hexdigest()
            assert "pendingMemoryPublication" not in _auxiliary(runner)
        else:
            assert "- new\n" in path.read_text()
            assert _auxiliary(runner)["pendingMemoryPublication"] == {
                "turnId": "actual-fault", "publication": "uncertain",
                "workspace": str(path.parent), "indexPath": str(runner.kit.memory.store.path),
                "provenancePath": str(runner.artifact_provenance.path)}

    asyncio.run(scenario())


def test_uncertainty_wins_aggregate_but_keeps_other_known_commit_and_stops_more_dispatches(tmp_path, monkeypatch):
    async def scenario():
        runner = _runner(tmp_path)
        path = _target(runner)
        _fault(monkeypatch, path, stage="uncertain")

        async def save(turn):
            assert _call(turn, "append_daily_note", {"text": "Known committed daily fact"}, "daily")["status"] == "ok"
            assert _call(turn, "add_memory_entry", {"section": "Notes", "text": "new"}, "fault")["publication"] == "uncertain"
            turn.record_message({"role": "assistant", "content": [{"type": "toolCall", "id": "later",
                "name": "append_daily_note", "arguments": {"text": "Must not execute"}}]})
            with pytest.raises(RuntimeError, match="publication is uncertain"):
                turn.dispatch("later", "append_daily_note", {"text": "Must not execute"})
            return HostModelResult()

        outcome = await runner.run_turn("Save both", execute=save, request_id="mixed")
        assert outcome.memory_publication == "uncertain" and outcome.memory_writes_committed
        assert len(outcome.tools) == 2
        assert "Must not execute" not in (path.parent / "memory/2026-11-09.md").read_text()

    asyncio.run(scenario())


def test_fresh_runner_blocks_until_current_state_acknowledgment_indexes_without_replaying_write(tmp_path, monkeypatch):
    async def scenario():
        runner = _runner(tmp_path)
        path = _target(runner)
        original = _fault(monkeypatch, path, stage="uncertain")
        await runner.run_turn("Save new", execute=_save, request_id="pending")
        monkeypatch.setattr(os, "replace", original)
        path.write_text("current acknowledged survivor JADE-385\n")
        fresh = _runner(tmp_path)
        before = fresh.catalog.read_continuation(ID, session_key=KEY)["events"]
        called = False

        async def followup(turn):
            nonlocal called
            called = True
            return HostModelResult()

        blocked = await fresh.run_turn("Next", execute=followup)
        assert not called and not blocked.transcript_committed
        assert blocked.memory_publication == "uncertain"
        assert fresh.catalog.read_continuation(ID, session_key=KEY)["events"] == before
        with pytest.raises(RuntimeError, match="No matching"):
            await fresh.acknowledge_memory_publication(expected_turn_id="stale")
        assert _auxiliary(fresh)["pendingMemoryPublication"]["turnId"] == "pending"
        await fresh.acknowledge_memory_publication(expected_turn_id="pending")
        auxiliary = _auxiliary(fresh)
        assert "pendingMemoryPublication" not in auxiliary and auxiliary["needsIndex"] is False
        assert auxiliary["lastMemoryPublicationAcknowledgment"] == {"turnId": "pending", "acknowledgedAt": NOW,
            "workspace": str(path.parent), "indexPath": str(fresh.kit.memory.store.path),
            "provenancePath": str(fresh.artifact_provenance.path)}
        assert fresh.catalog.read_continuation(ID, session_key=KEY)["events"] == before
        # Actual source content, not an assertion that the original '- new'
        # survived, supplies the acknowledgment's freshly published index.
        found = fresh.kit.dispatch("memory_search", {"query": "JADE-385", "minScore": 0}, session=fresh.session)
        assert any("JADE-385" in hit["snippet"] for hit in found["results"])
        assert (await fresh.run_turn("Next", execute=followup)).ready and called
        assert "new" not in path.read_text()

    asyncio.run(scenario())


def test_failed_acknowledgment_keeps_pending_marker_and_next_admission_blocked(tmp_path, monkeypatch):
    async def scenario():
        runner = _runner(tmp_path)
        path = _target(runner)
        original = _fault(monkeypatch, path, stage="uncertain")
        await runner.run_turn("Save", execute=_save, request_id="pending")
        monkeypatch.setattr(os, "replace", original)
        monkeypatch.setattr(runner.kit.memory.store, "reindex", lambda *_: (_ for _ in ()).throw(OSError("actual index source failed")))
        with pytest.raises(OSError, match="index source failed"):
            await runner.acknowledge_memory_publication(expected_turn_id="pending")
        assert _auxiliary(runner)["pendingMemoryPublication"]["turnId"] == "pending"
        assert "lastMemoryPublicationAcknowledgment" not in _auxiliary(runner)
        blocked = await runner.run_turn("Next", execute=_save)
        assert not blocked.transcript_committed and blocked.memory_publication == "uncertain"

    asyncio.run(scenario())


def test_uncertainty_is_saved_before_a_failed_index_attempt(tmp_path, monkeypatch):
    async def scenario():
        runner = _runner(tmp_path)
        path = _target(runner)
        _fault(monkeypatch, path, stage="uncertain")
        monkeypatch.setattr(runner.kit.memory.store, "reindex", lambda *_: (_ for _ in ()).throw(OSError("index unavailable")))
        outcome = await runner.run_turn("Save", execute=_save, request_id="pending")
        assert outcome.index_status == "failed" and outcome.memory_publication == "uncertain"
        assert _auxiliary(runner)["needsIndex"] is True
        assert _auxiliary(runner)["pendingMemoryPublication"]["turnId"] == "pending"
        fresh = _runner(tmp_path)
        blocked = await fresh.run_turn("Next", execute=_save)
        assert not blocked.transcript_committed and blocked.memory_publication == "uncertain"

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["pending-turn", "identity"])
def test_acknowledgment_cannot_clear_a_changed_owner_after_real_indexing(tmp_path, monkeypatch, change):
    async def scenario():
        runner = _runner(tmp_path)
        path = _target(runner)
        original = _fault(monkeypatch, path, stage="uncertain")
        await runner.run_turn("Save", execute=_save, request_id="pending")
        monkeypatch.setattr(os, "replace", original)
        actual = runner.kit.memory.store.reindex

        def index(workspace):
            result = actual(workspace)
            entry = runner.catalog.get_session_entry(KEY)
            if change == "identity":
                entry["sessionId"] = "rotated-owner"
            else:
                entry["sdkHostLifecycle"]["pendingMemoryPublication"]["turnId"] = "newer-pending"
            runner.catalog.upsert_session(KEY, entry)
            return result

        monkeypatch.setattr(runner.kit.memory.store, "reindex", index)
        with pytest.raises(RuntimeError, match="changed"):
            await runner.acknowledge_memory_publication(expected_turn_id="pending")
        current = runner.catalog.get_session_entry(KEY)
        assert "lastMemoryPublicationAcknowledgment" not in current["sdkHostLifecycle"]
        assert current["sdkHostLifecycle"]["pendingMemoryPublication"]["turnId"] == (
            "newer-pending" if change == "pending-turn" else "pending")

    asyncio.run(scenario())


def test_cancelled_acknowledgment_holds_lane_until_actual_index_source_finishes(tmp_path, monkeypatch):
    async def scenario():
        runner = _runner(tmp_path)
        path = _target(runner)
        original = _fault(monkeypatch, path, stage="uncertain")
        await runner.run_turn("Save", execute=_save, request_id="pending")
        monkeypatch.setattr(os, "replace", original)
        started, release = threading.Event(), threading.Event()
        actual = runner.kit.memory.store.reindex

        def index(workspace):
            started.set()
            assert release.wait(5)
            return actual(workspace)

        monkeypatch.setattr(runner.kit.memory.store, "reindex", index)
        acknowledgment = asyncio.create_task(runner.acknowledge_memory_publication(expected_turn_id="pending"))
        try:
            assert await asyncio.wait_for(asyncio.to_thread(started.wait, 5), 6)
            acknowledgment.cancel()
            followup = asyncio.create_task(runner.run_turn("Next", execute=_save))
            await asyncio.sleep(0)
            assert not acknowledgment.done() and not followup.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await acknowledgment
        blocked = await followup
        assert not blocked.transcript_committed and blocked.memory_publication == "uncertain"
        assert _auxiliary(runner)["pendingMemoryPublication"]["turnId"] == "pending"

    asyncio.run(scenario())


def test_true_rejected_rename_rolls_back_provenance_and_has_no_publication_claim(tmp_path, monkeypatch):
    async def scenario():
        runner = _runner(tmp_path)
        path = _target(runner)
        before = path.read_text()
        _fault(monkeypatch, path, stage="refused")
        outcome = await runner.run_turn("Save", execute=_save, sender_is_owner=False)
        assert outcome.memory_publication == "none" and not outcome.memory_writes_committed
        assert path.read_text() == before
        assert runner.artifact_provenance.read(workspace_dir=path.parent, relative_path=path.name) is None
        assert "publication" not in outcome.tools[0]["result"]
        assert "pendingMemoryPublication" not in _auxiliary(runner)

    asyncio.run(scenario())


def test_forged_publication_attribute_does_not_prevent_original_observer_rollback(tmp_path):
    runner = _runner(tmp_path)
    path = _target(runner)
    observer = MemoryWriteProvenanceObserver(store=runner.artifact_provenance,
        mutation_root=path.parent, workspace_dir=path.parent, resolve_origin_class=lambda: "untrusted")
    forged = RuntimeError("did not publish")
    forged.publication = "committed"

    def reject():
        raise forged

    with pytest.raises(RuntimeError) as caught:
        observer.write(absolute_path=path, content_before=path.read_text(), content_after="never published", commit=reject)
    assert caught.value is forged
    assert runner.artifact_provenance.read(workspace_dir=path.parent, relative_path=path.name) is None
    assert "never published" not in path.read_text()


@pytest.mark.parametrize("publication", ["committed", "uncertain"])
@pytest.mark.parametrize("tool_name", ["add_memory_entry", "write"])
def test_external_tool_data_cannot_mint_publisher_receipts(tmp_path, publication, tool_name):
    async def scenario():
        config = MemoryConfig(workspace_dir=tmp_path / "workspace",
            flags=FeatureFlags(vector_search=False, curated_memory_writes=False))
        external_result = {"status": "error", "error": "External diagnostic", "publication": publication,
                           "memoryPublicationOwner": True, "afterWriteError": "External diagnostic data"}
        # The same public name is legal when builtin curation is disabled. It
        # still selects the extra registration, never the real publisher owner.
        runner = HostSessionRunner.open(config.workspace_dir,
            catalog=MemorySessionCatalog(tmp_path / "sessions.sqlite", clock_ms=lambda: NOW),
            session=SessionState.new(session_key=KEY, session_id=ID), config=config,
            extra_tools=[TurnTool(tool_name, lambda _id, _args: deepcopy(external_result), "network")])

        async def execute(turn):
            assert _call(turn, tool_name, {"section": "Notes", "text": "external"}, "external") == external_result
            return HostModelResult()

        outcome = await runner.run_turn("Use external tool", execute=execute)
        assert outcome.memory_publication == "none" and not outcome.memory_writes_committed
        assert outcome.index_status == "ready"
        assert outcome.tools[0]["result"] == external_result
        assert outcome.tools[0]["memoryPublicationOwner"] is False
        assert all(item.publication is None and not item.committed for item in outcome.failures)
        assert "pendingMemoryPublication" not in _auxiliary(runner)
        assert not (runner.kit.memory.workspace.root / "MEMORY.md").exists()

    asyncio.run(scenario())


@pytest.mark.parametrize("different", ["workspace", "index", "provenance"])
def test_acknowledgment_refuses_another_workspace_or_index_owner(tmp_path, monkeypatch, different):
    async def scenario():
        runner = _runner(tmp_path)
        target = _target(runner)
        original = _fault(monkeypatch, target, stage="uncertain")
        await runner.run_turn("Save", execute=_save, request_id="pending")
        monkeypatch.setattr(os, "replace", original)
        workspace = tmp_path / "another-workspace" if different == "workspace" else target.parent
        config = MemoryConfig(workspace_dir=workspace,
            store_path=tmp_path / "another-index.sqlite" if different == "index" else None,
            flags=FeatureFlags(vector_search=False))
        other = HostSessionRunner.open(workspace, config=config, catalog=runner.catalog,
            session=SessionState.new(session_key=KEY, session_id=ID),
            artifact_provenance=MemoryArtifactProvenanceStore(tmp_path / "another-provenance.sqlite")
                if different == "provenance" else None)
        with pytest.raises(RuntimeError, match="different workspace, index or provenance"):
            await other.acknowledge_memory_publication(expected_turn_id="pending")
        assert _auxiliary(runner)["pendingMemoryPublication"]["turnId"] == "pending"
        assert "lastMemoryPublicationAcknowledgment" not in _auxiliary(runner)

    asyncio.run(scenario())
