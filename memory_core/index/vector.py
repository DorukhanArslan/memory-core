from __future__ import annotations

import json
import math
import struct
from collections.abc import Sequence


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Native cosine over the shared prefix; absent dimensions do not enter either norm."""
    if not a or not b:
        return 0.0

    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for av, bv in zip(a, b):
        # SQLite's native vector codec and JavaScript arithmetic use binary64.
        # A null coordinate follows the native helper's nullish-zero fallback.
        av = 0.0 if av is None else float(av)
        bv = 0.0 if bv is None else float(bv)
        dot += av * bv
        norm_a += av * av
        norm_b += bv * bv

    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def decode_memory_embedding(raw: str | bytes | bytearray | memoryview) -> list[float]:
    """Read a derived vector without letting corrupt rows interrupt candidate search.

    Ordinary Python rows retain their private JSON encoding. Binary rows use the
    native persistent little-endian binary64 codec, including its invalid-length
    and non-finite rejection. Both representations produce the same logical array.
    """
    if isinstance(raw, (bytes, bytearray, memoryview)):
        encoded = bytes(raw)
        if len(encoded) % 8:
            return []
        values = [coordinate[0] for coordinate in struct.iter_unpack("<d", encoded)]
    elif isinstance(raw, str):
        try:
            values = json.loads(raw)
        except (ValueError, TypeError):
            return []
        if not isinstance(values, list):
            return []
    else:
        return []
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
        return []
    try:
        vector = [float(value) for value in values]
    except (OverflowError, ValueError):
        return []
    return vector if all(math.isfinite(value) for value in vector) else []
