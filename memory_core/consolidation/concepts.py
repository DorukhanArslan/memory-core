"""Concept tags for short-term recall entries.

Port of ``extensions/memory-core/src/concept-vocabulary.ts`` (``deriveConceptTags``,
its stop-word sets, protected glossary and script classification) at OpenClaw
pin 4c42815348. The oracle operation ``deriveConceptTags`` compares these tags
with the real TypeScript function.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from memory_core._icu import character_category, lowercase, normalize_nfkc, script_name, word_tokens
from memory_core.bootstrap._js import js_trim, utf16_len

MAX_CONCEPT_TAGS = 8


def _normalize_lowercase_string(value: str) -> str:
    return lowercase(js_trim(value))


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
    _normalize_lowercase_string(normalize_nfkc(word))
    for word in _PROTECTED_GLOSSARY
]



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
    for raw_token in _collect_compound_tokens(source) + word_tokens(source):
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
        if (not before or not _is_letter_or_number(before)) and (not after or not _is_letter_or_number(after)):
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
    normalized_source = _normalize_lowercase_string(normalize_nfkc(source))
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


def _is_letter_or_number(char: str) -> bool:
    category = character_category(char)
    return 1 <= category <= 5 or 9 <= category <= 11


def _collect_compound_tokens(source: str) -> list[str]:
    # /[\p{L}\p{N}]+(?:[._/-][\p{L}\p{N}]+)+/gu on the pinned Unicode data.
    found = []
    index = 0
    while index < len(source):
        if not _is_letter_or_number(source[index]):
            index += 1
            continue
        start = index
        compound = False
        while index < len(source) and _is_letter_or_number(source[index]):
            index += 1
            if (index + 1 < len(source) and source[index] in "._/-"
                    and _is_letter_or_number(source[index + 1])):
                compound = True
                index += 1
        if compound:
            found.append(source[start:index])
    return found


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
        _strip_non_alnum_edges(normalize_nfkc(raw_token)).replace("_", "-")
    )
    if not normalized or not any(_is_letter_or_number(char) for char in normalized) or utf16_len(normalized) > 32:
        return None
    if _is_numeric_compound(normalized) or re.fullmatch(
        r"\d{4}-\d{2}-\d{2}\.[^\W_]+", normalized, re.UNICODE
    ):
        return None
    script = _classify_concept_tag_script(normalized)
    # Glossary entries are an explicit allowlist of short technical terms
    # (e.g. "kv", "s3"); they bypass the per-script minimum length gate.
    if (
        not from_glossary
        and normalized not in _PROTECTED_GLOSSARY
        and utf16_len(normalized) < _minimum_token_length_for_script(script)
    ):
        return None
    if _is_kana_only_token(normalized) and utf16_len(normalized) < 3:
        return None
    if normalized in _CONCEPT_STOP_WORDS:
        return None
    return normalized


def _is_numeric_compound(value: str) -> bool:
    """``/^\\p{N}+(?:[./-]\\p{N}+)*$/u``: numbers, dates and versions are not concepts."""
    return bool(value) and all(
        part and all(9 <= character_category(char) <= 11 for char in part)
        for part in re.split(r"[./-]", value)
    )


def _strip_non_alnum_edges(value: str) -> str:
    start = 0
    end = len(value)
    while start < end and not _is_letter_or_number(value[start]):
        start += 1
    while end > start and not _is_letter_or_number(value[end - 1]):
        end -= 1
    return value[start:end]


def _classify_concept_tag_script(tag: str) -> str:
    normalized = normalize_nfkc(tag)
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
    return script_name(char) == b"Latn"


def _is_cjk(char: str) -> bool:
    return script_name(char) in {b"Hani", b"Hira", b"Kana", b"Hang"}


def _is_kana_only_token(value: str) -> bool:
    scripts = {script_name(char) for char in value}
    return not scripts.intersection({b"Hani", b"Hang"}) and bool(scripts.intersection({b"Hira", b"Kana"}))
