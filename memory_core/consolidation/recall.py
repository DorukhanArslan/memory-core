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

import hashlib
import re
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from memory_core.bootstrap._js import js_i_pattern, js_trim
from memory_core.config import MemoryConfig
from memory_core.consolidation._util import (
    clamp_score,
    hash_query,
    iso_ms,
    normalize_snippet,
    to_int,
    write_json_atomic,
)
from memory_core.consolidation.concepts import derive_concept_tags
from memory_core.consolidation.markers import contains_promotion_marker
from memory_core.consolidation.origins import MemoryEntryOrigin, MemoryEntryOriginLedger
from memory_core.consolidation.store import (
    normalize_phase_signal_entry,
    phase_signal_store_path,
    read_phase_signal_store,
    read_recall_store,
    recall_store_lock,
    recall_store_path,
    truncate_short_term_snippet,
    write_recall_store,
)

DREAMING_SIGNAL_PHASES = frozenset({"light", "rem"})

_DREAMING_TRANSCRIPT_PROMPT_LINE_RE = re.compile(
    js_i_pattern(
        r"\[[^\]]*dreaming-narrative[^\]]*]\s*(?:User|Assistant):\s*"
        r"Write a dream diary entry from these memory fragments:?"
    )
)
_RAW_SESSION_METADATA_RE = re.compile(
    js_i_pattern(
        r"\bSession Key\b.{0,260}\bSession ID\b|\bSession ID\b.{0,260}\bSession Key\b"
    )
)
_RAW_CONVERSATION_SUMMARY_RE = re.compile(js_i_pattern(r"^(?:[-*+]\s*)?Conversation Summary:"))
_RAW_TRANSCRIPT_TURN_RE = re.compile(js_i_pattern(r"^(?:[-*+]\s*)?(?:user|assistant):\s"))
_MEMORY_FLUSH_PROMPT_RE = re.compile(
    js_i_pattern(
        r"Save important context from this session to the daily memory file\.\s*STRICT RULES:"
    )
)
_PROMOTION_SCORE_METADATA_RE = re.compile(
    js_i_pattern(
        r"\[\s*score=\d+(?:\.\d+)?\s+(?:signals=\d+\s+)?recalls=\d+\s+avg=\d+(?:\.\d+)?"
        r"\s+source=memory/"
    )
)
_DREAMING_DIFF_PREFIX_RE = re.compile(js_i_pattern(r"@@\s*-\d+(?:,\d+)?\s+[-*+]\s+"))


def is_workspace_contained_path(workspace_dir: Path, relative_path: str) -> bool:
    """True when ``relative_path`` has no ``..`` segment and resolves inside ``workspace_dir``.

    memory-core hardening without an upstream counterpart (upstream's
    ``isShortTermMemoryPath`` accepts ``memory/../..`` paths and rehydration
    resolves them as given): a hit path must not reach another subject's or the
    agent's workspace (``SubjectConsolidation``, decision Q16).
    """
    normalized = relative_path.replace("\\", "/")
    if ".." in normalized.split("/") or PurePosixPath(normalized).is_absolute():
        return False
    root = workspace_dir.resolve()
    return (root / normalized).resolve().is_relative_to(root)


# short-term-promotion-utils.ts at v2026.9.6.
_SHORT_TERM_PATH_RE = re.compile(r"(?:^|/)memory/(?:[^/]+/)*\d{4}-\d{2}-\d{2}(?:-[^/]+)?\.md")
_DREAMING_MEMORY_PATH_RE = re.compile(r"(?:^|/)memory/dreaming/")
_SESSION_CORPUS_PATH_RE = re.compile(
    r"(?:^|/)memory/\.dreams/session-corpus/\d{4}-\d{2}-\d{2}\.(?:md|txt)"
)
_SHORT_TERM_BASENAME_RE = re.compile(r"\d{4}-\d{2}-\d{2}(?:-[^/]+)?\.md")
MAX_QUERY_HASHES = 32
MAX_RECALL_DAYS = 16
_PROVENANCE_PRIORITY = ("owner", "agent", "system", "untrusted")


def normalize_memory_path(raw_path: str) -> str:
    """``normalizeMemoryPath``."""
    text = raw_path.replace("\\", "/")
    return text[2:] if text.startswith("./") else text


def is_short_term_session_corpus_path(file_path: str) -> bool:
    return _SESSION_CORPUS_PATH_RE.search(normalize_memory_path(file_path)) is not None


