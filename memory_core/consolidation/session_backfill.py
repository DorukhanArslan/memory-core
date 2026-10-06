"""The lineage writes of the session backfill (``extensions/memory-core/src/session-backfill.ts``).

Session backfill ingests old session transcripts into the dreaming pipeline: it stages grounded
recall entries (``applySessionBackfillDays``) and, with ``--rem`` or ``--apply``, writes diary
blocks into DREAMS.md (``buildSessionBackfillDiaryEntries``). Both paths reserve the
``memory_entry_origins`` rows of the sessions they read from before anything is published, so a
later ``memory forget`` of one session can find and purge what came from it.

Ported here are exactly those pieces, with the host owning the transcript scan that produces
:class:`SessionBackfillCandidate` values (upstream: ``scanSessionIngestionSource``):

- :func:`build_session_backfill_diary_entries` (session-backfill.ts:316 ``recordMemoryEntryOrigins``);
- :func:`coalesce_backfill_claims` and :func:`record_session_backfill_day` (the grounded recall
  signals of ``applySessionBackfillDays``, whose origins ledger writes are the ones of
  ``recordShortTermRecalls``, see :func:`memory_core.consolidation.recall.record_short_term_recalls`).

Not ported: the transcript scan, the rewind journal and the CLI plumbing. ``--rem`` needs the REM
evidence preview (``previewGroundedRemForFile``), which memory-core does not have; the host passes
it as ``rem_preview``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from memory_core.bootstrap._js import JS_SPACE_CLASS, js_trim
from memory_core.config import MemoryConfig
from memory_core.consolidation.llm_consolidation import hash_memory_content
from memory_core.consolidation.markers import format_promotion_marker
from memory_core.consolidation.origins import MemoryEntryOrigin, MemoryEntryOriginLedger
from memory_core.consolidation.recall import record_grounded_short_term_candidates
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY, RuntimeIdentity

SESSION_BACKFILL_QUERY_PREFIX = "__dreaming_session_backfill__"
TOP_CANDIDATE_LIMIT = 5
SESSION_INGESTION_SCORE = 0.58

_ROLE_PREFIX_RE = re.compile(r"^(?:assistant|user):[" + JS_SPACE_CLASS + r"]*", re.IGNORECASE | re.ASCII)
_WHITESPACE_RUN_RE = re.compile(f"[{JS_SPACE_CLASS}]+")
_LONE_SURROGATE_RE = re.compile("[\ud800-\udfff]")


@dataclass(frozen=True)
class SessionBackfillCandidate:
    """``SessionIngestionMessage``: one trusted transcript message selected for a day."""

    day: str
    snippet: str
    rendered: str
    # ``{"originClass", "sessionKind", "observedAt"}`` (``MemorySearchResult["provenance"]``).
    provenance: Mapping[str, Any]
    # ``{"agentId", "sessionId", optional "sessionKey"}``.
    session_origin: Mapping[str, Any] | None = None


def _json_stringify(value: Any) -> str:
    """``JSON.stringify`` of a plain value: well-formed (lone surrogates escaped), no spaces."""
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return _LONE_SURROGATE_RE.sub(lambda m: f"\\u{ord(m.group()):04x}", text)


def session_backfill_entry_key(day: str, line: str) -> str:
    """The key of a diary block: identical day/text blocks share it, so one marker holds every source."""
    return f"memory:session-backfill:{hash_memory_content(_json_stringify([day, line]))}"


def build_session_backfill_diary_entries(
    *,
    ledger: MemoryEntryOriginLedger,
    agent_id: str,
    days: Sequence[tuple[str, Sequence[SessionBackfillCandidate]]],
    rem_preview: Callable[[str, str, Callable[[str, Sequence[str]], str]], str | None] | None = None,
    identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> list[dict[str, Any]]:
    """``buildSessionBackfillDiaryEntries``: diary blocks (``isoDay``, ``sourcePath``, ``bodyLines``).

    Every block line is preceded by a promotion marker keyed by :func:`session_backfill_entry_key`;
    the sessions of each candidate behind the line are recorded in ``ledger`` for ``agent_id``
    *before* this returns (upstream reserves lineage before publication, even when later corpus or
    staging work fails). A candidate whose session belongs to another agent raises ``ValueError``.

    ``rem_preview(rel_path, content, format_item)`` stands for ``previewGroundedRemForFile``
    (``--rem``): it returns the rendered markdown of the REM evidence preview, or ``None`` when it
    found nothing, calling ``format_item(line, refs)`` for each item (``refs`` are
    ``<rel_path>:<start>-<end>`` citations into ``content``). Without it, or when it finds nothing,
    a block is the count line plus the top five snippets.
    """
    origins: list[MemoryEntryOrigin] = []

    def mark_line(day: str, line: str, sources: Sequence[SessionBackfillCandidate]) -> str:
        entry_key = session_backfill_entry_key(day, line)
        for source in sources:
            origin = source.session_origin
            if origin:
                session_key = origin.get("sessionKey")
                origins.append(
                    MemoryEntryOrigin(
                        entry_key=entry_key,
                        agent_id=origin["agentId"],
                        session_id=origin["sessionId"],
                        session_key=session_key if session_key is not None else None,
                        origin_class=source.provenance["originClass"],
                        observed_at=source.provenance["observedAt"],
                    )
                )
        return f"{format_promotion_marker(entry_key, identity)}\n{line}"

    entries: list[dict[str, Any]] = []
    for day, candidates in days:
        body_lines: list[str] | None = None
        if rem_preview is not None:
            rel_path = f"memory/{day}.md"
            content = "## Session transcript\n\n" + "\n".join(c.rendered for c in candidates) + "\n"

            def format_item(line: str, refs: Sequence[str]) -> str:
                matched = []
                for index, candidate in enumerate(candidates):
                    for ref in refs:
                        parts = [_js_number(part) for part in ref[len(rel_path) + 1 :].split("-")]
                        start = parts[0]
                        end = parts[1] if len(parts) > 1 else start
                        # The virtual markdown input has a heading and blank line before its candidates.
                        if start <= index + 3 <= end:
                            matched.append(candidate)
                            break
                return mark_line(day, line, matched)

            rendered = rem_preview(rel_path, content, format_item)
            if rendered is not None:
                body_lines = re.sub(f"^##[{JS_SPACE_CLASS}]+", "", rendered, flags=re.MULTILINE).split("\n")
        if body_lines is None:
            count = len(candidates)
            body_lines = [
                f"Session backfill found {count} trusted candidate{'' if count == 1 else 's'}.",
                *(
                    mark_line(day, f"- {candidate.snippet}", [candidate])
                    for candidate in candidates[:TOP_CANDIDATE_LIMIT]
                ),
            ]
        entries.append(
            {
                "isoDay": day,
                "sourcePath": f"memory/.dreams/session-corpus/{day}.txt",
                "bodyLines": body_lines,
            }
        )
    # Reserve lineage before publication, even when subsequent corpus/staging work fails.
    ledger.record(agent_id, origins)
    return entries


def _js_number(text: str) -> float:
    """``Number(text)`` for the digits of a citation (anything else is ``NaN``, which never matches)."""
    try:
        return float(js_trim(text)) if js_trim(text) else 0.0
    except ValueError:
        return float("nan")


def coalesce_backfill_claims(results: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """``coalesceBackfillClaims``: share the first citation of a claim, keep each source's identity.

    The role prefix (``User:`` / ``Assistant:``) is dropped from the snippet; claims are keyed by
    their whitespace-collapsed lower-case text. Results with an empty snippet are dropped. Each
    returned result keeps its own ``sessionOrigin`` and ``provenance`` so that coalescing a claim
    cannot discard its deletion lineage.
    """
    claims: dict[str, dict[str, Any]] = {}
    coalesced: list[dict[str, Any]] = []
    for result in results:
        snippet = js_trim(_ROLE_PREFIX_RE.sub("", str(result["snippet"]), count=1))
        key = _WHITESPACE_RUN_RE.sub(" ", snippet).lower()
        if not key:
            continue
        claim = claims.get(key)
        if claim is None:
            claim = {
                "path": result["path"],
                "startLine": result["startLine"],
                "endLine": result["endLine"],
                "snippet": snippet,
            }
            claims[key] = claim
        coalesced.append({**result, **claim})
    return coalesced


def record_session_backfill_day(
    *,
    config: MemoryConfig,
    ledger: MemoryEntryOriginLedger,
    day: str,
    results: Sequence[Mapping[str, Any]],
    now_ms: int,
    timezone: str | None = None,
) -> int:
    """The grounded signals of one backfill day (``applySessionBackfillDays``), with lineage.

    ``results`` are the session-corpus hits of the day (``path``, ``startLine``, ``endLine``,
    ``snippet``, ``provenance``, ``sessionOrigin``). They are coalesced, staged as grounded
    short-term candidates (query ``__dreaming_session_backfill__:<day>``, score 0.58, one signal per
    query and day) and their sessions are recorded in ``ledger`` before the recall store is published.
    Hits of a tombstoned session are dropped. Returns the number of entries written.
    """
    grounded = coalesce_backfill_claims(results)
    if not grounded:
        return 0
    return record_grounded_short_term_candidates(
        config=config,
        query=f"{SESSION_BACKFILL_QUERY_PREFIX}:{day}",
        items=[
            {
                "path": result["path"],
                "startLine": result["startLine"],
                "endLine": result["endLine"],
                "snippet": result["snippet"],
                "score": SESSION_INGESTION_SCORE,
                "dayBucket": day,
                "provenance": result.get("provenance"),
                "sessionOrigin": result.get("sessionOrigin"),
            }
            for result in grounded
        ],
        now_ms=now_ms,
        dedupe_by_query_per_day=True,
        timezone=timezone,
        origins=ledger,
    )
