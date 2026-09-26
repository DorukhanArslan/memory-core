"""Record short-term recall and dreaming signals into the recall stores.

Ports from ``extensions/memory-core/src/short-term-promotion.ts`` at OpenClaw
pin 4c42815348: ``recordShortTermRecalls`` (memory_search hits under
``memory/`` become recall entries), the daily-flush signal variant
(``signalType: "daily"``), ``recordDreamingPhaseSignals`` (light/REM hits) and
``isContaminatedDreamingSnippet`` (dream diary, transcript and promotion
scaffolding never becomes a recall entry).

Known gaps, unchanged from the demo pipeline: snippets are split per line into
single-line entries, recall days use the UTC date rather than the dreaming
timezone, ``dedupeByQueryPerDay``/``claimHash`` grounding and the
``memory.recall.*`` host events are not ported.
"""

from __future__ import annotations

import re
from typing import Any

from memory_core.config import MemoryConfig
from memory_core.consolidation._util import (
    append_distinct,
    clamp_score,
    hash_query,
    iso_ms,
    normalize_snippet,
    to_int,
    write_json_atomic,
)
from memory_core.consolidation.concepts import derive_concept_tags
from memory_core.consolidation.markers import contains_promotion_marker
from memory_core.consolidation.store import (
    normalize_phase_signal_entry,
    phase_signal_store_path,
    read_phase_signal_store,
    read_recall_store,
    recall_store_path,
    truncate_short_term_snippet,
    write_recall_store,
)

DREAMING_SIGNAL_PHASES = frozenset({"light", "rem"})

_DREAMING_TRANSCRIPT_PROMPT_LINE_RE = re.compile(
    r"\[[^\]]*dreaming-narrative[^\]]*]\s*(?:User|Assistant):\s*"
    r"Write a dream diary entry from these memory fragments:?",
    re.IGNORECASE,
)
_RAW_SESSION_METADATA_RE = re.compile(
    r"\bSession Key\b.{0,260}\bSession ID\b|\bSession ID\b.{0,260}\bSession Key\b",
    re.IGNORECASE,
)
_RAW_CONVERSATION_SUMMARY_RE = re.compile(r"^(?:[-*+]\s*)?Conversation Summary:", re.IGNORECASE)
_RAW_TRANSCRIPT_TURN_RE = re.compile(r"^(?:[-*+]\s*)?(?:user|assistant):\s", re.IGNORECASE)
_MEMORY_FLUSH_PROMPT_RE = re.compile(
    r"Save important context from this session to the daily memory file\.\s*STRICT RULES:",
    re.IGNORECASE,
)
_PROMOTION_SCORE_METADATA_RE = re.compile(
    r"\[\s*score=\d+(?:\.\d+)?\s+recalls=\d+\s+avg=\d+(?:\.\d+)?\s+source=memory/",
    re.IGNORECASE,
)
_DREAMING_DIFF_PREFIX_RE = re.compile(r"@@\s*-\d+(?:,\d+)?\s+[-*+]\s+", re.IGNORECASE)


