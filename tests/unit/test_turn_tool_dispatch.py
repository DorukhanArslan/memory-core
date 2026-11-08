"""Actual tool outcomes feed trust before retry writes and persisted provenance."""
from dataclasses import asdict
import asyncio
import json
from pathlib import Path
import subprocess
import sys

import pytest

from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore, with_daily_file_quarantine
from memory_core.consolidation.promotion import PromotionCandidate
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.turn_tool_dispatch import TurnTool, TurnToolDispatcher
from memory_core.turn_trust import TurnTrust


def test_registered_sources_override_model_arguments_and_returned_trust_claims():
    state = TurnTrust("turn", sender_is_owner=True)
    calls, outcomes = [], []
    def local(call_id, arguments):
        calls.append((call_id, dict(arguments)))
        return {"content": [{"type": "text", "text": "local"}], "resultContentSource": "network"}
    def network(call_id, arguments):
        calls.append((call_id, dict(arguments)))
        return {"content": [{"type": "text", "text": "network"}], "turnTainted": False}
    dispatcher = TurnToolDispatcher(state, [TurnTool("local", local), TurnTool("web", network, "network")],
                                    on_outcome=outcomes.append)
    assert dispatcher.dispatch("local", {"resultContentSource": "network"}, tool_call_id="local-call")["resultContentSource"] == "network"
    assert not state.is_tainted()
    result = dispatcher.dispatch("web", {"resultContentSource": None, "turnTainted": False}, tool_call_id="web-call")
    assert state.is_tainted() and result["turnTainted"] is False
    assert [outcome["toolName"] for outcome in outcomes] == ["local", "web"]
    assert "resultContentSource" not in outcomes[0] and outcomes[1]["resultContentSource"] == "network"
    assert len(calls) == 2


def test_real_network_execution_error_taints_but_missing_registration_never_executes():
    state = TurnTrust("turn", sender_is_owner=True)
    outcomes = []
    def fail(_id, _arguments):
        raise RuntimeError("declared network execution failure")
    dispatcher = TurnToolDispatcher(state, [TurnTool("web", fail, "network")], on_outcome=outcomes.append)
    with pytest.raises(KeyError):
        dispatcher.dispatch("unknown", {}, tool_call_id="missing")
    assert not state.is_tainted() and not outcomes
    with pytest.raises(RuntimeError, match="declared network"):
        dispatcher.dispatch("web", {}, tool_call_id="failed")
    assert state.is_tainted()
    assert outcomes[0]["error"] == {"name": "RuntimeError", "message": "declared network execution failure"}


def test_preparation_happens_after_real_observation_and_cannot_hide_network_taint():
    state = TurnTrust("turn", sender_is_owner=True)
    phases = []
    def prepare(result):
        phases.append(("prepare", state.is_tainted(), result["details"]["raw"]))
        return {"content": [{"type": "text", "text": "bounded"}]}
    dispatcher = TurnToolDispatcher(state, [TurnTool("web", lambda _id, _args: {
        "content": [{"type": "text", "text": "raw"}], "details": {"raw": True}}, "network")],
        on_outcome=lambda outcome: phases.append(("observe", state.is_tainted(), outcome["result"]["details"]["raw"])),
        model_result_preparer=prepare)
    assert dispatcher.dispatch("web", {}, tool_call_id="web") == {"content": [{"type": "text", "text": "bounded"}]}
    assert phases == [("observe", True, True), ("prepare", True, True)]


def test_async_dispatch_waits_for_source_outcome_before_tainting():
    async def run():
        state = TurnTrust("turn", sender_is_owner=True)
        entered, settle = asyncio.Event(), asyncio.Event()
        async def web(_id, _args):
            entered.set()
            await settle.wait()
            return {"content": [{"type": "text", "text": "settled network result"}]}
        dispatcher = TurnToolDispatcher(state, [TurnTool("web", web, "network")])
        with pytest.raises(TypeError, match="dispatch_async"):
            dispatcher.dispatch("web", {}, tool_call_id="sync-refused")
        task = asyncio.create_task(dispatcher.dispatch_async("web", {}, tool_call_id="async"))
        await entered.wait()
        assert not state.is_tainted()
        settle.set()
        result = await task
        assert result["content"][0]["text"] == "settled network result"
        assert state.is_tainted()
    asyncio.run(run())


