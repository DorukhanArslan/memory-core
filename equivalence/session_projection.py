"""Reuse retained transcript fixtures against the original native JSONL reader.

The old test modules are fixture sources only: their oracle adapters and expected
values never execute. This batch compares the host-supplied JSONL projection,
including raw source ordinals. The complete native JSONL projections cover the
transcript filtering outcomes point. Live SQLite branch selection, archive codecs
and host archive admission remain outside this batch; the boundaries point stays
open.
"""

from __future__ import annotations

import ast
from copy import deepcopy
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MTIME_MS = 1_800_000_000_000
_LEGACY = "tests/integration/test_openclaw_ts_oracle.py"
_TREE = "tests/integration/test_openclaw_transcript_tree_oracle.py"


def _fixture_namespace(relative: str, names: set[str]) -> dict[str, Any]:
    """Evaluate only named fixture declarations, never a legacy test or oracle."""
    source = ROOT / relative
    parsed = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    selected = []
    found = set()
    for node in parsed.body:
        name = node.name if isinstance(node, ast.FunctionDef) else None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            name = target.id if isinstance(target, ast.Name) else None
        if name in names:
            selected.append(node)
            found.add(name)
    if found != names:
        raise ValueError(f"Retained transcript fixture declarations changed: {relative}")
    namespace: dict[str, Any] = {"json": json, "copy": __import__("copy")}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(source), "exec"), namespace)
    return namespace


def _jsonl(events: list[Any]) -> str:
    return "\n".join(json.dumps(row, ensure_ascii=True) for row in events) + "\n"


def _case(name: str, arguments: dict[str, Any], source: str) -> dict[str, Any]:
    return {
        "id": f"session-projection-{name}",
        "requirement": "sessions.transcript-filtering",
        "operation": "session-projection",
        "input": {"mtimeMs": MTIME_MS, **deepcopy(arguments)},
        "covers": ([] if arguments.get("resetOnly")
                   else ["sessions.transcript-filtering.outcomes"]),
        "fixtureSource": source,
    }


def build_prospective_session_projection_cases() -> list[dict[str, Any]]:
    fixture = _fixture_namespace(_LEGACY, {
        "_sc_msg", "_sc_text", "_sc_case", "_SC_MTIME", "_SC_LONG", "_SC_BLOCKS",
        "SESSION_CORPUS_ENTRY_CASES", "_sm_row", "_sm_jsonl", "_sm_mock", "_sm_mirror",
        "_SM_RESET_AT", "_SM_RESET_LATER", "_SM_SANITIZE_TEXTS",
        "SESSION_MEMORY_TRANSCRIPT_CASES",
    })
    cases = [
        _case(f"legacy-corpus-{index:02d}", arguments, f"{_LEGACY}:SESSION_CORPUS_ENTRY_CASES[{index}]")
        for index, arguments in enumerate(fixture["SESSION_CORPUS_ENTRY_CASES"])
    ]
    # Reuse raw persisted rows (including malformed rows and delivery mirrors),
    # without importing the old recent-content policy or its expected result.
    seen: set[str] = set()
    for index, item in enumerate(fixture["SESSION_MEMORY_TRANSCRIPT_CASES"]):
        raw = item.get("content")
        if item["kind"] != "recent" or raw is None or raw in seen:
            continue
        seen.add(raw)
        cases.append(_case(f"legacy-recent-{index:02d}", {"jsonl": raw},
                           f"{_LEGACY}:SESSION_MEMORY_TRANSCRIPT_CASES[{index}]"))

    # The failed/empty/mirrored replay fixture is reused verbatim. Provider
    # labels are stored input only; both runners stay model-free.
    parsed = ast.parse((ROOT / _LEGACY).read_text(encoding="utf-8"))
    function = next(node for node in parsed.body if isinstance(node, ast.FunctionDef)
                    and node.name == "test_real_openclaw_oracle_normalize_assistant_replay_content_matches_python")
    assignments = [node for node in function.body if isinstance(node, ast.Assign)
                   and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                   and node.targets[0].id in {"zero_usage", "messages"}]
    namespace: dict[str, Any] = {}
    exec(compile(ast.Module(body=assignments, type_ignores=[]), _LEGACY, "exec"), namespace)
    cases.append(_case("legacy-failed-and-mirrored", {
        "jsonl": _jsonl([{"type": "message", "message": message}
                         for message in namespace["messages"]]),
    }, f"{_LEGACY}:test_real_openclaw_oracle_normalize_assistant_replay_content_matches_python"))

    # These exact persisted transcripts contain text on abandoned and side
    # branches. The native memory file reader exports physical file order;
    # runtime prompt tree selection is a separate contract.
    branch_source = "tests/unit/test_openclaw_session_corpus.py"
    branch_functions = {
        "test_openclaw_session_corpus_indexes_all_branches_in_file_order",
        "test_openclaw_session_corpus_indexes_side_append_entries_in_file_order",
        "test_openclaw_session_corpus_keeps_file_order_without_leaf_controls",
    }
    branch_module = ast.parse((ROOT / branch_source).read_text(encoding="utf-8"))
    for function in branch_module.body:
        if not isinstance(function, ast.FunctionDef) or function.name not in branch_functions:
            continue
        write = next(node for node in ast.walk(function) if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Attribute) and node.func.attr == "write_text")
        raw = eval(compile(ast.Expression(body=write.args[0]), branch_source, "eval"), {})
        name = function.name.removeprefix("test_openclaw_session_corpus_").replace("_", "-")
        cases.append(_case(name, {"jsonl": raw}, f"{branch_source}:{function.name}"))

    # Both usage-counted plain archive names reuse the malformed-ordinal fixture.
    # Codec/materialization and corpus admission are intentionally left open.
    for kind in ("reset", "deleted"):
        cases.append(_case(f"plain-{kind}-archive-ordinals", {
            **fixture["SESSION_CORPUS_ENTRY_CASES"][1],
            "filename": f"fixture.jsonl.{kind}.2026-02-16T22-26-33.000Z",
        }, f"{_LEGACY}:SESSION_CORPUS_ENTRY_CASES[1]"))

    trees = _fixture_namespace(_TREE, {"_cases"})["_cases"]()
    for index, item in enumerate(trees):
        cases.append(_case(f"legacy-raw-tree-{index:02d}", {
            "jsonl": _jsonl(item["entries"]), "resetEvents": item["entries"],
        }, f"{_TREE}:_cases()[{index}]"))

    unit_events = [
        {"type": "message", "message": {"role": "user", "content": "a"}},
        {"type": "custom"},
        {"type": "message", "message": {"role": "assistant", "content": "b"}},
    ]
    cases.append(_case("unit-line-map", {"jsonl": _jsonl(unit_events)},
                       "tests/unit/test_session_entry.py:test_entry_maps_lines_to_events_and_prefix_hash_matches"))
    for name, events in [
        ("unit-valid", [{"id": "k", "type": "message"},
                        {"type": "reset", "firstKeptEntryId": "k"}]),
        ("unit-missing", [{"type": "reset", "firstKeptEntryId": "x"}]),
        ("absent", []),
        ("no-kept-id", [{"type": "reset"}]),
        ("null-kept-id", [{"type": "reset", "firstKeptEntryId": None}]),
        ("empty-kept-id", [{"type": "reset", "firstKeptEntryId": " \t"}]),
    ]:
        cases.append(_case(f"reset-{name}", {"jsonl": _jsonl(events), "resetEvents": events},
                           "tests/unit/test_session_entry.py:test_reset_cutoff_and_inbound_metadata_and_date_parse"))
        cases.append(_case(f"reset-helper-{name}", {"resetOnly": True, "resetEvents": events},
                           "tests/unit/test_session_entry.py:test_reset_cutoff_and_inbound_metadata_and_date_parse"))
    return cases


