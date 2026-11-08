"""Durable message admission and fresh-process continuation regressions.

The append assertions follow the real SQLite append owner, not raw import rows.
No transcript, context list or session state crosses the subprocess boundary.
"""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from memory_core.redact import LoggingConfig
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.session_transcript_append import (
    SqliteTranscriptMutationConflictError,
    TranscriptTurnAdmissionConflictError,
)


KEY = "agent:main:dm:durable"


def _catalog(tmp_path, *, key=KEY):
    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite", clock_ms=lambda: 1000)
    catalog.upsert_session(key, {"sessionId": "first", "updatedAt": 1000})
    return catalog


def test_append_creates_real_header_and_parent_linked_full_messages(tmp_path):
    catalog = _catalog(tmp_path)
    user = {"role": "user", "content": [{"type": "text", "text": "Remember kumquat."}],
            "timestamp": 999, "__openclaw": {"senderIsOwner": True}}
    assistant = {"role": "assistant", "content": [{"type": "text", "text": "Saved."}],
                 "api": "openai-completions", "provider": "example", "model": "example-model",
                 "usage": {"input": 23, "output": 7, "cost": {"total": 0.001}},
                 "stopReason": "stop", "timestamp": 1001}
    first = catalog.append_message("first", user, session_key=KEY, event_id="u1", now_ms=999, cwd="/host/work")
    second = catalog.append_message("first", assistant, session_key=KEY, event_id="a1", now_ms=1001)
    transcript = catalog.read_transcript("first")
    assert transcript.events[0] == {"type": "session", "version": 4, "id": "first",
                                    "timestamp": "1970-01-01T00:00:01.000Z", "cwd": "/host/work"}
    assert [event.get("parentId") for event in transcript.events[1:]] == [None, "u1"]
    assert [event["message"] for event in transcript.events[1:]] == [user, assistant]
    assert first["anchor"]["rawSeq"] == 1
    assert second["anchor"]["activeMessagePosition"] == 1
    assert first["anchor"]["generation"] == second["anchor"]["generation"]
    assert first["anchor"]["storePath"] == str(catalog.path)
    user["content"].clear()
    second["message"]["usage"].clear()
    assert catalog.read_transcript("first").events[2]["message"] == assistant


def test_replay_after_reopen_is_unchanged_and_conflicts_roll_back_everything(tmp_path):
    catalog = _catalog(tmp_path)
    original = {"role": "user", "content": "Saved", "idempotencyKey": "  admitted-1  ", "timestamp": 10}
    first = catalog.append_message("first", original, session_key=KEY, event_id="owner")
    before = catalog.read_transcript("first")
    reopened = MemorySessionCatalog(catalog.path, clock_ms=lambda: 2000)
    replay = reopened.append_message("first", {**original, "timestamp": 999},
                                     session_key=KEY, event_id="different-retry-id")
    assert replay == {**first, "appended": False}
    assert reopened.read_transcript("first") == before
    with pytest.raises(TranscriptTurnAdmissionConflictError, match="admitted-1"):
        reopened.append_message("first", {**original, "content": "Changed"}, session_key=KEY)
    with pytest.raises(TranscriptTurnAdmissionConflictError, match="event:owner"):
        reopened.append_message("first", {"role": "user", "content": "Other"},
                                session_key=KEY, event_id="owner")
    assert reopened.read_transcript("first") == before
    assert reopened.snapshot().revision == catalog.snapshot().revision


def test_replay_does_not_equate_boolean_and_numeric_metadata(tmp_path):
    catalog = _catalog(tmp_path)
    catalog.append_message("first", {"role": "user", "content": "Saved", "flag": True},
                           session_key=KEY, event_id="owned")
    with pytest.raises(TranscriptTurnAdmissionConflictError):
        catalog.append_message("first", {"role": "user", "content": "Saved", "flag": 1},
                               session_key=KEY, event_id="owned")


