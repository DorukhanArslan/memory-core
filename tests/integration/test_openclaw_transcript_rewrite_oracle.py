"""``rewriteTranscriptEntriesInSessionManager`` against the real v2026.9.6 TypeScript.

Each case builds a transcript on a real in-memory ``SessionManager`` (upstream) and on
:class:`memory_core.transcript_rewrite.TranscriptSessionManager` (Python) from the same entry
script, applies the same replacement rounds and compares: the result of every round, the active
branch, every stored entry, the append cursor and the persisted entry list including the leaf
controls. Ids are normalized (build labels stay, new entries become ``n1..``, leaf controls
``l1..``) and timestamps dropped; everything else, message and compaction fields included, must be
equal.
"""

from __future__ import annotations

import json
import os
import random
from pathlib import Path
from typing import Any

import pytest

from demo.openclaw_oracle import OpenClawOracle
from memory_core.transcript_rewrite import (
    UNDEFINED,
    TranscriptSessionManager,
    rewrite_transcript_entries_in_session_manager,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("OPENCLAW_ORACLE_REPO"),
    reason="OPENCLAW_ORACLE_REPO is not set",
)


def _clean(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _opt(spec: dict[str, Any], key: str) -> Any:
    return spec.get(key, UNDEFINED)


def _build(spec_entries: list[dict[str, Any]]) -> tuple[TranscriptSessionManager, dict[str, str]]:
    manager = TranscriptSessionManager("/work")
    ids: dict[str, str] = {}

    def real(label: Any) -> Any:
        return ids[label] if isinstance(label, str) and label in ids else label

    for spec in spec_entries:
        if spec.get("op") == "branch":
            manager.branch(real(spec["to"]))
            continue
        if spec.get("op") == "resetLeaf":
            manager.reset_leaf()
            continue
        kind = spec["type"]
        if kind == "message":
            entry_id = manager.append_message(_clean(spec["message"]))
        elif kind == "compaction":
            entry_id = manager.append_compaction(
                spec.get("summary", "summary"),
                real(_opt(spec, "firstKeptEntryId")),
                spec.get("tokensBefore", 100),
                _opt(spec, "details"),
                _opt(spec, "fromHook"),
                spec.get("identity"),
                _opt(spec, "tokensAfter"),
            )
        elif kind == "reset":
            entry_id = manager.append_reset_boundary(
                spec.get("reason", "new"), real(spec.get("firstKeptEntryId"))
            )
        elif kind == "thinking_level_change":
            entry_id = manager.append_thinking_level_change(spec["thinkingLevel"])
        elif kind == "model_change":
            entry_id = manager.append_model_change(spec["provider"], spec["modelId"])
        elif kind == "custom":
            entry_id = manager.append_custom_entry(spec["customType"], _opt(spec, "data"))
        elif kind == "custom_message":
            entry_id = manager.append_custom_message_entry(
                spec["customType"], spec["content"], spec.get("display", True), _opt(spec, "details")
            )
        elif kind == "session_info":
            entry_id = manager.append_session_info(spec.get("name", ""))
        elif kind == "branch_summary":
            parent = spec.get("parentId")
            entry_id = manager.branch_with_summary(
                None if parent is None else real(parent),
                spec.get("summary", "branch"),
                _opt(spec, "details"),
                _opt(spec, "fromHook"),
            )
        elif kind == "label":
            entry_id = manager.append_label_change(real(spec["targetId"]), _opt(spec, "label"))
        else:
            raise AssertionError(kind)
        if spec.get("id"):
            ids[spec["id"]] = entry_id
    return manager, ids


_ID_KEYS = ("id", "parentId", "firstKeptEntryId", "targetId", "appendParentId", "fromId")


def _python_case(case: dict[str, Any]) -> dict[str, Any]:
    manager, ids = _build(case["entries"])
    id_to_label = {value: key for key, value in ids.items()}
    counters = {"entry": 0, "leaf": 0}

    def label(entry_id: Any) -> Any:
        if not isinstance(entry_id, str):
            return entry_id
        if entry_id not in id_to_label:
            counters["entry"] += 1
            id_to_label[entry_id] = f"n{counters['entry']}"
        return id_to_label[entry_id]

    def real(entry_id: Any) -> Any:
        return ids[entry_id] if isinstance(entry_id, str) and entry_id in ids else entry_id

    rounds = case.get("rounds") or [
        {
            "replacements": case.get("replacements", []),
            "preserveReplacementCompactionReplay": case.get("preserveReplacementCompactionReplay"),
        }
    ]
    outcomes: list[dict[str, Any]] = []
    for round_ in rounds:
        replacements = []
        for item in round_.get("replacements", []):
            entry_id = item["entryId"]
            if isinstance(entry_id, dict):
                branch = manager.get_branch()
                index = entry_id["branchIndex"]
                entry_id = branch[index]["id"] if index < len(branch) else None
            else:
                entry_id = real(entry_id)
            replacements.append({"entryId": entry_id, "message": _clean(item["message"])})
        try:
            result = rewrite_transcript_entries_in_session_manager(
                session_manager=manager,
                replacements=replacements,
                preserve_replacement_compaction_replay=bool(
                    round_.get("preserveReplacementCompactionReplay")
                ),
            )
            outcome: dict[str, Any] = {
                "changed": result.changed,
                "bytesFreed": result.bytes_freed,
                "rewrittenEntries": result.rewritten_entries,
            }
            if result.reason is not None:
                outcome["reason"] = result.reason
        except (ValueError, RuntimeError, TypeError) as error:
            outcome = {"error": str(error)}
        outcomes.append(outcome)
        for entry in manager.get_entries():
            label(entry["id"])

    def norm(entry: dict[str, Any]) -> dict[str, Any]:
        out = dict(entry)
        out.pop("timestamp", None)
        for key in _ID_KEYS:
            if key in out:
                out[key] = "root" if key == "fromId" and out[key] == "root" else label(out[key])
        return _clean(out)

    entries = manager.get_entries()
    for entry in entries:
        label(entry["id"])
    persisted = []
    for entry in manager.get_persisted_entries():
        if entry["type"] == "session":
            continue
        if entry["type"] == "leaf":
            counters["leaf"] += 1
            id_to_label[entry["id"]] = f"l{counters['leaf']}"
        persisted.append(norm(entry))
    return {
        "outcomes": outcomes,
        "branch": [norm(entry) for entry in manager.get_branch()],
        "entries": [norm(entry) for entry in entries],
        "leafId": label(manager.get_leaf_id()),
        "appendParentId": label(manager.get_append_parent_id()),
        "appendMode": manager.get_append_mode(),
        "persisted": persisted,
    }


def _normalize_errors(case: dict[str, Any]) -> dict[str, Any]:
    """A JS TypeError (``Cannot read properties of ...``) and Python's compare equal by kind."""

    for outcome in case["outcomes"]:
        if "error" in outcome and "Cannot read properties" in outcome["error"]:
            outcome["error"] = "TypeError"
    return case


def _compare(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]), timeout_seconds=120)
    result = oracle.run({"operation": "transcriptRewrite", "cases": cases})
    assert result["ok"] is True
    expected = result["result"]["cases"]
    assert len(expected) == len(cases)
    for index, (case, want) in enumerate(zip(cases, expected, strict=True)):
        got = _normalize_errors(_python_case(case))
        want = _normalize_errors(want)
        assert got == want, f"case {index}: {json.dumps(case)[:300]}"
    return expected


