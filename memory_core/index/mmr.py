from __future__ import annotations

import re
from collections.abc import Iterable
from typing import TypeVar

T = TypeVar("T", bound=dict)

CJK_RE = re.compile(
    r"[\u3040-\u309f\u30a0-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\u1100-\u11ff]"
)
ASCII_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def tokenize(text: str) -> set[str]:
    lower = (text or "").lower()
    ascii_tokens = ASCII_TOKEN_RE.findall(lower)

    chars = list(lower)
    cjk_data: list[tuple[str, int]] = []
    for index, char in enumerate(chars):
        if CJK_RE.fullmatch(char):
            cjk_data.append((char, index))

    bigrams = [
        char + next_char
        for (char, index), (next_char, next_index) in zip(cjk_data, cjk_data[1:], strict=False)
        if next_index == index + 1
    ]
    unigrams = [char for char, _index in cjk_data]
    return set(ascii_tokens + bigrams + unigrams)


def jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    intersection_size = len(set_a & set_b)
    union_size = len(set_a) + len(set_b) - intersection_size
    return 0.0 if union_size == 0 else intersection_size / union_size


def text_similarity(content_a: str, content_b: str) -> float:
    return jaccard_similarity(tokenize(content_a), tokenize(content_b))


def compute_mmr_score(relevance: float, max_similarity: float, lambda_: float) -> float:
    return lambda_ * relevance - (1 - lambda_) * max_similarity


def _max_similarity_to_selected(
    item: dict,
    selected_items: Iterable[dict],
    token_cache: dict[str, set[str]],
) -> float:
    max_similarity = 0.0
    item_tokens = token_cache.get(str(item["id"]), tokenize(str(item.get("content", ""))))

    for selected in selected_items:
        selected_tokens = token_cache.get(
            str(selected["id"]),
            tokenize(str(selected.get("content", ""))),
        )
        max_similarity = max(max_similarity, jaccard_similarity(item_tokens, selected_tokens))

    return max_similarity


def mmr_rerank(items: list[T], *, enabled: bool = False, lambda_: float = 0.7) -> list[T]:
    if not enabled or len(items) <= 1:
        return list(items)

    clamped_lambda = max(0.0, min(1.0, lambda_))
    if clamped_lambda == 1:
        return sorted(items, key=lambda item: float(item["score"]), reverse=True)

    token_cache = {str(item["id"]): tokenize(str(item.get("content", ""))) for item in items}

    scores = [float(item["score"]) for item in items]
    max_score = max(scores)
    min_score = min(scores)
    score_range = max_score - min_score

    def normalize_score(score: float) -> float:
        if score_range == 0:
            return 1.0
        return (score - min_score) / score_range

    selected: list[T] = []
    remaining = list(items)

    while remaining:
        best_item: T | None = None
        best_mmr_score = float("-inf")

        for candidate in remaining:
            normalized_relevance = normalize_score(float(candidate["score"]))
            max_similarity = _max_similarity_to_selected(candidate, selected, token_cache)
            mmr_score = compute_mmr_score(
                normalized_relevance,
                max_similarity,
                clamped_lambda,
            )

            best_original_score = (
                float(best_item["score"]) if best_item is not None else float("-inf")
            )
            if mmr_score > best_mmr_score or (
                mmr_score == best_mmr_score and float(candidate["score"]) > best_original_score
            ):
                best_mmr_score = mmr_score
                best_item = candidate

        if best_item is None:
            break

        selected.append(best_item)
        remaining.remove(best_item)

    return selected