def test_storage_redaction_preserves_real_tool_and_admission_identity(tmp_path):
    catalog = _catalog(tmp_path)
    config = LoggingConfig(redact_patterns=("SECRET[0-9]+",))
    assistant = {"role": "assistant", "idempotencyKey": "SECRET111",
                 "content": [{"type": "toolCall", "id": "SECRET222", "name": "lookup",
                              "arguments": {"query": "SECRET333", "count": 3}}],
                 "usage": {"input": 4, "output": 5}, "timestamp": 1000}
    result = catalog.append_message("first", assistant, session_key=KEY, event_id="call",
                                    logging_config=config)
    stored = result["message"]
    assert stored["idempotencyKey"] == "SECRET111"
    assert stored["content"][0]["id"] == "SECRET222"
    assert stored["content"][0]["arguments"] == {"query": "***", "count": 3}
    assert stored["usage"] == assistant["usage"]
    tool = catalog.append_message("first", {
        "role": "toolResult", "toolCallId": "SECRET222", "toolName": "lookup",
        "content": [{"type": "text", "text": "SECRET444"}],
        "details": {"next_page_token": "safe-cursor", "token": "SECRET555"},
        "isError": False, "timestamp": 1000,
    }, session_key=KEY, event_id="result", logging_config=config)
    assert tool["message"]["toolCallId"] == "SECRET222"
    assert tool["message"]["content"][0]["text"] == "***"
    assert tool["message"]["details"] == {"next_page_token": "safe-cursor", "token": "***"}
    assert tool["effectiveParentId"] == "call"
    assert b"SECRET333" not in catalog.path.read_bytes()
    assert b"SECRET444" not in catalog.path.read_bytes()


def test_active_branch_rebase_and_deliberate_branch_have_durable_parents(tmp_path):
    catalog = _catalog(tmp_path)
    for identifier in ("u1", "a1"):
        catalog.append_message("first", {"role": "user", "content": identifier},
                               session_key=KEY, event_id=identifier)
    active = catalog.append_message("first", {"role": "user", "content": "next"},
                                    session_key=KEY, event_id="u2", parent_id="u1", append_intent="active-branch")
    assert active["effectiveParentId"] == "a1"
    assert "anchor" in active
    branch = catalog.append_message("first", {"role": "user", "content": "branch"},
                                    session_key=KEY, event_id="branch", parent_id="u1")
    assert branch["effectiveParentId"] == "u1"
    # The native owner cannot certify dirty active projection rows before reconcile.
    assert "anchor" not in branch
    reopened = MemorySessionCatalog(catalog.path, clock_ms=lambda: 1000)
    after = reopened.append_message("first", {"role": "assistant", "content": "branch continuation"},
                                    session_key=KEY, event_id="branch-answer")
    assert after["effectiveParentId"] == "branch"


def test_stale_mutation_rejects_without_header_or_partial_message(tmp_path):
    catalog = _catalog(tmp_path)
    with pytest.raises(SqliteTranscriptMutationConflictError):
        catalog.append_message("first", {"role": "user", "content": "stale"},
                               session_key=KEY, expected_mutation_at=0)
    assert catalog.read_transcript("first").events == ()
    catalog.append_message("first", {"role": "user", "content": "accepted"},
                           session_key=KEY, expected_mutation_at=None)
    before = catalog.read_transcript("first")
    with pytest.raises(SqliteTranscriptMutationConflictError):
        catalog.append_message("first", {"role": "user", "content": "stale again"},
                               session_key=KEY, expected_mutation_at=None)
    assert catalog.read_transcript("first") == before


