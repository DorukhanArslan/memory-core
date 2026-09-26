"""Bootstrap context budget, truncation and truncation reports.

Port of OpenClaw ``src/agents/embedded-agent-helpers/bootstrap.ts``
(``buildBootstrapContextFiles``, ``trimBootstrapContent``,
``trimAgentsBootstrapContent``, ``buildAgentsPolicyDigest``, ``clampToBudget``;
lines 91-472) and ``src/agents/bootstrap-budget.ts`` (injection stats, budget
analysis, prompt warning lines and the compact truncation notice) at pin
4c42815348. All lengths are UTF-16 code units; head/tail slices are plain
UTF-16 slices (they may split a surrogate pair, bootstrap.ts:356-357) while the
final clamp is surrogate-safe, exactly like upstream.
"""

from __future__ import annotations

import math
import re
from functools import cmp_to_key
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from memory_core.bootstrap._js import (
    JS_IU_WORD_CLASS,
    JS_NON_SPACE,
    JS_SPACE,
    js_iu_keyword_pattern,
    js_json_stringify,
    js_trim,
    js_trim_end,
    locale_compare,
    truncate_utf16_safe,
    utf16_len,
    utf16_slice,
)
from memory_core.bootstrap.files import WorkspaceBootstrapFile
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY, RuntimeIdentity

DEFAULT_BOOTSTRAP_MAX_CHARS = 20_000
DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS = 60_000
DEFAULT_BOOTSTRAP_PROMPT_TRUNCATION_WARNING_MODE = "always"
MIN_BOOTSTRAP_FILE_BUDGET_CHARS = 64
BOOTSTRAP_HEAD_RATIO = 0.75
BOOTSTRAP_TAIL_RATIO = 0.25
MIN_BOOTSTRAP_TRIMMED_CONTENT_CHARS = 16
AGENTS_BOOTSTRAP_FILENAME = "AGENTS.md"
AGENTS_POLICY_DIGEST_RATIO = 0.35
AGENTS_POLICY_HEAD_RATIO = 0.45
AGENTS_POLICY_TAIL_RATIO = 0.15
AGENTS_POLICY_DIGEST_MAX_LINE_CHARS = 240

DEFAULT_BOOTSTRAP_NEAR_LIMIT_RATIO = 0.85
DEFAULT_BOOTSTRAP_PROMPT_WARNING_MAX_FILES = 3
DEFAULT_BOOTSTRAP_PROMPT_WARNING_SIGNATURE_HISTORY_MAX = 32

BOOTSTRAP_TRUNCATION_NOTICE_LINES = (
    "[Bootstrap truncation warning]",
    "Some workspace bootstrap files were truncated before Project Context injection.",
    "Treat Project Context as partial and read the relevant files directly if details seem missing.",
)
BOOTSTRAP_TRUNCATION_WARNING_HEADER_LINES = (
    "[Bootstrap truncation warning]",
    "Some workspace bootstrap files were truncated before injection.",
    "Treat Project Context as partial and read the relevant files directly if details seem missing.",
)

BootstrapPromptWarningMode = Literal["off", "once", "always"]
BootstrapTruncationCause = Literal["per-file-limit", "total-limit"]


@dataclass(frozen=True)
class ContextFile:
    """One injected Project Context file (upstream ``EmbeddedContextFile``)."""

    path: str
    content: str


@dataclass(frozen=True)
class TrimBootstrapResult:
    content: str
    truncated: bool
    max_chars: int
    original_length: int


# --- AGENTS.md policy digest (bootstrap.ts:157-219) -------------------------

_POLICY_STRUCTURE_RE = re.compile(
    rf"^(?:#{{1,6}}|{JS_SPACE}*[-*+]|{JS_SPACE}*[0-9]+[.)]){JS_SPACE}+{JS_NON_SPACE}"
)
_POLICY_KEYWORDS = (
    "AGENTS.md",
    "scoped",
    "required",
    "must",
    "never",
    "do not",
    "before subtree",
    "read scoped",
    "owner",
    "security",
    "secret",
    "credential",
    "test",
    "validation",
    "command",
    "commit",
    "push",
    "github",
    "pr",
)
_HIGH_PRIORITY_KEYWORDS = (
    "AGENTS.md",
    "scoped",
    "required",
    "must",
    "never",
    "do not",
    "before subtree",
    "read scoped",
    "security",
    "secret",
    "credential",
)


