import unicodedata

from memory_core.bootstrap import (
    ContextFile,
    WorkspaceBootstrapFile,
    analyze_bootstrap_budget,
    build_bootstrap_context_files,
    build_bootstrap_injection_stats,
    build_bootstrap_prompt_warning,
    build_bootstrap_prompt_warning_notice,
    clamp_to_budget,
    trim_bootstrap_content,
)
from memory_core.bootstrap._js import (
    JS_WHITESPACE,
    js_json_stringify,
    js_trim_end,
    js_utf8_encode,
    locale_compare,
    slice_utf16_safe,
    truncate_utf16_safe,
    utf16_len,
    utf16_slice,
)


def _probe_soul() -> str:
    return "\n".join(f"line {index} " + "x" * 40 for index in range(400))


def test_probe_soul_is_19889_utf16_units():
    assert utf16_len(_probe_soul()) == 19889


def test_head_tail_truncation_matches_upstream_probe():
    files = [
        WorkspaceBootstrapFile("SOUL.md", "/w/SOUL.md", _probe_soul()),
        WorkspaceBootstrapFile("USER.md", "/w/USER.md", missing=True),
        WorkspaceBootstrapFile("TOOLS.md", "/w/TOOLS.md", "short\n"),
    ]

    result = build_bootstrap_context_files(files, max_chars=300, total_max_chars=700)

    soul, user, tools = result.files
    assert "\n[...truncated, read SOUL.md for full content...]\n" in soul.content
    assert "…(truncated SOUL.md: kept 148+49 chars of 19889)…" in soul.content
    assert soul.content.startswith("line 0 ")
    assert soul.content.endswith("line 399 " + "x" * 40)
    assert utf16_len(soul.content) <= 300
    assert user.content == "[MISSING] Expected at: /w/USER.md"
    assert tools.content == "short"
    assert result.warnings == (
        "workspace bootstrap file SOUL.md is 19889 chars (limit 300); truncating in injected context",
    )


def test_compact_marker_when_full_marker_leaves_too_little_content():
    result = trim_bootstrap_content(_probe_soul(), "SOUL.md", 80)

    assert result.truncated is True
    assert result.content == (
        "line 0 " + "x" * 35 + "[…truncated 42+14/19889]" + "x" * 14
    )
    assert result.original_length == 19889


def test_js_whitespace_is_the_ecmascript_set():
    # ECMA-262 WhiteSpace (TAB, VT, FF, ZWNBSP, Zs) plus LineTerminator (LF, CR, LS, PS).
    zs = {chr(code) for code in range(0x110000) if unicodedata.category(chr(code)) == "Zs"}
    expected = zs | {"\t", "\u000b", "\u000c", "\ufeff", "\n", "\r", "\u2028", "\u2029"}
    assert set(JS_WHITESPACE) == expected
    assert len(JS_WHITESPACE) == len(expected)


def test_trim_end_uses_javascript_whitespace():
    assert js_trim_end("a \u00a0\u3000\ufeff\u2028\n") == "a"
    # U+0085 is str.isspace() in Python but not JavaScript whitespace.
    assert js_trim_end("a\u0085") == "a\u0085"
    assert trim_bootstrap_content("keep\u0085", "TOOLS.md", 100).content == "keep\u0085"


def test_head_and_tail_slices_keep_surrogate_pairs_whole():
    # v2026.9.6 slices head and tail with sliceUtf16Safe (the pin used a plain slice).
    content = "記憶と🧠" * 200
    result = trim_bootstrap_content(content, "IDENTITY.md", 301)
    agents = trim_bootstrap_content("😀" * 2000, "AGENTS.md", 301)

    for trimmed in (result, agents):
        assert trimmed.truncated is True
        assert not any(0xD800 <= ord(char) <= 0xDFFF for char in trimmed.content)
        assert utf16_len(trimmed.content) <= 301


def test_utf16_helpers_follow_javascript_slice_semantics():
    assert utf16_len("a😀") == 3
    assert utf16_slice("a😀b", 0, 2) == "a\ud83d"
    assert utf16_slice("a😀b", -2) == "\ude00b"
    assert slice_utf16_safe("a😀b", 0, 2) == "a"
    assert slice_utf16_safe("a😀b", 2) == "b"
    # Reversed bounds give "" at v2026.9.6 (the pin swapped them).
    assert slice_utf16_safe("abc", 2, 1) == ""
    assert truncate_utf16_safe("😀😀", 3) == "😀"