def is_short_term_memory_path(file_path: str) -> bool:
    """``isShortTermMemoryPath``: a dated daily file (any depth, optional suffix) or a corpus file."""
    normalized = normalize_memory_path(file_path)
    if _DREAMING_MEMORY_PATH_RE.search(normalized):
        return False
    if _SHORT_TERM_PATH_RE.search(normalized) and re.search(
        r"\.md\Z", normalized
    ):
        return True
    if _SESSION_CORPUS_PATH_RE.search(normalized):
        return True
    return _SHORT_TERM_BASENAME_RE.fullmatch(normalized) is not None


def build_claim_hash(snippet: str) -> str:
    """``buildClaimHash``: SHA-1 of the normalized snippet, 12 hex characters."""
    return hashlib.sha1(normalize_snippet(snippet).encode("utf-8", "surrogatepass")).hexdigest()[:12]


def build_daily_claim_entry_key(claim_hash: str) -> str:
    return f"memory:claim:{claim_hash}"


def build_entry_key(
    *, path: str, start_line: int, end_line: int, source: str, claim_hash: str | None = None
) -> str:
    """``buildEntryKey``: ``<source>:<path>:<start>:<end>`` plus the claim hash when given."""
    base = f"{source}:{normalize_memory_path(path)}:{start_line}:{end_line}"
    return f"{base}:{claim_hash}" if claim_hash else base


def merge_recent_distinct(existing: list[str], next_value: str, limit: int) -> list[str]:
    """``mergeRecentDistinct``: distinct non-empty values, the newest ``limit`` kept."""
    seen: set[str] = set()
    merged = []
    for value in existing:
        if isinstance(value, str) and value and value not in seen:
            seen.add(value)
            merged.append(value)
    if next_value and next_value not in merged:
        merged.append(next_value)
    return merged if len(merged) <= limit else merged[len(merged) - limit :]


def normalize_iso_day(iso_like: object) -> str | None:
    """``normalizeIsoDay``: the leading ``YYYY-MM-DD`` of a timestamp, else ``None``."""
    if not isinstance(iso_like, str):
        return None
    match = re.match(r"(\d{4}-\d{2}-\d{2})", iso_like.strip())
    return match.group(1) if match else None


def normalize_project_key_list(value: object) -> str | None:
    """``normalizeProjectKeyList``: ``; `` separated project keys, host part lower-cased."""
    if not isinstance(value, str):
        return None
    keys: dict[str, None] = {}
    for raw_key in value.split(";"):
        key = js_trim(raw_key)
        if not key or re.search(r"[\r\n<>]", key):
            continue
        if key.startswith("path:"):
            keys[key] = None
            continue
        separator = key.find("/")
        if separator < 1:
            keys[key] = None
            continue
        # The remote path keeps its case: folding paths could cross-inject memory between
        # distinct repositories on a case-sensitive host.
        keys[key[:separator].lower() + key[separator:]] = None
    return "; ".join(keys) if keys else None


def merge_project_key_lists(*values: object) -> str | None:
    parts: list[str] = []
    for value in values:
        normalized = normalize_project_key_list(value)
        if normalized:
            parts.extend(normalized.split(";"))
    return normalize_project_key_list(";".join(parts))


def merge_recall_provenance(existing: dict | None, incoming: dict) -> dict:
    """``mergeRecallProvenance``: the least trusted origin wins, unequal session kinds read unknown."""
    if not existing:
        return incoming
    origin = "untrusted"
    for candidate in _PROVENANCE_PRIORITY:
        if candidate in (existing.get("originClass"), incoming.get("originClass")):
            origin = candidate
    merged = {
        "originClass": origin,
        "sessionKind": incoming["sessionKind"]
        if existing.get("sessionKind") == incoming.get("sessionKind")
        else "unknown",
        "observedAt": max(existing.get("observedAt", 0), incoming.get("observedAt", 0)),
    }
    if existing.get("supersedesKey") and existing.get("supersedesKey") == incoming.get("supersedesKey"):
        merged["supersedesKey"] = existing["supersedesKey"]
    return merged


