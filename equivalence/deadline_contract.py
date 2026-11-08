"""Controlled clocks and providers around actual deadline and corpus owners."""
from __future__ import annotations

from copy import deepcopy
import heapq
import json
from pathlib import Path
import tempfile
import threading
import time
from typing import Any

from equivalence.search_contract import decode_search_tool_envelope


_START_MS = 1_000_000
_CONTROLLED_STATUS = {
    "backend": "builtin", "files": 1, "chunks": 1, "dirty": False,
    "workspaceDir": "/fixture/workspace", "dbPath": "/fixture/index.sqlite",
    "provider": "none", "requestedProvider": "none", "sources": ["memory"],
    "sourceCounts": [{"source": "memory", "files": 1, "chunks": 1}],
    "fts": {"enabled": True, "available": True},
}
_PROFILE = (
    "Original deadline/control owners and complete official memory_search factory, query, "
    "corpus and cooldown owners. Native uses Node's built-in mock timers; SDK uses its real "
    "production execution dependency with a fixture clock/scheduler and real workers. "
    "Controlled manager acquisition skips the index constructor and supplies only literal "
    "backend rows, failures and pending callbacks. Real provider entry, parent signals, "
    "partial publications, owner settlement, later admissions and per-backend callback "
    "counts are observed. No indexed-worker, retrieval-ranking, real transcript visibility, "
    "model-provider, operating-system scheduling latency or global cross-backend start "
    "ordering claim is made."
)
_GET_PROFILE = (
    "Actual official memory_get factory, secure builtin-file reader and corpus deadline "
    "owners over literal files in an owned workspace and controlled registered wiki "
    "callbacks. Node's built-in mock timers and the SDK production execution dependency "
    "drive real owner callbacks and parent signals. No manager or index constructor is "
    "substituted or credited. Builtin-only reads preserve the native unguarded pre-abort "
    "behavior; wiki/all execute the genuine corpus deadline. No OS scheduling latency, "
    "file-read race or model-provider claim is made."
)
_POLICY = (
    "No result/error/clock projection, timing tolerance, score rounding or event sorting. "
    "Complete public envelopes retain every field and actual elapsed duration. The reviewed "
    "JSON carrier codec validates the original text against complete details before decoding "
    "that carrier; original wire envelopes remain in raw evidence. Provider callbacks are "
    "observed separately per backend because independent worker/Promise entry has no global "
    "ordering contract; raw evidence retains the actual global interleaving. Actual typed "
    "Python provider keyword names map mechanically to their native names; callback/signal/"
    "symbol presence and executions remain observable. Explicit barriers and virtual clock "
    "commands precede compared state snapshots. Deadline provenance comes only from the "
    "actual owner identity, never error text or fixture-assigned flags."
)


def _row(name: str = "snapshot", *, source: str = "memory") -> dict[str, Any]:
    return {"path": f"memory/{name}.md" if source == "memory" else "sessions/fixture.jsonl",
            "startLine": 1, "endLine": 2, "score": 0.8, "snippet": f"Cedar {name}.\n",
            "source": source, "textScore": 0.2, "importance": 9,
            "provenance": {"originClass": "agent", "sessionKind": "unknown", "observedAt": _START_MS}}


def _query(corpus: str = "memory") -> dict[str, Any]:
    return {"query": "cedar", "maxResults": 6, "minScore": 0, "corpus": corpus}


