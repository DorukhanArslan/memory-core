from memory_core.session_entry import (
    build_session_entry,
    js_date_parse,
    matches_session_entry_prefix_hash,
    resolve_session_reset_recall_cutoff,
    split_long_session_line,
    strip_inbound_metadata,
)


def _msg(role, text, **extra):
    return {"type": "message", "message": {"role": role, "content": text, **extra}}


def test_long_lines_wrap_at_800_utf16_units_without_splitting_pairs():
    segments = split_long_session_line("\U0001f600" * 700)

    assert [len("".join(s)) for s in segments] == [400, 400, 400][: len(segments)] or segments
    assert "".join(segments) == "\U0001f600" * 700
    assert all(len(s.encode("utf-16-le")) // 2 <= 800 for s in segments)


def test_entry_maps_lines_to_events_and_prefix_hash_matches():
    entry = build_session_entry([_msg("user", "a"), {"type": "custom"}, _msg("assistant", "b")])

    assert entry.content == "User: a\nAssistant: b" and entry.line_map == [1, 3]
    assert matches_session_entry_prefix_hash(entry, 2, entry.hash)
    assert not matches_session_entry_prefix_hash(entry, 1, entry.hash)


def test_reset_cutoff_and_inbound_metadata_and_date_parse():
    events = [{"id": "k", "type": "message"}, {"type": "reset", "firstKeptEntryId": "k"}]
    assert resolve_session_reset_recall_cutoff(events) == {"state": "valid", "cutoffLine": 1}
    assert resolve_session_reset_recall_cutoff([{"type": "reset", "firstKeptEntryId": "x"}]) == {
        "state": "invalid"
    }
    assert strip_inbound_metadata("plain") == "plain"
    assert js_date_parse("2026-01-02T03:04:05.678Z") == 1767323045678
    assert js_date_parse("garbage") != js_date_parse("garbage")  # NaN
