"""Concept tags for short-term recall entries.

Port of ``extensions/memory-core/src/concept-vocabulary.ts`` (``deriveConceptTags``,
its stop-word sets, protected glossary and script classification) at OpenClaw
pin 4c42815348. The oracle operation ``deriveConceptTags`` compares these tags
with the real TypeScript function.
"""

from __future__ import annotations

import math
import re
import unicodedata
from pathlib import Path

MAX_CONCEPT_TAGS = 8


def _normalize_lowercase_string(value: str) -> str:
    return " ".join(str(value).strip().lower().split())


_LANGUAGE_STOP_WORDS = {
    "about",
    "after",
    "agent",
    "again",
    "also",
    "assistant",
    "because",
    "before",
    "being",
    "between",
    "build",
    "called",
    "could",
    "daily",
    "default",
    "deploy",
    "during",
    "every",
    "file",
    "files",
    "from",
    "have",
    "into",
    "just",
    "line",
    "lines",
    "long",
    "main",
    "make",
    "memory",
    "month",
    "more",
    "most",
    "move",
    "much",
    "next",
    "note",
    "notes",
    "over",
    "part",
    "past",
    "port",
    "same",
    "score",
    "search",
    "session",
    "sessions",
    "short",
    "should",
    "since",
    "some",
    "subagent",
    "system",
    "than",
    "that",
    "their",
    "there",
    "these",
    "they",
    "this",
    "through",
    "today",
    "user",
    "using",
    "with",
    "work",
    "workspace",
    "year",
    "and",
    "are",
    "for",
    "its",
    "our",
    "the",
    "then",
    "were",
    "you",
    "your",
    "al",
    "con",
    "como",
    "de",
    "del",
    "el",
    "en",
    "es",
    "la",
    "las",
    "los",
    "para",
    "por",
    "que",
    "se",
    "sin",
    "su",
    "sus",
    "una",
    "uno",
    "unos",
    "unas",
    "y",
    "au",
    "aux",
    "avec",
    "dans",
    "des",
    "du",
    "est",
    "et",
    "le",
    "les",
    "ou",
    "pour",
    "qui",
    "sans",
    "ses",
    "son",
    "sur",
    "une",
    "un",
    "auf",
    "aus",
    "bei",
    "das",
    "dem",
    "den",
    "der",
    "die",
    "ein",
    "eine",
    "einem",
    "einen",
    "einer",
    "für",
    "im",
    "in",
    "mit",
    "nach",
    "oder",
    "ohne",
    "über",
    "und",
    "von",
    "zu",
    "zum",
    "zur",
    "が",
    "から",
    "する",
    "して",
    "した",
    "で",
    "と",
    "に",
    "の",
    "は",
    "へ",
    "まで",
    "も",
    "や",
    "を",
    "与",
    "为",
    "了",
    "及",
    "和",
    "在",
    "将",
    "或",
    "把",
    "是",
    "用",
    "的",
    "과",
    "는",
    "도",
    "로",
    "를",
    "에",
    "에서",
    "와",
    "은",
    "으로",
    "을",
    "이",
    "하다",
    "한",
    "할",
    "해",
    "했다",
    "cjs",
    "cpp",
    "cts",
    "jsx",
    "json",
    "md",
    "mjs",
    "mts",
    "text",
    "toml",
    "ts",
    "tsx",
    "txt",
    "yaml",
    "yml",
}
_CONCEPT_STOP_WORDS = {_normalize_lowercase_string(word) for word in _LANGUAGE_STOP_WORDS}
_PROTECTED_GLOSSARY = [
    "backup",
    "backups",
    "embedding",
    "embeddings",
    "failover",
    "gateway",
    "glacier",
    "gpt",
    "kv",
    "network",
    "openai",
    "qmd",
    "router",
    "s3",
    "vlan",
    "sauvegarde",
    "routeur",
    "passerelle",
    "konfiguration",
    "sicherung",
    "überwachung",
    "configuración",
    "respaldo",
    "enrutador",
    "puerta-de-enlace",
    "バックアップ",
    "フェイルオーバー",
    "ルーター",
    "ネットワーク",
    "ゲートウェイ",
    "障害対応",
    "路由器",
    "备份",
    "故障转移",
    "网络",
    "网关",
    "라우터",
    "백업",
    "페일오버",
    "네트워크",
    "게이트웨이",
    "장애대응",
]
_PROTECTED_GLOSSARY = [
    _normalize_lowercase_string(unicodedata.normalize("NFKC", word))
    for word in _PROTECTED_GLOSSARY
]
_COMPOUND_TOKEN_RE = re.compile(r"[^\W_]+(?:[._/-][^\W_]+)+", re.UNICODE)
_SEGMENT_TOKEN_RE = re.compile(r"[^\W\d_]*[^\W_][^\W_]*(?:\.[^\W_]+)?", re.UNICODE)


