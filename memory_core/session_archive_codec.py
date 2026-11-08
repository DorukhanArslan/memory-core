"""Read transcript archives without changing the decoded JSONL bytes."""
from __future__ import annotations

from pathlib import Path
import sys


def read_session_transcript_bytes(path: Path) -> bytes:
    """Read plain JSONL or a Zstandard archive using native frame semantics.

    A registered archive keeps its source identity and filesystem metadata;
    decoding does not publish a second materialized transcript or index it.
    """
    data = path.read_bytes()
    if not path.name.endswith(".zst"):
        return data
    if sys.version_info >= (3, 14):
        from compression import zstd

        return zstd.ZstdDecompressor().decompress(data)
    import zstandard

    return zstandard.ZstdDecompressor().decompressobj().decompress(data)