def build_deadline_contract_cases() -> list[dict[str, Any]]:
    """Paired owner and whole-tool inputs with reviewed original-condition coverage."""
    cases: list[dict[str, Any]] = []

    def add(name: str, kind: str, *, requirement: str = "tools.deadline-cooldown", **arguments: Any) -> None:
        cases.append({"id": f"deadline-contract-{name}", "requirement": requirement,
                      "operation": ("deadline-partial-get-runtime" if arguments.get("toolName") == "memory_get"
                                    else "deadline-partial-runtime" if kind == "tool" else "deadline-partial"),
                      "covers": [], "input": {"kind": kind, **deepcopy(arguments)},
                      "driverScope": _GET_PROFILE if arguments.get("toolName") == "memory_get" else _PROFILE,
                      "normalizationPolicy": _POLICY})

    def source(name: str, actions: list[dict[str, Any]], **options: Any) -> None:
        owner = options.pop("owner", "search")
        add(name, "deadline", owner=owner, startMs=_START_MS,
            **({"timeoutMs": 30_000} if owner == "search" else {}), actions=actions, **options)

    value = {"text": "Çay 😀\x00", "metadata": [None, False, 0]}
    source("source-immediate-success", [{"op": "resolve", "value": value}, {"op": "settle"}])
    for name, elapsed in (("before", 29_999), ("at", 30_000), ("after", 30_001)):
        source(f"source-absolute-{name}", [{"op": "set-time", "nowMs": _START_MS + elapsed},
               {"op": "resolve", "value": value}, {"op": "settle"}])
    source("source-deadline-ignores-late-result", [{"op": "tick", "ms": 30_000}, {"op": "settle"},
           {"op": "resolve", "value": value}], abortBehavior="ignore")
    source("source-deadline-beats-provider-abort-wrapper", [{"op": "tick", "ms": 30_000}, {"op": "settle"}],
           abortError={"message": "provider wrapped cancellation", "code": "PROVIDER_CANCELLED"})
    source("source-parent-pre-abort-string", [], parentPreAbort="Caller cancelled")
    source("source-parent-pre-abort-error", [], parentPreAbort={"message": "Caller stopped", "code": "CALLER_STOP"})
    source("source-parent-mid-abort", [{"op": "tick", "ms": 17}, {"op": "abort", "reason": "Caller cancelled"},
           {"op": "settle"}])
    source("source-provider-timeout-text-is-unowned", [{"op": "reject", "error": {
        "message": "memory_search timed out after 30s", "code": "PROVIDER_FAILURE"}}, {"op": "settle"}],
        requirement="tools.unavailable-partial")
    source("source-corpus-owned-timeout", [{"op": "tick", "ms": 30_000}, {"op": "settle"}], owner="corpus")
    source("source-get-owned-timeout", [{"op": "tick", "ms": 30_000}, {"op": "settle"}],
           owner="corpus", operation="memory_get")
    source("source-bare-corpus-ignoring-task", [{"op": "tick", "ms": 30_000},
           {"op": "resolve", "value": value}, {"op": "settle"}], owner="corpus", abortBehavior="ignore")
    source("source-readiness-preserves-remaining-budget", [
        {"op": "tick", "ms": 10_000}, {"op": "pause"}, {"op": "tick", "ms": 40_000},
        {"op": "resume"}, {"op": "tick", "ms": 19_999}, {"op": "resolve", "value": value}, {"op": "settle"},
    ], owner="corpus")
    source("source-readiness-remaining-budget-expires", [
        {"op": "tick", "ms": 10_000}, {"op": "pause"}, {"op": "tick", "ms": 40_000},
        {"op": "resume"}, {"op": "tick", "ms": 20_000}, {"op": "settle"},
    ], owner="corpus")
    source("source-parent-abort-while-paused", [{"op": "pause"}, {"op": "tick", "ms": 40_000},
           {"op": "abort", "reason": {"message": "Caller stopped", "code": "CALLER_STOP"}}, {"op": "settle"}], owner="corpus")
    add("source-error-identity", "provenance", requirement="tools.unavailable-partial",
        message="memory_search timed out after 30s")
    add("source-balanced-control", "control", actions=[
        {"op": "subscribe", "id": "first"}, {"op": "pause"}, {"op": "pause"},
        {"op": "subscribe", "id": "during"}, {"op": "resume"},
        {"op": "unsubscribe", "id": "first"}, {"op": "resume"}, {"op": "resume"},
    ])

    def call(identifier: str, corpus: str = "memory", **fields: Any) -> dict[str, Any]:
        return {"op": "call", "id": identifier, "params": _query(corpus), **fields}

    def barrier(**fields: Any) -> dict[str, Any]:
        return {"op": "barrier", **fields}

    def resolve(lane: str, invocation: int, value: Any, **fields: Any) -> dict[str, Any]:
        return {"op": "resolve", "lane": lane, "invocation": invocation, "value": value, **fields}

    def reject(lane: str, invocation: int, message: str, **fields: Any) -> dict[str, Any]:
        return {"op": "reject", "lane": lane, "invocation": invocation, "error": {"message": message}, **fields}

    def tool(name: str, commands: list[dict[str, Any]], *, partial: bool = False, **options: Any) -> None:
        add(name, "tool", requirement="tools.unavailable-partial" if partial else "tools.deadline-cooldown",
            startMs=_START_MS, commands=commands, **options)

    wiki = [{"path": "wiki/cedar", "source": "wiki", "corpus": "wiki", "score": 0.9,
             "snippet": "Wiki cedar.", "title": "Cedar", "opaque": [None, False]}]
    tool("cooldown-admission-expiry-corpus-independence", [
        call("failed"), barrier(dispatches={"memory": 1}), reject("memory", 1, "provider unavailable"),
        barrier(settled=["failed"], finished={"memory": 1}), call("cached"), barrier(settled=["cached"]),
        call("sessions-cached", "sessions"), barrier(settled=["sessions-cached"]),
        call("wiki", "wiki"), barrier(dispatches={"wiki:alpha": 1}), resolve("wiki:alpha", 1, wiki), barrier(settled=["wiki"]),
        call("mixed", "all"), barrier(dispatches={"wiki:alpha": 2}), resolve("wiki:alpha", 2, wiki), barrier(settled=["mixed"]),
        {"op": "tick", "ms": 59_999}, call("still-cached"), barrier(settled=["still-cached"]),
        {"op": "tick", "ms": 1}, call("recovered"), barrier(dispatches={"memory": 2}),
        resolve("memory", 2, [_row("recovered")]), barrier(settled=["recovered"], finished={"memory": 2}),
    ], config={"sources": ["memory", "sessions"]}, supplements=[{"pluginId": "alpha"}])
    tool("true-timeout-cached-late-result-expiry", [
        call("timed-out"), barrier(dispatches={"memory": 1}), {"op": "tick", "ms": 30_000, "settled": ["timed-out"]},
        resolve("memory", 1, [_row("too-late")]), barrier(finished={"memory": 1}),
        call("cached"), barrier(settled=["cached"]), {"op": "tick", "ms": 60_000},
        call("recovered"), barrier(dispatches={"memory": 2}), resolve("memory", 2, [_row("recovered")]),
        barrier(settled=["recovered"], finished={"memory": 2}),
    ], abortBehavior="ignore")
    tool("configuration-change-clears-cooldown", [
        call("failed"), barrier(dispatches={"memory": 1}), reject("memory", 1, "provider unavailable"),
        barrier(settled=["failed"], finished={"memory": 1}),
        call("recovered", configPatch={"query": {"maxResults": 7}}), barrier(dispatches={"memory": 2}),
        resolve("memory", 2, [_row("reconfigured")]), barrier(settled=["recovered"], finished={"memory": 2}),
    ])
    tool("caller-abort-does-not-poison-admission", [
        call("cancelled"), barrier(dispatches={"memory": 1}),
        {"op": "abort", "id": "cancelled", "reason": {"message": "Caller stopped", "code": "CALLER_STOP"}, "settled": ["cancelled"]},
        resolve("memory", 1, [_row("too-late")]), barrier(finished={"memory": 1}),
        call("next"), barrier(dispatches={"memory": 2}), resolve("memory", 2, [_row("fresh")]),
        barrier(settled=["next"], finished={"memory": 2}),
    ], abortBehavior="ignore")
    tool("readiness-and-independent-wiki-settlement", [
        call("wiki-already-done", "all"), barrier(dispatches={"memory": 1, "wiki:alpha": 1}),
        {"op": "pause", "lane": "memory", "invocation": 1}, {"op": "tick", "ms": 5},
        resolve("wiki:alpha", 1, wiki), barrier(finished={"wiki:alpha": 1}, timerClears=2), {"op": "tick", "ms": 35_000},
        {"op": "resume", "lane": "memory", "invocation": 1}, resolve("memory", 1, [_row("after-readiness")]),
        barrier(settled=["wiki-already-done"], finished={"memory": 1}),
        call("wiki-times-out", "all"), barrier(dispatches={"memory": 2, "wiki:alpha": 2}),
        {"op": "pause", "lane": "memory", "invocation": 2}, {"op": "tick", "ms": 30_000},
        {"op": "resume", "lane": "memory", "invocation": 2}, resolve("memory", 2, [_row("memory-survives")]),
        barrier(settled=["wiki-times-out"], finished={"memory": 2}), resolve("wiki:alpha", 2, wiki),
        barrier(finished={"wiki:alpha": 2}),
    ], supplements=[{"pluginId": "alpha"}])
    tool("absolute-overdue-provider-completion", [
        call("overdue"), barrier(dispatches={"memory": 1}), {"op": "set-time", "nowMs": _START_MS + 30_000},
        resolve("memory", 1, [_row("too-late")]), barrier(settled=["overdue"], finished={"memory": 1}),
    ])
    tool("accepted-partial-late-update-explicit-recovery", [
        call("partial"), barrier(dispatches={"memory": 1}),
        {"op": "partial", "lane": "memory", "invocation": 1, "rows": [_row(), _row(source="sessions")]},
        {"op": "tick", "ms": 30_000, "settled": ["partial"]},
        {"op": "partial", "lane": "memory", "invocation": 1, "rows": [_row("late-snapshot")]},
        resolve("memory", 1, [_row("late-final")]), barrier(finished={"memory": 1}),
        call("fresh"), barrier(dispatches={"memory": 2}), resolve("memory", 2, [_row("fresh")]),
        barrier(settled=["fresh"], finished={"memory": 2}),
    ], partial=True, abortBehavior="ignore")
    tool("partial-invalidation-withholds-old-snapshot", [
        call("invalidated"), barrier(dispatches={"memory": 1}),
        {"op": "partial", "lane": "memory", "invocation": 1, "rows": [_row()]},
        {"op": "partial", "lane": "memory", "invocation": 1, "rows": []},
        {"op": "tick", "ms": 30_000, "settled": ["invalidated"]},
        resolve("memory", 1, [_row("too-late")]), barrier(finished={"memory": 1}),
        call("cached"), barrier(settled=["cached"]),
    ], partial=True, abortBehavior="ignore")
    tool("sessions-cannot-salvage-memory-or-session-partials", [
        call("sessions", "sessions"), barrier(dispatches={"memory": 1}),
        {"op": "partial", "lane": "memory", "invocation": 1, "rows": [_row(), _row(source="sessions")]},
        {"op": "tick", "ms": 30_000, "settled": ["sessions"]},
        resolve("memory", 1, []), barrier(finished={"memory": 1}),
        call("wiki", "wiki"), barrier(dispatches={"wiki:alpha": 1}), resolve("wiki:alpha", 1, wiki), barrier(settled=["wiki"]),
    ], partial=True, config={"sources": ["memory", "sessions"]}, supplements=[{"pluginId": "alpha"}], abortBehavior="ignore")
    tool("provider-timeout-text-stays-unowned-with-wiki-survival", [
        call("spoofed"), barrier(dispatches={"memory": 1}), reject("memory", 1, "memory_search timed out after 30s"),
        barrier(settled=["spoofed"], finished={"memory": 1}),
        call("mixed", "all"), barrier(dispatches={"wiki:alpha": 1}), resolve("wiki:alpha", 1, wiki), barrier(settled=["mixed"]),
        {"op": "tick", "ms": 60_000}, call("fresh"), barrier(dispatches={"memory": 2}),
        resolve("memory", 2, [_row("fresh")]), barrier(settled=["fresh"], finished={"memory": 2}),
    ], partial=True, supplements=[{"pluginId": "alpha"}])
    tool("wiki-failure-independent-memory-and-later-recovery", [
        call("mixed", "all"), barrier(dispatches={"memory": 1, "wiki:alpha": 1}),
        resolve("memory", 1, [_row()]), reject("wiki:alpha", 1, "wiki unavailable"),
        barrier(settled=["mixed"], finished={"memory": 1, "wiki:alpha": 1}),
        call("recovered", "all"), barrier(dispatches={"memory": 2, "wiki:alpha": 2}),
        resolve("memory", 2, [_row("fresh")]), resolve("wiki:alpha", 2, wiki),
        barrier(settled=["recovered"], finished={"memory": 2, "wiki:alpha": 2}),
    ], partial=True, supplements=[{"pluginId": "alpha"}])
    tool("both-corpora-timeout-wiki-retry-and-later-recovery", [
        call("both", "all"), barrier(dispatches={"memory": 1, "wiki:alpha": 1}),
        {"op": "tick", "ms": 30_000, "settled": ["both"]},
        resolve("memory", 1, []), resolve("wiki:alpha", 1, []), barrier(finished={"memory": 1, "wiki:alpha": 1}),
        call("wiki", "wiki"), barrier(dispatches={"wiki:alpha": 2}), resolve("wiki:alpha", 2, wiki), barrier(settled=["wiki"]),
        {"op": "tick", "ms": 60_000}, call("recovered", "all"), barrier(dispatches={"memory": 2, "wiki:alpha": 3}),
        resolve("memory", 2, [_row("fresh")]), resolve("wiki:alpha", 3, wiki),
        barrier(settled=["recovered"], finished={"memory": 2, "wiki:alpha": 3}),
    ], partial=True, supplements=[{"pluginId": "alpha"}], abortBehavior="ignore")
    def get_call(identifier: str, corpus: str = "memory", **fields: Any) -> dict[str, Any]:
        return {"op": "call", "id": identifier, "params": {
            "path": "wiki/cedar" if corpus == "wiki" else "MEMORY.md", "corpus": corpus, "from": 1, "lines": 2,
        }, **fields}

    read_reply = {"path": "wiki/cedar", "corpus": "wiki", "content": "Fresh wiki excerpt.",
                  "title": "Cedar", "opaque": [None, False]}
    tool("get-wiki-owned-timeout-late-result-and-recovery", [
        get_call("timeout", "wiki"), barrier(dispatches={"wiki:alpha": 1}),
        {"op": "tick", "ms": 30_000, "settled": ["timeout"]},
        resolve("wiki:alpha", 1, {**read_reply, "content": "Late ignored excerpt."}), barrier(finished={"wiki:alpha": 1}),
        get_call("recovered", "wiki"), barrier(dispatches={"wiki:alpha": 2}), resolve("wiki:alpha", 2, read_reply),
        barrier(settled=["recovered"], finished={"wiki:alpha": 2}),
    ], partial=True, toolName="memory_get", supplements=[{"pluginId": "alpha"}], files={"MEMORY.md": "Builtin memory.\n"})
    tool("get-builtin-pre-aborted-read-remains-unguarded", [
        get_call("builtin", parentPreAbort={"message": "Caller already cancelled", "code": "CALLER_STOP"}),
        barrier(settled=["builtin"]),
    ], toolName="memory_get", files={"MEMORY.md": "Builtin memory.\n"})
    tool("get-all-parent-abort-and-later-explicit-query", [
        get_call("cancelled", "all"), barrier(dispatches={"wiki:alpha": 1}),
        {"op": "abort", "id": "cancelled", "reason": {"message": "Caller stopped", "code": "CALLER_STOP"}, "settled": ["cancelled"]},
        resolve("wiki:alpha", 1, {**read_reply, "content": "Late ignored excerpt."}), barrier(finished={"wiki:alpha": 1}),
        get_call("fresh", "all"), barrier(dispatches={"wiki:alpha": 2}), resolve("wiki:alpha", 2, read_reply),
        barrier(settled=["fresh"], finished={"wiki:alpha": 2}),
    ], partial=True, toolName="memory_get", supplements=[{"pluginId": "alpha"}], files={"MEMORY.md": "Builtin memory.\n"})
    # The stable source/search run and fresh routed GET run were independently
    # reviewed. Credit follows the actual condition exercised; supporting
    # baselines, identity/control helpers and native bare-callback quirks remain
    # diagnostic rather than standing in for complete tool execution.
    deadline_source_outcomes = {
        "source-absolute-before", "source-absolute-at", "source-absolute-after",
        "source-deadline-ignores-late-result", "source-deadline-beats-provider-abort-wrapper",
        "source-corpus-owned-timeout", "source-get-owned-timeout",
        "source-readiness-preserves-remaining-budget", "source-readiness-remaining-budget-expires",
        "source-parent-abort-while-paused",
    }
    deadline_tool_outcomes = {
        "cooldown-admission-expiry-corpus-independence", "true-timeout-cached-late-result-expiry",
        "configuration-change-clears-cooldown", "readiness-and-independent-wiki-settlement",
        "absolute-overdue-provider-completion",
    }
    deadline_tool_boundaries = {
        "cooldown-admission-expiry-corpus-independence", "true-timeout-cached-late-result-expiry",
        "configuration-change-clears-cooldown", "caller-abort-does-not-poison-admission",
        "readiness-and-independent-wiki-settlement",
    }
    for case in cases:
        name = case["id"].removeprefix("deadline-contract-")
        if case["requirement"] == "tools.deadline-cooldown":
            if name in deadline_source_outcomes or name in deadline_tool_outcomes:
                case["covers"].append("tools.deadline-cooldown.outcomes")
            if name in deadline_tool_boundaries:
                case["covers"].append("tools.deadline-cooldown.boundaries")
        elif case["input"]["kind"] == "tool":
            if name != "get-all-parent-abort-and-later-explicit-query":
                case["covers"].append("tools.unavailable-partial.outcomes")
            case["covers"].append("tools.unavailable-partial.boundaries")
    return cases