# --- fixtures ---------------------------------------------------------------------------------


def _user(label: str, text: str = "hello", **extra: Any) -> dict[str, Any]:
    return {"id": label, "type": "message", "message": {"role": "user", "content": text, "timestamp": 1, **extra}}


def _assistant(label: str, text: str = "answer", calls: list[str] | None = None, **extra: Any) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    content += [{"type": "toolCall", "id": call, "name": "read", "arguments": {}} for call in calls or []]
    return {
        "id": label,
        "type": "message",
        "message": {"role": "assistant", "content": content, "timestamp": 2, **extra},
    }


def _result(label: str, call: str, text: str = "tool output") -> dict[str, Any]:
    return {
        "id": label,
        "type": "message",
        "message": {
            "role": "toolResult",
            "toolCallId": call,
            "toolName": "read",
            "content": [{"type": "text", "text": text}],
            "isError": False,
            "timestamp": 3,
        },
    }


def _replace(label: Any, message: dict[str, Any]) -> dict[str, Any]:
    return {"entryId": label, "message": message}


def _short_result(call: str, text: str = "[trimmed]") -> dict[str, Any]:
    return {
        "role": "toolResult",
        "toolCallId": call,
        "toolName": "read",
        "content": [{"type": "text", "text": text}],
        "isError": False,
        "timestamp": 3,
    }


