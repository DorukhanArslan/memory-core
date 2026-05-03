from demo.chat_session import ChatSessionState


def test_chat_session_records_turns_and_selects_latest():
    state = ChatSessionState()

    turn = state.add_turn(
        user_message="hello",
        recall_query="hello",
        recall_results=[],
        assistant_response="hi",
        memory_context=[],
    )

    assert turn.id == 1
    assert state.selected_turn_id == 1
    assert state.as_dict()["turns"][0]["assistantResponse"] == "hi"


def test_chat_session_reset_clears_turns():
    state = ChatSessionState()
    state.add_turn(
        user_message="hello",
        recall_query="hello",
        recall_results=[],
        assistant_response="hi",
        memory_context=[],
    )

    state.reset()

    assert state.as_dict()["turns"] == []
    assert state.selected_turn_id is None