def run_deadline_contract(arguments: dict[str, Any], *, evidence_directory: Path | None = None) -> dict[str, Any]:
    value = deepcopy(arguments)
    if value["kind"] == "tool":
        return _run_tool(value, evidence_directory=evidence_directory)
    return _run_source(value)


class _ManualClock:
    """A scheduler dependency, with actual production timers owning expiration."""

    def __init__(self, start_ms: float):
        self.now = start_ms
        self._lock = threading.RLock()
        self._queue: list = []
        self._sequence = 0
        self.trace: list[dict[str, Any]] = []

    def clock(self) -> float:
        with self._lock:
            return self.now

    def timer_clears(self) -> int:
        with self._lock:
            return sum(event["event"] == "cancelled" for event in self.trace)

    def schedule(self, delay_ms: float, callback):
        with self._lock:
            self._sequence += 1
            timer = [self.now + delay_ms, self._sequence, False, callback]
            heapq.heappush(self._queue, timer)
            self.trace.append({"event": "scheduled", "time": self.now, "due": timer[0], "id": timer[1]})

        def cancel():
            with self._lock:
                timer[2] = True
                self.trace.append({"event": "cancelled", "time": self.now, "id": timer[1]})

        return cancel

    def set_time(self, now_ms: float) -> None:
        with self._lock:
            self.now = now_ms

    def tick(self, milliseconds: float) -> None:
        with self._lock:
            self.now += milliseconds
        while True:
            with self._lock:
                if not self._queue or self._queue[0][0] > self.now:
                    return
                timer = heapq.heappop(self._queue)
                if timer[2]:
                    continue
                self.trace.append({"event": "fired", "time": self.now, "id": timer[1]})
            timer[3]()