def test_node_string_encoders():
    # Expected values measured with node v25.2.1 (Buffer.from / JSON.stringify).
    assert js_utf8_encode("a\U0001f600b\udc00") == b"a\xf0\x9f\x98\x80b\xef\xbf\xbd"
    assert js_utf8_encode("\ud83d\ude00") == "\U0001f600".encode("utf-8")
    assert js_json_stringify({"a": "x\ud83d", "b": "\ud83d\ude00", "c": [1, {}]}, indent=2) == (
        '{\n  "a": "x\\ud83d",\n  "b": "\U0001f600",\n  "c": [\n    1,\n    {}\n  ]\n}'
    )
    assert js_json_stringify({"a": "\u00e9", "b": []}) == '{"a":"\u00e9","b":[]}'


def test_clamp_to_budget_small_budgets():
    assert clamp_to_budget("abcdef", 0) == ""
    assert clamp_to_budget("abcdef", 3) == "abc"
    assert clamp_to_budget("abcdef", 4) == "abc…"
    assert clamp_to_budget("abc", 10) == "abc"


def test_total_budget_exhaustion_clamps_the_missing_marker():
    files = [
        WorkspaceBootstrapFile("AGENTS.md", "/w/AGENTS.md", "a" * 150),
        WorkspaceBootstrapFile("SOUL.md", "/w/SOUL.md", "b" * 150),
        WorkspaceBootstrapFile("TOOLS.md", "/w/TOOLS.md", missing=True),
        WorkspaceBootstrapFile("USER.md", "/w/USER.md", "c" * 30),
    ]

    result = build_bootstrap_context_files(files, max_chars=150, total_max_chars=330)

    assert [file.path for file in result.files] == ["/w/AGENTS.md", "/w/SOUL.md", "/w/TOOLS.md"]
    # 30 units remain: the marker is clamped to 29 units plus "…", then the budget is spent.
    assert result.files[2].content == "[MISSING] Expected at: /w/TOO…"
    assert result.warnings == ()


def test_total_max_chars_defaults_to_at_least_60000():
    files = [WorkspaceBootstrapFile("SOUL.md", "/w/SOUL.md", "s" * 70_000)]

    result = build_bootstrap_context_files(files, max_chars=65_000)

    # max(maxChars, 60000) total; floor residue of the 75/25 split may leave one unit unused.
    assert 60_000 < utf16_len(result.files[0].content) <= 65_000


def test_min_budget_warning_text():
    files = [
        WorkspaceBootstrapFile("AGENTS.md", "/w/AGENTS.md", "a" * 100),
        WorkspaceBootstrapFile("SOUL.md", "/w/SOUL.md", "b" * 100),
    ]

    result = build_bootstrap_context_files(files, max_chars=100, total_max_chars=150)

    assert [file.path for file in result.files] == ["/w/AGENTS.md"]
    assert result.warnings == (
        "remaining bootstrap budget is 50 chars (<64); skipping additional bootstrap files",
    )


def test_blank_path_is_skipped_with_upstream_warning():
    result = build_bootstrap_context_files(
        [WorkspaceBootstrapFile("SOUL.md", "   ", "text")], max_chars=100
    )

    assert result.files == ()
    assert result.warnings == (
        'skipping bootstrap file "SOUL.md" — missing or invalid "path" field '
        '(hook may have used "filePath" instead)',
    )


def test_empty_content_is_not_injected():
    result = build_bootstrap_context_files(
        [WorkspaceBootstrapFile("SOUL.md", "/w/SOUL.md", " \n\t")], max_chars=100
    )

    assert result.files == ()


def _agents_content() -> str:
    lines = ["# AGENTS.md", ""]
    for index in range(80):
        lines.append(f"Plain prose line {index} with nothing special in it at all.")
    lines.append("- You must read scoped files first.")
    lines.append("Never commit ſecrets.")
    lines.append("COMMİT dotted capital is not the commit keyword.")
    return "\n".join(lines)


