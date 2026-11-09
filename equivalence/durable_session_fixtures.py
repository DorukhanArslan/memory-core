"""Literal inputs for genuine three-process durable session owner experiments.

These requests contain no expected hits, reconstructed context or prior process
outputs. Both implementations execute their own persisted transcript, context,
participant, corpus and index owners. Coverage is limited to the reviewed durable flows.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


NOW = 1_794_268_800_000
STAMP = "2026-11-10T00:00:00.000Z"
PROFILE = (
    "Three distinct fresh OS processes write, reopen and continue, then reopen and verify "
    "the same real SQLite state. Ordinary active messages use genuine append owners; "
    "retained/control and incognito transcripts are literal raw-import inputs. Full "
    "current/retained metadata, transcript records, context/model-message projections, "
    "hidden history-prelude vectors, participant facts, real corpus/index/search outputs "
    "and actual append/read anchors remain observed. No provider call, pending-input "
    "custody, provider-signed replay, media migration, live writer fence or full turn "
    "barrier is claimed. The third process receives no mutations or prior output history."
    " Actual native settings fix temporal decay to enabled with a 30-day half-life; "
    "the SDK uses that same policy. Native Date and only the SDK decay module's "
    "datetime.now use each literal phase clock; timers and performance remain real."
)
NORMALIZATION = (
    "Complete native and SDK owner results, with full private SQL/process evidence retained. "
    "Exact owned-fixture-prefix substitution and the reviewed bijection of valid actual "
    "append/read-anchor generation tokens and exact producer store paths are the only "
    "identity codecs. No field dropping, expected-output injection, context projection, "
    "ordering repair, score tolerance or synthetic admission/visibility decisions."
)


def _assistant(content: list[dict], *, stop_reason: str = "stop", stamp: int = NOW) -> dict:
    return {"role": "assistant", "content": content, "api": "openai-completions",
            "provider": "openai", "model": "fixture-model", "stopReason": stop_reason,
            "timestamp": stamp, "usage": {"input": 17, "output": 5, "cacheRead": 0,
                "cacheWrite": 0, "totalTokens": 22,
                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0}}}


def _append(identifier: str, message: dict, **fields: Any) -> dict:
    return {"eventId": identifier, "message": message, "cwd": "/fixture/workspace", **fields}


def _queries(*terms: str) -> list[dict]:
    return [{"id": term, "query": term} for term in terms]


def build_durable_session_cases() -> list[dict[str, Any]]:
    key = "agent:main:dm:durable-tea"
    retained = "durable-tea-retained"
    active = "durable-tea-active"
    first_user = {"role": "user", "content": "Remember that I prefer kumquat tea.",
                  "timestamp": NOW, "idempotencyKey": "durable-tea-admission-1",
                  "__openclaw": {"senderIsOwner": True, "senderId": "alice"}}
    retained_events = [
        {"type": "session", "version": 4, "id": retained, "timestamp": STAMP,
         "cwd": "/fixture/workspace"},
        {"type": "message", "id": "retained-user", "parentId": None, "timestamp": STAMP,
         "message": {"role": "user", "content": "Archivekumquat is my older saved preference.",
                     "timestamp": NOW}},
        {"type": "message", "id": "retained-assistant", "parentId": "retained-user",
         "timestamp": STAMP,
         "message": _assistant([{"type": "text", "text": "Archivekumquat was recorded."}])},
    ]
    active_entry = {"sessionId": active, "previousSessionId": retained, "chatType": "direct",
                    "label": "Durable tea conversation", "compactionCount": 2,
                    "totalTokens": 123, "totalTokensFresh": True, "totalTokensVersion": 1,
                    "memoryFlush": {"kind": "failed", "compactionCount": 2, "failureCount": 1}}
    tea = {
        "kind": "durable", "agentId": "main", "nowMs": NOW,
        "sessionKey": key, "sessionId": active,
        "phases": [
            {"label": "write", "nowMs": NOW, "sessions": [
                {"sessionKey": key, "entry": {"sessionId": retained, "chatType": "direct",
                    "label": "Retained original incarnation", "updatedAt": NOW - 1000},
                 "events": retained_events},
                {"sessionKey": key, "entry": active_entry,
                 "participants": [{"identity": {"type": "profile", "id": "alice"}, "promptedAt": NOW}]},
            ], "appendMessages": [
                _append("tea-user-1", first_user),
                _append("tea-call-1", _assistant([
                    {"type": "toolCall", "id": "tea-lookup-1", "name": "lookup_preference",
                     "arguments": {"query": "kumquat", "options": {"saved": True}}},
                ], stop_reason="toolUse")),
                _append("tea-result-1", {"role": "toolResult", "toolCallId": "tea-lookup-1",
                    "toolName": "lookup_preference", "content": [{"type": "text", "text": "Kumquat tea."}],
                    "details": {"source": "saved-preference", "nested": {"kept": [1, True, None]}},
                    "isError": False, "timestamp": NOW}),
                _append("tea-assistant-1", _assistant([
                    {"type": "text", "text": "I saved your preference for kumquat tea."},
                ])),
            ], "anchorEntryId": "tea-assistant-1", "identityReads": [
                {"id": "retained", "sessionKey": key, "sessionId": retained},
            ], "queries": _queries("kumquat", "archivekumquat")},
            {"label": "continue", "nowMs": NOW + 60_000, "sessions": [
                {"sessionKey": key, "entry": {**active_entry,
                    "memoryFlush": {"kind": "succeeded", "compactionCount": 2}},
                 "participants": [{"identity": {"type": "profile", "id": "alice"},
                                   "promptedAt": NOW + 60_000}]},
            ], "appendMessages": [
                _append("tea-retry-different-id", {**first_user, "timestamp": NOW + 60_000}),
                _append("tea-conflicting-retry", {**first_user, "content": "A different admitted message."}),
                _append("tea-user-2", {"role": "user", "content": "Which tea do I prefer?",
                    "timestamp": NOW + 60_000, "idempotencyKey": "durable-tea-admission-2"}),
                _append("tea-assistant-2", _assistant([
                    {"type": "text", "text": "You prefer kumquat tea; this answer follows the reopened transcript."},
                ], stamp=NOW + 60_000)),
            ], "anchorEntryId": "tea-assistant-2", "identityReads": [
                {"id": "retained", "sessionKey": key, "sessionId": retained},
            ], "queries": _queries("kumquat", "archivekumquat")},
            {"label": "verify", "nowMs": NOW + 120_000, "anchorEntryId": "tea-assistant-2",
             "identityReads": [{"id": "retained", "sessionKey": key, "sessionId": retained}],
             "queries": _queries("kumquat", "archivekumquat")},
        ],
    }

    reset_key = "agent:main:dm:durable-reset"
    reset_id = "durable-reset-active"
    private_key = "agent:main:dashboard:incognito-durable"
    private_id = "durable-private"
    reset_events = [
        {"type": "session", "version": 4, "id": reset_id, "timestamp": STAMP, "cwd": "/fixture/workspace"},
        {"type": "thinking_level_change", "id": "reset-thinking", "parentId": None,
         "thinkingLevel": "high", "timestamp": STAMP},
        {"type": "model_change", "id": "reset-model", "parentId": "reset-thinking",
         "provider": "openai", "modelId": "fixture-model", "timestamp": STAMP},
        {"type": "message", "id": "reset-discarded", "parentId": "reset-model", "timestamp": STAMP,
         "message": {"role": "user", "content": "Discarded earlier topic.", "timestamp": NOW}},
        {"type": "message", "id": "reset-kept-user", "parentId": "reset-discarded", "timestamp": STAMP,
         "message": {"role": "user", "content": "Cobalt tea is the retained preference.",
                     "timestamp": NOW, "excludeFromContext": True}},
        {"type": "message", "id": "reset-kept-assistant", "parentId": "reset-kept-user", "timestamp": STAMP,
         "message": _assistant([{"type": "toolCall", "id": "reset-lookup", "name": "lookup_preference",
                                 "arguments": {"query": "cobalt"}}], stop_reason="toolUse")},
        {"type": "message", "id": "reset-paired-result", "parentId": "reset-kept-assistant", "timestamp": STAMP,
         "message": {"role": "toolResult", "toolCallId": "reset-lookup", "toolName": "lookup_preference",
                     "content": [{"type": "text", "text": "Cobalt retained result."}],
                     "details": {"pair": "retained"}, "isError": False, "timestamp": NOW}},
        {"type": "message", "id": "reset-orphan-result", "parentId": "reset-paired-result", "timestamp": STAMP,
         "message": {"role": "toolResult", "toolCallId": "missing-lookup", "toolName": "lookup_preference",
                     "content": [{"type": "text", "text": "Orphan must not become retained model context."}],
                     "isError": False, "timestamp": NOW}},
        {"type": "custom_message", "id": "reset-old-custom", "parentId": "reset-orphan-result",
         "customType": "note", "content": "Old custom display entry.", "display": True,
         "details": {"source": "fixture"}, "timestamp": STAMP},
        {"type": "compaction", "id": "reset-prior-compaction", "parentId": "reset-old-custom",
         "firstKeptEntryId": "reset-kept-user", "summary": "Earlier cobalt summary.",
         "tokensBefore": 101, "timestamp": STAMP},
        {"type": "reset", "id": "reset-boundary", "parentId": "reset-prior-compaction",
         "firstKeptEntryId": "reset-kept-user", "timestamp": STAMP},
    ]
    private_events = [
        {"type": "session", "version": 4, "id": private_id, "timestamp": STAMP, "cwd": "/fixture/workspace"},
        {"type": "message", "id": "private-user", "parentId": None, "timestamp": STAMP,
         "message": {"role": "user", "content": "Privatebasil belongs only to this process.", "timestamp": NOW}},
    ]
    private_read = {"id": "process-private", "sessionKey": private_key, "sessionId": private_id}
    reset = {
        "kind": "durable", "agentId": "main", "nowMs": NOW,
        "sessionKey": reset_key, "sessionId": reset_id,
        "phases": [
            {"label": "write", "nowMs": NOW, "sessions": [
                {"sessionKey": reset_key, "entry": {"sessionId": reset_id, "chatType": "direct",
                    "label": "Reset retained context", "compactionCount": 1,
                    "memoryFlush": {"kind": "failed", "compactionCount": 1, "failureCount": 1}},
                 "events": reset_events,
                 "participants": [{"identity": {"type": "profile", "id": "alice"}, "promptedAt": NOW}]},
                {"sessionKey": private_key, "entry": {"sessionId": private_id, "chatType": "direct"},
                 "events": private_events},
            ], "appendMessages": [
                _append("reset-user-1", {"role": "user", "content": "Continue after this reset.", "timestamp": NOW}),
                _append("reset-assistant-1", _assistant([
                    {"type": "text", "text": "Cobalt remains available from the retained paired context."},
                ])),
            ], "anchorEntryId": "reset-assistant-1", "identityReads": [private_read],
             "queries": _queries("cobalt", "privatebasil")},
            {"label": "continue", "nowMs": NOW + 60_000, "sessions": [
                {"sessionKey": reset_key, "entry": {"sessionId": reset_id, "chatType": "direct",
                    "label": "Reset retained context", "compactionCount": 1,
                    "memoryFlush": {"kind": "succeeded", "compactionCount": 1}}},
            ], "appendMessages": [
                _append("reset-user-2", {"role": "user", "content": "What is the retained preference?", "timestamp": NOW + 60_000}),
                _append("reset-assistant-2", _assistant([
                    {"type": "text", "text": "The retained preference is cobalt tea."},
                ], stamp=NOW + 60_000)),
            ], "anchorEntryId": "reset-assistant-2", "identityReads": [private_read],
             "queries": _queries("cobalt", "privatebasil")},
            {"label": "verify", "nowMs": NOW + 120_000, "anchorEntryId": "reset-assistant-2",
             "identityReads": [private_read], "queries": _queries("cobalt", "privatebasil")},
        ],
    }
    return [{"id": f"durable-session-{name}", "requirement": "sessions.durable-context",
             "operation": "durable-session-runtime",
             "covers": ["sessions.durable-context.outcomes", "sessions.durable-context.boundaries"],
             "input": deepcopy(value),
             "driverScope": PROFILE, "normalizationPolicy": NORMALIZATION}
            for name, value in (("retained-replay-continuation", tea), ("reset-and-private-reopen", reset))]