def _await(predicate, label: str) -> None:
    deadline = time.monotonic() + 5
    wake = threading.Event()
    while not predicate():
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Controlled fixture did not reach its explicit barrier: {label}")
        wake.wait(0.001)


def _fixture_error(spec: Any) -> BaseException:
    from memory_core.tools.common import MemoryToolError

    value = {"message": spec} if isinstance(spec, str) else spec or {}
    error = MemoryToolError(value.get("message", "Fixture provider failed"))
    if "name" in value:
        error.name = value["name"]
    if "code" in value:
        error.code = value["code"]
    return error


def _abort_reason(spec: Any) -> Any:
    return _fixture_error(spec) if isinstance(spec, dict) else spec


def _public_error(error: BaseException, *, provenance: bool = False) -> dict[str, Any]:
    from memory_core.tools.deadline import is_memory_search_deadline_error

    result = {"name": getattr(error, "name", type(error).__name__), "message": str(error)}
    for name in ("status", "code"):
        if hasattr(error, name):
            result[name] = getattr(error, name)
    if provenance:
        result["deadline"] = is_memory_search_deadline_error(error)
    return result


class _Deferred:
    def __init__(self):
        self.event = threading.Event()
        self.finished = threading.Event()
        self.lock = threading.Lock()
        self.value: Any = None
        self.error: BaseException | None = None

    def complete(self, *, value: Any = None, error: BaseException | None = None) -> None:
        with self.lock:
            if self.event.is_set():
                return
            self.value, self.error = deepcopy(value), error
            self.event.set()

    def result(self) -> Any:
        if not self.event.wait(5):
            raise RuntimeError("Controlled provider was not released by its fixture")
        if self.error is not None:
            raise self.error
        return self.value


