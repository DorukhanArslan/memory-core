"""Recovery custody at the SQLite admission and process-interruption boundaries."""
import asyncio
from multiprocessing import get_context

import pytest

from memory_core import curation
from tests.unit.test_host_publication_settlement import ID, KEY, _auxiliary, _interrupted_turn, _runner, _save, _target


def _pause_before_result(root, pipe):
    runner = _runner(root)
    _target(runner)
    publish = curation.commit_memory_content

    def pause(*args, **kwargs):
        result = publish(*args, **kwargs)
        pipe.send("published")
        pipe.recv()
        return result

    curation.commit_memory_content = pause
    asyncio.run(runner.run_turn("Save", execute=_save, request_id="original"))


def test_live_writer_retains_custody_until_process_exit(tmp_path):
    context = get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_pause_before_result, args=(tmp_path, child))
    process.start()
    child.close()
    calls = []

    async def followup(turn):
        calls.append(turn.model_request()["messages"])

    try:
        assert parent.poll(15) and parent.recv() == "published"
        reopened = _runner(tmp_path, interrupted_publication="openclaw")
        before = reopened.catalog.read_continuation(ID, session_key=KEY)
        refused = asyncio.run(reopened.run_turn("Next", request_id="new", execute=followup))
        assert not refused.transcript_committed and calls == []
        assert "may still be active" in refused.failures[0].message
        with pytest.raises(RuntimeError, match="may still be active"):
            asyncio.run(reopened.acknowledge_memory_publication(expected_turn_id="original"))
        assert reopened.catalog.read_continuation(ID, session_key=KEY) == before
    finally:
        process.terminate()
        process.join(10)
        parent.close()
    assert process.exitcode is not None
    accepted = asyncio.run(reopened.run_turn("Next", request_id="new", execute=followup))
    assert accepted.transcript_committed and not accepted.failures
    assert [msg["isError"] for msg in calls[0] if msg.get("toolCallId") == "save"] == [True]
    assert _auxiliary(reopened)["interruptedMemoryPublications"] == [
        before["instanceEntry"]["sdkHostLifecycle"]["pendingMemoryPublication"]]
    assert (reopened.kit.memory.workspace.root / "MEMORY.md").read_text().count("- new\n") == 1


def test_changed_publication_aborts_admission_without_consuming_either_turn(tmp_path, monkeypatch):
    recovering = _runner(tmp_path, interrupted_publication="openclaw")
    peer = _runner(tmp_path)
    marker = _interrupted_turn(recovering)
    before = recovering.catalog.read_transcript(ID, session_key=KEY)
    append = recovering.catalog.append_message

    def race(*args, **kwargs):
        entry = peer.catalog.get_session_entry(KEY)
        entry["sdkHostLifecycle"]["pendingMemoryPublication"] = {**marker, "stage": "uncertain"}
        peer.catalog.upsert_session(KEY, entry)
        return append(*args, **kwargs)

    monkeypatch.setattr(recovering.catalog, "append_message", race)
    result = asyncio.run(recovering.run_turn("Next", request_id="new", execute=_save))
    assert not result.transcript_committed and not result.tools
    assert "changed before admission" in result.failures[0].message
    assert recovering.catalog.read_transcript(ID, session_key=KEY).events == before.events
    assert _auxiliary(recovering)["pendingMemoryPublication"] == {**marker, "stage": "uncertain"}
    assert "interruptedMemoryPublications" not in _auxiliary(recovering)
