from memory_core.history import get_history_limit_from_session_key, limit_history_turns


def _message(role: str, text: str) -> dict[str, object]:
    return {"role": role, "content": [{"type": "text", "text": text}]}


def test_limit_history_turns_keeps_last_n_user_turns_with_assistant_responses():
    messages = [
        _message("user", "u1"),
        _message("assistant", "a1"),
        _message("user", "u2"),
        _message("assistant", "a2"),
        _message("toolResult", "tool after a2"),
        _message("user", "u3"),
    ]

    assert limit_history_turns(messages, 2) == messages[2:]


def test_limit_history_turns_preserves_leading_compaction_summary():
    messages = [
        _message("compactionSummary", "summary of earlier turns"),
        _message("branchSummary", "side branch"),
        _message("user", "u1"),
        _message("assistant", "a1"),
        _message("user", "u2"),
        _message("assistant", "a2"),
    ]

    limited = limit_history_turns(messages, 1)

    assert limited == messages[:2] + messages[4:]


def test_limit_history_turns_returns_all_when_only_leading_summaries():
    messages = [_message("compactionSummary", "summary")]

    assert limit_history_turns(messages, 1) == messages


def test_limit_history_turns_disabled_for_missing_zero_or_negative_limits():
    messages = [_message("user", "u1"), _message("assistant", "a1")]

    assert limit_history_turns(messages, None) == messages
    assert limit_history_turns(messages, 0) == messages
    assert limit_history_turns(messages, -1) == messages


def test_get_history_limit_from_session_key_uses_dm_override_before_default():
    config = {
        "channels": {
            "telegram": {
                "dmHistoryLimit": 15,
                "dms": {
                    "123": {"historyLimit": 5},
                    "789": {"historyLimit": 0},
                },
            }
        }
    }

    assert get_history_limit_from_session_key("telegram:dm:123", config) == 5
    assert get_history_limit_from_session_key("telegram:dm:456", config) == 15
    assert get_history_limit_from_session_key("telegram:dm:789", config) == 0


def test_get_history_limit_from_session_key_supports_agent_prefix_and_channel_limit():
    config = {
        "channels": {
            "slack": {"historyLimit": 10, "dmHistoryLimit": 15},
            "telegram": {"dmHistoryLimit": 7, "dms": {"123": {"historyLimit": 3}}},
        }
    }

    assert get_history_limit_from_session_key("agent:beta:slack:channel:c1", config) == 10
    assert get_history_limit_from_session_key("agent:main:telegram:dm:123:thread:999", config) == 3


def test_get_history_limit_from_session_key_rejects_unknown_or_unsupported_keys():
    config = {
        "channels": {
            "telegram": {"historyLimit": 10},
            "discord": {"dmHistoryLimit": 10},
        }
    }

    assert get_history_limit_from_session_key(None, config) is None
    assert get_history_limit_from_session_key("telegram:slash:123", config) is None
    assert get_history_limit_from_session_key("unknown:dm:123", config) is None
    assert get_history_limit_from_session_key("discord:channel:123", config) is None
    assert get_history_limit_from_session_key("telegram:dm:123", config) is None
