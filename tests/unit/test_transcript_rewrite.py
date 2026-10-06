"""Edges of memory_core/transcript_rewrite.py that the oracle fixtures cannot reach.

The rewrite and the in-memory manager are compared with the real TypeScript in
``tests/integration/test_openclaw_transcript_rewrite_oracle.py``; this file covers the host hook
for assistant delivery directives (a Python-side extension point) and the guard that upstream
raises only under concurrent mutation.
"""

from __future__ import annotations

from typing import Any

import pytest

from memory_core.transcript_rewrite import (
    TranscriptSessionManager,
    rewrite_transcript_entries_in_session_manager,
)


def _manager(prepare: Any = None) -> tuple[TranscriptSessionManager, list[str]]:
    manager = TranscriptSessionManager("/work", prepare_message=prepare)
    ids = [
        manager.append_message({"role": "user", "content": "one"}),
        manager.append_message({"role": "assistant", "content": [{"type": "text", "text": "[[tag]] two"}]}),
        manager.append_message({"role": "user", "content": "three"}),
    ]
    return manager, ids


def test_prepare_message_hook_runs_on_every_assistant_append():
    seen: list[str] = []

    def prepare(message: dict[str, Any]) -> None:
        seen.append(message["content"][0]["text"])
        message["content"][0]["text"] = message["content"][0]["text"].replace("[[tag]] ", "")

    manager, ids = _manager(prepare)
    assert seen == ["[[tag]] two"]
    result = rewrite_transcript_entries_in_session_manager(
        session_manager=manager,
        replacements=[{"entryId": ids[0], "message": {"role": "user", "content": "1"}}],
    )
    assert result.changed and result.rewritten_entries == 1
    assert len(seen) == 2, "the re-appended assistant copy is prepared again, as upstream's append would"
    assert [e["message"]["role"] for e in manager.get_branch()] == ["user", "assistant", "user"]


def test_commit_rejects_a_source_outside_the_loaded_view():
    manager, ids = _manager()
    rewrite = manager.prepare_transcript_rewrite()
    rewrite.session_manager.branch(ids[0])
    rewrite.session_manager.append_message({"role": "user", "content": "x"})
    with pytest.raises(ValueError, match="not in the loaded view"):
        rewrite.commit({"ghost": rewrite.session_manager.get_leaf_id() or ""})


def test_non_string_entry_id_is_a_type_error_like_upstream_trim():
    manager, ids = _manager()
    with pytest.raises(TypeError):
        rewrite_transcript_entries_in_session_manager(
            session_manager=manager,
            replacements=[{"entryId": None, "message": {"role": "user", "content": "x"}}],
        )


def test_abandoned_suffix_stays_stored_but_off_the_branch():
    manager, ids = _manager()
    rewrite_transcript_entries_in_session_manager(
        session_manager=manager,
        replacements=[{"entryId": ids[1], "message": {"role": "assistant", "content": [{"type": "text", "text": "2"}]}}],
    )
    active = {entry["id"] for entry in manager.get_branch()}
    stored = {entry["id"] for entry in manager.get_entries()}
    assert ids[1] not in active and ids[2] not in active and {ids[1], ids[2]} <= stored
    assert ids[0] in active
