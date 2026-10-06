from memory_core.history import get_history_limit_from_session_key, limit_history_turns


def _message(role: str, text: str) -> dict[str, object]:
    return {"role": role, "content": [{"type": "text", "text": text}]}


def test_limit_history_turns_keeps_everything_within_the_fifty_percent_cushion():
    messages = [
        _message("user", "u1"),
        _message("assistant", "a1"),
        _message("user", "u2"),
        _message("assistant", "a2"),
        _message("toolResult", "tool after a2"),
        _message("user", "u3"),
    ]

    assert limit_history_turns(messages, 2) == messages


def test_limit_history_turns_evicts_a_batch_once_over_the_cushion():
    # limit 2 -> cut at more than 3 user turns, keep 2 + (n - 2) % 2
    messages = []
    for n in range(1, 5):
        messages += [_message("user", f"u{n}"), _message("assistant", f"a{n}")]
    # 4 users: keep 2 + (4-2) % 2 = 2 turns
    assert limit_history_turns(messages, 2) == messages[4:]
    # 5 users: keep 2 + (5-2) % 2 = 3 turns, the cache prefix moves in steps
    messages += [_message("user", "u5"), _message("assistant", "a5")]
    assert limit_history_turns(messages, 2) == messages[4:]


def test_limit_history_turns_preserves_leading_compaction_summary():
    messages = [
        _message("compactionSummary", "summary of earlier turns"),
        _message("branchSummary", "side branch"),
        _message("user", "u1"),
        _message("assistant", "a1"),
        _message("user", "u2"),
        _message("assistant", "a2"),
        _message("user", "u3"),
        _message("assistant", "a3"),
    ]

    limited = limit_history_turns(messages, 1)

    assert limited == messages[:2] + messages[6:]


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


def test_get_history_limit_account_scopes_and_route_facts():
    config = {
        "session": {"identityLinks": {"alice": ["telegram:123"]}},
        "channels": {
            "telegram": {
                "dmHistoryLimit": 20,
                "historyLimit": 10,
                "dms": {"alice": {"historyLimit": 7}},
                "accounts": {
                    "Work Team": {"dmHistoryLimit": 40},
                    "direct": {"dmHistoryLimit": 50},
                },
            }
        },
    }

    assert (
        get_history_limit_from_session_key("telegram:dm:1", config, {"accountId": "work-team"}) == 40
    )
    # Ambiguous without route facts (an account named "direct", or the peer "dm:1").
    assert get_history_limit_from_session_key("telegram:direct:dm:1", config) == 20
    assert (
        get_history_limit_from_session_key("telegram:direct:dm:1", config, {"peerId": "1"}) == 50
    )
    assert (
        get_history_limit_from_session_key(
            "telegram:direct:dm:1", config, {"chatType": "direct", "accountId": "default"}
        )
        == 20
    )
    assert get_history_limit_from_session_key("telegram:dm:alice", config, {"peerId": "123"}) == 7
    assert get_history_limit_from_session_key("Telegram:group:g", config) == 10