def test_dispatched_network_retry_quarantine_and_assistant_source_survive_real_process_reopen(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ledger = MemoryArtifactProvenanceStore(tmp_path / "provenance.sqlite")
    state = TurnTrust("first", sender_is_owner=True)
    outcomes = []
    observer = state.write_observer(store=ledger, mutation_root=workspace, workspace_dir=workspace,
                                    session_id="session", session_key="agent:main:dm:turn", now=lambda: 1000)
    def write(_id, arguments):
        target = workspace / arguments["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        before = target.read_text() if target.exists() else ""
        observer.write(absolute_path=target, content_before=before, content_after=arguments["text"],
                       commit=lambda: target.write_text(arguments["text"]))
        return {"content": [{"type": "text", "text": "written"}], "details": {"path": arguments["path"]}}
    tools = [TurnTool("write", write), TurnTool("web", lambda _id, _args: {
        "content": [{"type": "text", "text": "External cedar preference."}], "details": {"host": "fixture"}}, "network")]
    first_attempt = TurnToolDispatcher(state, tools, on_outcome=outcomes.append)
    first_attempt.dispatch("write", {"path": "memory/2026-11-10.md", "text": "Owner note."}, tool_call_id="before")
    assert ledger.read(workspace_dir=workspace, relative_path="memory/2026-11-10.md").origin_class == "agent"
    first_attempt.dispatch("web", {}, tool_call_id="network")
    # A real host retry constructs another dispatcher with the SAME state; the
    # already-created observer also reads that live state at this later write.
    retry = TurnToolDispatcher(state, tools, on_outcome=outcomes.append)
    retry.dispatch("write", {"path": "memory/2026-11-10.md", "text": "External cedar note."}, tool_call_id="after")
    artifact = ledger.read(workspace_dir=workspace, relative_path="memory/2026-11-10.md")
    assert artifact.origin_class == "untrusted"
    assert artifact.session_id == "session" and artifact.session_key == "agent:main:dm:turn"
    candidate = PromotionCandidate(
        key="cedar", path="memory/2026-11-10.md", start_line=1, end_line=1,
        snippet="External cedar note.", recall_count=1, daily_count=1, grounded_count=1,
        signal_count=1, avg_score=1, max_score=1, unique_queries=1, score=1,
        first_recalled_at="2026-11-10T00:00:00Z", last_recalled_at="2026-11-10T00:00:00Z",
        provenance={"originClass": "agent"},
    )
    quarantined = with_daily_file_quarantine(candidate, dict(ledger.list(workspace)))
    assert quarantined.provenance["originClass"] == "untrusted"
    state_path = tmp_path / "trusted-turn.json"
    state_path.write_text(json.dumps(state.to_json()))
    state_dir = tmp_path / "state"
    catalog = MemorySessionCatalog(state_dir / "agents/main/sessions/authority.sqlite", clock_ms=lambda: 1000)
    key = "agent:main:dm:turn"
    catalog.upsert_session(key, {"sessionId": "session", "updatedAt": 1000})
    assistant = state.stamp_assistant({"role": "assistant", "content": "External cedar saved.", "timestamp": 1000})
    catalog.replace_events("session", [{"type": "message", "id": "user", "message": {
        "role": "user", "content": "Remember cedar.", "timestamp": 1000, "__openclaw": {"senderIsOwner": True}}},
        {"type": "message", "id": "assistant", "message": assistant}], session_key=key)
    child_code = """
import json,sys
from pathlib import Path
from dataclasses import asdict
from memory_core.turn_trust import TurnTrust
from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.session_corpus import MemoryCoreSessionCorpus
p=Path(sys.argv[1]);w=p/'workspace'; state=TurnTrust.from_json(json.loads((p/'trusted-turn.json').read_text()),expected_turn_id='first')
ledger=MemoryArtifactProvenanceStore(p/'provenance.sqlite'); catalog=MemorySessionCatalog(p/'state/agents/main/sessions/authority.sqlite',clock_ms=lambda:1000)
corpus=MemoryCoreSessionCorpus(p/'state',catalog=catalog); file,=corpus.discover_files(); entry=corpus.read_source_entry(file)
print(json.dumps({'trust':state.to_json(),'artifact':asdict(ledger.read(workspace_dir=w,relative_path='memory/2026-11-10.md')),'entry':entry,'events':list(catalog.read_transcript('session',session_key='agent:main:dm:turn').events)}))
"""
    process = subprocess.run([sys.executable, "-c", child_code, str(tmp_path)],
                             cwd=Path(__file__).resolve().parents[2], text=True, capture_output=True, check=True)
    reopened = json.loads(process.stdout)
    assert reopened["trust"] == state.to_json()
    assert reopened["artifact"] == asdict(artifact)
    assert reopened["events"][1]["message"] == assistant
    assert [line["originClass"] for line in reopened["entry"]["lineProvenance"]] == ["owner", "untrusted"]
    # New-turn authority is clean; the existing file's quarantine remains sticky.
    fresh = TurnTrust("second", sender_is_owner=True)
    assert fresh.is_tainted() is False
    later = fresh.write_observer(store=ledger, mutation_root=workspace, workspace_dir=workspace, now=lambda: 2000)
    target = workspace / "memory/2026-11-10.md"
    later.write(absolute_path=target, content_before=target.read_text(), content_after="Later owner note.",
                commit=lambda: target.write_text("Later owner note."))
    assert ledger.read(workspace_dir=workspace, relative_path="memory/2026-11-10.md").origin_class == "untrusted"
    assert len(outcomes) == 3
