"""Reset-aware transcript navigation against the real v2026.9.6 TypeScript.

The kept-tail and stale-parent fixtures come from transcript-tree.test.ts. Variants
exercise reset boundary navigation, parentless rows, side appends and compaction
retention through the same public tree selectors. No agent or provider loop runs.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path

import pytest

from demo.openclaw_oracle import OpenClawOracle
from memory_core.transcript_tree import (
    UNSET,
    is_canonical_session_transcript_entry,
    is_session_transcript_side_append_entry,
    scan_session_transcript_tree,
    select_session_transcript_leaf_controlled_path,
    select_visible_transcript_events,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("OPENCLAW_ORACLE_REPO"),
    reason="OPENCLAW_ORACLE_REPO is not set",
)


def _cases():
    kept_tail = [
        {"type": "message", "id": "kept-user", "parentId": None},
        {"type": "message", "id": "kept-assistant", "parentId": "kept-user"},
        {
            "type": "reset",
            "id": "reset-boundary",
            "parentId": "kept-assistant",
            "firstKeptEntryId": "kept-user",
        },
        {"type": "message", "id": "branch-user", "parentId": None},
        {
            "type": "leaf",
            "id": "branch-leaf",
            "parentId": "reset-boundary",
            "targetId": "branch-user",
        },
    ]
    cases = [[], kept_tail[:3], kept_tail]
    for target in ("kept-user", "kept-assistant", "reset-boundary", None, "missing-stale-parent"):
        entries = copy.deepcopy(kept_tail)
        entries[-1]["targetId"] = target
        cases.append(entries)
    for parent in (None, "kept-user", "missing-stale-parent", "reset-boundary"):
        for side in (False, True):
            entries = copy.deepcopy(kept_tail)
            appended = {"type": "custom", "id": "continued", "parentId": parent}
            if side:
                appended["appendMode"] = "side"
            entries.append(appended)
            cases.append(entries)
    for first_kept in ("kept-user", "kept-assistant", "missing-stale-parent", None):
        entries = copy.deepcopy(kept_tail)
        entries[2]["firstKeptEntryId"] = first_kept
        cases.append(entries)
    parentless = copy.deepcopy(kept_tail)
    del parentless[2]["parentId"]
    cases.append(parentless)
    second_reset = copy.deepcopy(kept_tail)
    second_reset.extend(
        [
            {"type": "reset", "id": "second-reset", "parentId": "branch-user"},
            {"type": "leaf", "id": "second-leaf", "parentId": "second-reset", "targetId": "branch-user"},
        ]
    )
    cases.append(second_reset)
    cases.append(
        [
            {"type": "message", "id": "user", "parentId": None},
            {"type": "message", "id": "assistant", "parentId": "user"},
            {
                "type": "custom",
                "id": "bootstrap-context",
                "parentId": "missing-stale-parent",
                "customType": "openclaw:bootstrap-context:full",
            },
        ]
    )
    # A disjoint branch still retains the most recent reset/compaction boundary.
    for boundary_type in ("reset", "compaction"):
        entries = copy.deepcopy(kept_tail)
        entries[2]["type"] = boundary_type
        entries[3]["appendMode"] = "side"
        cases.append(entries)
    # Pre-reset invalid navigation remains invalid; reset must not erase its flag.
    cases.append(
        [
            kept_tail[0],
            {"type": "leaf", "id": "broken-leaf", "parentId": "kept-user", "targetId": "unknown-target"},
            *kept_tail[1:],
        ]
    )
    return [{"entries": entries} for entries in cases]


def _python_result(entries):
    tree = scan_session_transcript_tree(entries)
    return {
        "canonical": [is_canonical_session_transcript_entry(entry) for entry in entries],
        "sideAppend": [is_session_transcript_side_append_entry(entry) for entry in entries],
        "tree": {
            "leafId": tree.leaf_id,
            "appendParentId": tree.append_parent_id,
            "hasLeafControl": tree.has_leaf_control,
            "hasLeafUpdate": tree.has_leaf_update,
            "hasExplicitLeafUpdate": tree.has_explicit_leaf_update,
            "hasInvalidLeafControl": tree.has_invalid_leaf_control,
            "nodes": [
                {
                    "id": node.id,
                    "parentId": node.parent_id,
                    "leafId": None if node.leaf_id is UNSET else node.leaf_id,
                    "appendParentId": node.append_parent_id,
                    "appendMode": node.append_mode,
                    "index": node.index,
                }
                for node in tree.nodes
            ],
        },
        "leafControlledPath": select_session_transcript_leaf_controlled_path(entries),
        "visibleEvents": select_visible_transcript_events(entries),
    }


def test_reset_navigation_matches_pinned_transcript_tree_oracle():
    cases = _cases()
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))
    result = oracle.run({"operation": "transcriptTree", "cases": cases})
    assert result["ok"] is True
    expected = result["result"]["cases"]
    assert len(expected) == len(cases) == 26
    for index, (case, want) in enumerate(zip(cases, expected, strict=True)):
        assert _python_result(case["entries"]) == want, (index, case)