CHECKPOINT = {"type": "anthropic-compaction", "replayIndex": 1}


def _scripted_cases() -> list[dict[str, Any]]:
    linear = [
        _user("u1"),
        _assistant("a1", calls=["c1"]),
        _result("r1", "c1", "x" * 400),
        _assistant("a2", "second"),
        _user("u2", "more"),
        _assistant("a3", "third"),
    ]
    return [
        {"entries": linear, "replacements": [_replace("r1", _short_result("c1"))]},
        {"entries": linear, "replacements": [_replace("u1", {"role": "user", "content": "x", "timestamp": 1})]},
        {"entries": linear, "replacements": [_replace("a3", {"role": "assistant", "content": [{"type": "text", "text": "z"}]})]},
        {"entries": linear, "replacements": []},
        {"entries": linear, "replacements": [_replace("  ", _short_result("c1")), _replace("", _short_result("c1"))]},
        {"entries": linear, "replacements": [_replace("ghost", _short_result("c1"))]},
        {"entries": linear, "replacements": [_replace("r1", linear[2]["message"])]},
        {"entries": [], "replacements": [_replace("r1", _short_result("c1"))]},
        {
            "entries": linear,
            "replacements": [_replace("r1", _short_result("c1", "first")), _replace("r1", _short_result("c1", "last"))],
        },
        {
            "entries": linear,
            "replacements": [_replace("r1", _short_result("c1")), _replace("a3", {"role": "assistant", "content": []})],
        },
        # Two rounds: the second names entries the first created.
        {
            "entries": linear,
            "rounds": [
                {"replacements": [_replace("r1", _short_result("c1"))]},
                {"replacements": [_replace({"branchIndex": 3}, {"role": "assistant", "content": [{"type": "text", "text": "short"}]})]},
                {"replacements": [_replace({"branchIndex": 9}, {"role": "user", "content": "none"})]},
            ],
        },
        # A stale replay checkpoint dies on re-append, and on the replacement unless preserved.
        {
            "entries": [
                _user("u1"),
                _assistant("a1", providerReplay=CHECKPOINT),
                _user("u2"),
                _assistant("a2", providerReplay={"type": "other", "replayIndex": 1}),
                _assistant("a3", providerReplay={"type": "openai-responses-compaction", "id": "x"}),
            ],
            "replacements": [
                _replace("u1", {"role": "user", "content": "changed"}),
                _replace("a2", {"role": "assistant", "content": [{"type": "text", "text": "n"}], "providerReplay": CHECKPOINT}),
            ],
        },
        {
            "entries": [_user("u1"), _assistant("a1", providerReplay=CHECKPOINT), _user("u2")],
            "replacements": [
                _replace("a1", {"role": "assistant", "content": [{"type": "text", "text": "n"}], "providerReplay": CHECKPOINT}),
            ],
            "preserveReplacementCompactionReplay": True,
        },
        {
            "entries": [_user("u1"), _assistant("a1", providerReplay=CHECKPOINT), _user("u2")],
            "replacements": [
                _replace("a1", {"role": "assistant", "content": [{"type": "text", "text": "n"}], "providerReplay": CHECKPOINT}),
            ],
        },
        # Compaction in the suffix: firstKeptEntryId follows the rewritten entry; identity and
        # optional fields survive; an unknown identity does not inherit.
        {
            "entries": [
                _user("u1"),
                _assistant("a1", calls=["c1"]),
                _result("r1", "c1", "y" * 300),
                _user("u2"),
                {"id": "k1", "type": "compaction", "firstKeptEntryId": "r1", "summary": "S", "tokensBefore": 900,
                 "details": {"files": ["a"]}, "fromHook": True, "tokensAfter": 120, "identity": {"runId": "run-1", "itemId": "it-1"}},
                _user("u3"),
                {"id": "k2", "type": "compaction", "firstKeptEntryId": "u3", "tokensBefore": 10, "identity": {"itemId": "only-item"}},
                {"id": "k3", "type": "compaction", "firstKeptEntryId": "ghost-id", "tokensBefore": 10},
                {"id": "k4", "type": "compaction", "firstKeptEntryId": "u3", "tokensBefore": 10, "identity": {"runId": ""}},
                _assistant("a4"),
            ],
            "replacements": [_replace("r1", _short_result("c1"))],
        },
        # Rewrite before a compaction whose kept entry lies before the rewrite.
        {
            "entries": [
                _user("u1"),
                _assistant("a1"),
                _user("u2"),
                {"id": "k1", "type": "compaction", "firstKeptEntryId": "u1", "summary": "S"},
                _assistant("a2", "after"),
            ],
            "replacements": [_replace("u2", {"role": "user", "content": "edited"})],
        },
        # Reset boundaries in the suffix, with and without a kept entry.
        {
            "entries": [
                _user("u1"),
                _assistant("a1", calls=["c1"]),
                _result("r1", "c1"),
                {"id": "z1", "type": "reset", "reason": "new", "firstKeptEntryId": "u1"},
                _user("u2"),
                {"id": "z2", "type": "reset", "reason": "reset"},
                _user("u3"),
                _assistant("a3"),
            ],
            "replacements": [_replace("a1", {"role": "assistant", "content": [{"type": "text", "text": "tiny"}]})],
        },
        {
            "entries": [
                _user("u1"),
                _assistant("a1"),
                {"id": "z1", "type": "reset", "reason": "new", "firstKeptEntryId": "a1"},
                _user("u2"),
                _assistant("a2"),
            ],
            "replacements": [_replace("u2", {"role": "user", "content": "e"})],
        },
        {
            "entries": [
                _user("u1"),
                _assistant("a1"),
                {"id": "z1", "type": "reset", "reason": "new", "firstKeptEntryId": "a1"},
                _user("u2"),
                _assistant("a2"),
            ],
            "replacements": [_replace("a1", {"role": "assistant", "content": [{"type": "text", "text": "e"}]})],
        },
        # Metadata and structural entries.
        {
            "entries": [
                _user("u1"),
                {"id": "t1", "type": "thinking_level_change", "thinkingLevel": "high"},
                {"id": "m1", "type": "model_change", "provider": "anthropic", "modelId": "claude"},
                _assistant("a1"),
                {"id": "x1", "type": "custom", "customType": "openclaw.cache-ttl", "data": {"timestamp": 5}},
                {"id": "x2", "type": "custom", "customType": "plain"},
                {"id": "cm1", "type": "custom_message", "customType": "note", "content": "hi", "display": False, "details": {"k": 1}},
                {"id": "cm2", "type": "custom_message", "customType": "note", "content": [{"type": "text", "text": "t"}]},
                {"id": "s1", "type": "session_info", "name": "My\r\n\nsession  "},
                {"id": "s2", "type": "session_info", "name": ""},
                {"id": "l1", "type": "label", "targetId": "a1", "label": "mark"},
                {"id": "l2", "type": "label", "targetId": "u1"},
                _user("u2"),
            ],
            "replacements": [_replace("u1", {"role": "user", "content": "changed first"})],
        },
        {
            "entries": [
                _user("u1"),
                _assistant("a1"),
                {"id": "l1", "type": "label", "targetId": "a1", "label": "mark"},
                {"id": "l2", "type": "label", "targetId": "a1", "label": "relabel"},
                {"id": "l3", "type": "label", "targetId": "a1"},
                _user("u2"),
            ],
            "replacements": [_replace("a1", {"role": "assistant", "content": [{"type": "text", "text": "e"}]})],
        },
        # Branch summaries.
        {
            "entries": [
                _user("u1"),
                _assistant("a1"),
                {"id": "b1", "type": "branch_summary", "parentId": "a1", "summary": "left", "details": {"d": 1}, "fromHook": False},
                _user("u2"),
                {"id": "b2", "type": "branch_summary", "parentId": None, "summary": "root"},
                _user("u3"),
            ],
            "replacements": [_replace("a1", {"role": "assistant", "content": [{"type": "text", "text": "e"}]})],
        },
        # Side branches: only the active branch rewrites; the abandoned one stays stored.
        {
            "entries": [
                _user("u1"),
                _assistant("a1"),
                _user("u2", "left"),
                _assistant("a2", "left reply"),
                {"op": "branch", "to": "a1"},
                _user("u3", "right"),
                _assistant("a3", "right reply"),
            ],
            "replacements": [_replace("u3", {"role": "user", "content": "right edited"})],
        },
        {
            "entries": [
                _user("u1"),
                _assistant("a1"),
                _user("u2", "left"),
                {"op": "branch", "to": "a1"},
                _user("u3", "right"),
            ],
            "replacements": [_replace("u2", {"role": "user", "content": "left edited"})],
        },
        {
            "entries": [
                _user("u1"),
                _assistant("a1"),
                {"op": "resetLeaf"},
                _user("u2", "second root"),
                _assistant("a2"),
            ],
            "replacements": [_replace("u2", {"role": "user", "content": "e"}), _replace("u1", {"role": "user", "content": "e"})],
        },
        {
            "entries": [_user("u1"), _assistant("a1"), {"op": "branch", "to": "u1"}, _assistant("a1b", "alt"), _user("u2")],
            "rounds": [
                {"replacements": [_replace("a1b", {"role": "assistant", "content": [{"type": "text", "text": "alt2"}]})]},
                {"replacements": [_replace({"branchIndex": 0}, {"role": "user", "content": "first"})]},
            ],
        },
        # Multi-byte text frees bytes by UTF-8 length, not by characters.
        {
            "entries": [_user("u1", "日本語のテキスト" * 20), _assistant("a1")],
            "replacements": [_replace("u1", {"role": "user", "content": "短い"})],
        },
        {
            "entries": [_user("u1", "emoji \U0001f600" * 30), _assistant("a1")],
            "replacements": [_replace("u1", {"role": "user", "content": "x"})],
        },
        # A larger replacement frees nothing.
        {"entries": linear, "replacements": [_replace("u1", {"role": "user", "content": "x" * 5000})]},
    ]


