"""Private POSIX cache for OpenClaw-compatible compressed transcript generations."""
from __future__ import annotations

from collections.abc import Callable, Collection
from contextlib import closing, suppress
import hashlib
import os
from pathlib import Path
import sqlite3
import stat
import time
from typing import BinaryIO

from memory_core.project_name import DIST_NAME
from memory_core.session_archive_codec import decode_session_transcript_bytes

_MAX_AGE = 24 * 60 * 60


def _key(*parts: str | Path) -> str:
    return hashlib.sha256(b"\0".join(os.fsencode(part) for part in parts)).hexdigest()


def _directory(authority: Path, *, create: bool) -> Path | None:
    if not hasattr(os, "geteuid"):
        return None
    uid = os.geteuid()
    authority = authority.resolve()
    directory = authority.parent / f".{DIST_NAME}-session-archives-{_key(authority.name)[:24]}"
    if create:
        directory.mkdir(mode=0o700, exist_ok=True)
    with suppress(FileNotFoundError):
        info = directory.lstat()
        if stat.S_ISDIR(info.st_mode) and info.st_uid == uid and not info.st_mode & 0o077:
            return directory
    return None


def _database(directory: Path, *, create: bool) -> sqlite3.Connection | None:
    path = directory / "archives-v1.sqlite"
    if create:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
    elif not path.exists():
        return None
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_nlink != 1:
        return None
    db = sqlite3.connect(path, timeout=0.2)
    try:
        db.execute("PRAGMA secure_delete=ON")
        db.execute("CREATE TABLE IF NOT EXISTS archives "
                   "(source TEXT PRIMARY KEY, catalog TEXT, origins TEXT, generation TEXT, stored INTEGER, frame BLOB)")
        # An earlier forget may have committed while this optional database
        # was busy. Only hashes of the authorities and session IDs are queued.
        for marker in directory.glob("purge-*"):
            tag = marker.name.removeprefix("purge-")
            if len(tag) == 64 and all(ch in "0123456789abcdef" for ch in tag):
                with db:
                    db.execute("DELETE FROM archives WHERE catalog=?1 OR origins=?1", (tag,))
                marker.unlink(missing_ok=True)
        return db
    except BaseException:
        db.close()
        raise


def _register_catalog(catalog: Path, origins: Path) -> bool:
    """Make the source catalog discoverable to an independently committed origins forget."""
    root = _directory(origins, create=True)
    if root is None:
        return False
    path = catalog.resolve()
    marker = root / ("catalog-" + _key(path))
    wire = os.fsencode(path)
    try:
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        info = marker.lstat()
        return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.geteuid()
                and not info.st_mode & 0o077 and info.st_size == len(wire) and marker.read_bytes() == wire)
    with os.fdopen(fd, "wb") as stream:
        stream.write(wire)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return True


def _purge(directory: Path, tags: Collection[str]) -> None:
    if not (directory / "archives-v1.sqlite").exists():
        return
    for tag in tags:
        with suppress(FileExistsError):
            fd = os.open(directory / ("purge-" + tag), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
    db = _database(directory, create=False)
    if db is not None:
        db.close()


def discard_session_archives(authority: Path, agent: str, session_ids: Collection[str]) -> None:
    """Evict through the stable authority path, including all registered catalogs."""
    with suppress(OSError, sqlite3.Error):
        root = _directory(authority, create=False)
        if root is None:
            return
        tags = [_key(authority.resolve(), agent, sid) for sid in session_ids]
        with suppress(OSError, sqlite3.Error):
            _purge(root, tags)
        for marker in root.glob("catalog-*"):
            with suppress(OSError, sqlite3.Error):
                info = marker.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 8192:
                    continue
                catalog = Path(os.fsdecode(marker.read_bytes()))
                if not catalog.is_absolute() or marker.name != "catalog-" + _key(catalog):
                    continue
                directory = _directory(catalog, create=False)
                if directory is not None and directory != root:
                    _purge(directory, tags)


def discard_archive(catalog: Path, agent: str, path: Path) -> None:
    with suppress(OSError, sqlite3.Error):
        directory = _directory(catalog, create=False)
        db = _database(directory, create=False) if directory is not None else None
        if db is not None:
            with closing(db), db:
                db.execute("DELETE FROM archives WHERE source=?", (_key(catalog.resolve(), agent, path.absolute()),))


def read_archive(
    stream: BinaryIO, catalog: Path, origins: Path | None, catalog_agent: str, origins_agent: str, session_id: str,
    path: Path, info: os.stat_result, mtime_ms: float, is_forgotten: Callable[[str], bool],
) -> bytes | None:
    """Read an admitted source using its size and truncated millisecond generation.

    Device and inode also isolate replacement files. Each access checks current
    source permissions and uses current redaction. If this optional cache is
    unavailable, the original, already open source remains authoritative.
    """
    frame = None
    key = _key(catalog.resolve(), catalog_agent, path.absolute())
    catalog_tag = _key(catalog.resolve(), catalog_agent, session_id)
    origins_tag = _key(origins.resolve(), origins_agent, session_id) if origins is not None else None
    catalog_identity = catalog.stat()
    generation = (f"{catalog_identity.st_dev}:{catalog_identity.st_ino}:{info.st_dev}:{info.st_ino}:"
                  f"{info.st_uid}:{info.st_gid}:{info.st_size}:{int(mtime_ms)}")
    now = int(time.time())
    with suppress(OSError, sqlite3.Error):
        if origins is not None and not _register_catalog(catalog, origins):
            return decode_session_transcript_bytes(stream.read(), compressed=True)
        directory = _directory(catalog, create=True)
        db = _database(directory, create=True) if directory is not None else None
        if db is not None:
            with closing(db), db:
                db.execute("DELETE FROM archives WHERE stored < ?", (now - _MAX_AGE,))
                # A forget that committed before our writer lock wins. Any
                # later forget evicts the frame after this transaction ends,
                # even if this reader dies before returning its projection.
                try:
                    if is_forgotten(session_id):
                        return None
                except (OSError, sqlite3.Error):
                    return None
                found = db.execute("SELECT frame FROM archives WHERE source=? AND catalog=? AND origins IS ? AND generation=?",
                                   (key, catalog_tag, origins_tag, generation)).fetchone()
                if found is not None:
                    try:
                        return decode_session_transcript_bytes(found[0], compressed=True)
                    except Exception:
                        # A damaged cache frame can be rebuilt from the admitted source.
                        pass
                frame = stream.read()
                decoded = decode_session_transcript_bytes(frame, compressed=True)
                db.execute("INSERT OR REPLACE INTO archives VALUES(?,?,?,?,?,?)",
                           (key, catalog_tag, origins_tag, generation, now, frame))
                return decoded
    return decode_session_transcript_bytes(stream.read() if frame is None else frame, compressed=True)
