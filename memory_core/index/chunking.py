from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryChunk:
    id: str
    path: str
    start_line: int
    end_line: int
    text: str
    source: str = "memory"


def chunk_markdown(
    path: str,
    text: str,
    *,
    target_tokens: int = 400,
    overlap_tokens: int = 80,
) -> list[MemoryChunk]:
    target = max(1, target_tokens)
    overlap = max(0, overlap_tokens)
    line_tokens = [
        (index + 1, line, line.split()) for index, line in enumerate(text.splitlines())
    ]
    chunks: list[MemoryChunk] = []
    current: list[tuple[int, str, list[str]]] = []
    current_count = 0

    for item in line_tokens:
        current.append(item)
        current_count += len(item[2])
        if current_count >= target:
            chunk = _make_chunk(path, current)
            if chunk is not None:
                chunks.append(chunk)
            current = _overlap_rows(current, overlap)
            current_count = sum(len(row[2]) for row in current)

    if current:
        chunk = _make_chunk(path, current)
        if chunk is not None and (not chunks or chunks[-1].id != chunk.id):
            chunks.append(chunk)

    return chunks


def _overlap_rows(
    rows: list[tuple[int, str, list[str]]],
    overlap_tokens: int,
) -> list[tuple[int, str, list[str]]]:
    if overlap_tokens <= 0:
        return []

    selected: list[tuple[int, str, list[str]]] = []
    count = 0
    for row in reversed(rows):
        selected.insert(0, row)
        count += len(row[2])
        if count >= overlap_tokens:
            break
    return selected


def _make_chunk(path: str, rows: list[tuple[int, str, list[str]]]) -> MemoryChunk | None:
    start_line = rows[0][0]
    end_line = rows[-1][0]
    chunk_text = "\n".join(row[1] for row in rows).strip()
    if not chunk_text:
        return None
    chunk_text = f"{chunk_text}\n"
    digest = hashlib.sha256(
        f"{path}:{start_line}:{end_line}:{chunk_text}".encode("utf-8")
    ).hexdigest()
    return MemoryChunk(
        id=digest,
        path=path,
        start_line=start_line,
        end_line=end_line,
        text=chunk_text,
    )