def _run_source(value: dict[str, Any]) -> dict[str, Any]:
    from memory_core.cancellation import CancellationSignal
    from memory_core.tools.deadline import (
        MemorySearchDeadlineControl, MemoryToolDeadlineContext,
        create_memory_search_deadline_error, run_memory_corpus_deadline,
        run_memory_search_with_deadline,
    )

    if value["kind"] == "provenance":
        owned = create_memory_search_deadline_error(value["message"])
        ordinary = _fixture_error({"message": str(owned)})
        copied = _fixture_error({"message": str(owned)})
        copied.__dict__.update(owned.__dict__)
        return {name: _public_error(error, provenance=True) for name, error in (
            ("owned", owned), ("ordinary", ordinary), ("copy", copied), ("cloned", deepcopy(owned)),
        )}
    if value["kind"] == "control":
        control = MemorySearchDeadlineControl()
        listeners, events = {}, []
        for action in value["actions"]:
            if action["op"] == "subscribe":
                identifier = action["id"]
                listeners[identifier] = control.subscribe(
                    lambda event, identifier=identifier: events.append({"listener": identifier, "action": event}),
                )
            elif action["op"] == "unsubscribe":
                if action["id"] in listeners:
                    listeners[action["id"]]()
            elif action["op"] in {"pause", "resume"}:
                control.report(action["op"])
            else:
                raise ValueError(f"Unsupported deadline-control action: {action['op']}")
        return {"events": events}
    if value["kind"] != "deadline":
        raise ValueError(f"Unsupported deadline-contract operation: {value['kind']}")
    clock = _ManualClock(value["startMs"])
    parent = CancellationSignal()
    context = MemoryToolDeadlineContext(signal=parent, clock=clock.clock, schedule=clock.schedule)
    gate = _Deferred()
    state: dict[str, Any] = {"signal": None, "control": None, "outcome": None, "error": None}
    completed = threading.Event()
    events, clock_steps = [], []

    def provider(signal):
        state["signal"] = signal
        events.append({"event": "provider:start", "time": clock.clock()})

        def aborted():
            reason = signal.reason
            events.append({"event": "provider:abort", "time": clock.clock(), "reason":
                           _public_error(reason, provenance=True) if isinstance(reason, BaseException) else reason})
            if value.get("abortBehavior") != "ignore":
                gate.complete(error=_fixture_error(value["abortError"]) if "abortError" in value else reason)

        signal.add_listener(aborted)
        try:
            result = gate.result()
            events.append({"event": "provider:fulfilled", "time": clock.clock(), "value": deepcopy(result)})
            return result
        except BaseException as error:
            events.append({"event": "provider:rejected", "time": clock.clock(),
                           "error": _public_error(error, provenance=True)})
            raise
        finally:
            gate.finished.set()

    def corpus_run(signal, control):
        state["control"] = control
        return provider(signal)

    def run():
        try:
            result = (run_memory_search_with_deadline(value["timeoutMs"], provider, context=context)
                      if value["owner"] == "search" else run_memory_corpus_deadline(
                          value.get("operation", "memory_search"), corpus_run, context=context,
                      ))
            state["outcome"] = {"result": result}
        except BaseException as error:
            state["error"] = error
            state["outcome"] = {"error": _public_error(error, provenance=True)}
        finally:
            completed.set()

    if "parentPreAbort" in value:
        parent.abort(_abort_reason(value["parentPreAbort"]))
    threading.Thread(target=run, name="fixture-deadline-caller", daemon=True).start()
    _await(lambda: state["signal"] is not None or completed.is_set(), "provider entry or pre-abort settlement")
    for action in value["actions"]:
        operation = action["op"]
        if operation == "tick":
            clock.tick(action["ms"])
        elif operation == "set-time":
            clock.set_time(action["nowMs"])
        elif operation == "resolve":
            gate.complete(value=action["value"])
        elif operation == "reject":
            gate.complete(error=_fixture_error(action["error"]))
        elif operation == "abort":
            parent.abort(_abort_reason(action["reason"]))
        elif operation in {"pause", "resume"}:
            if state["control"] is None:
                raise ValueError("Only corpus owners expose a readiness control channel")
            state["control"].report(operation)
        elif operation not in {"settle", "flush"}:
            raise ValueError(f"Unsupported deadline action: {operation}")
        clock_steps.append({**deepcopy(action), "time": clock.clock()})
        if gate.event.is_set() and state["signal"] is not None:
            _await(gate.finished.is_set, "released provider settlement")
        if operation == "settle":
            _await(completed.is_set, "deadline settlement")
    _await(completed.is_set, "final deadline settlement")
    signal = state["signal"]
    observed_signal = None if signal is None else {
        "aborted": signal.aborted,
        **({"reason": _public_error(signal.reason, provenance=True)
            if isinstance(signal.reason, BaseException) else signal.reason} if signal.aborted else {}),
        "reasonIsOutcomeError": signal.aborted and signal.reason is state["error"],
    }
    return {"outcome": state["outcome"], "signal": observed_signal, "events": events, "clockSteps": clock_steps}