def test_agents_policy_digest_render():
    result = trim_bootstrap_content(_agents_content(), "AGENTS.md", 600)

    assert result.truncated is True
    assert "[...truncated, read AGENTS.md for full content...]" in result.content
    assert "[Policy digest from AGENTS.md]" in result.content
    assert "- You must read scoped files first." in result.content
    # U+017F folds onto "s" under /iu, so "ſecrets" still hits the keyword list.
    assert "Never commit ſecrets." in result.content
    assert "…(truncated AGENTS.md: kept " in result.content
    assert utf16_len(result.content) <= 600


def test_agents_digest_keyword_boundaries_follow_javascript():
    from memory_core.bootstrap.budget import _is_policy_digest_candidate

    assert _is_policy_digest_candidate("please commit this")
    assert not _is_policy_digest_candidate("COMMİT")
    assert not _is_policy_digest_candidate("committed work")
    assert _is_policy_digest_candidate("  3) numbered item")
    assert not _is_policy_digest_candidate("٣) arabic digit is not \\d")


def _truncated_analysis():
    files = [WorkspaceBootstrapFile("AGENTS.md", "/w/AGENTS.md", _agents_content())]
    built = build_bootstrap_context_files(files, max_chars=600)
    stats = build_bootstrap_injection_stats(files, built.files)
    return analyze_bootstrap_budget(stats, bootstrap_max_chars=600, bootstrap_total_max_chars=60_000)


def test_truncation_warning_lines_and_notice_are_verbatim():
    from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY

    warning = build_bootstrap_prompt_warning(
        _truncated_analysis(), identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY
    )
    memory_core_warning = build_bootstrap_prompt_warning(_truncated_analysis())

    assert warning.warning_shown is True
    assert warning.lines[0].startswith("AGENTS.md: ")
    assert warning.lines[0].endswith("% removed; max/file).")
    assert warning.lines[1:] == (
        "AGENTS.md was truncated; read the full AGENTS.md before relying on scoped policy.",
        "If unintentional, raise agents.defaults.bootstrapMaxChars and/or "
        "agents.defaults.bootstrapTotalMaxChars.",
    )
    # The default MEMORY_CORE_RUNTIME_IDENTITY names no OpenClaw config keys; the rest is equal.
    assert memory_core_warning.lines[:-1] == warning.lines[:-1]
    assert memory_core_warning.lines[-1] == (
        "If unintentional, raise the per-file and/or total bootstrap character limits."
    )
    assert memory_core_warning.signature == warning.signature
    assert build_bootstrap_prompt_warning_notice(warning.lines) == (
        "[Bootstrap truncation warning]\n"
        "Some workspace bootstrap files were truncated before Project Context injection.\n"
        "Treat Project Context as partial and read the relevant files directly if details seem "
        "missing."
    )
    # appendBootstrapPromptWarning is gone upstream (0b450013ea0, #130325), and so is its port.
    import memory_core.bootstrap as bootstrap_package

    assert not hasattr(bootstrap_package, "append_bootstrap_prompt_warning")


def test_once_mode_suppresses_a_seen_signature():
    analysis = _truncated_analysis()
    first = build_bootstrap_prompt_warning(analysis, mode="once")
    second = build_bootstrap_prompt_warning(
        analysis, mode="once", seen_signatures=first.warning_signatures_seen
    )
    off = build_bootstrap_prompt_warning(analysis, mode="off")

    assert first.warning_shown is True
    assert first.signature is not None and first.signature.startswith('{"bootstrapMaxChars":600,')
    assert second.warning_shown is False
    assert second.lines == ()
    assert off.warning_shown is False
    assert off.warning_signatures_seen == ()
    assert build_bootstrap_prompt_warning_notice(()) is None


def test_locale_compare_matches_icu_for_ascii():
    assert locale_compare("alpha.md", "Zeta.md") < 0
    assert locale_compare("a", "A") < 0
    assert locale_compare("a-b", "ab") < 0
    assert locale_compare("a_b", "a-b") < 0
    assert locale_compare("E", "é") < 0
    assert locale_compare("same", "same") == 0


