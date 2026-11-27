"""Real optional flushes retain custody while foreground work takes priority."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import gc
import json
import os
import sys

import pytest

from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.host.lifecycle import FlushModelExecutor, FlushModelUnavailable, HostModelResult
from memory_core.host.managed_maintenance import schedule_optional
from memory_core.host.managed_session import ManagedHostSession
from memory_core.host.session import SessionState, TurnUsage
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.session_visibility import resolve_memory_search_source_policy
from memory_core.workspace import workspace_file_lock


NOW = 1_794_182_400_000
KEY = "agent:main:dm:optional-maintenance"
ID = "optional-maintenance"
STATE = SessionState.new(session_key=KEY, session_id=ID)
FACT = "The maintenance calibration token is SAFFRON-673.\n"


def _owner(tmp_path, *, maintenance="background", flush_config=None, **options):
    root = tmp_path / "workspace"
    root.mkdir(exist_ok=True)
    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite", clock_ms=lambda: NOW)
    config = MemoryConfig(root, store_path=tmp_path / "index.sqlite", citation_mode="off",
                          flags=FeatureFlags(vector_search=False, temporal_decay=False))
    policy = resolve_memory_search_source_policy(["memory"], remember_across_conversations=False)
    return ManagedHostSession.open(root, catalog=catalog, config=config, source_policy=policy,
        maintenance=maintenance, memory_publication="on-search", timezone="UTC", now_ms=lambda: NOW, flush_config=flush_config,
        identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY, **options)


def _answer(turn, *, due=False):
    turn.record_message({"role": "assistant", "content": [{"type": "text", "text": "Done."}]})
    return HostModelResult(TurnUsage(176_000 if due else 20, 3))


async def _due(turn):
    return _answer(turn, due=True)


async def _ordinary(turn):
    return _answer(turn)


async def _write(turn):
    args = {"path": turn.flush_request.target, "content": FACT}
    turn.record_message({"role": "assistant", "content": [{"type": "toolCall", "id": "save",
        "name": "write", "arguments": deepcopy(args)}]})
    return await turn.dispatch_async("save", "write", args)


async def _join(owner):
    for job in tuple(owner._maintenance_jobs):
        await asyncio.wait_for(job.join(), 5)


@pytest.mark.parametrize("option", ["maintenance", "interrupted_publication"])
@pytest.mark.parametrize("value", ["later", None, True])
def test_invalid_maintenance_policy_is_rejected_before_workspace_creation(tmp_path, value, option):
    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite")
    root = tmp_path / "absent"
    with pytest.raises(ValueError, match=option):
        ManagedHostSession.open(root, catalog=catalog, **{option: value})
    assert not root.exists()


def test_new_compatibility_turn_can_flush_without_restarting_old_maintenance(tmp_path):
    async def scenario():
        owner = _owner(tmp_path, interrupted_publication="openclaw")
        runner = owner.runner(STATE)
        old = {"turnId": "old", "publication": "uncertain", "stage": "intent",
               "workspace": str(owner.kit.memory.workspace.root), "indexPath": str(owner.store.path),
               "provenancePath": str(runner.artifact_provenance.path)}
        owner.catalog.upsert_session(KEY, {"sessionId": ID, "sdkHostLifecycle": {
            "version": 1, "lastTurnId": "old", "publicationMode": "managed",
            "needsIndex": True, "needsMemoryIndex": True, "pendingMemoryPublication": old}})
        flushes = []

        async def flush(turn):
            flushes.append(turn.turn_id)
            await _write(turn)

        try:
            duplicate = await runner.run_turn("Old request", execute=_due, execute_flush=flush, request_id="old")
            assert not duplicate.transcript_committed and not owner.maintenance_status()["jobs"]
            reply = await runner.run_turn("Save the new calibration", execute=_due,
                                          execute_flush=flush, request_id="new")
            assert not reply.failures, reply.failures
            assert reply.transcript_committed
            await _join(owner)
            assert len(flushes) == 1
            assert (owner.kit.memory.workspace.root / "memory/2026-11-09.md").read_text() == FACT
            assert owner.publication_status()["memoryIndexStatus"] == "pending"
            owner.reindex(force=True)
            metadata = owner.catalog.get_session_entry(KEY)["sdkHostLifecycle"]
            assert metadata["interruptedMemoryPublications"] == [old]
            assert metadata["needsMemoryIndex"] is False
            assert "pendingMemoryPublication" not in metadata and "lastMemoryPublicationAcknowledgment" not in metadata
        finally:
            await owner.aclose()

        strict = _owner(tmp_path)
        try:
            blocked = await strict.runner(STATE).run_turn("Next", execute=_ordinary, request_id="after-restart")
            assert not blocked.transcript_committed and not strict.maintenance_status()["jobs"]
            await strict.runner(STATE).acknowledge_memory_publication(expected_turn_id="old")
            metadata = strict.catalog.get_session_entry(KEY)["sdkHostLifecycle"]
            assert metadata["interruptedMemoryPublications"] == [{**old, "acknowledgedAt": NOW}]
            continued = await strict.runner(STATE).run_turn("Next", execute=_ordinary, request_id="after-restart")
            assert continued.transcript_committed and not continued.failures
        finally:
            await strict.aclose()

    asyncio.run(scenario())


def test_pending_due_work_yields_before_body_and_usage_is_not_applied_twice(tmp_path):
    async def scenario():
        owner = _owner(tmp_path)
        runner = owner.runner(STATE)
        called = []

        async def flush(turn):
            called.append(turn)
            await _write(turn)

        try:
            first = await runner.run_turn("Retain the saffron preference.", execute=_due,
                                          execute_flush=flush, request_id="first")
            assert first.flush is None and not first.memory_writes_committed
            pending = owner.maintenance_status()["jobs"][-1]
            assert pending["state"] == "pending" and not pending["running"]

            async def next_turn(turn):
                assert not called
                assert turn.session.entry["totalTokens"] == 176_000
                assert turn.session.entry["totalTokensFresh"] is True
                assert turn.session.last_output_tokens == 3
                assert owner.maintenance_status()["jobs"][0]["state"] == "cancelled"
                return _answer(turn)

            second = await runner.run_turn("Ask immediately.", execute=next_turn, execute_flush=flush)
            assert not second.failures and not called
            assert not list(owner.kit.memory.workspace.root.glob("memory/*.md"))
            json.dumps(owner.maintenance_status())
        finally:
            await owner.aclose()

    asyncio.run(scenario())


def test_running_real_write_joins_provider_cleanup_before_two_next_admissions(tmp_path):
    async def scenario():
        owner = _owner(tmp_path)
        runner = owner.runner(STATE)
        written, abort, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        admitted = []
        cancellations = []

        async def flush(turn):
            actual = await _write(turn)
            assert actual["status"] == "ok" and actual["action"] == "appended"
            written.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cancellations.append("actual provider abort")
                abort.set()
                await release.wait()

        async def next_turn(turn):
            admitted.append(turn.turn_id)
            assert release.is_set()
            return _answer(turn)

        try:
            await runner.run_turn("Retain a fact.", execute=_due, execute_flush=flush, request_id="first")
            await asyncio.wait_for(written.wait(), 5)
            source = next(owner.kit.memory.workspace.root.glob("memory/*.md"))
            assert source.read_text() == FACT
            first = asyncio.create_task(owner.runner(STATE).run_turn("Question one.", execute=next_turn))
            await asyncio.wait_for(abort.wait(), 5)
            second = asyncio.create_task(owner.runner(STATE).run_turn("Question two.", execute=next_turn))
            await asyncio.sleep(0)
            gc.collect()
            assert not admitted and len(cancellations) == 1
            assert not owner.maintenance_status()["jobs"][0]["settled"]
            release.set()
            await asyncio.gather(first, second)
            outcome = owner.maintenance_status()["jobs"][0]["outcome"]
            assert outcome["memory_writes_committed"] and outcome["cancelled"]
            assert outcome["flush"]["cancelled"]
            assert "memoryFlush" not in outcome["session"]["entry"]
            assert len(admitted) == 2 and len(cancellations) == 1
            reopened = MemorySessionCatalog(owner.catalog.path).get_session_entry(KEY)
            assert "memoryFlush" not in reopened
            provenance = owner.kit.memory.store.artifact_provenance.read(
                workspace_dir=owner.kit.memory.workspace.root, relative_path=source.relative_to(owner.kit.memory.workspace.root).as_posix())
            assert provenance.origin_class == "untrusted"
            json.dumps(owner.maintenance_status())
        finally:
            release.set()
            await owner.aclose()

    asyncio.run(scenario())


def test_another_managed_owner_for_same_catalog_can_preempt_the_actual_job(tmp_path):
    async def scenario():
        first = _owner(tmp_path)
        second = _owner(tmp_path)
        written = asyncio.Event()
        cancelled = []

        async def flush(turn):
            await _write(turn)
            written.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cancelled.append(True)

        try:
            await first.runner(STATE).run_turn("Save.", execute=_due, execute_flush=flush)
            await asyncio.wait_for(written.wait(), 5)
            await second.runner(STATE).run_turn("New question.", execute=_ordinary)
            assert cancelled == [True]
            assert first.maintenance_status()["jobs"][0]["settled"]
        finally:
            await first.aclose()
            await second.aclose()

    asyncio.run(scenario())


def test_real_hardlink_refusal_is_retained_in_job_and_durable_session_state(tmp_path):
    async def scenario():
        owner = _owner(tmp_path)
        actual = []

        async def flush(turn):
            target = owner.kit.memory.workspace.root / turn.flush_request.target
            link = tmp_path / "held-hardlink"
            os.link(target, link)
            try:
                actual.append(await _write(turn))
            finally:
                link.unlink()

        try:
            await owner.runner(STATE).run_turn("Save the fact.", execute=_due, execute_flush=flush)
            await _join(owner)
            assert actual[0]["status"] == "error"
            outcome = owner.maintenance_status()["jobs"][0]["outcome"]
            assert not outcome["memory_writes_committed"] and outcome["failures"]
            assert outcome["flush"]["failure"]["failure_count"] == 1
            reopened = MemorySessionCatalog(owner.catalog.path).get_session_entry(KEY)
            assert reopened["memoryFlush"]["kind"] == "failed"
            assert next(owner.kit.memory.workspace.root.glob("memory/*.md")).read_bytes() == b""
            json.dumps(owner.maintenance_status())
        finally:
            await owner.aclose()

    asyncio.run(scenario())


def test_close_cancels_pending_work_and_joins_running_provider_settlement(tmp_path):
    async def scenario():
        owner = _owner(tmp_path)
        written, aborted, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def flush(turn):
            await _write(turn)
            written.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                aborted.set()
                await release.wait()

        await owner.runner(STATE).run_turn("Save.", execute=_due, execute_flush=flush)
        await asyncio.wait_for(written.wait(), 5)
        with pytest.raises(RuntimeError, match="active"):
            owner.close()
        closing = asyncio.create_task(owner.aclose())
        try:
            await asyncio.wait_for(aborted.wait(), 5)
            assert not closing.done() and not owner.store.closed
            with pytest.raises(RuntimeError, match="closed"):
                owner.runner(STATE)
            closing.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await closing
            assert owner.store.closed and owner.maintenance_status()["jobs"][0]["settled"]
        finally:
            release.set()
            await owner.aclose()

    asyncio.run(scenario())


def test_maintenance_callback_cannot_reenter_or_close_its_own_owner(tmp_path):
    async def scenario():
        owner = _owner(tmp_path)
        runner = owner.runner(STATE)
        checked = []

        async def flush(turn):
            with pytest.raises(RuntimeError, match="reenter"):
                await runner.run_turn("Recursive question.", execute=_ordinary)
            with pytest.raises(RuntimeError, match="own managed owner"):
                await owner.aclose()
            checked.append(True)
            await _write(turn)

        try:
            await runner.run_turn("Save.", execute=_due, execute_flush=flush)
            await _join(owner)
            assert checked == [True]
            assert owner.maintenance_status()["jobs"][0]["outcome"]["flush"]["wrote"]
        finally:
            await owner.aclose()

    asyncio.run(scenario())


def test_queued_foreground_retires_an_older_optional_spec_before_it_can_write(tmp_path):
    async def scenario():
        owner = _owner(tmp_path)
        first = owner.runner(STATE)
        second = owner.runner(STATE)
        started, release, second_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
        called = []

        async def model(turn):
            started.set()
            await release.wait()
            return _answer(turn, due=True)

        async def flush(turn):
            called.append(True)
            await _write(turn)

        async def newer(turn):
            second_started.set()
            return _answer(turn)

        try:
            a = asyncio.create_task(first.run_turn("First question.", execute=model, execute_flush=flush, request_id="first"))
            await started.wait()
            b = asyncio.create_task(second.run_turn("Already queued.", execute=newer, request_id="second"))
            await asyncio.sleep(0)
            release.set()
            await asyncio.gather(a, b)
            await _join(owner)
            assert second_started.is_set() and not called
            assert owner.catalog.get_session_entry(KEY)["sdkHostLifecycle"]["lastTurnId"] == "second"
            assert owner.maintenance_status()["jobs"][0]["outcome"]["cancelled"]
        finally:
            await owner.aclose()

    asyncio.run(scenario())


def test_actual_delivery_acknowledgment_holds_lane_after_pending_owner_preemption(tmp_path):
    async def scenario():
        owner = _owner(tmp_path)
        delivered, acknowledge, admitted = asyncio.Event(), asyncio.Event(), asyncio.Event()
        called = []

        async def flush(turn):
            called.append(True)
            await _write(turn)

        async def deliver(outcome):
            assert outcome.payloads == ()
            pending = owner.maintenance_status()["jobs"][-1]
            assert pending["state"] == "pending" and not pending["running"]
            delivered.set()
            await acknowledge.wait()

        async def next_turn(turn):
            assert acknowledge.is_set()
            admitted.set()
            return _answer(turn)

        first = asyncio.create_task(owner.runner(STATE).run_turn("Save.", execute=_due,
            execute_flush=flush, deliver=deliver, request_id="delivered"))
        try:
            await asyncio.wait_for(delivered.wait(), 5)
            job = next(iter(owner._maintenance_jobs))
            second = asyncio.create_task(owner.runner(STATE).run_turn("Ask immediately.", execute=next_turn))
            await asyncio.wait_for(job.cancel_requested.wait(), 5)
            assert not first.done() and not admitted.is_set() and not called
            acknowledge.set()
            await asyncio.gather(first, second)
            assert admitted.is_set() and not called
            assert owner.maintenance_status()["jobs"][0]["state"] == "cancelled"
        finally:
            acknowledge.set()
            await owner.aclose()

    asyncio.run(scenario())


def test_real_failed_delivery_does_not_run_optional_work_or_erase_committed_foreground(tmp_path):
    async def scenario():
        owner = _owner(tmp_path)
        runner = owner.runner(STATE)
        read_end, write_end = os.pipe()
        os.close(read_end)
        called = []

        async def deliver(outcome):
            os.write(write_end, b"the actual reply transport has closed")

        async def flush(turn):
            called.append(True)
            await _write(turn)

        try:
            with pytest.raises(BrokenPipeError):
                await runner.run_turn("Reply once.", execute=_due, execute_flush=flush, deliver=deliver)
            await _join(owner)
            assert runner.last_outcome.transcript_committed
            assert runner.last_outcome.failures[-1].phase == "delivery"
            assert runner.last_outcome.session.entry["totalTokens"] == 176_000
            assert not called
            assert owner.maintenance_status()["jobs"][0]["state"] == "cancelled"
            continuation = owner.catalog.read_continuation(ID, session_key=KEY)
            assert len([m for m in continuation["llmMessages"] if m["role"] == "user"]) == 1
        finally:
            os.close(write_end)
            await owner.aclose()

    asyncio.run(scenario())


def test_cancelled_delivery_caller_retains_real_acknowledgment_custody(tmp_path):
    async def scenario():
        owner = _owner(tmp_path)
        runner = owner.runner(STATE)
        delivered, acknowledge = asyncio.Event(), asyncio.Event()

        async def deliver(outcome):
            delivered.set()
            await acknowledge.wait()

        first = asyncio.create_task(runner.run_turn("Reply.", execute=_due, deliver=deliver))
        try:
            await asyncio.wait_for(delivered.wait(), 5)
            first.cancel()
            await asyncio.sleep(0)
            assert not first.done()
            acknowledge.set()
            with pytest.raises(asyncio.CancelledError):
                await first
            await _join(owner)
            assert runner.last_outcome.cancelled and runner.last_outcome.transcript_committed
            assert owner.maintenance_status()["jobs"][0]["state"] == "cancelled"
        finally:
            acknowledge.set()
            await owner.aclose()

    asyncio.run(scenario())


def test_close_during_delivery_cannot_admit_a_late_optional_writer(tmp_path):
    async def scenario():
        owner = _owner(tmp_path)
        delivered, acknowledge = asyncio.Event(), asyncio.Event()
        called = []

        async def deliver(outcome):
            delivered.set()
            await acknowledge.wait()

        async def flush(turn):
            called.append(True)
            await _write(turn)

        first = asyncio.create_task(owner.runner(STATE).run_turn("Save.", execute=_due,
            execute_flush=flush, deliver=deliver))
        try:
            await asyncio.wait_for(delivered.wait(), 5)
            closing = asyncio.create_task(owner.aclose())
            await asyncio.sleep(0)
            assert not closing.done() and not owner.store.closed
            with pytest.raises(RuntimeError, match="closed"):
                owner.runner(STATE)
            acknowledge.set()
            await asyncio.gather(first, closing)
            assert owner.store.closed and not called
        finally:
            acknowledge.set()
            await owner.aclose()

    asyncio.run(scenario())


def test_pending_owner_rejects_foreground_from_a_different_event_loop(tmp_path):
    async def scenario():
        owner = _owner(tmp_path)
        runner = owner.runner(STATE)
        delivered, acknowledge = asyncio.Event(), asyncio.Event()

        async def deliver(outcome):
            delivered.set()
            await acknowledge.wait()

        first = asyncio.create_task(runner.run_turn("Save.", execute=_due, deliver=deliver))
        try:
            await asyncio.wait_for(delivered.wait(), 5)
            other = owner.runner(STATE)
            with pytest.raises(RuntimeError, match="another event loop"):
                await asyncio.to_thread(lambda: asyncio.run(other.run_turn("Foreign loop.", execute=_ordinary)))
            acknowledge.set()
            await first
        finally:
            acknowledge.set()
            await owner.aclose()

    asyncio.run(scenario())


def test_optional_settlement_task_survives_collection_of_a_bare_provider_wait(tmp_path):
    async def scenario():
        entered = asyncio.Event()
        completed = []

        async def run(job):
            entered.set()
            await asyncio.Future()

        job = schedule_optional((str(tmp_path / "catalog.sqlite"), "main", KEY), run,
                                lambda value: completed.append(value))
        try:
            await entered.wait()
            gc.collect()
            await asyncio.sleep(0)
            assert job.running and not job.done.done() and not completed
        finally:
            # No producer was admitted; this explicitly shuts down the regression fixture.
            job._task.cancel()
            await job.join()
        assert completed == [job]

    asyncio.run(scenario())


def test_preempted_target_preparation_joins_the_real_file_lock_before_next_admission(tmp_path):
    async def scenario():
        owner = _owner(tmp_path)
        runner = owner.runner(STATE)
        target = owner.kit._flush_plan(200_000).relative_path
        lock = workspace_file_lock(owner.kit.memory.workspace.root, target)
        lock.acquire()
        admitted = asyncio.Event()

        async def next_turn(turn):
            admitted.set()
            return _answer(turn)

        async def prepared():
            while True:
                entry = owner.catalog.get_session_entry(KEY)
                if entry["sdkHostLifecycle"].get("pendingMemoryPublication"):
                    return
                await asyncio.sleep(0)

        try:
            await runner.run_turn("Save.", execute=_due, request_id="held-preparation")
            await asyncio.wait_for(prepared(), 5)
            job = next(iter(owner._maintenance_jobs))
            second = asyncio.create_task(owner.runner(STATE).run_turn("Next.", execute=next_turn))
            await asyncio.wait_for(job.cancel_requested.wait(), 5)
            assert not admitted.is_set() and not job.done.done()
            lock.release()
            await asyncio.wait_for(second, 5)
            assert admitted.is_set() and job.done.done()
            assert not (owner.kit.memory.workspace.root / target).exists()
            assert "pendingMemoryPublication" not in owner.catalog.get_session_entry(KEY)["sdkHostLifecycle"]
        finally:
            if lock.locked():
                lock.release()
            await owner.aclose()

    asyncio.run(scenario())


def test_cancellation_after_actual_ack_withdraws_optional_authority_before_release(tmp_path):
    async def scenario():
        owner = _owner(tmp_path)
        acknowledged, called = [], []
        operation = None

        async def deliver(outcome):
            acknowledged.append(True)
            asyncio.get_running_loop().call_soon(operation.cancel)

        async def flush(turn):
            called.append(True)
            await _write(turn)

        try:
            operation = asyncio.create_task(owner.runner(STATE).run_turn("Reply.", execute=_due,
                execute_flush=flush, deliver=deliver))
            with pytest.raises(asyncio.CancelledError):
                await operation
            await _join(owner)
            assert acknowledged == [True] and not called
            assert owner.maintenance_status()["jobs"][0]["state"] == "cancelled"
            assert not list(owner.kit.memory.workspace.root.glob("memory/*.md"))
        finally:
            await owner.aclose()

    asyncio.run(scenario())


def test_cancelled_caller_keeps_cancellation_after_actual_transport_failure_settles(tmp_path):
    async def scenario():
        owner = _owner(tmp_path)
        runner = owner.runner(STATE)
        delivered, release = asyncio.Event(), asyncio.Event()
        read_end, write_end = os.pipe()
        os.close(read_end)

        async def deliver(outcome):
            delivered.set()
            await release.wait()
            os.write(write_end, b"closed transport")

        operation = asyncio.create_task(runner.run_turn("Reply.", execute=_due, deliver=deliver))
        try:
            await delivered.wait()
            operation.cancel()
            await asyncio.sleep(0)
            assert not operation.done()
            release.set()
            with pytest.raises(asyncio.CancelledError) as caught:
                await operation
            assert isinstance(caught.value.__cause__, BrokenPipeError)
            assert runner.last_outcome.cancelled and runner.last_outcome.transcript_committed
            assert runner.last_outcome.failures[-1].phase == "delivery"
            assert runner.last_outcome.failures[-1].error_type == "BrokenPipeError"
            await _join(owner)
            assert owner.maintenance_status()["jobs"][0]["state"] == "cancelled"
        finally:
            release.set()
            os.close(write_end)
            await owner.aclose()

    asyncio.run(scenario())

@pytest.mark.parametrize(("configured", "routes", "exact"), [
    (None, [("conversation", "primary"), ("other", "backup")], False),
    ("maintenance", [("conversation", "maintenance")], True),
    ("local/unavailable", [("local", "unavailable")], True),
])
def test_automatic_flush_dispatches_real_model_candidates(tmp_path, configured, routes, exact):
    async def scenario():
        owner = _owner(tmp_path, maintenance="inline", flush_config={"model": configured})
        script = tmp_path / "model.py"
        script.write_text(
            "import json, os, sys\n"
            "with open(sys.argv[1], 'a') as out:\n"
            "    print(json.dumps([os.getpid(), *sys.argv[2:]]), file=out)\n"
            "sys.exit(75 if sys.argv[3] in ('primary', 'unavailable') else 0)\n"
        )
        log = tmp_path / "candidate-calls.jsonl"
        selections = []

        async def execute_candidate(turn, route, selection):
            selections.append((selection.requested_route_resolution, selection.fallbacks_override))
            assert turn.flush_request is not None
            process = await asyncio.create_subprocess_exec(sys.executable, str(script), str(log), route.provider, route.model)
            if await process.wait():
                raise FlushModelUnavailable("Local test transport exhausted")
            return None

        try:
            executor = FlushModelExecutor("conversation", "primary", ["other/backup"], execute_candidate)
            outcome = await owner.runner(STATE).run_turn("Save this fact.", execute=_due, execute_flush=executor)
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            assert all(pid != os.getpid() for pid, _, _ in calls)
            assert [(provider, model) for _, provider, model in calls] == routes
            assert selections == [(("raw", ()) if exact else (None, None))] * len(routes)
            assert bool(outcome.failures) is (configured == "local/unavailable")
        finally:
            await owner.aclose()

    asyncio.run(scenario())
