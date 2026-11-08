"""Reuse flush fixtures against the actual native owners.

Complete plans and target preparation execute over the declared fixture domain.
Python's date limits and stricter filesystem admission, plus the native target's
authority-revocation checks, leave plan/target acceptance incomplete. Exported
token gates do not prove runtime transcript accounting, heartbeat exclusions,
durable stamps or retry state. All acceptance points remain uncredited.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import tempfile
from typing import Any
from unittest.mock import patch

NOW_MS = 1777824000000
FALLBACK_NOW_MS = 1780142400000


def build_prospective_flush_contract_cases() -> list[dict[str, Any]]:
    """Reuse substantive matrices from tests/unit/test_memory_flush_plan.py.

    Sources include ``test_build_memory_flush_plan_derives_reserve_and_soft_threshold_from_the_window``,
    ``test_force_flush_transcript_bytes_parses_like_parse_non_negative_byte_size``,
    ``test_flush_plan_accepts_ecma402_offset_time_zones``, the fresh/versioned gate
    and compaction-cycle cases, target preparation/path rejection, and the error
    length, cause-chain and UTF-16 boundaries. Assertions remain independent:
    native results come from the original exported TypeScript owners.
    """
    cases: list[dict[str, Any]] = []

    def add(name: str, kind: str, **arguments: Any) -> None:
        requirement = "flush.plan-target" if kind in {"plan", "target"} else "flush.trigger-usage"
        cases.append({
            "id": f"flush-{name}", "requirement": requirement, "operation": "flush-contract",
            "input": {"kind": kind, **arguments},
            # Native helpers alone cannot close either runtime acceptance point.
            # Target preparation has documented stricter Python filesystem admission.
            "covers": [],
            "driverScope": "complete plan or target preparation" if kind in {"plan", "target"}
            else "exported helper only; runtime accounting and retry lifecycle unproven",
        })
        if kind == "plan":
            cases[-1]["normalizationPolicy"] = (
                "All plan fields and prompt text are retained. Absent optional model is null. "
                "Python receives the declared host time format; native detected host format "
                "is retained and compared separately."
            )
        elif kind == "target":
            cases[-1]["normalizationPolicy"] = (
                "Compare complete path-validation error messages and surviving file contents. "
                "Language exception class names are not compared."
            )

    def plan(name: str, *, defaults: dict | None = None, **params: Any) -> None:
        params.setdefault("nowMs", NOW_MS)
        if defaults is not None:
            params["cfg"] = {"agents": {"defaults": defaults}}
        add(f"plan-{name}", "plan", params=params, fallbackNowMs=FALLBACK_NOW_MS,
            hostTimeFormat="12")

    def flush(name: str, settings: dict, **params: Any) -> None:
        plan(name, defaults={"compaction": {"memoryFlush": settings}}, **params)

    plan("default")
    plan("istanbul", defaults={"userTimezone": "Europe/Istanbul"})
    for window in (None, 0, -5, 200000, 80000, 79999, 26000, 26000.9, 8000, 100, 1):
        plan(f"window-{window}", contextWindowTokens=window)
    flush("smaller-soft", {"softThresholdTokens": 456}, contextWindowTokens=26000)
    for index, value in enumerate((-1, 2.9, 0, "7", True)):
        flush(f"soft-{index}", {"softThresholdTokens": value})
    for index, value in enumerate((
        1.5, -0.5, -1e-9, 2**53 - 1, 2**53, 2**60, True,
        "0.5", "0.5b", "2.5b", "1.5kb", " 3MB ", "2 mb", "1pb", "", "٣", "3\n",
        "9007199254740993",
    )):
        flush(f"byte-size-{index}", {"forceFlushTranscriptBytes": value})
    flush("disabled", {"enabled": False})
    flush("enabled", {"enabled": True})
    flush("model-trim", {"model": "  provider/model-small  "})
    flush("model-blank", {"model": " \t "})
    plan("removed-overrides", defaults={
        "userTimezone": "Europe/Istanbul", "compaction": {
            "reserveTokensFloor": 123, "memoryFlush": {
                "softThresholdTokens": 456, "forceFlushTranscriptBytes": "3mb",
                "prompt": "ignored", "systemPrompt": "ignored", "model": " fast ",
            },
        },
    })
    plan("negative-fractional-date", nowMs=-0.5)
    for index, now_ms in enumerate((8640000000000001, -8640000000000001, None)):
        plan(f"fallback-date-{index}", nowMs=now_ms)
    for index, timezone in enumerate((
        "UTC", "Europe/Istanbul", "America/Los_Angeles", "+03:00", "+0300", "+03",
        " +03:00 ", "-05:30", "−03:00", "+23:59", "+24:00", "+03:60", "+3", "UTC+3",
    )):
        plan(f"timezone-{index}", defaults={"userTimezone": timezone}, nowMs=1777842000000)
    # Both owners ignore the retired config knob. The fixture supplies Python's
    # host format separately; the native output reports its actual detected format.
    for time_format in ("12", "24"):
        plan(f"ignored-time-format-{time_format}", defaults={"timeFormat": time_format})

    for name, path, text in (
        ("new-daily", "memory/2026-09-25.md", None),
        ("preserve-existing", " memory/2026-09-25.md ", "- kept\n"),
        ("blank", "", None), ("whitespace", "  ", None),
        ("absolute", "@workspace/memory/x.md", None),
        ("parent", "../x.md", None), ("nested-parent", "memory/../../x.md", None),
        ("workspace-root", ".", None),
    ):
        add(f"target-{name}", "target", relativePath=path, existingText=text)

    fresh = {"totalTokens": 176000, "totalTokensFresh": True, "totalTokensVersion": 1}
    for name, entry, token_count, threshold in (
        ("below", {**fresh, "totalTokens": 175999}, None, 176000),
        ("at", fresh, None, 176000), ("above", {**fresh, "totalTokens": 176001}, None, 176000),
        ("stale", {**fresh, "totalTokensFresh": False}, None, 176000),
        ("unversioned", {"totalTokens": 176000, "totalTokensFresh": True}, None, 176000),
        ("old-version", {**fresh, "totalTokensVersion": 0}, None, 176000),
        ("missing-usage", {}, None, 176000), ("missing-entry", None, 176000, 176000),
        ("projected-stale", {**fresh, "totalTokensFresh": False}, 176000, 176000),
        ("empty-entry-projected", {}, 176000, 176000),
        ("projected-wins", fresh, 100, 176000),
        ("zero-projected-fallback", fresh, 0, 176000),
        ("negative-projected-fallback", fresh, -1, 176000),
        ("zero-threshold", fresh, None, 0), ("negative-threshold", fresh, None, -1),
        ("same-cycle", {**fresh, "compactionCount": 2,
                        "memoryFlush": {"kind": "succeeded", "compactionCount": 2}}, None, 176000),
        ("next-cycle", {**fresh, "compactionCount": 3,
                        "memoryFlush": {"kind": "succeeded", "compactionCount": 2}}, None, 176000),
        ("flat-stamp-ignored", {**fresh, "compactionCount": 2,
                                "memoryFlushCompactionCount": 2}, None, 176000),
        ("failed-last-cycle", {**fresh, "compactionCount": 3,
                              "memoryFlush": {"kind": "failed", "compactionCount": 2,
                                              "failureCount": 2}}, None, 176000),
    ):
        add(f"gate-{name}", "gate", entry=entry, tokenCount=token_count, threshold=threshold)
    for index, entry in enumerate((
        None, {}, fresh, {**fresh, "totalTokensFresh": False},
        {**fresh, "totalTokensVersion": 0}, {**fresh, "totalTokensVersion": True},
        {**fresh, "totalTokens": 0}, {**fresh, "totalTokens": -1},
        {**fresh, "totalTokens": 2.5}, {**fresh, "totalTokens": "176000"},
    )):
        add(f"fresh-usage-{index}", "fresh", entry=entry)
    for index, params in enumerate((
        {"contextWindowTokens": 200000, "reserveTokensFloor": 20000},
        {"contextWindowTokens": 26000, "reserveTokensFloor": 6500},
        {"contextWindowTokens": 100, "reserveTokensFloor": 20000},
        {"contextWindowTokens": 26000.9, "reserveTokensFloor": 6500.9,
         "minimumThresholdTokens": 25000.9},
    )):
        add(f"compaction-threshold-{index}", "threshold", params=params)
    for index, message in enumerate(("x" * 199, "x" * 200, "x" * 201,
                                     "x" * 198 + "😀tail", "  bad flush  ", "")):
        add(f"error-text-{index}", "error", message=message)
    add("error-cause-chain", "error", message="outer", cause="inner", exception=True)
    add("error-exception-trim", "error", message="  boom  ", exception=True)
    return cases


def build_flush_contract_cases() -> list[dict[str, Any]]:
    """Register all 111 source comparisons with no whole-acceptance credit.

    The prospective builder name remains available for existing callers.
    Dependencies execute from the verified pinned source graph; plans, targets
    and token gates are included in every registered run.
    """
    return build_prospective_flush_contract_cases()


def run_flush_contract(arguments: dict[str, Any]) -> Any:
    """Translate fixture arguments and preserve complete model-free outputs."""
    from memory_core import memory_flush as flush

    kind = arguments["kind"]
    if kind == "plan":
        params = arguments["params"]
        with patch("memory_core.current_time._date_now_ms", return_value=arguments["fallbackNowMs"]):
            plan = flush.build_memory_flush_plan_from_config(
                workspace_dir=None, cfg=deepcopy(params.get("cfg")), now_ms=params.get("nowMs"),
                context_window_tokens=params.get("contextWindowTokens"),
                time_format=arguments["hostTimeFormat"],
            )
        if plan is None:
            return {"hostTimeFormat": arguments["hostTimeFormat"], "plan": None}
        names = {"soft_threshold_tokens": "softThresholdTokens",
                 "force_flush_transcript_bytes": "forceFlushTranscriptBytes",
                 "reserve_tokens_floor": "reserveTokensFloor", "system_prompt": "systemPrompt",
                 "relative_path": "relativePath"}
        return {"hostTimeFormat": arguments["hostTimeFormat"], "plan": {
            names.get(key, key): value for key, value in asdict(plan).items()
        }}
    if kind == "target":
        with tempfile.TemporaryDirectory(prefix="memory-flush-contract-") as temporary:
            root = Path(temporary) / "workspace"
            root.mkdir()
            path = arguments["relativePath"].replace("@workspace", str(root))
            if arguments.get("existingText") is not None:
                target = root / path.strip()
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(arguments["existingText"], encoding="utf-8")
            try:
                flush.ensure_memory_flush_target_file(root, path)
                result: dict[str, Any] = {"ok": True}
            except ValueError as error:
                result = {"ok": False, "error": {"message": str(error)}}
            result["files"] = {
                file.relative_to(root).as_posix(): file.read_text(encoding="utf-8")
                for file in sorted(root.rglob("*")) if file.is_file()
            }
            return result
    if kind == "gate":
        entry = deepcopy(arguments.get("entry"))
        return {
            "shouldRun": flush.should_run_memory_flush(
                entry=entry, token_count=arguments.get("tokenCount"), threshold=arguments["threshold"],
            ),
            "alreadyFlushed": flush.has_already_flushed_for_current_compaction(entry)
            if entry is not None else None,
        }
    if kind == "fresh":
        return flush.resolve_fresh_session_total_tokens(arguments.get("entry"))
    if kind == "threshold":
        params = arguments["params"]
        return flush.resolve_compaction_threshold(
            context_window_tokens=params["contextWindowTokens"],
            reserve_tokens_floor=params["reserveTokensFloor"],
            minimum_threshold_tokens=params.get("minimumThresholdTokens"),
        )
    if kind == "error":
        if not arguments.get("exception"):
            return flush.truncate_memory_flush_error_message(arguments["message"])
        error = RuntimeError(arguments["message"])
        if "cause" in arguments:
            error.__cause__ = RuntimeError(arguments["cause"])
        return flush.truncate_memory_flush_error_message(error)
    raise ValueError(f"Unsupported flush contract operation: {kind}")