def record_short_term_recalls(
    *,
    config: MemoryConfig,
    query: str,
    results: list[dict[str, Any]],
    now_ms: int,
    signal_type: str = "recall",
) -> int:
    """Record ``memory_search`` hits as short-term recall signals.

    Only hits whose ``path`` is ``memory/*.md`` count. Each non-heading line of
    a hit's snippet becomes the entry ``memory:<path>:<line>:<line>``; its
    ``recallCount`` (or ``dailyCount`` when ``signal_type == "daily"``),
    scores, query hashes (max 32), recall days (max 16) and concept tags are
    updated. Contaminated dreaming snippets are skipped. Returns the number of
    entries touched; the store is rewritten when any memory hit was seen.
    """
    store_path = recall_store_path(config.workspace_dir)
    store = read_recall_store(store_path, now_ms)
    now_iso = iso_ms(now_ms)
    query_hash = hash_query(query.lower().strip())
    changed = 0
    touched = False
    for result in results:
        path = str(result.get("path") or "")
        if not path.startswith("memory/") or not path.endswith(".md"):
            continue
        touched = True
        start_line = to_int(result.get("startLine"), 1)
        score = clamp_score(float(result.get("score") or 0))
        for line_number, raw_snippet in candidate_lines(
            raw=str(result.get("snippet") or ""), start_line=start_line
        ):
            if is_contaminated_dreaming_snippet(raw_snippet):
                continue
            snippet = truncate_short_term_snippet(raw_snippet)
            key = f"memory:{path}:{line_number}:{line_number}"
            entry = store["entries"].get(key)
            if entry is None:
                entry = {
                    "key": key,
                    "path": path,
                    "startLine": line_number,
                    "endLine": line_number,
                    "source": "memory",
                    "snippet": snippet,
                    "recallCount": 0,
                    "dailyCount": 0,
                    "groundedCount": 0,
                    "totalScore": 0.0,
                    "maxScore": 0.0,
                    "firstRecalledAt": now_iso,
                    "lastRecalledAt": now_iso,
                    "queryHashes": [],
                    "recallDays": [],
                    "conceptTags": derive_concept_tags(path, snippet),
                }
                store["entries"][key] = entry
            entry["totalScore"] = float(entry.get("totalScore") or 0) + score
            entry["maxScore"] = max(float(entry.get("maxScore") or 0), score)
            entry["lastRecalledAt"] = now_iso
            entry["conceptTags"] = entry.get("conceptTags") or derive_concept_tags(path, snippet)
            entry["queryHashes"] = append_distinct(
                list(entry.get("queryHashes") or []), query_hash, 32
            )
            entry["recallDays"] = append_distinct(
                list(entry.get("recallDays") or []), now_iso[:10], 16
            )
            if signal_type == "daily":
                entry["dailyCount"] = to_int(entry.get("dailyCount"), 0) + 1
            else:
                entry["recallCount"] = to_int(entry.get("recallCount"), 0) + 1
            changed += 1
    if changed or touched:
        store["updatedAt"] = now_iso
        write_recall_store(store_path, store)
    return changed


def record_short_term_phase_signals(
    *,
    config: MemoryConfig,
    keys: list[str],
    phase: str,
    now_ms: int,
) -> int:
    """Count a light or REM dreaming hit for each recall key; returns keys recorded.

    Raises ``ValueError`` for any phase other than ``"light"`` or ``"rem"``.
    """
    if phase not in DREAMING_SIGNAL_PHASES:
        raise ValueError(f"unsupported dreaming phase: {phase}")
    path = phase_signal_store_path(config.workspace_dir)
    store = read_phase_signal_store(path, now_ms)
    now_iso = iso_ms(now_ms)
    changed = 0
    for key in keys:
        if not key:
            continue
        entry = normalize_phase_signal_entry(key, store["entries"].get(key))
        if phase == "light":
            entry["lightHits"] += 1
            entry["lastLightAt"] = now_iso
        else:
            entry["remHits"] += 1
            entry["lastRemAt"] = now_iso
        entry["updatedAt"] = now_iso
        store["entries"][key] = entry
        changed += 1
    if changed:
        store["updatedAt"] = now_iso
        write_json_atomic(path, store)
    return changed


def record_daily_memory_flush(
    *,
    config: MemoryConfig,
    target: str,
    entry: str,
    now_ms: int,
) -> int:
    """Record a daily-flush write as ``daily`` signals for the lines it added.

    ``target`` must be an existing ``memory/*.md`` file; each non-heading line
    of ``entry`` found verbatim (whitespace-normalized) in it counts once.
    """
    if not target.startswith("memory/") or not target.endswith(".md"):
        return 0
    path = config.workspace_dir / target
    if not path.exists():
        return 0
    file_lines = path.read_text(encoding="utf-8").splitlines()
    results = []
    for _, snippet in candidate_lines(entry, 1):
        line_number = _find_line_number(file_lines, snippet)
        if line_number is None:
            continue
        results.append(
            {
                "path": target,
                "startLine": line_number,
                "endLine": line_number,
                "snippet": snippet,
                "score": 1,
            }
        )
    return record_short_term_recalls(
        config=config,
        query=entry,
        results=results,
        now_ms=now_ms,
        signal_type="daily",
    )