def derive_concept_tags(path: str, snippet: str, limit: int = MAX_CONCEPT_TAGS) -> list[str]:
    """Derive up to ``limit`` concept tags from a path basename and snippet.

    Glossary hits come first, then compound and segment tokens, each normalized
    (NFKC, lowercase, edge punctuation stripped) and filtered by stop words and
    per-script minimum lengths (upstream ``deriveConceptTags``).
    """
    normalized_limit = max(0, int(limit)) if math.isfinite(float(limit)) else MAX_CONCEPT_TAGS
    if normalized_limit == 0:
        return []
    source = f"{Path(path).name} {snippet}"
    tags: list[str] = []
    for raw_token in _collect_glossary_matches(source):
        _push_normalized_concept_tag(tags, raw_token, normalized_limit, from_glossary=True)
        if len(tags) >= normalized_limit:
            return tags
    for raw_token in _collect_compound_tokens(source) + _collect_segment_tokens(source):
        _push_normalized_concept_tag(tags, raw_token, normalized_limit)
        if len(tags) >= normalized_limit:
            break
    return tags


def _minimum_token_length_for_script(script: str) -> int:
    return 2 if script == "cjk" else 3


def _includes_standalone_term(source: str, entry: str) -> bool:
    start = source.find(entry)
    while start != -1:
        before = source[start - 1] if start > 0 else ""
        after_index = start + len(entry)
        after = source[after_index] if after_index < len(source) else ""
        if (not before or not before.isalnum()) and (not after or not after.isalnum()):
            return True
        start = source.find(entry, start + 1)
    return False


def _glossary_entry_requires_whole_word(entry: str) -> bool:
    return len(entry) < _minimum_token_length_for_script(_classify_concept_tag_script(entry))


_GLOSSARY_WHOLE_WORD: dict[str, bool] = {}


def _glossary_whole_word(entry: str) -> bool:
    if not _GLOSSARY_WHOLE_WORD:
        _GLOSSARY_WHOLE_WORD.update(
            {word: _glossary_entry_requires_whole_word(word) for word in _PROTECTED_GLOSSARY}
        )
    return _GLOSSARY_WHOLE_WORD[entry]


def _collect_glossary_matches(source: str) -> list[str]:
    normalized_source = _normalize_lowercase_string(unicodedata.normalize("NFKC", source))
    matches = []
    for entry in _PROTECTED_GLOSSARY:
        # Short glossary entries (e.g. "kv", "s3") bypass the min-length gate,
        # so they must match as standalone terms rather than inside longer words.
        present = (
            _includes_standalone_term(normalized_source, entry)
            if _glossary_whole_word(entry)
            else entry in normalized_source
        )
        if present:
            matches.append(entry)
    return matches


def _collect_compound_tokens(source: str) -> list[str]:
    return _COMPOUND_TOKEN_RE.findall(source)