def _run_tool(value: dict[str, Any], *, evidence_directory: Path | None) -> dict[str, Any]:
    from memory_core.cancellation import CancellationSignal
    from memory_core.config import MemoryConfig
    from memory_core.flags import FeatureFlags
    from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
    from memory_core.supplements import RegisteredMemoryCorpusSupplement
    from memory_core.tools.deadline import MemoryToolDeadlineContext
    from memory_core.tools.get_factory import create_memory_get_tool
    from memory_core.tools.memory_search import MemorySearchToolContext, reset_memory_search_tool_cooldowns
    from memory_core.tools.search_factory import create_memory_search_tool

    clock = _ManualClock(value["startMs"])
    observed = _ControlledProviders(value, clock)
    settings = value.get("config", {})
    is_get = value.get("toolName") == "memory_get"
    reader_directory = tempfile.TemporaryDirectory(prefix="memory-deadline-get-") if is_get else None
    workspace = Path(reader_directory.name) if reader_directory is not None else Path("/fixture/workspace")
    if is_get:
        for relative, text in value.get("files", {}).items():
            path = Path(relative)
            if path.is_absolute() or ".." in relative.replace("\\", "/").split("/"):
                raise ValueError("Fixture files must remain in their owned workspace")
            filename = workspace / path
            filename.parent.mkdir(parents=True, exist_ok=True)
            filename.write_text(text, encoding="utf-8")

    def configure(options):
        if options.get("provider", "none") != "none":
            raise ValueError("Controlled deadline fixtures do not execute embedding providers")
        query = options.get("query", {})
        return MemoryConfig(
            workspace_dir=workspace, store_path=None if is_get else Path("/fixture/index.sqlite"),
            session_search="sessions" in options.get("sources", ["memory"]),
            search_max_results=query.get("maxResults", 6), search_min_score=query.get("minScore", 0.35),
            flags=FeatureFlags(vector_search=False),
        )

    config = configure(settings)
    store = None if is_get else _ControlledStore(config, observed)
    current_config = config
    execution = MemoryToolDeadlineContext(clock=clock.clock, schedule=clock.schedule)
    options = value.get("options", {})
    context = MemorySearchToolContext(clock=clock.clock, execution=execution,
                                      sandboxed=options.get("sandboxed"))
    supplements = []
    for provider in value.get("supplements", []):
        identifier = provider["pluginId"]
        observed.lane(f"wiki:{identifier}")
        observed.wiki_dispatches[identifier] = []
        supplements.append(RegisteredMemoryCorpusSupplement(
            identifier, _UnusedSupplement(),
            reader=lambda identifier=identifier, **query: observed.wiki_read(identifier, query),
            searcher=lambda identifier=identifier, **query: observed.wiki_search(identifier, query),
        ))
    observed.lane("memory")
    tool = (create_memory_get_tool(
        config, get_config=lambda: current_config, supplements=supplements,
        agent_session_key=options.get("agentSessionKey"), sandboxed=options.get("sandboxed"), execution=execution,
    ) if is_get else create_memory_search_tool(
        config, store, get_config=lambda: current_config, context=context, supplements=supplements,
        agent_session_key=options.get("agentSessionKey"), active_project_keys=options.get("activeProjectKeys"),
        conversation_recall=options.get("conversationRecall"), runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
    ))
    if tool is None:
        raise ValueError("The actual controlled SDK memory search tool was unavailable")
    calls: dict[str, dict[str, Any]] = {}
    clock_steps = []

    def barrier(command):
        _await(lambda: all(len(observed.lane(name)["records"]) >= count
                           for name, count in command.get("dispatches", {}).items())
               and all(sum(item["finished"] for item in observed.lane(name)["records"]) >= count
                       for name, count in command.get("finished", {}).items())
               and all(calls.get(identifier, {}).get("settled") for identifier in command.get("settled", []))
               and clock.timer_clears() >= command.get("timerClears", 0),
               "explicit provider/control observations")

    def counts():
        return {
            "dispatchCounts": {name: len(lane["records"]) for name, lane in observed.lanes.items()},
            "activeCounts": {name: sum(not record["finished"] for record in lane["records"])
                             for name, lane in observed.lanes.items()},
            "abortCounts": {name: sum(record["aborted"] for record in lane["records"])
                            for name, lane in observed.lanes.items()},
            "settledCalls": [identifier for identifier, call in calls.items() if call["settled"]],
        }

    def call_tool(command, record):
        try:
            envelope = tool.execute(command["id"], deepcopy(command["params"]), record["controller"])
        except BaseException as error:
            result = {"id": command["id"], "error": _public_error(error)}
            record["wire"] = deepcopy(result)
        else:
            record["wire"] = {"id": command["id"], "result": envelope}
            result = {"id": command["id"], "result": decode_search_tool_envelope(envelope)}
        record["output"] = result
        record["settled"] = True

    reset_memory_search_tool_cooldowns()
    try:
        for command in value["commands"]:
            operation = command["op"]
            if operation == "call":
                if command["id"] in calls:
                    raise ValueError("Controlled calls require unique ids")
                if command.get("configPatch"):
                    current_config = configure({**settings, **command["configPatch"]})
                record = {"controller": CancellationSignal(), "settled": False}
                if "parentPreAbort" in command:
                    record["controller"].abort(_abort_reason(command["parentPreAbort"]))
                calls[command["id"]] = record
                threading.Thread(target=call_tool, args=(deepcopy(command), record),
                                 name="fixture-memory-search-caller", daemon=True).start()
            elif operation == "tick":
                clock.tick(command["ms"])
            elif operation == "set-time":
                clock.set_time(command["nowMs"])
            elif operation == "abort":
                calls[command["id"]]["controller"].abort(_abort_reason(command["reason"]))
            elif operation in {"resolve", "reject", "partial", "pause", "resume"}:
                record = observed.lane(command["lane"])["records"][command["invocation"] - 1]
                if operation == "resolve":
                    record["gate"].complete(value=command["value"])
                elif operation == "reject":
                    record["gate"].complete(error=_fixture_error(command["error"]))
                elif operation == "partial":
                    observed.log(command["lane"], command["invocation"], "partial", rows=deepcopy(command["rows"]))
                    record["options"]["on_partial_results"](deepcopy(command["rows"]))
                else:
                    observed.log(command["lane"], command["invocation"], operation)
                    record["options"]["deadline_control"].report(operation)
                if operation in {"resolve", "reject"}:
                    _await(record["gate"].finished.is_set, "released provider settlement")
            elif operation not in {"barrier", "settle", "flush", "await-dispatch"}:
                raise ValueError(f"Unsupported controlled deadline command: {operation}")
            required = ({"settled": [command["id"]]} if operation == "settle" else
                        {"dispatches": {command["lane"]: command["count"]}} if operation == "await-dispatch" else command)
            barrier(required)
            clock_steps.append({**deepcopy(command), "time": clock.clock(),
                                **({"timerClearCount": clock.timer_clears()} if "timerClears" in command else {}),
                                **(counts() if operation in {"barrier", "tick", "set-time", "pause", "resume", "settle"} else {})})
        _await(lambda: all(call["settled"] for call in calls.values()), "all tool replies")
        result = {"provider": "none", "calls": [deepcopy(call["output"]) for call in calls.values()],
                  "memoryDispatches": deepcopy(observed.memory_dispatches),
                  "wikiDispatches": deepcopy(observed.wiki_dispatches),
                  "lanes": {name: deepcopy(lane["events"]) for name, lane in observed.lanes.items()},
                  "clockSteps": deepcopy(clock_steps)}
        raw = [{"managerFixture": not is_get, "constructorSkipped": not is_get, "globalEvents": observed.global_events,
                **({"managerAcquisition": "not-required", "indexManagerConstructed": False} if is_get else {}),
                "pythonEnvelopes": [deepcopy(call["wire"]) for call in calls.values()],
                "clockSteps": clock_steps, "timerEvents": clock.trace,
                "memoryOptionSurfaces": observed.memory_option_surfaces,
                **({"files": {relative: list((workspace / relative).read_bytes()) for relative in value.get("files", {})}}
                   if is_get else {"status": observed.status}),
                "memoryDispatches": observed.memory_dispatches, "wikiDispatches": observed.wiki_dispatches}]
        if evidence_directory is not None:
            evidence_directory.mkdir(parents=True, exist_ok=True)
            (evidence_directory / "python-raw.json").write_text(
                json.dumps(raw, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8",
            )
        return result
    finally:
        reset_memory_search_tool_cooldowns()
        if reader_directory is not None:
            reader_directory.cleanup()


class _ControlledProviders:
    def __init__(self, value: dict[str, Any], clock: _ManualClock):
        self.input, self.clock = value, clock
        self.status = {**deepcopy(_CONTROLLED_STATUS), **deepcopy(value.get("status", {}))}
        self.lanes: dict[str, dict[str, Any]] = {}
        self.global_events: list[dict[str, Any]] = []
        self.memory_dispatches: list[dict[str, Any]] = []
        self.wiki_dispatches: dict[str, list[dict[str, Any]]] = {}
        self.memory_option_surfaces: list[dict[str, Any]] = []
        self.lock = threading.RLock()

    def lane(self, name: str) -> dict[str, Any]:
        with self.lock:
            return self.lanes.setdefault(name, {"records": [], "events": []})

    def log(self, lane: str, invocation: int, event: str, **data: Any) -> None:
        value = {"event": event, "invocation": invocation, "time": self.clock.clock(), **data}
        with self.lock:
            self.lane(lane)["events"].append(value)
            self.global_events.append({"lane": lane, **deepcopy(value)})

    def start(self, name: str, args: dict[str, Any], signal=None, options=None) -> Any:
        gate = _Deferred()
        with self.lock:
            records = self.lane(name)["records"]
            invocation = len(records) + 1
            record = {"gate": gate, "signal": signal, "options": options, "finished": False, "aborted": False}
            records.append(record)
            self.log(name, invocation, "start", args=deepcopy(args))

        def aborted():
            record["aborted"] = True
            reason = signal.reason
            self.log(name, invocation, "abort", reason=_public_error(reason) if isinstance(reason, BaseException) else reason)
            if self.input.get("abortBehavior") != "ignore":
                gate.complete(error=_fixture_error(self.input["abortError"]) if "abortError" in self.input else reason)

        if signal is not None:
            signal.add_listener(aborted)
        try:
            result = gate.result()
            self.log(name, invocation, "fulfilled", value=deepcopy(result))
            return result
        except BaseException as error:
            self.log(name, invocation, "rejected", error=_public_error(error),
                     sameAsSignalReason=signal is not None and error is signal.reason)
            raise
        finally:
            record["finished"] = True
            gate.finished.set()

    def wiki_search(self, identifier: str, arguments: dict[str, Any]) -> Any:
        names = {"max_results": "maxResults", "agent_id": "agentId",
                 "agent_session_key": "agentSessionKey"}
        query = {names.get(key, key): deepcopy(value) for key, value in arguments.items()}
        self.wiki_dispatches[identifier].append(query)
        return self.start(f"wiki:{identifier}", query)

    def wiki_read(self, identifier: str, arguments: dict[str, Any]) -> Any:
        names = {"from_line": "fromLine", "line_count": "lineCount", "agent_id": "agentId",
                 "agent_session_key": "agentSessionKey"}
        query = {names.get(key, key): deepcopy(value) for key, value in arguments.items()}
        self.wiki_dispatches[identifier].append(query)
        return self.start(f"wiki:{identifier}", query)


class _ControlledStore:
    supports_partial_results = True
    embeddings = None

    def __init__(self, config, providers: _ControlledProviders):
        self.config, self.providers = config, providers
        self.path, self.flags = config.resolved_store_path(), config.effective_flags()

    def index_identity(self):
        return {"status": "valid"}

    def status(self):
        return deepcopy(self.providers.status)

    def search(self, query, **options):
        names = {"max_results": "maxResults", "min_score": "minScore", "session_key": "sessionKey",
                 "active_project_keys": "activeProjectKeys", "sources": "sources"}
        args = {names[key]: list(value) if isinstance(value, set) else deepcopy(value)
                for key, value in options.items() if key in names and value is not None}
        args.update(signalPresent=options.get("signal") is not None,
                    partialCallbackPresent=callable(options.get("on_partial_results")),
                    deadlineControlPresent=options.get("deadline_control") is not None,
                    onDebugPresent=callable(options.get("on_debug")))
        self.providers.memory_dispatches.append({"query": query, "options": args})
        self.providers.memory_option_surfaces.append({"ownKeys": list(options),
                                                     "callableKeys": [key for key, item in options.items() if callable(item)]})
        return self.providers.start("memory", {"query": query, "options": args}, options.get("signal"), options)


class _UnusedSupplement:
    def search(self, **_query):
        raise RuntimeError("Controlled registered searches must use their actual native callback")

    def get(self, **_query):
        return None