def is_contaminated_dreaming_snippet(raw: str) -> bool:
    """True for snippets that are pipeline scaffolding rather than memory content.

    Port of ``isContaminatedDreamingSnippet``: promotion markers and score
    metadata, dream-diary prompts, raw session metadata, conversation
    summaries, transcript turns, the memory-flush prompt, and staged
    ``Candidate:``/``Reflections:`` narrative lines with confidence, evidence,
    status and recall fields.
    """
    snippet = normalize_snippet(raw)
    if not snippet:
        return False
    if contains_promotion_marker(snippet):
        return True
    if _DREAMING_TRANSCRIPT_PROMPT_LINE_RE.search(snippet):
        return True
    if (
        _RAW_SESSION_METADATA_RE.search(snippet)
        or _RAW_CONVERSATION_SUMMARY_RE.match(snippet)
        or _RAW_TRANSCRIPT_TURN_RE.match(snippet)
        or _MEMORY_FLUSH_PROMPT_RE.search(snippet)
        or _PROMOTION_SCORE_METADATA_RE.search(snippet)
    ):
        return True
    return (
        _has_dreaming_narrative_lead(snippet)
        and re.search(r"\bconfidence:\s*\d", snippet, re.IGNORECASE) is not None
        and re.search(
            r"\bevidence:\s*(?:memory/\.dreams/session-corpus/|memory/)",
            snippet,
            re.IGNORECASE,
        )
        is not None
        and re.search(r"\bstatus:\s*staged\b", snippet, re.IGNORECASE) is not None
        and re.search(r"\brecalls:\s*\d+\b", snippet, re.IGNORECASE) is not None
    )


def candidate_lines(raw: str, start_line: int) -> list[tuple[int, str]]:
    """Split a snippet into ``(line_number, normalized_line)`` pairs, skipping headings."""
    candidates = []
    for offset, line in enumerate(raw.splitlines()):
        snippet = normalize_snippet(line)
        if not snippet or snippet.startswith("#"):
            continue
        candidates.append((start_line + offset, snippet))
    if candidates:
        return candidates
    snippet = normalize_snippet(raw)
    return [(start_line, snippet)] if snippet else []


def _find_line_number(lines: list[str], snippet: str) -> int | None:
    normalized = normalize_snippet(snippet)
    for index, line in enumerate(lines, start=1):
        candidate = normalize_snippet(line)
        if candidate == normalized:
            return index
    return None


def _consume_dreaming_lead_prefix(snippet: str) -> str:
    index = 0
    while index < len(snippet):
        diff_match = _DREAMING_DIFF_PREFIX_RE.match(snippet, index)
        if diff_match:
            index = diff_match.end()
            continue
        char = snippet[index]
        if char in "[(":
            index += 1
            while index < len(snippet) and snippet[index] == " ":
                index += 1
            continue
        if char in "-*+>" and index + 1 < len(snippet) and snippet[index + 1] == " ":
            index += 2
            continue
        break
    return snippet[index:]


def _has_dreaming_narrative_lead(snippet: str) -> bool:
    without_prefix = _consume_dreaming_lead_prefix(snippet)
    if re.match(r"^(?:Candidate|Reflections?):", without_prefix, re.IGNORECASE):
        return True
    return (
        re.search(r"\b(?:Candidate|Reflections?):", without_prefix[:200], re.IGNORECASE)
        is not None
    )
