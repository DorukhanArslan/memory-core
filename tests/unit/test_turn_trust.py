"""Sticky current-turn trust, provenance stamping and exact-turn restoration."""
from copy import deepcopy
import json

import pytest

from memory_core.turn_trust import TurnTrust, is_active_turn_tainted, with_assistant_turn_taint


def test_only_actual_network_nonpresentation_outcomes_taint_and_taint_is_sticky():
    state = TurnTrust("one", sender_is_owner=True)
    state.observe({"toolName": "presentation", "resultContentSource": "network", "presentationOnly": True})
    assert not state.is_tainted()
    state.observe({"toolName": "local", "result": {"resultContentSource": "network", "turnTainted": True}})
    assert not state.is_tainted()
    state.observe({"toolName": "web", "resultContentSource": "network"})
    state.observe({"toolName": "local"})
    assert state.is_tainted() and state.resolve_origin_class() == "untrusted"


def test_writer_resolves_current_owner_each_time_without_changing_sticky_taint():
    state = TurnTrust("one", sender_is_owner=True)
    assert state.resolve_origin_class() == "agent"
    state.sender_is_owner = False
    assert state.resolve_origin_class() == "untrusted" and not state.is_tainted()
    state.sender_is_owner = None
    assert state.resolve_origin_class() == "agent"
    state.observe({"resultContentSource": "network"})
    state.sender_is_owner = True
    assert state.resolve_origin_class() == "untrusted"


def test_trusted_serialization_continues_exact_turn_while_new_turn_resets():
    state = TurnTrust("one", sender_is_owner=True)
    state.observe({"resultContentSource": "network"})
    restored = TurnTrust.from_json(json.loads(json.dumps(state.to_json())), expected_turn_id="one")
    assert restored.to_json() == state.to_json()
    with pytest.raises(ValueError, match="exact host turn"):
        TurnTrust.from_json(state.to_json(), expected_turn_id="two")
    assert TurnTrust("two", sender_is_owner=True).is_tainted() is False
    with pytest.raises(ValueError):
        TurnTrust.from_json({**state.to_json(), "tainted": "true"}, expected_turn_id="one")


def test_assistant_stamp_preserves_supported_metadata_and_does_not_change_source():
    message = {"role": "assistant", "content": [{"type": "text", "text": "Saved."}],
               "__openclaw": {"resultContentSource": "network", "senderIsOwner": True,
                                "arbitrary": {"kept": "outside supported stamp"}}}
    original = deepcopy(message)
    assert with_assistant_turn_taint(message, False) is message
    stamped = with_assistant_turn_taint(message, True)
    assert stamped == {**message, "__openclaw": {"resultContentSource": "network", "turnTainted": True}}
    assert message == original
    assert stamped["content"] is message["content"]


def test_transcript_active_turn_read_stops_at_new_user_and_keeps_network_result_taint():
    transcript = [{"role": "user", "content": "hello"},
                  {"role": "toolResult", "__openclaw": {"resultContentSource": "network"}},
                  {"role": "assistant", "content": "answer"}]
    assert is_active_turn_tainted(transcript)
    assert not is_active_turn_tainted([*transcript, {"role": "user", "content": "new turn"}])
    assert is_active_turn_tainted([{"role": "assistant", "__openclaw": {"turnTainted": True}}])