def build_session_projection_cases() -> list[dict[str, Any]]:
    """Return all 79 fixtures verified against the native JSONL reader.

    The first complete native comparison is retained in
    .equivalence-results/session-completion-04-hosted-git-info.json. Earlier
    blocked reports remain separate. Reset helpers receive no outcomes credit,
    and archive codecs, admission and integrated reset fences remain unproved.
    """
    return build_prospective_session_projection_cases()


def run_session_projection(arguments: dict[str, Any]) -> dict[str, Any]:
    from memory_core.session_entry import (
        build_session_entry,
        matches_session_entry_prefix_hash,
        parse_jsonl_records,
        resolve_session_reset_recall_cutoff,
    )

    if arguments.get("resetOnly"):
        return {"resolvedResetCutoff": resolve_session_reset_recall_cutoff(arguments["resetEvents"])}

    observed = []
    entry = build_session_entry(
        records=parse_jsonl_records(arguments["jsonl"]),
        mtime_ms=arguments["mtimeMs"],
        session_kind=arguments.get("sessionKind", "unknown"),
        generated_by_dreaming_narrative=arguments.get("generatedByDreamingNarrative", False),
        generated_by_cron_run=arguments.get("generatedByCronRun", False),
        # The native raw-file reader has no SQLite generation metadata.
        reset_recall_cutoff={"state": "absent"},
        on_transcript_message=lambda message, at: observed.append({"message": message, "at": at}),
    )
    line_count = len(entry.line_map)
    return {
        "entry": {
            "content": entry.content,
            "lineMap": entry.line_map,
            "messageTimestampsMs": entry.message_timestamps_ms,
            "lineProvenance": entry.line_provenance,
            "hash": entry.hash,
            "sessionKind": entry.session_kind,
            "generatedByDreamingNarrative": entry.generated_by_dreaming_narrative,
            "generatedByCronRun": entry.generated_by_cron_run,
            "resetRecallCutoff": entry.reset_recall_cutoff,
        },
        "observed": observed,
        "prefixHashChecks": [matches_session_entry_prefix_hash(entry, count, entry.hash)
                             for count in (-1, 0, line_count, line_count + 1)],
        "resolvedResetCutoff": (resolve_session_reset_recall_cutoff(arguments["resetEvents"])
                                if "resetEvents" in arguments else None),
    }