def record_short_term_recalls(
    *,
    config: MemoryConfig,
    query: str,
    results: list[dict[str, Any]],
    now_ms: int,
    signal_type: str = "recall",
    dedupe_by_query_per_day: bool = False,
    day_bucket: str | None = None,
    timezone: str | None = None,
    origins: MemoryEntryOriginLedger | None = None,
) -> int:
    """Record ``memory_search`` hits as short-term recall signals (``recordShortTermRecalls``).

    A hit whose ``source`` is memory and whose path is a dated daily file (or a session-corpus
    file) becomes one entry keyed by its range (``memory:<path>:<start>:<end>``), or by its claim
    hash once daily ingestion has made the claim canonical. The entry carries the signal counts
    (``recallCount`` for ``recall``, ``dailyCount`` for ``daily``, ``groundedCount`` for
    ``grounded``), scores, query hashes (``userQueryHashes`` only for interactive recalls),
    recall days in the dreaming timezone, concept tags, merged provenance and the claim hash.
    Contaminated dreaming snippets are skipped. A path outside the workspace is skipped (a
    memory-core hardening). Returns the number of entries written. Not ported: the
    ``memory.recall.*`` host events.

    Session lineage (``recordShortTermRecalls``, short-term-promotion-record.ts:370): a hit may
    carry ``sessionOrigin`` (``agentId``, ``sessionId``, optional ``sessionKey``), the session
    transcript it came from. Under the workspace lock, hits of a tombstoned (forgotten) session
    are dropped; every other entry written records one ``memory_entry_origins`` row per source
    session (its ``provenance`` origin class and ``observedAt``) in ``origins`` *before* the
    recall store is published, so a failed ledger write leaves no staged entry without its
    lineage. Without an ``origins`` ledger ``sessionOrigin`` is ignored (upstream always has the
    agent database).
    """
    from memory_core.consolidation.promotion import format_memory_dreaming_day

    query = js_trim(query)
    if not query:
        return 0
    memory_results = [r for r in results if r.get("source", "memory") == "memory"]
    relevant = [r for r in memory_results if is_short_term_memory_path(str(r.get("path") or ""))]
    if not relevant:
        return 0
    store_path = recall_store_path(config.workspace_dir)
    now_iso = iso_ms(now_ms)
    today_bucket = format_memory_dreaming_day(now_ms, timezone)
    changed = 0
    source_sessions: dict[str, set[str]] = {}
    if origins is not None:
        for result in relevant:
            session_origin = _session_origin(result)
            if session_origin is not None:
                source_sessions.setdefault(session_origin["agentId"], set()).add(session_origin["sessionId"])
    with recall_store_lock(config.workspace_dir):
        store = read_recall_store(store_path, now_ms)
        entries = store["entries"]
        if origins is not None and source_sessions:
            # Revalidate under the lock: a forget can finish while transcripts were being scanned.
            forgotten = {
                agent: {t.session_id for t in origins.list_session_tombstones(agent, sorted(ids))}
                for agent, ids in source_sessions.items()
            }
            relevant = [
                result
                for result in relevant
                if (so := _session_origin(result)) is None or so["sessionId"] not in forgotten.get(so["agentId"], ())
            ]
            if not relevant:
                return 0
        origin_rows: list[MemoryEntryOrigin] = []
        for result in relevant:
            normalized_path = normalize_memory_path(str(result.get("path") or ""))
            if not is_workspace_contained_path(config.workspace_dir, normalized_path):
                continue
            raw_snippet = normalize_snippet(str(result.get("snippet") or ""))
            snippet = truncate_short_term_snippet(raw_snippet)
            start_line = to_int(result.get("startLine"), 1)
            end_line = to_int(result.get("endLine"), start_line)
            if not raw_snippet or (
                signal_type == "grounded"
                and not (
                    isinstance(result.get("startLine"), int | float)
                    and isinstance(result.get("endLine"), int | float)
                )
            ):
                continue
            if is_contaminated_dreaming_snippet(
                raw_snippet,
                allow_transcript_turn_snippet=signal_type != "grounded"
                and is_short_term_session_corpus_path(normalized_path),
            ):
                continue
            identity_snippet = (
                normalize_snippet(str(result.get("identitySnippet") or raw_snippet))
                if signal_type == "daily"
                else raw_snippet
            )
            claim_hash = build_claim_hash(identity_snippet)
            non_daily_entry = None
            if signal_type == "daily":
                for entry in entries.values():
                    if (
                        not str(entry.get("key", "")).startswith("memory:claim:")
                        and max(0, to_int(entry.get("recallCount"), 0))
                        + max(0, to_int(entry.get("groundedCount"), 0))
                        > 0
                        and entry.get("claimHash") == claim_hash
                    ):
                        non_daily_entry = entry
                        break
            range_start = max(1, start_line)
            range_end = max(1, end_line)
            claim_key = (
                build_daily_claim_entry_key(claim_hash)
                if signal_type == "daily"
                else build_entry_key(
                    path=normalized_path,
                    start_line=range_start,
                    end_line=range_end,
                    source="memory",
                    claim_hash=claim_hash,
                )
            )
            daily_claim_entry = (
                None if signal_type == "daily" else entries.get(build_daily_claim_entry_key(claim_hash))
            )
            if non_daily_entry is not None:
                key = non_daily_entry["key"]
            elif daily_claim_entry is not None:
                key = daily_claim_entry["key"]
            elif signal_type != "recall" or claim_key in entries:
                key = claim_key
            else:
                key = build_entry_key(
                    path=normalized_path, start_line=start_line, end_line=end_line, source="memory"
                )
            existing = entries.get(key)
            score = clamp_score(float(result.get("score") or 0))
            effective_query = (
                normalize_snippet(str(result.get("query") or query)) or query
                if signal_type == "grounded"
                else query
            )
            query_hash = hash_query(effective_query.lower().strip())
            day = (
                normalize_iso_day(
                    (result.get("dayBucket") if signal_type == "grounded" else None)
                    or day_bucket
                    or ""
                )
                or today_bucket
            )
            signal_count = (
                max(1, int(float(result.get("signalCount") or 1))) if signal_type == "grounded" else 1
            )
            recall_days_base = list((existing or {}).get("recallDays") or [])
            query_hashes_base = list((existing or {}).get("queryHashes") or [])
            dedupe_signal = (
                dedupe_by_query_per_day
                and query_hash in query_hashes_base
                and day in recall_days_base
            )
            added = 0 if dedupe_signal else signal_count
            prior = existing or {}
            recall_count = max(0, to_int(prior.get("recallCount"), 0) + (added if signal_type == "recall" else 0))
            daily_count = max(0, to_int(prior.get("dailyCount"), 0) + (added if signal_type == "daily" else 0))
            grounded_count = max(0, to_int(prior.get("groundedCount"), 0) + (added if signal_type == "grounded" else 0))
            total_score = max(0.0, float(prior.get("totalScore") or 0) + score * added)
            max_score = max(float(prior.get("maxScore") or 0), 0.0 if dedupe_signal else score)
            query_hashes = merge_recent_distinct(query_hashes_base, query_hash, MAX_QUERY_HASHES)
            user_query_hashes = (
                merge_recent_distinct(list(prior.get("userQueryHashes") or []), query_hash, MAX_QUERY_HASHES)
                if signal_type == "recall"
                else prior.get("userQueryHashes")
            )
            recall_days = merge_recent_distinct(recall_days_base, day, MAX_RECALL_DAYS)
            concept_tags = derive_concept_tags(normalized_path, snippet)
            # Workspace-file hits without explicit provenance keep the index's agent default.
            source_provenance = result.get("provenance") or {
                "originClass": "agent",
                "sessionKind": "unknown",
                "observedAt": now_ms,
            }
            provenance = merge_recall_provenance(prior.get("provenance"), source_provenance)
            project_key = merge_project_key_lists(prior.get("projectKey"), result.get("projectKey"))
            unchanged_repeat = (
                (dedupe_by_query_per_day or signal_type == "daily")
                and query_hash in query_hashes_base
                and prior.get("snippet") == snippet
            )
            last_recalled_at = (
                prior.get("lastRecalledAt") or now_iso if unchanged_repeat else now_iso
            )
            preserve_first_daily_source = existing is not None and (
                signal_type == "daily" or daily_claim_entry is not None
            )
            entry = {
                "key": key,
                "path": prior["path"] if preserve_first_daily_source else normalized_path,
                "startLine": prior["startLine"] if preserve_first_daily_source else range_start,
                "endLine": prior["endLine"] if preserve_first_daily_source else range_end,
                "source": "memory",
                "snippet": snippet or prior.get("snippet") or "",
                "recallCount": recall_count,
                "dailyCount": daily_count,
                "groundedCount": grounded_count,
                "totalScore": total_score,
                "maxScore": max_score,
                "firstRecalledAt": prior.get("firstRecalledAt") or now_iso,
                "lastRecalledAt": last_recalled_at,
                "queryHashes": query_hashes,
            }
            if user_query_hashes is not None:
                entry["userQueryHashes"] = user_query_hashes
            entry["recallDays"] = recall_days
            entry["conceptTags"] = concept_tags or list(prior.get("conceptTags") or [])
            entry["provenance"] = provenance
            entry["claimHash"] = claim_hash
            if project_key:
                entry["projectKey"] = project_key
            if prior.get("promotedAt"):
                entry["promotedAt"] = prior["promotedAt"]
            entries[key] = entry
            changed += 1
            session_origin = _session_origin(result) if origins is not None else None
            if session_origin is not None:
                origin_rows.append(
                    MemoryEntryOrigin(
                        entry_key=key,
                        agent_id=session_origin["agentId"],
                        session_id=session_origin["sessionId"],
                        session_key=session_origin.get("sessionKey"),
                        origin_class=source_provenance["originClass"],
                        observed_at=source_provenance["observedAt"],
                    )
                )
        if origins is not None:
            # Reserve lineage before publishing the entries.
            for agent in source_sessions:
                origins.record(agent, [row for row in origin_rows if row.agent_id == agent])
        store["updatedAt"] = now_iso
        write_recall_store(store_path, store)
    return changed


