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


@pytest.mark.skipif(sys.platform == "win32", reason="The shared archive cache requires private POSIX files")
@pytest.mark.parametrize("forget_authority", ["catalog", "origins"])
def test_compat_archive_reopen_strict_freshness_and_forget(tmp_path, monkeypatch, forget_authority):
    import os
    import sqlite3
    import tempfile
    from contextlib import closing
    from memory_core.consolidation.origins import MemoryEntryOriginLedger
    from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
    from memory_core.session_catalog import MemorySessionCatalog
    from memory_core.session_corpus import MemoryCoreSessionCorpus, SessionCorpusFile

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite")
    ledger = MemoryEntryOriginLedger(lambda _: tmp_path / "origins#?.sqlite")
    path = tmp_path / "example.jsonl.reset.2026-11-09T00-00-00Z.zst"
    file = SessionCorpusFile("sessions/main/" + path.name, path, session_id="example", artifact_kind="archive-artifact")
    stamp = 1794000000000000000

    def write(letter):
        frame = _compress(b'{"type":"message","message":{"role":"user","content":"' + letter + b'"}}\n')
        path.write_bytes(frame)
        os.utime(path, ns=(stamp, stamp))
        return frame

    def corpus(**kwargs):
        return MemoryCoreSessionCorpus(tmp_path, agent_id=" MAIN " if forget_authority == "catalog" else "main", catalog=catalog,
                                       runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
                                       archive_origins_path=ledger.database_path("main"), **kwargs)

    first = write(b"A")
    assert corpus().read_index_entry(file).content == "User: A"
    assert len(write(b"B")) == len(first)
    assert corpus().read_index_entry(file).content == "User: A"
    assert corpus(cache_compressed_archives=False).read_index_entry(file).content == "User: B"
    other_tmp = tmp_path / "other-temp"
    other_tmp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(other_tmp))
    database, = tmp_path.glob(".*-session-archives-*/*.sqlite")
    with closing(sqlite3.connect(database, isolation_level=None)) as db:
        assert db.execute("SELECT frame FROM archives").fetchone() == (first,)
        db.execute("BEGIN EXCLUSIVE")
        assert corpus().read_index_entry(file).content == "User: B"
        if forget_authority == "catalog":
            catalog.tombstone_session("example")
        else:
            assert ledger.record_session_tombstones("main", ["example"]) == 1
        assert corpus().read_index_entry(file) is None
        assert corpus(cache_compressed_archives=False).read_index_entry(file) is None
        db.execute("COMMIT")
        assert corpus().read_index_entry(file) is None
        assert db.execute("SELECT count(*) FROM archives").fetchone() == (0,)
    assert path.is_file()
    catalog.path.unlink()
    assert corpus().read_index_entry(file) is None
    assert not catalog.path.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="The shared archive cache requires private POSIX files")
def test_corrupt_or_unsafe_optional_archive_cache_reads_the_original(tmp_path):
    import sqlite3
    from contextlib import closing
    from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
    from memory_core.session_catalog import MemorySessionCatalog
    from memory_core.session_corpus import MemoryCoreSessionCorpus, SessionCorpusFile

    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite")
    corpus = MemoryCoreSessionCorpus(tmp_path, agent_id="main", catalog=catalog,
                                     runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)
    path = tmp_path / "s.jsonl.deleted.2026-11-09T00-00-00Z.zst"
    path.write_bytes(_compress(b'{"type":"message","message":{"role":"user","content":"admitted"}}\n'))
    file = SessionCorpusFile("sessions/main/" + path.name, path, session_id="s", artifact_kind="archive-artifact")
    assert corpus.read_index_entry(file).content == "User: admitted"
    database, = tmp_path.glob(".*-session-archives-*/*.sqlite")
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("UPDATE archives SET frame=?", (b"corrupt frame",))
    assert corpus.read_index_entry(file).content == "User: admitted"
    database.write_bytes(b"corrupt SQLite")
    assert corpus.read_index_entry(file).content == "User: admitted"
    database.unlink()
    other = tmp_path / "different-owner"
    other.write_bytes(b"untouched")
    database.symlink_to(other)
    assert corpus.read_index_entry(file).content == "User: admitted"
    assert other.read_bytes() == b"untouched"