def _keyword_regex(keywords: Iterable[str]) -> re.Pattern[str]:
    # JavaScript /\b(?:...)\b/iu: every keyword starts and ends with a word
    # character, so \b reduces to "no /iu word character" on the outer side.
    alternation = "|".join(js_iu_keyword_pattern(keyword) for keyword in keywords)
    return re.compile(rf"(?<![{JS_IU_WORD_CLASS}])(?:{alternation})(?![{JS_IU_WORD_CLASS}])")


_POLICY_KEYWORD_RE = _keyword_regex(_POLICY_KEYWORDS)
_HIGH_PRIORITY_RE = _keyword_regex(_HIGH_PRIORITY_KEYWORDS)
_JS_WHITESPACE_RUN_RE = re.compile(f"{JS_SPACE}+")
_LINE_SPLIT_RE = re.compile(r"\r?\n")


def _is_agents_bootstrap_file(file_name: str | None) -> bool:
    return file_name is not None and file_name.lower() == AGENTS_BOOTSTRAP_FILENAME.lower()


def _is_policy_digest_candidate(line: str) -> bool:
    if _POLICY_STRUCTURE_RE.search(line):
        return True
    return _POLICY_KEYWORD_RE.search(line) is not None


def _normalize_policy_digest_line(line: str) -> str:
    normalized = _JS_WHITESPACE_RUN_RE.sub(" ", js_trim(line))
    if utf16_len(normalized) <= AGENTS_POLICY_DIGEST_MAX_LINE_CHARS:
        return normalized
    return f"{truncate_utf16_safe(normalized, AGENTS_POLICY_DIGEST_MAX_LINE_CHARS - 1)}…"


@dataclass(frozen=True)
class _PolicyDigest:
    text: str
    omitted_lines: int


def _build_agents_policy_digest(content: str, budget: int) -> _PolicyDigest:
    if budget <= 0:
        return _PolicyDigest("", 0)
    candidates: list[tuple[int, str]] = []
    for index, raw_line in enumerate(_LINE_SPLIT_RE.split(content)):
        line = _normalize_policy_digest_line(raw_line)
        if line and _is_policy_digest_candidate(line):
            candidates.append((index, line))
    selected: set[int] = set()
    used = 0

    def try_select(index: int, line: str) -> None:
        nonlocal used
        separator_chars = 1 if selected else 0
        line_length = utf16_len(line)
        if used + separator_chars + line_length > budget:
            return
        selected.add(index)
        used += separator_chars + line_length

    for index, line in candidates:
        if _HIGH_PRIORITY_RE.search(line):
            try_select(index, line)
    for index, line in candidates:
        if index not in selected:
            try_select(index, line)
    lines = [line for index, line in sorted(candidates) if index in selected]
    return _PolicyDigest("\n".join(lines), max(0, len(candidates) - len(lines)))


