"""Real SDK host writes, durable continuation and next-admission ordering."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import threading

import pytest

from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.host.lifecycle import HostModelResult, HostSessionRunner
from memory_core.host.session import SessionState, TurnUsage
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.turn_tool_dispatch import TurnTool


NOW = 1_794_182_400_000
KEY = "agent:main:dm:lifecycle"
ID = "lifecycle-session"


def _runner(tmp_path, *, catalog=None, extra_tools=()):
    catalog = catalog or MemorySessionCatalog(tmp_path / "sessions.sqlite", clock_ms=lambda: NOW)
    config = MemoryConfig(workspace_dir=tmp_path / "workspace",
        flags=FeatureFlags(vector_search=False, temporal_decay=False))
    return HostSessionRunner.open(config.workspace_dir, catalog=catalog,
        session=SessionState.new(session_key=KEY, session_id=ID), config=config,
        extra_tools=extra_tools, now_ms=lambda: NOW)


def _call(turn, name, arguments, identifier):
    turn.record_message({"role": "assistant", "content": [
        {"type": "toolCall", "id": identifier, "name": name, "arguments": deepcopy(arguments)}],
        "provider": "host-fixture", "model": "actual-callback", "custom": {"keep": [False, None]}})


def _answer(turn, text="Done."):
    turn.record_message({"role": "assistant", "content": [{"type": "text", "text": text}],
                         "usage": {"input": 20, "output": 2}})
    return HostModelResult(TurnUsage(20, 2))


def test_real_note_is_searchable_by_immediate_next_turn_and_context_reopens(tmp_path):
    async def scenario():
        runner = _runner(tmp_path)
        index = runner.kit.memory.store.path
        assert runner.artifact_provenance.path == index.with_name(f"{index.stem}.provenance.sqlite")
        runner.catalog.upsert_session(KEY, {"sessionId": ID, "chatType": "direct",
            "callerMetadata": {"preserve": [False, None, 9]}})

        async def save(turn):
            _call(turn, "append_daily_note", {"text": "My calibration token is ZEPHYR-482."}, "save")
            receipt = await turn.dispatch_async("save", "append_daily_note", {"text": "My calibration token is ZEPHYR-482."})
            assert receipt["status"] == "ok"
            # An independent current metadata edit must survive finalization.
            current = runner.catalog.read_continuation(ID, session_key=KEY)["instanceEntry"]
            runner.catalog.upsert_session(KEY, {**current, "outsideEdit": {"retained": True}})
            return _answer(turn)

        saved = await runner.run_turn({"role": "user", "content": "Remember that my calibration token is ZEPHYR-482.",
            "idempotencyKey": "client-admission-key", "customUser": {"preserve": [False, None]}},
            execute=save, request_id="request-save")
        assert saved.ready and saved.transcript_committed and saved.memory_writes_committed
        assert saved.index_status == "ready"

        seen = []
        async def recall(turn):
            seen.extend(turn.messages)
            arguments = {"query": "ZEPHYR-482", "corpus": "memory", "minScore": 0}
            _call(turn, "memory_search", arguments, "recall")
            receipt = await turn.dispatch_async("recall", "memory_search", arguments)
            assert any("ZEPHYR-482" in hit["snippet"] for hit in receipt["results"])
            return _answer(turn, "I found the saved note.")

        recalled = await runner.run_turn("What is my saved calibration token?", execute=recall)
        assert recalled.ready
        current = runner.catalog.get_session_entry(KEY)
        assert current["callerMetadata"] == {"preserve": [False, None, 9]}
        assert current["outsideEdit"] == {"retained": True}
        assert current["sdkHostLifecycle"]["needsIndex"] is False
        reopened = MemorySessionCatalog(runner.catalog.path).read_continuation(ID, session_key=KEY)
        assert len(reopened["events"]) == 9
        assert any(message.get("custom") == {"keep": [False, None]} for message in reopened["llmMessages"])
        assert reopened["events"][1]["message"]["idempotencyKey"] == "client-admission-key"
        assert reopened["events"][1]["message"]["customUser"] == {"preserve": [False, None]}
        assert [message["role"] for message in seen] == ["user", "assistant", "toolResult", "assistant", "user"]
        assert any("append_daily_note" == message.get("toolName") for message in reopened["llmMessages"])

    asyncio.run(scenario())


def test_committed_write_with_failed_index_stays_visible_and_next_admission_repairs(tmp_path, monkeypatch):
    async def scenario():
        runner = _runner(tmp_path)
        reindex = runner.kit.memory.store.reindex
        monkeypatch.setattr(runner.kit.memory.store, "reindex", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("index publication unavailable")))

        async def save(turn):
            arguments = {"text": "The durable orange code is AMBER-713."}
            _call(turn, "append_daily_note", arguments, "save")
            receipt = await turn.dispatch_async("save", "append_daily_note", arguments)
            assert receipt["status"] == "ok" and "publication unavailable" in receipt["afterWriteError"]
            return _answer(turn)

        failed = await runner.run_turn("Remember that my orange code is AMBER-713.", execute=save)
        assert failed.transcript_committed and failed.memory_writes_committed
        assert failed.index_status == "failed" and not failed.ready
        assert any(f.phase == "tool-index" and f.committed for f in failed.failures)
        assert "AMBER-713" in (runner.kit.memory.workspace.root / "memory/2026-11-09.md").read_text()
        assert runner.catalog.get_session_entry(KEY)["sdkHostLifecycle"]["needsIndex"] is True

        called = False
        async def never(turn):
            nonlocal called
            called = True
            return _answer(turn)
        blocked = await runner.run_turn("This input must await publication.", execute=never)
        assert not called and not blocked.transcript_committed and blocked.index_status == "failed"
        assert blocked.failures[0].phase == "index-repair"

        monkeypatch.setattr(runner.kit.memory.store, "reindex", reindex)
        async def recall(turn):
            arguments = {"query": "AMBER-713", "corpus": "memory", "minScore": 0}
            _call(turn, "memory_search", arguments, "find")
            actual = await turn.dispatch_async("find", "memory_search", arguments)
            assert any("AMBER-713" in hit["snippet"] for hit in actual["results"])
            return _answer(turn)
        repaired = await runner.run_turn("Find the note after repair.", execute=recall)
        assert repaired.ready
        assert runner.catalog.get_session_entry(KEY)["sdkHostLifecycle"]["needsIndex"] is False

    asyncio.run(scenario())


def test_cancelled_dispatch_future_does_not_release_lane_before_real_sync_writer(tmp_path, monkeypatch):
    async def scenario():
        runner = _runner(tmp_path)
        entered, release = threading.Event(), threading.Event()
        reindex = runner.kit.memory.store.reindex
        first = True
        def blocked_reindex(*args, **kwargs):
            nonlocal first
            if first:
                first = False
                entered.set()
                assert release.wait(5), "The test must release the actual producer"
            return reindex(*args, **kwargs)
        monkeypatch.setattr(runner.kit.memory.store, "reindex", blocked_reindex)

        async def save(turn):
            args = {"text": "A real pending writer keeps COBALT-941."}
            _call(turn, "append_daily_note", args, "pending")
            pending = asyncio.create_task(turn.dispatch_async("pending", "append_daily_note", args))
            assert await asyncio.to_thread(entered.wait, 5)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            return HostModelResult(TurnUsage(20, 2))

        first_turn = asyncio.create_task(runner.run_turn("Remember that my cobalt code is COBALT-941.", execute=save))
        assert await asyncio.to_thread(entered.wait, 5)
        admitted = asyncio.Event()
        async def recall(turn):
            admitted.set()
            arguments = {"query": "COBALT-941", "corpus": "memory", "minScore": 0}
            _call(turn, "memory_search", arguments, "next")
            result = await turn.dispatch_async("next", "memory_search", arguments)
            assert any("COBALT-941" in hit["snippet"] for hit in result["results"])
            return _answer(turn)
        second_turn = asyncio.create_task(runner.run_turn("Recall the cobalt code.", execute=recall))
        first_turn.cancel()
        await asyncio.sleep(0)
        assert not admitted.is_set() and not first_turn.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first_turn
        assert runner.last_outcome.cancelled and runner.last_outcome.memory_writes_committed
        assert (await second_turn).ready
        assert admitted.is_set()

    asyncio.run(scenario())


def test_one_live_trust_owner_survives_retry_and_new_turn_starts_clean(tmp_path):
    async def scenario():
        network = TurnTool("fetch_external", lambda _id, _args: {"content": [{"type": "text", "text": "The external preference is cedar tea."}]}, "network")
        runner = _runner(tmp_path, extra_tools=[network])
        async def tainted(turn):
            _call(turn, "fetch_external", {}, "external")
            await turn.dispatch_async("external", "fetch_external", {})
            # A host model retry reuses this exact admitted turn and trust owner.
            assert turn.trust.is_tainted()
            arguments = {"text": "The external preference is cedar tea."}
            _call(turn, "append_daily_note", arguments, "retry-write")
            await turn.dispatch_async("retry-write", "append_daily_note", arguments)
            return _answer(turn)
        outcome = await runner.run_turn("Read an external source and save it.", execute=tainted)
        assert outcome.ready
        record = runner.artifact_provenance.read(workspace_dir=runner.kit.memory.workspace.root,
                                                relative_path="memory/2026-11-09.md")
        assert record.origin_class == "untrusted"
        assert any(message.get("__openclaw", {}).get("turnTainted") is True for message in outcome.messages)
        async def clean(turn):
            assert not turn.trust.is_tainted()
            arguments = {"text": "The owner prefers clear summaries."}
            _call(turn, "upsert_user_directive", arguments, "clean")
            await turn.dispatch_async("clean", "upsert_user_directive", arguments)
            return _answer(turn)
        assert (await runner.run_turn("Save my own local preference.", execute=clean)).ready
        clean_record = runner.artifact_provenance.read(workspace_dir=runner.kit.memory.workspace.root, relative_path="USER.md")
        assert clean_record.origin_class == "agent"

    asyncio.run(scenario())


def test_late_and_unrecorded_dispatches_cannot_write(tmp_path):
    async def scenario():
        runner = _runner(tmp_path)
        captured = []
        async def model(turn):
            captured.append(turn)
            with pytest.raises(ValueError, match="recorded assistant"):
                turn.dispatch("missing", "append_daily_note", {"text": "Never saved."})
            _call(turn, "append_daily_note", {"text": "Also never saved."}, "late")
            return HostModelResult(TurnUsage(20, 2))
        assert (await runner.run_turn("A cancelled plan has no write.", execute=model)).ready
        with pytest.raises(RuntimeError, match="closed"):
            captured[0].dispatch("late", "append_daily_note", {"text": "Also never saved."})
        assert not (runner.kit.memory.workspace.root / "memory/2026-11-09.md").exists()
    asyncio.run(scenario())


def test_due_flush_executes_actual_append_before_next_turn_and_state_reopens(tmp_path):
    async def scenario():
        runner = _runner(tmp_path)
        async def model(turn):
            turn.record_message({"role": "assistant", "content": [{"type": "text", "text": "I will retain the saffron preference."}]})
            return HostModelResult(TurnUsage(176_000, 10))
        async def flush(turn):
            assert turn.context is None and turn.flush_request is not None
            assert any("saffron" in str(message) for message in turn.messages)
            arguments = {"path": turn.flush_request.target, "content": "The owner prefers saffron tea.\n"}
            _call(turn, "write", arguments, "flush-write")
            result = await turn.dispatch_async("flush-write", "write", arguments)
            assert result["status"] == "ok"
            turn.record_message({"role": "assistant", "content": [{"type": "text", "text": "NO_REPLY"}]})
        saved = await runner.run_turn("Remember that I prefer saffron tea.", execute=model, execute_flush=flush)
        assert saved.ready and saved.flush.wrote and saved.memory_writes_committed
        assert saved.session.entry["memoryFlush"]["kind"] == "succeeded"
        raw = runner.catalog.read_continuation(ID, session_key=KEY)
        assert len(raw["events"]) == 3  # maintenance content stays outside the visible conversation
        reopened_catalog = MemorySessionCatalog(runner.catalog.path, clock_ms=lambda: NOW)
        reopened = _runner(tmp_path, catalog=reopened_catalog)
        async def recall(turn):
            arguments = {"query": "saffron", "corpus": "memory", "minScore": 0}
            _call(turn, "memory_search", arguments, "find-flush")
            result = await turn.dispatch_async("find-flush", "memory_search", arguments)
            assert any("saffron" in hit["snippet"] for hit in result["results"])
            assert turn.session.entry["memoryFlush"]["kind"] == "succeeded"
            return _answer(turn)
        assert (await reopened.run_turn("Find my saved tea preference.", execute=recall)).ready
    asyncio.run(scenario())


def test_shared_catalog_key_serializes_distinct_runner_instances(tmp_path):
    async def scenario():
        first = _runner(tmp_path)
        second_catalog = MemorySessionCatalog(first.catalog.path, clock_ms=lambda: NOW)
        second = _runner(tmp_path, catalog=second_catalog)
        entered, release, admitted = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def owner(turn):
            entered.set()
            await release.wait()
            return _answer(turn, "The first owner completed.")
        async def next_owner(turn):
            admitted.set()
            assert any("first owner completed" in str(message) for message in turn.messages)
            return _answer(turn)
        running = asyncio.create_task(first.run_turn("First turn.", execute=owner))
        await entered.wait()
        queued = asyncio.create_task(second.run_turn("Immediate next turn.", execute=next_owner))
        await asyncio.sleep(0)
        assert not admitted.is_set()
        release.set()
        assert (await running).ready and (await queued).ready
    asyncio.run(scenario())


def test_incognito_and_workspace_mismatch_fail_before_workspace_initialization(tmp_path):
    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite")
    workspace = tmp_path / "private-workspace"
    private = SessionState.new(session_key="agent:main:dashboard:incognito-hidden", session_id="private")
    with pytest.raises(ValueError, match="Incognito"):
        HostSessionRunner.open(workspace, catalog=catalog, session=private,
            config=MemoryConfig(workspace, flags=FeatureFlags(vector_search=False)))
    assert not workspace.exists()
    with pytest.raises(ValueError, match="same owner"):
        HostSessionRunner.open(workspace, catalog=catalog,
            session=SessionState.new(session_key=KEY, session_id=ID),
            config=MemoryConfig(tmp_path / "different-owner", flags=FeatureFlags(vector_search=False)))
    assert not workspace.exists()
    with pytest.raises(ValueError, match="different agents"):
        HostSessionRunner.open(workspace, catalog=catalog,
            session=SessionState.new(session_key=KEY, session_id=ID),
            config=MemoryConfig(workspace, agent_id="other", flags=FeatureFlags(vector_search=False)))
    assert not workspace.exists()


def test_real_tool_failure_is_visible_even_when_model_returns_a_reply(tmp_path):
    async def scenario():
        runner = _runner(tmp_path)
        async def model(turn):
            arguments = {"text": " "}
            _call(turn, "append_daily_note", arguments, "invalid-write")
            result = await turn.dispatch_async("invalid-write", "append_daily_note", arguments)
            assert result["status"] == "error"
            return _answer(turn, "The operation failed.")
        outcome = await runner.run_turn("Try an invalid note.", execute=model)
        assert not outcome.ready and not outcome.memory_writes_committed
        assert any(f.phase == "tool" for f in outcome.failures)
        assert outcome.index_status == "ready" and outcome.transcript_committed
    asyncio.run(scenario())


def test_failed_actual_flush_receipt_does_not_stamp_success(tmp_path):
    async def scenario():
        runner = _runner(tmp_path)
        async def model(turn):
            turn.record_message({"role": "assistant", "content": "I will retain the violet preference."})
            return HostModelResult(TurnUsage(176_000, 10))
        async def flush(turn):
            arguments = {"path": "memory/another-file.md", "content": "This path must be refused.\n"}
            _call(turn, "write", arguments, "refused-flush")
            actual = await turn.dispatch_async("refused-flush", "write", arguments)
            assert actual["status"] == "error" and actual["isError"] is True
        result = await runner.run_turn("Remember that I prefer violet tea.", execute=model, execute_flush=flush)
        assert not result.ready and not result.memory_writes_committed
        assert result.flush.failure is not None and not result.flush.wrote
        assert result.session.entry["memoryFlush"]["kind"] == "failed"
        assert any(failure.phase == "flush" for failure in result.failures)
        assert not (runner.kit.memory.workspace.root / "memory/another-file.md").exists()
        assert runner.catalog.get_session_entry(KEY)["memoryFlush"]["kind"] == "failed"
    asyncio.run(scenario())


def test_flush_body_commit_survives_index_failure_without_duplicate_append(tmp_path, monkeypatch):
    async def scenario():
        runner = _runner(tmp_path)
        reindex = runner.kit.memory.store.reindex
        monkeypatch.setattr(runner.kit.memory.store, "reindex", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("offline index write failure")))
        async def model(turn):
            turn.record_message({"role": "assistant", "content": "I will retain the lime preference."})
            return HostModelResult(TurnUsage(176_000, 10))
        async def flush(turn):
            arguments = {"path": turn.flush_request.target, "content": "The owner prefers lime tea.\n"}
            _call(turn, "write", arguments, "committed-flush")
            actual = await turn.dispatch_async("committed-flush", "write", arguments)
            assert actual["status"] == "ok" and "afterWriteError" in actual
        result = await runner.run_turn("Remember that I prefer lime tea.", execute=model, execute_flush=flush)
        assert result.flush.wrote and result.memory_writes_committed and result.index_status == "failed"
        assert result.session.entry["memoryFlush"]["kind"] == "succeeded"  # the body save succeeded
        note = runner.kit.memory.workspace.root / "memory/2026-11-09.md"
        before = note.read_bytes()
        monkeypatch.setattr(runner.kit.memory.store, "reindex", reindex)
        async def next_model(turn):
            return _answer(turn)
        async def no_duplicate(_turn):
            pytest.fail("Index repair must not repeat an already committed flush")
        assert (await runner.run_turn("Continue after index repair.", execute=next_model, execute_flush=no_duplicate)).ready
        assert note.read_bytes() == before
    asyncio.run(scenario())


def test_cancellation_after_actual_flush_body_retains_commit_without_success_stamp(tmp_path):
    async def scenario():
        runner = _runner(tmp_path)
        committed, finish = asyncio.Event(), asyncio.Event()
        async def model(turn):
            turn.record_message({"role": "assistant", "content": "The jade preference is ready to save."})
            return HostModelResult(TurnUsage(176_000, 10))
        async def flush(turn):
            arguments = {"path": turn.flush_request.target, "content": "The owner prefers jade tea.\n"}
            _call(turn, "write", arguments, "body-before-cancel")
            assert turn.dispatch("body-before-cancel", "write", arguments)["status"] == "ok"
            committed.set()
            await finish.wait()
        operation = asyncio.create_task(runner.run_turn("Remember my jade preference.", execute=model, execute_flush=flush))
        await committed.wait()
        operation.cancel()
        await asyncio.sleep(0)
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(operation, 5)
        outcome = runner.last_outcome
        assert outcome.cancelled and outcome.transcript_committed and outcome.memory_writes_committed
        assert outcome.flush.cancelled and outcome.flush.wrote
        assert outcome.flush.entries == ("The owner prefers jade tea.\n",)
        assert outcome.session.entry.get("memoryFlush", {}).get("kind") != "succeeded"
        assert runner.catalog.get_session_entry(KEY).get("memoryFlush", {}).get("kind") != "succeeded"
        assert any(failure.phase == "flush-authority" and failure.committed for failure in outcome.failures)
        note = runner.kit.memory.workspace.root / "memory/2026-11-09.md"
        assert note.read_text().count("jade tea") == 1
        async def next_model(turn):
            return _answer(turn)
        assert (await asyncio.wait_for(runner.run_turn("Continue after cancellation.", execute=next_model), 5)).ready
        assert note.read_text().count("jade tea") == 1
    asyncio.run(scenario())


def test_rotation_after_actual_flush_body_retains_commit_and_new_current_entry(tmp_path):
    async def scenario():
        runner = _runner(tmp_path)
        expected = []
        async def model(turn):
            turn.record_message({"role": "assistant", "content": "The ruby preference is ready to save."})
            return HostModelResult(TurnUsage(176_000, 10))
        async def flush(turn):
            arguments = {"path": turn.flush_request.target, "content": "The owner prefers ruby tea.\n"}
            _call(turn, "write", arguments, "body-before-rotation")
            assert turn.dispatch("body-before-rotation", "write", arguments)["status"] == "ok"
            runner.catalog.upsert_session(KEY, {"sessionId": "rotation-after-body", "outside": {"keep": 8}})
            expected.append(runner.catalog.get_session_entry(KEY))
        outcome = await runner.run_turn("Remember my ruby preference.", execute=model, execute_flush=flush)
        assert not outcome.ready and outcome.transcript_committed and outcome.memory_writes_committed
        assert outcome.flush.cancelled and outcome.flush.wrote
        assert outcome.flush.entries == ("The owner prefers ruby tea.\n",)
        assert outcome.session.entry.get("memoryFlush", {}).get("kind") != "succeeded"
        assert runner.catalog.get_session_entry(KEY) == expected[0]
        assert any(failure.phase == "flush-authority" and failure.committed for failure in outcome.failures)
        assert (runner.kit.memory.workspace.root / "memory/2026-11-09.md").read_text().count("ruby tea") == 1
    asyncio.run(scenario())


def test_observed_rotation_refuses_old_runner_messages_and_dispatch(tmp_path):
    async def scenario():
        runner = _runner(tmp_path)
        async def model(turn):
            arguments = {"text": "An invalidated owner must not write this."}
            _call(turn, "append_daily_note", arguments, "stale")
            runner.catalog.upsert_session(KEY, {"sessionId": "new-incarnation", "outside": "preserved"})
            with pytest.raises(RuntimeError, match="incarnation changed"):
                turn.record_message({"role": "assistant", "content": "Stale reply."})
            with pytest.raises(RuntimeError, match="incarnation changed"):
                await turn.dispatch_async("stale", "append_daily_note", arguments)
        outcome = await runner.run_turn("Start a turn before rotation.", execute=model)
        assert not outcome.ready and not outcome.memory_writes_committed
        assert runner.catalog.get_session_entry(KEY)["sessionId"] == "new-incarnation"
        assert runner.catalog.get_session_entry(KEY)["outside"] == "preserved"
        assert not (runner.kit.memory.workspace.root / "memory/2026-11-09.md").exists()
    asyncio.run(scenario())


def test_reentrant_callback_fails_instead_of_deadlocking_session_admission(tmp_path):
    async def scenario():
        runner = _runner(tmp_path)
        async def model(turn):
            with pytest.raises(RuntimeError, match="reenter"):
                await runner.run_turn("A nested turn cannot take the active lane.", execute=model)
            return _answer(turn)
        assert (await runner.run_turn("An ordinary outer turn.", execute=model)).ready
        events = runner.catalog.read_continuation(ID, session_key=KEY)["events"]
        assert sum(event.get("message", {}).get("role") == "user" for event in events) == 1
    asyncio.run(scenario())


def test_child_inherited_context_can_reenter_after_its_admission_owner_finishes(tmp_path):
    async def scenario():
        runner = _runner(tmp_path)
        outer_finished = asyncio.Event()
        children = []
        async def next_model(turn):
            assert any("The parent has finished" in str(message) for message in turn.messages)
            return _answer(turn)
        async def child():
            await outer_finished.wait()
            return await runner.run_turn("The child now owns a later turn.", execute=next_model)
        async def parent(turn):
            children.append(asyncio.create_task(child()))
            return _answer(turn, "The parent has finished.")
        assert (await runner.run_turn("The parent creates a future followup.", execute=parent)).ready
        outer_finished.set()
        assert (await asyncio.wait_for(children[0], 5)).ready
        assert sum(event.get("message", {}).get("role") == "user"
                   for event in runner.catalog.read_continuation(ID, session_key=KEY)["events"]) == 2
    asyncio.run(scenario())


def test_rejected_executor_submission_releases_dispatch_without_running_source(tmp_path):
    async def scenario():
        runner = _runner(tmp_path)
        loop = asyncio.get_running_loop()
        rejected_executor = ThreadPoolExecutor(max_workers=1)
        rejected_executor.shutdown()
        async def save(turn):
            arguments = {"text": "A rejected source must never save SCARLET-881."}
            _call(turn, "append_daily_note", arguments, "rejected")
            loop.set_default_executor(rejected_executor)
            with pytest.raises(RuntimeError, match="cannot schedule new futures"):
                await turn.dispatch_async("rejected", "append_daily_note", arguments)
            assert turn._active == 0
            assert turn.messages[-1]["role"] == "toolResult"
            assert turn.messages[-1]["isError"] is True
            return _answer(turn, "The host could not schedule this write.")
        try:
            outcome = await asyncio.wait_for(runner.run_turn("Remember my scarlet token.", execute=save), 5)
        finally:
            # Restore a genuine usable host executor so repair and the next
            # admission exercise the normal physical worker path.
            loop.set_default_executor(ThreadPoolExecutor(max_workers=2))
        assert outcome.transcript_committed and not outcome.memory_writes_committed
        assert not outcome.ready and outcome.index_status == "failed"
        assert any(failure.phase == "tool-scheduling" and failure.error_type == "RuntimeError"
                   for failure in outcome.failures)
        receipt, = outcome.tools
        assert receipt["sourceExecuted"] is False
        assert "cannot schedule new futures" in receipt["schedulingError"]["message"]
        assert "result" not in receipt and "error" not in receipt
        note = runner.kit.memory.workspace.root / "memory/2026-11-09.md"
        assert not note.exists()
        async def recovered(turn):
            arguments = {"text": "The recovered host saves EMERALD-442."}
            _call(turn, "append_daily_note", arguments, "recovered")
            assert (await turn.dispatch_async("recovered", "append_daily_note", arguments))["status"] == "ok"
            return _answer(turn)
        assert (await asyncio.wait_for(runner.run_turn("Remember my emerald token.", execute=recovered), 5)).ready
        assert "EMERALD-442" in note.read_text() and "SCARLET-881" not in note.read_text()
    asyncio.run(scenario())


def test_terminal_producer_cancellation_joins_real_publication_before_releasing_lane(tmp_path, monkeypatch):
    async def scenario():
        runner = _runner(tmp_path)
        reindex = runner.kit.memory.store.reindex
        entered, release = threading.Event(), threading.Event()
        count = 0
        def actual_publication(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 2:  # first is the actual curated write's refresh; second is final publication
                entered.set()
                assert release.wait(5), "The actual publication producer must be released"
            return reindex(*args, **kwargs)
        monkeypatch.setattr(runner.kit.memory.store, "reindex", actual_publication)
        async def save(turn):
            arguments = {"text": "The owner keeps the terminal code COPPER-531."}
            _call(turn, "append_daily_note", arguments, "committed")
            await turn.dispatch_async("committed", "append_daily_note", arguments)
            return _answer(turn)
        operation = asyncio.create_task(runner.run_turn("Remember my terminal code COPPER-531.", execute=save))
        assert await asyncio.to_thread(entered.wait, 5)
        actual_producers = [task for task in asyncio.all_tasks()
            if getattr(task.get_coro(), "__qualname__", "") == HostSessionRunner._produce.__qualname__]
        assert len(actual_producers) == 1
        actual_producers[0].cancel()  # terminate the owner itself, not merely its caller/dispatch future
        admitted = asyncio.Event()
        async def recall(turn):
            admitted.set()
            arguments = {"query": "COPPER-531", "corpus": "memory", "minScore": 0}
            _call(turn, "memory_search", arguments, "after-terminal-cancel")
            result = await turn.dispatch_async("after-terminal-cancel", "memory_search", arguments)
            assert any("COPPER-531" in hit["snippet"] for hit in result["results"])
            return _answer(turn)
        next_turn = asyncio.create_task(runner.run_turn("Recall the terminal code.", execute=recall))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert actual_producers[0].cancelled()
        assert not operation.done() and not admitted.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(operation, 5)
        cancelled = runner.last_outcome
        assert cancelled.cancelled and cancelled.memory_writes_committed and cancelled.transcript_committed
        assert cancelled.index_status == "failed" and cancelled.failures[0].phase == "producer"
        assert (await asyncio.wait_for(next_turn, 5)).ready
        assert admitted.is_set()
        note = runner.kit.memory.workspace.root / "memory/2026-11-09.md"
        assert note.read_text().count("COPPER-531") == 1
    asyncio.run(scenario())


def test_rotation_before_due_finalization_creates_no_stale_flush_target(tmp_path):
    async def scenario():
        runner = _runner(tmp_path)
        expected = []
        async def model(turn):
            turn.record_message({"role": "assistant", "content": "The visible response completed."})
            runner.catalog.upsert_session(KEY, {"sessionId": "rotated-before-flush", "outside": {"keep": 7}})
            expected.append(runner.catalog.get_session_entry(KEY))
            return HostModelResult(TurnUsage(176_000, 10))
        async def never(_turn):
            pytest.fail("The rotated owner cannot start its old flush")
        outcome = await runner.run_turn("Remember the pending indigo preference.", execute=model, execute_flush=never)
        assert not outcome.ready
        assert any("incarnation changed" in failure.message for failure in outcome.failures)
        assert runner.catalog.get_session_entry(KEY) == expected[0]
        assert not (runner.kit.memory.workspace.root / "memory/2026-11-09.md").exists()
    asyncio.run(scenario())


def test_caller_cancellation_before_due_flush_preserves_usage_without_target(tmp_path):
    async def scenario():
        runner = _runner(tmp_path)
        entered, finish = asyncio.Event(), asyncio.Event()
        async def model(turn):
            turn.record_message({"role": "assistant", "content": "The visible response completed."})
            entered.set()
            await finish.wait()
            return HostModelResult(TurnUsage(176_000, 10))
        async def never(_turn):
            pytest.fail("Caller cancellation cannot start fresh optional flush work")
        operation = asyncio.create_task(runner.run_turn("Remember my pending sage preference.", execute=model, execute_flush=never))
        await entered.wait()
        operation.cancel()
        await asyncio.sleep(0)
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await operation
        outcome = runner.last_outcome
        assert outcome.cancelled and outcome.transcript_committed
        assert outcome.session.entry["totalTokens"] == 176_000
        assert runner.catalog.get_session_entry(KEY)["totalTokens"] == 176_000
        assert not (runner.kit.memory.workspace.root / "memory/2026-11-09.md").exists()
    asyncio.run(scenario())
