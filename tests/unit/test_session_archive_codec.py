"""Real compressed frames preserve transcript bytes and expose decoder failures."""
import sys

import pytest

from memory_core.session_archive_codec import read_session_transcript_bytes


def _compress(data):
    if sys.version_info >= (3, 14):
        from compression import zstd
        return zstd.compress(data)
    import zstandard
    return zstandard.ZstdCompressor().compress(data)


def test_archive_decoding_preserves_raw_jsonl_and_the_native_first_frame_boundary(tmp_path):
    first = b'{"type":"message","message":{"role":"user","content":"Cedar \\ud83d\\ude00"}}\r\n'
    second = b'{"type":"message","message":{"role":"assistant","content":"invalid \xff"}}\n'
    path = tmp_path / 'session.jsonl.reset.2026-11-09T00-00-00Z.zst'
    encoded = _compress(first) + _compress(second)
    path.write_bytes(encoded)
    assert read_session_transcript_bytes(path) == first
    assert path.read_bytes() == encoded
    assert list(tmp_path.iterdir()) == [path]


def test_plain_transcripts_are_read_without_encoding_or_newline_changes(tmp_path):
    path = tmp_path / 'session.jsonl'
    payload = b'\xff\r\n\x00\n'
    path.write_bytes(payload)
    assert read_session_transcript_bytes(path) == payload


def test_invalid_compressed_archive_is_an_error_instead_of_an_empty_projection(tmp_path):
    if sys.version_info >= (3, 14):
        from compression.zstd import ZstdError
    else:
        from zstandard import ZstdError

    path = tmp_path / 'session.jsonl.deleted.2026-11-09T00-00-00Z.zst'
    path.write_bytes(b'not a Zstandard frame')
    with pytest.raises(ZstdError):
        read_session_transcript_bytes(path)