def _trim_agents_bootstrap_content(content: str, max_chars: int) -> TrimBootstrapResult:
    trimmed = js_trim_end(content)
    total = utf16_len(trimmed)
    if total <= max_chars:
        return TrimBootstrapResult(trimmed, False, max_chars, total)

    head_chars = math.floor(max_chars * AGENTS_POLICY_HEAD_RATIO)
    tail_chars = math.floor(max_chars * AGENTS_POLICY_TAIL_RATIO)
    digest_budget = math.floor(max_chars * AGENTS_POLICY_DIGEST_RATIO)
    digest = _build_agents_policy_digest(trimmed, digest_budget)

    def render() -> str:
        parts = [
            utf16_slice(trimmed, 0, head_chars),
            f"[...truncated, read {AGENTS_BOOTSTRAP_FILENAME} for full content...]",
            "[Policy digest from AGENTS.md]" if digest.text else "",
            digest.text,
            f"[...{digest.omitted_lines} more policy lines omitted...]"
            if digest.omitted_lines > 0
            else "",
            f"…(truncated {AGENTS_BOOTSTRAP_FILENAME}: kept {head_chars}+policy "
            f"{utf16_len(digest.text)}+{tail_chars} chars of {total})…",
            utf16_slice(trimmed, -tail_chars) if tail_chars > 0 else "",
        ]
        return "\n".join(part for part in parts if part)

    rendered = render()
    while utf16_len(rendered) > max_chars and (tail_chars > 0 or head_chars > 1 or digest_budget > 0):
        overflow = utf16_len(rendered) - max_chars
        if tail_chars > 0:
            tail_chars = max(0, tail_chars - overflow)
        elif head_chars > 1:
            head_chars = max(1, head_chars - overflow)
        else:
            digest_budget = max(0, digest_budget - overflow)
            digest = _build_agents_policy_digest(trimmed, digest_budget)
        rendered = render()

    if utf16_len(rendered) > max_chars:
        rendered = truncate_utf16_safe(rendered, max_chars)
    return TrimBootstrapResult(rendered, True, max_chars, total)


# --- generic truncation (bootstrap.ts:271-384) ------------------------------


def trim_bootstrap_content(content: str, file_name: str, max_chars: int) -> TrimBootstrapResult:
    """Port of ``trimBootstrapContent``: trimEnd, then 75/25 head/tail truncation."""
    trimmed = js_trim_end(content)
    total = utf16_len(trimmed)
    if total <= max_chars:
        return TrimBootstrapResult(trimmed, False, max_chars, total)
    if _is_agents_bootstrap_file(file_name):
        return _trim_agents_bootstrap_content(content, max_chars)

    def full_marker(head: int, tail: int) -> str:
        return "\n".join(
            [
                "",
                f"[...truncated, read {file_name} for full content...]",
                f"…(truncated {file_name}: kept {head}+{tail} chars of {total})…",
                "",
            ]
        )

    def compact_marker(head: int, tail: int) -> str:
        return f"[…truncated {head}+{tail}/{total}]"

    def separator_chars(head: int, tail: int, marker: str) -> int:
        return (int(head > 0) + int(tail > 0)) if "\n" in marker else 0

    probe = full_marker(0, 0)
    full_budget = max_chars - utf16_len(probe) - separator_chars(1, 1, probe)
    marker_template: Callable[[int, int], str] = (
        full_marker if full_budget >= MIN_BOOTSTRAP_TRIMMED_CONTENT_CHARS else compact_marker
    )

    head_chars = 0
    tail_chars = 0
    marker = marker_template(head_chars, tail_chars)
    for _ in range(3):
        content_budget = max(
            0, max_chars - utf16_len(marker) - separator_chars(head_chars, tail_chars, marker)
        )
        next_head = math.floor(content_budget * BOOTSTRAP_HEAD_RATIO)
        next_tail = math.floor(content_budget * BOOTSTRAP_TAIL_RATIO)
        next_marker = marker_template(next_head, next_tail)
        if (
            next_head == head_chars
            and next_tail == tail_chars
            and utf16_len(next_marker) == utf16_len(marker)
        ):
            break
        head_chars, tail_chars, marker = next_head, next_tail, next_marker

    def rendered_length() -> int:
        return (
            head_chars
            + tail_chars
            + utf16_len(marker)
            + separator_chars(head_chars, tail_chars, marker)
        )

    while rendered_length() > max_chars and (tail_chars > 0 or head_chars > 0):
        overflow = rendered_length() - max_chars
        if tail_chars > 0:
            tail_chars = max(0, tail_chars - overflow)
        else:
            head_chars = max(0, head_chars - overflow)
        marker = marker_template(head_chars, tail_chars)

    if head_chars == 0 and tail_chars == 0 and total > 0:
        single_marker = marker_template(1, 0)
        if 1 + utf16_len(single_marker) + separator_chars(1, 0, single_marker) <= max_chars:
            head_chars = 1
            marker = single_marker

    head = utf16_slice(trimmed, 0, head_chars)
    tail = utf16_slice(trimmed, -tail_chars) if tail_chars > 0 else ""
    joiner = "\n" if "\n" in marker else ""
    rendered = joiner.join(part for part in (head, marker, tail) if part)
    if utf16_len(rendered) > max_chars:
        rendered = truncate_utf16_safe(rendered, max_chars)
    return TrimBootstrapResult(rendered, True, max_chars, total)


