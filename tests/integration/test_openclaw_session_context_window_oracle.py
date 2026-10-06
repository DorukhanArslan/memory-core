"""The reset boundary of the session context window against the real v2026.9.6 TypeScript.

``selectResetKeptEntries`` (tool-result-pairing.ts) and ``iterateSessionContextEntries``
(session.ts) run over scripted and seeded-random entry lists; Python must select the same entries
(by index) with the same context kind.
"""

from __future__ import annotations

import os
import random
from pathlib import Path
from typing import Any

import pytest

from demo.openclaw_oracle import OpenClawOracle
from memory_core.session_context_window import (
    iterate_session_context_entries,
    select_reset_kept_entries,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("OPENCLAW_ORACLE_REPO"),
    reason="OPENCLAW_ORACLE_REPO is not set",
)


def _msg(entry_id: str, message: dict[str, Any]) -> dict[str, Any]:
    return {"type": "message", "id": entry_id, "parentId": None, "message": message}


def _user(entry_id: str, text: str = "hi", **extra: Any) -> dict[str, Any]:
    return _msg(entry_id, {"role": "user", "content": text, **extra})


def _assistant(entry_id: str, calls: list[tuple[str, str]] | None = None, **extra: Any) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "text", "text": "ok"}]
    for call_id, name in calls or []:
        content.append({"type": "toolCall", "id": call_id, "name": name, "arguments": {}})
    extra = {key: value for key, value in extra.items() if value is not None}
    return _msg(entry_id, {"role": "assistant", "content": content, **extra})


def _result(entry_id: str, call_id: str | None, name: str = "read", **extra: Any) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": "toolResult",
        "toolName": name,
        "content": [{"type": "text", "text": "out"}],
        "isError": False,
        **extra,
    }
    if call_id is not None:
        message["toolCallId"] = call_id
    return _msg(entry_id, message)


def _boundary(kind: str, entry_id: str, first_kept: str | None, **extra: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {"type": kind, "id": entry_id, "parentId": None, **extra}
    if kind == "reset":
        entry.setdefault("reason", "new")
    else:
        entry.setdefault("summary", "s")
        entry.setdefault("tokensBefore", 10)
    if first_kept is not None:
        entry["firstKeptEntryId"] = first_kept
    return entry


def _python(entries: list[dict[str, Any]]) -> dict[str, Any]:
    index_of = {id(entry): index for index, entry in enumerate(entries)}
    return {
        "resetKept": [index_of[id(entry)] for entry in select_reset_kept_entries(entries)],
        "window": [
            {"index": index_of[id(entry)], "context": context}
            for entry, context in iterate_session_context_entries(entries)
        ],
    }


def _compare(cases: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))
    result = oracle.run(
        {"operation": "sessionContextWindow", "cases": [{"entries": entries} for entries in cases]}
    )
    assert result["ok"] is True
    expected = result["result"]["cases"]
    assert len(expected) == len(cases)
    for index, (entries, want) in enumerate(zip(cases, expected, strict=True)):
        assert _python(entries) == want, f"case {index}"
    return expected


def _custom_message(entry_id: str) -> dict[str, Any]:
    return {
        "type": "custom_message",
        "id": entry_id,
        "parentId": None,
        "customType": "x",
        "content": "c",
        "display": True,
    }