def test_persisted_anchor_survives_restart_and_replacement_revokes_its_generation(tmp_path):
    catalog = _catalog(tmp_path)
    first = catalog.append_message("first", {"role": "user", "content": "Saved", "idempotencyKey": "input-1"},
                                    session_key=KEY, event_id="u1")
    reopened = MemorySessionCatalog(catalog.path, clock_ms=lambda: 1000)
    assert reopened.read_anchor("first", "u1", session_key=KEY) == first["anchor"]
    events = list(reopened.read_transcript("first").events)
    reopened.replace_events("first", events)
    replaced = reopened.read_anchor("first", "u1", session_key=KEY)
    assert replaced["generation"] != first["anchor"]["generation"]
    assert {k: v for k, v in replaced.items() if k != "generation"} == {
        k: v for k, v in first["anchor"].items() if k != "generation"
    }
    reopened.replace_events("first", [])
    assert reopened.read_anchor("first", "u1", session_key=KEY) is None


def test_history_instance_projection_keeps_current_full_entry_and_retained_window_facts(tmp_path):
    catalog = _catalog(tmp_path)
    catalog.upsert_session(KEY, {"sessionId": "first", "updatedAt": 1000, "chatType": "direct",
                                "label": "current label", "compactionCount": 3,
                                "memoryFlush": {"kind": "succeeded", "compactionCount": 3}})
    catalog.append_message("first", {"role": "user", "content": "Old"}, session_key=KEY, event_id="old")
    current = catalog.list_transcript_instances()[0]
    assert current["entry"]["label"] == "current label"
    assert current["entry"]["updatedAt"] == 1002
    assert current["sourceMetadata"] == {"createdAt": 1000, "channel": None, "accountId": None,
                                         "chatType": "direct", "hookExternalContentSource": None}
    catalog.upsert_session(KEY, {"sessionId": "second", "previousSessionId": "first", "updatedAt": 2000})
    retained = catalog.list_transcript_instances()[0]
    assert retained["entry"] == {"sessionId": "first", "updatedAt": 1002, "chatType": "direct"}
    assert len(catalog.list_transcript_instances(include_all_windows=True)) == 2
    assert catalog.list_transcript_instances(session_id="second") == []


def test_raw_navigation_revokes_anchor_until_a_bounded_import_rebuilds_projection(tmp_path):
    catalog = _catalog(tmp_path)
    catalog.append_message("first", {"role": "user", "content": "Saved"}, session_key=KEY, event_id="u1")
    catalog.append_events("first", [{"type": "leaf", "id": "select-u1", "parentId": "u1", "targetId": "u1"}])
    assert catalog.read_anchor("first", "u1", session_key=KEY) is None
    catalog.replace_events("first", list(catalog.read_transcript("first").events))
    assert catalog.read_anchor("first", "u1", session_key=KEY)["activeMessagePosition"] == 0


_PHASE_SCRIPT = r'''
import json, os, sys
from pathlib import Path
import memory_core
from memory_core.session_catalog import MemorySessionCatalog
assert Path(memory_core.__file__).resolve().is_relative_to(Path(os.environ['PYTHONPATH']))
path, phase = sys.argv[1:]
c = MemorySessionCatalog(path, clock_ms=lambda: 1000)
k = 'agent:main:dm:durable'
if phase == 'write':
    c.upsert_session(k, {'sessionId':'old','updatedAt':1000,'compactionCount':2,
        'totalTokens':123,'totalTokensFresh':True,'totalTokensVersion':1,
        'memoryFlush':{'kind':'failed','compactionCount':2,'failureCount':1}})
    c.append_message('old', {'role':'user','content':'Remember kumquat.', 'timestamp':1000},
        session_key=k,event_id='u1',cwd='/host/work')
    c.append_message('old', {'role':'assistant','content':[{'type':'toolCall','id':'call1','name':'lookup',
        'arguments':{'query':'kumquat'}}], 'api':'openai-completions','provider':'example',
        'model':'example-model','usage':{'input':11,'output':4},'stopReason':'toolUse','timestamp':1000},
        session_key=k,event_id='a1')
    c.append_message('old', {'role':'toolResult','toolCallId':'call1','toolName':'lookup',
        'content':[{'type':'text','text':'A citrus fruit.'}], 'details':{'source':'saved'},
        'isError':False,'timestamp':1000},session_key=k,event_id='t1')
elif phase == 'continue':
    before = c.read_continuation('old',session_key=k)
    assert [m['role'] for m in before['llmMessages']] == ['user','assistant','toolResult']
    assert before['entry']['memoryFlush']['kind'] == 'failed'
    c.append_message('old', {'role':'assistant','content':[{'type':'text','text':'Your preference is saved.'}],
        'api':'openai-completions','provider':'example','model':'example-model',
        'usage':{'input':19,'output':6},'stopReason':'stop','timestamp':1000},
        session_key=k,event_id='a2')
    entry = c.get_session_entry(k)
    c.upsert_session(k,{**entry,'memoryFlush':{'kind':'succeeded','compactionCount':2}})
    c.upsert_session(k,{'sessionId':'new','previousSessionId':'old','updatedAt':2000,
        'compactionCount':0,'memoryFlush':{'kind':'failed','failureCount':1}})
    c.append_message('new', {'role':'user','content':'A new conversation.', 'timestamp':2000},
        session_key=k,event_id='new-u',cwd='/host/new')
result = {sid:c.read_continuation(sid,session_key=k) for sid in ('old','new')}
print(json.dumps({'pid':os.getpid(),'result':result}))
'''


