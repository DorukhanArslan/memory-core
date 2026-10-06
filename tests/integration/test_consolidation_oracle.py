"""Oracle tests of the opt-in LLM consolidation step against the real OpenClaw v2026.9.6 module.

``consolidateMemory`` op: the runner drives ``consolidateMemoryForTests``
(extensions/memory-core/src/test-helpers.ts) and ``applyMemoryConsolidationPlan``
(dreaming-consolidation.ts) with a stubbed model; Python runs
memory_core.consolidation.llm_consolidation with the same stub. Prompts, plans, applied
MEMORY.md bytes and warnings must be equal.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from demo.openclaw_oracle import OpenClawOracle
from memory_core.consolidation import (
    CONSOLIDATION_SYSTEM_PROMPT,
    PromotionCandidate,
    apply_memory_consolidation_plan,
    consolidate_memory,
)
from memory_core.consolidation.llm_consolidation import (
    ConsolidationOperation,
    ConsolidationRequest,
    MemoryConsolidationPlan,
)
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY

NOW_MS = 1782986400000  # 2026-07-02T10:00:00Z
SRC = "Source: memory/2026-07-01.md#L1-L1"
ANNOTATIONS = "<!-- trigger: preference --> <!-- importance: 9 -->"


def cand(
    key: str,
    snippet: str,
    project: str | None = None,
    *,
    path: str = "memory/2026-07-01.md",
    provenance: dict[str, Any] | None = None,
    score: float = 0.9,
    tags: tuple[str, ...] = ("preference",),
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "key": key,
        "path": path,
        "startLine": 1,
        "endLine": 1,
        "source": "memory",
        "snippet": snippet,
        "recallCount": 3,
        "signalCount": 3,
        "avgScore": 0.9,
        "maxScore": 0.9,
        "uniqueQueries": 2,
        "firstRecalledAt": "2026-07-01T10:00:00.000Z",
        "lastRecalledAt": "2026-07-01T10:00:00.000Z",
        "ageDays": 0,
        "score": score,
        "recallDays": ["2026-07-01", "2026-07-02"],
        "conceptTags": list(tags),
        "components": {"frequency": 1},
    }
    if project:
        out["projectKey"] = project
    out["provenance"] = provenance or {
        "originClass": "agent",
        "sessionKind": "interactive",
        "observedAt": 1782900000000,
    }
    return out


def reply(*operations: tuple[str, str, list[str]]) -> str:
    return json.dumps(
        {
            "operations": [
                {"candidateKey": key, "action": action, "priorEntries": prior}
                for key, action, prior in operations
            ]
        }
    )


def entry(text: str, project: str | None = None) -> str:
    tail = f" <!-- project: {project} -->" if project else ""
    return f"- {text}{tail}"


def lineage_block(lineage: str, key: str, text: str) -> str:
    return (
        f"<!-- openclaw-memory-lineage:{lineage} -->\n"
        f"<!-- openclaw-memory-promotion:{key} -->\n"
        f"- {text} {SRC} {ANNOTATIONS}"
    )


def _scenarios() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    base_memory = "# Memory\n\n- Existing global fact.\n- Prefers tabs over spaces.\n"

    # --- plan application -------------------------------------------------------------
    out["added"] = {
        "existingMemory": base_memory,
        "candidates": [cand("a", "Use metric units globally.")],
        "replies": [reply(("a", "added", []))],
        "expect": {"plan": True, "applied": True},
    }
    out["merged_duplicate"] = {
        "existingMemory": base_memory,
        "candidates": [cand("m", "- Prefers   tabs over spaces.")],
        "replies": [reply(("m", "merged", ["- Prefers tabs over spaces."]))],
        "expect": {"plan": True, "applied": True},
    }
    out["merged_unrelated_rejected"] = {
        "existingMemory": base_memory,
        "candidates": [cand("m", "Prefers dark mode.")],
        "replies": [reply(("m", "merged", ["- Existing global fact."]))],
        "expect": {"plan": False},
    }
    lineage_memory = (
        "# Memory\n\n"
        + lineage_block("db-host", "old", "Database host is db1.")
        + "\n- Other fact.\n"
    )
    stale_entry = f"- Database host is db1. {SRC} {ANNOTATIONS}"
    sup = cand(
        "new",
        "Database host is db2.",
        provenance={"originClass": "owner", "supersedesKey": "db-host"},
    )
    out["superseded_lineage"] = {
        "existingMemory": lineage_memory,
        "candidates": [sup],
        "replies": [reply(("new", "superseded", [stale_entry]))],
        "expect": {"plan": True, "applied": True},
    }
    out["superseded_wrong_entry"] = {
        "existingMemory": lineage_memory,
        "candidates": [sup],
        "replies": [reply(("new", "superseded", ["- Other fact."]))],
        "expect": {"plan": False},
    }
    out["stale_lineage_left_by_added"] = {
        "existingMemory": lineage_memory,
        "candidates": [sup],
        "replies": [reply(("new", "added", []))],
        "expect": {"plan": False},
    }
    out["superseded_without_lineage"] = {
        "existingMemory": base_memory,
        "candidates": [cand("n", "Fact.")],
        "replies": [reply(("n", "superseded", ["- Existing global fact."]))],
        "expect": {"plan": False},
    }
    out["merged_lineage_inherited"] = {
        "existingMemory": "# Memory\n\n"
        + lineage_block("db-host", "old", "Database host is db1.")
        + "\n",
        "candidates": [cand("same", "Database host is db1.", provenance={"originClass": "owner"})],
        "replies": [reply(("same", "merged", [stale_entry]))],
        "expect": {"plan": True, "applied": True},
    }
    out["empty_memory_header"] = {
        "existingMemory": "",
        "candidates": [cand("a", "First fact.")],
        "replies": [reply(("a", "added", []))],
        "expect": {"plan": True, "applied": True},
    }
    out["crlf_memory"] = {
        "existingMemory": "# Memory\r\n\r\n- Fact one.\r\n- Fact two.\r\n",
        "candidates": [cand("c", "Fact one.")],
        "replies": [reply(("c", "merged", ["- Fact one."]))],
        "expect": {"plan": True, "applied": True},
    }
    many = [cand(f"k{i}", f"Distinct fact number {i}.") for i in range(10)]
    out["highlights_capped_at_eight"] = {
        "existingMemory": base_memory,
        "candidates": many,
        "replies": [reply(*[(f"k{i}", "added", []) for i in range(10)])],
        "memoryFileMaxChars": 20000,
        "expect": {"plan": True, "applied": True},
    }
    out["duplicate_result_entry_appended_once"] = {
        "existingMemory": base_memory,
        "candidates": [cand("d1", "Same text."), cand("d2", "Same text.")],
        "replies": [reply(("d1", "added", []), ("d2", "added", []))],
        "expect": {"plan": True, "applied": True},
    }
    out["added_already_present_result"] = {
        "existingMemory": f"# Memory\n\n- Same text. {SRC} {ANNOTATIONS}\n",
        "candidates": [cand("p", "Same text.")],
        "replies": [reply(("p", "added", []))],
        "expect": {"plan": False},
    }
    out["prior_entry_with_continuation"] = {
        "existingMemory": "# Memory\n\n- Wrapped fact\n  continues here.\n- Other.\n",
        "candidates": [cand("w", "Wrapped fact")],
        "replies": [reply(("w", "merged", ["- Wrapped fact"]))],
        "expect": {"plan": False},
    }
    out["prior_entry_duplicated_in_memory"] = {
        "existingMemory": "# Memory\n\n- Twin.\n- Twin.\n- x\n- y\n- z\n",
        "candidates": [cand("t", "Twin.")],
        "replies": [reply(("t", "merged", ["- Twin."]))],
        "expect": {"plan": False},
    }
    out["prior_entries_trimmed"] = {
        "existingMemory": base_memory,
        "candidates": [cand("m", "Prefers tabs over spaces.")],
        "replies": [reply(("m", "merged", ["  - Prefers tabs over spaces.\t"]))],
        "expect": {"plan": True, "applied": True},
    }
    out["only_punctuation_snippet"] = {
        "existingMemory": base_memory,
        "candidates": [cand("z", "...", tags=())],
        "replies": [reply(("z", "added", []))],
        "expect": {"plan": False},
    }
    out["unicode_snippet"] = {
        "existingMemory": base_memory,
        "candidates": [cand("u", "Kullanici Istanbul'da \U0001f600 yasiyor, café nächste.")],
        "replies": [reply(("u", "added", []))],
        "expect": {"plan": True, "applied": True},
    }

    # --- malformed model output -------------------------------------------------------
    good = reply(("a", "added", []))
    malformed: dict[str, Any] = {
        "not_json": "I would add it.",
        "empty_string": "",
        "fenced_json": f"```json\n{good}\n```",
        "json_array": "[]",
        "json_null": "null",
        "operations_missing": "{}",
        "operations_not_array": json.dumps({"operations": "a"}),
        "operations_empty": json.dumps({"operations": []}),
        "operation_not_object": json.dumps({"operations": ["a"]}),
        "unknown_candidate": reply(("zzz", "added", [])),
        "bad_action": json.dumps(
            {"operations": [{"candidateKey": "a", "action": "deleted", "priorEntries": []}]}
        ),
        "prior_not_array": json.dumps(
            {"operations": [{"candidateKey": "a", "action": "added", "priorEntries": "x"}]}
        ),
        "prior_non_string": json.dumps(
            {"operations": [{"candidateKey": "a", "action": "added", "priorEntries": [1]}]}
        ),
        "key_not_string": json.dumps(
            {"operations": [{"candidateKey": 1, "action": "added", "priorEntries": []}]}
        ),
        "duplicate_operation": reply(("a", "added", []), ("a", "added", [])),
        "nan_constant": '{"operations": NaN}',
        "extra_fields_ignored": json.dumps(
            {
                "operations": [
                    {
                        "candidateKey": "a",
                        "action": "added",
                        "priorEntries": [],
                        "resultEntry": "- model prose that must be ignored",
                    }
                ],
                "commentary": "x",
            }
        ),
        "added_with_prior": reply(("a", "added", ["- Existing global fact."])),
        "merged_without_prior": reply(("a", "merged", [])),
        "prior_not_in_memory": reply(("a", "merged", ["- Not there."])),
    }
    for name, text in malformed.items():
        out[f"malformed_{name}"] = {
            "existingMemory": base_memory,
            "candidates": [cand("a", "Fact A.")],
            "replies": [text],
            "expect": {"plan": name == "extra_fields_ignored"},
        }
    out["malformed_throws"] = {
        "existingMemory": base_memory,
        "candidates": [cand("a", "Fact A.")],
        "replies": [{"throw": "model unavailable"}],
        "expect": {"plan": False},
    }
    out["malformed_raw_non_string"] = {
        "existingMemory": base_memory,
        "candidates": [cand("a", "Fact A.")],
        "replies": [{"raw": {"text": 5}}],
        "expect": {"plan": False},
    }
    out["malformed_raw_undefined"] = {
        "existingMemory": base_memory,
        "candidates": [cand("a", "Fact A.")],
        "replies": [{"raw": {}}],
        "expect": {"plan": False},
    }
    out["malformed_one_group_fails_all_groups_still_asked"] = {
        "existingMemory": base_memory,
        "candidates": [cand("g", "Global."), cand("a", "Alpha.", "github.com/acme/alpha")],
        "replies": ["nonsense", reply(("a", "added", []))],
        "expect": {"plan": False},
    }

    # --- candidate eligibility --------------------------------------------------------
    out["no_candidates"] = {
        "existingMemory": base_memory,
        "candidates": [],
        "replies": [],
        "expect": {"plan": False},
    }
    out["untrusted_origin_filtered"] = {
        "existingMemory": base_memory,
        "candidates": [
            cand("u", "Untrusted.", provenance={"originClass": "untrusted"}),
            cand("s", "System.", provenance={"originClass": "system"}),
            cand("n", "No provenance.", provenance={"sessionKind": "interactive"}),
        ],
        "replies": [],
        "expect": {"plan": False},
    }
    out["session_derived_needs_interactive"] = {
        "existingMemory": base_memory,
        "candidates": [
            cand(
                "cron",
                "Cron derived.",
                path="memory/.dreams/session-corpus/2026-07-01.txt",
                provenance={"originClass": "agent", "sessionKind": "cron"},
            ),
            cand(
                "inter",
                "Interactive derived.",
                path="memory/.dreams/session-corpus/2026-07-01.txt",
                provenance={"originClass": "agent", "sessionKind": "interactive"},
            ),
            cand(
                "sess",
                "Sessions path.",
                path="sessions\\agent\\a.md",
                provenance={"originClass": "owner", "sessionKind": "heartbeat"},
            ),
        ],
        "replies": [reply(("inter", "added", []))],
        "expect": {"plan": True, "applied": True},
    }

    # --- project scoping --------------------------------------------------------------
    project_candidates = [
        cand("beta", "Beta deployment uses blue.", "github.com/acme/beta"),
        cand("global", "Use metric units globally."),
        cand("alpha", "Alpha deployment uses green.", "github.com/acme/alpha"),
    ]
    out["project_groups_isolated_passes"] = {
        "existingMemory": "# Memory\n\n- Existing global fact.\n",
        "candidates": project_candidates,
        "replies": [
            reply(("global", "added", [])),
            reply(("alpha", "added", [])),
            reply(("beta", "added", [])),
        ],
        "memoryFileMaxChars": 20000,
        "model": "stub-model",
        "expect": {"plan": True, "applied": True},
    }
    beta_prior = "- Shared deployment uses blue. <!-- project: github.com/acme/beta -->"
    out["project_cross_project_merge_rejected"] = {
        "existingMemory": f"# Memory\n\n{beta_prior}\n- Two.\n- Three.\n- Four.\n",
        "candidates": [
            cand("beta", "Beta deployment uses blue.", "github.com/acme/beta"),
            cand("global", "Use metric units globally."),
            cand("alpha", "Shared deployment uses blue.", "github.com/acme/alpha"),
        ],
        "replies": [
            reply(("global", "added", [])),
            reply(("alpha", "merged", [beta_prior])),
            reply(("beta", "added", [])),
        ],
        "expect": {"plan": False},
    }
    out["project_same_group_merge_accepted"] = {
        "existingMemory": f"# Memory\n\n{beta_prior}\n- Two.\n- Three.\n- Four.\n",
        "candidates": [cand("beta", "Shared deployment uses blue.", "github.com/acme/beta")],
        "replies": [reply(("beta", "merged", [beta_prior]))],
        "expect": {"plan": True, "applied": True},
    }
    out["project_global_cannot_touch_project_entry"] = {
        "existingMemory": f"# Memory\n\n{beta_prior}\n- Two.\n- Three.\n- Four.\n",
        "candidates": [cand("g", "Shared deployment uses blue.")],
        "replies": [reply(("g", "merged", [beta_prior]))],
        "expect": {"plan": False},
    }
    out["project_multi_key_and_invalid_annotations"] = {
        "existingMemory": (
            "# Memory\n\n- Multi. <!-- project: GitHub.com/Acme/Beta; github.com/acme/alpha -->\n"
            "- Broken. <!-- project: -->\n- Open. <!-- project: x\n- Fine.\n- Fine two.\n"
        ),
        "candidates": [cand("m", "Multi.", "github.com/acme/alpha")],
        "replies": [reply(("m", "merged", ["- Broken. <!-- project: -->"]))],
        "expect": {"plan": False},
    }
    out["project_key_with_angle_brackets_is_global"] = {
        "existingMemory": base_memory,
        "candidates": [cand("x", "Odd project key.", "bad<key>")],
        "replies": [reply(("x", "added", []))],
        "expect": {"plan": True, "applied": True},
    }
    out["project_path_keys"] = {
        "existingMemory": "# Memory\n\n- Local. <!-- project: path:/work/app -->\n- b\n- c\n- d\n",
        "candidates": [cand("l", "Local.", "path:/work/app")],
        "replies": [reply(("l", "merged", ["- Local. <!-- project: path:/work/app -->"]))],
        "expect": {"plan": True, "applied": True},
    }

    # --- budget and loss limits -------------------------------------------------------
    out["budget_exceeded_by_aggregate"] = {
        "existingMemory": "# Memory\n",
        "candidates": [
            cand("global", "Use metric units globally."),
            cand("alpha", "Alpha deployment uses green.", "github.com/acme/alpha"),
        ],
        "replies": [reply(("global", "added", [])), reply(("alpha", "added", []))],
        "memoryFileMaxChars": 330,
        "expect": {"plan": False},
    }
    out["budget_exact_fit"] = {
        "existingMemory": "# Memory\n",
        "candidates": [cand("global", "Use metric units globally.")],
        "replies": [reply(("global", "added", []))],
        "memoryFileMaxChars": 10000,
        "expect": {"plan": True, "applied": True},
    }
    out["budget_tiny_and_fractional"] = {
        "existingMemory": "# Memory\n",
        "candidates": [cand("global", "Use metric units globally.")],
        "replies": [reply(("global", "added", []))],
        "memoryFileMaxChars": 0.5,
        "expect": {"plan": False},
    }
    out["loss_fraction_exceeded"] = {
        "existingMemory": "# Memory\n\n- One.\n- Two.\n- Three.\n- Four.\n",
        "candidates": [cand("a", "One."), cand("b", "Two.")],
        "replies": [reply(("a", "merged", ["- One."]), ("b", "merged", ["- Two."]))],
        "maxPriorEntryLossFraction": 0.25,
        "expect": {"plan": False},
    }
    out["loss_fraction_allows_half"] = {
        "existingMemory": "# Memory\n\n- One.\n- Two.\n- Three.\n- Four.\n",
        "candidates": [cand("a", "One."), cand("b", "Two.")],
        "replies": [reply(("a", "merged", ["- One."]), ("b", "merged", ["- Two."]))],
        "maxPriorEntryLossFraction": 0.5,
        "expect": {"plan": True, "applied": True},
    }
    out["loss_fraction_zero"] = {
        "existingMemory": "# Memory\n\n- One.\n",
        "candidates": [cand("a", "One.")],
        "replies": [reply(("a", "merged", ["- One."]))],
        "maxPriorEntryLossFraction": 0,
        "expect": {"plan": False},
    }
    long_snippet = "Long fact sentence number one. " * 30 + "Tail " * 40
    out["snippet_token_cap"] = {
        "existingMemory": "# Memory\n",
        "candidates": [cand("long", long_snippet)],
        "replies": [reply(("long", "added", []))],
        "maxPromotedSnippetTokens": 10,
        "memoryFileMaxChars": 20000,
        "expect": {"plan": True, "applied": True},
    }
    out["snippet_token_cap_floor_one"] = {
        "existingMemory": "# Memory\n",
        "candidates": [cand("long", "\U0001f600\U0001f600\U0001f600 emoji cut test")],
        "replies": [reply(("long", "added", []))],
        "maxPromotedSnippetTokens": 0.4,
        "expect": {"plan": False},
    }
    out["snippet_token_cap_floor_one_letters"] = {
        "existingMemory": "# Memory\n",
        "candidates": [cand("long", "ab\U0001f600\U0001f600 emoji cut test")],
        "replies": [reply(("long", "added", []))],
        "maxPromotedSnippetTokens": 0.4,
        "expect": {"plan": True, "applied": True},
    }
    out["snippet_default_cap"] = {
        "existingMemory": "# Memory\n",
        "candidates": [cand("long", long_snippet * 3)],
        "replies": [reply(("long", "added", []))],
        "memoryFileMaxChars": 20000,
        "expect": {"plan": True, "applied": True},
    }
    out["importance_and_trigger_annotations"] = {
        "existingMemory": "# Memory\n",
        "candidates": [
            cand("lo", "Low score fact.", score=0.1, tags=("alpha, beta", "<!-- x -->", "c;d", "e")),
            cand("hi", "High score fact.", score=1.0, tags=()),
        ],
        "replies": [reply(("lo", "added", []), ("hi", "added", []))],
        "expect": {"plan": True, "applied": True},
    }

    # --- direct application of hand-built plans ---------------------------------------
    def op(key: str, action: str, result: str, prior: list[str], lineage: str | None = None):
        item: dict[str, Any] = {
            "candidateKey": key,
            "action": action,
            "resultEntry": result,
            "priorEntries": prior,
        }
        if lineage:
            item["lineageKey"] = lineage
        return item

    result_line = f"- Fresh. {SRC} {ANNOTATIONS}"
    out["apply_replayed_marker"] = {
        "existingMemory": "# Memory\n\n<!-- openclaw-memory-promotion:r -->\n- Old.\n",
        "plan": {"operations": [op("r", "added", result_line, [])]},
        "expect": {"applied": False},
    }
    out["apply_spaced_marker_not_detected"] = {
        "existingMemory": "# Memory\n\n<!--openclaw-memory-promotion:r-->\n- Old.\n",
        "plan": {"operations": [op("r", "added", result_line, [])]},
        "expect": {"applied": True},
    }
    out["apply_prior_drifted"] = {
        "existingMemory": "# Memory\n\n- Old.\n",
        "plan": {"operations": [op("r", "merged", result_line, ["- Gone."])]},
        "expect": {"applied": False},
    }
    out["apply_nul_rejected"] = {
        "existingMemory": "# Memory\n\n- Old\0.\n",
        "plan": {"operations": [op("r", "added", result_line, [])]},
        "expect": {"applied": False},
    }
    out["apply_removes_marker_lines_of_prior"] = {
        "existingMemory": (
            "# Memory\n\n<!-- openclaw-memory-lineage:ln -->\n<!-- openclaw-memory-promotion:o -->\n"
            "- Old. Source: memory/a.md#L1-L1\n\n<!-- openclaw-memory-promotion:p -->\n- Plain.\n"
            "<!-- openclaw-memory-lineage:orphan -->\n- Orphan lineage.\n"
        ),
        "plan": {
            "operations": [
                op("n1", "superseded", result_line, ["- Old. Source: memory/a.md#L1-L1"], "ln"),
                op("n2", "merged", "- Plain. Source: memory/b.md#L1-L1 x", ["- Plain."]),
                op("n3", "merged", "- Orphan lineage. Source: memory/c.md#L1-L1 x", ["- Orphan lineage."]),
            ]
        },
        "maxPriorEntryLossFraction": 1,
        "expect": {"applied": True},
    }
    out["apply_superseded_lineage_mismatch"] = {
        "existingMemory": "# Memory\n\n<!-- openclaw-memory-lineage:ln -->\n<!-- openclaw-memory-promotion:o -->\n- Old.\n",
        "plan": {"operations": [op("n1", "superseded", result_line, ["- Old."], "other")]},
        "maxPriorEntryLossFraction": 1,
        "expect": {"applied": False},
    }
    out["apply_merged_lineage_conflict"] = {
        "existingMemory": "# Memory\n\n<!-- openclaw-memory-lineage:ln -->\n<!-- openclaw-memory-promotion:o -->\n- Old.\n",
        "plan": {"operations": [op("n1", "merged", result_line, ["- Old."], "other")]},
        "maxPriorEntryLossFraction": 1,
        "expect": {"applied": False},
    }
    out["apply_whitespace_only_memory"] = {
        "existingMemory": "  \n\t\n",
        "plan": {"operations": [op("n", "added", result_line, [])]},
        "expect": {"applied": True},
    }
    out["apply_timezone_day"] = {
        "existingMemory": "# Memory\n",
        "plan": {"operations": [op("n", "added", result_line, [])]},
        "nowMs": 1782946800000,
        "timezone": "Pacific/Kiritimati",
        "expect": {"applied": True},
    }
    out["apply_empty_plan"] = {
        "existingMemory": "# Memory\n\n- Old.\n",
        "plan": {"operations": []},
        "expect": {"applied": True},
    }
    for scenario in out.values():
        scenario.setdefault("maxPriorEntryLossFraction", 1)
    return out


SCENARIOS = _scenarios()


class _Logger:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, message: str) -> None:
        self.warnings.append(message)


def _candidate(raw: dict[str, Any]) -> PromotionCandidate:
    return PromotionCandidate(
        key=raw["key"],
        path=raw["path"],
        start_line=raw["startLine"],
        end_line=raw["endLine"],
        snippet=raw["snippet"],
        recall_count=raw["recallCount"],
        daily_count=0,
        grounded_count=0,
        signal_count=raw["signalCount"],
        avg_score=raw["avgScore"],
        max_score=raw["maxScore"],
        unique_queries=raw["uniqueQueries"],
        score=raw["score"],
        first_recalled_at=raw["firstRecalledAt"],
        last_recalled_at=raw["lastRecalledAt"],
        concept_tags=tuple(raw["conceptTags"]),
        project_key=raw.get("projectKey"),
        provenance=raw.get("provenance"),
    )


def _plan_json(plan: MemoryConsolidationPlan | None) -> dict[str, Any] | None:
    if plan is None:
        return None
    operations = []
    for operation in plan.operations:
        item: dict[str, Any] = {
            "candidateKey": operation.candidate_key,
            "action": operation.action,
            "resultEntry": operation.result_entry,
            "priorEntries": operation.prior_entries,
        }
        if operation.lineage_key:
            item["lineageKey"] = operation.lineage_key
        operations.append(item)
    return {"operations": operations}


def _run_python(scenario: dict[str, Any]) -> dict[str, Any]:
    logger = _Logger()
    calls: list[dict[str, Any]] = []
    replies = list(scenario.get("replies", []))
    now_ms = scenario.get("nowMs", NOW_MS)
    loss = scenario.get("maxPriorEntryLossFraction", 0.25)

    def model(request: ConsolidationRequest) -> Any:
        calls.append(
            {
                "message": request.message,
                "extraSystemPrompt": request.system_prompt,
                "timeoutMs": request.timeout_ms,
                "agentId": "oracle",
                **({"model": request.model} if request.model else {}),
            }
        )
        item = replies[len(calls) - 1]
        if isinstance(item, dict) and "throw" in item:
            raise RuntimeError(item["throw"])
        if isinstance(item, dict) and "raw" in item:
            raw = item["raw"]
            return type("R", (), {"text": raw.get("text")})()
        return item

    plan: MemoryConsolidationPlan | None
    if "plan" in scenario:
        plan = MemoryConsolidationPlan(
            [
                ConsolidationOperation(
                    candidate_key=item["candidateKey"],
                    action=item["action"],
                    result_entry=item["resultEntry"],
                    prior_entries=list(item["priorEntries"]),
                    lineage_key=item.get("lineageKey"),
                )
                for item in copy.deepcopy(scenario["plan"]["operations"])
            ]
        )
    else:
        plan = consolidate_memory(
            model=model,
            existing_memory=scenario["existingMemory"],
            candidates=[_candidate(item) for item in scenario["candidates"]],
            model_name=scenario.get("model"),
            max_prior_entry_loss_fraction=loss,
            memory_file_max_chars=scenario.get("memoryFileMaxChars"),
            max_promoted_snippet_tokens=scenario.get("maxPromotedSnippetTokens"),
            now_ms=now_ms,
            identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
            logger=logger,  # type: ignore[arg-type]
        )
    applied = None
    if plan is not None:
        result = apply_memory_consolidation_plan(
            existing_memory=scenario["existingMemory"],
            plan=plan,
            now_ms=now_ms,
            timezone=scenario.get("timezone", "UTC"),
            memory_file_max_chars=scenario.get("memoryFileMaxChars"),
            max_prior_entry_loss_fraction=loss,
            identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
        )
        if result is not None:
            applied = {
                "content": result.content,
                "added": result.added,
                "merged": result.merged,
                "superseded": result.superseded,
                "highlights": list(result.highlights),
            }
    return {"plan": _plan_json(plan), "applied": applied, "calls": calls, "warnings": logger.warnings}


def _normalize_calls(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # The runner's agentId is the memory-core test agent; Python has no agent concept.
    return [{**call, "agentId": "oracle"} for call in calls]


def _oracle_scenarios() -> dict[str, Any]:
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))
    payload = {
        "operation": "consolidateMemory",
        "nowMs": NOW_MS,
        "scenarios": list(SCENARIOS.values()),
    }
    response = oracle.run(payload)
    assert response["ok"] is True, response
    return response["result"]


_ORACLE_CACHE: dict[str, Any] = {}


def _oracle_result() -> dict[str, Any]:
    if not _ORACLE_CACHE:
        _ORACLE_CACHE.update(_oracle_scenarios())
    return _ORACLE_CACHE


def test_real_openclaw_oracle_consolidation_system_prompt_matches_python():
    assert _oracle_result()["systemPrompt"] == CONSOLIDATION_SYSTEM_PROMPT


def test_real_openclaw_oracle_consolidation_scenarios_match_python():
    result = _oracle_result()
    names = list(SCENARIOS)
    assert len(result["scenarios"]) == len(names)
    mismatches = []
    unmet: list[Any] = []
    for name, upstream in zip(names, result["scenarios"], strict=True):
        scenario = SCENARIOS[name]
        python = _run_python(scenario)
        upstream = {**upstream, "calls": _normalize_calls(upstream["calls"])}
        python = {**python, "calls": _normalize_calls(python["calls"])}
        if upstream != python:
            mismatches.append((name, upstream, python))
        expect = scenario.get("expect", {})
        if "plan" in expect:
            if (upstream["plan"] is not None) != expect["plan"]:
                unmet.append((name, "plan", upstream["warnings"]))
        if "applied" in expect:
            if (upstream["applied"] is not None) != expect["applied"]:
                unmet.append((name, "applied", upstream["warnings"]))
    assert not unmet, "\n".join(f"{n} {k} {w}" for n, k, w in unmet)
    assert not mismatches, mismatches[0]


def test_real_openclaw_oracle_consolidation_prompt_text_equality():
    result = _oracle_result()
    by_name = dict(zip(SCENARIOS, result["scenarios"], strict=True))
    prompts = [json.loads(call["message"]) for call in by_name["project_groups_isolated_passes"]["calls"]]
    assert [[c["projectKey"] for c in prompt["candidates"]] for prompt in prompts] == [
        [None],
        ["github.com/acme/alpha"],
        ["github.com/acme/beta"],
    ]
    assert by_name["project_groups_isolated_passes"]["calls"][0]["model"] == "stub-model"
    assert by_name["project_groups_isolated_passes"]["calls"][0]["timeoutMs"] == 60000
    # Every raw prompt (not just the parsed form) equals the Python bytes.
    for name, upstream in by_name.items():
        if "plan" in SCENARIOS[name]:
            continue
        python = _run_python(SCENARIOS[name])
        assert [c["message"] for c in upstream["calls"]] == [c["message"] for c in python["calls"]], name
        assert [c["extraSystemPrompt"] for c in upstream["calls"]] == [
            c["extraSystemPrompt"] for c in python["calls"]
        ], name
