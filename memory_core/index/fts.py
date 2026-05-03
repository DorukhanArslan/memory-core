from __future__ import annotations

import math


def _unicode_word_tokens(raw: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    for char in raw:
        if char.isalnum() or char == "_":
            current.append(char)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return [token.strip() for token in tokens if token.strip()]


def build_fts_query(raw: str) -> str | None:
    tokens = _unicode_word_tokens(raw)
    if not tokens:
        return None
    quoted = [f'"{token.replace('"', '')}"' for token in tokens]
    return " AND ".join(quoted)


def bm25_rank_to_score(rank: float) -> float:
    if not math.isfinite(rank):
        return 1 / (1 + 999)
    if rank < 0:
        relevance = -rank
        return relevance / (1 + relevance)
    return 1 / (1 + rank)