def _random_cases(count: int) -> list[dict[str, Any]]:
    rng = random.Random(2026_09_06)
    cases: list[dict[str, Any]] = []
    for _ in range(count):
        entries: list[dict[str, Any]] = []
        labels: list[str] = []
        message_labels: list[str] = []
        call_index = 0
        for position in range(rng.randint(3, 14)):
            label = f"e{position}"
            roll = rng.random()
            if roll < 0.2:
                entries.append(_user(label, "u" * rng.randint(1, 80)))
                message_labels.append(label)
            elif roll < 0.4:
                calls = [f"c{call_index}"] if rng.random() < 0.4 else []
                call_index += len(calls)
                extra = {"providerReplay": CHECKPOINT} if rng.random() < 0.3 else {}
                entries.append(_assistant(label, "a" * rng.randint(1, 80), calls, **extra))
                message_labels.append(label)
            elif roll < 0.55 and call_index:
                entries.append(_result(label, f"c{rng.randrange(call_index)}", "t" * rng.randint(1, 200)))
                message_labels.append(label)
            elif roll < 0.62 and labels:
                entries.append(
                    {"id": label, "type": "compaction", "firstKeptEntryId": rng.choice(labels), "summary": "S", "tokensBefore": 7,
                     **({"identity": {"runId": "r"}} if rng.random() < 0.4 else {}),
                     **({"tokensAfter": 3} if rng.random() < 0.3 else {})}
                )
            elif roll < 0.68 and labels:
                kept = rng.choice([*labels, None]) if rng.random() < 0.8 else None
                entries.append({"id": label, "type": "reset", "reason": rng.choice(["new", "reset"]), **({"firstKeptEntryId": kept} if kept else {})})
            elif roll < 0.72:
                entries.append({"id": label, "type": "thinking_level_change", "thinkingLevel": rng.choice(["low", "high"])})
            elif roll < 0.76:
                entries.append({"id": label, "type": "model_change", "provider": "p", "modelId": "m"})
            elif roll < 0.8:
                entries.append({"id": label, "type": "custom", "customType": "k", "data": {"n": position}})
            elif roll < 0.84:
                entries.append({"id": label, "type": "custom_message", "customType": "n", "content": "c", "display": rng.random() < 0.5})
            elif roll < 0.87:
                entries.append({"id": label, "type": "session_info", "name": rng.choice(["a", " b\n", ""])})
            elif roll < 0.92 and labels:
                entries.append(
                    {"id": label, "type": "label", "targetId": rng.choice(labels), **rng.choice([{"label": "x"}, {}])}
                )
            elif roll < 0.96 and labels:
                entries.append({"id": label, "type": "branch_summary", "parentId": rng.choice([*labels, None]), "summary": "bs"})
            elif labels:
                entries.append({"op": "branch", "to": rng.choice(labels)})
                continue
            else:
                entries.append({"op": "resetLeaf"})
                continue
            labels.append(label)
        if not message_labels:
            continue
        picks = rng.sample(message_labels, k=min(len(message_labels), rng.randint(1, 3)))
        replacements = [
            _replace(pick, {"role": "user", "content": "r" * rng.randint(1, 40), "timestamp": 9}) for pick in picks
        ]
        case: dict[str, Any] = {"entries": entries, "replacements": replacements}
        if rng.random() < 0.3:
            case["rounds"] = [
                {"replacements": replacements, "preserveReplacementCompactionReplay": rng.random() < 0.5},
                {"replacements": [_replace({"branchIndex": rng.randint(0, 6)}, {"role": "user", "content": "second"})]},
            ]
        cases.append(case)
    return cases


def test_scripted_rewrites_match_oracle():
    expected = _compare(_scripted_cases())
    # Premises: rewrites actually happened, and the interesting outcomes occur.
    outcomes = [outcome for case in expected for outcome in case["outcomes"]]
    assert sum(1 for outcome in outcomes if outcome.get("changed")) >= 20
    assert {outcome.get("reason") for outcome in outcomes} >= {
        "no replacements requested",
        "empty session",
        "no changed matching message entries",
    }
    assert any(outcome.get("bytesFreed", 0) > 0 for outcome in outcomes)
    assert any(entry["type"] == "leaf" for case in expected for entry in case["persisted"])


def test_random_rewrites_match_oracle():
    cases = _random_cases(300)
    assert len(cases) > 250
    expected = _compare(cases)
    outcomes = [outcome for case in expected for outcome in case["outcomes"]]
    assert sum(1 for outcome in outcomes if outcome.get("changed")) > 150
    # The only failures are second-round replacements naming a branch index that does not exist.
    assert {outcome["error"] for outcome in outcomes if "error" in outcome} <= {"TypeError"}
