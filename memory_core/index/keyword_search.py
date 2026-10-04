"""Keyword retrieval of the memory index (OpenClaw ``memory/manager-search.ts`` and
``manager-keyword-retrieval.ts`` at v2026.9.6).

Two surfaces feed one candidate list: the chunk text (FTS5 over ``chunks_fts``, BM25) and the file
path (FTS5 over ``paths_fts``, with exact-path tiers: a query that names a file, a basename or a
stem). Hits keep their raw BM25 ``text_score`` and carry a boosted ``score`` (query overlap, path
and length boosts) that ranks them. This module holds the pure parts: the path matcher, the boost
and the merge/limit/compare of hits; the SQL is in :mod:`sqlite_store`.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

from memory_core.bootstrap._js import locale_sort_key
from memory_core.index.cjk_chars import utf16_length

EXACT_PATH_CANDIDATE_LIMIT = 200
SNIPPET_MAX_CHARS = 700


@dataclass
class KeywordHit:
    id: str
    path: str
    start_line: int
    end_line: int
    source: str
    snippet: str
    score: float
    text_score: float
    path_score: float = 0.0
    exact_path_specificity: int = 0
    has_body_match: bool = True


def _word_tokens(raw: str) -> list[str]:
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
    return tokens


def normalize_search_tokens(raw: str) -> list[str]:
    """``normalizeSearchTokens``: NFC, lower-cased word tokens."""
    return [token.strip().lower() for token in _word_tokens(unicodedata.normalize("NFC", raw)) if token.strip()]


def _literal_matcher(value: str, *, whole: bool = False) -> re.Pattern[str]:
    literal = re.escape(unicodedata.normalize("NFC", value))
    return re.compile(f"^(?:{literal})$" if whole else literal, re.IGNORECASE)


def prepare_query_matchers(ranking_query: str) -> list[tuple[re.Pattern[str], re.Pattern[str]]]:
    tokens = list(dict.fromkeys(normalize_search_tokens(ranking_query)))
    return [(_literal_matcher(token, whole=True), _literal_matcher(token)) for token in tokens]


def score_fallback_keyword_result(
    *,
    query_matchers: list[tuple[re.Pattern[str], re.Pattern[str]]],
    path: str,
    text: str,
    fts_score: float,
) -> float:
    """``scoreFallbackKeywordResult``: the BM25 score plus lexical overlap, path and length boosts."""
    if not query_matchers:
        return fts_score
    text_tokens = normalize_search_tokens(text)
    token_set = set(text_tokens)
    overlap = sum(
        1 for word, _ in query_matchers if any(word.search(token) for token in text_tokens)
    )
    unique_query_overlap = overlap / len(query_matchers)
    density = overlap / max(len(token_set), 1)
    normalized_path = unicodedata.normalize("NFC", path)
    path_boost = 0.0
    for _, substring in query_matchers:
        path_boost += 0.18 if substring.search(normalized_path) else 0.0
    text_length_boost = min(utf16_length(text) / 160, 0.18)
    lexical_boost = unique_query_overlap * 0.45 + density * 0.2 + path_boost + text_length_boost
    return min(1.0, fts_score + lexical_boost)


def _normalize_path_identifier(value: str) -> str:
    text = value.strip().replace("\\", "/")
    if text.startswith("./"):
        text = text[2:]
    return unicodedata.normalize("NFC", text).lower()


def prepare_exact_path_matcher(query: str) -> Callable[[str], int]:
    """``prepareExactPathMatcher``: 3 full path, 2 basename, 1 stem, else 0."""
    normalized_query = _normalize_path_identifier(query)
    if not normalized_query or normalized_query == ".":
        return lambda _path: 0
    has_directory = "/" in normalized_query

    def match(candidate_path: str) -> int:
        normalized_path = _normalize_path_identifier(candidate_path)
        if normalized_query == normalized_path:
            return 3
        if has_directory:
            return 0
        basename = normalized_path.split("/")[-1]
        if normalized_query == basename:
            return 2
        extension_index = basename.rfind(".")
        stem = basename[:extension_index] if extension_index > 0 else basename
        return 1 if normalized_query == stem else 0

    return match


def _body_score(hit: KeywordHit) -> float:
    return hit.score if hit.has_body_match else 0.0


def keyword_hit_sort_key(hit: KeywordHit, *, prefer_exact_body: bool = True):
    """``compareKeywordSearchHits`` as a sort key."""
    body_presence = (
        -int(hit.has_body_match) if prefer_exact_body and hit.exact_path_specificity > 0 else 0
    )
    return (
        -hit.exact_path_specificity,
        body_presence,
        -hit.score,
        -hit.text_score,
        -hit.path_score if hit.exact_path_specificity == 0 else 0,
        locale_sort_key(hit.path),
        hit.start_line,
        locale_sort_key(hit.id),
    )


def merge_keyword_search_hits(
    result_sets: list[list[KeywordHit]], exact_path_query: str
) -> list[KeywordHit]:
    """``mergeKeywordSearchHits``: by chunk id; only the original query claims exact path tiers."""
    match_exact_path = prepare_exact_path_matcher(exact_path_query)
    seen: dict[str, KeywordHit] = {}
    for results in result_sets:
        for result in results:
            existing = seen.get(result.id)
            if existing is None:
                result.exact_path_specificity = match_exact_path(result.path)
                seen[result.id] = result
                continue
            existing_has_body = existing.has_body_match
            result_has_body = result.has_body_match
            existing_body = existing.score if existing_has_body else 0.0
            result_body = result.score if result_has_body else 0.0
            existing.text_score = max(existing.text_score, result.text_score)
            existing.path_score = max(existing.path_score, result.path_score)
            existing.has_body_match = existing.has_body_match or result.has_body_match
            body_score = max(existing_body, result_body)
            existing.score = body_score if body_score > 0 else existing.path_score
            # Path hits project the first chunk; a real body-match snippet stays authoritative.
            if (result_has_body and not existing_has_body) or (
                result_has_body == existing_has_body and len(result.snippet) > len(existing.snippet)
            ):
                existing.snippet = result.snippet
    merged = list(seen.values())
    for result in merged:
        if not result.has_body_match:
            # A uniform exact-only baseline lets temporal decay order otherwise equivalent
            # filename hits without reusing incomparable path BM25.
            result.score = 1.0 if result.exact_path_specificity > 0 else result.path_score
    return sorted(merged, key=keyword_hit_sort_key)


def limit_keyword_search_hits(results: list[KeywordHit], non_exact_limit: int) -> list[KeywordHit]:
    """``limitKeywordSearchHits``: bounded exact-path tier, then the non-exact window."""
    ranked = sorted(results, key=keyword_hit_sort_key)
    exact_body = [h for h in ranked if h.exact_path_specificity > 0 and h.has_body_match][
        :non_exact_limit
    ]
    exact_path_only = [h for h in ranked if h.exact_path_specificity > 0 and not h.has_body_match]
    bounded_exact = sorted(exact_body + exact_path_only, key=keyword_hit_sort_key)
    selected_path_keys: set[str] = set()
    for entry in bounded_exact:
        selected_path_keys.add(f"{entry.source}:{entry.path}")
        if len(selected_path_keys) == EXACT_PATH_CANDIDATE_LIMIT:
            break
    exact = [h for h in bounded_exact if f"{h.source}:{h.path}" in selected_path_keys]
    non_exact = [h for h in ranked if h.exact_path_specificity == 0][:non_exact_limit]
    return exact + non_exact
