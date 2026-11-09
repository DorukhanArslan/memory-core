"""A shared managed host owner keeps transcript publication explicitly pending."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import os
from pathlib import Path
import threading

import pytest

from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.host.kit import HostKit
from memory_core.host.lifecycle import HostModelResult, HostSessionRunner
from memory_core.host.managed_session import ManagedHostSession, ManagedHostSessionRunner
from memory_core.host.session import SessionState
from memory_core.host.session_publication import SessionPublicationController
from memory_core.index.sqlite_store import MemoryIndexRequiresFullReindexError
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.session_visibility import resolve_memory_search_source_policy


NOW = 1_794_182_400_000
KEY = "agent:main:dm:managed-owner"
ID = "managed-owner"
STATE = SessionState.new(session_key=KEY, session_id=ID)


def test_managed_runner_rejects_inherited_eager_open_before_any_workspace_io(tmp_path):
    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite", clock_ms=lambda: NOW)
    root = tmp_path / "must-stay-absent"
    config = MemoryConfig(workspace_dir=root, flags=FeatureFlags(vector_search=False))
    before = catalog.snapshot()
    with pytest.raises(TypeError, match=r"ManagedHostSession.open"):
        ManagedHostSessionRunner.open(root, catalog=catalog, session=STATE, config=config)
    assert not root.exists()
    assert catalog.snapshot() == before


class ManualCall:
    def __init__(self, callback):
        self.callback = callback
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


class ManualScheduler:
    def __init__(self):
        self.calls = []

    def __call__(self, delay, callback):
        call = ManualCall(callback)
        self.calls.append((delay, call))
        return call


def _owner(tmp_path, *, source_policy=None):
    root = tmp_path / "workspace"
    root.mkdir()
    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite", clock_ms=lambda: NOW)
    config = MemoryConfig(workspace_dir=root, store_path=tmp_path / "index.sqlite",
        citation_mode="off", session_search=True,
        flags=FeatureFlags(vector_search=False, temporal_decay=False))
    policy = (resolve_memory_search_source_policy(["memory"], remember_across_conversations=True)
        if source_policy is None else source_policy)
    scheduler = ManualScheduler()
    owner = ManagedHostSession.open(root, catalog=catalog, config=config,
        source_policy=policy, scheduler=scheduler,
        identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY, now_ms=lambda: NOW)
    return owner, scheduler


def _call(turn, name, arguments, identifier="write"):
    turn.record_message({"role": "assistant", "content": [{"type": "toolCall",
        "id": identifier, "name": name, "arguments": deepcopy(arguments)}]})
    return turn.dispatch(identifier, name, arguments)


def _answer(turn):
    turn.record_message({"role": "assistant", "content": [{"type": "text", "text": "Saved."}]})
    return HostModelResult()


async def _save(turn):
    _call(turn, "append_daily_note", {"text": "The managed cedar token is CEDAR-731."})
    return _answer(turn)


def _auxiliary(owner):
    return owner.catalog.get_session_entry(KEY)["sdkHostLifecycle"]


def _session_rows(owner):
    return [row for row in owner.store.read_published_index()["chunks"] if row["source"] == "sessions"]


def _seed_transcript(owner):
    owner.catalog.upsert_session(KEY, {"sessionId": ID, "updatedAt": NOW})
    owner.catalog.append_message(ID, {"role": "user", "content": "An older published violet token."},
        session_key=KEY, event_id="older-user", now_ms=NOW)


def test_cold_curator_commits_real_bytes_without_claiming_index_publication(tmp_path):
    owner, _ = _owner(tmp_path)
    try:
        assert owner.store.read_index_meta() is None
        assert owner.controller.status()["notStarted"] is True
        result = owner.kit.dispatch("append_daily_note", {"text": "Cold real cedar note."}, session=STATE)

        assert result["status"] == "ok" and result["indexStatus"] == "pending"
        assert "afterWriteError" not in result
        assert (owner.kit.memory.workspace.root / "memory/2026-11-09.md").read_text() == "Cold real cedar note.\n"
        assert owner.store.read_index_meta() is None
        assert owner.store.read_published_index()["chunks"] == []
        assert owner.controller.status()["notStarted"] is True
        assert owner.publication_status()["ready"] is False
    finally:
        owner.close()


def test_cold_turn_and_fresh_runner_preserve_deferred_memory_and_session_markers(tmp_path):
    async def scenario():
        owner, _ = _owner(tmp_path)
        try:
            runner = owner.runner(STATE)
            first = await runner.run_turn("Remember the managed cedar token.", execute=_save, request_id="cold-save")
            assert first.transcript_committed and first.memory_writes_committed
            assert first.index_status == "pending" and not first.ready
            assert not first.failures
            assert first.tools[0]["result"]["indexStatus"] == "pending"
            auxiliary = _auxiliary(owner)
            assert auxiliary["publicationMode"] == "managed"
            assert auxiliary["needsMemoryIndex"] is True
            assert auxiliary["needsSessionIndex"] is True
            assert auxiliary["needsIndex"] is True

            fresh = owner.runner(STATE)
            assert fresh.kit is runner.kit is owner.kit
            assert fresh.kit.memory.store is owner.store
            async def answer(turn):
                return _answer(turn)
            second = await fresh.run_turn("Continue before the first search.", execute=answer)
            assert second.transcript_committed and second.index_status == "pending"
            assert not second.ready and not second.failures
            assert owner.store.read_index_meta() is None
            assert owner.controller.status()["notStarted"] is True
            assert _auxiliary(owner)["needsMemoryIndex"] is True
            assert _auxiliary(owner)["needsSessionIndex"] is True
        finally:
            await owner.aclose()

    asyncio.run(scenario())


def test_explicit_reindex_publishes_real_sources_and_new_runner_reuses_started_owner(tmp_path):
    owner, _ = _owner(tmp_path)
    try:
        _seed_transcript(owner)
        (owner.kit.memory.workspace.root / "MEMORY.md").write_text("Published durable cedar memory.\n")
        owner.reindex(force=True)
        status = owner.publication_status()
        assert status["memoryIndexStatus"] == status["sessionIndexStatus"] == status["indexStatus"] == "ready"
        assert status["sessionPending"] is False and status["ready"] is True
        assert owner.store.index_identity() == {"status": "valid"}
        assert {row["source"] for row in owner.store.read_published_index()["chunks"]} == {"memory", "sessions"}
        before = owner.controller.status()

        first, second = owner.runner(STATE), owner.runner(STATE)
        assert first.kit is second.kit is owner.kit
        assert first.catalog is second.catalog is owner.catalog
        assert first.kit.memory.store is owner.store
        assert owner.controller.status()["jobCount"] == before["jobCount"]
        assert sum(job["reason"] == "startup" for job in before["jobs"]) == 1
    finally:
        owner.close()


def test_warm_turn_publishes_memory_scope_and_preserves_unpublished_session_delta(tmp_path, monkeypatch):
    async def scenario():
        owner, scheduler = _owner(tmp_path)
        try:
            _seed_transcript(owner)
            owner.reindex()
            before = _session_rows(owner)
            assert before
            operations_before = owner.store.lifecycle_snapshot()["operationCount"]

            def forbid_full(*_args, **_kwargs):
                raise AssertionError("A managed turn must not publish all transcript sources")
            monkeypatch.setattr(owner.store, "reindex", forbid_full)
            runner = owner.runner(STATE)
            outcome = await runner.run_turn("Remember a new managed cedar token.", execute=_save)

            assert outcome.transcript_committed and outcome.memory_writes_committed
            assert outcome.index_status == "pending" and not outcome.ready and not outcome.failures
            assert _session_rows(owner) == before
            assert any("CEDAR-731" in row["text"] for row in owner.store.read_published_index()["chunks"]
                if row["source"] == "memory")
            status = owner.publication_status()
            assert status["memoryIndexStatus"] == "ready" and status["sessionIndexStatus"] == "pending"
            assert status["sessionPending"] is True and status["ready"] is False
            auxiliary = _auxiliary(owner)
            assert auxiliary["needsMemoryIndex"] is False
            assert auxiliary["needsSessionIndex"] is True and auxiliary["needsIndex"] is True
            assert scheduler.calls
            operations = [row for row in owner.store.lifecycle_snapshot()["operations"] if row["id"] > operations_before]
            assert not any(row["name"] == "reindex" for row in operations)
            assert any(row["name"] == "reindex-sources" and row["request"]["sources"] == ["memory"]
                for row in operations)

            async def answer(turn):
                return _answer(turn)
            continued = await owner.runner(STATE).run_turn("Continue with the same pending session publication.", execute=answer)
            assert continued.transcript_committed and continued.index_status == "pending"
            assert not continued.failures and _session_rows(owner) == before
        finally:
            await owner.aclose()

    asyncio.run(scenario())


def test_synchronize_publishes_the_actual_pending_transcript_and_reports_ready(tmp_path):
    async def scenario():
        owner, _ = _owner(tmp_path)
        try:
            owner.reindex()
            outcome = await owner.runner(STATE).run_turn("Remember the managed cedar token.", execute=_save)
            assert outcome.index_status == "pending" and _session_rows(owner) == []

            status = await asyncio.to_thread(owner.synchronize, timeout=5)

            assert status["ready"] is True and status["indexStatus"] == "ready"
            assert status["memoryIndexStatus"] == status["sessionIndexStatus"] == "ready"
            assert status["sessionPending"] is False
            assert any("Remember the managed cedar token." in row["text"] for row in _session_rows(owner))
            assert owner.controller.status()["generation"] == owner.controller.status()["publishedGeneration"]
        finally:
            await owner.aclose()

    asyncio.run(scenario())


def test_failed_memory_publication_stays_dirty_and_repairs_before_next_admission(tmp_path, monkeypatch):
    async def scenario():
        owner, _ = _owner(tmp_path)
        try:
            owner.reindex()
            publish = owner.store.reindex_sources
            def fail_memory(workspace, **options):
                if set(options["sources"]) == {"memory"}:
                    raise OSError("scoped memory publication unavailable")
                return publish(workspace, **options)
            monkeypatch.setattr(owner.store, "reindex_sources", fail_memory)
            runner = owner.runner(STATE)
            failed = await runner.run_turn("Remember the cedar token despite an index fault.", execute=_save)
            assert failed.transcript_committed and failed.memory_writes_committed
            assert failed.index_status == "failed" and not failed.ready
            assert "scoped memory publication unavailable" in failed.tools[0]["result"]["afterWriteError"]
            assert _auxiliary(owner)["needsMemoryIndex"] is True
            assert "CEDAR-731" in (owner.kit.memory.workspace.root / "memory/2026-11-09.md").read_text()

            admitted = False
            async def answer(turn):
                nonlocal admitted
                admitted = True
                return _answer(turn)
            blocked = await owner.runner(STATE).run_turn("Wait for the failed memory refresh.", execute=answer)
            assert not admitted and not blocked.transcript_committed
            assert blocked.index_status == "failed" and blocked.failures[0].phase == "index-repair"

            monkeypatch.setattr(owner.store, "reindex_sources", publish)
            recovered = await owner.runner(STATE).run_turn("Continue after real scoped repair.", execute=answer)
            assert admitted and recovered.transcript_committed and not recovered.failures
            assert recovered.index_status == "pending"
            assert _auxiliary(owner)["needsMemoryIndex"] is False
            assert _auxiliary(owner)["needsSessionIndex"] is True
        finally:
            await owner.aclose()

    asyncio.run(scenario())


def test_acknowledgment_publishes_memory_scope_and_preserves_session_dirtiness(tmp_path, monkeypatch):
    async def scenario():
        owner, _ = _owner(tmp_path)
        try:
            _seed_transcript(owner)
            target = owner.kit.memory.workspace.root / "MEMORY.md"
            target.write_text("# Memory\n\n## Notes\n- original\n")
            owner.reindex()
            before = _session_rows(owner)
            actual_replace = os.replace

            class UncertainRename(OSError):
                name = "Error"
                code = "EIO"

            def uncertain_replace(source, destination):
                result = actual_replace(source, destination)
                if Path(destination) == target:
                    raise UncertainRename("actual rename completed before the reported fault")
                return result
            monkeypatch.setattr(os, "replace", uncertain_replace)

            async def save(turn):
                _call(turn, "add_memory_entry", {"section": "Notes", "text": "uncertain cedar token"})
                return _answer(turn)
            runner = owner.runner(STATE)
            outcome = await runner.run_turn("Save the uncertain cedar token.", execute=save, request_id="uncertain-write")
            assert outcome.memory_publication == "uncertain" and not outcome.ready
            assert _auxiliary(owner)["pendingMemoryPublication"]["turnId"] == "uncertain-write"
            monkeypatch.setattr(os, "replace", actual_replace)

            def forbid_full(*_args, **_kwargs):
                raise AssertionError("Acknowledgment must not publish deferred session sources")
            monkeypatch.setattr(owner.store, "reindex", forbid_full)
            await owner.runner(STATE).acknowledge_memory_publication(expected_turn_id="uncertain-write")

            auxiliary = _auxiliary(owner)
            assert "pendingMemoryPublication" not in auxiliary
            assert auxiliary["needsMemoryIndex"] is False
            assert auxiliary["needsSessionIndex"] is True and auxiliary["needsIndex"] is True
            assert _session_rows(owner) == before
            assert any("uncertain cedar token" in row["text"] for row in owner.store.read_published_index()["chunks"]
                if row["source"] == "memory")
        finally:
            await owner.aclose()

    asyncio.run(scenario())


def test_default_runner_remains_eager_and_returns_ready_after_real_full_publication(tmp_path):
    async def scenario():
        root = tmp_path / "workspace"
        config = MemoryConfig(workspace_dir=root, flags=FeatureFlags(vector_search=False, temporal_decay=False))
        runner = HostSessionRunner.open(root, config=config,
            catalog=MemorySessionCatalog(tmp_path / "catalog.sqlite", clock_ms=lambda: NOW),
            session=STATE, now_ms=lambda: NOW)
        assert runner.kit.memory.store.read_index_meta() is not None
        outcome = await runner.run_turn("Remember the eager cedar token.", execute=_save)
        assert outcome.ready and outcome.index_status == "ready"
        assert runner.catalog.get_session_entry(KEY)["sdkHostLifecycle"]["needsIndex"] is False

    asyncio.run(scenario())


def test_returned_runner_refuses_closed_owner_before_catalog_admission(tmp_path):
    async def scenario():
        owner, _ = _owner(tmp_path)
        runner = owner.runner(STATE)
        before = owner.catalog.snapshot()
        owner.close()
        called = False
        async def answer(turn):
            nonlocal called
            called = True
            return _answer(turn)

        with pytest.raises(RuntimeError, match="closed"):
            await runner.run_turn("This closed owner must not admit a user.", execute=answer)
        assert not called
        assert owner.catalog.snapshot() == before
        assert owner.catalog.read_transcript(ID, session_key=KEY) is None
        assert owner.store.closed and owner.controller.status()["closed"]
        owner.close()

    asyncio.run(scenario())


def test_synchronous_close_refuses_active_turn_and_model_self_close_without_deadlock(tmp_path):
    async def scenario():
        owner, _ = _owner(tmp_path)
        entered, release = asyncio.Event(), asyncio.Event()
        async def answer(turn):
            with pytest.raises(RuntimeError, match="cannot close its own"):
                owner.close()
            with pytest.raises(RuntimeError, match="cannot close its own"):
                await owner.aclose()
            entered.set()
            await release.wait()
            return _answer(turn)

        running = asyncio.create_task(owner.runner(STATE).run_turn("Keep this real model callback admitted.", execute=answer))
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            with pytest.raises(RuntimeError, match="active"):
                owner.close()
            assert not owner.store.closed and not running.done()
            release.set()
            assert (await asyncio.wait_for(running, timeout=5)).transcript_committed
            owner.close()
            assert owner.store.closed
        finally:
            release.set()
            await running
            await owner.aclose()

    asyncio.run(scenario())


def test_cancelled_aclose_and_turn_caller_wait_for_real_accepted_tool_settlement(tmp_path, monkeypatch):
    async def scenario():
        owner, _ = _owner(tmp_path)
        owner.reindex()
        entered, release = threading.Event(), threading.Event()
        publish = owner.store.reindex_sources
        first_memory_publication = True
        def hold_memory_publication(workspace, **options):
            nonlocal first_memory_publication
            if set(options["sources"]) == {"memory"} and first_memory_publication:
                first_memory_publication = False
                entered.set()
                assert release.wait(5), "The test must release its actual memory publisher"
            return publish(workspace, **options)
        monkeypatch.setattr(owner.store, "reindex_sources", hold_memory_publication)

        async def save(turn):
            arguments = {"text": "The joined physical cedar token is CEDAR-942."}
            turn.record_message({"role": "assistant", "content": [{"type": "toolCall",
                "id": "held-write", "name": "append_daily_note", "arguments": arguments}]})
            await turn.dispatch_async("held-write", "append_daily_note", arguments)
            return _answer(turn)

        runner = owner.runner(STATE)
        running = asyncio.create_task(runner.run_turn("Remember the joined cedar token.", execute=save))
        closing = None
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            closing = asyncio.create_task(owner.aclose())
            def wait_until_closing():
                with owner._condition:
                    return owner._condition.wait_for(lambda: owner._closing, timeout=5)
            assert await asyncio.to_thread(wait_until_closing)
            closing.cancel()
            running.cancel()
            await asyncio.sleep(0)
            assert not closing.done() and not running.done()
            assert not owner.store.closed
            assert "CEDAR-942" in (owner.kit.memory.workspace.root / "memory/2026-11-09.md").read_text()

            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(running, timeout=5)
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(closing, timeout=5)

            assert runner.last_outcome.cancelled and runner.last_outcome.memory_writes_committed
            assert owner.store.closed and owner.controller.status()["closed"]
            assert owner.store.lifecycle_snapshot()["activeOperations"] == 0
            transcript = owner.catalog.read_continuation(ID, session_key=KEY)
            assert any(message.get("role") == "toolResult" for message in transcript["llmMessages"])
        finally:
            release.set()
            await asyncio.gather(running, *([closing] if closing is not None else []), return_exceptions=True)
            await owner.aclose()

    asyncio.run(scenario())


def test_cold_acknowledgment_keeps_uncertainty_without_full_scope_fallback(tmp_path, monkeypatch):
    async def scenario():
        owner, _ = _owner(tmp_path)
        try:
            target = owner.kit.memory.workspace.root / "MEMORY.md"
            target.write_text("# Memory\n\n## Notes\n- original\n")
            actual_replace = os.replace
            class UncertainRename(OSError):
                name = "Error"
                code = "EIO"
            def uncertain_replace(source, destination):
                result = actual_replace(source, destination)
                if Path(destination) == target:
                    raise UncertainRename("actual cold rename completed before the reported fault")
                return result
            monkeypatch.setattr(os, "replace", uncertain_replace)
            async def save(turn):
                _call(turn, "add_memory_entry", {"section": "Notes", "text": "cold uncertain cedar token"})
                return _answer(turn)
            runner = owner.runner(STATE)
            outcome = await runner.run_turn("Save a cold uncertain cedar token.", execute=save, request_id="cold-uncertain")
            assert outcome.memory_publication == "uncertain"
            assert owner.store.read_index_meta() is None
            pending = deepcopy(_auxiliary(owner)["pendingMemoryPublication"])
            monkeypatch.setattr(os, "replace", actual_replace)
            full_reindex = owner.store.reindex
            def forbid_full(*_args, **_kwargs):
                raise AssertionError("Cold acknowledgment must not silently widen to full publication")
            monkeypatch.setattr(owner.store, "reindex", forbid_full)

            with pytest.raises(MemoryIndexRequiresFullReindexError):
                await runner.acknowledge_memory_publication(expected_turn_id="cold-uncertain")
            assert _auxiliary(owner)["pendingMemoryPublication"] == pending
            assert _auxiliary(owner)["needsMemoryIndex"] is True
            assert _auxiliary(owner)["needsSessionIndex"] is True
            assert owner.store.read_index_meta() is None
            assert owner.controller.status()["notStarted"] is True

            monkeypatch.setattr(owner.store, "reindex", full_reindex)
            owner.reindex()
            assert _auxiliary(owner)["pendingMemoryPublication"] == pending
            await runner.acknowledge_memory_publication(expected_turn_id="cold-uncertain")
            assert "pendingMemoryPublication" not in _auxiliary(owner)
            assert "cold uncertain cedar token" in target.read_text()
        finally:
            await owner.aclose()

    asyncio.run(scenario())


def test_full_owner_reindex_propagates_original_startup_failure_then_explicitly_recovers(tmp_path, monkeypatch):
    owner, _ = _owner(tmp_path)
    try:
        _seed_transcript(owner)
        failure = OSError("actual startup discovery failed once")
        discover = owner.controller._discover
        start = owner.controller.start
        attempts = 0
        def fail_first_discovery():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise failure
            return discover()
        def start_and_join_actual_startup():
            start()
            assert owner.controller.wait_idle(timeout=5)
        monkeypatch.setattr(owner.controller, "_discover", fail_first_discovery)
        monkeypatch.setattr(owner.controller, "start", start_and_join_actual_startup)

        with pytest.raises(OSError) as raised:
            owner.reindex()
        assert raised.value is failure
        assert attempts == 1
        assert owner.store.index_identity() == {"status": "valid"}
        assert owner.controller.status()["jobs"][0]["state"] == "failed"
        assert owner.publication_status()["ready"] is False

        monkeypatch.setattr(owner.controller, "_discover", discover)
        monkeypatch.setattr(owner.controller, "start", start)
        owner.reindex()
        assert owner.publication_status()["ready"] is True
        assert owner.controller.status()["lastError"] is None
        assert any("older published violet token" in row["text"] for row in _session_rows(owner))
    finally:
        owner.close()


@pytest.mark.parametrize("invalid", ["unscoped-kit", "unbound-controller"])
def test_managed_constructor_refuses_components_that_bypass_shared_scoped_ownership(tmp_path, invalid):
    owner, _ = _owner(tmp_path)
    extra_controller = None
    try:
        if invalid == "unscoped-kit":
            kit = HostKit(owner.kit.memory, artifact_provenance=owner.store.artifact_provenance,
                identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY, now_ms=lambda: NOW)
            controller = owner.controller
        else:
            kit = owner.kit
            extra_controller = SessionPublicationController(owner.store, owner.kit.memory.workspace, owner.catalog)
            controller = extra_controller
        before = owner.store.read_published_index()
        with pytest.raises(ValueError):
            ManagedHostSession(kit, owner.catalog, controller)
        assert owner.store.read_published_index() == before
        assert owner.controller.status()["notStarted"] is True
    finally:
        if extra_controller is not None:
            extra_controller.close()
        owner.close()


def test_returned_runner_refuses_closed_acknowledgment_before_catalog_access(tmp_path, monkeypatch):
    async def scenario():
        owner, _ = _owner(tmp_path)
        runner = owner.runner(STATE)
        owner.close()
        def forbid_catalog_read(*_args, **_kwargs):
            raise AssertionError("A closed managed owner must reject ACK before reading the catalog")
        monkeypatch.setattr(owner.catalog, "get_session_entry", forbid_catalog_read)
        with pytest.raises(RuntimeError, match="closed"):
            await runner.acknowledge_memory_publication(expected_turn_id="closed-ack")
        assert owner.store.closed

    asyncio.run(scenario())


def test_aclose_joins_acknowledgment_through_final_metadata_after_actual_refresh(tmp_path, monkeypatch):
    async def scenario():
        owner, _ = _owner(tmp_path)
        owner.reindex()
        target = owner.kit.memory.workspace.root / "MEMORY.md"
        target.write_text("# Memory\n\n## Notes\n- original\n")
        actual_replace = os.replace
        class UncertainRename(OSError):
            name = "Error"
            code = "EIO"
        def uncertain_replace(source, destination):
            result = actual_replace(source, destination)
            if Path(destination) == target:
                raise UncertainRename("actual rename completed before acknowledgment custody test")
            return result
        monkeypatch.setattr(os, "replace", uncertain_replace)
        async def save(turn):
            _call(turn, "add_memory_entry", {"section": "Notes", "text": "acknowledged cedar token"})
            return _answer(turn)
        runner = owner.runner(STATE)
        uncertain = await runner.run_turn("Save a token requiring acknowledgment.", execute=save, request_id="held-ack")
        assert uncertain.memory_publication == "uncertain"
        monkeypatch.setattr(os, "replace", actual_replace)

        entered, release_source, close_entered = threading.Event(), threading.Event(), threading.Event()
        publication_done, release_metadata = asyncio.Event(), asyncio.Event()
        publish = owner.store.reindex_sources
        def hold_refresh(workspace, **options):
            entered.set()
            assert release_source.wait(5), "The test must release its accepted ACK refresh"
            return publish(workspace, **options)
        blocking = runner._blocking
        async def hold_after_refresh(function, *args):
            result = await blocking(function, *args)
            publication_done.set()
            await release_metadata.wait()
            return result
        close = owner.store.close
        def observe_close():
            close_entered.set()
            return close()
        monkeypatch.setattr(owner.store, "reindex_sources", hold_refresh)
        monkeypatch.setattr(runner, "_blocking", hold_after_refresh)
        monkeypatch.setattr(owner.store, "close", observe_close)
        acknowledgment = asyncio.create_task(runner.acknowledge_memory_publication(expected_turn_id="held-ack"))
        closing = None
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            closing = asyncio.create_task(owner.aclose())
            def wait_until_closing():
                with owner._condition:
                    return owner._condition.wait_for(lambda: owner._closing, timeout=5)
            assert await asyncio.to_thread(wait_until_closing)
            assert not acknowledgment.done() and not closing.done()
            release_source.set()
            await asyncio.wait_for(publication_done.wait(), timeout=5)
            assert "pendingMemoryPublication" in _auxiliary(owner)
            assert not close_entered.is_set(), "Closing must wait for ACK metadata, beyond the SQLite source operation"
            assert not closing.done() and not owner.store.closed

            release_metadata.set()
            await asyncio.wait_for(acknowledgment, timeout=5)
            await asyncio.wait_for(closing, timeout=5)
            assert "pendingMemoryPublication" not in _auxiliary(owner)
            assert _auxiliary(owner)["lastMemoryPublicationAcknowledgment"]["turnId"] == "held-ack"
            assert close_entered.is_set() and owner.store.closed
        finally:
            release_source.set()
            release_metadata.set()
            await asyncio.gather(acknowledgment, *([closing] if closing is not None else []), return_exceptions=True)
            await owner.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(("key", "metadata"), [
    ("agent:main:cron:job:run:excluded", {}),
    ("agent:main:heartbeat", {"heartbeatIsolatedBaseSessionKey": "agent:main:main"}),
])
def test_synchronize_clears_session_dirtiness_when_real_corpus_excludes_the_session(tmp_path, key, metadata):
    async def scenario():
        owner, _ = _owner(tmp_path)
        try:
            owner.reindex()
            identifier = "excluded-session"
            owner.catalog.upsert_session(key, {"sessionId": identifier, **metadata})
            async def answer(turn):
                return _answer(turn)
            outcome = await owner.runner(SessionState.new(session_key=key, session_id=identifier)).run_turn(
                "An actual excluded maintenance conversation.", execute=answer)
            assert outcome.transcript_committed

            status = owner.synchronize(timeout=5)

            assert owner.controller.status()["pending"] is False
            assert _session_rows(owner) == []
            assert status["ready"] is True and status["sessionPending"] is False
            auxiliary = owner.catalog.get_session_entry(key)["sdkHostLifecycle"]
            assert auxiliary["needsSessionIndex"] is False and auxiliary["needsIndex"] is False
        finally:
            await owner.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("rotate", [False, True])
def test_real_coverage_check_preserves_independent_metadata_edit_and_session_rotation(tmp_path, monkeypatch, rotate):
    owner, _ = _owner(tmp_path)
    try:
        _seed_transcript(owner)
        entry = owner.catalog.get_session_entry(KEY)
        entry["sdkHostLifecycle"] = {"publicationMode": "managed", "needsMemoryIndex": True,
            "needsSessionIndex": True, "needsIndex": True}
        owner.catalog.upsert_session(KEY, entry)
        check = owner._session_current
        changed = False
        def change_metadata_after_actual_coverage_check(key, identifier):
            nonlocal changed
            covered = check(key, identifier)
            if key == KEY and not changed:
                changed = True
                current = owner.catalog.get_session_entry(KEY)
                current["outsideReset"] = {"preserve": [False, None, 7]}
                if rotate:
                    current["sessionId"] = "new-managed-incarnation"
                owner.catalog.upsert_session(KEY, current)
            return covered
        monkeypatch.setattr(owner, "_session_current", change_metadata_after_actual_coverage_check)

        owner.reindex()

        current = owner.catalog.get_session_entry(KEY)
        assert changed
        assert current["sessionId"] == ("new-managed-incarnation" if rotate else ID)
        assert current["outsideReset"] == {"preserve": [False, None, 7]}
        assert owner.catalog.read_transcript(ID, session_key=KEY) is not None
    finally:
        owner.close()


def test_explicit_empty_index_sources_have_no_session_publication_claim(tmp_path):
    owner, _ = _owner(tmp_path, source_policy={"sources": []})
    try:
        _seed_transcript(owner)
        status = owner.publication_status()
        assert status["sessionPending"] is False
        assert status["sessionIndexStatus"] == "ready"
        assert owner.controller.status()["notStarted"] is True
        assert owner.kit.memory.workspace.discover_indexable_files() == []
        assert owner.store.read_index_meta() is None

        owner.reindex()

        assert owner.store.read_published_index()["chunks"] == []
        assert owner.publication_status()["ready"] is True
        assert owner.controller.status()["jobCount"] == 0
    finally:
        owner.close()


def test_atomic_coverage_patch_refuses_real_session_reset_at_catalog_commit_boundary(tmp_path, monkeypatch):
    owner, _ = _owner(tmp_path)
    try:
        _seed_transcript(owner)
        entry = owner.catalog.get_session_entry(KEY)
        dirty = {"publicationMode": "managed", "needsMemoryIndex": True,
            "needsSessionIndex": True, "needsIndex": True}
        entry["sdkHostLifecycle"] = deepcopy(dirty)
        owner.catalog.upsert_session(KEY, entry)
        old_window = owner.catalog.read_continuation(ID, session_key=KEY)["instanceEntry"]
        compare_and_patch = owner.catalog.compare_and_patch_host_lifecycle
        results = []
        raced = {}
        def reset_before_genuine_compare(*, expected_revision, updates):
            assert KEY in updates
            current = owner.catalog.get_session_entry(KEY)
            current.update(sessionId="reset-at-atomic-boundary", outsideReset={"retained": [False, None, 7]})
            owner.catalog.upsert_session(KEY, current)
            owner.catalog.append_message("reset-at-atomic-boundary",
                {"role": "user", "content": "A genuine new conversation after the coverage scan."},
                session_key=KEY, event_id="reset-at-boundary", now_ms=NOW)
            raced["entry"] = owner.catalog.get_session_entry(KEY)
            raced["revision"] = owner.catalog.snapshot().revision
            result = compare_and_patch(expected_revision=expected_revision, updates=updates)
            results.append(result)
            return result
        monkeypatch.setattr(owner.catalog, "compare_and_patch_host_lifecycle", reset_before_genuine_compare)

        owner.reindex()

        assert results == [False]
        assert owner.catalog.snapshot().revision == raced["revision"]
        assert owner.catalog.get_session_entry(KEY) == raced["entry"]
        assert _auxiliary(owner) == dirty
        assert owner.catalog.read_continuation(ID, session_key=KEY)["instanceEntry"] == old_window
        continuation = owner.catalog.read_continuation("reset-at-atomic-boundary", session_key=KEY)
        assert continuation["instanceEntry"] == raced["entry"]
        assert any(message.get("content") == "A genuine new conversation after the coverage scan."
            for message in continuation["llmMessages"])
        assert owner.publication_status()["ready"] is False
    finally:
        owner.close()


def test_atomic_coverage_patch_refuses_actual_metadata_and_transcript_commit_after_coverage_scan(tmp_path, monkeypatch):
    owner, _ = _owner(tmp_path)
    try:
        _seed_transcript(owner)
        entry = owner.catalog.get_session_entry(KEY)
        dirty = {"publicationMode": "managed", "needsMemoryIndex": True,
            "needsSessionIndex": True, "needsIndex": True}
        entry["sdkHostLifecycle"] = deepcopy(dirty)
        owner.catalog.upsert_session(KEY, entry)
        compare_and_patch = owner.catalog.compare_and_patch_host_lifecycle
        results = []
        raced = {}
        def append_before_genuine_compare(*, expected_revision, updates):
            assert KEY in updates
            current = owner.catalog.get_session_entry(KEY)
            current["outsideEdit"] = {"retained": [False, None, 9]}
            owner.catalog.upsert_session(KEY, current)
            owner.catalog.append_message(ID,
                {"role": "user", "content": "A genuine late amber token absent from the published snapshot."},
                session_key=KEY, event_id="append-at-atomic-boundary", now_ms=NOW)
            raced["entry"] = owner.catalog.get_session_entry(KEY)
            raced["revision"] = owner.catalog.snapshot().revision
            raced["events"] = owner.catalog.read_continuation(ID, session_key=KEY)["events"]
            result = compare_and_patch(expected_revision=expected_revision, updates=updates)
            results.append(result)
            return result
        monkeypatch.setattr(owner.catalog, "compare_and_patch_host_lifecycle", append_before_genuine_compare)

        owner.reindex()

        assert results == [False]
        assert owner.catalog.snapshot().revision == raced["revision"]
        assert owner.catalog.get_session_entry(KEY) == raced["entry"]
        assert _auxiliary(owner) == dirty
        continuation = owner.catalog.read_continuation(ID, session_key=KEY)
        assert continuation["instanceEntry"] == raced["entry"]
        assert continuation["events"] == raced["events"]
        assert any(message.get("content") == "A genuine late amber token absent from the published snapshot."
            for message in continuation["llmMessages"])
        assert all("late amber token" not in row["text"] for row in _session_rows(owner))
        assert owner.publication_status()["ready"] is False
    finally:
        owner.close()
