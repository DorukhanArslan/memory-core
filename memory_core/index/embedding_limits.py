"""Pinned text-only pre-embedding byte limits, retaining original chunk spans.

Ports embedding-model-limits.ts, embedding-input-limits.ts and the text branch
of embedding-chunk-limits.ts. These limits approximate tokenizer capacity with
UTF-8 bytes; they do not tokenize or split an indivisible surrogate pair.
"""
from __future__ import annotations

import math
from typing import Any

from memory_core.bootstrap._js import js_utf8_encode
from memory_core.index.chunking import MemoryChunk


EMBEDDING_BATCH_MAX_TOKENS = 8000
DEFAULT_EMBEDDING_MAX_INPUT_TOKENS = 8192
DEFAULT_LOCAL_EMBEDDING_MAX_INPUT_TOKENS = 2048


def resolve_embedding_max_input_tokens(provider: Any) -> int | float:
    maximum = getattr(provider, "max_input_tokens", None)
    if type(maximum) in (int, float):
        return maximum
    return (DEFAULT_LOCAL_EMBEDDING_MAX_INPUT_TOKENS if provider.provider_id == "local"
            else DEFAULT_EMBEDDING_MAX_INPUT_TOKENS)


def split_text_to_utf8_byte_limit(text: str, max_utf8_bytes: int | float) -> list[str]:
    if max_utf8_bytes <= 0 or len(js_utf8_encode(text)) <= max_utf8_bytes:
        return [text]
    data = text.encode("utf-16-le", "surrogatepass")
    length = len(data) // 2

    def part(start, end):
        return data[start * 2:end * 2].decode("utf-16-le", "surrogatepass")

    def unit(index):
        return int.from_bytes(data[index * 2:index * 2 + 2], "little")

    parts = []
    cursor = 0
    while cursor < length:
        low = cursor + 1
        high = math.nan if math.isnan(max_utf8_bytes) else min(length, cursor + max_utf8_bytes)
        best = cursor
        while low <= high:
            mid = math.floor((low + high) / 2)
            if len(js_utf8_encode(part(cursor, mid))) <= max_utf8_bytes:
                best = mid
                low = mid + 1
            else:
                high = mid - 1
        if best <= cursor:
            best = min(length, cursor + 1)
        if (cursor < best < length and 0xD800 <= unit(best - 1) <= 0xDBFF
                and 0xDC00 <= unit(best) <= 0xDFFF):
            best = best - 1 if best - 1 > cursor else best + 1
        parts.append(part(cursor, best))
        cursor = best
    return parts


def enforce_embedding_max_input_tokens(provider: Any, chunks: list[MemoryChunk],
                                        hard_max_input_tokens: int | float = EMBEDDING_BATCH_MAX_TOKENS) -> list[MemoryChunk]:
    maximum = resolve_embedding_max_input_tokens(provider)
    if type(hard_max_input_tokens) in (int, float) and hard_max_input_tokens > 0:
        maximum = math.nan if math.isnan(maximum) else min(maximum, hard_max_input_tokens)
    result = []
    for chunk in chunks:
        if len(js_utf8_encode(chunk.text)) <= maximum:
            result.append(chunk)
        else:
            result.extend(chunk.with_text(text) for text in split_text_to_utf8_byte_limit(chunk.text, maximum))
    return result
