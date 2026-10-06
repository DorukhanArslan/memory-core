from memory_core.compaction_replay import (
    is_compaction_replay_checkpoint,
    replace_compaction_replay_owner_content,
    strip_compaction_replay_checkpoint,
)
from memory_core.replay_history import normalize_assistant_replay_content


def _owner(replay):
    blocks = [
        {"type": "text", "text": "a"},
        {"type": "thinking", "thinking": "b", "signature": "s"},
        {"type": "text", "text": "c"},
    ]
    return {"role": "assistant", "content": blocks, "providerReplay": replay}, blocks


def test_checkpoint_types():
    assert is_compaction_replay_checkpoint({"type": "anthropic-compaction"})
    assert is_compaction_replay_checkpoint({"type": "openai-responses-retained-compaction"})
    assert not is_compaction_replay_checkpoint({"type": "other"})
    assert not is_compaction_replay_checkpoint(None)
    assert "providerReplay" not in strip_compaction_replay_checkpoint(
        _owner({"type": "anthropic-compaction"})[0]
    )


def test_replace_reindexes_when_a_block_before_the_index_goes():
    message, blocks = _owner({"type": "anthropic-compaction", "replayIndex": 2})
    result = replace_compaction_replay_owner_content(message, [blocks[1], blocks[2]])
    assert result["providerReplay"]["replayIndex"] == 1


def test_replace_strips_for_new_blocks_and_empty_content():
    message, _ = _owner({"type": "openai-responses-compaction", "replayIndex": 1})
    assert "providerReplay" not in replace_compaction_replay_owner_content(
        message, [{"type": "text", "text": "a"}]
    )
    assert "providerReplay" not in replace_compaction_replay_owner_content(message, [])
    retained, _ = _owner({"type": "openai-responses-retained-compaction"})
    assert "providerReplay" in replace_compaction_replay_owner_content(retained, [])


def test_replay_normalization_reindexes_the_owner_checkpoint():
    message, _ = _owner({"type": "anthropic-compaction", "replayIndex": 3})
    message["content"].insert(0, {"type": "image", "data": "AA==", "mimeType": "image/png"})
    (out,) = normalize_assistant_replay_content([message])
    assert out["providerReplay"]["replayIndex"] == 2
