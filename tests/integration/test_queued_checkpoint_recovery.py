"""A queued user and a provider checkpoint share one foreground admission transaction."""

import asyncio

import pytest

from equivalence.compaction_assembly_inputs import inputs
from equivalence.compaction_assembly_sdk import drive
from memory_core.compaction_replay import ReplayModel
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.host import (
    HistoryReplayContext,
    HostSessionRunner,
    ProviderTurnExecutor,
    RuntimePromptInput,
    SessionState,
)
from memory_core.session_catalog import MemorySessionCatalog


@pytest.mark.parametrize("mode", ["queued", "internal-restart", "concurrent-writer"])
def test_queued_checkpoint_recovery_publishes_with_the_foreground_admission(tmp_path, mode):
    async def exercise():
        seed = inputs()["retained"]
        await drive({"input": seed}, tmp_path, "seed")
        clock = seed["attemptMs"]
        model = ReplayModel("openai", "openai-responses", "gpt-5.4", seed["model"]["baseUrl"])
        key, sid = seed["sessionKey"], seed["sessionId"]
        db, workspace = tmp_path / "catalog.sqlite", tmp_path / "workspace"
        catalog = MemorySessionCatalog(db, clock_ms=lambda: clock)
        queued = {"role": "user", "content": "Queued orchard note", "timestamp": clock - 1}
        catalog.append_message(sid, queued, session_key=key, event_id="external-user", now_ms=clock - 1)
        catalog.append_events(
            sid,
            [
                {
                    "type": "custom",
                    "id": "external-metadata",
                    "parentId": "external-user",
                    "customType": "test-queued-metadata",
                    "data": {"source": "queued"},
                }
            ],
            session_key=key,
        )
        runner = HostSessionRunner.open(
            workspace,
            catalog=catalog,
            session=SessionState.new(session_key=key, session_id=sid),
            config=MemoryConfig(
                workspace_dir=workspace,
                store_path=tmp_path / "index.sqlite",
                flags=FeatureFlags(vector_search=False),
            ),
            seed_bootstrap=False,
            now_ms=lambda: clock,
        )
        requests, summaries = [], []

        async def provider(request):
            requests.append(request)
            return {
                "role": "assistant",
                "api": model.api,
                "provider": model.provider,
                "model": model.id,
                "timestamp": clock,
                "stopReason": "stop",
                "content": [{"type": "text", "text": "Ready."}],
            }

        async def summarize(request):
            summaries.append(request)
            if mode == "concurrent-writer" and len(summaries) == 1:
                other = MemorySessionCatalog(db, clock_ms=lambda: clock)
                other.append_message(
                    sid,
                    {"role": "user", "content": "Independent update"},
                    session_key=key,
                    event_id="concurrent",
                    now_ms=clock,
                )
            return "Reviewed the earlier messages."

        foreground = {"role": "user", "content": "Continue with the orchard. " * 5400}
        if mode == "internal-restart":
            foreground["provenance"] = {
                "kind": "internal_system",
                "sourceTool": "main_session_restart_recovery",
            }
        outcome = await runner.run_turn(
            foreground,
            execute=ProviderTurnExecutor(model, 16_000, provider, summarize, keep_recent_tokens=512),
            request_id="new-foreground",
            prompt_context=RuntimePromptInput(history_replay=HistoryReplayContext(model)),
        )
        assert summaries
        physical = list(catalog.read_transcript(sid).events)
        visible = catalog.read_continuation(sid, session_key=key)["visibleEvents"]
        assert any(e.get("id") == "external-user" for e in physical)
        if mode == "concurrent-writer":
            assert not requests and len(outcome.failures) == 1
            assert outcome.failures[0].error_type == "SqliteTranscriptMutationConflictError"
            assert any(e.get("id") == "concurrent" for e in visible)
            assert not any(
                e.get("type") == "compaction" or e.get("id") == "new-foreground:user" for e in physical
            )
            return
        assert not outcome.failures and len(requests) == 1
        [current] = [e["message"] for e in visible if e.get("id") == "new-foreground:user"]
        assert (
            "Queued orchard note" in current["content"] and "Continue with the orchard." in current["content"]
        )
        assert sum(e.get("type") == "compaction" for e in physical) == 1
        assert sum(e.get("customType") == "test-queued-metadata" for e in visible) == 1
        assert any(e.get("id") == "external-user" for e in visible) == (mode == "internal-restart")

    asyncio.run(exercise())