def _scripted_cases() -> list[list[dict[str, Any]]]:
    paired = [
        _user("u1"),
        _assistant("a1", [("c1", "read"), ("c2", "write")]),
        _result("r1", "c1"),
        _result("r2", "c2"),
        _user("u2", "later"),
    ]
    return [
        # No boundary at all.
        paired,
        # Compaction keeps every message-like entry from firstKeptEntryId on.
        [*paired, _boundary("compaction", "k1", "a1"), _user("u3"), _assistant("a3")],
        [*paired, _boundary("compaction", "k1", None), _user("u3")],
        [*paired, _boundary("compaction", "k1", "missing"), _user("u3")],
        # A reset keeps the retained tail's user/assistant messages and paired results only.
        [*paired, _boundary("reset", "z1", "u1"), _user("u3")],
        [*paired, _boundary("reset", "z1", "a1"), _user("u3")],
        [*paired, _boundary("reset", "z1", "r1"), _user("u3")],
        [*paired, _boundary("reset", "z1", None), _user("u3")],
        [*paired, _boundary("reset", "z1", "missing"), _user("u3")],
        [*paired, _boundary("reset", "z1", "u1")],
        # Orphan, duplicate and displaced tool results are not paired.
        [
            _user("u1"),
            _result("r0", "ghost"),
            _assistant("a1", [("c1", "read")]),
            _result("r1", "c1"),
            _result("r1b", "c1"),
            _result("r2", None),
            _boundary("reset", "z1", "u1"),
        ],
        # A result displaced to a later frame crosses only when one open call can own it.
        [
            _assistant("a1", [("c1", "read")]),
            _user("u1"),
            _assistant("a2", [("c2", "read")]),
            _result("r1", "c1"),
            _result("r2", "c2"),
            _boundary("reset", "z1", "a1"),
        ],
        # Legacy result without an id inherits a lone call; mismatched names do not.
        [
            _assistant("a1", [("c1", "read")]),
            _result("r1", None, name="read"),
            _assistant("a2", [("c2", "read")]),
            _result("r2", None, name="exec"),
            _boundary("reset", "z1", "a1"),
        ],
        # Context exclusion: dropped in the current tail, kept by an explicit reset retention.
        [
            _user("u1", "old", excludeFromContext=True),
            _assistant("a1", excludeFromContext=True),
            _user("u2"),
            _boundary("reset", "z1", "u1"),
            _user("u3", "new", excludeFromContext=True),
            _user("u4"),
        ],
        [
            _user("u1", "old", excludeFromContext=True),
            _user("u2"),
            _boundary("compaction", "k1", "u1"),
            _user("u3", "new", excludeFromContext=True),
        ],
        # Non-message entries inside and outside the window.
        [
            _user("u1"),
            _custom_message("cm1"),
            {"type": "branch_summary", "id": "bs1", "parentId": None, "fromId": "u1", "summary": "b"},
            {"type": "model_change", "id": "m1", "parentId": None, "provider": "p", "modelId": "m"},
            {"type": "custom", "id": "cu1", "parentId": None, "customType": "x"},
            _boundary("reset", "z1", "u1"),
            _custom_message("cm2"),
        ],
        # Several boundaries: the last one wins, earlier ones inside the tail are skipped.
        [
            _user("u1"),
            _boundary("compaction", "k1", "u1"),
            _user("u2"),
            _assistant("a2", [("c9", "read")]),
            _result("r9", "c9"),
            _boundary("reset", "z1", "u2"),
            _user("u3"),
            _boundary("compaction", "k2", "u3"),
            _user("u4"),
        ],
        # firstKeptEntryId pointing at or after the boundary falls back to the boundary.
        [*paired, _boundary("reset", "z1", "z1"), _user("u3")],
        [*paired, _boundary("reset", "z1", "u3"), _user("u3")],
        # Failed assistant frames still own their results.
        [
            _user("u1"),
            _assistant("a1", [("c1", "read")], stopReason="error"),
            _result("r1", "c1"),
            _boundary("reset", "z1", "u1"),
        ],
        [],
    ]


def _random_cases(count: int) -> list[list[dict[str, Any]]]:
    rng = random.Random(9_6_2026)
    cases: list[list[dict[str, Any]]] = []
    for _ in range(count):
        entries: list[dict[str, Any]] = []
        call_pool: list[str] = []
        for position in range(rng.randint(3, 16)):
            entry_id = f"e{position}"
            roll = rng.random()
            if roll < 0.2:
                entries.append(_user(entry_id, excludeFromContext=rng.random() < 0.2))
            elif roll < 0.45:
                calls = [(f"c{position}_{n}", rng.choice(["read", "exec"])) for n in range(rng.randint(0, 2))]
                call_pool.extend(call_id for call_id, _name in calls)
                entries.append(_assistant(entry_id, calls, stopReason=rng.choice([None, "stop", "error"])))
            elif roll < 0.75:
                pick = rng.choice(call_pool) if call_pool and rng.random() < 0.8 else rng.choice(["x", None])
                entries.append(_result(entry_id, pick, name=rng.choice(["read", "exec", ""])))
            elif roll < 0.82:
                entries.append(_custom_message(entry_id))
            elif roll < 0.9:
                kept = rng.choice([e["id"] for e in entries] + ["nope", None]) if entries else None
                entries.append(_boundary(rng.choice(["reset", "compaction"]), entry_id, kept))
            else:
                entries.append({"type": "label", "id": entry_id, "parentId": None, "targetId": "e0"})
        cases.append(entries)
    return cases


def test_context_window_scripted_cases_match_oracle():
    expected = _compare(_scripted_cases())
    # Premise checks: a reset retains the paired tail; an orphan result is cut from it.
    assert [item["context"] for item in expected[4]["window"]].count("reset-retained") == 5
    assert 1 not in expected[10]["resetKept"], "the orphan tool result is not retained"
    assert [item["index"] for item in expected[10]["window"]][:2] == [6, 0]


def test_context_window_random_cases_match_oracle():
    expected = _compare(_random_cases(400))
    contexts = {item["context"] for case in expected for item in case["window"]}
    assert contexts == {"current", "retained", "reset-retained"}