def _session_origin(result: Mapping[str, Any]) -> dict[str, Any] | None:
    """The ``sessionOrigin`` of a hit when it names an agent and a session, else ``None``."""
    origin = result.get("sessionOrigin")
    if not isinstance(origin, Mapping):
        return None
    agent_id, session_id = origin.get("agentId"), origin.get("sessionId")
    if not isinstance(agent_id, str) or not isinstance(session_id, str):
        return None
    session_key = origin.get("sessionKey")
    return {
        "agentId": agent_id,
        "sessionId": session_id,
        **({"sessionKey": session_key} if isinstance(session_key, str) else {}),
    }


def record_grounded_short_term_candidates(
    *,
    config: MemoryConfig,
    query: str,
    items: list[dict[str, Any]],
    now_ms: int,
    dedupe_by_query_per_day: bool = False,
    day_bucket: str | None = None,
    timezone: str | None = None,
    origins: MemoryEntryOriginLedger | None = None,
) -> int:
    """``recordGroundedShortTermCandidates``: grounded backfill signals (never interactive recalls)."""
    return record_short_term_recalls(
        config=config,
        query=query,
        results=[{**item, "source": "memory"} for item in items],
        now_ms=now_ms,
        signal_type="grounded",
        dedupe_by_query_per_day=dedupe_by_query_per_day,
        day_bucket=day_bucket,
        timezone=timezone,
        origins=origins,
    )


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