def _collect_segment_tokens(source: str) -> list[str]:
    # Approximates Intl.Segmenter("und", {granularity: "word"}) word-like segments. A "."
    # keeps a word together only between two letters or two digits (UAX #29 WB6/7, WB11/12):
    # "0.76" and "e.g" stay whole, "26.md" (from a dated file name) splits into "26" and "md".
    tokens: list[str] = []
    for token in _SEGMENT_TOKEN_RE.findall(source):
        head, dot, tail = token.partition(".")
        if dot and head[-1].isdigit() != tail[0].isdigit():
            tokens.extend((head, tail))
        else:
            tokens.append(token)
    return tokens


def _push_normalized_concept_tag(
    tags: list[str], raw_token: str, limit: int, from_glossary: bool = False
) -> None:
    normalized = _normalize_concept_token(raw_token, from_glossary=from_glossary)
    if not normalized or normalized in tags:
        return
    tags.append(normalized)
    if len(tags) > limit:
        del tags[limit:]


def _normalize_concept_token(raw_token: str, from_glossary: bool = False) -> str | None:
    normalized = _normalize_lowercase_string(
        _strip_non_alnum_edges(unicodedata.normalize("NFKC", raw_token)).replace("_", "-")
    )
    if not normalized or not any(char.isalnum() for char in normalized) or len(normalized) > 32:
        return None
    if (
        normalized.isdigit()
        or re.fullmatch(r"\d{4}-\d{2}-\d{2}", normalized)
        or re.fullmatch(r"\d{4}-\d{2}-\d{2}\.[^\W_]+", normalized, re.UNICODE)
    ):
        return None
    script = _classify_concept_tag_script(normalized)
    # Glossary entries are an explicit allowlist of short technical terms
    # (e.g. "kv", "s3"); they bypass the per-script minimum length gate.
    if not from_glossary and len(normalized) < _minimum_token_length_for_script(script):
        return None
    if _is_kana_only_token(normalized) and len(normalized) < 3:
        return None
    if normalized in _CONCEPT_STOP_WORDS:
        return None
    return normalized


def _strip_non_alnum_edges(value: str) -> str:
    start = 0
    end = len(value)
    while start < end and not value[start].isalnum():
        start += 1
    while end > start and not value[end - 1].isalnum():
        end -= 1
    return value[start:end]


def _classify_concept_tag_script(tag: str) -> str:
    normalized = unicodedata.normalize("NFKC", tag)
    has_latin = any(_is_latin(char) for char in normalized)
    has_cjk = any(_is_cjk(char) for char in normalized)
    if has_latin and has_cjk:
        return "mixed"
    if has_cjk:
        return "cjk"
    if has_latin:
        return "latin"
    return "other"


def _is_latin(char: str) -> bool:
    try:
        return "LATIN" in unicodedata.name(char)
    except ValueError:
        return False


def _is_cjk(char: str) -> bool:
    codepoint = ord(char)
    return (
        0x4E00 <= codepoint <= 0x9FFF
        or 0x3400 <= codepoint <= 0x4DBF
        or 0x3040 <= codepoint <= 0x309F
        or 0x30A0 <= codepoint <= 0x30FF
        or 0xAC00 <= codepoint <= 0xD7AF
    )


def _is_kana_only_token(value: str) -> bool:
    has_han_or_hangul = any(_is_han(char) or _is_hangul(char) for char in value)
    has_kana = any(_is_hiragana(char) or _is_katakana(char) for char in value)
    return not has_han_or_hangul and has_kana


def _is_han(char: str) -> bool:
    codepoint = ord(char)
    return 0x4E00 <= codepoint <= 0x9FFF or 0x3400 <= codepoint <= 0x4DBF


def _is_hiragana(char: str) -> bool:
    return 0x3040 <= ord(char) <= 0x309F


def _is_katakana(char: str) -> bool:
    return 0x30A0 <= ord(char) <= 0x30FF


def _is_hangul(char: str) -> bool:
    return 0xAC00 <= ord(char) <= 0xD7AF