def _phase(path: Path, phase: str) -> dict:
    root = Path(__file__).resolve().parents[2]
    environment = {**os.environ, "PYTHONPATH": str(root)}
    run = subprocess.run([sys.executable, "-c", _PHASE_SCRIPT, str(path), phase],
                         cwd=root, env=environment, text=True, capture_output=True, check=True)
    return json.loads(run.stdout)


def test_three_fresh_processes_reconstruct_and_continue_retained_full_context(tmp_path):
    path = tmp_path / "catalog.sqlite"
    first = _phase(path, "write")
    second = _phase(path, "continue")
    third = _phase(path, "verify")
    assert len({first["pid"], second["pid"], third["pid"]}) == 3
    old, new = third["result"]["old"], third["result"]["new"]
    assert [event.get("id") for event in old["events"]] == ["old", "u1", "a1", "t1", "a2"]
    assert [event.get("parentId") for event in old["events"][1:]] == [None, "u1", "a1", "t1"]
    assert [message["role"] for message in old["llmMessages"]] == ["user", "assistant", "toolResult", "assistant"]
    assert old["llmMessages"][2]["details"] == {"source": "saved"}
    assert old["llmMessages"][1]["usage"] == {"input": 11, "output": 4}
    assert old["instanceEntry"]["memoryFlush"] == {"kind": "succeeded", "compactionCount": 2}
    assert old["entry"]["sessionId"] == new["entry"]["sessionId"] == "new"
    assert new["context"]["messages"][0]["content"] == "A new conversation."
    assert first["result"]["old"]["version"]["generation"] == old["version"]["generation"]
    assert old["version"]["generation"] != new["version"]["generation"]
    assert second["result"] == third["result"]


def test_incognito_message_append_is_real_process_state_and_leaves_no_disk_payload(tmp_path):
    key = "agent:main:dashboard:incognito-private"
    catalog = _catalog(tmp_path, key=key)
    result = catalog.append_message("first", {"role": "user", "content": "private kumquat"},
                                    session_key=key, event_id="private")
    assert result["appended"] is True
    assert catalog.read_transcript("first", session_key=key).events[1]["message"]["content"] == "private kumquat"
    assert catalog.snapshot().instances == ()
    assert b"private kumquat" not in catalog.path.read_bytes()
    assert b"private kumquat" not in b"".join(p.read_bytes() for p in tmp_path.iterdir() if p.is_file())
    run = subprocess.run([
        sys.executable, "-c",
        "from memory_core.session_catalog import MemorySessionCatalog; import sys; "
        "c=MemorySessionCatalog(sys.argv[1]); assert c.read_transcript('first', "
        f"session_key={key!r}) is None",
        str(catalog.path),
    ], check=True, capture_output=True)
    assert run.returncode == 0
