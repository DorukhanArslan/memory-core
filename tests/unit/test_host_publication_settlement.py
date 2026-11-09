"""Actual publisher faults through host admission, indexing and acknowledgment."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import errno
import hashlib
import os
from pathlib import Path
import signal
import threading

import pytest

from memory_core.config import MemoryConfig
from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
from memory_core.flags import FeatureFlags
from memory_core.host.lifecycle import HostModelResult, HostSessionRunner
from memory_core.host.session import SessionState, TurnUsage
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
        session=SessionState.new(session_key=KEY, session_id=ID), config=config, now_ms=lambda: NOW)


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
                "stage": "uncertain",
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


@pytest.mark.parametrize("different", ["workspace", "index", "provenance", "rebound-provenance"])
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
        if different == "rebound-provenance":
            other = runner
            other.kit.memory.store.artifact_provenance = MemoryArtifactProvenanceStore(tmp_path / "rebound-ledger.sqlite")
        else:
            other = HostSessionRunner.open(workspace, config=config, catalog=runner.catalog,
                session=SessionState.new(session_key=KEY, session_id=ID),
                artifact_provenance=MemoryArtifactProvenanceStore(tmp_path / "another-provenance.sqlite")
                    if different == "provenance" else None)
        with pytest.raises(RuntimeError, match="different workspace, index or provenance"):
            await other.acknowledge_memory_publication(expected_turn_id="pending")
        assert _auxiliary(runner)["pendingMemoryPublication"]["turnId"] == "pending"
        assert "lastMemoryPublicationAcknowledgment" not in _auxiliary(runner)

    asyncio.run(scenario())


def test_failed_intent_save_does_not_start_the_actual_memory_producer(tmp_path, monkeypatch):
    import memory_core.curation as curation

    async def scenario():
        runner = _runner(tmp_path)
        target = _target(runner)
        before = target.read_bytes()
        actual_save, actual_publish = runner.catalog.upsert_session, curation.commit_memory_content
        publications = []

        def save(key, entry, **kwargs):
            if entry.get("sdkHostLifecycle", {}).get("pendingMemoryPublication", {}).get("stage") == "intent":
                raise OSError("intent catalog save refused")
            return actual_save(key, entry, **kwargs)

        def publish(*args, **kwargs):
            publications.append(args)
            return actual_publish(*args, **kwargs)

        monkeypatch.setattr(runner.catalog, "upsert_session", save)
        monkeypatch.setattr(curation, "commit_memory_content", publish)
        outcome = await runner.run_turn("Save", execute=_save)
        assert outcome.tools[0]["result"]["status"] == "error"
        assert outcome.tools[0]["memoryProducerStarted"] is False
        assert publications == [] and target.read_bytes() == before
        assert runner.artifact_provenance.read(workspace_dir=target.parent, relative_path=target.name) is None
        assert outcome.memory_publication == "none" and not outcome.memory_writes_committed
        assert "pendingMemoryPublication" not in _auxiliary(runner)

    asyncio.run(scenario())


@pytest.mark.parametrize("publication", ["uncertain", "committed", "ok"])
def test_final_catalog_failure_leaves_prior_intent_for_fresh_runner(tmp_path, monkeypatch, publication):
    async def scenario():
        runner = _runner(tmp_path)
        target = _target(runner)
        original_replace = os.replace
        if publication != "ok":
            _fault(monkeypatch, target, stage=publication)
        actual_save = runner.catalog.upsert_session
        intent_saved = False

        def save(key, entry, **kwargs):
            nonlocal intent_saved
            pending = entry.get("sdkHostLifecycle", {}).get("pendingMemoryPublication")
            if pending is not None and pending.get("stage") == "intent":
                result = actual_save(key, entry, **kwargs)
                intent_saved = True
                return result
            if intent_saved:
                raise OSError("final catalog settlement refused")
            return actual_save(key, entry, **kwargs)

        monkeypatch.setattr(runner.catalog, "upsert_session", save)
        outcome = await runner.run_turn("Save", execute=_save, request_id="unsettled")
        assert outcome.index_status == "failed" and not outcome.ready
        assert outcome.memory_writes_committed is (publication != "uncertain")
        pending = _auxiliary(runner)["pendingMemoryPublication"]
        assert pending["turnId"] == "unsettled" and pending["stage"] == "intent"
        monkeypatch.setattr(runner.catalog, "upsert_session", actual_save)
        monkeypatch.setattr(os, "replace", original_replace)
        fresh = _runner(tmp_path)
        before = fresh.catalog.read_continuation(ID, session_key=KEY)["events"]
        blocked = await fresh.run_turn("Next", execute=_save)
        assert not blocked.transcript_committed and blocked.memory_publication == "uncertain"
        assert fresh.catalog.read_continuation(ID, session_key=KEY)["events"] == before
        actual_bytes = target.read_bytes()
        await fresh.acknowledge_memory_publication(expected_turn_id="unsettled")
        assert target.read_bytes() == actual_bytes and "pendingMemoryPublication" not in _auxiliary(fresh)

    asyncio.run(scenario())


@pytest.mark.parametrize("name,arguments", [
    ("append_daily_note", {"text": False}),
    ("add_memory_entry", {"section": "Notes", "text": ""}),
])
def test_invalid_builtin_arguments_never_enter_mutation_or_quarantine(tmp_path, monkeypatch, name, arguments):
    async def scenario():
        runner = _runner(tmp_path)
        target = _target(runner)
        before = target.read_bytes()
        actual = runner.catalog.upsert_session
        intent_saves = []

        def save(key, entry, **kwargs):
            if entry.get("sdkHostLifecycle", {}).get("pendingMemoryPublication"):
                intent_saves.append(entry)
            return actual(key, entry, **kwargs)

        monkeypatch.setattr(runner.catalog, "upsert_session", save)

        async def invalid(turn):
            assert _call(turn, name, arguments, "invalid")["status"] == "error"
            return HostModelResult()

        outcome = await runner.run_turn("Try invalid arguments", execute=invalid)
        assert not outcome.tools[0]["memoryProducerStarted"] and not intent_saves
        assert outcome.memory_publication == "none" and target.read_bytes() == before
        assert "pendingMemoryPublication" not in _auxiliary(runner)

        async def chat(turn):
            return HostModelResult()

        assert (await runner.run_turn("Just chat", execute=chat)).ready
        assert not intent_saves

    asyncio.run(scenario())


def test_concurrent_owned_writes_share_one_intent_until_whole_turn_settles(tmp_path, monkeypatch):
    async def scenario():
        runner = _runner(tmp_path)
        target = _target(runner)
        actual = runner.catalog.upsert_session
        intent_saves = []

        def save(key, entry, **kwargs):
            pending = entry.get("sdkHostLifecycle", {}).get("pendingMemoryPublication")
            if pending is not None:
                intent_saves.append(deepcopy(pending))
            return actual(key, entry, **kwargs)

        monkeypatch.setattr(runner.catalog, "upsert_session", save)

        async def save_both(turn):
            calls = [{"type": "toolCall", "id": name, "name": "add_memory_entry",
                "arguments": {"section": "Notes", "text": name}} for name in ("first", "second")]
            turn.record_message({"role": "assistant", "content": calls})
            results = await asyncio.gather(*(turn.dispatch_async(call["id"], call["name"], call["arguments"]) for call in calls))
            assert all(result["status"] == "ok" for result in results)
            assert _auxiliary(runner)["pendingMemoryPublication"]["stage"] == "intent"
            return HostModelResult()

        outcome = await runner.run_turn("Save both", execute=save_both)
        assert outcome.ready and outcome.memory_writes_committed
        assert len(intent_saves) == 1 and intent_saves[0]["stage"] == "intent"
        assert "pendingMemoryPublication" not in _auxiliary(runner)
        assert "- first\n" in target.read_text() and "- second\n" in target.read_text()

    asyncio.run(scenario())


def test_partial_append_io_failure_retains_intent_without_inventing_lower_publication(tmp_path, monkeypatch):
    resource = pytest.importorskip("resource")
    if not hasattr(signal, "SIGXFSZ"):
        pytest.skip("The genuine file-size failure requires SIGXFSZ")

    async def scenario():
        runner = _runner(tmp_path)
        target = runner.kit.memory.workspace.root / "memory/2026-11-09.md"
        actual = MemoryWriteProvenanceObserver.write
        failures = []

        def write(observer, *, absolute_path, content_before, content_after, commit):
            def bounded_commit():
                previous_limit = resource.getrlimit(resource.RLIMIT_FSIZE)
                previous_handler = signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
                try:
                    resource.setrlimit(resource.RLIMIT_FSIZE, (5, previous_limit[1]))
                    return commit()
                except OSError as error:
                    failures.append(error.errno)
                    raise
                finally:
                    resource.setrlimit(resource.RLIMIT_FSIZE, previous_limit)
                    signal.signal(signal.SIGXFSZ, previous_handler)

            return actual(observer, absolute_path=absolute_path, content_before=content_before,
                content_after=content_after, commit=bounded_commit if Path(absolute_path) == target else commit)

        monkeypatch.setattr(MemoryWriteProvenanceObserver, "write", write)

        async def append(turn):
            result = _call(turn, "append_daily_note", {"text": "partial actual append body"}, "append")
            assert result["status"] == "error" and "publication" not in result
            turn.record_message({"role": "assistant", "content": [{"type": "toolCall", "id": "retry",
                "name": "append_daily_note", "arguments": {"text": "must not replay"}}]})
            with pytest.raises(RuntimeError, match="publication is uncertain"):
                turn.dispatch("retry", "append_daily_note", {"text": "must not replay"})
            return HostModelResult()

        outcome = await runner.run_turn("Append", execute=append, request_id="partial")
        assert failures == [errno.EFBIG]
        assert target.read_bytes() == b"parti"
        assert outcome.memory_publication == "uncertain" and not outcome.memory_writes_committed
        assert _auxiliary(runner)["pendingMemoryPublication"]["stage"] == "intent"
        assert outcome.tools[0]["memoryProducerStarted"] is True
        assert next(failure for failure in outcome.failures if failure.phase == "tool").publication is None

    asyncio.run(scenario())


def test_due_flush_preparation_does_not_mutate_when_intent_save_fails(tmp_path, monkeypatch):
    async def scenario():
        runner = _runner(tmp_path)
        target = runner.kit.memory.workspace.root / "memory/2026-11-09.md"
        actual_save = runner.catalog.upsert_session
        flush_called = False

        def save(key, entry, **kwargs):
            if entry.get("sdkHostLifecycle", {}).get("pendingMemoryPublication"):
                raise OSError("flush intent save refused")
            return actual_save(key, entry, **kwargs)

        monkeypatch.setattr(runner.catalog, "upsert_session", save)

        async def model(turn):
            return HostModelResult(TurnUsage(176_000, 10))

        async def flush(turn):
            nonlocal flush_called
            flush_called = True
            return HostModelResult()

        outcome = await runner.run_turn("A large completed model turn", execute=model, execute_flush=flush)
        assert not target.exists() and not flush_called
        assert outcome.memory_publication == "none" and not outcome.memory_writes_committed
        assert outcome.session.entry["totalTokens"] == 176_000
        assert any("flush intent save refused" in failure.message for failure in outcome.failures)

    asyncio.run(scenario())


def test_invalid_private_flush_arguments_do_not_leave_unresolved_intent(tmp_path):
    async def scenario():
        runner = _runner(tmp_path)
        target = runner.kit.memory.workspace.root / "memory/2026-11-09.md"

        async def model(turn):
            return HostModelResult(TurnUsage(176_000, 10))

        async def flush(turn):
            assert _auxiliary(runner)["pendingMemoryPublication"]["stage"] == "intent"
            result = _call(turn, "write", {"path": turn.flush_request.target, "content": False}, "invalid")
            assert result["status"] == "error"
            return HostModelResult()

        outcome = await runner.run_turn("A large turn", execute=model, execute_flush=flush)
        assert target.exists() and target.read_bytes() == b""
        assert outcome.tools[0]["memoryProducerStarted"] is False
        assert outcome.memory_publication == "none" and "pendingMemoryPublication" not in _auxiliary(runner)

    asyncio.run(scenario())


def test_constructor_rejects_a_ledger_attached_after_the_immutable_kit_was_built(tmp_path):
    from memory_core import HostKit, Memory

    config = MemoryConfig(tmp_path / "workspace", flags=FeatureFlags(vector_search=False))
    catalog = MemorySessionCatalog(tmp_path / "sessions.sqlite")
    memory = Memory.from_workspace(config.workspace_dir, config=config, session_catalog=catalog)
    kit = HostKit(memory)
    memory.store.artifact_provenance = MemoryArtifactProvenanceStore(tmp_path / "late-ledger.sqlite")
    with pytest.raises(ValueError, match="Construct HostKit with artifact_provenance"):
        HostSessionRunner(kit, catalog, session=SessionState.new(session_key=KEY, session_id=ID))


def test_rebinding_the_index_ledger_cannot_bypass_the_required_write_observer(tmp_path):
    async def scenario():
        runner = _runner(tmp_path)
        target = _target(runner)
        before = target.read_bytes()
        runner.kit.memory.store.artifact_provenance = MemoryArtifactProvenanceStore(tmp_path / "replacement-ledger.sqlite")
        outcome = await runner.run_turn("Save", execute=_save)
        assert target.read_bytes() == before and outcome.tools[0]["memoryProducerStarted"] is False
        assert not outcome.memory_writes_committed and outcome.memory_publication == "none"
        assert any("provenance store changed" in item.message for item in outcome.failures)

    asyncio.run(scenario())


def test_terminal_cancelled_flush_producer_keeps_partial_write_intent(tmp_path, monkeypatch):
    async def scenario():
        runner = _runner(tmp_path)
        target = runner.kit.memory.workspace.root / "memory/2026-11-09.md"
        actual = os.write
        flush_turn = None
        written = []
        body = "\n".join(f"{number:06d} actual durable flush payload" for number in range(20_000))

        def write(descriptor, data):
            result = actual(descriptor, data)
            if flush_turn is not None and target.exists():
                current, opened = target.stat(), os.fstat(descriptor)
                if (current.st_dev, current.st_ino) == (opened.st_dev, opened.st_ino):
                    written.append(result)
                    flush_turn.cancel_requested.set()
            return result

        monkeypatch.setattr(os, "write", write)

        async def model(turn):
            return HostModelResult(TurnUsage(176_000, 10))

        async def flush(turn):
            nonlocal flush_turn
            flush_turn = turn
            _call(turn, "write", {"path": turn.flush_request.target, "content": body}, "partial")
            raise AssertionError("The actual append authority check should cancel the producer")

        outcome = await runner.run_turn("A large turn", execute=model, execute_flush=flush, request_id="cancelled-producer")
        assert written == [512 * 1024] and target.read_bytes() == body.encode()[:512 * 1024]
        receipt = outcome.tools[0]
        assert receipt["memoryProducerStarted"] is True and receipt["sourceSettled"] is True
        assert "result" not in receipt and "error" not in receipt
        assert outcome.memory_publication == "uncertain" and not outcome.memory_writes_committed
        assert _auxiliary(runner)["pendingMemoryPublication"]["stage"] == "intent"
        blocked = await _runner(tmp_path).run_turn("Next", execute=model)
        assert not blocked.transcript_committed and blocked.memory_publication == "uncertain"

    asyncio.run(scenario())