def clamp_to_budget(content: str, budget: int) -> str:
    """Port of ``clampToBudget`` (bootstrap.ts:372-384)."""
    if budget <= 0:
        return ""
    if utf16_len(content) <= budget:
        return content
    if budget <= 3:
        return truncate_utf16_safe(content, budget)
    return f"{truncate_utf16_safe(content, budget - 1)}…"


def resolve_bootstrap_char_limit(value: object, default: int) -> int:
    """Port of ``resolveBootstrapMaxChars`` / ``resolveBootstrapTotalMaxChars``.

    ``bootstrap.ts:120-145``: a finite number above 0 is floored; anything else
    (``None``, 0, a negative value, NaN, infinity, a non-number) falls back to
    ``default``. Upstream reads the value from agent config; hosts pass it here.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    if not math.isfinite(value) or value <= 0:
        return default
    return math.floor(value)


@dataclass(frozen=True)
class BootstrapContextFilesResult:
    files: tuple[ContextFile, ...]
    warnings: tuple[str, ...]


def build_bootstrap_context_files(
    files: Sequence[WorkspaceBootstrapFile],
    *,
    max_chars: int = DEFAULT_BOOTSTRAP_MAX_CHARS,
    total_max_chars: int | None = None,
) -> BootstrapContextFilesResult:
    """Port of ``buildBootstrapContextFiles`` (bootstrap.ts:413-472).

    Files are consumed in the given (load) order against a per-file cap and a
    shared total budget. ``total_max_chars=None`` means
    ``max(max_chars, 60000)`` like upstream's option default.
    """
    total = max(
        1,
        math.floor(
            total_max_chars
            if total_max_chars is not None
            else max(max_chars, DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS)
        ),
    )
    remaining = total
    warnings: list[str] = []
    result: list[ContextFile] = []
    for file in files:
        if remaining <= 0:
            break
        path_value = js_trim(file.path) if isinstance(file.path, str) else ""
        if not path_value:
            warnings.append(
                f'skipping bootstrap file "{file.name}" — missing or invalid "path" field '
                '(hook may have used "filePath" instead)'
            )
            continue
        if file.missing:
            capped = clamp_to_budget(f"[MISSING] Expected at: {path_value}", remaining)
            if not capped:
                break
            remaining = max(0, remaining - utf16_len(capped))
            result.append(ContextFile(path_value, capped))
            continue
        if remaining < MIN_BOOTSTRAP_FILE_BUDGET_CHARS:
            warnings.append(
                f"remaining bootstrap budget is {remaining} chars "
                f"(<{MIN_BOOTSTRAP_FILE_BUDGET_CHARS}); skipping additional bootstrap files"
            )
            break
        file_max_chars = max(1, min(max_chars, remaining))
        trimmed = trim_bootstrap_content(file.content or "", file.name, file_max_chars)
        within_budget = clamp_to_budget(trimmed.content, remaining)
        if not within_budget:
            continue
        if trimmed.truncated or utf16_len(within_budget) < utf16_len(trimmed.content):
            warnings.append(
                f"workspace bootstrap file {file.name} is {trimmed.original_length} chars "
                f"(limit {trimmed.max_chars}); truncating in injected context"
            )
        remaining = max(0, remaining - utf16_len(within_budget))
        result.append(ContextFile(path_value, within_budget))
    return BootstrapContextFilesResult(tuple(result), tuple(warnings))


# --- bootstrap-budget.ts ----------------------------------------------------


@dataclass(frozen=True)
class BootstrapInjectionStat:
    name: str
    path: str
    missing: bool
    raw_chars: int
    injected_chars: int
    truncated: bool


@dataclass(frozen=True)
class BootstrapAnalyzedFile:
    name: str
    path: str
    missing: bool
    raw_chars: int
    injected_chars: int
    truncated: bool
    near_limit: bool
    causes: tuple[BootstrapTruncationCause, ...]


@dataclass(frozen=True)
class BootstrapBudgetAnalysis:
    files: tuple[BootstrapAnalyzedFile, ...]
    truncated_files: tuple[BootstrapAnalyzedFile, ...]
    near_limit_files: tuple[BootstrapAnalyzedFile, ...]
    total_near_limit: bool
    has_truncation: bool
    raw_chars: int
    injected_chars: int
    truncated_chars: int
    bootstrap_max_chars: int
    bootstrap_total_max_chars: int
    near_limit_ratio: float


@dataclass(frozen=True)
class BootstrapPromptWarning:
    signature: str | None
    warning_shown: bool
    lines: tuple[str, ...]
    warning_signatures_seen: tuple[str, ...] = field(default_factory=tuple)


def _posix_basename(value: str) -> str:
    # path.posix.basename: trailing slashes are ignored; "/" yields "".
    return value.rstrip("/").rsplit("/", 1)[-1]


def build_bootstrap_injection_stats(
    bootstrap_files: Sequence[WorkspaceBootstrapFile],
    injected_files: Sequence[ContextFile],
) -> tuple[BootstrapInjectionStat, ...]:
    """Port of ``buildBootstrapInjectionStats`` (bootstrap-budget.ts:135-173)."""
    injected_by_path: dict[str, str] = {}
    injected_by_basename: dict[str, str] = {}
    for file in injected_files:
        path_value = js_trim(file.path) if isinstance(file.path, str) else ""
        if not path_value:
            continue
        injected_by_path.setdefault(path_value, file.content)
        injected_by_basename.setdefault(_posix_basename(path_value.replace("\\", "/")), file.content)
    stats: list[BootstrapInjectionStat] = []
    for file in bootstrap_files:
        path_value = js_trim(file.path) if isinstance(file.path, str) else ""
        raw_chars = 0 if file.missing else utf16_len(js_trim_end(file.content or ""))
        injected = injected_by_path.get(path_value) if path_value else None
        if injected is None:
            injected = injected_by_path.get(file.name)
        if injected is None:
            injected = injected_by_basename.get(file.name)
        injected_chars = utf16_len(injected) if injected else 0
        stats.append(
            BootstrapInjectionStat(
                name=file.name,
                path=path_value or file.name,
                missing=file.missing,
                raw_chars=raw_chars,
                injected_chars=injected_chars,
                truncated=(not file.missing) and injected_chars < raw_chars,
            )
        )
    return tuple(stats)


def _normalize_positive_limit(value: float) -> int:
    if not math.isfinite(value) or value <= 0:
        return 1
    return math.floor(value)


def analyze_bootstrap_budget(
    files: Sequence[BootstrapInjectionStat],
    *,
    bootstrap_max_chars: int,
    bootstrap_total_max_chars: int,
    near_limit_ratio: float | None = None,
) -> BootstrapBudgetAnalysis:
    """Port of ``analyzeBootstrapBudget`` (bootstrap-budget.ts:176-233)."""
    max_chars = _normalize_positive_limit(bootstrap_max_chars)
    total_max = _normalize_positive_limit(bootstrap_total_max_chars)
    ratio = (
        near_limit_ratio
        if isinstance(near_limit_ratio, int | float)
        and math.isfinite(near_limit_ratio)
        and 0 < near_limit_ratio < 1
        else DEFAULT_BOOTSTRAP_NEAR_LIMIT_RATIO
    )
    non_missing = [file for file in files if not file.missing]
    raw_chars = sum(file.raw_chars for file in non_missing)
    injected_chars = sum(file.injected_chars for file in non_missing)
    total_near_limit = injected_chars >= math.ceil(total_max * ratio)
    total_over_limit = injected_chars >= total_max
    analyzed: list[BootstrapAnalyzedFile] = []
    for file in files:
        if file.missing:
            analyzed.append(BootstrapAnalyzedFile(**vars(file), near_limit=False, causes=()))
            continue
        causes: list[BootstrapTruncationCause] = []
        if file.truncated:
            if file.raw_chars > max_chars:
                causes.append("per-file-limit")
            if total_over_limit:
                causes.append("total-limit")
        analyzed.append(
            BootstrapAnalyzedFile(
                **vars(file),
                near_limit=file.raw_chars >= math.ceil(max_chars * ratio),
                causes=tuple(causes),
            )
        )
    truncated_files = tuple(file for file in analyzed if file.truncated)
    return BootstrapBudgetAnalysis(
        files=tuple(analyzed),
        truncated_files=truncated_files,
        near_limit_files=tuple(file for file in analyzed if file.near_limit),
        total_near_limit=total_near_limit,
        has_truncation=bool(truncated_files),
        raw_chars=raw_chars,
        injected_chars=injected_chars,
        truncated_chars=max(0, raw_chars - injected_chars),
        bootstrap_max_chars=max_chars,
        bootstrap_total_max_chars=total_max,
        near_limit_ratio=ratio,
    )


def _truncation_signature(analysis: BootstrapBudgetAnalysis) -> str | None:
    if not analysis.has_truncation:
        return None
    files = [
        {
            "path": file.path or file.name,
            "rawChars": file.raw_chars,
            "injectedChars": file.injected_chars,
            "causes": sorted(file.causes),
        }
        for file in analysis.truncated_files
    ]

    def compare(left: dict, right: dict) -> int:
        path_cmp = locale_compare(left["path"], right["path"])
        if path_cmp != 0:
            return path_cmp
        if left["rawChars"] != right["rawChars"]:
            return left["rawChars"] - right["rawChars"]
        if left["injectedChars"] != right["injectedChars"]:
            return left["injectedChars"] - right["injectedChars"]
        return locale_compare("+".join(left["causes"]), "+".join(right["causes"]))

    files.sort(key=cmp_to_key(compare))
    return js_json_stringify(
        {
            "bootstrapMaxChars": analysis.bootstrap_max_chars,
            "bootstrapTotalMaxChars": analysis.bootstrap_total_max_chars,
            "files": files,
        }
    )


def _js_round(value: float) -> int:
    return math.floor(value + 0.5)


def format_bootstrap_truncation_warning_lines(
    analysis: BootstrapBudgetAnalysis,
    *,
    max_files: int | None = None,
    identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> tuple[str, ...]:
    """Port of ``formatBootstrapTruncationWarningLines`` (bootstrap-budget.ts:270-316).

    The last line names OpenClaw's ``agents.defaults.bootstrap*MaxChars``
    config keys upstream; it comes from ``identity`` (verbatim with
    ``OPENCLAW_COMPAT_RUNTIME_IDENTITY``, memory-core's own wording by default).
    """
    if not analysis.has_truncation:
        return ()
    limit = (
        math.floor(max_files)
        if isinstance(max_files, int | float) and math.isfinite(max_files) and max_files > 0
        else DEFAULT_BOOTSTRAP_PROMPT_WARNING_MAX_FILES
    )
    duplicate_counts: dict[str, int] = {}
    for file in analysis.truncated_files:
        duplicate_counts[file.name] = duplicate_counts.get(file.name, 0) + 1
    top_files = analysis.truncated_files[:limit]
    lines: list[str] = []
    for file in top_files:
        pct = (
            _js_round(((file.raw_chars - file.injected_chars) / file.raw_chars) * 100)
            if file.raw_chars > 0
            else 0
        )
        cause_text = ", ".join(
            "max/file" if cause == "per-file-limit" else "max/total" for cause in file.causes
        )
        name_label = (
            f"{file.name} ({file.path})"
            if duplicate_counts.get(file.name, 0) > 1 and js_trim(file.path)
            else file.name
        )
        lines.append(
            f"{name_label}: {file.raw_chars} raw -> {file.injected_chars} injected "
            f"(~{max(0, pct)}% removed{f'; {cause_text}' if cause_text else ''})."
        )
    if len(analysis.truncated_files) > len(top_files):
        lines.append(f"+{len(analysis.truncated_files) - len(top_files)} more truncated file(s).")
    if any(file.name.lower() == "agents.md" for file in analysis.truncated_files):
        lines.append(
            "AGENTS.md was truncated; read the full AGENTS.md before relying on scoped policy."
        )
    lines.append(identity.bootstrap_truncation_limits_line)
    return tuple(lines)


def _normalize_seen_signatures(signatures: Iterable[str] | None) -> list[str]:
    result: list[str] = []
    for signature in signatures or ():
        value = js_trim(signature) if isinstance(signature, str) else ""
        if value and value not in result:
            result.append(value)
    return result


def _append_seen_signature(signatures: list[str], signature: str) -> list[str]:
    if not js_trim(signature) or signature in signatures:
        return signatures
    appended = [*signatures, signature]
    return appended[-DEFAULT_BOOTSTRAP_PROMPT_WARNING_SIGNATURE_HISTORY_MAX:]


def build_bootstrap_prompt_warning(
    analysis: BootstrapBudgetAnalysis,
    *,
    mode: BootstrapPromptWarningMode = DEFAULT_BOOTSTRAP_PROMPT_TRUNCATION_WARNING_MODE,
    previous_signature: str | None = None,
    seen_signatures: Iterable[str] | None = None,
    max_files: int | None = None,
    identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> BootstrapPromptWarning:
    """Port of ``buildBootstrapPromptWarning`` (bootstrap-budget.ts:319-349).

    ``identity`` picks the wording of the config-limit line (see
    :func:`format_bootstrap_truncation_warning_lines`).
    """
    signature = _truncation_signature(analysis)
    seen = _normalize_seen_signatures(seen_signatures)
    if previous_signature and previous_signature not in seen:
        seen = _append_seen_signature(seen, previous_signature)
    has_seen = bool(signature and signature in seen)
    shown = mode != "off" and bool(signature) and (mode == "always" or not has_seen)
    signatures_seen = (
        _append_seen_signature(seen, signature) if signature and mode != "off" else seen
    )
    return BootstrapPromptWarning(
        signature=signature,
        warning_shown=shown,
        lines=format_bootstrap_truncation_warning_lines(
            analysis, max_files=max_files, identity=identity
        )
        if shown
        else (),
        warning_signatures_seen=tuple(signatures_seen),
    )


def build_bootstrap_prompt_warning_notice(warning_lines: Iterable[str] | None) -> str | None:
    """Port of ``buildBootstrapPromptWarningNotice`` (bootstrap-budget.ts:376-386)."""
    if not any(js_trim(line) for line in (warning_lines or ())):
        return None
    return "\n".join(BOOTSTRAP_TRUNCATION_NOTICE_LINES)


def append_bootstrap_prompt_warning(
    prompt: str,
    warning_lines: Iterable[str] | None,
    *,
    preserve_exact_prompt: str | None = None,
) -> str:
    """Port of ``appendBootstrapPromptWarning`` (bootstrap-budget.ts:352-373)."""
    normalized = [js_trim(line) for line in (warning_lines or ())]
    normalized = [line for line in normalized if line]
    if not normalized:
        return prompt
    if preserve_exact_prompt and prompt == preserve_exact_prompt:
        return prompt
    block = "\n".join(
        [*BOOTSTRAP_TRUNCATION_WARNING_HEADER_LINES, *(f"- {line}" for line in normalized)]
    )
    return f"{prompt}\n\n{block}" if prompt else block
