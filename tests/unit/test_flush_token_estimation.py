from __future__ import annotations

from copy import deepcopy

import pytest

from memory_core.flush_token_estimation import estimate_flush_messages_tokens
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ({"role": "user", "content": "12345"}, 2),
        ({"role": "user", "content": "中文"}, 2),
        ({"role": "user", "content": "😀😀😀"}, 2),
        ({"role": "assistant", "content": [{"type": "text", "text": "12345"}]}, 2),
        ({"role": "assistant", "content": [{"type": "thinking", "thinking": "12345"}]}, 2),
        ({"role": "assistant", "content": [{"type": "toolCall", "name": "x", "arguments": {"n": 1.0}}]}, 2),
        ({"role": "assistant", "content": [{"type": "toolCall", "name": "x"}]}, 3),
        ({"role": "toolResult", "content": "12345", "details": {"secret": "x" * 1000}}, 2),
        ({"role": "toolResult", "content": [{"type": "tool_result", "content": "12345"}]}, 2),
        ({"role": "custom", "content": "12345"}, 2),
        ({"role": "bashExecution", "command": "x", "output": "12345"}, 2),
        ({"role": "branchSummary", "summary": "12345"}, 2),
        ({"role": "compactionSummary", "summary": "12345"}, 2),
        ({"role": "user", "content": "12345", "excludeFromContext": True}, 0),
        ({"role": "user", "content": "", "__openclawCompactionPlanningOmittedChars": 5}, 2),
        ({"role": "user", "content": "", "__openclawCompactionPlanningOmittedChars": True}, 0),
    ],
)
def test_compaction_token_estimate_has_no_message_overhead(message, expected):
    before = deepcopy(message)
    assert estimate_flush_messages_tokens([message]) == expected
    assert message == before


def test_runtime_context_is_removed_without_removing_other_custom_messages():
    messages = [
        {"role": "custom", "customType": MEMORY_CORE_RUNTIME_IDENTITY.runtime_context_custom_type, "content": "secret" * 1000},
        {"role": "custom", "customType": "ordinary", "content": "1234"},
    ]
    assert estimate_flush_messages_tokens(messages) == 1


def test_image_and_nontext_omissions_are_charged_once_each_per_message():
    images = [{"type": "image"}, {"type": "image"}]
    # Two image budgets plus one image notice and the serializer's role/separator charge.
    assert estimate_flush_messages_tokens([{"role": "user", "content": images}]) == 4014
    content = images + [{"type": "audio"}, {"type": "audio"}]
    assert estimate_flush_messages_tokens([{"role": "user", "content": content}]) == 4025


def test_sender_labels_require_a_stable_id_and_strip_nulls_and_outer_whitespace():
    bare = {"role": "user", "content": ""}
    assert estimate_flush_messages_tokens([{**bare, "__openclaw": {"senderName": "long name"}}]) == 0
    labelled = {**bare, "__openclaw": {"senderId": "  id\x00 ", "senderName": " User "}}
    # Exact suffix: ' sender={"id":"id","name":"User"}' (33 chars).
    assert estimate_flush_messages_tokens([labelled]) == 9
