"""Reuse bootstrap budget fixtures against native clipping and warning functions.

The probe, policy digest, missing marker, path matching and USER cap cases reuse
the inputs from tests/unit/test_bootstrap_budget.py. Results are produced afresh
by the existing Python functions; no expected OpenClaw snapshots live here.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any


def build_bootstrap_budget_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    def add(name: str, arguments: dict[str, Any], *, boundaries: bool = False) -> None:
        cases.append({
            "id": f"bootstrap-budget-{name}", "requirement": "prompt.bootstrap-budget",
            "operation": "bootstrap-budget", "input": arguments,
            "covers": [f"prompt.bootstrap-budget.{'boundaries' if boundaries else 'outcomes'}"],
        })

    def file(name: str, content: str | None = None, **extra: Any) -> dict[str, Any]:
        return {"name": name, "path": f"/w/{name}", "content": content,
                "missing": False, **extra}

    def clip(name: str, files: list[dict[str, Any]], *, max_chars: int = 200,
             total: int = 60000, boundaries: bool = False, **extra: Any) -> None:
        add(name, {"files": files, "maxChars": max_chars, "totalMaxChars": total, **extra},
            boundaries=boundaries)

    # Existing upstream probe and compact-marker inputs.
    probe = "\n".join(f"line {index} " + "x" * 40 for index in range(400))
    clip("head-tail-probe", [file("SOUL.md", probe), file("USER.md", missing=True),
                             file("TOOLS.md", "short\n")], max_chars=300, total=700)
    clip("compact-marker-probe", [file("SOUL.md", probe)], max_chars=80)
    for limit in (1, 2, 3, 4, 16, 63, 64, 65, 100, 200, 301):
        clip(f"per-file-{limit}", [file("SOUL.md", "a" * (limit + 1))], max_chars=limit)
    for length in (199, 200, 201):
        clip(f"per-file-exact-{length}", [file("SOUL.md", "x" * length)])
    for total in (1, 2, 3, 4, 63, 64, 65, 163, 164, 165, 200, 201):
        clip(f"aggregate-{total}", [file("SOUL.md", "s" * 100),
                                   file("TOOLS.md", "t" * 100)], total=total)
    clip("missing-marker-exhaustion", [file("AGENTS.md", "a" * 150),
         file("SOUL.md", "b" * 150), file("TOOLS.md", missing=True),
         file("USER.md", "c" * 30)], max_chars=150, total=330)
    for total in (1, 2, 3, 4, 30, 31):
        clip(f"missing-marker-clamp-{total}", [file("TOOLS.md", missing=True)], total=total)
    clip("missing-marker-budget-accounting", [file("TOOLS.md", missing=True),
         file("SOUL.md", "s" * 100)], max_chars=100, total=100)
    add("large-default-total", {"files": [file("SOUL.md", "s" * 70000)], "maxChars": 65000})
    for length in (3999, 4000, 4001, 5000):
        clip(f"fixed-user-{length}", [file("user.md", "u" * length)], max_chars=20000)
    clip("lowered-user-cap", [file("USER.md", "u" * 5000)], max_chars=3000)
    clip("user-aggregate-cap", [file("SOUL.md", "s" * 3000),
         file("USER.md", "u" * 5000)], max_chars=20000, total=5000)
    for length in (99, 100, 101):
        clip(f"utf16-exact-{length}", [file("SOUL.md", "😀" * length)], max_chars=200)
    clip("utf16-head-tail", [file("IDENTITY.md", "記憶と🧠" * 200)], max_chars=301)
    clip("utf16-agents", [file("AGENTS.md", "😀" * 2000)], max_chars=301)
    clip("js-trim-end", [file("SOUL.md", "a \u00a0\u3000\ufeff\u2028\n"),
                        file("TOOLS.md", "keep\u0085")])
    clip("invalid-path", [file("SOUL.md", "text", path="   "),
                          file("TOOLS.md", "text", path=None)], boundaries=True)
    clip("blank-content", [file("SOUL.md", " \n\t"), file("TOOLS.md", "")], boundaries=True)

    agents = "\n".join(["# AGENTS.md", "", *[
        f"Plain prose line {index} with nothing special in it at all." for index in range(80)],
        "- You must read scoped files first.", "Never commit ſecrets.",
        "COMMİT dotted capital is not the commit keyword."])
    clip("agents-policy-digest", [file("AGENTS.md", agents)], max_chars=600)
    framed = "\n".join(["Plain framing prose.", "- You must read scoped files.", "",
        "Another prose line.", "```", "- never inside a fence frame", "禁止 pushing secrets 🔴"])
    clip("agents-policy-framing", [file("AGENTS.md", ("plain prose\n" * 50) + framed)],
         max_chars=600)
    for ratio in (0, 0.5, 0.85, 1):
        clip(f"near-limit-ratio-{ratio}", [file("SOUL.md", "s" * 85)],
             max_chars=100, total=100, nearLimitRatio=ratio)
    for length in (84, 85, 86):
        clip(f"near-limit-exact-{length}", [file("SOUL.md", "s" * length)],
             max_chars=100, total=100)

    warning_files = [file("AGENTS.md", agents), file("SOUL.md", "s" * 700),
        file("SOUL.md", "b" * 700, path="/w/other/SOUL.md"), file("USER.md", "u" * 700)]
    clip("warning-off-once-always-state", warning_files, max_chars=600, boundaries=True,
         warningSteps=[{"mode": "off"}, {"mode": "once", "useSeen": True},
                       {"mode": "once", "useSeen": True}, {"mode": "always", "useSeen": True}])
    clip("warning-previous-signature", warning_files, max_chars=600, boundaries=True,
         warningSteps=[{"mode": "once"}, {"mode": "once", "usePrevious": True}])
    clip("warning-signature-normalization", warning_files, max_chars=600, boundaries=True,
         warningSteps=[{"mode": "once", "seenSignatures": [" a ", "a", "", "\ufeff b "]}])
    clip("warning-history-eviction", warning_files, max_chars=600, boundaries=True,
         warningSteps=[{"mode": "once", "seenSignatures": [f"seen-{n}" for n in range(33)]}])
    for maximum in (0, -1, 0.9, 1, 1.9, 5):
        clip(f"warning-max-files-{maximum}", warning_files, max_chars=600, boundaries=True,
             warningSteps=[{"mode": "always", "maxFiles": maximum}])
    clip("warning-no-truncation", [file("SOUL.md", "short")], boundaries=True,
         warningSteps=[{"mode": "once", "seenSignatures": [" a ", "a"]}])
    add("stats-path-only", {"kind": "stats", "files": [file("SOUL.md", "a", path="/w/a/SOUL.md"),
        file("SOUL.md", "b", path="/w/b/SOUL.md"), file("  ", "c", path="/w/c/NOTES.md"),
        file("", "d", path="")], "injectedFiles": [{"path": "/w/a/SOUL.md", "content": "a"},
        {"path": "SOUL.md", "content": "b"}]}, boundaries=True)
    add("stats-duplicate-path-first", {"kind": "stats", "files": [
        file("SOUL.md", "abc", path=" /w/a/SOUL.md "),
        file("", "abc", path="C:\\workspace\\NOTES.md")], "injectedFiles": [
        {"path": "/w/a/SOUL.md", "content": "a"}, {"path": "/w/a/SOUL.md", "content": "abc"}]},
        boundaries=True)
    for length in (3999, 4000, 4001):
        clip(f"personal-user-{length}", [file("USER.md", "shared", path="/w/USER.md"),
             file("USER.md", "p" * length, path="/w/users/alice/USER.md", personalUser=True),
             file("MEMORY.md", "facts")], max_chars=20000, boundaries=True)
    clip("personal-user-aggregate-skip", [file("SOUL.md", "s" * 100),
         file("USER.md", "p" * 101, path="/w/users/alice/USER.md", personalUser=True),
         file("MEMORY.md", "facts")], total=200, boundaries=True)
    return cases


def _json_fields(value: Any) -> dict[str, Any]:
    """Translate dataclass field names; preserve all native result values."""
    names = {"raw_chars": "rawChars", "injected_chars": "injectedChars",
             "effective_file_limit": "effectiveFileLimit", "near_limit": "nearLimit"}
    return {names.get(key, key): list(item) if isinstance(item, tuple) else item
            for key, item in asdict(value).items()}


def run_bootstrap_budget(arguments: dict[str, Any]) -> dict[str, Any]:
    """Call existing Python functions; only translate arguments and result shapes."""
    from memory_core.bootstrap.budget import (
        DEFAULT_BOOTSTRAP_MAX_CHARS, DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS, ContextFile,
        analyze_bootstrap_budget, build_bootstrap_context_files, build_bootstrap_injection_stats,
        build_bootstrap_prompt_warning, build_bootstrap_prompt_warning_notice,
    )
    from memory_core.bootstrap.files import WorkspaceBootstrapFile
    from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY

    files = [WorkspaceBootstrapFile(name=entry.get("name"), path=entry.get("path"),
        content=entry.get("content"), missing=entry.get("missing", False),
        personal_user=entry.get("personalUser", False)) for entry in arguments["files"]]
    if arguments.get("kind") == "stats":
        return {"stats": [_json_fields(stat) for stat in build_bootstrap_injection_stats(
            files, [ContextFile(**entry) for entry in arguments["injectedFiles"]])]}
    maximum = arguments.get("maxChars", DEFAULT_BOOTSTRAP_MAX_CHARS)
    total = arguments.get("totalMaxChars", max(maximum, DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS))
    built = build_bootstrap_context_files(files, max_chars=maximum, total_max_chars=total)
    stats = build_bootstrap_injection_stats(files, built.files)
    analysis = analyze_bootstrap_budget(stats, bootstrap_max_chars=maximum,
        bootstrap_total_max_chars=total, near_limit_ratio=arguments.get("nearLimitRatio"))
    diagnosis = {
        "files": [_json_fields(file) for file in analysis.files],
        "truncatedFiles": [_json_fields(file) for file in analysis.truncated_files],
        "nearLimitFiles": [_json_fields(file) for file in analysis.near_limit_files],
        "totalNearLimit": analysis.total_near_limit, "hasTruncation": analysis.has_truncation,
        "totals": {"rawChars": analysis.raw_chars, "injectedChars": analysis.injected_chars,
                   "truncatedChars": analysis.truncated_chars,
                   "bootstrapMaxChars": analysis.bootstrap_max_chars,
                   "bootstrapTotalMaxChars": analysis.bootstrap_total_max_chars,
                   "nearLimitRatio": analysis.near_limit_ratio},
    }
    transitions = []
    previous = None
    for step in arguments.get("warningSteps", [{"mode": "always"}]):
        warning = build_bootstrap_prompt_warning(analysis, mode=step["mode"],
            previous_signature=(previous.signature if step.get("usePrevious") and previous
                                else step.get("previousSignature")),
            seen_signatures=(previous.warning_signatures_seen if step.get("useSeen") and previous
                             else step.get("seenSignatures")), max_files=step.get("maxFiles"),
            identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)
        transitions.append({"signature": warning.signature, "warningShown": warning.warning_shown,
            "lines": list(warning.lines), "warningSignaturesSeen": list(warning.warning_signatures_seen),
            "notice": build_bootstrap_prompt_warning_notice(warning.lines)})
        previous = warning
    return {"files": [{"path": file.path, "content": file.content,
                       **({"personalUser": True} if file.personal_user else {})}
                      for file in built.files], "warnings": list(built.warnings),
            "stats": [_json_fields(stat) for stat in stats], "analysis": diagnosis,
            "warningTransitions": transitions}
