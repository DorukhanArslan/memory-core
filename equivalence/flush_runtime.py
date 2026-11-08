"""Fixtures for the native flush trigger, accounting and retry lifecycle.

The reference executes ``runMemoryFlushIfNeeded``. Model execution is never
reached: a declared preparation error occurs only after the real trigger admits
an attempt. Python uses the public persisted-session preparation entry point.
These fixtures do not compare model execution, flush writes or host queues.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
from typing import Any
from unittest.mock import patch


NOW_MS = 1777824000000
_OWNED_ENTRY_FIELDS = (
    "totalTokens", "totalTokensFresh", "totalTokensVersion", "compactionCount",
    "memoryFlush", "incognito",
)
_PREPARATION_ERROR = "fixture preparation failed"


def _event(identifier: str, message: dict[str, Any], parent: str | None = None) -> dict[str, Any]:
    return {"type": "message", "id": identifier, "parentId": parent, "message": message}


def _assistant(identifier: str, usage: dict[str, Any], parent: str | None = None,
               **extra: Any) -> dict[str, Any]:
    return _event(identifier, {
        "role": "assistant", "content": [{"type": "text", "text": "noted"}],
        "usage": usage, **extra,
    }, parent)


def serialized_event_bytes(events: list[dict[str, Any]]) -> int:
    """UTF-8 bytes of declared canonical event JSON, with one newline per event.

    The reference independently reads SQLite active-event statistics. Fixtures
    containing a reset or tree control must supply the selected active rows when
    the Python host supplies its byte count; no header is included.
    """
    return sum(len(json.dumps(event, ensure_ascii=False, separators=(",", ":"),
                              allow_nan=False).encode("utf-8")) + 1 for event in events)


def _context_event_bytes(events: list[dict[str, Any]]) -> int:
    """Supply the host's active context byte snapshot, excluding discarded rows.

    Existing candidate branch/window owners select the retained context. A reset
    is a control boundary, whereas a compaction contributes its summary event
    bytes. The native SQLite statistics independently calculate the same fact.
    This projection affects bytes only: accounting still receives chronological
    events so reset barriers remain ahead of their retained earlier usage.
    """
    from memory_core.session_context_window import iterate_session_context_entries
    from memory_core.transcript_tree import select_session_transcript_leaf_controlled_path

    active = select_session_transcript_leaf_controlled_path(events)
    selected = events if active is None else active
    context = [event for event, _ in iterate_session_context_entries(selected)
               if event.get("type") != "reset"]
    return serialized_event_bytes(context)


def build_flush_runtime_cases() -> list[dict[str, Any]]:
    """Exercise the complete trigger-accounting domain against the real owner.

    Accounting/projection and byte snapshots cover outcomes. Admission gates,
    scan barriers and retry transitions cover boundaries; exact threshold and
    cycle fixtures exercise both. Credit still requires every registered native
    comparison to match in the full gate. Execution/finalization is uncredited.
    """
    cases: list[dict[str, Any]] = []
    base = {"sessionId": "session", "updatedAt": NOW_MS, "compactionCount": 0}
    fresh = {"totalTokens": 176000, "totalTokensFresh": True, "totalTokensVersion": 1}

    def add(name: str, *, entry: dict[str, Any] | None = None,
            events: list[dict[str, Any]] | None = None,
            acceptance: tuple[str, ...] = ("outcomes",), **arguments: Any) -> None:
        cases.append({
            "id": f"flush-runtime-{name}", "operation": "flush-trigger-runtime",
            "requirement": "flush.trigger-usage",
            "covers": [f"flush.trigger-usage.{point}" for point in acceptance],
            "input": {
                "entry": {**base, **deepcopy(entry or {})},
                "events": deepcopy(events or []), "contextWindowTokens": 200000,
                "promptForEstimate": "", "sessionKey": "agent:main:main", **arguments,
            },
            "driverScope": "real runtime accounting, trigger admission and durable retry state; "
                           "declared failure before model execution",
            "normalizationPolicy": "Compare owned accounting/compaction/flush entry fields "
                                   "with absent fields preserved, attempt admission, outcome "
                                   "and actual active-transcript UTF-8 bytes. Host storage "
                                   "metadata and native visible-error rendering are outside "
                                   "this trigger-accounting comparison.",
        })

    for name, total in (("below-threshold", 175999), ("at-threshold", 176000),
                        ("above-threshold", 176001)):
        add(name, entry={**fresh, "totalTokens": total}, acceptance=("outcomes", "boundaries"))
    add("missing-usage")
    add("stale-usage-without-transcript", entry={**fresh, "totalTokensFresh": False})
    add("unversioned-usage", entry={"totalTokens": 176000, "totalTokensFresh": True},
        acceptance=("outcomes", "boundaries"))
    add("old-version-usage", entry={**fresh, "totalTokensVersion": 0},
        acceptance=("outcomes", "boundaries"))
    add("zero-fresh-total", entry={**fresh, "totalTokens": 0},
        acceptance=("outcomes", "boundaries"))

    at = [_assistant("provider", {"input": 175999, "output": 1})]
    add("stale-usage-recovered", entry={**fresh, "totalTokensFresh": False}, events=at)
    add("missing-usage-recovered", events=at)
    add("provider-cache-components", events=[_assistant("provider", {
        "input": 170000, "cacheRead": 5000, "cacheWrite": 999, "output": 1,
    })])
    add("provider-context-snapshot", events=[_assistant("provider", {
        "input": 10, "contextUsage": {
            "state": "available", "promptTokens": 175999, "totalTokens": 176000,
        }, "output": 1,
    })])
    add("output-only-does-not-invent-prompt", events=[_assistant("provider", {"output": 176000})])
    add("total-minus-output-fallback", events=[_assistant("provider", {
        "total": 176000, "output": 1,
    })])
    add("latest-output-only-anchor-stops-scan", events=[
        *at, _assistant("output-only", {"output": 1}, "provider"),
    ], acceptance=("boundaries",))
    add("zero-usage-continues-scan", events=[
        *at, _assistant("zero", {"input": 0, "output": 0}, "provider"),
    ])
    add("latest-usage-replaces-older", events=[
        *at, _assistant("latest", {"input": 50, "output": 1}, "provider"),
    ])

    for name, barrier in (
        ("reset", {"type": "reset", "id": "barrier", "parentId": "provider"}),
        ("compaction", {"type": "compaction", "id": "barrier", "parentId": "provider",
                        "summary": "compacted", "firstKeptEntryId": "provider"}),
        ("unavailable-context", _assistant("barrier", {
            "contextUsage": {"state": "unavailable"},
        }, "provider")),
        ("legacy-cli-usage", _assistant("barrier", {"input": 175999, "output": 1},
                                         "provider", api="cli")),
    ):
        add(f"{name}-barrier", events=[*at, barrier], acceptance=("boundaries",))
    add("unavailable-with-components-is-usable", events=[_assistant("provider", {
        "input": 175999, "output": 1, "contextUsage": {"state": "unavailable"},
    })])
    add("cli-explicit-context-is-usable", events=[_assistant("provider", {
        "contextUsage": {"state": "available", "promptTokens": 175999,
                         "totalTokens": 176000}, "output": 1,
    }, api="cli")])

    add("trailing-user-projection", events=[
        _assistant("provider", {"input": 175998, "output": 1}),
        _event("next", {"role": "user", "content": "next"}, "provider"),
    ])
    add("trailing-tool-projection", events=[
        _assistant("provider", {"input": 175998, "output": 1}),
        _event("tool", {"role": "toolResult", "toolCallId": "t", "toolName": "read",
                        "content": [{"type": "text", "text": "next"}],
                        "isError": False, "timestamp": NOW_MS}, "provider"),
    ])
    add("tool-details-excluded-from-projection", events=[
        _assistant("provider", {"input": 175998, "output": 1}),
        _event("tool", {"role": "toolResult", "toolCallId": "t", "toolName": "read",
                        "content": [{"type": "text", "text": "next"}],
                        "details": {"hidden": "x" * 4096}, "isError": False,
                        "timestamp": NOW_MS}, "provider"),
    ])
    add("oversized-tool-projection", contextWindowTokens=26000, events=[
        _assistant("provider", {"input": 14000, "output": 1}),
        _event("tool", {"role": "toolResult", "toolCallId": "t", "toolName": "read",
                        "content": [{"type": "text", "text": "x" * 120000}],
                        "isError": False, "timestamp": NOW_MS}, "provider"),
    ])
    add("unicode-and-persisted-sender-projection", events=[
        _assistant("provider", {"input": 175970, "output": 1}),
        _event("next", {"role": "user", "content": "你好世界 😀 İ",
                        "__openclaw": {"senderId": " stable-7 ", "senderName": " Ada\u0000 ",
                                        "senderUsername": " ada "}}, "provider"),
    ])
    add("active-leaf-discards-side-usage", events=[
        _event("root", {"role": "user", "content": "root"}),
        _assistant("active", {"input": 50, "output": 1}, "root"),
        _assistant("side", {"input": 175999, "output": 1}, "root"),
        {"type": "leaf", "id": "select-active", "parentId": "side", "targetId": "active"},
    ])
    add("active-leaf-selects-reliable-usage", events=[
        _event("root", {"role": "user", "content": "root"}),
        _assistant("active", {"input": 175999, "output": 1}, "root"),
        _assistant("side", {"input": 50, "output": 1}, "root"),
        {"type": "leaf", "id": "select-active", "parentId": "side", "targetId": "active"},
    ])
    add("fresh-empty-prompt-does-not-read-output", entry={**fresh, "totalTokens": 175999},
        events=at)
    for name, total in (("below", 167806), ("at", 167807)):
        add(f"fresh-output-buffer-{name}", entry={**fresh, "totalTokens": total},
            events=[_assistant("provider", {"input": total, "output": 8192})],
            promptForEstimate="x", acceptance=("outcomes", "boundaries"))
    add("fresh-derived-total-never-decreases", entry={**fresh, "totalTokens": 175998},
        events=[_assistant("provider", {"input": 50, "output": 1})],
        promptForEstimate="x")
    add("fresh-derived-total-can-increase", entry={**fresh, "totalTokens": 175000},
        events=at, promptForEstimate="x")
    add("next-prompt-projection", entry={**fresh, "totalTokens": 175999},
        promptForEstimate="x")

    unicode_events = [_event("unicode", {"role": "user", "content": "İstanbul 😀"})]
    byte_size = serialized_event_bytes(unicode_events)
    for name, limit in (("below", byte_size + 1), ("at", byte_size), ("above", byte_size - 1)):
        add(f"transcript-bytes-{name}", events=unicode_events,
            flushConfig={"forceFlushTranscriptBytes": limit},
            acceptance=("outcomes", "boundaries"))
    add("transcript-byte-force-disabled", events=unicode_events,
        flushConfig={"forceFlushTranscriptBytes": 0}, acceptance=("outcomes", "boundaries"))
    add("reset-discards-byte-force", events=[
        *at, {"type": "reset", "id": "barrier", "parentId": "provider"},
    ], flushConfig={"forceFlushTranscriptBytes": 1}, acceptance=("outcomes", "boundaries"))
    add("flush-config-disabled", entry=fresh, flushConfig={"enabled": False},
        acceptance=("boundaries",))
    add("heartbeat-exclusion", entry=fresh, isHeartbeat=True, acceptance=("boundaries",))
    add("cli-exclusion", entry=fresh, isCli=True, acceptance=("boundaries",))
    add("read-only-workspace-exclusion", entry=fresh, memoryFlushWritable=False,
        acceptance=("boundaries",))
    add("incognito-entry-exclusion", entry={**fresh, "incognito": True},
        acceptance=("boundaries",))
    add("incognito-key-exclusion", entry=fresh,
        sessionKey="agent:main:dashboard:incognito-fixture", acceptance=("boundaries",))

    add("current-cycle-success-suppresses", entry={
        **fresh, "compactionCount": 2,
        "memoryFlush": {"kind": "succeeded", "compactionCount": 2},
    }, acceptance=("outcomes", "boundaries"))
    add("previous-cycle-success-admits", entry={
        **fresh, "compactionCount": 3,
        "memoryFlush": {"kind": "succeeded", "compactionCount": 2},
    }, acceptance=("outcomes", "boundaries"))
    add("same-cycle-suppresses-byte-force", entry={
        "memoryFlush": {"kind": "succeeded", "compactionCount": 0},
    }, events=unicode_events, flushConfig={"forceFlushTranscriptBytes": 1},
        acceptance=("outcomes", "boundaries"))
    add("retry-exhaustion-and-next-cycle", entry=fresh,
        steps=[{}, {}, {}, {}, {"entryPatch": {"compactionCount": 1}}, {}],
        acceptance=("boundaries",))
    add("previous-cycle-stamp-survives-failure", entry={
        **fresh, "compactionCount": 3,
        "memoryFlush": {"kind": "succeeded", "compactionCount": 2},
    }, steps=[{}, {}], acceptance=("boundaries",))
    add("failure-count-resumes", entry={
        **fresh, "memoryFlush": {"kind": "failed", "failureCount": 2},
    }, steps=[{}, {}], acceptance=("boundaries",))
    add("heartbeat-does-not-consume-retry", entry={
        **fresh, "memoryFlush": {"kind": "failed", "failureCount": 2},
    }, steps=[{"isHeartbeat": True}, {}, {}], acceptance=("boundaries",))
    add("usage-tail-limit-excludes-old-snapshot", events=[
        *at, *[_event(f"tail-{index}", {"role": "user", "content": "x"},
                     "provider" if index == 0 else f"tail-{index-1}") for index in range(512)],
    ], acceptance=("boundaries",))
    return cases


def _project_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(entry[key]) for key in _OWNED_ENTRY_FIELDS if key in entry}


def run_flush_runtime(arguments: dict[str, Any], *,
                      evidence_directory: Path | None = None) -> dict[str, Any]:
    """Run public HostKit preparation and reconstruct host state between attempts.

    The explicit host adapter persists returned ``SessionState`` as JSON and
    reloads it before another attempt. Storage-engine equivalence is not claimed.
    """
    from memory_core.client import Memory
    from memory_core.config import MemoryConfig
    from memory_core.flags import FeatureFlags
    from memory_core.host import HostKit, SessionState
    from memory_core.memory_flush import resolve_memory_flush_runtime_skip
    from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY

    supplied = deepcopy(arguments)
    with tempfile.TemporaryDirectory(prefix="memory-flush-runtime-") as temporary:
        root = Path(temporary)
        state_path = root / "session-state.json"
        settings = deepcopy(supplied.get("flushConfig", {}))
        memory = Memory.from_workspace(
            root, config=MemoryConfig(workspace_dir=root, flags=FeatureFlags(vector_search=False)),
            initialize=False,
        )
        kit = HostKit(memory, now_ms=lambda: NOW_MS, flush_config=settings,
                      identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)
        state = SessionState(session_key=supplied.get("sessionKey", "agent:main:main"),
                             session_id="session", entry=supplied.get("entry", {}))
        skip = resolve_memory_flush_runtime_skip(entry=state.entry, session_key=state.session_key)
        process_only = skip is not None and skip.reason == "runtime_skip:incognito"
        if not process_only:
            state_path.write_text(json.dumps(state.to_json(), ensure_ascii=False), encoding="utf-8")
        snapshots = []
        raw = []
        events = deepcopy(supplied.get("events", []))
        for step in supplied.get("steps", [{}]):
            if not process_only:
                state = SessionState.from_json(json.loads(state_path.read_text(encoding="utf-8")))
            entry = {**dict(state.entry), **step.get("entryPatch", {})}
            state = SessionState(session_key=state.session_key, session_id=state.session_id,
                                 kind=state.kind, entry=entry)
            events = deepcopy(step.get("events", events))
            byte_size = None if process_only else _context_event_bytes(events)
            visible = [event["message"] for event in events if isinstance(event.get("message"), dict)]
            attempt_count = 0

            def fail_preparation(*_args: Any, **_kwargs: Any) -> None:
                nonlocal attempt_count
                attempt_count += 1
                raise OSError(_PREPARATION_ERROR)

            with patch("memory_core.host.kit.ensure_memory_flush_target_file", fail_preparation):
                record = kit.prepare_flush(
                    state, transcript=visible, transcript_events=events,
                    context_window_tokens=step.get("contextWindowTokens", supplied.get("contextWindowTokens", 200000)),
                    transcript_bytes=byte_size,
                    prompt_for_estimate=step.get("promptForEstimate", supplied.get("promptForEstimate", "")),
                    is_heartbeat=step.get("isHeartbeat", supplied.get("isHeartbeat", False)),
                    is_cli=step.get("isCli", supplied.get("isCli", False)),
                    memory_flush_writable=step.get("memoryFlushWritable",
                                                  supplied.get("memoryFlushWritable", True)),
                )
            failure = record.flush_failure
            outcome = "skipped" if failure is None else "exhausted" if failure.exhausted else "failed"
            state = record.session
            persisted = None
            if not process_only:
                state_path.write_text(json.dumps(state.to_json(), ensure_ascii=False), encoding="utf-8")
                persisted = SessionState.from_json(json.loads(state_path.read_text(encoding="utf-8")))
            snapshots.append({
                "outcome": outcome, "triggered": bool(attempt_count),
                "entry": _project_entry(dict(record.session.entry)),
                "persistedEntry": None if persisted is None else _project_entry(dict(persisted.entry)),
                "transcriptByteSize": byte_size, "preparationAttempts": attempt_count,
            })
            raw.append({**snapshots[-1], "before": entry, "session": state.to_json(),
                        "persistedSession": None if persisted is None else persisted.to_json(),
                        "decision": asdict(record.flush_decision), "events": deepcopy(events),
                        "injectedFailure": "target-preparation" if attempt_count else None})
        if evidence_directory is not None:
            evidence_directory.mkdir(parents=True, exist_ok=True)
            (evidence_directory / "python-raw.json").write_text(
                json.dumps(raw, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8",
            )
        return {"provider": "none", "snapshots": snapshots}