def undecorate_search_results(results: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return ``memory_search`` hits without the citation suffix of their snippets.

    ``memory_core.tools.memory_search`` appends ``"\n\nSource: <path>#L<a>-L<b>"`` to each
    snippet when citations are on (upstream ``decorateCitations``); upstream
    records the raw hits (``tools.ts`` ``queueShortTermRecallTracking``), so the
    suffix is removed before recording.
    """
    undecorated = []
    for result in results:
        item = dict(result)
        snippet = item.get("snippet")
        citation = item.get("citation")
        if isinstance(snippet, str) and isinstance(citation, str) and citation:
            suffix = f"\n\n{citation}"
            if snippet.endswith(suffix):
                item["snippet"] = snippet[: -len(suffix)]
        undecorated.append(item)
    return undecorated


def is_contaminated_dreaming_snippet(raw: str, *, allow_transcript_turn_snippet: bool = False) -> bool:
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
        or (not allow_transcript_turn_snippet and _RAW_TRANSCRIPT_TURN_RE.match(snippet))
        or _MEMORY_FLUSH_PROMPT_RE.search(snippet)
        or _PROMOTION_SCORE_METADATA_RE.search(snippet)
    ):
        return True
    has_status = re.search(js_i_pattern(r"\bstatus:\s*staged\b"), snippet) is not None
    has_recalls = re.search(js_i_pattern(r"\brecalls:\s*\d+\b"), snippet) is not None
    has_reflection_note = re.search(js_i_pattern(r"\bnote:\s*reflection\b"), snippet) is not None
    return (
        _has_dreaming_narrative_lead(snippet)
        and re.search(js_i_pattern(r"\bconfidence:\s*\d"), snippet) is not None
        and re.search(
            js_i_pattern(r"\bevidence:\s*(?:memory/\.dreams/session-corpus/|memory/)"),
            snippet,
        )
        is not None
        and ((has_status and has_recalls) or has_reflection_note)
    )


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
    if re.match(js_i_pattern(r"^(?:Candidate|Reflections?):"), without_prefix):
        return True
    head = without_prefix[:200]
    return (
        re.search(js_i_pattern(r"\b(?:Candidate|Reflections?):"), head) is not None
        or re.search(js_i_pattern(r"#{1,6}\s+Reflections?\b"), head) is not None
    )