def test_user_md_has_a_fixed_4000_char_cap():
    # USER_BOOTSTRAP_MAX_CHARS (28630a9a650, #114819): min(maxChars, 4000), any case.
    user = WorkspaceBootstrapFile("user.md", "/w/user.md", "u" * 5000)
    soul = WorkspaceBootstrapFile("SOUL.md", "/w/SOUL.md", "s" * 5000)

    result = build_bootstrap_context_files([user, soul], max_chars=20_000)
    small = build_bootstrap_context_files([user], max_chars=1_000)

    assert utf16_len(result.files[0].content) <= 4_000 < utf16_len(result.files[1].content)
    assert result.warnings == (
        "workspace bootstrap file user.md is 5000 chars (limit 4000); truncating in injected context",
    )
    assert small.warnings == (
        "workspace bootstrap file user.md is 5000 chars (limit 1000); truncating in injected context",
    )


def _analysis(files, max_chars, total):
    built = build_bootstrap_context_files(files, max_chars=max_chars, total_max_chars=total)
    stats = build_bootstrap_injection_stats(files, built.files)
    return analyze_bootstrap_budget(stats, bootstrap_max_chars=max_chars, bootstrap_total_max_chars=total)


def test_budget_analysis_reports_the_effective_file_limit_and_user_cap_lines():
    from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY

    user = WorkspaceBootstrapFile("USER.md", "/w/USER.md", "u" * 5000)
    only_user = _analysis([user], 20_000, 60_000)
    warning = build_bootstrap_prompt_warning(only_user, identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)
    # A per-file limit below the fixed cap is configurable, so both lines appear.
    lowered = build_bootstrap_prompt_warning(
        _analysis([user], 3_000, 60_000), identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY
    )

    (file,) = only_user.files
    assert (file.effective_file_limit, file.causes, file.near_limit) == (4_000, ("per-file-limit",), True)
    assert warning.lines[1:] == (
        "USER.md has a fixed 4000-character bootstrap cap; keep it compact.",
    )
    assert lowered.lines[1:] == (
        "If unintentional, raise agents.defaults.bootstrapMaxChars and/or "
        "agents.defaults.bootstrapTotalMaxChars.",
    )


def test_total_limit_is_a_cause_only_when_the_remaining_budget_bound_the_file():
    files = [
        WorkspaceBootstrapFile("AGENTS.md", "/w/AGENTS.md", "a" * 150),
        WorkspaceBootstrapFile("SOUL.md", "/w/SOUL.md", "b" * 150),
    ]

    analysis = _analysis(files, 150, 200)

    agents, soul = analysis.files
    # AGENTS.md fit in its 150-unit cap with 200 left; SOUL.md got the remaining 50.
    assert (agents.truncated, agents.causes) == (False, ())
    assert soul.truncated is True and soul.causes == ("total-limit",)


def test_injection_stats_match_by_path_only():
    files = [
        WorkspaceBootstrapFile("SOUL.md", "/w/a/SOUL.md", "a"),
        WorkspaceBootstrapFile("SOUL.md", "/w/b/SOUL.md", "b"),
        WorkspaceBootstrapFile("  ", "/w/c/NOTES.md", "c"),
        WorkspaceBootstrapFile("", "", "d"),
    ]
    injected = [ContextFile("/w/a/SOUL.md", "a"), ContextFile("SOUL.md", "b")]

    stats = build_bootstrap_injection_stats(files, injected)

    assert [(stat.name, stat.path, stat.injected_chars) for stat in stats] == [
        ("SOUL.md", "/w/a/SOUL.md", 1),
        # No fallback to the file name or basename (the pin matched those).
        ("SOUL.md", "/w/b/SOUL.md", 0),
        ("NOTES.md", "/w/c/NOTES.md", 0),
        ("bootstrap", "bootstrap", 0),
    ]


def test_agents_digest_candidates_carry_their_framing_prose():
    from memory_core.bootstrap.budget import _policy_digest_candidates

    content = "\n".join(
        [
            "Plain framing prose.",
            "- You must read scoped files.",
            "",
            "Another prose line.",
            "```",
            "- never inside a fence frame",
            "禁止 pushing secrets 🔴",
        ]
    )

    candidates = _policy_digest_candidates(content)

    assert [(candidate.text, candidate.high_priority) for candidate in candidates] == [
        ("Plain framing prose.\n- You must read scoped files.", True),
        ("- never inside a fence frame", True),
        ("禁止 pushing secrets 🔴", True),
    ]
